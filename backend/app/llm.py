"""Any OpenAI-compatible chat endpoint (DeepSeek by default). Configured only in backend/.env."""
import json
import os
import re

import httpx


def configured() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def model() -> str:
    return os.environ.get("LLM_MODEL", "deepseek-v4-flash")


_no_thinking = os.environ.get("LLM_THINKING", "disabled").lower() != "enabled"


def _call(messages: list, temperature: float, max_tokens: int, json_mode: bool) -> dict:
    global _no_thinking
    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    body = {"model": model(), "temperature": temperature, "max_tokens": max_tokens, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if _no_thinking:
        # DeepSeek V4 models think by default; extraction work doesn't need it and the reasoning
        # can eat the whole output budget (finish_reason=length, empty content)
        body["thinking"] = {"type": "disabled"}
    r = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
        json=body,
        timeout=180,
    )
    if r.status_code == 400 and _no_thinking and "thinking" in r.text.lower():
        _no_thinking = False  # this provider doesn't know the field: stop sending it
        return _call(messages, temperature, max_tokens, json_mode)
    if r.status_code != 200:
        raise RuntimeError(f"LLM 返回 {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]


def _parse(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)  # some models wrap JSON in prose / code fences
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def chat_json(system: str, user: str, temperature: float = 0.2, max_tokens: int = 8000) -> dict:
    if not os.environ.get("LLM_API_KEY"):
        raise RuntimeError("没有配置 LLM：在 backend/.env 里写 LLM_API_KEY（以及可选的 LLM_BASE_URL、LLM_MODEL）")
    # the word "json" must appear in the prompt for DeepSeek's JSON mode
    messages = [{"role": "system", "content": system + "\n只输出一个 json 对象，不要输出其他文字。"},
                {"role": "user", "content": user}]
    last = None
    # JSON mode sometimes returns empty content (DeepSeek documents this); retry, then retry without it
    for json_mode in (True, True, False):
        choice = _call(messages, temperature, max_tokens, json_mode)
        out = _parse(choice["message"].get("content") or "")
        if out is not None:
            return out
        last = choice
    msg = last["message"]
    reason = last.get("finish_reason")
    hint = ""
    if reason == "length":
        hint = "输出被长度截断：模型可能还在思考（思考过程占满了长度），或这一批帖子太多，把 price.py 里的批大小调小。"
    elif msg.get("reasoning_content") and not msg.get("content"):
        hint = "模型只返回了思考过程没有正文，换非推理模型试试。"
    raise RuntimeError(
        f"LLM（{model()}）连续 3 次没有返回可用的 json，finish_reason={reason}。{hint}"
        f" 返回内容：{(msg.get('content') or '')[:200]!r}"
    )
