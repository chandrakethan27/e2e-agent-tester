"""Run lifecycle commands: init, phase, agent."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..paths import runs_root
from ..workspace import AGENT_NAMES, AGENT_STATUSES, DEPTHS, PHASE_STATUSES, PHASES, PROFILES, init_run, load_run, set_agent, set_phase
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
    p.set_defaults(handler=_agent)


def _init(args: argparse.Namespace) -> int:
    run_dir = init_run(args.source, args.profile, args.depth, args.runs_root or runs_root())
    run = load_run(run_dir)
    emit({"run_dir": str(run_dir.resolve()), "run_id": run["run_id"], "budgets": run["budgets"], "notes": run["notes"]})
    return 0


def _phase(args: argparse.Namespace) -> int:
    set_phase(args.run_dir, args.phase, args.status)
    emit(load_run(args.run_dir)["phases"])
    return 0


def _agent(args: argparse.Namespace) -> int:
    set_agent(args.run_dir, args.agent, args.status, note=args.note, agent_id=args.agent_id)
    emit(load_run(args.run_dir)["agents"][args.agent])
    return 0
