import subprocess
from datetime import datetime, timezone

import pytest

from e2eat.sandbox import (
    execute,
    image_tag,
    network_name,
    run_cmd,
    stale_run_ids,
    teardown,
    write_run_env,
)

RID = "o-r-20261015-093000"


def fake(outputs):
    calls = []

    def runner(cmd):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=outputs.get(" ".join(cmd[:3]), ""), stderr="")

    return runner, calls


def test_names():
    assert network_name(RID) == "e2eat-o-r-20261015-093000"
    assert image_tag(RID) == "e2eat/o-r-20261015-093000:app"


def test_run_cmd_applies_limits_labels_and_localhost_ports(tmp_path):
    cmd = run_cmd(RID, tmp_path, "python:3.12-slim", "app", ports=["5000", "8080:80"], env=["MODE=test"],
                  volumes=[f"{tmp_path}/data:/data", "pgdata:/var/lib/postgresql/data"], command=["python", "app.py"])
    joined = " ".join(cmd)
    assert cmd[:3] == ["docker", "run", "-d"]
    assert f"--label e2eat.run={RID}" in joined
    assert f"--network e2eat-{RID} --network-alias app" in joined
    assert "--memory 4g" in joined and "--security-opt no-new-privileges" in joined
    assert "-p 127.0.0.1:5000:5000" in joined and "-p 127.0.0.1:8080:80" in joined
    assert cmd[-3:] == ["python:3.12-slim", "python", "app.py"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extra": ["--privileged"]},
        {"extra": ["--network", "host"]},
        {"extra": ["--pid=host"]},
        {"extra": ["--cap-add", "SYS_ADMIN"]},
        {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]},
        {"volumes": ["/:/host"]},
        {"ports": ["abc"]},
        {"env": ["NOEQUALS"]},
    ],
)
def test_run_cmd_refuses_unsafe(tmp_path, kwargs):
    with pytest.raises(ValueError):
        run_cmd(RID, tmp_path, "img", "app", **kwargs)


def test_teardown_removes_labeled_resources(tmp_path):
    (tmp_path / ".secrets.env").write_text("K=V\n")
    runner, calls = fake({"docker ps -aq": "c1\nc2\n", "docker network ls": "n1\n", "docker images -q": "i1\n"})
    removed = teardown(RID, run_dir=tmp_path, runner=runner)
    assert removed == {"containers": 2, "networks": 1, "volumes": 0, "images": 1}
    assert ["docker", "rm", "-f", "-v", "c1", "c2"] in calls
    assert ["docker", "rmi", "-f", "i1"] in calls
    assert not (tmp_path / ".secrets.env").exists()


def test_teardown_can_keep_images():
    runner, calls = fake({"docker images -q": "i1\n"})
    assert teardown(RID, keep_images=True, runner=runner)["images"] == 0
    assert not any(c[:2] == ["docker", "rmi"] for c in calls)


def test_stale_run_ids():
    runner, _ = fake({"docker ps -a": "old-20261015-010000\nnew-20261015-093000\n",
                      "docker network ls": "old-20261015-010000\nbogus\n"})
    now = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
    assert stale_run_ids(now=now, runner=runner) == ["old-20261015-010000"]


def test_write_run_env_only_writes_needed_single_line_values(tmp_path):
    info = write_run_env(tmp_path, ["OPENAI_API_KEY", "MISSING_KEY", "MULTI"], {"OPENAI_API_KEY": "sk-1", "MULTI": "a\nb", "OTHER": "x"})
    assert info["present"] == ["OPENAI_API_KEY"]
    assert info["missing"] == ["MISSING_KEY", "MULTI"]
    env = tmp_path / ".secrets.env"
    assert env.read_text() == "OPENAI_API_KEY=sk-1\n"
    assert env.stat().st_mode & 0o777 == 0o600


def test_execute_captures_output_and_timeout(tmp_path):
    ok = execute(["sh", "-c", "echo hello"], log_path=tmp_path / "a.log")
    assert ok["exit_code"] == 0 and (tmp_path / "a.log").read_text().strip() == "hello"
    slow = execute(["sleep", "5"], timeout=0.2)
    assert slow["exit_code"] == 124 and "timed out" in slow["tail"]


@pytest.mark.parametrize("volume", [".:/app", "..:/x", "~:/h", "$HOME:/h"])
def test_relative_and_home_mounts_are_paths_not_named_volumes(tmp_path, volume):
    with pytest.raises(ValueError):
        run_cmd(RID, tmp_path, "img", "app", volumes=[volume])


def test_repo_mounts_must_be_read_only(tmp_path):
    (tmp_path / "repo").mkdir()
    with pytest.raises(ValueError, match="read-only"):
        run_cmd(RID, tmp_path, "img", "app", volumes=[f"{tmp_path}/repo:/src"])
    assert f"{tmp_path}/repo:/src:ro" in run_cmd(RID, tmp_path, "img", "app", volumes=[f"{tmp_path}/repo:/src:ro"])


def test_build_inputs_must_stay_in_run_dir(tmp_path):
    from e2eat.sandbox import check_build_inputs

    check_build_inputs(tmp_path, tmp_path / "repo", tmp_path / "repo" / ".e2eat" / "Dockerfile")
    with pytest.raises(ValueError):
        check_build_inputs(tmp_path, tmp_path.parent, None)
    with pytest.raises(ValueError):
        check_build_inputs(tmp_path, tmp_path / "repo", tmp_path.parent / "Dockerfile")
