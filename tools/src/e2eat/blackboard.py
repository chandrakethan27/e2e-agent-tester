"""Findings and messages on the blackboard: ids, queries, and cross-examination status changes."""

from __future__ import annotations

import re
from pathlib import Path

from .jsonio import read_json, read_json_or, write_json

SEVERITIES = ("critical", "high", "medium", "low", "info")
FINDING_STATUSES = ("open", "confirmed", "disputed", "dropped")
CHALLENGE_CONFIDENCE = 0.6
_FINDING_ID = re.compile(r"^F-[a-z0-9-]+-\d{3}$")


def short_name(agent: str) -> str:
    return agent.removesuffix("-agent")


def severity_rank(finding: dict) -> int:
    severity = finding.get("severity")
    return SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)


def _board(run_dir: Path) -> Path:
    return Path(run_dir) / "blackboard"


def _next_number(run_dir: Path, prefix: str) -> int:
    pattern = re.compile(rf"^{re.escape(prefix)}(\d{{3}})\.json$")
    numbers = [
        int(m[1])
        for sub in ("findings", "messages", "invalid")
        for path in (_board(run_dir) / sub).glob(f"{prefix}*.json")
        if (m := pattern.match(path.name))
    ]
    return max(numbers, default=0) + 1


def next_finding_id(run_dir: Path, agent: str) -> str:
    prefix = f"F-{short_name(agent)}-"
    return f"{prefix}{_next_number(run_dir, prefix):03d}"


def next_message_id(run_dir: Path, agent: str) -> str:
    prefix = f"Q-{short_name(agent)}-"
    return f"{prefix}{_next_number(run_dir, prefix):03d}"


def _load_dir(directory: Path) -> list[dict]:
    documents = (read_json_or(path, None) for path in sorted(directory.glob("*.json")))
    return [doc for doc in documents if isinstance(doc, dict) and "id" in doc]


def load_findings(run_dir: Path) -> list[dict]:
    return _load_dir(_board(run_dir) / "findings")


def load_messages(run_dir: Path) -> list[dict]:
    return _load_dir(_board(run_dir) / "messages")


def challengeable(findings: list[dict], limit: int) -> list[dict]:
    """Open findings that matter most or that the owner was unsure about, most severe first."""
    picked = [
        f for f in findings
        if f.get("status") == "open"
        and (f.get("severity") in ("critical", "high") or f.get("confidence", 1) < CHALLENGE_CONFIDENCE)
    ]
    picked.sort(key=lambda f: (severity_rank(f), f.get("confidence", 1), f["id"]))
    return picked[:limit]


def _finding_path(run_dir: Path, finding_id: str) -> Path:
    path = _board(run_dir) / "findings" / f"{finding_id}.json"
    if not _FINDING_ID.match(finding_id) or not path.exists():
        raise ValueError(f"unknown finding {finding_id!r}")
    return path


def update_finding(run_dir: Path, finding_id: str, **fields) -> dict:
    if "status" in fields and fields["status"] not in FINDING_STATUSES:
        raise ValueError(f"unknown finding status {fields['status']!r}")
    path = _finding_path(run_dir, finding_id)
    data = read_json(path)
    data.update({key: value for key, value in fields.items() if value is not None})
    write_json(path, data)
    return data


def apply_crossexam(run_dir: Path) -> dict[str, int]:
    """Apply skeptic challenges (open → disputed) and rulings (→ confirmed/dropped). Safe to run repeatedly."""
    facts = _board(run_dir) / "facts"
    counts = {"disputed": 0, "confirmed": 0, "dropped": 0, "unknown": 0}
    for item in read_json_or(facts / "skeptic-challenges.json", {}).get("challenges", []):
        try:
            current = read_json(_finding_path(run_dir, item["finding_id"]))
        except ValueError:
            counts["unknown"] += 1
            continue
        if current.get("status") == "open":
            update_finding(run_dir, item["finding_id"], status="disputed", challenge=item["challenge"])
            counts["disputed"] += 1
    for item in read_json_or(facts / "skeptic-rulings.json", {}).get("rulings", []):
        try:
            update_finding(run_dir, item["finding_id"], status=item["ruling"], ruling_reason=item["reason"])
        except ValueError:
            counts["unknown"] += 1
            continue
        counts[item["ruling"]] += 1
    return counts


def finalize_findings(run_dir: Path) -> dict[str, int]:
    """Close cross-examination: open → confirmed; unruled disputes stand only if rebutted and not conceded."""
    counts = {"confirmed": 0, "dropped": 0}
    for f in load_findings(run_dir):
        if f.get("status") == "open":
            update_finding(run_dir, f["id"], status="confirmed")
            counts["confirmed"] += 1
        elif f.get("status") == "disputed":
            keep = bool(f.get("rebuttal")) and not f.get("conceded", False)
            reason = "rebuttal stood without a skeptic ruling" if keep else "challenge unanswered or conceded"
            update_finding(run_dir, f["id"], status="confirmed" if keep else "dropped", ruling_reason=f.get("ruling_reason") or reason)
            counts["confirmed" if keep else "dropped"] += 1
    return counts
