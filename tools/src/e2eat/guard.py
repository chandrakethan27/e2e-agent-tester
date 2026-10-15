"""PreToolUse guard: refuse Bash commands that would expose the host to evaluated code or leak secrets.

Agents read untrusted repo text, so a prompt injection could ask them to mount the home folder, exfiltrate
secrets.env, or run a repo's compose file. This guard makes the e2eat CLI the only route for those actions.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from .sandbox import NAMED_VOLUME, UNSAFE_FLAGS

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}
_SECRETS_FILE = re.compile(r"(?<![\w.-])secrets\.env(?![\w.-])")
_SEGMENTS = re.compile(r"&&|\|\||[;|&\n]")
_URL_HOST = re.compile(r"https?://([^/\s:'\"?#]+)")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_COMPOSE_ACTIONS = {"up", "run", "create", "start"}
# Programs that can read, copy or send a file. Mentions in prose (heredoc data, docs being written) are fine.
_FILE_READERS = {
    "cat", "less", "more", "head", "tail", "cp", "mv", "scp", "rsync", "curl", "wget", "nc", "ncat", "base64", "xxd",
    "od", "strings", "grep", "egrep", "rg", "sed", "awk", "sort", "uniq", "cut", "tr", "tee", "tar", "zip", "gzip",
    "open", "source", ".", "node", "perl", "ruby", "php", "bash", "sh", "zsh", "jq", "diff", "cmp", "dd", "ln",
}
_SECRET_SUBSTITUTION = re.compile(r"<\s*\S*secrets\.env|\$\([^)]*secrets\.env|`[^`]*\b(?:cat|head|tail|base64|grep|sed|awk|python3?|curl)\b[^`]*secrets\.env")


def check_command(command: str, project_root: Path) -> str | None:
    """Return why the command must be blocked, or None to allow it."""
    runs = Path(project_root) / "runs"
    for segment in _SEGMENTS.split(command):
        if reason := _check_segment(segment.strip(), runs):
            return reason
    return None


def _words(segment: str) -> list[str]:
    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    while words and _ENV_ASSIGNMENT.match(words[0]):
        words = words[1:]
    return words


def _check_segment(segment: str, runs: Path) -> str | None:
    words = _words(segment)
    if not words or words[0] in ("./bin/e2eat", "bin/e2eat") or words[0].endswith("/bin/e2eat"):
        return None
    prog = Path(words[0]).name
    if _SECRETS_FILE.search(segment) and (
        prog in _FILE_READERS or prog.startswith("python") or _SECRET_SUBSTITUTION.search(segment)
    ):
        return "secrets.env may only be read by ./bin/e2eat (sandbox env, redact)"
    if prog == "docker-compose" or (prog == "docker" and words[1:2] == ["compose"]):
        if _COMPOSE_ACTIONS & set(words):
            return "repo compose files are never executed; recreate services with ./bin/e2eat sandbox build/run"
    if prog == "docker" and words[1:2] in (["run"], ["create"]):
        return _check_docker_run(words, runs)
    if prog in ("curl", "wget"):
        for host in _URL_HOST.findall(segment):
            if host not in LOCAL_HOSTS and "." in host:
                return f"{prog} to external host {host} is blocked; use WebFetch or gh api for public data"
    if prog == "git" and ("RUN_DIR" in segment or "/runs/" in segment):
        return "run git on evaluated code only via ./bin/e2eat git <run-dir> ..."
    return None


def _check_docker_run(words: list[str], runs: Path) -> str | None:
    if UNSAFE_FLAGS.search(" ".join(words)):
        return "unsafe docker options (privileged, host namespaces, extra capabilities or the Docker socket)"
    for i, word in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if word in ("-v", "--volume"):
            source = nxt.split(":", 1)[0]
        elif word.startswith("--volume="):
            source = word.split("=", 1)[1].split(":", 1)[0]
        elif word == "--mount" or word.startswith("--mount="):
            source = _mount_source(nxt if word == "--mount" else word.split("=", 1)[1])
        else:
            continue
        if source is not None and (problem := _bind_problem(source, runs)):
            return problem
    return None


def _mount_source(spec: str) -> str | None:
    fields = dict(part.split("=", 1) for part in spec.split(",") if "=" in part)
    if fields.get("type", "volume") != "bind":
        return None
    return fields.get("src") or fields.get("source") or ""


def _bind_problem(source: str, runs: Path) -> str | None:
    if NAMED_VOLUME.match(source) or source == "$RUN_DIR" or source.startswith(("$RUN_DIR/", "${RUN_DIR}")):
        return None
    if "$" in source or source.startswith("~") or not os.path.isabs(source):
        return f"bind mount {source!r} is not an absolute path inside runs/"
    if not Path(os.path.normpath(source)).is_relative_to(runs):
        return f"bind mount {source!r} is outside runs/"
    return None
