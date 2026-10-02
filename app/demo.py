"""Approved fictional demo data, never installation IDs or availability."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEMO_PATH = Path(__file__).resolve().parents[1] / "data/demo/telephone-demo.json"
DEMO_TIMEZONE = "Europe/Tallinn"


def _text(value, cap=500):
    if not isinstance(value, str) or not value.strip() or len(value) > cap:
        raise ValueError("invalid synthetic demo data")
    return value.strip()


def validate_call_id(value):
    # Bound both the email local part and the adapter's 128-character write key.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,48}", value):
        raise ValueError("invalid call scope")
    return value


def load_demo_data(path=None):
    """Read only the disclosed profile, FAQ and reserved fictional contacts."""
    try:
        source = json.loads(Path(path or DEMO_PATH).read_text(encoding="utf-8"))
        if (
            source["schema_version"] != 1
            or source["synthetic"] is not True
            or source["automatic_import"] is not False
            or any(
                source["safety"].get(flag) is not False
                for flag in (
                    "send_notifications",
                    "make_outbound_calls",
                    "collect_payments",
                    "speak_prices",
                )
            )
        ):
            raise ValueError
        profile = source["fictional_property"]
        if (
            profile.get("address") is not None
            or profile.get("real_visitor_location") is not False
            or profile.get("timezone") != DEMO_TIMEZONE
            or profile.get("language") != "et"
        ):
            raise ValueError
        profile = {
            "name": _text(profile["name"], 100),
            "description_et": _text(profile["description_et"]),
            "language": "et",
            "timezone": DEMO_TIMEZONE,
            "address": None,
            "real_visitor_location": False,
        }
        faq = [
            {
                "question_et": _text(entry["question_et"]),
                "answer_et": _text(entry["answer_et"]),
            }
            for entry in source["manual_demo_faq"]["entries"]
        ]
        guests = {}
        for entry in source["guests"]:
            fixture_id = _text(entry["fixture_id"], 40)
            guest = entry["guest"]
            if (
                not re.fullmatch(r"guest-\d{3}", fixture_id)
                or fixture_id in guests
                or set(guest) != {"firstName", "lastName", "email", "phone"}
                or not re.fullmatch(r"[a-z0-9.]+@example\.invalid", guest["email"])
                or not re.fullmatch(r"\+120255501\d{2}", guest["phone"])
            ):
                raise ValueError
            guests[fixture_id] = {
                key: _text(value, 100) for key, value in guest.items()
            }
        if "guest-001" not in guests or not faq:
            raise ValueError
        return {"synthetic": True, "profile": profile, "faq": faq, "guests": guests}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("invalid synthetic demo data") from None


def scoped_guest(data, fixture_id, call_id):
    """Bind a saved fixture to a trusted call scope, never to model contacts."""
    validate_call_id(call_id)
    guest = copy.deepcopy(data["guests"][fixture_id])
    local, domain = guest["email"].split("@")
    guest["email"] = f"{local}+{call_id}@{domain}"
    return guest


def get_demo_profile(data=None, *, call_id, now=None):
    data = load_demo_data() if data is None else data
    validate_call_id(call_id)
    now = datetime.now(ZoneInfo(DEMO_TIMEZONE)) if now is None else now
    return {
        "synthetic": True,
        "call_id": call_id,
        "current_date": now.astimezone(ZoneInfo(DEMO_TIMEZONE)).date().isoformat(),
        "timezone": DEMO_TIMEZONE,
        "profile": copy.deepcopy(data["profile"]),
        "faq": copy.deepcopy(data["faq"]),
        "guest_fixtures": [
            {
                "fixture_id": fixture_id,
                "name": f"{guest['firstName']} {guest['lastName']}",
                "guest": scoped_guest(data, fixture_id, call_id),
            }
            for fixture_id, guest in data["guests"].items()
        ],
        "availability_source": "Query the actual booking backend; demo data does not prove availability.",
    }
