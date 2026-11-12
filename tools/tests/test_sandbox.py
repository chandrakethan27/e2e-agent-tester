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
    (tmp_path / "blackboard" / "evidence" / "perf-agent").mkdir(parents=True)
    cmd = run_cmd(RID, tmp_path, "python:3.12-slim", "app", ports=["5000", "8080:80"], env=["MODE=test"],
                  volumes=[f"{tmp_path}/blackboard/evidence/perf-agent:/work", "pgdata:/var/lib/postgresql/data"],
                  command=["python", "app.py"])
    joined = " ".join(cmd)
    assert f"-v {tmp_path}/blackboard/evidence/perf-agent:/work" in joined
    assert f"--mount type=volume,src=e2eat-{RID}-pgdata,dst=/var/lib/postgresql/data,volume-label=e2eat.run={RID}" in joined
    assert "--cap-drop ALL" in joined
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
    env = tmp_path / "secrets.d" / "r.env"
    info = write_run_env(env, ["OPENAI_API_KEY", "MISSING_KEY", "MULTI"], {"OPENAI_API_KEY": "sk-1", "MULTI": "a\nb", "OTHER": "x"})
    assert info["present"] == ["OPENAI_API_KEY"]
    assert info["missing"] == ["MISSING_KEY", "MULTI"]
    assert env.read_text() == "OPENAI_API_KEY=sk-1\n"
    assert env.stat().st_mode & 0o777 == 0o600
    assert env.parent.stat().st_mode & 0o777 == 0o700


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


@pytest.mark.parametrize("image", ["--privileged", "-v/:/host", "bad image", "img;rm", ""])
def test_image_cannot_smuggle_docker_options(tmp_path, image):
    with pytest.raises(ValueError, match="image"):
        run_cmd(RID, tmp_path, image, "app")


@pytest.mark.parametrize("image", ["grafana/k6:0.54.0", "ghcr.io/google/osv-scanner:v1.9.1", "e2eat/r:app", "python@sha256:" + "a" * 64])
def test_normal_image_references_pass(tmp_path, image):
    assert image in run_cmd(RID, tmp_path, image, "app")


@pytest.mark.parametrize("name", ["-x", "A b", "app/../x", "x" * 80])
def test_bad_container_names_are_refused(tmp_path, name):
    with pytest.raises(ValueError, match="name"):
        run_cmd(RID, tmp_path, "img", name)


@pytest.mark.parametrize("pair", ["--privileged=1", "A B=1", "=x", "1A=x"])
def test_env_keys_must_be_plain_names(tmp_path, pair):
    with pytest.raises(ValueError):
        run_cmd(RID, tmp_path, "img", "app", env=[pair])


def test_bind_mounts_only_from_allowed_places(tmp_path):
    for sub in ("repo", "runtime-config", "blackboard/evidence/x", "blackboard/facts"):
        (tmp_path / sub).mkdir(parents=True)
    ok = run_cmd(RID, tmp_path, "img", "app", volumes=[
        f"{tmp_path}/repo:/src:ro", f"{tmp_path}/runtime-config:/cfg:ro", f"{tmp_path}/blackboard/evidence/x:/out"])
    assert f"{tmp_path}/runtime-config:/cfg:ro" in " ".join(ok)
    for bad in (f"{tmp_path}:/w", f"{tmp_path}/blackboard:/w", f"{tmp_path}/blackboard/facts:/w:ro", f"{tmp_path}/run.json:/r:ro",
                f"{tmp_path}/runtime-config:/cfg", f"{tmp_path.parent}:/w:ro", "/:/host", f"{tmp_path}/repo:relative"):
        with pytest.raises(ValueError):
            run_cmd(RID, tmp_path, "img", "app", volumes=[bad])


def test_symlink_inside_repo_cannot_escape_the_run_dir(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "link").symlink_to("/")
    with pytest.raises(ValueError):
        run_cmd(RID, tmp_path, "img", "app", volumes=[f"{tmp_path}/repo/link:/h:ro"])


def test_named_volumes_are_per_run_and_labelled(tmp_path):
    cmd = run_cmd(RID, tmp_path, "img", "app", volumes=["data:/d:ro"])
    assert f"type=volume,src=e2eat-{RID}-data,dst=/d,volume-label=e2eat.run={RID},readonly" in cmd


def test_teardown_also_removes_the_per_run_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("E2EAT_HOME", str(tmp_path))
    from e2eat.paths import run_env_file

    write_run_env(run_env_file(RID), ["K"], {"K": "value"})
    assert run_env_file(RID).exists()
    teardown(RID, runner=fake({})[0])
    assert not run_env_file(RID).exists()
