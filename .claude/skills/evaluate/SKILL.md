---
name: evaluate
description: Evaluate a GitHub repo, git URL, local folder, or uploaded archive end to end with a team of agents — build and run it in Docker, run E2E, security, performance, architecture and viability checks, cross-examine the findings, and produce a scored enterprise-readiness report with use-case ideas. Use when the user runs /evaluate or asks to test, vet, assess, or evaluate a repository or codebase.
argument-hint: <github-url | git-url | path | archive> [--profile adopt|radar|audit] [--depth quick|standard|deep] [--resume <run-id>]
---

# /evaluate — orchestrator

You are the hub. You run the phases, own `run.json`, route messages between agents, and keep the user informed with one short line per phase. Agents do the testing; `./bin/e2eat` does the bookkeeping. Run every command from the project root. Never run the evaluated project's code on the host yourself.

Arguments: `$ARGUMENTS`. Defaults: `--profile adopt --depth standard`. If no source is given, ask for one.
Profiles: `adopt` (is it safe and solid enough for enterprise/client work?), `radar` (what is it good for, how good is it?), `audit` (is this code production-ready?).

## Spawning agents
- Prompt template — fill every field:
  ```
  RUN_DIR=<absolute run dir>
  PROJECT_ROOT=<absolute project root>
  PROFILE=<profile>  DEPTH=<depth>
  BUDGETS=<budgets JSON from run.json>
  PHASE=<phase>  TASK=<one line, e.g. "Phase 2 wave 1: functional testing">
  <extra input, e.g. the challengeable finding ids>
  Follow your agent definition and .claude/skills/evaluate/references/agent-contract.md.
  ```
- `subagent_type` is the agent name (e.g. `recon-agent`). If that type is not available in this session (agents created mid-session load on restart), use `general-purpose` and begin the prompt with: "Read .claude/agents/<name>.md and act exactly as that agent."
- Bookkeeping: `./bin/e2eat agent $RUN_DIR <name> running --agent-id <id>` when spawned; `./bin/e2eat agent $RUN_DIR <name> done` (or `failed --note "<why>"`) when it returns. Keep each agent's id — you resume agents with SendMessage.
- After every agent or wave: `./bin/e2eat validate $RUN_DIR --check-evidence`. If an agent's files are invalid, SendMessage it once with the issues; if they are still invalid, rerun validate with `--quarantine`.

## Preflight
1. `./bin/e2eat doctor` — if a required check fails, stop and tell the user exactly what to fix (e.g. "Start Docker Desktop, then rerun").
2. `./bin/e2eat sandbox stale` — clean leftovers from old runs.
3. New run: `./bin/e2eat init <source> --profile <p> --depth <d>` → `run_dir`, `run_id`, `budgets`. Resume (`--resume <run-id>`): `RUN_DIR=runs/<run-id>`, `./bin/e2eat status $RUN_DIR`, continue from the first phase that is not `done`.
4. Tell the user the run id, profile, depth and expected time (quick ≈ 15 min, standard ≈ 45, deep ≈ 90).

## Phase 0 · Intake
`./bin/e2eat phase $RUN_DIR intake running` → spawn **recon-agent** → validate → `./bin/e2eat phase $RUN_DIR intake done`. Update the user: project type and stack.

## Phase 1 · Build & run
`./bin/e2eat phase $RUN_DIR build running` → spawn **runner-agent** → validate → `./bin/e2eat phase $RUN_DIR build done`. Update the user: runtime status and strategy, or why it could not run (the run continues static-only).

## Phase 2 · Assess
1. `./bin/e2eat squad $RUN_DIR` → squad and skipped agents.
2. `./bin/e2eat phase $RUN_DIR assess running`. **Wave 1:** spawn every squad agent in ONE message so they run in parallel. Wait until all have finished (you are notified as each completes).
3. **Questions:** `./bin/e2eat messages $RUN_DIR --status open`. For each, SendMessage the `to` agent: "Answer question <id> in blackboard/messages/<id>.json per the agent contract." Then SendMessage the asker: "<id> is answered — read it and finish the affected checks." At most 2 rounds; leftovers stay open and become coverage gaps.
4. **Wave 2 (exclusive, only when runtime status is running):** if perf-agent's facts list `wave2` items, SendMessage perf-agent "run wave 2" and wait. Then, if functional-tester's facts list `wave2` items, SendMessage functional-tester "run wave 2" and wait. Never run these two at the same time — they share one browser and restarts disturb load tests.
5. **Budget:** if elapsed time passes 70% of BUDGETS.minutes during Phase 2, SendMessage every running agent: "Time budget reached — write your findings and facts now and finish."
6. `./bin/e2eat validate $RUN_DIR --check-evidence --quarantine` → `./bin/e2eat phase $RUN_DIR assess done`. Update the user: findings by severity (`./bin/e2eat status $RUN_DIR`).

## Phase 3 · Cross-examination
1. `./bin/e2eat findings $RUN_DIR --challengeable` (capped by budgets.challenge_limit). If the list is empty, go to step 5.
2. `./bin/e2eat phase $RUN_DIR crossexam running`. Spawn **skeptic-agent** with the list (round 1), then `./bin/e2eat apply-crossexam $RUN_DIR` — challenged findings become `disputed`.
3. For each finding in `./bin/e2eat findings $RUN_DIR --status disputed`, SendMessage its owning agent (agent id from run.json): "Challenge on <id>: <challenge>. Defend it with evidence or concede, per the agent contract." Owners may work in parallel. If an owner cannot be resumed, spawn it fresh with the same instruction.
4. SendMessage skeptic-agent: "Round 2 — rule on every finding you challenged." Then `./bin/e2eat apply-crossexam $RUN_DIR`.
5. `./bin/e2eat finalize-findings $RUN_DIR` → `./bin/e2eat phase $RUN_DIR crossexam done`.
6. The runtime is no longer needed: `./bin/e2eat sandbox teardown $RUN_DIR`. Update the user: confirmed vs dropped.

## Phase 4 · Synthesis
`./bin/e2eat phase $RUN_DIR synthesis running` → `./bin/e2eat score $RUN_DIR` → spawn **use-case-strategist** → validate → spawn **report-writer** → validate → `./bin/e2eat phase $RUN_DIR synthesis done`.

## Phase 5 · Finalize
`./bin/e2eat phase $RUN_DIR finalize running` → `./bin/e2eat redact $RUN_DIR` → `./bin/e2eat validate $RUN_DIR` → `./bin/e2eat render $RUN_DIR` → `./bin/e2eat sandbox teardown $RUN_DIR` → `./bin/e2eat phase $RUN_DIR finalize done`.

## Final answer to the user
- Verdict, overall score and coverage %, plus any triggered gates.
- The 3 most important confirmed findings (id, severity, one line each).
- The 3 best use cases and the key anti-use-case.
- Report path `runs/<run-id>/report.html` — offer to open it (`open runs/<run-id>/report.html`) or publish it as an Artifact to share.

## Failure rules
- An agent failing or timing out never stops the run: mark it `failed`, continue; its dimensions become N/A and coverage drops.
- If runner-agent fails without writing `runtime.json`, the scoring gate treats the project as not run (adopt/audit verdict capped). Say so in your final answer.
- If `apply-crossexam` rejects a skeptic file as invalid, SendMessage the skeptic the error once and rerun it; never edit the file yourself.
- If you must stop early (user abort, fatal error): run `./bin/e2eat sandbox teardown $RUN_DIR` first and mark the current phase `failed`.
