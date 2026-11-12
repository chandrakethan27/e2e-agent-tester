"""Read-only git queries on the evaluated repo, hardened against repo-controlled configuration."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence

ALLOWED_SUBCOMMANDS = ("log", "shortlog", "rev-list", "ls-files", "rev-parse")
FORBIDDEN_OPTIONS = ("--output", "--ext-diff", "--textconv", "--exec", "-o")
# Override every config key a planted .git/config could use to run a command during a read-only query.
HARDENING = (
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.pager=cat",
    "-c", "core.sshCommand=false",
    "-c", "credential.helper=",
    "-c", "protocol.allow=never",
    "-c", "core.editor=false",
    "-c", "core.attributesFile=/dev/null",
    "-c", "log.showSignature=false",
    "-c", "gpg.program=false",
    "-c", "gpg.ssh.program=false",
    "-c", "gpg.x509.program=false",
)


def git_cmd(run_dir: Path, args: Sequence[str]) -> list[str]:
    if not args or args[0] not in ALLOWED_SUBCOMMANDS:
        raise ValueError(f"git subcommand must be one of {', '.join(ALLOWED_SUBCOMMANDS)}")
    if any(arg.startswith(FORBIDDEN_OPTIONS) for arg in args[1:]):
        raise ValueError(f"git options {', '.join(FORBIDDEN_OPTIONS)} are not allowed")
    sub, rest = args[0], list(args[1:])
    if sub == "log":  # a planted .git/config or .gitattributes could otherwise run a textconv/external diff program
        rest = ["--no-textconv", "--no-ext-diff", *rest]
    return ["git", "--no-pager", *HARDENING, "-C", str(Path(run_dir).resolve() / "repo"), sub, *rest]


def git_env(run_dir: Path) -> dict[str, str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}  # no inherited GIT_DIR, GIT_EXEC_PATH, ...
    return clean | {
        "GIT_CEILING_DIRECTORIES": str(Path(run_dir).resolve()),  # never walk up into the tool's own repo
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
    }


def run_git(run_dir: Path, args: Sequence[str]) -> dict:
    cmd = git_cmd(run_dir, args)
    if not (Path(run_dir) / "repo" / ".git").is_dir():
        return {"exit_code": 3, "stdout": "", "stderr": "source has no git history"}
    proc = subprocess.run(cmd, env=git_env(run_dir), capture_output=True, text=True, timeout=300)
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
