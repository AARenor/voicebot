"""Real Estonian room audio -> consent -> Easy REST read/cancel; NOT PSTN.

Requires pinned media Python and running private worker. Uses only call-scoped
fictional contacts; no transcript/audio is written. Cleans only its own data.
"""

import argparse
import array
import asyncio
import gc
from datetime import datetime, timedelta
import io
import json
import re
from pathlib import Path
import sys
import traceback
import uuid
import wave
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import httpx
from livekit import api, rtc
from app.providers.azure_tts import AzureTtsClient
from app.telephone import AFFIRMATIONS, CANCELLATIONS, CONSENT_TEXT
from probe import credentials


def failure_message(exc):
    reason = str(exc)
    if reason not in {
        "missing opaque call scope",
        "no complete spoken reply",
        "no spoken canonical recap",
        "appointment created before consent",
        "decline created an appointment",
        "no unique consented booking",
        "independent backend read failed",
        "spoken cancellation failed",
        "own appointment cleanup failed",
        "own customer cleanup failed",
    }:
        reason = "sensitive details withheld"
    return "FAIL spoken booking probe: " + type(exc).__name__ + " (" + reason + ")"


def diagnostic_counts(inputs, replies):
    # Never print transcripts; distinguish STT/planning/delivery failure by codes.
    normalized = [
        " ".join(re.sub(r"[.,!]", " ", text.casefold()).split()) for text in inputs
    ]
    return {
        "final_input_turns": len(inputs),
        "final_reply_count": len(replies),
        "affirmative_observed": any(text in AFFIRMATIONS for text in normalized),
        "cancellation_observed": any(text in CANCELLATIONS for text in normalized),
        "recap_count": sum("Fiktiivne testbroneering:" in text for text in replies),
        "failed_action_reply_count": sum(
            "Toiming ei õnnestunud" in text for text in replies
        ),
    }


async def records(client, path):
    response = await client.get(path)
    response.raise_for_status()
    return response.json()


async def cleanup_new(client, before_bookings, before_customers, email):
    bookings = await records(client, "/appointments")
    customers = await records(client, "/customers")
    own = {
        c["id"]
        for c in customers
        if c["id"] not in before_customers and c.get("email") == email
    }
    for booking in bookings:
        if booking["id"] not in before_bookings and booking.get("customerId") in own:
            assert (
                await client.delete("/appointments/" + str(booking["id"]))
            ).status_code in (204, 404), "own appointment cleanup failed"
    for customer_id in own:
        assert (await client.delete("/customers/" + str(customer_id))).status_code in (
            204,
            404,
        ), "own customer cleanup failed"


async def run(env):
    name = "voicebot-conversation-" + uuid.uuid4().hex
    client = api.LiveKitAPI(
        url="http://127.0.0.1:7880",
        api_key=env["LIVEKIT_API_KEY"],
        api_secret=env["LIVEKIT_API_SECRET"],
    )
    room = rtc.Room()
    source = None
    audio_tasks = []
    words, inputs = [], []
    voiced_frames = 0
    last_audio = 0

    async def receive(track):
        nonlocal voiced_frames, last_audio
        stream = rtc.AudioStream.from_track(
            track=track, sample_rate=16000, num_channels=1
        )
        try:
            async for event in stream:
                samples = array.array("h", bytes(event.frame.data))
                if sum(float(s) ** 2 for s in samples) / max(1, len(samples)) > 40000:
                    voiced_frames += 1
                    last_audio = asyncio.get_running_loop().time()
        finally:
            await stream.aclose()

    @room.on("track_subscribed")
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_tasks.append(asyncio.create_task(receive(track)))

    @room.on("transcription_received")
    def transcribed(segments, participant, publication):
        for segment in segments:
            if segment.final:
                (
                    inputs
                    if participant and participant.identity == "conversation-probe"
                    else words
                ).append(segment.text)

    tts = AzureTtsClient(
        env["AZURE_SPEECH_KEY"],
        env["AZURE_REGION"],
        # Distinct caller voice. Anu remains the native agent's reply voice;
        # Groq mishears Anu's isolated compound-word cancellation fixture.
        "et-EE-KertNeural",
        "et-EE",
        output_format="riff-24khz-16bit-mono-pcm",
    )

    async def wait_reply(previous, previous_audio):
        for _ in range(120):
            now = asyncio.get_running_loop().time()
            if (
                len(words) > previous
                and voiced_frames > previous_audio + 20
                and now - last_audio > 1.5
            ):
                return
            await asyncio.sleep(0.5)
        raise AssertionError("no complete spoken reply")

    async def speak(text):
        previous, audio = len(words), voiced_frames
        data = await asyncio.to_thread(tts.synthesize, text)
        with wave.open(io.BytesIO(data), "rb") as wav:
            while chunk := wav.readframes(480):
                await source.capture_frame(
                    rtc.AudioFrame(chunk, 24000, 1, len(chunk) // 2)
                )
        for _ in range(75):
            await source.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480))
        await source.wait_for_playout()
        await wait_reply(previous, audio)

    headers = {
        "Authorization": env.get("EASY_AUTH_SCHEME", "Bearer ") + env["EASY_API_KEY"]
    }
    base = "http://127.0.0.1:8088" + env.get("EASY_API_PREFIX", "/index.php/api/v1")
    before_bookings = before_customers = set()
    email = None
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=20) as backend:
        try:
            before_bookings = {b["id"] for b in await records(backend, "/appointments")}
            before_customers = {c["id"] for c in await records(backend, "/customers")}
            await client.room.create_room(
                api.CreateRoomRequest(name=name, departure_timeout=5)
            )
            credential = (
                api.AccessToken(env["LIVEKIT_API_KEY"], env["LIVEKIT_API_SECRET"])
                .with_identity("conversation-probe")
                .with_grants(api.VideoGrants(room_join=True, room=name))
                .to_jwt()
            )
            await room.connect("ws://127.0.0.1:7880", credential)
            source = rtc.AudioSource(24000, 1, queue_size_ms=100)
            track = rtc.LocalAudioTrack.create_audio_track(
                "synthetic-conversation", source
            )
            await room.local_participant.publish_track(
                track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            )
            await client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name="voicebot", room=name)
            )
            await wait_reply(0, 0)
            call_id = next(
                (
                    p.attributes.get("voicebot.call_id")
                    for p in room.remote_participants.values()
                    if p.attributes.get("voicebot.call_id")
                ),
                None,
            )
            assert call_id, "missing opaque call scope"
            email = "demo.esimene+" + call_id + "@example.invalid"
            day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=14)
            while day.weekday() > 4:
                day += timedelta(days=1)
            months = [
                "jaanuaril",
                "veebruaril",
                "märtsil",
                "aprillil",
                "mail",
                "juunil",
                "juulil",
                "augustil",
                "septembril",
                "oktoobril",
                "novembril",
                "detsembril",
            ]
            request = f"Palun broneeri demo spaakonsultatsioon {day.day}. {months[day.month - 1]} {day.year} kell üheksa."
            before_reply = len(words)
            await speak(request)
            assert any(
                "Fiktiivne testbroneering:" in reply for reply in words[before_reply:]
            ), "no spoken canonical recap"
            assert {
                b["id"] for b in await records(backend, "/appointments")
            } == before_bookings, "appointment created before consent"
            await speak("Ei, ära kinnita broneeringut.")
            assert {
                b["id"] for b in await records(backend, "/appointments")
            } == before_bookings, "decline created an appointment"
            before_reply = len(words)
            await speak(request)
            assert any(
                "Fiktiivne testbroneering:" in reply for reply in words[before_reply:]
            ), "no spoken canonical recap"
            await speak(CONSENT_TEXT)
            customers = await records(backend, "/customers")
            own = {c["id"] for c in customers if c.get("email") == email}
            booked = [
                b
                for b in await records(backend, "/appointments")
                if b["id"] not in before_bookings and b.get("customerId") in own
            ]
            assert len(booked) == 1, "no unique consented booking"
            stored = await backend.get("/appointments/" + str(booked[0]["id"]))
            assert (
                stored.status_code == 200 and day.isoformat() in stored.json()["start"]
            ), "independent backend read failed"
            await speak("Jah, tühista.")
            assert (
                await backend.get("/appointments/" + str(booked[0]["id"]))
            ).status_code == 404, "spoken cancellation failed"
            assert len(inputs) >= 5
            print(
                json.dumps(
                    {
                        "pass": True,
                        "final_input_turns": len(inputs),
                        "spoken_replies": len(words),
                        "voiced_frames": voiced_frames,
                        "before_consent_empty": True,
                        "decline_no_write": True,
                        "rest_booking_verified": True,
                        "rest_cancel_verified": True,
                        "carrier_verified": False,
                    }
                )
            )
        except Exception:
            print(json.dumps({"diagnostics": diagnostic_counts(inputs, words)}))
            raise
        finally:
            try:
                await room.disconnect()
                if source:
                    await source.aclose()
                for task in audio_tasks:
                    task.cancel()
                await asyncio.gather(*audio_tasks, return_exceptions=True)
                try:
                    await client.room.delete_room(api.DeleteRoomRequest(room=name))
                except api.TwirpError as exc:
                    if exc.code != "not_found":
                        raise
            finally:
                try:
                    if email:
                        await cleanup_new(
                            backend, before_bookings, before_customers, email
                        )
                finally:
                    tts.close()
                    await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-container", required=True)
    args = parser.parse_args()
    failure = None
    try:
        asyncio.run(run(credentials(args.source_container)))
    except Exception as exc:
        failure = failure_message(exc)
        traceback.clear_frames(exc.__traceback__)
    gc.collect()
    if failure:
        raise SystemExit(failure)
