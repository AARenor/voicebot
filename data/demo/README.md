# Fictional telephone demo data

`telephone-demo.json` contains a fictional spa profile, three synthetic guests,
three illustrative appointments, manual FAQ examples and Estonian call prompts.
Email uses the reserved `example.invalid` domain; phone numbers use the fictional
NANPA 202-555-01xx range. Never send email, dial or text these fixtures.

The installed Easy!Appointments backend **already** contains:

- **Voicebot Synthetic Spa Demo**;
- **Demo spa consultation**, service 1, 30 minutes;
- **Demo Therapist**, provider 2;
- weekdays 09:00–17:00, break 12:00–13:00, weekends closed, Europe/Tallinn.

Those IDs are installation-specific. Use `get_slot_catalogue` before searching.
The JSON's `tool_example.search.arguments` matches the current telephone tool
schema; `guests[].guest` matches the new-customer confirmation payload. Obtain
slot/hold/booking IDs from actual tool results, never from fixture labels.

**Saving this file does not import customers/appointments or add property FAQ to
the agent.** Example bookings are not confirmed or availability guarantees. The
fictional property/FAQ is manual reference only; the worker keeps its existing
synthetic-demonstration disclosure and excludes unapproved property FAQ. Dates
are examples based on 2026-10-02; choose a future working day when testing later.
Do not quote prices, collect payments or present this as a real spa.

Use the Estonian call prompts to test disclosure, search, consent/decline and
same-call cancellation. In a booking test, independently read the appointment
from the backend and clean up only the synthetic records created by that test.

Existing end-to-end SDK/backend verification, which creates and cleans its own
unique synthetic customer/appointment:

```bash
docker exec -i livekit-worker-1 python - < deploy/telephony/booking_probe.py
```

Public telephone calling still requires the DIDWW number and public SIP/RTP
route. See [telephone runbook](../../deploy/telephony/README.md) and
[configured backend dataset](../../deploy/easyappointments/README.md).
