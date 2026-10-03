"""Atomic ownership, receipt truth and pre-parse HTTP bounds; no live network."""

import asyncio
import copy
import json
import time
from unittest.mock import patch

import httpx
import pytest

from app.booking.tools import Dispatcher
from app.hackathon import DemoSession, run_demo_turn
from app.telephone import CallTools, CONSENT_TEXT
from tests.test_demo_plan import LiveSlots, REQUEST
from tests.test_product_demo import AUTH, Speaker, call, client as demo_client

client = demo_client


def test_failed_search_cannot_grant_unreturned_slot_ownership():
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend))
        # A prior successfully returned slot remains owned; a failed new batch
        # must not insert its valid prefix before discovering the bad suffix.
        args = {"service": "6", "provider": "2", "date": REQUEST["date"]}
        assert "error" not in await state.dispatch("search_slots", args)
        before = copy.deepcopy(state.slots)
        backend.slots = [
            {**backend.slots[0], "slotId": "unreturned-slot"},
            {**backend.slots[0], "slotId": "malformed-slot", "start": "INVALID"},
        ]
        assert await state.dispatch("search_slots", args) == {
            "error": "booking_unavailable"
        }
        assert state.slots == before
        state.observe_user_text("Proovin uuesti.")
        assert await state.dispatch("hold_slot", {"slot_id": "unreturned-slot"}) == {
            "error": "not_owned"
        }
        assert not any(name == "hold" for name, _ in backend.calls)

    asyncio.run(run())


def test_native_historical_cancel_replay_cannot_replace_new_confirmation():
    async def run():
        from types import SimpleNamespace

        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend))

        async def book(hold_id):
            assert (await state.dispatch("plan_demo_booking", REQUEST))["ok"]
            assert state.mark_recap_delivered(hold_id)
            state.observe_user_text(CONSENT_TEXT)
            assert (await state.dispatch("confirm_slot_booking", {"hold_id": hold_id}))[
                "ok"
            ]

        await book("backend-hold")
        state.observe_user_text("Jah, tühista.")
        assert (await state.dispatch("cancel_slot_booking", {"booking_id": "42"}))["ok"]
        backend.slots[0]["slotId"] = "second-slot"
        backend.confirm_result = {"ok": True, "booking": {"id": 43}}

        async def second_hold(slot_id):
            backend.calls.append(("hold", {"slot_id": slot_id}))
            return SimpleNamespace(hold_id="second-hold")

        backend.create_hold = second_hold
        state.observe_user_text("Soovin uut aega.")
        await book("second-hold")
        assert state.turn_mutation == "confirmed"
        assert (await state.dispatch("cancel_slot_booking", {"booking_id": "42"}))["ok"]
        assert (
            state.guard_reply("Tere!", state.results) == "Testbroneering on kinnitatud."
        )
        assert sum(name == "confirm" for name, _ in backend.calls) == 2
        assert sum(name == "cancel" for name, _ in backend.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "condition", ["approved", "declined", "expired", "uncertain", "cancel"]
)
def test_http_current_owned_ids_survive_prose_only_history(condition):
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend))
        session = DemoSession("fixture", state, time.monotonic() + 600)
        stack = {"stt": None, "llm_secondary": None, "tts": Speaker()}

        class Plan:
            def __init__(self):
                self.first = True

            def chat(self, messages, tools=None):
                if self.first:
                    self.first = False
                    return call("plan_demo_booking", REQUEST)
                return {"content": "Tere!"}

        stack["llm_primary"] = Plan()
        recap = await run_demo_turn(session, stack, b"", "Soovin aega", "et")
        assert "backend-hold" not in recap["reply"], (
            "caller-facing recap is not a tool-ID channel"
        )
        if condition == "expired":
            state.pending["expires_at"] = 0
        if condition == "uncertain":
            state._unknown_mutation()
        if condition == "cancel":
            state.bookings.add("42")
            state.last_booking = "42"
        # Losing this trusted state would force the next turn to guess IDs:
        # history intentionally contains caller-facing prose, not tool results.
        contexts = []

        class CurrentIds:
            def chat(self, messages, tools=None):
                context = json.loads(
                    messages[0]["content"].rsplit("Server-owned state: ", 1)[1]
                )
                contexts.append(context)
                if messages[-1]["role"] == "tool":
                    return {"content": "Tere!"}
                if context["pending"] and context["pending"]["approved"]:
                    return call(
                        "confirm_slot_booking",
                        {"hold_id": context["pending"]["hold_id"]},
                    )
                if condition == "cancel":
                    return call(
                        "cancel_slot_booking", {"booking_id": context["last_booking"]}
                    )
                return {"content": "Tere!"}

        primary = CurrentIds()
        stack["llm_primary"] = primary
        text = (
            "Jah, tühista."
            if condition == "cancel"
            else "Ei, aitäh."
            if condition == "declined"
            else CONSENT_TEXT
        )
        pending_before = copy.deepcopy(state.pending)
        result = await run_demo_turn(session, stack, b"", text, "et")
        if condition == "approved":
            assert pending_before["hold_id"] == "backend-hold"
            assert pending_before["delivery"] is True
            assert contexts == []  # The server performs the owned action directly.
            assert result["booking_ids"] == ["42"]
            assert result["booking_changes"][0]["action"] == "confirmed"
        elif condition in {"declined", "expired"}:
            assert contexts[0]["pending"] is None
        else:
            assert contexts == [] and state.pending is None
        if condition == "uncertain":
            assert result["outcome"] == "unknown_outcome"
        if condition == "cancel":
            assert state.last_booking == "42"
            assert result["reply"] == "Testbroneering on tühistatud."
        assert sum(name == "confirm" for name, _ in backend.calls) == (
            condition == "approved"
        )
        assert sum(name == "cancel" for name, _ in backend.calls) == (
            condition == "cancel"
        )

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_completed_write_is_not_hidden_by_later_read_error(cancel):
    class Sequence:
        def __init__(self, *answers):
            self.answers = iter(answers)

        def chat(self, messages, tools=None):
            return next(self.answers)

    async def run():
        backend = LiveSlots()
        session = DemoSession(
            "fixture", CallTools(Dispatcher(slot=backend)), time.monotonic() + 600
        )
        stack = {"stt": None, "llm_secondary": None, "tts": Speaker()}
        stack["llm_primary"] = Sequence(
            call("plan_demo_booking", REQUEST), {"content": "Tere!"}
        )
        assert (
            "Fiktiivne testbroneering:"
            in (
                await run_demo_turn(
                    session, stack, b"", "Soovin testbroneeringut", "et"
                )
            )["reply"]
        )
        stack["llm_primary"] = Sequence(
            call("confirm_slot_booking", {"hold_id": "backend-hold"}),
            call("get_demo_profile", {"extra": True}),
            {"content": "Tere!"},
        )
        result = await run_demo_turn(session, stack, b"", CONSENT_TEXT, "et")
        if cancel:
            stack["llm_primary"] = Sequence(
                call("cancel_slot_booking", {"booking_id": "42"}),
                call("get_demo_profile", {"extra": True}),
                {"content": "Tere!"},
            )
            result = await run_demo_turn(session, stack, b"", "Jah, tühista.", "et")
        prefix = (
            "Testbroneering on tühistatud."
            if cancel
            else "Testbroneering on kinnitatud."
        )
        assert result["reply"].startswith(prefix)
        assert "päring ebaõnnestus" in result["reply"]
        assert result["outcome"] == "tools_failed"  # secondary failure is not hidden
        assert result["booking_changes"][0]["action"] == (
            "cancelled" if cancel else "confirmed"
        )
        assert result["reply"] == stack["tts"].spoken[-1]
        assert sum(name == "confirm" for name, _ in backend.calls) == 1

    # Exercise the shared error guard with a model-issued mixed tool sequence.
    # HTTP terminal shortcuts have separate coverage in test_http_booking_terminals.
    with patch("app.hackathon.trusted_booking_response", return_value=None):
        asyncio.run(run())


@pytest.mark.parametrize("authorized", [False, True])
def test_oversized_non_object_json_has_small_private_error(client, authorized):
    response = client.post(
        "/api/turn",
        content=json.dumps(["PRIVATE-FIXTURE" * 160_000]),
        headers={"Content-Type": "application/json", **(AUTH if authorized else {})},
    )
    assert response.status_code == (413 if authorized else 403)
    assert len(response.content) < 1000
    assert "PRIVATE-FIXTURE" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert not client.app.state.stack["llm_primary"].messages


@pytest.mark.parametrize(
    "body",
    [b"[]", b"null", b"bad json", b"\xff", b"[" * 10_000],
    ids=["array", "null", "garbage", "invalid_utf8", "too_deep"],
)
def test_invalid_json_never_echoes_or_reaches_providers(client, body):
    response = client.post("/api/turn", content=body, headers=AUTH)
    assert response.status_code == 400
    assert len(response.content) < 1000
    assert response.headers["Cache-Control"] == "no-store"
    assert not client.app.state.stack["llm_primary"].messages


@pytest.mark.parametrize("declared_length", [None, "1"])
def test_chunked_body_is_bounded_without_trusting_content_length(
    client, declared_length
):
    consumed = []

    async def run():
        async def content():
            for index in range(200):
                consumed.append(index)
                yield b" " * 10_000

        headers = dict(AUTH)
        if declared_length is not None:
            headers["Content-Length"] = declared_length
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app),
            base_url="http://fixture.invalid",
        ) as http:
            response = await http.post("/api/turn", content=content(), headers=headers)
        assert response.status_code == 413
        assert len(response.content) < 1000
        assert response.headers["Cache-Control"] == "no-store"

    asyncio.run(run())
    assert len(consumed) < 200, "unbounded stream was fully consumed before rejection"
    assert not client.app.state.stack["llm_primary"].messages
