from unittest.mock import patch

from fastapi.testclient import TestClient

from app.server import create_app, build_stack


def test_calls_require_operator_and_never_cache():
    with patch.dict("os.environ", {"OPERATOR_TOKEN": "fixture-operator", "VOICEBOT_BUSINESS_TYPE": "hotel_spa"}, clear=True):
        with TestClient(create_app()) as client:
            for headers, expected in (
                ({}, 403),
                ({"Authorization": "Bearer invalid"}, 403),
                ({"Authorization": "Bearer fixture-operator"}, 200),
            ):
                response = client.get("/api/calls", headers=headers)
                assert response.status_code == expected
                assert response.headers["Cache-Control"] == "no-store"


def test_calls_fail_closed_without_operator():
    with patch.dict("os.environ", {}, clear=True):
        with TestClient(create_app()) as client:
            response = client.get("/api/calls")
            assert response.status_code == 503
            assert response.headers["Cache-Control"] == "no-store"


def test_livekit_requires_complete_credentials():
    with patch.dict(
        "os.environ",
        {"LIVEKIT_URL": "http://localhost:7880", "LIVEKIT_API_KEY": "fixture"},
        clear=True,
    ):
        assert build_stack()["livekit"] is None


def test_config_flags_cannot_claim_carrier_verification():
    with patch.dict("os.environ", {"VOICEBOT_CARRIER_VERIFIED": "1"}, clear=True):
        with TestClient(create_app()) as client:
            status = client.get("/api/status").json()
            assert status["telephone"]["carrier_call_verified"] is False
            assert status["telephone"]["public_ingress_verified"] is False


def test_http_turn_does_not_persist_transcript():
    result = {
        "text_heard": "Guest private@example.test",
        "reply": "Private guest reply",
        "audio": b"fixture",
        "tool_results": [],
        "fallback_used": False,
    }
    with patch.dict("os.environ", {"OPERATOR_TOKEN": "fixture-operator", "VOICEBOT_BUSINESS_TYPE": "hotel_spa"}, clear=True):
        with TestClient(create_app()) as client:
            client.app.state.stack.update(llm_primary=object(), tts=object())
            with (
                patch("app.turn.run_turn", return_value=result),
                patch("app.callslog.log_call") as log,
            ):
                response = client.post(
                    "/api/turn",
                    json={"text": result["text_heard"]},
                    headers={"Authorization": "Bearer fixture-operator"},
                )
                assert response.status_code == 200
                summary = log.call_args.args[3]
                assert summary == "HTTP voice turn"
                assert "private" not in summary.lower()
