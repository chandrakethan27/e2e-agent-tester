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


def _git(repo, *args):
    import subprocess

    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


def test_init_neutralizes_imported_git_config(tmp_path, sample_repo):
    import subprocess

    _git(sample_repo, "init", "-q")
    _git(sample_repo, "add", "README.md")
    _git(sample_repo, "commit", "-qm", "init")
    marker = tmp_path / "pwned"
    _git(sample_repo, "config", "core.fsmonitor", f"touch {marker}")
    (sample_repo / ".git" / "hooks" / "post-checkout").write_text("#!/bin/sh\ntouch /tmp/x\n")
    run_dir = init_run(str(sample_repo), "adopt", "quick", tmp_path / "runs")
    subprocess.run(["git", "-C", str(run_dir / "repo"), "ls-files"], capture_output=True)
    assert not marker.exists()
    assert not (run_dir / "repo" / ".git" / "hooks").exists()
    assert any(".git" in note for note in load_run(run_dir)["notes"])


def test_init_drops_gitdir_redirect_file(tmp_path, sample_repo):
    (sample_repo / ".git").write_text("gitdir: /etc\n")
    run_dir = init_run(str(sample_repo), "adopt", "quick", tmp_path / "runs")
    assert not (run_dir / "repo" / ".git").exists()


def test_init_refuses_source_containing_runs_root(tmp_path, sample_repo):
    with pytest.raises(ValueError, match="runs folder"):
        init_run(str(sample_repo), "adopt", "quick", sample_repo / "runs")


def test_init_stores_source_without_credentials(tmp_path):
    def fake_fetch(source, dest):
        dest.mkdir(parents=True)

    run_dir = init_run("https://user:tok@git.example.com/a/b.git", "adopt", "quick", tmp_path / "runs", fetch=fake_fetch)
    assert "tok" not in (run_dir / "run.json").read_text()
