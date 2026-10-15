"""Validate run artifacts against the JSON Schemas packaged with e2eat."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Iterator

from jsonschema import Draft202012Validator

SCHEMA_NAMES = ("run", "recon", "runtime", "finding", "message", "scores", "usecases", "report", "challenges", "rulings")
TOP_LEVEL = {"run.json": "run", "scores.json": "scores", "usecases.json": "usecases", "report.json": "report"}
FACTS = {"recon.json": "recon", "runtime.json": "runtime",
         "skeptic-challenges.json": "challenges", "skeptic-rulings.json": "rulings"}
QUARANTINABLE = ("finding", "message")
LINE_SUFFIX = re.compile(r"(#L?\d+(-L?\d+)?|:\d+(-\d+)?)$")


@dataclass(frozen=True)
class Issue:
    path: str  # relative to the run dir
    message: str


@cache
def load_schema(name: str) -> dict:
    if name not in SCHEMA_NAMES:
        raise ValueError(f"unknown schema {name!r}; choose from {', '.join(SCHEMA_NAMES)}")
    text = resources.files("e2eat").joinpath("schemas", f"{name}.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def validate_document(data: object, kind: str) -> list[str]:
    validator = Draft202012Validator(load_schema(kind))
    errors = sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def evidence_problem(run_dir: Path, ref: str) -> str | None:
    target = LINE_SUFFIX.sub("", ref)
    if not target or Path(target).is_absolute():
        return f"evidence must be a path relative to the run dir: {ref}"
    root = Path(run_dir).resolve()
    try:
        path = (root / target).resolve()
        if not path.is_relative_to(root):
            return f"evidence escapes the run dir: {ref}"
        if not path.exists():
            return f"evidence not found: {ref}"
    except (ValueError, OSError):
        return f"evidence path is invalid: {ref!r}"
    return None


def _identity_problems(data: dict, kind: str, stem: str) -> list[str]:
    problems = [] if data["id"] == stem else [f"id {data['id']} must match file name {stem}"]
    owner = data["agent"] if kind == "finding" else data["from"]
    prefix = f"{'F' if kind == 'finding' else 'Q'}-{owner.removesuffix('-agent')}-"
    if not data["id"].startswith(prefix):
        problems.append(f"id {data['id']} must start with {prefix}")
    return problems


def validate_file(run_dir: Path, rel: Path, kind: str, check_evidence: bool = False) -> list[str]:
    try:
        data = json.loads((run_dir / rel).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"invalid JSON: {exc}"]
    except OSError as exc:
        return [f"unreadable: {exc}"]
    errors = validate_document(data, kind)
    if errors or kind not in QUARANTINABLE:
        return errors
    errors = _identity_problems(data, kind, rel.stem)
    if kind == "finding" and check_evidence:
        errors += [problem for ref in data["evidence"] if (problem := evidence_problem(run_dir, ref))]
    return errors


def _documents(run_dir: Path) -> Iterator[tuple[Path, str]]:
    for name, kind in TOP_LEVEL.items():
        if (run_dir / name).exists():
            yield Path(name), kind
    board = run_dir / "blackboard"
    for name, kind in FACTS.items():
        if (board / "facts" / name).exists():
            yield Path("blackboard", "facts", name), kind
    for sub, kind in (("findings", "finding"), ("messages", "message")):
        for path in sorted((board / sub).glob("*.json")):
            yield path.relative_to(run_dir), kind


def validate_run(run_dir: Path, check_evidence: bool = False, quarantine: bool = False) -> list[Issue]:
    run_dir = Path(run_dir)
    issues: list[Issue] = []
    for rel, kind in list(_documents(run_dir)):
        errors = validate_file(run_dir, rel, kind, check_evidence)
        issues += [Issue(rel.as_posix(), error) for error in errors]
        if errors and quarantine and kind in QUARANTINABLE:
            shutil.move(run_dir / rel, run_dir / "blackboard" / "invalid" / rel.name)
    return issues
