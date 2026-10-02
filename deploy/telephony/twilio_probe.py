"""Synthetic signed protocol probe, NEVER a real PSTN/Twilio account API call.

Default: only verify the HTTPS webhook (no paid agent). --media explicitly
dispatches a native agent, sends synthetic silence, and checks returned audio.
Fresh credentials only from environment; no headers/TwiML/audio are printed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import os
import sys
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.twilio_security import Config, MEDIA_URL, NATIVE_AUDIO_MARK, VOICE_URL


def signature(config, url, fields=None):
    data = url + "".join(k + v for k, v in sorted((fields or {}).items()))
    return base64.b64encode(
        hmac.new(config.auth.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()


async def probe(config, *, media=False):
    call, stream = "CA" + uuid.uuid4().hex, "MZ" + uuid.uuid4().hex
    fields = {"AccountSid": config.account, "To": config.phone, "CallSid": call}
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        denied = await client.post(VOICE_URL, data=fields)
        if (
            denied.status_code != 403
            or denied.headers.get("cache-control") != "no-store"
        ):
            raise RuntimeError("probe_auth_gate_failed")
        response = await client.post(
            VOICE_URL,
            data=fields,
            headers={"X-Twilio-Signature": signature(config, VOICE_URL, fields)},
        )
        if (
            response.status_code != 200
            or response.headers.get("cache-control") != "no-store"
            or len(response.content) > 4096
        ):
            raise RuntimeError("probe_webhook_failed")
        root = ET.fromstring(response.content)
        node = root.find("Connect/Stream")
        if node is None or node.get("url") != MEDIA_URL or root.find("Hangup") is None:
            raise RuntimeError("probe_capacity_or_contract_failed")
        parameter = node.find("Parameter")
        if parameter is None or parameter.get("name") != "call_binding":
            raise RuntimeError("probe_binding_missing")
        binding = parameter.get("value")
    if not media:
        return False

    import audioop
    import aiohttp

    start = {
        "event": "start",
        "sequenceNumber": "1",
        "streamSid": stream,
        "start": {
            "accountSid": config.account,
            "callSid": call,
            "streamSid": stream,
            "tracks": ["inbound"],
            "mediaFormat": {
                "encoding": "audio/x-mulaw",
                "sampleRate": 8000,
                "channels": 1,
            },
            "customParameters": {"call_binding": binding},
        },
    }
    connected = {"event": "connected", "protocol": "Call", "version": "1.0.0"}
    headers = {"X-Twilio-Signature": signature(config, MEDIA_URL)}
    sequence, chunk = [1], [0]
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=65)
    ) as session:
        async with session.ws_connect(
            MEDIA_URL, headers=headers, max_msg_size=4096, heartbeat=10
        ) as socket:
            await socket.send_json(connected)
            await socket.send_json(start)
            began = time.monotonic()

            async def silence():
                while time.monotonic() - began < 45:
                    sequence[0] += 1
                    chunk[0] += 1
                    await socket.send_json(
                        {
                            "event": "media",
                            "sequenceNumber": str(sequence[0]),
                            "streamSid": stream,
                            "media": {
                                "track": "inbound",
                                "chunk": str(chunk[0]),
                                "timestamp": str(
                                    int((time.monotonic() - began) * 1000)
                                ),
                                "payload": base64.b64encode(b"\xff" * 160).decode(),
                            },
                        }
                    )
                    await asyncio.sleep(0.02)

            task = asyncio.create_task(silence())
            audible, native_marked = False, False
            try:
                while time.monotonic() - began < 45:
                    message = await socket.receive_json(
                        timeout=max(0.1, 45 - (time.monotonic() - began))
                    )
                    if (
                        message.get("event") == "media"
                        and message.get("streamSid") == stream
                    ):
                        pcm = audioop.ulaw2lin(
                            base64.b64decode(
                                message["media"]["payload"], validate=True
                            ),
                            2,
                        )
                        audible |= audioop.rms(pcm, 2) > 32
                    elif (
                        message.get("event") == "mark"
                        and message.get("streamSid") == stream
                    ):
                        native_marked |= (
                            message.get("mark", {}).get("name") == NATIVE_AUDIO_MARK
                        )
                    if audible and native_marked:
                        break
                else:
                    raise RuntimeError("probe_native_audio_missing")
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                sequence[0] += 1
                if not socket.closed:
                    await socket.send_json(
                        {
                            "event": "stop",
                            "sequenceNumber": str(sequence[0]),
                            "streamSid": stream,
                            "stop": {"accountSid": config.account, "callSid": call},
                        }
                    )
        # Consumed nonce must not create another agent, even after stop.
        async with session.ws_connect(
            MEDIA_URL, headers=headers, max_msg_size=4096
        ) as replay:
            await replay.send_json(connected)
            await replay.send_json(start)
            result = await replay.receive(timeout=5)
            if result.type not in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            ):
                raise RuntimeError("probe_binding_replayed")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--media",
        action="store_true",
        help="explicit paid native-agent audio test; still no carrier phone call",
    )
    parser.add_argument(
        "--source-container",
        help="existing trusted voicebot container; inherit private LiveKit keys only",
    )
    args = parser.parse_args(argv)
    try:
        env = dict(os.environ)
        # Never source missing Twilio values from a container or old credentials.
        if args.source_container and all(
            env.get(name)
            for name in (
                "TWILIO_AUTH_TOKEN",
                "TWILIO_ACCOUNT_SID",
                "TWILIO_PHONE_NUMBER",
            )
        ):
            from deploy.telephony.manage import environment

            inherited = environment(args.source_container)
            for name in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
                env[name] = inherited.get(name, "")
            env["LIVEKIT_URL"] = env.get("LIVEKIT_URL") or "ws://livekit:7880"
        config = Config.from_env(env)
        if config is None:
            print("FAIL: twilio_probe_configuration_missing", file=sys.stderr)
            return 1
        heard = asyncio.run(asyncio.wait_for(probe(config, media=args.media), 75))
        print(
            "PASS: synthetic_native_audio_mark_and_nonce_replay_gate (not a carrier call)"
            if heard
            else "PASS: signed_webhook_only (no paid agent or carrier call)"
        )
        return 0
    except Exception:
        print("FAIL: twilio_probe_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
