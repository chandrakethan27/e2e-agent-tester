"""JSON helpers: atomic writes so a crashed writer never leaves half a file on the blackboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_json_or(path: Path, default: Any) -> Any:
    try:
        return read_json(path)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
