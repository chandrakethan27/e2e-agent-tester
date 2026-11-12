# E2E Agent Tester — Design Spec

Date: 2026-10-15
Status: Approved (user: "do everything" after Sections 1–2 approved interactively)

## 1. Purpose

Given a GitHub repo URL or a local/uploaded code directory, a team of Claude Code
agents ingests the project, builds and runs it inside Docker, performs end-to-end
and non-functional testing, judges enterprise readiness, and writes an
evidence-backed report with use-case ideas.

Success = user runs `/evaluate <source>` and receives `runs/<id>/report.html`
containing a verdict, per-dimension scores, confirmed findings with evidence and
repro steps, a coverage statement (what was and was not tested), and concrete
use-case / anti-use-case recommendations.

### Decisions made with the user
| Decision | Choice |
|---|---|
| Form factor | Claude Code-native: subagents + orchestrator skill + `/evaluate` command |
| Report audience | All three profiles, selected per run: `adopt`, `radar`, `audit` |
| Coordination | Hub (orchestrator) + shared blackboard files + skeptic cross-examination |
| Sandbox | Local Docker (+ docker compose for dependent services) |

### Non-goals (v1)
- No job queue or multi-user service (possible v2 via Agent SDK). _Revised 2026-11: a read-only live view of a run (`web/`) now ships; see §13._
- No mobile-app runtime testing (static analysis only).
- No cloud sandbox; Docker Desktop must be running locally.
- No automatic fixing of the evaluated repo.

## 2. Architecture

```
/evaluate <github-url | git-url | ./path | archive.zip|.tar.gz> [--profile adopt|radar|audit] [--depth quick|standard|deep] [--resume <run-id>]
        │
        ▼
  ORCHESTRATOR skill (main session; runs phases, owns run.json, routes messages)
        │
  Phase 0  INTAKE ───────► recon-agent
  Phase 1  BUILD & RUN ──► runner-agent
  Phase 2  ASSESS (parallel; squad chosen by project_type)
           functional-tester · suite-runner · security-agent ·
           perf-agent · architecture-agent · viability-agent
  Phase 3  CROSS-EXAM ───► skeptic-agent ⇄ finding owners
  Phase 4  SYNTHESIS ────► use-case-strategist → report-writer
  Phase 5  FINALIZE ─────► e2eat score + render, sandbox teardown
```

The orchestrator runs in the main Claude Code session because subagents cannot
spawn subagents. Every agent is a `.claude/agents/<name>.md` definition with one
responsibility and a JSON output contract. Deterministic work (workspace setup,
schema validation, scanners, scoring, HTML rendering, teardown) lives in a small
Python CLI, `e2eat`, run with `uv run e2eat ...`. LLM agents judge; code computes.

### 2.1 Agent roster

| Agent | Phase | Responsibility | Key tools |
|---|---|---|---|
| recon-agent | 0 | Fingerprint stack, classify `project_type`, entrypoints, services/secrets needed, license, repo health, README claims ledger | git, `gh api`, Read/Grep |
| runner-agent | 1 | Produce Dockerfile/compose (reuse repo's if present), build, start, health-check, seed data; publish runtime facts | docker, `e2eat sandbox` |
| functional-tester | 2 | Derive user journeys + README claims, execute E2E per project type, record pass/fail with evidence | gstack browse binary, curl, docker exec |
| suite-runner | 2 | Run the repo's own test suite + coverage inside the container | docker exec |
| security-agent | 2 | Secret scan, SAST, dependency CVEs, container scan, OWASP review, active verification of top findings against the running app | `e2eat scan` (gitleaks, semgrep, trivy, osv-scanner in Docker), optional `cso` skill |
| perf-agent | 2 | Latency/throughput/resource usage under load; page-load timings for UIs; DB load for databases | `grafana/k6` in Docker on the run network, gstack browse `perf` (wave 2), `docker stats` |
| architecture-agent | 2 | Design quality, maintainability, tech debt, operability signals (config, logging, metrics, health endpoints) | arxitect review guidance, Read/Grep |
| viability-agent | 2 | License compatibility, bus factor, release cadence, issue responsiveness, docs quality, alternatives | `gh api`, WebSearch |
| skeptic-agent | 3 | Challenge findings lacking strong evidence; rule final status | Read |
| use-case-strategist | 4 | Use cases, anti-use-cases, integration patterns, comparison vs alternatives | Read, WebSearch |
| report-writer | 4 | Write `report.json` (verdict narrative, executive summary, sections) | Read |

### 2.2 Phase rules
- Phase 0 and 1 are sequential. Phase 2 agents run in parallel (background Agent calls in one message).
- Squad selection by `project_type` (section 5). Agents that do not apply are skipped and logged in `run.json`.
- **"Doesn't run" is a finding, not a crash.** If Phase 1 fails after 3 strategies, the runner files a critical `functional` finding with build logs and the run continues in **static-only mode**: runtime-dependent agents (functional-tester, perf-agent) are skipped, and the report states it plainly.
- `--depth` sets budgets: quick ≈ 10–15 min total, standard ≈ 30–45 min, deep ≈ 60+ min. Budgets are passed to each agent in its prompt (max journeys, load duration, scanner set).

## 3. Blackboard & data contracts

```
runs/<run-id>/                     run-id = <slug>-<yyyymmdd-hhmmss> UTC; slug = lowercase [a-z0-9-] of owner-repo or dir/archive name
  run.json                         inputs, profile, depth, phases{name:status}, squad, skipped, timings  (orchestrator only)
  repo/                            source (read-only for all agents except runner-agent's Docker files under .e2eat/)
  blackboard/
    facts/recon.json               written by recon-agent
    facts/runtime.json             written by runner-agent
    facts/<agent>.json             optional extra facts (e.g. functional-tester journey table)
    findings/F-<agent>-<nnn>.json  one file per finding
    messages/Q-<nnn>.json          directed agent-to-agent questions
    evidence/<agent>/...           logs, screenshots, scanner JSON, bench output
  scores.json                      e2eat score
  usecases.json                    use-case-strategist
  report.json                      report-writer
  report.md, report.html           e2eat render
```

JSON Schemas ship inside the `e2eat` package (`tools/src/e2eat/schemas/`), are printed by `e2eat schema <name>`, and are enforced by `e2eat validate`.
Cross-exam files: `blackboard/facts/skeptic-challenges.json` (round 1) and `blackboard/facts/skeptic-rulings.json` (round 2).

**finding** (required: id, agent, dimension, severity, title, claim, evidence, confidence, status)
- `dimension` ∈ functional | security | performance | reliability | maintainability | operability | compliance | viability
- `severity` ∈ critical | high | medium | low | info
- `evidence`: non-empty array of paths relative to the run dir (optionally `#Lnn`) or `repo/<path>:<line>`
- `repro`: optional string (command or steps)
- `confidence`: 0–1
- `status` ∈ open | confirmed | disputed | dropped; `challenge` / `rebuttal`: optional strings

**message**: id, from, to, question, answer (nullable), status ∈ open | answered | expired

**recon facts**: project_type, secondary_types[], languages[], frameworks[], package_managers[], entrypoints[], has_dockerfile, has_compose, services_needed[], secrets_needed[], license{spdx, file}, repo_health{stars, forks, contributors, last_commit, open_issues, releases, archived}, claims[] (README claims to verify: {id, text, testable})

**runtime facts**: status ∈ running | failed | static-only (`running` = app/CLI/library verified usable in a container), strategy_used, base_urls[] (host, 127.0.0.1), internal_urls[] (on the run network, for load tools), exec_container (container for `docker exec`, or null), ports[], containers[], network, health{endpoint, ok}, startup_secs, image_size_mb, idle_mem_mb, logs[]

### 3.1 How agents talk
1. **Facts (broadcast)** — recon and runner publish facts; all Phase 2 agents read them first.
2. **Wave 2 (exclusive work)** — the gstack browse daemon is a single shared browser and restarts disturb load tests, so browser timing (perf-agent `$B perf`) and disruptive reliability checks (functional-tester restart/kill/SIGTERM) are deferred: agents list them in their facts, and after wave 1 the orchestrator resumes those agents one at a time to run them.
3. **Questions (directed)** — an agent writes `messages/Q-<nnn>.json` (`to` = agent name). After each Phase 2 wave the orchestrator routes open questions to the target agent (SendMessage if still resumable, else a fresh targeted spawn), writes the answer, then resumes the asker with SendMessage. Max 2 waves; unanswered questions become `expired`.
4. **Challenges (adversarial)** — skeptic marks findings `disputed` with `challenge`; orchestrator forwards each to the owning agent, which adds evidence (`rebuttal` + new evidence paths) or concedes; skeptic rules `confirmed` / `dropped`. Only critical/high and confidence < 0.6 findings are challenged. Unchallenged findings with valid evidence become `confirmed`.

### 3.2 Integrity rules
- Agents write only their own findings/evidence paths. Facts are write-once per agent.
- Only the orchestrator edits `run.json`; only the orchestrator applies status changes ruled by the skeptic.
- `e2eat validate` runs after each phase; an invalid file is bounced to its agent once, then moved to `blackboard/invalid/` and logged.
- A finding whose evidence paths do not exist is dropped by `e2eat validate --check-evidence`.

## 4. Sandbox, safety & secrets
- **No repo code runs on the host.** Installs, builds, tests, and the app itself run only in containers. Host commands are limited to git, gh, docker, `uv run e2eat`, curl/browse against 127.0.0.1.
- Every container/network/volume is labeled `e2eat.run=<run-id>` and created through `e2eat sandbox` helpers or with the same labels.
- Default limits: `--cpus 2 --memory 4g --pids-limit 1024 --security-opt no-new-privileges`, never `--privileged`, never mount the Docker socket, publish ports to `127.0.0.1` only. Per-run bridge network `e2eat-<run-id>`.
- Egress is allowed (dependency installs need it). Documented limitation: runtime egress is not filtered in v1.
- **Secrets**: user keeps keys in `secrets.env` (gitignored, template `secrets.env.example`). Runner passes only keys listed in `recon.secrets_needed` that are present, via a filtered env file in the run dir (deleted at teardown). Missing keys → feature marked "untested: needs <KEY>" (info finding, coverage gap). `e2eat redact` scrubs secret values from evidence before render.
- **Teardown always runs** (success, failure, or abort): `e2eat sandbox teardown <run-dir>` removes labeled containers, networks, volumes, and images built for the run (images kept with `--keep-images`).
- Prereq check (`e2eat doctor`): docker daemon reachable, git, gh auth status, uv, gstack browse binary present.

## 5. Testing strategy by project type

| project_type | functional-tester | perf-agent | suite-runner | notes |
|---|---|---|---|---|
| web-app | browse journeys: load, nav, forms, auth, console/network errors, responsive | page load + web vitals, API latency | yes | |
| api-service | endpoint tests from OpenAPI/routes: happy path, validation, auth, error codes | k6 latency p50/p95/p99, error rate at N concurrency | yes | |
| cli | documented commands, help/version, exit codes, bad input | runtime on sample inputs | yes | |
| library | run README/examples in container, write smoke script against public API | micro-bench of documented hot path (deep only) | yes | |
| database | client connect, CRUD, transactions/concurrent increments, restart durability (kill -9 → restart → verify), backup/restore if documented | load test ops/s + p99 at concurrency, compare to documented claims | yes | |
| ai-app (LLM/RAG/agent) | task evals on sample inputs; groundedness spot-checks; prompt-injection probe | latency/token cost per task | yes | needs keys; else static-only for that feature |
| data-pipeline / infra-tool | run documented example pipeline/manifest | throughput on sample | yes | |
| mobile / unknown | static only | — | if runnable | |

Cross-cutting checks (all runnable types): **README claims ledger** — every testable claim gets pass/fail/untested; **reliability** — SIGTERM graceful shutdown, kill/restart recovery, health endpoint, idle memory, startup time; **operability** — env-based config, structured logs, metrics/tracing, official image, deployment docs.

## 6. Scoring & profiles (deterministic, `e2eat score`)
- Dimension score = 100 − Σ penalties of **confirmed** findings (critical 40, high 20, medium 8, low 3, info 0), floored at 0.
- A dimension with zero coverage (agent skipped or static-only) is **N/A**; weights renormalize over covered dimensions and `coverage_pct` = covered weight share.
- Overall = weighted mean by profile:

| dimension | adopt | radar | audit |
|---|---|---|---|
| functional | .15 | .30 | .15 |
| security | .25 | .10 | .25 |
| performance | .05 | .15 | .10 |
| reliability | .15 | .05 | .15 |
| maintainability | .05 | .15 | .25 |
| operability | .10 | .05 | .10 |
| compliance | .15 | .05 | .00 |
| viability | .10 | .15 | .00 |

- Verdict labels: adopt/radar → ≥80 **Adopt**, 65–79 **Trial**, 50–64 **Assess**, <50 **Hold**; audit → ≥80 **Production-ready**, 60–79 **Needs work**, <60 **Not ready**.
- Gates (override, cap verdict at Hold / Not ready): confirmed critical security finding; project could not run (adopt, audit); for adopt only — no license or license in `{AGPL-3.0*, SSPL-1.0, BUSL-1.1, Commons-Clause, unknown}` flagged confirmed by viability-agent as incompatible; coverage_pct < 40% → verdict suffixed "(low confidence)".

## 7. Use cases & report
- use-case-strategist writes `usecases.json`: `use_cases[]` {title, scenario, industries[], fit (high|medium|low), why (cites findings/facts), integration_sketch, prerequisites[], risks[]}, `anti_use_cases[]` {title, why}, `alternatives[]` {name, url, when_better, when_worse}, `integration_patterns[]`.
- report-writer writes `report.json`: executive_summary, verdict_rationale, highlights[], top_risks[] (finding ids), coverage_notes[], next_steps[].
- `e2eat render` combines run.json + facts + confirmed findings + scores + usecases + report into `report.md` and a self-contained `report.html` (no external assets, light/dark, phone-width safe). Optional: publish via the Artifact tool when the user asks.

## 8. Error handling
- Agent output invalid → bounce once with validator errors → else quarantine + log.
- Agent timeout/failure → phase continues; agent marked `failed` in run.json; its dimensions become N/A (coverage drops).
- Build failure → 3 strategies (repo Dockerfile/compose → generated Dockerfile from detected stack → minimal "deps + tests only" image) → static-only.
- `--resume <run-id>` restarts from the first phase not `done` in run.json.
- Teardown executes in every terminal path; orchestrator also runs `e2eat sandbox teardown --stale` at start to clean leftovers older than 6h.

## 9. Testing the system itself
- `e2eat` unit tests (pytest): workspace init (URL + local path + run-id), schema validation incl. evidence check, scoring math + gates + N/A renormalization, redaction, render output, sandbox command construction (docker calls mocked).
- Fixture repos in `fixtures/`: `vuln-flask` (known SQLi + hardcoded secret + no license), `tiny-cli` (healthy, MIT), `broken-build` (fails to install). Golden expectations in `fixtures/EXPECTED.md`.
- Acceptance: `/evaluate fixtures/vuln-flask --depth quick` yields a Hold verdict with a confirmed SQLi finding; `/evaluate fixtures/broken-build` yields static-only report with a critical "could not run" finding.

## 10. Repository layout
```
E2EAgentTester/
  CLAUDE.md  README.md  .gitignore  secrets.env.example
  .claude/
    settings.json
    skills/evaluate/SKILL.md                 (/evaluate — the orchestrator)
    skills/evaluate/references/agent-contract.md   (shared rules every agent reads first)
    agents/{recon-agent, runner-agent, functional-tester, suite-runner, security-agent,
            perf-agent, architecture-agent, viability-agent, skeptic-agent,
            use-case-strategist, report-writer}.md
  bin/e2eat                                  (uv wrapper; agents call ./bin/e2eat)
  tools/  (uv project "e2eat")
    pyproject.toml
    src/e2eat/{paths, jsonio, source, workspace, validate, blackboard, squad, score, redact, render, sandbox, scan, doctor}.py
    src/e2eat/cli/{__init__, output, run_cmds, blackboard_cmds, report_cmds, sandbox_cmds}.py
    src/e2eat/schemas/{run, recon, runtime, finding, message, scores, usecases, report, challenges, rulings}.schema.json
    src/e2eat/templates/{report.html.j2, report.md.j2}
    tests/
  fixtures/{vuln-flask, tiny-cli, broken-build}/  fixtures/EXPECTED.md
  runs/   (gitignored)
```

## 11. Revisions during planning
- `/evaluate` is the skill itself (`.claude/skills/evaluate/`); no separate command file.
- Inputs also accept generic `https://…/*.git` URLs and `.zip/.tar.gz/.tgz/.tar` archives (safe extraction; single top-level folder unwrapped). Symlinks that escape the fetched repo are removed and noted in run.json.
- Squad selection is deterministic (`e2eat squad`): runtime agents = functional-tester, suite-runner, perf-agent (dropped when runtime ≠ running); static agents = security, architecture, viability (always).
- If project agents were created mid-session and are not yet registered, the orchestrator spawns `general-purpose` with "Read .claude/agents/<name>.md and follow it exactly".
- Host safety is also enforced by `.claude/settings.json` deny rules for host package managers/build tools.

## 12. Revisions after the final review (2026-10-15)
- Repo compose files are never executed; runner-agent recreates services via `e2eat sandbox build/run`. Repo bind mounts must be read-only; build context/Dockerfile must be inside the run dir; `.`/`..`/`~`/`$VAR` mount sources are paths, not named volumes.
- Imported `.git` is neutralized at init; host git on evaluated code only via `e2eat git` (allowlisted read-only subcommands, config-exec keys overridden, `GIT_CEILING_DIRECTORIES`). `e2eat git` prints git's raw output (the one non-JSON command besides `guard`).
- Git sources are cloned with full history (gitleaks needs old blobs); a gitleaks "partial scan" is reported as not ok. Credentials in clone URLs are stripped from run.json and the saved remote.
- Finding status lives in `finding-status.json` (orchestrator-owned); agent-written status is ignored. Skeptic files are schema-validated before any change is applied.
- Evidence links are emitted only for refs that pass the evidence check, percent-encoded with a `./` prefix.
- Redaction works on bytes, JSON string values (structure preserved), JSON-escaped forms and run.json; config literals (true/false/…) and short numbers are not treated as secrets; inline comments and multi-line values in the secrets file are handled.
- Gate "not built and run" applies to adopt/audit whenever runtime status is not running (missing file included).
- A `PreToolUse` guard hook (`e2eat guard`) enforces the host-safety rules for every agent; `.claude/settings.json` also denies reading the secrets file and more host toolchains.
- Sources that contain (or sit inside) the runs folder are refused.

## 13. Revisions after the hardening review (2026-11)
A full read of code, prompts and four real runs found that safety, scoring and lifecycle claims held on the happy path only. The hardening pass changed the design as follows; where this section conflicts with earlier ones it wins.

**Safety model.** The guard hook covers Bash and the Read/Write/Edit/Grep/Glob tools and fails closed. Bash is parsed quote-aware (substitutions, subshells, heredocs, `sh -c`, wrappers). Docker is an allowlist: agents may inspect, log, stop/start/kill/exec on `e2eat-<run-id>-*` containers and `docker cp` into them; `run/create/build/compose/volume|network create/prune` are blocked and replaced by `e2eat sandbox build|run` (the k6 load test and the suite-runner fallback use `sandbox run --foreground`). `sandbox run` validates image, name and env keys, allows bind mounts only from `repo/` and `runtime-config/` (read-only) and `blackboard/evidence/` (writable), turns named volumes into per-run labelled volumes, and drops capabilities. The per-run env file lives in `.secrets.d/` outside `runs/`. Generated Dockerfiles and config go to `runtime-config/`, never into the evaluated repo. The guard is defence in depth, not a sandbox.

**Scoring.** Coverage is what agents report as run (`coverage.<dimension>.{planned,run}` in facts, `untested` lists), validated by schema. Weights scale by `run/planned`; an agent that is done without valid facts, failed or unfinished caps the verdict at the second band; a confirmed critical in any weighted dimension gates (licence: adopt only); static-only is a labelled mode. `score` refuses open/disputed findings, duplicate ids, unknown enums and corrupt ledger/runtime files. Rounding is half-up.

**Cross-examination.** Eligibility is critical/high or confidence ≤ 0.6. Rulings only apply to challenged findings. A challenged finding without a ruling blocks `finalize-findings` unless settled explicitly (`--unruled keep|drop`). Eligible findings never challenged are confirmed but flagged unreviewed. Severity and dimension are frozen into the ledger at finalize.

**Orchestration.** A briefing checkpoint (what it is, how it will be tested, what cannot be tested, which keys to share) precedes the build; a not-run checkpoint follows a failed build (continue static-only / retry up to twice / stop). `squad --plan` previews without writing; `static-only`, `reconfigure`, `messages --expire`, `sandbox env --check` and `sandbox stale --except` support those flows. Every agent run, including SendMessage resumes, is recorded; `agent … done` is refused until the agent's output file validates. Unanswered questions expire into coverage gaps. perf-agent's load test moves to an exclusive wave 2; functional-tester restores the app after disruptive checks. A `SessionEnd` hook tears down labelled resources.

**Run bookkeeping.** `run.json` gains `timings` and `finished_at`; `events.jsonl` records every phase/agent transition; writes are atomic and serialized by a run lock; `next-id` reserves numbers.

**Live view.** `web/` (Next.js, Docker, read-only `runs/`) renders state from `run.json`, `events.jsonl`, facts, findings, the ledger and scores; it serves the report and its evidence at `/runs/<id>/…` (allowed prefixes only, sandboxed). It is reused across sessions and optional. The `e2eat web` commands build, start, lock and stop it.

**Report.** Notices for STATIC ONLY / NOT RUN / PARTIAL, gates and caps, a claims ledger (default `untested`), validated top risks, a dropped-findings appendix and the briefing's "could not test" list.

**Not yet done.** The base image and Next.js version are not digest-pinned/upgraded; `RUN_DIR` arguments are not confined to `runs/` by the CLI (the guard, mount allowlist and run-dir validation cover the risky paths); runtime egress is still unfiltered; no live `/evaluate` acceptance of the three fixtures has been run since this pass (the scoring-level expectations are pinned in tests).
