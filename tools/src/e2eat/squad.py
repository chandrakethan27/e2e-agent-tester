"""Choose which Phase 2 agents run, from the project type, runtime status and depth."""

from __future__ import annotations

from pathlib import Path

from .jsonio import read_json_strict
from .workspace import load_run, save_run

PROJECT_TYPES = ("web-app", "api-service", "cli", "library", "database", "ai-app", "data-pipeline", "infra-tool", "mobile", "unknown")
RUNTIME_AGENTS = ("functional-tester", "suite-runner", "perf-agent")
STATIC_AGENTS = ("security-agent", "architecture-agent", "viability-agent")
_RUNTIME_BY_TYPE = {
    "web-app": RUNTIME_AGENTS,
    "api-service": RUNTIME_AGENTS,
    "cli": RUNTIME_AGENTS,
    "database": RUNTIME_AGENTS,
    "ai-app": RUNTIME_AGENTS,
    "data-pipeline": RUNTIME_AGENTS,
    "library": ("functional-tester", "suite-runner"),
    "infra-tool": ("functional-tester", "suite-runner"),
    "mobile": ("suite-runner",),
    "unknown": ("suite-runner",),
}
_DEEP_EXTRAS = {"library": ("perf-agent",)}


def select_squad(project_type: str, runtime_status: str, depth: str) -> tuple[list[str], dict[str, str]]:
    if project_type not in _RUNTIME_BY_TYPE:
        raise ValueError(f"unknown project_type {project_type!r}; choose from {', '.join(PROJECT_TYPES)}")
    wanted = set(_RUNTIME_BY_TYPE[project_type])
    if depth == "deep":
        wanted |= set(_DEEP_EXTRAS.get(project_type, ()))
    skipped = {agent: f"not applicable to {project_type} at depth {depth}" for agent in RUNTIME_AGENTS if agent not in wanted}
    if runtime_status != "running":
        skipped |= {agent: f"runtime status is {runtime_status}" for agent in RUNTIME_AGENTS if agent in wanted}
        wanted = set()
    return [agent for agent in RUNTIME_AGENTS if agent in wanted] + list(STATIC_AGENTS), skipped


def plan_squad(run_dir: Path) -> dict:
    facts = Path(run_dir) / "blackboard" / "facts"
    recon = read_json_strict(facts / "recon.json", expect=dict)  # no recon means nothing to plan: fail loudly
    runtime = read_json_strict(facts / "runtime.json", {"status": "missing"}, dict)
    if "project_type" not in recon:
        raise ValueError("recon.json has no project_type; rerun recon-agent")
    run = load_run(run_dir)
    squad, skipped = select_squad(recon["project_type"], runtime.get("status", "missing"), run["depth"])
    run["squad"], run["skipped"] = squad, skipped
    for agent, reason in skipped.items():
        run["agents"][agent] = {"status": "skipped", "note": reason}
    save_run(run_dir, run)
    return {"squad": squad, "skipped": skipped}
