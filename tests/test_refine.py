"""Refine-round tests: calls log, seeded FAQ wiring, UI badge/refresh."""

import os
import sys
import unittest

sys.path.insert(0, "voicebot")

from app import callslog  # noqa: E402
from app.booking.tools import Dispatcher  # noqa: E402
from app.knowledge import open_db, retrieve  # noqa: E402
from app.knowledge.seed import SEED_DOCS, seed  # noqa: E402


def run(coro):
    import asyncio

    return asyncio.run(coro)


class TestCallsLog(unittest.TestCase):
    def setUp(self):
        self.db = callslog.open_log()
        callslog.seed_demo(self.db)

    def test_seed_once(self):
        self.assertEqual(len(callslog.list_calls(self.db)), 3)
        self.assertEqual(callslog.seed_demo(self.db), 0)

    def test_log_and_list(self):
        row_id = callslog.log_call(
            self.db, "et", "+3725000000", "Testkõne", "hold_created"
        )
        self.assertGreater(row_id, 3)
        calls = callslog.list_calls(self.db)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0]["summary"], "Testkõne")

    def test_hostile_strings_safe(self):
        callslog.log_call(
            self.db, "et'); DROP TABLE calls;--", "<img>", "'; DELETE;", "x"
        )
        self.assertEqual(len(callslog.list_calls(self.db)), 4)
        tables = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        self.assertIn(("calls",), tables)

    def test_limit_clamped(self):
        self.assertLessEqual(len(callslog.list_calls(self.db, limit=-5)), 200)

    def test_retention_prune(self):
        old = ("2020-01-01 00:00", "et", "+372•••00", "vana", "x", "real")
        self.db.execute(
            "INSERT INTO calls (at, lang, peer, summary, outcome, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            old,
        )
        self.db.commit()
        self.assertEqual(callslog.prune(self.db, retention_days=30), 1)
        self.assertEqual(len(callslog.list_calls(self.db)), 3)


class TestSeededFaq(unittest.TestCase):
    def setUp(self):
        self.db = open_db()
        seed(self.db)

    def test_seed_docs_present(self):
        self.assertEqual(len(SEED_DOCS), 5)
        hits = retrieve(self.db, "millal saab saabuda")
        self.assertTrue(hits)

    def test_answer_faq_end_to_end(self):
        dispatcher = Dispatcher(faq=lambda q: retrieve(self.db, q, lang="et"))
        out = run(dispatcher.dispatch("answer_faq", {"question": "spa"}))
        self.assertTrue(out["passages"])
        self.assertIn("9.00", out["passages"][0]["text"])


class TestUiBadge(unittest.TestCase):
    def test_status_badge_and_refresh_present(self):
        from pathlib import Path

        html = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "dashboard"
            / "static"
            / "index.html"
        ).read_text()
        self.assertIn("/api/status", html)
        self.assertIn("setInterval", html)
        self.assertIn("30000", html)
        self.assertNotIn("onclick=", html)
        self.assertIn("loadStatus", html)


class TestLogHardening(unittest.TestCase):
    def setUp(self):
        self.db = callslog.open_log()
        callslog.seed_demo(self.db)

    def test_peer_masked_at_write(self):
        callslog.log_call(self.db, "et", "+3725123456", "t", "hold_created")
        rows = self.db.execute("SELECT peer FROM calls WHERE source='real'").fetchall()
        self.assertEqual(rows[0][0], "+372•••56")
        self.assertNotIn("123456", rows[0][0])

    def test_provenance_demo_vs_real(self):
        callslog.log_call(self.db, "et", "+3725000000", "t", "hold_created")
        by_source = {c["source"] for c in callslog.list_calls(self.db)}
        self.assertEqual(by_source, {"demo", "real"})

    def test_threads_share_singleton_safely(self):
        import threading

        callslog.reset_default()
        callslog.seed_demo(callslog.get_default())
        errors = []

        def worker(_):
            try:
                db = callslog.get_default()
                callslog.log_call(db, "et", "+3725000000", "t", "x")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(
            len(callslog.list_calls(callslog.get_default())), 13
        )  # 3 demo + 10 logged
        callslog.reset_default()

    def test_hostile_fts_and_giant_inputs(self):
        db = open_db()
        seed(db)
        for hostile in ['"', "*", "OR", "x" * 10000, '" OR 1=1 --']:
            self.assertIsInstance(retrieve(db, hostile), list)
        self.assertLessEqual(len(retrieve(db, "spa", top_k=10**9)), 20)


if __name__ == "__main__":
    unittest.main()
