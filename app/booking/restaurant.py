"""Persistent synthetic restaurant inventory shared by web and telephone.

The restaurant contract includes party size and a dining interval. SlotAdapter
is only the internal bridge to the existing owned-hold/consent machinery:
service IDs encode party size, and provider IDs identify actual dining tables.
There are no spa providers, hotel inventory, payments, or external notifications.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .base import CLOCK, Hold, SlotAdapter, UnknownQuoteError
from ..restaurant_data import DAYS, load_restaurant_data


class RestaurantAdapter(SlotAdapter):
    """Single-host SQLite table allocator; every query is restaurant-scoped."""

    business_type = "restaurant"
    HOLD_SECONDS = 120
    QUOTE_SECONDS = 120

    def __init__(self, state_db, *, data=None, allow_writes=False, now=None):
        self.data = copy.deepcopy(data) if data is not None else load_restaurant_data()
        self.restaurant_id = self.data["restaurant_id"]
        self.state_db = str(state_db)
        self.allow_writes = allow_writes is True
        self.operational = False
        self._now = now or (lambda: datetime.now(ZoneInfo(self.data["timezone"])))
        self._quotes = {}
        self._quote_lock = threading.RLock()
        if self.allow_writes:
            if self.state_db == ":memory:" or not Path(self.state_db).is_absolute():
                raise ValueError("absolute_restaurant_database_required")
            Path(self.state_db).parent.mkdir(parents=True, exist_ok=True)
            with self._connection(write=True) as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS restaurant_holds (
                        restaurant_id TEXT NOT NULL,
                        id TEXT NOT NULL,
                        slot_json TEXT NOT NULL,
                        table_id TEXT NOT NULL,
                        start_epoch REAL NOT NULL,
                        end_epoch REAL NOT NULL,
                        expires_epoch REAL NOT NULL,
                        PRIMARY KEY (restaurant_id, id)
                    );
                    CREATE INDEX IF NOT EXISTS restaurant_hold_interval
                    ON restaurant_holds (restaurant_id, table_id, start_epoch, end_epoch);
                    CREATE TABLE IF NOT EXISTS restaurant_reservations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        restaurant_id TEXT NOT NULL,
                        hold_id TEXT NOT NULL,
                        table_id TEXT NOT NULL,
                        party_size INTEGER NOT NULL,
                        start_epoch REAL NOT NULL,
                        end_epoch REAL NOT NULL,
                        start_local TEXT NOT NULL,
                        end_local TEXT NOT NULL,
                        guest_scope_hash TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled')),
                        UNIQUE (restaurant_id, hold_id)
                    );
                    CREATE INDEX IF NOT EXISTS restaurant_reservation_interval
                    ON restaurant_reservations (restaurant_id, table_id, start_epoch, end_epoch, status);
                    CREATE TABLE IF NOT EXISTS restaurant_actions (
                        restaurant_id TEXT NOT NULL,
                        key TEXT NOT NULL,
                        request_hash TEXT NOT NULL,
                        response_json TEXT NOT NULL,
                        PRIMARY KEY (restaurant_id, key)
                    );
                """
                )
            self.operational = True

    @contextmanager
    def _connection(self, *, write=False):
        connection = sqlite3.connect(self.state_db, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _validate_request(self, day, party_size):
        if (
            type(party_size) is not int
            or not 1 <= party_size <= self.data["maximum_party_size"]
        ):
            raise ValueError("restaurant_party_size_invalid")
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("restaurant_date_invalid")
        parsed = datetime.strptime(day, "%Y-%m-%d").date()
        if not 0 <= (parsed - self._now().date()).days <= self.data["advance_days"]:
            raise ValueError("restaurant_date_out_of_range")
        return parsed

    def _occupied(self, connection, table_id, start, end, *, exclude_hold=""):
        parameters = (self.restaurant_id, table_id, end, start)
        reserved = connection.execute(
            "SELECT 1 FROM restaurant_reservations WHERE restaurant_id=? AND table_id=? "
            "AND start_epoch < ? AND end_epoch > ? AND status='confirmed' LIMIT 1",
            parameters,
        ).fetchone()
        held = connection.execute(
            "SELECT 1 FROM restaurant_holds WHERE restaurant_id=? AND table_id=? "
            "AND start_epoch < ? AND end_epoch > ? AND expires_epoch > ? AND id != ? LIMIT 1",
            (*parameters, self._now().timestamp(), exclude_hold),
        ).fetchone()
        return bool(reserved or held)

    async def search_tables(self, day, party_size, table_id=None):
        return await asyncio.to_thread(self._search_tables, day, party_size, table_id)

    def _search_tables(self, day, party_size, table_id=None):
        parsed = self._validate_request(day, party_size)
        if not self.operational:
            raise ValueError("restaurant_writes_not_enabled")
        hours = self.data["opening_hours"][DAYS[parsed.weekday()]]
        if hours is None or day in self.data["closures"]:
            return []
        zone = ZoneInfo(self.data["timezone"])
        opening = datetime.fromisoformat(day + "T" + hours["start"]).replace(
            tzinfo=zone
        )
        closing = datetime.fromisoformat(day + "T" + hours["end"]).replace(tzinfo=zone)
        duration = timedelta(minutes=self.data["reservation_duration_minutes"])
        interval = timedelta(minutes=self.data["slot_interval_minutes"])
        tables = sorted(
            self.data["tables"], key=lambda table: (table["capacity"], int(table["id"]))
        )
        available = []
        with self._connection() as connection:
            start = opening
            while start + duration <= closing:
                end = start + duration
                for table in tables:
                    if (
                        table["capacity"] < party_size
                        or (table_id is not None and table["id"] != table_id)
                        or start <= self._now()
                        or self._occupied(
                            connection, table["id"], start.timestamp(), end.timestamp()
                        )
                    ):
                        continue
                    available.append(
                        {
                            "slotId": "table_" + uuid.uuid4().hex,
                            "serviceId": str(party_size),
                            "providerId": table["id"],
                            "date": day,
                            "start": start.replace(tzinfo=None).isoformat(
                                timespec="seconds"
                            ),
                            "end": end.replace(tzinfo=None).isoformat(
                                timespec="seconds"
                            ),
                            "party_size": party_size,
                            "duration_minutes": self.data[
                                "reservation_duration_minutes"
                            ],
                            "table_capacity": table["capacity"],
                            "restaurant_id": self.restaurant_id,
                        }
                    )
                start += interval
        with self._quote_lock:
            now = CLOCK()
            self._quotes = {
                key: value for key, value in self._quotes.items() if value[0] > now
            }
            for slot in available:
                self._quotes[slot["slotId"]] = (
                    now + self.QUOTE_SECONDS,
                    copy.deepcopy(slot),
                )
            while len(self._quotes) > 5000:
                self._quotes.pop(next(iter(self._quotes)))
        return available

    async def search_slots(self, service, date, provider=None):
        if not isinstance(service, str) or not re.fullmatch(r"[1-9][0-9]?", service):
            raise ValueError("restaurant_party_size_invalid")
        return await self.search_tables(
            date, int(service), None if provider in (None, "0") else provider
        )

    async def create_hold(self, slot_id):
        return await asyncio.to_thread(self._create_hold, slot_id)

    def _validate_slot_configuration(self, slot):
        """Recheck current operator rules when a previously quoted slot writes."""
        day = self._validate_request(slot["date"], slot["party_size"])
        hours = self.data["opening_hours"][DAYS[day.weekday()]]
        table = next(
            (
                table
                for table in self.data["tables"]
                if table["id"] == slot["providerId"]
            ),
            None,
        )
        if (
            hours is None
            or slot["date"] in self.data["closures"]
            or table is None
            or table["capacity"] < slot["party_size"]
        ):
            raise ValueError("restaurant_table_unavailable")
        start = datetime.fromisoformat(slot["start"])
        end = datetime.fromisoformat(slot["end"])
        opening = datetime.fromisoformat(slot["date"] + "T" + hours["start"])
        closing = datetime.fromisoformat(slot["date"] + "T" + hours["end"])
        if (
            start < opening
            or end > closing
            or end - start
            != timedelta(minutes=self.data["reservation_duration_minutes"])
        ):
            raise ValueError("restaurant_table_unavailable")
        if (start - opening).total_seconds() % (
            self.data["slot_interval_minutes"] * 60
        ):
            raise ValueError("restaurant_table_unavailable")

    def _create_hold(self, slot_id):
        with self._quote_lock:
            quote = self._quotes.get(slot_id)
            if quote is None or quote[0] <= CLOCK():
                raise UnknownQuoteError(slot_id)
            slot = copy.deepcopy(quote[1])
        self._validate_slot_configuration(slot)
        zone = ZoneInfo(self.data["timezone"])
        start = datetime.fromisoformat(slot["start"]).replace(tzinfo=zone).timestamp()
        end = datetime.fromisoformat(slot["end"]).replace(tzinfo=zone).timestamp()
        now = self._now().timestamp()
        if start <= now:
            raise ValueError("restaurant_past_datetime")
        hold_id = "restaurant_hold_" + uuid.uuid4().hex
        with self._connection(write=True) as connection:
            connection.execute(
                "DELETE FROM restaurant_holds WHERE restaurant_id=? AND expires_epoch<=?",
                (self.restaurant_id, now),
            )
            if self._occupied(connection, slot["providerId"], start, end):
                raise ValueError("restaurant_table_unavailable")
            connection.execute(
                "INSERT INTO restaurant_holds VALUES (?,?,?,?,?,?,?)",
                (
                    self.restaurant_id,
                    hold_id,
                    json.dumps(slot),
                    slot["providerId"],
                    start,
                    end,
                    now + self.HOLD_SECONDS,
                ),
            )
        return Hold(hold_id, slot_id, None, "", CLOCK() + self.HOLD_SECONDS, slot)

    async def get_hold(self, hold_id):
        return await asyncio.to_thread(self._get_hold, hold_id)

    def _get_hold(self, hold_id):
        if not self.operational:
            return None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM restaurant_holds WHERE restaurant_id=? AND id=? AND expires_epoch>?",
                (self.restaurant_id, hold_id, self._now().timestamp()),
            ).fetchone()
        if row is None:
            return None
        slot = json.loads(row["slot_json"])
        remaining = row["expires_epoch"] - self._now().timestamp()
        return Hold(
            hold_id, slot["slotId"], None, "", CLOCK() + max(0, remaining), slot
        )

    @staticmethod
    def _request_hash(action, identifier, guest_scope=""):
        return hashlib.sha256(
            json.dumps([action, identifier, guest_scope]).encode()
        ).hexdigest()

    def _replay(self, connection, key, fingerprint):
        row = connection.execute(
            "SELECT * FROM restaurant_actions WHERE restaurant_id=? AND key=?",
            (self.restaurant_id, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != fingerprint:
            return {"error": "idempotency_conflict"}
        return json.loads(row["response_json"])

    def _record(self, connection, key, fingerprint, response):
        connection.execute(
            "INSERT INTO restaurant_actions VALUES (?,?,?,?)",
            (self.restaurant_id, key, fingerprint, json.dumps(response)),
        )
        return response

    def _booking(self, row):
        return {
            "id": row["id"],
            "table_id": row["table_id"],
            "party_size": row["party_size"],
            "start": row["start_local"],
            "end": row["end_local"],
            "status": row["status"],
            "synthetic": True,
        }

    async def confirm(self, hold_id, guest, idempotency_key):
        return await asyncio.to_thread(self._confirm, hold_id, guest, idempotency_key)

    def _confirm(self, hold_id, guest, key):
        if not self.operational:
            raise ValueError("restaurant_writes_not_enabled")
        email = guest.get("email") if isinstance(guest, dict) else None
        if not isinstance(email, str) or not re.fullmatch(
            r"[a-z0-9.+_-]+@example\.invalid", email
        ):
            return {"error": "synthetic_guest_required"}
        if not isinstance(key, str) or not re.fullmatch(
            r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}", key
        ):
            return {"error": "invalid_arguments"}
        guest_scope = hashlib.sha256(email.encode()).hexdigest()
        fingerprint = self._request_hash("confirm", hold_id, guest_scope)
        with self._connection(write=True) as connection:
            replay = self._replay(connection, key, fingerprint)
            if replay is not None:
                return replay
            existing = connection.execute(
                "SELECT * FROM restaurant_reservations WHERE restaurant_id=? AND hold_id=?",
                (self.restaurant_id, hold_id),
            ).fetchone()
            if existing is not None:
                if existing["guest_scope_hash"] != guest_scope:
                    return {"error": "not_owned"}
                if existing["status"] == "cancelled":
                    return {"error": "already_cancelled"}
                return self._record(
                    connection,
                    key,
                    fingerprint,
                    {"ok": True, "booking": self._booking(existing)},
                )
            hold = connection.execute(
                "SELECT * FROM restaurant_holds WHERE restaurant_id=? AND id=?",
                (self.restaurant_id, hold_id),
            ).fetchone()
            if hold is None or hold["expires_epoch"] <= self._now().timestamp():
                return {"error": "hold_expired_or_unknown"}
            if hold["start_epoch"] <= self._now().timestamp():
                return {"error": "past_datetime"}
            if self._occupied(
                connection,
                hold["table_id"],
                hold["start_epoch"],
                hold["end_epoch"],
                exclude_hold=hold_id,
            ):
                return {"error": "slot_unavailable"}
            slot = json.loads(hold["slot_json"])
            try:
                self._validate_slot_configuration(slot)
            except ValueError:
                return {"error": "slot_unavailable"}
            connection.execute(
                "INSERT INTO restaurant_reservations (restaurant_id,hold_id,table_id,party_size,start_epoch,end_epoch,start_local,end_local,guest_scope_hash,status) VALUES (?,?,?,?,?,?,?,?,?,'confirmed')",
                (
                    self.restaurant_id,
                    hold_id,
                    hold["table_id"],
                    slot["party_size"],
                    hold["start_epoch"],
                    hold["end_epoch"],
                    slot["start"],
                    slot["end"],
                    guest_scope,
                ),
            )
            row = connection.execute(
                "SELECT * FROM restaurant_reservations WHERE restaurant_id=? AND hold_id=?",
                (self.restaurant_id, hold_id),
            ).fetchone()
            connection.execute(
                "DELETE FROM restaurant_holds WHERE restaurant_id=? AND id=?",
                (self.restaurant_id, hold_id),
            )
            return self._record(
                connection,
                key,
                fingerprint,
                {"ok": True, "booking": self._booking(row)},
            )

    async def cancel(self, booking_id, idempotency_key):
        return await asyncio.to_thread(self._cancel, booking_id, idempotency_key)

    def _cancel(self, booking_id, key):
        if not self.operational:
            raise ValueError("restaurant_writes_not_enabled")
        if (
            not isinstance(booking_id, str)
            or not booking_id.isascii()
            or not booking_id.isdigit()
        ):
            return {"error": "invalid_arguments"}
        if not isinstance(key, str) or not re.fullmatch(
            r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}", key
        ):
            return {"error": "invalid_arguments"}
        fingerprint = self._request_hash("cancel", booking_id)
        with self._connection(write=True) as connection:
            replay = self._replay(connection, key, fingerprint)
            if replay is not None:
                return replay
            row = connection.execute(
                "SELECT * FROM restaurant_reservations WHERE restaurant_id=? AND id=?",
                (self.restaurant_id, booking_id),
            ).fetchone()
            if row is None:
                return {"error": "booking_unknown"}
            connection.execute(
                "UPDATE restaurant_reservations SET status='cancelled' WHERE restaurant_id=? AND id=?",
                (self.restaurant_id, booking_id),
            )
            return self._record(
                connection,
                key,
                fingerprint,
                {"ok": True, "booking_id": booking_id, "status": "cancelled"},
            )

    async def get_slot_catalogue(self):
        return {
            "synthetic": True,
            "business_type": "restaurant",
            "restaurant": copy.deepcopy(self.data),
            "services": [
                {
                    "id": str(party),
                    "name": f"Table for {party}",
                    "duration": self.data["reservation_duration_minutes"],
                }
                for party in range(1, self.data["maximum_party_size"] + 1)
            ],
            "providers": [
                {
                    "id": table["id"],
                    "name": table["name"],
                    "capacity": table["capacity"],
                    "working_hours": copy.deepcopy(self.data["opening_hours"]),
                }
                for table in self.data["tables"]
            ],
        }

    async def get_operator_catalogue(self):
        return {
            "source": "restaurant",
            "data_mode": "synthetic",
            **await self.get_slot_catalogue(),
        }

    async def get_operator_bookings(self, date, *, page=1, length=50):
        return await asyncio.to_thread(self._operator_bookings, date, page, length)

    def _operator_bookings(self, day, page, length):
        rows = []
        if Path(self.state_db).is_file():
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM restaurant_reservations WHERE restaurant_id=? AND substr(start_local,1,10)=? ORDER BY start_local,id LIMIT ? OFFSET ?",
                    (self.restaurant_id, day, length, (page - 1) * length),
                ).fetchall()
        table_names = {table["id"]: table["name"] for table in self.data["tables"]}
        return {
            "source": "restaurant",
            "data_mode": "synthetic",
            "fetched_at": self._now().isoformat(),
            "date": day,
            "page": page,
            "length": length,
            "has_more": "unknown" if len(rows) == length else False,
            "items": [
                {
                    "id": row["id"],
                    "start_local": row["start_local"],
                    "end_local": row["end_local"],
                    "timezone": self.data["timezone"],
                    "time_state": "valid",
                    "provider_id": int(row["table_id"]),
                    "provider_name": table_names.get(row["table_id"], "Table"),
                    "service_id": row["party_size"],
                    "service_name": f"Table for {row['party_size']}",
                    "status": row["status"],
                }
                for row in rows
            ],
        }

    async def close(self):
        with self._quote_lock:
            self._quotes.clear()
