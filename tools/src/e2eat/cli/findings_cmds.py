"""Blackboard commands: ids, finding/message queries, cross-examination, run status."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ..blackboard import (
    FINDING_STATUSES,
    apply_crossexam,
    challengeable,
    expire_open_messages,
    finalize_findings,
    load_findings,
    load_messages,
    next_finding_id,
    next_message_id,
    update_finding,
)
from ..workspace import load_run
from .output import emit

SUMMARY_FIELDS = ("id", "agent", "dimension", "severity", "title", "confidence", "status")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("next-id", help="next free finding id (or message id with --message) for an agent")
    p.add_argument("run_dir", type=Path)
    p.add_argument("agent")
    p.add_argument("--message", action="store_true")
    p.set_defaults(handler=_next_id)

    p = sub.add_parser("findings", help="list findings in compact form")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--status", choices=FINDING_STATUSES)
    p.add_argument("--challengeable", action="store_true", help="open critical/high or low-confidence findings, capped by budgets.challenge_limit")
    p.add_argument("--limit", type=int)
    p.set_defaults(handler=_findings)

    p = sub.add_parser("messages", help="list agent-to-agent questions")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--status", choices=("open", "answered", "expired"))
    p.add_argument("--expire", action="store_true", help="mark every still-open question expired (unanswered = coverage gap) and list them")
    p.set_defaults(handler=_messages)

    p = sub.add_parser("set-status", help="set a finding status (orchestrator only)")
    p.add_argument("run_dir", type=Path)
    p.add_argument("finding_id")
    p.add_argument("status", choices=FINDING_STATUSES)
    p.add_argument("--reason")
    p.set_defaults(handler=_set_status)

    p = sub.add_parser("apply-crossexam", help="apply skeptic challenges and rulings to findings")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(handler=_apply_crossexam)

    p = sub.add_parser("finalize-findings", help="close cross-examination: open → confirmed; refuses while challenged findings lack a ruling")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--unruled", choices=("block", "keep", "drop"), default="block",
                   help="what to do with challenged findings that have no skeptic ruling (default: refuse)")
    p.set_defaults(handler=_finalize)

    p = sub.add_parser("status", help="phases, squad, agents, finding and message counts")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(handler=_status)


def _next_id(args: argparse.Namespace) -> int:
    make = next_message_id if args.message else next_finding_id
    emit({"id": make(args.run_dir, args.agent)})
    return 0


def _findings(args: argparse.Namespace) -> int:
    findings = load_findings(args.run_dir)
    if args.status:
        findings = [f for f in findings if f.get("status") == args.status]
    if args.challengeable:
        findings = challengeable(findings, args.limit or load_run(args.run_dir)["budgets"]["challenge_limit"])
    elif args.limit:
        findings = findings[: args.limit]
    emit([{key: f.get(key) for key in SUMMARY_FIELDS} for f in findings])
    return 0


def _messages(args: argparse.Namespace) -> int:
    if args.expire:
        emit({"expired": expire_open_messages(args.run_dir)})
        return 0
    messages = load_messages(args.run_dir)
    emit([m for m in messages if not args.status or m.get("status") == args.status])
    return 0


def _set_status(args: argparse.Namespace) -> int:
    emit(update_finding(args.run_dir, args.finding_id, status=args.status, ruling_reason=args.reason))
    return 0


def _apply_crossexam(args: argparse.Namespace) -> int:
    emit(apply_crossexam(args.run_dir))
    return 0


def _finalize(args: argparse.Namespace) -> int:
    emit(finalize_findings(args.run_dir, args.unruled))
    return 0


def _status(args: argparse.Namespace) -> int:
    run = load_run(args.run_dir)
    findings = load_findings(args.run_dir)
    confirmed = [f for f in findings if f.get("status") == "confirmed"]
    emit({
        "run_id": run["run_id"],
        "profile": run["profile"],
        "depth": run["depth"],
        "phases": run["phases"],
        "squad": run["squad"],
        "skipped": run["skipped"],
        "agents": run["agents"],
        "findings": {
            "by_status": dict(Counter(f.get("status") for f in findings)),
            "confirmed_by_severity": dict(Counter(f.get("severity") for f in confirmed)),
        },
        "open_messages": [m["id"] for m in load_messages(args.run_dir) if m.get("status") == "open"],
    })
    return 0
