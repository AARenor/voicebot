"""Bounded question selectors and spoken schedules from trusted venue data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .restaurant_data import DAYS


@dataclass(frozen=True)
class RestaurantQuestion:
    # Keep selector identities only; never retain caller prose or guest details.
    topics: tuple[str, ...]
    days: tuple[int, ...] | None = None
    date: str | None = None


INFORMATION_TOPICS = (
    "menu", "hours", "kitchen", "allergens", "policies", "location", "price",
    "duration", "children", "groups", "cancellation_help", "changes", "late",
    "parking", "pets", "highchair", "accessibility", "terrace", "extras", "staff",
)

PATTERNS = {
    "allergens": r"allerg|allergeen|аллерг|глютен|glut(?:ee|e)n|peanut|pähkl|орех|laktoos|lactose|лактоз|sisald|contain|koostis|ingredients|содерж|состав",
    "price": r"\b(?:price|cost|hind|hinna\w*|hinnaga|maksab|цен\w*|стоим\w*)\b",
    "menu": r"menüü|menu|меню|vegan|веган|vegetarian|taimetoit|вегетар|\b(?:dishes|serve|roogi|блюд\w*)\b|mis.*süüa|mida.*(?:süüa|pakute)",
    "kitchen": r"kitchen|köök|köögi|кухн|(?:kell|kellaajani|millal).*süüa|when.*(?:food|eat)|(?:до скольки|когда).*еда",
    "hours": r"\b(?:hours|open\w*|close\w*|shut|lahtiole\w*|avatud|avate|lahti|kinni|sulge\w*|tööa\w*|откры\w*|закры\w*|работа\w*)\b",
    "location": r"\b(?:where|address|location|located|aadress|asute|asub|kus|где|адрес|находит\w*)\b",
    "duration": r"(?:how long|kui kaua|сколько времени|как долго).*(?:table|stay|keep|laua|broneering|стол|брон)|(?:reservation|broneering|брон\w*).*(?:last|kest|длит)",
    "groups": r"\b(?:group\w*|grup\w*|seltskonn\w*|firmapidu|sünnipäev\w*|групп\w*|компани\w*)\b",
    "children": r"\b(?:children|kids?|child|lapsed|lastega|laste|laps|дети|детей|детьми|реб[её]н\w*)\b",
    "cancellation_help": r"(?:how|kuidas|как).*(?:cancel|tühista|отмен)|(?:can|kas|можно).*(?:cancel|tühista|отмен)",
    "changes": r"(?:change|move|muuta|muutmine|muutmiseks|измен|перенес).*(?:booking|reservation|broneering|брон)|(?:booking|reservation|broneering\w*|брон\w*).*(?:change|move|muuta|muutm|измен|перенес)",
    "late": r"\b(?:late|hiline\w*|опозд\w*)\b",
    "parking": r"parkim|parkida|parking|car park|парков",
    "pets": r"\b(?:dogs?|pets?|koer\w*|lemmikloom\w*|собак\w*|животн\w*)\b",
    "highchair": r"high\s?chair|high chair|lastetool|детск\w*\s+(?:стул|кресл)",
    "accessibility": r"wheelchair|accessible|accessibility|ratastool|ligipääs|инвалид|коляск|доступн",
    "terrace": r"terrac|terrass|outside seating|outdoor seating|террас",
    "extras": r"dessert|magustoit|magustoitu|drinks?|vein|wine|jook|joog|напит|десерт",
    "staff": r"\b(?:staff|human|transfer|callback|personali\w*|inimese\w*|teenindaja\w*|персонал\w*|сотрудник\w*|оператор\w*|перевед\w*)\b|\b(?:order|delivery|takeaway|tellim\w*|kojuvedu|достав\w*|заказ\w*)\b",
    "policies": r"polic|reegl|tingimus|правил",
}

DAY_PATTERNS = (
    r"monday|esmaspäev\w*|понедельник\w*",
    r"tuesday|teisipäev\w*|вторник\w*",
    r"wednesday|kolmapäev\w*|сред[ауые]",
    r"thursday|neljapäev\w*|четверг\w*",
    r"friday|reede\w*|пятниц\w*",
    r"saturday|laupäev\w*|суббот\w*",
    r"sunday|pühapäev\w*|воскресень\w*",
)
BOOKING_REQUEST = re.compile(r"broneer|reserve|reservation|book|lau[ad]|table|брон|столик")


def match_question(
    text: str,
    *,
    previous: RestaurantQuestion | None = None,
    has_dish: bool = False,
    has_diet: bool = False,
    now: datetime | None = None,
) -> RestaurantQuestion | None:
    text = " ".join(text.casefold().split())
    if not text or len(text) > 2000:
        return None
    matches = [(match.start(), topic) for topic, pattern in PATTERNS.items()
               if (match := re.search(pattern, text))]
    topics = [topic for _, topic in sorted(matches)]
    # Narrative party counts are booking details, not a request for policies.
    # In particular, "for two adults and two children" must reach the planner.
    policy_question = bool(re.search(
        r"\?|^(?:kas|kuidas|miks|do|does|can|are|is|how|what|may|мож\w*|как|сколько|вход\w*|учит\w*)\b",
        text,
    ))
    if not policy_question:
        topics = [topic for topic in topics if topic not in {"children", "groups"}]
    if "kitchen" in topics:
        topics = [topic for topic in topics if topic != "hours"]
        if not re.search(r"menüü|menu|меню|pakute|serve|dishes|roogi|блюд", text):
            topics = [topic for topic in topics if topic != "menu"]
    if "highchair" in topics:
        topics = [topic for topic in topics if topic != "children"]
    if "allergens" in topics:
        topics = [topic for topic in topics if topic != "menu"]
    if not topics and (has_dish or has_diet):
        topics = ["menu"]
    days = tuple(index for index, pattern in enumerate(DAY_PATTERNS)
                 if re.search(r"\b(?:" + pattern + r")\b", text))
    if re.search(r"nädalavahetus|weekends?|выходн", text):
        days = (5, 6)
    elif re.search(r"tööpäev|weekdays?|будн", text):
        days = (0, 1, 2, 3, 4)
    elif len(days) == 2 and re.search(r"through|\bto\b|kuni|päevast|reedest|\bпо\b", text):
        days = tuple(range(days[0], days[-1] + 1))
    relative = next((offset for pattern, offset in (
        (r"\bülehomme\b|\bday after tomorrow\b|\bпослезавтра\b", 2),
        (r"\bhomme\b|\btomorrow\b|\bзавтра\b", 1),
        (r"\btäna\b|\btoday\b|\bсегодня\b", 0),
    ) if re.search(pattern, text)), None)
    requested_date = None
    if not topics and previous and not BOOKING_REQUEST.search(text):
        if (days or relative is not None) and len(text.split()) <= 8:
            topics = [topic for topic in previous.topics if topic in {"hours", "kitchen"}]
    if not topics:
        return None
    if (
        not days and relative is None and previous
        and re.search(r"^(?:aga|ja|and|what about|а|и)\b", text)
        and any(topic in {"hours", "kitchen"} for topic in topics)
        and any(topic in {"hours", "kitchen"} for topic in previous.topics)
    ):
        days, requested_date = previous.days or (), previous.date
    if relative is not None and any(topic in {"hours", "kitchen"} for topic in topics):
        today = (now or datetime.now(ZoneInfo("Europe/Tallinn"))).date()
        target = today + timedelta(days=relative)
        requested_date, days = target.isoformat(), (target.weekday(),)
    explicit_date = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    if explicit_date and any(topic in {"hours", "kitchen"} for topic in topics):
        try:
            target = datetime.strptime(explicit_date[0], "%Y-%m-%d").date()
        except ValueError:
            return None
        requested_date, days = target.isoformat(), (target.weekday(),)
    return RestaurantQuestion(tuple(topics[:3]), days or None, requested_date)


SINGLES = {
    "et": ("esmaspäeval", "teisipäeval", "kolmapäeval", "neljapäeval", "reedel", "laupäeval", "pühapäeval"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "ru": ("в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье"),
}
FROM_DAYS = {
    "et": ("esmaspäevast", "teisipäevast", "kolmapäevast", "neljapäevast", "reedest", "laupäevast", "pühapäevast"),
    "ru": ("с понедельника", "со вторника", "со среды", "с четверга", "с пятницы", "с субботы", "с воскресенья"),
}
TO_DAYS = {
    "et": ("esmaspäevani", "teisipäevani", "kolmapäevani", "neljapäevani", "reedeni", "laupäevani", "pühapäevani"),
    "ru": ("по понедельник", "по вторник", "по среду", "по четверг", "по пятницу", "по субботу", "по воскресенье"),
}


def natural_list(items: list[str], language: str) -> str:
    conjunction = {"et": " ning ", "en": " and ", "ru": " и "}[language]
    return conjunction.join(items) if len(items) <= 2 else ", ".join(items[:-1]) + conjunction + items[-1]


def _day_label(indices: list[int], language: str) -> str:
    if indices == list(range(7)):
        return {"et": "iga päev", "en": "every day", "ru": "каждый день"}[language]
    if len(indices) == 1:
        return SINGLES[language][indices[0]]
    if len(indices) == 2:
        labels = [SINGLES[language][index] for index in indices]
        if language == "ru":
            labels[1] = labels[1].removeprefix("в ").removeprefix("во ")
        return {"et": " ja ", "en": " and ", "ru": " и "}[language].join(labels)
    if language == "en":
        return SINGLES[language][indices[0]] + " through " + SINGLES[language][indices[-1]]
    return FROM_DAYS[language][indices[0]] + " " + TO_DAYS[language][indices[-1]]


def _clock(value: str) -> str:
    hour, _, minute = value.partition(":")
    return str(int(hour)) + (":" + minute if minute != "00" else "")


def format_schedule(
    data: dict[str, Any],
    language: str,
    *,
    days: tuple[int, ...] | None = None,
    kitchen: bool = False,
) -> str:
    """Combine equal consecutive selected days; never bridge an omitted day."""
    groups: list[tuple[list[int], tuple[str, str] | None]] = []
    for index in sorted(set(days if days is not None else range(7))):
        hours = data["opening_hours"][DAYS[index]]
        interval = None
        if hours:
            end = hours["end"]
            if kitchen:
                end = (datetime.strptime(end, "%H:%M") - timedelta(minutes=data["kitchen_closes_minutes_before"])).strftime("%H:%M")
            if end > hours["start"]:
                interval = (hours["start"], end)
        if groups and groups[-1][1] == interval and groups[-1][0][-1] + 1 == index:
            groups[-1][0].append(index)
        else:
            groups.append(([index], interval))
    parts = []
    for indices, interval in groups:
        label = _day_label(indices, language)
        if interval is None:
            value = {"et": "suletud", "en": "closed", "ru": "закрыто"}[language]
        else:
            start, end = map(_clock, interval)
            value = {"et": f"kell {start}–{end}", "en": f"{start}–{end}", "ru": f"с {start} до {end}"}[language]
        parts.append(label + " " + value)
    answer = natural_list(parts, language)
    return answer[:1].upper() + answer[1:]


GUIDANCE = {
    "et": {
        "duration": "Laud on broneeritud {duration} minutiks.",
        "children": "Arvesta lapsed broneeringu inimeste arvu sisse.",
        "groups": "Laua saab broneerida kuni {maximum} inimesele. Suurema grupiga tulek lepi personaliga kokku.",
        "cancellation_help": "Selles vestluses tehtud broneeringu tühistamiseks ütle „Jah, tühista”.",
        "changes": "Broneeringu muutmiseks võta ühendust restorani töötajaga.",
        "late": "Kui hilined, küsi töötajalt, kas laud saab oodata.",
        "parking": "Parkimisvõimalused täpsustab restorani töötaja.",
        "pets": "Lemmikloomaga tulek küsi restorani töötajalt üle.",
        "highchair": "Lastetooli olemasolu küsi restorani töötajalt.",
        "accessibility": "Ligipääsetavus täpsusta restorani töötajaga.",
        "terrace": "Terrassikoht tuleb restorani töötajaga kokku leppida.",
        "extras": "Mul pole selle kohta menüüinfot. Küsi restorani töötajalt.",
    },
    "en": {
        "duration": "The table reservation lasts {duration} minutes.",
        "children": "Include children in the total number of guests.",
        "groups": "You can book for up to {maximum} guests. Please arrange larger groups with the team.",
        "cancellation_help": 'To cancel a booking made in this conversation, say "Yes, cancel".',
        "changes": "Please contact the restaurant team to change a reservation.",
        "late": "If you're running late, ask the team whether they can keep your table.",
        "parking": "Please ask the restaurant team about parking.",
        "pets": "Please check with the restaurant team before bringing a pet.",
        "highchair": "Please ask the restaurant team whether a high chair is available.",
        "accessibility": "Please check accessibility with the restaurant team.",
        "terrace": "Please arrange terrace seating with the restaurant team.",
        "extras": "I don't have that menu information. Please ask the restaurant team.",
    },
    "ru": {
        "duration": "Столик бронируется на {duration} минут.",
        "children": "Включите детей в общее число гостей.",
        "groups": "Можно забронировать столик на {maximum} гостей. Большую группу согласуйте с персоналом.",
        "cancellation_help": "Чтобы отменить бронь, сделанную в этом разговоре, скажите «Да, отмените».",
        "changes": "Для изменения брони свяжитесь с сотрудником ресторана.",
        "late": "Если опаздываете, уточните у сотрудника, смогут ли придержать столик.",
        "parking": "Уточните возможность парковки у сотрудника ресторана.",
        "pets": "Приход с питомцем уточните у сотрудника ресторана.",
        "highchair": "Уточните наличие детского стула у сотрудника ресторана.",
        "accessibility": "Уточните доступность у сотрудника ресторана.",
        "terrace": "Место на террасе согласуйте с сотрудником ресторана.",
        "extras": "У меня нет этой информации о меню. Уточните у сотрудника ресторана.",
    },
}
