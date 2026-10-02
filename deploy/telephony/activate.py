"""Credential-only SIP provisioning; never opens ports or claims a carrier proof.

Run with the pinned media Python. Carrier credentials are environment lookups,
not command arguments or files. A public edge is still an external prerequisite.
"""

import argparse
import asyncio
import ipaddress
import json
from pathlib import Path
import re
import socket
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from deploy.telephony.manage import environment

REQUIRED = (
    "SIP_NUMBER",
    "SIP_ALLOWED_CIDRS",
    "SIP_AUTH_USER",
    "SIP_AUTH_PASSWORD",
    "SIP_PUBLIC_HOST",
)


def edge_declared(host):
    # DNS/public address declaration is NOT reachability. Refuse our HTTP-only
    # dashboard and private/Tailscale destinations before provisioning anything.
    if not host or host.lower().rstrip(".") == "robot.arleserver.cfd":
        return False
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if not re.fullmatch(r"[a-zA-Z0-9.-]{1,253}", host):
            return False
        try:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, 5060, type=socket.SOCK_DGRAM)
            ]
        except (OSError, ValueError):
            return False
    return bool(addresses) and all(address.is_global for address in addresses)


def readiness(env, runtime_ready):
    missing = [name for name in REQUIRED if not env.get(name, "").strip()]
    number_configured = not any(name in missing for name in REQUIRED[:-1])
    if number_configured:
        try:
            from app.sip_setup import specifications

            specifications(env)
        except Exception:
            number_configured = False
    edge = edge_declared(env.get("SIP_PUBLIC_HOST", ""))
    return {
        "private_runtime_ready": runtime_ready,
        "number_credentials_configured": number_configured,
        "public_edge_declared": edge,
        "public_edge_verified": False,
        "carrier_verified": False,
        "inbound_configuration_ready": bool(
            runtime_ready and number_configured and edge
        ),
        "missing_environment": missing,
        "external_gate": "Owner-controlled public SIP/RTP route and independent off-LAN call still required; provisioning does not open ports.",
    }


def runtime_health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8081/", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


async def configure(env):
    from livekit import api
    from app.sip_setup import provision

    async with api.LiveKitAPI(
        url="http://127.0.0.1:7880",
        api_key=env["LIVEKIT_API_KEY"],
        api_secret=env["LIVEKIT_API_SECRET"],
    ) as client:
        await provision(client, env)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "provision"])
    parser.add_argument("--source-container", required=True)
    args = parser.parse_args(argv)
    try:
        env = environment(args.source_container)
        report = readiness(env, runtime_health())
        print(json.dumps(report, sort_keys=True))
        if not report["inbound_configuration_ready"]:
            return 2
        if args.action == "provision":
            asyncio.run(configure(env))
            print(
                "PASS exact-number inbound configuration; no public or carrier verification, no account changes"
            )
        return 0
    except Exception:
        print(
            "FAIL activation prerequisite or operation (sensitive details withheld)",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
