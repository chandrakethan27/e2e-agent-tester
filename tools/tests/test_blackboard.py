import json

import pytest

from e2eat.blackboard import (
    apply_crossexam,
    challengeable,
    finalize_findings,
    load_findings,
    next_finding_id,
    next_message_id,
    update_finding,
)
from e2eat.cli import main
from helpers import add_finding, finding, write_json


def test_next_ids(run_dir):
    assert next_finding_id(run_dir, "security-agent") == "F-security-001"
    add_finding(run_dir, id="F-security-007")
    assert next_finding_id(run_dir, "security-agent") == "F-security-008"
    assert next_finding_id(run_dir, "functional-tester") == "F-functional-tester-001"
    assert next_message_id(run_dir, "perf-agent") == "Q-perf-001"


def test_next_id_skips_quarantined_numbers(run_dir):
    write_json(run_dir / "blackboard/invalid/F-security-003.json", {})
    assert next_finding_id(run_dir, "security-agent") == "F-security-004"


def test_challengeable_picks_severe_or_unsure():
    findings = [
        finding(id="F-a-001", severity="low", confidence=0.9),
        finding(id="F-a-002", severity="critical"),
        finding(id="F-a-003", severity="medium", confidence=0.4),
        finding(id="F-a-004", severity="high", status="confirmed"),
    ]
    assert [f["id"] for f in challengeable(findings, limit=10)] == ["F-a-002", "F-a-003"]
    assert [f["id"] for f in challengeable(findings, limit=1)] == ["F-a-002"]


def test_update_finding_guards(run_dir):
    with pytest.raises(ValueError):
        update_finding(run_dir, "F-x-001", status="confirmed")
    with pytest.raises(ValueError):
        update_finding(run_dir, "../run", status="confirmed")
    add_finding(run_dir)
    with pytest.raises(ValueError):
        update_finding(run_dir, "F-security-001", status="maybe")


def test_crossexam_round_trip(run_dir):
    add_finding(run_dir, id="F-security-001")
    add_finding(run_dir, id="F-security-002", severity="critical")
    add_finding(run_dir, id="F-security-003", severity="low")
    facts = run_dir / "blackboard/facts"
    write_json(facts / "skeptic-challenges.json", {"challenges": [
        {"finding_id": "F-security-001", "challenge": "Evidence shows a parameterized query."},
        {"finding_id": "F-security-002", "challenge": "No repro against the running app."},
        {"finding_id": "F-nope-001", "challenge": "Refers to a finding that does not exist."},
    ]})
    assert apply_crossexam(run_dir) == {"disputed": 2, "confirmed": 0, "dropped": 0, "unknown": 1}
    update_finding(run_dir, "F-security-002", rebuttal="Added transcript repro-002.")
    write_json(facts / "skeptic-rulings.json", {"rulings": [
        {"finding_id": "F-security-001", "ruling": "dropped", "reason": "false positive"},
    ]})
    apply_crossexam(run_dir)
    assert finalize_findings(run_dir) == {"confirmed": 2, "dropped": 0}
    statuses = {f["id"]: f["status"] for f in load_findings(run_dir)}
    assert statuses == {"F-security-001": "dropped", "F-security-002": "confirmed", "F-security-003": "confirmed"}


def test_finalize_drops_unanswered_disputes(run_dir):
    add_finding(run_dir)
    add_finding(run_dir, id="F-security-002", rebuttal="ok", conceded=True)
    update_finding(run_dir, "F-security-001", status="disputed", challenge="Prove it with a transcript.")
    update_finding(run_dir, "F-security-002", status="disputed", challenge="Prove it.")
    assert finalize_findings(run_dir) == {"confirmed": 0, "dropped": 2}


def test_cli_findings_and_status(run_dir, capsys):
    add_finding(run_dir)
    assert main(["findings", str(run_dir), "--challengeable"]) == 0
    assert [f["id"] for f in json.loads(capsys.readouterr().out)] == ["F-security-001"]
    assert main(["next-id", str(run_dir), "perf-agent", "--message"]) == 0
    assert json.loads(capsys.readouterr().out) == {"id": "Q-perf-001"}
    assert main(["status", str(run_dir)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["findings"]["by_status"] == {"open": 1}
    assert status["phases"]["intake"] == "pending"


@pytest.mark.parametrize("challenges", [[], {"challenges": [{"challenge": "missing the finding id here"}]}])
def test_malformed_skeptic_files_are_rejected_before_any_change(run_dir, challenges):
    add_finding(run_dir)
    write_json(run_dir / "blackboard/facts/skeptic-challenges.json", challenges)
    with pytest.raises(ValueError, match="skeptic-challenges"):
        apply_crossexam(run_dir)
    assert load_findings(run_dir)[0]["status"] == "open"


def test_invalid_ruling_value_changes_nothing(run_dir):
    add_finding(run_dir)
    write_json(run_dir / "blackboard/facts/skeptic-rulings.json",
               {"rulings": [{"finding_id": "F-security-001", "ruling": "open", "reason": "nope"}]})
    with pytest.raises(ValueError, match="skeptic-rulings"):
        apply_crossexam(run_dir)
    assert load_findings(run_dir)[0]["status"] == "open"


def test_agents_cannot_self_confirm(run_dir):
    add_finding(run_dir, status="confirmed", severity="critical")
    [f] = load_findings(run_dir)
    assert f["status"] == "open"
    assert [x["id"] for x in challengeable(load_findings(run_dir), 5)] == ["F-security-001"]
    update_finding(run_dir, "F-security-001", status="dropped", ruling_reason="false positive")
    assert load_findings(run_dir)[0]["status"] == "dropped"
