"""Local browser integration app with the real routes and fictional providers.

Run with: uvicorn tests.browser_fixture:create_app --factory --port 8765
The token is a public test fixture, not a deployment credential. No external
provider is contacted. The committed MP3 test tone is synthetic audio.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx

from app.booking.demo_stay import DemoStayAdapter
from app.booking.easyappointments import EasyAppointmentsAdapter
from app.booking.tools import Dispatcher
from app.server import create_app as server_app

_storage = tempfile.TemporaryDirectory(prefix="voicebot-browser-")


class FixtureSpeech:
    def transcribe(self, audio):
        return "Tere!"

    def synthesize(self, text):
        return (Path(__file__).parent / "fixtures/speech-tone.mp3").read_bytes()

    def close(self):
        pass


class FixtureLlm:
    def chat(self, messages, tools=None):
        return {"content": "Tere! Kuidas saan aidata?"}


def create_app():
    today = datetime.now(ZoneInfo("Europe/Tallinn")).date()
    records = []

    def provider(request):
        path = request.url.path
        if path.endswith("/services"):
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "Lõõgastav spaakonsultatsioon", "duration": 30}
                ],
            )
        if path.endswith("/providers"):
            plan = {
                key: {
                    "start": "09:00",
                    "end": "17:00",
                    "breaks": [{"start": "12:00", "end": "13:00"}],
                }
                for key in ("monday", "tuesday", "wednesday", "thursday", "friday")
            }
            plan.update(saturday=None, sunday=None)
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 2,
                        "firstName": "Demo",
                        "lastName": "Terapeut",
                        "services": [1],
                        "timezone": "Europe/Tallinn",
                        "settings": {"workingPlan": json.dumps(plan)},
                    }
                ],
            )
        if path.endswith("/services/1"):
            return httpx.Response(200, json={"id": 1, "duration": 30})
        if path.endswith("/availabilities"):
            day = request.url.params.get(
                "date", (today + timedelta(days=1)).isoformat()
            )
            times = ["09:00", "09:30", "10:00", "10:30", "14:00", "15:00"]
            reserved = {
                row["start"].split(" ")[1][:5]
                for row in records
                if row["start"].startswith(day)
            }
            return httpx.Response(
                200, json=[time for time in times if time not in reserved]
            )
        if path.endswith("/customers") and request.method == "POST":
            return httpx.Response(201, json={"id": 10})
        if path.endswith("/appointments"):
            if request.method == "POST":
                record = {
                    "id": 100 + len(records),
                    "status": "Confirmed",
                    **json.loads(request.content),
                }
                records.append(record)
                return httpx.Response(201, json=record)
            day = request.url.params.get("date")
            return httpx.Response(
                200,
                json=[
                    row
                    for row in records
                    if day is None or row["start"].startswith(day)
                ],
            )
        if "/appointments/" in path and request.method == "DELETE":
            booking_id = int(path.rsplit("/", 1)[1])
            records[:] = [row for row in records if row["id"] != booking_id]
            return httpx.Response(204)
        raise AssertionError("unknown fictional provider operation")

    with patch.dict(os.environ, {"OPERATOR_TOKEN": "fixture-operator"}, clear=True):
        app = server_app()
    os.environ["OPERATOR_TOKEN"] = "fixture-operator"
    os.environ["PUBLIC_PHONE_NUMBER"] = "+12025550109"
    slot = EasyAppointmentsAdapter(
        "https://fixture.invalid",
        "fixture",
        transport=httpx.MockTransport(provider),
        state_db=str(Path(_storage.name) / "slots.db"),
        allow_writes=True,
    )
    stay = DemoStayAdapter(str(Path(_storage.name) / "stays.db"))
    speech = FixtureSpeech()
    app.state.stack.update(
        slot=slot,
        booking_reader=slot,
        stay=stay,
        dispatcher=Dispatcher(slot=slot, stay=stay),
        stt=speech,
        tts=speech,
        llm_primary=FixtureLlm(),
    )
    app.state.capabilities.update(
        text_turn_ready=True,
        audio_turn_ready=True,
        slot_booking_ready=True,
        stay_booking_ready=True,
        booking_read_ready=True,
        booking_view_source="easyappointments",
    )
    return app
