---
name: "flightaware"
title: "FlightAware AeroAPI"
description: "Look up live/historical flight status, delays, positions, and airport/airline info via FlightAware."
metadata: { "includeInPrompt": true }
---

# FlightAware

## Connecting
There is nothing for the user to connect and no key to enter. Run `flightaware status` to check it is reachable, or `flightaware status --verify` to also confirm a live read works. If status comes back unavailable, tell the user FlightAware is not reachable from this device right now and try again later. Never ask the user for a FlightAware API key.

## Common flows

### Track a flight
Run `flight` with the airline flight number to get its current status, then use the returned `fa_flight_id` with `position` for where it is now or `track` for its recent path. For a picture, run `map` with `--save <path>` to write a static image of the flight.

### Find flights in the air
Use `search` to find airborne flights by origin, destination, or area. Default to one page of results and ask before pulling more.

### Airport activity
Use `airport` for an airport's details, `airport-delays` for current delays, `airport-flights` for arrivals and departures, and `airport-weather` for conditions. `nearby-airports` finds airports around a location.

### Airline activity
Use `operator` for an airline's details and `operator-flights` for its recent and scheduled flights.

### History
For past flights, use the `history` commands with an explicit date range. They cover flights, tracks, routes, airport activity, and an aircraft's last flight.

### Predictions and schedules
Use `foresight` for FlightAware's predicted status and positions, `schedules` for scheduled flights between two dates, and `disruptions` for cancellation and delay counts.

## Other commands
The flows above cover the common cases. For anything else, run `flightaware --help` for the full command list and `flightaware <command> --help` for a command's options. This includes aircraft owner and type lookups, route and count queries, and advanced search syntax.

## Rules
- Use the airline's ICAO flight number when you can (`UAL123`, not `UA123`). If the user's flight number is ambiguous, resolve it with `canonical-flight` first.
- For "where is my flight", get the flight first, pick the right date and leg, then look up its position or track. Do not guess an `fa_flight_id`.
- If FlightAware says a flight or aircraft is blocked or has no data, tell the user plainly and do not try to work around it.
- Flight reads preserve AeroAPI's raw times and add semantic UTC/user-local fields such as `scheduled_gate_departure_at`, `estimated_takeoff_at`, `actual_landing_at`, and `scheduled_gate_arrival_at`. Prefer their `user_local` values in replies. Position samples similarly add `position_observed_at`.
- FlightAware does not cover airline policies, terminal maps, baggage, booking, or customer service. For those, use web search and make clear which details came from the web rather than FlightAware.
- Reply in plain language about the flight, not about how you looked it up. Do not show the user commands, ids, tokens, or raw status codes.

## Limits
- You can't book travel, buy tickets, change a reservation, or contact an airline or airport.
- Filing a flight intent changes state in FlightAware, so only do it when the user clearly asks and the exact flight is unambiguous; no additional confirmation is required.
