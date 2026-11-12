"""`e2eat` entry point. Every `*_cmds.py` module in this package registers its own subcommands."""

from __future__ import annotations

import argparse
import importlib
import os
import pkgutil
import subprocess
import sys
from types import ModuleType


def _command_groups() -> list[ModuleType]:
    names = sorted(info.name for info in pkgutil.iter_modules(__path__) if info.name.endswith("_cmds"))
    return [importlib.import_module(f"{__name__}.{name}") for name in names]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="e2eat", description="Deterministic helpers for the E2E Agent Tester agents.")
    sub = parser.add_subparsers(dest="command", required=True)
    for group in _command_groups():
        group.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough: list[str] = []
    if "--" in argv:  # everything after the first literal -- belongs to the program being run (container command, git pathspec)
        cut = argv.index("--")
        argv, passthrough = argv[:cut], argv[cut + 1:]
    args = build_parser().parse_args(argv)
    args.passthrough = passthrough
    try:
        return int(args.handler(args) or 0)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"e2eat: error: {exc}", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired as exc:
        print(f"e2eat: error: {' '.join(map(str, exc.cmd))[:120]} timed out after {exc.timeout}s", file=sys.stderr)
        return 2
    except Exception as exc:  # a malformed input file or a bug: one clear line, traceback only on request
        if os.environ.get("E2EAT_DEBUG"):
            raise
        print(f"e2eat: internal error: {type(exc).__name__}: {exc} (set E2EAT_DEBUG=1 for the traceback)", file=sys.stderr)
        return 70
