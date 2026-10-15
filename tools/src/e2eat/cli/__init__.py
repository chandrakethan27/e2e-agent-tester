"""`e2eat` entry point. Every `*_cmds.py` module in this package registers its own subcommands."""

from __future__ import annotations

import argparse
import importlib
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
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args) or 0)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"e2eat: error: {exc}", file=sys.stderr)
        return 2
