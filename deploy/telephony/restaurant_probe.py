"""Bounded fictional restaurant RTC conversation and independent ledger proof.

Uses real speech providers, not a physical microphone or carrier. Never stores
audio/transcripts. Reads and cleans only reservations bound to its opaque call.
"""

import argparse
import array
import asyncio
from datetime import datetime, timedelta
import gc
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback
import uuid
import wave
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from livekit import api, rtc
from app.providers.azure_tts import AzureTtsClient
from app.languages import CONSENT, spoken_date
from conversation_probe import diagnostic_counts, failure_message
from probe import credentials


OWNED_CODE = """
import asyncio,json,os,re,sqlite3,sys
args=json.loads(sys.argv[1]); scope=args['call_id']
assert re.fullmatch('[a-f0-9]{32}',scope)
path=os.environ.get('RESTAURANT_STATE_DB','/data/restaurant-booking.db')
db=sqlite3.connect('file:'+path+'?mode=ro',uri=True); db.row_factory=sqlite3.Row
try:
 rows=db.execute('SELECT result FROM table_writes WHERE key LIKE ?',('tel-'+scope+'-%',)).fetchall()
 ids=set()
 for row in rows:
  result=json.loads(row['result']); booking=result.get('booking',{})
  if result.get('ok') is True and isinstance(booking,dict):
   value=booking.get('id')
   if isinstance(value,str) and re.fullmatch('table_[a-f0-9]{32}',value):ids.add(value)
 items=[]
 for value in sorted(ids):
  row=db.execute('SELECT id,date,start_time,start,end,party_size,status FROM table_bookings WHERE id=?',(value,)).fetchone()
  assert row is not None
  items.append(dict(row))
finally: db.close()
if args.get('cleanup'):
 from app.booking.demo_table import DemoTableAdapter
 async def clean():
  adapter=DemoTableAdapter(path)
  for item in items:
   if item['status']=='confirmed':
    result=await adapter.cancel(item['id'],'probe-cleanup-'+scope+'-'+item['id'])
    assert result.get('ok') is True
    item['status']='cancelled'
 asyncio.run(clean())
print(json.dumps({'items':items}))
"""


def read_owned(container, call_id, *, cleanup=False):
    if not isinstance(call_id, str) or not re.fullmatch(r"[a-f0-9]{32}", call_id):
        raise ValueError("invalid probe call scope")
    result = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "python",
            "-c",
            OWNED_CODE,
            json.dumps({"call_id": call_id, "cleanup": cleanup}),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError("independent ledger read failed")
    return json.loads(result.stdout)["items"]


def scenario(language, day):
    if language == "en":
        result = {
            "voice": "en-US-GuyNeural",
            "locale": "en-US",
            "request": f"Please reserve a table for four people on {spoken_date(day.isoformat())} at six in the evening.",
            "decline": "No, do not confirm the booking.",
            "cancel": "Please cancel this test booking.",
            "recap_marker": "Fictional test booking:",
        }
    elif language == "et":
        months = (
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
        )
        result = {
            "voice": "et-EE-KertNeural",
            "locale": "et-EE",
            "request": f"Palun laud neljale inimesele {day.day}. {months[day.month - 1]} {day.year} kell kaheksateist.",
            "decline": "Ei, ära kinnita broneeringut.",
            "cancel": "Jah, tühista.",
            "recap_marker": "Fiktiivne testbroneering:",
        }
    elif language == "ru":
        months = (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        )
        result = {
            "voice": "ru-RU-DmitryNeural",
            "locale": "ru-RU",
            "request": f"Пожалуйста, столик на четырёх человек {day.day} {months[day.month - 1]} {day.year} года в восемнадцать часов.",
            "decline": "Нет, не подтверждайте бронирование.",
            "cancel": "Да, отмените.",
            "recap_marker": "Вымышленное тестовое бронирование:",
        }
    else:
        raise ValueError("unsupported probe language")
    return {
        **result,
        "consent": CONSENT[language],
        "expected_time": "18:00",
        "party_size": 4,
    }


async def run(container, env, language="et"):
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=14)
    phrases = scenario(language, day)
    name = "voicebot-restaurant-probe-" + uuid.uuid4().hex
    client = api.LiveKitAPI(
        url="http://127.0.0.1:7880",
        api_key=env["LIVEKIT_API_KEY"],
        api_secret=env["LIVEKIT_API_SECRET"],
    )
    room = rtc.Room()
    source, call_id = None, None
    audio_tasks, replies, inputs = [], [], []
    voiced_frames, last_audio = 0, 0
    tts = AzureTtsClient(
        env["AZURE_SPEECH_KEY"],
        env["AZURE_REGION"],
        phrases["voice"],
        phrases["locale"],
        output_format="riff-24khz-16bit-mono-pcm",
    )

    async def receive(track):
        nonlocal voiced_frames, last_audio
        stream = rtc.AudioStream.from_track(
            track=track, sample_rate=16000, num_channels=1
        )
        try:
            async for event in stream:
                samples = array.array("h", bytes(event.frame.data))
                if sum(float(x) ** 2 for x in samples) / max(1, len(samples)) > 40000:
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
                    if participant and participant.identity == "restaurant-probe"
                    else replies
                ).append(segment.text)

    async def wait_reply(previous, audio):
        deadline = asyncio.get_running_loop().time() + 60
        while asyncio.get_running_loop().time() < deadline:
            if (
                len(replies) > previous
                and voiced_frames > audio + 20
                and asyncio.get_running_loop().time() - last_audio > 1.5
            ):
                return
            await asyncio.sleep(0.5)
        raise AssertionError("no complete spoken reply")

    async def speak(text):
        previous, audio = len(replies), voiced_frames
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

    try:
        await client.room.create_room(
            api.CreateRoomRequest(name=name, departure_timeout=5)
        )
        credential = (
            api.AccessToken(env["LIVEKIT_API_KEY"], env["LIVEKIT_API_SECRET"])
            .with_identity("restaurant-probe")
            .with_grants(api.VideoGrants(room_join=True, room=name))
            .to_jwt()
        )
        await room.connect("ws://127.0.0.1:7880", credential)
        source = rtc.AudioSource(24000, 1, queue_size_ms=100)
        track = rtc.LocalAudioTrack.create_audio_track(
            "fictional-restaurant-caller", source
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
        previous = len(replies)
        await speak(phrases["request"])
        assert any(phrases["recap_marker"] in reply for reply in replies[previous:]), (
            "no spoken canonical recap"
        )
        assert not await asyncio.to_thread(read_owned, container, call_id), (
            "appointment created before consent"
        )
        await speak(phrases["decline"])
        assert not await asyncio.to_thread(read_owned, container, call_id), (
            "decline created an appointment"
        )
        previous = len(replies)
        await speak(phrases["request"])
        assert any(phrases["recap_marker"] in reply for reply in replies[previous:]), (
            "no spoken canonical recap"
        )
        await speak(phrases["consent"])
        items = await asyncio.to_thread(read_owned, container, call_id)
        assert len(items) == 1, "no unique consented booking"
        assert (
            items[0]["date"] == day.isoformat()
            and items[0]["start_time"] == "18:00"
            and items[0]["party_size"] == 4
            and items[0]["status"] == "confirmed"
        ), "independent backend read failed"
        await speak(phrases["cancel"])
        items = await asyncio.to_thread(read_owned, container, call_id)
        assert len(items) == 1 and items[0]["status"] == "cancelled", (
            "spoken cancellation failed"
        )
        print(
            json.dumps(
                {
                    "pass": True,
                    "language": language,
                    "final_input_turns": len(inputs),
                    "spoken_replies": len(replies),
                    "voiced_frames": voiced_frames,
                    "before_consent_empty": True,
                    "decline_no_write": True,
                    "ledger_booking_verified": True,
                    "ledger_cancel_verified": True,
                    "physical_microphone_verified": False,
                    "carrier_verified": False,
                }
            )
        )
    except Exception:
        print(json.dumps({"diagnostics": diagnostic_counts(inputs, replies)}))
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
            except api.TwirpError as error:
                if error.code != "not_found":
                    raise
        finally:
            try:
                if call_id:
                    await asyncio.to_thread(
                        read_owned, container, call_id, cleanup=True
                    )
            finally:
                tts.close()
                await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-container", required=True)
    parser.add_argument("--language", choices=("et", "en", "ru"), default="et")
    args = parser.parse_args()
    failure = None
    try:
        asyncio.run(
            run(
                args.source_container, credentials(args.source_container), args.language
            )
        )
    except Exception as error:
        failure = failure_message(error)
        traceback.clear_frames(error.__traceback__)
    gc.collect()
    if failure:
        raise SystemExit(failure)
