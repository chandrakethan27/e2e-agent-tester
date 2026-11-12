"""Locations shared by every e2eat command."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    """Project root: $E2EAT_HOME when set (bin/e2eat sets it), else the repo containing this package."""
    env = os.environ.get("E2EAT_HOME")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[3]


def runs_root() -> Path:
    return home() / "runs"


def secrets_file() -> Path:
    return home() / "secrets.env"


def secrets_dir() -> Path:
    """Per-run env files live here, outside runs/ so the live-view container and run artifacts never see them."""
    return home() / ".secrets.d"


def run_env_file(run_id: str) -> Path:
    return secrets_dir() / f"{run_id}.env"
