"""Turn loop: hear -> think (+tools) -> book -> speak.

One inbound turn: transcribe audio, chat with tool-calling, execute any
tool calls via Dispatcher (errors become tool results, never call drops),
render the final reply through the price gate, synthesize it.
Primary LLM 429/retryable failure fails over to the secondary once.
Empty transcription returns a repeat-prompt without spending LLM/TTS.
History is sanitized (role allowlist, turn/char caps, tool output is
untrusted data). Price-like tokens in the final reply must match a
quoted_total from THIS turn's tool results or the reply is replaced
with a safe handoff.
"""

from __future__ import annotations

import json
import re

from .booking.tools import BOOKING_TOOLS
from .providers.errors import (
    ProviderError,
    RateLimitedError,
    RetryableProviderError,
)

REPEAT_PROMPT = {
    "et": "Vabandust, ma ei kuulnud. Palun korrake?",
    "en": "Sorry, I didn't catch that. Please repeat?",
    "ru": "Извините, не расслышал. Повторите, пожалуйста?",
}

FILLER = {
    "et": "Üks hetk, kontrollin...",
    "en": "One moment, checking...",
    "ru": "Одну минуту, проверяю...",
}

PRICE_HANDOFF = {
    "et": "Hinna kinnitan kohe — üks hetk, kontrollin pakkumist.",
    "en": "Let me confirm that price right away — one moment.",
    "ru": "Сейчас уточню цену — одну минуту.",
}

PRICE_RE = re.compile(
    r"€\s?\d{1,3}(?: \d{3}(?!\d))+(?:[.,]\d{2})?"
    r"|€\s?\d+(?:[.,]\d{2})?"
    r"|\d+[.,]\d{2}\s?(?:€|EUR|eurot|euros|eurod|euro)(?!\w)"
    r"|\d+\s?(?:€|EUR|eurot|euros|eurod|euro)(?!\w)",
    re.IGNORECASE,
)

MAX_HISTORY_TURNS = 12
MAX_HISTORY_CHARS = 2000
MAX_REPLY_CHARS = 600
ALLOWED_ROLES = {"user", "assistant", "tool"}


def _norm_price(raw: str) -> str:
    """Canonical numeric core: lowercase, no spaces/commas/currency."""
    s = re.sub(r"\s+", "", raw).replace(",", ".").lower()
    s = s.replace("€", "")
    s = re.sub(r"(eurot|euros|eurod|euro|eur)$", "", s)
    return s


def _canon_price(raw: str):
    """Decimal when numeric (240.00 == 240), else the norm string."""
    from decimal import Decimal, InvalidOperation

    try:
        return Decimal(_norm_price(raw))
    except InvalidOperation:
        return _norm_price(raw)


def allowed_prices(tool_results: list) -> set[str]:
    """Collect verbatim quoted totals from this turn's tool results."""
    allowed: set[str] = set()
    for item in tool_results:
        result = item.get("result") if isinstance(item, dict) else None
        if not isinstance(result, dict):
            continue
        for offer in result.get("offers", []) or []:
            if isinstance(offer, dict) and offer.get("quoted_total"):
                allowed.add(_canon_price(str(offer["quoted_total"])))
        if result.get("quoted_total"):
            allowed.add(_canon_price(str(result["quoted_total"])))
    return allowed


def enforce_price_gate(reply: str, tool_results: list, lang: str) -> tuple[str, bool]:
    """Replace replies containing unquoted prices with a safe handoff.

    Returns (reply_to_speak, gated_flag).
    """
    found = {_canon_price(m.group(0)) for m in PRICE_RE.finditer(reply)}
    if not found:
        return reply, False
    if found.issubset(allowed_prices(tool_results)):
        return reply, False
    return PRICE_HANDOFF.get(lang, PRICE_HANDOFF["et"]), True


def sanitize_history(history: list | None) -> list:
    """Role allowlist + turn cap + char cap. Tool output stays untrusted."""
    clean = []
    for message in history or []:
        if not isinstance(message, dict):
            continue
        if message.get("role") not in ALLOWED_ROLES:
            continue
        content = message.get("content")
        if isinstance(content, str) and len(content) > MAX_HISTORY_CHARS:
            message = {**message, "content": content[:MAX_HISTORY_CHARS]}
        clean.append(message)
    return clean[-MAX_HISTORY_TURNS:]


async def run_turn(
    audio: bytes,
    stt,
    llm_primary,
    tts,
    dispatcher,
    llm_secondary=None,
    language: str = "et",
    history: list | None = None,
) -> dict:
    """Execute one voice turn. Returns heard/reply/audio/tool_results."""
    lang = language if language in ("et", "en", "ru") else "et"
    try:
        text = stt.transcribe(audio)
    except ProviderError:
        # Any STT failure (retryable or bad-payload/4xx) degrades to the
        # repeat prompt — the caller always hears something.

        prompt = REPEAT_PROMPT.get(lang, REPEAT_PROMPT["et"])
        return {
            "text_heard": "",
            "reply": prompt,
            "audio": tts.synthesize(prompt),
            "tool_results": [],
            "fallback_used": True,
        }
    if not (text or "").strip():
        prompt = REPEAT_PROMPT.get(lang, REPEAT_PROMPT["et"])
        return {
            "text_heard": "",
            "reply": prompt,
            "audio": tts.synthesize(prompt),
            "tool_results": [],
            "fallback_used": False,
        }

    messages = sanitize_history(history) + [{"role": "user", "content": text}]
    answer, fallback_used = _sync_chat(
        llm_primary, llm_secondary, messages, tools=BOOKING_TOOLS
    )

    tool_results = []
    tool_calls = answer.get("tool_calls") or []
    if tool_calls:
        for index, call in enumerate(tool_calls):
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            call_id = call.get("id") if isinstance(call, dict) else None
            call_id = call_id or f"call-{index}"
            try:
                result = await dispatcher.dispatch(
                    fn.get("name", ""), fn.get("arguments", {})
                )
            except Exception as exc:  # noqa: BLE001 - errors become results
                result = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"
                    if not isinstance(exc, ProviderError)
                    else str(exc),
                }
            tool_results.append({"id": call_id, "result": result})
        assistant_msg: dict = {
            "role": "assistant",
            "content": answer.get("content"),
            "tool_calls": tool_calls,
        }
        tool_msgs = [
            {
                "role": "tool",
                "tool_call_id": r["id"],
                "content": json.dumps(r["result"], ensure_ascii=False),
            }
            for r in tool_results
        ]
        follow, fallback2 = _sync_chat(
            llm_primary, llm_secondary, messages + [assistant_msg] + tool_msgs
        )
        fallback_used = fallback_used or fallback2
        reply = (follow.get("content") or "").strip()
    else:
        reply = (answer.get("content") or "").strip()

    if not reply:
        reply = FILLER.get(lang, FILLER["et"])
    if len(reply) > MAX_REPLY_CHARS:
        reply = reply[:MAX_REPLY_CHARS].rstrip() + "…"
    reply, _ = enforce_price_gate(reply, tool_results, lang)
    return {
        "text_heard": text,
        "reply": reply,
        "audio": tts.synthesize(reply),
        "tool_results": tool_results,
        "fallback_used": fallback_used,
    }


def _sync_chat(
    llm_primary, llm_secondary, messages: list, tools=None
) -> tuple[dict, bool]:
    """Synchronous chat with one failover (LLM clients are sync)."""
    try:
        if tools is None:
            return llm_primary.chat(messages), False
        return llm_primary.chat(messages, tools=tools), False
    except (RateLimitedError, RetryableProviderError):
        if llm_secondary is None:
            raise
        if tools is None:
            return llm_secondary.chat(messages), True
        return llm_secondary.chat(messages, tools=tools), True
