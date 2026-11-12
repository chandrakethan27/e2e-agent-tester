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


# --------------------------------------------------------------------------- prompts must match the real CLI

import argparse
import json

from e2eat.cli import build_parser
from e2eat.validate import SCHEMA_NAMES, load_schema

PROMPTS = [SKILL, *sorted((ROOT / ".claude" / "agents").glob("*.md")), ROOT / ".claude" / "skills" / "evaluate" / "references" / "agent-contract.md"]
INVOCATION = re.compile(r"\./bin/e2eat ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?([^`→\n]*)")


def _subparsers(parser):
    action = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    return action.choices if action else {}


def _options(parser):
    return {s for a in parser._actions for s in a.option_strings}


def test_every_e2eat_invocation_in_the_prompts_exists():
    top = _subparsers(build_parser())
    problems = []
    for path in PROMPTS:
        for m in INVOCATION.finditer(path.read_text(encoding="utf-8")):
            cmd, second, rest = m[1], m[2], m[3]
            where = f"{path.name}: {m[0].strip()[:80]}"
            if cmd not in top:
                problems.append(f"unknown command - {where}")
                continue
            parser, subs = top[cmd], _subparsers(top[cmd])
            if subs and second:
                if second not in subs:
                    problems.append(f"unknown subcommand - {where}")
                    continue
                parser = subs[second]
            elif cmd == "schema" and second and second not in SCHEMA_NAMES:
                problems.append(f"unknown schema - {where}")
            if cmd == "git":
                continue  # everything after the run dir belongs to git
            flags = re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", re.split(r"\s--\s", rest)[0])
            problems += [f"unknown flag {f} - {where}" for f in flags if f not in _options(parser)]
    assert problems == []


def test_runtime_fields_named_in_prompts_exist_in_the_schema():
    properties = set(load_schema("runtime")["properties"])
    for path in PROMPTS:
        for m in re.finditer(r"runtime\.json` \(([^)]*)\)", path.read_text(encoding="utf-8")):
            fields = {f.strip(" `") for f in m[1].split(",")}
            assert fields <= properties, (path.name, fields - properties)


def test_skill_uses_the_new_orchestration_commands():
    body = SKILL.read_text(encoding="utf-8")
    for needle in ("squad $RUN_DIR --plan", "sandbox env $RUN_DIR --check", "static-only $RUN_DIR", "reconfigure $RUN_DIR",
                   "messages $RUN_DIR --expire", "finalize-findings $RUN_DIR --unruled keep", "sandbox stale --except", "teardown-active"):
        assert needle in body, needle


def test_assessing_agents_are_told_to_report_coverage():
    for name in ("functional-tester", "suite-runner", "security-agent", "perf-agent", "architecture-agent", "viability-agent", "runner-agent"):
        text = (ROOT / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
        assert '"coverage"' in text or "`coverage" in text, name
    contract = (ROOT / ".claude" / "skills" / "evaluate" / "references" / "agent-contract.md").read_text(encoding="utf-8")
    assert "Coverage report" in contract and "Who owns what" in contract


def test_no_prompt_still_uses_raw_docker_run_or_the_old_env_file():
    for path in PROMPTS:
        text = path.read_text(encoding="utf-8")
        assert "docker run " not in text.replace("`docker run`", ""), path.name
        assert "repo/.e2eat" not in text, path.name


def test_settings_wire_the_guard_to_every_tool_and_tear_down_on_session_end():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = {h["matcher"] for h in settings["hooks"]["PreToolUse"]}
    assert "Bash" in matchers and any("Write" in m and "Read" in m for m in matchers)
    assert "teardown-active" in settings["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
