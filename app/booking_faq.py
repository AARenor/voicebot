"""Reviewed booking questions; dynamic answers use the current tool result only."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .languages import LANGUAGES, spoken_time
from .booking_dates import ESTONIAN_DATE_PATTERN


FAQ_PATH = Path(__file__).resolve().parents[1] / "data/demo/booking-faq.json"
RESTAURANT_FAQ_PATH = FAQ_PATH.with_name("restaurant-phone-faq.json")
ROUTES = {"static", "stay_catalogue", "slot_catalogue", "clarify", "status"}
CLARIFY = {
    "et": "Ma ei saanud päris täpselt aru. Kas soovid infot hotelli, spaa või testbroneeringu kohta?",
    "en": "I didn't quite understand. Would you like information about the hotel, spa or a test booking?",
    "ru": "Я не совсем поняла. Вам нужна информация об отеле, спа или тестовом бронировании?",
}
RESTAURANT_CLARIFY = {
    "et": "Ma ei saanud küsimusest päris täpselt aru. Kas küsid menüü, lahtiolekuaegade või lauabroneeringu kohta?",
    "en": "I didn't quite understand. The Meretuule Kitchen demo can answer verified restaurant questions, but real table reservations are not configured.",
    "ru": "Я не совсем понял. Демонстрация Meretuule Köök может отвечать на подтверждённые вопросы о ресторане, но настоящие бронирования столиков не настроены.",
}
MISSING_FACTS = {
    "et": "Selle küsimuse jaoks vajalikku infot ei saanud praegu süsteemist kinnitada. Palun proovi hiljem uuesti.",
    "en": "I couldn't verify the information needed for that question in the system. Please try again later.",
    "ru": "Не удалось проверить нужную для этого вопроса информацию в системе. Попробуйте позже.",
}
NO_BOOKING = {
    "et": "Selles vestluses ei ole kinnitatud testbroneeringut. Kas soovid broneerimisega alustada?",
    "en": "There is no confirmed test booking in this conversation. Would you like to start a booking?",
    "ru": "В этом разговоре нет подтверждённого тестового бронирования. Хотите начать бронирование?",
}
ROOM_CONTEXT = {
    "et": ("Vabad demotoad tuleb eraldi kontrollida.", "Demobroneeringus saab arvestada täiskasvanute ja laste arvu.", "Eraldi voodite olemasolu ei ole kinnitatud ja voodite ümberseadistamist demo ei toeta."),
    "en": ("Available demo rooms need a separate check.", "A demo booking can include adults and children.", "Separate beds have not been verified, and the demo does not support changing the bed setup."),
    "ru": ("Наличие свободных демонстрационных номеров нужно проверить отдельно.", "В тестовом бронировании можно указать взрослых и детей.", "Наличие отдельных кроватей не подтверждено. Демонстрация не поддерживает изменение расположения кроватей."),
}


def action_claim(text):
    """Keep the established receipt warning for an unsupported success claim."""
    return bool(re.search(
        r"\b(?:broneerisin|broneerisime|tühistasin|"
        r"(?:test)?broneering\s+on\s+(?:kinnitatud|tühistatud|(?:edukalt\s+)?loodud)|"
        r"(?:test\s+)?booking\s+(?:is|was|has been)\s+(?:confirmed|cancelled|canceled|created)|"
        r"i\s+(?:have\s+)?(?:booked|reserved|cancelled|canceled)|"
        r"(?:тестовое\s+)?бронирование\s+(?:подтвержд[её]н\w*|отмен[её]н\w*)|"
        r"забронировал\w*|забронирован\w*)\b",
        text, re.I,
    ))


COURTESY = {
    "et": ("tere palun öelge", "palun öelge", "öelge palun", "tere", "tervist", "palun", "vabandust"),
    "en": ("hello could you tell me", "could you tell me", "can you tell me", "please tell me", "hello", "hi", "please", "excuse me"),
    "ru": ("здравствуйте подскажите пожалуйста", "подскажите пожалуйста", "скажите пожалуйста", "подскажите", "здравствуйте", "привет", "пожалуйста"),
}


@lru_cache(maxsize=4)
def load_faq(path=None):
    """Fail closed on incomplete translations or unknown routing metadata."""
    try:
        data = json.loads(Path(path or FAQ_PATH).read_text(encoding="utf-8"))
        entries = data["entries"]
        if data["schema_version"] != 1 or not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise ValueError
        ids = set()
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("route") not in ROUTES:
                raise ValueError
            identifier = entry["id"]
            if not isinstance(identifier, str) or not re.fullmatch(r"booking-\d{3}", identifier) or identifier in ids:
                raise ValueError
            ids.add(identifier)
            for language in LANGUAGES:
                for kind in ("question", "answer"):
                    text = entry[kind + "_" + language]
                    if not isinstance(text, str) or not text.strip() or len(text) > 500:
                        raise ValueError
                variants = entry.get("variants_" + language, [])
                if not isinstance(variants, list) or len(variants) > 20 or any(
                    not isinstance(text, str) or not text.strip() or len(text) > 500
                    for text in variants
                ):
                    raise ValueError
        return tuple(entries)
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("invalid booking FAQ") from None


def normalize(text):
    return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", text).casefold()).split())


def _without_courtesy(text, language):
    for _ in range(3):
        original = text
        for prefix in COURTESY[language]:
            if text.startswith(prefix + " "):
                text = text[len(prefix) + 1:]
                break
        for suffix in ("palun", "aitäh", "please", "thanks", "thank you", "пожалуйста", "спасибо"):
            if text.endswith(" " + suffix):
                text = text[:-len(suffix) - 1]
                break
        if original == text:
            break
    return text


def match_question(text, language, entries=None):
    """Only complete reviewed questions; unmatched mixed requests keep planning."""
    if language not in LANGUAGES or not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return ()
    entries = load_faq() if entries is None else entries
    lookup = {}
    for entry in entries:
        for phrase in (entry["question_" + language], *entry.get("variants_" + language, [])):
            key = normalize(phrase)
            # Ambiguous aliases must never silently pick an unrelated answer.
            if key in lookup and (lookup[key] is None or lookup[key]["id"] != entry["id"]):
                lookup[key] = None
            else:
                lookup[key] = entry
    value = _without_courtesy(normalize(text), language)
    if value in lookup:
        return (lookup[value],) if lookup[value] else ()
    parts = [part.strip(" .,!\n\t") for part in re.split(
        r"[?!;\n]+|\s+(?:ja|and|и)\s+(?=(?:kas|mis|millal|can|is|do|what|можно|есть|как|где)\b)",
        text, flags=re.I,
    ) if part.strip(" .,!\n\t")]
    # A greeting can precede questions, but an extra command must not disappear.
    if parts and normalize(parts[0]) in {"tere", "tervist", "hello", "hi", "здравствуйте", "привет"}:
        parts.pop(0)
    if not 1 <= len(parts) <= 3:
        return ()
    found = []
    for part in parts:
        value = _without_courtesy(normalize(part), language)
        entry = lookup.get(value)
        if entry is None:
            return ()
        if entry not in found:
            found.append(entry)
    return tuple(found)


def question_language(text, current, entries=None):
    """Known written questions also identify English without an STT language tag."""
    if match_question(text, current, entries=entries):
        return current
    matches = [language for language in LANGUAGES if language != current and match_question(text, language, entries=entries)]
    return matches[0] if len(matches) == 1 else current


def booking_input(text):
    """Recognize bounded planning inputs without treating every want as a booking."""
    value = normalize(text)
    if not value:
        return False
    # Month names are common short answers to a date question, including ASR
    # ordinals such as "kuuendal oktoobril". Preserve them for planning.
    if re.fullmatch(rf"(?:palun\s+)?{ESTONIAN_DATE_PATTERN}(?:\s+(?:palun|sobib))?", value, re.I):
        return True
    if re.search(r"\b(?:broneeri\w*|bruneeri\w*|book|reserve|reserving|заброниру\w*)\b", value):
        return True
    desire = re.search(
        r"\b(?:soovin|sooviks\w*|tahaks\w*|tahan|otsi|leia|find|want|need|хочу|хотел\w*|найти|найдите|ищу)\b",
        value,
    )
    entity = re.search(
        r"\b(?:(?:demo)?(?:toa\w*|tuba\w*|toad|tube|peretuba|sviit\w*)|spaa?\w*|hooldus\w*|massaa\w*|room\w*|stay|treatment\w*|massage|appointment\w*|номер\w*|спа\w*|процедур\w*|массаж\w*)\b",
        value,
    )
    if desire and entity:
        return True
    if re.fullmatch(r"[\d\s:./-]+", text.strip()):
        return True
    choices = {
        "peretuba", "aiavaatega kaheinimesetuba", "spaa sviit", "demo spaakonsultatsioon",
        "family room", "garden view double room", "spa suite", "demo spa consultation",
        "семейный номер", "двухместный номер с видом на сад", "спа люкс", "демонстрационная спа консультация",
    }
    if value in choices:
        return True
    # Additional clauses stay with planning rather than vanishing into a FAQ.
    if re.search(r"\b(?:ja|and|и)\b", value) and re.search(
        r"\b(?:täiskasvanu\w*|laps\w*|last|adults?|children|child|взрослы\w*|детей|реб[её]нка)\b",
        value,
    ):
        return True
    # Short answers to date/time/guest-count questions still reach the planner.
    count = r"(?:\d+|üks|kaks|kolm|neli|viis|kuus|one|two|three|four|five|six|один|одна|два|две|двое|три|трое|четыре|четверо)"
    people = r"(?:täiskasvanu\w*|laps\w*|last|adults?|children|child|guests?|взрослы\w*|реб[её]нок|детей|реб[её]нка|гост\w*)"
    guest_count = count + r"\s+" + people + r"(?:\s+(?:ja|and|и)\s+" + count + r"\s+" + people + r")?"
    if re.fullmatch(count, value):
        return True
    if re.fullmatch(guest_count, value):
        return True
    if any(re.fullmatch(guest_count, normalize(part)) for part in re.split(r"[?!;\n]+", text)[1:]):
        return True
    relative_day = r"(?:täna|homme|ülehomme|today|tomorrow|day after tomorrow|сегодня|завтра|послезавтра)"
    clock = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|üks|kaks|kolm|neli|viis|kuus|seitse|kaheksa|üheksa|kümme|один|два|три|четыре|пять|шесть|семь|восемь|девять|десять)(?:\s+\d+)?"
    day_part = r"(?:\s+(?:am|pm|in the morning|in the afternoon|in the evening|hommikul|päeval|õhtul|утра|дня|вечера))?"
    if re.fullmatch(r"(?:kell|at|в)\s+" + clock + r"(?:\s+часа?)?" + day_part, value):
        return True
    return bool(re.fullmatch(
        relative_day + r"(?:\s+(?:kell|at|в)\s+" + clock + day_part + r")?",
        value,
    ))


WORDS = {
    "et": {
        "rooms": "Demotoad",
        "guests": "külalist",
        "up_to": "kuni",
        "breakfast": "hommikusöök",
        "wifi": "Wi-Fi",
        "balcony": "rõdu",
        "garden": "aiavaade",
        "double": "kaheinimesevoodi",
        "extra": "lisavoodid",
        "not_verified": "Seda omadust ei ole praeguses demokataloogis kinnitatud.",
        "arrival": "Saabumine alates kell",
        "departure": "Lahkumine kuni kell",
        "local": "Tallinna kohaliku aja järgi",
        "services": "Demo spaateenused",
        "minutes": "minutit",
        "providers": "Teenindajad",
        "hours": "Spaateenuste tööajad",
        "closed": "suletud",
        "break": "paus",
        "to": "kuni kell",
        "availability": "Vabad ajad tuleb eraldi kontrollida.",
        "no_massage": "Praeguses demokataloogis massaaži ei ole."
    },
    "en": {
        "rooms": "Demo rooms",
        "guests": "guests",
        "up_to": "up to",
        "breakfast": "breakfast",
        "wifi": "Wi-Fi",
        "balcony": "balcony",
        "garden": "garden view",
        "double": "double bed",
        "extra": "extra beds",
        "not_verified": "That feature has not been verified in the current demo catalogue.",
        "arrival": "Check-in is from",
        "departure": "Check-out is by",
        "local": "Tallinn local time",
        "services": "Demo spa services",
        "minutes": "minutes",
        "providers": "Therapists",
        "hours": "Spa treatment hours",
        "closed": "closed",
        "break": "break",
        "to": "to",
        "availability": "Available appointments need a separate check.",
        "no_massage": "There is no massage service in the current demo catalogue."
    },
    "ru": {
        "rooms": "Демонстрационные номера",
        "guests": "гостей",
        "up_to": "до",
        "breakfast": "завтрак",
        "wifi": "Wi-Fi",
        "balcony": "балкон",
        "garden": "вид на сад",
        "double": "двуспальная кровать",
        "extra": "дополнительные кровати",
        "not_verified": "Эта характеристика не подтверждена в текущем демонстрационном каталоге.",
        "arrival": "Заезд с",
        "departure": "Выезд до",
        "local": "по местному времени Таллина",
        "services": "Демонстрационные спа-услуги",
        "minutes": "минут",
        "providers": "Специалисты",
        "hours": "Время работы спа-специалистов",
        "closed": "закрыто",
        "break": "перерыв",
        "to": "до",
        "availability": "Доступное время нужно проверить отдельно.",
        "no_massage": "В текущем демонстрационном каталоге нет массажа."
    }
}
DAYS = {
    "et": ("esmaspäev", "teisipäev", "kolmapäev", "neljapäev", "reede", "laupäev", "pühapäev"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "ru": ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"),
}
DAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
FEATURES = {
    "breakfast": {"hommikusöök", "breakfast", "завтрак"},
    "wifi": {"wi fi", "wifi"},
    "balcony": {"rõdu", "balcony", "балкон"},
    "garden": {"aiavaade", "garden view", "вид на сад"},
    "double": {"kaheinimesevoodi", "double bed", "двуспальная кровать"},
    "extra": {"lisavoodid", "extra beds", "дополнительные кровати"},
}


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError
    return value.strip()


def _clock(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError
    return value


def _hours(result, language, *, weekend=False):
    words, schedules = WORDS[language], []
    providers = result["providers"]
    if not isinstance(providers, list):
        raise ValueError

    def interval(value):
        start, end = _clock(value["start"]), _clock(value["end"])
        if language == "en":
            return spoken_time(start) + " to " + spoken_time(end)
        if language == "ru":
            return start + "–" + end
        return start + " " + words["to"] + " " + end

    for provider in providers[:2]:
        hours, groups = provider.get("working_hours"), {}
        if not isinstance(hours, dict):
            continue
        for index, day in enumerate(DAY_KEYS):
            if day not in hours or (weekend and index < 5):
                continue
            value = hours[day]
            summary = words["closed"] if value is None else interval(value)
            if value and value.get("breaks"):
                breaks = value["breaks"]
                if not isinstance(breaks, list) or len(breaks) > 4:
                    raise ValueError
                summary += ", " + words["break"] + " " + ", ".join(
                    interval(item) for item in breaks
                )
            groups.setdefault(summary, []).append(DAYS[language][index])
        if groups:
            schedules.append(_text(provider["name"]) + ": " + "; ".join(
                ", ".join(days) + ": " + summary for summary, days in groups.items()
            ))
    return f"{words['hours']}: " + ". ".join(schedules) + ". " + words["availability"] if schedules else None


def render_catalogue(entries, result, language):
    """Speak only the requested facts; never use the saved research snapshot."""
    if language not in LANGUAGES or not isinstance(result, dict) or result.get("error") or result.get("ok") is False:
        return None
    words, replies = WORDS[language], []
    try:
        for entry in entries:
            number = int(entry["id"].split("-")[-1])
            if entry["route"] == "stay_catalogue":
                rooms = result["room_types"]
                if not isinstance(rooms, list) or not rooms:
                    return None
                rooms = rooms[:4]
                if number == 9:
                    reply = words["rooms"] + ": " + "; ".join(_text(room["name"]) for room in rooms) + "."
                elif number in {10, 11}:
                    descriptions = []
                    for room in rooms:
                        capacity = room["capacity"]
                        if type(capacity) is not int or not 1 <= capacity <= 100:
                            return None
                        descriptions.append(f"{_text(room['name'])}: {words['up_to']} {capacity} {words['guests']}")
                    reply = "; ".join(descriptions) + ". " + ROOM_CONTEXT[language][0]
                    if number == 11:
                        reply = ROOM_CONTEXT[language][1] + " " + reply
                elif number in {13, 15, 16, 17}:
                    features = {13: ("breakfast",), 15: ("wifi",), 16: ("balcony", "garden"), 17: ("double", "extra")}[number]
                    descriptions = []
                    for room in rooms:
                        amenities = room["amenities"]
                        if not isinstance(amenities, list) or any(not isinstance(item, str) for item in amenities):
                            return None
                        values = {normalize(item) for item in amenities}
                        verified = [words[key] for key in features if values & FEATURES[key]]
                        if verified:
                            descriptions.append(_text(room["name"]) + ": " + ", ".join(verified))
                    reply = "; ".join(descriptions) + "." if descriptions else words["not_verified"]
                    if number == 17:
                        reply += " " + ROOM_CONTEXT[language][2]
                elif number in {18, 19}:
                    key, label = ("checkin_time", "arrival") if number == 18 else ("checkout_time", "departure")
                    reply = f"{words[label]} {_clock(result['property'][key])}, {words['local']}."
                else:
                    return None
            elif entry["route"] == "slot_catalogue":
                services = result["services"]
                if not isinstance(services, list) or not services:
                    return None
                if number in {22, 28}:
                    selected = services[:4]
                    if number == 28:
                        selected = [service for service in services if re.search(r"massaa\w*|massage|массаж", _text(service["name"]), re.I)][:4]
                    reply = words["services"] + ": " + "; ".join(_text(service["name"]) for service in selected) + "." if selected else words["no_massage"]
                elif number == 23:
                    descriptions = []
                    for service in services[:4]:
                        duration = service["duration"]
                        if type(duration) is not int or not 1 <= duration <= 1440:
                            return None
                        descriptions.append(f"{_text(service['name'])}: {duration} {words['minutes']}")
                    reply = "; ".join(descriptions) + "."
                elif number == 24:
                    providers = result["providers"]
                    if not isinstance(providers, list) or not providers:
                        return None
                    reply = words["providers"] + ": " + "; ".join(_text(provider["name"]) for provider in providers[:4]) + ". " + words["availability"]
                elif number in {25, 26}:
                    reply = _hours(result, language, weekend=number == 26)
                    if reply is None:
                        return None
                else:
                    return None
            else:
                return None
            if reply not in replies:
                replies.append(reply)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return " ".join(replies) if replies else None
