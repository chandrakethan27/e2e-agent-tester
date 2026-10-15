import pytest

from e2eat.squad import plan_squad, select_squad
from e2eat.workspace import load_run
from helpers import write_json

FULL = ["functional-tester", "suite-runner", "perf-agent", "security-agent", "architecture-agent", "viability-agent"]


def test_web_app_running_gets_full_squad():
    assert select_squad("web-app", "running", "standard") == (FULL, {})


def test_failed_runtime_keeps_static_agents_only():
    squad, skipped = select_squad("api-service", "failed", "quick")
    assert squad == ["security-agent", "architecture-agent", "viability-agent"]
    assert skipped["functional-tester"] == "runtime status is failed"


def test_library_perf_only_when_deep():
    assert "perf-agent" not in select_squad("library", "running", "standard")[0]
    assert "perf-agent" in select_squad("library", "running", "deep")[0]


def test_unknown_type_rejected():
    with pytest.raises(ValueError):
        select_squad("spaceship", "running", "quick")


def test_plan_squad_updates_run(run_dir):
    write_json(run_dir / "blackboard/facts/recon.json", {"project_type": "cli"})
    write_json(run_dir / "blackboard/facts/runtime.json", {"status": "running"})
    result = plan_squad(run_dir)
    assert load_run(run_dir)["squad"] == result["squad"] == FULL


def test_plan_squad_without_runtime_facts(run_dir):
    write_json(run_dir / "blackboard/facts/recon.json", {"project_type": "web-app"})
    result = plan_squad(run_dir)
    assert result["skipped"]["perf-agent"] == "runtime status is missing"
    assert load_run(run_dir)["agents"]["perf-agent"]["status"] == "skipped"
