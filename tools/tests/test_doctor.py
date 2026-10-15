import subprocess

from e2eat.doctor import run_checks

GIB = 1024**3


def which(tool):
    return f"/usr/bin/{tool}"


def test_doctor_all_good(tmp_path):
    browse = tmp_path / "browse"
    browse.write_text("")
    secrets = tmp_path / "secrets.env"
    secrets.write_text("")

    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 0, "29.1.3\n", "")

    checks = run_checks(runner=runner, which=which, browse_bin=browse, secrets=secrets, disk_free=lambda: 50 * GIB)
    assert all(c.ok for c in checks)
    assert {c.name for c in checks} == {"git", "docker", "uv", "docker daemon", "gh auth", "gstack browse", "secrets.env", "disk space"}


def test_doctor_flags_stopped_daemon(tmp_path):
    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 1, "", "Cannot connect to the Docker daemon")

    checks = {c.name: c for c in run_checks(runner=runner, which=which, browse_bin=tmp_path / "x", secrets=tmp_path / "y")}
    assert not checks["docker daemon"].ok and checks["docker daemon"].required
    assert "start Docker Desktop" in checks["docker daemon"].detail
    assert not checks["gstack browse"].ok and not checks["gstack browse"].required


def test_doctor_blocks_on_low_disk(tmp_path):
    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 0, "29.1.3\n", "")

    checks = {c.name: c for c in run_checks(runner=runner, which=which, browse_bin=tmp_path / "x", secrets=tmp_path / "y", disk_free=lambda: 2 * GIB)}
    assert not checks["disk space"].ok and checks["disk space"].required
    assert "free" in checks["disk space"].detail
