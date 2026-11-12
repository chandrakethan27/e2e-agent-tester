# E2E Agent Tester

Claude Code-native multi-agent system: `/evaluate <repo>` builds, runs, tests and scores a repository, then reports enterprise readiness and where it can be used.

- Orchestrator: `.claude/skills/evaluate/SKILL.md`. Agents: `.claude/agents/*.md`. Shared agent rules: `.claude/skills/evaluate/references/agent-contract.md`.
- Deterministic helpers: `./bin/e2eat` (Python in `tools/`). Tests: `uv run --project tools pytest tools/tests -q`.
- Design: `docs/superpowers/specs/2026-10-15-e2e-agent-tester-design.md`. Plan: `docs/superpowers/plans/2026-10-15-e2e-agent-tester.md`.

## Rules
- Never run an evaluated project's code, package manager or build on the host — containers only. `.claude/settings.json` denies host package managers.
- Every Docker resource of a run carries `e2eat.run=<run-id>`; always finish with `./bin/e2eat sandbox teardown <run-dir>`. Exceptions: the live-view container/image (`e2eat.web=1`, built and run only by `./bin/e2eat web …`) and the shared Trivy cache volume. Agents never run raw `docker run/create/build/compose`: services, load tests and test runs go through `./bin/e2eat sandbox build|run`.
- Scores come only from `./bin/e2eat score`; agents never write scores. Finding status comes only from `finding-status.json` (written by `e2eat` on the orchestrator's behalf). Dimension coverage comes only from the `coverage` block in each agent's facts file; `score` fails closed on unresolved findings or corrupt files.
- The `PreToolUse` guard hook (`./bin/e2eat guard`) applies to this whole project, including you: it blocks reading the secrets files (`secrets.env`, `.secrets.d/`) outside e2eat, external curl/wget, raw docker run/create/build/compose, host bind mounts, raw git or `cd` into `runs/*/repo`, host execution of evaluated code, and Read/Write/Edit of files `e2eat` owns. It fails closed; if a harmless command is blocked, rephrase it rather than working around the guard. Use `./bin/e2eat git <run-dir> …` for history.
- Prompts and docs must only name real `e2eat` commands/flags (`tools/tests/test_skill_definition.py` checks every `./bin/e2eat …` mention). Host `npm`/`node` are denied: build, lock and run `web/` through `./bin/e2eat web start|lock`.
- Before finishing code changes run: `uv run --project tools pytest tools/tests -q`, `uv run --project tools --with ruff ruff check tools`, `uv run --project tools --with mypy mypy --config-file tools/pyproject.toml tools/src/e2eat`.
- New CLI command group: add `tools/src/e2eat/cli/<name>_cmds.py` with `register(sub)`; it is discovered automatically.
- New agent: add `.claude/agents/<name>.md` (frontmatter `name`, `description`, `tools`; body must point to the agent contract), wire it into `squad.py`/`score.py` if it covers a dimension, and extend `tools/tests/test_agent_definitions.py` expectations and `AGENT_NAMES` in `workspace.py`. An agent that assesses a dimension must report `coverage` in its facts (see the agent contract).
