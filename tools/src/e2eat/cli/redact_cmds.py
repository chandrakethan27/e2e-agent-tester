"""Redact command: scrub secret values from a run's evidence and outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..paths import secrets_file
from ..redact import parse_env_file, redact_run
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("redact", help="replace secret values (from secrets.env) in evidence and outputs")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--secrets", type=Path, default=None, help="env file with the secrets (default: <project>/secrets.env)")
    p.set_defaults(handler=_redact)


def _redact(args: argparse.Namespace) -> int:
    path = args.secrets or secrets_file()
    if not path.exists():
        emit({"changed": [], "note": f"no secrets file at {path}"})
        return 0
    emit({"changed": redact_run(args.run_dir, parse_env_file(path))})
    return 0
