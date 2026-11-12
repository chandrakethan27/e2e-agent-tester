"""web commands: start/stop the live visualization of a run."""

from __future__ import annotations

import argparse
import subprocess
import sys

from ..paths import home, runs_root
from ..web import start, status, stop, update_lockfile, wait_ready
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    web = sub.add_parser("web", help="live visualization of the agents working on a run (Next.js, in Docker)")
    wsub = web.add_subparsers(dest="web_command", required=True)

    p = wsub.add_parser("start", help="build and start the site, then open it in the browser")
    p.add_argument("--run-id", help="run to show first (default: the newest run)")
    p.add_argument("--port", type=int, default=3000)
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--rebuild", action="store_true", help="rebuild and restart even when the site is already running")
    p.set_defaults(handler=_start)

    p = wsub.add_parser("status", help="is the site running, and where")
    p.set_defaults(handler=_status)

    p = wsub.add_parser("lock", help="regenerate web/package-lock.json in a container (after changing web/package.json)")
    p.set_defaults(handler=_lock)

    p = wsub.add_parser("stop", help="stop the site")
    p.set_defaults(handler=_stop)


def _start(args: argparse.Namespace) -> int:
    result = start(runs_root().resolve(), home() / "web", args.port, args.run_id, rebuild=args.rebuild)
    result["ready"] = wait_ready(result["url"])
    if not result["ready"]:
        result["warning"] = "the site did not answer within 45 s; check `docker logs e2eat-web`"
    elif not args.no_open and sys.platform == "darwin":
        subprocess.run(["open", result["url"]], check=False)
    emit(result)
    return 0 if result["ready"] else 1


def _lock(args: argparse.Namespace) -> int:
    emit(update_lockfile(home() / "web"))
    return 0


def _status(args: argparse.Namespace) -> int:
    emit(status())
    return 0


def _stop(args: argparse.Namespace) -> int:
    stop()
    emit({"stopped": True})
    return 0
