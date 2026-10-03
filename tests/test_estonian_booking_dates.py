"""Caller date answers reach both transports as exact Tallinn-local dates."""

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.booking_dates import MONTHS, interpreted_dates, resolve_estonian_date
from app.booking_faq import booking_input
from app.conversation import QUESTIONS
from app.telephone import ASK_DATE_TIME, ASK_TIME, CallTools, UNKNOWN_REPLY
from tests.test_product_demo import client, send, start
from tests.test_telephone import Slots


TODAY = date(2026, 10, 3)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        # It is already 3 October in Tallinn, but still 2 October in UTC.
        return cls(2026, 10, 2, 22, 15, tzinfo=timezone.utc).astimezone(tz)


@pytest.mark.parametrize("token,expected", [
    ("täna", "2026-10-03"), ("homme", "2026-10-04"), ("ülehomme", "2026-10-05"),
    ("6. oktoober", "2026-10-06"), ("6 oktoobril", "2026-10-06"),
    ("Kuues oktoober", "2026-10-06"), ("kuuendal oktoobril", "2026-10-06"),
    ("6. oktoober 2027", "2027-10-06"), ("6. oktoobril 2027. aastal", "2027-10-06"),
    ("2026-10-06", "2026-10-06"), ("2. oktoober", "2027-10-02"),
    ("29. veebruar", "2028-02-29"),
])
def test_dates_resolve_to_the_next_real_calendar_occurrence(token, expected):
    assert resolve_estonian_date(token, TODAY) == {"status": "resolved", "date": expected}
    assert booking_input(token)


@pytest.mark.parametrize("number,names", list(enumerate(MONTHS, 1)))
def test_all_month_names_and_spoken_case_endings(number, names):
    for name in names:
        assert resolve_estonian_date(f"6. {name} 2027", TODAY) == {
            "status": "resolved", "date": f"2027-{number:02d}-06",
        }


@pytest.mark.parametrize("token", ["31. aprill", "30. veebruar", "0. oktoober", "2026-02-29"])
def test_impossible_dates_are_not_replaced_by_another_day(token):
    assert resolve_estonian_date(token, TODAY) == {"status": "invalid"}


def test_explicit_years_and_new_year_are_preserved():
    assert resolve_estonian_date("6. oktoober 2025", TODAY) == {"status": "past", "date": "2025-10-06"}
    assert resolve_estonian_date("homme", date(2026, 12, 31)) == {"status": "resolved", "date": "2027-01-01"}
    assert interpreted_dates("Saabun 6. oktoobril ja lahkun 8. oktoobril.", TODAY) == [
        {"status": "resolved", "date": "2026-10-06"},
        {"status": "resolved", "date": "2026-10-08"},
    ]


@pytest.mark.parametrize("text", ["6 eurot", "A6-oktoober", "13.90 eurot", "homme või ülehomme", "mitte homme"])
def test_unrelated_or_ambiguous_inputs_are_not_single_date_answers(text):
    assert not booking_input(text)


@pytest.mark.parametrize("answer,expected", [
    ("Homme.", "2026-10-04"), ("6. oktoober", "2026-10-06"),
    ("Kuuendal oktoobril.", "2026-10-06"), ("Palun 6. oktoobril.", "2026-10-06"),
])
def test_spa_date_followup_moves_to_time_and_keeps_the_selected_day(answer, expected):
    with patch("app.telephone.datetime", Clock):
        state = CallTools(Slots())
        state.observe_user_text("Soovin broneerida spaad.")
        assert state.inquiry_reply() == ASK_DATE_TIME
        state.observe_user_text(answer)
        assert state.inquiry_reply() == ASK_TIME
        assert state.booking_inquiry == {"kind": "slot", "date": expected}
        state.observe_user_text("Kell 10:30.")
        assert state.booking_inquiry == {"kind": "slot", "date": expected, "start_time": "10:30"}
        assert not state.dispatcher.calls and not state.bookings


def test_named_date_and_time_in_one_request_do_not_confuse_day_with_hour():
    with patch("app.telephone.datetime", Clock):
        state = CallTools(Slots())
        state.observe_user_text("Soovin 6. oktoobril 2026 kell 18:30 broneerida spaad.")
        assert state.booking_inquiry == {"kind": "slot", "date": "2026-10-06", "start_time": "18:30"}
        state.observe_user_text("8. oktoober.")
        assert state.booking_inquiry == {"kind": "slot", "date": "2026-10-08", "start_time": "18:30"}


def test_one_final_turn_uses_one_date_snapshot_even_at_midnight():
    state = CallTools(Slots())
    with patch("app.telephone.datetime") as clock:
        clock.now.side_effect = [datetime(2026, 10, 3, 23, 59, 59), datetime(2026, 10, 4)]
        state.observe_user_text("Soovin homme spaasse.")
        assert clock.now.call_count == 1
    assert state.requested_dates[0]["date"] == state.booking_inquiry["date"] == "2026-10-04"


def test_date_context_is_turn_scoped_and_cannot_authorize_a_write():
    with patch("app.telephone.datetime", Clock):
        state = CallTools(Slots())
        state.observe_user_text("homme", is_final=False)
        assert state.requested_dates == []
        state.observe_user_text("6. oktoober")
        fields = state.requested_dates
        fields[0]["date"] = "2099-01-01"
        assert state.requested_dates[0]["date"] == "2026-10-06"
        assert not state.pending and not state.cancel_approval
        state.observe_user_text("Aitäh!")
        assert state.requested_dates == []
        state._unknown_mutation()
        state.observe_user_text("homme")
        assert state.guard_reply("Mis kell soovid tulla?", []) == UNKNOWN_REPLY


@pytest.mark.parametrize("answer,expected", [("homme", "2026-10-04"), ("6. oktoober", "2026-10-06")])
def test_http_arrival_date_answer_reaches_planner_without_repeating_date_question(client, answer, expected):
    class Planner:
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            assert '"requested_dates":[{"status":"resolved","date":"' + expected + '"}]' in messages[0]["content"]
            return {"content": QUESTIONS["et"]["departure"][0]}

    planner = Planner()
    client.app.state.stack["llm_primary"] = planner
    session = start(client)
    saved = client.app.state.demo_sessions.sessions[session]
    saved.tools = CallTools(Slots(), call_id=saved.tools.call_id)
    with patch("app.telephone.datetime", Clock):
        assert send(client, session, "Kas saate toa broneerida?").json()["reply"] == QUESTIONS["et"]["arrival"][0]
        result = send(client, session, answer).json()
    assert result["reply"] == QUESTIONS["et"]["departure"][0]
    assert client.app.state.stack["tts"].spoken[-1] == result["reply"]
    assert planner.calls == 1 and result["booking_changes"] == []


@pytest.mark.parametrize("answer,spoken", [("homme", "4. oktoobril 2026"), ("6. oktoober", "6. oktoobril 2026")])
def test_restaurant_demo_acknowledges_the_date_without_claiming_a_booking(client, answer, spoken):
    session = start(client)
    with patch("app.telephone.datetime", Clock):
        result = send(client, session, answer).json()
    assert result["reply"] == f"Sain aru, soovid tulla {spoken}. Selles demos ei saa veel lauda broneerida."
    assert result["timings_ms"]["llm"] == 0 and result["booking_changes"] == []


@pytest.mark.parametrize("answer", ["31. aprill", "6. oktoober 2025"])
def test_invalid_or_past_date_is_clarified_without_calling_a_planner(client, answer):
    with patch("app.telephone.datetime", Clock):
        result = send(client, start(client), answer).json()
    assert "kuupäev" in result["reply"]
    assert result["timings_ms"]["llm"] == 0
    assert not client.app.state.stack["llm_primary"].messages


@pytest.mark.parametrize("answer,expected", [("homme", "2026-10-04"), ("6. oktoober", "2026-10-06")])
def test_native_arrival_answer_injects_the_exact_date_into_current_planning_turn(answer, expected):
    pytest.importorskip("livekit.agents")
    from livekit.agents import llm
    from livekit.agents.voice.agent import ModelSettings
    from app.worker import TelephoneAgent

    async def run():
        agent = TelephoneAgent(CallTools(Slots()))
        request = llm.ChatMessage(role="user", content=["Kas saate toa broneerida?"])
        context = llm.ChatContext(items=[request])
        await agent.on_user_turn_completed(context.copy(), request)
        question = [chunk async for chunk in agent.llm_node(context, [], ModelSettings())]
        assert question == [QUESTIONS["et"]["arrival"][0]]
        answer_message = llm.ChatMessage(role="user", content=[answer])
        context.items.extend([llm.ChatMessage(role="assistant", content=question), answer_message])
        await agent.on_user_turn_completed(context.copy(), answer_message)

        async def planner(agent, chat_ctx, tools, settings):
            assert any(
                '"requested_dates": [{"status": "resolved", "date": "' + expected + '"}]' in (item.text_content or "")
                for item in chat_ctx.items if isinstance(item, llm.ChatMessage) and item.role == "system"
            )
            yield QUESTIONS["et"]["departure"][0]

        with patch("livekit.agents.Agent.default.llm_node", planner):
            chunks = [chunk async for chunk in agent.llm_node(context, [], ModelSettings())]
        assert chunks == [QUESTIONS["et"]["departure"][0]]
        assert agent.state.guard_reply(chunks[0], []) == chunks[0]
        assert not agent.state.dispatcher.calls and not agent.state.bookings

    with patch("app.telephone.datetime", Clock):
        asyncio.run(run())
