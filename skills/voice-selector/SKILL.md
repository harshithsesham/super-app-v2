---
name: "voice_selector"
description: "Browse, preview, select, or check the voice used for voice calls. Use when the user asks about available voices or wants to change the one in use."
metadata: { "includeInPrompt": false, "voiceOnly": true }
---

# Voice Selector

## Purpose
Recommend and set the voice used for voice calls. On a live call this skill is
run by the **Voice Background Agent** (the voice companion) after the live voice
agent delegates a voice-change request to it — that is the only context where
`set_voice_preference` is available, so a voice change is always applied from the
companion, never from the root agent directly. First decide which of two paths the
request wants:

- **Set a named voice directly** — the request names a specific voice ("switch to
  Satiny", "use Glossy"). Resolve the name and set it immediately; **do not** show
  the widget.
- **Suggest voices with the `voice_options` widget** — a generic, exploratory, or
  preference-based change ("change your voice", "something calmer", "what voices are
  there"). Pick a few fitting voices and present them with the `voice_options`
  widget so the user can preview, select, or browse all.

## Decide the path

Read the request and pick exactly one path:

- **Direct set** when the user names a specific voice that exists in the catalog —
  "switch to Satiny", "use the Glossy voice", "make your voice Smoky", "change to
  Warm". Resolve the name to its catalog `id` and set it immediately (see "Set a
  named voice directly"). **Do not show the widget.** The named request is itself
  the confirmation — do not ask again before setting.
- **Suggest voices with the widget** for every other voice-change or browse request:
  a generic change with no name ("can you change your voice?", "use a different
  voice", "pick a voice for me", "switch it up", "help me pick a voice"),
  browsing/availability ("what voices are there?", "show me the options"), or a
  preference/characteristic with no single catalog name ("something calmer", "a
  younger-sounding voice", "a British accent", "sound deeper/warmer"). A request to
  **sound different by characteristic** (calmer, deeper, warmer, younger, an accent)
  is a voice-change — suggest fitting voices; it is NOT a request to merely adjust
  your speaking tone, and you must not just say you'll "speak softer" without
  presenting the widget. See "Suggest voices with the `voice_options` widget".
- If the user names a voice that is **not** in the catalog, do not fabricate it —
  treat it as a preference and suggest the closest real matches with the widget.

## The voice_source.json catalog

All real voices live in `/opt/hatch/skills/voice-selector/voice_source.json`. You do not
know the voices from memory — always read this file before recommending or
setting, and copy ids and names from it verbatim. A failed read means stop and fix
the read, never improvise voices.

**Reading it:** `read /opt/hatch/skills/voice-selector/voice_source.json` — pass
that absolute path exactly. Product skills live outside the durable home; use
the same path with `exec`/`cat`.

**Shape:** a JSON array of voice entries. Each entry has:
- `id` — the canonical voice id, e.g. `avocado_v2:MAI_01`. Use it verbatim in the
  `voice_options` widget, when calling `set_voice_preference`, and when passing
  `--voice` to `tts`.
- `name` — the display name, e.g. "Warm". This is the only thing you may say to
  the user; never speak the id or any `avocado`/`play_ai` prefix.
- `gender` — the explicit voice gender code from the catalog: `F`, `M`, or `N`.
  Use this field for gender matching instead of inferring from the name or
  parsing `long_description`.
- `description` — a short UI blurb, e.g. "Friendly, American".
- `long_description` — the fuller audited ranking description. Older entries
  may carry a `(gender, age)` suffix for compatibility. Treat the explicit
  `gender` field as the canonical gender source.

Example entry:

```json
{"id": "avocado_v2:MAI_01", "name": "Warm", "gender": "F", "description": "Friendly, American", "long_description": "Friendly, warm, American (F, Middle)"}
```

Match entries by meaning, not literal keywords. Treat `long_description` as
the primary evidence for semantic persona fit because it contains the audited
vocal character, delivery, accent, and affect. Use `description` as a compact
summary and `gender` as the authoritative gender signal (see priority below).

## Set a named voice directly

Use this path when the request names a specific catalog voice ("switch to Satiny",
"use the Glossy voice", "make your voice Smoky").

1. **Read the catalog** ("The voice_source.json catalog" above) and resolve the
   requested name to its entry, copying `id` and `name` verbatim as a matched pair.
   If the name is not in the catalog, do not invent it — switch to the widget path
   with the closest real matches instead.
2. **Call `set_voice_preference` immediately** — no confirmation step, because
   the named request is itself the confirmation. Pass only the canonical id:

   ```text
   set_voice_preference({"voice_id": "<id>"})
   ```

   The tool owns persistence. Do **not** write or delete `user/voice.json`, and
   do not record the choice in `USER.md`, `MEMORY.md`, a persona/identity file,
   or a note. Those are not voice-preference mutation paths.

3. **Confirm by display name**, briefly (e.g. "Done — I've switched to Satiny."). On
   a live voice call the new voice applies live mid-session; if no call is active it
   applies to the next call. Do not restart the call, end the call, or tell the user
   to do either, and **do not show the widget**.

## Suggest voices with the `voice_options` widget

Use this path for generic, exploratory, browse, or preference requests — anything
that is a voice change or voice question without a single named catalog voice.

### 1. Pick the voices to suggest

1. **Read the catalog** (see "The voice_source.json catalog" above) and the
   persona before choosing.
2. **Read the persona/context** (each if present): `SOUL.md` (core character),
   `IDENTITY.md` (identity and vibe), `USER.md` (the user's preferences),
   `MEMORY.md` (durable memory). Also use the conversation for cues.
3. **Choose the voices that genuinely fit, using this priority.** Recommend only
   as many as are actually relevant — two or three strong matches is better than
   padding. Never exceed three, and never present an empty widget. Use each
   entry's explicit `gender` field (`F`, `M`, or `N`) for gender matching. Age
   remains available in the `(gender, age)` suffix of `long_description`.
   1. **Gender.** Infer the assistant's gender presentation only from direct
      evidence: explicit pronouns or gender, the assistant's name, a specific
      named-person/character reference, or direct gendered identity and
      relationship words. Do not infer gender from profession, personality,
      interests, tone, or general vibe; doctors, nurses, executives, assistants,
      and caregivers may have any gender. When direct evidence establishes a
      gender, strongly prefer matching voices and exclude mismatches. If the
      user explicitly asked for a particular gender, honor that.
   2. **Tone and vibe.** Use the full `long_description` first to match warmth,
      energy, delivery, and formality, plus any explicit cue ("warm",
      "professional", "calm", "playful").
   3. **Age and accent.** Read these from the descriptions and use them when the
      persona or request suggests them; otherwise prefer common, widely
      accepted voices.
   4. **Natural by default.** Standard voices; pick novelty/heavily-themed
      character voices (cartoonish, villainous, pirate, caveman) only when the
      persona is explicitly playful or themed.
   5. **Sparse persona.** If the persona is generic, pick safe, versatile voices.
   Interpret by meaning, not literal keywords, and make the suggestions varied.
4. **Copy each voice's `id` and `name` verbatim from the file** — character for
   character, as a matched pair. Never translate an id to a name, reformat, or
   supply one from memory. If a voice is not in the file you just read, it does
   not exist — do not use it.

### 2. Emit the `voice_options` widget

Present your suggestions with the `widget.create` tool, called with exactly
these arguments:

```text
{
  "kind": "voice_options",
  "data": {
    "options": [ {"voice_id": "<exact catalog id>", "name": "<exact catalog name>"}, … up to 3 genuinely-fitting suggestions … ],
    "browse_all": true
  }
}
```

Each option has only `voice_id` (the catalog voice id) and `name` (the display
name) — no `description`. The client renders a TTS preview and a select control
per option, plus a "browse all voices" row that opens the browse-voices sheet
locally. Selecting an option only highlights it in the widget; when the user
confirms with "Switch voice", the client submits a `Switch voice to <name>` turn
back to you (see "When the user chooses"). Because `browse_all` is `true` you do
not need to list every voice — the browse-all row covers the rest. Always pass a
non-empty `options` list matched to the request; never emit an empty widget.

On a live call the Voice Background Agent's turn inherits the caller's client
connection, so `widget.create` reaches the caller's screen.

**The `voice_options` widget is the only way to present a set of voices.** Do NOT
build your own list of voice names in text and do NOT read a list of names aloud —
the widget renders and previews the real voices for you. Do NOT open the
browse-voices sheet (`voice.browse_voices`) yourself; it is reached only
through the widget's "browse all voices" row (a local client action). Every
`voice_id`/`name` you pass must be copied verbatim from the catalog; never invent a
voice name (e.g. do not say "Arista", "Zoe", or any name not in
`voice_source.json`).

**Say one short line that you've suggested a few voices to try.** Do not enumerate
the voices, do not give a per-voice reason, and do not announce a "preferred pick" —
the widget already lists and previews the voices, so reading them aloud is redundant
and too much on a call. One short line is enough, e.g. "I've suggested a few voices
to try — take a listen and pick the one you like." If you mention any voice at all,
use display names only; never say internal ids or "Avocado"/"PlayAI".

If `widget.create` returns an error (e.g. the client did not declare the
`voice_options` capability), fall back to describing the suggested voices by
display name in your reply and letting the user pick in conversation.

### 3. When the user chooses

When the user picks a voice — either in the widget (confirming with **"Switch
voice"**) or from the browse-all sheet — the client submits a `Switch voice to
<name>` turn back to you. Neither pick persists the voice on its own. Handle that
turn like the direct-set path: resolve `<name>` to its catalog `id` and call
`set_voice_preference({"voice_id": "<id>"})` to persist it (the tool owns
persistence; do not write `user/voice.json`), then confirm briefly by display
name. On a live voice call the new voice applies live mid-session; if no call is
active, it applies to the next call. Do not restart or end the call.

If instead the user tells you a specific catalog voice by name in conversation
("go with Satiny"), that is the direct-set path — call
`set_voice_preference({"voice_id": "<id>"})` with the selected catalog id and
confirm by display name. If the user asks to clear or reset the preference without
choosing a concrete catalog voice, do not invent another tool shape; explain that
this flow sets a concrete voice and offer the widget again.

## Checking / current voice
To report the current voice, read `user/voice.json`. If it is missing, empty, or
holds an id not in the catalog, the default voice is id `avocado_v2:MAI_01` —
look that id up in `voice_source.json` and report its current display name (do
not hard-code the name, since names can change). The user can also change the
voice from Settings, so always re-read the file rather than trusting memory or
prior turns.

## TTS preview (optional)
Every catalog voice supports TTS, and the `tts` CLI accepts the catalog `id`
directly. To play a standalone preview the user asked for:

```sh
tts speak --text "<preview text>" --voice <voice_id> --output /tmp/voice-preview.mp3
```

Share the resulting path. Default preview text: `"Hey, how are you doing?"`. Keep
preview text short (under ~200 characters). The browse-voices sheet also previews
voices on its own, so a separate preview is only for explicit "let me hear X"
requests.

## Operating Rules
1. Refer to voices by display **name** only (e.g. "Warm", "Punchy"). Never say
   "Avocado", "PlayAI", "play_ai", or any internal id prefix to the user.
2. Always read `voice_source.json` before suggesting or setting — never pick from
   memory.
3. Do not fabricate voices. Only offer or set ids/names that appear verbatim in the
   file you just read. A failed catalog read means stop and fix the read, not
   improvise. A named voice that is not in the catalog is a preference — suggest the
   closest matches with the widget, do not invent the named voice.
4. Apply gender matching only when the persona supplies the direct evidence in
   the picking priority; never derive it from profession or personality. When
   direct evidence exists, do not suggest a mismatched voice unless the user
   explicitly asked for it.
5. A **named** request ("switch to Satiny") is its own confirmation — set it
   directly without asking again and without showing the widget. For a **widget**
   suggestion, never call `set_voice_preference` from your own suggestion before
   the user picks; when the user confirms with "Switch voice", handle the
   resulting `Switch voice to <name>` turn via the direct-set path (call
   `set_voice_preference`).
6. After changing a voice, simply confirm the voice is set (by display name). Do
   not restart the call, end the call, or tell the user to start a new one. Active
   calls apply the new voice mid-session; if no call is active, the preference
   applies to the next call.
7. When you emit the widget, say only one short line that you've suggested a few
   voices — do not read out the voice list, per-voice reasons, or a preferred pick.
   The widget shows and previews them on screen.
8. If no voice preference is set, you may proactively offer once ("Want to pick a
   voice?"). Do not repeat the offer if the user declines.
