"""RSS -> topics table; the LLM pulls heat keywords out of the last 1h / 24h of titles."""
import json
from datetime import timedelta

from . import config, db, llm, notify
from .ns import Client

LABEL_TO_SLUG = {v: k for k, v in config.CATEGORIES.items()}

SYSTEM = """你在分析 NodeSeek 论坛（VPS、服务器、网络、开发者社区）一段时间内的新帖标题，找出这段时间大家在讨论什么。
要求：
- 关键词要具体：商家名、产品、事件、技术名词（如"搬瓦工补货""DMIT 涨价""Cloudflare 故障""Claude 封号"），不要"求助""分享""VPS"这种泛词。
- 同一件事的不同说法合并成一个关键词。
- heat 是 0-100 的热度，综合帖子数和话题集中程度；count 是相关帖子数；post_ids 是相关帖子的 id（只能用给出的 id）。
- 按 heat 从高到低，最多 {top_n} 个；没有明显热点时可以少给。
- summary：用一两句话概括这段时间的整体动向，不超过 80 字。
只输出 JSON：{{"keywords": [{{"word": "...", "heat": 0, "count": 0, "post_ids": []}}], "summary": "..."}}"""


def _slug(cat: str) -> str:
    cat = (cat or "").strip()
    return LABEL_TO_SLUG.get(cat, cat.lower())


def poll(ctx):
    cfg = config.get()["hot"]
    items = Client(ctx.log).rss(cfg["rss_url"])
    wanted = set(cfg["categories"])
    rows = [
        (i["post_id"], i["title"], _slug(i["category"]), i["author"], i["published"], config.now_str())
        for i in items
        if i["post_id"] and (not wanted or not i["category"] or _slug(i["category"]) in wanted)
    ]
    before = db.one("SELECT COUNT(*) n FROM topics")["n"]
    db.many(
        """INSERT INTO topics(post_id,title,category,author,published_at,fetched_at) VALUES(?,?,?,?,?,?)
           ON CONFLICT(post_id) DO UPDATE SET title=excluded.title""",
        rows,
    )
    added = db.one("SELECT COUNT(*) n FROM topics")["n"] - before
    ctx.summary = f"RSS {len(items)} 条，入库 {added} 条新帖"
    ctx.log(ctx.summary)


def analyze(ctx, win: str):
    cfg = config.get()["hot"]
    hours = 1 if win == "1h" else 24
    since = (config.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    cats = cfg["categories"]
    rows = db.q(
        f"SELECT post_id, title, category FROM topics WHERE published_at>=? "
        f"{'AND category IN (%s)' % ','.join('?' * len(cats)) if cats else ''} ORDER BY post_id DESC LIMIT 600",
        [since] + cats,
    )
    if len(rows) < 3:
        ctx.summary = f"最近 {hours} 小时只有 {len(rows)} 帖，跳过"
        ctx.log(ctx.summary)
        return
    payload = [{"id": r["post_id"], "t": r["title"], "c": config.CATEGORIES.get(r["category"], r["category"])} for r in rows]
    ctx.log(f"最近 {hours} 小时 {len(rows)} 帖，调用 LLM（{llm.model()}）分析…")
    out = llm.chat_json(SYSTEM.format(top_n=cfg["top_n"]), json.dumps(payload, ensure_ascii=False), temperature=0.3)
    ids = {r["post_id"] for r in rows}
    kws = []
    for k in out.get("keywords", [])[: cfg["top_n"]]:
        if not k.get("word"):
            continue
        pids = [int(p) for p in k.get("post_ids", []) if str(p).isdigit() and int(p) in ids]
        kws.append({"word": str(k["word"])[:30], "heat": max(0, min(100, int(k.get("heat") or 0))),
                    "count": len(pids) or int(k.get("count") or 0), "post_ids": pids[:30]})
    kws.sort(key=lambda k: -k["heat"])
    db.ex(
        "INSERT INTO hot_snapshots(win,created_at,post_count,keywords,summary) VALUES(?,?,?,?,?)",
        (win, config.now_str(), len(rows), json.dumps(kws, ensure_ascii=False), str(out.get("summary", ""))[:300]),
    )
    ctx.summary = f"{len(rows)} 帖 → {len(kws)} 个关键词"
    ctx.log(ctx.summary, "：", "、".join(k["word"] for k in kws[:8]))
    if win == "24h" and kws:
        text = f"NodeSeek 今日热点（{len(rows)} 帖）\n" + "\n".join(
            f"{i + 1}. {k['word']}  ·  {k['count']} 帖" for i, k in enumerate(kws[:10])
        )
        if out.get("summary"):
            text += f"\n\n{out['summary']}"
        notify.send("hot", text)


# ---------- read side ----------
def overview(win: str) -> dict:
    snaps = db.q("SELECT * FROM hot_snapshots WHERE win=? ORDER BY id DESC LIMIT 2", (win,))
    cur = snaps[0] if snaps else None
    prev = snaps[1] if len(snaps) > 1 else None
    prev_heat = {k["word"]: k["heat"] for k in json.loads(prev["keywords"])} if prev else {}
    keywords = []
    if cur:
        for k in json.loads(cur["keywords"]):
            k["delta"] = None if not prev else k["heat"] - prev_heat.get(k["word"], 0)
            k["new"] = bool(prev) and k["word"] not in prev_heat
            keywords.append(k)
        all_ids = {p for k in keywords for p in k["post_ids"]}
        titles = {
            r["post_id"]: r
            for r in db.q(
                f"SELECT post_id, title, category, published_at FROM topics WHERE post_id IN ({','.join('?' * len(all_ids))})",
                list(all_ids),
            )
        } if all_ids else {}
        for k in keywords:
            k["posts"] = [titles[p] for p in k["post_ids"] if p in titles][:8]

    # posts per hour for the last 24h, stacked by category
    since = (config.now() - timedelta(hours=23)).strftime("%Y-%m-%d %H:00:00")
    hourly = db.q(
        """SELECT substr(published_at,1,13) h, category, COUNT(*) n FROM topics
           WHERE published_at>=? GROUP BY h, category ORDER BY h""",
        (since,),
    )
    hours = [(config.now() - timedelta(hours=23 - i)).strftime("%Y-%m-%d %H") for i in range(24)]
    by_hour = {h: {} for h in hours}
    for r in hourly:
        if r["h"] in by_hour:
            by_hour[r["h"]][r["category"]] = r["n"]
    latest = db.q("SELECT post_id, title, category, author, published_at FROM topics ORDER BY post_id DESC LIMIT 40")
    history = db.q("SELECT id, created_at, post_count FROM hot_snapshots WHERE win=? ORDER BY id DESC LIMIT 24", (win,))
    return {
        "win": win,
        "snapshot": {k: cur[k] for k in ("id", "created_at", "post_count", "summary")} if cur else None,
        "keywords": keywords,
        "hourly": [{"hour": h, "by_cat": by_hour[h], "total": sum(by_hour[h].values())} for h in hours],
        "latest": latest,
        "history": history[::-1],
        "categories": config.CATEGORIES,
        "total_topics": db.one("SELECT COUNT(*) n FROM topics")["n"],
    }
