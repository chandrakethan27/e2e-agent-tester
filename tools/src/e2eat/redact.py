"""Scrub secret values out of evidence and outputs before anything is rendered or shared."""

from __future__ import annotations

from pathlib import Path

MIN_SECRET_LEN = 4  # shorter values would shred ordinary text
OUTPUT_FILES = ("scores.json", "usecases.json", "report.json", "report.md", "report.html")


def parse_env_file(path: Path) -> dict[str, str]:
    secrets: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        secrets[key.strip()] = value
    return secrets


def redact_text(text: str, secrets: dict[str, str]) -> str:
    # Longest first so a secret that contains another is replaced whole.
    for key, value in sorted(secrets.items(), key=lambda kv: len(kv[1]), reverse=True):
        if len(value) >= MIN_SECRET_LEN:
            text = text.replace(value, f"[REDACTED:{key}]")
    return text


def _redact_file(path: Path, secrets: dict[str, str]) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False  # binary evidence (screenshots) cannot hold text secrets we could scrub
    cleaned = redact_text(text, secrets)
    if cleaned == text:
        return False
    path.write_text(cleaned, encoding="utf-8")
    return True


def redact_run(run_dir: Path, secrets: dict[str, str]) -> list[str]:
    run_dir = Path(run_dir)
    candidates = [p for p in sorted((run_dir / "blackboard").rglob("*")) if p.is_file() and not p.is_symlink()]
    candidates += [run_dir / name for name in OUTPUT_FILES if (run_dir / name).is_file()]
    return [p.relative_to(run_dir).as_posix() for p in candidates if _redact_file(p, secrets)]
