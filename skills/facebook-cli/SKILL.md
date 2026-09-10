---
name: "facebook_cli"
icon: "facebook"
title: "Facebook"
description: "Read the user's Facebook: posts, comments, reactions, friends, timelines, profiles, stories, feeds, groups, Marketplace listings, and saved items; create, edit, publish, and delete the user's own Marketplace listings."
metadata: { "includeInPrompt": true }
---

# Facebook CLI

## Quick Reference

```
facebook-cli
├── post
│   ├── comments
│   │   └── read --post-id <id> [--limit N] [--after <cursor>]  # Read comments (paginated: data[] + paging.cursors.after; post link at summary.post_url)
│   └── reactions
│       └── read --post-id <id>  # Reaction summary only: summary.total_count + summary.reaction_counts (no individual reactor list)
├── me                                         # Your Facebook name + profile ID
│   └── friends [--name] [--city] [--hometown] [--work] [--education] [--filter-mode AND|OR] [--json-query <json>] [--birthday-within-days [N]] [--limit N] [--after <cursor>]  # Paginated: data[] + paging.cursors.after
├── marketplace
│   ├── search --query "..." [options]         # Search listings
│   ├── my-listings [--status active|pending|sold|draft] [--limit N] [--after <cursor>]  # Your own listings (active + inactive), paginated
│   ├── listing details --listing-id <id>      # Item details
│   ├── listing create --title "..." --price N --photo /path [options]  # Create; goes LIVE only with photos+condition+category+location (location = --latitude & --longitude; no --location flag), else DRAFT
│   ├── listing edit --listing-id <id> --photo /path [options]  # Edit a listing (photos uploaded automatically)
│   ├── listing delete --listing-id <id>       # WRITE — permanently delete your listing; prompts for approval
│   ├── listing publish --listing-id <id>      # WRITE — take a DRAFT live; needs photos+condition+category+location (location = --latitude & --longitude); prompts for approval
│   └── seller-info --listing-id <id>          # Seller ratings/info
├── groups
│   ├── search [--keywords "..."]         # Search/list your groups; --role any = all public groups
│   └── posts --group-id <id>             # Browse posts in a group; --query filters by text
├── saved
│   ├── list [--type post|video|link|product|reel|event|page] [--collection-id <id>] [--limit N] [--after <opaque>]
│   ├── add --savable-id <FBID> [--type ...] [--collection-id <id>]      # WRITE — auto-allowed
│   ├── remove --savable-id <FBID> [--type ...] [--collection-id <id>]   # WRITE — auto-allowed
│   └── collections
│       ├── list
│       └── create --name "..."                  # WRITE — auto-allowed
├── story
│   └── feed [--limit <n>]               # Fetch your story feed (story tray)
├── feed
│   ├── newsfeed [--limit <n>] [--after <cursor>] # Ranked algorithmic newsfeed (organic stories)
│   └── friends [--limit <n>] [--after <cursor>]  # Ranked friends-only feed
├── timeline
│   └── fetch --profile-id <id> [--limit N] [--after <cursor>]  # Fetch timeline posts; use next_cursor to page (check author_id vs owner_id)
└── profile
    └── info --profile-id <id>                 # Look up profile info
```


## Account Linking

Before running any facebook-cli command, verify the user's Facebook account is connected by running `facebook-cli me`, except for `facebook-cli marketplace search`, `facebook-cli marketplace listing details`, and `facebook-cli marketplace seller-info`. If the command returns account info (name and profile ID), the account is connected — proceed normally. Cache this result for the rest of the conversation; do not re-run the check before every command. If any subsequent command fails with an auth or account error, re-run `facebook-cli me` to recheck account linking status.

If the command fails or returns an error indicating no account is linked, the account is not connected. Get the connect URL by running `facebook-cli connect-url` (it outputs JSON with a `connect_url` field), then tell the user, substituting that URL:

> Your Facebook account is not connected. To connect it, visit [Meta Accounts Center](`connect_url`) and link your Facebook account.

If the user asks to disconnect their Facebook account, run `facebook-cli disconnect-url` (it outputs JSON with a `disconnect_url` field) and direct them to that URL:

> To disconnect your Facebook account, visit [Meta Accounts Center](`disconnect_url`) and remove the linked account.

Always read these URLs from the command output rather than hardcoding them.

## When to use facebook-cli vs social.search

Use **facebook-cli** (this skill) for all structured Facebook operations:
- Looking up friends by name, city, work, education, or hometown (`me friends --name`, `--city`, `--work`, etc.)
- Interest-based friend search via SocialGraphSearch (`me friends --json-query`)
- Reading a specific person's timeline (`timeline fetch`)
- Reading comments or reactions on a post (`post comments read`, `post reactions read`)
- Viewing profile info (`profile info`)
- Browsing your newsfeed or friends feed (`feed newsfeed`, `feed friends`)
- Searching or browsing Marketplace

Use **social.search** only for free-text semantic search across your Facebook graph — e.g. "find posts about hiking" or "posts mentioning Paris from last month". If the user asks about a specific person, their friends, timeline, or profile, always start with facebook-cli.

## Supported Post ID Formats

When using `post comments read` or `post reactions read`, these formats are accepted for `--post-id`:
- `123456789012345` — raw numeric post ID
- `pfbid02...` — PFBID format

## Composability

When the user asks "what can I do on Facebook?" or at the start of a session, generate 3-5 contextual suggestions that combine multiple commands into useful read-only workflows.

### How outputs chain across commands

- **Identity -> profile details**: `me` produces `profile_id` -> `profile info --profile-id` for full profile directory (name, city, workplace, school, bio)
- **Identity -> own timeline**: `me` produces `profile_id` -> `timeline fetch --profile-id <id>` for your own posts
- **Friends -> timeline -> comments/reactions**: `me friends` produces `profile_id` -> `timeline fetch --profile-id` -> posts produce `post_id` -> `post comments read`, `post reactions read`
- **Search/timeline -> comments/reactions**: Search results or timeline posts produce `post_id` -> feed into `post comments read`, `post reactions read`
- **Marketplace search -> item -> seller**: Search results produce `listing_id` -> `listing details` -> `seller-info`
- **My listings -> manage**: `marketplace my-listings` produces your own `listing_id` -> `marketplace listing edit` (update), `marketplace listing delete` (remove), or `marketplace listing publish` (take a draft live). Use `--status` to scope to active/pending/sold/draft and `--after` to page.
- **Create draft -> complete -> publish**: `marketplace listing create` missing any of photos/condition/category/location saves a draft -> `marketplace listing edit` to add the missing field(s) -> `marketplace listing publish` to take it live. If publish fails with missing fields, the error names exactly which to add via edit, then retry.
- **Groups search -> posts**: `groups search` produces `group_id` -> `groups posts --group-id <id>` for group posts
- **Groups posts + friends cross-reference**: When the user asks about friends' activity in a group, call `me friends` to get the friend list, then compare against post authors from `groups posts` — do not ask the user to provide their friend list manually.
- **Friends -> profile details**: `me friends` produces `profile_id` -> `profile info --profile-id` for full directory info
- **Profile -> timeline**: Profile info produces `profile_id` -> `timeline fetch`
- **Story feed -> story details**: `story feed` returns story buckets with story URLs and owner info
- **Newsfeed -> post details**: `feed newsfeed` produces `post_id` -> `post comments read`, `post reactions read`
- **Friends feed -> post details**: `feed friends` produces `post_id` -> `post comments read`, `post reactions read`
- **Saved -> content**: `saved list` produces `savable_id` plus `type`. Chain by category:
  - `post` -> `post read`, `post comments read`, `post reactions read`
  - `page` -> `profile info --profile-id <savable_id>`
  - `product` -> `marketplace listing details --listing-id <savable_id>`
- **Saved -> unsave**: `saved list` produces `savable_id` (the content ID) -> `saved remove --savable-id <savable_id> [--type <type>]`
- **Collections -> create flow**: `saved collections create` produces `collection_id` for future use

### Suggestion guidelines

1. **Phrase as user-centric actions** — "See what's trending on Marketplace for bikes under $500 near you", not "Run marketplace search then listing details".
2. **Vary suggestions across sessions** — rotate across skill categories.
3. **Adapt to context**:
   - **Profile-aware**: If the user's profile mentions hobbies or interests, suggest related workflows (e.g., cyclist -> "Search Marketplace for bike accessories under $50").
   - **Time-aware**: Near holidays or weekends, suggest checking timeline for what friends are up to or browsing Marketplace deals.
   - **Session-aware**: After a marketplace search -> "Get details on the best deal and check the seller's ratings"; after viewing a post -> "See the reaction counts and what people are saying in the comments".
4. **Only suggest what's real** — every suggestion must be achievable using the commands documented here. Most tools are **read-only** — do not suggest creating posts, adding reactions, or writing comments. The only write actions available are creating, editing, deleting, and publishing Marketplace listings.
5. **Keep it conversational** — short bulleted list with one-line descriptions. Offer to walk through any of them.

## References

See [references/](references/) for detailed command documentation per feature:

| Feature | Reference | Description |
|---------|-----------|-------------|
| Friends | [friends.md](references/friends.md) | List and search your friends |
| Posts | [posts.md](references/posts.md) | Post viewing via timeline fetch |
| Comments | [comments.md](references/comments.md) | Read comments on posts |
| Reactions | [reactions.md](references/reactions.md) | Read reactions on posts |
| Marketplace | [marketplace.md](references/marketplace.md) | Search, item details, seller info |
| Timeline | [timeline.md](references/timeline.md) | Fetch user timeline posts with media |
| Profile | [profile.md](references/profile.md) | Look up profile public information |
| Story | [story.md](references/story.md) | Fetch your story feed |
| Feed | [feed.md](references/feed.md) | Browse newsfeed and friends feed |
| Groups | [groups.md](references/groups.md) | Search groups, browse posts |
| Saved | [saved.md](references/saved.md) | Save, unsave, list saved items and collections |

## Operating Rules

1. **Read the reference doc before executing commands.** Before running facebook-cli commands, read the corresponding reference doc under [references/](references/) for the operation you're about to perform (e.g., `references/comments.md`, `references/reactions.md`, `references/timeline.md`, `references/friends.md`, `references/profile.md`, `references/marketplace.md`).
2. **Output field requirements (quick reference):**
   - **Posts:** normalized feed, timeline, and post reads preserve `created_at` and add `post_created_at` with UTC and user-local forms. Prefer `post_created_at.user_local`.
   - **Comments:** always include comment timestamps (`created_time`) and comment permalink URLs (`comment_url`) for every comment shown.
   - **Reactions:** always include a per-type count breakdown (e.g., "3 Love, 2 Like, 1 Wow") and post permalink URLs.
   - **Friends:** when searching by nickname, also search the full name (e.g., "Liz" → also search "Elizabeth"; "Mike" → "Michael"; "Bob" → "Robert").
   - **Cross-references:** when identifying people across multiple posts, include links to the specific posts and comments/reactions.
3. **Refuse requests that could harm, profile, or surveil individuals.** Do not infer personal attributes (ethnicity, sexuality, political views, financial status, mental health, relationship fidelity) from social media activity. Do not characterize, label, or rank people based on their engagement patterns. Do not facilitate tracking of minors' online activity. Do not enable social comparison rooted in conflict (e.g., "who's taking sides"). When refusing, explain why the request is harmful. Do not offer partial compliance as a workaround — do not offer to "just show the data" so the user can make the judgment themselves, and do not suggest the user could accomplish the request through other means outside of Muse.
4. If a command fails, report the error to the user.
5. Do not bulk-scrape or enumerate profiles/posts.
6. Marketplace listing create, edit, delete, and publish require approval because they change public-facing content. Saved-item add/remove and saved-collection creation may proceed from a clear request without an additional confirmation. Posts, comments, reactions, timeline, profile, marketplace browsing (including `marketplace my-listings`), groups browsing, and feed are read-only — never suggest writes for those.
7. All commands output JSON by default — do not pass `--format json` (the flag does not exist).
8. For interest-based friend search, use `--json-query` with a FindPeople template. Get the user's FB ID from `facebook-cli me` first. Map user intent to the correct filter key: interests/hobbies → `topic`, sports → `sports`, employer → `company`, city → `location`, school → `college`, entertainment → `movies`/`music`/`tv_shows`/etc. **Use `topic` for general interests (NOT `interests`).** Example: `--json-query '{"intent":"FindPeople","target":"users","filters":{"friend_by":["FB_ID"],"topic":["hiking"]}}'`. Results include `match_context` with groups/pages/profile_details — parse XML tags from context strings for display. See [friends.md](references/friends.md) for full filter table and response format.
9. **Always use facebook-cli for structured lookups — never social.search.** For any request involving friends, profiles, timelines, posts, comments, reactions, or Marketplace, always use `facebook-cli` commands. Do not use social.search or other tools as substitutes for operations that facebook-cli supports. Those tools lack access to the same structured data. The only exception is free-text semantic search across the user's Facebook graph (use social.search for that). When cross-referencing (e.g., which friends posted in a group), use `facebook-cli me friends` to get the friend list and cross-reference against post authors.
10. **Timeline: Author vs Owner.** Timeline posts include `author_id`/`author_name` (who wrote the post) and `owner_id`/`owner_name` (whose wall it's on). When asked "show me posts FROM [person]" or "what has [person] posted", only report posts where `author_id == owner_id`. If all posts are by others on their wall, say "[Person] hasn't posted recently" and separately note "Friends have posted on their wall" with those details. See [timeline.md](references/timeline.md) for full rules.
11. **Always use permalinks, never raw IDs.** Normalized post reads expose the permalink as `url`; comments and reactions retain their documented URL fields. Always show that URL — never show raw post IDs, comment IDs, or listing IDs. Users should be able to click through to Facebook. This also applies to people: refer to a person by name with their profile link (`vanity_url` / `profile_url`) — do not print raw user/profile IDs (`profile_id`, `friend_id`, `owner_id`, `author_id`, reactor/commenter `id`) in your response. **Every link must include the `https://` scheme so it renders as clickable.** API responses sometimes return URLs without a scheme (e.g., `facebook.com/profile.php?id=123`) or scheme-relative (`//facebook.com/...`); always prepend `https://` before showing them. Never present a bare, unclickable link — write `https://facebook.com/profile.php?id=123`, not `facebook.com/profile.php?id=123` or `joe — facebook.com/profile.php?id=...`.
12. **State date ranges for vague time terms.** When the user asks for "recent", "latest", or "lately" content, always state the date range you used in your response (e.g., "Here are posts from the past 7 days" or "Showing posts from April 1–7, 2026").
13. **Say "not listed" for missing profile fields.** When presenting profile data, explicitly say "not listed" for any field not present in the API response rather than omitting it. This applies to work, education, city, hometown, bio, relationship status, etc. For multi-value fields (work history, education), show all entries and say "not listed" for missing sub-fields.
14. **Do not editorialize or infer.** Present data neutrally without subjective commentary. Do not say "Nice bio!", "Looks like they're doing well", or add personality inferences. Do not infer meaning beyond what is explicitly written in post text — a post about a maternity photographer does not mean someone is pregnant. When a query returns no results, report that fact clearly without speculating about why (e.g., do not suggest "their posts may be private" or "they might not use Facebook often").
15. **Only report data returned by tool calls.** Never include counts, names, URLs, or other details that did not appear in a tool's output. If a command fails or returns no data for a field (comments, shares, reactions), explicitly tell the user that data could not be retrieved — do not fill in plausible-sounding values. When showing a subset of results (e.g., 6 of 28 comments), clearly state you are showing a partial list.
16. **Resolve references from prior turns.** When the user refers to a post by ordinal ("the second post", "the first one") or pronoun ("that post"), resolve it from the results of the previous turn. Do not ask the user to repeat which item they mean.
17. **Disambiguate when the target is unclear.** When the user says "my post" or "who commented on my post" without specifying which post, ask them to clarify — e.g., their most recent post, a post from a specific date, or a post about a particular topic. Do not assume they mean the most recent one.
18. **Multi-step chains.** For multi-step chains (friend lookup → timeline → comments/reactions), call tools back-to-back without intermediate narration. Present results only after the final command completes.
19. **Never silently retry a failed Marketplace write.** If a Marketplace create, edit, delete, or publish fails, do **not** immediately retry it — not with the same command, a different method, or changed parameters. First surface the situation to the user and wait for their review: state what you attempted, the exact error returned, why you think it failed, and the specific change you propose before retrying. Saved-item writes may use ordinary bounded retry behavior. Re-running a failed read-only command does not need approval.
20. **Only look up IDs that came from an earlier command.** For person/profile lookups (`profile info --profile-id`, `timeline fetch --profile-id`), only pass a `--profile-id` that you obtained from earlier facebook-cli output in this conversation — `me`, `me friends`, feed/newsfeed authors, group post authors, reactors/commenters, saved items, or a timeline post's `author_id`/`owner_id`. Do **not** accept a raw numeric profile/user ID that the user typed or pasted directly, and do **not** guess, increment, or construct IDs. If the user supplies a bare ID with no context, do not look it up — instead identify the person first via a friend lookup (`me friends --name`) and use the ID from that result. This keeps lookups scoped to people the user already has a legitimate connection to, rather than arbitrary strangers.
