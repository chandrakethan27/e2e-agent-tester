"""PreToolUse guard: refuse tool calls that would expose the host to evaluated code or leak secrets.

Agents read untrusted repo text, so a prompt injection could ask them to mount the home folder, exfiltrate
secrets.env, run a repo's compose file or tamper with the scoring ledger. This guard makes the e2eat CLI the
only route for those actions. It is defence in depth, not a sandbox: the real isolation is Docker plus the
validation inside the e2eat CLI. It fails closed: a command it cannot analyse is blocked.

Bash commands are split quote-aware (including ``$(...)``, backticks, subshells, heredocs, ``sh -c`` and common
wrappers such as ``sudo``/``env``/``timeout``/``xargs``) and every resulting simple command is checked.
"""

from __future__ import annotations

import ipaddress
import os
import posixpath
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import UNSAFE_FLAGS

MAX_DEPTH = 6
LOCAL_NAMES = {"localhost", "host.docker.internal", "ip6-localhost"}
SECRET_NAMES = {"secrets.env", ".secrets.env"}
_SECRETS_FILE = re.compile(r"(?<![\w-])\.?secrets\.env(?![\w.-])|(?<![\w-])\.secrets\.d(?![\w-])")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_SUBST = "$__SUB__"
_REPO_PATH = re.compile(r"(?:^|[/=:])runs/[^/\s]+/repo(?:/|$)|\$\{?RUN_DIR\}?/repo(?:/|$)")
_RUNS_PATH = re.compile(r"(?<![\w.-])runs/|\$\{?RUN_DIR\}?|/runs/")
_KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "in", "!", "{", "}", "time", "case", "esac"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_SECRET_BODY = re.compile(
    r"(?:open|Path|read_text|read_bytes|readlines|dotenv_values|load_dotenv|parse_env_file|readFileSync|File\.read"
    r"|system|run|call|Popen|check_output|exec\w*)\s*\([^)\n]*secrets\.env"
)
_SECRET_SUBSTITUTION = re.compile(r"<\s*\S*secrets\.env|\$\([^)]*secrets\.env|`[^`]*secrets\.env")
# Programs that can read, copy or send a file. Mentions in prose (heredoc data, docs being written) are fine.
_FILE_READERS = {
    "cat", "less", "more", "head", "tail", "cp", "mv", "scp", "rsync", "curl", "wget", "nc", "ncat", "base64", "xxd",
    "od", "strings", "grep", "egrep", "fgrep", "rg", "sed", "awk", "sort", "uniq", "cut", "tr", "tee", "tar", "zip",
    "gzip", "open", "source", ".", "node", "perl", "ruby", "php", "bash", "sh", "zsh", "jq", "diff", "cmp", "dd", "ln",
    "nl", "xargs", "env", "command", "docker", "podman", "uv", "uvx", "find", "tac", "rev", "paste", "column", "fold",
    "fmt", "pr", "hexdump", "zcat", "openssl", "ssh", "sftp", "ftp", "vi", "vim", "nano", "bat", "lsof", "eval",
}
_SENSITIVE_HOME = (
    ".ssh", ".aws", ".gnupg", ".config/gh", ".docker/config.json", ".npmrc", ".netrc", ".gitconfig", ".zshrc", ".zprofile",
    ".bashrc", ".bash_profile", ".profile", "Library/LaunchAgents", ".claude/settings.json", ".claude/settings.local.json",
)

_WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
    "doas": {"-u", "-C"},
    "command": set(), "builtin": set(), "exec": {"-a"}, "nohup": set(), "time": set(), "setsid": set(), "caffeinate": set(),
    "nice": {"-n"}, "ionice": {"-c", "-n", "-p"}, "stdbuf": {"-i", "-o", "-e"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "env": {"-u", "-C", "-S"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s", "-i"},
}
_FETCH_TOOLS = {"curl", "wget"}
_NETWORK_TOOLS = {"nc", "ncat", "netcat", "socat", "telnet", "ssh", "scp", "sftp", "ftp", "tftp", "http", "https", "httpie", "xh", "aria2c", "lwp-request"}
_INTERPRETERS = {"node", "nodejs", "deno", "bun", "ruby", "perl", "php", "java", "lua", "Rscript", "sh", "bash", "zsh", "dash", "ksh",
                 "source", ".", "osascript"}
_BUILD_TOOLS = {"uv", "uvx", "npx", "npm", "pnpm", "yarn", "go", "cargo", "make", "gradle", "mvn", "pip", "pip3", "poetry", "bundle", "rake",
                "composer", "dotnet", "tox", "pytest"}
# Options that take a value. Mis-classifying a flag as value-taking would swallow the URL and hide it, so the short sets
# only hold letters that are unambiguous for that tool.
_LONG_VALUE_OPTS = {
    "--header", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii", "--request", "--output", "--user",
    "--user-agent", "--referer", "--cookie", "--cookie-jar", "--form", "--form-string", "--upload-file", "--max-time", "--connect-timeout",
    "--write-out", "--retry", "--retry-delay", "--retry-max-time", "--cacert", "--cert", "--key", "--limit-rate", "--output-document",
    "--directory-prefix", "--post-data", "--post-file", "--timeout", "--tries", "--wait", "--range", "--max-redirs", "--json",
}
_SHORT_VALUE_LETTERS = {"curl": set("HdXouAebcFTmwErCPUtyYz"), "wget": set("OoPeUTtwBl")}
_FETCH_REDIRECTING = {
    "curl": {"--resolve", "--connect-to", "-x", "--proxy", "--preproxy", "-K", "--config", "--proxy-header"},
    "wget": {"--proxy", "-i", "--input-file", "-e", "--execute", "--config"},
}
_DOCKER_GLOBAL_VALUE = {"--context", "-c", "-H", "--host", "--config", "-l", "--log-level", "--tlscacert", "--tlscert", "--tlskey"}
_DOCKER_PLAIN_OK = {
    "ps", "logs", "stats", "inspect", "top", "port", "info", "version", "images", "exec", "stop", "start", "restart", "kill", "rm",
    "rmi", "wait", "pause", "unpause", "pull", "events", "diff", "history",
}
_DOCKER_GROUP_OK = {
    "container": {"ls", "list", "ps", "inspect", "logs", "stats", "top", "port", "stop", "start", "restart", "kill", "rm", "wait", "pause", "unpause", "exec", "diff", "cp"},
    "image": {"ls", "list", "inspect", "history", "pull", "rm"},
    "network": {"ls", "list", "inspect", "rm"},
    "volume": {"ls", "list", "inspect", "rm"},
    "system": {"df", "info", "events"},
    "compose": {"ps", "logs", "ls", "version", "images", "top"},
    "buildx": {"ls", "inspect", "version"},
}
_DOCKER_NEEDS_E2EAT_TARGET = {"exec", "stop", "start", "restart", "kill", "rm", "pause", "unpause", "wait"}
_DOCKER_MUTATING = {"stop", "start", "restart", "kill", "rm", "rmi", "pause", "unpause"}
_DOCKER_PROGS = {"docker", "podman", "nerdctl"}
_SANDBOX_HINT = "use ./bin/e2eat sandbox build/run (evaluated services, k6, test runs) or ./bin/e2eat scan"


@dataclass
class _Cmd:
    raw: str
    text: str  # raw with every substitution replaced by a placeholder, for word splitting
    heredoc: str = ""
    subs: list[str] = field(default_factory=list)


class _TooDeep(Exception):
    pass


def check_command(command: str, project_root: Path) -> str | None:
    """Return why the command must be blocked, or None to allow it."""
    root = Path(project_root)
    try:
        return _check_script(command.replace("\\\n", " "), root, {}, 0)
    except _TooDeep:
        return "command nesting is too deep to analyse"
    except Exception as exc:  # fail closed: never let a parser bug turn into a free pass
        return f"guard could not analyse this command ({type(exc).__name__}); simplify it or use ./bin/e2eat"


# ---------------------------------------------------------------------------------------------------------------------
# Parsing


def _match_close(script: str, start: int, opener: str, closer: str) -> int:
    """Index of the closer matching the opener at script[start] (quote aware); -1 when unbalanced."""
    depth, i, quote = 0, start, None
    while i < len(script):
        c = script[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = None
        elif c == "\\":
            i += 1
        elif c in "'\"":
            quote = c
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split(script: str, depth: int = 0) -> list[_Cmd]:
    if depth > MAX_DEPTH:
        raise _TooDeep
    cmds: list[_Cmd] = []
    raw: list[str] = []
    text: list[str] = []
    subs: list[str] = []
    pending: list[tuple[str, bool]] = []
    quote: str | None = None
    i, n = 0, len(script)

    def flush() -> _Cmd | None:
        nonlocal raw, text, subs
        r, t = "".join(raw).strip(), "".join(text).strip()
        cmd = _Cmd(r, t, subs=subs) if r else None
        raw, text, subs = [], [], []
        if cmd:
            cmds.append(cmd)
        return cmd

    def put(chunk: str) -> None:
        raw.append(chunk)
        text.append(chunk)

    def add_sub(inner: str, lead: int, end: int) -> None:
        subs.append(inner)
        cmds.extend(_split(inner, depth + 1))
        raw.append(script[lead:end])
        text.append(_SUBST)

    while i < n:
        c = script[i]
        nxt = script[i + 1] if i + 1 < n else ""
        if quote == "'":
            put(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            put(script[i:i + 2])
            i += 2
            continue
        if c == "$" and nxt == "(":
            end = _match_close(script, i + 1, "(", ")")
            if end < 0:
                raise ValueError("unbalanced $(")
            add_sub(script[i + 2:end], i, end + 1)
            i = end + 1
            continue
        if c == "`":
            end = script.find("`", i + 1)
            if end < 0:
                raise ValueError("unbalanced backtick")
            add_sub(script[i + 1:end], i, end + 1)
            i = end + 1
            continue
        if quote == '"':
            put(c)
            if c == '"':
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            put(c)
            i += 1
            continue
        if c in "<>" and nxt == "(":
            end = _match_close(script, i + 1, "(", ")")
            if end < 0:
                raise ValueError("unbalanced process substitution")
            add_sub(script[i + 2:end], i, end + 1)
            i = end + 1
            continue
        if c == "#" and (i == 0 or script[i - 1] in " \t\n;&|("):
            end = script.find("\n", i)
            i = n if end < 0 else end
            continue
        if c == "<" and nxt == "<" and script[i + 2:i + 3] != "<":
            m = _HEREDOC.match(script, i)
            if m:
                pending.append((m.group(3), m.group(1) == "-"))
                put(m.group(0))
                i = m.end()
                continue
        if c == "\n":
            cmd = flush()
            i += 1
            if pending:
                bodies = []
                for delim, strip in pending:
                    lines = []
                    while i < n:
                        end = script.find("\n", i)
                        line = script[i:] if end < 0 else script[i:end]
                        i = n if end < 0 else end + 1
                        if (line.strip() if strip else line) == delim:
                            break
                        lines.append(line)
                    bodies.append("\n".join(lines))
                pending = []
                if cmd:
                    cmd.heredoc = "\n".join(bodies)
            continue
        if c in ";|(){}" or (c == "&" and nxt != ">" and (i == 0 or script[i - 1] not in "<>")):
            if c in "{}":  # only a grouping brace when standing alone as a word; otherwise literal text
                prev = script[i - 1] if i else " "
                if not (prev in " \t\n;(" and nxt in " \t\n"):
                    put(c)
                    i += 1
                    continue
            flush()
            i += 2 if script[i:i + 2] in ("&&", "||", "|&") else 1
            continue
        put(c)
        i += 1
    flush()
    return cmds


def _words(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _expand(word: str, env: dict[str, str]) -> str:
    return _VAR.sub(lambda m: env.get(m.group(1) or m.group(2), m.group(0)), word)


# ---------------------------------------------------------------------------------------------------------------------
# Rules


def _check_script(script: str, root: Path, env: dict[str, str], depth: int) -> str | None:
    env = dict(env)
    for cmd in _split(script, depth):
        if reason := _check_cmd(cmd, root, env, depth):
            return reason
    return None


def _is_own_e2eat(word: str, root: Path) -> bool:
    word = word.replace("${CLAUDE_PROJECT_DIR}", "$CLAUDE_PROJECT_DIR")
    if word in ("./bin/e2eat", "bin/e2eat", "$CLAUDE_PROJECT_DIR/bin/e2eat"):
        return True
    return os.path.isabs(word) and os.path.normpath(word) == str(root / "bin" / "e2eat")


def _check_cmd(cmd: _Cmd, root: Path, env: dict[str, str], depth: int) -> str | None:
    words = _words(cmd.text)
    local = dict(env)
    while words and _ENV_ASSIGNMENT.match(words[0]):
        key, _, value = words.pop(0).partition("=")
        local[key] = _expand(value, local)
    while words and words[0] in _KEYWORDS:
        words.pop(0)
    if not words:  # a bare assignment: remember it for later commands of the same script
        env.update({k: v for k, v in local.items() if k not in env or env[k] != v})
        return None
    if words[0] == "export":
        for word in words[1:]:
            if "=" in word:
                key, _, value = word.partition("=")
                env[key] = _expand(value, env)
        return None
    words = [_expand(w, local) for w in words]

    via_xargs = False
    wrappers: set[str] = set()
    for _ in range(6):
        prog = Path(words[0]).name
        if prog not in _WRAPPERS:
            break
        value_opts = _WRAPPERS[prog]
        via_xargs = via_xargs or prog == "xargs"
        wrappers.add(prog)
        words = words[1:]
        while words and (words[0].startswith("-") or (prog == "env" and _ENV_ASSIGNMENT.match(words[0]))):
            if prog == "env" and _ENV_ASSIGNMENT.match(words[0]):
                key, _, value = words[0].partition("=")
                local[key] = value
                words = words[1:]
            else:
                words = words[2:] if words[0] in value_opts else words[1:]
        if prog == "timeout" and words:
            words = words[1:]  # the duration
        if not words:
            return None

    if _is_own_e2eat(words[0], root):
        return None
    prog = Path(words[0]).name
    if words[0].startswith("$"):
        name = words[0].lstrip("${").rstrip("}")
        if name != "B":  # $B is the gstack browse binary, set by the agents' own prompts
            return "the command name comes from a variable or substitution; write the program out"
        return None
    if words[0].endswith("/bin/e2eat"):
        return "only this project's own bin/e2eat is trusted"

    if prog in _SHELLS or prog == "eval":
        script = None
        if prog == "eval":
            script = " ".join(words[1:])
        else:
            for idx, word in enumerate(words[1:], 1):
                if word.startswith("-") and not word.startswith("--") and "c" in word[1:] and idx + 1 < len(words):
                    script = words[idx + 1]
                    break
        if script is not None and (reason := _check_script(script, root, local, depth + 1)):
            return reason
        if cmd.heredoc and (reason := _check_script(cmd.heredoc, root, local, depth + 1)):
            return reason

    if cmd.heredoc and (prog.startswith("python") or prog in _INTERPRETERS) and _SECRET_BODY.search(cmd.heredoc):
        return "secrets.env may only be read by ./bin/e2eat (sandbox env, redact)"

    if reason := _check_repo_exec(prog, words):
        return reason
    if _SECRETS_FILE.search(cmd.raw) and (
        prog in _FILE_READERS or wrappers & _FILE_READERS or prog.startswith("python") or _SECRET_SUBSTITUTION.search(cmd.raw)
    ):
        return "secrets.env may only be read by ./bin/e2eat (sandbox env, redact)"
    if prog in _DOCKER_PROGS or prog in ("docker-compose", "podman-compose"):
        return _check_docker(words, prog, root)
    if prog in _NETWORK_TOOLS:
        return f"{prog} is blocked: agents have no reason to open arbitrary connections"
    if prog in _FETCH_TOOLS:
        if via_xargs:
            return f"{prog} through xargs cannot be checked; pass a literal local URL"
        return _check_fetch(prog, words)
    if prog == "git":
        return _check_git(words)
    if prog in ("cd", "pushd") and any(_REPO_PATH.search(w) for w in words[1:]):
        return "do not cd into the evaluated repo (the shell keeps the directory and git or tools would then act on untrusted code)"
    return None


def _check_repo_exec(prog: str, words: list[str]) -> str | None:
    msg = "never run the evaluated project's code on the host; run it in a container via ./bin/e2eat sandbox"
    if _REPO_PATH.search(words[0]):
        return msg
    args = [w for w in words[1:] if not w.startswith("-")]
    if prog.startswith("python") or prog in _INTERPRETERS:
        skip = 1 if "-m" in words[1:] else 0
        script = args[skip:skip + 1]
        if script and _REPO_PATH.search(script[0]):
            return msg
    if prog in _BUILD_TOOLS and any(_REPO_PATH.search(w) for w in words[1:]):
        return msg
    return None


def _check_docker(words: list[str], prog: str, root: Path) -> str | None:
    runs = root / "runs"
    if prog in ("docker-compose", "podman-compose"):
        args = words[1:]
        while args and args[0].startswith("-"):
            args = args[2:] if args[0] in ("-f", "-p", "--file", "--project-name", "--profile") else args[1:]
        return None if args[:1] and args[0] in _DOCKER_GROUP_OK["compose"] else "repo compose files are never executed; recreate services with ./bin/e2eat sandbox build/run"
    args = words[1:]
    while args and args[0].startswith("-"):
        args = args[2:] if args[0] in _DOCKER_GLOBAL_VALUE else args[1:]
    if not args:
        return None
    if UNSAFE_FLAGS.search(" ".join(words)):
        return "unsafe docker options (privileged, host namespaces, extra capabilities, devices or the Docker socket)"
    sub = args[0]
    rest = args[1:]
    if "prune" in args:
        return "docker prune would remove resources of other projects; use ./bin/e2eat sandbox teardown"
    if sub in _DOCKER_GROUP_OK:
        action = next((a for a in rest if not a.startswith("-")), "")
        if action not in _DOCKER_GROUP_OK[sub]:
            return f"docker {sub} {action} is not allowed here; {_SANDBOX_HINT}"
        if sub == "container":
            sub, rest = action, [a for a in rest if a != action]
        elif sub == "image" and action == "rm":
            sub, rest = "rmi", [a for a in rest if a != action]
        else:
            return None
    elif sub not in _DOCKER_PLAIN_OK and sub != "cp":
        return f"docker {sub} is not allowed from agents; {_SANDBOX_HINT}"
    if sub in _DOCKER_MUTATING and any("__SUB__" in a or "`" in a for a in rest):
        return f"docker {sub} with a command substitution could hit other containers; name the e2eat-<run-id>-* container"
    if sub in _DOCKER_NEEDS_E2EAT_TARGET and not any("e2eat-" in a or a.startswith("$") for a in rest):
        return f"docker {sub} may only target e2eat-<run-id>-* containers"
    if sub == "cp":
        for arg in (a for a in rest if not a.startswith("-") or a == "-"):
            if re.match(r"^[A-Za-z0-9][\w.-]*:", arg):
                continue  # container:path
            if problem := _host_path_problem(arg, runs):
                return f"docker cp {problem}"
    return None


def _host_path_problem(path: str, runs: Path) -> str | None:
    if path.startswith(("$RUN_DIR/", "${RUN_DIR}/")):
        rel = posixpath.normpath(path.split("/", 1)[1])
        return None if not (rel.startswith("..") or os.path.isabs(rel)) else f"path {path!r} escapes the run dir"
    if path == "$RUN_DIR" or "$" in path or path.startswith("~") or not os.path.isabs(path):
        return f"path {path!r} must be an absolute path inside runs/"
    if not Path(os.path.realpath(path)).is_relative_to(os.path.realpath(runs)):
        return f"path {path!r} is outside runs/"
    return None


def _host_of(target: str) -> str:
    rest = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", target.strip())
    rest = re.split(r"[/?#]", rest, maxsplit=1)[0].rsplit("@", 1)[-1]
    if rest.startswith("["):
        return rest[1:rest.find("]")] if "]" in rest else rest[1:]
    return rest.split(":", 1)[0] if rest.count(":") == 1 else rest


def _is_local(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host in LOCAL_NAMES or host.endswith(".localhost"):
        return True
    try:
        addr = ipaddress.ip_address(int(host, 0)) if re.fullmatch(r"(?:0x[0-9a-f]+|\d+)", host) else ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_unspecified


def _takes_next_arg(prog: str, arg: str) -> bool:
    """For a short-option cluster such as -sSo: does the first value letter end the cluster (value is the next arg)?"""
    letters = _SHORT_VALUE_LETTERS[prog]
    for idx, ch in enumerate(arg[1:]):
        if ch in letters:
            return idx == len(arg) - 2
    return False


def _check_fetch(prog: str, words: list[str]) -> str | None:
    args = words[1:]
    targets: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        head = arg.split("=", 1)[0]
        if head in _FETCH_REDIRECTING[prog]:
            return f"{prog} {head} can send traffic to external hosts"
        if head == "--url":
            targets.append(arg.split("=", 1)[1] if "=" in arg else (args[i + 1] if i + 1 < len(args) else ""))
            i += 1 if "=" in arg else 2
        elif arg in _LONG_VALUE_OPTS:
            i += 2
        elif arg.startswith("--") or arg == "-":
            i += 1
        elif arg.startswith("-"):
            i += 2 if _takes_next_arg(prog, arg) else 1
        else:
            targets.append(arg)
            i += 1
    for target in targets:
        host = _host_of(target)
        if not host:
            continue
        if "$" in host:
            return f"{prog} host {host!r} is not a literal; use a literal 127.0.0.1/localhost URL"
        if not _is_local(host):
            return f"{prog} to external host {host} is blocked; use WebFetch or gh api for public data"
    return None


def _git_args(words: list[str]) -> list[str]:
    out, skip = [], False
    for word in words[1:]:
        if skip:
            skip = False
        elif word in ("-m", "--message", "-F", "--file"):
            skip = True
        elif not word.startswith("--message="):
            out.append(word)
    return out


def _check_git(words: list[str]) -> str | None:
    if any(_RUNS_PATH.search(arg) for arg in _git_args(words)):
        return "run git on evaluated code only via ./bin/e2eat git <run-dir> ..."
    return None


# ---------------------------------------------------------------------------------------------------------------------
# File tools (Read, Write, Edit, NotebookEdit, Grep, Glob)

_RUN_PROTECTED = {"finding-status.json", "scores.json", "run.json"}
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
FILE_TOOLS = _WRITE_TOOLS | {"Read", "Grep", "Glob"}


def check_file_access(tool: str, tool_input: dict, project_root: Path, *, subagent: bool = False) -> str | None:
    """Block secret reads, writes to the integrity files e2eat owns, edits of the evaluated repo, and risky home paths."""
    root = os.path.realpath(project_root)
    candidates: list[str] = [v for k in ("file_path", "notebook_path", "path", "glob") if isinstance(v := tool_input.get(k), str)]
    home = os.path.realpath(os.path.expanduser("~"))
    for raw in candidates:
        expanded = os.path.expanduser(raw)
        path = os.path.realpath(expanded if os.path.isabs(expanded) else os.path.join(root, expanded))
        name = os.path.basename(path)
        if name in SECRET_NAMES or os.path.basename(raw) in SECRET_NAMES or f"{os.sep}.secrets.d{os.sep}" in path + os.sep:
            return "secrets.env may only be read or written by ./bin/e2eat (sandbox env, redact)"
        rel_home = os.path.relpath(path, home) if path == home or path.startswith(home + os.sep) else None
        if rel_home and any(rel_home == s or rel_home.startswith(s + os.sep) for s in _SENSITIVE_HOME):
            return f"{raw} holds credentials or shell/agent configuration; agents may not touch it"
        if tool not in _WRITE_TOOLS:
            continue
        runs = os.path.join(root, "runs")
        if path.startswith(runs + os.sep):
            parts = os.path.relpath(path, runs).split(os.sep)
            if len(parts) == 2 and parts[1] in _RUN_PROTECTED:
                return f"{parts[1]} is owned by e2eat; use ./bin/e2eat (phase, agent, score, set-status, finalize-findings)"
            if len(parts) >= 3 and parts[1] == "repo" and parts[2] != ".e2eat":
                return "the evaluated repo is read-only; only repo/.e2eat/ may be written"
        elif subagent and not path.startswith(("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")):
            return "agents may only write inside runs/<run-id>/"
    return None
