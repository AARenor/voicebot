# Pärnu booking-system evidence

Research snapshot: **2026-09-30**. This note is an evidence ledger for the
voicebot demo and future hotel sales work. It distinguishes current adoption
from vendor customer lists and stale indexed booking pages.

## Executive conclusion

- **BOUK is currently used by at least 10 accommodation properties in Pärnu
  city.** Each confirmed row below has both an official-property-site link to
  `bouk.io` and an active, non-demo property returned by BOUK's public booking
  API.
- **No major Pärnu spa hotel is currently confirmed to use BOUK for timed spa
  treatments.** BOUK supports rooms and hourly services in one product, but
  the major Pärnu spa hotels checked currently point to SALBOS instead.
- **SALBOS is the strongest production target for Pärnu spa hotels.** Hedon,
  ESTONIA Resort/Medical Spa, Wasa Resort, Tervise Paradiis, Tervis Medical
  Spa, and Viiking expose SALBOS-style hotel/spa booking shops or are listed by
  SALBOS as users.
- For the hackathon, BOUK is still the best locally relevant single-system
  trial: its product supports daily, hourly, and monthly room/service inventory,
  and its current frontend states a 14-day full-feature trial without a credit
  card. Official API access is normally part of the Professional plan, so trial
  API access must be confirmed before implementation.
- **No evidence of an Estonian QloApps deployment was found.** Do not claim
  that Estonian hotels use QloApps. It remains a technically suitable
  open-source demo backend only.

## Confirmation standard

A property is **confirmed current** only when all of these hold:

1. The property's official website currently links to a `bouk.io/booking/...`
   URL.
2. `GET https://api.bouk.io/hotels/{id}/load` returns the expected property.
3. The BOUK response reports `active: true` and `isDemo: false`.

Search-engine results and BOUK's customer page are discovery evidence only.
Where the current official property site points elsewhere, that current link
wins over an older indexed BOUK page.

## Confirmed current BOUK properties — Pärnu city

| Property | Type | BOUK ID | Snapshot inventory | Official-site evidence | BOUK evidence |
| --- | --- | ---: | ---: | --- | --- |
| Pärnu Hotel | Hotel | 505 | 31 rooms | [hotelparnu.com](https://www.hotelparnu.com/) links to BOUK | [booking engine](https://bouk.io/booking/parnu/505/rooms) |
| Rannahotell | Hotel | 191 | 64 rooms | [rannahotell.ee](https://rannahotell.ee/) links to BOUK | [booking engine](https://bouk.io/booking/rannahotell/191/rooms) |
| Frost Boutique Hotel | Hotel with sauna/relaxation area | 240 | 14 rooms | [frosthotel.ee](https://frosthotel.ee/) links to BOUK | [booking engine](https://bouk.io/booking/frost/240/rooms) |
| Rosenplänter Boutique Hotel | Hotel | 257 | 13 rooms | [rosenplanter.ee](https://rosenplanter.ee/) links to BOUK | [booking engine](https://bouk.io/booking/rosenplanter/257/rooms) |
| Kurgo Villa Hotel | Hotel | 355 | 28 rooms | [kurgovilla.ee](https://kurgovilla.ee/) links to BOUK | [booking engine](https://bouk.io/booking/kurgovilla/355/rooms) |
| Hotel Hansalinn | Hotel | 488 | 11 rooms | [hansalinn.ee](https://hansalinn.ee/) links to BOUK | [booking engine](https://bouk.io/booking/hansalinn/488/rooms) |
| Hommiku Hostel-Guesthouse | Hostel | 429 | 22 rooms | [hommikuhostel.ee](https://hommikuhostel.ee/) links to BOUK | [booking engine](https://bouk.io/booking/hommikuhostel/429/rooms) |
| Embrace Guestrooms & Apartments | Guestrooms/apartments | 280 | 12 rooms | [embrace.ee](https://embrace.ee/) links to BOUK | [booking engine](https://bouk.io/booking/embrace/280/rooms) |
| Reldor Motel | Motel/hotel | 509 | 44 rooms | [reldor.ee/motell](https://reldor.ee/motell/) links to BOUK | [booking engine](https://bouk.io/booking/reldor/509/rooms) |
| Alice Backyard | Apartments | 439 | 28 units in snapshot | [alicebackyard.ee](https://alicebackyard.ee/) links to BOUK | [booking engine](https://bouk.io/booking/alice-backyard/439/rooms) |

Inventory counts are a point-in-time API snapshot, not contractual property
capacity. They are useful for identifying a real, configured, non-demo account.

### Spa caveat

Frost is listed by Visit Pärnu as having a sauna/relaxation area, but its BOUK
`search/extra-services` response was empty on the research date. This confirms
BOUK for Frost's hotel rooms, **not** for public spa appointment scheduling.
The other confirmed Pärnu-city rows are primarily accommodation evidence.

## Pärnu County and adjacent candidates

| Property | Status | Evidence |
| --- | --- | --- |
| Viisnurga Holiday Home, Uulu | Confirmed current; active non-demo BOUK property and official site links to BOUK | [official site](https://www.viisnurgapuhkemajad.ee/) · [BOUK](https://bouk.io/booking/viisnurga/284/rooms) |
| Reiu Holiday Centre, Paikuse | Official site links to BOUK, but BOUK API reports `isDemo: true`; do not count as a production customer without re-checking | [official site](https://reiupuhkekeskus.ee/) · [BOUK](https://bouk.io/booking/reiupuhkekeskus/924/rooms) |
| Tõhela Lake Holiday Village | Active non-demo BOUK API property, but no current BOUK link was found on the official site; vendor-listed/unconfirmed | [official site](https://www.tohelajarvepk.ee/) · [BOUK](https://bouk.io/booking/tohela/442/rooms) |

## Stale or migrated BOUK evidence — do not cite as current

| Property | Old/indexed BOUK evidence | Current evidence and decision |
| --- | --- | --- |
| Hedon Spa & Hotel | Indexed BOUK property ID 189; API still says active but exposes zero room types | Current official hotel and treatment buttons point to `hotel.hedonspa.com` / `online.hedonspa.com`, both SALBOS-linked WordPress/WooCommerce shops. Treat BOUK as legacy. |
| Viiking Spa Hotel | Indexed BOUK property ID 154 | BOUK load response is empty; current official site points to `hotel.viiking.ee` and `spa.viiking.ee`, both SALBOS-linked. Stale. |
| Wasa Resort | Indexed BOUK property ID 492 | BOUK load response is empty; current official site points to `hotel.wasahotels.ee` and `spa.wasahotels.ee`, both SALBOS-linked. Stale. |

This table explains why search results alone overstate BOUK's Pärnu spa
footprint.

## Local production systems

### SALBOS

SALBOS's official customer list names multiple Pärnu hotel/spa operators,
including ESTONIA Medical Spa & Hotel, Tervis Medical Spa, Tervise Paradiis,
Hedon Spa & Hotel, ESTONIA Resort Hotel & Spa, Wasa Resort, and Viiking Spa
Hotel:

- [SALBOS customer list](https://salbos.com/en/)
- [Hotel module](https://salbos.com/en/hotel/)
- [Spa module](https://salbos.com/en/spa/)
- [Tervise Paradiis: transition to SALBOS](https://terviseparadiis.ee/en/transition-to-the-salbos-software/)

Checked SALBOS-linked shops expose standard WooCommerce REST namespaces
(`wc/v1`, `wc/v2`, `wc/v3`, `wc/store/v1`). Public product reads work, for
example:

- `https://spa.terviseparadiis.ee/wp-json/wc/store/v1/products`
- `https://spa.viiking.ee/wp-json/wc/store/v1/products`

That proves a standard catalogue/API layer, not authorization to create real
bookings. Room availability and booking writes may use private SALBOS logic.
Production work requires property/vendor credentials and documentation.

### D-EDGE

Hestia Hotel Strand's current official booking buttons point to D-EDGE's
`secure-hotel-booking.com` engine. D-EDGE advertises GraphQL connectivity but
does not offer a public self-service write sandbox suitable for this hackathon.

## BOUK trial and API implications

Official BOUK sources:

- [Features](https://bouk.io/product/features): one system for room or service
  inventory sold daily, hourly, or monthly; unified calendar; multi-service
  booking; property and spa positioning.
- [Pricing](https://bouk.io/pricing): full-access trial, no credit card,
  cancel anytime; API access/support is listed in the Professional plan.
- [Customers](https://bouk.io/customers): broad Estonian adoption.
- [Terms](https://bouk.io/page/terms): service is operated by OpenHotels OÜ
  under Estonian law.

The current production frontend bundle states: “14 days free trial for all
features, no credit card required.” Because API access is normally a
Professional-plan feature, verify that the trial exposes official API
credentials/docs before writing the BOUK adapter. Do not build against
undocumented browser endpoints as a production integration.

## Recommended claims

Safe:

> BOUK is used by multiple Pärnu hotels, including Pärnu Hotel, Rannahotell,
> Frost Boutique Hotel, Rosenplänter, Kurgo Villa, Hansalinn, Hommiku Hostel,
> Embrace, Reldor Motel, and Alice Backyard. BOUK supports both room and hourly
> service inventory in one platform. Major Pärnu spa hotels commonly use
> SALBOS, which is the next production connector target.

Unsafe — do not claim:

- “Pärnu's major spa hotels currently use BOUK.”
- “Hedon, Viiking, or Wasa currently use BOUK.”
- “SALBOS booking writes are available through its public WooCommerce API.”
- “Estonian hotels use QloApps.”

## Re-verification checklist

Before using this evidence in a future pitch:

1. Re-open each official property site and confirm its booking link.
2. Re-check BOUK `active` / `isDemo` state.
3. Treat a current official-site link as stronger than search-index history.
4. Confirm official write API credentials and scope before promising booking,
   change, or cancellation support.
