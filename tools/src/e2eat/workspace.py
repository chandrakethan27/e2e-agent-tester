"""Run workspaces: runs/<run-id>/ with run.json, the fetched repo, and the blackboard."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .jsonio import read_json, write_json
from .source import Source, drop_escaping_symlinks, fetch_source, neutralize_git_dir, parse_source, strip_userinfo

PROFILES = ("adopt", "radar", "audit")
DEPTHS = ("quick", "standard", "deep")
PHASES = ("intake", "build", "assess", "crossexam", "synthesis", "finalize")
PHASE_STATUSES = ("pending", "running", "done", "failed", "skipped")
AGENT_STATUSES = PHASE_STATUSES
BLACKBOARD_DIRS = ("facts", "findings", "messages", "evidence", "invalid")
BUDGETS = {
    "quick": {"minutes": 15, "max_journeys": 5, "load_seconds": 10, "load_concurrency": 10,
              "scanners": ["gitleaks", "osv"], "challenge_limit": 5},
    "standard": {"minutes": 45, "max_journeys": 12, "load_seconds": 30, "load_concurrency": 50,
                 "scanners": ["gitleaks", "semgrep", "osv", "trivy"], "challenge_limit": 15},
    "deep": {"minutes": 90, "max_journeys": 25, "load_seconds": 120, "load_concurrency": 100,
             "scanners": ["gitleaks", "semgrep", "osv", "trivy"], "challenge_limit": 40},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check(value: str, allowed: tuple[str, ...], what: str) -> None:
    if value not in allowed:
        raise ValueError(f"unknown {what} {value!r}; choose from {', '.join(allowed)}")


def make_run_id(slug: str, now: datetime) -> str:
    return f"{slug}-{now.astimezone(timezone.utc):%Y%m%d-%H%M%S}"


def load_run(run_dir: Path) -> dict:
    return read_json(Path(run_dir) / "run.json")


def save_run(run_dir: Path, run: dict) -> None:
    write_json(Path(run_dir) / "run.json", run)


def init_run(
    raw_source: str,
    profile: str,
    depth: str,
    runs_root: Path,
    now: datetime | None = None,
    fetch: Callable[[Source, Path], None] = fetch_source,
) -> Path:
    _check(profile, PROFILES, "profile")
    _check(depth, DEPTHS, "depth")
    source = parse_source(raw_source)
    if source.kind == "dir":
        src, runs = Path(source.location), Path(runs_root).resolve()
        if runs.is_relative_to(src) or src.is_relative_to(runs):
            raise ValueError(f"source {src} contains the runs folder (or is inside it); evaluate a copy stored elsewhere")
    now = now or _now()
    run_id = make_run_id(source.slug, now)
    run_dir = Path(runs_root) / run_id
    if run_dir.exists():
        raise FileExistsError(f"run already exists: {run_dir}")
    for name in BLACKBOARD_DIRS:
        (run_dir / "blackboard" / name).mkdir(parents=True)
    try:
        fetch(source, run_dir / "repo")
        dropped = drop_escaping_symlinks(run_dir / "repo")
        git_notes = neutralize_git_dir(run_dir / "repo") if source.kind != "git" else []
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    save_run(run_dir, {
        "run_id": run_id,
        "source": {"raw": strip_userinfo(raw_source), "kind": source.kind, "location": strip_userinfo(source.location), "ref": source.ref},
        "profile": profile,
        "depth": depth,
        "budgets": BUDGETS[depth],
        "created_at": now.isoformat(timespec="seconds"),
        "phases": {phase: "pending" for phase in PHASES},
        "squad": [],
        "skipped": {},
        "agents": {},
        "notes": [f"removed symlink escaping repo: {path}" for path in dropped] + git_notes,
    })
    return run_dir


def set_phase(run_dir: Path, phase: str, status: str) -> None:
    _check(phase, PHASES, "phase")
    _check(status, PHASE_STATUSES, "phase status")
    run = load_run(run_dir)
    run["phases"][phase] = status
    save_run(run_dir, run)


def set_agent(run_dir: Path, agent: str, status: str, note: str | None = None, agent_id: str | None = None) -> None:
    _check(status, AGENT_STATUSES, "agent status")
    run = load_run(run_dir)
    entry = run["agents"].get(agent, {})
    entry["status"] = status
    if note is not None:
        entry["note"] = note
    if agent_id is not None:
        entry["agent_id"] = agent_id
    entry["updated_at"] = _now().isoformat(timespec="seconds")
    run["agents"][agent] = entry
    save_run(run_dir, run)


def resume_phase(run: dict) -> str | None:
    return next((p for p in PHASES if run["phases"].get(p) not in ("done", "skipped")), None)
