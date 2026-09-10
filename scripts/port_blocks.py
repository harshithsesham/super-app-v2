"""Port the reconstructed Muse prompt blocks into superapp/prompts/blocks.

The source blocks were recovered from strings in a stripped binary, so some
files carry three kinds of noise this script removes:

1. Inline block markers: a run like ``placeholder_nameblocks/chat/tool_rules.md<text>``
   means the extractor glued the *next* block's path and body onto this file.
   We split there and write the glued text to its own block file if that
   block does not already exist.
2. Placeholder-name runs: bare ``{name}`` identifiers concatenated without
   spaces right before a marker. Dropped.
3. Binary garbage: once a file runs into Rust symbol/string-table dumps, the
   remainder is discarded (first garbage line onward).
"""
from __future__ import annotations
import re, sys, pathlib

SRC = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                   "/Users/god/Downloads/aria-inspectable-source/prompt-blocks/blocks")
DST = pathlib.Path(__file__).resolve().parent.parent / "superapp/prompts/blocks"

MARKER = re.compile(r"(?P<junk>[a-z_]*)blocks/(?P<path>[a-z_0-9/]+\.md)")
GARBAGE_PATTERNS = [
    re.compile(r"struct [A-Za-z]+ with \d+ elements"),
    re.compile(r"<\|"),
    re.compile(r"assertion failed"),
    re.compile(r"[a-z_]+::[a-z_]+::"),
    re.compile(r"\x00"),
    re.compile(r"^[A-Za-z0-9\-_]{60,}$"),
    re.compile(r"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"),
    re.compile(r"[a-z]+_[a-z_]+[a-z]+_[a-z_]+[a-z]+_[a-z_]+[a-z]+_[a-z_]+[a-z_]{40,}"),  # long glued identifiers
]

def is_garbage(line: str) -> bool:
    if not line.strip():
        return False
    for p in GARBAGE_PATTERNS:
        if p.search(line):
            return True
    # a long line with almost no spaces is a string-table dump
    if len(line) > 120 and line.count(" ") / len(line) < 0.04:
        return True
    return False

def clean_segment(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if is_garbage(line):
            break
        kept.append(line.rstrip())
    out = "\n".join(kept).strip("\n")
    return out + "\n" if out else ""

written: dict[str, str] = {}
split_out: list[str] = []
truncated: list[str] = []

for src in sorted(SRC.rglob("*")):
    if not src.is_file() or src.name == ".DS_Store":
        continue
    rel = src.relative_to(SRC).as_posix()
    # file names themselves can carry a glued marker, e.g. "x.md{project_context}blocks/..."
    rel = rel.split("{")[0]
    raw = src.read_text(encoding="utf-8", errors="replace")
    pieces: list[tuple[str, str]] = []
    pos, cur_path = 0, rel
    for m in MARKER.finditer(raw):
        before = raw[pos:m.start()]
        pieces.append((cur_path, before))
        cur_path = m.group("path")
        pos = m.end()
    pieces.append((cur_path, raw[pos:]))
    for i, (path, body) in enumerate(pieces):
        body = clean_segment(body)
        if not body:
            continue
        if i > 0 and path != rel:
            if path in written:
                continue  # already have a real file for it
            split_out.append(path)
        if body.count("\n") + 1 < raw.count("\n") + 1 and i == len(pieces) - 1 and len(pieces) == 1:
            truncated.append(path)
        if path in written and i == 0:
            continue
        written.setdefault(path, body)

# real files always win over split-out fragments
for src in sorted(SRC.rglob("*.md")):
    rel = src.relative_to(SRC).as_posix()
    if rel in written and rel not in split_out:
        continue

for path, body in written.items():
    dst = DST / path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body, encoding="utf-8")

print(f"wrote {len(written)} blocks to {DST}")
print(f"split out {len(split_out)} inline blocks: {sorted(set(split_out))}")
print(f"truncated garbage in {len(truncated)} files: {truncated}")
