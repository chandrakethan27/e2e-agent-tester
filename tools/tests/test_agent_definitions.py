"""Agent definitions stay consistent with the code that schedules and scores them."""

import re
from pathlib import Path

import pytest

from e2eat.score import DIMENSION_AGENTS
from e2eat.squad import RUNTIME_AGENTS, STATIC_AGENTS

ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = ROOT / ".claude" / "agents"
PIPELINE_AGENTS = {"recon-agent", "runner-agent", "skeptic-agent", "use-case-strategist", "report-writer"}
KNOWN_TOOLS = {"Bash", "Read", "Write", "Edit", "Grep", "Glob", "WebSearch", "WebFetch", "Skill"}


def frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, f"{path.name} has no frontmatter"
    fields = dict(line.split(": ", 1) for line in m[1].splitlines() if ": " in line)
    return fields, m[2]


def all_agent_names() -> list[str]:
    names = set(RUNTIME_AGENTS) | set(STATIC_AGENTS) | PIPELINE_AGENTS
    for agents in DIMENSION_AGENTS.values():
        names |= set(agents)
    return sorted(names)


@pytest.mark.parametrize("name", all_agent_names())
def test_agent_definition(name):
    fields, body = frontmatter(AGENTS_DIR / f"{name}.md")
    assert fields["name"] == name
    assert len(fields["description"]) > 40
    assert {tool.strip() for tool in fields["tools"].split(",")} <= KNOWN_TOOLS
    assert "references/agent-contract.md" in body


def test_no_unexpected_agent_files():
    assert {p.stem for p in AGENTS_DIR.glob("*.md")} == set(all_agent_names())


def test_contract_documents_the_finding_format():
    contract = (ROOT / ".claude/skills/evaluate/references/agent-contract.md").read_text()
    for word in ("next-id", "evidence", "confidence", "rebuttal", "conceded", "Never run the evaluated project"):
        assert word in contract


PROMPTS = sorted(AGENTS_DIR.glob("*.md")) + [ROOT / ".claude/skills/evaluate/references/agent-contract.md", ROOT / ".claude/skills/evaluate/SKILL.md"]


@pytest.mark.parametrize("path", PROMPTS)
def test_git_on_the_repo_goes_through_the_hardened_wrapper(path):
    # Host git on an evaluated repo can run repo-controlled config (core.fsmonitor) and, without a ceiling,
    # walks up into this tool's own repo. Only `./bin/e2eat git` is safe.
    assert "git -C $RUN_DIR/repo" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", PROMPTS)
def test_repo_compose_files_are_never_executed(path):
    text = path.read_text(encoding="utf-8")
    assert "docker compose -p" not in text and "up -d --build" not in text


def test_settings_guard_hook_and_secret_denies():
    import json

    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    hooks = settings["hooks"]["PreToolUse"]
    assert any(h["matcher"] == "Bash" and "e2eat guard" in h["hooks"][0]["command"] for h in hooks)
    assert "Read(./secrets.env)" in settings["permissions"]["deny"]
