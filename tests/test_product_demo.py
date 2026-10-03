"""Session-owned HTTP demo through the same native ownership/consent gates."""

import base64
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.booking.easyappointments import EasyAppointmentsAdapter
from app.booking.tools import Dispatcher
from app.providers.errors import ProviderError
from app.server import create_app
from app.telephone import CONSENT_TEXT

AUTH = {"Authorization": "Bearer fixture-operator"}
CONSENT = "Jah, kinnitan selle testbroneeringu."
CANCEL = "Palun tühista see testbroneering."


class Speaker:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text):
        self.spoken.append(text)
        return text.encode()


class SimpleLlm:
    def __init__(self, reply="Tere!", error=None):
        self.messages, self.reply, self.error = [], reply, error

    def chat(self, messages, tools=None):
        self.messages.append(messages)
        if self.error:
            raise self.error
        return {"content": self.reply}


@pytest.fixture
def client(monkeypatch):
    from app import callslog

    with patch.dict("os.environ", {"OPERATOR_TOKEN": "fixture-operator", "VOICEBOT_BUSINESS_TYPE": "hotel_spa"}, clear=True):
        callslog.reset_default()
        app = create_app()
    monkeypatch.setenv("OPERATOR_TOKEN", "fixture-operator")
    app.state.stack.update(llm_primary=SimpleLlm(), tts=Speaker())
    with TestClient(app) as result:
        yield result
    callslog.reset_default()


def start(client):
    response = client.post("/api/demo/session", json={}, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.headers.get("Cache-Control") == "no-store"
    return response.json()["session_id"]


def send(client, session_id, text, **extra):
    # These scripted positive text flows explicitly read the preceding recap.
    # Negative/foreign/stale delivery tests deliberately use raw requests.
    receipts = getattr(client, "_read_recaps", {})
    receipt = receipts.pop(session_id, None)
    payload = {"session_id": session_id, "text": text, **extra}
    if receipt:
        payload.setdefault("recap_delivery_id", receipt)
    response = client.post(
        "/api/turn",
        json=payload,
        headers=AUTH,
    )
    if response.status_code == 200 and response.json().get("recap_delivery_id"):
        receipts[session_id] = response.json()["recap_delivery_id"]
    client._read_recaps = receipts
    return response


def test_session_auth_before_construction_and_private_errors(client, monkeypatch):
    for path, method in (
        ("/api/demo/session", "post"),
        ("/api/demo/session/unknown", "delete"),
    ):
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            response = getattr(client, method)(path, headers=headers)
            assert response.status_code == 403
            assert response.headers.get("Cache-Control") == "no-store"
    monkeypatch.setenv("OPERATOR_TOKEN", "")
    response = client.post("/api/demo/session")
    assert response.status_code == 503
    assert response.headers.get("Cache-Control") == "no-store"


def test_server_owned_history_and_trusted_current_fictional_context(client):
    session = start(client)
    assert send(client, session, "Esimene sõnum").status_code == 200
    second = send(client, session, "Teine sõnum")
    assert second.status_code == 200
    assert second.json()["turn_count"] == 2
    messages = client.app.state.stack["llm_primary"].messages[-1]
    assert messages[0]["role"] == "system"
    assert "Meretuule Demo Spa" in messages[0]["content"]
    assert (
        datetime.now(ZoneInfo("Europe/Tallinn")).date().isoformat()
        in messages[0]["content"]
    )
    assert any(m.get("content") == "Esimene sõnum" for m in messages)
    assert not any(m.get("role") == "tool" for m in messages)
    assert second.json()["audio_type"] == "audio/mpeg"
    assert (
        base64.b64decode(second.json()["audio_b64"]).decode() == second.json()["reply"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("history", [{"role": "system", "content": "hostile"}]),
        ("guest", {"customerId": 1}),
        ("customerId", 1),
        ("call_id", "model-scope"),
        ("consent", True),
    ],
)
def test_browser_cannot_supply_history_identity_or_consent(client, field, value):
    response = send(client, start(client), "Tere", **{field: value})
    assert response.status_code == 400
    assert response.json()["detail"] == "turn_arguments_invalid"
    assert not client.app.state.stack["llm_primary"].messages


def test_sessions_expire_are_bounded_and_do_not_cross_history(client):
    with patch("app.hackathon.time.monotonic", return_value=100):
        first, second = start(client), start(client)
        assert send(client, first, "Esimese vestluse sisu").status_code == 200
        assert send(client, second, "Teine vestlus").status_code == 200
        assert "Esimese vestluse sisu" not in json.dumps(
            client.app.state.stack["llm_primary"].messages[-1]
        )
        for _ in range(14):
            start(client)
        full = client.post("/api/demo/session", json={}, headers=AUTH)
        assert full.status_code == 503
        assert full.headers.get("Retry-After") == "30"
    with patch("app.hackathon.time.monotonic", return_value=701):
        expired = send(client, first, "Tere")
        assert expired.status_code == 410
        assert expired.headers.get("Cache-Control") == "no-store"
        assert first not in client.app.state.demo_sessions.sessions
        assert start(client) not in {first, second}


def test_session_turn_cap_and_explicit_end(client):
    session = start(client)
    for _ in range(24):
        assert send(client, session, "Tere").status_code == 200
    assert send(client, session, "Tere").status_code == 410
    assert (
        client.delete("/api/demo/session/" + session, headers=AUTH).status_code == 200
    )
    assert send(client, session, "Tere").status_code in (404, 410)


def test_session_busy_denies_overlapping_paid_turns(client):
    entered, release = threading.Event(), threading.Event()

    class Slow(SimpleLlm):
        def chat(self, messages, tools=None):
            entered.set()
            assert release.wait(5)
            return {"content": "Valmis"}

    client.app.state.stack["llm_primary"] = Slow()
    session = start(client)
    replies = []
    thread = threading.Thread(
        target=lambda: replies.append(send(client, session, "Millised spaateenused on saadaval?"))
    )
    thread.start()
    try:
        assert entered.wait(5)
        denied = send(client, session, "Kordus")
        assert denied.status_code == 409
        assert (
            client.delete("/api/demo/session/" + session, headers=AUTH).status_code
            == 409
        )
    finally:
        release.set()
        thread.join(5)
    assert replies[0].status_code == 200


@pytest.mark.parametrize(
    "reply", ["See maksab sada eurot.", "Hind on sada eurot.", "See maksab €120."]
)
def test_safe_speech_normalized_before_tts_and_response_matches_audio(client, reply):
    client.app.state.stack["llm_primary"] = SimpleLlm(reply)
    response = send(client, start(client), "Kui palju spaahooldus maksab?")
    assert response.status_code == 200
    result = response.json()
    from app.booking_faq import load_faq

    assert result["reply"] == next(entry["answer_et"] for entry in load_faq() if entry["id"] == "booking-033")
    assert not client.app.state.stack["llm_primary"].messages
    assert client.app.state.stack["tts"].spoken[-1] == result["reply"]
    assert base64.b64decode(result["audio_b64"]).decode() == result["reply"]


def test_tts_failure_has_text_warning_and_no_secret_or_raw_exception(client):
    class FailingTts:
        def synthesize(self, text):
            raise RuntimeError("PRIVATE provider credential")

    client.app.state.stack["tts"] = FailingTts()
    response = send(client, start(client), "Tere")
    assert response.status_code == 200
    assert response.json()["tts_failed"] is True
    assert response.json()["audio_b64"] == ""
    assert {"stage": "tts", "code": "reply_audio_unavailable"} in response.json()[
        "warnings"
    ]
    assert set(response.json()["timings_ms"]) == {"stt", "llm", "tools", "tts", "total"}
    assert all(value >= 0 for value in response.json()["timings_ms"].values())
    assert "PRIVATE" not in response.text


def test_transcription_failure_reports_the_failed_stage_without_provider_details(
    client,
):
    class FailingStt:
        def transcribe(self, audio):
            raise RuntimeError("PRIVATE transcription credential")

    client.app.state.stack["stt"] = FailingStt()
    response = client.post(
        "/api/turn",
        json={
            "session_id": start(client),
            "audio_b64": base64.b64encode(b"fixture audio").decode(),
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["fallback_used"] is True
    assert {"stage": "stt", "code": "transcription_unavailable"} in response.json()[
        "warnings"
    ]
    assert response.json()["timings_ms"]["stt"] >= 0
    assert "PRIVATE" not in response.text


def test_model_failure_reports_the_failed_stage_and_keeps_a_spoken_reply(client):
    client.app.state.stack["llm_primary"] = SimpleLlm(
        error=RuntimeError("PRIVATE model error")
    )
    response = send(client, start(client), "Millised spaateenused on saadaval?")
    assert response.status_code == 200
    assert {"stage": "llm", "code": "reply_provider_unavailable"} in response.json()[
        "warnings"
    ]
    assert response.json()["reply"]
    assert response.json()["audio_b64"]
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize(
    "reason,status",
    [
        ("rate_limited", 429),
        ("provider_unavailable", 503),
        ("request_rejected", 400),
        ("transport_error", None),
        ("completion_incomplete", 200),
        ("invalid_response", 200),
    ],
)
def test_model_failure_reports_only_closed_provider_diagnostics(client, reason, status):
    error = ProviderError("PRIVATE provider body", reason=reason, status_code=status)
    client.app.state.stack["llm_primary"] = SimpleLlm(error=error)
    response = send(client, start(client), "Millised spaateenused on saadaval?")
    warning = response.json()["warnings"][0]
    assert warning == {
        "stage": "llm",
        "code": "reply_provider_unavailable",
        "cause": reason,
        **({"http_status": status} if status is not None else {}),
    }
    assert "PRIVATE" not in response.text
    assert response.json()["booking_changes"] == []


def test_model_failure_rejects_untrusted_diagnostic_attributes(client):
    error = ProviderError("PRIVATE provider body")
    error.reason = "PRIVATE provider cause"
    error.status_code = "PRIVATE provider status"
    client.app.state.stack["llm_primary"] = SimpleLlm(error=error)
    response = send(client, start(client), "Millised spaateenused on saadaval?")
    assert response.json()["warnings"] == [
        {"stage": "llm", "code": "reply_provider_unavailable"}
    ]
    assert "PRIVATE" not in response.text


def test_model_followup_failure_preserves_cause_after_successful_tool(client):
    class FollowupFailure:
        def chat(self, messages, tools=None):
            if messages[-1]["role"] == "tool":
                raise ProviderError(
                    "PRIVATE followup body", reason="request_rejected", status_code=400
                )
            return call("get_demo_profile", {})

    client.app.state.stack["llm_primary"] = FollowupFailure()
    response = send(client, start(client), "Palun kontrolli demoprofiili.")
    data = response.json()
    assert data["tools_used"] == 1
    assert data["warnings"] == [
        {
            "stage": "llm",
            "code": "reply_provider_unavailable",
            "cause": "request_rejected",
            "http_status": 400,
        }
    ]
    assert data["fallback_used"] is True
    assert data["booking_changes"] == []
    assert "PRIVATE" not in response.text


def call(name, args):
    return {
        "tool_calls": [
            {"id": name, "function": {"name": name, "arguments": json.dumps(args)}}
        ]
    }


def install_backend(client, tmp_path, *, unknown=False, cancel_unknown=False):
    day = (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
    ).isoformat()
    records, writes = [], []

    def handler(request):
        path = request.url.path
        if request.method in ("POST", "DELETE"):
            writes.append(request)
        if path.endswith("/services"):
            return httpx.Response(
                200, json=[{"id": 6, "name": "Live consultation", "duration": 60}]
            )
        if path.endswith("/providers"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 2,
                        "firstName": "Demo",
                        "lastName": "Provider",
                        "services": [6],
                        "timezone": "Europe/Tallinn",
                    }
                ],
            )
        if path.endswith("/availabilities"):
            return httpx.Response(200, json=["10:00"] if not records else [])
        if path.endswith("/services/6"):
            return httpx.Response(200, json={"duration": 60})
        if path.endswith("/customers"):
            return httpx.Response(201, json={"id": 9})
        if path.endswith("/appointments"):
            if request.method == "POST":
                records.append({"id": 42, **json.loads(request.content)})
                if unknown:
                    raise httpx.ReadTimeout("PRIVATE")
                return httpx.Response(201, json={"id": 42})
            return httpx.Response(200, json=records)
        if path.endswith("/appointments/42") and request.method == "DELETE":
            if cancel_unknown:
                raise httpx.ReadTimeout("PRIVATE delete outcome")
            records.clear()
            return httpx.Response(204)
        raise AssertionError("unexpected backend operation")

    adapter = EasyAppointmentsAdapter(
        "https://fixture.invalid",
        "fixture",
        transport=httpx.MockTransport(handler),
        state_db=str(tmp_path / "writer.db"),
        allow_writes=True,
    )
    client.app.state.stack.update(
        slot=adapter, booking_reader=adapter, dispatcher=Dispatcher(slot=adapter)
    )
    return day, records, writes


class BookingLlm:
    def __init__(self, day):
        self.day, self.step, self.hold = day, 0, None
        self.messages = []

    def chat(self, messages, tools=None):
        self.messages.append(messages)
        if self.step == 0:
            answer = call("get_slot_catalogue", {})
        elif self.step == 1:
            answer = call(
                "search_slots", {"service": "6", "provider": "2", "date": self.day}
            )
        elif self.step == 2:
            latest = json.loads(messages[-1]["content"])
            answer = call("hold_slot", {"slot_id": latest["slots"][0]["slotId"]})
        elif self.step == 3:
            self.hold = json.loads(messages[-1]["content"])["hold_id"]
            answer = call("prepare_demo_booking", {"hold_id": self.hold})
        elif self.step == 4:
            answer = {"content": "Kas kinnitad testbroneeringu?"}
        elif self.step == 5:
            assert self.hold in messages[0]["content"], "lost trusted hold context"
            answer = call("confirm_slot_booking", {"hold_id": self.hold})
        elif self.step == 6:
            answer = {"content": "Testbroneering kinnitatud."}
        elif self.step == 7:
            answer = call("cancel_slot_booking", {"booking_id": "42"})
        else:
            answer = {"content": "Testbroneering tühistatud."}
        self.step += 1
        return answer


def test_owned_multiturn_prepare_confirm_read_cancel_and_fixture_alias(
    client, tmp_path
):
    day, records, writes = install_backend(client, tmp_path)
    model = BookingLlm(day)
    client.app.state.stack["llm_primary"] = model
    session = start(client)
    prepare = send(client, session, "Soovin testbroneeringut")
    assert prepare.status_code == 200
    assert not records and not writes
    state = client.app.state.demo_sessions.sessions[session].tools
    assert state.pending["recap"]["start"].startswith(day)
    assert prepare.json()["reply"] == state.render_recap()
    for recap in (
        "Live consultation",
        "Demo Provider",
        "10:00",
        "Demo Esimene",
        CONSENT_TEXT,
    ):
        assert recap in prepare.json()["reply"], "canonical recap was not returned"
    confirmed = send(
        client, session, CONSENT, recap_delivery_id=prepare.json()["recap_delivery_id"]
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["outcome"] == "tools_ok"
    assert records and confirmed.json()["booking_ids"] == ["42"]
    assert confirmed.json()["booking_changes"] == [
        {
            "action": "confirmed",
            "id": "42",
            "date": day,
            "start_local": day + " 10:00",
            "timezone": "Europe/Tallinn",
        }
    ]
    customer = json.loads(
        next(r for r in writes if r.url.path.endswith("/customers")).content
    )
    assert customer["email"].startswith("demo.esimene+") and customer["email"].endswith(
        "@example.invalid"
    )
    assert customer["phone"] == "+12025550101"
    read = client.get("/api/bookings", params={"date": day}, headers=AUTH)
    assert read.status_code == 200 and read.json()["items"][0]["id"] == 42
    assert "customerId" not in read.text
    cancelled = send(client, session, CANCEL)
    assert cancelled.status_code == 200 and cancelled.json()["outcome"] == "tools_ok"
    assert not records
    assert cancelled.json()["booking_changes"][0]["date"] == day
    assert (
        client.get("/api/bookings", params={"date": day}, headers=AUTH).json()["items"]
        == []
    )


def test_generic_http_uses_call_ownership_and_no_unapproved_hotel_faq(client):
    class Attack:
        def chat(self, messages, tools=None):
            assert "Meretuule Demo Spa" in messages[0]["content"]
            assert "answer_faq" not in {t["function"]["name"] for t in tools}
            if messages[-1]["role"] != "tool":
                return call(
                    "confirm_slot_booking",
                    {"hold_id": "foreign", "guest": {"customerId": 1}},
                )
            return {"content": "Toiming keelatud."}

    client.app.state.stack["llm_primary"] = Attack()
    with patch("app.callslog.log_call") as log:
        response = client.post(
            "/api/turn", json={"text": "Millised spaateenused on saadaval?"}, headers=AUTH
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "tools_failed"
    assert log.call_args.args[4] == "tools_failed"
    assert log.call_args.args[3] == "HTTP voice turn"


def test_unknown_write_logged_closed_and_not_automatically_retried(client, tmp_path):
    day, _, writes = install_backend(client, tmp_path, unknown=True)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    session = start(client)
    prepared = send(client, session, "Soovin testbroneeringut")
    assert prepared.status_code == 200

    class Retry:
        def chat(self, messages, tools=None):
            if messages[-1]["role"] != "tool":
                pending = json.loads(
                    messages[0]["content"].split("Server-owned state: ")[-1]
                )
                self.hold = pending["pending"]["hold_id"]
                return call("confirm_slot_booking", {"hold_id": self.hold})
            latest = json.loads(messages[-1]["content"])
            if latest.get("error") == "write_outcome_unknown":
                return call("confirm_slot_booking", {"hold_id": self.hold})
            return {"content": "Tulemus on ebaselge."}

    client.app.state.stack["llm_primary"] = Retry()
    with patch("app.callslog.log_call") as log:
        response = send(
            client,
            session,
            CONSENT,
            recap_delivery_id=prepared.json()["recap_delivery_id"],
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "unknown_outcome"
    assert response.json()["recap_delivery_id"] is None
    assert log.call_args.args[4] == "unknown_outcome"
    assert len([r for r in writes if r.url.path.endswith("/appointments")]) == 1
    assert "PRIVATE" not in response.text


def test_root_image_copies_fictional_demo_fixture():
    assert (
        "COPY data/demo/ ./data/demo/"
        in (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    )


def test_session_is_bound_to_authenticated_operator_credential(client, monkeypatch):
    session = start(client)
    monkeypatch.setenv("OPERATOR_TOKEN", "rotated-fixture")
    response = client.post(
        "/api/turn",
        json={"session_id": session, "text": "Tere"},
        headers={"Authorization": "Bearer rotated-fixture"},
    )
    assert response.status_code == 403
    assert response.headers.get("Cache-Control") == "no-store"


def test_audio_transcript_is_server_observed_before_model_confirmation(
    client, tmp_path
):
    day, records, _ = install_backend(client, tmp_path)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    session = start(client)
    prepared = send(client, session, "Soovin testbroneeringut")
    assert prepared.status_code == 200

    class Stt:
        def transcribe(self, audio, *, language):
            assert audio == b"RIFF-fixture"
            assert language == "auto"
            return CONSENT

    client.app.state.stack["stt"] = Stt()
    response = client.post(
        "/api/turn",
        json={
            "session_id": session,
            "audio_b64": base64.b64encode(b"RIFF-fixture").decode(),
            "recap_delivery_id": prepared.json()["recap_delivery_id"],
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["text_heard"] == CONSENT
    assert records


def test_uncertain_cancellation_is_not_logged_as_success(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path, cancel_unknown=True)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    session = start(client)
    prepared = send(client, session, "Soovin testbroneeringut")
    assert prepared.status_code == 200
    assert (
        send(
            client,
            session,
            CONSENT,
            recap_delivery_id=prepared.json()["recap_delivery_id"],
        ).status_code
        == 200
    )
    with patch("app.callslog.log_call") as log:
        response = send(client, session, CANCEL)
    assert response.status_code == 200
    assert response.json()["outcome"] == "unknown_outcome"
    assert response.json()["booking_changes"] == []
    assert records and len([r for r in writes if r.method == "DELETE"]) == 1
    assert log.call_args.args[4] == "unknown_outcome"
    assert "PRIVATE" not in response.text


def test_unknown_mutation_survives_failed_model_followup_in_response_and_log(
    client, tmp_path
):
    day, _, writes = install_backend(client, tmp_path, unknown=True)
    model = BookingLlm(day)
    client.app.state.stack["llm_primary"] = model
    session = start(client)
    prepared = send(client, session, "Soovin testbroneeringut")
    assert prepared.status_code == 200

    class FailingFollowup:
        def chat(self, messages, tools=None):
            if messages[-1]["role"] == "tool":
                raise RuntimeError("PRIVATE followup failure")
            return call("confirm_slot_booking", {"hold_id": model.hold})

    client.app.state.stack["llm_primary"] = FailingFollowup()
    with patch("app.callslog.log_call") as log:
        response = send(
            client,
            session,
            CONSENT,
            recap_delivery_id=prepared.json()["recap_delivery_id"],
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "unknown_outcome"
    assert response.json()["tools_used"] == 1
    assert log.call_args.args[4] == "unknown_outcome"
    assert len([r for r in writes if r.url.path.endswith("/appointments")]) == 1
    assert "PRIVATE" not in response.text


def test_unexpected_private_error_is_closed_and_no_store(client):
    with TestClient(client.app, raise_server_exceptions=False) as guarded:
        with patch(
            "app.hackathon.run_demo_turn",
            side_effect=RuntimeError("PRIVATE internal failure"),
        ):
            response = guarded.post("/api/turn", json={"text": "Tere"}, headers=AUTH)
    assert response.status_code == 500
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.json()["detail"] == "private_operation_failed"
    assert "PRIVATE" not in response.text


def test_existing_operator_mutations_also_never_cache_auth_errors(client):
    for path in (
        "/api/reset",
        "/api/holds/foreign/confirm",
        "/api/holds/foreign/cancel",
    ):
        response = client.post(path)
        assert response.status_code == 403
        assert response.headers.get("Cache-Control") == "no-store"


def test_model_cannot_announce_a_booking_without_a_write(client):
    client.app.state.stack["llm_primary"] = SimpleLlm("Testbroneering on kinnitatud.")
    response = send(client, start(client), "Soovin testbroneeringut").json()
    assert response["reply"] != "Testbroneering on kinnitatud."
    assert response["booking_ids"] == []
    assert response["booking_changes"] == []
    assert client.app.state.stack["tts"].spoken[-1] == response["reply"]


def test_http_advertises_compact_native_conversation_tools(client, tmp_path):
    install_backend(client, tmp_path)
    observed = {}

    class Probe(SimpleLlm):
        def chat(self, messages, tools=None):
            observed["names"] = {tool["function"]["name"] for tool in tools}
            observed["instructions"] = messages[0]["content"]
            return {"content": "Tere!"}

    client.app.state.stack["llm_primary"] = Probe()
    assert send(client, start(client), "Millised spaateenused on saadaval?").status_code == 200
    assert "plan_demo_booking" in observed["names"]
    assert "search_slots" in observed["names"]
    assert "get_slot_catalogue" in observed["names"]
    assert "plan_demo_booking" in observed["instructions"]


def test_failed_preparation_turn_does_not_arm_later_consent(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)

    class Premature(BookingLlm):
        def chat(self, messages, tools=None):
            if self.step == 0:
                self.step = 2
                return {
                    "tool_calls": call("get_slot_catalogue", {})["tool_calls"]
                    + call(
                        "search_slots",
                        {"service": "6", "provider": "2", "date": self.day},
                    )["tool_calls"]
                }
            if self.step == 3:
                self.hold = json.loads(messages[-1]["content"])["hold_id"]
                self.step = 5
                # Terminal recaps now skip model follow-up. A premature write
                # can still be attempted in the same model tool-call batch.
                return {
                    "tool_calls": call("prepare_demo_booking", {"hold_id": self.hold})[
                        "tool_calls"
                    ]
                    + call("confirm_slot_booking", {"hold_id": self.hold})["tool_calls"]
                }
            if self.step >= 5:
                self.step += 1
                if messages[-1]["role"] != "tool":
                    return call("confirm_slot_booking", {"hold_id": self.hold})
                return {"content": "Testbroneering on kinnitatud."}
            return super().chat(messages, tools)

    client.app.state.stack["llm_primary"] = Premature(day)
    session = start(client)
    prepared = send(client, session, "Soovin testbroneeringut").json()
    assert prepared["outcome"] == "tools_failed"
    assert prepared["recap_delivery_id"] is None
    assert not records and not writes
    confirmed = send(client, session, CONSENT).json()
    assert not records and not writes, "undelivered recap authorized a write"
    assert confirmed["booking_changes"] == []


def test_failed_recap_synthesis_without_explicit_read_ack_cannot_arm_consent(
    client, tmp_path
):
    day, records, writes = install_backend(client, tmp_path)
    client.app.state.stack["llm_primary"] = BookingLlm(day)

    class FailingTts:
        def synthesize(self, text):
            raise RuntimeError("PRIVATE unavailable")

    client.app.state.stack["tts"] = FailingTts()
    session = start(client)
    assert send(client, session, "Soovin testbroneeringut").json()["tts_failed"] is True
    client.app.state.stack["tts"] = Speaker()
    result = client.post(
        "/api/turn", json={"session_id": session, "text": CONSENT}, headers=AUTH
    ).json()
    assert not records and not writes
    assert result["booking_changes"] == []


def test_cancelled_confirmation_replay_has_no_new_success_metadata(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)
    model = BookingLlm(day)
    client.app.state.stack["llm_primary"] = model
    session = start(client)
    prepared = send(client, session, "Soovin testbroneeringut")
    assert prepared.status_code == 200
    assert (
        send(
            client,
            session,
            CONSENT,
            recap_delivery_id=prepared.json()["recap_delivery_id"],
        ).json()["booking_changes"][0]["action"]
        == "confirmed"
    )
    assert (
        send(client, session, CANCEL).json()["booking_changes"][0]["action"]
        == "cancelled"
    )
    assert not records
    count = len(writes)

    class Replay:
        def chat(self, messages, tools=None):
            if messages[-1]["role"] != "tool":
                return call("confirm_slot_booking", {"hold_id": model.hold})
            return {"content": "Testbroneering on kinnitatud."}

    client.app.state.stack["llm_primary"] = Replay()
    result = send(client, session, "Ei, ära kinnita.").json()
    assert result["booking_changes"] == []
    assert result["reply"] != "Testbroneering on kinnitatud."
    assert not records and len(writes) == count
