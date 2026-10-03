"""Browser delivery receipts exercise the real HTTP app and owned CallTools."""

import base64
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.languages import CONSENT as LOCALIZED_CONSENT
from tests.test_product_demo import (
    AUTH,
    CONSENT,
    BookingLlm,
    Speaker,
    call,
    install_backend,
    start,
)
from tests.test_product_demo import client as client  # noqa: PLC0414


def send(client, session_id, text, **extra):
    # Delivery tests must never inherit the positive-flow helper's implicit read.
    return client.post(
        "/api/turn",
        json={"session_id": session_id, "text": text, **extra},
        headers=AUTH,
    )


@pytest.mark.parametrize("invalid", ["expired", "foreign", "consumed"])
def test_invalid_stream_receipt_is_rejected_before_headers_or_recognition(
    client, tmp_path, invalid
):
    from tests.test_browser_audio_stream import STREAM_AUTH

    day, records, writes = install_backend(client, tmp_path)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    session_id = start(client)
    prepared = send(client, session_id, "Soovin testbroneeringut").json()
    receipt = prepared["recap_delivery_id"]
    session = client.app.state.demo_sessions.sessions[session_id]
    if invalid == "expired":
        session.tools.pending["expires_at"] = 0
    elif invalid == "foreign":
        receipt = "0" * 32
    else:
        session.consume_recap_delivery(receipt)

    class Recognition:
        calls = 0

        def transcribe(self, audio, **kwargs):
            self.calls += 1
            return "Jah, kinnitan."

    recognition = Recognition()
    client.app.state.stack["stt"] = recognition
    observed = session.tools._turn_serial
    spoken = list(client.app.state.stack["tts"].spoken)
    response = client.post(
        "/api/turn",
        headers=STREAM_AUTH,
        json={
            "session_id": session_id,
            "audio_b64": base64.b64encode(b"fictional-audio").decode(),
            "recap_delivery_id": receipt,
        },
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "recap_delivery_expired_or_unknown"}
    assert response.headers["Cache-Control"] == "no-store"
    assert recognition.calls == 0 and session.tools._turn_serial == observed
    assert client.app.state.stack["tts"].spoken == spoken
    assert not session.busy and not records and not writes


def prepare(client, day, session_id):
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    response = send(client, session_id, "Soovin testbroneeringut")
    assert response.status_code == 200, response.text
    return response.json()


def receipt(result):
    value = result.get("recap_delivery_id")
    assert isinstance(value, str) and len(value) == 32, "missing opaque recap receipt"
    return value


def test_synthesis_alone_does_not_authorize_http_booking(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)
    session_id = start(client)
    prepared = prepare(client, day, session_id)
    assert prepared["audio_b64"]
    result = send(client, session_id, CONSENT).json()
    assert not records and not writes, "synthesis was incorrectly treated as delivery"
    assert result["outcome"] == "ok"  # no model-authorized confirmation attempt
    assert result["booking_changes"] == []
    state = client.app.state.demo_sessions.sessions[session_id].tools
    assert state.pending is None  # unheard affirmation invalidates preparation


@pytest.mark.parametrize("audio", [False, True], ids=["typed", "recognized"])
def test_exact_receipt_is_consumed_before_subsequent_final_consent(
    client, tmp_path, audio
):
    day, records, writes = install_backend(client, tmp_path)
    session_id = start(client)
    prepared = prepare(client, day, session_id)
    state = client.app.state.demo_sessions.sessions[session_id].tools
    assert state.pending["delivery"] is False
    assert state.pending["approved"] is False
    delivery_id = receipt(prepared)
    assert delivery_id not in {session_id, state.call_id, state.pending["hold_id"]}
    payload = {"session_id": session_id, "recap_delivery_id": delivery_id}
    if audio:

        class Stt:
            def transcribe(self, data, *, language):
                assert data == b"RIFF-fixture" and language == "auto"
                return CONSENT

        client.app.state.stack["stt"] = Stt()
        payload["audio_b64"] = base64.b64encode(b"RIFF-fixture").decode()
    else:
        payload["text"] = CONSENT
    response = client.post("/api/turn", json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "tools_ok"
    assert response.json()["booking_ids"] == ["42"]
    assert response.json().get("recap_delivery_id") is None
    assert len(records) == 1
    assert sum(r.url.path.endswith("/appointments") for r in writes) == 1
    replay = send(client, session_id, CONSENT, recap_delivery_id=delivery_id)
    assert replay.status_code == 409
    assert len(records) == 1


@pytest.mark.parametrize("text", ["Ei, ära kinnita.", "Võib-olla hiljem."])
def test_receipt_is_delivery_not_explicit_consent(client, tmp_path, text):
    day, records, writes = install_backend(client, tmp_path)
    session_id = start(client)
    prepared = prepare(client, day, session_id)
    response = send(client, session_id, text, recap_delivery_id=receipt(prepared))
    assert response.status_code == 200, response.text
    assert response.json()["booking_changes"] == []
    assert not records and not writes
    assert client.app.state.demo_sessions.sessions[session_id].tools.pending is None


def test_foreign_session_receipt_is_rejected_before_observing_input(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)
    first, second = start(client), start(client)
    first_receipt = receipt(prepare(client, day, first))
    prepare(client, day, second)
    session = client.app.state.demo_sessions.sessions[second]
    pending = session.tools.pending
    serial = session.tools._turn_serial
    history = list(session.history)
    response = send(client, second, CONSENT, recap_delivery_id=first_receipt)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "recap_delivery_expired_or_unknown"}
    assert response.headers["Cache-Control"] == "no-store"
    assert session.tools.pending is pending
    assert pending["delivery"] is False and pending["approved"] is False
    assert session.tools._turn_serial == serial and session.history == history
    assert not session.busy
    assert not records and not writes


@pytest.mark.parametrize(
    "invalidated",
    ["superseded", "expired", "unknown", "changed", "wrong_kind", "not_owned"],
)
def test_receipt_requires_the_exact_current_live_preparation(
    client, tmp_path, invalidated
):
    day, records, writes = install_backend(client, tmp_path)
    session_id = start(client)
    prepared = prepare(client, day, session_id)
    delivery_id = receipt(prepared)
    session = client.app.state.demo_sessions.sessions[session_id]
    pending = session.tools.pending
    if invalidated == "superseded":
        slot_id = next(iter(session.tools.slots))
        replacement = client.post(
            "/api/booking/prepare",
            json={"session_id": session_id, "kind": "slot", "slot_id": slot_id},
            headers=AUTH,
        )
        assert replacement.status_code == 200, replacement.text
        assert session.tools.pending is not pending
        assert session.tools.pending["hold_id"] == pending["hold_id"]
        assert replacement.json()["recap_text"] == prepared["reply"]
    elif invalidated == "expired":
        pending["expires_at"] = 0
    elif invalidated == "unknown":
        session.tools._unknown_mutation()
    elif invalidated == "wrong_kind":
        pending["kind"] = "stay"
    elif invalidated == "not_owned":
        session.tools.holds.clear()
    else:
        pending["recap"]["guest_name"] = "Demo Teine"
    serial = session.tools._turn_serial
    response = send(client, session_id, CONSENT, recap_delivery_id=delivery_id)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "recap_delivery_expired_or_unknown"
    assert session.tools._turn_serial == serial
    assert not records and not writes


def test_old_receipt_cannot_skip_an_intervening_normal_input(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)
    session_id = start(client)
    delivery_id = receipt(prepare(client, day, session_id))
    assert send(client, session_id, "Tere").status_code == 200
    result = send(client, session_id, CONSENT, recap_delivery_id=delivery_id)
    assert result.status_code == 409, result.text
    assert not records and not writes


@pytest.mark.parametrize(
    "language,utterance",
    [
        ("et", "Korda palun"),
        ("en", "Please speak in English."),
        ("ru", "Говорите по-русски."),
    ],
)
@pytest.mark.parametrize("streaming", [False, True], ids=["json", "ndjson"])
def test_repeated_or_translated_recap_has_a_fresh_receipt_without_new_tools(
    client, tmp_path, language, utterance, streaming
):
    day, records, writes = install_backend(client, tmp_path)
    session_id = start(client)
    original = prepare(client, day, session_id)
    state = client.app.state.demo_sessions.sessions[session_id].tools
    pending = state.pending

    class UnusedModel:
        def chat(self, *args, **kwargs):
            raise AssertionError("canonical repeat must not request a model")

    client.app.state.stack["llm_primary"] = UnusedModel()
    if streaming:
        from tests.test_browser_audio_stream import STREAM_AUTH, events

        repeated = events(
            client.post(
                "/api/turn",
                headers=STREAM_AUTH,
                json={
                    "session_id": session_id,
                    "text": utterance,
                    "language": language,
                },
            )
        )[-1]
    else:
        repeated = send(client, session_id, utterance, language=language).json()
    assert (
        state.pending is not pending and state.pending["hold_id"] == pending["hold_id"]
    )
    assert state.pending["expires_at"] == pending["expires_at"]
    assert repeated["reply"] == state.render_recap()
    assert repeated["language"] == language and repeated["tools_used"] == 0
    assert receipt(repeated) != receipt(original)
    assert 0 < repeated["recap_expires_in_s"] <= original["recap_expires_in_s"]
    assert not state.pending["delivery"] and not state.pending["approved"]
    assert not records and not writes
    confirmed = send(
        client,
        session_id,
        LOCALIZED_CONSENT[language],
        language=language,
        recap_delivery_id=receipt(repeated),
    )
    assert confirmed.status_code == 200 and confirmed.json()["booking_ids"] == ["42"]
    assert len(records) == 1
    assert sum(r.url.path.endswith("/appointments") for r in writes) == 1
    stale = send(
        client,
        session_id,
        LOCALIZED_CONSENT[language],
        recap_delivery_id=receipt(original),
        language=language,
    )
    assert stale.status_code == 409
    assert len(records) == 1


@pytest.mark.parametrize(
    "invalidated", ["expired", "replaced", "changed", "not_owned", "unknown"]
)
def test_done_cannot_issue_a_receipt_for_a_preparation_changed_during_speech(
    client, tmp_path, invalidated
):
    from tests.test_browser_audio_stream import STREAM_AUTH, events

    day, records, writes = install_backend(client, tmp_path)
    session_id = start(client)
    session = client.app.state.demo_sessions.sessions[session_id]

    class InvalidatingSpeech(Speaker):
        def stream(self, text):
            pending = session.tools.pending
            assert pending is not None and not pending["delivery"]
            yield b"first-real-mp3-fixture"
            if invalidated == "expired":
                pending["expires_at"] = 0
            elif invalidated == "replaced":
                session.tools.pending = dict(pending)
            elif invalidated == "changed":
                pending["recap"]["guest_name"] = "Demo Teine"
            elif invalidated == "not_owned":
                session.tools.holds.clear()
            else:
                session.tools._unknown_mutation()
            yield b"last-real-mp3-fixture"

    client.app.state.stack.update(tts=InvalidatingSpeech(), llm_primary=BookingLlm(day))
    done = events(
        client.post(
            "/api/turn",
            headers=STREAM_AUTH,
            json={"session_id": session_id, "text": "Soovin testbroneeringut"},
        )
    )[-1]
    assert not done["tts_failed"]
    assert done["recap_delivery_id"] is None and done["recap_expires_in_s"] is None
    assert session.recap_delivery is None
    if session.tools.pending is not None:
        assert not session.tools.pending["delivery"]
        assert not session.tools.pending["approved"]
    assert not records and not writes


@pytest.mark.parametrize("failure", ["raises", "empty_audio"])
def test_canonical_text_only_recap_can_be_deliberately_read_then_acknowledged(
    client, tmp_path, failure
):
    day, records, writes = install_backend(client, tmp_path)

    class FailedSpeech:
        def synthesize(self, text):
            if failure == "raises":
                raise RuntimeError("PRIVATE provider detail")
            return b""

    client.app.state.stack["tts"] = FailedSpeech()
    session_id = start(client)
    prepared = prepare(client, day, session_id)
    assert prepared["tts_failed"] is True and prepared["audio_b64"] == ""
    assert prepared["fallback_used"] is False
    assert (
        "Live consultation" in prepared["reply"] and "Demo Esimene" in prepared["reply"]
    )
    assert prepared["warnings"] == [{"stage": "tts", "code": "reply_audio_unavailable"}]
    assert "PRIVATE" not in str(prepared)
    state = client.app.state.demo_sessions.sessions[session_id].tools
    assert state.pending is not None and state.pending["delivery"] is False
    client.app.state.stack["tts"] = Speaker()
    result = send(client, session_id, CONSENT, recap_delivery_id=receipt(prepared))
    assert result.status_code == 200, result.text
    assert result.json()["booking_ids"] == ["42"]
    assert len(records) == 1 and writes


@pytest.mark.parametrize("failure", ["raises", "empty_audio"])
def test_failed_ndjson_recap_has_no_playback_receipt(client, tmp_path, failure):
    from tests.test_browser_audio_stream import STREAM_AUTH, events

    day, records, writes = install_backend(client, tmp_path)

    class FailedStream(Speaker):
        def stream(self, text):
            if failure == "raises":
                raise RuntimeError("PRIVATE provider detail")
            yield b""

    client.app.state.stack.update(tts=FailedStream(), llm_primary=BookingLlm(day))
    session_id = start(client)
    response = client.post(
        "/api/turn",
        headers=STREAM_AUTH,
        json={"session_id": session_id, "text": "Soovin testbroneeringut"},
    )
    items = events(response)
    assert [item["type"] for item in items] == ["reply", "done"]
    done = items[-1]
    assert done["tts_failed"] and done["audio_b64"] == ""
    assert done["recap_delivery_id"] is None and done["recap_expires_in_s"] is None
    session = client.app.state.demo_sessions.sessions[session_id]
    assert session.recap_delivery is None and session.tools.pending is None
    assert "PRIVATE" not in response.text
    assert not records and not writes


@pytest.mark.parametrize("fail_step", [0, 1, 2])
def test_failed_model_planning_cannot_offer_a_recap_receipt(
    client, tmp_path, fail_step
):
    day, records, writes = install_backend(client, tmp_path)

    class FailedFollowup(BookingLlm):
        def chat(self, messages, tools=None):
            if self.step == fail_step:
                raise RuntimeError("PRIVATE model detail")
            return super().chat(messages, tools)

    client.app.state.stack["llm_primary"] = FailedFollowup(day)
    session_id = start(client)
    response = send(client, session_id, "Soovin testbroneeringut")
    assert response.status_code == 200
    assert response.json()["fallback_used"] is True
    assert response.json().get("recap_delivery_id") is None
    assert client.app.state.demo_sessions.sessions[session_id].tools.pending is None
    assert not records and not writes
    forged = send(client, session_id, CONSENT, recap_delivery_id="a" * 32)
    assert forged.status_code == 409, forged.text
    assert not records and not writes


def test_canonical_recap_avoids_a_failing_model_followup(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)

    class FailedFollowup(BookingLlm):
        def chat(self, messages, tools=None):
            if self.step == 4:
                raise RuntimeError("PRIVATE model detail")
            return super().chat(messages, tools)

    model = FailedFollowup(day)
    client.app.state.stack["llm_primary"] = model
    session_id = start(client)
    result = send(client, session_id, "Soovin testbroneeringut").json()
    assert model.step == 4 and not result["fallback_used"]
    assert receipt(result)
    state = client.app.state.demo_sessions.sessions[session_id].tools
    assert state.pending and not state.pending["delivery"]
    assert not records and not writes


@pytest.mark.parametrize("value", [None, True, [], "", "a" * 31, "a" * 33, "X" * 32])
def test_receipt_input_is_typed_and_bounded_before_providers(client, value):
    session_id = start(client)
    spoken = list(client.app.state.stack["tts"].spoken)
    response = send(client, session_id, CONSENT, recap_delivery_id=value)
    assert response.status_code == 400
    assert response.json()["detail"] == "recap_delivery_invalid"
    assert not client.app.state.stack["llm_primary"].messages
    assert client.app.state.stack["tts"].spoken == spoken


def test_receipt_cannot_be_used_on_an_isolated_turn(client):
    response = client.post(
        "/api/turn", json={"text": CONSENT, "recap_delivery_id": "a" * 32}, headers=AUTH
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "recap_delivery_requires_session"
    assert not client.app.state.stack["llm_primary"].messages
    assert not client.app.state.stack["tts"].spoken


def test_unknown_receipt_rejects_audio_before_paid_recognition(client):
    recognized = []

    class Stt:
        def transcribe(self, audio, *, language):
            recognized.append(audio)
            return CONSENT

    client.app.state.stack["stt"] = Stt()
    session_id = start(client)
    response = client.post(
        "/api/turn",
        json={
            "session_id": session_id,
            "audio_b64": base64.b64encode(b"RIFF-fixture").decode(),
            "recap_delivery_id": "a" * 32,
        },
        headers=AUTH,
    )
    assert response.status_code == 409
    assert recognized == []
    assert client.app.state.demo_sessions.sessions[session_id].tools._turn_serial == 0


def test_room_http_receipt_preserves_real_persistent_fictional_booking(
    client, tmp_path
):
    adapter = DemoStayAdapter(str(tmp_path / "stays.db"))
    client.app.state.stack.update(stay=adapter, dispatcher=Dispatcher(stay=adapter))
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
    checkin, checkout = day.isoformat(), (day + timedelta(days=2)).isoformat()

    class RoomLlm:
        step = 0

        def chat(self, messages, tools=None):
            if self.step == 0:
                answer = call(
                    "search_availability",
                    {
                        "checkin": checkin,
                        "checkout": checkout,
                        "adults": 2,
                        "room_type": "garden-double",
                    },
                )
            elif self.step == 1:
                offer = json.loads(messages[-1]["content"])["offers"][0]
                answer = call("hold_offer", {"price_quote_id": offer["price_quote_id"]})
            elif self.step == 2:
                self.hold_id = json.loads(messages[-1]["content"])["hold_id"]
                answer = call("prepare_demo_stay", {"hold_id": self.hold_id})
            elif self.step == 4:
                answer = call("confirm_booking", {"hold_id": self.hold_id})
            else:
                answer = {"content": "Tere!"}
            self.step += 1
            return answer

    client.app.state.stack["llm_primary"] = RoomLlm()
    session_id = start(client)
    prepared = send(client, session_id, "Soovin hotellituba.").json()
    assert "Aiavaatega kaheinimesetuba" in prepared["reply"]
    assert checkin in prepared["reply"] and checkout in prepared["reply"]
    assert "258.00 EUR" in prepared["reply"]
    assert client.get("/api/stays", headers=AUTH).json()["items"] == []
    state = client.app.state.demo_sessions.sessions[session_id].tools
    assert state.pending["kind"] == "stay"
    assert state.pending["delivery"] is False and state.pending["approved"] is False
    result = send(client, session_id, CONSENT, recap_delivery_id=receipt(prepared))
    assert result.status_code == 200, result.text
    assert result.json()["outcome"] == "tools_ok"
    booking_id = result.json()["booking_ids"][0]
    assert result.json()["booking_changes"] == [
        {
            "action": "confirmed",
            "id": booking_id,
            "kind": "stay",
            "date": checkin,
            "checkin": checkin,
            "checkout": checkout,
            "timezone": "Europe/Tallinn",
        }
    ]
    assert client.get("/api/stays", headers=AUTH).json()["items"][0]["id"] == booking_id
