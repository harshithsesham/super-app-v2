---
name: "ticketmaster"
description: "Search Ticketmaster events and seats with pricing. Returns Buy-now links to Ticketmaster checkout; it cannot complete a purchase itself."
metadata: { "includeInPrompt": true }
---

# Ticketmaster

## Purpose
Search events and get smart Ticketmaster seat recommendations.

## Tooling

```sh
ticketmaster <subcommand> [options]
```

#### search-events
Search for events by keyword (required), location, and date range. Supports `--country-code` (default: US), `--page` (0-indexed), and `--sort` (e.g. `date,asc`, `relevance,desc`, `name,asc`). `--start-date` and `--end-date` accept ISO 8601 values; bare `YYYY-MM-DD` dates are normalized by the CLI.

```sh
ticketmaster search-events --keyword "Taylor Swift" --city "Los Angeles" --size 10
ticketmaster search-events --keyword "Lakers" --start-date 2026-05-01 --end-date 2026-06-01 --state-code CA --sort date,asc
```

#### event-details
Get full details for a specific event ID returned by `search-events`.

```sh
ticketmaster event-details --event-id vvG1IZ_AKnSEae
```

#### top-picks
Get seat recommendations sorted by price or quality. Default `--selection Any` returns Standard + Resale + Platinum tickets. Use `--selection Standard` to exclude resale. Returns `venue_map_url` and per-pick `snapshot_image_url` when available. Pipe the output to `seat-view-carousel` to render seat views.

```sh
ticketmaster top-picks --event-id vvG1IZ_AKnSEae --quantity 2 --sort listprice
ticketmaster top-picks --event-id vvG1IZ_AKnSEae --quantity 4 --sections "MEZZ,ORCH" --sort quality
ticketmaster top-picks --event-id vvG1IZ_AKnSEae --quantity 2 --price-min 50 --price-max 150 --limit 10
ticketmaster top-picks --event-id vvG1IZ_AKnSEae --quantity 2 --selection Standard --sort listprice
ticketmaster top-picks --event-id vvG1IZ_AKnSEae --quantity 2 --areas "10,11" --ticket-type-id 000000000001
```

#### seat-view-carousel
Generate a carousel HTML widget from top-picks JSON. Takes the full top-picks JSON output as `--input`. Outputs raw HTML to stdout.

```sh
ticketmaster seat-view-carousel --input '<top-picks JSON>' --title "Lakers vs Thunder" --subtitle "Paycom Center · May 13 · 8:30 PM"
```

## Output

Commands return JSON from Ticketmaster. Do not expect an
`ok` wrapper around endpoint output.

The CLI maps snake_case query params to Ticketmaster camelCase API params. The
response body is the raw Ticketmaster payload unless this CLI adds explicit
convenience fields for local rendering.

**search-events**: raw Ticketmaster Discovery search response. Events are in
`_embedded.events[]`; pagination is in `page`. For each event, use `id` as the
event ID for follow-up calls, `name` for the title, `url` for the public
Ticketmaster page, `dates.start.localDate`, `dates.start.localTime`, and
`dates.start.dateTime` for timing, `_embedded.venues[0]` for venue/city/state,
and `priceRanges[]` when Ticketmaster includes search-level pricing.

**event-details**: raw Ticketmaster Discovery event object. Read fields
directly from the event: `id`, `name`, `url`, `dates.start.*`,
`dates.timezone`, `dates.status.code`, `priceRanges[]`, `classifications[]`,
`images[]`, `_embedded.venues[]`, `_embedded.attractions[]`, and `_links`.

Timed event reads add `event_starts_at` / `event_ends_at` with canonical UTC
and user-local forms, plus runtime-generated `retrieved_at`. Prefer the
user-local form when answering; date-only event fields remain dates.

**top-picks**: raw Ticketmaster Top Picks response with CLI convenience fields
added for carousel rendering when available.

Top-picks contains `picks[]`, `_embedded.offer[]`, `eventDetails`, and `page`.
Seat-level pricing lives in `_embedded.offer[]`, keyed by `offerId`; each pick
references offers through `picks[].offers[]`. Use the first referenced matching
offer as the primary displayed price and show `_embedded.offer[].totalPrice` as
the user-facing ticket price (not `faceValue`). If
`eventDetails.allInclusivePricing` is true, say the displayed `totalPrice`
includes fees and show `eventDetails.listingsDisclaimer` when present. You may
show `faceValue` only as additional context, not as the main price.

Ticketmaster may return both camelCase and snake_case duplicates. Use this
precedence when reading fields:
- Checkout URL: `pick.redirect_url || pick.redirectUrl`
- Seat image: `pick.snapshot_image_url || pick.snapshotImageUrl || pick.snapshotURL`
- Price: `pick.total_price || _embedded.offer[offerId].totalPrice`

The CLI may add these convenience fields for carousel rendering:
`venue_map_url`, `snapshotURL`, `snapshot_image_url`, `redirect_url`,
`total_price`, `face_value`, and `currency`.

Each pick may include: `{ type, selection, section, row, seats, area, quality, descriptions, listingDetails, offers, snapshotImageUrl, redirectUrl }`.

**seat-view-carousel**: Outputs raw HTML to stdout — a self-contained carousel widget with venue map + per-pick seat view slides. It does **not** download images or save image files. It renders remote HTTPS Ticketmaster image URLs directly and adds `referrerpolicy="no-referrer"` to image tags. Images are Ticketmaster-hosted, for example `https://app.ticketmaster.com/maps/geometry/...`. Checkout URLs must be valid HTTPS URLs; `https://ticketmaster.evyy.net/...` affiliate redirect URLs with preselected seats are valid and required when returned.

When a pick has a valid checkout URL (`redirect_url || redirectUrl`) and a displayed price, the slide banner includes a clickable Buy now link immediately after the price and the seat-view image is clickable so users can go directly to Ticketmaster checkout. General-admission picks render with their area description (for example, `GA FLOOR STANDING`) instead of row/seat placeholders. If the checkout URL is absent/invalid or pricing is unavailable, the carousel omits that pick.

The carousel filters out picks that do not have both a parseable `total_price` and a valid HTTPS checkout URL (`redirect_url || redirectUrl`) so it never shows "Pricing TBD" slides. The carousel layout width is dynamic based on the final slide count after filtering.

After generating the HTML, immediately create and show it inline: call
`widget.create` with exactly these arguments:

```json
{
  "kind": "html",
  "present_now": true,
  "data": {
    "html": "<stdout>",
    "display_text": "<Event> - Seat Views",
    "fallback_text": "<Event> - Seat Views"
  }
}
```

Include the returned `embed_token` in the reply. Do **not** save carousel HTML to `workspace/your_files/` for widget rendering; that path is treated as generated artifacts and cannot be rendered by `widget.create`. No image files need saving. Optional persistence only: save a fallback HTML file under `workspace/` (not `workspace/your_files/`) and return a `sandbox://` link.

## Auth
No user setup is required for Ticketmaster service access.

## Operating Rules
1. Always use `search-events` first to find the event ID before calling `top-picks`.
2. When the user asks for "cheap" tickets, use `--sort listprice`. When they want "best" seats, use `--sort quality`.
3. Arena section discovery: When searching for a seating level (floor, mezzanine, orchestra, pit, upper, etc.), never guess the section name — venues use inconsistent naming. Always run a broad `--sort quality --limit 20` query first with no `--sections` filter to discover the venue's actual section names and area labels, then use those exact names in subsequent filtered queries with `--sections`.
4. When a valid checkout URL (`redirect_url || redirectUrl`) and a displayed price are present, make it easy to buy: the carousel will render a clickable Buy now link on each seat slide, and any text summary should include a compact `[Buy now](<redirect_url>)` link. Ticketmaster affiliate links such as `https://ticketmaster.evyy.net/...` are valid checkout URLs. If the checkout URL is absent/invalid or pricing is unavailable, do not fabricate a checkout link or present the seat as directly purchasable.
5. For resale tickets (`selection: "resale"`), show the `listingDetails` description when present and note these are verified resale tickets.
6. If the selected offer has a `limit` object, respect its `min` and `max` quantity bounds.
7. If `eventDetails.allInclusivePricing` is true, note that the displayed price includes fees. Show `eventDetails.listingsDisclaimer` and `eventDetails.importantInformation` when present.
8. After `top-picks` returns, prioritize perceived speed: immediately send a concise text summary before starting carousel rendering. Use 1–3 bullets focused on purchase decisions (for example: best value, closest view, cheapest option), each with Section/Row, price, and `[Buy now](<redirect_url>)` only when both a valid checkout URL and price are present. Do not show a large ticket table by default.
9. After sending the summary, prepare the carousel asynchronously in a background subagent/worker so the user sees results quickly while the seat-view HTML is generated:
   ```sh
   ticketmaster seat-view-carousel --input '<top-picks JSON output>' \
     --title "<Artist> — <Tour>" \
     --subtitle "<Venue> · <Date> · <Time> · <N> listings · Prices include fees"
   ```
   Then call `widget.create` with `kind: "html"`, `present_now: true`, and `data` carrying the stdout HTML as `html` plus `display_text`/`fallback_text` of `<Event> - Seat Views`, and include the returned `embed_token` in the reply. Keep user-visible text conversational; do not mention subagents, workers, commands, or rendering internals.
10. `priceRanges[]` from search-events is often absent or incomplete (Discovery API limitation). Never tell the user "no pricing available" based on search-events alone — always use `top-picks` to get real pricing.
11. Use the raw Discovery `id` from `_embedded.events[]` for `event-details` and prefer it for `top-picks` calls. `top-picks` accepts either the Discovery ID (for example `vvG...`) or the numeric geometry/eventDetails ID (for example `0900...`); the response may echo the numeric ID as `eventDetails.id`.
12. Once you deliver the link to the tickets, encourage the user to complete checkout themselves by visiting the URL.
