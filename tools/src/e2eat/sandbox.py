"""Docker sandbox helpers. Every resource carries the label e2eat.run=<run-id> so teardown can find it."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Collection, Sequence

from .paths import run_env_file

LABEL = "e2eat.run"
# Capabilities a typical service image legitimately needs; everything else is dropped.
_CAPS = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID", "NET_BIND_SERVICE", "KILL")
CAP_ARGS = ("--cap-drop", "ALL", *(arg for cap in _CAPS for arg in ("--cap-add", cap)))
LIMITS = ("--cpus", "2", "--memory", "4g", "--pids-limit", "1024", "--security-opt", "no-new-privileges", *CAP_ARGS)
UNSAFE_FLAGS = re.compile(
    r"--privileged"
    r"|(?:--net(?:work)?|--pid|--ipc|--userns|--uts|--cgroupns)[= ](?:host|container:\S+)"
    r"|--cap-add[= ](?!(?:CAP_)?(?:" + "|".join(_CAPS) + r")\b)"
    r"|--device\b"
    r"|--security-opt[= ]\S*(?:unconfined|disable)"
    r"|docker\.sock",
    re.IGNORECASE,
)
NAMED_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
IMAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,200}$")  # never starts with "-", so it cannot be read as a docker option
CONTAINER_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,40}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MOUNT_TARGET = re.compile(r"^/[A-Za-z0-9_./-]*$")
# Bind mounts are only allowed from these places inside the run dir; the repo and generated config are read-only.
READ_ONLY_ROOTS = ("repo", "runtime-config")
WRITABLE_ROOTS = ("blackboard/evidence",)
_PORT = re.compile(r"^(\d{1,5})(?::(\d{1,5}))?$")
_RUN_STAMP = re.compile(r"-(\d{8}-\d{6})$")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]
DEFAULT_TIMEOUT = 120


def runner_with_timeout(seconds: float) -> Runner:
    """A subprocess runner that never hangs: a timeout becomes exit code 124, a missing binary exit code 127."""

    def run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(list(cmd), capture_output=True, text=True, timeout=seconds)
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(list(cmd), 124, _text(exc.stdout), f"{_text(exc.stderr)}[e2eat] timed out after {seconds}s")
        except FileNotFoundError as exc:
            return subprocess.CompletedProcess(list(cmd), 127, "", str(exc))

    return run


default_runner = runner_with_timeout(DEFAULT_TIMEOUT)


def network_name(run_id: str) -> str:
    return f"e2eat-{run_id}"


def container_name(run_id: str, name: str) -> str:
    return f"e2eat-{run_id}-{name}"


def compose_project(run_id: str) -> str:
    return f"e2eat-{run_id}"


def volume_name(run_id: str, name: str) -> str:
    return f"e2eat-{run_id}-{name}"


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


def _volume_args(spec: str, run_dir: Path, run_id: str) -> list[str]:
    """Turn a -v spec into docker arguments. Named volumes become labelled, per-run volumes; bind mounts must come from
    an allowed place inside the run dir (the repo and runtime-config read-only, evidence writable)."""
    source, _, rest = spec.partition(":")
    target, _, opts = rest.partition(":")
    options = [o for o in opts.split(",") if o]
    if not MOUNT_TARGET.match(target):
        raise ValueError(f"volume needs an absolute container path like SRC:/path[:ro]: {spec}")
    if NAMED_VOLUME.match(source):
        mount = f"type=volume,src={volume_name(run_id, source)},dst={target},volume-label={LABEL}={run_id}"
        return ["--mount", mount + (",readonly" if "ro" in options else "")]
    if "$" in source or not os.path.isabs(source):
        raise ValueError(f"bind mounts must be absolute paths inside the run dir: {spec}")
    try:
        resolved = Path(source).resolve()
        base = Path(run_dir).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"cannot resolve mount source {source}: {exc}") from exc
    for roots, writable in ((READ_ONLY_ROOTS, False), (WRITABLE_ROOTS, True)):
        for root in roots:
            if resolved.is_relative_to(base / root):
                if not writable and "ro" not in options:
                    raise ValueError(f"mounts of {root}/ must be read-only (append :ro): {spec}")
                return ["-v", f"{source}:{target}" + (f":{opts}" if opts else "")]
    allowed = ", ".join([*READ_ONLY_ROOTS, *WRITABLE_ROOTS])
    raise ValueError(f"bind mounts are only allowed from {allowed} inside the run dir: {spec}")


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
    if not IMAGE_REF.match(image):
        raise ValueError(f"bad image reference {image!r}")
    if not CONTAINER_NAME.match(name):
        raise ValueError(f"bad container name {name!r}; use lowercase letters, digits, '_', '.', '-'")
    mounts = [arg for volume in volumes for arg in _volume_args(volume, Path(run_dir), run_id)]
    cmd = ["docker", "run", "-d" if detach else "--rm", "--name", container_name(run_id, name),
           "--label", f"{LABEL}={run_id}", "--network", network_name(run_id), "--network-alias", name, *LIMITS]
    for spec in ports:
        cmd += ["-p", _port_mapping(spec)]
    for pair in env:
        key, sep, _ = pair.partition("=")
        if not sep or not ENV_KEY.match(key):
            raise ValueError(f"env must be KEY=VALUE with a plain variable name: {pair!r}")
        cmd += ["-e", pair]
    if env_file:
        cmd += ["--env-file", str(env_file)]
    return [*cmd, *mounts, *extra, image, *command]


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


def teardown(run_id: str, run_dir: Path | None = None, keep_images: bool = False, runner: Runner = default_runner) -> dict:
    """Remove every labelled resource of the run. Failures are reported under "errors" instead of being counted as removed."""
    filters = [f"label={LABEL}={run_id}", f"label=com.docker.compose.project={compose_project(run_id)}"]
    errors: list[str] = []

    def ids(*base: str) -> list[str]:
        found: set[str] = set()
        for flt in filters:
            proc = runner([*base, "--filter", flt])
            if proc.returncode == 0:
                found |= set(proc.stdout.split())
            else:
                errors.append(f"{' '.join(base[:3])} failed: {(proc.stderr or proc.stdout).strip()[:200]}")
        return sorted(found)

    removed: dict = {"containers": 0, "networks": 0, "volumes": 0, "images": 0}
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
            proc = runner([*remove_cmd, *found])
            if proc.returncode == 0:
                removed[kind] = len(found)
            else:
                errors.append(f"removing {kind} failed: {(proc.stderr or proc.stdout).strip()[:200]}")
    run_env_file(run_id).unlink(missing_ok=True)
    if run_dir is not None:
        (Path(run_dir) / ".secrets.env").unlink(missing_ok=True)  # written there by older versions
    if errors:
        removed["errors"] = errors
    return removed


def run_started_at(run_id: str) -> datetime | None:
    m = _RUN_STAMP.search(run_id)
    if not m:
        return None
    try:
        return datetime.strptime(m[1], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:  # e.g. a label like x-20261399-000000
        return None


def stale_run_ids(
    now: datetime | None = None,
    max_age_hours: float = 6,
    runner: Runner = default_runner,
    exclude: Collection[str] = (),
) -> list[str]:
    """Run ids older than max_age_hours that still own containers, networks, volumes or images."""
    now = now or datetime.now(timezone.utc)
    fmt = '{{.Label "' + LABEL + '"}}'
    seen: set[str] = set()
    for cmd in (["docker", "ps", "-a", "--filter", f"label={LABEL}", "--format", fmt],
                ["docker", "network", "ls", "--filter", f"label={LABEL}", "--format", fmt],
                ["docker", "volume", "ls", "--filter", f"label={LABEL}", "--format", fmt]):
        proc = runner(cmd)
        if proc.returncode == 0:
            seen |= {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    proc = runner(["docker", "image", "ls", "--filter", f"label={LABEL}", "--format", "{{.Repository}}"])
    if proc.returncode == 0:
        seen |= {line.strip().removeprefix("e2eat/") for line in proc.stdout.splitlines() if line.strip().startswith("e2eat/")}
    cutoff = timedelta(hours=max_age_hours)
    return sorted(rid for rid in seen if rid not in exclude and (started := run_started_at(rid)) and now - started > cutoff)


def write_run_env(dest: Path, needed: Sequence[str], secrets: dict[str, str]) -> dict:
    """Write only the secrets this project needs to `dest` (mode 600, created atomically) for --env-file."""
    present = [key for key in needed if secrets.get(key) and "\n" not in secrets[key]]
    missing = [key for key in needed if key not in present]
    dest = Path(dest)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("".join(f"{key}={secrets[key]}\n" for key in present))
    dest.chmod(0o600)
    return {"env_file": str(dest.resolve()), "present": present, "missing": missing}
