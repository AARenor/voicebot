"""Dashboard API tests (fastapi TestClient, demo store only)."""

import os
import sys
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
        self.assertEqual(len(self.client.get("/api/calls").json()["calls"]), 3)
        config = self.client.get("/api/config").json()["config"]
        self.assertIn("voice_et", config)
        self.assertNotIn("GROQ_API_KEY", str(config))
        metrics = self.client.get("/api/metrics").json()["metrics"]
        self.assertIn("quote_fidelity", metrics)

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


if __name__ == "__main__":
    unittest.main()
