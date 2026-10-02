import asyncio
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("livekit.agents")

from app.booking.easyappointments import EasyAppointmentsAdapter
from app.telephone import CallTools
from tests.test_telephone import ENV


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "demo_booking_probe", ROOT / "deploy/telephony/booking_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_probe_uses_preparation_transcript_gate_and_exact_scoped_cleanup(
    tmp_path, capsys
):
    async def run():
        customers = {
            1: {"id": 1, "email": "demo.esimene@example.invalid"},
            2: {"id": 2, "email": "demo.esimene+foreign-call@example.invalid"},
        }
        appointments = {
            1: {"id": 1, "customerId": 1},
            2: {"id": 2, "customerId": 2},
        }
        foreign_customers, foreign_appointments = (
            copy.deepcopy(customers),
            copy.deepcopy(appointments),
        )
        writes, states = [], []
        service = {"id": 1, "name": "Demo spa consultation", "duration": 30}

        def backend(request):
            path = request.url.path.rsplit("/api/v1", 1)[-1]
            if request.method in {"POST", "DELETE"}:
                writes.append(
                    (
                        request.method,
                        path,
                        json.loads(request.content) if request.content else None,
                    )
                )
            if request.method == "GET":
                if path == "/services":
                    return httpx.Response(200, json=[service])
                if path == "/services/1":
                    return httpx.Response(200, json=service)
                if path == "/providers":
                    return httpx.Response(
                        200, json=[{"id": 2, "name": "Demo Therapist", "services": [1]}]
                    )
                if path == "/availabilities":
                    return httpx.Response(200, json=["10:30"])
                if path == "/customers":
                    return httpx.Response(200, json=list(customers.values()))
                if path == "/appointments":
                    return httpx.Response(200, json=list(appointments.values()))
                if path.startswith("/appointments/"):
                    booking_id = int(path.rsplit("/", 1)[-1])
                    return (
                        httpx.Response(200, json=appointments[booking_id])
                        if booking_id in appointments
                        else httpx.Response(404)
                    )
            if request.method == "POST" and path == "/customers":
                customers[3] = {"id": 3, **json.loads(request.content)}
                return httpx.Response(201, json=customers[3])
            if request.method == "POST" and path == "/appointments":
                appointments[3] = {"id": 3, **json.loads(request.content)}
                return httpx.Response(201, json=appointments[3])
            if request.method == "DELETE" and path.startswith("/appointments/"):
                booking_id = int(path.rsplit("/", 1)[-1])
                return httpx.Response(
                    204 if appointments.pop(booking_id, None) else 404
                )
            if request.method == "DELETE" and path.startswith("/customers/"):
                customer_id = int(path.rsplit("/", 1)[-1])
                return httpx.Response(204 if customers.pop(customer_id, None) else 404)
            raise AssertionError("unexpected fixture request")

        transport = httpx.MockTransport(backend)
        adapter = EasyAppointmentsAdapter(
            "http://fixture",
            "fixture",
            transport=transport,
            state_db=str(tmp_path / "probe.db"),
            allow_writes=True,
        )
        client = httpx.AsyncClient(
            base_url="http://fixture/index.php/api/v1", transport=transport
        )

        def state_factory(dispatcher):
            state = CallTools(dispatcher)
            states.append(state)
            return state

        with (
            patch.dict(
                "os.environ", {**ENV, "EASY_BASE_URL": "http://fixture"}, clear=True
            ),
            patch.object(probe, "EasyAppointmentsAdapter", return_value=adapter),
            patch.object(probe, "CallTools", side_effect=state_factory),
            patch.object(probe.httpx, "AsyncClient", return_value=client),
        ):
            await probe.main()
        assert customers == foreign_customers
        assert appointments == foreign_appointments
        guests = [
            body
            for method, path, body in writes
            if method == "POST" and path == "/customers"
        ]
        assert len(guests) == 1
        assert guests[0]["email"] == f"demo.esimene+{states[0].call_id}@example.invalid"
        assert guests[0]["phone"] == "+12025550101"
        assert (
            sum(
                method == "POST" and path == "/appointments"
                for method, path, _ in writes
            )
            == 1
        )
        assert all(
            path
            not in {
                "/customers/1",
                "/customers/2",
                "/appointments/1",
                "/appointments/2",
            }
            for method, path, _ in writes
            if method == "DELETE"
        )
        assert states[0].outcome == "booking_cancelled"

    asyncio.run(run())
    assert "PASS native SDK tools" in capsys.readouterr().out


def test_probe_failure_is_nonzero_and_redacted_in_clean_environment():
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/telephony/booking_probe.py")],
        env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert (
        "FAIL synthetic booking probe: ValueError (details withheld)" in result.stderr
    )
    assert "Traceback" not in result.stderr
