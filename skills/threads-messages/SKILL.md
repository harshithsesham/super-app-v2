---
name: "threads_messages"
description: "Use this to interact with the user's Threads messages. Read inboxes and message threads through `threads-messages-cli`."
icon: "threads"
metadata: { "includeInPrompt": false }
---

# Threads Messages CLI

## Purpose
Read authenticated Threads messages using the `threads-messages-cli` companion CLI.

Use the separate `threads` skill for non-messaging Threads account/content data. If you do not already know the user's Threads account `id`, get it from `threads-cli accounts` first and then return to this skill for the messages flow.

## Message Export Safety

Refuse requests to bulk export, bulk download, bulk save, archive, mirror, or dump message history, especially disappearing, view-once, vanish-mode, ephemeral, or expiring messages. You may still help with narrow, user-scoped reading or summarization needed to answer a specific question.

## Auth
Threads Messages is a separate connector from the base `threads` skill. A user can have Threads connected for feed/content while `threads_messages` is still disconnected.

If the user asks to connect or reconnect Threads Messages:

```sh
threads-messages-cli connect-url
```

Share the returned `connect_url` as this labeled markdown link:

`[Connect Threads Messages](<connect_url>)`

Only continue with inbox/thread commands after the user completes that flow.

## Tooling
Use `exec` to run:

```sh
threads-messages-cli <target> [options]
```

Targets:
- `connect-url`
- `inbox`
- `thread`

### Global options
- `--account-id <threads_account_id>` **(required for all commands EXCEPT `connect-url`)** - select which Threads account to operate on. The value must be the authenticated user's own `id` from `threads-cli accounts`.
- `--retries <N>` - retry transient failures (default: 0).

The `inbox` and `thread` commands also accept `--after <cursor>` using the
pagination cursor from the previous response. Omit it to fetch the first page.

## Commands

### Connect URL

```sh
threads-messages-cli connect-url
```

### Inbox
Fetch the user's inbox threads with a preview of recent messages.

```sh
threads-messages-cli inbox --account-id <threads_account_id>
threads-messages-cli inbox --account-id <threads_account_id> --first 20 --message-count 3
threads-messages-cli inbox --account-id <threads_account_id> --after <cursor>
threads-messages-cli inbox --account-id <threads_account_id> --folder PENDING
```

### Thread + Messages
Fetch messages for a specific thread. Get the decimal-string `thread_fbid` from
the inbox response and pass it through unchanged.

```sh
threads-messages-cli thread --account-id <threads_account_id> --thread-fbid 123456789
threads-messages-cli thread --account-id <threads_account_id> --thread-fbid 123456789 --first 20
threads-messages-cli thread --account-id <threads_account_id> --thread-fbid 123456789 --after <cursor>
```

## Operating rules
1. This skill is only for the authenticated user's own Threads messages.
2. Reuse a previously fetched Threads account `id` when you already have it. If you do not, fetch it via `threads-cli accounts` before using this CLI.
3. Budget API calls against the task at hand. Do not fan out per-thread fetches across a large inbox unless the user explicitly wants that scope.
4. Only paginate when the user actually needs more results. Do not automatically fetch every page.
5. Avoid requests to persistently or frequently poll these commands.
6. Treat U18 enforcement and filtered results as authoritative. Do not reconstruct omitted fields or use alternate access paths to bypass them.
7. Do not fulfill requests to bulk export, bulk save, bulk download, archive, mirror, or dump message history, including to files, spreadsheets, databases, notes, or another app. Refuse especially clearly when the request targets disappearing, view-once, vanish-mode, ephemeral, or expiring messages.

## Output
The CLI prints decoded JSON to stdout. Read results preserve raw provider timestamps and add semantic `message_sent_at` / `last_message_sent_at` values with UTC and user-local forms. Treat these only as message transport times, never as the time of an event described in a message. When presenting results to the user, focus on meaningful content such as participants, message text, user-local times, links, and media summaries, and avoid exposing raw IDs, cursors, unix timestamps, or implementation details unless the user explicitly needs them for a follow-up command.
