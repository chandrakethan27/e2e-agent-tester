"""Render command: write report.md and report.html for a run."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..render import render_run
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("render", help="write report.md and a self-contained report.html")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(handler=_render)


def _render(args: argparse.Namespace) -> int:
    emit(render_run(args.run_dir))
    return 0
