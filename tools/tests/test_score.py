import pytest

from e2eat.blackboard import update_finding
from e2eat.jsonio import read_json
from e2eat.score import (
    ASSESSING_AGENTS,
    BANDS,
    DIMENSION_AGENTS,
    DIMENSIONS,
    WEIGHTS,
    compute_scores,
    half_up,
    score_run,
)
from e2eat.validate import validate_run
from e2eat.workspace import set_agent
from helpers import add_finding, finding, write_json

RUNNING = {"status": "running"}
ALL = list(ASSESSING_AGENTS)


def run_with(profile, done=(), failed=(), squad=(), skipped=()):
    agents = {a: {"status": "done"} for a in done}
    agents |= {a: {"status": "failed"} for a in failed}
    agents |= {a: {"status": "skipped"} for a in skipped}
    return {"profile": profile, "agents": agents, "squad": list(squad)}


def facts_for(agents, planned=4, ran=4, dims=None):
    """Coverage as each agent would report it: every dimension it can vouch for, `ran` of `planned` checks."""
    out = {}
    for agent in agents:
        own = [d for d in DIMENSIONS if agent in DIMENSION_AGENTS[d]]
        out[agent] = {"coverage": {d: {"planned": planned, "run": ran} for d in (dims or own)}}
    return out


def score(profile, done, findings=(), runtime=RUNNING, facts=None, **kw):
    facts = facts_for(done) if facts is None else facts
    return compute_scores(run_with(profile, done, **kw), list(findings), runtime, facts)


def test_perfect_run_adopt():
    s = score("adopt", ALL)
    assert (s["overall"], s["verdict"], s["coverage_pct"], s["gates"], s["caps"]) == (100, "Adopt", 100, [], [])
    assert s["mode"] == "run"


def test_penalties_and_weights():
    findings = [
        finding(id="F-security-001", severity="high", status="confirmed"),
        finding(id="F-security-002", severity="medium", status="confirmed"),
        finding(id="F-security-003", severity="critical", status="dropped"),
    ]
    s = score("adopt", ALL, findings)
    assert s["dimensions"]["security"]["score"] == 72
    assert s["dimensions"]["security"]["findings"] == ["F-security-001", "F-security-002"]
    assert s["overall"] == 93  # 0.25 * 72 + 0.75 * 100
    assert s["counts"]["dropped"] == 1


# --------------------------------------------------------------------------- coverage comes from checks run, not attendance


def test_an_agent_that_returned_without_facts_earns_no_coverage_and_caps_the_verdict():
    s = score("adopt", ALL, facts=facts_for([a for a in ALL if a != "perf-agent"]))
    assert s["dimensions"]["performance"]["covered"] is False
    assert s["coverage_pct"] < 100
    assert any("perf-agent" in c for c in s["caps"])
    assert s["verdict"] in ("Trial", "Assess", "Hold")


def test_partial_checks_scale_the_dimensions_weight():
    facts = facts_for(ALL)
    facts["perf-agent"]["coverage"]["performance"] = {"planned": 4, "run": 1}
    s = score("adopt", ALL, facts=facts)
    assert s["dimensions"]["performance"]["coverage"] == 0.25
    assert s["coverage_pct"] == 96  # performance (weight .05) counts a quarter: 100 - 5 + 1.25 = 96.25
    assert s["dimensions"]["performance"]["checks"] == {"planned": 4, "run": 1}


def test_zero_checks_run_means_not_covered_even_if_agent_is_done():
    facts = facts_for(ALL)
    facts["functional-tester"]["coverage"]["reliability"] = {"planned": 3, "run": 0}
    facts["perf-agent"]["coverage"]["reliability"] = {"planned": 2, "run": 0}
    s = score("adopt", ALL, facts=facts)
    assert s["dimensions"]["reliability"]["covered"] is False and s["dimensions"]["reliability"]["score"] is None


def test_runner_agent_alone_does_not_cover_functional():
    s = score("adopt", ["runner-agent", "security-agent"])
    assert s["dimensions"]["functional"]["covered"] is False
    assert s["dimensions"]["operability"]["covered"] is True


def test_run_cannot_exceed_planned():
    facts = facts_for(["security-agent"], planned=2, ran=9)
    assert score("adopt", ["security-agent"], facts=facts)["dimensions"]["security"]["checks"] == {"planned": 2, "run": 2}


def test_malformed_coverage_entries_are_ignored_not_trusted():
    facts = {"security-agent": {"coverage": {"security": {"planned": "9", "run": True}, "bogus": {"planned": 1, "run": 1}}}}
    s = score("adopt", ["security-agent"], facts=facts)
    assert s["dimensions"]["security"]["covered"] is False
    assert any("security-agent" in c for c in s["caps"])


def test_untested_items_are_collected():
    facts = facts_for(["functional-tester"])
    facts["functional-tester"]["untested"] = [{"what": "claim C-003", "why": "needs OPENAI_API_KEY"}]
    assert score("adopt", ["functional-tester"], facts=facts)["untested"] == [
        {"agent": "functional-tester", "what": "claim C-003", "why": "needs OPENAI_API_KEY"}]


def test_uncovered_dimensions_are_na_and_weights_renormalize():
    findings = [finding(id="F-security-001", status="confirmed"), finding(id="F-security-002", status="confirmed")]
    s = score("radar", ["security-agent"], findings, squad=["security-agent"])
    assert s["dimensions"]["performance"]["score"] is None
    assert s["coverage_pct"] == 10
    assert s["overall"] == 60
    assert s["verdict"] == "Assess (low confidence)"


def test_zero_coverage_is_insufficient_data():
    s = score("adopt", [], runtime={})
    assert (s["overall"], s["verdict"], s["coverage_pct"]) == (None, "Insufficient data", 0)


def test_confirmed_finding_without_a_coverage_report_counts_at_a_floor():
    s = score("adopt", [], [finding(severity="low", status="confirmed")], runtime={})
    d = s["dimensions"]["security"]
    assert d["covered"] is True and d["coverage"] == 0.25 and d["score"] == 97


# --------------------------------------------------------------------------- gates and caps


def test_critical_security_gate_caps_verdict():
    s = score("adopt", ALL, [finding(severity="critical", status="confirmed")])
    assert s["overall"] == 90
    assert s["verdict"] == "Hold"
    assert s["gates"] == ["confirmed critical security finding"]


@pytest.mark.parametrize("dimension", ["functional", "reliability", "performance", "operability", "maintainability", "viability"])
def test_any_weighted_dimension_critical_gates_adopt(dimension):
    f = finding(id="F-x-001", dimension=dimension, severity="critical", status="confirmed")
    s = score("adopt", ALL, [f])
    assert s["verdict"] == "Hold" and s["gates"] == [f"confirmed critical {dimension} finding"]


def test_critical_in_a_zero_weight_dimension_does_not_gate():
    assert WEIGHTS["audit"]["viability"] == 0
    f = finding(id="F-x-001", dimension="viability", severity="critical", status="confirmed")
    assert score("audit", ALL, [f])["gates"] == []


def test_license_gate_only_for_adopt():
    lic = finding(id="F-viability-001", agent="viability-agent", dimension="compliance", severity="critical", status="confirmed")
    assert score("adopt", ALL, [lic])["verdict"] == "Hold"
    assert score("radar", ALL, [lic])["gates"] == []


def test_not_run_gate_applies_to_adopt_and_audit_only():
    done = ["runner-agent", "security-agent", "architecture-agent", "viability-agent"]
    assert score("audit", done, runtime={"status": "failed"})["verdict"] == "Not ready"
    assert score("radar", done, runtime={"status": "failed"})["gates"] == []


@pytest.mark.parametrize("runtime", [{}, {"status": "failed"}])
def test_missing_or_failed_runtime_gates_adopt(runtime):
    s = score("adopt", ["runner-agent", "security-agent", "architecture-agent", "viability-agent"], runtime=runtime)
    assert s["verdict"] == "Hold" and s["gates"][0].startswith("project was not built and run") and s["mode"] == "not-run"


def test_static_only_is_labelled_as_a_chosen_static_review_not_a_build_failure():
    s = score("adopt", ["security-agent", "architecture-agent", "viability-agent"], runtime={"status": "static-only"})
    assert s["mode"] == "static-only" and s["verdict"] == "Hold"
    assert s["gates"] == ["static review only: the project was not run (runtime status: static-only)"]


def test_a_failed_agent_caps_the_verdict_at_the_second_band():
    done = [a for a in ALL if a not in ("perf-agent", "suite-runner")]
    s = score("adopt", done, failed=["perf-agent", "suite-runner"])
    assert s["overall"] == 100 and s["verdict"] == "Trial"
    assert s["caps"] == ["agent(s) failed: perf-agent, suite-runner"]
    assert score("audit", done, failed=["perf-agent"])["verdict"] == "Needs work"


def test_a_squad_agent_that_never_finished_caps_too():
    s = score("adopt", [a for a in ALL if a != "perf-agent"], squad=["perf-agent", "security-agent"])
    assert any("did not finish: perf-agent" in c for c in s["caps"])
    assert not any("skipped" in c for c in score("adopt", ALL, squad=["perf-agent"], skipped=["suite-runner"])["caps"])


def test_the_degraded_run_that_used_to_score_adopt_no_longer_does():
    """Shape of a real run: perf-agent and suite-runner failed, reliability reported nothing, 8 of 11 claims untested."""
    done = ["runner-agent", "functional-tester", "security-agent", "architecture-agent", "viability-agent"]
    facts = facts_for(done)
    facts["functional-tester"]["coverage"] = {"functional": {"planned": 11, "run": 3}, "reliability": {"planned": 4, "run": 0}}
    s = score("adopt", done, facts=facts, failed=["perf-agent", "suite-runner"])
    assert s["dimensions"]["reliability"]["covered"] is False
    assert s["dimensions"]["functional"]["coverage"] < 0.3
    assert s["verdict"] != "Adopt" and s["coverage_pct"] < 85


# --------------------------------------------------------------------------- rounding and invariants


@pytest.mark.parametrize("x, expected", [(64.5, 65), (0.5, 1), (64.4, 64), (2.5, 3)])
def test_half_up_rounding(x, expected):
    assert half_up(x) == expected


@pytest.mark.parametrize("profile", WEIGHTS)
def test_profile_weights_sum_to_one(profile):
    assert sum(WEIGHTS[profile].values()) == pytest.approx(1.0)
    assert set(WEIGHTS[profile]) == set(DIMENSIONS)


@pytest.mark.parametrize("profile", BANDS)
def test_band_boundaries(profile):
    thresholds = [t for t, _ in BANDS[profile]]
    assert thresholds == sorted(thresholds, reverse=True) and thresholds[-1] == 0
    from e2eat.score import verdict_for

    for threshold, label in BANDS[profile]:
        assert verdict_for(profile, threshold) == label
        if threshold:
            assert verdict_for(profile, threshold - 1) != label


# --------------------------------------------------------------------------- score_run fails closed


def _facts_file(run_dir, agent, **coverage):
    write_json(run_dir / "blackboard" / "facts" / f"{agent}.json",
               {"coverage": {d: {"planned": 2, "run": 2} for d in DIMENSIONS if agent in DIMENSION_AGENTS[d]}} | coverage)


def test_score_run_writes_valid_scores(run_dir):
    set_agent(run_dir, "security-agent", "done")
    _facts_file(run_dir, "security-agent")
    add_finding(run_dir, status="confirmed")
    update_finding(run_dir, "F-security-001", status="confirmed")
    scores = score_run(run_dir)
    assert read_json(run_dir / "scores.json") == scores
    assert scores["dimensions"]["security"]["coverage"] == 1.0
    assert validate_run(run_dir) == []


def test_score_run_refuses_open_or_disputed_findings(run_dir):
    add_finding(run_dir, id="F-security-001", severity="critical")
    add_finding(run_dir, id="F-security-002")
    update_finding(run_dir, "F-security-002", status="disputed", challenge="Prove it with evidence.")
    with pytest.raises(ValueError, match="still open or disputed"):
        score_run(run_dir)
    assert not (run_dir / "scores.json").exists()


def test_score_run_refuses_a_corrupt_ledger(run_dir):
    add_finding(run_dir)
    (run_dir / "finding-status.json").write_text("{oops")
    with pytest.raises(ValueError, match="not valid JSON"):
        score_run(run_dir)


def test_score_run_refuses_malformed_runtime_facts(run_dir):
    (run_dir / "blackboard" / "facts" / "runtime.json").write_text("[1, 2]")
    with pytest.raises(ValueError, match="JSON dict"):
        score_run(run_dir)


def test_score_run_refuses_duplicate_ids_and_unknown_enums(run_dir):
    add_finding(run_dir, id="F-security-001")
    write_json(run_dir / "blackboard" / "findings" / "F-security-002.json", finding(id="F-security-001"))
    update_finding(run_dir, "F-security-001", status="confirmed")
    with pytest.raises(ValueError, match="duplicate finding ids"):
        score_run(run_dir)
    (run_dir / "blackboard" / "findings" / "F-security-002.json").unlink()
    write_json(run_dir / "blackboard" / "findings" / "F-security-001.json", finding(id="F-security-001", severity="CRITICAL"))
    with pytest.raises(ValueError, match="unknown severity"):
        score_run(run_dir)


def test_invalid_agent_facts_are_ignored_and_reported(run_dir):
    set_agent(run_dir, "perf-agent", "done")
    write_json(run_dir / "blackboard" / "facts" / "perf-agent.json", {"p50_ms": 0})
    scores = score_run(run_dir)
    assert scores["dimensions"]["performance"]["covered"] is False
    assert any("perf-agent" in p for p in scores["problems"]) and any("perf-agent" in c for c in scores["caps"])
