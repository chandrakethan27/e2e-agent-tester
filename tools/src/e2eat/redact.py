"""Scrub secret values out of evidence and outputs before anything is rendered or shared."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MIN_SECRET_LEN = 4  # shorter values would shred ordinary text
NOT_SECRETS = {"true", "false", "null", "none", "yes", "no", "on", "off"}  # config literals, not credentials
OUTPUT_FILES = ("run.json", "scores.json", "finding-status.json", "usecases.json", "report.json", "report.md", "report.html")
EXTRA_DIRS = ("runtime-config", "repo/.e2eat")  # files agents generate outside the blackboard


def parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; inline ' #' comments end unquoted values; multi-line quoted values are unusable and come back empty."""
    secrets: dict[str, str] = {}
    lines = iter(Path(path).read_text(encoding="utf-8").splitlines())
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if value[:1] in ("'", '"'):
            quote = value[0]
            if len(value) >= 2 and value.endswith(quote):
                value = value[1:-1]
            else:
                for rest in lines:  # skip the rest of a multi-line value
                    if rest.rstrip().endswith(quote):
                        break
                value = ""
        else:
            value = value.split(" #", 1)[0].strip()
        secrets[key.strip()] = value
    return secrets


def _redactable(secrets: dict[str, str]) -> list[tuple[str, str]]:
    usable = [
        (key, value) for key, value in secrets.items()
        if len(value) >= MIN_SECRET_LEN and value.lower() not in NOT_SECRETS and not (value.isdigit() and len(value) < 8)
    ]
    return sorted(usable, key=lambda kv: len(kv[1]), reverse=True)  # longest first so containing secrets go whole


def redact_text(text: str, secrets: dict[str, str]) -> str:
    for key, value in _redactable(secrets):
        for form in {value, json.dumps(value)[1:-1]}:  # raw and JSON-escaped
            text = text.replace(form, f"[REDACTED:{key}]")
    return text


def _redact_json(data: Any, secrets: dict[str, str]) -> Any:
    if isinstance(data, str):
        return redact_text(data, secrets)
    if isinstance(data, list):
        return [_redact_json(item, secrets) for item in data]
    if isinstance(data, dict):
        return {key: _redact_json(value, secrets) for key, value in data.items()}
    return data


def _redact_bytes(raw: bytes, secrets: dict[str, str]) -> bytes:
    for key, value in _redactable(secrets):
        for form in {value, json.dumps(value)[1:-1]}:
            raw = raw.replace(form.encode("utf-8"), f"[REDACTED:{key}]".encode())
    return raw


def _redact_file(path: Path, secrets: dict[str, str]) -> bool:
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if path.suffix == ".json":
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # not valid JSON: fall back to byte replacement
        else:
            cleaned = _redact_json(data, secrets)
            if cleaned == data:
                return False
            path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return True
    cleaned_bytes = _redact_bytes(raw, secrets)
    if cleaned_bytes == raw:
        return False
    path.write_bytes(cleaned_bytes)
    return True


def redact_run(run_dir: Path, secrets: dict[str, str]) -> list[str]:
    run_dir = Path(run_dir)
    candidates = [p for p in sorted((run_dir / "blackboard").rglob("*")) if p.is_file() and not p.is_symlink()]
    for extra in EXTRA_DIRS:
        candidates += [p for p in sorted((run_dir / extra).rglob("*")) if p.is_file() and not p.is_symlink()]
    candidates += [run_dir / name for name in OUTPUT_FILES if (run_dir / name).is_file()]
    return [p.relative_to(run_dir).as_posix() for p in candidates if _redact_file(p, secrets)]
