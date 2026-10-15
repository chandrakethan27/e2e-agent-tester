"""Machine-readable output: every command prints exactly one JSON document."""

from __future__ import annotations

import json
from typing import Any


def emit(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))
