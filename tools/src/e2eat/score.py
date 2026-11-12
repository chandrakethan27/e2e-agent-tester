"""Deterministic scoring: confirmed findings + reported coverage → dimension scores → profile-weighted verdict.

Design rules (each one closes a way for a degraded run to look good):
- A dimension counts only as far as agents *reported running checks* for it (`coverage` in their facts files); an agent
  that merely returned earns nothing. Partial coverage scales the dimension's weight.
- A confirmed critical finding in any dimension that carries weight caps the verdict at the lowest band
  (compliance only for the adopt profile, where it means the licence forbids use).
- Failed, unfinished or fact-less assessing agents cap the verdict one band below the best.
- Scoring refuses to run on unresolved findings, duplicate ids, unknown severities/dimensions or a corrupt ledger.
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Mapping

from .blackboard import SEVERITIES, load_findings
from .jsonio import read_json_or, read_json_strict, write_json
from .validate import validate_document
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
# Which agents may report coverage for a dimension. runner-agent only vouches for operability (build, start, health, resources).
DIMENSION_AGENTS = {
    "functional": ("functional-tester", "suite-runner"),
    "security": ("security-agent",),
    "performance": ("perf-agent",),
    "reliability": ("functional-tester", "perf-agent"),
    "maintainability": ("architecture-agent", "suite-runner"),
    "operability": ("architecture-agent", "runner-agent"),
    "compliance": ("viability-agent",),
    "viability": ("viability-agent",),
}
ASSESSING_AGENTS = tuple(sorted({agent for agents in DIMENSION_AGENTS.values() for agent in agents}))
FACTS_FILE = {"runner-agent": "runtime.json"}  # every other agent writes facts/<agent>.json
BANDS = {
    "adopt": ((80, "Adopt"), (65, "Trial"), (50, "Assess"), (0, "Hold")),
    "radar": ((80, "Adopt"), (65, "Trial"), (50, "Assess"), (0, "Hold")),
    "audit": ((80, "Production-ready"), (60, "Needs work"), (0, "Not ready")),
}
LOW_COVERAGE_PCT = 40
CAP_BAND_INDEX = 1  # a capped run can be at best the second band
PARTIAL_FLOOR = 0.25  # weight given to a dimension that has confirmed findings but no usable coverage report


def half_up(value: float) -> int:
    return math.floor(value + 0.5)  # round() would send 64.5 down to 64 (banker's rounding) right at a band edge


def verdict_for(profile: str, overall: int) -> str:
    return next(label for threshold, label in BANDS[profile] if overall >= threshold)


def facts_path(run_dir: Path, agent: str) -> Path:
    return Path(run_dir) / "blackboard" / "facts" / FACTS_FILE.get(agent, f"{agent}.json")


def coverage_of(facts: object) -> dict[str, tuple[int, int]]:
    """dimension -> (planned, run) as reported by an agent; empty when the facts have no usable coverage block."""
    block = facts.get("coverage") if isinstance(facts, dict) else None
    if not isinstance(block, dict):
        return {}
    out = {}
    for dim, entry in block.items():
        if dim not in DIMENSIONS or not isinstance(entry, dict):
            continue
        planned, ran = entry.get("planned"), entry.get("run")
        if all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (planned, ran)):
            out[dim] = (planned, min(ran, planned))
    return out


def _untested(agent: str, facts: object) -> list[dict]:
    items = facts.get("untested") if isinstance(facts, dict) else None
    if not isinstance(items, list):
        return []
    return [{"agent": agent, "what": str(i["what"]), "why": str(i.get("why", ""))} for i in items if isinstance(i, dict) and i.get("what")]


def run_mode(runtime: dict) -> str:
    status = runtime.get("status")
    return "run" if status == "running" else "static-only" if status == "static-only" else "not-run"


def _gates(profile: str, confirmed: list[dict], runtime: dict) -> list[str]:
    weights = WEIGHTS[profile]
    gates = []
    for dim in DIMENSIONS:
        if not any(f.get("dimension") == dim and f.get("severity") == "critical" for f in confirmed):
            continue
        if dim == "compliance":
            if profile == "adopt":
                gates.append("confirmed critical compliance (license) finding")
        elif weights[dim] > 0:
            gates.append(f"confirmed critical {dim} finding")
    mode = run_mode(runtime)
    if profile in ("adopt", "audit") and mode == "static-only":
        gates.append("static review only: the project was not run (runtime status: static-only)")
    elif profile in ("adopt", "audit") and mode == "not-run":
        gates.append(f"project was not built and run successfully (runtime status: {runtime.get('status', 'missing')})")
    return gates


def compute_scores(run: dict, findings: list[dict], runtime: dict, facts: Mapping[str, object] | None = None) -> dict:
    profile = run["profile"]
    weights = WEIGHTS[profile]
    facts = facts or {}
    agents = run.get("agents", {})

    def state(agent: str) -> str | None:
        return agents.get(agent, {}).get("status")

    done = [a for a in ASSESSING_AGENTS if state(a) == "done"]
    reported = {a: coverage_of(facts.get(a)) for a in done}
    caps = []
    failed = [a for a in ASSESSING_AGENTS if state(a) == "failed"]
    unfinished = [a for a in run.get("squad", []) if a in ASSESSING_AGENTS and state(a) not in ("done", "skipped", "failed")]
    no_facts = [a for a in done if not reported[a]]
    if failed:
        caps.append(f"agent(s) failed: {', '.join(failed)}")
    if unfinished:
        caps.append(f"agent(s) did not finish: {', '.join(unfinished)}")
    if no_facts:
        caps.append(f"agent(s) finished without usable coverage facts: {', '.join(no_facts)}")

    confirmed = [f for f in findings if f.get("status") == "confirmed"]
    dimensions = {}
    for dim in DIMENSIONS:
        hits = [f for f in confirmed if f.get("dimension") == dim]
        planned = sum(reported.get(a, {}).get(dim, (0, 0))[0] for a in DIMENSION_AGENTS[dim])
        ran = sum(reported.get(a, {}).get(dim, (0, 0))[1] for a in DIMENSION_AGENTS[dim])
        fraction = ran / planned if planned and ran else 0.0
        if not fraction and hits:
            fraction = PARTIAL_FLOOR  # something was found, so something was tested, but nothing vouches for how much
        covered = fraction > 0
        score = max(0, 100 - sum(PENALTY.get(f.get("severity"), 0) for f in hits)) if covered else None
        dimensions[dim] = {
            "score": score, "covered": covered, "weight": weights[dim], "coverage": round(fraction, 2),
            "checks": {"planned": planned, "run": ran}, "findings": sorted(f["id"] for f in hits),
        }
    effective = {dim: d["weight"] * d["coverage"] for dim, d in dimensions.items()}
    covered_weight = sum(effective.values())
    coverage_pct = half_up(100 * covered_weight)
    gates = _gates(profile, confirmed, runtime)
    bands = BANDS[profile]
    if covered_weight == 0:
        overall, verdict = None, "Insufficient data"
    else:
        overall = half_up(sum(effective[dim] * d["score"] for dim, d in dimensions.items() if d["covered"]) / covered_weight)
        index = next(i for i, (threshold, _) in enumerate(bands) if overall >= threshold)
        if gates:
            index = len(bands) - 1
        elif caps:
            index = max(index, CAP_BAND_INDEX)
        verdict = bands[index][1]
        if coverage_pct < LOW_COVERAGE_PCT:
            verdict += " (low confidence)"
    untested = [item for agent in done for item in _untested(agent, facts.get(agent))]
    return {
        "profile": profile,
        "mode": run_mode(runtime),
        "overall": overall,
        "verdict": verdict,
        "coverage_pct": coverage_pct,
        "dimensions": dimensions,
        "gates": gates,
        "caps": caps,
        "untested": untested,
        "problems": [],
        "counts": {
            "confirmed": len(confirmed),
            "dropped": sum(1 for f in findings if f.get("status") == "dropped"),
            "unreviewed": sum(1 for f in confirmed if f.get("reviewed") is False),
            "by_severity": {s: sum(1 for f in confirmed if f.get("severity") == s) for s in SEVERITIES},
        },
    }


def integrity_problems(findings: list[dict]) -> list[str]:
    """Reasons the findings cannot be scored yet. Scoring must fail closed rather than quietly ignore them."""
    problems = []
    duplicates = sorted(i for i, n in Counter(f["id"] for f in findings).items() if n > 1)
    if duplicates:
        problems.append(f"duplicate finding ids: {', '.join(duplicates)}")
    unresolved = sorted(f["id"] for f in findings if f.get("status") in ("open", "disputed"))
    if unresolved:
        problems.append(f"{len(unresolved)} finding(s) still open or disputed ({', '.join(unresolved[:5])}); run apply-crossexam and finalize-findings first")
    bad = sorted(
        f"{f['id']} (severity {f.get('severity')!r}, dimension {f.get('dimension')!r})"
        for f in findings
        if f.get("severity") not in SEVERITIES or f.get("dimension") not in DIMENSIONS
    )
    if bad:
        problems.append(f"findings with an unknown severity or dimension: {', '.join(bad[:5])}")
    return problems


def score_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    findings = load_findings(run_dir)  # raises on a corrupt status ledger
    if problems := integrity_problems(findings):
        raise ValueError("cannot score: " + "; ".join(problems))
    runtime = read_json_strict(run_dir / "blackboard" / "facts" / "runtime.json", {}, dict)
    facts: dict[str, object] = {}
    facts_problems = []
    for agent in ASSESSING_AGENTS:
        data = read_json_or(facts_path(run_dir, agent), None)
        if data is None:
            continue
        errors = [] if agent == "runner-agent" else validate_document(data, "agentfacts")
        if errors:
            facts_problems.append(f"{agent}: facts ignored ({errors[0]})")
        else:
            facts[agent] = data
    scores = compute_scores(load_run(run_dir), findings, runtime, facts)
    scores["problems"] = facts_problems
    write_json(run_dir / "scores.json", scores)
    return scores
