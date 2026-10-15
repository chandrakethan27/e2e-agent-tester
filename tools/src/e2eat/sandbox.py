"""Docker sandbox helpers. Every resource carries the label e2eat.run=<run-id> so teardown can find it."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

LABEL = "e2eat.run"
LIMITS = ("--cpus", "2", "--memory", "4g", "--pids-limit", "1024", "--security-opt", "no-new-privileges")
UNSAFE_FLAGS = re.compile(
    r"--privileged|(?:--net(?:work)?|--pid|--ipc|--userns|--uts)[= ]host\b|--cap-add[= ](?:ALL|SYS_ADMIN)\b|docker\.sock"
)
NAMED_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PORT = re.compile(r"^(\d{1,5})(?::(\d{1,5}))?$")
_RUN_STAMP = re.compile(r"-(\d{8}-\d{6})$")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def network_name(run_id: str) -> str:
    return f"e2eat-{run_id}"


def container_name(run_id: str, name: str) -> str:
    return f"e2eat-{run_id}-{name}"


def compose_project(run_id: str) -> str:
    return f"e2eat-{run_id}"


def image_tag(run_id: str, name: str = "app") -> str:
    return f"e2eat/{run_id}:{name}"


def network_create_cmd(run_id: str) -> list[str]:
    return ["docker", "network", "create", "--label", f"{LABEL}={run_id}", network_name(run_id)]


def build_cmd(run_id: str, context: Path, dockerfile: Path | None = None, name: str = "app") -> list[str]:
    cmd = ["docker", "build", "--label", f"{LABEL}={run_id}", "-t", image_tag(run_id, name)]
    if dockerfile:
        cmd += ["-f", str(dockerfile)]
    return [*cmd, str(context)]


def _port_mapping(spec: str) -> str:
    m = _PORT.match(str(spec))
    if not m:
        raise ValueError(f"bad port {spec!r}; use CONTAINER or HOST:CONTAINER")
    host, container = (m[1], m[2]) if m[2] else (m[1], m[1])
    return f"127.0.0.1:{host}:{container}"


def _inside(run_dir: Path, path: Path) -> bool:
    return Path(path).resolve().is_relative_to(Path(run_dir).resolve())


def _check_volume(spec: str, run_dir: Path) -> None:
    source, _, rest = spec.partition(":")
    if NAMED_VOLUME.match(source):
        return  # named volume
    if "$" in source or not _inside(run_dir, Path(source)):
        raise ValueError(f"bind mounts must come from inside the run dir: {spec}")
    options = rest.partition(":")[2].split(",")
    if _inside(Path(run_dir) / "repo", Path(source)) and "ro" not in options:
        raise ValueError(f"mounts of the evaluated repo must be read-only (append :ro): {spec}")


def check_build_inputs(run_dir: Path, context: Path, dockerfile: Path | None) -> None:
    for path in (context, dockerfile):
        if path is not None and not _inside(run_dir, path):
            raise ValueError(f"build context and Dockerfile must be inside the run dir: {path}")


def run_cmd(
    run_id: str,
    run_dir: Path,
    image: str,
    name: str,
    *,
    ports: Sequence[str] = (),
    env: Sequence[str] = (),
    env_file: Path | None = None,
    volumes: Sequence[str] = (),
    extra: Sequence[str] = (),
    command: Sequence[str] = (),
    detach: bool = True,
) -> list[str]:
    joined = " ".join(extra)
    if UNSAFE_FLAGS.search(joined) or any("docker.sock" in v for v in volumes):
        raise ValueError(f"refusing unsafe docker options: {joined or ', '.join(volumes)}")
    for volume in volumes:
        _check_volume(volume, run_dir)
    cmd = ["docker", "run", "-d" if detach else "--rm", "--name", container_name(run_id, name),
           "--label", f"{LABEL}={run_id}", "--network", network_name(run_id), "--network-alias", name, *LIMITS]
    for spec in ports:
        cmd += ["-p", _port_mapping(spec)]
    for pair in env:
        if "=" not in pair:
            raise ValueError(f"env must be KEY=VALUE: {pair!r}")
        cmd += ["-e", pair]
    if env_file:
        cmd += ["--env-file", str(env_file)]
    for volume in volumes:
        cmd += ["-v", volume]
    return [*cmd, *extra, image, *command]


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def execute(cmd: Sequence[str], log_path: Path | None = None, timeout: float | None = None) -> dict:
    try:
        proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        output, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        output, code = f"{_text(exc.stdout)}{_text(exc.stderr)}\n[e2eat] timed out after {timeout}s\n", 124
    if log_path is not None:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output, encoding="utf-8")
    return {"exit_code": code, "tail": output[-4000:], "log": str(log_path) if log_path else None}


def teardown(run_id: str, run_dir: Path | None = None, keep_images: bool = False, runner: Runner = default_runner) -> dict[str, int]:
    filters = [f"label={LABEL}={run_id}", f"label=com.docker.compose.project={compose_project(run_id)}"]

    def ids(*base: str) -> list[str]:
        found: set[str] = set()
        for flt in filters:
            proc = runner([*base, "--filter", flt])
            if proc.returncode == 0:
                found |= set(proc.stdout.split())
        return sorted(found)

    removed = {"containers": 0, "networks": 0, "volumes": 0, "images": 0}
    steps = [
        ("containers", ("docker", "ps", "-aq"), ("docker", "rm", "-f", "-v")),
        ("networks", ("docker", "network", "ls", "-q"), ("docker", "network", "rm")),
        ("volumes", ("docker", "volume", "ls", "-q"), ("docker", "volume", "rm", "-f")),
    ]
    if not keep_images:
        steps.append(("images", ("docker", "images", "-q"), ("docker", "rmi", "-f")))
    for kind, list_cmd, remove_cmd in steps:
        found = ids(*list_cmd)
        if found:
            runner([*remove_cmd, *found])
            removed[kind] = len(found)
    if run_dir is not None:
        (Path(run_dir) / ".secrets.env").unlink(missing_ok=True)
    return removed


def run_started_at(run_id: str) -> datetime | None:
    m = _RUN_STAMP.search(run_id)
    return datetime.strptime(m[1], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc) if m else None


def stale_run_ids(now: datetime | None = None, max_age_hours: float = 6, runner: Runner = default_runner) -> list[str]:
    now = now or datetime.now(timezone.utc)
    fmt = '{{.Label "' + LABEL + '"}}'
    seen: set[str] = set()
    for cmd in (["docker", "ps", "-a", "--filter", f"label={LABEL}", "--format", fmt],
                ["docker", "network", "ls", "--filter", f"label={LABEL}", "--format", fmt]):
        proc = runner(cmd)
        if proc.returncode == 0:
            seen |= {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    cutoff = timedelta(hours=max_age_hours)
    return sorted(rid for rid in seen if (started := run_started_at(rid)) and now - started > cutoff)


def write_run_env(run_dir: Path, needed: Sequence[str], secrets: dict[str, str]) -> dict:
    """Write only the secrets this project needs into RUN_DIR/.secrets.env (mode 600) for --env-file."""
    present = [key for key in needed if secrets.get(key) and "\n" not in secrets[key]]
    missing = [key for key in needed if key not in present]
    path = Path(run_dir) / ".secrets.env"
    path.write_text("".join(f"{key}={secrets[key]}\n" for key in present), encoding="utf-8")
    path.chmod(0o600)
    return {"env_file": str(path.resolve()), "present": present, "missing": missing}
