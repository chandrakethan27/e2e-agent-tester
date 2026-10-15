from e2eat.jsonio import read_json
from e2eat.score import compute_scores, score_run
from e2eat.validate import validate_run
from e2eat.workspace import set_agent
from helpers import add_finding, finding

ALL = ["runner-agent", "functional-tester", "suite-runner", "perf-agent", "security-agent", "architecture-agent", "viability-agent"]
RUNNING = {"status": "running"}


def run_with(profile, done):
    return {"profile": profile, "agents": {agent: {"status": "done"} for agent in done}}


def test_perfect_run_adopt():
    s = compute_scores(run_with("adopt", ALL), [], RUNNING)
    assert (s["overall"], s["verdict"], s["coverage_pct"], s["gates"]) == (100, "Adopt", 100, [])


def test_penalties_and_weights():
    findings = [
        finding(id="F-security-001", severity="high", status="confirmed"),
        finding(id="F-security-002", severity="medium", status="confirmed"),
        finding(id="F-security-003", severity="critical", status="dropped"),
    ]
    s = compute_scores(run_with("adopt", ALL), findings, RUNNING)
    assert s["dimensions"]["security"]["score"] == 72
    assert s["dimensions"]["security"]["findings"] == ["F-security-001", "F-security-002"]
    assert s["overall"] == 93  # 0.25 * 72 + 0.75 * 100
    assert s["verdict"] == "Adopt"
    assert s["counts"]["dropped"] == 1


def test_uncovered_dimensions_are_na_and_weights_renormalize():
    findings = [finding(id="F-security-001", status="confirmed"), finding(id="F-security-002", status="confirmed")]
    s = compute_scores(run_with("radar", ["security-agent"]), findings, RUNNING)
    assert s["dimensions"]["performance"]["score"] is None
    assert s["coverage_pct"] == 10
    assert s["overall"] == 60
    assert s["verdict"] == "Assess (low confidence)"


def test_zero_coverage_is_insufficient_data():
    s = compute_scores(run_with("adopt", []), [], {})
    assert (s["overall"], s["verdict"], s["coverage_pct"]) == (None, "Insufficient data", 0)


def test_critical_security_gate_caps_verdict():
    s = compute_scores(run_with("adopt", ALL), [finding(severity="critical", status="confirmed")], RUNNING)
    assert s["overall"] == 90
    assert s["verdict"] == "Hold"
    assert s["gates"] == ["confirmed critical security finding"]


def test_could_not_run_gate_applies_to_adopt_and_audit_only():
    done = ["runner-agent", "security-agent", "architecture-agent", "viability-agent"]
    assert compute_scores(run_with("audit", done), [], {"status": "failed"})["verdict"] == "Not ready"
    assert compute_scores(run_with("radar", done), [], {"status": "failed"})["gates"] == []


def test_license_gate_only_for_adopt():
    lic = finding(id="F-viability-001", agent="viability-agent", dimension="compliance", severity="critical", status="confirmed")
    assert compute_scores(run_with("adopt", ALL), [lic], RUNNING)["verdict"] == "Hold"
    assert compute_scores(run_with("radar", ALL), [lic], RUNNING)["gates"] == []


def test_confirmed_finding_counts_as_coverage_even_if_agent_failed():
    s = compute_scores(run_with("adopt", []), [finding(severity="low", status="confirmed")], {})
    assert s["dimensions"]["security"]["covered"] is True


def test_score_run_writes_valid_scores(run_dir):
    set_agent(run_dir, "security-agent", "done")
    add_finding(run_dir, status="confirmed")
    scores = score_run(run_dir)
    assert read_json(run_dir / "scores.json") == scores
    assert validate_run(run_dir) == []
