"""Trusted business configuration shared by web and media workers."""

from __future__ import annotations

import os


def business_type(env=None):
    env = os.environ if env is None else env
    value = env.get("VOICEBOT_BUSINESS_TYPE", "restaurant")
    if value not in ("restaurant", "hotel_spa"):
        raise ValueError("voicebot_business_type_invalid")
    return value


def restaurant_database(env=None):
    env = os.environ if env is None else env
    return env.get("RESTAURANT_STATE_DB") or os.path.join(
        os.path.dirname(env.get("EASY_STATE_DB", "/data/easy-booking.db")),
        "restaurant-booking.db",
    )


def restaurant_writes_enabled(env=None):
    env = os.environ if env is None else env
    # Existing authorized synthetic-demo installations can migrate without
    # server access. Explicit restaurant=0 overrides the earlier demo opt-in.
    return env.get("RESTAURANT_DEMO_WRITES", env.get("EASY_DEMO_WRITES", "0")) == "1"


def restaurant_dispatcher(adapter, data):
    from .booking.tools import Dispatcher

    return Dispatcher(
        slot=adapter if adapter.operational else None,
        business_type="restaurant",
        restaurant_data=data,
    )
