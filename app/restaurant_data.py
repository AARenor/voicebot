"""Validated, operator-maintained restaurant knowledge; no generated facts."""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

LANGUAGES = ("et", "en", "ru")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data/demo/restaurant-demo.json"


def _text(value, cap=1200):
    if not isinstance(value, str) or not value.strip() or len(value) > cap:
        raise ValueError("restaurant_configuration_invalid")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("restaurant_configuration_invalid")
    return value.strip()


def _translations(value):
    if not isinstance(value, dict) or set(value) != set(LANGUAGES):
        raise ValueError("restaurant_configuration_invalid")
    return {language: _text(value[language]) for language in LANGUAGES}


def load_restaurant_data(path=None):
    try:
        source = Path(path or os.environ.get("RESTAURANT_CONFIG_PATH") or DEFAULT_PATH)
        if source.stat().st_size > 100_000:
            raise ValueError()
        data = json.loads(source.read_text(encoding="utf-8"))
        if data["schema_version"] != 1 or data["synthetic"] is not True:
            raise ValueError()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", data["restaurant_id"]):
            raise ValueError()
        _text(data["name"], 100)
        ZoneInfo(data["timezone"])
        # Shared speech/calendar guards currently use Tallinn local time.
        if data["timezone"] != "Europe/Tallinn" or data["address"] is not None:
            raise ValueError()
        for field in ("description", "policies", "allergy_notice"):
            _translations(data[field])
        ranges = {
            "reservation_duration_minutes": (30, 240),
            "slot_interval_minutes": (5, 60),
            "advance_days": (1, 90),
            "maximum_party_size": (1, 20),
            "kitchen_closes_minutes_before": (0, 120),
        }
        for key, (low, high) in ranges.items():
            if type(data[key]) is not int or not low <= data[key] <= high:
                raise ValueError()
        if set(data["opening_hours"]) != set(DAYS):
            raise ValueError()
        for hours in data["opening_hours"].values():
            if hours is None:
                continue
            if set(hours) != {"start", "end"}:
                raise ValueError()
            for key in ("start", "end"):
                if not re.fullmatch(r"\d{2}:\d{2}", hours[key]):
                    raise ValueError()
                time.fromisoformat(hours[key])
            if hours["start"] >= hours["end"]:
                raise ValueError()
        if not isinstance(data["closures"], dict) or len(data["closures"]) > 366:
            raise ValueError()
        for day, reason in data["closures"].items():
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
            _translations(reason)
        tables = data["tables"]
        if not isinstance(tables, list) or not 1 <= len(tables) <= 100:
            raise ValueError()
        ids = set()
        for table in tables:
            if not re.fullmatch(r"[1-9][0-9]{0,4}", table["id"]) or table["id"] in ids:
                raise ValueError()
            ids.add(table["id"])
            _text(table["name"], 100)
            if type(table["capacity"]) is not int or not 1 <= table["capacity"] <= 20:
                raise ValueError()
        if max(table["capacity"] for table in tables) < data["maximum_party_size"]:
            raise ValueError()
        if not isinstance(data["menu"], list) or not 1 <= len(data["menu"]) <= 100:
            raise ValueError()
        menu_ids = set()
        for item in data["menu"]:
            _text(item["id"], 100)
            if item["id"] in menu_ids:
                raise ValueError()
            menu_ids.add(item["id"])
            _translations(item["name"])
            for key in ("diet", "allergens"):
                if not isinstance(item[key], list) or len(item[key]) > 20:
                    raise ValueError()
                for entry in item[key]:
                    _text(entry, 50)
            # No unsourced prices; a future connector needs approved price data.
            if item["price"] is not None:
                raise ValueError()
        return copy.deepcopy(data)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, LookupError):
        raise ValueError("restaurant_configuration_invalid") from None


def restaurant_demo_profile(data):
    """Adapt disclosed knowledge to the shared synthetic contact/consent guard."""
    from .demo import load_demo_data

    demo = load_demo_data()
    demo["profile"].update(
        name=data["name"],
        description_et=data["description"]["et"],
        description_en=data["description"]["en"],
        description_ru=data["description"]["ru"],
    )
    demo["faq"] = [
        {
            "question_et": "Kas see on päris restoran?",
            "question_en": "Is this a real restaurant?",
            "question_ru": "Это настоящий ресторан?",
            "answer_et": "See on fiktiivne restoranidemo. Broneering ei anna õigust päris restoranikülastusele.",
            "answer_en": "This is a fictional restaurant demo. A reservation does not entitle you to a real restaurant visit.",
            "answer_ru": "Это демонстрация вымышленного ресторана. Бронирование не даёт права на настоящее посещение.",
        },
        {
            "question_et": "Kus restoran asub?",
            "question_en": "Where is the restaurant?",
            "question_ru": "Где находится ресторан?",
            "answer_et": "Restoranidemol ei ole päris aadressi ega külastuskohta.",
            "answer_en": "The restaurant demo has no real address or visitor location.",
            "answer_ru": "У демонстрационного ресторана нет настоящего адреса и места для посещения.",
        },
    ]
    return demo
