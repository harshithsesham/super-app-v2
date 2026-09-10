"""Terminal chat with the agent.

    python -m superapp.cli                 # interactive
    python -m superapp.cli --task "..."    # one-shot
    python -m superapp.cli --show-prompt   # print the assembled system prompt and exit
"""
from __future__ import annotations
import argparse, sys
from rich.console import Console
from .config import CONFIG
from .tools import local, memory_tools  # noqa: F401  (registers handlers)
from .agent import subagents  # noqa: F401
from .browser import worker as _bw, web as _bweb  # noqa: F401
from .agent.loop import Agent

console = Console()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", help="run one task and exit")
    ap.add_argument("--tz", default="America/Chicago")
    ap.add_argument("--show-prompt", action="store_true")
    ap.add_argument("--events", action="store_true", help="print tool calls and handoffs as they happen")
    args = ap.parse_args()

    def on_text(s: str):
        console.print(s, end="", highlight=False, markup=False)

    def on_event(kind: str, data: dict):
        if args.events:
            console.print(f"[dim]· {kind} {data}[/dim]")

    agent = Agent("chat", tz=args.tz, on_text=on_text, on_event=on_event)
    if args.show_prompt:
        p = agent.system_prompt()
        print(p)
        console.print(f"\n[dim]{len(p)} chars, ~{len(p)//4} tokens[/dim]")
        return
    if not CONFIG.api_key:
        sys.exit("META_API_KEY is not set. Copy .env.example to .env and add your Meta Model API key.")
    console.print(f"[bold]{agent.assistant_name()}[/bold] ready (model={CONFIG.model}, home={CONFIG.home}). "
                  "Type /quit to exit.")
    if args.task:
        agent.run_turn(args.task)
        console.print()
        return
    while True:
        try:
            user = console.input("\n[bold cyan]you>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user in ("/quit", "/exit"):
            break
        if not user and agent.inbox.empty():
            continue
        console.print(f"[bold magenta]{agent.assistant_name()}>[/bold magenta] ", end="")
        agent.run_turn(user or None)
        console.print()


if __name__ == "__main__":
    main()
