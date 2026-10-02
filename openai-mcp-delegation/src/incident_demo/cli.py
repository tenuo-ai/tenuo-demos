"""Command-line entry point for the demo."""

from __future__ import annotations

import argparse
import asyncio
import os

from .agents import run_live_agent
from .scenarios import run_baseline, run_cases


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Task-scoped authorization across OpenAI agents and MCP"
    )
    parser.add_argument(
        "command",
        choices=("baseline", "cases", "agent", "all"),
        nargs="?",
        default="cases",
    )
    return parser


async def _run(command: str) -> None:
    if command in {"baseline", "all"}:
        await run_baseline(show=True)
    if command == "agent" or (command == "all" and os.environ.get("OPENAI_API_KEY")):
        print("\nLive agent investigation\n")
        print(await run_live_agent())
    elif command == "all":
        print("\nOPENAI_API_KEY is not set; skipped live agent run")
    if command in {"cases", "all"}:
        await run_cases(show=True)


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(_run(args.command))


if __name__ == "__main__":
    main()
