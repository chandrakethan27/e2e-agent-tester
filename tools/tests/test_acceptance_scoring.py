"""The known-answer fixtures (fixtures/EXPECTED.md) as executable checks at the scoring and squad level.

A live `/evaluate` of each fixture needs an interactive Claude Code session with Docker; these tests pin what the
deterministic half must conclude once the agents have produced findings and coverage of the expected shape."""

from e2eat.score import ASSESSING_AGENTS, DIMENSION_AGENTS, DIMENSIONS, compute_scores
from e2eat.squad import select_squad
from helpers import finding

RUNNING = {"status": "running"}


def run_with(profile, done, squad=()):
    return {"profile": profile, "agents": {a: {"status": "done"} for a in done}, "squad": list(squad)}


def coverage(agents, ran_ratio=1.0):
    return {a: {"coverage": {d: {"planned": 4, "run": round(4 * ran_ratio)} for d in DIMENSIONS if a in DIMENSION_AGENTS[d]}} for a in agents}


def confirmed(fid, dimension, severity, agent):
    return finding(id=fid, agent=agent, dimension=dimension, severity=severity, status="confirmed")


def test_vuln_flask_is_held_for_security_and_license():
    findings = [
        confirmed("F-security-001", "security", "critical", "security-agent"),   # SQL injection in /search, curl repro
        confirmed("F-security-002", "security", "critical", "security-agent"),   # API_SECRET found by gitleaks
        confirmed("F-security-003", "security", "high", "security-agent"),       # flask/werkzeug 2.2.2 CVEs (osv)
        confirmed("F-functional-004", "functional", "high", "functional-tester"),  # "safe against injection" / "1000 req/s" are false
        confirmed("F-viability-005", "compliance", "critical", "viability-agent"),  # missing license
    ]
    s = compute_scores(run_with("adopt", ASSESSING_AGENTS), findings, RUNNING, coverage(ASSESSING_AGENTS))
    assert s["verdict"] == "Hold"
    assert "confirmed critical security finding" in s["gates"]
    assert "confirmed critical compliance (license) finding" in s["gates"]
    assert s["mode"] == "run"


def test_tiny_cli_is_adopt_or_trial_under_radar():
    agents = [a for a in ASSESSING_AGENTS if a != "perf-agent"]  # a CLI squad still includes perf, but the radar verdict must survive its absence
    done = [*agents, "perf-agent"]
    findings = [confirmed("F-architecture-001", "maintainability", "low", "architecture-agent"),
                confirmed("F-viability-002", "viability", "low", "viability-agent")]
    s = compute_scores(run_with("radar", done), findings, RUNNING, coverage(done))
    assert s["verdict"] in ("Adopt", "Trial") and s["gates"] == [] and s["caps"] == []


def test_broken_build_is_held_with_the_not_run_gate_and_a_static_squad():
    squad, skipped = select_squad("api-service", "failed", "quick")
    assert squad == ["security-agent", "architecture-agent", "viability-agent"]
    assert set(skipped) == {"functional-tester", "suite-runner", "perf-agent"}
    done = ["runner-agent", *squad]
    facts = coverage(done)
    facts["runner-agent"] = {"coverage": {"operability": {"planned": 4, "run": 0, "blocked": 4}}}
    findings = [confirmed("F-runner-001", "functional", "critical", "runner-agent")]  # npm 404 for the missing package
    s = compute_scores(run_with("adopt", done, squad), findings, {"status": "failed"}, facts)
    assert s["verdict"] == "Hold" and s["mode"] == "not-run"
    assert any(g.startswith("project was not built and run successfully") for g in s["gates"])
    assert "confirmed critical functional finding" in s["gates"]
    assert s["dimensions"]["performance"]["covered"] is False and s["dimensions"]["reliability"]["covered"] is False


def test_a_clean_full_run_still_earns_adopt():
    s = compute_scores(run_with("adopt", ASSESSING_AGENTS), [], RUNNING, coverage(ASSESSING_AGENTS))
    assert (s["verdict"], s["overall"], s["coverage_pct"]) == ("Adopt", 100, 100)
