# Fictional restaurant demo data

`telephone-demo.json` contains the fictional Meretuule Köök profile, synthetic
guest fixtures and restaurant call examples. The sample table service and
provider are illustrative configuration only; they are not imported into a
backend and do not prove restaurant availability. `restaurant-phone-faq.json`
contains reviewed answers in Estonian, English and Russian. Menu, allergen,
opening-hours, location and real reservation claims stay unverified.

The public website, browser demo, and native telephone worker use a trusted
`restaurant` business context. Restaurant sessions expose no spa/stay or slot
booking tools until a restaurant dataset is configured. The installed private
Easy!Appointments instance still contains its synthetic spa dataset. Do not
enable restaurant writes against it. A future table dataset must define exact
party-size services, tables as providers, operating hours, 90-minute duration,
30-minute intervals, and disabled notifications before the tools can be
reviewed for activation.

Email uses the reserved `example.invalid` domain; phone numbers use the fictional
NANPA 202-555-01xx range. Never send email, dial or text these fixtures. Example
appointments are not confirmed bookings or availability guarantees. Payments
are not collected and no real guest data should be used.
