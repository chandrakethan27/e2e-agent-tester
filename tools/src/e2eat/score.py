"""Deterministic scoring: confirmed findings → dimension scores → profile-weighted verdict."""

from __future__ import annotations

from pathlib import Path

from .blackboard import SEVERITIES, load_findings
from .jsonio import read_json_strict, write_json
from .workspace import load_run

DIMENSIONS = ("functional", "security", "performance", "reliability", "maintainability", "operability", "compliance", "viability")
PENALTY = {"critical": 40, "high": 20, "medium": 8, "low": 3, "info": 0}
WEIGHTS = {
    "adopt": {"functional": .15, "security": .25, "performance": .05, "reliability": .15,
              "maintainability": .05, "operability": .10, "compliance": .15, "viability": .10},
    "radar": {"functional": .30, "security": .10, "performance": .15, "reliability": .05,
              "maintainability": .15, "operability": .05, "compliance": .05, "viability": .15},
    "audit": {"functional": .15, "security": .25, "performance": .10, "reliability": .15,
              "maintainability": .25, "operability": .10, "compliance": .0, "viability": .0},
}
# A dimension counts as tested when one of these agents finished (or a confirmed finding exists for it).
DIMENSION_AGENTS = {
    "functional": ("functional-tester", "suite-runner", "runner-agent"),
    "security": ("security-agent",),
    "performance": ("perf-agent",),
    "reliability": ("functional-tester", "perf-agent"),
    "maintainability": ("architecture-agent", "suite-runner"),
    "operability": ("architecture-agent", "runner-agent"),
    "compliance": ("viability-agent",),
    "viability": ("viability-agent",),
}
BANDS = {
    "adopt": ((80, "Adopt"), (65, "Trial"), (50, "Assess"), (0, "Hold")),
    "radar": ((80, "Adopt"), (65, "Trial"), (50, "Assess"), (0, "Hold")),
    "audit": ((80, "Production-ready"), (60, "Needs work"), (0, "Not ready")),
}
LOW_COVERAGE_PCT = 40


def verdict_for(profile: str, overall: int) -> str:
    return next(label for threshold, label in BANDS[profile] if overall >= threshold)


def _gates(profile: str, confirmed: list[dict], runtime: dict) -> list[str]:
    def critical_in(dimension: str) -> bool:
        return any(f.get("dimension") == dimension and f.get("severity") == "critical" for f in confirmed)

    gates = []
    if critical_in("security"):
        gates.append("confirmed critical security finding")
    if profile == "adopt" and critical_in("compliance"):
        gates.append("confirmed critical compliance (license) finding")
    if profile in ("adopt", "audit") and runtime.get("status") != "running":
        gates.append(f"project was not built and run successfully (runtime status: {runtime.get('status', 'missing')})")
    return gates


def compute_scores(run: dict, findings: list[dict], runtime: dict) -> dict:
    profile = run["profile"]
    weights = WEIGHTS[profile]
    done = {name for name, info in run.get("agents", {}).items() if info.get("status") == "done"}
    confirmed = [f for f in findings if f.get("status") == "confirmed"]
    dimensions = {}
    for dim in DIMENSIONS:
        hits = [f for f in confirmed if f.get("dimension") == dim]
        covered = bool(hits) or any(agent in done for agent in DIMENSION_AGENTS[dim])
        score = max(0, 100 - sum(PENALTY.get(f.get("severity"), 0) for f in hits)) if covered else None
        dimensions[dim] = {"score": score, "covered": covered, "weight": weights[dim], "findings": sorted(f["id"] for f in hits)}
    covered_weight = sum(d["weight"] for d in dimensions.values() if d["covered"])
    coverage_pct = round(100 * covered_weight)
    gates = _gates(profile, confirmed, runtime)
    if covered_weight == 0:
        overall, verdict = None, "Insufficient data"
    else:
        overall = round(sum(d["weight"] * d["score"] for d in dimensions.values() if d["covered"]) / covered_weight)
        verdict = BANDS[profile][-1][1] if gates else verdict_for(profile, overall)
        if coverage_pct < LOW_COVERAGE_PCT:
            verdict += " (low confidence)"
    return {
        "profile": profile,
        "overall": overall,
        "verdict": verdict,
        "coverage_pct": coverage_pct,
        "dimensions": dimensions,
        "gates": gates,
        "counts": {
            "confirmed": len(confirmed),
            "dropped": sum(1 for f in findings if f.get("status") == "dropped"),
            "by_severity": {s: sum(1 for f in confirmed if f.get("severity") == s) for s in SEVERITIES},
        },
    }


def score_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    runtime = read_json_strict(run_dir / "blackboard" / "facts" / "runtime.json", {}, dict)
    scores = compute_scores(load_run(run_dir), load_findings(run_dir), runtime)
    write_json(run_dir / "scores.json", scores)
    return scores
