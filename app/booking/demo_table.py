"""Durable physical-table inventory for a disclosed fictional restaurant.

SQLite holds allocate one table atomically; only confirmed reservations and
unexpired holds occupy it. No real restaurant, payment or notification is used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .base import Hold, UnknownQuoteError
from ..demo import load_demo_data
from ..providers.errors import ProviderError


DEMO_VENUE = {
    "name": "Meretuule restoran",
    "timezone": "Europe/Tallinn",
    "address": None,
    "real_visitor_location": False,
    "notice": "Fiktiivne restoran. Testbroneering ei anna õigust päris restoranikülastusele. Makseid ei koguta.",
}
TABLES = tuple(
    {"id": f"table-{i:02d}", "name": f"Laud {i}", "capacity": capacity}
    for i, capacity in enumerate((2, 2, 4, 4, 6), 1)
)
RULES = {
    "opening_time": "12:00",
    "closing_time": "22:00",
    "duration_minutes": 120,
    "horizon_days": 90,
    "min_party_size": 1,
    "max_party_size": 6,
    "children_count_toward_party_size": True,
    "combine_tables": False,
}
MENU = (
    {
        "name_et": "Roheline salat",
        "description_et": "Fiktiivne eelroa näidis, mitte päris toidu tellimine.",
        "name_en": "Green salad",
        "description_en": "A fictional starter example, not a real food order.",
        "name_ru": "Зелёный салат",
        "description_ru": "Вымышленный пример закуски, не настоящий заказ еды.",
    },
    {
        "name_et": "Ahjuköögiviljad",
        "description_et": "Fiktiivne pearoa näidis. Koostist ega allergeeniohutust ei kinnitata.",
        "name_en": "Roasted vegetables",
        "description_en": "A fictional main-course example. Ingredients and allergen safety are not verified.",
        "name_ru": "Запечённые овощи",
        "description_ru": "Вымышленный пример основного блюда. Состав и безопасность при аллергии не подтверждены.",
    },
    {
        "name_et": "Marjamagustoit",
        "description_et": "Fiktiivne magustoidu näidis. Selle demo kaudu ei võeta vastu tellimusi ega makseid.",
        "name_en": "Berry dessert",
        "description_en": "A fictional dessert example. This demo accepts no food orders or payments.",
        "name_ru": "Ягодный десерт",
        "description_ru": "Вымышленный пример десерта. Эта демонстрация не принимает заказы еды или оплату.",
    },
)


def _identifier(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[a-f0-9]{32}", value):
        raise ProviderError("demo_table: invalid identifier")
    return value


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[\w][\w.-]{0,127}", value):
        raise ProviderError("demo_table: invalid idempotency key")
    return value


class DemoTableAdapter:
    """One concrete restaurant backend, shared through its own persistent DB."""

    operational = True

    def __init__(self, state_db: str, *, hold_ttl_seconds=600, offer_ttl_seconds=600):
        if not isinstance(state_db, str) or not state_db or state_db == ":memory:":
            raise ValueError("persistent demo restaurant database path required")
        if any(
            type(ttl) is not int or not 1 <= ttl <= 3600
            for ttl in (hold_ttl_seconds, offer_ttl_seconds)
        ):
            raise ValueError(
                "demo restaurant TTL must be an integer between 1 and 3600 seconds"
            )
        self._path = os.path.abspath(state_db)
        self._hold_ttl = hold_ttl_seconds
        self._offer_ttl = offer_ttl_seconds
        self._guests = load_demo_data(
            Path(__file__).resolve().parents[2] / "data/demo/restaurant-demo.json"
        )["guests"]
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS restaurant_tables (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    capacity INTEGER NOT NULL CHECK(capacity >= 1), active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS table_offers (
                    id TEXT PRIMARY KEY, date TEXT NOT NULL, start_time TEXT NOT NULL,
                    start TEXT NOT NULL, end TEXT NOT NULL, party_size INTEGER NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS table_holds (
                    id TEXT PRIMARY KEY, offer_id TEXT NOT NULL, table_id TEXT NOT NULL,
                    table_name TEXT NOT NULL, capacity INTEGER NOT NULL,
                    expires_at REAL NOT NULL, status TEXT NOT NULL,
                    FOREIGN KEY(offer_id) REFERENCES table_offers(id),
                    FOREIGN KEY(table_id) REFERENCES restaurant_tables(id)
                );
                CREATE TABLE IF NOT EXISTS table_bookings (
                    id TEXT PRIMARY KEY, hold_id TEXT UNIQUE NOT NULL,
                    table_id TEXT NOT NULL, table_name TEXT NOT NULL, capacity INTEGER NOT NULL,
                    date TEXT NOT NULL, start_time TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                    party_size INTEGER NOT NULL, guest_name TEXT NOT NULL,
                    status TEXT NOT NULL, created_at REAL NOT NULL,
                    FOREIGN KEY(hold_id) REFERENCES table_holds(id),
                    FOREIGN KEY(table_id) REFERENCES restaurant_tables(id)
                );
                CREATE TABLE IF NOT EXISTS table_writes (
                    key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS table_booking_intervals
                    ON table_bookings(table_id,status,start,end);
                CREATE INDEX IF NOT EXISTS table_hold_expiry
                    ON table_holds(table_id,status,expires_at);
                CREATE INDEX IF NOT EXISTS table_hold_offer ON table_holds(offer_id);
            """)
            for table in TABLES:
                db.execute(
                    "INSERT OR IGNORE INTO restaurant_tables(id,name,capacity) VALUES(?,?,?)",
                    (table["id"], table["name"], table["capacity"]),
                )

    def __repr__(self):
        return "DemoTableAdapter(synthetic=True)"

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self._path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    async def _run(self, call, *args):
        try:
            return await asyncio.to_thread(call, *args)
        except sqlite3.Error:
            raise ProviderError("demo_table: database unavailable") from None

    @staticmethod
    def _request(day, start_time, party_size, now):
        if type(party_size) is not int or not 1 <= party_size <= 6:
            raise ProviderError("demo_table: invalid party size")
        try:
            if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise ValueError
            if not isinstance(start_time, str) or not re.fullmatch(
                r"\d{2}:\d{2}", start_time
            ):
                raise ValueError
            requested = date.fromisoformat(day)
            naive = datetime.fromisoformat(day + "T" + start_time)
        except (TypeError, ValueError):
            raise ProviderError("demo_table: invalid date or time") from None
        zone = ZoneInfo(DEMO_VENUE["timezone"])
        today = datetime.fromtimestamp(now, zone).date()
        if not today <= requested <= today + timedelta(days=RULES["horizon_days"]):
            raise ProviderError("demo_table: requested time is outside future horizon")
        start = naive.replace(tzinfo=zone, fold=0)
        if (
            start.utcoffset() != naive.replace(tzinfo=zone, fold=1).utcoffset()
            or start.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
            != naive
        ):
            raise ProviderError("demo_table: invalid or ambiguous local time")
        if start.timestamp() <= now:
            raise ProviderError("demo_table: requested time is outside future horizon")
        end = (
            start.astimezone(timezone.utc)
            + timedelta(minutes=RULES["duration_minutes"])
        ).astimezone(zone)
        if (
            start_time < RULES["opening_time"]
            or end.date() != requested
            or end.strftime("%H:%M") > RULES["closing_time"]
        ):
            raise ProviderError("demo_table: sitting is outside opening hours")
        return start.isoformat(), end.isoformat()

    @staticmethod
    def _free_tables(db, start, end, party_size, now, *, exclude_hold=""):
        return db.execute(
            "SELECT t.id AS table_id,t.name AS table_name,t.capacity FROM restaurant_tables t"
            " WHERE t.active=1 AND t.capacity >= ?"
            " AND NOT EXISTS(SELECT 1 FROM table_bookings b WHERE b.table_id=t.id"
            " AND b.status='confirmed' AND julianday(b.start) < julianday(?) AND julianday(b.end) > julianday(?))"
            " AND NOT EXISTS(SELECT 1 FROM table_holds h JOIN table_offers o ON o.id=h.offer_id"
            " WHERE h.table_id=t.id AND h.status='held' AND h.expires_at > ? AND h.id != ?"
            " AND julianday(o.start) < julianday(?) AND julianday(o.end) > julianday(?))"
            " ORDER BY t.capacity,t.id",
            (party_size, end, start, now, exclude_hold, end, start),
        ).fetchall()

    @staticmethod
    def _details(row):
        return {
            "kind": "table",
            "venue_name": DEMO_VENUE["name"],
            "timezone": DEMO_VENUE["timezone"],
            "date": row["date"],
            "start_time": row["start_time"],
            "end_time": datetime.fromisoformat(row["end"]).strftime("%H:%M"),
            "start": row["start"],
            "end": row["end"],
            "party_size": row["party_size"],
            "duration_minutes": RULES["duration_minutes"],
            "table_id": row["table_id"],
            "table_name": row["table_name"],
            "capacity": row["capacity"],
            "quoted_total": None,
        }

    async def get_table_catalogue(self):
        return await self._run(self._catalogue)

    def _catalogue(self):
        with self._connect() as db:
            tables = db.execute(
                "SELECT id,name,capacity FROM restaurant_tables WHERE active=1 ORDER BY capacity,id"
            ).fetchall()
        return {
            "synthetic": True,
            "source": "demo_table",
            "venue": dict(DEMO_VENUE),
            "tables": [dict(table) for table in tables],
            "rules": dict(RULES),
            "menu": [dict(item) for item in MENU],
        }

    async def search_tables(self, date, start_time, party_size):
        return await self._run(self._search, date, start_time, party_size)

    def _search(self, day, start_time, party_size):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            start, end = self._request(day, start_time, party_size, now)
            db.execute(
                "DELETE FROM table_offers WHERE expires_at <= ?"
                " AND id NOT IN (SELECT offer_id FROM table_holds)",
                (now,),
            )
            free = self._free_tables(db, start, end, party_size, now)
            if not free:
                return []
            offer_id = "table_offer_" + uuid.uuid4().hex
            expires = now + self._offer_ttl
            db.execute(
                "INSERT INTO table_offers VALUES(?,?,?,?,?,?,?)",
                (offer_id, day, start_time, start, end, party_size, expires),
            )
            details = self._details(
                {
                    "date": day,
                    "start_time": start_time,
                    "start": start,
                    "end": end,
                    "party_size": party_size,
                    **dict(free[0]),
                }
            )
            return [
                {
                    **details,
                    "table_offer_id": offer_id,
                    "synthetic": True,
                    "source": "demo_table",
                    "expires_at": datetime.fromtimestamp(
                        expires, timezone.utc
                    ).isoformat(),
                }
            ]

    def _hold(self, db, row):
        offer = db.execute(
            "SELECT * FROM table_offers WHERE id=?", (row["offer_id"],)
        ).fetchone()
        recap = self._details(
            {
                **dict(offer),
                "table_id": row["table_id"],
                "table_name": row["table_name"],
                "capacity": row["capacity"],
            }
        )
        return Hold(
            row["id"],
            row["offer_id"],
            None,
            "EUR",
            time.monotonic() + max(0, row["expires_at"] - time.time()),
            {
                "kind": "table",
                "recap": recap,
                "table_offer_id": row["offer_id"],
                "expires_at": datetime.fromtimestamp(
                    row["expires_at"], timezone.utc
                ).isoformat(),
                "synthetic": True,
                "source": "demo_table",
            },
        )

    async def create_hold(self, table_offer_id):
        _identifier(table_offer_id, "table_offer")
        return await self._run(self._create_hold, table_offer_id)

    def _create_hold(self, offer_id):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            offer = db.execute(
                "SELECT * FROM table_offers WHERE id=?", (offer_id,)
            ).fetchone()
            if offer is None or offer["expires_at"] <= now:
                raise UnknownQuoteError(offer_id)
            if self._request(
                offer["date"], offer["start_time"], offer["party_size"], now
            ) != (offer["start"], offer["end"]):
                raise ProviderError("demo_table: offer changed")
            existing = db.execute(
                "SELECT * FROM table_holds WHERE offer_id=? ORDER BY rowid DESC LIMIT 1",
                (offer_id,),
            ).fetchone()
            if existing and existing["status"] == "confirmed":
                raise ProviderError("demo_table: offer already booked")
            if (
                existing
                and existing["status"] == "held"
                and existing["expires_at"] > now
            ):
                return self._hold(db, existing)
            free = self._free_tables(
                db, offer["start"], offer["end"], offer["party_size"], now
            )
            if not free:
                raise ProviderError("demo_table: table unavailable")
            table = free[0]
            hold_id = "hold_" + uuid.uuid4().hex
            expires = min(now + self._hold_ttl, offer["expires_at"])
            db.execute(
                "INSERT INTO table_holds VALUES(?,?,?,?,?,?,?)",
                (
                    hold_id,
                    offer_id,
                    table["table_id"],
                    table["table_name"],
                    table["capacity"],
                    expires,
                    "held",
                ),
            )
            return self._hold(
                db,
                db.execute(
                    "SELECT * FROM table_holds WHERE id=?", (hold_id,)
                ).fetchone(),
            )

    async def get_hold(self, hold_id):
        _identifier(hold_id, "hold")
        return await self._run(self._get_hold, hold_id)

    def _get_hold(self, hold_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM table_holds WHERE id=?", (hold_id,)
            ).fetchone()
            if (
                row is None
                or row["status"] != "held"
                or row["expires_at"] <= time.time()
            ):
                return None
            return self._hold(db, row)

    def _guest(self, guest):
        if not isinstance(guest, dict) or set(guest) != {
            "firstName",
            "lastName",
            "email",
            "phone",
        }:
            raise ProviderError("demo_table: approved fictional guest required")
        if any(
            not isinstance(v, str) or not v.strip() or len(v) > 160
            for v in guest.values()
        ):
            raise ProviderError("demo_table: approved fictional guest required")
        for fixture in self._guests.values():
            local = fixture["email"].split("@")[0]
            if all(
                guest[k] == fixture[k] for k in ("firstName", "lastName", "phone")
            ) and re.fullmatch(
                re.escape(local) + r"(?:\+[A-Za-z0-9_-]{8,48})?@example\.invalid",
                guest["email"],
            ):
                return f"{fixture['firstName']} {fixture['lastName']}"
        raise ProviderError("demo_table: approved fictional guest required")

    @staticmethod
    def _replay(db, key, fingerprint):
        row = db.execute("SELECT * FROM table_writes WHERE key=?", (key,)).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                return {"ok": False, "error": "idempotency_conflict"}
            return json.loads(row["result"])
        return None

    @staticmethod
    def _record(db, key, fingerprint, result):
        db.execute(
            "INSERT INTO table_writes VALUES(?,?,?)",
            (key, fingerprint, json.dumps(result, ensure_ascii=False)),
        )
        return result

    def _booking(self, row):
        return {
            **self._details(row),
            "id": row["id"],
            "status": row["status"],
            "guest_name": row["guest_name"],
            "synthetic": True,
        }

    async def confirm(self, hold_id, guest, idempotency_key):
        _identifier(hold_id, "hold")
        _key(idempotency_key)
        guest_name = self._guest(guest)
        fingerprint = hashlib.sha256(
            json.dumps(["confirm", hold_id, guest], sort_keys=True).encode()
        ).hexdigest()
        return await self._run(
            self._confirm, hold_id, guest_name, idempotency_key, fingerprint
        )

    def _confirm(self, hold_id, guest_name, key, fingerprint):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            replay = self._replay(db, key, fingerprint)
            if replay is not None:
                return replay
            row = db.execute(
                "SELECT h.*,o.date,o.start_time,o.start,o.end,o.party_size,"
                "t.active,t.capacity AS current_capacity,t.name AS current_name FROM table_holds h"
                " JOIN table_offers o ON o.id=h.offer_id JOIN restaurant_tables t ON t.id=h.table_id WHERE h.id=?",
                (hold_id,),
            ).fetchone()
            if row is None or row["status"] != "held" or row["expires_at"] <= now:
                return self._record(
                    db,
                    key,
                    fingerprint,
                    {"ok": False, "error": "hold_expired_or_unknown"},
                )
            try:
                if self._request(
                    row["date"], row["start_time"], row["party_size"], now
                ) != (row["start"], row["end"]):
                    raise ProviderError("demo_table: offer changed")
            except ProviderError:
                return self._record(
                    db,
                    key,
                    fingerprint,
                    {"ok": False, "error": "table_request_expired"},
                )
            free = self._free_tables(
                db,
                row["start"],
                row["end"],
                row["party_size"],
                now,
                exclude_hold=hold_id,
            )
            if (
                not row["active"]
                or row["capacity"] != row["current_capacity"]
                or row["table_name"] != row["current_name"]
                or row["table_id"] not in {t["table_id"] for t in free}
            ):
                return self._record(
                    db, key, fingerprint, {"ok": False, "error": "table_unavailable"}
                )
            booking_id = "table_" + uuid.uuid4().hex
            db.execute(
                "INSERT INTO table_bookings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    booking_id,
                    hold_id,
                    row["table_id"],
                    row["table_name"],
                    row["capacity"],
                    row["date"],
                    row["start_time"],
                    row["start"],
                    row["end"],
                    row["party_size"],
                    guest_name,
                    "confirmed",
                    now,
                ),
            )
            db.execute(
                "UPDATE table_holds SET status='confirmed' WHERE id=?", (hold_id,)
            )
            booking = self._booking(
                db.execute(
                    "SELECT * FROM table_bookings WHERE id=?", (booking_id,)
                ).fetchone()
            )
            return self._record(
                db,
                key,
                fingerprint,
                {
                    "ok": True,
                    "kind": "table",
                    "synthetic": True,
                    "source": "demo_table",
                    "booking_id": booking_id,
                    "booking": booking,
                },
            )

    async def cancel(self, booking_id, idempotency_key):
        _identifier(booking_id, "table")
        _key(idempotency_key)
        fingerprint = hashlib.sha256(("cancel:" + booking_id).encode()).hexdigest()
        return await self._run(self._cancel, booking_id, idempotency_key, fingerprint)

    def _cancel(self, booking_id, key, fingerprint):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = self._replay(db, key, fingerprint)
            if replay is not None:
                return replay
            row = db.execute(
                "SELECT id FROM table_bookings WHERE id=?", (booking_id,)
            ).fetchone()
            if row is None:
                return self._record(
                    db, key, fingerprint, {"ok": False, "error": "booking_not_found"}
                )
            db.execute(
                "UPDATE table_bookings SET status='cancelled' WHERE id=?", (booking_id,)
            )
            return self._record(
                db,
                key,
                fingerprint,
                {
                    "ok": True,
                    "kind": "table",
                    "synthetic": True,
                    "source": "demo_table",
                    "booking_id": booking_id,
                    "status": "cancelled",
                },
            )

    async def get_operator_bookings(self, date=None):
        if date is not None:
            try:
                if (
                    not isinstance(date, str)
                    or datetime.strptime(date, "%Y-%m-%d").date().isoformat() != date
                ):
                    raise ValueError
            except (ValueError, TypeError):
                raise ProviderError("demo_table: invalid booking date") from None
        return await self._run(self._bookings, date)

    def _bookings(self, day):
        with self._connect() as db:
            records = db.execute(
                "SELECT * FROM table_bookings WHERE (? IS NULL OR date=?)"
                " ORDER BY status='confirmed' DESC,start,created_at DESC,id LIMIT 201",
                (day, day),
            ).fetchall()
        return {
            "source": "demo_table",
            "synthetic": True,
            "kind": "table",
            "date": day,
            "items": [self._booking(row) for row in records[:200]],
            "truncated": len(records) > 200,
        }
