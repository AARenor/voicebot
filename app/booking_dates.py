"""Resolve Estonian caller dates; these are preferences, never booking consent."""

from datetime import date, timedelta
import re


MONTHS = (
    ("jaanuar", "jaanuaril"), ("veebruar", "veebruaril"),
    ("märts", "märtsil"), ("aprill", "aprillil"), ("mai", "mail"),
    ("juuni", "juunil"), ("juuli", "juulil"), ("august", "augustil"),
    ("september", "septembril"), ("oktoober", "oktoobril"),
    ("november", "novembril"), ("detsember", "detsembril"),
)
ORDINALS = (
    ("esimene", "esimesel"), ("teine", "teisel"), ("kolmas", "kolmandal"),
    ("neljas", "neljandal"), ("viies", "viiendal"), ("kuues", "kuuendal"),
    ("seitsmes", "seitsmendal"), ("kaheksas", "kaheksandal"),
    ("üheksas", "üheksandal"), ("kümnes", "kümnendal"),
)
_MONTH_NUMBERS = {word: number for number, words in enumerate(MONTHS, 1) for word in words}
_DAY_NUMBERS = {word: number for number, words in enumerate(ORDINALS, 1) for word in words}
_DAY = r"(?:\d{1,2}|" + "|".join(_DAY_NUMBERS) + ")"
_MONTH = "(?:" + "|".join(_MONTH_NUMBERS) + ")"
_NAMED_DATE = rf"{_DAY}\.?\s+{_MONTH}(?:\s+\d{{4}}(?:\.?\s+aasta(?:l)?)?)?"
ESTONIAN_DATE_PATTERN = rf"(?:ülehomme|homme|täna|\d{{4}}-\d{{2}}-\d{{2}}|{_NAMED_DATE})"
DATE_MENTIONS = re.compile(rf"(?<![\w-]){ESTONIAN_DATE_PATTERN}(?![\w-])", re.I)
_NAMED_PARTS = re.compile(
    rf"(?P<day>{_DAY})\.?\s+(?P<month>{_MONTH})"
    r"(?:\s+(?P<year>\d{4})(?:\.?\s+aasta(?:l)?)?)?", re.I,
)


def resolve_estonian_date(token: str, today: date) -> dict[str, str]:
    """Resolve an exact token against Tallinn's date, without guessing invalid dates.

    A month/day without a year means its next occurrence, including today.
    Explicit years remain exact, and past or impossible dates require clarification.
    """
    token = token.casefold().strip()
    try:
        if token in {"täna", "homme", "ülehomme"}:
            resolved = today + timedelta(days={"täna": 0, "homme": 1, "ülehomme": 2}[token])
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
            resolved = date.fromisoformat(token)
        elif match := _NAMED_PARTS.fullmatch(token):
            day = int(match["day"]) if match["day"].isdigit() else _DAY_NUMBERS[match["day"]]
            month = _MONTH_NUMBERS[match["month"]]
            year = int(match["year"]) if match["year"] else today.year
            if match["year"]:
                resolved = date(year, month, day)
            else:
                # Validate independently of the current leap year, then choose
                # the next real occurrence (29 February may be years away).
                date(2000, month, day)
                for year in range(today.year, min(today.year + 5, 10000)):
                    try:
                        resolved = date(year, month, day)
                    except ValueError:
                        continue
                    if resolved >= today:
                        break
                else:
                    return {"status": "invalid"}
        else:
            return {"status": "invalid"}
    except (ValueError, OverflowError):
        return {"status": "invalid"}
    return {"status": "past" if resolved < today else "resolved", "date": resolved.isoformat()}


def interpreted_dates(text: str, today: date) -> list[dict[str, str]]:
    """Return only normalized fields from the current finalized utterance."""
    return [resolve_estonian_date(match[0], today) for match in DATE_MENTIONS.finditer(text)]
