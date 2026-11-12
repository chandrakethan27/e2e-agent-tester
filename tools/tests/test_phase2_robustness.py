"""Regression tests for CLI correctness and robustness: argument order, errors, locking, ids, timings, timeouts."""

import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from e2eat.blackboard import FINDING_STATUSES, SEVERITIES, load_findings, next_finding_id, update_finding
from e2eat.cli import main
from e2eat.jsonio import read_json_strict, run_lock, write_json
from e2eat.sandbox import runner_with_timeout, stale_run_ids, teardown
from e2eat.score import DIMENSIONS
from e2eat.source import drop_escaping_symlinks, fetch_source, parse_source
from e2eat.validate import load_schema, validate_document, validate_run
from e2eat.workspace import AGENT_NAMES, load_run, set_agent, set_phase
from helpers import add_finding, finding

RID = "o-r-20261015-093000"


# --------------------------------------------------------------------------- sandbox run argument order


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake_execute(cmd, log_path=None, timeout=None):
        calls.append(list(cmd))
        return {"exit_code": 0, "tail": "", "log": None}

    monkeypatch.setattr("e2eat.cli.sandbox_cmds.execute", fake_execute)
    return calls


@pytest.mark.parametrize("options_first", [False, True])
def test_sandbox_run_accepts_run_dir_before_or_after_options(run_dir, captured, options_first):
    run_id = load_run(run_dir)["run_id"]
    opts = ["--name", "app", "--image", "alpine", "-p", "5000"]
    argv = ["sandbox", "run", *opts, str(run_dir)] if options_first else ["sandbox", "run", str(run_dir), *opts]
    assert main([*argv, "--", "sh", "-c", "echo hi"]) == 0
    cmd = captured[0]
    assert cmd[cmd.index("alpine"):] == ["alpine", "sh", "-c", "echo hi"]
    assert f"e2eat-{run_id}-app" in cmd and "127.0.0.1:5000:5000" in cmd


def test_sandbox_run_without_command_still_works(run_dir, captured):
    assert main(["sandbox", "run", str(run_dir), "--name", "app", "--image", "alpine"]) == 0
    assert captured[0][-1] == "alpine"


def test_sandbox_run_refuses_option_smuggled_through_image(run_dir, captured, capsys):
    assert main(["sandbox", "run", str(run_dir), "--name", "app", "--image=--privileged"]) == 2
    assert "bad image reference" in capsys.readouterr().err
    assert captured == []


def test_git_pathspec_after_double_dash_is_preserved(run_dir, monkeypatch):
    seen = []
    monkeypatch.setattr("e2eat.cli.git_cmds.run_git", lambda d, a: seen.append(list(a)) or {"stdout": "", "stderr": "", "exit_code": 0})
    main(["git", str(run_dir), "log", "-1", "--", "README.md"])
    main(["git", str(run_dir), "--", "log", "-1"])
    assert seen == [["log", "-1", "--", "README.md"], ["log", "-1"]]


# --------------------------------------------------------------------------- errors and exit codes


def test_unexpected_errors_become_one_line_not_a_traceback(run_dir, monkeypatch, capsys):
    monkeypatch.setattr("e2eat.cli.run_cmds.load_run", lambda d: (_ for _ in ()).throw(KeyError("phases")))
    assert main(["phase", str(run_dir), "intake", "running"]) in (2, 70)
    assert "Traceback" not in capsys.readouterr().err


def test_timeouts_are_reported_not_raised(run_dir, monkeypatch, capsys):
    def boom(args):
        raise subprocess.TimeoutExpired(["docker", "info"], 5)

    monkeypatch.setattr("e2eat.cli.sandbox_cmds._names", boom)
    assert main(["sandbox", "names", str(run_dir)]) == 2
    assert "timed out" in capsys.readouterr().err


def test_agent_names_are_validated(run_dir, capsys):
    with pytest.raises(SystemExit):
        main(["agent", str(run_dir), "recon", "done"])
    with pytest.raises(ValueError, match="unknown agent"):
        set_agent(run_dir, "recon", "done")


def test_agent_names_match_the_agent_definitions():
    defined = {p.stem for p in (Path(__file__).resolve().parents[2] / ".claude" / "agents").glob("*.md")}
    assert set(AGENT_NAMES) == defined


# --------------------------------------------------------------------------- strict json, locking, ids


def test_strict_read_distinguishes_missing_from_malformed(tmp_path):
    assert read_json_strict(tmp_path / "none.json", {"d": 1}) == {"d": 1}
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_json_strict(tmp_path / "bad.json", {})
    (tmp_path / "list.json").write_text("[1]")
    with pytest.raises(ValueError, match="must hold a JSON dict"):
        read_json_strict(tmp_path / "list.json", {}, dict)
    with pytest.raises(FileNotFoundError):
        read_json_strict(tmp_path / "none.json")


def test_corrupt_ledger_stops_scoring_instead_of_resetting_findings(run_dir):
    add_finding(run_dir, id="F-security-001", severity="critical")
    update_finding(run_dir, "F-security-001", status="confirmed")
    (run_dir / "finding-status.json").write_text("{truncated")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_findings(run_dir)


def test_concurrent_writes_never_lose_updates_or_corrupt_files(run_dir):
    def work(i):
        set_agent(run_dir, AGENT_NAMES[i % len(AGENT_NAMES)], "running", note=f"n{i}")

    threads = [threading.Thread(target=work, args=(i,)) for i in range(24)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    run = load_run(run_dir)
    assert set(run["agents"]) == set(AGENT_NAMES)
    leftovers = [p.name for p in run_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_concurrent_ledger_updates_keep_every_finding(run_dir):
    ids = [add_finding(run_dir, id=f"F-security-{n:03d}") for n in range(1, 9)]
    ids = [f"F-security-{n:03d}" for n in range(1, 9)]
    threads = [threading.Thread(target=update_finding, args=(run_dir, i), kwargs={"status": "confirmed"}) for i in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert {f["id"]: f["status"] for f in load_findings(run_dir)} == {i: "confirmed" for i in ids}


def test_next_id_reserves_numbers(run_dir):
    first = next_finding_id(run_dir, "security-agent")
    second = next_finding_id(run_dir, "security-agent")
    assert (first, second) == ("F-security-001", "F-security-002")
    add_finding(run_dir, id="F-security-009")
    assert next_finding_id(run_dir, "security-agent") == "F-security-010"


def test_next_id_is_unique_under_concurrency(run_dir):
    got = []
    threads = [threading.Thread(target=lambda: got.append(next_finding_id(run_dir, "perf-agent"))) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(got)) == 12


def test_run_lock_is_exclusive(run_dir):
    order = []

    def second():
        with run_lock(run_dir):
            order.append("second")

    with run_lock(run_dir):
        t = threading.Thread(target=second)
        t.start()
        t.join(timeout=0.3)
        order.append("first")
    t.join()
    assert order == ["first", "second"]


# --------------------------------------------------------------------------- timings and events


def test_phase_and_agent_timings_and_event_log(run_dir):
    set_phase(run_dir, "intake", "running")
    set_agent(run_dir, "recon-agent", "running", agent_id="a1")
    set_agent(run_dir, "recon-agent", "done", note="ok")
    set_phase(run_dir, "intake", "done")
    run = load_run(run_dir)
    assert "started_at" in run["timings"]["intake"] and "finished_at" in run["timings"]["intake"]
    assert "started_at" in run["agents"]["recon-agent"] and "finished_at" in run["agents"]["recon-agent"]
    assert "finished_at" not in run
    set_phase(run_dir, "finalize", "done")
    assert "finished_at" in load_run(run_dir)
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert [(e["kind"], e["name"], e["status"]) for e in events[:4]] == [
        ("phase", "intake", "running"), ("agent", "recon-agent", "running"), ("agent", "recon-agent", "done"), ("phase", "intake", "done")]
    assert events[2]["note"] == "ok"


def test_rerunning_an_agent_clears_its_finish_time(run_dir):
    set_agent(run_dir, "perf-agent", "running")
    set_agent(run_dir, "perf-agent", "done")
    set_agent(run_dir, "perf-agent", "running")
    assert "finished_at" not in load_run(run_dir)["agents"]["perf-agent"]


# --------------------------------------------------------------------------- validation


def test_briefing_and_ledger_have_schemas(run_dir):
    facts = run_dir / "blackboard" / "facts"
    write_json(facts / "briefing.json", {"summary": "x", "plan": ["a"], "cannot_test": []})
    assert validate_run(run_dir) == []
    write_json(facts / "briefing.json", {"summary": "x", "plan": "not a list", "cannot_test": []})
    assert any("briefing.json" in i.path for i in validate_run(run_dir))
    write_json(facts / "briefing.json", {"summary": "x", "plan": [], "cannot_test": []})
    write_json(run_dir / "finding-status.json", {"F-a-001": {"status": "bogus"}})
    assert any("finding-status.json" in i.path for i in validate_run(run_dir))


def test_quarantine_waits_for_files_still_being_written_and_never_overwrites(run_dir):
    bad = run_dir / "blackboard" / "findings" / "F-security-001.json"
    bad.write_text("{half written")
    issues = validate_run(run_dir, quarantine=True, grace_secs=60)
    assert bad.exists() and any("moments ago" in i.message for i in issues)
    validate_run(run_dir, quarantine=True)
    assert not bad.exists()
    bad.write_text("{again")
    validate_run(run_dir, quarantine=True)
    assert sorted(p.name for p in (run_dir / "blackboard" / "invalid").iterdir()) == ["F-security-001.1.json", "F-security-001.json"]


def test_schema_enums_match_the_python_constants():
    finding_schema = load_schema("finding")["properties"]
    assert tuple(finding_schema["severity"]["enum"]) == SEVERITIES
    assert set(finding_schema["dimension"]["enum"]) == set(DIMENSIONS)
    assert set(finding_schema["status"]["enum"]) == set(FINDING_STATUSES)
    assert validate_document({"F-a-001": {"status": "confirmed"}}, "ledger") == []


# --------------------------------------------------------------------------- source


def test_symlink_loops_are_dropped_not_crashed_on(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "loop").symlink_to("loop")
    (repo / "a").symlink_to("b")
    (repo / "b").symlink_to("a")
    (repo / "ok.txt").write_text("x")
    assert drop_escaping_symlinks(repo) == ["a", "loop"]  # b is left as a harmless dangling link once a is gone
    assert (repo / "ok.txt").exists()


def test_clone_timeout_becomes_a_clear_error(tmp_path, monkeypatch):
    def hang(cmd, check=True, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr("e2eat.source.subprocess.run", hang)
    with pytest.raises(ValueError, match="timed out"):
        fetch_source(parse_source("https://github.com/o/r"), tmp_path / "dest")


# --------------------------------------------------------------------------- docker helpers


def _runner(outputs, rc=0):
    calls = []

    def run(cmd):
        calls.append(list(cmd))
        key = " ".join(cmd[:3])
        return subprocess.CompletedProcess(cmd, outputs.get(key + "!") if outputs.get(key + "!") is not None else rc, stdout=outputs.get(key, ""), stderr="boom")

    return run, calls


def test_teardown_reports_failures_instead_of_claiming_success():
    runner, _ = _runner({"docker ps -aq": "c1\n", "docker rm -f": ""}, rc=0)
    ok = teardown(RID, runner=runner)
    assert "errors" not in ok and ok["containers"] == 1

    def failing(cmd):
        return subprocess.CompletedProcess(cmd, 1 if cmd[:3] == ["docker", "rm", "-f"] else 0, stdout="c1\n" if "ps" in cmd else "", stderr="denied")

    bad = teardown(RID, runner=failing)
    assert bad["containers"] == 0 and any("removing containers failed" in e for e in bad["errors"])

    daemon_down = teardown(RID, runner=lambda cmd: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Cannot connect to the Docker daemon"))
    assert any("Cannot connect" in e for e in daemon_down["errors"])


def test_stale_covers_volumes_images_exclusions_and_bad_stamps():
    now = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
    outputs = {
        "docker ps -a": "old-20261015-010000\n",
        "docker volume ls": "vol-20261015-020000\nx-20261399-000000\n",
        "docker image ls": "e2eat/img-20261015-030000\nother/thing\n",
        "docker network ls": "keep-20261015-010000\n",
    }
    runner, _ = _runner(outputs)
    assert stale_run_ids(now=now, runner=runner, exclude={"keep-20261015-010000"}) == [
        "img-20261015-030000", "old-20261015-010000", "vol-20261015-020000"]


def test_runner_turns_timeouts_and_missing_binaries_into_exit_codes():
    assert runner_with_timeout(0.2)(["sleep", "5"]).returncode == 124
    assert runner_with_timeout(5)(["definitely-not-a-binary-xyz"]).returncode == 127


def test_findings_helper_is_still_usable():
    assert finding(id="F-a-001")["id"] == "F-a-001"
