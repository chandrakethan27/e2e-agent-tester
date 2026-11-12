"""CLI pieces the revised orchestrator relies on."""

import json

import pytest

from e2eat.blackboard import expire_open_messages
from e2eat.cli import main
from e2eat.jsonio import read_json
from e2eat.workspace import load_run, set_phase
from helpers import write_json

RECON = {
    "project_type": "api-service", "secondary_types": [], "languages": ["python"], "frameworks": [], "entrypoints": [],
    "has_dockerfile": False, "has_compose": False, "services_needed": [], "secrets_needed": ["OPENAI_API_KEY", "STRIPE_KEY"],
    "license": {"spdx": "MIT", "file": "LICENSE"}, "repo_health": {}, "claims": [], "run_hints": [], "test_hints": [],
}


def facts(run_dir, name, data):
    write_json(run_dir / "blackboard" / "facts" / name, data)


def out(capsys):
    return json.loads(capsys.readouterr().out)


# ------------------------------------------------------------------ done requires output


def test_done_is_refused_until_the_agents_output_exists_and_is_valid(run_dir, capsys):
    assert main(["agent", str(run_dir), "perf-agent", "done"]) == 1
    assert "perf-agent.json is missing" in out(capsys)["problems"][0]
    assert "perf-agent" not in load_run(run_dir)["agents"]
    facts(run_dir, "perf-agent.json", {"p50_ms": 1})
    assert main(["agent", str(run_dir), "perf-agent", "done"]) == 1
    capsys.readouterr()
    facts(run_dir, "perf-agent.json", {"coverage": {"performance": {"planned": 2, "run": 2}}})
    assert main(["agent", str(run_dir), "perf-agent", "done"]) == 0
    assert load_run(run_dir)["agents"]["perf-agent"]["status"] == "done"


def test_done_can_be_forced_and_failed_never_needs_output(run_dir, capsys):
    assert main(["agent", str(run_dir), "perf-agent", "failed", "--note", "docker died"]) == 0
    assert main(["agent", str(run_dir), "suite-runner", "done", "--force"]) == 0


def test_runner_done_needs_runtime_with_coverage(run_dir, capsys):
    runtime = {"status": "failed", "strategy_used": "none", "base_urls": [], "internal_urls": [], "exec_container": None,
               "containers": [], "network": None, "health": {"ok": False}, "logs": []}
    facts(run_dir, "runtime.json", runtime)
    assert main(["agent", str(run_dir), "runner-agent", "done"]) == 1
    assert "coverage is missing" in out(capsys)["problems"][0]
    facts(run_dir, "runtime.json", runtime | {"coverage": {"operability": {"planned": 4, "run": 0, "blocked": 4}}})
    assert main(["agent", str(run_dir), "runner-agent", "done"]) == 0


def test_recon_and_synthesis_agents_need_their_output_too(run_dir, capsys):
    for agent in ("recon-agent", "use-case-strategist", "report-writer"):
        assert main(["agent", str(run_dir), agent, "done"]) == 1
    capsys.readouterr()
    facts(run_dir, "recon.json", RECON)
    assert main(["agent", str(run_dir), "recon-agent", "done"]) == 0


# ------------------------------------------------------------------ squad preview, static-only, reconfigure


def test_squad_plan_previews_without_touching_run_json(run_dir, capsys):
    facts(run_dir, "recon.json", RECON)
    before = (run_dir / "run.json").read_text()
    assert main(["squad", str(run_dir), "--plan"]) == 0
    plan = out(capsys)
    assert plan["preview"] is True and "functional-tester" in plan["squad"] and plan["skipped"] == {}
    assert (run_dir / "run.json").read_text() == before


def test_plain_squad_with_no_runtime_still_skips_runtime_agents(run_dir, capsys):
    facts(run_dir, "recon.json", RECON)
    assert main(["squad", str(run_dir)]) == 0
    assert set(out(capsys)["skipped"]) == {"functional-tester", "suite-runner", "perf-agent"}


def test_static_only_records_the_choice_and_squad_follows(run_dir, capsys):
    facts(run_dir, "recon.json", RECON)
    assert main(["static-only", str(run_dir)]) == 0
    capsys.readouterr()
    run = load_run(run_dir)
    assert run["phases"]["build"] == "skipped" and run["agents"]["runner-agent"]["status"] == "skipped"
    assert read_json(run_dir / "blackboard/facts/runtime.json")["status"] == "static-only"
    assert main(["validate", str(run_dir)]) == 0
    capsys.readouterr()
    assert main(["squad", str(run_dir)]) == 0
    assert out(capsys)["squad"] == ["security-agent", "architecture-agent", "viability-agent"]


def test_reconfigure_changes_profile_and_depth_before_assess_only(run_dir, capsys):
    assert main(["reconfigure", str(run_dir), "--profile", "audit", "--depth", "deep"]) == 0
    result = out(capsys)
    assert (result["profile"], result["depth"], result["budgets"]["minutes"]) == ("audit", "deep", 90)
    assert load_run(run_dir)["profile"] == "audit"
    set_phase(run_dir, "assess", "running")
    with pytest.raises(SystemExit):
        main(["reconfigure", str(run_dir), "--depth", "huge"])
    assert main(["reconfigure", str(run_dir), "--depth", "quick"]) == 2


# ------------------------------------------------------------------ messages and secrets


def test_unanswered_questions_can_be_expired(run_dir, capsys):
    write_json(run_dir / "blackboard/messages/Q-perf-001.json",
               {"id": "Q-perf-001", "from": "perf-agent", "to": "runner-agent", "question": "Seed 10k rows please", "answer": None, "status": "open"})
    write_json(run_dir / "blackboard/messages/Q-perf-002.json",
               {"id": "Q-perf-002", "from": "perf-agent", "to": "runner-agent", "question": "Another one?", "answer": "done", "status": "answered"})
    assert main(["messages", str(run_dir), "--expire"]) == 0
    assert out(capsys) == {"expired": ["Q-perf-001"]}
    assert main(["messages", str(run_dir), "--status", "expired"]) == 0
    assert [m["id"] for m in out(capsys)] == ["Q-perf-001"]
    assert expire_open_messages(run_dir) == []


@pytest.fixture
def secrets_home(tmp_path, monkeypatch):
    monkeypatch.setenv("E2EAT_HOME", str(tmp_path / "home"))
    path = tmp_path / "keys.env"
    path.write_text("OPENAI_API_KEY=sk-test-1\nUNRELATED=x\n")
    return path


def test_env_check_reports_without_writing_and_honours_the_briefing(run_dir, secrets_home, capsys):
    facts(run_dir, "recon.json", RECON)
    assert main(["sandbox", "env", str(run_dir), "--check", "--secrets", str(secrets_home)]) == 0
    assert out(capsys) == {"env_file": None, "present": ["OPENAI_API_KEY"], "missing": ["STRIPE_KEY"], "withheld": []}
    assert not (secrets_home.parent / "home" / ".secrets.d").exists()
    facts(run_dir, "briefing.json", {"summary": "s", "plan": [], "cannot_test": [], "approved_secrets": ["STRIPE_KEY"]})
    assert main(["sandbox", "env", str(run_dir), "--check", "--secrets", str(secrets_home)]) == 0
    assert out(capsys)["withheld"] == ["OPENAI_API_KEY"]
    assert main(["sandbox", "env", str(run_dir), "--secrets", str(secrets_home)]) == 0
    written = out(capsys)
    assert written["present"] == [] and written["withheld"] == ["OPENAI_API_KEY"]


def test_teardown_active_removes_every_labelled_run(monkeypatch, capsys):
    monkeypatch.setattr("e2eat.cli.sandbox_cmds.labelled_run_ids", lambda: {"b-20261015-010101", "a-20261015-010101"})
    monkeypatch.setattr("e2eat.cli.sandbox_cmds.teardown", lambda rid: {"containers": 1})
    assert main(["sandbox", "teardown-active"]) == 0
    assert out(capsys)["active"] == ["a-20261015-010101", "b-20261015-010101"]
