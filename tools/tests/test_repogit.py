import subprocess

import pytest

from e2eat.repogit import run_git
from e2eat.workspace import init_run


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


@pytest.fixture
def git_run(tmp_path, sample_repo):
    _git(sample_repo, "init", "-q")
    _git(sample_repo, "add", "-A")
    _git(sample_repo, "commit", "-qm", "init")
    return init_run(str(sample_repo), "adopt", "quick", tmp_path / "runs")


def test_run_git_lists_files_and_ignores_planted_fsmonitor(tmp_path, git_run):
    marker = tmp_path / "pwned"
    _git(git_run / "repo", "config", "core.fsmonitor", f"touch {marker}")  # planted after init, e.g. by a container
    result = run_git(git_run, ["ls-files"])
    assert result["exit_code"] == 0 and "README.md" in result["stdout"]
    assert not marker.exists()


def test_run_git_rejects_unsafe_subcommands_and_options(git_run):
    for args in (["config", "core.x", "y"], ["log", "--output=/tmp/x"], ["log", "--ext-diff"], []):
        with pytest.raises(ValueError):
            run_git(git_run, args)


def test_run_git_without_history_never_reads_the_tool_repo(run_dir):
    result = run_git(run_dir, ["log", "-1"])
    assert result == {"exit_code": 3, "stdout": "", "stderr": "source has no git history"}
