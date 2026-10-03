"""LLM tool dispatch: booking function schemas + validated execution.

Schemas are what the LLM sees (Groq/OpenAI function-calling shape).
dispatch_tool() validates args BEFORE touching adapters and enforces the
price guard: spoken prices come only from verbatim offer snapshots that
carry a price_quote_id — never from embeddings or LLM invention.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, time

import httpx

from .base import SlotAdapter, StayAdapter, UnknownQuoteError
from ..providers.errors import ProviderError

TOOL_SEARCH = {
    "type": "function",
    "function": {
        "name": "search_availability",
        "description": "Search configured stay inventory. Returns backend-priced offers, "
        "each with a price_quote_id.",
        "parameters": {
            "type": "object",
            "required": ["checkin", "checkout"],
            "properties": {
                "checkin": {"type": "string"},
                "checkout": {"type": "string"},
                "adults": {"type": "integer"},
                "children": {"type": "integer", "minimum": 0, "maximum": 8},
                "room_type": {"type": "string"},
                "service": {"type": "string"},
            },
        },
    },
}

TOOL_HOLD = {
    "type": "function",
    "function": {
        "name": "hold_offer",
        "description": "Hold one priced offer (no charge).",
        "parameters": {
            "type": "object",
            "required": ["price_quote_id"],
            "properties": {"price_quote_id": {"type": "string"}},
        },
    },
}

TOOL_CONFIRM = {
    "type": "function",
    "function": {
        "name": "confirm_booking",
        "description": "Confirm a held booking (re-prices against PMS).",
        "parameters": {
            "type": "object",
            "required": ["hold_id", "guest", "idempotency_key"],
            "properties": {
                "hold_id": {"type": "string"},
                "guest": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
        },
    },
}

TOOL_CANCEL_STAY = {
    "type": "function",
    "function": {
        "name": "cancel_booking",
        "description": "Cancel a hotel stay booking by its backend booking id.",
        "parameters": {
            "type": "object",
            "required": ["booking_id"],
            "properties": {
                "booking_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
        },
    },
}

TOOL_STAY_CATALOGUE = {
    "type": "function",
    "function": {
        "name": "get_stay_catalogue",
        "description": "List actual configured room types, capacities and disclosed property policies. Query search_availability for dates and quoted prices.",
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOL_FAQ = {
    "type": "function",
    "function": {
        "name": "answer_faq",
        "description": "Look up hotel policy/FAQ passages (never prices).",
        "parameters": {
            "type": "object",
            "required": ["question"],
            "properties": {"question": {"type": "string"}},
        },
    },
}

TOOL_SEARCH_SLOTS = {
    "type": "function",
    "function": {
        "name": "search_slots",
        "description": "Search spa treatment time slots.",
        "parameters": {
            "type": "object",
            "required": ["service", "date"],
            "properties": {
                "service": {"type": "string"},
                "date": {"type": "string"},
                "provider": {"type": "string"},
            },
        },
    },
}

TOOL_HOLD_SLOT = {
    "type": "function",
    "function": {
        "name": "hold_slot",
        "description": "Hold one time slot as a local snapshot (no charge; "
        "not a remote reservation — availability is rechecked at confirm).",
        "parameters": {
            "type": "object",
            "required": ["slot_id"],
            "properties": {"slot_id": {"type": "string"}},
        },
    },
}

TOOL_CONFIRM_SLOT = {
    "type": "function",
    "function": {
        "name": "confirm_slot_booking",
        "description": "Confirm a held slot. Guest must carry customerId, "
        "or firstName + lastName + email + phone.",
        "parameters": {
            "type": "object",
            "required": ["hold_id", "guest"],
            "properties": {
                "hold_id": {"type": "string"},
                "guest": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
        },
    },
}

TOOL_CANCEL_SLOT = {
    "type": "function",
    "function": {
        "name": "cancel_slot_booking",
        "description": "Cancel a slot booking by booking id (idempotent).",
        "parameters": {
            "type": "object",
            "required": ["booking_id"],
            "properties": {
                "booking_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
        },
    },
}

TOOL_CATALOGUE = {
    "type": "function",
    "function": {
        "name": "get_slot_catalogue",
        "description": "List spa services and providers with numeric ids "
        "(resolve names to ids; never invent ids).",
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOL_TABLE_CATALOGUE = {
    "type": "function",
    "function": {
        "name": "get_table_catalogue",
        "description": "Read the fictional restaurant venue, physical tables and booking rules. Not availability or prices.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}

TOOL_SEARCH_TABLES = {
    "type": "function",
    "function": {
        "name": "search_tables",
        "description": "Search the exact requested restaurant date, Tallinn time and total diner count, including seated children. Never substitute times or combine tables.",
        "parameters": {
            "type": "object",
            "required": ["date", "start_time", "party_size"],
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "start_time": {"type": "string", "description": "HH:MM, Tallinn time"},
                "party_size": {"type": "integer", "minimum": 1, "maximum": 6},
            },
            "additionalProperties": False,
        },
    },
}

TOOL_HOLD_TABLE = {
    "type": "function",
    "function": {
        "name": "hold_table",
        "description": "Temporarily allocate one available physical table for a returned exact offer. The held recap owns the actual table; this does not confirm a reservation.",
        "parameters": {
            "type": "object",
            "required": ["table_offer_id"],
            "properties": {"table_offer_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
}

TOOL_CONFIRM_TABLE = {
    "type": "function",
    "function": {
        "name": "confirm_table_booking",
        "description": "Confirm an owned held fictional table. Trusted policy supplies the approved fictional guest and write key after consent.",
        "parameters": {
            "type": "object",
            "required": ["hold_id", "guest"],
            "properties": {
                "hold_id": {"type": "string"},
                "guest": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
}

TOOL_CANCEL_TABLE = {
    "type": "function",
    "function": {
        "name": "cancel_table_booking",
        "description": "Cancel an owned fictional table reservation by its authoritative table-prefixed booking id.",
        "parameters": {
            "type": "object",
            "required": ["booking_id"],
            "properties": {
                "booking_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
}

TABLE_TOOLS = [
    TOOL_TABLE_CATALOGUE,
    TOOL_SEARCH_TABLES,
    TOOL_HOLD_TABLE,
    TOOL_CONFIRM_TABLE,
    TOOL_CANCEL_TABLE,
]
_TABLE_PARAMETERS = {
    tool["function"]["name"]: tool["function"]["parameters"] for tool in TABLE_TOOLS
}

BOOKING_TOOLS = [
    TOOL_SEARCH,
    TOOL_HOLD,
    TOOL_CONFIRM,
    TOOL_CANCEL_STAY,
    TOOL_STAY_CATALOGUE,
    TOOL_FAQ,
    TOOL_SEARCH_SLOTS,
    TOOL_HOLD_SLOT,
    TOOL_CONFIRM_SLOT,
    TOOL_CANCEL_SLOT,
    TOOL_CATALOGUE,
    *TABLE_TOOLS,
]


def _require_slot(adapter) -> SlotAdapter:
    if adapter is None or not getattr(adapter, "operational", False):
        raise ProviderError("tools: slot booking not configured")
    return adapter


def _require_stay(adapter) -> StayAdapter:
    if adapter is None or not getattr(adapter, "operational", False):
        raise ProviderError("tools: stay booking not configured")
    return adapter


def _require_table(adapter):
    if adapter is None or not getattr(adapter, "operational", False):
        raise ProviderError("tools: table booking not configured")
    return adapter


def _table_request(args):
    day = _require_str(args, "date", 10)
    start_time = _require_str(args, "start_time", 5)
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError
        if not re.fullmatch(r"\d{2}:\d{2}", start_time):
            raise ValueError
        time.fromisoformat(start_time)
    except ValueError:
        raise ProviderError("tools: bad arg date or start_time") from None
    party_size = args.get("party_size")
    if type(party_size) is not int or not 1 <= party_size <= 6:
        raise ProviderError("tools: bad arg party_size")
    return day, start_time, party_size


def _table_key(args):
    if "idempotency_key" in args:
        key = _require_str(args, "idempotency_key", 128)
        if not re.fullmatch(r"[\w][\w.-]{0,127}", key):
            raise ProviderError("tools: bad arg idempotency_key")
        return key
    return _idempotency_key(args)


async def _guarded(code: str, call, *args):
    """Run one adapter call; map internals to closed codes.

    PMS internals (HTTP bodies, KeyErrors on snapshot keys) must never
    reach LLM context or speech — full detail belongs in server logs.
    Transport failures (httpx/OSError/timeouts) also map to the closed
    code so the model never sees stack traces.
    """
    try:
        return await call(*args)
    except UnknownQuoteError:
        raise ProviderError(f"tools: {code}") from None
    except ProviderError:
        raise ProviderError(f"tools: {code}") from None
    except (httpx.HTTPError, OSError, asyncio.TimeoutError, TimeoutError):
        raise ProviderError(f"tools: {code}") from None


def _require_str(args: dict, name: str, cap: int = 256) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value or len(value) > cap:
        raise ProviderError(f"tools: bad arg {name!r}")
    return value


def _require_date(args: dict, name: str) -> str:
    from datetime import datetime

    value = _require_str(args, name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ProviderError(f"tools: bad date {name!r}: {exc}") from exc
    return value


def _coerce_adults(args: dict) -> int:
    try:
        adults = int(str(args.get("adults", 2)))
    except (ValueError, TypeError) as exc:
        raise ProviderError(f"tools: bad adults: {exc}") from exc
    if not 1 <= adults <= 10:
        raise ProviderError("tools: adults out of range 1..10")
    return adults


def _coerce_children(args: dict) -> int:
    value = args.get("children", 0)
    if isinstance(value, bool):
        raise ProviderError("tools: bad children")
    try:
        children = int(str(value))
    except (ValueError, TypeError):
        raise ProviderError("tools: bad children") from None
    if not 0 <= children <= 8:
        raise ProviderError("tools: children out of range 0..8")
    return children


def _require_guest(args: dict) -> dict:
    guest = args.get("guest")
    if not isinstance(guest, dict) or not guest:
        raise ProviderError("tools: bad arg 'guest'")
    if guest.get("customerId") is not None:
        return guest
    has_name = bool(
        guest.get("firstName") or guest.get("lastName") or guest.get("name")
    )
    has_contact = bool(guest.get("phone") or guest.get("email"))
    if not (has_name and has_contact):
        raise ProviderError("tools: guest needs customerId or (name + phone/email)")
    return guest


_SLOT_GUEST_ALLOW = frozenset(
    {"firstName", "lastName", "name", "email", "phone", "notes", "customerId"}
)


def _require_slot_guest(args: dict) -> dict:
    """Slot-track guest: customerId, or first+last+email+phone (strict).

    A display `name` maps into first/last on a whitespace split. Trusted
    keys only — nothing beyond what the PMS customer/appointment calls
    need, and no raw guest data ever reaches the journal.
    """
    guest = _require_guest(args)
    extra = set(guest) - _SLOT_GUEST_ALLOW
    if extra:
        raise ProviderError("tools: guest carries untrusted fields")
    if guest.get("customerId") is not None:
        return {k: guest[k] for k in guest if k in _SLOT_GUEST_ALLOW}
    mapped = dict(guest)
    if (not mapped.get("firstName") or not mapped.get("lastName")) and isinstance(
        mapped.get("name"), str
    ):
        parts = mapped["name"].split()
        if len(parts) >= 2:
            mapped.setdefault("firstName", parts[0])
            mapped.setdefault("lastName", " ".join(parts[1:]))
    for field in ("firstName", "lastName", "email", "phone"):
        value = mapped.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProviderError(
                "tools: guest needs customerId or"
                " (firstName + lastName + email + phone)"
            )
    return {k: mapped[k] for k in mapped if k in _SLOT_GUEST_ALLOW}


def _idempotency_key(args: dict) -> str:
    import re as _re

    key = args.get("idempotency_key")
    if (
        isinstance(key, str)
        and key
        and len(key) <= 128
        and _re.fullmatch(r"[\w][\w\-.]*", key)
    ):
        return key
    # Never trust the model for exactly-once: mint server-side.
    return "srv_" + uuid.uuid4().hex


def speak_offer(offer: dict) -> str:
    """Verbatim price utterance. Raises unless the offer carries a live
    price_quote_id AND a quoted_total — the anti-hallucination gate."""
    quote_id = offer.get("price_quote_id")
    total = offer.get("quoted_total")
    if not quote_id or total is None:
        raise ProviderError("tools: refuse to utter price without live price_quote_id")
    return f"{offer.get('label', 'Pakkumine')}: {total} {offer.get('currency', 'EUR')}"


class Dispatcher:
    """Binds tool names to operational adapters for one explicit business.

    Tool-error results carry closed codes (hold_invalid, pms_error) so
    PMS internals never leak into LLM context or speech; full detail
    belongs in server logs, not transcripts.
    """

    def __init__(
        self, stay=None, slot=None, faq=None, *, table=None, business=None
    ) -> None:
        self.business = (
            business
            if business is not None
            else ("restaurant" if table is not None else "legacy")
        )
        if self.business not in {"legacy", "restaurant"}:
            raise ValueError("unsupported booking business")
        self._stay: StayAdapter | None = stay
        self._slot: SlotAdapter | None = slot
        self._table = table
        self._faq = faq  # callable(question) -> passages

    def available_tools(self) -> list[dict]:
        """Advertise only workflows that can actually execute.

        Configured PMS stubs remain status-visible but never tempt the LLM
        into NotImplementedError paths. FAQ is independent of PMS readiness.
        """
        if self.business == "restaurant":
            return (
                list(TABLE_TOOLS)
                if self._table is not None
                and getattr(self._table, "operational", False)
                else []
            )
        tools = []
        if self._faq is not None:
            tools.append(TOOL_FAQ)
        if self._stay is not None and getattr(self._stay, "operational", False):
            tools.extend((TOOL_SEARCH, TOOL_HOLD, TOOL_CONFIRM, TOOL_CANCEL_STAY))
            if callable(getattr(self._stay, "get_stay_catalogue", None)):
                tools.append(TOOL_STAY_CATALOGUE)
        if self._slot is not None and getattr(self._slot, "operational", False):
            tools.extend(
                (
                    TOOL_SEARCH_SLOTS,
                    TOOL_HOLD_SLOT,
                    TOOL_CONFIRM_SLOT,
                    TOOL_CANCEL_SLOT,
                    TOOL_CATALOGUE,
                )
            )
        return tools

    async def get_stay_hold(self, hold_id: str):
        """Trusted call-policy read; not advertised as a model tool."""
        if self.business != "legacy":
            raise ProviderError("tools: stay booking not configured")
        stay = _require_stay(self._stay)
        getter = getattr(stay, "get_hold", None)
        if not callable(getter):
            raise ProviderError("tools: stay hold read not configured")
        return await _guarded(
            "hold_invalid", getter, _require_str({"hold_id": hold_id}, "hold_id")
        )

    async def get_table_hold(self, hold_id: str):
        """Trusted policy readback of the actual allocated table, not a model tool."""
        if self.business != "restaurant":
            raise ProviderError("tools: table booking not configured")
        table = _require_table(self._table)
        return await _guarded(
            "hold_invalid",
            table.get_hold,
            _require_str({"hold_id": hold_id}, "hold_id"),
        )

    async def release_table_hold(self, hold_id: str):
        """Trusted policy cleanup only; never advertised as a model tool."""
        if self.business != "restaurant":
            raise ProviderError("tools: table booking not configured")
        table = _require_table(self._table)
        release = getattr(table, "release_hold", None)
        if not callable(release):
            return False
        return await _guarded(
            "hold_invalid", release, _require_str({"hold_id": hold_id}, "hold_id")
        )

    async def dispatch(self, name: str, args: dict) -> dict:
        if isinstance(args, str):
            # Real LLM wire shape sends arguments as a JSON string.
            try:
                args = json.loads(args)
            except (ValueError, TypeError) as exc:
                raise ProviderError(f"tools: bad JSON args: {exc}") from exc
        if not isinstance(args, dict):
            raise ProviderError("tools: args must be an object")
        if self.business == "restaurant" and name not in _TABLE_PARAMETERS:
            raise ProviderError("tools: tool not available for restaurant")
        if name in _TABLE_PARAMETERS:
            if self.business != "restaurant":
                raise ProviderError("tools: table booking not configured")
            parameters = _TABLE_PARAMETERS[name]
            if set(args) - set(parameters["properties"]):
                raise ProviderError("tools: untrusted restaurant arguments")
            if set(parameters.get("required", ())) - set(args):
                raise ProviderError("tools: bad arg required restaurant field")
            table = _require_table(self._table)
            if name == "get_table_catalogue":
                return await _guarded("catalogue_failed", table.get_table_catalogue)
            if name == "search_tables":
                offers = await _guarded(
                    "search_failed", table.search_tables, *_table_request(args)
                )
                return {"kind": "table", "offers": offers}
            if name == "hold_table":
                hold = await _guarded(
                    "hold_invalid",
                    table.create_hold,
                    _require_str(args, "table_offer_id"),
                )
                return {
                    "kind": "table",
                    "hold_id": hold.hold_id,
                    "table_offer_id": hold.price_quote_id,
                    "quoted_total": None,
                    "currency": hold.currency,
                    "recap": hold.payload["recap"],
                    "expires_at": hold.payload["expires_at"],
                    "synthetic": hold.payload.get("synthetic") is True,
                    "source": hold.payload.get("source"),
                }
            if name == "confirm_table_booking":
                return await _guarded(
                    "confirm_failed",
                    table.confirm,
                    _require_str(args, "hold_id"),
                    _require_guest(args),
                    _table_key(args),
                )
            if name == "cancel_table_booking":
                return await _guarded(
                    "cancel_failed",
                    table.cancel,
                    _require_str(args, "booking_id"),
                    _table_key(args),
                )
        if name == "search_availability":
            stay = _require_stay(self._stay)
            checkin = _require_date(args, "checkin")
            checkout = _require_date(args, "checkout")
            if checkout <= checkin:
                raise ProviderError("tools: checkout must be after checkin")
            offers = await _guarded(
                "search_failed",
                stay.search_availability,
                checkin,
                checkout,
                {
                    "adults": _coerce_adults(args),
                    "children": _coerce_children(args),
                    "room_type": args.get("room_type", ""),
                    "service": args.get("service", ""),
                },
            )
            return {"offers": offers}
        if name == "hold_offer":
            stay = _require_stay(self._stay)
            quote_id = _require_str(args, "price_quote_id")
            try:
                hold = await stay.create_hold(quote_id)
            except (UnknownQuoteError, ProviderError):
                raise ProviderError("tools: hold_invalid") from None
            result = {
                "hold_id": hold.hold_id,
                "price_quote_id": hold.price_quote_id,
                "quoted_total": hold.quoted_total,
                "currency": hold.currency,
            }
            if hold.payload.get("synthetic") is True:
                result["synthetic"] = True
                result["source"] = hold.payload.get("source")
            if isinstance(hold.payload.get("recap"), dict):
                result["recap"] = hold.payload["recap"]
            return result
        if name == "confirm_booking":
            stay = _require_stay(self._stay)
            guest = _require_guest(args)
            return await _guarded(
                "confirm_failed",
                stay.confirm,
                _require_str(args, "hold_id"),
                guest,
                _idempotency_key(args),
            )
        if name == "cancel_booking":
            stay = _require_stay(self._stay)
            return await _guarded(
                "cancel_failed",
                stay.cancel,
                _require_str(args, "booking_id"),
                _idempotency_key(args),
            )
        if name == "get_stay_catalogue":
            stay = _require_stay(self._stay)
            describe = getattr(stay, "get_stay_catalogue", None)
            if not callable(describe):
                raise ProviderError("tools: catalogue not configured")
            return await _guarded("catalogue_failed", describe)
        if name == "search_slots":
            slot = _require_slot(self._slot)
            return {
                "slots": await _guarded(
                    "search_failed",
                    slot.search_slots,
                    _require_str(args, "service"),
                    _require_date(args, "date"),
                    args.get("provider")
                    if isinstance(args.get("provider"), str)
                    else None,
                )
            }
        if name == "hold_slot":
            slot = _require_slot(self._slot)
            slot_id = _require_str(args, "slot_id")
            try:
                hold = await slot.create_hold(slot_id)
            except (UnknownQuoteError, ProviderError):
                raise ProviderError("tools: hold_invalid") from None
            return {"hold_id": hold.hold_id}
        if name == "confirm_slot_booking":
            slot = _require_slot(self._slot)
            guest = _require_slot_guest(args)
            return await _guarded(
                "confirm_failed",
                slot.confirm,
                _require_str(args, "hold_id"),
                guest,
                _idempotency_key(args),
            )
        if name == "cancel_slot_booking":
            slot = _require_slot(self._slot)
            return await _guarded(
                "cancel_failed",
                slot.cancel,
                _require_str(args, "booking_id"),
                _idempotency_key(args),
            )
        if name == "get_slot_catalogue":
            slot = _require_slot(self._slot)
            describe = getattr(slot, "get_slot_catalogue", None)
            if not callable(describe):
                raise ProviderError("tools: catalogue not configured")
            return await _guarded("catalogue_failed", describe)
        if name == "answer_faq":
            if self._faq is None:
                raise ProviderError("tools: no FAQ backend configured")
            question = args.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ProviderError("tools: bad arg 'question'")
            return {"passages": self._faq(question[:500])}
        raise ProviderError(f"tools: unknown tool {name!r}")
