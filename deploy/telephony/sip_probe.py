"""Private synthetic SIP digest/dispatch/RTP probe; never dials the public network."""

import asyncio
import audioop
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import select
import socket
import struct
import subprocess
import sys
import time
import uuid
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from livekit import api
from app.sip_setup import specifications
from app.providers.groq import GroqClient


def md5(value):
    return hashlib.md5(value.encode()).hexdigest()


def invite(host, local, number, user, password, authenticated=True, reject=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((local, 0))
    sock.settimeout(35 if reject else 15)
    rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtp.bind((local, 0))
    rtp.settimeout(25)
    uri = f"sip:{number}@{host}:5060"
    call = uuid.uuid4().hex
    tag = uuid.uuid4().hex[:12]
    remote_to = f"<{uri}>"
    sdp = (
        f"v=0\r\no=probe 1 1 IN IP4 {local}\r\ns=synthetic\r\nc=IN IP4 {local}\r\nt=0 0\r\n"
        f"m=audio {rtp.getsockname()[1]} RTP/AVP 0 8 101\r\na=rtpmap:0 PCMU/8000\r\n"
        "a=rtpmap:8 PCMA/8000\r\na=rtpmap:101 telephone-event/8000\r\na=sendrecv\r\n"
    )

    def send(method, seq, auth="", body="", to=None, target=None):
        target = target or uri
        headers = (
            f"{method} {target} SIP/2.0\r\nVia: SIP/2.0/UDP {local}:{sock.getsockname()[1]};branch=z9hG4bK{uuid.uuid4().hex};rport\r\n"
            f"From: <sip:+15555550101@{local}>;tag={tag}\r\nTo: {to or remote_to}\r\n"
            f"Call-ID: {call}\r\nCSeq: {seq} {method}\r\n"
            f"Contact: <sip:probe@{local}:{sock.getsockname()[1]}>\r\nMax-Forwards: 10\r\n"
            f"{auth}Content-Type: application/sdp\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        )
        sock.sendto(headers.encode(), (host, 5060))

    def response():
        while True:
            try:
                raw = sock.recv(65536).decode(errors="replace")
            except TimeoutError:
                if reject:
                    return 0, ""
                raise
            status = int(raw.split()[1])
            print("SIP response status:", status, flush=True)
            if status >= 200:
                return status, raw

    try:
        send("INVITE", 1, body=sdp)
        status, raw = response()
        if reject and status in (0, 403, 404):
            return {"wrong_number_unanswered": True}
        assert status in (401, 407), "inbound call was not digest-challenged"
        if not authenticated:
            return {"unauthenticated_challenged": True}
        values = dict(re.findall(r'(\w+)="([^"]+)"', raw))
        realm, nonce = values["realm"], values["nonce"]
        send("ACK", 1)
        cnonce, nc = uuid.uuid4().hex, "00000001"
        ha1, ha2 = md5(f"{user}:{realm}:{password}"), md5("INVITE:" + uri)
        qop = "auth" if "qop=" in raw else ""
        digest = (
            md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")
            if qop
            else md5(f"{ha1}:{nonce}:{ha2}")
        )
        auth = (
            f'{"Proxy-Authorization" if status == 407 else "Authorization"}: Digest username="{user}", realm="{realm}", '
            f'nonce="{nonce}", uri="{uri}", response="{digest}", algorithm=MD5'
            + (f', qop=auth, nc={nc}, cnonce="{cnonce}"' if qop else "")
            + "\r\n"
        )
        send("INVITE", 2, auth=auth, body=sdp)
        status, raw = response()
        if reject:
            assert status in (0, 403, 404), "wrong-number call was not rejected"
            return {"wrong_number_unanswered": True}
        assert status == 200, f"authenticated INVITE rejected: {status}"
        print("SIP stage: authenticated INVITE answered (200)")
        remote_to = re.search(r"^To:\s*(.+)", raw, re.M | re.I).group(1).strip()
        contact = re.search(r"^Contact:\s*<([^>]+)>", raw, re.M | re.I)
        target = contact.group(1) if contact else uri
        send("ACK", 2, to=remote_to, target=target)
        remote_rtp = int(re.search(r"^m=audio\s+(\d+)", raw, re.M).group(1))
        # Establish symmetric RTP from the caller endpoint; never contact a
        # public target. PCMU silence is standard payload 0 at 8 kHz/20 ms.
        packets = 0
        voiced = 0
        decoded = []
        seq = 0
        deadline = time.monotonic() + 25
        while voiced < 100 and time.monotonic() < deadline:
            rtp.sendto(
                struct.pack("!BBHII", 0x80, 0, seq, seq * 160, 123456) + b"\xff" * 160,
                (host, remote_rtp),
            )
            seq += 1
            if select.select([rtp], [], [], 0.02)[0]:
                packet, peer = rtp.recvfrom(2048)
                if len(packet) < 12:
                    continue
                payload_type = packet[1] & 127
                if (
                    peer == (host, remote_rtp)
                    and len(packet) > 12
                    and packet[0] >> 6 == 2
                    and payload_type in (0, 8)
                ):
                    packets += 1
                    offset = 12 + 4 * (packet[0] & 15)
                    if packet[0] & 16:
                        offset += (
                            4
                            + 4
                            * struct.unpack("!H", packet[offset + 2 : offset + 4])[0]
                        )
                    pcm = (audioop.ulaw2lin if payload_type == 0 else audioop.alaw2lin)(
                        packet[offset:], 2
                    )
                    decoded.append(pcm)
                    if audioop.rms(pcm, 2) > 200:
                        voiced += 1
        send("BYE", 3, to=remote_to, target=target)
        while True:
            status, raw = response()
            if re.search(r"^CSeq:\s*3 BYE", raw, re.M | re.I):
                assert status == 200, "BYE failed"
                break
        assert voiced >= 100, "no voiced greeting RTP"
        return {
            "digest_authenticated": True,
            "sip_answered": True,
            "received_rtp_packets": packets,
            "decoded_voiced_packets": voiced,
            "bye_acknowledged": True,
            "_pcm": b"".join(decoded),
        }
    finally:
        sock.close()
        rtp.close()


async def main():
    inspected = json.loads(
        subprocess.check_output(
            ["docker", "inspect", "livekit-worker-1", "livekit-sip-1"]
        )
    )
    env = dict(v.split("=", 1) for v in inspected[0]["Config"]["Env"] if "=" in v)
    network = inspected[1]["NetworkSettings"]["Networks"]["coolify"]
    host, local = network["IPAddress"], network["Gateway"]
    config = {
        "SIP_NUMBER": "+15555550100",
        "SIP_ALLOWED_CIDRS": local + "/32",
        "SIP_AUTH_USER": "loopback-probe",
        "SIP_AUTH_PASSWORD": secrets.token_urlsafe(32),
    }
    trunk, rule = specifications(config)
    suffix = uuid.uuid4().hex
    trunk.name = "voicebot-probe-" + suffix
    rule.name = trunk.name
    rule.rule.dispatch_rule_individual.room_prefix = trunk.name + "-"
    trunk_id = rule_id = None
    observer = None
    async with api.LiveKitAPI(
        url="http://127.0.0.1:7880",
        api_key=env["LIVEKIT_API_KEY"],
        api_secret=env["LIVEKIT_API_SECRET"],
    ) as lk:
        try:
            before = {
                r.name for r in (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
            }
            created = await lk.sip.create_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(trunk=trunk)
            )
            trunk_id = created.sip_trunk_id
            rule.trunk_ids.append(trunk_id)
            created_rule = await lk.sip.create_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(dispatch_rule=rule)
            )
            rule_id = created_rule.sip_dispatch_rule_id
            negative = await asyncio.to_thread(
                invite,
                host,
                local,
                config["SIP_NUMBER"],
                config["SIP_AUTH_USER"],
                config["SIP_AUTH_PASSWORD"],
                False,
            )
            after = {
                r.name for r in (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
            }
            assert after == before, "unauthenticated INVITE dispatched a room"

            async def observe_worker():
                for _ in range(120):
                    rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
                    for room in rooms:
                        if room.name not in before and room.name.startswith(
                            trunk.name + "-"
                        ):
                            participants = (
                                await lk.room.list_participants(
                                    api.ListParticipantsRequest(room=room.name)
                                )
                            ).participants
                            if any(
                                p.kind == api.ParticipantInfo.AGENT
                                for p in participants
                            ) and any(
                                p.kind == api.ParticipantInfo.SIP for p in participants
                            ):
                                return room.name
                    await asyncio.sleep(0.25)
                raise TimeoutError("no isolated SIP/agent room")

            observer = asyncio.create_task(observe_worker())
            positive = await asyncio.to_thread(
                invite,
                host,
                local,
                config["SIP_NUMBER"],
                config["SIP_AUTH_USER"],
                config["SIP_AUTH_PASSWORD"],
            )
            observed_room = await observer
            for _ in range(60):
                rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
                if not any(r.name == observed_room for r in rooms):
                    break
                await asyncio.sleep(0.25)
            assert not any(r.name == observed_room for r in rooms), (
                "call room remained after BYE"
            )
            positive["isolated_sip_agent_room_verified"] = True
            positive["call_room_teardown_verified"] = True
            wrong_dispatched = asyncio.Event()
            negative_done = asyncio.Event()

            async def observe_negative():
                while not negative_done.is_set():
                    rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
                    if any(r.name.startswith(trunk.name + "-") for r in rooms):
                        wrong_dispatched.set()
                    await asyncio.sleep(0.25)

            negative_observer = asyncio.create_task(observe_negative())
            wrong = await asyncio.to_thread(
                invite,
                host,
                local,
                "+15555550199",
                config["SIP_AUTH_USER"],
                config["SIP_AUTH_PASSWORD"],
                True,
                True,
            )
            negative_done.set()
            await negative_observer
            assert not wrong_dispatched.is_set(), "wrong number dispatched a room"
            rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
            assert not any(r.name.startswith(trunk.name + "-") for r in rooms), (
                "wrong number dispatched a room"
            )
            wrong["wrong_number_no_dispatch_verified"] = True
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(8000)
                wav.writeframes(positive.pop("_pcm"))
            stt = GroqClient(env["GROQ_API_KEY"])
            try:
                heard = await asyncio.to_thread(
                    stt.transcribe, buffer.getvalue(), "sip-greeting.wav"
                )
                assert "tere" in heard.lower(), "SIP greeting content not verified"
            finally:
                stt.close()
            positive["greeting_content_verified"] = True
            print(
                json.dumps(
                    {
                        "pass": True,
                        **negative,
                        **positive,
                        **wrong,
                        "carrier_verified": False,
                    }
                )
            )
        finally:
            if observer is not None:
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
            try:
                if rule_id:
                    await lk.sip.delete_dispatch_rule(
                        api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=rule_id)
                    )
            finally:
                try:
                    if trunk_id:
                        await lk.sip.delete_trunk(
                            api.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id)
                        )
                finally:
                    rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
                    for room in rooms:
                        if room.name.startswith(trunk.name + "-"):
                            await lk.room.delete_room(
                                api.DeleteRoomRequest(room=room.name)
                            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        raise SystemExit(
            "FAIL synthetic SIP probe: " + type(exc).__name__ + " (details withheld)"
        ) from None
