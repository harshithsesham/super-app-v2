---
name: "duffel"
description: "Search, book, pay for, and manage flights through Duffel"
allowed-tools: ["exec", "widget.create"]
metadata: { "includeInPrompt": true }
---

# Duffel Flight Booking

Use only this public CLI surface:

```text
search
seat-options
validate-booking
book
booking-status
cancellation-quote
cancel-booking
```

Never invent identifiers, call undocumented endpoints, or expose `off_`, `ord_`,
or `ore_` ids to travelers. Run commands directly: do not pipe output through
`head` or custom parsers, which can hide errors or required offer data.

## Booking flow

1. Start by searching the complete itinerary and exact passenger mix together.
2. Show 3–6 complete offers; let the traveler choose one.
3. Optionally show `seat-options` and collect bookable seats.
4. Collect all required passenger details together.
5. Before starting any purchase step, ask once whether the user wants Muse to book through Duffel or directly on the airline’s website. Explain that Duffel is usually more seamless; with the airline option, Muse will still attempt the entire booking in Browser but may occasionally need user input for decisions or required interactions. Never imply that the user must complete the booking themselves, and do not speculate about specific limitations.
6. If the user chooses the airline, leave the Duffel flow and continue the booking with `browser.spawn_task` following `../booking/references/browser-booking.md`. Ask whether they want to log in to the airline website as the first step, and re-check all details. Prepare the booking through the airline's final review page, but do not submit or pay. Relay the exact total, fees, and fare conditions; only after the traveler approves those exact terms, steer the same task to submit. Verify that the task saw a confirmation before reporting success.
7. If the user chose Duffel flow: run `validate-booking` until `ready_to_book: true`.
8. If the user chose Duffel flow: list Stripe Link payment methods and select an exact returned `pm_…` id.
9. If the user chose Duffel flow: call `book` once with the same offer, booking document, and seats.
10. If the user chose Duffel flow: on success, report every carrier confirmation reference/PNR and ticket status.

Never skip validation or silently change the selected offer, route, passenger
mix, fare, or seats before booking.

## Search and compare

```sh
duffel search --origin SFO --destination LAX --departure-date 2026-09-30
duffel search --origin SFO --destination LAX --departure-date 2026-09-30 \
  --return-date 2026-10-04 --adults 2 --child-age 8 --lap-infants 1
duffel search --leg SFO:LAX:2026-09-30 --leg LAX:JFK:2026-10-03 --adults 2
duffel search --origin SFO --destination LAX --departure-date 2026-09-30 \
  --max-connections 0 --sort duration --limit 30
```

Use `--limit 30` for comparison searches so the shortlist is not based on a
narrow result set, then present only the 3–6 most useful distinct offers. Start
with every flight requested as one itinerary in the same search: use
`--return-date` for a round trip and repeated `--leg` arguments for multi-city
travel.

Use exact three-letter airport IATA codes, not metro codes such as `NYC`.
Resolve unambiguous places, but confirm ambiguous dates or materially different
airport choices; never guess an obscure or ambiguous code. Search each
acceptable airport pair separately; results are hard-filtered and nearby-airport
inventory is excluded. Before concluding that an airline has no service to a
city, check its relevant airports separately. Zero results means only that the
scanned Duffel inventory contained no match. For an exact-flight request, match
the number in returned Duffel offers and do not substitute a different flight
or use schedule data as proof it is bookable.

Passenger pricing is fixed at search:

- `--adults` is the adult count.
- Repeat `--child-age` for each seated traveler aged 2–17, using age on the
  itinerary's final travel date.
- `--lap-infants` counts travelers under two without a seat; each must have a
  different accompanying adult.

Ask for missing ages once. Ask whether an infant is seated or on a lap; never
infer it. This integration cannot reliably book an infant under two in their
own seat, so do not validate or pay for that case; direct it to the airline.
Never search a known child as an adult or claim a child will be repriced at
booking. Search again whenever the passenger mix changes.

Prefer one combined Duffel offer and booking for the complete itinerary. If no
combined offer contains every requested leg, or the traveler explicitly asks
for separate tickets, split only with their agreement before the first `book`.
Explain that each
booking has its own confirmation, fare conditions, approval, and payment; later
offers are not held while an earlier one is purchased, so a later failure can
leave earlier tickets booked. Compare the combined total. Compare useful
alternatives such as cheapest, fastest, nonstop, and explicitly refundable,
and identify all legs and total party price. Results are limited to Duffel
inventory.

Present the shortlist with `widget.create`, using `kind: "list"`. Put the
list title and `items` inside `data`. For each item, use `type: "flight"`,
put the airline and total price with currency in `title`, the route and
airport-local departure and arrival times in `subtitle`, and duration, stops,
and fare conditions in `tertiary_title`. Include both slices for round trips
and mark next-day arrivals `+1`. Copy an airline image URL from the result into
`image_url` when available. Place the returned `embed_token` in the reply. If
the client cannot render the widget, use compact Markdown bullets with the
same flight details. Treat `refundable` and `changeable` as three-valued:
`yes`, `no`, or `not stated`.

Fare brand, cabin, baggage, refundability, and changeability are optional
provider facts. Preserve passenger/segment differences; render missing facts as
“not stated,” never “none,” “not allowed,” or “non-refundable.” Airport-local
times must not be timezone-converted without an explicit airport timezone.
`--refundable` means refundable before departure with no stated positive
penalty, not “cancel anytime.” Never infer baggage or airline-standard fees.

After selection, use `validate-booking`'s `selected_offer` as the canonical
itinerary, price, baggage, and fare-condition snapshot.

## Seats

Use `seat-options` only after shortlisting. It returns passenger-specific,
bookable Duffel services; an omitted seat is unavailable, while `$0.00` is a
bookable seat with no added fee. Use `row` and `section` for adjacency—seats on
opposite sides of an aisle are not adjacent. Seat maps are carrier-dependent
and inventory remains live.

Choose at most one seat per passenger per segment and never duplicate a seat.
Pass every choice to validation and booking using the returned one-based
passenger and segment numbers:

```sh
duffel validate-booking --offer-id off_… --booking-json '{...}' \
  --seat 1:1:28B --seat 2:1:28C
```

## Passenger details

After offer selection, collect only:

- each traveler's legal given/family name, birth date, title, and gender;
- one reachable trip email and phone, reusable for passengers when designated
  as their shared contact;
- the accompanying adult for each lap infant; and
- passport details only when validation requires them.

Allowed titles are `mr`, `ms`, `mrs`, `miss`, and `dr`; gender is `m` or `f`.
A required passport uses `type: "passport"`, its number as
`unique_identifier`, a two-letter uppercase `issuing_country_code`, and
`expires_on` in `YYYY-MM-DD`. Never send an empty document, invent identity
data, or ticket an unborn traveler; explain that booking must wait until birth.
Do not promise the same fare, availability, or adjacent seats later.

Mention optional loyalty numbers and seat availability once without blocking.
When loyalty is supplied, validation verifies programme support, attaches it
to the offer passenger, refreshes pricing, and confirms it remained attached.
Unknown, unsupported, or failed attachment blocks checkout; omit it only with
the traveler's explicit agreement. This preparation has no HITL.
Loyalty benefits remain subject to the airline.

Keep passengers in search order. Do not include Duffel passenger ids or fields
owned by the CLI (`id`, `infant_passenger_id`, `user_id`, `type`,
`selected_offers`, `services`, `payment`, or `payments`). The CLI assigns offer
slots, validates age/type compatibility, and rejects other undocumented fields
before checkout.

```json
{
  "data": {
    "passengers": [{
      "given_name": "Legal given name",
      "family_name": "Legal family name",
      "born_on": "1990-01-01",
      "title": "ms",
      "gender": "f",
      "email": "trip-contact@example.com",
      "phone_number": "+14155550123",
      "loyalty_programme_accounts": [
        {"airline_iata_code": "UA", "account_number": "…"}
      ]
    }]
  }
}
```

For a lap infant, add `"accompanying_adult": 1`, using the adult's one-based
position in the passenger array.

## Validate before payment

```sh
duffel validate-booking --offer-id off_… --booking-json '{...}'
```

Validation refreshes the live offer and checks expiry/current total, passenger
count/order/ages/types, required contacts and documents, lap-infant linkage,
seats, and loyalty. It creates no Stripe request and has no HITL. Ask for every
`required_missing` or `invalid` item together and rerun. Optional omissions do
not block, but requested loyalty must not be silently discarded.

Before `book`, compare every `selected_offer.slices[].from` and `.to` with the
chosen airports. Stop on any mismatch; never infer a route from search args,
flight number, or city name.

A first booking may require the Muse account owner's email and legal name for
a Duffel payment profile. This is not a passenger and is created internally
only after purchase approval. When validation requests it, pass the same values
to validation and booking:

```sh
duffel validate-booking --offer-id off_… --booking-json '{...}' \
  --customer-email owner@example.com \
  --customer-given-name Account --customer-family-name Owner
```

## Book once

```sh
stripe-link payment-methods list --format json

duffel book --offer-id off_… --payment-method-id pm_… \
  --booking-json '{...}' --seat 1:1:28B --seat 2:1:28C \
  --customer-email owner@example.com \
  --customer-given-name Account --customer-family-name Owner
```

If Stripe Link is disconnected, explain the one-time virtual-card flow and
provide its connection link. Omit `--customer-*` when validation did not request
them.

`book` refreshes and revalidates before any Stripe request. Its single approval
covers the itinerary, passengers, seats/fees, fare conditions, total, optional
first-time Duffel profile, one-time virtual card, 3DS, and immediate paid order.
Never use Duffel balance, held-order, inline-card, or separate order/payment
flows.

The trusted approval must show compact traveler names; a separate lap-infant
row with name, birth date, accompanying adult, and `no seat`; city and airport
codes, flights, operating carriers, schedules, fare/cabin, selected seats,
masked loyalty, baggage, refund/change conditions, price breakdown, and legal
links. Label absent provider conditions as not stated.

After success, treat a requested loyalty account marked
`not_confirmed_on_order` as unverified, not rejected: explain that Duffel's
booking response did not confirm it, it may still be attached, and the traveler
should check with the airline using the PNR and add it only if absent. Never
claim attachment failed solely because the response omitted it, and never retry
or rebook a successful order to repair loyalty.

## Recovery

| Result | Action |
|---|---|
| Validation failure or expired offer before approval | Correct all fields together, or search again if expired. No spend exists. |
| `stripe_link_action_required` with `auto_resume` | Send the complete Markdown link once, wait for the traveler to connect, then rerun the identical `book`. |
| `replacement_required` | Stop; do not change card/offer or create another spend without explicit recovery guidance. |
| Partially completed split booking | Stop. Report the successful bookings and PNRs plus every unpurchased leg. Do not buy a replacement or cancel anything without the traveler's explicit instruction. |
| Definitive Duffel rejection | Say no booking was created and the card was not captured; any temporary authorization will fall off on the issuer's schedule. Do not retry until the traveler explicitly requests a new attempt in a later message. |
| Timeout, 5xx, or ambiguous mutation | Do not claim success/failure or retry. Inspect `booking-status`; otherwise escalate. |
| Ambiguous customer-profile creation | No payment started; do not retry profile creation. Escalate for profile recovery. |
| Success with `resource_authorization.persisted: false` | Report the PNR/order and warn later management may be unavailable. Never repeat the booking. |

Identical offer plus normalized booking data form a resumable checkout identity.
A newly searched offer is a new checkout and can create another authorization
hold, so never use it as an automatic retry.

## Review, cancellation, and limits

```sh
duffel booking-status
duffel booking-status ord_…
duffel cancellation-quote ord_…
duffel cancel-booking ore_…
```

Without an id, `booking-status` lists locally authorized orders and can recover
a lost order id. `cancellation-quote` does not cancel; report its exact known
refund, destination, airline credits, and expiry. A null refund amount is
unknown, not zero: say that the carrier did not provide a quote. `cancel-booking`
re-checks the exact quote and asks once before the irreversible cancellation.
Never invent an unknown refund or fee.

Unsupported: paid bags or other services, partial-passenger cancellation,
date/time or name changes, pets, unaccompanied-minor service, check-in, and
boarding passes. Do not improvise with raw APIs; direct the traveler to the
airline or support.

## Approval rules

- No HITL: search, seat options, validation, booking status, cancellation quote.
- Exactly one HITL: Duffel `book`, airline browser checkout, or cancellation. The
  airline browser checkout uses the same single purchase-approval boundary as
  `book`.
- Any change to flight, date, passengers, fare, services, or total requires a
  fresh purchase approval.
- Reads may be retried. Never automatically retry an ambiguous mutation.
