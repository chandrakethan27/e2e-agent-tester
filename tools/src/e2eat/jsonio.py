"""JSON helpers: atomic writes and a run-level lock so a crash or a concurrent writer never corrupts the blackboard."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_MISSING = object()


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_json_or(path: Path, default: Any) -> Any:
    """Lenient: the default for a missing OR malformed file. Only for agent-written files that `validate` reports."""
    try:
        return read_json(path)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def read_json_strict(path: Path, default: Any = _MISSING, expect: type | tuple[type, ...] | None = None) -> Any:
    """The default only when the file is missing. A malformed file or a wrong top-level type is an error, never a silent default."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if default is _MISSING:
            raise
        return default
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if expect is not None and not isinstance(data, expect):
        names = " or ".join(t.__name__ for t in (expect if isinstance(expect, tuple) else (expect,)))
        raise ValueError(f"{path} must hold a JSON {names}, found {type(data).__name__}")
    return data


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")  # unique, so writers never share one
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Exclusive advisory lock. Do not nest on the same path: a second open file description would wait forever."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_lock(run_dir: Path):
    """Serialises every read-modify-write of run.json, the status ledger and the id counters of one run."""
    return file_lock(Path(run_dir) / ".e2eat.lock")
