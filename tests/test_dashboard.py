"""Dashboard API tests (fastapi TestClient, demo store only)."""

import os
import sys
import time
import unittest

sys.path.insert(0, "voicebot")

os.environ["OPERATOR_TOKEN"] = "test-token"

from app.dashboard import demo  # noqa: E402
from app.server import create_app  # noqa: E402

try:
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TestDashboard(unittest.TestCase):
    def setUp(self):
        demo.reset()
        self.client = TestClient(create_app())

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"ok": True})

    def test_index_serves_html(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("operaatori töölaud", response.text)
        self.assertIn('id="holds"', response.text)

    def test_holds_list(self):
        holds = self.client.get("/api/holds").json()["holds"]
        self.assertEqual(len(holds), 2)
        self.assertIn("expires_in_s", holds[0])

    def test_confirm_requires_token(self):
        response = self.client.post("/api/holds/hold_demo_sea12/confirm")
        self.assertEqual(response.status_code, 403)
        os.environ["OPERATOR_TOKEN"] = ""
        try:
            response = self.client.post("/api/holds/hold_demo_sea12/confirm")
            self.assertEqual(response.status_code, 503)
        finally:
            os.environ["OPERATOR_TOKEN"] = "test-token"

    def test_confirm_cancel_flow(self):
        headers = {"Authorization": "Bearer test-token"}
        ok = self.client.post(
            "/api/holds/hold_demo_sea12/confirm", headers=headers
        ).json()
        self.assertTrue(ok["ok"])
        again = self.client.post("/api/holds/hold_demo_sea12/confirm", headers=headers)
        self.assertEqual(again.status_code, 404)
        cancel = self.client.post(
            "/api/holds/hold_demo_mer34/cancel", headers=headers
        ).json()
        self.assertEqual(cancel["status"], "cancelled")
        wrong = self.client.post(
            "/api/holds/hold_demo_mer34/cancel",
            headers={"Authorization": "Bearer nope"},
        )
        self.assertEqual(wrong.status_code, 403)

    def test_calls_config_metrics_shapes(self):
        self.assertEqual(
            len(
                self.client.get(
                    "/api/calls", headers={"Authorization": "Bearer test-token"}
                ).json()["calls"]
            ),
            3,
        )
        config = self.client.get("/api/config").json()["config"]
        self.assertIn("voice_et", config)
        self.assertNotIn("GROQ_API_KEY", str(config))
        metrics = self.client.get("/api/metrics").json()["metrics"]
        self.assertIn("quote_fidelity", metrics)

    def test_status_exposes_truthful_capabilities(self):
        body = self.client.get("/api/status").json()
        capabilities = body["capabilities"]
        self.assertFalse(capabilities["operator_hold_commands_ready"])
        self.assertTrue(capabilities["serving_demo_data"])
        self.assertFalse(capabilities["text_turn_ready"])
        self.assertFalse(capabilities["audio_turn_ready"])

    def test_live_without_command_service_fails_closed(self):
        from app.dashboard import api as dashboard_api

        headers = {"Authorization": "Bearer test-token"}
        before = demo.STORE["holds"][0]["status"]
        dashboard_api.configure_mode(demo=False, commands_ready=False)
        try:
            response = self.client.post(
                "/api/holds/hold_demo_sea12/confirm", headers=headers
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(demo.STORE["holds"][0]["status"], before)
        finally:
            dashboard_api.configure_mode(demo=True, commands_ready=False)

    def test_hostile_hold_id_renders_inert(self):
        # P1-1 regression: a hold_id carrying quotes/brackets must come back
        # byte-identical via JSON (no HTML/JS interpretation server-side);
        # the UI inserts it via textContent + dataset only (static review).
        demo.STORE["holds"].append(
            {
                "hold_id": "x');alert(1);//<b>",
                "venue": "X",
                "kind": "slot",
                "guest": "<img>",
                "service": "s",
                "slot": "d",
                "quoted_total": None,
                "currency": "EUR",
                "price_quote_id": "q",
                "status": "pending",
                "expires_at": 9999999999.0,
            }
        )
        holds = self.client.get("/api/holds").json()["holds"]
        evil = [h for h in holds if "alert" in h["hold_id"]][0]
        self.assertEqual(evil["hold_id"], "x');alert(1);//<b>")
        html = self.client.get("/").text
        self.assertNotIn("onclick=", html)

    def test_non_ascii_token_is_403_not_500(self):
        # R2 P1: str compare_digest raised TypeError on non-ASCII input.
        # (HTTP clients won't transmit raw non-ASCII headers, so exercise
        # the gate directly as the server sees it post latin-1 decode.)
        from app.dashboard.api import _require_operator
        from fastapi import HTTPException

        try:
            _require_operator("Bearer tëst-õäöü")
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 403)
        else:
            self.fail("expected 403")
        # Accept path still works after the bytes-compare change.
        _require_operator("Bearer test-token")

    def test_whitespace_token_rejected(self):
        os.environ["OPERATOR_TOKEN"] = "   "
        try:
            response = self.client.post("/api/holds/hold_demo_sea12/cancel")
            self.assertEqual(response.status_code, 503)
        finally:
            os.environ["OPERATOR_TOKEN"] = "test-token"

    def test_zenoti_survives_livekit_configured(self):
        # R2 P1-1: slot fallback must not be coupled to the LiveKit branch.
        from app.server import build_stack

        old = dict(os.environ)
        try:
            os.environ["LIVEKIT_URL"] = "http://livekit:7880"
            os.environ["LIVEKIT_API_KEY"] = "fixture-media-key"
            os.environ["LIVEKIT_API_SECRET"] = "fixture-secret"
            os.environ["ZENOTI_API_KEY"] = "z"
            stack = build_stack()
            self.assertIsNotNone(stack["livekit"])
            self.assertIsNotNone(stack["slot"])
            self.assertEqual(type(stack["slot"]).__name__, "ZenotiAdapter")
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_status_reports_livekit_wiring(self):
        from app.server import build_stack

        old = dict(os.environ)
        try:
            for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
                os.environ.pop(key, None)
            self.assertFalse(build_stack()["livekit"] is not None)
            os.environ["LIVEKIT_URL"] = "http://livekit:7880"
            os.environ["LIVEKIT_API_KEY"] = "fixture-media-key"
            os.environ["LIVEKIT_API_SECRET"] = "fixture-secret"
            wired = build_stack()["livekit"]
            self.assertEqual(wired["url"], "http://livekit:7880")
            self.assertNotIn("SECRET", str(wired).upper().replace("API_SECRET", ""))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_expired_hold_confirm_410(self):
        headers = {"Authorization": "Bearer test-token"}
        demo.STORE["holds"][0]["expires_at"] = time.time() - 1
        response = self.client.post(
            "/api/holds/hold_demo_sea12/confirm", headers=headers
        )
        self.assertEqual(response.status_code, 410)

    def test_turn_body_must_be_object(self):
        auth = {"Authorization": "Bearer test-token"}
        response = self.client.post("/api/turn", json=["x"], headers=auth)
        self.assertIn(response.status_code, (400, 422))  # never 500

    def test_turn_demo_gated_and_bad_body(self):
        auth = {"Authorization": "Bearer test-token"}
        response = self.client.post("/api/turn", json={"text": "Tere!"}, headers=auth)
        self.assertEqual(response.status_code, 503)
        response = self.client.post("/api/turn", json={}, headers=auth)
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/turn", json={"text": "Tere!"})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/turn", json={"text": "x" * 501}, headers=auth)
        self.assertEqual(response.status_code, 413)

    def test_turn_text_path_live(self):
        import base64

        from app.booking.tools import Dispatcher

        class FakeLlm:
            def chat(self, messages, tools=None):
                return {"content": "Tere! Kuidas saan aidata?"}

        class FakeTts:
            def synthesize(self, text):
                return b"AUDIO:" + text.encode()[:8]

        app = self.client
        stack = app.app.state.stack
        stack["llm_primary"] = FakeLlm()
        stack["tts"] = FakeTts()
        stack["dispatcher"] = Dispatcher()
        auth = {"Authorization": "Bearer test-token"}
        response = self.client.post("/api/turn", json={"text": "Tere!"}, headers=auth)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("Tere!", body["reply"])
        self.assertTrue(base64.b64decode(body["audio_b64"]))
        self.assertEqual(body["tools_used"], 0)

    def test_shutdown_closes_async_slot(self):
        import httpx
        from fastapi.testclient import TestClient

        from app.booking.easyappointments import EasyAppointmentsAdapter

        closed = []
        import os
        import tempfile

        adapter = EasyAppointmentsAdapter(
            "https://x.example",
            "k",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
            state_db=os.path.join(
                tempfile.mkdtemp(prefix="easy-dash-"), "easy-booking.db"
            ),
        )
        orig_close = adapter.close

        async def spy():
            closed.append("async")
            await orig_close()

        adapter.close = spy
        self.client.app.state.stack["slot"] = adapter
        with TestClient(self.client.app):
            pass
        self.assertIn("async", closed)

    def test_shutdown_closes_providers(self):
        from fastapi.testclient import TestClient

        closed = []

        class Closer:
            def close(self):
                closed.append("sync")

        self.client.app.state.stack["tts"] = Closer()
        with TestClient(self.client.app):
            pass
        self.assertIn("sync", closed)

    def test_turn_text_path_logs_real_call(self):
        from app import callslog
        from app.booking.tools import Dispatcher

        class FakeLlm:
            def chat(self, messages, tools=None):
                return {"content": "Tere! Kuidas saan aidata?"}

        class FakeTts:
            def synthesize(self, text):
                return b"AUDIO:" + text.encode()[:8]

        stack = self.client.app.state.stack
        stack["llm_primary"] = FakeLlm()
        stack["tts"] = FakeTts()
        stack["dispatcher"] = Dispatcher()

        def real_calls():
            return [
                c
                for c in callslog.list_calls(callslog.get_default())
                if c["source"] == "real"
            ]

        before = len(real_calls())
        auth = {"Authorization": "Bearer test-token"}
        response = self.client.post("/api/turn", json={"text": "Tere!"}, headers=auth)
        self.assertEqual(response.status_code, 200)
        after = real_calls()
        self.assertEqual(len(after), before + 1)
        self.assertEqual(after[0]["outcome"], "ok")
        self.assertEqual(after[0]["lang"], "et")


if __name__ == "__main__":
    unittest.main()
