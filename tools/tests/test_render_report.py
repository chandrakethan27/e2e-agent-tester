"""What the report tells the reader: honest notices, claims ledger, validated top risks, dropped findings."""

import pytest

from e2eat.blackboard import update_finding
from e2eat.render import gather, render_run
from e2eat.render import testing_notice as notice_for
from helpers import add_finding, write_json

FACTS = "blackboard/facts"
RUNNING = {"status": "running", "strategy_used": "repo-docker", "base_urls": [], "internal_urls": [], "exec_container": None,
           "containers": [], "network": None, "health": {"ok": True}, "logs": []}


def html(run_dir):
    render_run(run_dir)
    return (run_dir / "report.html").read_text(encoding="utf-8")


def setup_run(run_dir, **scores):
    write_json(run_dir / FACTS / "runtime.json", RUNNING)
    write_json(run_dir / "scores.json", {"profile": "adopt", "overall": 80, "verdict": "Trial", "coverage_pct": 90, "dimensions": {}, "gates": [],
                                          "counts": {}, "caps": []} | scores)


def test_static_only_has_its_own_notice_not_the_failure_wording():
    notice = notice_for({"agents": {}}, {"status": "static-only"})
    assert notice["level"] == "STATIC ONLY" and "At your request" in notice["text"]
    assert notice_for({"agents": {}}, {"status": "failed"})["level"] == "NOT RUN"


def test_caps_alone_produce_a_partial_notice():
    notice = notice_for({"agents": {}}, {"status": "running"}, {"caps": ["agent(s) finished without usable coverage facts: perf-agent"]})
    assert notice["level"] == "PARTIAL" and "perf-agent" in notice["text"]
    assert notice_for({"agents": {}}, {"status": "running"}, {"caps": []}) is None


def test_notice_levels_are_styled_apart(run_dir):
    write_json(run_dir / FACTS / "runtime.json", {**RUNNING, "status": "static-only"})
    page = html(run_dir)
    assert "notice-static-only" in page and ".notice-partial,.notice-static-only{border-left-color:var(--warn)}" in page


def test_caps_gates_and_unreviewed_are_shown(run_dir):
    setup_run(run_dir, gates=["confirmed critical security finding"], caps=["agent(s) failed: perf-agent"], counts={"unreviewed": 2})
    page = html(run_dir)
    assert "Gate: confirmed critical security finding" in page and "Limited: agent(s) failed: perf-agent" in page
    assert "2 confirmed finding(s) were not cross-examined" in page
    assert "Limited: agent(s) failed: perf-agent" in (run_dir / "report.md").read_text()


def test_claims_ledger_defaults_to_untested_never_pass(run_dir):
    write_json(run_dir / FACTS / "recon.json", {"claims": [
        {"id": "C-001", "text": "Handles 1000 req/s", "testable": True},
        {"id": "C-002", "text": "Safe against injection", "testable": True},
        {"id": "C-003", "text": "Works offline", "testable": True}]})
    write_json(run_dir / FACTS / "functional-tester.json", {"claims": [
        {"claim_id": "C-002", "result": "fail", "evidence": ["blackboard/evidence/x.txt", 5], "note": "SQLi"}]})
    ledger = {c["id"]: c["result"] for c in gather(run_dir)["claims"]}
    assert ledger == {"C-001": "untested", "C-002": "fail", "C-003": "untested"}
    page = html(run_dir)
    assert "Claims checked (3)" in page and "Handles 1000 req/s" in page


def test_top_risks_only_name_confirmed_findings(run_dir):
    add_finding(run_dir, id="F-security-001", severity="high", title="Kept finding")
    add_finding(run_dir, id="F-security-002", severity="high", title="Dropped finding", status="open")
    update_finding(run_dir, "F-security-001", status="confirmed")
    update_finding(run_dir, "F-security-002", status="dropped", ruling_reason="false positive: test fixture")
    write_json(run_dir / "report.json", {"top_risks": ["F-security-001", "F-security-002", "F-nope-009"]})
    ctx = gather(run_dir)
    assert ctx["top_risks"] == ["F-security-001"] and ctx["top_risks_removed"] == 2
    page = html(run_dir)
    assert 'href="#F-security-001"' in page and 'href="#F-security-002"' not in page
    assert "2 risk(s) named in the summary did not survive cross-examination" in page


def test_dropped_findings_appear_with_the_skeptics_reason(run_dir):
    add_finding(run_dir, id="F-security-001", title="Looked scary")
    update_finding(run_dir, "F-security-001", status="dropped", ruling_reason="example key from the docs")
    page = html(run_dir)
    assert "Dropped in cross-examination (1)" in page and "example key from the docs" in page
    assert "example key from the docs" in (run_dir / "report.md").read_text()


def test_medium_findings_are_open_and_have_a_visible_marker(run_dir):
    add_finding(run_dir, id="F-security-001", severity="medium")
    update_finding(run_dir, "F-security-001", status="confirmed")
    page = html(run_dir)
    assert 'id="F-security-001" open' in page and "summary::before" in page


def test_unreviewed_findings_are_labelled(run_dir):
    add_finding(run_dir, id="F-security-001", severity="critical")
    from e2eat.blackboard import finalize_findings

    finalize_findings(run_dir)
    assert "· unreviewed" in html(run_dir)


def test_briefing_cannot_test_items_reach_the_coverage_section(run_dir):
    write_json(run_dir / FACTS / "briefing.json", {"summary": "s", "plan": [], "cannot_test": ["Stripe checkout (no key)"]})
    assert "Stripe checkout (no key)" in html(run_dir)


@pytest.mark.parametrize("name", ["scores.json", "report.json", "usecases.json"])
def test_a_malformed_artifact_is_an_error_not_a_blank_section(run_dir, name):
    (run_dir / name).write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        render_run(run_dir)
