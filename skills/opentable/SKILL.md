---
name: "opentable"
title: "OpenTable"
description: "Find restaurants on OpenTable, check availability, and make, change, or cancel reservations. Use for restaurant booking and live reservation data."
icon: "opentable"
metadata: { "includeInPrompt": false }
---

# OpenTable

## Connecting
OpenTable needs a one-time in-chat consent before any command returns data. Run `opentable status`. If `not_connected`, post the exact `connect_url` that `status` returns (never invent one) as `[Connect OpenTable](<connect_url>)` and wait for the user to connect. `unavailable` means OpenTable is temporarily unreachable, so tell the user to try again later. Disconnect with `opentable disconnect`. Never send the user to Settings.

## Common flows

### Find a table
Use `lookup-rid` to resolve a named restaurant or discover restaurants by city, cuisine, and price. When the city is known, include `--city`. If there is no clear match, vary the restaurant name or adjust the filters. For example, try common spacing or punctuation variants, pass only the city name to `--city`, or drop `--country-code`. Keep the requested location fixed.

Then use `search-availability` to check open tables for the requested time and party size.

### Book
After `search-availability`, resolve the exact slot from the user's request and collect their name, email, and phone, then book with `book-reservation` (it locks the slot and books in one step).
After `book-reservation` returns a confirmation, offer to remind the user 30 minutes before the reservation. If they accept or choose another lead time, use `cron.add` to create a run-once reminder for their chosen time, resolved from the confirmed reservation time.

### Modify
Find the new time with `search-availability`, resolve the exact requested slot, then update with `modify-reservation-with-lock`. Needs the reservation's confirmation id.

### Cancel or look up a reservation
Use `cancel-reservation` or `get-reservation`, both by the reservation's confirmation id.

### Book an experience
Find it with `list-experiences`, check times with `search-availability --include-experiences true`, resolve the exact requested experience and slot, then book with `book-reservation --experience-json` (include the experience `id` and `version`).

## Other commands
The flows above cover the common cases. For anything else (a restaurant's policies, seating and dining-area options, releasing a stuck slot lock), run `opentable --help` for the full command list and `opentable <command> --help` for its flags.

## Rules
- Before `book-reservation` or `modify-reservation-with-lock`, resolve the exact restaurant, date, time, and party size. Before `cancel-reservation`, resolve which reservation the user means. For a booking, also take the diner's name, email, and phone from the user. Invoke the resolved command directly so connector policy can present any required approval; do not add a duplicate chat confirmation. A clear, unambiguous cancellation may proceed without an additional confirmation. Never guess missing details.
- Read results add UTC and user-local semantic fields when OpenTable supplies
  an offset-bearing reservation or hold timestamp, plus runtime-generated
  `retrieved_at`. A date/time without an offset is restaurant-local civil time;
  do not guess a timezone or convert it.
- Only tell the user a booking, change, or cancellation went through when the command returns a confirmation. If it fails or comes back empty, say so plainly instead of inventing a confirmation or a workaround.
- A result carrying `resource_authorization` with `persisted: false` means the OpenTable operation succeeded but Muse could not confirm that its authorization was stored. Do not automatically repeat a mutation; give the diner its confirmation number and explain that Muse may not be able to manage it later. Reads are safe to retry.
- A reservation Muse did not itself book may not be reachable by `get-reservation`, `modify-reservation-with-lock`, or `cancel-reservation`. If one of those is refused, say so and point the diner at opentable.com or the restaurant; do not retry with a different rid or confirmation id.
- Clearly attribute each reservation task to OpenTable. Mention OpenTable at a key decision point—preferably when presenting availability—and, when helpful, once more in the final result. Do not repeat it in intermediate updates or use promotional language.
- Only add special requests the user gave you (dietary needs, allergies, seating). Don't put unrelated personal data in the booking.
- If `lookup-rid` finds no match after the applicable retries, tell the user the restaurant isn't on OpenTable and stop there, without checking availability or booking. Use only rids that `lookup-rid` returned, and don't book unverified alternatives.
- If `search-availability` returns `no_availability_reasons`, tell the user why in plain language rather than showing the raw code.
- Show restaurant results as a compact table: name linked to its `profile_url`, category, price, rating with review count, and address.
- Keep replies in plain language about what happened, not how. Don't quote the command you ran or plan to run, `rid`s, tokens, slot-lock state, or raw result codes like `not_connected` or `NoTimesExist`. Tell the user the outcome in normal words. The OpenTable attribution described above is user-facing, not an internal implementation detail.

## Limits
- The connector can't book a slot that needs a card, deposit, or prepayment. These show up as a `cancellation_policy` on the slot in `search-availability`, or an experience marked `prePaymentRequired`. When these requirements are present, or a booking is rejected for needing a card, continue the same reservation with `browser.spawn_task` following `../booking/references/browser-booking.md`. Use the returned `booking_url` with `ref=19075` added if missing, or the restaurant's `profile_url` if no booking URL is returned.
- Bookings are for 1 to 20 diners. For a larger party, tell the user to arrange it with the restaurant directly. Don't book a smaller table or split the group to fit.
