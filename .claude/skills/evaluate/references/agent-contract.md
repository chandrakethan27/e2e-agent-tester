# Agent contract — read this first

You are one agent in the E2E Agent Tester team. The orchestrator's prompt gives you
`RUN_DIR` (absolute path of `runs/<run-id>/`), `PROJECT_ROOT` (absolute path of this tool),
`PROFILE`, `DEPTH`, `BUDGETS` (JSON) and your `TASK`.
Run every command from `PROJECT_ROOT`. `./bin/e2eat <command>` prints JSON.

## Read before acting
- `$RUN_DIR/run.json` — profile, depth, budgets, squad.
- `$RUN_DIR/blackboard/facts/recon.json` and `runtime.json` when they exist. Do not re-discover what they already say.
- Schemas: `./bin/e2eat schema finding` (also `message`, `recon`, `runtime`, `usecases`, `report`, `challenges`, `rulings`).

## Write only your own things
- Findings: `blackboard/findings/<id>.json`. Get the id with `./bin/e2eat next-id $RUN_DIR <your-agent-name>`. One finding = one problem.
- Evidence: `blackboard/evidence/<your-agent-name>/…` (logs, HTTP transcripts, screenshots, scanner output).
- Facts: `blackboard/facts/<your-agent-name>.json` — your structured results, including what works.
- Never edit `run.json`, other agents' files, or anything under `repo/` (runner-agent may write `repo/.e2eat/` only).

## Finding format
```json
{
  "id": "F-security-003",
  "agent": "security-agent",
  "dimension": "security",
  "severity": "high",
  "title": "SQL injection in GET /search",
  "claim": "The q parameter is concatenated into SQL (app.py:31); a boolean payload returns every row.",
  "evidence": ["blackboard/evidence/security-agent/sqli-search.txt", "repo/app.py:31"],
  "repro": "curl -s 'http://127.0.0.1:5000/search?q=x%27%20OR%20%271%27=%271'",
  "confidence": 0.95,
  "status": "open"
}
```
- `dimension`: functional | security | performance | reliability | maintainability | operability | compliance | viability
- `severity`: **critical** blocks any production use (exploitable vuln, core purpose broken, data loss, license forbids use) · **high** major function broken or serious risk · **medium** real issue with a workaround · **low** minor · **info** observation, no penalty
- `evidence`: paths relative to RUN_DIR, or `repo/<file>:<line>` for code. Every path must exist. No evidence = no finding.
- `confidence`: how sure you are the claim is true (0–1). Below 0.6 will be challenged.
- `status`: always `open` when you create it.
- Positive results (things that work) go in your facts file, not in findings.

## Talking to other agents
Need something from another agent (seeded data, a URL, a credential)? Write a question:
`./bin/e2eat next-id $RUN_DIR <your-agent-name> --message` → `blackboard/messages/<id>.json`
`{"id": "Q-perf-001", "from": "perf-agent", "to": "runner-agent", "question": "Seed 10k rows into products so load tests are realistic.", "answer": null, "status": "open"}`
Then carry on with what you can do. The orchestrator routes questions between waves and resumes you with the answer.
When you are asked to answer a question addressed to you, write the answer into that file's `answer` field and set `status` to `answered`.

## Cross-examination
If the orchestrator forwards a challenge on one of your findings, either:
- **defend** — add new evidence files, append their paths to `evidence`, set `rebuttal` to a short explanation (you may lower `severity` if the challenge is fair); or
- **concede** — set `conceded` to `true` and `rebuttal` to why.
Never change `status` yourself.

## Safety rules (non-negotiable)
- Never run the evaluated project's code, package managers, or build tools on the host. Use containers only, through `./bin/e2eat sandbox build|run` (services, load tests, test runs) and `docker exec`/`docker logs`/`docker stats` on `e2eat-<run-id>-*` containers. Raw `docker run`, `docker create`, `docker build`, `docker compose` and `docker volume/network create` are blocked by the guard.
- Send traffic only to `127.0.0.1`/`localhost` or containers on the run network. Never probe third-party hosts.
- Active security checks use harmless proofs (read-only queries, marker strings). No destructive payloads.
- Run git on the evaluated code only through `./bin/e2eat git $RUN_DIR <log|shortlog|rev-list|ls-files|rev-parse> …` — hardened and read-only; it exits 3 when the source has no history. Raw git there can execute repo-controlled config, and for sources without history it would read this tool's own repo.
- Never run the evaluated repo's compose files, and never read `secrets.env` yourself. A guard hook blocks these, external `curl`/`wget`, and bind mounts from outside `runs/`; if it blocks you, change approach rather than working around it.
- Never print or copy secret values. The per-run env file (outside `runs/`, created by `sandbox env`) exists only for `sandbox run --secrets`.
- Stay within BUDGETS. If you run out of time, write what you have.

## Finish
1. `./bin/e2eat validate $RUN_DIR --check-evidence` and fix anything it reports about your files.
2. Reply in ≤150 words: what you did, findings by severity, open questions, anything that blocked you.
