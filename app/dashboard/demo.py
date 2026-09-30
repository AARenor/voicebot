"""Demo in-memory store: holds queue, call log, venue config, metrics.

Shadow-mode semantics: staff confirm/cancel marks the hold in the queue;
real PMS writes happen in Phase 2 drivers. No secrets here — config
carries driver names and masked key fingerprints only.
"""

from __future__ import annotations

import time


def seed() -> dict:
    now = time.time()
    return {
        "holds": [
            {
                "hold_id": "hold_demo_sea12",
                "venue": "Demo Spa",
                "kind": "slot",
                "guest": "Mari Maasikas",
                "service": "Classic massage 60min",
                "slot": "2026-10-01 17:00",
                "quoted_total": None,
                "currency": "EUR",
                "price_quote_id": "slot_demo_1",
                "status": "pending",
                "expires_at": now + 540,
            },
            {
                "hold_id": "hold_demo_mer34",
                "venue": "Demo Hotel",
                "kind": "stay",
                "guest": "Jaan Tamm",
                "service": "Sea-view double, 2026-10-12 → 2026-10-14",
                "slot": "2026-10-12",
                "quoted_total": "€240.00",
                "currency": "EUR",
                "price_quote_id": "quote_demo_1",
                "status": "pending",
                "expires_at": now + 320,
            },
        ],
        "calls": [
            {
                "id": "call_demo_1",
                "at": "2026-09-30 08:12",
                "lang": "et",
                "from": "+372 5••• ••21",
                "summary": "Küsis broneeringu muutmist → hold_demo_mer34",
                "outcome": "hold_created",
            },
            {
                "id": "call_demo_2",
                "at": "2026-09-30 08:40",
                "lang": "et",
                "from": "+372 5••• ••87",
                "summary": "Massaažiaegade küsimine → hold_demo_sea12",
                "outcome": "hold_created",
            },
            {
                "id": "call_demo_3",
                "at": "2026-09-30 09:02",
                "lang": "ru",
                "from": "+372 5••• ••44",
                "summary": "Hinna küsimine ilma pakkumiseta → operaatorile",
                "outcome": "handoff",
            },
        ],
        "config": {
            "venue": "Demo Hotel + Spa",
            "voice_et": "et-EE-AnuNeural (Azure) → PocketTTS-ET → Piper",
            "voice_en_ru": "ElevenLabs v4 Turbo",
            "stt": "Groq Whisper free + TalTech-2604 sidecar",
            "pms": {
                "hotel": "Apaleo (pending keys)",
                "spa": "Easy!Appointments (demo)",
            },
            "did": "+372 (DIDHub $2.50, eu-inbound pinned)",
            "key_fingerprints": {"groq": "••••3f9a", "azure": "••••71c2"},
        },
        "metrics": {
            "resolution_rate": "— (pilot)",
            "ttfb_p50_ms": "—",
            "ttfb_p95_ms": "—",
            "quote_fidelity": "100% (quote-ID gate)",
            "handoff_rate": "1 / 3 demo calls",
        },
    }


STORE: dict = seed()


def reset() -> None:
    global STORE
    STORE = seed()
