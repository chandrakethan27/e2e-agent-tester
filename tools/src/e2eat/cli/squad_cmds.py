"""Squad command: decide and record which Phase 2 agents run."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..squad import plan_squad
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("squad", help="choose Phase 2 agents from recon + runtime facts and record them in run.json")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--plan", action="store_true", help="preview only: write nothing, assume the runtime will come up")
    p.set_defaults(handler=_squad)


def _squad(args: argparse.Namespace) -> int:
    emit(plan_squad(args.run_dir, preview=args.plan))
    return 0
