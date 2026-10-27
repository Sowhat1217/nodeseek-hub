"""Sign-in runs on its own. Posts and comments are written by the LLM as drafts; nothing is
published until the user presses 发布 on the 升级 page."""
import json
import re
from datetime import timedelta

import httpx

from . import config, db, llm, notify
from .ns import Client, parse_feed

POST_SYSTEM = """你是 NodeSeek 论坛（VPS、服务器、网络、开发者社区）的一位老用户，要发一个新帖。
从给你的素材（新闻、今日热点关键词）里挑一个这个社区真正会感兴趣的点来写；都不合适就返回 skip=true。
要求：
- 写的是有信息量的内容：说清楚发生了什么、跟这个社区有什么关系、你的看法或值得讨论的问题。可以以提问结尾引导讨论。
- 只用素材里有的事实，不编造数据、经历和来源；涉及新闻要在文末附原文链接。
- 一律用中文写。素材是英文的，用中文转述要点，产品名、公司名等专有名词保留英文。
- 口语化、简洁，像真人发帖。不要"总之""综上所述""希望对大家有帮助"这类套话，不用 emoji 堆砌，不用 Markdown 标题。
- 标题 10-30 字，具体，不做标题党。正文 80-400 字。
{style}
只输出 JSON：{{"skip": false, "reason": "为什么选这个", "title": "...", "content": "...", "source": "用到的素材链接或关键词"}}"""

COMMENT_SYSTEM = """你是 NodeSeek 论坛（VPS、服务器、网络、开发者社区）的一位老用户，在看一个帖子，决定要不要回复。
只有能说出具体、有用的东西时才回复：回答楼主的问题、补充相关信息、提出有价值的追问或不同看法。
以下情况返回 skip=true：帖子是抽奖/广告/交易/求打赏、内容太少看不懂、你没有确实有用的话可说、需要亲身经历才能回答。
要求：
- 针对帖子里的具体内容说话，不说"支持""感谢分享""学习了""mark"这类空话。
- 不编造亲身经历、测试数据或事实；不确定的就用提问的方式。
- 口语化，像真人回帖，一到三句话，不超过 120 字。不用 emoji，不用 Markdown。
{style}
只输出 JSON：{{"skip": false, "reason": "为什么回/不回", "comment": "..."}}"""


# ---------- sign-in ----------
def checkin(ctx):
    cfg = config.get()["upgrade"]["checkin"]
    day = config.today()
    if db.one("SELECT id FROM checkins WHERE day=? AND ok=1", (day,)):
        ctx.summary = "今天已经签到过"
        ctx.log(ctx.summary)
        return
    ok, msg = Client(ctx.log).checkin(cfg["random"])
    if not ok and ("已完成签到" in msg or "已签到" in msg):
        ok = True
    db.ex("INSERT INTO checkins(day,at,ok,message) VALUES(?,?,?,?)", (day, config.now_str(), int(ok), msg[:300]))
    ctx.summary = msg[:80]
    ctx.log("签到", "成功" if ok else "失败", msg)
    notify.send("checkin", f"NodeSeek 签到{'成功' if ok else '失败'}：{msg}")
    if not ok:
        ctx.fail(msg)


# ---------- post drafts ----------
def _news(feeds: list[str]) -> list[dict]:
    used = {r["source"] for r in db.q("SELECT source FROM drafts WHERE kind='post'")}
    since = (config.now() - timedelta(hours=36)).strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for url in feeds:
        try:
            r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            out += [i for i in parse_feed(r.text)[:15] if i["published"] >= since and i["link"] not in used]
        except Exception:
            continue
    return out[:30]


def post_draft(ctx):
    cfg = config.get()["upgrade"]["post"]
    material: dict = {}
    news = _news(cfg["news_feeds"])
    if news:
        material["新闻"] = [{"title": n["title"], "link": n["link"], "summary": n["summary"][:300]} for n in news]
    if cfg["use_hot"]:
        snap = db.one("SELECT keywords FROM hot_snapshots WHERE win='24h' ORDER BY id DESC LIMIT 1")
        if snap:
            used = {r["source"] for r in db.q("SELECT source FROM drafts WHERE kind='post' AND created_at>=?",
                                              ((config.now() - timedelta(days=2)).strftime("%Y-%m-%d"),))}
            material["今日热点关键词"] = [k["word"] for k in json.loads(snap["keywords"])[:8] if k["word"] not in used]
    if not material:
        ctx.summary = "没有素材（配置新闻源，或等热度分析出结果）"
        ctx.log(ctx.summary)
        return
    recent = [r["title"] for r in db.q("SELECT title FROM drafts WHERE kind='post' ORDER BY id DESC LIMIT 20")]
    material["最近已写过的标题（不要重复）"] = recent
    style = f"额外要求：{cfg['style']}" if cfg["style"] else ""
    ctx.log(f"素材：新闻 {len(news)} 条，热点 {len(material.get('今日热点关键词', []))} 个，调用 LLM 写草稿…")
    out = llm.chat_json(POST_SYSTEM.format(style=style), json.dumps(material, ensure_ascii=False), temperature=0.7)
    if out.get("skip") or not out.get("content"):
        ctx.summary = f"LLM 跳过：{out.get('reason', '')}"[:120]
        ctx.log(ctx.summary)
        return
    did = db.ex(
        "INSERT INTO drafts(kind,category,title,content,source,created_at) VALUES('post',?,?,?,?,?)",
        (cfg["category"], out["title"][:80], out["content"], str(out.get("source", ""))[:300], config.now_str()),
    )
    ctx.summary = f"草稿 #{did}：{out['title']}"
    ctx.log(ctx.summary, "|", out.get("reason", ""))
    notify.send("drafts", f"新帖草稿待发布\n{out['title']}\n\n{out['content'][:300]}")


# ---------- comment drafts ----------
def comment_draft(ctx):
    cfg = config.get()["upgrade"]["comment"]
    today = config.today()
    made_today = db.one("SELECT COUNT(*) n FROM drafts WHERE kind='comment' AND created_at>=?", (today,))["n"]
    room = min(cfg["per_run"], cfg["daily_max"] - made_today)
    if room <= 0:
        ctx.summary = f"今天已写 {made_today} 条评论草稿，到达上限"
        ctx.log(ctx.summary)
        return
    since = (config.now() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    cats = cfg["categories"]
    rows = db.q(
        f"""SELECT * FROM topics WHERE published_at>=? {'AND category IN (%s)' % ','.join('?' * len(cats)) if cats else ''}
            AND post_id NOT IN (SELECT target_id FROM drafts WHERE kind='comment' AND target_id IS NOT NULL)
            ORDER BY post_id DESC LIMIT 60""",
        [since] + cats,
    )
    kws = [k.lower() for k in cfg["keywords"] if k.strip()]
    if kws:
        rows = [r for r in rows if any(k in r["title"].lower() for k in kws)]
    if not rows:
        ctx.summary = "没有合适的帖子"
        ctx.log(ctx.summary)
        return
    client = Client(ctx.log)
    style = f"额外要求：{cfg['style']}" if cfg["style"] else ""
    made = 0
    for r in rows[: room * 4]:
        if made >= room:
            break
        try:
            d = client.post(r["post_id"])
        except Exception as e:
            ctx.log(f"读取 {r['post_id']} 失败: {e}")
            continue
        if len(d["content"]) < 15:
            continue
        out = llm.chat_json(
            COMMENT_SYSTEM.format(style=style),
            json.dumps({"标题": r["title"], "版块": config.CATEGORIES.get(r["category"], r["category"]),
                        "正文": d["content"][:2500]}, ensure_ascii=False),
            temperature=0.6,
        )
        if out.get("skip") or not (out.get("comment") or "").strip():
            ctx.log(f"跳过 {r['post_id']}《{r['title'][:20]}》：{out.get('reason', '')}")
            # remember the skip so the same post isn't re-read every run
            db.ex(
                "INSERT INTO drafts(kind,target_id,target_title,content,status,result,created_at) "
                "VALUES('comment',?,?,'', 'discarded', ?, ?)",
                (r["post_id"], r["title"], "LLM 跳过：" + str(out.get("reason", ""))[:200], config.now_str()),
            )
            continue
        db.ex(
            "INSERT INTO drafts(kind,target_id,target_title,category,content,source,created_at) VALUES('comment',?,?,?,?,?,?)",
            (r["post_id"], r["title"], r["category"], out["comment"].strip(), str(out.get("reason", ""))[:300], config.now_str()),
        )
        made += 1
        ctx.log(f"草稿：{r['post_id']}《{r['title'][:20]}》→ {out['comment'][:40]}")
    ctx.summary = f"写了 {made} 条评论草稿"
    if made:
        notify.send("drafts", f"{made} 条评论草稿待发布，去面板「升级」页查看。")


# ---------- publish (user action) ----------
def publish(draft_id: int) -> tuple[bool, str]:
    d = db.one("SELECT * FROM drafts WHERE id=?", (draft_id,))
    if not d or d["status"] not in ("pending", "failed"):
        return False, "草稿不存在或已处理"
    c = Client()
    try:
        if d["kind"] == "post":
            ok, msg = c.new_post(d["title"], d["content"], d["category"] or "daily")
        else:
            ok, msg = c.new_comment(d["target_id"], d["content"])
    except Exception as e:
        ok, msg = False, str(e)
    db.ex(
        "UPDATE drafts SET status=?, result=?, published_at=? WHERE id=?",
        ("published" if ok else "failed", msg[:500], config.now_str() if ok else None, draft_id),
    )
    return ok, msg


def status() -> dict:
    day = config.today()
    since = (config.now() - timedelta(days=29)).strftime("%Y-%m-%d")
    checkins = db.q("SELECT day, MAX(ok) ok, MAX(at) at, message FROM checkins WHERE day>=? GROUP BY day ORDER BY day", (since,))
    streak, cur = 0, config.now()
    ok_days = {c["day"] for c in checkins if c["ok"]}
    if day not in ok_days:
        cur -= timedelta(days=1)
    while cur.strftime("%Y-%m-%d") in ok_days:
        streak += 1
        cur -= timedelta(days=1)
    counts = {
        r["kind"] + "_" + r["status"]: r["n"]
        for r in db.q("SELECT kind, status, COUNT(*) n FROM drafts WHERE created_at>=? GROUP BY kind, status", (day,))
    }
    return {
        "today": next((c for c in checkins if c["day"] == day), None),
        "checkins": checkins,
        "streak": streak,
        "today_counts": counts,
        "has_account": bool(config.get()["ns"].get("username") and config.get()["ns"].get("password_enc")),
    }


