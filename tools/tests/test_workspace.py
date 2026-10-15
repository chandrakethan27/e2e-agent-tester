import pytest

from e2eat.workspace import BUDGETS, PHASES, init_run, load_run, resume_phase, set_agent, set_phase


def test_init_run_creates_layout(run_dir):
    assert run_dir.name == "my-sample-repo-20261015-093000"
    for sub in ("facts", "findings", "messages", "evidence", "invalid"):
        assert (run_dir / "blackboard" / sub).is_dir()
    assert (run_dir / "repo" / "src" / "app.py").exists()
    run = load_run(run_dir)
    assert (run["profile"], run["depth"]) == ("adopt", "quick")
    assert run["budgets"] == BUDGETS["quick"]
    assert run["phases"] == {p: "pending" for p in PHASES}


def test_init_run_rejects_bad_profile(tmp_path, sample_repo):
    with pytest.raises(ValueError, match="profile"):
        init_run(str(sample_repo), "yolo", "quick", tmp_path / "runs")


def test_init_run_cleans_up_when_fetch_fails(tmp_path, sample_repo):
    def boom(source, dest):
        raise OSError("network down")

    with pytest.raises(OSError):
        init_run(str(sample_repo), "adopt", "quick", tmp_path / "runs", fetch=boom)
    assert list((tmp_path / "runs").iterdir()) == []


def test_init_run_records_dropped_symlinks(tmp_path, sample_repo):
    (sample_repo / "leak").symlink_to("/etc/hosts")
    run_dir = init_run(str(sample_repo), "radar", "deep", tmp_path / "runs")
    assert not (run_dir / "repo" / "leak").is_symlink()
    assert load_run(run_dir)["notes"] == ["removed symlink escaping repo: leak"]


def test_phase_and_agent_updates(run_dir):
    set_phase(run_dir, "intake", "done")
    set_agent(run_dir, "recon-agent", "running", agent_id="abc123")
    set_agent(run_dir, "recon-agent", "done", note="ok")
    run = load_run(run_dir)
    assert run["phases"]["intake"] == "done"
    assert run["agents"]["recon-agent"]["status"] == "done"
    assert run["agents"]["recon-agent"]["agent_id"] == "abc123"
    assert resume_phase(run) == "build"


def test_set_phase_rejects_unknown_status(run_dir):
    with pytest.raises(ValueError):
        set_phase(run_dir, "intake", "exploded")
