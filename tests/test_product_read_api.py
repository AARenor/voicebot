"""Operator schedule: backend truth without guest data or write capability."""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.booking.easyappointments import EasyAppointmentsAdapter
from app.server import build_stack, create_app


AUTH = {"Authorization": "Bearer fixture-operator"}


def venue_day():
    return datetime.now(ZoneInfo("Europe/Tallinn")).date().isoformat()


def provider_handler(rows, calls, *, timezone="Europe/Tallinn", failure=None):
    def handle(request):
        calls.append(request)
        path = request.url.path
        if failure is not None:
            if isinstance(failure, Exception):
                raise failure
            return httpx.Response(
                failure, text="PRIVATE backend body", headers={"Retry-After": "9999"}
            )
        if path.endswith("/services"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 6,
                        "name": "<img onerror=alert(1)>",
                        "duration": 60,
                        "price": 100,
                    }
                ],
            )
        if path.endswith("/providers"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 2,
                        "firstName": "Demo",
                        "lastName": "Provider",
                        "services": [6],
                        "timezone": timezone,
                        "email": "private@example.test",
                    }
                ],
            )
        if path.endswith("/appointments"):
            return httpx.Response(200, json=rows)
        raise AssertionError("unexpected read path")

    return handle


def row(day=None, **changes):
    day = day or venue_day()
    return {
        "id": 42,
        "start": day + " 10:00:00",
        "end": day + " 11:00:00",
        "status": "Booked",
        "serviceId": 6,
        "providerId": 2,
        "customerId": 9,
        "notes": "PRIVATE",
        **changes,
    }


def make_client(tmp_path, rows, calls, **kwargs):
    adapter = EasyAppointmentsAdapter(
        "https://fixture.invalid",
        "fixture",
        state_db=str(tmp_path / "never-open.db"),
        transport=httpx.MockTransport(provider_handler(rows, calls, **kwargs)),
    )
    with patch.dict(
        "os.environ",
        {
            "OPERATOR_TOKEN": "fixture-operator",
            "VOICEBOT_BUSINESS": "legacy",
        },
        clear=True,
    ):
        app = create_app()
    app.state.stack["booking_reader"] = adapter
    return TestClient(app), adapter


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.setenv("OPERATOR_TOKEN", "fixture-operator")
    monkeypatch.delenv("EASY_LIVE_TESTS", raising=False)


def test_read_only_construction_never_opens_journal(tmp_path):
    path = tmp_path / "not-created" / "j.db"
    with patch(
        "app.booking.easyappointments._Journal",
        side_effect=AssertionError("reader opened journal"),
    ):
        reader = EasyAppointmentsAdapter(
            "https://fixture.invalid", "fixture", state_db=str(path)
        )
    assert not path.exists()
    assert not reader.operational
    with pytest.raises(Exception, match="writes not enabled"):
        asyncio.run(reader.confirm("h", {}, "key"))
    with pytest.raises(Exception, match="writes not enabled"):
        asyncio.run(reader.cancel("42", "key"))
    asyncio.run(reader.close())


def test_stack_wires_reader_with_writes_disabled_without_journal():
    with patch.dict(
        "os.environ",
        {
            "EASY_BASE_URL": "https://fixture.invalid",
            "EASY_API_KEY": "fixture",
            "EASY_DEMO_WRITES": "0",
            "VOICEBOT_BUSINESS": "legacy",
        },
        clear=True,
    ):
        with patch(
            "app.booking.easyappointments._Journal",
            side_effect=AssertionError("no writes"),
        ):
            stack = build_stack()
    assert stack["slot"] is None
    assert stack.get("booking_reader") is not None
    asyncio.run(stack["booking_reader"].close())


def test_auth_precedes_upstream_and_all_private_responses_no_store(
    tmp_path, monkeypatch
):
    calls = []
    client, _ = make_client(tmp_path, [row()], calls)
    with client:
        for path in ("/api/bookings?date=" + venue_day(), "/api/catalogue"):
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                response = client.get(path, headers=headers)
                assert response.status_code == 403
                assert response.headers.get("Cache-Control") == "no-store"
            monkeypatch.setenv("OPERATOR_TOKEN", "")
            response = client.get(path, headers=AUTH)
            assert response.status_code == 503
            assert response.headers.get("Cache-Control") == "no-store"
            monkeypatch.setenv("OPERATOR_TOKEN", "fixture-operator")
    assert calls == []


def test_provider_projection_and_exact_fixed_query(tmp_path):
    calls = []
    client, _ = make_client(tmp_path, [row()], calls)
    with client:
        response = client.get(
            "/api/bookings",
            params={
                "date": venue_day(),
                "page": 2,
                "length": 1,
                "fields": "customerId,notes",
            },
            headers=AUTH,
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        body = response.json()
        assert body["source"] == "easyappointments"
        assert body["data_mode"] == "synthetic"
        assert body["page"] == 2 and body["length"] == 1
        assert body["has_more"] == "unknown"
        assert body["items"][0] == {
            "id": 42,
            "start_local": venue_day() + " 10:00:00",
            "end_local": venue_day() + " 11:00:00",
            "timezone": "Europe/Tallinn",
            "time_state": "valid",
            "service_id": 6,
            "service_name": "<img onerror=alert(1)>",
            "provider_id": 2,
            "provider_name": "Demo Provider",
            "status": "Booked",
        }
        assert not any(
            key in response.text
            for key in ("customerId", "notes", "private@example", "price", "PRIVATE")
        )
        appointments = next(r for r in calls if r.url.path.endswith("/appointments"))
        assert dict(appointments.url.params) == {
            "date": venue_day(),
            "page": "2",
            "length": "1",
            "sort": "+start,+id",
            "fields": "id,start,end,status,serviceId,providerId",
        }
        metadata = next(r for r in calls if r.url.path.endswith("/providers"))
        assert (
            metadata.url.params["fields"] == "id,firstName,lastName,services,timezone"
        )
        catalogue = client.get("/api/catalogue", headers=AUTH)
        assert catalogue.status_code == 200
        assert "price" not in catalogue.text and "email" not in catalogue.text


@pytest.mark.parametrize(
    "params",
    [
        {"date": "2026-1-1"},
        {"date": "junk"},
        {"date": "2026-02-30"},
        {"page": "0"},
        {"page": "101"},
        {"page": "1.5"},
        {"length": "0"},
        {"length": "51"},
        {"length": "x"},
        {
            "date": (
                datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=91)
            ).isoformat()
        },
    ],
)
def test_invalid_queries_do_not_read(tmp_path, params):
    calls = []
    client, _ = make_client(tmp_path, [], calls)
    with client:
        response = client.get(
            "/api/bookings", params={"date": venue_day(), **params}, headers=AUTH
        )
        assert response.status_code == 400
        assert response.headers.get("Cache-Control") == "no-store"
    assert calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"id": True},
        {"id": -1},
        {"serviceId": 99},
        {"providerId": 99},
        {"start": "junk"},
        {"end": venue_day() + " 09:00:00"},
        {"status": {"PRIVATE": 1}},
    ],
)
def test_malformed_payload_is_closed_502(tmp_path, changes):
    calls = []
    client, _ = make_client(tmp_path, [row(**changes)], calls)
    with client:
        response = client.get(
            "/api/bookings", params={"date": venue_day()}, headers=AUTH
        )
        assert response.status_code == 502
        assert response.json()["detail"] == "booking_payload_invalid"
        assert response.headers.get("Cache-Control") == "no-store"
        assert "PRIVATE" not in response.text


@pytest.mark.parametrize(
    "failure,status",
    [
        (401, 502),
        (429, 503),
        (500, 503),
        (httpx.ReadTimeout("PRIVATE"), 504),
        (httpx.ConnectError("PRIVATE"), 503),
    ],
)
def test_provider_failures_closed_no_store(tmp_path, failure, status):
    client, _ = make_client(tmp_path, [], [], failure=failure)
    with client:
        response = client.get(
            "/api/bookings", params={"date": venue_day()}, headers=AUTH
        )
        assert response.status_code == status
        assert response.headers.get("Cache-Control") == "no-store"
        assert "PRIVATE" not in response.text
        if failure == 429:
            assert response.headers.get("Retry-After") == "60"


@pytest.mark.parametrize(
    "day,start,end,expected",
    [
        ("2026-01-15", "10:00:00", "11:00:00", "valid"),
        ("2026-07-15", "10:00:00", "11:00:00", "valid"),
        ("2026-03-29", "03:00:00", "03:30:00", "invalid"),
        ("2026-10-25", "03:00:00", "03:30:00", "ambiguous"),
    ],
)
def test_tallinn_wall_time_no_guessed_utc(tmp_path, day, start, end, expected):
    calls = []
    _, reader = make_client(
        tmp_path, [row(day, start=day + " " + start, end=day + " " + end)], calls
    )

    async def exercise():
        try:
            body = await reader.get_operator_bookings(day, page=1, length=50)
            assert body["items"][0]["time_state"] == expected
            assert body["items"][0]["start_local"] == day + " " + start
            assert "start_utc" not in body["items"][0]
        finally:
            await reader.close()

    asyncio.run(exercise())


def test_unknown_timezone_is_visible_warning(tmp_path):
    _, reader = make_client(tmp_path, [row()], [], timezone="not/a-zone")

    async def exercise():
        try:
            body = await reader.get_operator_bookings(venue_day(), page=1, length=50)
            assert body["items"][0]["time_state"] == "unknown_timezone"
            assert body["items"][0]["timezone"] is None
        finally:
            await reader.close()

    asyncio.run(exercise())


def test_empty_page_is_success_not_provider_failure(tmp_path):
    client, _ = make_client(tmp_path, [], [])
    with client:
        response = client.get("/api/bookings", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["has_more"] is False


def test_unconfigured_reader_closed():
    with patch.dict("os.environ", {"OPERATOR_TOKEN": "fixture-operator"}, clear=True):
        with TestClient(create_app()) as client:
            response = client.get("/api/bookings", headers=AUTH)
            assert response.status_code == 503
            assert response.headers.get("Cache-Control") == "no-store"
