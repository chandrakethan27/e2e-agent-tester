"""Score command: compute scores.json from confirmed findings."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..score import score_run
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("score", help="compute scores.json (dimension scores, gates, verdict) from confirmed findings")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(handler=_score)


def _score(args: argparse.Namespace) -> int:
    emit(score_run(args.run_dir))
    return 0
