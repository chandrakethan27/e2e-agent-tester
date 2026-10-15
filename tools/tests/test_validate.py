import pytest
from jsonschema import Draft202012Validator

from e2eat.validate import SCHEMA_NAMES, load_schema, validate_run
from helpers import add_finding, finding, write_json


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schemas_are_valid_json_schema(name):
    Draft202012Validator.check_schema(load_schema(name))


def test_fresh_run_is_valid(run_dir):
    assert validate_run(run_dir) == []


def test_valid_finding_passes_evidence_check(run_dir):
    add_finding(run_dir)
    assert validate_run(run_dir, check_evidence=True) == []


def test_missing_required_field_reported(run_dir):
    data = finding()
    del data["claim"]
    write_json(run_dir / "blackboard/findings/F-security-001.json", data)
    issues = validate_run(run_dir)
    assert [i.path for i in issues] == ["blackboard/findings/F-security-001.json"]
    assert "'claim' is a required property" in issues[0].message


def test_malformed_json_is_an_issue_not_a_crash(run_dir):
    (run_dir / "blackboard/findings/F-security-001.json").write_text("{not json")
    issues = validate_run(run_dir)
    assert issues and issues[0].message.startswith("invalid JSON")


@pytest.mark.parametrize(
    "ref, problem",
    [
        ("../../etc/passwd", "escapes the run dir"),
        ("/etc/passwd", "relative to the run dir"),
        ("blackboard/evidence/security-agent/nope.txt", "not found"),
    ],
)
def test_evidence_must_exist_inside_run(run_dir, ref, problem):
    add_finding(run_dir, with_evidence=False, evidence=[ref])
    issues = validate_run(run_dir, check_evidence=True)
    assert any(problem in i.message for i in issues)


def test_repo_line_references_are_accepted(run_dir):
    add_finding(run_dir, with_evidence=False, evidence=["repo/src/app.py:1", "repo/README.md#L1-L3"])
    assert validate_run(run_dir, check_evidence=True) == []


def test_id_must_match_file_and_agent(run_dir):
    write_json(run_dir / "blackboard/findings/F-security-002.json", finding(id="F-perf-002"))
    messages = [i.message for i in validate_run(run_dir)]
    assert any("must match file name" in m for m in messages)
    assert any("must start with F-security-" in m for m in messages)


def test_message_id_must_match_sender(run_dir):
    msg = {"id": "Q-perf-001", "from": "functional-tester", "to": "runner-agent", "question": "seed data?", "answer": None, "status": "open"}
    write_json(run_dir / "blackboard/messages/Q-perf-001.json", msg)
    assert any("must start with Q-functional-tester-" in i.message for i in validate_run(run_dir))


def test_quarantine_moves_invalid_findings(run_dir):
    (run_dir / "blackboard/findings/F-security-001.json").write_text("[]")
    validate_run(run_dir, quarantine=True)
    assert not (run_dir / "blackboard/findings/F-security-001.json").exists()
    assert (run_dir / "blackboard/invalid/F-security-001.json").exists()


def test_unknown_schema_name():
    with pytest.raises(ValueError):
        load_schema("nope")
