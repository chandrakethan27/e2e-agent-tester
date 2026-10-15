"""Doctor command: preflight checks for /evaluate."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from ..doctor import run_checks
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("doctor", help="check docker, git, uv, gh, gstack browse and secrets.env (exit 1 if a required check fails)")
    p.set_defaults(handler=_doctor)


def _doctor(args: argparse.Namespace) -> int:
    checks = run_checks()
    ok = all(c.ok for c in checks if c.required)
    emit({"ok": ok, "checks": [asdict(c) for c in checks]})
    return 0 if ok else 1
