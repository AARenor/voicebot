# Fictional telephone demo data

`telephone-demo.json` contains a fictional spa profile, three synthetic guests,
three illustrative appointments, approved fictional FAQ and Estonian call prompts.
`booking-faq.json` supplies 50 reviewed questions, aliases and replies in Estonian,
English and Russian. The shared native/HTTP policy recognizes complete questions
and reviewed alternate wording, including up to three questions in one turn.
Extra booking commands continue through planning; FAQ text never authorizes a write.

Room/service catalogues, durations, amenities and hours are rendered from fresh
tool results. Saved research answers and `observed_answer_et` are documentation,
not a runtime source of catalogue facts. Availability and room quotes still need
the existing search/planning tools. Booking status uses only this conversation's
owned result; missing hotel policies are disclosed instead of guessed. An unknown
question gets a clarification, while unsupported success claims retain the
established verification warning. Translation templates preserve backend values.
Matching uses complete reviewed phrases rather than a shared keyword: a Wi-Fi
password question, breakfast menu or hotel-hours question cannot silently become
a different amenity or spa-hours answer. Short booking details continue to the
existing planner.

Email uses the reserved `example.invalid` domain; phone numbers use the fictional
NANPA 202-555-01xx range. Never send email, dial or text these fixtures.

The installed Easy!Appointments backend **already** contains:

- **Voicebot Synthetic Spa Demo**;
- **Demo spa consultation**, service 1, 30 minutes;
- **Demo Therapist**, provider 2;
- weekdays 09:00–17:00, break 12:00–13:00, weekends closed, Europe/Tallinn.

Those IDs are installation-specific. Use `get_slot_catalogue` before searching.
The JSON's `tool_example.search.arguments` matches the current telephone tool
schema. `CallTools` loads profile/FAQ/guest fixtures and supplies the backend guest
payload itself; the model selects only a fixture ID, never contact fields. Obtain
slot/hold/booking IDs from actual tool results, never from fixture labels.

**This file never imports customers, appointments, installation IDs or hours.**
The agent uses only its approved fictional profile/FAQ/guest fixtures. Example
bookings are not confirmed or availability guarantees. The prompt includes the
current date in Europe/Tallinn; resolve live catalogue IDs and query backend
availability instead of reusing the file's example dates or hours.
Do not quote prices, collect payments or present this as a real spa.

Use `get_demo_profile` for the profile, FAQ and call-scoped guest contacts. Each
fixture email is scoped as `demo.esimene+<call_id>@example.invalid` (and similarly
for the other guests), so concurrent calls and cleanup cannot match one another.
The trusted caller can supply an opaque 8–48 character `[A-Za-z0-9_-]` scope to
`CallTools(..., call_id=...)`; the model cannot. Otherwise a UUID is generated.
The native worker publishes only `voicebot.call_id` in participant attributes.

After `search_slots` → `hold_slot`, call `prepare_demo_booking` with the owned
`hold_id` and optional `guest_fixture_id` (default `guest-001`). Read its live
service/provider/date/time recap and ask for the exact consent phrase. Only a
**subsequent final user transcript** observed by the trusted STT/HTTP caller can
authorize `confirm_slot_booking({"hold_id": ...})`. Preparation/approval expires
after 60 seconds; decline, ambiguity or a new proposal requires a new recap.
No `guest`, `consent` or model-supplied ownership fields authorize a write.
Cancellation requires the latest owned booking and explicit final user intent.
Successful write retries replay the same outcome with no additional write.

Use the Estonian call prompts to test disclosure, search, consent/decline and
same-call cancellation. In a booking test, independently read the appointment
from the backend and clean up only the synthetic records created by that test.

Existing end-to-end SDK/backend verification, which creates and cleans its own
call-scoped synthetic customer/appointment (including deterministic transcript
gates; this script is not a spoken call):

```bash
docker exec -i livekit-worker-1 python - < deploy/telephony/booking_probe.py
```

Public telephone calling still requires the DIDWW number and public SIP/RTP
route. See [telephone runbook](../../deploy/telephony/README.md) and
[configured backend dataset](../../deploy/easyappointments/README.md).
