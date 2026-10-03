"""Spa inquiry spelling tolerance never authorizes a booking or model facts."""

import asyncio
import json
from datetime import datetime
from unittest.mock import patch

import pytest

from app.telephone import (
    ASK_DATE, ASK_DATE_TIME, ASK_TIME, CallTools, CONSENT_TEXT,
    MUTATION_REPLIES, UNKNOWN_REPLY, UNVERIFIED_REPLY,
)
from tests.test_telephone import Slots, prepared


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 3, 0, 15, tzinfo=tz)


@pytest.fixture
def state():
    with patch("app.telephone.datetime", Clock):
        yield CallTools(Slots())


@pytest.mark.parametrize("text", [
    "Tere, tahaks homme bruneerida spaad?",
    "Tere! Tahaks homme broneerida spaad.",
    "Soovin homme spaasse broneerida.",
    "Tere, sooviksin homme broneerida spaa.",
    "Soovin homme spaakonsultatsiooni.",
    "Tere, tahan homme brooneerida spaahooldust.",
])
def test_greeting_and_spa_spelling_ask_for_missing_time_without_actions(state, text):
    state.observe_user_text(text)
    assert state.inquiry_reply() == ASK_TIME
    assert state.booking_inquiry == {"kind": "slot", "date": "2026-10-04"}
    assert not state.dispatcher.calls and not state.holds and not state.bookings
    assert state.pending is None and state.cancel_approval is None


@pytest.mark.parametrize("text,reply,fields", [
    ("Soovin broneerida spaad.", ASK_DATE_TIME, {"kind": "slot"}),
    ("Tahaks täna spaasse.", ASK_TIME, {"kind": "slot", "date": "2026-10-03"}),
    ("Tahaks ülehomme spaasse.", ASK_TIME, {"kind": "slot", "date": "2026-10-05"}),
    ("Soovin 2026-11-02 broneerida spaad.", ASK_TIME, {"kind": "slot", "date": "2026-11-02"}),
    ("Soovin kell 10:30 broneerida spaad.", ASK_DATE, {"kind": "slot", "start_time": "10:30"}),
    ("Soovin homme kell kümme spaasse.", None, {"kind": "slot", "date": "2026-10-04", "start_time": "10:00"}),
])
def test_only_user_fields_determine_missing_question(state, text, reply, fields):
    state.observe_user_text(text)
    assert state.inquiry_reply() == reply
    assert state.booking_inquiry == fields


@pytest.mark.parametrize("text", ["Kell 10:30.", "10.30", "Palun kell 10:30."])
def test_followup_time_retains_requested_tomorrow_and_stops_clarification(state, text):
    state.observe_user_text("Tere, tahaks homme bruneerida spaad?")
    serial = state._turn_serial
    state.observe_user_text(text)
    assert state._turn_serial == serial + 1
    assert state.inquiry_reply() is None
    assert state.booking_inquiry == {"kind": "slot", "date": "2026-10-04", "start_time": "10:30"}
    assert '"date":"2026-10-04"' in state.conversation_instructions
    assert not state.dispatcher.calls and not state.bookings


def test_followup_updates_date_and_time_and_public_context_is_a_copy(state):
    state.observe_user_text("Soovin homme kell 10 spaasse.")
    state.observe_user_text("Ülehomme.")
    state.observe_user_text("Kell 11:30 sobib.")
    assert state.booking_inquiry == {"kind": "slot", "date": "2026-10-05", "start_time": "11:30"}
    context = state.booking_inquiry
    context["date"] = "2099-01-01"
    assert state.booking_inquiry["date"] == "2026-10-05"
    assert "spaasse" not in json.dumps(state.booking_inquiry)
    assert state.inquiry_reply() is None


@pytest.mark.parametrize("followup", ["Ülehomme 11:30.", "2026-11-02 11.30."])
def test_followup_can_supply_date_and_time_together_without_kell(state, followup):
    state.observe_user_text("Soovin broneerida spaad.")
    state.observe_user_text(followup)
    assert state.booking_inquiry["start_time"] == "11:30"
    assert state.booking_inquiry["date"] in {"2026-10-05", "2026-11-02"}
    assert state.inquiry_reply() is None


def test_new_request_starts_new_fields_and_interim_transcript_changes_nothing(state):
    state.observe_user_text("Soovin homme kell 10 spaasse.")
    state.observe_user_text("Ei, ära broneeri.", is_final=False)
    assert state.booking_inquiry["date"] == "2026-10-04"
    assert state.booking_inquiry["start_time"] == "10:00"
    state.observe_user_text("Soovin broneerida spaad.")
    assert state.booking_inquiry == {"kind": "slot"}
    assert state.inquiry_reply() == ASK_DATE_TIME


@pytest.mark.parametrize("text", [
    "Ei, ära broneeri spaad homme.", "Soovin spaad, aga mitte homme.",
    "Jah, kinnitan.", "Jah, tühista.", "Tere!", "Kus spaa asub?",
    "Soovin homme broneerida hotellitoa ja spaad.",
    "Soovin homme või ülehomme broneerida spaad.",
    "Soovin 2026-02-30 broneerida spaad.",
    "Soovin 2020-01-01 broneerida spaad.",
    "Soovin homme kell 25 spaasse.", "Soovin homme kell 10:70 spaasse.",
    "Soovin homme kell pool kümme spaasse.",
    "Soovin homme kell 10 või kell 12 spaasse.", None,
    "Soovin homme kell kakskümmend üks spaasse.",
    "Soovin homme kell kakskümmendüks spaasse.",
    "Soovin homme kell 9.5 spaasse.", "Soovin homme kell 9:5 spaasse.",
    "Soovin homme kell 10:30 või 11:30 spaasse.",
    "Soovin homme kell 10 või 11 spaasse.",
    "Soovin homme kell kümme või üksteist spaasse.",
    "Soovin homme kell 10 kuni 11 spaasse.",
    "Soovin homme umbes kell 10 spaasse.",
    "Soovin homme või esmaspäeval spaasse.",
    "Soovin homme asemel reedel spaasse.",
    "Kas minu broneering spaasse homme on olemas?",
    "Broneerisin spaad homme.", "Soovin broneerida spaahotelli.",
])
def test_negation_ambiguous_fields_and_unrelated_turns_clear_inquiry(state, text):
    state.observe_user_text("Tahaks homme spaasse.")
    state.observe_user_text(text)
    assert state.booking_inquiry is None and state.inquiry_reply() is None
    assert not state.pending and not state.cancel_approval
    assert not state.dispatcher.calls and not state.bookings
    state.observe_user_text("10:30")
    assert state.booking_inquiry is None


@pytest.mark.parametrize("prose", [
    "Tere! Mis kellaaega eelistad homme?",
    "Millisele ajale soovid spaakonsultatsiooni broneerida?",
    "Millal soovite tulla?", "Mis kuupäevaks ja kellaajaks soovid testbroneeringut?",
    "Millist spaateenust soovite?",
])
def test_bounded_question_paraphrases_render_server_missing_field_question(state, prose):
    state.observe_user_text("Tere, tahaks homme bruneerida spaad?")
    assert state.guard_reply(prose, []) == ASK_TIME


@pytest.mark.parametrize("prose,reply", [
    ("Broneering on kinnitatud.", UNVERIFIED_REPLY),
    ("Homme on spaas vabu aegu.", UNVERIFIED_REPLY),
    ("Mis kellaajaks soovid? Panin sulle aja kirja.", UNVERIFIED_REPLY),
    ("Kas sinu broneering on juba kinnitatud?", UNVERIFIED_REPLY),
    ("Millal soovid päris hotelli saabuda?", UNVERIFIED_REPLY),
    ("Spaa asub Tallinnas ja ootab sind homme.", UNVERIFIED_REPLY),
    ("See maksab sada eurot.", "Ma ei saa praegu hinda kinnitada."),
])
def test_inquiry_does_not_whitelist_success_availability_or_price_claims(state, prose, reply):
    state.observe_user_text("Tahaks homme spaasse.")
    assert state.guard_reply(prose, []) == reply
    assert not state.bookings and not state.dispatcher.calls


def test_recap_errors_and_execution_truth_take_precedence_over_questions(state):
    async def run():
        state.observe_user_text("Tahaks homme spaasse.")
        await prepared(state)
        recap = state.render_recap()
        assert state.inquiry_reply() is None
        assert state.guard_reply("Mis kellaaega eelistad?", []) == recap
        state.observe_user_text(CONSENT_TEXT)
        assert state.booking_inquiry is None and state.pending["approved"]
        assert state.inquiry_reply() is None
        result = await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        assert result["ok"]
        assert state.guard_reply("Mis kellaaega eelistad?", []) == MUTATION_REPLIES["confirmed"]
        state.observe_user_text("Tahaks homme spaasse.")
        state.results.append({"error": "booking_unavailable"})
        assert state.inquiry_reply() is None
        assert state.guard_reply("Mis kellaaega eelistad?", []) == "Toiming ei õnnestunud; edu ei ole kinnitatud."
        state._unknown_mutation()
        state.observe_user_text("Tahaks homme spaasse.")
        assert state.booking_inquiry is None and state.inquiry_reply() is None
        assert state.guard_reply("Mis kellaaega eelistad?", []) == UNKNOWN_REPLY

    asyncio.run(run())


def test_actual_read_is_not_hidden_by_inquiry(state):
    async def run():
        state.observe_user_text("Tahaks homme spaasse.")
        result = await state.dispatch("get_slot_catalogue", {})
        assert state.inquiry_reply() is None
        reply = state.guard_reply("Millisele ajale soovite tulla?", [result])
        assert "Live consultation" in reply
        assert reply != ASK_TIME

    asyncio.run(run())


def test_supplied_read_result_also_takes_precedence_over_question_paraphrase(state):
    state.observe_user_text("Tahaks homme spaasse.")
    result = {"services": [{"id": 1, "name": "Canonical consultation", "duration": 30}], "providers": []}
    reply = state.guard_reply("Millisele ajale soovite tulla?", [result])
    assert "Canonical consultation" in reply and reply != ASK_TIME
