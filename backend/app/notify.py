"""Telegram notifications. Each module can be switched on/off in the 通知 page."""
import httpx

from . import config, db
from .security import decrypt

MODULES = {
    "price": "价格走势日报",
    "hot": "热度关键词（每日）",
    "checkin": "签到结果",
    "drafts": "新草稿待发布",
    "errors": "任务出错",
}


def send(module: str, text: str, force: bool = False) -> bool:
    """Send if the module is enabled (force=True ignores the switch, for the test button).
    Never raises: a notification failure must not break the job that sent it."""
    n = config.get()["notify"]
    if not force and not n["modules"].get(module, False):
        return False
    if not force and not (n.get("tg_token_enc") and n.get("tg_chat_id")):
        return False  # not set up yet: nothing to report, don't fill the history with failures
    err = ""
    try:
        if not n.get("tg_token_enc") or not n.get("tg_chat_id"):
            raise RuntimeError("没有配置 Telegram 机器人 Token 或 Chat ID")
        token = decrypt(n["tg_token_enc"])
        r = httpx.post(
            f"{n['tg_api'].rstrip('/')}/bot{token}/sendMessage",
            json={"chat_id": n["tg_chat_id"], "text": text[:4000], "disable_web_page_preview": True},
            timeout=20,
        )
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(explain(data.get("description", r.text[:200])))
    except Exception as e:
        err = str(e)
    db.ex(
        "INSERT INTO notifications(at,module,text,ok,error) VALUES(?,?,?,?,?)",
        (config.now_str(), module, text[:4000], int(not err), err),
    )
    if err and force:
        raise RuntimeError(err)
    return not err


def explain(desc: str) -> str:
    d = desc.lower()
    if "unauthorized" in d:
        return "Token 不对：去 @BotFather 重新复制机器人的 Token。"
    if "chat not found" in d:
        return "找不到这个 Chat ID：先在 Telegram 里给机器人发一条消息（群聊要先把机器人拉进群），再检查 ID。"
    if "bot was blocked" in d:
        return "你屏蔽了这个机器人，在 Telegram 里解除屏蔽后再试。"
    return desc
