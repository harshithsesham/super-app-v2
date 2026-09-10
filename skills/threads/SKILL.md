---
name: "threads"
description: "Read the user's Threads account: profile, posts, feed, saved posts, activity, insights, social graph, search, and trends. Can tune feed ranking on request; it cannot post or draft."
icon: "threads"
metadata: { "includeInPrompt": true }
---

# Threads CLI

## Purpose
Read authenticated Threads data using the `threads-cli` companion CLI. The CLI
uses the same thin, schema-less adapter pattern as `instagram-cli`; WWW owns
command behavior, validation, persisted documents, privacy filtering, and
response serialization.

Use the separate `threads_messages` skill for Threads inboxes and message threads.

## Account Linking

Before running any other command, verify the user's Threads account is connected by running `threads-cli accounts`. If the command returns account info (one or more accounts with `id`), the account is connected — proceed normally. Cache this result for the rest of the conversation; do not re-run the check before every command. If any subsequent command fails with an auth or account error, re-run `threads-cli accounts` to recheck account linking status.

If the command fails or returns an empty result indicating no account is linked, the account is not connected. Get the connect URL by running `threads-cli connect-url` (it outputs JSON with a `connect_url` field), then tell the user, substituting that URL:

> Your Threads account is not connected. To connect it, visit [Meta Accounts Center](`connect_url`) and link your Threads account.

If the user asks to disconnect their Threads account, run `threads-cli disconnect-url` (it outputs JSON with a `disconnect_url` field) and direct them to that URL:

> To disconnect your Threads account, visit [Meta Accounts Center](`disconnect_url`) and remove the linked account.

Always read these URLs from the command output rather than hardcoding them.

## Tooling
Use `exec` to run:

```sh
threads-cli <target> [options]
```

Targets:
- `accounts`
- `profile`
- `activity-feed`
- `liked-media`
- `saved-posts`
- `insights-overview`
- `post-insights`
- `top-posts`
- `user-profile`
- `profile-threads`
- `profile-replies`
- `profile-media`
- `followers`
- `following`
- `post`
- `fetch-post-comments` (alias: `comments`)
- `fetch-post-likers` (alias: `likers`)
- `feedback-hub-overview`
- `feedback-hub-tab`
- `trends`
- `search`
- `feed`
- `dear-algo-whisper`

### Post output

`feed` and `post` retain the same compact `social_posts_v1` presentation as
`instagram-cli`. That projection uses only the filtered fields returned by WWW;
the client does not re-fetch, reconstruct, or bypass omitted server data. If
WWW returns an explicit error-only post row, the CLI omits that empty row and
surfaces its message as `provider_error`.

### Global options
- `--account-id <threads_account_id>` **(required for all commands except `accounts`)** — select which Threads account to operate on. The value must be the authenticated user's own `id` field from the `accounts` response. Always call `accounts` first. If it returns multiple entries, ask the user which account to use.
- `--retries <N>` — retry transient failures (default: 0). This is not
  supported for `dear-algo-whisper`, because retrying could create a duplicate
  intent.

## WWW service boundary

The CLI uses an explicit route table:

- `accounts` uses `GET /hatch/th/me/accounts`.
- All other targets listed above, including `activity-feed`, use
  `POST /hatch/th/cli`.
- Threads inbox and thread reads belong to the separate `threads_messages`
  skill.

The named request body is `{"command":"feed","account_id":"<id>",
"params":"{\"variant\":\"for_you\"}","tool_call_id":"<optional-id>"}`.
`params` is a JSON-encoded object string. The CLI forwards the current tool-call
correlation ID when available and decodes the endpoint's JSON-encoded `result`.
WWW logs the authoritative response-FBID sidecar before removing it; the client
must not reconstruct privacy identifiers from the public result. A named-command
failure is never retried through `/gq`.

The direct command allowlist is `profile`, `activity-feed`, `user-profile`, `post`,
`profile-threads`, `profile-replies`, `profile-media`, `followers`, `following`,
`liked-media`, `saved-posts`, `fetch-post-comments`, `fetch-post-likers`,
`feedback-hub-overview`, `feedback-hub-tab`, `insights-overview`,
`post-insights`, `top-posts`, `trends`, `search`, `feed`, and
`dear-algo-whisper`. The client must not send caller-selected GraphQL document
IDs or globally redirect compatibility commands.

## Commands

### Accounts
List Threads accounts associated with the currently authenticated user.

```sh
threads-cli accounts
```

### Profile
Fetch the current user's own Threads profile.

```sh
threads-cli profile --account-id <threads_account_id>
```

### Activity Feed
Fetch the user's activity notifications.

```sh
threads-cli activity-feed --account-id <threads_account_id>
threads-cli activity-feed --account-id <threads_account_id> --first 20
threads-cli activity-feed --account-id <threads_account_id> --category-filter text_post_app_mentions
threads-cli activity-feed --account-id <threads_account_id> --after <cursor>
```

Category filters: `text_post_app_conversations`, `text_post_app_following`, `text_post_app_private_follow_requests`, `text_post_app_mentions`, `text_post_app_replies`, `text_post_app_user_follows`, `text_post_app_quote_posts`, `text_post_app_reposts`.

### Liked Media
Fetch posts you've liked.
This uses the shared engagement query and supports `--since`, `--until`, `--sort-order`, `--limit`, and `--after`.

```sh
threads-cli liked-media --account-id <threads_account_id>
threads-cli liked-media --account-id <threads_account_id> --limit 20
threads-cli liked-media --account-id <threads_account_id> --since 2026-03-01 --until 2026-03-20
threads-cli liked-media --account-id <threads_account_id> --sort-order asc
threads-cli liked-media --account-id <threads_account_id> --after <cursor>
```

### Saved Posts
Fetch your saved posts.
This uses the shared engagement query and supports `--since`, `--until`, `--sort-order`, `--limit`, and `--after`.

```sh
threads-cli saved-posts --account-id <threads_account_id>
threads-cli saved-posts --account-id <threads_account_id> --limit 20
threads-cli saved-posts --account-id <threads_account_id> --since 2026-03-01 --until 2026-03-20
threads-cli saved-posts --account-id <threads_account_id> --after <cursor>
```

### Insights Overview
Fetch account-level insights (views, likes, quotes, replies, reposts, traffic sources, demographics).

```sh
threads-cli insights-overview --account-id <threads_account_id> --start-date 2026-03-13 --end-date 2026-03-20
threads-cli insights-overview --account-id <threads_account_id> --start-date 2026-03-13 --end-date 2026-03-20 --sections followers
```

Section values: `summary`, `views`, `interactions`, `followers`, `demographics`, `all`.

The typed insights backend uses the Threads account selected by
`--account-id`. Do not retry an account-binding failure through `/gq`; run
`accounts` again and pass one of the returned account IDs.

### Post-Level Insights
Fetch insights for a specific post.

```sh
threads-cli post-insights --account-id <threads_account_id> --post-id 3856993780407305605
```

### Top Posts
Fetch the most-viewed posts and the service-defined top three most-liked posts
over a date range. `--count` controls most-viewed posts and is bounded to 50.

```sh
threads-cli top-posts --account-id <threads_account_id> --start-date 2026-03-13 --end-date 2026-03-20
threads-cli top-posts --account-id <threads_account_id> --start-date 2026-03-13 --end-date 2026-03-20 --count 5
```

### Other User's Profile
Fetch another user's profile by numeric Threads user FBID. Usernames and profile
URLs are not accepted by the named WWW handler.

```sh
threads-cli user-profile --account-id <threads_account_id> --user-id 12345678
```

### Profile Threads
Fetch threads by numeric Threads user FBID. `--limit` is accepted as a
compatibility alias for `--first`.

```sh
threads-cli profile-threads --account-id <threads_account_id> --user-id 12345678
threads-cli profile-threads --account-id <threads_account_id> --user-id 12345678 --first 10 --after <cursor>
```

### Profile Replies
Fetch a user's replies.

```sh
threads-cli profile-replies --account-id <threads_account_id> --user-id 12345678
threads-cli profile-replies --account-id <threads_account_id> --user-id 12345678 --first 10 --after <cursor>
```

### Profile Media
Fetch a user's media posts (images, videos, carousels).

```sh
threads-cli profile-media --account-id <threads_account_id> --user-id 12345678
threads-cli profile-media --account-id <threads_account_id> --user-id 12345678 --first 10 --after <cursor>
```

### Followers
Fetch a user's followers list.

```sh
threads-cli followers --account-id <threads_account_id> --user-id 12345678
threads-cli followers --account-id <threads_account_id> --user-id 12345678 --first 10 --after <cursor>
```

### Following
Fetch a user's following list.

```sh
threads-cli following --account-id <threads_account_id> --user-id 12345678
threads-cli following --account-id <threads_account_id> --user-id 12345678 --first 10 --after <cursor>
```

### Post by ID
Fetch a specific post. Use `fetch-post-comments` for its replies.

```sh
threads-cli post --account-id <threads_account_id> --post-id 3856993780407305605
```

### Fetch Post Comments
Fetch comments for one or more post media IDs.
Use `--since`, `--until`, `--sort-order`, `--limit`, and repeated/comma-separated `--author-id` filters when needed.

```sh
threads-cli fetch-post-comments --account-id <threads_account_id> --post-ids 3856993780407305605
threads-cli fetch-post-comments --account-id <threads_account_id> --post-ids 3856993780407305605,3856993780407305606 --limit 20 --after <cursor>
threads-cli fetch-post-comments --account-id <threads_account_id> --post-ids 3856993780407305605 --since 2026-03-01 --until 2026-03-20 --author-id 12345678
threads-cli comments --account-id <threads_account_id> --post-ids 3856993780407305605
```

### Fetch Post Likers
Fetch users who liked one or more post media IDs.
Use `--since`, `--until`, `--sort-order`, `--limit`, and repeated/comma-separated `--reactor-id` filters when needed.

```sh
threads-cli fetch-post-likers --account-id <threads_account_id> --post-ids 3856993780407305605
threads-cli fetch-post-likers --account-id <threads_account_id> --post-ids 3856993780407305605 --limit 20 --after <cursor>
threads-cli fetch-post-likers --account-id <threads_account_id> --post-ids 3856993780407305605 --since 2026-03-01 --until 2026-03-20 --reactor-id 12345678
threads-cli likers --account-id <threads_account_id> --post-ids 3856993780407305605
```

### Feedback Hub Overview
Fetch a post's engagement summary (likes, reposts, quotes counts).

```sh
threads-cli feedback-hub-overview --account-id <threads_account_id> --post-id 3856993780407305605
```

### Feedback Hub Tab
Fetch paginated lists of users who liked, reposted, or quoted a post.

```sh
threads-cli feedback-hub-tab --account-id <threads_account_id> --post-id 3856993780407305605 --tab-type like
threads-cli feedback-hub-tab --account-id <threads_account_id> --post-id 3856993780407305605 --tab-type repost --first 10
threads-cli feedback-hub-tab --account-id <threads_account_id> --post-id 3856993780407305605 --tab-type quote --after <cursor>
```

### Trends
Fetch trending topics on Threads.

```sh
threads-cli trends --account-id <threads_account_id>
threads-cli trends --account-id <threads_account_id> --first 10
```

### Search
Search Threads by keyword, or dive deeper into a trend.

```sh
threads-cli search --account-id <threads_account_id> --query "AI news"
threads-cli search --account-id <threads_account_id> --query "AI news" --recent 1
threads-cli search --account-id <threads_account_id> --query "trending topic" --trend-fbid 987654
threads-cli search --account-id <threads_account_id> --query "AI" --first 10 --after <cursor>
```

Use `--recent 1` for "Recent" tab results instead of "Top".

### Feed
Fetch the ranked feed (For You or Following).

For You feed:
```sh
threads-cli feed --account-id <threads_account_id> --variant for_you
```

Following feed:
```sh
threads-cli feed --account-id <threads_account_id> --variant following
threads-cli feed --account-id <threads_account_id> --variant following --sort-by recent
```

For all feed variants, use `--after` for pagination:
```sh
threads-cli feed --account-id <threads_account_id> --variant for_you --after <cursor>
```

### Dear Algo Whisper
Send a message directly to the Threads ranking algorithm to modify what the user sees in their feed (e.g. "show me less politics", "more cat content"). A clear user request may proceed without an additional confirmation.

```sh
threads-cli dear-algo-whisper --account-id <threads_account_id> --message "show me less politics"
```

## Operating rules
1. This skill is for the authenticated user's own Threads data, not general Threads search.
2. **Always call `accounts` first** to obtain the account `id` for `--account-id`. Cache this value for subsequent commands in the same conversation. If `accounts` returns no entries, direct the user to Meta Accounts Center to link a Threads account (refer to the "Account Linking" section for details).
3. **Minimize API calls to avoid rate limiting.** The Threads API enforces strict rate limits — excessive calls will result in `429 Too Many Requests` errors that are not retried. Follow these principles:
   - **Batch your information gathering.** Before making calls, plan which data you actually need. Don't fetch data speculatively.
   - **Reuse data from earlier responses.** If you already fetched `accounts` or `profile`, extract IDs and usernames from that response instead of calling again.
   - **Avoid redundant pagination.** Only paginate (`--after`) when the user explicitly needs more results. Don't automatically fetch all pages.
   - **Never call the same command twice with identical arguments** in one conversation unless the previous call failed or the user explicitly asks for a refresh.
4. Avoid requests to persistently / frequently poll these commands.
5. Use numeric Threads FBIDs for account, user, post, and other entity identifiers. Do not derive an identifier from a Threads URL or pass a URL where an FBID is required.
6. Treat U18 enforcement as a server-side invariant. Do not reconstruct filtered fields, retry through `/gq`, or otherwise bypass server results.
7. Do not expose raw media URLs when WWW omits them. Use the structured, filtered result returned by the named command.

## Output
The CLI prints decoded JSON to stdout.
