"""Shared Azure delivery and pronunciation, independent of media dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from html import escape
import os
import re
from xml.sax.saxutils import quoteattr

from ..languages import CONSENT


@dataclass(frozen=True)
class SpeechDelivery:
    mode: str = "natural"
    rate: float = 0.98
    recap_rate: float = 0.94
    sentence_pause_ms: int = 180

    def __post_init__(self) -> None:
        if (
            self.mode not in {"natural", "neutral"}
            or not 0.85 <= self.rate <= 1.15
            or not 0.85 <= self.recap_rate <= 1.15
            or isinstance(self.sentence_pause_ms, bool)
            or not isinstance(self.sentence_pause_ms, int)
            or not 100 <= self.sentence_pause_ms <= 500
        ):
            raise ValueError("invalid speech delivery configuration")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SpeechDelivery:
        env = os.environ if env is None else env
        try:
            return cls(
                mode=env.get("VOICEBOT_SPEAKING_STYLE", "natural").strip(),
                rate=float(env.get("VOICEBOT_SPEECH_RATE", "0.98")),
                recap_rate=float(env.get("VOICEBOT_RECAP_RATE", "0.94")),
                sentence_pause_ms=int(env.get("VOICEBOT_SENTENCE_PAUSE_MS", "180")),
            )
        except (TypeError, ValueError):
            raise ValueError("invalid speech delivery configuration") from None

    def effective_rate(self, *, recap: bool = False) -> float:
        if self.mode == "neutral":
            return 1.0
        return min(self.rate, self.recap_rate) if recap else self.rate


def is_recap(text: str) -> bool:
    return any(consent in text for consent in CONSENT.values())


def spoken_estonian_date(value: str) -> str:
    date = datetime.fromisoformat(value)
    days = (
        "esmaspäeval",
        "teisipäeval",
        "kolmapäeval",
        "neljapäeval",
        "reedel",
        "laupäeval",
        "pühapäeval",
    )
    months = (
        "jaanuaril",
        "veebruaril",
        "märtsil",
        "aprillil",
        "mail",
        "juunil",
        "juulil",
        "augustil",
        "septembril",
        "oktoobril",
        "novembril",
        "detsembril",
    )
    return f"{days[date.weekday()]}, {date.day}. {months[date.month - 1]} {date.year}"


_PRONUNCIATION = re.compile(
    r"(?<!\w)(?:\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|kell \d{2}:\d{2}|ajavöönd Europe/Tallinn|Europe/Tallinn)(?!\w)"
)


def spoken_estonian_time(hour: int, minute: int) -> str:
    words = (
        "null",
        "üks",
        "kaks",
        "kolm",
        "neli",
        "viis",
        "kuus",
        "seitse",
        "kaheksa",
        "üheksa",
        "kümme",
        "üksteist",
        "kaksteist",
        "kolmteist",
        "neliteist",
        "viisteist",
        "kuusteist",
        "seitseteist",
        "kaheksateist",
        "üheksateist",
    )
    tens = ("", "", "kakskümmend", "kolmkümmend", "nelikümmend", "viiskümmend")

    def number(value: int) -> str:
        if value < 20:
            return words[value]
        return tens[value // 10] + (" " + words[value % 10] if value % 10 else "")

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("invalid spoken time")
    return number(hour) + (" " + number(minute) if minute else "")


def _pronounced_text(text: str, language: str) -> str:
    if language != "et-EE":
        return escape(text, quote=False)
    parts, end = [], 0
    for match in _PRONUNCIATION.finditer(text):
        parts.append(escape(text[end : match.start()], quote=False))
        original = match[0]
        try:
            if "Europe/Tallinn" in original:
                alias = "Tallinna aja järgi"
            elif original.startswith("kell "):
                hour, minute = map(int, original[5:].split(":"))
                alias = "kell " + spoken_estonian_time(hour, minute)
            else:
                date = datetime.fromisoformat(original)
                alias = spoken_estonian_date(original)
                if len(original) > 10:
                    alias += " kell " + spoken_estonian_time(date.hour, date.minute)
            parts.append(
                f"<sub alias={quoteattr(alias)}>{escape(original, quote=False)}</sub>"
            )
        except ValueError:
            parts.append(escape(original, quote=False))
        end = match.end()
    parts.append(escape(text[end:], quote=False))
    return "".join(parts)


def speech_markup(
    text: str,
    voice: str,
    language: str,
    delivery: SpeechDelivery,
    *,
    recap: bool = False,
) -> str:
    # All model/backend text is literal. Only this renderer can introduce tags.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    if delivery.mode == "neutral":
        return escape(text, quote=False)
    body = _pronounced_text(text, language)
    rate = delivery.effective_rate(recap=recap)
    body = f'<prosody rate="{rate:.2f}">{body}</prosody>'
    # Use only documented styles; Anu/Kert keep their native intonation.
    if voice in {"en-US-JennyNeural", "en-US-GuyNeural"} and language == "en-US":
        body = f'<mstts:express-as style="friendly" styledegree="0.8">{body}</mstts:express-as>'
    # Short sentence pauses keep replies conversational. Recaps retain the
    # provider's default pauses so dates and consent remain easy to follow.
    if not recap:
        body = (
            f'<mstts:silence type="Sentenceboundary-exact" '
            f'value="{delivery.sentence_pause_ms}ms"/>' + body
        )
    return body
