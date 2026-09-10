## Dependency Preflight
The toolkit code and fonts ship on the VM, and so does the whole render stack: imaging, ffmpeg, the capture browser, and transcription all come with the VM image, with nothing to install or download. `/opt/hatch/skills/magic-moment/install.sh` verifies that stack, runs a smoke render, and reclaims the vendor layer older installs left behind.
Check first, before any other build step: run `bash /opt/hatch/skills/magic-moment/install.sh --check`. It is sub-second, checks the shipped stack, and touches nothing. Exit 0 confirms dependency presence; rendering and transcript validation establish readiness. Exit 1 means run the full script yourself, right now: `bash /opt/hatch/skills/magic-moment/install.sh` (seconds, idempotent, safe from the cell). No sudo, no root, no handing off. On an image that does not ship the full render stack it says so plainly, and your final report states that setup is not possible on this VM, which is the complete and correct answer.
Hard rules when the stack is missing or broken. Each of these has produced a fabricated video, which is worse than failing:
- Do not `pip install` or download pieces of the stack by hand. The shipped stack is what makes renders reproducible and reviewable; a hand-built substitute drifts from the versions the card and overlay pipeline was tuned against and fails in ways the one-line errors cannot name.
- Do not write or edit `~/workspace/.output/<name>/mm_transcript.json` yourself, and do not reuse a transcript from different footage. `./mm transcribe` preserves the ASR source; use the documented `transcript_correction` field for user-supplied corrections.
- If `/opt/hatch/skills/magic-moment/install.sh` fails, put its actual error in your final report and stop. Do not work around it.
The fonts are self-contained: Optimistic AI (the product face) and Noto Color Emoji ship in the toolkit's `assets/fonts/`, and `load_font` loads from there and nowhere else. Every locked layout number was measured against those exact files, so a system substitute would reflow the whole layout.
## Use the User's Real Avatar
Keep the renderer's animated avatar header: it springs into the opening,
pins above the conversation, and laughs on the closing screen. The renderer
uses level up only when the laughing clip is unavailable, and keeps the close
on screen through one full reaction.
The renderer reads the avatar media and agent name from this VM automatically.
Do not substitute a stock face or add avatars to unrelated cards. Use
`./mm avatar` for card content when the story is about generating that avatar.
Inspect the entrance, pinned header, and closing celebration in the rendered
video, and keep the creator's face visible.
