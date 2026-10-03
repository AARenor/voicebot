"""Easy!Appointments controlled demo REST adapter (SlotAdapter, spa only).

GPL-3.0. Shapes below follow the real openapi.yml v1.0.0 (fetched
2026-09-30 from github.com/alextselegidis/easyappointments):
  GET /availabilities?providerId&serviceId&date -> 200: string[] (times)
  GET /services -> 200: ServiceRecord[] ({id, name, duration, price, ...})
  GET /providers -> 200: ProviderRecord[] ({id, firstName, services, ...})
  GET /appointments -> 200: AppointmentRecord[] (reconciliation read/filter)
  POST /appointments (AppointmentPayload) -> 201: AppointmentRecord
  DELETE /appointments/{id} -> 204 (404 treated as success: idempotent)
  AppointmentPayload: {start, end, customerId, providerId, serviceId,
    notes?, status?, location?}; CustomerPayload: {firstName, lastName,
    email?, phone?, ...}; ServiceRecord: {id, duration (min), price, ...}
  Auth: BearerToken OR BasicAuth per spec.
Single-resource slots — never rooms. Self-host per property.
Auth scheme + API prefix are constructor params: VERIFY both against the
property's openapi.yml at deploy (defaults match upstream layout).

Safety (spec 2026-10-01): upstream 1.6.0 REST creation does NOT reject
overlaps, so this demo is the sole booking writer. Writes serialize across
adapter instances/processes via a file lock next to the SQLite journal,
recheck remote availability inside the lock, and record a durable pending
row (deterministic opaque marker in notes) BEFORE the single POST. A key
that is pending stays fail-closed: reconcile via GET /appointments exact
marker match, never a blind second POST — even after restart or timeout.
The journal stores minimal customer/booking IDs and outcomes, never guest fields.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import date as calendar_date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .base import Hold, HoldLedger, SlotAdapter, UnknownQuoteError
from ..providers.errors import (
    ProviderError,
    RetryableProviderError,
    raise_for_provider,
)

DEFAULT_STATE_DB = "/data/easy-booking.db"


class BookingReadError(Exception):
    """Closed operator-read failure; never carries upstream bodies or URLs."""

    def __init__(self, code="booking_payload_invalid", status=502, retry_after=None):
        super().__init__(code)
        self.code, self.status, self.retry_after = code, status, retry_after


def _read_id(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,14}", str(value)):
        raise BookingReadError()
    return int(value)


def _read_text(value, limit=200):
    if not isinstance(value, str) or len(value) > limit:
        raise BookingReadError()
    return value


def _wall_time(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?", value
    ):
        raise BookingReadError()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise BookingReadError() from None


def _time_state(local, zone):
    """Round-trip both folds; expose gaps/folds without inventing an instant."""
    if zone is None:
        return "unknown_timezone"
    instants = set()
    for fold in (0, 1):
        instant = local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) == local:
            instants.add(instant)
    return "invalid" if not instants else "ambiguous" if len(instants) > 1 else "valid"


def _require_key(value, where: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ProviderError(f"{where}: bad idempotency_key")
    return value


def _clean_error(error: str) -> str:
    """Strip backend body echoes from recorded errors (journal PII rule).

    Typed messages from this module carry no guest data, but PMS error
    bodies may echo the submitted payload — never persist that.
    """
    return str(error).split(" body=", 1)[0][:300]


def _parse_start(value: str):
    """Accept our slot format with or without seconds (API emits both)."""
    from datetime import datetime

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except (ValueError, TypeError):
            continue
    raise ProviderError(f"easy.confirm: bad start: {value!r}")


def _required_int(value, name: str) -> int:
    try:
        return int(str(value))
    except (ValueError, TypeError) as exc:
        raise ProviderError(f"easy.confirm: bad {name}: {exc}") from exc


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return _required_int(value, "providerId")


def _path_segment(value: str) -> str:
    """Booking ids are int-like per AppointmentRecord; reject path junk."""
    if not str(value).isdigit():
        raise ProviderError(f"easy.cancel: bad booking_id: {value!r}")
    return str(value)


def _is_int_like(value) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return int(str(value)) > 0
    except (ValueError, TypeError):
        return False


def _working_hours(record):
    """Allowlist the provider's current working plan; missing is unknown."""
    settings = record.get("settings")
    if not isinstance(settings, dict):
        return None
    plan = settings.get("workingPlan")
    if isinstance(plan, str):
        try:
            plan = json.loads(plan) if len(plan) <= 16000 else None
        except ValueError:
            return None
    if not isinstance(plan, dict):
        return None
    days = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    hours = {}
    try:
        for day in days:
            if day not in plan:
                return None
            value = plan[day]
            if value is None:
                hours[day] = None
                continue
            if not isinstance(value, dict):
                return None
            start, end = value["start"], value["end"]
            if (
                any(
                    not isinstance(v, str)
                    or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", v)
                    for v in (start, end)
                )
                or end <= start
            ):
                return None
            breaks = value.get("breaks", [])
            if not isinstance(breaks, list) or len(breaks) > 6:
                return None
            clean_breaks = []
            for pause in breaks:
                pause_start, pause_end = pause["start"], pause["end"]
                if (
                    any(
                        not isinstance(v, str)
                        or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", v)
                        for v in (pause_start, pause_end)
                    )
                    or not start <= pause_start < pause_end <= end
                ):
                    return None
                clean_breaks.append({"start": pause_start, "end": pause_end})
            clean_breaks.sort(key=lambda pause: (pause["start"], pause["end"]))
            if any(
                previous["end"] > following["start"]
                for previous, following in zip(clean_breaks, clean_breaks[1:])
            ):
                return None
            hours[day] = {"start": start, "end": end, "breaks": clean_breaks}
    except (KeyError, TypeError):
        return None
    return hours


class _Journal:
    """Durable idempotency journal (SQLite). No guest PII stored."""

    def __init__(self, path: str) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._path = path
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS easy_writes("
                "idempotency_key TEXT PRIMARY KEY, status TEXT NOT NULL,"
                " marker TEXT NOT NULL, booking_id TEXT,"
                " result TEXT, updated_at REAL NOT NULL)"
            )
            conn.commit()

    @contextmanager
    def _connect(self):
        # Connection.__exit__ commits/rolls back but does not close the handle.
        # Close deterministically so repeat reads do not leak descriptors or
        # retain Windows file locks after a temporary journal is finished.
        conn = sqlite3.connect(self._path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, marker, booking_id, result, updated_at"
                " FROM easy_writes WHERE idempotency_key=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        status, marker, booking_id, result, updated_at = row
        parsed = None
        if result:
            try:
                parsed = json.loads(result)
            except ValueError:
                parsed = None
        return {
            "status": status,
            "marker": marker,
            "booking_id": booking_id,
            "result": parsed,
            "updated_at": updated_at,
        }

    def put_pending(self, key: str, marker: str) -> None:
        self.put_result(key, marker, "pending_appointment", None, None)

    def pending_appointments(self, exclude: str) -> list[tuple[str, str]]:
        """Unresolved appointment writes besides `exclude` (global block)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT idempotency_key, marker FROM easy_writes"
                " WHERE status LIKE 'pending%' AND idempotency_key != ?",
                (exclude,),
            ).fetchall()
        return [(str(k), str(m)) for k, m in rows]

    def put_result(
        self,
        key: str,
        marker: str,
        status: str,
        booking_id: str | None,
        result: dict | None,
    ) -> None:
        now = time.time()
        blob = json.dumps(result) if result is not None else None
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO easy_writes(idempotency_key, status, marker,"
                " booking_id, result, updated_at) VALUES(?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(idempotency_key) DO UPDATE SET status=?,"
                " marker=?, booking_id=?, result=?, updated_at=?",
                (
                    key,
                    status,
                    marker,
                    booking_id,
                    blob,
                    now,
                    status,
                    marker,
                    booking_id,
                    blob,
                    now,
                ),
            )
            conn.commit()


def _acquire_lock(lock_path: str, timeout: float):
    """Blocking file-lock acquisition (run via to_thread, never on loop)."""
    import errno

    parent = os.path.dirname(os.path.abspath(lock_path))
    os.makedirs(parent, exist_ok=True)
    handle = open(lock_path, "a+b")
    if os.name == "nt":
        import msvcrt

        # Windows locks a byte range rather than the entire file. Every writer
        # uses byte zero; closing the returned handle releases that lock.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
    else:
        import fcntl
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return handle
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("easy.confirm: lock busy")
                time.sleep(0.05)
    except Exception:
        handle.close()
        raise


class EasyAppointmentsAdapter(SlotAdapter):
    operational = False  # opt in via allow_writes (demo-write gate)

    def __init__(
        self,
        base_url: str,
        api_key: str,
        auth_scheme: str = "Bearer ",
        api_prefix: str = "/index.php/api/v1",
        transport: httpx.BaseTransport | None = None,
        state_db: str | None = None,
        allow_writes: bool = False,
        lock_timeout: float = 10.0,
    ) -> None:
        self._base = base_url.rstrip("/") + api_prefix
        self._key = api_key
        self._holds = HoldLedger()
        self._slots: dict[str, dict] = {}  # slot_id -> slot snapshot
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"{auth_scheme}{api_key}"},
            timeout=30.0,
            transport=transport,
        )
        # Read capability must not depend on writable disk or open a journal.
        self._journal = (
            _Journal(state_db or os.environ.get("EASY_STATE_DB", DEFAULT_STATE_DB))
            if allow_writes
            else None
        )
        self._lock_path = self._journal._path + ".lock" if self._journal else None
        self._lock_timeout = lock_timeout
        self._write_lock = asyncio.Lock()  # in-process sibling of the file lock
        self._catalog_cache: dict | None = None
        self._catalog_at = 0.0
        # Instance-gated: credentials alone never advertise booking tools.
        self.operational = bool(allow_writes)

    def __repr__(self) -> str:
        return "EasyAppointmentsAdapter(redacted)"

    async def close(self) -> None:
        await self._http.aclose()

    # -- private operator projection (not part of SlotAdapter) ---------
    async def _operator_records(self, suffix, params, limit):
        try:
            response = await self._http.get(f"{self._base}{suffix}", params=params)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            raise BookingReadError("booking_provider_timeout", 504) from None
        except (httpx.HTTPError, OSError):
            raise BookingReadError("booking_provider_unavailable", 503) from None
        if response.status_code == 429 or response.status_code >= 500:
            try:
                retry = min(60, max(1, int(response.headers.get("Retry-After", "30"))))
            except ValueError:
                retry = 30
            raise BookingReadError("booking_provider_unavailable", 503, retry)
        if response.status_code != 200:
            raise BookingReadError("booking_provider_rejected", 502)
        try:
            rows = response.json()
        except ValueError:
            raise BookingReadError() from None
        if not isinstance(rows, list) or len(rows) > limit:
            raise BookingReadError()
        return rows

    async def get_operator_catalogue(self):
        """Fixed, bounded read fields; omit prices and all customer metadata."""
        services_raw = await self._operator_records(
            "/services",
            {
                "fields": "id,name,duration",
                "sort": "+id",
                "page": 1,
                "length": 100,
            },
            100,
        )
        providers_raw = await self._operator_records(
            "/providers",
            {
                "fields": "id,firstName,lastName,services,timezone",
                "sort": "+id",
                "page": 1,
                "length": 100,
            },
            100,
        )
        services, providers = [], []
        try:
            for record in services_raw:
                duration = _read_id(record["duration"])
                if duration > 1440:
                    raise BookingReadError()
                services.append(
                    {
                        "id": _read_id(record["id"]),
                        "name": _read_text(record["name"]),
                        "duration": duration,
                    }
                )
            for record in providers_raw:
                raw_zone = record.get("timezone")
                try:
                    zone = (
                        ZoneInfo(raw_zone)
                        if isinstance(raw_zone, str) and len(raw_zone) <= 100
                        else None
                    )
                except (ValueError, ZoneInfoNotFoundError):
                    zone = None
                offered = record["services"]
                if not isinstance(offered, list) or len(offered) > 100:
                    raise BookingReadError()
                providers.append(
                    {
                        "id": _read_id(record["id"]),
                        "name": (
                            _read_text(record["firstName"])
                            + " "
                            + _read_text(record.get("lastName", ""))
                        ).strip(),
                        "services": [_read_id(s) for s in offered],
                        "timezone": zone.key if zone else None,
                    }
                )
        except (KeyError, TypeError, AttributeError):
            raise BookingReadError() from None
        if len({s["id"] for s in services}) != len(services) or len(
            {p["id"] for p in providers}
        ) != len(providers):
            raise BookingReadError()
        return {
            "source": "easyappointments",
            "data_mode": "synthetic",
            "services": services,
            "providers": providers,
        }

    async def get_operator_bookings(self, day, *, page=1, length=50):
        try:
            if (
                not isinstance(day, str)
                or calendar_date.fromisoformat(day).isoformat() != day
            ):
                raise ValueError()
            if (
                type(page) is not int
                or not 1 <= page <= 100
                or type(length) is not int
                or not 1 <= length <= 50
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise BookingReadError("booking_query_invalid", 400) from None
        records = await self._operator_records(
            "/appointments",
            {
                "date": day,
                "page": page,
                "length": length,
                "sort": "+start,+id",
                "fields": "id,start,end,status,serviceId,providerId",
            },
            length,
        )
        catalogue = await self.get_operator_catalogue()
        services = {s["id"]: s for s in catalogue["services"]}
        providers = {p["id"]: p for p in catalogue["providers"]}
        items, seen = [], set()
        try:
            for record in records:
                rid = _read_id(record["id"])
                service = services[_read_id(record["serviceId"])]
                provider = providers[_read_id(record["providerId"])]
                start, end = _wall_time(record["start"]), _wall_time(record["end"])
                if (
                    rid in seen
                    or end <= start
                    or start.date().isoformat() != day
                    or service["id"] not in provider["services"]
                ):
                    raise BookingReadError()
                seen.add(rid)
                zone = ZoneInfo(provider["timezone"]) if provider["timezone"] else None
                states = {_time_state(t, zone) for t in (start, end)}
                time_state = next(
                    (
                        s
                        for s in ("unknown_timezone", "invalid", "ambiguous")
                        if s in states
                    ),
                    "valid",
                )
                items.append(
                    {
                        "id": rid,
                        "start_local": start.isoformat(sep=" "),
                        "end_local": end.isoformat(sep=" "),
                        "timezone": provider["timezone"],
                        "time_state": time_state,
                        "provider_id": provider["id"],
                        "provider_name": provider["name"],
                        "service_id": service["id"],
                        "service_name": service["name"],
                        "status": _read_text(record["status"], 80),
                    }
                )
        except (KeyError, TypeError, AttributeError):
            raise BookingReadError() from None
        return {
            "source": "easyappointments",
            "data_mode": "synthetic",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "date": day,
            "page": page,
            "length": length,
            "has_more": "unknown" if len(items) == length else False,
            "items": items,
        }

    # -- catalogue ----------------------------------------------------
    async def _get(self, suffix: str, params: dict | None = None):
        try:
            return await self._http.get(f"{self._base}{suffix}", params=params)
        except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
            raise RetryableProviderError(
                f"easy: transport: {type(exc).__name__}"
            ) from exc

    def _marker(self, idempotency_key: str) -> str:
        digest = hashlib.sha256(f"{self._base}|{idempotency_key}".encode()).hexdigest()[
            :16
        ]
        return f"vb-{digest}"

    async def _catalogue(self) -> dict:
        now = time.monotonic()
        if self._catalog_cache is not None and now - self._catalog_at < 300:
            return self._catalog_cache
        services_resp = await self._get("/services")
        raise_for_provider(services_resp, "easy.catalogue.services")
        providers_resp = await self._get("/providers")
        raise_for_provider(providers_resp, "easy.catalogue.providers")
        try:
            services = services_resp.json()
            providers = providers_resp.json()
            if isinstance(services, dict) and "data" in services:
                services = services["data"]
            if isinstance(providers, dict) and "data" in providers:
                providers = providers["data"]
            if not isinstance(services, list) or not isinstance(providers, list):
                raise ProviderError("easy.catalogue: bad payload")
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"easy.catalogue: bad payload: {exc}") from exc
        catalog = {"services": services, "providers": providers}
        self._catalog_cache = catalog
        self._catalog_at = now
        return catalog

    async def get_slot_catalogue(self) -> dict:
        """Read-only service/provider catalogue (model never invents IDs)."""
        catalog = await self._catalogue()
        services = []
        for record in catalog["services"]:
            if not isinstance(record, dict):
                continue
            try:
                sid = int(record["id"])
            except (KeyError, ValueError, TypeError):
                continue
            services.append(
                {
                    "id": sid,
                    "name": str(record.get("name", "")),
                    "duration": record.get("duration"),
                    "price": record.get("price"),
                    "currency": record.get("currency", "EUR"),
                }
            )
        providers = []
        for record in catalog["providers"]:
            if not isinstance(record, dict):
                continue
            try:
                pid = int(record["id"])
            except (KeyError, ValueError, TypeError):
                continue
            name = str(
                record.get("name", "")
                or " ".join(
                    str(record.get(k, "")).strip() for k in ("firstName", "lastName")
                ).strip()
            )
            provider = {"id": pid, "name": name, "services": record.get("services")}
            hours = _working_hours(record)
            if hours is not None:
                provider["working_hours"] = hours
                provider["timezone"] = record.get("timezone", "Europe/Tallinn")
            providers.append(provider)
        return {"services": services, "providers": providers}

    def _match_name(self, records: list, value: str, keys: tuple) -> str | None:
        wanted = str(value).strip().lower()
        for record in records:
            if not isinstance(record, dict):
                continue
            candidates = []
            for key in keys:
                text = str(record.get(key, "")).strip().lower()
                if text:
                    candidates.append(text)
            # Full "firstName lastName" display names are searchable too.
            full = (
                (
                    str(record.get("firstName", "")).strip()
                    + " "
                    + str(record.get("lastName", "")).strip()
                )
                .strip()
                .lower()
            )
            if full:
                candidates.append(full)
            if wanted in candidates:
                try:
                    return str(int(record["id"]))
                except (KeyError, ValueError, TypeError):
                    continue
        return None

    async def _resolve_ids(
        self, service: str, provider: str | None
    ) -> tuple[str, str | None]:
        service_id: str | None = None
        provider_id: str | None = None
        if _is_int_like(service):
            service_id = str(int(str(service)))
        if provider is not None and _is_int_like(provider):
            provider_id = str(int(str(provider)))
        if service_id is not None and (provider is None or provider_id is not None):
            if provider_id is not None:
                # Strict compatibility: an unreadable catalogue, an unknown
                # provider id, or a missing/invalid services list is a closed
                # failure — never a silent pass.
                catalog = await self._catalogue()
                if not self._provider_compatible(catalog, provider_id, service_id):
                    raise ProviderError("easy.search_slots: provider cannot do service")
            return service_id, provider_id
        # Name resolution via official catalogue (no invention).
        catalog = await self._catalogue()
        if service_id is None:
            resolved = self._match_name(catalog["services"], service, ("name",))
            if resolved is None:
                raise ProviderError(f"easy.search_slots: unknown service: {service!r}")
            service_id = resolved
        if provider is not None and provider_id is None:
            resolved = self._match_name(
                catalog["providers"],
                provider,
                ("name", "firstName", "lastName", "email"),
            )
            if resolved is None:
                raise ProviderError(
                    f"easy.search_slots: unknown provider: {provider!r}"
                )
            provider_id = resolved
        if provider_id is not None and not self._provider_compatible(
            catalog, provider_id, service_id
        ):
            raise ProviderError("easy.search_slots: provider cannot do service")
        return service_id, provider_id

    @staticmethod
    def _provider_compatible(catalog: dict, provider_id: str, service_id: str) -> bool:
        for record in catalog["providers"]:
            if not isinstance(record, dict):
                continue
            try:
                if str(int(record["id"])) != provider_id:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            offered = record.get("services")
            if not isinstance(offered, list):
                return False  # missing/invalid constraint: fail closed
            try:
                return str(int(service_id)) in {str(int(s)) for s in offered}
            except (ValueError, TypeError):
                return False
        return False  # unknown provider id: fail closed

    # -- slots --------------------------------------------------------
    async def search_slots(
        self, service: str, date: str, provider: str | None = None
    ) -> list[dict]:
        from datetime import datetime

        if not isinstance(service, str) or not service.strip():
            raise ProviderError("easy.search_slots: bad service")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except (ValueError, TypeError) as exc:
            raise ProviderError(f"easy.search_slots: bad date: {exc}") from exc
        service_id, provider_id = await self._resolve_ids(service, provider)
        params: dict = {"serviceId": service_id, "date": date}
        if provider_id is not None:
            params["providerId"] = provider_id
        response = await self._get("/availabilities", params=params)
        raise_for_provider(response, "easy.search_slots")
        try:
            times = response.json()
            if isinstance(times, dict) and "data" in times:
                times = times["data"]  # defensive envelope unwrap
            if not isinstance(times, list):
                raise ProviderError(
                    f"easy.search_slots: bad payload: {type(times).__name__}"
                )
            slots = []
            for t in times:
                start = f"{date} {t}" if " " not in str(t) else str(t)
                # '|' separator: service ids are integer-like, never contain
                # it; empty provider stays empty (no '-' collision).
                slot_id = f"{service_id}|{provider_id or ''}|{start}"
                slot = {
                    "slotId": slot_id,
                    "serviceId": service_id,
                    "providerId": provider_id,
                    "date": date,
                    "start": start,
                }
                self._slots[slot_id] = slot
                slots.append(slot)
            return slots
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"easy.search_slots: bad payload: {exc}") from exc

    async def _ensure_customer(self, guest: dict) -> int:
        """Use explicit ID or this adapter's verified exact-guest creation."""
        if guest.get("customerId") is not None:
            return _required_int(guest.get("customerId"), "customerId")
        body = {
            "firstName": guest.get("firstName", ""),
            "lastName": guest.get("lastName", ""),
            "email": guest.get("email", ""),
            "phone": guest.get("phone", ""),
        }
        # Call-scoped email and all clean fields must match. Explicit IDs never
        # seed this bounded, memory-only proof of our own successful creation.
        customer_key = (
            "created-customer:"
            + hashlib.sha256(
                json.dumps([self._base, body], sort_keys=True).encode()
            ).hexdigest()
        )
        customer_id = self._holds.get_memo(customer_key, "created_customerId")
        if customer_id is not None:
            return customer_id
        try:
            response = await self._http.post(f"{self._base}/customers", json=body)
        except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
            raise RetryableProviderError(
                f"easy.ensure_customer: {type(exc).__name__}"
            ) from exc
        raise_for_provider(response, "easy.ensure_customer")
        if response.status_code != 201:
            raise RetryableProviderError("easy.ensure_customer: completion unverified")
        try:
            customer_id = response.json()["id"]
            if not _is_int_like(customer_id):
                raise ValueError("invalid id")
            customer_id = int(customer_id)
            self._holds.memo(customer_key, "created_customerId", customer_id)
            return customer_id
        except (KeyError, ValueError, TypeError):
            # A malformed successful write may already have committed. Do not
            # persist a conversion error containing backend-controlled data.
            raise RetryableProviderError(
                "easy.ensure_customer: malformed response"
            ) from None

    async def _service_duration(self, service_id: str) -> int:
        try:
            response = await self._http.get(f"{self._base}/services/{service_id}")
        except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
            raise RetryableProviderError(f"easy.service: {type(exc).__name__}") from exc
        raise_for_provider(response, "easy.service")
        try:
            return int(response.json()["duration"])
        except (KeyError, ValueError, TypeError):
            raise ProviderError("easy.service: bad payload") from None

    async def _availability_times(
        self, service_id: str, provider_id: str | None, date: str
    ) -> list[str]:
        params: dict = {"serviceId": service_id, "date": date}
        if provider_id is not None:
            params["providerId"] = provider_id
        response = await self._get("/availabilities", params=params)
        raise_for_provider(response, "easy.confirm.recheck")
        try:
            times = response.json()
            if isinstance(times, dict) and "data" in times:
                times = times["data"]
            if not isinstance(times, list):
                raise ProviderError("easy.confirm.recheck: bad payload")
            return [f"{date} {t}" if " " not in str(t) else str(t) for t in times]
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"easy.confirm.recheck: bad payload: {exc}") from exc

    async def _reconcile(self, marker: str) -> dict | None:
        """Match exactly one remote record by bounded marker token.

        Returns None (stay unknown) on read errors, malformed payloads,
        zero matches, ambiguous multiple matches, or a match without a
        positive integer id.
        """
        token = f"[voicebot {marker}]"
        try:
            response = await self._get("/appointments")
        except ProviderError:
            return None
        if response.status_code >= 400:
            return None
        try:
            records = response.json()
            if isinstance(records, dict) and "data" in records:
                records = records["data"]
            if not isinstance(records, list):
                return None
        except (ValueError, TypeError, AttributeError):
            return None
        matches = [
            record
            for record in records
            if isinstance(record, dict) and token in str(record.get("notes", ""))
        ]
        if len(matches) != 1:
            return None
        if not _is_int_like(matches[0].get("id")):
            return None
        return matches[0]

    @staticmethod
    def _filter_guest(guest: dict) -> dict:
        """Strict slot guest: customerId, or first+last+email+phone.

        A display `name` maps into first/last on a whitespace split. Only
        trusted keys pass; the journal never sees raw guest data.
        """
        if not isinstance(guest, dict) or not guest:
            raise ProviderError("easy.confirm: bad guest")
        if guest.get("customerId") is not None:
            _required_int(guest.get("customerId"), "customerId")
            return {"customerId": int(str(guest["customerId"]))}
        guest = dict(guest)
        if (not guest.get("firstName") or not guest.get("lastName")) and isinstance(
            guest.get("name"), str
        ):
            parts = guest["name"].split()
            if len(parts) >= 2:
                guest.setdefault("firstName", parts[0])
                guest.setdefault("lastName", " ".join(parts[1:]))
        for field in ("firstName", "lastName", "email", "phone"):
            value = guest.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ProviderError(
                    "easy.confirm: guest needs customerId or"
                    " (firstName + lastName + email + phone)"
                )
        clean = {
            k: guest[k].strip()
            for k in ("firstName", "lastName", "email", "phone")
            if isinstance(guest.get(k), str) and guest[k].strip()
        }
        notes = guest.get("notes")
        if isinstance(notes, str) and notes.strip():
            clean["notes"] = notes.strip()[:200]
        return clean

    @staticmethod
    def _snapshot_slot(hold) -> dict:
        """Validate the held slot snapshot; corrupt keys fail closed."""
        slot = hold.payload.get("slot") if isinstance(hold.payload, dict) else None
        if not isinstance(slot, dict):
            raise ProviderError("easy.confirm: bad slot snapshot")
        try:
            service_id = str(slot["serviceId"])
            raw_provider = slot.get("providerId")
            date = str(slot["date"])
            start = str(slot["start"])
        except KeyError as exc:
            raise ProviderError(f"easy.confirm: bad slot snapshot: {exc}") from exc
        if not _is_int_like(service_id) or (
            raw_provider not in (None, "") and not _is_int_like(raw_provider)
        ):
            raise ProviderError("easy.confirm: bad slot ids")
        from datetime import datetime

        try:
            datetime.strptime(date, "%Y-%m-%d")
        except (ValueError, TypeError) as exc:
            raise ProviderError(f"easy.confirm: bad slot date: {exc}") from exc
        _parse_start(start)  # raises closed ProviderError on garbage
        return {
            "service_id": str(int(service_id)),
            "provider_id": (
                None if raw_provider in (None, "") else str(int(str(raw_provider)))
            ),
            "date": date,
            "start": start,
        }

    def _success_result(self, record: dict) -> dict:
        """Commit a booking only on a positive integer id."""
        booking_id = record.get("id")
        if not _is_int_like(booking_id):
            raise ProviderError("easy.confirm: bad payload: no id")
        return {"ok": True, "booking": {"id": record.get("id", booking_id)}}

    async def create_hold(self, slot_id: str) -> Hold:
        # $0 demo: no price — never utter one on this track. A hold is a
        # local snapshot of live search output, not a remote reservation:
        # the slot is rechecked against the PMS at confirm time.
        if not isinstance(slot_id, str) or not slot_id:
            raise UnknownQuoteError(str(slot_id))
        try:
            slot = self._slots[slot_id]
        except KeyError:
            raise UnknownQuoteError(slot_id) from None
        return self._holds.create(
            price_quote_id=slot_id,
            quoted_total=None,
            currency="EUR",
            payload={"slot": dict(slot)},
        )

    async def confirm(self, hold_id: str, guest: dict, idempotency_key: str) -> dict:
        _require_key(idempotency_key, "easy.confirm")
        if not self.operational:
            raise ProviderError("easy.confirm: writes not enabled")
        marker = self._marker(idempotency_key)
        journal = self._journal.get(idempotency_key)
        if journal is not None and journal["status"] == "success":
            return journal["result"] or {"ok": True}
        if journal is not None and journal["status"] == "failed":
            return self._failed_confirmation(journal)
        if journal is not None and journal["status"].startswith("pending"):
            return await self._settle_pending(idempotency_key, journal, hold_id)
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        hold = self._holds.get(hold_id)
        if hold is None:
            return {"ok": False, "error": "hold_expired_or_unknown"}
        clean_guest = self._filter_guest(guest)
        snapshot = self._snapshot_slot(hold)
        async with self._write_lock:
            try:
                lock = await asyncio.to_thread(
                    _acquire_lock, self._lock_path, self._lock_timeout
                )
            except (TimeoutError, OSError):
                return {"ok": False, "error": "confirm_in_progress"}
            try:
                return await self._confirm_locked(
                    idempotency_key, marker, hold_id, snapshot, clean_guest
                )
            finally:
                try:
                    lock.close()
                except Exception:
                    pass

    async def _settle_pending(self, key: str, row: dict, hold_id: str) -> dict:
        # Crash/timeout window: NEVER blindly POST again. Only a uniquely
        # matched remote record may resolve the write.
        if row["status"] == "pending_customer":
            # Customer writes have no supported idempotency primitive. An
            # uncertain create requires operator recovery, never a new POST.
            return {"ok": False, "error": "write_outcome_unknown"}
        matched = await self._reconcile(row["marker"])
        if matched is None:
            return {"ok": False, "error": "write_outcome_unknown"}
        result = self._success_result(matched)
        self._journal.put_result(
            key, row["marker"], "success", result["booking"]["id"], result
        )
        self._holds.record(key, result)
        if hold_id:
            self._holds.release(hold_id)
        return result

    def _fail(self, key: str, marker: str, error: str) -> dict:
        result = {"ok": False, "error": _clean_error(error)}
        self._journal.put_result(key, marker, "failed", None, result)
        return self._holds.record(key, result)

    @staticmethod
    def _failed_confirmation(row: dict) -> dict:
        # Older journals contain private provider details, not public codes.
        result = row.get("result")
        error = result.get("error") if isinstance(result, dict) else None
        return {
            "ok": False,
            "error": "slot_stale" if error == "slot_stale" else "confirm_failed",
        }

    async def _confirm_locked(
        self,
        key: str,
        marker: str,
        hold_id: str,
        snapshot: dict,
        clean_guest: dict,
    ) -> dict:
        # Re-read the journal UNDER the lock: a same-key concurrent waiter
        # must return replay/reconcile — never overwrite success with stale.
        journal = self._journal.get(key)
        if journal is not None and journal["status"] == "success":
            return journal["result"] or {"ok": True}
        if journal is not None and journal["status"] == "failed":
            return self._failed_confirmation(journal)
        if journal is not None and journal["status"].startswith("pending"):
            return await self._settle_pending(key, journal, hold_id)
        # A pre-lock snapshot may expire or be consumed while waiting. Durable
        # same-key replay/reconciliation above remains valid after hold expiry.
        hold = self._holds.get(hold_id)
        if hold is None:
            return {"ok": False, "error": "hold_expired_or_unknown"}
        snapshot = self._snapshot_slot(hold)
        # Global appointment block: while ANY appointment write is unresolved,
        # a new key must not POST (timeout-while-processing would overlap).
        # Other pendings reconcile read-only here; unresolved blocks closed.
        for other_key, other_marker in self._journal.pending_appointments(key):
            if self._journal.get(other_key)["status"] == "pending_customer":
                return {"ok": False, "error": "write_outcome_unknown"}
            matched = await self._reconcile(other_marker)
            if matched is None:
                return {"ok": False, "error": "write_outcome_unknown"}
            result = self._success_result(matched)
            self._journal.put_result(
                other_key, other_marker, "success", result["booking"]["id"], result
            )
            self._holds.record(other_key, result)
        service_id = snapshot["service_id"]
        provider_id = snapshot["provider_id"]
        # Duration and start validate BEFORE any customer side effect.
        try:
            minutes = await self._service_duration(service_id)
            if not 1 <= minutes <= 1440:
                raise ProviderError("easy.service: bad duration")
            start = _parse_start(snapshot["start"])
            end = start + timedelta(minutes=minutes)
            times = await self._availability_times(
                service_id, provider_id, snapshot["date"]
            )
            available_starts = {_parse_start(value) for value in times}
        except (ProviderError, OverflowError, ValueError):
            # No POST has begun: even a read timeout is a known failed attempt.
            # Persist it so this key never retries automatically or after restart.
            return self._fail(key, marker, "confirm_failed")
        if start not in available_starts:
            return self._fail(key, marker, "slot_stale")
        if not self._holds.reserve(key):
            return {"ok": False, "error": "confirm_in_progress"}
        recorded = False
        try:
            customer_id = (
                (journal.get("result") or {}).get("customerId")
                if journal is not None and journal["status"] == "customer_ready"
                else self._holds.get_memo(key, "customerId")
            )
            if customer_id is None:
                if clean_guest.get("customerId") is None:
                    # Persist BEFORE creating a customer: task cancellation,
                    # process death and fresh-key retries must not duplicate it.
                    self._journal.put_result(
                        key, marker, "pending_customer", None, None
                    )
                try:
                    customer_id = await self._ensure_customer(clean_guest)
                except RetryableProviderError:
                    return {"ok": False, "error": "write_outcome_unknown"}
                except ProviderError:
                    return self._fail(key, marker, "confirm_failed")
                self._holds.memo(key, "customerId", customer_id)
                self._journal.put_result(
                    key, marker, "customer_ready", None, {"customerId": customer_id}
                )
            notes = f"[voicebot {marker}]"
            extra = clean_guest.get("notes", "")
            if extra:
                notes = f"{notes} {extra[:200]}"
            body = {
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "customerId": customer_id,
                "providerId": _optional_int(provider_id),
                "serviceId": _required_int(service_id, "serviceId"),
                "notes": notes,
                "status": "Booked",
            }
            body = {k: v for k, v in body.items() if v is not None}
            # Durable appointment pending sits ADJACENT to the single POST.
            self._journal.put_pending(key, marker)
            try:
                response = await self._http.post(
                    f"{self._base}/appointments", json=body
                )
            except (httpx.HTTPError, OSError, asyncio.TimeoutError):
                return {"ok": False, "error": "write_outcome_unknown"}
            try:
                raise_for_provider(response, "easy.confirm")
            except RetryableProviderError:
                # 429/5xx: commit state ambiguous — stay pending.
                return {"ok": False, "error": "write_outcome_unknown"}
            except ProviderError:
                # Known 4xx: terminal, never retry this key blindly.
                return self._fail(key, marker, "confirm_failed")
            if response.status_code != 201:
                return {"ok": False, "error": "write_outcome_unknown"}
            try:
                record = response.json()
                if not isinstance(record, dict):
                    raise ProviderError("easy.confirm: bad payload: no id")
                result = self._success_result(record)
            except (ValueError, ProviderError):
                # Malformed 201: commit ambiguous — stay pending.
                return {"ok": False, "error": "write_outcome_unknown"}
            self._journal.put_result(
                key, marker, "success", result["booking"]["id"], result
            )
            self._holds.release(hold_id)  # consumed: no reconfirm with new key
            result = self._holds.record(key, result)
            recorded = True
            return result
        finally:
            if not recorded:
                self._holds.release_pending(key)

    async def cancel(self, booking_id: str, idempotency_key: str) -> dict:
        _require_key(idempotency_key, "easy.cancel")
        if not self.operational:
            raise ProviderError("easy.cancel: writes not enabled")
        namespaced = f"cancel:{idempotency_key}"
        replayed = self._holds.check_replay(namespaced)
        if replayed is not None:
            return replayed
        journal = self._journal.get(namespaced)
        if journal is not None and journal["status"] in {"success", "cancel_uncertain"}:
            return journal["result"] or {"ok": True}
        if journal is not None and journal["status"] == "failed":
            raise ProviderError(
                (journal["result"] or {}).get("error", "easy.cancel: failed")
            )
        booking_ref = _path_segment(booking_id)
        async with self._write_lock:
            try:
                lock = await asyncio.to_thread(
                    _acquire_lock, self._lock_path, self._lock_timeout
                )
            except (TimeoutError, OSError):
                return {"ok": False, "error": "cancel_in_progress"}
            try:
                # Re-read under the lock: a concurrent waiter replays.
                replayed = self._holds.check_replay(namespaced)
                if replayed is not None:
                    return replayed
                journal = self._journal.get(namespaced)
                if journal is not None and journal["status"] in {
                    "success",
                    "cancel_uncertain",
                }:
                    return journal["result"] or {"ok": True}
                if journal is not None and journal["status"] == "failed":
                    raise ProviderError(
                        (journal["result"] or {}).get("error", "easy.cancel: failed")
                    )
                if not self._holds.reserve(namespaced):
                    return {"ok": False, "error": "cancel_in_progress"}
                recorded = False
                try:
                    try:
                        response = await self._http.delete(
                            f"{self._base}/appointments/{booking_ref}"
                        )
                    except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
                        raise RetryableProviderError(
                            f"easy.cancel: {type(exc).__name__}"
                        ) from exc
                    if response.status_code == 404:
                        # Already gone: idempotent cancel counts as success.
                        result = {
                            "ok": True,
                            "booking_id": booking_id,
                            "already_gone": True,
                        }
                    else:
                        raise_for_provider(response, "easy.cancel")
                        if response.status_code != 204:
                            result = {"ok": False, "error": "write_outcome_unknown"}
                            self._journal.put_result(
                                namespaced,
                                "cancel",
                                "cancel_uncertain",
                                booking_id,
                                result,
                            )
                            return self._holds.record(namespaced, result)
                        result = {"ok": True, "booking_id": booking_id}
                    self._journal.put_result(
                        namespaced, "cancel", "success", booking_id, result
                    )
                    result = self._holds.record(namespaced, result)
                    recorded = True
                    return result
                except ProviderError as exc:
                    if not isinstance(exc, RetryableProviderError):
                        self._journal.put_result(
                            namespaced,
                            "cancel",
                            "failed",
                            None,
                            {"ok": False, "error": _clean_error(str(exc))},
                        )
                    raise
                finally:
                    if not recorded:
                        self._holds.release_pending(namespaced)
            finally:
                try:
                    lock.close()
                except Exception:
                    pass
