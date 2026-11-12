---
name: evaluate
description: Evaluate a GitHub repo, git URL, local folder, or uploaded archive end to end with a team of agents — build and run it in Docker, run E2E, security, performance, architecture and viability checks, cross-examine the findings, and produce a scored enterprise-readiness report with use-case ideas. Use when the user runs /evaluate or asks to test, vet, assess, or evaluate a repository or codebase.
argument-hint: <github-url | git-url | path | archive> [--profile adopt|radar|audit] [--depth quick|standard|deep] [--resume <run-id>]
---

# /evaluate — orchestrator

You are the hub. You run the phases, own `run.json`, route messages between agents, and keep the user informed with one short line per phase. Agents do the testing; `./bin/e2eat` does the bookkeeping. Run every command from the project root. Never run the evaluated project's code on the host yourself. Never edit `run.json`, `finding-status.json` or `scores.json` by hand — only `./bin/e2eat` writes them.

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
- **Bookkeeping — every time an agent works, including SendMessage resumes:**
  - when it starts: `./bin/e2eat agent $RUN_DIR <name> running --agent-id <id>` — `<id>` is the id the Agent tool returned for that agent. Never invent one. A resume of a known agent: `./bin/e2eat agent $RUN_DIR <name> running` (no id);
  - when it returns: `./bin/e2eat agent $RUN_DIR <name> done`. This is **refused** (exit 1, with the problems listed) while the agent's required output is missing or invalid: SendMessage the agent the problems once; if it is still refused, `./bin/e2eat agent $RUN_DIR <name> failed --note "<why>"`;
  - an agent that errors or does not answer: `failed --note "<why>"`. Never pass `--force` to hide a missing output.
- After every agent or wave: `./bin/e2eat validate $RUN_DIR --check-evidence`. If an agent's files are invalid, SendMessage it once with the issues; if they are still invalid, rerun validate with `--quarantine`.
- **Time:** the run's clock starts at `run.json` `created_at`. A running agent that has not returned when elapsed time passes the depth budget (BUDGETS.minutes) gets SendMessage "Time budget reached — write your findings and facts now and finish." If it has not returned 5 minutes later, mark it `failed` and carry on.

## Preflight
1. `./bin/e2eat doctor` — if a required check fails, stop and tell the user exactly what to fix (e.g. "Start Docker Desktop, then rerun").
2. New run: `./bin/e2eat init <source> --profile <p> --depth <d>` → `run_dir` (absolute), `run_id`, `budgets`. If `init` fails (private repo, bad URL, rejected archive, symlink trouble), show the error in one line and stop — there is nothing to clean up. Resume (`--resume <run-id>`): `RUN_DIR=$PWD/runs/<run-id>` (absolute), `./bin/e2eat status $RUN_DIR`, continue from the first phase that is not `done` or `skipped`; agents recorded `running` with no live process are restarted.
3. `./bin/e2eat sandbox stale --except <run-id>` — clean leftovers from other, old runs; never the run you are working on.
4. Tell the user the run id, profile, depth and expected time (quick ≈ 15 min, standard ≈ 45, deep ≈ 90).
5. **Live view:** `./bin/e2eat web start --run-id <run-id>` builds the Next.js visualization (first time ≈ 1–2 min) and opens it in the browser. If it fails (Docker down, port busy), say so in one line and continue — the site is optional. Leave it running after the run so the user can open the report from it (`./bin/e2eat web stop` stops it).

## Phase 0 · Intake
`./bin/e2eat phase $RUN_DIR intake running` → spawn **recon-agent** → validate → `./bin/e2eat phase $RUN_DIR intake done`. Update the user: project type and stack.
If recon-agent fails or `recon.json` is still invalid after one repair round, nothing can be planned: `./bin/e2eat phase $RUN_DIR intake failed`, `./bin/e2eat sandbox teardown $RUN_DIR`, tell the user why, and stop.

## Briefing & test plan (checkpoint — before any build or test)
Intake has cloned and fingerprinted the repo but nothing has been executed yet. Talk to the user **in the chat** (plain prose, not tool output) before Phase 1:
1. **What this repo is** — 4–6 lines from `blackboard/facts/recon.json` and the README: purpose, who uses it, stack, project type, size, license, repo health. Say what you could not determine.
2. **How I will test it end to end** — tailored to this repo, as a short list:
   - how it will be built and started (runtime strategy from recon: repo Dockerfile, toolchain image, …) and in a container only;
   - which agents run (`./bin/e2eat squad $RUN_DIR --plan` — a read-only preview) and what each will check for this project type (journeys, own test suite, load, security scans, architecture, license/viability);
   - what **cannot** be tested and why — `./bin/e2eat sandbox env $RUN_DIR --check` reports which required keys are `present` / `missing` in `secrets.env` without writing anything or showing values. Missing keys and paid services become "untested", not "passed";
   - profile, depth, expected time, and Docker/disk needs.
3. Write `$RUN_DIR/blackboard/facts/briefing.json` — `{"summary": "<the 4–6 line summary>", "plan": ["<plan bullet>", …], "cannot_test": ["<item>", …], "approved_secrets": ["<KEY>", …]}` — so the live site shows the same briefing. `approved_secrets` is empty until the user approves sharing keys.
4. **Ask to proceed** with AskUserQuestion: `Start as planned (Recommended)` / `Start and share <present KEYS> with the sandboxed app` / `Change depth or profile` / `Static review only (don't run it)` / `Cancel`. Only the keys the user explicitly approves go into `approved_secrets` (rewrite briefing.json); keys not approved are withheld from the container and reported untested. Wait for the answer.
   - Change depth/profile: `./bin/e2eat reconfigure $RUN_DIR --profile <p> --depth <d>` (same run, same recon), update the briefing, ask again.
   - Static review only: `./bin/e2eat static-only $RUN_DIR` (records `runtime.json` as `static-only`, skips the build phase and runner-agent), then go to Phase 2. Say so in the final answer.
   - Cancel: `./bin/e2eat sandbox teardown $RUN_DIR`, stop.

## Phase 1 · Build & run
`./bin/e2eat phase $RUN_DIR build running` → spawn **runner-agent** → validate → `./bin/e2eat phase $RUN_DIR build done`. Update the user: runtime status and strategy.
**Not-run checkpoint:** if `blackboard/facts/runtime.json` is missing or its `status` is not `running`, STOP and warn the user in the chat before continuing: "The project could NOT be run (<reason>). Everything from here is static review only; functional, performance and reliability results will be absent and the verdict is capped." Then AskUserQuestion: `Continue static-only` / `Retry build with your hint` / `Stop`. Do not proceed to Phase 2 without an answer. The final report and your final answer must repeat this warning.
- **Retry (at most twice):** `./bin/e2eat sandbox teardown $RUN_DIR`; drop the earlier "could not be built or run" finding(s) with `./bin/e2eat set-status $RUN_DIR <id> dropped --reason "superseded by retry"`; spawn a **fresh** runner-agent whose prompt starts with "RETRY: a new budget of 3 attempts applies. User hint: <hint>"; record it as a new `running` agent with its new id.
- **Stop:** `./bin/e2eat sandbox teardown $RUN_DIR`, `./bin/e2eat phase $RUN_DIR build failed`, tell the user, stop.

## Phase 2 · Assess
1. `./bin/e2eat squad $RUN_DIR` → squad and skipped agents (this records them in run.json; run it once, here, after Phase 1).
2. `./bin/e2eat phase $RUN_DIR assess running`. **Wave 1:** spawn every squad agent in ONE message so they run in parallel (mark each `running` first). perf-agent's wave 1 is preparation and micro-benchmarks only — its load test is a wave 2 item so it does not run on top of the other agents' traffic. Wait until all have finished (you are notified as each completes).
3. **Questions** (after wave 1 and again after wave 2): `./bin/e2eat messages $RUN_DIR --status open`. For each, mark the `to` agent `running`, SendMessage it "Answer question <id> in blackboard/messages/<id>.json per the agent contract.", then SendMessage the asker "<id> is answered — read it and finish the affected checks." (mark it `running` too). If the `to` agent is skipped or failed, or the question is addressed to the orchestrator, answer it yourself in the message file's `answer` field only if it is a plain fact from the blackboard; otherwise leave it. At most 2 rounds. After the last round, `./bin/e2eat messages $RUN_DIR --expire` — unanswered questions become coverage gaps.
4. **Wave 2 (exclusive, only when runtime status is running):** one after the other, never concurrently — they share one browser and restarts disturb load tests: perf-agent first if its facts list `wave2` items (including the load test), then functional-tester if its facts list `wave2` items. For each: `./bin/e2eat agent $RUN_DIR <name> running`, SendMessage "run wave 2", wait, `./bin/e2eat agent $RUN_DIR <name> done`. After functional-tester's wave 2 confirm the app is up again (`docker ps` shows its container `Up`); if not, `docker start <container>` before anything else relies on it.
5. **Budget:** apply the time rules above; a budget cut-off is recorded in the agent's `untested` list, never hidden.
6. `./bin/e2eat validate $RUN_DIR --check-evidence --quarantine` → `./bin/e2eat phase $RUN_DIR assess done`. Update the user: findings by severity (`./bin/e2eat status $RUN_DIR`).

## Phase 3 · Cross-examination
1. `./bin/e2eat findings $RUN_DIR --challengeable` (capped by budgets.challenge_limit). If the list is empty: `./bin/e2eat phase $RUN_DIR crossexam skipped`, `./bin/e2eat agent $RUN_DIR skeptic-agent skipped --note "nothing to challenge"`, then step 5.
2. `./bin/e2eat phase $RUN_DIR crossexam running`. Spawn **skeptic-agent** with the list (round 1), then `./bin/e2eat apply-crossexam $RUN_DIR` — challenged findings become `disputed`. If the skeptic fails or its file is invalid after one repair round, skip to step 5: the eligible findings are then confirmed but flagged **unreviewed** and the report says so.
3. For each finding in `./bin/e2eat findings $RUN_DIR --status disputed`, SendMessage its owning agent (agent id from run.json; mark it `running` first): "Challenge on <id>: <challenge>. Defend it with evidence or concede, per the agent contract." Owners may work in parallel. If an owner cannot be resumed, spawn it fresh with the same instruction and the finding id.
4. SendMessage skeptic-agent: "Round 2 — rule on every finding you challenged." (resume; if it cannot be resumed, spawn it fresh once with the ids, challenges and rebuttals). Then `./bin/e2eat apply-crossexam $RUN_DIR`. A ruling only counts for a finding the skeptic challenged.
5. `./bin/e2eat finalize-findings $RUN_DIR` → `./bin/e2eat phase $RUN_DIR crossexam done`. It **refuses** while challenged findings have no skeptic ruling: rerun round 2 once; if there is still no ruling, settle them explicitly with `./bin/e2eat finalize-findings $RUN_DIR --unruled keep` (a rebutted, unconceded finding stands, flagged unreviewed) and say so in the final answer.
6. The runtime is no longer needed: `./bin/e2eat sandbox teardown $RUN_DIR`. If it reports `errors`, retry once and mention leftovers. Update the user: confirmed vs dropped vs unreviewed.

## Phase 4 · Synthesis
`./bin/e2eat phase $RUN_DIR synthesis running` → `./bin/e2eat score $RUN_DIR` → spawn **use-case-strategist** → validate → spawn **report-writer** → validate → `./bin/e2eat phase $RUN_DIR synthesis done`.
- `score` refuses (exit non-zero, reason in the message) when findings are still open/disputed, ids are duplicated, a severity/dimension is unknown, or the ledger/runtime file is corrupt. Fix the cause with the commands above (never by editing files) and rerun.
- If use-case-strategist or report-writer fails twice, continue: the report renders without that narrative; say so in the final answer.

## Phase 5 · Finalize
`./bin/e2eat phase $RUN_DIR finalize running` → `./bin/e2eat redact $RUN_DIR` → `./bin/e2eat validate $RUN_DIR` → `./bin/e2eat render $RUN_DIR` → `./bin/e2eat sandbox teardown $RUN_DIR` → `./bin/e2eat phase $RUN_DIR finalize done`. If the final `validate` reports issues, still render, and list the issues in the final answer.

## Final answer to the user
- **First, a testing-completeness line**: "Tested by running the project" / "NOT RUN — static review only" / "PARTIAL — <failed agents>". `report.html` shows the same banner automatically; never soften it. If a failed agent or untested area (missing or unapproved keys, Docker/disk problems, skipped wave 2, expired questions, unreviewed findings) limits the verdict, say so before the verdict.
- Verdict, overall score and coverage %, plus any triggered gates and caps (`scores.json` `gates`, `caps`, `untested`).
- The 3 most important confirmed findings (id, severity, one line each).
- The 3 best use cases and the key anti-use-case.
- Report path `runs/<run-id>/report.html` — offer to open it (`open runs/<run-id>/report.html`) or publish it as an Artifact to share.

## Failure rules
- An agent failing or timing out never stops the run (except recon-agent, which the whole plan depends on): mark it `failed`, continue; its dimensions become N/A, coverage drops and the verdict is capped.
- If runner-agent fails without writing `runtime.json`, the scoring gate treats the project as not run (adopt/audit verdict capped). Say so in your final answer.
- If `apply-crossexam` rejects a skeptic file as invalid, SendMessage the skeptic the error once and rerun it; never edit the file yourself.
- If you must stop early (user abort, fatal error): run `./bin/e2eat sandbox teardown $RUN_DIR` first and mark the current phase `failed`. A SessionEnd hook runs `./bin/e2eat sandbox teardown-active` as a backstop if the session dies, so run at most one `/evaluate` session at a time.
