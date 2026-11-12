"""Findings and messages on the blackboard: ids, queries, and cross-examination status changes."""

from __future__ import annotations

import re
from pathlib import Path

from .jsonio import read_json, read_json_or, read_json_strict, run_lock, write_json
from .validate import validate_document

SEVERITIES = ("critical", "high", "medium", "low", "info")
FINDING_STATUSES = ("open", "confirmed", "disputed", "dropped")
CHALLENGE_CONFIDENCE = 0.6
# Status is the orchestrator's call, not the agent's: it lives in this run-level ledger and overrides
# whatever an agent wrote into its own finding file.
STATUS_FILE = "finding-status.json"
ORCHESTRATOR_FIELDS = ("status", "challenge", "ruling_reason")
_FINDING_ID = re.compile(r"^F-[a-z0-9-]+-\d{3}$")


def short_name(agent: str) -> str:
    return agent.removesuffix("-agent")


def severity_rank(finding: dict) -> int:
    severity = finding.get("severity")
    return SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)


def _board(run_dir: Path) -> Path:
    return Path(run_dir) / "blackboard"


IDS_FILE = ".ids.json"


def _next_number(run_dir: Path, prefix: str) -> int:
    """Reserve the next number: two agents asking at once, or before writing their file, never get the same id."""
    pattern = re.compile(rf"^{re.escape(prefix)}(\d{{3}})\.json$")
    with run_lock(run_dir):
        issued = read_json_strict(Path(run_dir) / IDS_FILE, {}, dict)
        numbers = [
            int(m[1])
            for sub in ("findings", "messages", "invalid")
            for path in (_board(run_dir) / sub).glob(f"{prefix}*.json")
            if (m := pattern.match(path.name))
        ]
        number = max([*numbers, issued.get(prefix, 0)]) + 1
        write_json(Path(run_dir) / IDS_FILE, issued | {prefix: number})
    return number


def next_finding_id(run_dir: Path, agent: str) -> str:
    prefix = f"F-{short_name(agent)}-"
    return f"{prefix}{_next_number(run_dir, prefix):03d}"


def next_message_id(run_dir: Path, agent: str) -> str:
    prefix = f"Q-{short_name(agent)}-"
    return f"{prefix}{_next_number(run_dir, prefix):03d}"


def _load_dir(directory: Path) -> list[dict]:
    documents = (read_json_or(path, None) for path in sorted(directory.glob("*.json")))
    return [doc for doc in documents if isinstance(doc, dict) and "id" in doc]


def _status_ledger(run_dir: Path) -> dict:
    return read_json_strict(Path(run_dir) / STATUS_FILE, {}, dict)  # a corrupt ledger must stop scoring, not reset every finding to open


def load_findings(run_dir: Path) -> list[dict]:
    """Findings with their effective status: 'open' unless the orchestrator recorded otherwise."""
    ledger = _status_ledger(run_dir)
    return [
        {k: v for k, v in doc.items() if k not in ORCHESTRATOR_FIELDS} | {"status": "open"} | ledger.get(doc["id"], {})
        for doc in _load_dir(_board(run_dir) / "findings")
    ]


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
    changes = {key: value for key, value in fields.items() if value is not None}
    owned = {key: value for key, value in changes.items() if key in ORCHESTRATOR_FIELDS}
    with run_lock(run_dir):
        if owned:
            ledger = _status_ledger(run_dir)
            ledger[finding_id] = ledger.get(finding_id, {}) | owned
            write_json(Path(run_dir) / STATUS_FILE, ledger)
        data = read_json(path)
        data.update(changes)  # mirror orchestrator fields so agents reading the file see the challenge
        write_json(path, data)
    return next((f for f in load_findings(run_dir) if f["id"] == finding_id), data)


def apply_crossexam(run_dir: Path) -> dict[str, int]:
    """Apply skeptic challenges (open → disputed) and rulings (→ confirmed/dropped). Safe to run repeatedly."""
    facts = _board(run_dir) / "facts"
    challenges = _crossexam_items(facts / "skeptic-challenges.json", "challenges")
    rulings = _crossexam_items(facts / "skeptic-rulings.json", "rulings")  # both checked before anything changes
    status = {f["id"]: f["status"] for f in load_findings(run_dir)}
    counts = {"disputed": 0, "confirmed": 0, "dropped": 0, "unknown": 0}
    for item in challenges:
        if item["finding_id"] not in status:
            counts["unknown"] += 1
        elif status[item["finding_id"]] == "open":
            update_finding(run_dir, item["finding_id"], status="disputed", challenge=item["challenge"])
            counts["disputed"] += 1
    for item in rulings:
        if item["finding_id"] not in status:
            counts["unknown"] += 1
            continue
        update_finding(run_dir, item["finding_id"], status=item["ruling"], ruling_reason=item["reason"])
        counts[item["ruling"]] += 1
    return counts


def _crossexam_items(path: Path, kind: str) -> list[dict]:
    if not path.exists():
        return []
    data = read_json_or(path, None)
    errors = ["not valid JSON"] if data is None else validate_document(data, kind)
    if errors:
        raise ValueError(f"{path.name} is invalid ({errors[0]}); ask the skeptic to rewrite it")
    return data[kind]


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
