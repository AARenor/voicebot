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

import asyncio
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
    """Role allowlist + turn cap + char cap. Tool output stays untrusted.

    Non-string content blocks are JSON-encoded (truncated) so a list
    payload can't sail through untruncated into provider context.
    """
    clean = []
    for message in history or []:
        if not isinstance(message, dict):
            continue
        if message.get("role") not in ALLOWED_ROLES:
            continue
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
            message = {**message, "content": content}
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
    text: str | None = None,
) -> dict:
    """Execute one voice turn. Returns heard/reply/audio/tool_results.

    text skips STT (typed/test turns); audio turns transcribe first.
    """
    lang = language if language in ("et", "en", "ru") else "et"
    if text is None:
        if not (audio or b"").strip():
            # Empty audio never reaches paid STT.
            prompt = REPEAT_PROMPT.get(lang, REPEAT_PROMPT["et"])
            return {
                "text_heard": "",
                "reply": prompt,
                "audio": await _speak(tts, prompt),
                "tool_results": [],
                "fallback_used": False,
            }
        try:
            text = await asyncio.to_thread(stt.transcribe, audio)
        except ProviderError:
            # Any STT failure (retryable or bad-payload/4xx) degrades to the
            # repeat prompt — the caller always hears something.
            prompt = REPEAT_PROMPT.get(lang, REPEAT_PROMPT["et"])
            return {
                "text_heard": "",
                "reply": prompt,
                "audio": await _speak(tts, prompt),
                "tool_results": [],
                "fallback_used": True,
            }
    if not (text or "").strip():
        prompt = REPEAT_PROMPT.get(lang, REPEAT_PROMPT["et"])
        return {
            "text_heard": "",
            "reply": prompt,
            "audio": await _speak(tts, prompt),
            "tool_results": [],
            "fallback_used": False,
        }

    try:
        return await _run_dialogue(
            text,
            lang,
            messages=sanitize_history(history) + [{"role": "user", "content": text}],
            stt=stt,
            llm_primary=llm_primary,
            tts=tts,
            dispatcher=dispatcher,
            llm_secondary=llm_secondary,
        )
    except Exception:
        # Last resort: programming bugs still produce a handoff, never a
        # dropped call. (PII-free static text.)
        handoff = PRICE_HANDOFF.get(lang, PRICE_HANDOFF["et"])
        return {
            "text_heard": text if isinstance(text, str) else "",
            "reply": handoff,
            "audio": await _speak(tts, handoff),
            "tool_results": [],
            "fallback_used": True,
        }


async def _speak(tts, text: str) -> bytes:
    """Synthesize off the event loop, degrading to silence."""
    try:
        return await asyncio.to_thread(tts.synthesize, text)
    except Exception:
        return b""


async def _run_dialogue(
    text: str,
    lang: str,
    messages: list,
    stt,
    llm_primary,
    tts,
    dispatcher,
    llm_secondary=None,
) -> dict:
    """Core turn after audio/text are validated (may raise)."""
    messages = messages
    answer, fallback_used = await asyncio.to_thread(
        _sync_chat, llm_primary, llm_secondary, messages, BOOKING_TOOLS
    )

    tool_results = []
    for _round in range(2):  # at most two tool rounds, then render
        tool_calls = answer.get("tool_calls") or []
        if not tool_calls:
            break
        round_results = []
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
            round_results.append({"id": call_id, "result": result})
        tool_results.extend(round_results)
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
            for r in round_results
        ]
        messages = messages + [assistant_msg] + tool_msgs
        # Follow-up keeps tools: one-shot chains (search → hold) work.
        answer, fallback_round = await asyncio.to_thread(
            _sync_chat, llm_primary, llm_secondary, messages, BOOKING_TOOLS
        )
        fallback_used = fallback_used or fallback_round
    reply = (answer.get("content") or "").strip()

    if not reply:
        reply = FILLER.get(lang, FILLER["et"])
    if len(reply) > MAX_REPLY_CHARS:
        reply = reply[:MAX_REPLY_CHARS].rstrip() + "…"
    reply, _ = enforce_price_gate(reply, tool_results, lang)
    audio = await _speak(tts, reply)
    return {
        "text_heard": text,
        "reply": reply,
        "audio": audio,
        "tool_results": tool_results,
        "fallback_used": fallback_used,
        "tts_failed": audio == b"",
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
        redacted = _redact_for_secondary(messages)
        if tools is None:
            return llm_secondary.chat(redacted), True
        return llm_secondary.chat(redacted, tools=tools), True


_PII_KEYS = {
    "guest",
    "customer",
    "customerid",
    "phone",
    "email",
    "firstname",
    "lastname",
    "name",
}


_PHONE_RE = re.compile(r"\+\d{7,}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _scrub(value):
    """Drop guest-shaped keys recursively (secondary-tier PII guard)."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k.lower() not in _PII_KEYS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str):
        return _PHONE_RE.sub(
            "[redacted phone]", _EMAIL_RE.sub("[redacted email]", value)
        )
    return value


def _redact_for_secondary(messages: list) -> list:
    """Strip tool-call skeletons and guest PII before the failover LLM.

    The free-tier secondary may train on prompts: it gets conversation
    prose, never tool args/results carrying names/phones. Documented
    degradation: failover answers without booking detail.
    """
    redacted = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        message = {k: v for k, v in message.items() if k != "tool_calls"}
        if message.get("role") == "tool":
            message = {**message, "content": "[redacted tool output]"}
        elif isinstance(message.get("content"), (dict, list)):
            message = {**message, "content": _scrub(message["content"])}
        elif isinstance(message.get("content"), str):
            message = {**message, "content": _scrub(message["content"])}
        redacted.append(message)
    return redacted
