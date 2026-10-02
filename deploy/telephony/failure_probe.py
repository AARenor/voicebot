"""Isolated invalid-Azure-credential job: verify audible cached fallback over RTC.

Clones the trusted worker environment in memory; never stops the normal worker.
"""

import asyncio
import argparse
import difflib
import gc
import io
import json
from pathlib import Path
import os
import subprocess
import sys
import time
import uuid
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from livekit import api, rtc
from app.providers.groq import GroqClient
from app.telephone import FALLBACK


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drain", action="store_true")
    options = parser.parse_args()
    c = json.loads(subprocess.check_output(["docker", "inspect", "livekit-worker-1"]))[
        0
    ]
    env = dict(v.split("=", 1) for v in c["Config"]["Env"] if "=" in v)
    name = "voicebot-failure-probe-" + uuid.uuid4().hex
    clone_env = {
        **os.environ,
        **env,
        "VOICEBOT_AGENT_NAME": name,
        "AZURE_SPEECH_KEY": "intentionally-invalid-test-fixture",
    }
    if options.drain:
        clone_env["AZURE_SPEECH_KEY"] = env["AZURE_SPEECH_KEY"]
    volume = next(m["Name"] for m in c["Mounts"] if m["Destination"] == "/data")
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "coolify",
        "--init",
        "--mount",
        "type=volume,source=" + volume + ",target=/data",
    ]
    for key in (*env.keys(), "VOICEBOT_AGENT_NAME"):
        args += ["-e", key]
    args += [c["Config"]["Image"]]
    subprocess.run(args, env=clone_env, capture_output=True, check=True)
    room = rtc.Room()
    client = api.LiveKitAPI(
        url="http://127.0.0.1:7880",
        api_key=env["LIVEKIT_API_KEY"],
        api_secret=env["LIVEKIT_API_SECRET"],
    )
    frames, tasks = [], []
    received = asyncio.Event()
    second_room = None

    async def listen(track):
        stream = rtc.AudioStream.from_track(
            track=track, sample_rate=16000, num_channels=1
        )
        try:
            async for ev in stream:
                frames.append(bytes(ev.frame.data))
                if any(ev.frame.data):
                    received.set()
        finally:
            await stream.aclose()

    @room.on("track_subscribed")
    def track(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(listen(track)))

    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["docker", "logs", name], capture_output=True, text=True
            )
            rows = []
            for line in (result.stdout + result.stderr).splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
            if any(r.get("message") == "registered worker" for r in rows):
                break
            await asyncio.sleep(0.25)
        else:
            raise TimeoutError("failure worker not registered")
        await client.room.create_room(api.CreateRoomRequest(name=name))
        jwt = (
            api.AccessToken(env["LIVEKIT_API_KEY"], env["LIVEKIT_API_SECRET"])
            .with_identity("synthetic-failure")
            .with_grants(api.VideoGrants(room_join=True, room=name))
            .to_jwt()
        )
        await room.connect("ws://127.0.0.1:7880", jwt)
        await client.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=name, room=name)
        )
        await asyncio.wait_for(received.wait(), 35)
        if options.drain:
            subprocess.run(
                ["docker", "kill", "--signal=TERM", name],
                capture_output=True,
                check=True,
            )
            await asyncio.sleep(1)
            second_room = name + "-new-job"
            await client.room.create_room(api.CreateRoomRequest(name=second_room))
            await client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=name, room=second_room)
            )
            await asyncio.sleep(2)
            dispatches = await client.agent_dispatch.list_dispatch(second_room)
            assert all(not d.state.jobs for d in dispatches), (
                "new job accepted during drain"
            )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                state = json.loads(
                    subprocess.check_output(["docker", "inspect", name])
                )[0]["State"]
                if not state["Running"]:
                    assert state["ExitCode"] == 0, "worker drain exited uncleanly"
                    break
                await asyncio.sleep(0.25)
            else:
                raise TimeoutError("worker did not drain")
            rooms = (await client.room.list_rooms(api.ListRoomsRequest())).rooms
            assert not any(r.name == name for r in rooms), (
                "call room survived worker drain"
            )
            print(
                "PASS SIGTERM drain: new job rejected, worker exit 0, active call room terminated"
            )
            return
        await asyncio.sleep(7)
        print("Failure probe received PCM bytes:", sum(map(len, frames)))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"".join(frames))
        stt = GroqClient(env["GROQ_API_KEY"])
        try:
            heard = await asyncio.to_thread(
                stt.transcribe, buffer.getvalue(), "failure.wav"
            )
            print(
                "Fallback content check:",
                {
                    word: word in heard.lower()
                    for word in ("vabandust", "saadaval", "hiljem")
                },
                "characters:",
                len(heard),
            )
            similarity = difflib.SequenceMatcher(
                None, FALLBACK.casefold(), heard.casefold()
            ).ratio()
            print("Fallback ASR similarity:", round(similarity, 3))
            # ASR need not spell every word identically after Opus transport.
            assert "saadaval" in heard.lower() and similarity >= 0.8, (
                "wrong failure audio"
            )
        finally:
            stt.close()
        print(
            "PASS forced Azure authentication failure -> independently cached Estonian fallback audible over RTC"
        )
    finally:
        try:
            await room.disconnect()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await client.room.delete_room(api.DeleteRoomRequest(room=name))
            except api.TwirpError as exc:
                if exc.code != "not_found":
                    raise
        finally:
            try:
                if second_room:
                    await client.room.delete_room(
                        api.DeleteRoomRequest(room=second_room)
                    )
            finally:
                try:
                    await client.aclose()
                finally:
                    try:
                        subprocess.run(
                            ["docker", "stop", "-t", "40", name],
                            capture_output=True,
                            check=True,
                        )
                    finally:
                        subprocess.run(
                            ["docker", "rm", name], capture_output=True, check=True
                        )


if __name__ == "__main__":
    failure = None
    try:
        asyncio.run(main())
    except Exception as exc:
        failure = (
            "FAIL forced provider audio proof: "
            + type(exc).__name__
            + " (details withheld)"
        )
    gc.collect()
    if failure:
        raise SystemExit(failure)
