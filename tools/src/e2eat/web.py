"""Launch the live run visualization (the Next.js app in web/) in a container that can only read runs/."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from .sandbox import Runner, runner_with_timeout

IMAGE = "e2eat-web:latest"
CONTAINER = "e2eat-web"
LABEL = "e2eat.web=1"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _check(port: int, run_id: str | None) -> None:
    if not 1 <= port <= 65535:
        raise ValueError(f"port {port} out of range")
    if run_id is not None and not _RUN_ID.match(run_id):
        raise ValueError(f"unsafe run id {run_id!r}")


def build_cmd(web_dir: Path) -> list[str]:
    return ["docker", "build", "--label", LABEL, "-t", IMAGE, str(web_dir)]


def run_cmd(runs_dir: Path, port: int, run_id: str | None) -> list[str]:
    _check(port, run_id)
    cmd = ["docker", "run", "-d", "--name", CONTAINER, "--label", LABEL,
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "512m",
           "-p", f"127.0.0.1:{port}:3000", "-v", f"{runs_dir}:/runs:ro", "-e", "RUNS_DIR=/runs"]
    if run_id:
        cmd += ["-e", f"DEFAULT_RUN_ID={run_id}"]
    return cmd + [IMAGE]


def open_url(port: int, run_id: str | None) -> str:
    return f"http://127.0.0.1:{port}/" + (f"?run={run_id}" if run_id else "")


def _run(cmd: Sequence[str], runner: Runner, what: str) -> str:
    proc = runner(cmd)
    if proc.returncode != 0:
        raise ValueError(f"{what} failed: {(proc.stderr or proc.stdout).strip()[-600:]}")
    return proc.stdout.strip()


def start(runs_dir: Path, web_dir: Path, port: int, run_id: str | None, runner: Runner = runner_with_timeout(900)) -> dict:
    _check(port, run_id)
    _run(build_cmd(web_dir), runner, "docker build of the web app")
    runner(["docker", "rm", "-f", CONTAINER])
    _run(run_cmd(runs_dir, port, run_id), runner, "starting the web container")
    return {"url": open_url(port, run_id), "container": CONTAINER}


def stop(runner: Runner = runner_with_timeout(60)) -> None:
    runner(["docker", "rm", "-f", CONTAINER])
