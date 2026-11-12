"""Guard command: Claude Code PreToolUse hook. Silent on allow; exit 2 with a reason on stderr blocks the call."""

from __future__ import annotations

import argparse
import json
import sys

from ..guard import FILE_TOOLS, check_command, check_file_access
from ..paths import home


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("guard", help="PreToolUse hook: reads the hook event on stdin, exit 2 blocks unsafe tool calls")
    p.set_defaults(handler=_guard)


def _block(reason: str) -> int:
    print(f"Blocked by E2E Agent Tester guard: {reason}", file=sys.stderr)
    return 2


def _guard(args: argparse.Namespace) -> int:
    try:
        event = json.load(sys.stdin)
        tool, tool_input = event["tool_name"], event["tool_input"]
        if not isinstance(tool, str) or not isinstance(tool_input, dict):
            raise TypeError("malformed hook event")
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return _block("could not read the hook event, so the call is refused (fail closed)")
    try:
        if tool == "Bash":
            command = tool_input.get("command")
            if not isinstance(command, str):
                return _block("Bash call without a command string")
            reason = check_command(command, home()) if command else None
        elif tool in FILE_TOOLS:
            reason = check_file_access(tool, tool_input, home(), subagent=bool(event.get("agent_id")))
        else:
            reason = None
    except Exception as exc:  # fail closed
        return _block(f"guard error ({type(exc).__name__}); call refused")
    return _block(reason) if reason else 0
