"""Nightly trade-board scrape -> LLM normalisation -> premium trend + hot VPS.

Watermark: the largest post id seen so far. Each night pages are read from page 1 until the
ids drop to the stop id (the smallest id first seen within `lookback_days`, so posts edited
to "已出" a few days later are still caught), with `max_pages` as a hard cap."""
import json
import re
import statistics
import time
from datetime import timedelta

from . import config, db, llm, notify
from .ns import Client

SIGNAL = re.compile(r"已出|已收|秒出|出掉|已售|成交|出了|sold", re.I)
BATCH_WITH_BODY = 30   # posts sent with their body (up to 1500 chars each)
BATCH_TITLE = 60       # title-only posts are short, so many fit in one call

SYSTEM = """你在整理 NodeSeek 交易区的帖子，提取剩余价值交易的信息。对每个帖子输出：
- merchant：VPS 商家，统一成常用写法（如 搬瓦工、DMIT、RackNerd、wawo、懒猫云、Bage）。不确定或不是 VPS 交易则为 null。优先沿用"已知商家"里的写法。
- model：型号或套餐，简短（如 DC9 CN2 GIA、LAX.Pro.Wee、品川 199）。没有则 null。
- side："sell"（出）或 "buy"（收）。
- price：帖子写的总价（成交价/标价），数字，如"价格：80 元"=80、"总价280出"=280、"40出wawo"=40。没写为 null。
- premium：在剩余价值上加的钱，数字。
  1) 明写的：直接取。"余值+50出"=50，"+4200"=4200，"溢价150收"=150；"剩余价值出/剩余收"没写数字=0。负数表示低于剩余价值。
  2) 没明写、但有总价，且正文给了续费价、付费周期和到期日：按"今天"算剩余价值（续费价 × 剩余天数 ÷ 周期天数，月付按 30 天、年付按 365 天），premium = 总价 − 剩余价值（换成和总价同一币种，美元按"汇率"），保留整数，并把 premium_estimated 设为 true。
  3) 其他情况（只有总价算不出剩余价值、价格被删、看不出来）为 null。不要猜。
- premium_estimated：premium 是按第 2 条算出来的为 true，否则省略。
- currency：price 和 premium 的币种，"CNY" 或 "USD"（写"刀""$""美元"为 USD）。
- discount：折扣，如"75折"=0.75，"8折"=0.8；没有为 null。折扣不要算进 premium。
- is_deal：只有出售帖确实已经卖出（标题或正文标了已出/已秒出且不是"暂不出""不出了"之类取消，也不是"秒出封贴"之类宣传语）才为 true。收购帖只有明确"已收"且没有"不收了/停收"才为 true。拿不准就 false。
- note：只在 is_deal 为 true 时写一句判断依据（不超过 20 字），否则省略这个字段。
只输出 JSON：{"items": [{"id": 帖子id, "merchant": ..., "model": ..., "side": ..., "price": ..., "premium": ..., "currency": ..., "discount": ..., "is_deal": ...}]}（估算的再加 "premium_estimated": true，成交的再加 "note"）"""


def run(ctx):
    cfg = config.get()["price"]
    c = Client(ctx.log)
    today = config.today()
    since = (config.now() - timedelta(days=cfg["lookback_days"])).strftime("%Y-%m-%d")
    watermark = db.get_setting("trade_watermark")
    stop_id = None
    if watermark:
        r = db.one("SELECT MIN(post_id) AS m FROM trade_posts WHERE first_seen>=?", (since,))
        # ids <= stop_id are skipped; keep the oldest lookback post itself in range
        stop_id = min(watermark, r["m"] - 1) if r and r["m"] else watermark
        ctx.log(f"水位线 {watermark}，回看到 {stop_id}")
    else:
        ctx.log(f"首次运行，取前 {cfg['cold_pages']} 页")
    max_pages = cfg["max_pages"] if watermark else cfg["cold_pages"]

    seen, new, top = 0, 0, watermark or 0
    for page in range(1, max_pages + 1):
        items = [i for i in c.list_page("trade", page) if not i["pinned"] and i["category"] == "trade"]
        if not items:
            ctx.log(f"第 {page} 页没有帖子，停止")
            break
        reached = False
        for it in items:
            if stop_id and it["post_id"] <= stop_id:
                reached = True
                continue
            top = max(top, it["post_id"])
            seen += 1
            existed = db.one("SELECT post_id FROM trade_posts WHERE post_id=?", (it["post_id"],))
            new += not existed
            db.ex(
                """INSERT INTO trade_posts(post_id,title,author,views,replies,first_seen,last_seen,signal)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(post_id) DO UPDATE SET title=excluded.title, views=excluded.views,
                     replies=excluded.replies, last_seen=excluded.last_seen, signal=excluded.signal""",
                (it["post_id"], it["title"], it["author"], it["views"], it["replies"], today, today,
                 int(bool(SIGNAL.search(it["title"])))),
            )
        ctx.log(f"第 {page} 页：{len(items)} 帖")
        if reached:
            break
        time.sleep(cfg["delay"])
    db.set_setting("trade_watermark", top or watermark)
    ctx.log(f"列表完成：本次 {seen} 帖，其中新帖 {new}")

    # detail pages for deal-looking titles whose title changed since the last LLM pass
    todo = db.q(
        "SELECT * FROM trade_posts WHERE last_seen=? AND (llm_title IS NULL OR llm_title!=title) ORDER BY post_id",
        (today,),
    )
    fetched = 0
    for row in todo:
        # read the body only when we don't have it yet, or the title changed since the LLM last saw it
        # (e.g. "出" -> "已出"); a re-run after a failure reuses the stored body
        title_changed = row["llm_title"] is not None and row["llm_title"] != row["title"]
        if row["signal"] and (row["content"] is None or title_changed):
            fetched += 1
            try:
                d = c.post(row["post_id"])
                row.update(content=d["content"][:3000], posted_at=d["posted_at"], edited_at=d["edited_at"])
                db.ex(
                    "UPDATE trade_posts SET content=?, posted_at=?, edited_at=? WHERE post_id=?",
                    (row["content"], row["posted_at"], row["edited_at"], row["post_id"]),
                )
            except Exception as e:
                if "404" in str(e):  # level-locked posts (🔒) are invisible to anonymous visitors
                    ctx.log(f"详情 {row['post_id']} 匿名看不到（带锁帖或已删除），只按标题判断")
                    # "" = tried, not readable; None = not tried yet. Stops re-requesting it every run
                    db.ex("UPDATE trade_posts SET content='' WHERE post_id=?", (row["post_id"],))
                else:
                    ctx.log(f"详情 {row['post_id']} 读取失败: {e}")
            time.sleep(cfg["delay"])
    ctx.log(f"需要 LLM 归一的帖子 {len(todo)} 个，带正文 {sum(bool(r.get('content')) for r in todo)} 个（本次新读详情 {fetched} 个）")
    normalise(ctx, todo, cfg["usd_rate"])

    deals = db.q(
        "SELECT * FROM trade_posts WHERE deal_date=? AND is_deal=1 AND side='sell' ORDER BY premium_cny DESC",
        (today,),
    )
    ctx.summary = f"{seen} 帖，新 {new}，成交 {len(deals)}"
    notify.send("price", report(today, seen, new, deals))


def _canon_maps():
    """lower-case -> the spelling seen most often, so "Vmiss" and "VMISS" land on one name."""
    merchants: dict[str, str] = {}
    for r in db.q("SELECT merchant, COUNT(*) n FROM trade_posts WHERE merchant IS NOT NULL GROUP BY merchant ORDER BY n DESC"):
        merchants.setdefault(r["merchant"].lower(), r["merchant"])
    models: dict[tuple, str] = {}
    for r in db.q(
        "SELECT merchant, model, COUNT(*) n FROM trade_posts WHERE model IS NOT NULL GROUP BY merchant, model ORDER BY n DESC"
    ):
        models.setdefault(((r["merchant"] or "").lower(), r["model"].lower()), r["model"])
    return merchants, models


def normalise(ctx, rows, usd_rate):
    if not rows:
        return
    canon_m, canon_model = _canon_maps()
    merchants = list(dict.fromkeys(canon_m.values()))[:150]
    with_body = [r for r in rows if r.get("content")]
    title_only = [r for r in rows if not r.get("content")]
    chunks = [with_body[i : i + BATCH_WITH_BODY] for i in range(0, len(with_body), BATCH_WITH_BODY)]
    chunks += [title_only[i : i + BATCH_TITLE] for i in range(0, len(title_only), BATCH_TITLE)]
    done = 0
    for n, chunk in enumerate(chunks, 1):
        posts = [
            {
                "id": r["post_id"],
                "title": r["title"],
                **({"content": r["content"][:1500]} if r.get("content") else {}),
                **({"edited": True} if r.get("edited_at") else {}),
            }
            for r in chunk
        ]
        ctx.log(f"LLM 第 {n}/{len(chunks)} 批：{len(chunk)} 帖（{'含正文' if chunk[0].get('content') else '只有标题'}）…")
        try:
            out = llm.chat_json(SYSTEM, json.dumps(
                {"今天": config.today(), "汇率": f"1 美元 = {usd_rate} 人民币", "已知商家": merchants, "posts": posts},
                ensure_ascii=False))
        except Exception as e:
            ctx.log("LLM 失败:", e)
            ctx.fail("LLM 调用失败")
            return
        by_id = {int(o.get("id", 0)): o for o in out.get("items", []) if str(o.get("id", "")).isdigit()}
        for r in chunk:
            o = by_id.get(r["post_id"])
            if not o:
                continue
            prem = _float(o.get("premium"))
            price = _float(o.get("price"))
            cur = (o.get("currency") or "CNY").upper()
            rate = usd_rate if cur == "USD" else 1
            cny = None if prem is None else round(prem * rate, 2)
            price_cny = None if price is None else round(price * rate, 2)
            est = int(bool(o.get("premium_estimated")) and prem is not None)
            merchant = _s(o.get("merchant"))
            if merchant:
                merchant = canon_m.setdefault(merchant.lower(), merchant)
            model = _s(o.get("model"))
            if model:
                model = canon_model.setdefault(((merchant or "").lower(), model.lower()), model)
            is_deal = bool(o.get("is_deal"))
            deal_date = None
            if is_deal:
                old = db.one("SELECT deal_date FROM trade_posts WHERE post_id=?", (r["post_id"],))
                deal_date = (old and old["deal_date"]) or (r.get("edited_at") or "")[:10] or config.today()
                if not re.match(r"\d{4}-\d\d-\d\d$", deal_date):
                    deal_date = config.today()
            db.ex(
                """UPDATE trade_posts SET merchant=?, model=?, side=?, price=?, price_cny=?, premium=?, currency=?,
                   premium_cny=?, premium_est=?, discount=?, is_deal=?, deal_date=?, llm_note=?, llm_title=title
                   WHERE post_id=?""",
                (merchant, model, o.get("side") if o.get("side") in ("sell", "buy") else None,
                 price, price_cny, prem, cur, cny, est, _float(o.get("discount")), int(is_deal), deal_date,
                 _s(o.get("note")), r["post_id"]),
            )
        done += len(chunk)
        ctx.log(f"LLM 归一 第 {n}/{len(chunks)} 批，{done}/{len(rows)} 帖")


def _float(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _s(v):
    v = (v or "").strip() if isinstance(v, str) else None
    return v or None


def report(day, seen, new, deals) -> str:
    lines = [f"交易区日报 {day[5:]}", f"抓取 {seen} 帖 · 新帖 {new} · 成交 {len(deals)}"]
    priced = [d for d in deals if d["premium_cny"] is not None]
    if priced:
        lines.append(f"成交溢价中位数 ¥{statistics.median(d['premium_cny'] for d in priced):g}")
        lines.append("")
        for d in priced[:8]:
            name = " ".join(x for x in (d["merchant"], d["model"]) if x) or d["title"][:24]
            lines.append(f"· {name}  {'+' if d['premium_cny'] >= 0 else ''}{d['premium_cny']:g} 元")
    hot = db.q(
        """SELECT merchant, COUNT(*) n FROM trade_posts WHERE first_seen=? AND merchant IS NOT NULL
           GROUP BY merchant ORDER BY n DESC LIMIT 5""",
        (day,),
    )
    if hot:
        lines += ["", "今日热门：" + "、".join(f"{h['merchant']}×{h['n']}" for h in hot)]
    return "\n".join(lines)


# ---------- read side for the API ----------
def overview(days: int, merchant: str | None = None) -> dict:
    since = (config.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    where = "is_deal=1 AND side='sell' AND deal_date>=?"
    args: list = [since]
    if merchant:
        where += " AND merchant=?"
        args.append(merchant)
    deals = db.q(f"SELECT * FROM trade_posts WHERE {where} ORDER BY deal_date DESC, post_id DESC", args)
    priced = [d for d in deals if d["premium_cny"] is not None]

    # previous period, for the KPI deltas
    prev_since = (config.now() - timedelta(days=2 * days - 1)).strftime("%Y-%m-%d")
    prev = db.q(
        "SELECT premium_cny FROM trade_posts WHERE is_deal=1 AND side='sell' AND deal_date>=? AND deal_date<?"
        + (" AND merchant=?" if merchant else ""),
        [prev_since, since] + ([merchant] if merchant else []),
    )
    prev_priced = [p["premium_cny"] for p in prev if p["premium_cny"] is not None]
    posts = db.one(
        "SELECT COUNT(*) n FROM trade_posts WHERE first_seen>=?" + (" AND merchant=?" if merchant else ""),
        [since] + ([merchant] if merchant else []),
    )["n"]

    # series: daily median per merchant+model, top 6 by number of priced deals
    groups: dict[str, list] = {}
    for d in priced:
        key = " ".join(x for x in (d["merchant"], d["model"]) if x) or "未识别"
        groups.setdefault(key, []).append(d)
    top = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:6]
    dates = [(config.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d") for i in range(days)]
    # line = trailing 7-day median (daily medians of a few deals are too noisy to read); dots = that day's own median
    win = 1 if days <= 7 else 7
    series = []
    for key, ds in top:
        per_day: dict[str, list] = {}
        for d in ds:
            per_day.setdefault(d["deal_date"], []).append(d["premium_cny"])
        points = []
        for i, day in enumerate(dates):
            window = [v for dd in dates[max(0, i - win + 1) : i + 1] for v in per_day.get(dd, [])]
            if window and (day in per_day or points):
                points.append({
                    "date": day,
                    "value": statistics.median(window),
                    "day": statistics.median(per_day[day]) if day in per_day else None,
                    "n": len(per_day.get(day, [])),
                })
        series.append({"key": key, "count": len(ds), "median": statistics.median(x["premium_cny"] for x in ds), "points": points})
    daily = []
    for day in dates:
        v = [d["premium_cny"] for d in priced if d["deal_date"] == day]
        daily.append({"date": day, "deals": sum(1 for d in deals if d["deal_date"] == day),
                      "median": statistics.median(v) if v else None})

    heat = db.q(
        f"""SELECT merchant, model, COUNT(*) posts, SUM(views) views, SUM(replies) replies,
                   SUM(is_deal) deals
            FROM trade_posts WHERE first_seen>=? AND merchant IS NOT NULL {"AND merchant=?" if merchant else ""}
            GROUP BY merchant, model ORDER BY posts DESC, views DESC LIMIT 10""",
        [since] + ([merchant] if merchant else []),
    )
    merchants = [r["merchant"] for r in db.q(
        "SELECT merchant, COUNT(*) n FROM trade_posts WHERE merchant IS NOT NULL GROUP BY merchant ORDER BY n DESC LIMIT 60"
    )]
    return {
        "days": days,
        "window": win,
        "dates": dates,
        "kpi": {
            "deals": len(deals),
            "deals_prev": len(prev),
            "posts": posts,
            "median": statistics.median(d["premium_cny"] for d in priced) if priced else None,
            "median_prev": statistics.median(prev_priced) if prev_priced else None,
            "priced": len(priced),
        },
        "daily": daily,
        "series": series,
        "deals": [
            {k: d[k] for k in ("post_id", "title", "merchant", "model", "premium", "currency", "premium_cny",
                               "premium_est", "price", "price_cny", "discount", "deal_date", "views", "replies",
                               "llm_note")}
            for d in deals[:200]
        ],
        "heat": heat,
        "merchants": merchants,
        "watermark": db.get_setting("trade_watermark"),
    }
