"""Persistent, finite room inventory for the disclosed fictional hotel demo.

This is a local demo PMS, not a connection to a real hotel. SQLite transactions
reserve an individual room for an exclusive, expiring hold and atomically turn
that hold into a booking. Quotes, writes and idempotency survive restarts. No
payment, email, phone call or notification is sent.
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
from zoneinfo import ZoneInfo

from .base import Hold, StayAdapter, UnknownQuoteError
from ..providers.errors import ProviderError

DEMO_PROPERTY = {
    "name": "Meretuule Demo Spa",
    "timezone": "Europe/Tallinn",
    "checkin_time": "15:00",
    "checkout_time": "12:00",
    "notice": "Fiktiivne hotell ja spaa. Testbroneering ei anna õigust päris majutusele. Makseid ei koguta.",
}
ROOM_TYPES = (
    {
        "id": "garden-double",
        "name": "Aiavaatega kaheinimesetuba",
        "description": "Rahulik näidistuba kahele, aiavaade ja suur kaheinimesevoodi.",
        "capacity": 2,
        "inventory": 6,
        "nightly_cents": 12900,
        "amenities": ["Aiavaade", "Kaheinimesevoodi", "Hommikusöök", "Wi-Fi"],
    },
    {
        "id": "spa-suite",
        "name": "Spaa sviit",
        "description": "Avar näidissviit puhkenurga ja rõduga kahele külalisele.",
        "capacity": 2,
        "inventory": 2,
        "nightly_cents": 19900,
        "amenities": ["Rõdu", "Puhkenurk", "Hommikusöök", "Wi-Fi"],
    },
    {
        "id": "family-room",
        "name": "Peretuba",
        "description": "Näidistuba kuni neljale külalisele, kaheinimesevoodi ja lisavoodid.",
        "capacity": 4,
        "inventory": 3,
        "nightly_cents": 16900,
        "amenities": ["Lisavoodid", "Puhkenurk", "Hommikusöök", "Wi-Fi"],
    },
)


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _identifier(value: str, prefix: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[a-f0-9]{32}", value):
        raise ProviderError("demo_stay: invalid identifier")
    return value


def _key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[\w][\w.-]{0,127}", value):
        raise ProviderError("demo_stay: invalid idempotency key")
    return value


class DemoStayAdapter(StayAdapter):
    """A tested local StayAdapter; inventory is shared through a durable DB."""

    operational = True

    def __init__(self, state_db: str, *, hold_ttl_seconds=600, quote_ttl_seconds=600):
        if not isinstance(state_db, str) or not state_db or state_db == ":memory:":
            raise ValueError("persistent demo stay database path required")
        if not 1 <= hold_ttl_seconds <= 3600 or not 1 <= quote_ttl_seconds <= 3600:
            raise ValueError("demo stay TTL must be between 1 and 3600 seconds")
        self._path = os.path.abspath(state_db)
        self._hold_ttl = hold_ttl_seconds
        self._quote_ttl = quote_ttl_seconds
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS stay_room_types (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                    capacity INTEGER NOT NULL, nightly_cents INTEGER NOT NULL,
                    amenities TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS stay_rooms (
                    id TEXT PRIMARY KEY, room_type_id TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(room_type_id) REFERENCES stay_room_types(id)
                );
                CREATE TABLE IF NOT EXISTS stay_quotes (
                    id TEXT PRIMARY KEY, room_type_id TEXT NOT NULL,
                    checkin TEXT NOT NULL, checkout TEXT NOT NULL,
                    adults INTEGER NOT NULL, children INTEGER NOT NULL,
                    total_cents INTEGER NOT NULL, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stay_holds (
                    id TEXT PRIMARY KEY, quote_id TEXT NOT NULL, room_id TEXT NOT NULL,
                    expires_at REAL NOT NULL, status TEXT NOT NULL,
                    FOREIGN KEY(quote_id) REFERENCES stay_quotes(id)
                );
                CREATE TABLE IF NOT EXISTS stay_bookings (
                    id TEXT PRIMARY KEY, hold_id TEXT UNIQUE NOT NULL,
                    room_id TEXT NOT NULL, room_type_id TEXT NOT NULL,
                    room_name TEXT NOT NULL, checkin TEXT NOT NULL, checkout TEXT NOT NULL,
                    adults INTEGER NOT NULL, children INTEGER NOT NULL,
                    total_cents INTEGER NOT NULL, guest_name TEXT NOT NULL,
                    status TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stay_writes (
                    key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS stay_booking_dates
                    ON stay_bookings(room_id, status, checkin, checkout);
                CREATE INDEX IF NOT EXISTS stay_hold_expiry
                    ON stay_holds(room_id, status, expires_at);
            """)
            for room in ROOM_TYPES:
                db.execute(
                    "INSERT OR IGNORE INTO stay_room_types"
                    "(id,name,description,capacity,nightly_cents,amenities) VALUES(?,?,?,?,?,?)",
                    (room["id"], room["name"], room["description"], room["capacity"],
                     room["nightly_cents"], json.dumps(room["amenities"], ensure_ascii=False)),
                )
                for index in range(room["inventory"]):
                    db.execute(
                        "INSERT OR IGNORE INTO stay_rooms(id,room_type_id) VALUES(?,?)",
                        (f"{room['id']}-{index + 1:02d}", room["id"]),
                    )

    def __repr__(self):
        return "DemoStayAdapter(synthetic=True)"

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
            raise ProviderError("demo_stay: database unavailable") from None

    @staticmethod
    def _dates(checkin, checkout):
        try:
            start, end = date.fromisoformat(checkin), date.fromisoformat(checkout)
            if start.isoformat() != checkin or end.isoformat() != checkout:
                raise ValueError
            today = datetime.now(ZoneInfo(DEMO_PROPERTY["timezone"])).date()
            if not today <= start <= today + timedelta(days=730):
                raise ValueError
            if not 1 <= (end - start).days <= 30:
                raise ValueError
        except (ValueError, TypeError):
            raise ProviderError("demo_stay: invalid stay dates") from None
        return start, end

    @staticmethod
    def _party(party):
        if not isinstance(party, dict):
            raise ProviderError("demo_stay: invalid occupancy")
        adults, children = party.get("adults", 2), party.get("children", 0)
        if type(adults) is not int or not 1 <= adults <= 10:
            raise ProviderError("demo_stay: invalid occupancy")
        if type(children) is not int or not 0 <= children <= 8:
            raise ProviderError("demo_stay: invalid occupancy")
        room_type = party.get("room_type") or ""
        if not isinstance(room_type, str) or len(room_type) > 80:
            raise ProviderError("demo_stay: invalid room type")
        return adults, children, room_type

    @staticmethod
    def _free_rooms(db, room_type, checkin, checkout, now, *, exclude_hold=""):
        return db.execute(
            "SELECT r.id FROM stay_rooms r WHERE r.room_type_id=? AND r.active=1"
            " AND NOT EXISTS(SELECT 1 FROM stay_bookings b WHERE b.room_id=r.id"
            " AND b.status='confirmed' AND b.checkin < ? AND b.checkout > ?)"
            " AND NOT EXISTS(SELECT 1 FROM stay_holds h JOIN stay_quotes q ON q.id=h.quote_id"
            " WHERE h.room_id=r.id AND h.status='held' AND h.expires_at > ? AND h.id != ?"
            " AND q.checkin < ? AND q.checkout > ?) ORDER BY r.id",
            (room_type, checkout, checkin, now, exclude_hold, checkout, checkin),
        ).fetchall()

    async def get_stay_catalogue(self):
        return await self._run(self._catalogue)

    def _catalogue(self):
        with self._connect() as db:
            records = db.execute(
                "SELECT t.*, COUNT(r.id) AS inventory FROM stay_room_types t"
                " LEFT JOIN stay_rooms r ON r.room_type_id=t.id AND r.active=1"
                " WHERE t.active=1 GROUP BY t.id ORDER BY t.nightly_cents,t.id"
            ).fetchall()
        return {
            "synthetic": True, "source": "demo_stay", "property": dict(DEMO_PROPERTY),
            "room_types": [
                {"id": r["id"], "name": r["name"], "description": r["description"],
                 "capacity": r["capacity"], "inventory": r["inventory"],
                 "amenities": json.loads(r["amenities"]), "currency": "EUR"}
                for r in records
            ],
        }

    async def search_availability(self, checkin, checkout, party):
        start, end = self._dates(checkin, checkout)
        adults, children, room_type = self._party(party)
        return await self._run(self._search, checkin, checkout, (end - start).days,
                               adults, children, room_type)

    def _search(self, checkin, checkout, nights, adults, children, room_type):
        now, offers = time.time(), []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Expired unreferenced quotes need no durable history.
            db.execute("DELETE FROM stay_quotes WHERE expires_at < ?"
                       " AND id NOT IN (SELECT quote_id FROM stay_holds)", (now,))
            room_types = db.execute(
                "SELECT * FROM stay_room_types WHERE active=1 AND capacity >= ?"
                " AND (?='' OR id=?) ORDER BY nightly_cents,id",
                (adults + children, room_type, room_type),
            ).fetchall()
            for room in room_types:
                free = self._free_rooms(db, room["id"], checkin, checkout, now)
                if not free:
                    continue
                quote_id = "quote_" + uuid.uuid4().hex
                cents = room["nightly_cents"] * nights
                db.execute("INSERT INTO stay_quotes VALUES(?,?,?,?,?,?,?,?)",
                           (quote_id, room["id"], checkin, checkout, adults, children,
                            cents, now + self._quote_ttl))
                offers.append({
                    "price_quote_id": quote_id, "room_type_id": room["id"],
                    "label": room["name"], "checkin": checkin, "checkout": checkout,
                    "nights": nights, "adults": adults, "children": children,
                    "available_rooms": len(free), "quoted_total": _money(cents),
                    "currency": "EUR", "synthetic": True, "source": "demo_stay",
                    "expires_at": datetime.fromtimestamp(now + self._quote_ttl, timezone.utc).isoformat(),
                })
        return offers

    def _hold(self, db, row):
        quote = db.execute(
            "SELECT q.*,t.name FROM stay_quotes q JOIN stay_room_types t"
            " ON t.id=q.room_type_id WHERE q.id=?", (row["quote_id"],)
        ).fetchone()
        recap = {
            "room_type_id": quote["room_type_id"], "room_name": quote["name"],
            "checkin": quote["checkin"], "checkout": quote["checkout"],
            "nights": (date.fromisoformat(quote["checkout"]) - date.fromisoformat(quote["checkin"])).days,
            "adults": quote["adults"], "children": quote["children"],
            "quoted_total": _money(quote["total_cents"]), "currency": "EUR",
            "timezone": DEMO_PROPERTY["timezone"],
        }
        return Hold(row["id"], row["quote_id"], recap["quoted_total"], "EUR",
                    time.monotonic() + max(0, row["expires_at"] - time.time()),
                    {"recap": recap, "synthetic": True, "source": "demo_stay"})

    async def create_hold(self, price_quote_id):
        _identifier(price_quote_id, "quote")
        return await self._run(self._create_hold, price_quote_id)

    def _create_hold(self, quote_id):
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            quote = db.execute(
                "SELECT q.*,t.active,t.capacity FROM stay_quotes q JOIN stay_room_types t"
                " ON t.id=q.room_type_id WHERE q.id=?", (quote_id,)
            ).fetchone()
            if quote is None or quote["expires_at"] <= now or not quote["active"]:
                raise UnknownQuoteError(quote_id)
            self._dates(quote["checkin"], quote["checkout"])
            if quote["capacity"] < quote["adults"] + quote["children"]:
                raise ProviderError("demo_stay: occupancy changed")
            existing = db.execute(
                "SELECT * FROM stay_holds WHERE quote_id=? ORDER BY expires_at DESC LIMIT 1",
                (quote_id,),
            ).fetchone()
            if existing and existing["status"] == "held" and existing["expires_at"] > now:
                return self._hold(db, existing)
            if existing and existing["status"] == "confirmed":
                raise ProviderError("demo_stay: quote already booked")
            free = self._free_rooms(db, quote["room_type_id"], quote["checkin"], quote["checkout"], now)
            if not free:
                raise ProviderError("demo_stay: room unavailable")
            hold_id = "hold_" + uuid.uuid4().hex
            expires = min(now + self._hold_ttl, quote["expires_at"])
            db.execute("INSERT INTO stay_holds VALUES(?,?,?,?,?)",
                       (hold_id, quote_id, free[0]["id"], expires, "held"))
            row = db.execute("SELECT * FROM stay_holds WHERE id=?", (hold_id,)).fetchone()
            return self._hold(db, row)

    async def get_hold(self, hold_id):
        _identifier(hold_id, "hold")
        return await self._run(self._get_hold, hold_id)

    def _get_hold(self, hold_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM stay_holds WHERE id=?", (hold_id,)).fetchone()
            if row is None or row["status"] != "held" or row["expires_at"] <= time.time():
                return None
            return self._hold(db, row)

    @staticmethod
    def _guest(guest):
        if not isinstance(guest, dict):
            raise ProviderError("demo_stay: fictional guest required")
        first, last, email = (guest.get(k) for k in ("firstName", "lastName", "email"))
        if any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in (first, last, email)):
            raise ProviderError("demo_stay: fictional guest required")
        if not re.fullmatch(r"demo\.[a-z]+(?:\+[A-Za-z0-9_-]{8,48})?@example\.invalid", email):
            raise ProviderError("demo_stay: fictional guest required")
        return f"{first.strip()} {last.strip()}", email

    @staticmethod
    def _replay(db, key, fingerprint):
        row = db.execute("SELECT * FROM stay_writes WHERE key=?", (key,)).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                return {"ok": False, "error": "idempotency_conflict"}
            return json.loads(row["result"])
        return None

    @staticmethod
    def _record(db, key, fingerprint, result):
        db.execute("INSERT INTO stay_writes VALUES(?,?,?)",
                   (key, fingerprint, json.dumps(result, ensure_ascii=False)))
        return result

    @staticmethod
    def _booking(row):
        return {
            "id": row["id"], "status": row["status"], "room_type_id": row["room_type_id"],
            "room_name": row["room_name"], "checkin": row["checkin"], "checkout": row["checkout"],
            "nights": (date.fromisoformat(row["checkout"]) - date.fromisoformat(row["checkin"])).days,
            "adults": row["adults"], "children": row["children"],
            "quoted_total": _money(row["total_cents"]), "currency": "EUR",
            "guest_name": row["guest_name"], "synthetic": True,
        }

    async def confirm(self, hold_id, guest, idempotency_key):
        _identifier(hold_id, "hold")
        _key(idempotency_key)
        guest_name, email = self._guest(guest)
        fingerprint = hashlib.sha256(json.dumps(["confirm", hold_id, guest_name, email]).encode()).hexdigest()
        return await self._run(self._confirm, hold_id, guest_name, idempotency_key, fingerprint)

    def _confirm(self, hold_id, guest_name, key, fingerprint):
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = self._replay(db, key, fingerprint)
            if replay is not None:
                return replay
            row = db.execute(
                "SELECT h.*,q.room_type_id,q.checkin,q.checkout,q.adults,q.children,q.total_cents,"
                "t.name,t.nightly_cents,t.active,t.capacity FROM stay_holds h"
                " JOIN stay_quotes q ON q.id=h.quote_id JOIN stay_room_types t ON t.id=q.room_type_id"
                " WHERE h.id=?", (hold_id,),
            ).fetchone()
            if row is None or row["status"] != "held" or row["expires_at"] <= now:
                return self._record(db, key, fingerprint, {"ok": False, "error": "hold_expired_or_unknown"})
            try:
                self._dates(row["checkin"], row["checkout"])
            except ProviderError:
                return self._record(db, key, fingerprint, {"ok": False, "error": "stay_dates_expired"})
            nights = (date.fromisoformat(row["checkout"]) - date.fromisoformat(row["checkin"])).days
            if not row["active"] or row["capacity"] < row["adults"] + row["children"]:
                return self._record(db, key, fingerprint, {"ok": False, "error": "room_unavailable"})
            if row["nightly_cents"] * nights != row["total_cents"]:
                return self._record(db, key, fingerprint, {"ok": False, "error": "price_changed"})
            free = self._free_rooms(db, row["room_type_id"], row["checkin"], row["checkout"], now,
                                    exclude_hold=hold_id)
            if row["room_id"] not in {r["id"] for r in free}:
                return self._record(db, key, fingerprint, {"ok": False, "error": "room_unavailable"})
            booking_id = "stay_" + uuid.uuid4().hex
            db.execute("INSERT INTO stay_bookings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (booking_id, hold_id, row["room_id"], row["room_type_id"], row["name"],
                        row["checkin"], row["checkout"], row["adults"], row["children"],
                        row["total_cents"], guest_name, "confirmed", now,))
            db.execute("UPDATE stay_holds SET status='confirmed' WHERE id=?", (hold_id,))
            booking = self._booking(db.execute("SELECT * FROM stay_bookings WHERE id=?", (booking_id,)).fetchone())
            return self._record(db, key, fingerprint,
                                {"ok": True, "synthetic": True, "booking_id": booking_id, "booking": booking})

    async def cancel(self, booking_id, idempotency_key):
        _identifier(booking_id, "stay")
        _key(idempotency_key)
        fingerprint = hashlib.sha256(("cancel:" + booking_id).encode()).hexdigest()
        return await self._run(self._cancel, booking_id, idempotency_key, fingerprint)

    def _cancel(self, booking_id, key, fingerprint):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = self._replay(db, key, fingerprint)
            if replay is not None:
                return replay
            row = db.execute("SELECT id FROM stay_bookings WHERE id=?", (booking_id,)).fetchone()
            if not row:
                return self._record(db, key, fingerprint, {"ok": False, "error": "booking_not_found"})
            db.execute("UPDATE stay_bookings SET status='cancelled' WHERE id=?", (booking_id,))
            return self._record(db, key, fingerprint,
                                {"ok": True, "synthetic": True, "booking_id": booking_id, "status": "cancelled"})

    async def get_operator_bookings(self, day=None):
        if day is not None:
            try:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError
            except (ValueError, TypeError):
                raise ProviderError("demo_stay: invalid booking date") from None
        return await self._run(self._bookings, day)

    def _bookings(self, day):
        with self._connect() as db:
            records = db.execute(
                "SELECT * FROM stay_bookings WHERE (? IS NULL OR (checkin <= ? AND checkout > ?))"
                " ORDER BY checkin,created_at,id LIMIT 200", (day, day, day),
            ).fetchall()
        return {"source": "demo_stay", "synthetic": True, "date": day,
                "items": [self._booking(row) for row in records]}
