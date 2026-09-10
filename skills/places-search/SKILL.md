---
name: "places_search"
title: "Places Search"
description: "Find, compare, share, and/or visualize details on physical places near the user or in a specified area, including restaurants, cafes, bars, hotels, parks, attractions, shops, and businesses with local services. Not for itineraries, choosing a city or region, dated events or showtimes, or directions."
metadata: { "includeInPrompt": false }
---

# Places

Run `local-search` and `places <command>` through `exec`. They are CLIs, not
deferred tool namespaces. Once this skill is loaded, do not search for it again
or try to load a `places` namespace. Both print JSON to stdout for you to read,
not show the user. Use `--help` when needed. No sign-in is required.

## Common flows

### Find places

Use `local-search` for standing places people can visit: restaurants, cafes,
bars, hotels, parks, trails, attractions, shops, and local services. A follow-up
like "anything cheaper?" or "Italian instead?" refines the preceding search.

- Make the first `--query` the broad, intent-aligned anchor. Add complementary
  queries only when they explore a different facet, such as a subtype or a
  specific venue name. Do not send paraphrases. The CLI accepts at most six
  distinct queries.
- Keep area text out of queries and pass it with `--location`. Omit `--location`
  only when the user's current device location should be used. Use `--radius`
  only when the user requests or implies a meaningful distance bound.
- One call covers one area. When the user names multiple cities or
  neighborhoods, run a separate call for each and cover each in the answer.
- Use `--search-type discovery` for category or set searches. Use `known_place`
  only when the whole request concerns one or a few named businesses or
  landmarks. A broad anchor mixed with named needle queries stays `discovery`.
- For "best," trending, insider, or nuanced requests, run a web search first
  and feed useful venue names into `local-search` as needle queries. Skip that
  step for plain, well-scoped requests.

### Get richer details

- `places details` takes numeric place IDs only. It cannot search by name or
  address; use `local-search` for that.
- Numeric place IDs returned by web search are valid inputs to `places details`,
  just like IDs returned by `local-search`.
- Prefer the local-search response when it already contains enough detail. Use
  `places details` for richer or fresher hours, prices, photos, reviews, and
  offerings.
- Batch several IDs into one call when comparing places. Pass `--motivation`
  with the user's intent so quotes and photos are ranked for it.

### Show places on a map

When the final answer presents one or more place results, create one map if at least one has both a numeric place ID and coordinates. This applies to recommendations, comparisons, named-place lookups, and other uses where a map could ground the user on your results. Map only the final places that have both fields.

Create one `local_map` widget with this payload:

```json
{
  "kind": "local_map",
  "data": {
    "elements": [
      {
        "kind": "rich_place",
        "place_id": "<numeric ID>",
        "name": "<name from the same result>",
        "coordinate": {
          "latitude": 0.0,
          "longitude": 0.0
        }
      }
    ]
  }
}
```

- Replace the example coordinates with the returned numeric values. Copy the
  ID, name, and coordinates from the same result record. Never geocode a name
  to fill in a missing coordinate.
- Include the returned `embed_token` in the reply. Without it, the user sees
  no map.
- Create one map per answer, even when the request covers multiple areas.
- If creation fails, answer in text. Do not retry or build an HTML or image map.

### Identify a place from a photo

Use `places detect` when captured frames and GPS need to resolve which place the
user is at. It returns ranked candidates as `{place_id, place_name, confidence}`.
Pass a returned ID to `places details` for more. The optional 4th `--location`
field is the connected Wi-Fi BSSID; include it verbatim when known to improve
Home/Work matching, and never echo a raw BSSID back to the user.

## Rules

- Judge the merged result set rather than following rank. Set aside
  wrong-category or wrong-area results. If the set is weak, retry with a bare
  venue name, a narrower subtype, or a better area.
- Never invent a place or put one on a map or place card without an ID returned
  by a tool.
- Recommend roughly five to eight strong places when the results support it.
  Do not dump the whole set or pad it with weak matches.
- Never put raw place IDs or coordinates in the reply. Name places by name and
  address.

## Limits

- Do not write directions, turn-by-turn steps, maps links, or navigation
  controls.
- Do not estimate travel times or distances. Use only values returned by a tool.
