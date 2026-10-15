"""Sandbox commands: per-run Docker names, network, image builds, containers, secrets env file, teardown."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..jsonio import read_json
from ..paths import secrets_file
from ..redact import parse_env_file
from ..sandbox import (
    LABEL,
    build_cmd,
    compose_project,
    container_name,
    execute,
    image_tag,
    network_create_cmd,
    network_name,
    run_cmd,
    stale_run_ids,
    teardown,
    write_run_env,
)
from ..workspace import load_run
from .output import emit


def register(sub: argparse._SubParsersAction) -> None:
    sandbox = sub.add_parser("sandbox", help="Docker sandbox helpers (all resources labeled e2eat.run=<run-id>)")
    ssub = sandbox.add_subparsers(dest="sandbox_command", required=True)

    p = ssub.add_parser("names", help="docker names used for this run")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(handler=_names)

    p = ssub.add_parser("net", help="create the run's bridge network")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(handler=_net)

    p = ssub.add_parser("build", help="docker build with the run label; tag e2eat/<run-id>:<name>")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--context", type=Path, help="build context (default: <run-dir>/repo)")
    p.add_argument("--dockerfile", type=Path)
    p.add_argument("--name", default="app")
    p.add_argument("--log", type=Path)
    p.add_argument("--timeout", type=float, default=1800)
    p.set_defaults(handler=_build)

    p = ssub.add_parser("run", help="docker run with limits, labels, run network, localhost-only ports")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--name", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("-p", "--port", action="append", default=[], help="CONTAINER or HOST:CONTAINER (bound to 127.0.0.1)")
    p.add_argument("-e", "--env", action="append", default=[], help="non-secret KEY=VALUE")
    p.add_argument("-v", "--volume", action="append", default=[], help="named volume or bind mount from inside the run dir")
    p.add_argument("--secrets", action="store_true", help="pass RUN_DIR/.secrets.env (create it with `sandbox env`)")
    p.add_argument("--foreground", action="store_true", help="run to completion with --rm instead of detaching")
    p.add_argument("--timeout", type=float, default=900, help="seconds, foreground only")
    p.add_argument("--log", type=Path)
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- command and args for the container")
    p.set_defaults(handler=_run)

    p = ssub.add_parser("env", help="write RUN_DIR/.secrets.env with only the secrets recon says are needed")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--secrets", type=Path, default=None)
    p.set_defaults(handler=_env)

    p = ssub.add_parser("teardown", help="remove every container, network, volume and image of the run")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--keep-images", action="store_true")
    p.set_defaults(handler=_teardown)

    p = ssub.add_parser("stale", help="tear down leftovers from runs older than --max-age-hours")
    p.add_argument("--max-age-hours", type=float, default=6)
    p.set_defaults(handler=_stale)


def _run_id(run_dir: Path) -> str:
    return load_run(run_dir)["run_id"]


def _default_log(run_dir: Path, name: str) -> Path:
    return Path(run_dir) / "blackboard" / "evidence" / "sandbox" / name


def _names(args: argparse.Namespace) -> int:
    rid = _run_id(args.run_dir)
    emit({"run_id": rid, "label": f"{LABEL}={rid}", "network": network_name(rid), "compose_project": compose_project(rid),
          "image_tag": image_tag(rid), "container_prefix": container_name(rid, "")})
    return 0


def _net(args: argparse.Namespace) -> int:
    result = execute(network_create_cmd(_run_id(args.run_dir)))
    ok = result["exit_code"] == 0 or "already exists" in result["tail"]
    emit({"ok": ok, "network": network_name(_run_id(args.run_dir)), **result})
    return 0 if ok else 1


def _build(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    rid = _run_id(run_dir)
    log = args.log or _default_log(run_dir, f"build-{args.name}.log")
    result = execute(build_cmd(rid, args.context or run_dir / "repo", args.dockerfile, args.name), log, args.timeout)
    emit({"ok": result["exit_code"] == 0, "image": image_tag(rid, args.name), **result})
    return 0 if result["exit_code"] == 0 else 1


def _run(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    rid = _run_id(run_dir)
    env_file = run_dir / ".secrets.env" if args.secrets else None
    if env_file and not env_file.exists():
        raise ValueError("no .secrets.env yet; run `e2eat sandbox env <run-dir>` first")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    cmd = run_cmd(rid, run_dir, args.image, args.name, ports=args.port, env=args.env, env_file=env_file,
                  volumes=args.volume, command=command, detach=not args.foreground)
    log = args.log or _default_log(run_dir, f"run-{args.name}.log")
    result = execute(cmd, log, args.timeout if args.foreground else 600)
    if args.foreground and result["exit_code"] == 124:
        execute(["docker", "rm", "-f", container_name(rid, args.name)])  # killing the client does not stop the container
    emit({"ok": result["exit_code"] == 0, "container": container_name(rid, args.name), **result})
    return 0 if result["exit_code"] == 0 else 1


def _env(args: argparse.Namespace) -> int:
    recon = read_json(args.run_dir / "blackboard" / "facts" / "recon.json")
    path = args.secrets or secrets_file()
    secrets = parse_env_file(path) if path.exists() else {}
    emit(write_run_env(args.run_dir, recon.get("secrets_needed", []), secrets))
    return 0


def _teardown(args: argparse.Namespace) -> int:
    emit(teardown(_run_id(args.run_dir), args.run_dir, args.keep_images))
    return 0


def _stale(args: argparse.Namespace) -> int:
    stale = stale_run_ids(max_age_hours=args.max_age_hours)
    emit({"stale": stale, "removed": {rid: teardown(rid) for rid in stale}})
    return 0
