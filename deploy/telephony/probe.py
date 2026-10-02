"""Headless real-provider room-audio smoke; synthetic data only, no carrier claim."""

import argparse
import array
import asyncio
import io
import gc
import json
from pathlib import Path
import subprocess
import sys
import traceback
import uuid
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from livekit import api, rtc
from app.providers.azure_tts import AzureTtsClient


def credentials(container):
    c = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
    return dict(v.split("=", 1) for v in c["Config"]["Env"] if "=" in v)


async def probe(env, phrase, number, barge_in=False):
    name = "voicebot-probe-" + uuid.uuid4().hex
    key, secret = env["LIVEKIT_API_KEY"], env["LIVEKIT_API_SECRET"]
    client = api.LiveKitAPI(url="http://127.0.0.1:7880", api_key=key, api_secret=secret)
    room = rtc.Room()
    frames, words, input_words = [], [], []
    received = asyncio.Event()
    tasks = []
    source = None
    non_silent_times = []

    async def audio(track):
        stream = rtc.AudioStream.from_track(
            track=track, sample_rate=16000, num_channels=1
        )
        try:
            async for ev in stream:
                frames.append(bytes(ev.frame.data))
                samples = array.array("h", bytes(ev.frame.data))
                if sum(float(s) ** 2 for s in samples) / max(len(samples), 1) > 40000:
                    non_silent_times.append(asyncio.get_running_loop().time())
                    received.set()
        finally:
            await stream.aclose()

    @room.on("track_subscribed")
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(audio(track)))

    @room.on("transcription_received")
    def transcribed(segments, participant, publication):
        for segment in segments:
            if segment.final:
                (
                    input_words
                    if participant and participant.identity == "probe"
                    else words
                ).append(segment.text)

    try:
        await client.room.create_room(
            api.CreateRoomRequest(name=name, departure_timeout=5)
        )
        token = (
            api.AccessToken(key, secret)
            .with_identity("probe")
            .with_grants(api.VideoGrants(room_join=True, room=name))
            .to_jwt()
        )
        await room.connect("ws://127.0.0.1:7880", token)
        source = rtc.AudioSource(24000, 1, queue_size_ms=100)
        track = rtc.LocalAudioTrack.create_audio_track("synthetic-utterance", source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await room.local_participant.publish_track(track, options)
        await client.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name="voicebot", room=name)
        )
        await asyncio.wait_for(received.wait(), 45)
        # Wait for the complete AI-demo disclosure before injecting speech.
        if not barge_in:
            await asyncio.sleep(9)
        tts = AzureTtsClient(
            env["AZURE_SPEECH_KEY"],
            env["AZURE_REGION"],
            "et-EE-AnuNeural",
            "et-EE",
            output_format="riff-24khz-16bit-mono-pcm",
        )
        try:
            data = await asyncio.to_thread(tts.synthesize, phrase)
        finally:
            tts.close()
        prior = len(frames)
        started = asyncio.get_running_loop().time()
        with wave.open(io.BytesIO(data), "rb") as wav:
            assert wav.getframerate() == 24000 and wav.getnchannels() == 1
            while chunk := wav.readframes(480):
                await source.capture_frame(
                    rtc.AudioFrame(chunk, 24000, 1, len(chunk) // 2)
                )
        for _ in range(75):
            await source.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480))
        await source.wait_for_playout()
        if barge_in:
            # VAD barge-in must stop the long greeting while the caller speaks;
            # endpointing cannot legitimately start a reply during this window.
            assert not any(
                started + 1.5 < t < started + 2.5 for t in non_silent_times
            ), "greeting did not stop on barge-in"
        for _ in range(40):
            if len(frames) > prior + 50 and input_words and len(words) >= 2:
                break
            await asyncio.sleep(1)
        assert len(frames) > prior + 50, "no reply audio"
        assert input_words, "no final STT proof"
        assert len(words) >= 2, "no reply transcription"
        print(
            json.dumps(
                {
                    "probe": number,
                    "pass": True,
                    "audio_frames": len(frames),
                    "final_input_turns": len(input_words),
                    "spoken_replies": len(words),
                    "isolated_room": True,
                    "carrier_verified": False,
                    "barge_in_verified": barge_in,
                }
            )
        )
    finally:
        try:
            await room.disconnect()
        finally:
            try:
                if source is not None:
                    await source.aclose()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                try:
                    await client.room.delete_room(api.DeleteRoomRequest(room=name))
                except api.TwirpError as exc:
                    if exc.code != "not_found":
                        raise
                finally:
                    await client.aclose()


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-container", required=True)
    p.add_argument("--concurrent", action="store_true")
    p.add_argument("--barge-in", action="store_true")
    args = p.parse_args()
    env = credentials(args.source_container)
    phrases = ["Palun ütle, kas sa oled demoabiline."]
    if args.concurrent:
        phrases.append("Palun vasta lühidalt eesti keeles ja ütle tere.")
    await asyncio.gather(
        *(probe(env, phrase, i + 1, args.barge_in) for i, phrase in enumerate(phrases))
    )
    gc.collect()


if __name__ == "__main__":
    failure = None
    try:
        asyncio.run(main())
    except Exception as exc:
        failure = (
            "FAIL headless room proof: "
            + type(exc).__name__
            + " (sensitive details withheld)"
        )
        traceback.clear_frames(exc.__traceback__)
    gc.collect()
    if failure:
        raise SystemExit(failure)
