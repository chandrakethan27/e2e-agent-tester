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
    assert apply_crossexam(run_dir) == {"disputed": 2, "confirmed": 0, "dropped": 0, "unknown": 1, "ignored": 0}
    update_finding(run_dir, "F-security-002", rebuttal="Added transcript repro-002.")
    write_json(facts / "skeptic-rulings.json", {"rulings": [
        {"finding_id": "F-security-001", "ruling": "dropped", "reason": "false positive"},
        {"finding_id": "F-security-002", "ruling": "confirmed", "reason": "the rebuttal transcript reproduces it"},
    ]})
    apply_crossexam(run_dir)
    assert finalize_findings(run_dir) == {"confirmed": 1, "dropped": 0, "unreviewed": 0}
    statuses = {f["id"]: f["status"] for f in load_findings(run_dir)}
    assert statuses == {"F-security-001": "dropped", "F-security-002": "confirmed", "F-security-003": "confirmed"}


def test_finalize_drops_unanswered_disputes(run_dir):
    add_finding(run_dir)
    add_finding(run_dir, id="F-security-002", rebuttal="ok", conceded=True)
    update_finding(run_dir, "F-security-001", status="disputed", challenge="Prove it with a transcript.")
    update_finding(run_dir, "F-security-002", status="disputed", challenge="Prove it.")
    with pytest.raises(ValueError, match="no skeptic ruling"):
        finalize_findings(run_dir)
    assert finalize_findings(run_dir, unruled="keep") == {"confirmed": 0, "dropped": 2, "unreviewed": 0}


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


def test_challenge_boundary_is_inclusive():
    findings = [finding(id="F-a-001", severity="low", confidence=0.6), finding(id="F-a-002", severity="low", confidence=0.61)]
    assert [f["id"] for f in challengeable(findings, 5)] == ["F-a-001"]


def test_a_ruling_only_applies_to_a_challenged_finding(run_dir):
    add_finding(run_dir, id="F-security-001", severity="critical")
    add_finding(run_dir, id="F-security-002", severity="critical")
    facts = run_dir / "blackboard/facts"
    write_json(facts / "skeptic-challenges.json", {"challenges": [{"finding_id": "F-security-001", "challenge": "Show the exploit working."}]})
    write_json(facts / "skeptic-rulings.json", {"rulings": [
        {"finding_id": "F-security-001", "ruling": "dropped", "reason": "no exploit"},
        {"finding_id": "F-security-002", "ruling": "dropped", "reason": "never challenged"}]})
    assert apply_crossexam(run_dir) == {"disputed": 1, "confirmed": 0, "dropped": 1, "unknown": 0, "ignored": 1}
    assert {f["id"]: f["status"] for f in load_findings(run_dir)} == {"F-security-001": "dropped", "F-security-002": "open"}
    assert apply_crossexam(run_dir)["dropped"] == 0  # repeating changes nothing


def test_finalize_settles_unruled_disputes_only_when_told_to(run_dir):
    add_finding(run_dir, id="F-security-001", rebuttal="see repro", severity="critical")
    add_finding(run_dir, id="F-security-002", severity="critical")
    for fid in ("F-security-001", "F-security-002"):
        update_finding(run_dir, fid, status="disputed", challenge="Prove it with evidence.")
    with pytest.raises(ValueError, match="2 challenged"):
        finalize_findings(run_dir)
    assert {f["status"] for f in load_findings(run_dir)} == {"disputed"}  # the refusal changed nothing
    assert finalize_findings(run_dir, unruled="keep") == {"confirmed": 1, "dropped": 1, "unreviewed": 1}
    statuses = {f["id"]: f for f in load_findings(run_dir)}
    assert statuses["F-security-001"]["status"] == "confirmed" and statuses["F-security-001"]["reviewed"] is False
    assert statuses["F-security-002"]["status"] == "dropped"


def test_finalize_drop_mode_drops_even_rebutted_findings(run_dir):
    add_finding(run_dir, rebuttal="see repro")
    update_finding(run_dir, "F-security-001", status="disputed", challenge="Prove it with evidence.")
    assert finalize_findings(run_dir, unruled="drop")["dropped"] == 1


def test_finalize_flags_eligible_findings_nobody_challenged_and_freezes_severity(run_dir):
    add_finding(run_dir, id="F-security-001", severity="critical")  # eligible, but the skeptic never looked at it
    add_finding(run_dir, id="F-security-002", severity="low", confidence=0.9)  # not eligible: reviewed does not apply
    assert finalize_findings(run_dir) == {"confirmed": 2, "dropped": 0, "unreviewed": 1}
    by_id = {f["id"]: f for f in load_findings(run_dir)}
    assert by_id["F-security-001"]["reviewed"] is False and "reviewed" not in by_id["F-security-002"]
    # an agent editing its own file afterwards cannot move the score
    write_json(run_dir / "blackboard/findings/F-security-001.json", finding(id="F-security-001", severity="info", dimension="viability"))
    after = {f["id"]: f for f in load_findings(run_dir)}["F-security-001"]
    assert (after["severity"], after["dimension"], after["status"]) == ("critical", "security", "confirmed")


def test_finalize_rejects_unknown_mode(run_dir):
    with pytest.raises(ValueError):
        finalize_findings(run_dir, unruled="maybe")
