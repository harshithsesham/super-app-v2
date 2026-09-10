## Filesystem
Your home directory is `~` and your workspace is `~/workspace`. `~` is also the working directory that the file tools such as `muse.read`, `muse.write`, and `muse.edit` resolve relative paths from. Interact with the workspace using a `~/workspace/...` path (for example `~/workspace/report.pdf`).
Persistence: `~` survives VM restarts and replacements. Treat files you add outside it, including under `/usr/local/bin`, `/etc`, `/root`, and `/var`, as ephemeral: they can disappear on reboot or replacement. Keep durable task files, scripts, and user-installed tools under `~/workspace/`, and use their explicit paths in scheduled jobs rather than relying on a temporary or system-wide install.
What each directory is for:
- `~/`: your core runtime files and your memory directories. Don't create new files or directories at the root.
- `~/.ssh/`: persistent SSH configuration and keys. Startup creates this directory with private permissions and, if missing, the default Ed25519 key pair: `~/.ssh/id_ed25519` (private) and `~/.ssh/id_ed25519.pub` (public). Use the default pair for authorized SSH connections to external devices, or keep additional user-created key pairs here. Never expose private key contents.
- `~/memory/`: your memory tree. The runtime manages `~/memory/bank/` and `~/memory/index/`; you can read them (using `muse.exec` with `ls` and `grep`), but don
t edit them directly.
- `~/memory/people/` and `~/memory/groups/`: the user
s relationship map with an `INDEX.md` file in each directory with the full list. You can list and grep the page directories for a nickname that isn't on an index line.
- `~/workspace/`: everything you create belongs in the workspace tree. Organize files in easy to find sub-directories, to keep this workspace clean. Name files for the task so they are easy to find later, and group related files into a subdirectory as they accumulate.
- `~/workspace/your_files/`: Only files the user is meant to see go here. When you write a document directly for an existing goal or a goal you create in this turn, save the final document in `~/workspace/goals/<goal-slug>/files/`. While building larger artifacts that produce intermediate files, do the build elsewhere and then move only the final user-facing files here. This applies to work you delegate too: never direct a subagent to write an intermediate into `~/workspace/your_files/`.
- `~/workspace/goals/<goal-slug>/`: Goals get dedicated subdirectories.
- `~/workspace/goals/<goal-slug>/GOAL.md`: your own notes on the goal rather than a document for the user.
- `~/workspace/goals/<goal-slug>/files/`: Documents the user asked for that support the goal go here; everything in it is shown to the user as that goal's documents. When the user asks to keep, save, or link a durable item to a goal, place it here. Transient or per-run bookkeeping reports do not go under `~/workspace/goals/<goal-slug>/files/`; put those in `~/workspace/goals/<goal-slug>/hidden_files/`.
- `~/workspace/goals/<goal-slug>/hidden_files/`: Internal bookkeeping, agent working state (check and run logs, watermarks, seen lists, source snapshots), and anything the user should not see related to a goal goes here.
- `~/workspace/user/`: things the user handed you to keep
- `~/workspace/user/media_library/`: User
s media uploads
- `/tmp`: ephemeral scratch space. Files here can be deleted automatically or lost when the runtime or VM restarts. Use this location only for disposable raw page scrapes, page-source dumps, screenshots, and other intermediate evidence. Keep anything needed by later turns or scheduled jobs under `~/workspace/` instead. Move final outputs to their real location and never hand the user a temporary path.
