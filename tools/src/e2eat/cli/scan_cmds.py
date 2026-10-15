"""Scan command: run security scanners against the run's repo."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..scan import run_scans
from ..workspace import load_run
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("scan", help="run gitleaks/semgrep/trivy/osv in containers; output to evidence/security-agent/")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--tools", help="comma-separated scanners (default: budgets.scanners of the run)")
    p.set_defaults(handler=_scan)


def _scan(args: argparse.Namespace) -> int:
    tools = args.tools.split(",") if args.tools else load_run(args.run_dir)["budgets"]["scanners"]
    summary = run_scans(args.run_dir, [tool.strip() for tool in tools if tool.strip()])
    emit(summary)
    return 0 if all(r["ok"] for r in summary["results"]) else 1
