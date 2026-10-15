"""Guard command: Claude Code PreToolUse hook. Silent on allow; exit 2 with a reason on stderr blocks the call."""

from __future__ import annotations

import argparse
import json
import sys

from ..guard import check_command
from ..paths import home


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("guard", help="PreToolUse hook: reads the hook event on stdin, exit 2 blocks unsafe Bash commands")
    p.set_defaults(handler=_guard)


def _guard(args: argparse.Namespace) -> int:
    try:
        event = json.load(sys.stdin)
        command = event["tool_input"]["command"] if event.get("tool_name") == "Bash" else ""
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return 0  # not a Bash event we understand: let Claude Code's own permissions decide
    reason = check_command(command, home()) if isinstance(command, str) and command else None
    if reason:
        print(f"Blocked by E2E Agent Tester guard: {reason}", file=sys.stderr)
        return 2
    return 0
