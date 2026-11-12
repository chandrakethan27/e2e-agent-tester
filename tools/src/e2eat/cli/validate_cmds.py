"""Contract commands: validate run artifacts, print schemas."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from ..validate import SCHEMA_NAMES, load_schema, validate_run
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("validate", help="validate run artifacts against the schemas (exit 1 on issues)")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--check-evidence", action="store_true", help="also require every evidence path to exist inside the run")
    p.add_argument("--quarantine", action="store_true", help="move invalid findings/messages to blackboard/invalid/")
    p.set_defaults(handler=_validate)

    p = sub.add_parser("schema", help="print a JSON Schema")
    p.add_argument("name", choices=SCHEMA_NAMES)
    p.set_defaults(handler=_schema)


def _validate(args: argparse.Namespace) -> int:
    issues = validate_run(args.run_dir, args.check_evidence, args.quarantine, grace_secs=3)
    emit({"ok": not issues, "issues": [asdict(issue) for issue in issues]})
    return 1 if issues else 0


def _schema(args: argparse.Namespace) -> int:
    emit(load_schema(args.name))
    return 0
