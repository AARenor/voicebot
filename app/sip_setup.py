"""Environment-only, fail-closed DIDWW/SIP provisioning. No purchase or outbound trunk."""

import asyncio
import ipaddress
import os
import re

from livekit import api


def specifications(env=None):
    env = os.environ if env is None else env
    keys = ("SIP_NUMBER", "SIP_ALLOWED_CIDRS", "SIP_AUTH_USER", "SIP_AUTH_PASSWORD")
    if any(not env.get(k, "").strip() for k in keys):
        raise ValueError(
            "exact number, carrier networks and digest credentials required"
        )
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", env["SIP_NUMBER"]):
        raise ValueError("E.164 number required")
    agent_name = env.get("VOICEBOT_AGENT_NAME", "voicebot")
    if not isinstance(agent_name, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,48}", agent_name
    ):
        raise ValueError("valid worker name required")
    networks = [
        ipaddress.ip_network(s.strip(), strict=True)
        for s in env["SIP_ALLOWED_CIDRS"].split(",")
    ]
    if any(n.prefixlen < (24 if n.version == 4 else 64) for n in networks):
        raise ValueError("carrier-specific narrow networks required")
    trunk = api.SIPInboundTrunkInfo(
        name="voicebot-inbound",
        numbers=[env["SIP_NUMBER"]],
        allowed_addresses=[str(n) for n in networks],
        auth_username=env["SIP_AUTH_USER"],
        auth_password=env["SIP_AUTH_PASSWORD"],
    )
    rule = api.SIPDispatchRuleInfo(
        name="voicebot-individual",
        numbers=[env["SIP_NUMBER"]],
        hide_phone_number=True,
        rule=api.SIPDispatchRule(
            dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                room_prefix="voicebot-"
            )
        ),
        room_config=api.RoomConfiguration(
            agents=[api.RoomAgentDispatch(agent_name=agent_name)]
        ),
    )
    trunk.ringing_timeout.FromSeconds(30)
    trunk.max_call_duration.FromSeconds(660)
    return trunk, rule


async def provision(client, env=None):
    trunk, rule = specifications(env)
    trunks = (
        await client.sip.list_sip_inbound_trunk(api.ListSIPInboundTrunkRequest())
    ).items
    existing = [t for t in trunks if t.name == trunk.name]
    if existing:
        if len(existing) != 1:
            raise ValueError("ambiguous managed trunk")
        current = existing[0]
        for field in (
            "numbers",
            "allowed_addresses",
            "auth_username",
            "auth_password",
            "ringing_timeout",
            "max_call_duration",
        ):
            if getattr(current, field) != getattr(trunk, field):
                raise ValueError("existing trunk differs; no automatic overwrite")
        trunk = current
    rules = (
        await client.sip.list_sip_dispatch_rule(api.ListSIPDispatchRuleRequest())
    ).items
    existing_rules = [r for r in rules if r.name == rule.name]
    if len(existing_rules) > 1:
        raise ValueError("ambiguous managed dispatch")
    if not existing and existing_rules:
        # An orphaned managed rule cannot match a newly allocated trunk ID.
        # Reject before mutation rather than leaving a partial new trunk.
        raise ValueError("existing dispatch without matching managed trunk")
    if not existing:
        trunk = await client.sip.create_sip_inbound_trunk(
            api.CreateSIPInboundTrunkRequest(trunk=trunk)
        )
    rule.trunk_ids.append(trunk.sip_trunk_id)
    if existing_rules:
        current = existing_rules[0]
        for field in (
            "trunk_ids",
            "numbers",
            "rule",
            "room_config",
            "hide_phone_number",
        ):
            if getattr(current, field) != getattr(rule, field):
                raise ValueError("existing dispatch differs; no automatic overwrite")
        rule = current
    else:
        rule = await client.sip.create_sip_dispatch_rule(
            api.CreateSIPDispatchRuleRequest(dispatch_rule=rule)
        )
    return trunk.sip_trunk_id, rule.sip_dispatch_rule_id


async def main():
    specifications()
    async with api.LiveKitAPI() as client:
        await provision(client)
    print(
        "PASS: exact-number authenticated trunk and isolated named-worker dispatch configured; not a carrier-call proof"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit(
            "FAIL: SIP provisioning rejected or unavailable (no sensitive response printed)"
        ) from None
