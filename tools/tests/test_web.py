import subprocess
from pathlib import Path

import pytest

from e2eat.web import CONTAINER, IMAGE, build_cmd, find_free_port, open_url, run_cmd, running_port, start, status, stop, wait_ready


def test_run_mounts_only_runs_read_only_on_loopback(tmp_path):
    runs = tmp_path / "runs"
    cmd = run_cmd(runs, 3000, "r-1")
    assert cmd[:3] == ["docker", "run", "-d"]
    assert f"{runs}:/runs:ro" in cmd
    assert "127.0.0.1:3000:3000" in cmd
    assert "no-new-privileges" in " ".join(cmd) and "ALL" in cmd
    assert "DEFAULT_RUN_ID=r-1" in cmd
    assert cmd[-1] == IMAGE


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

    result = start(tmp_path / "runs", tmp_path / "web", 3000, "r-1", runner=runner, is_free=lambda p: True)
    assert [c[1] for c in calls] == ["ps", "build", "rm", "run"]
    assert calls[2] == ["docker", "rm", "-f", CONTAINER]
    assert result["url"] == "http://127.0.0.1:3000/?run=r-1" and result["reused"] is False


def test_start_stops_when_build_fails(tmp_path):
    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 1 if cmd[1] == "build" else 0, "", "no space left on device")

    with pytest.raises(ValueError, match="no space left"):
        start(tmp_path / "runs", tmp_path / "web", 3000, None, runner=runner, is_free=lambda p: True)


def test_stop_removes_container():
    calls = []
    stop(runner=lambda cmd: calls.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert calls == [["docker", "rm", "-f", CONTAINER]]


def test_build_labels_image(tmp_path):
    assert build_cmd(Path("web"))[-3:] == ["-t", IMAGE, "web"]


def _ps(stdout):
    def runner(cmd):
        runner.calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout if cmd[1] == "ps" else "", "")

    runner.calls = []
    return runner


def test_a_running_site_is_reused_not_rebuilt_or_killed(tmp_path):
    runner = _ps("127.0.0.1:3005->3000/tcp\n")
    result = start(tmp_path / "runs", tmp_path / "web", 3000, "r-2", runner=runner)
    assert result == {"url": "http://127.0.0.1:3005/?run=r-2", "container": CONTAINER, "port": 3005, "reused": True}
    assert [c[1] for c in runner.calls] == ["ps"]


def test_rebuild_replaces_a_running_site(tmp_path):
    runner = _ps("127.0.0.1:3000->3000/tcp")
    start(tmp_path / "runs", tmp_path / "web", 3000, None, runner=runner, rebuild=True, is_free=lambda p: True)
    assert [c[1] for c in runner.calls] == ["ps", "build", "rm", "run"]


def test_busy_port_moves_to_the_next_free_one(tmp_path):
    runner = _ps("")
    result = start(tmp_path / "runs", tmp_path / "web", 3000, None, runner=runner, is_free=lambda p: p >= 3002)
    assert result["port"] == 3002 and "127.0.0.1:3002:3000" in runner.calls[-1]
    with pytest.raises(ValueError, match="no free port"):
        find_free_port(3000, tries=3, is_free=lambda p: False)


def test_running_port_and_status():
    assert running_port(_ps("0.0.0.0:9999->80/tcp")) is None
    assert status(_ps("127.0.0.1:3000->3000/tcp")) == {"running": True, "port": 3000, "url": "http://127.0.0.1:3000/"}
    assert status(_ps(""))["running"] is False


def test_wait_ready_polls_until_the_site_answers():
    import urllib.error

    attempts = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(url, timeout):
        attempts.append(url)
        if len(attempts) < 3:
            raise urllib.error.URLError("connection refused")
        return Response()

    assert wait_ready("http://127.0.0.1:3000/?run=r", timeout=30, opener=opener, sleep=lambda s: None) is True
    assert attempts[-1] == "http://127.0.0.1:3000/api/state"
    assert wait_ready("http://x/", timeout=0, opener=lambda u, timeout: (_ for _ in ()).throw(OSError("down")), sleep=lambda s: None) is False


def test_lock_runs_npm_in_a_container_with_only_the_web_dir_mounted(tmp_path):
    from e2eat.web import lock_cmd, update_lockfile

    web = tmp_path / "web"
    web.mkdir()
    cmd = lock_cmd(web)
    assert cmd[:3] == ["docker", "run", "--rm"] and f"{web.resolve()}:/app" in cmd and cmd.count("-v") == 1
    assert "--ignore-scripts" in cmd and "--package-lock-only" in cmd and "ALL" in cmd

    def runner(c):
        (web / "package-lock.json").write_text("{}")
        return subprocess.CompletedProcess(c, 0, "", "")

    assert update_lockfile(web, runner=runner)["bytes"] == 2
    with pytest.raises(ValueError, match="not written"):
        update_lockfile(tmp_path / "other", runner=lambda c: subprocess.CompletedProcess(c, 0, "", ""))
