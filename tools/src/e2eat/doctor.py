"""Preflight checks before /evaluate starts a run."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import secrets_file
from .sandbox import Runner, default_runner

MIN_FREE_BYTES = 5 * 1024**3
BROWSE_BIN = Path.home() / ".claude" / "skills" / "gstack" / "browse" / "dist" / "browse"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def run_checks(
    runner: Runner = default_runner,
    which: Callable[[str], str | None] = shutil.which,
    browse_bin: Path = BROWSE_BIN,
    secrets: Path | None = None,
    disk_free: Callable[[], int] = lambda: shutil.disk_usage(Path.home()).free,
) -> list[Check]:
    checks = [Check(tool, bool(which(tool)), which(tool) or "not on PATH") for tool in ("git", "docker", "uv")]
    if which("docker"):
        proc = runner(["docker", "info", "--format", "{{.ServerVersion}}"])
        version = proc.stdout.strip() if proc.returncode == 0 else ""
        checks.append(Check("docker daemon", bool(version), f"server {version}" if version else "daemon not reachable — start Docker Desktop"))
    if which("gh"):
        ok = runner(["gh", "auth", "status"]).returncode == 0
        checks.append(Check("gh auth", ok, "authenticated" if ok else "run `gh auth login` for GitHub repo health data", required=False))
    else:
        checks.append(Check("gh auth", False, "gh not installed — repo health falls back to git history", required=False))
    browse = Path(browse_bin)
    checks.append(Check("gstack browse", browse.exists(),
                        str(browse) if browse.exists() else f"missing {browse} — web journeys fall back to curl", required=False))
    secrets = secrets or secrets_file()
    checks.append(Check("secrets.env", secrets.exists(),
                        str(secrets) if secrets.exists() else "no secrets.env — features needing API keys are reported untested", required=False))
    free = disk_free()
    checks.append(Check("disk space", free >= MIN_FREE_BYTES,
                        f"{free / 1024**3:.1f} GiB free" if free >= MIN_FREE_BYTES
                        else f"only {free / 1024**3:.1f} GiB free — need {MIN_FREE_BYTES // 1024**3} GiB; Docker image builds fail on a full disk"))
    return checks
