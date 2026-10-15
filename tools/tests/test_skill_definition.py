"""The orchestrator skill references every pipeline agent and the CLI commands it relies on."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "evaluate" / "SKILL.md"
PIPELINE_AGENTS = ("recon-agent", "runner-agent", "skeptic-agent", "use-case-strategist", "report-writer", "perf-agent", "functional-tester")
COMMANDS = ("doctor", "sandbox stale", "init", "phase", "squad", "validate", "messages", "findings", "apply-crossexam",
            "finalize-findings", "sandbox teardown", "score", "redact", "render")


def test_skill_frontmatter_and_references():
    text = SKILL.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m
    fields = dict(line.split(": ", 1) for line in m[1].splitlines() if ": " in line)
    assert fields["name"] == "evaluate"
    assert "argument-hint" in fields
    body = m[2]
    for agent in PIPELINE_AGENTS:
        assert agent in body, agent
    for command in COMMANDS:
        assert f"./bin/e2eat {command}" in body, command
