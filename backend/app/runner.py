"""Job registry + APScheduler. Schedules are rebuilt from the settings whenever they are saved."""
import threading
import traceback
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, db, hot, notify, price, upgrade

scheduler = BackgroundScheduler(timezone=config.TZ)
KEEP_RUNS = 300


def cleanup(ctx):
    c = config.get()["cleanup"]
    ago = lambda d: (config.now() - timedelta(days=d)).strftime("%Y-%m-%d")
    plan = [
        ("topics", "published_at", c["topics_days"]),
        ("runs", "started_at", c["runs_days"]),
        ("notifications", "at", c["notifications_days"]),
        ("hot_snapshots", "created_at", c["topics_days"]),
        ("trade_posts", "first_seen", c["trade_days"]),
    ]
    parts = []
    for table, col, days in plan:
        if days and days > 0:
            n = db.one(f"SELECT COUNT(*) n FROM {table} WHERE {col}<?", (ago(days),))["n"]
            db.ex(f"DELETE FROM {table} WHERE {col}<?", (ago(days),))
            parts.append(f"{table} {n}")
    if c["drafts_days"]:
        n = db.one("SELECT COUNT(*) n FROM drafts WHERE status!='pending' AND created_at<?", (ago(c["drafts_days"]),))["n"]
        db.ex("DELETE FROM drafts WHERE status!='pending' AND created_at<?", (ago(c["drafts_days"]),))
        parts.append(f"drafts {n}")
    db.ex("PRAGMA wal_checkpoint(TRUNCATE)")
    ctx.summary = "删除 " + "，".join(parts)
    ctx.log(ctx.summary)


# name -> (label, function, module that owns it in the UI)
JOBS = {
    "price": ("抓取交易区", price.run, "price"),
    "hot_rss": ("拉取 RSS", hot.poll, "hot"),
    "hot_1h": ("1 小时热度", lambda ctx: hot.analyze(ctx, "1h"), "hot"),
    "hot_24h": ("24 小时热度", lambda ctx: hot.analyze(ctx, "24h"), "hot"),
    "checkin": ("签到", upgrade.checkin, "upgrade"),
    "post_draft": ("写帖子草稿", upgrade.post_draft, "upgrade"),
    "comment_draft": ("写评论草稿", upgrade.comment_draft, "upgrade"),
    "cleanup": ("数据清理", cleanup, "settings"),
}


class Ctx:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self.lines: list[str] = []
        self.summary = ""
        self.failed: str | None = None

    def log(self, *args):
        self.lines.append(f"[{config.now():%H:%M:%S}] " + " ".join(str(a) for a in args))
        # write through on every line, so the log dialog shows progress while the job runs
        db.ex("UPDATE runs SET log=? WHERE id=?", ("\n".join(self.lines)[-20000:], self.run_id))

    def fail(self, reason: str):
        self.failed = reason
        self.log("【出错】", reason)


_running: set[str] = set()
_lock = threading.Lock()


def run_job(name: str):
    with _lock:
        if name in _running:
            return
        _running.add(name)
    run_id = db.ex("INSERT INTO runs(job,started_at,status) VALUES(?,?,'running')", (name, config.now_str()))
    ctx = Ctx(run_id)
    status = "ok"
    try:
        JOBS[name][1](ctx)
    except Exception as e:
        status = "error"
        ctx.summary = ctx.summary or f"{type(e).__name__}: {e}"[:200]
        ctx.log(traceback.format_exc())
    finally:
        with _lock:
            _running.discard(name)
    if ctx.failed:
        status = "error"
        ctx.summary = ctx.summary or ctx.failed
    if status == "error":  # notify on ok -> error only
        prev = db.one("SELECT status FROM runs WHERE job=? AND id<? AND status!='running' ORDER BY id DESC LIMIT 1", (name, run_id))
        if not prev or prev["status"] != "error":
            notify.send("errors", f"{JOBS[name][0]} 出错\n{ctx.summary}\n\n" + "\n".join(ctx.lines[-8:])[-1500:])
    db.ex(
        "UPDATE runs SET finished_at=?, status=?, summary=?, log=? WHERE id=?",
        (config.now_str(), status, ctx.summary[:300], "\n".join(ctx.lines)[-20000:], run_id),
    )
    db.ex(
        "DELETE FROM runs WHERE job=? AND id NOT IN (SELECT id FROM runs WHERE job=? ORDER BY id DESC LIMIT ?)",
        (name, name, KEEP_RUNS),
    )


def run_now(name: str):
    threading.Thread(target=run_job, args=(name,), daemon=True).start()


def is_running(name: str) -> bool:
    return name in _running


def _at(hhmm: str, minute_offset: int = 0) -> CronTrigger:
    h, m = (int(x) for x in hhmm.split(":"))
    return CronTrigger(hour=h, minute=m, timezone=config.TZ)


def schedule_plan(cfg: dict) -> list[tuple[str, str, object]]:
    """[(job, job_id, trigger)] for everything that is switched on."""
    plan = []
    if cfg["price"]["enabled"]:
        plan.append(("price", "price", _at(cfg["price"]["time"])))
    h = cfg["hot"]
    if h["enabled"]:
        # on whole minutes (13:01:00, 13:02:00 …); every N minutes counts from the top of the hour
        n = max(1, int(h["poll_minutes"]))
        plan.append(("hot_rss", "hot_rss", CronTrigger(minute="*" if n == 1 else f"*/{n}", second=0, timezone=config.TZ)))
        if h["hourly"]:
            plan.append(("hot_1h", "hot_1h", CronTrigger(minute=3, timezone=config.TZ)))
        plan.append(("hot_24h", "hot_24h", _at(h["daily_time"])))
    u = cfg["upgrade"]
    if u["checkin"]["enabled"]:
        plan.append(("checkin", "checkin", _at(u["checkin"]["time"])))
    if u["post"]["enabled"]:
        for i, t in enumerate(u["post"]["times"]):
            plan.append(("post_draft", f"post_draft-{i}", _at(t)))
    if u["comment"]["enabled"]:
        for i, t in enumerate(u["comment"]["times"]):
            plan.append(("comment_draft", f"comment_draft-{i}", _at(t)))
    plan.append(("cleanup", "cleanup", _at(cfg["cleanup"]["time"])))
    return plan


def sync_jobs():
    for job in scheduler.get_jobs():
        job.remove()
    for name, jid, trig in schedule_plan(config.get()):
        scheduler.add_job(run_job, trig, args=[name], id=jid, max_instances=1, coalesce=True, misfire_grace_time=300)


def next_runs() -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for job in scheduler.get_jobs():
        name = job.args[0]
        if job.next_run_time and (name not in out or job.next_run_time < out[name]):
            out[name] = job.next_run_time
    return out


def start():
    # runs left as "running" by a previous process (killed / restarted) will never finish
    db.ex(
        "UPDATE runs SET status='error', finished_at=?, summary='服务重启，任务中断' WHERE status='running'",
        (config.now_str(),),
    )
    scheduler.start()
    sync_jobs()
