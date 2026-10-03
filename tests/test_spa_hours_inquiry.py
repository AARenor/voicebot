"""Current spa working-plan inquiries use a read, never booking authority."""

import asyncio
import copy

import pytest

from app.telephone import CallTools, CONSENT_TEXT, UNKNOWN_REPLY
from tests.test_telephone import Slots, prepared


QUESTION = "Mis kell spaateenindaja töötab ja millal on tema lõunapaus? Palun kontrolli tööplaani."


class Hours(Slots):
    async def dispatch(self, name, args):
        if name == "get_slot_catalogue":
            self.calls.append((name, copy.deepcopy(args)))
            return {
                "services": [{"id": 1, "name": "Backend consultation", "duration": 45}],
                "providers": [{
                    "id": 2, "name": "Database therapist", "services": [1],
                    "working_hours": {
                        "monday": {"start": "08:30", "end": "16:45", "breaks": [
                            {"start": "11:15", "end": "11:50"},
                        ]}, "sunday": None,
                    },
                }],
            }
        return await super().dispatch(name, args)


def test_final_hours_request_selects_current_database_plan_and_breaks():
    async def run():
        state = CallTools(Hours())
        assert not state.spa_hours_inquiry
        state.observe_user_text(QUESTION, is_final=False)
        assert not state.spa_hours_inquiry
        state.observe_user_text(QUESTION)
        assert state.spa_hours_inquiry and state.conversation.focus == "hours"
        assert not state.dispatcher.calls and not state.holds and not state.bookings
        result = await state.dispatch("get_slot_catalogue", {})
        assert state.spa_hours_inquiry
        reply = state.guard_reply("", [result])
        assert "Database therapist" in reply
        assert "08:30–16:45" in reply and "11:15–11:50" in reply
        assert "pühapäev: suletud" in reply
        assert "Backend consultation" not in reply
        assert "Vaba aeg tuleb eraldi kontrollida" in reply
        assert state.dispatcher.calls == [("get_slot_catalogue", {})]
        assert not state.pending and not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize("text", [
    "Soovin homme broneerida spaad.", "Mis spaateenused on olemas?", "Tere!",
    "Mis kell hotell avatakse?", "Mis kell saan spaatoa broneerida?",
    "Kas see on päris spaa?", "Jah, kinnitan.", "Jah, tühista.",
    "Kas spaa töötab kell 10? Palun kinnita broneering.",
])
def test_non_hours_and_mixed_requests_reset_flag_without_actions(text):
    state = CallTools(Hours())
    state.observe_user_text(QUESTION)
    assert state.spa_hours_inquiry
    state.observe_user_text(text)
    assert not state.spa_hours_inquiry
    assert not state.dispatcher.calls and not state.bookings


def test_authoritative_recap_and_unknown_mutation_override_hours_action():
    async def run():
        state = CallTools(Hours())
        state.observe_user_text(QUESTION)
        await prepared(state)
        recap = state.render_recap()
        assert not state.spa_hours_inquiry
        assert state.guard_reply("", state.results) == recap
        state.observe_user_text(CONSENT_TEXT)
        assert not state.spa_hours_inquiry and state.pending["approved"]
        assert (await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"}))["ok"]
        assert not state.spa_hours_inquiry
        assert state.guard_reply("", []) == "Testbroneering on kinnitatud."
        state._unknown_mutation()
        state.observe_user_text(QUESTION)
        assert not state.spa_hours_inquiry
        assert state.guard_reply("", []) == UNKNOWN_REPLY

    asyncio.run(run())


def test_unsupported_language_and_missing_adapter_cannot_trigger_catalogue_read():
    state = CallTools(Hours())
    state.observe_user_text(QUESTION, unsupported=True)
    assert not state.spa_hours_inquiry
    state.observe_user_text(QUESTION)
    state.names.discard("get_slot_catalogue")
    assert not state.spa_hours_inquiry


def test_catalogue_error_and_unknown_schedule_are_not_fixture_hours():
    state = CallTools(Hours())
    state.observe_user_text(QUESTION)
    error = {"error": "booking_unavailable"}
    state.results.append(error)
    assert state.guard_reply("", []) == "Toiming ei õnnestunud; edu ei ole kinnitatud."
    state.observe_user_text(QUESTION)
    reply = state.guard_reply("", [{"services": [], "providers": []}])
    assert "Tööaegu ei ole andmebaasist kinnitatud" in reply
    assert "09:00" not in reply and "12:00" not in reply
