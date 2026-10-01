# Open-source booking backend comparison

Research snapshot: **2026-10-01**.

## Decision

Use **Easy!Appointments 1.6.0** for the hackathon and frame the booking demo
around spa treatments or consultations.

- It is the smallest system that matches the required domain directly:
  service + provider + working schedule + available slot + appointment.
- Its open-source edition has an official JSON REST API for availability and
  appointment create, read, update, and delete operations.
- It has an operator-facing calendar and administration UI.
- It can be self-hosted without a paid API entitlement.
- The repository already contains an `EasyAppointmentsAdapter`, reducing the
  amount of new integration code needed before the live-instance safety tests.

Use **QloApps** instead only if multi-night room inventory, occupancy, nightly
rates, and hotel-specific reservation semantics become mandatory. Do not force
room nights and spa slots through one contract: retain the separate
`StayAdapter` and `SlotAdapter` boundaries.

## Selection gate

A candidate passes only if all of the following are available in its free,
self-hosted edition:

1. an official, documented integration API rather than browser-endpoint or
   database reverse engineering;
2. availability or inventory reads;
3. supported create, change, and cancel operations;
4. an administration UI in which judges can see the resulting booking; and
5. a practical hackathon deployment path.

Documentation proves capability, not operational safety. The selected system
still has to pass real-instance success, conflict, retry, timeout, and
authorization tests before the adapter may advertise live writes.

## Comparison

| Candidate | Domain and license | API evidence | Deployment / fit | Verdict |
| --- | --- | --- | --- | --- |
| **Easy!Appointments** | Appointment scheduling; GPL-3.0 | Official REST API and OpenAPI specification: availability plus appointment, customer, service, and provider CRUD; Basic auth or a Settings-issued Bearer credential | PHP/MySQL and Docker; exact service/provider/slot model; 1.6.0 was the latest stable release at the check date | **Selected** |
| **Cal.diy** | Appointment scheduling; MIT | API v2 documents slots, temporary slot reservations, booking creation, rescheduling, and cancellation | Node/Postgres with Docker Compose; richer scheduling and hold semantics, but materially heavier. Its own README recommends it only for personal/non-production use and requires advanced administration | **Strong runner-up**, not worth switching for this demo |
| **LibreBooking** | Resource reservations; GPL-3.0 | Official API provides resource availability, schedule slots, and reservation listing/create/update/delete; session-token authentication | PHP/MySQL and Docker; active v6.0.0, but models rooms/equipment more naturally than treatments and therapists | Passes the API gate, weaker domain fit |
| **QloApps** | Hotel PMS/booking engine; OSL-3.0 | Official `hotel_ari` availability/rate API and `bookings` GET/POST/PUT API. The [booking implementation](https://github.com/Qloapps/QloApps/blob/develop/classes/webservice/WebserviceSpecificManagementBookings.php) supports room/date changes and cancellation through `booking_status=3`; the [resource declaration](https://github.com/Qloapps/QloApps/blob/develop/classes/webservice/WebserviceRequest.php) intentionally forbids direct DELETE | PHP/MySQL and Docker; hotel-native but larger and XML-heavy; v1.7.0 is the latest stable release found | Best open-source option **for room nights only** |
| **pretix** | Event ticketing; AGPL-3.0 with additional terms | Mature official API for events, quotas, cart reservations, orders, changes, cancellation/deletion, and idempotency | Strong for spa-day tickets or workshops, but not for therapist working plans or recurring treatment slots. Its additional terms also restrict SaaS/third-party-service use | API-capable, wrong domain |
| **ERPNext/Frappe** | ERP; GPL-3.0 | Frappe generates CRUD APIs for DocTypes, but generic CRUD is not a hotel/spa availability contract | Far heavier than a scheduler; the former Frappe hospitality repository is archived and ERPNext describes hospitality as early-stage | Reject for the hackathon |
| **HotelDruid** | Hotel management; AGPL-3.0 | No official free-core API covering room availability and reservation lifecycle was found | LAMP deployment is simple, but booking-engine/channel-manager functionality is split into hosted add-ons | Fails the API gate |
| **Solidres** | Open-source Joomla/WordPress booking extension | No verified free-edition API covering availability plus create/change/cancel was found | CMS-coupled and add-on dependent | Fails the API gate |
| **Odoo Community hotel modules** | ERP plus third-party modules | Odoo has generic RPC/CRUD, but no official Community hotel module supplies the required semantics | Hotel modules found were third-party and commonly paid; heavy deployment | Fails the free-core gate |

Event systems such as Alf.io and Hi.Events were also excluded because their
inventory unit is an event ticket rather than a provider's timed service.
Rallly is a scheduling poll, not a booking system, and OpenMeetings is a video
conferencing system.

## Why Easy!Appointments wins

### Against Cal.diy

Cal.diy has the strongest technical alternative API. In particular, its API
documents temporary slot reservations, which Easy!Appointments does not.
However, the hackathon does not need Cal.diy's broader scheduling platform,
and its Node/Postgres stack, larger configuration surface, and explicit
personal/non-production warning add risk. It would also require a new adapter.

Choose Cal.diy only if its richer calendar/timezone integration or an explicit
provider-side temporary slot reservation becomes a hard requirement.

### Against LibreBooking

LibreBooking has a real writable API, not merely internal web routes. Its core
object is a reservable resource, though. Representing treatments, durations,
prices, and therapist/service compatibility would require conventions on top
of that model. Easy!Appointments already exposes those concepts directly.

### Against QloApps

QloApps is the only evaluated free system with a credible hotel-native API.
It should remain the room-demo fallback, but it brings room types, assigned
rooms, occupancy, rates, taxes, orders, and XML schemas that the chosen spa
story does not need. Selecting it would also mean completing the current
`QloAppsAdapter` stub instead of validating the existing slot adapter.

### Against event and ERP systems

pretix has an unusually mature API, including idempotency, but mapping every
treatment slot to event/ticket inventory would make the demo misleading.
ERPNext/Frappe provides generic data access rather than a ready-made booking
contract and would add an ERP deployment to solve a small scheduling problem.

## Integration and safety implications

Easy!Appointments documents the required lifecycle but does not document a
provider-side idempotency key or temporary hold primitive. Therefore:

- keep the endpoint in `EASY_BASE_URL` and the credential in `EASY_API_KEY`,
  never in source;
- re-read availability immediately before appointment creation;
- prove that concurrent creates for the same slot produce exactly one booking;
- after a timeout or unknown write outcome, query appointments before retrying;
- test update and delete against the deployed version, not only mocks; and
- keep the [adapter](../../app/booking/easyappointments.py) non-operational by
  default; its explicit synthetic-demo opt-in is not permission for real traffic
  until the
  [R-003 race and R-004 reconciliation gates](../architecture/risk-register.md)
  pass.

**Installation follow-through (2026-10-01):** the pinned private 1.6.0 service
and [runbook](../../deploy/easyappointments/README.md) now exist. Opt-in
`tests/test_easyappointments_installed.py` passes availability, customer/
appointment lifecycle, cancellation, authorization failure, malformed payloads,
same-slot contention and committed-write timeout/restart reconciliation. PUT
update is tested directly (send both start/end); rescheduling is still not in
`SlotAdapter`. Exact 1.6.0 source and the installed behavior confirm REST POST
does not enforce overlap exclusion: the SQLite/file-lock journal protects only
our controlled single-host writer. Production gates remain open.

## First-party sources

Checked 2026-10-01:

- Easy!Appointments [repository](https://github.com/alextselegidis/easyappointments),
  [REST API guide](https://github.com/alextselegidis/easyappointments/blob/develop/docs/rest-api.md),
  [OpenAPI specification](https://github.com/alextselegidis/easyappointments/blob/develop/openapi.yml),
  and [releases](https://github.com/alextselegidis/easyappointments/releases)
- Cal.diy [repository and deployment warning](https://github.com/calcom/cal.diy),
  [booking API reference](https://github.com/calcom/cal.diy/blob/main/agents/skills/calcom-api/references/bookings.md),
  and [slot API reference](https://github.com/calcom/cal.diy/blob/main/agents/skills/calcom-api/references/slots-availability.md)
- LibreBooking [repository](https://github.com/LibreBooking/librebooking),
  [API documentation](https://github.com/LibreBooking/librebooking/blob/develop/docs/source/API.rst),
  [GPL-3.0 license](https://github.com/LibreBooking/librebooking/blob/develop/LICENSE.md),
  and [Docker deployment](https://github.com/LibreBooking/docker)
- QloApps [repository](https://github.com/Qloapps/QloApps),
  [webservice basics](https://devdocs.qloapps.com/webservice/basic-topics.html),
  and [availability/bookings APIs](https://devdocs.qloapps.com/webservice/advanced-api-uses.html)
- pretix [repository](https://github.com/pretix/pretix),
  [REST API](https://docs.pretix.eu/dev/api/), and
  [license](https://github.com/pretix/pretix/blob/master/LICENSE)
- Frappe [REST API](https://docs.frappe.io/framework/user/en/api/rest),
  [ERPNext hospitality page](https://docs.frappe.io/erpnext/hospitality), and
  [archived hospitality repository](https://github.com/frappe/hospitality);
  ERPNext's core license is
  [GPL-3.0](https://github.com/frappe/erpnext/blob/develop/license.txt)
- [HotelDruid](https://www.hoteldruid.com/) and its
  [AGPL-3.0 license](https://github.com/digital-druid/hoteldruid/blob/master/LICENSE),
  [Solidres](https://www.solidres.com/), and
  [Odoo Apps](https://apps.odoo.com/)
