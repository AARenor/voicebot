"""Pronunciation-only formatting; never changes stored or displayed replies."""

import re


_TIME_RANGE = re.compile(
    r"(?<![\w:./–—-])"
    r"(?P<start>(?:[01]?\d|2[0-3])(?::[0-5]\d)?)"
    r"\s*[-–—]\s*"
    r"(?P<end>(?:[01]?\d|2[0-3])(?::[0-5]\d)?)"
    r"(?![\w:/–—-]|\.\d)"
)
_HOURS_CONTEXT = re.compile(r"\b(?:kell|avatud|tööa\w*|lahtioleku\w*)\b", re.I)
_OTHER_UNITS = re.compile(
    r"^\s*(?:€|%|\b(?:eur|euro\w*|kraadi|minutit|külalist|ööd)\b)", re.I
)


def normalize_estonian_speech(text: str, lang: str = "et-EE") -> str:
    """Read clock ranges as '9 kuni kell 17' instead of an ambiguous dash."""
    if lang.casefold() not in {"et", "et-ee"}:
        return text

    def clock(value):
        hour, separator, minute = value.partition(":")
        return str(int(hour)) + (":" + minute if separator and minute != "00" else "")

    def replace(match):
        start, end = match.group("start", "end")
        if ":" not in start and ":" not in end:
            # Bare numeric ranges also occur in prices, dates and quantities.
            # Require an hours context or a standalone range before speaking
            # them as clock times; full HH:MM ranges identify themselves.
            before, after = text[:match.start()], text[match.end():]
            standalone = not before.strip() and not after.strip(" \t\r\n.!?")
            if _OTHER_UNITS.match(after) or not (
                standalone or _HOURS_CONTEXT.search(before[-120:])
            ):
                return match.group(0)
        return f"{clock(start)} kuni kell {clock(end)}"

    return _TIME_RANGE.sub(replace, text)
