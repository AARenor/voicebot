"""Provider + EasyAppointments tests (httpx.MockTransport, no network).

Groq: transcribe text, chat message + tool_calls, 429 retry-after, 500
retryable, list-payload TypeError typed.
Azure: token fetch + cache reuse + refresh, empty-token refetch, 401
force-refresh retry, SSML escaping, 429.
Easy (real openapi.yml shapes): /availabilities string[] -> slot dicts,
confirm builds AppointmentPayload (customer create + service duration),
records + replays idempotently, expired hold = no HTTP, cancel 204/404,
unknown slot typed, 500 retryable.
"""

import asyncio
import json
import sys
import unittest

import httpx

sys.path.insert(0, "voicebot")

from app.booking.easyappointments import EasyAppointmentsAdapter  # noqa: E402
from app.providers.azure_tts import AzureTtsClient, ssml  # noqa: E402
from app.providers.errors import (  # noqa: E402
    ProviderError,
    RateLimitedError,
    RetryableProviderError,
)
from app.providers.groq import GroqClient  # noqa: E402
from app.booking.base import UnknownQuoteError  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TestGroq(unittest.TestCase):
    def client(self, handler):
        return GroqClient("k", transport=httpx.MockTransport(handler))

    def test_transcribe(self):
        def handler(request):
            self.assertIn("/openai/v1/audio/transcriptions", str(request.url))
            return httpx.Response(200, json={"text": "Tere!"})

        self.assertEqual(self.client(handler).transcribe(b"RIFF"), "Tere!")

    def test_chat_with_tools(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "function": {
                                            "name": "search",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )

        msg = self.client(handler).chat(
            [{"role": "user", "content": "hi"}], tools=[{"type": "function"}]
        )
        self.assertEqual(msg["tool_calls"][0]["id"], "c1")

    def test_429_surfaces_retry_after(self):
        def handler(request):
            return httpx.Response(429, headers={"retry-after": "2"})

        with self.assertRaises(RateLimitedError) as ctx:
            self.client(handler).transcribe(b"x")
        self.assertEqual(ctx.exception.retry_after, 2.0)

    def test_500_is_retryable(self):
        def handler(request):
            return httpx.Response(500, text="boom")

        with self.assertRaises(RetryableProviderError):
            self.client(handler).chat([])

    def test_list_payload_typed(self):
        def handler(request):
            return httpx.Response(200, json=["not", "an", "object"])

        with self.assertRaises(ProviderError):
            self.client(handler).transcribe(b"x")


class TestAzureTts(unittest.TestCase):
    def test_token_cached_then_synthesize(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            if "issueToken" in str(request.url):
                return httpx.Response(200, text="tok123")
            self.assertEqual(
                request.headers["X-Microsoft-OutputFormat"],
                "audio-16khz-32kbitrate-mono-mp3",
            )
            self.assertIn("et-EE-AnuNeural", request.content.decode())
            return httpx.Response(200, content=b"AUDIO")

        client = AzureTtsClient(
            "k",
            "northeurope",
            "et-EE-AnuNeural",
            "et-EE",
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(client.synthesize("Tere!"), b"AUDIO")
        self.assertEqual(client.synthesize("Tere jälle!"), b"AUDIO")
        token_calls = [u for u in calls if "issueToken" in u]
        self.assertEqual(len(token_calls), 1)  # cached

    def test_empty_token_refetches(self):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            if "issueToken" in str(request.url):
                # First empty (flaky), then good.
                return httpx.Response(200, text="" if len(seen) == 1 else "tok9")
            return httpx.Response(200, content=b"A")

        client = AzureTtsClient(
            "k",
            "northeurope",
            "et-EE-AnuNeural",
            "et-EE",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(ProviderError):
            client.get_token()
        self.assertEqual(client.synthesize("Tere!"), b"A")
        self.assertEqual(len([u for u in seen if "issueToken" in u]), 2)

    def test_401_refreshes_once(self):
        synth_calls = []

        def handler(request):
            if "issueToken" in str(request.url):
                return httpx.Response(200, text="fresh")
            synth_calls.append(request.headers.get("Authorization"))
            if len(synth_calls) == 1:
                return httpx.Response(401, text="deny")
            return httpx.Response(200, content=b"B")

        client = AzureTtsClient(
            "k",
            "northeurope",
            "et-EE-AnuNeural",
            "et-EE",
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(client.synthesize("Tere!"), b"B")
        self.assertEqual(synth_calls, ["Bearer fresh", "Bearer fresh"])

    def test_429_on_synthesize(self):
        def handler(request):
            if "issueToken" in str(request.url):
                return httpx.Response(200, text="t")
            return httpx.Response(429, headers={"retry-after": "5"})

        client = AzureTtsClient(
            "k",
            "northeurope",
            "et-EE-AnuNeural",
            "et-EE",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(RateLimitedError):
            client.synthesize("Tere!")

    def test_ssml_escapes_guest_text(self):
        out = ssml("Tere <Mari> & co", "et-EE-AnuNeural", "et-EE")
        self.assertIn("Tere &lt;Mari&gt; &amp; co", out)
        self.assertIn("name='et-EE-AnuNeural'", out)


class TestEasyAppointments(unittest.TestCase):
    def adapter(self, handler):
        return EasyAppointmentsAdapter(
            "https://spa.example", "k", transport=httpx.MockTransport(handler)
        )

    def test_search_slots_real_shape(self):
        def handler(request):
            self.assertIn("/api/v1/availabilities", str(request.url))
            self.assertEqual(request.url.params["serviceId"], "6")
            return httpx.Response(200, json=["17:00", "18:00"])

        slots = run(self.adapter(handler).search_slots("6", "2026-10-01", provider="2"))
        self.assertEqual(slots[0]["slotId"], "6|2|2026-10-01 17:00")
        self.assertEqual(slots[0]["start"], "2026-10-01 17:00")

    def test_confirm_builds_appointment_payload(self):
        bodies = []

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00", "18:00"])
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments"):
                bodies.append(json.loads(request.content))
                return httpx.Response(201, json={"id": 42})
            raise AssertionError(f"unexpected {url}")

        adapter = self.adapter(handler)
        slots = run(adapter.search_slots("6", "2026-10-01", provider="2"))
        hold = run(adapter.create_hold(slots[0]["slotId"]))
        result = run(
            adapter.confirm(hold.hold_id, {"customerId": 5, "notes": "palun"}, "idem-1")
        )
        self.assertTrue(result["ok"])
        self.assertEqual(bodies[0]["customerId"], 5)
        self.assertEqual(bodies[0]["serviceId"], 6)
        self.assertEqual(bodies[0]["providerId"], 2)
        self.assertEqual(bodies[0]["start"], "2026-10-01 17:00:00")
        self.assertEqual(bodies[0]["end"], "2026-10-01 18:00:00")
        self.assertEqual(bodies[0]["status"], "Booked")
        # Replay: no second POST.
        second = run(adapter.confirm(hold.hold_id, {"customerId": 5}, "idem-1"))
        self.assertEqual(second, result)
        posts = [b for b in bodies]
        self.assertEqual(len(posts), 1)

    def test_confirm_creates_customer_when_missing(self):
        seen = []

        def handler(request):
            url = str(request.url.path)
            seen.append(url)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 30})
            if url.endswith("/appointments"):
                return httpx.Response(201, json={"id": 43})
            raise AssertionError(f"unexpected {url}")

        adapter = self.adapter(handler)
        slots = run(adapter.search_slots("6", "2026-10-01"))
        hold = run(adapter.create_hold(slots[0]["slotId"]))
        result = run(
            adapter.confirm(hold.hold_id, {"firstName": "Mari", "phone": "+372"}, "k2")
        )
        self.assertTrue(result["ok"])
        self.assertTrue(any(u.endswith("/customers") for u in seen))

    def test_confirm_expired_hold(self):
        def handler(request):  # pragma: no cover
            raise AssertionError("must not touch HTTP")

        adapter = self.adapter(handler)
        result = run(adapter.confirm("ghost", {}, "k"))
        self.assertEqual(result["error"], "hold_expired_or_unknown")

    def test_unknown_slot_typed(self):
        adapter = self.adapter(lambda r: httpx.Response(200, json=[]))
        with self.assertRaises(UnknownQuoteError):
            run(adapter.create_hold("bogus"))

    def test_cancel_204_and_404(self):
        def handler_204(request):
            return httpx.Response(204)

        adapter = self.adapter(handler_204)
        self.assertTrue(run(adapter.cancel("42", "c1"))["ok"])

        def handler_404(request):
            return httpx.Response(404, text="gone")

        adapter2 = self.adapter(handler_404)
        result = run(adapter2.cancel("42", "c2"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["already_gone"])

    def test_pending_blocks_double_submit(self):
        adapter = self.adapter(lambda r: httpx.Response(200, json=[]))
        self.assertTrue(adapter._holds.reserve("dup"))
        # A second reserve for the same key refuses (in-flight/crash guard).
        self.assertFalse(adapter._holds.reserve("dup"))

    def test_http_error_retryable(self):
        def handler(request):
            return httpx.Response(500, text="down")

        adapter = self.adapter(handler)
        with self.assertRaises(RetryableProviderError):
            run(adapter.search_slots("6", "2026-10-01"))

    def test_500_then_retry_same_key_succeeds(self):
        # P0-1 regression: a failed attempt must NOT poison the key.
        attempts = []

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments"):
                attempts.append(1)
                if len(attempts) == 1:
                    return httpx.Response(500, text="flaky")
                return httpx.Response(201, json={"id": 44})
            raise AssertionError(f"unexpected {url}")

        adapter = self.adapter(handler)
        try:
            slots = run(adapter.search_slots("6", "2026-10-01"))
            hold = run(adapter.create_hold(slots[0]["slotId"]))
            with self.assertRaises(RetryableProviderError):
                run(adapter.confirm(hold.hold_id, {"customerId": 5}, "flaky-key"))
            result = run(adapter.confirm(hold.hold_id, {"customerId": 5}, "flaky-key"))
            self.assertTrue(result["ok"])
            self.assertEqual(len(attempts), 2)
        finally:
            run(adapter.close())

    def test_garbage_slots_rejected(self):
        def handler(request):
            return httpx.Response(200, json={"error": "denied"})

        adapter = self.adapter(handler)
        try:
            with self.assertRaises(ProviderError):
                run(adapter.search_slots("6", "2026-10-01"))
        finally:
            run(adapter.close())

    def test_seconds_start_accepted(self):
        adapter = self.adapter(lambda r: httpx.Response(200, json=[]))
        try:
            adapter._slots["s"] = {
                "slotId": "s",
                "serviceId": "6",
                "providerId": "2",
                "date": "2026-10-01",
                "start": "2026-10-01 17:00:00",
            }
            hold = run(adapter.create_hold("s"))
            self.assertEqual(hold.payload["slot"]["start"], "2026-10-01 17:00:00")
        finally:
            run(adapter.close())


if __name__ == "__main__":
    unittest.main()
