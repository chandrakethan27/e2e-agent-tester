"""Git command: hardened, read-only git on the evaluated repo. Prints git's own output (not JSON) so agents can pipe it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..repogit import ALLOWED_SUBCOMMANDS, run_git


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("git", help=f"read-only git on <run-dir>/repo ({', '.join(ALLOWED_SUBCOMMANDS)}); raw output")
    p.add_argument("run_dir", type=Path)
    p.add_argument("args", nargs=argparse.REMAINDER, help="git subcommand and options, e.g. log -1 --format=%%cI")
    p.set_defaults(handler=_git)


def _git(args: argparse.Namespace) -> int:
    git_args = args.args[1:] if args.args[:1] == ["--"] else args.args
    result = run_git(args.run_dir, git_args)
    sys.stdout.write(result["stdout"])
    sys.stderr.write(result["stderr"])
    return result["exit_code"]
