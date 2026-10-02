# Carrier-facing edge audit — 2026-10-02

Independent read-only host audit for the hackathon build. No credentials, keys,
router/account logins, remote scans, network changes or public exposure.

## Observed

- `ip -brief address show`, `ip -4 route show table main`: Ethernet
  `192.168.18.24/24`, Wi-Fi `192.168.18.6/24`, gateway `192.168.18.1`.
- `ip -6 address show scope global`, `ip -6 route show default`: no public
  physical-interface IPv6 or IPv6 default. Tailscale ULA is not public IPv6.
- Allowlisted SSH directives in `/home/arle/.ssh/config:3–7`: `arleserver` and
  `arleserver-lan` resolve to this same host's `100.76.78.100`, not a public VPS.
- Sanitized `tailscale status --json`: self on Tailscale, four cached shared
  peers, no established public gateway. Serve/Funnel status both empty.
- Selected `systemctl show` properties: cloudflared and tailscaled active.
  `/srv/ai/README.md:28–32,60–62` describes loopback HTTP origins/tunnel and
  deny-by-default UFW, not carrier-facing SIP/RTP.
- Networking-only Docker inspection: current canonical deployment is
  `deploy/telephony/compose.yaml`. Host publications: SIP TCP/UDP 5060,
  LiveKit API 7880 and worker health 8081 on **127.0.0.1 only**. RTC/RTP are
  unpublished; internal listeners do not prove Internet reachability.
- Read-only noninteractive sudo UFW/nft/iptables inspection: incoming/routed
  traffic denied, no SIP/RTP allowance. Docker DNAT for SIP/API loopback-only;
  raw-table rules drop non-loopback traffic targeting those publications.

## What is still needed

An owner-controlled inbound-capable home WAN with forwarding/firewall and
correct advertised media address, **or** a confirmed existing UDP-capable public
gateway. Router WAN/public-vs-CGNAT status was not established. A reference-only
VPS archive is not evidence of a running gateway. Cloudflare HTTP tunnels and
private Tailscale addresses are not replacements for the carrier's SIP/RTP path.

The telephone-only public edge needs the chosen SIP transport/port and UDP
**10000–10100**, restricted to actual carrier signaling/media networks. Keep
LiveKit API/RTC, Redis and worker health private. Do not copy the stale wider
range from `/home/arle/livekit/README.md` or expose the private Compose wildcard.

An authorized independent off-LAN probe must prove signaling and bidirectional
media. DNS, an outbound public-IP lookup, localhost health, credentials or a
manual flag do not establish either public ingress or a real carrier call.

No public edge was verified. This is a factual external prerequisite, not a
missing application credential that can be silently filled in by the bot.
