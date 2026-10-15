import subprocess
from pathlib import Path

import pytest

from e2eat.guard import check_command
from e2eat.web import CONTAINER, IMAGE, build_cmd, open_url, run_cmd, start, stop


def test_run_mounts_only_runs_read_only_on_loopback(tmp_path):
    runs = tmp_path / "runs"
    cmd = run_cmd(runs, 3000, "r-1")
    assert cmd[:3] == ["docker", "run", "-d"]
    assert f"{runs}:/runs:ro" in cmd
    assert "127.0.0.1:3000:3000" in cmd
    assert "no-new-privileges" in " ".join(cmd) and "ALL" in cmd
    assert "DEFAULT_RUN_ID=r-1" in cmd
    assert cmd[-1] == IMAGE
    assert check_command(" ".join(cmd), tmp_path) is None  # the project's own guard accepts it


@pytest.mark.parametrize("port", [0, 70000, -1])
def test_rejects_bad_port(tmp_path, port):
    with pytest.raises(ValueError):
        run_cmd(tmp_path / "runs", port, None)


def test_rejects_unsafe_run_id(tmp_path):
    with pytest.raises(ValueError):
        run_cmd(tmp_path / "runs", 3000, "x;rm -rf /")


def test_url_includes_run_when_given():
    assert open_url(3000, "r-1") == "http://127.0.0.1:3000/?run=r-1"
    assert open_url(3000, None) == "http://127.0.0.1:3000/"


def test_start_builds_replaces_old_container_and_runs(tmp_path):
    calls = []

    def runner(cmd):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "abc123\n", "")

    result = start(tmp_path / "runs", tmp_path / "web", 3000, "r-1", runner=runner)
    assert [c[1] for c in calls] == ["build", "rm", "run"]
    assert calls[1] == ["docker", "rm", "-f", CONTAINER]
    assert result["url"] == "http://127.0.0.1:3000/?run=r-1"


def test_start_stops_when_build_fails(tmp_path):
    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 1 if cmd[1] == "build" else 0, "", "no space left on device")

    with pytest.raises(ValueError, match="no space left"):
        start(tmp_path / "runs", tmp_path / "web", 3000, None, runner=runner)


def test_stop_removes_container():
    calls = []
    stop(runner=lambda cmd: calls.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert calls == [["docker", "rm", "-f", CONTAINER]]


def test_build_labels_image(tmp_path):
    assert build_cmd(Path("web"))[-3:] == ["-t", IMAGE, "web"]
