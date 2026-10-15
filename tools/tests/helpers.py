"""Builders for blackboard documents shared by tests."""

import json
from pathlib import Path


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def finding(**overrides) -> dict:
    base = {
        "id": "F-security-001",
        "agent": "security-agent",
        "dimension": "security",
        "severity": "high",
        "title": "SQL injection in /search",
        "claim": "q is concatenated into SQL",
        "evidence": ["blackboard/evidence/security-agent/repro-001.txt"],
        "confidence": 0.9,
        "status": "open",
    }
    return base | overrides


def add_finding(run_dir: Path, with_evidence: bool = True, **overrides) -> dict:
    data = finding(**overrides)
    if with_evidence:
        for ref in data["evidence"]:
            target = run_dir / ref.split("#")[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("evidence\n")
    write_json(run_dir / "blackboard" / "findings" / f"{data['id']}.json", data)
    return data
