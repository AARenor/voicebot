"""Regression tests for reviewer round 1 findings (P0 + P1s).

P0-1: Hold.expired() must return bool; fresh holds retrievable, expired gone.
P1-1: unknown price_quote_id raises UnknownQuoteError (not KeyError).
P1-2: idempotency replay returns recorded result without PMS re-touch.
P1-3: slot/demo holds carry quoted_total=None (no price to utter).
P1-4: ET TTS chain resolves to et-EE voices only, fail closed otherwise.
"""

import asyncio
import sys
import time
import unittest

sys.path.insert(0, "voicebot")

from app.booking.base import Hold, HoldLedger, UnknownQuoteError  # noqa: E402
from app.booking import apaleo, cloudbeds, mews  # noqa: E402
from app import pipeline  # noqa: E402


class TestHoldExpiry(unittest.TestCase):
    def test_fresh_hold_retrievable(self):
        ledger = HoldLedger(ttl_seconds=60)
        hold = ledger.create("q1", "€120", "EUR", {})
        self.assertIsInstance(hold.expired(), bool)
        self.assertFalse(hold.expired())
        self.assertIsNotNone(ledger.get(hold.hold_id))

    def test_expired_hold_gone(self):
        ledger = HoldLedger(ttl_seconds=60)
        hold = ledger.create("q1", "€120", "EUR", {})
        self.assertTrue(hold.expired(now=hold.expires_at + 1))
        ledger._holds[hold.hold_id] = Hold(
            hold.hold_id,
            "q1",
            "€120",
            "EUR",
            time.monotonic() - 1,
            {},
        )
        self.assertIsNone(ledger.get(hold.hold_id))


class TestUnknownQuote(unittest.TestCase):
    def test_stay_adapters_raise_typed(self):
        adapters = [
            apaleo.ApaleoAdapter("id", "s"),
            mews.MewsAdapter("ct", "at", "c", "https://x"),
            cloudbeds.CloudbedsAdapter("k"),
        ]
        for adapter in adapters:
            with self.assertRaises(UnknownQuoteError):
                asyncio.run(adapter.create_hold("nope"))
        with self.assertRaises(LookupError):
            asyncio.run(adapters[0].create_hold("nope"))


class TestIdempotency(unittest.TestCase):
    def test_replay_returns_recorded(self):
        ledger = HoldLedger()
        recorded = {"ok": True, "booking_id": "b1"}
        ledger.record("key-1", recorded)
        self.assertEqual(ledger.check_replay("key-1"), recorded)
        self.assertIsNone(ledger.check_replay("key-2"))

    def test_confirm_replay_short_circuits(self):
        adapter = apaleo.ApaleoAdapter("id", "s")
        adapter._holds.record("k", {"ok": True, "booking_id": "b9"})
        result = asyncio.run(adapter.confirm("whatever", {}, "k"))
        self.assertEqual(result, {"ok": True, "booking_id": "b9"})


class TestSlotHoldsPriceless(unittest.TestCase):
    def test_slot_and_demo_holds_have_no_price(self):
        from app.booking.easyappointments import EasyAppointmentsAdapter
        from app.booking.qloapps import QloAppsAdapter
        from app.booking.zenoti import ZenotiAdapter

        z = asyncio.run(ZenotiAdapter("k").create_hold("slot1"))
        easy = EasyAppointmentsAdapter("http://x", "k")
        easy._slots["slot2"] = {
            "slotId": "slot2",
            "serviceId": "6",
            "providerId": "2",
            "date": "2026-10-01",
            "start": "2026-10-01 17:00",
        }
        e = asyncio.run(easy.create_hold("slot2"))
        q = asyncio.run(QloAppsAdapter("dsn").create_hold("q3"))
        self.assertIsNone(z.quoted_total)
        self.assertIsNone(e.quoted_total)
        self.assertIsNone(q.quoted_total)


class TestEtChain(unittest.TestCase):
    def test_et_chain_passes(self):
        chain = pipeline.build_pipeline("et")["tts"]
        self.assertTrue(all(v.startswith(pipeline.ET_VOICE_ALLOW) for v in chain))

    def test_tampered_chain_fails_closed(self):
        original = pipeline.TTS_ROUTE["et"]
        pipeline.TTS_ROUTE["et"] = ("en-US-Standard-A",)
        try:
            with self.assertRaises(ValueError):
                pipeline.build_pipeline("et")
        finally:
            pipeline.TTS_ROUTE["et"] = original


if __name__ == "__main__":
    unittest.main()
