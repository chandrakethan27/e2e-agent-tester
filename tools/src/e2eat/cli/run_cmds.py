"""Run lifecycle commands: init, phase, agent."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..paths import runs_root
from ..validate import agent_output_problems
from ..workspace import (
    AGENT_NAMES, AGENT_STATUSES, DEPTHS, PHASE_STATUSES, PHASES, PROFILES, init_run, load_run, mark_static_only, reconfigure_run,
    set_agent, set_phase,
)
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init", help="create a run workspace and fetch the source")
    p.add_argument("source", help="GitHub URL, git URL, directory, or .zip/.tar.gz/.tgz/.tar archive")
    p.add_argument("--profile", choices=PROFILES, default="adopt")
    p.add_argument("--depth", choices=DEPTHS, default="standard")
    p.add_argument("--runs-root", type=Path, default=None)
    p.set_defaults(handler=_init)

    p = sub.add_parser("phase", help="set a phase status (orchestrator only)")
    p.add_argument("run_dir", type=Path)
    p.add_argument("phase", choices=PHASES)
    p.add_argument("status", choices=PHASE_STATUSES)
    p.set_defaults(handler=_phase)

    p = sub.add_parser("agent", help="set an agent status (orchestrator only)")
    p.add_argument("run_dir", type=Path)
    p.add_argument("agent", choices=AGENT_NAMES)
    p.add_argument("status", choices=AGENT_STATUSES)
    p.add_argument("--note")
    p.add_argument("--agent-id", help="Agent tool id, kept so the agent can be resumed with SendMessage")
    p.add_argument("--force", action="store_true", help="mark done even though the agent's output file is missing or invalid")
    p.set_defaults(handler=_agent)

    p = sub.add_parser("reconfigure", help="change profile/depth of a run that has not started assessing (keeps repo and recon)")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--profile", choices=PROFILES)
    p.add_argument("--depth", choices=DEPTHS)
    p.set_defaults(handler=_reconfigure)

    p = sub.add_parser("static-only", help="record that the project will not be run: runtime.json=static-only, build and runner-agent skipped")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(handler=_static_only)


def _init(args: argparse.Namespace) -> int:
    run_dir = init_run(args.source, args.profile, args.depth, args.runs_root or runs_root())
    run = load_run(run_dir)
    emit({"run_dir": str(run_dir.resolve()), "run_id": run["run_id"], "budgets": run["budgets"], "notes": run["notes"]})
    return 0


def _phase(args: argparse.Namespace) -> int:
    set_phase(args.run_dir, args.phase, args.status)
    emit(load_run(args.run_dir)["phases"])
    return 0


def _reconfigure(args: argparse.Namespace) -> int:
    emit(reconfigure_run(args.run_dir, args.profile, args.depth))
    return 0


def _static_only(args: argparse.Namespace) -> int:
    mark_static_only(args.run_dir)
    emit({"runtime": "static-only", "phases": load_run(args.run_dir)["phases"]})
    return 0


def _agent(args: argparse.Namespace) -> int:
    if args.status == "done" and not args.force and (problems := agent_output_problems(args.run_dir, args.agent)):
        emit({"ok": False, "agent": args.agent, "problems": problems, "hint": "ask the agent to fix its output, or mark it failed"})
        return 1
    set_agent(args.run_dir, args.agent, args.status, note=args.note, agent_id=args.agent_id)
    emit(load_run(args.run_dir)["agents"][args.agent])
    return 0
