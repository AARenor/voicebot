"""Safety contract for Easy!Appointments demo writer (spec 2026-10-01).

RED-first: exercises operational gating, catalogue/ID validation, stale
slots, concurrency, ambiguous-write reconciliation + restart replay, journal
hygiene, and Dispatcher slot tools. Requires new adapter behavior; must FAIL
before implementation.
"""

import asyncio
import os
import sys
import tempfile
import unittest

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.booking.easyappointments import EasyAppointmentsAdapter  # noqa: E402
from app.booking.tools import Dispatcher  # noqa: E402
from app.providers.errors import ProviderError  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def make_adapter(handler, db_path, catalogue="auto", **kw):
    if catalogue == "auto":
        inner = handler

        def handler(request, _inner=inner):
            path = str(request.url.path)
            if path.endswith("/services") and request.method == "GET":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": 6,
                            "name": "Massage",
                            "duration": 60,
                            "price": 10,
                            "currency": "EUR",
                        },
                    ],
                )
            if path.endswith("/providers") and request.method == "GET":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": 2,
                            "firstName": "Anna",
                            "lastName": "Smith",
                            "services": [6],
                        },
                    ],
                )
            return _inner(request)

    return EasyAppointmentsAdapter(
        "https://spa.example",
        "k",
        transport=httpx.MockTransport(handler),
        state_db=db_path,
        **kw,
    )


def seed_slot(adapter, service="6", provider="2", start="2026-10-01 17:00"):
    date = start.split(" ")[0]
    slot_id = f"{service}|{provider}|{start}"
    adapter._slots[slot_id] = {
        "slotId": slot_id,
        "serviceId": service,
        "providerId": provider,
        "date": date,
        "start": start,
    }
    return slot_id


GUEST = {
    "firstName": "Mari",
    "lastName": "Maasikas",
    "email": "mari@example.ee",
    "phone": "+3725123456",
}


class TestOperationalGating(unittest.TestCase):
    def test_operational_false_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(
                lambda r: httpx.Response(200, json=[]), os.path.join(d, "j.db")
            )
            self.assertFalse(a.operational)
            self.assertFalse(EasyAppointmentsAdapter.operational)
            disp = Dispatcher(slot=a)
            self.assertEqual(disp.available_tools(), [])

    def test_demo_write_opt_in_enables(self):
        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(
                lambda r: httpx.Response(200, json=[]),
                os.path.join(d, "j.db"),
                allow_writes=True,
            )
            self.assertTrue(a.operational)
            disp = Dispatcher(slot=a)
            names = {t["function"]["name"] for t in disp.available_tools()}
            self.assertIn("search_slots", names)
            self.assertIn("cancel_slot_booking", names)
            self.assertIn("get_slot_catalogue", names)

    def test_hold_description_honest(self):
        from app.booking import tools as tmod

        desc = tmod.TOOL_HOLD_SLOT["function"]["description"]
        lowered = desc.lower()
        self.assertIn("local", lowered)
        self.assertIn("not a remote reservation", lowered)


class TestCatalogue(unittest.TestCase):
    def test_catalogue_lists_services_and_providers(self):
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/services"):
                return httpx.Response(
                    200,
                    json=[
                        {"id": 6, "name": "Massage", "duration": 60},
                    ],
                )
            if url.endswith("/providers"):
                return httpx.Response(
                    200,
                    json=[
                        {"id": 2, "firstName": "Anna", "services": [6]},
                    ],
                )
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(
                handler,
                os.path.join(d, "j.db"),
                catalogue=None,
                allow_writes=True,
            )
            cat = run(a.get_slot_catalogue())
            self.assertEqual(cat["services"][0]["name"], "Massage")
            self.assertEqual(cat["providers"][0]["id"], 2)

    def test_names_resolve_to_ids(self):
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/services"):
                return httpx.Response(
                    200, json=[{"id": 6, "name": "Massage", "duration": 60}]
                )
            if url.endswith("/providers"):
                return httpx.Response(
                    200, json=[{"id": 2, "firstName": "Anna", "services": [6]}]
                )
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(
                handler,
                os.path.join(d, "j.db"),
                catalogue=None,
                allow_writes=True,
            )
            slots = run(a.search_slots("Massage", "2026-10-01", provider="Anna"))
            self.assertEqual(slots[0]["serviceId"], "6")
            self.assertEqual(slots[0]["providerId"], "2")

    def test_invalid_ids_rejected_without_http(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            if str(request.url.path).endswith("/services"):
                return httpx.Response(200, json=[])
            if str(request.url.path).endswith("/providers"):
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=["17:00"])

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(
                handler,
                os.path.join(d, "j.db"),
                catalogue=None,
                allow_writes=True,
            )
            with self.assertRaises(ProviderError):
                run(a.search_slots("6; DROP TABLE", "2026-10-01"))
            with self.assertRaises(ProviderError):
                run(a.search_slots("no-such-service-xyz", "2026-10-01"))

    def test_incompatible_provider_rejected(self):
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/services"):
                return httpx.Response(200, json=[{"id": 6, "name": "M"}])
            if url.endswith("/providers"):
                return httpx.Response(
                    200, json=[{"id": 2, "firstName": "A", "services": [7]}]
                )
            return httpx.Response(200, json=["17:00"])

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(
                handler,
                os.path.join(d, "j.db"),
                catalogue=None,
                allow_writes=True,
            )
            with self.assertRaises(ProviderError):
                run(a.search_slots("6", "2026-10-01", provider="2"))


class TestStaleAndConcurrency(unittest.TestCase):
    def _booked_handler(self, booked):
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=[] if booked["taken"] else ["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                booked["taken"] = True
                booked["posts"] += 1
                return httpx.Response(201, json={"id": 42})
            if "/appointments" in url and request.method == "GET":
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        return handler

    def test_stale_slot_conflict(self):
        booked = {"taken": False, "posts": 0}

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=[])  # gone
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                booked["posts"] += 1
                return httpx.Response(201, json={"id": 99})
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            out = run(a.confirm(hold.hold_id, dict(GUEST), "k-stale-1"))
            self.assertEqual(out, {"ok": False, "error": "slot_stale"})
            self.assertEqual(booked["posts"], 0)

    def test_concurrent_same_slot_single_post(self):
        import threading

        booked = {"taken": False, "posts": 0}
        handler = self._booked_handler(booked)
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            sid = seed_slot(a)
            h1 = run(a.create_hold(sid))
            h2 = run(a.create_hold(sid))
            barrier = threading.Barrier(2)

            async def one(hold_id, key):
                await asyncio.to_thread(barrier.wait)
                return await a.confirm(hold_id, dict(GUEST), key)

            async def both():
                return await asyncio.gather(
                    one(h1.hold_id, "k-conc-1"), one(h2.hold_id, "k-conc-2")
                )

            r1, r2 = run(both())
            oks = [r for r in (r1, r2) if r.get("ok")]
            notoks = [r for r in (r1, r2) if not r.get("ok")]
            self.assertEqual(len(oks), 1)
            self.assertEqual(len(notoks), 1)
            self.assertIn(notoks[0]["error"], ("slot_stale", "confirm_in_progress"))
            self.assertEqual(booked["posts"], 1)


class TestAmbiguousWrites(unittest.TestCase):
    def test_transport_error_yields_unknown_and_reconciles(self):
        state = {"posts": 0, "fail_first": True}

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                state["posts"] += 1
                if state["fail_first"]:
                    raise httpx.ConnectError("boom")
                return httpx.Response(201, json={"id": 55})
            if url.endswith("/appointments") and request.method == "GET":
                import hashlib

                marker = (
                    "vb-"
                    + hashlib.sha256(
                        ("https://spa.example/index.php/api/v1|k-amb-1").encode()
                    ).hexdigest()[:16]
                )
                if state["posts"] >= 1:
                    return httpx.Response(
                        200, json=[{"id": 55, "notes": f"[voicebot {marker}] x"}]
                    )
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            # Simulate server DID store despite transport error.
            out1 = run(a.confirm(hold.hold_id, dict(GUEST), "k-amb-1"))
            self.assertEqual(out1["error"], "write_outcome_unknown")
            self.assertEqual(state["posts"], 1)
            out2 = run(a.confirm(hold.hold_id, dict(GUEST), "k-amb-1"))
            self.assertTrue(out2.get("ok"))
            self.assertEqual(state["posts"], 1)  # never re-POSTed

    def test_auth_failure_is_terminal_not_unknown(self):
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments"):
                return httpx.Response(401, text="unauthorized")
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            with self.assertRaises(ProviderError):
                run(a.confirm(hold.hold_id, dict(GUEST), "k-auth-1"))

    def test_restart_replay_without_hold(self):
        import hashlib

        marker = (
            "vb-"
            + hashlib.sha256(
                ("https://spa.example/index.php/api/v1|k-restart-1").encode()
            ).hexdigest()[:16]
        )

        def handler1(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                raise httpx.ConnectError("cut")
            if url.endswith("/appointments"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        def handler2(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/appointments") and request.method == "GET":
                return httpx.Response(
                    200, json=[{"id": 77, "notes": f"[voicebot {marker}] hi"}]
                )
            if url.endswith("/appointments") and request.method == "POST":
                raise AssertionError("must never re-POST after restart")
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a1 = make_adapter(handler1, db, allow_writes=True)
            sid = seed_slot(a1)
            hold = run(a1.create_hold(sid))
            out1 = run(a1.confirm(hold.hold_id, dict(GUEST), "k-restart-1"))
            self.assertEqual(out1["error"], "write_outcome_unknown")
            run(a1.close())
            # New process: fresh adapter, no holds, same journal.
            a2 = make_adapter(handler2, db, allow_writes=True)
            out2 = run(a2.confirm("no-such-hold", dict(GUEST), "k-restart-1"))
            self.assertTrue(out2.get("ok"))
            self.assertEqual(out2["booking"]["id"], 77)
            run(a2.close())

    def test_aged_pending_never_reposts(self):
        import sqlite3

        posts = []

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                posts.append(1)
                raise httpx.ConnectError("cut")
            if url.endswith("/appointments"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            out1 = run(a.confirm(hold.hold_id, dict(GUEST), "k-age-1"))
            self.assertEqual(out1["error"], "write_outcome_unknown")
            # Age the pending row far past any timeout, then retry: still
            # unknown, and still exactly one POST (never a blind second).
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "UPDATE easy_writes SET updated_at=1"
                    " WHERE idempotency_key='k-age-1'"
                )
                conn.commit()
            conn.close()
            out2 = run(a.confirm(hold.hold_id, dict(GUEST), "k-age-1"))
            self.assertEqual(out2["error"], "write_outcome_unknown")
            self.assertEqual(posts, [1])

    def test_journal_holds_no_pii(self):
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                raise httpx.ConnectError("cut")
            if url.endswith("/appointments"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            run(a.confirm(hold.hold_id, dict(GUEST), "k-pii-1"))
            blob = open(db, "rb").read().decode("utf-8", "ignore")
            self.assertNotIn("+3725123456", blob)
            self.assertNotIn("Mari", blob)

    def test_journal_errors_carry_no_echo(self):
        # A backend that echoes the request body in a 4xx must not get
        # guest data persisted via the recorded error string.
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/customers"):
                return httpx.Response(
                    400, text='{"error": "bad firstName Mari Maasikas"}'
                )
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            with self.assertRaises(ProviderError):
                run(a.confirm(hold.hold_id, dict(GUEST), "k-pii-2"))
            blob = open(db, "rb").read().decode("utf-8", "ignore")
            self.assertNotIn("Mari", blob)
            self.assertNotIn("+3725123456", blob)


class TestDispatcherSlotTools(unittest.TestCase):
    def test_cancel_and_catalogue_tools(self):
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/services"):
                return httpx.Response(200, json=[{"id": 6, "name": "M"}])
            if url.endswith("/providers"):
                return httpx.Response(200, json=[{"id": 2, "name": "A"}])
            if "/appointments/42" in url and request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            disp = Dispatcher(slot=a)
            cat = run(disp.dispatch("get_slot_catalogue", {}))
            self.assertIn("services", cat)
            out = run(
                disp.dispatch(
                    "cancel_slot_booking", {"booking_id": "42", "idempotency_key": "c1"}
                )
            )
            self.assertTrue(out["ok"])
            with self.assertRaises(ProviderError):
                run(
                    disp.dispatch(
                        "cancel_slot_booking",
                        {"booking_id": "../evil", "idempotency_key": "c2"},
                    )
                )

    def test_transport_mapped_to_closed_error(self):
        def handler(request):
            raise httpx.ConnectError("down")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            disp = Dispatcher(slot=a)
            with self.assertRaises(ProviderError) as ctx:
                run(
                    disp.dispatch(
                        "search_slots", {"service": "6", "date": "2026-10-01"}
                    )
                )
            self.assertEqual(str(ctx.exception), "tools: search_failed")


class TestReviewRework(unittest.TestCase):
    """P0/P1 regressions from independent review (must fail pre-fix)."""

    def test_customer_commit_cancellation_blocks_all_reposts(self):
        customers = []
        committed = asyncio.Event()

        async def handler(request):
            path = request.url.path
            if path.endswith("/services/6"):
                return httpx.Response(200, json={"duration": 60})
            if path.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if path.endswith("/customers") and request.method == "POST":
                customers.append(1)
                committed.set()
                await asyncio.sleep(30)
                return httpx.Response(201, json={"id": 7})
            if path.endswith("/appointments"):
                return httpx.Response(200, json=[])
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)

            async def exercise():
                hold = await a.create_hold(seed_slot(a))
                task = asyncio.create_task(
                    a.confirm(hold.hold_id, dict(GUEST), "customer-crash")
                )
                await committed.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(
                    a._journal.get("customer-crash")["status"], "pending_customer"
                )
                b = make_adapter(handler, db, allow_writes=True)
                self.assertEqual(
                    (await b.confirm("lost-hold", {}, "customer-crash"))["error"],
                    "write_outcome_unknown",
                )
                fresh = await b.create_hold(seed_slot(b))
                result = await b.confirm(fresh.hold_id, dict(GUEST), "fresh-key")
                self.assertEqual(result["error"], "write_outcome_unknown")
                self.assertEqual(customers, [1])

            run(exercise())

    def test_malformed_customer_id_never_persists_echo(self):
        def handler(request):
            if request.url.path.endswith("/services/6"):
                return httpx.Response(200, json={"duration": 60})
            if request.url.path.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if request.url.path.endswith("/customers"):
                return httpx.Response(201, json={"id": "PRIVATE-SENTINEL"})
            return httpx.Response(200, json=[])

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            hold = run(a.create_hold(seed_slot(a)))
            try:
                outcome = run(
                    a.confirm(hold.hold_id, dict(GUEST), "malformed-customer")
                )
            except ProviderError:
                outcome = None
            self.assertFalse(b"PRIVATE-SENTINEL" in open(db, "rb").read())
            self.assertEqual(outcome, {"ok": False, "error": "write_outcome_unknown"})

    def test_journal_strips_double_quoted_provider_echo(self):
        from app.booking.easyappointments import _clean_error

        self.assertEqual(
            _clean_error('easy.confirm: HTTP 400 body="Mari\'s private payload"'),
            "easy.confirm: HTTP 400",
        )

    def test_concurrent_same_key_replays_under_lock(self):
        posts = []

        async def handler(request):
            if request.url.path.endswith("/services/6"):
                return httpx.Response(200, json={"duration": 60})
            if request.url.path.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if request.url.path.endswith("/appointments") and request.method == "POST":
                posts.append(1)
                await asyncio.sleep(0.1)
                return httpx.Response(201, json={"id": 9})
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            b = make_adapter(handler, db, allow_writes=True)

            async def exercise():
                ha = await a.create_hold(seed_slot(a))
                hb = await b.create_hold(seed_slot(b))
                results = await asyncio.gather(
                    a.confirm(ha.hold_id, {"customerId": 7}, "same-key"),
                    b.confirm(hb.hold_id, {"customerId": 7}, "same-key"),
                )
                self.assertEqual(results[0], results[1])
                self.assertTrue(results[0]["ok"])
                self.assertEqual(posts, [1])
                self.assertEqual(a._journal.get("same-key")["status"], "success")

            run(exercise())

    def test_same_key_waiter_returns_success_never_overwrites(self):
        # A durable success row must win over a stale slot, with zero POSTs.
        posts = []

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["18:00"])  # slot gone
            if url.endswith("/appointments") and request.method == "POST":
                posts.append(1)
                return httpx.Response(201, json={"id": 9})
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            result = {"ok": True, "booking": {"id": 77}}
            a._journal.put_result("k-wait", a._marker("k-wait"), "success", 77, result)
            out = run(a.confirm(hold.hold_id, dict(GUEST), "k-wait"))
            self.assertEqual(out, result)
            self.assertEqual(posts, [])

    def test_terminal_precustomer_errors_record_failed(self):
        calls = {"customers": 0}

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/services/6"):
                return httpx.Response(400, text="bad service")
            if url.endswith("/customers"):
                calls["customers"] += 1
                return httpx.Response(201, json={"id": 7})
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            with self.assertRaises(ProviderError):
                run(a.confirm(hold.hold_id, dict(GUEST), "k-svc400"))
            self.assertEqual(calls["customers"], 0)  # validated before side effects
            with self.assertRaises(ProviderError):
                run(a.confirm(hold.hold_id, dict(GUEST), "k-svc400"))
            self.assertEqual(calls["customers"], 0)  # failed row replays, no retry

    def test_customer_timeout_never_duplicates(self):
        calls = {"customers": 0}

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/customers"):
                calls["customers"] += 1
                raise httpx.ConnectError("cut")
            if url.endswith("/appointments"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            self.assertEqual(
                run(a.confirm(hold.hold_id, dict(GUEST), "k-cust"))["error"],
                "write_outcome_unknown",
            )
            self.assertEqual(
                run(a.confirm(hold.hold_id, dict(GUEST), "k-cust"))["error"],
                "write_outcome_unknown",
            )
            self.assertEqual(calls["customers"], 1)  # never blindly duplicated

    def test_reconcile_requires_unique_exact_match(self):
        posts = []
        remote = [
            {"id": 1, "notes": "[voicebot vb-deadbeefdeadbeef] collision-a"},
            {"id": 2, "notes": "[voicebot vb-deadbeefdeadbeef] collision-b"},
        ]

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                posts.append(1)
                raise httpx.ConnectError("cut")
            if url.endswith("/appointments"):
                return httpx.Response(200, json=remote)
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            out1 = run(a.confirm(hold.hold_id, dict(GUEST), "k-dup"))
            self.assertEqual(out1["error"], "write_outcome_unknown")
            # Force the pending marker onto the colliding records, then retry:
            # two hits must stay unknown, never pick one.
            marker = f"[voicebot {a._marker('k-dup')}]"
            for rec in remote:
                rec["notes"] = f"{marker} {rec['notes']}"
            out2 = run(a.confirm(hold.hold_id, dict(GUEST), "k-dup"))
            self.assertEqual(out2["error"], "write_outcome_unknown")
            self.assertEqual(posts, [1])

    def test_201_without_id_stays_unknown(self):
        posts = []

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                posts.append(1)
                return httpx.Response(201, json={"ok": True})  # no id
            if url.endswith("/appointments"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            sid = seed_slot(a)
            hold = run(a.create_hold(sid))
            out1 = run(a.confirm(hold.hold_id, dict(GUEST), "k-noid"))
            self.assertEqual(out1["error"], "write_outcome_unknown")
            out2 = run(a.confirm(hold.hold_id, dict(GUEST), "k-noid"))
            self.assertEqual(out2["error"], "write_outcome_unknown")
            self.assertEqual(posts, [1])

    def test_cancel_persists_and_namespaces(self):
        deletes = []

        def handler(request):
            url = str(request.url.path)
            if "/appointments/" in url and request.method == "DELETE":
                deletes.append(url)
                return httpx.Response(204)
            if url.endswith("/appointments"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            out = run(a.cancel("42", "ck-1"))
            self.assertTrue(out["ok"])
            self.assertEqual(len(deletes), 1)
            # Journal persisted under namespaced key:
            row = a._journal.get("cancel:ck-1")
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "success")
            # In-memory replay must be namespaced (plain key untouched):
            self.assertIsNone(a._holds.check_replay("ck-1"))
            # Restart replays from journal with zero new DELETEs:
            b = make_adapter(handler, db, allow_writes=True)
            out2 = run(b.cancel("42", "ck-1"))
            self.assertEqual(out2, out)
            self.assertEqual(len(deletes), 1)
            # Direct cancel without the gate fails closed:
            c = make_adapter(handler, db)
            with self.assertRaises(ProviderError):
                run(c.cancel("42", "ck-2"))
            with self.assertRaises(ProviderError):
                run(c.confirm("whatever", dict(GUEST), "ck-3"))

    def test_corrupt_hold_closed(self):
        def handler(request):
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            with self.assertRaises((ProviderError, Exception)):
                run(a.create_hold({"not": "a-string"}))
            hold = a._holds.create(
                price_quote_id="x",
                quoted_total=None,
                currency="EUR",
                payload={"slot": {"broken": True}},
            )
            with self.assertRaises(ProviderError):
                run(a.confirm(hold.hold_id, dict(GUEST), "k-corrupt"))

    def test_strict_ids_need_catalogue(self):
        def handler(request):
            url = str(request.url.path)
            if url.endswith("/services"):
                return httpx.Response(500, text="down")
            if url.endswith("/providers"):
                return httpx.Response(500, text="down")
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(
                handler,
                os.path.join(d, "j.db"),
                catalogue=None,
                allow_writes=True,
            )
            # Numeric service+provider with unreadable catalogue: closed.
            with self.assertRaises(ProviderError):
                run(a.search_slots("6", "2026-10-01", "2"))

        def unknown_provider(request):
            url = str(request.url.path)
            if url.endswith("/services"):
                return httpx.Response(200, json=[{"id": 6, "name": "M"}])
            if url.endswith("/providers"):
                return httpx.Response(200, json=[{"id": 9, "services": [6]}])
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(
                unknown_provider,
                os.path.join(d, "j.db"),
                catalogue=None,
                allow_writes=True,
            )
            with self.assertRaises(ProviderError):
                run(a.search_slots("6", "2026-10-01", "2"))  # unknown provider id
            # Full provider names resolve ("Demo Therapist" style):
            out = run(a.search_slots("M", "2026-10-01"))
            self.assertTrue(out)

    def test_global_pending_blocks_new_key(self):
        posts = []

        def handler(request):
            url = str(request.url.path)
            if url.endswith("/availabilities"):
                return httpx.Response(200, json=["17:00"])
            if url.endswith("/customers"):
                return httpx.Response(201, json={"id": 7})
            if url.endswith("/services/6"):
                return httpx.Response(200, json={"id": 6, "duration": 60})
            if url.endswith("/appointments") and request.method == "POST":
                posts.append(1)
                if len(posts) == 1:
                    raise httpx.ConnectError("cut")
                return httpx.Response(201, json={"id": 55})
            if url.endswith("/appointments"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "j.db")
            a = make_adapter(handler, db, allow_writes=True)
            sid = seed_slot(a)
            hold_a = run(a.create_hold(sid))
            out_a = run(a.confirm(hold_a.hold_id, dict(GUEST), "k-block-a"))
            self.assertEqual(out_a["error"], "write_outcome_unknown")
            # Same slot, NEW key: must not POST while A is unresolved.
            hold_b = run(a.create_hold(sid))
            out_b = run(a.confirm(hold_b.hold_id, dict(GUEST), "k-block-b"))
            self.assertEqual(out_b["error"], "write_outcome_unknown")
            self.assertEqual(posts, [1])

    def test_strict_guest(self):
        def handler(request):
            return httpx.Response(404, text="no")

        with tempfile.TemporaryDirectory() as d:
            a = make_adapter(handler, os.path.join(d, "j.db"), allow_writes=True)
            disp = Dispatcher(slot=a)
            # 'name' maps into first/last; full fields accepted:
            out = run(
                disp.dispatch(
                    "confirm_slot_booking",
                    {
                        "hold_id": "h",
                        "guest": {
                            "name": "Mari Maasikas",
                            "email": "m@example.ee",
                            "phone": "+3721",
                        },
                        "idempotency_key": "gk-1",
                    },
                )
            )
            self.assertEqual(out["error"], "hold_expired_or_unknown")
            # Missing last name / contact: rejected outright:
            for bad in (
                {"firstName": "Mari", "phone": "+3721"},
                {"firstName": "Mari", "lastName": "M", "phone": "+3721"},
                {"firstName": "Mari", "lastName": "M", "email": "m@e.ee"},
            ):
                with self.assertRaises(ProviderError):
                    run(
                        disp.dispatch(
                            "confirm_slot_booking",
                            {"hold_id": "h", "guest": bad, "idempotency_key": "gk-x"},
                        )
                    )


if __name__ == "__main__":
    unittest.main()
