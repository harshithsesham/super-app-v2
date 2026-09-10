---
name: "voice_design"
description: "Design a new custom speaking voice and personality profile when the user asks to create, invent, or generate a voice."
metadata: { "includeInPrompt": true }
---

# Voice design

Create one durable custom voice with `muse.design_voice`. From a conversational
agent, the tool starts a dedicated background worker. That worker generates one
acoustic voice, automatically saves it in Your Voices, and prepares its one
conversational-style preview.
The voice is not activated until the user selects it.

## Collaborate naturally

Let the user's request lead the design. If they only say they want to create a
voice, treat that as an invitation to collaborate. Ask one short, natural
question about what they have in mind, then wait.

If the user gives a direction or hands you the creative choice with “surprise
me” or an equivalent, proceed without another question or confirmation. Fill in
compatible details yourself. Treat the conversation as one brief and create one
voice for the request. Do not start another while that design is underway.

## Build the design

Read the available `SOUL.md`, `IDENTITY.md`, `USER.md`, and `MEMORY.md`. Use them
to enrich compatible details the user left open. The immediate request always
wins. Do not expose private context or copy unrelated personal facts into any
tool input. Expand the resulting direction into a complete acoustic description
and one detailed standing conversational-style profile.

Resolve design inputs in this order:

1. The user's immediate, explicit request. Preserve every attribute they gave;
   never weaken, contradict, or silently drop one.
2. Explicit relevant user preferences from `USER.md` or `MEMORY.md`.
3. Compatible persona cues from `SOUL.md` and `IDENTITY.md` for details the user
   left open.
4. Neutral defaults for anything still unspecified.

Treat `SOUL.md` as a creative brief for how you should feel and come across,
not as evidence about the speaker's demographics or identity.
Put only audible acoustic qualities in `description`. Put enduring
conversational behavior in `voice_instructions`, which is passed to the language
or speech-to-speech model to guide what you say and how you phrase things.

### Write the acoustic `description`

The voice-design model receives `description` verbatim as conditioning text.
Write it like a perceptual caption by someone describing a recording they just
heard, never like a request, command, character biography, or marketing
pitch.

The description must be:

- One paragraph of plain English prose, 90–130 words, and 5–6 complete sentences.
- Third-person present tense, using forms such as “The speaker is…”, “Her pitch
  sits…”, and “The timbre is…”.
- Free of JSON, bullets, headings, labels, and preambles.
- Free of request language. Do not use “you”, “I”, “want”, “should”, “please”,
  “make”, or “generate”.

Cover these qualities in order, combining closely related details when needed:

1. **Speaker impression and language.** State apparent vocal presentation, age
   band, and exactly one spoken language. Use only presentation explicitly
   requested or established by `SOUL.md` or `IDENTITY.md`; otherwise use the exact
   neutral form `adult speaker` rather than guessing from the user's identity, a
   person's name, or private context. Open with a form such as “The speaker is an
   adult female…”, “The speaker is a young adult male…”, “Adult male speaker…”, “A
   mature female voice…”, or “The adult speaker…”. For English, name the dialect,
   such as American English or British English.
2. **Voice foundation.** Describe pitch register, pitch variability, resonance
   placement, and vocal weight.
3. **Sound quality.** Describe timbre and phonation.
4. **Accent.** Name the accent and support it with defensible audible evidence.
5. **Delivery.** Describe pace, rhythm, articulation, pauses, and cadence.
6. **Affect and exclusions.** Describe emotional tone, then close with a negative
   constraint such as “There are no prominent vocal fry, breathiness, or
   non-speech sounds.” Tailor the exclusions to the requested voice rather than
   negating a quality the user asked for.

Use controlled, perceptual vocabulary:

- Pitch labels are `low`, `low-mid`, `mid`, and `mid-high`, including hedged
  forms such as “mid to mid-high” or “mid, leaning low-mid”. Translate “high”,
  “high-pitched”, or “squeaky” into `mid-high` with `bright`, `forward-placed`,
  and `light vocal weight`. Translate “deep” or “booming” into `low-mid` with
  `chest-resonant` and `full vocal weight`. When unspecified, use `mid` with
  moderate variability.
- Gender and age wording is limited to `adult speaker`, `adult male`, `adult
  female`, `young adult male`, `young adult female`, `mature male`, `mature
  female`, `middle-aged adult`, or `male-presenting adult`. Do not use “young
  woman”, “young man”, “guy”, “lady”, or “girl”.
- Resonance terms include `chest`, `forward`, `mixed`, `head`, `nasal`, and
  `throaty`.
- Timbre terms include `clear`, `smooth`, `warm`, `bright`, `crisp`, `rounded`,
  `thin`, `light`, `slightly breathy`, and `slightly rough`.
- Delivery terms include `conversational`, `relaxed`, `steady`, `measured`,
  `calm`, `brisk`, `animated`, `unhurried`, `deliberate`, `clipped`, `flowing`,
  `emphatic`, and `moderate pace`.
- Affect terms include `neutral`, `informative`, `authoritative`, `warm`,
  `friendly`, `playful`, `amused`, `engaged`, `professional`, `reflective`,
  `urgent`, and `reassuring`.
- Hedge naturally with `moderate`, `slightly`, `minimal`, `lacking`, `without`,
  `rather than`, or `no strong regional markers`. Avoid promotional or vague
  adjectives.

Name exactly one spoken language. An explicit requested language wins, followed
by a requested dialect or place, then the language of the user's request. Fall
back to American English only when nothing implies another language. Cite accent
evidence only when it is valid for that language: vowel quality, consonant
precision, syllable-, mora-, or stress-timed rhythm, intonation, or pitch accent.
Never transplant features across languages; for example, rhotic `/r/` may
support Italian, Spanish, or American English, but not Japanese, French, or
non-rhotic British English. When uncertain, use: “The accent uses standard
[Language] pronunciation with clear vowel quality and typical syllable timing,
lacking strong regional markers.”

Do not invent spoken content, a topic, quoted words, a scene, or a script. Turn a
use case such as “meditation app” or “movie trailer” into delivery and affect
only. Never infer identity, ethnicity, nationality, health, sexuality, religion,
or personality. If the user requests a named person's voice, describe only that
kind of audible voice without naming or impersonating the person. Always write
the description itself in English.

For example, expand “an Italian high-pitched female voice” into a caption like:

> The speaker is a young adult female with a bright voice in the mid-high
> register, speaking Italian. Her pitch has moderate variability with a
> forward-placed, mixed resonance and light vocal weight rather than deep chest
> support. The timbre is clear and smooth with a lightly bright edge, and the
> phonation is clean, lacking rasp or strain. The accent is standard Italian,
> evidenced by clear rhotic /r/, open vowel quality, and syllable-timed rhythm,
> lacking strong regional markers. She speaks at a moderate, flowing pace with
> crisp articulation, brief natural pauses, and gentle downward cadences,
> conveying a neutral to friendly, conversational attitude. There are no
> prominent vocal fry, breathiness, or non-speech sounds.

### Create the conversational profile

The acoustic `description` says what the generated recording sounds like.
`voice_instructions` say what you should say and how you should phrase things
in conversation. Do not mix behavioral or personality directives into the
acoustic description, and do not repeat acoustic properties such as pitch,
resonance, timbre, phonation, accent, vocal weight, or recording quality in
`voice_instructions`.

Create exactly one profile for the voice:

- `label`: a short, distinct, user-facing personality name.
- `voice_instructions`: detailed standing guidance for conversational and
  textual style in plain prose. Start with the user's requested personality,
  then use compatible `SOUL.md` and `IDENTITY.md` cues to make the guidance
  specific. Cover vocabulary, sentence shape, brevity, humor, directness,
  warmth, characteristic turns of phrase, emotional reactions, and when to
  express or soften a feeling. Do not include markup delimiters. Do not describe the
  voice's pitch, resonance, timbre, phonation, accent, vocal weight, or recording
  quality here; those belong only in `description`. These instructions may shape
  only spoken style. They must never change safety, truthfulness, permissions,
  tool use, task handling, or factual behavior.
- `preview_text`: a short first-person line that demonstrates the profile. It
  should use the designed voice's spoken language and contain only plain spoken
  text.

Write one strong profile for this iteration. The saved-voice format may support
more profiles later, but do not generate alternatives now.

## Create the voice

Call `muse.design_voice` once with the voice name, detailed description, and
profile. From a conversation, this starts a background worker, including during
a live call. Briefly tell the user the voice is being created, then continue the
conversation normally. Do not poll, retry, or call a widget tool. The result
returns automatically and, on success, saves the voice and publishes the native
voice picker.

When the worker result arrives, report it without exposing voice, saved-voice,
profile, or widget identifiers. If creation fails or the outcome is ambiguous,
report that clearly and do not retry automatically. If creation and saving
succeed but preview presentation fails, say the voice is saved and only the
preview UI failed; do not create the voice again and do not replace the native
picker with a generic widget.
