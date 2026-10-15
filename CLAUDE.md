# E2E Agent Tester

Claude Code-native multi-agent system: `/evaluate <repo>` builds, runs, tests and scores a repository, then reports enterprise readiness and where it can be used.

- Orchestrator: `.claude/skills/evaluate/SKILL.md`. Agents: `.claude/agents/*.md`. Shared agent rules: `.claude/skills/evaluate/references/agent-contract.md`.
- Deterministic helpers: `./bin/e2eat` (Python in `tools/`). Tests: `uv run --project tools pytest tools/tests -q`.
- Design: `docs/superpowers/specs/2026-10-15-e2e-agent-tester-design.md`. Plan: `docs/superpowers/plans/2026-10-15-e2e-agent-tester.md`.

## Rules
- Never run an evaluated project's code, package manager or build on the host — containers only. `.claude/settings.json` denies host package managers.
- Every Docker resource of a run carries `e2eat.run=<run-id>`; always finish with `./bin/e2eat sandbox teardown <run-dir>`.
- Scores come only from `./bin/e2eat score`; agents never write scores.
- New CLI command group: add `tools/src/e2eat/cli/<name>_cmds.py` with `register(sub)`; it is discovered automatically.
- New agent: add `.claude/agents/<name>.md` (frontmatter `name`, `description`, `tools`; body must point to the agent contract), wire it into `squad.py`/`score.py` if it covers a dimension, and extend `tools/tests/test_agent_definitions.py` expectations.
