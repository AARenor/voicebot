"""The bounded dialogue must reach catalogue → search → hold → confirm."""

import asyncio

from app.turn import run_turn


class Speaker:
    def synthesize(self, text):
        return b"AUDIO"


class Dispatcher:
    def __init__(self):
        self.calls = []

    def available_tools(self):
        return []

    async def dispatch(self, name, args):
        self.calls.append(name)
        return {"ok": True}


class Model:
    def __init__(self, names):
        self.names = iter(names)

    def chat(self, messages, tools=None):
        name = next(self.names, None)
        if name is None:
            return {"content": "Broneering kinnitatud."}
        return {
            "tool_calls": [{"id": name, "function": {"name": name, "arguments": {}}}]
        }


def test_four_dependent_booking_steps_execute():
    dispatcher = Dispatcher()
    names = ["get_slot_catalogue", "search_slots", "hold_slot", "confirm_slot_booking"]
    result = asyncio.run(
        run_turn(
            b"",
            None,
            Model(names),
            Speaker(),
            dispatcher,
            text="Kinnita demobroneering.",
        )
    )
    assert dispatcher.calls == names
    assert len(result["tool_results"]) == 4
    assert result["reply"] == "Broneering kinnitatud."


def test_repeating_tools_stop_without_unverified_success():
    dispatcher = Dispatcher()
    result = asyncio.run(
        run_turn(
            b"",
            None,
            Model(["search_slots"] * 20),
            Speaker(),
            dispatcher,
            text="Otsi aega.",
        )
    )
    assert len(dispatcher.calls) == 4
    assert result["fallback_used"] is True
    assert "kinnitatud" not in result["reply"].lower()
