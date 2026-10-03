"""Bounded date vocabulary for restaurant requests, never booking consent.

Estonian case endings are tolerated in date/count context even when the caller
mixes cases. No fuzzy matching or replacement of the stored caller text occurs.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta


CASE_ENDINGS = ("", "l", "le", "ks", "st", "ga", "ni", "s", "sse", "ta", "lt", "t")
CARDINAL_BASES = (
    ("üks", "ühe", "üht", "ühte"),
    ("kaks", "kahe", "kaht", "kahte"),
    ("kolm", "kolme"),
    ("neli", "nelja"),
    ("viis", "viie", "viit"),
    ("kuus", "kuue", "kuut"),
    ("seitse", "seitsme", "seitset"),
    ("kaheksa",),
    ("üheksa",),
    ("kümme", "kümne", "kümmet"),
)
ORDINAL_BASES = (
    ("esimene", "esimese", "esimest"),
    ("teine", "teise", "teist"),
    ("kolmas", "kolmanda"),
    ("neljas", "neljanda"),
    ("viies", "viienda"),
    ("kuues", "kuuenda"),
    ("seitsmes", "seitsmenda"),
    ("kaheksas", "kaheksanda"),
    ("üheksas", "üheksanda"),
    ("kümnes", "kümnenda"),
)


def _forms(bases: tuple[str, ...]) -> set[str]:
    return {base + ending for base in bases for ending in CASE_ENDINGS}


ESTONIAN_COUNTS = {
    form: number
    for number, bases in enumerate(CARDINAL_BASES, 1)
    for form in _forms(bases)
}
DAY_FORMS = dict(ESTONIAN_COUNTS)
DAY_FORMS["null"] = 0
for number, bases in enumerate(ORDINAL_BASES, 1):
    DAY_FORMS.update(dict.fromkeys(_forms(bases), number))
for number, (cardinal, stem) in enumerate(
    zip(
        (
            "üksteist",
            "kaksteist",
            "kolmteist",
            "neliteist",
            "viisteist",
            "kuusteist",
            "seitseteist",
            "kaheksateist",
            "üheksateist",
        ),
        (
            "üheteist",
            "kaheteist",
            "kolmeteist",
            "neljateist",
            "viieteist",
            "kuueteist",
            "seitsmeteist",
            "kaheksateist",
            "üheksateist",
        ),
    ),
    11,
):
    DAY_FORMS.update(
        dict.fromkeys(
            _forms((cardinal, stem + "kümne", stem + "kümnes", stem + "kümnenda")),
            number,
        )
    )
for tens, cardinal, stem in ((20, "kakskümmend", "kahe"), (30, "kolmkümmend", "kolme")):
    DAY_FORMS.update(
        dict.fromkeys(
            _forms((cardinal, stem + "kümne", stem + "kümnes", stem + "kümnenda")), tens
        )
    )
    # Also recognize 32..39 so an impossible day cannot fall back to day 2..9.
    for form, units in list(DAY_FORMS.items()):
        if 1 <= units <= 9:
            for prefix in (cardinal, stem + "kümne"):
                for separator in (" ", "", "-"):
                    DAY_FORMS[prefix + separator + form] = tens + units

MONTH_BASES = (
    ("jaanuar", "jaanuari"),
    ("veebruar", "veebruari"),
    ("märts", "märtsi"),
    ("aprill", "aprilli"),
    ("mai",),
    ("juuni",),
    ("juuli",),
    ("august", "augusti"),
    ("september", "septembri"),
    ("oktoober", "oktoobri"),
    ("november", "novembri"),
    ("detsember", "detsembri"),
)
MONTH_FORMS = {
    base + ending: number
    for number, bases in enumerate(MONTH_BASES, 1)
    for base in bases
    for ending in CASE_ENDINGS + ("il", "ile", "iks", "ist", "iga", "ini")
}


def _alternatives(forms: dict[str, int]) -> str:
    return "|".join(
        re.escape(form)
        for form in sorted(forms, key=lambda value: (-len(value), value))
    )


DAY_PATTERN = r"(?:\d{1,2}\.?|" + _alternatives(DAY_FORMS) + ")"
MONTH_PATTERN = "(?:" + _alternatives(MONTH_FORMS) + ")"
NAMED_DATES = (
    re.compile(
        r"(?<!\w)(?P<day>"
        + DAY_PATTERN
        + r")\s*(?P<month>"
        + MONTH_PATTERN
        + r")(?!\w)"
    ),
    re.compile(
        r"(?<!\w)(?P<month>"
        + MONTH_PATTERN
        + r")\s+(?P<day>"
        + DAY_PATTERN
        + r")(?!\w)"
    ),
)
MONTHS = re.compile(r"\b" + MONTH_PATTERN + r"\b")
ALTERNATIVE_DAY = re.compile(
    r"(?<!\w)" + DAY_PATTERN + r"\s*(?:või|ja|kuni|or|through|to|или|до|[-–])\s*$"
)
ISO_DATE = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")
LOCAL_DATE = re.compile(r"\b(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})\b")

TOMORROW_FORMS = {"homme", "hommele", "hommeks"} | {
    "homs" + ending
    for ending in ("e", "eks", "ele", "el", "est", "et", "esse", "eni", "ega")
}
RELATIVE_FORMS = {
    **dict.fromkeys(TOMORROW_FORMS, 1),
    **dict.fromkeys({"üle" + form for form in TOMORROW_FORMS}, 2),
    **dict.fromkeys(
        {"täna", "tänaks", "tänale"}
        | {
            "tänas" + ending
            for ending in ("e", "eks", "ele", "el", "est", "et", "esse", "eni", "ega")
        },
        0,
    ),
    "tomorrow": 1,
    "day after tomorrow": 2,
    "today": 0,
    "завтра": 1,
    "послезавтра": 2,
    "сегодня": 0,
}
RELATIVE = re.compile(r"\b(?:" + _alternatives(RELATIVE_FORMS) + r")\b")
WEEKDAYS = {
    "monday": 0,
    "esmaspäev": 0,
    "понедельник": 0,
    "tuesday": 1,
    "teisipäev": 1,
    "вторник": 1,
    "wednesday": 2,
    "kolmapäev": 2,
    "сред": 2,
    "thursday": 3,
    "neljapäev": 3,
    "четверг": 3,
    "friday": 4,
    "reede": 4,
    "пятниц": 4,
    "saturday": 5,
    "laupäev": 5,
    "суббот": 5,
    "sunday": 6,
    "pühapäev": 6,
    "воскресенье": 6,
}
WEEKDAY = re.compile(r"\b(?P<base>" + _alternatives(WEEKDAYS) + r")\w*\b")


@dataclass(frozen=True)
class DateResolution:
    value: str | None
    issue: str | None
    remaining_text: str


def resolve_restaurant_date(text: str, now: datetime) -> DateResolution:
    """Resolve one date, masking its words before time and party extraction.

    A missing year means the next occurrence of that calendar date. Explicit
    years are kept. The restaurant's existing advance window is enforced later.
    Conflicting, negated or impossible dates ask for clarification instead.
    """
    text = " ".join(unicodedata.normalize("NFC", text.casefold()).split())
    spans: list[tuple[int, int]] = []
    values: set[str] = set()
    issue = None

    def record(
        start: int, end: int, value: date | None, error: str | None = None
    ) -> None:
        nonlocal issue
        if any(start < right and end > left for left, right in spans):
            return
        spans.append((start, end))
        # A declined date is not a booking request, even if only one was heard.
        if re.search(r"\b(?:mitte|ei|ära|not|не)(?:\s+\w+){0,2}\s*$", text[:start]):
            error = "date_ambiguous"
        if error:
            issue = error
        elif value:
            values.add(value.isoformat())

    def calendar(
        day: int, month: int, year: int | None
    ) -> tuple[date | None, str | None]:
        try:
            candidate = date(year or now.year, month, day)
            if year is None and candidate < now.date():
                candidate = date(now.year + 1, month, day)
            return candidate, None
        except ValueError:
            return None, "date_invalid"

    for pattern in (ISO_DATE, LOCAL_DATE):
        for match in pattern.finditer(text):
            value, error = calendar(
                int(match["day"]), int(match["month"]), int(match["year"])
            )
            record(*match.span(), value, error)
    for pattern in NAMED_DATES:
        for match in pattern.finditer(text):
            raw_day = match["day"].rstrip(".")
            day = int(raw_day) if raw_day.isdecimal() else DAY_FORMS[raw_day]
            end = match.end()
            start = match.start()
            year = None
            error = None
            # Do not consume a neighbouring guest count as a year.
            year_match = re.match(r"\s+(\d{2,4})(?!\d)", text[end:])
            if year_match and not re.match(
                r"\s+(?:inimes|külalis|külalist|täiskasvan|last|lapse|people|guests|adults|children)\w*\b",
                text[end + year_match.end() :],
            ):
                end += year_match.end()
                if len(year_match[1]) != 4:
                    error = "date_ambiguous"
                else:
                    year = int(year_match[1])
            preceding_year = re.search(r"\b(\d{4})\.?\s+aasta(?:l)?\s+$", text[:start])
            if preceding_year:
                start = preceding_year.start()
                if year is not None and year != int(preceding_year[1]):
                    error = "date_ambiguous"
                else:
                    year = int(preceding_year[1])
            # Unsupported larger compound numbers must not become their units.
            if re.search(
                r"\b(?:\w*(?:kümmend|kümne|sada|saja)|\d+)[ -]+$", text[: match.start()]
            ):
                error = "date_invalid"
            if ALTERNATIVE_DAY.search(text[: match.start()]):
                error = "date_ambiguous"
            value, invalid = calendar(day, MONTH_FORMS[match["month"]], year)
            record(start, end, value, error or invalid)
    for match in RELATIVE.finditer(text):
        record(*match.span(), now.date() + timedelta(days=RELATIVE_FORMS[match[0]]))
    for match in WEEKDAY.finditer(text):
        offset = (WEEKDAYS[match["base"]] - now.weekday()) % 7 or 7
        record(*match.span(), now.date() + timedelta(days=offset))
    for match in MONTHS.finditer(text):
        if not any(
            match.start() < right and match.end() > left for left, right in spans
        ):
            record(*match.span(), None, "date_incomplete")
    if len(values) > 1:
        issue = "date_ambiguous"
    remaining = list(text)
    for left, right in spans:
        remaining[left:right] = " " * (right - left)
    return DateResolution(
        next(iter(values)) if len(values) == 1 and not issue else None,
        issue,
        "".join(remaining),
    )
