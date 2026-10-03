"""Working-plan questions use verified catalogue data without model prose."""

import base64
from unittest.mock import Mock

import httpx
import pytest

from app.booking.tools import Dispatcher
from app.providers.azure_tts import AzureTtsClient
from tests.test_demo_plan import LiveSlots
from tests.test_product_demo import AUTH, SimpleLlm, send, start
from tests.test_product_demo import client as client


QUESTION = (
    "Mis kell spaateenindaja töötab ja millal on tema lõunapaus? "
    "Palun kontrolli tööplaani."
)


@pytest.mark.parametrize("audio_input", [False, True])
@pytest.mark.parametrize("question", [
    QUESTION, "Palun näita spaa tööaegu, tahaks teada.",
])
def test_spa_hours_are_rendered_from_working_plan_without_model(client, audio_input, question):
    backend = LiveSlots()
    backend.catalogue["providers"][0]["working_hours"] = {
        "monday": {
            "start": "09:00", "end": "17:00",
            "breaks": [{"start": "12:00", "end": "13:00"}],
        },
        "sunday": None,
    }
    model = SimpleLlm(error=AssertionError("hours must not call provider"))
    stt = Mock()
    stt.transcribe.return_value = question
    speech_requests = []

    def azure_response(request):
        if request.url.path.endswith("issueToken"):
            return httpx.Response(200, text="fixture-token")
        speech_requests.append(request.content.decode("utf-8"))
        return httpx.Response(200, content=b"fixture-audio")

    speaker = AzureTtsClient(
        "fixture-key", "northeurope", "et-EE-AnuNeural", "et-EE",
        transport=httpx.MockTransport(azure_response),
    )
    client.app.state.stack.update(
        dispatcher=Dispatcher(slot=backend), llm_primary=model, stt=stt, tts=speaker,
    )
    session = start(client)
    speech_requests.clear()
    payload = {"session_id": session, "language": "et"}
    payload.update(
        {"audio_b64": base64.b64encode(b"fixture-speech").decode()}
        if audio_input else {"text": question}
    )
    try:
        response = client.post("/api/turn", json=payload, headers=AUTH)
    finally:
        speaker.close()
    assert response.status_code == 200
    result = response.json()
    assert result["outcome"] == "tools_ok" and result["warnings"] == []
    assert not result["fallback_used"] and result["tools_used"] == 1
    assert "Backend therapist" in result["reply"]
    assert "09:00–17:00" in result["reply"] and "paus" in result["reply"]
    for value in ("9", "17", "12", "13", "suletud"):
        assert value in result["reply"]
    assert result["timings_ms"]["llm"] == 0 and not model.messages
    assert result["booking_ids"] == result["booking_changes"] == []
    assert backend.calls == [("catalogue", {})]
    assert base64.b64decode(result["audio_b64"]) == b"fixture-audio"
    assert len(speech_requests) == 1
    assert "9 kuni kell 17" in speech_requests[0]
    assert "12 kuni kell 13" in speech_requests[0]
    assert result["input_status"] == ("recognized" if audio_input else "typed")


def test_failed_hours_read_is_closed_without_provider_or_booking(client):
    backend = LiveSlots()

    async def failed():
        raise RuntimeError("PRIVATE backend exception")

    backend.get_slot_catalogue = failed
    model = SimpleLlm(error=AssertionError("error must not call provider"))
    client.app.state.stack.update(dispatcher=Dispatcher(slot=backend), llm_primary=model)
    result = send(client, start(client), QUESTION).json()
    assert result["outcome"] == "tools_failed" and result["tools_used"] == 1
    assert not result["booking_changes"] and not model.messages
    assert result["timings_ms"]["llm"] == 0
    assert "PRIVATE" not in str(result)
