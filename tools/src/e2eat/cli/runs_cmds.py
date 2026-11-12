"""runs commands: list run workspaces and prune old ones."""

from __future__ import annotations

import argparse

from ..paths import runs_root
from ..runs import list_runs, prune_runs
from ..sandbox import labelled_run_ids
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    runs = sub.add_parser("runs", help="list run workspaces and prune old ones")
    rsub = runs.add_subparsers(dest="runs_command", required=True)

    p = rsub.add_parser("list", help="runs with verdict, state and size, newest first")
    p.set_defaults(handler=_list)

    p = rsub.add_parser("prune", help="delete all but the newest runs (dry run unless --apply)")
    p.add_argument("--keep", type=int, default=10, help="how many of the newest runs to keep (default 10)")
    p.add_argument("--apply", action="store_true", help="actually delete; without it only report what would go")
    p.set_defaults(handler=_prune)


def _list(args: argparse.Namespace) -> int:
    emit(list_runs(runs_root()))
    return 0


def _prune(args: argparse.Namespace) -> int:
    emit(prune_runs(runs_root(), args.keep, apply=args.apply, busy=labelled_run_ids()))
    return 0
