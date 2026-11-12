# E2E Agent Tester

Paste a GitHub repo (or point at a folder or archive) and a team of Claude Code agents will **build it, run it, test it end to end, attack it, load it, judge its design and viability, argue about the findings, and tell you whether it is ready for enterprise use — and where it fits.**

```
/evaluate https://github.com/owner/repo --profile adopt --depth standard
```

## Prerequisites
- Claude Code, Docker Desktop (running), git, [uv](https://docs.astral.sh/uv/)
- Optional: `gh auth login` (repo health data), gstack browse (browser journeys for web apps), `secrets.env` (copy `secrets.env.example`) for projects that need API keys
- Check with `./bin/e2eat doctor`

## How it works

```
/evaluate <source>
  Phase 0  recon-agent          what is it? stack, type, claims, license, repo health
  checkpoint                    briefing: what it is, how it will be tested, what cannot be tested — you approve
                                (change depth/profile, static review only, or cancel; approve which API keys are shared)
  Phase 1  runner-agent         build & start it in Docker (or prove it can't run — you decide how to continue)
  Phase 2  in parallel          functional-tester · suite-runner · security-agent
                                perf-agent (prep) · architecture-agent · viability-agent
           wave 2 (exclusive)   perf load test, browser timings, restart/kill reliability checks
  Phase 3  skeptic-agent        challenges critical/high/low-confidence findings; owners defend or concede
  Phase 4  score                deterministic verdict from confirmed findings and reported coverage
           use-case-strategist  where to use it, where not, alternatives
           report-writer        executive summary, risks, next steps
  Phase 5  redact · render · teardown  →  runs/<run-id>/report.html
```

Agents share a file **blackboard** (`runs/<run-id>/blackboard/`): facts everyone reads, findings with evidence, and directed questions between agents. Every finding needs evidence (logs, transcripts, screenshots, code lines whose cited lines must exist). Critical/high findings and findings the owner is unsure about (confidence ≤ 0.6) are cross-examined by the skeptic; the rest are confirmed as filed, and any eligible finding the skeptic never reached is flagged **unreviewed** in the report. Scores are computed deterministically by `e2eat score`, never by an agent.

## How the verdict is computed
- **Coverage comes from checks that ran, not from agents that returned.** Each assessing agent reports `coverage: {dimension: {planned, run}}` and an `untested` list in its facts file. A dimension's weight is scaled by `run / planned`; an agent without valid facts earns nothing and caps the verdict.
- **Gates:** a confirmed critical finding in any dimension that carries weight forces the lowest band (licence criticals only gate the `adopt` profile). Not running the project gates `adopt`/`audit`; a deliberate static-only review is labelled as such.
- **Caps:** failed, unfinished or fact-less assessing agents cap the verdict at the second band ("Trial" / "Needs work").
- **Fail closed:** `e2eat score` refuses open/disputed findings, duplicate ids, unknown severities/dimensions and corrupt ledger or runtime files instead of scoring around them.
- The report lists the gates, caps, unreviewed findings, every README claim with its result (`untested` unless proven), what could not be tested, and the findings dropped in cross-examination with the skeptic's reason.

## Live view
`/evaluate` starts a small Next.js site (`./bin/e2eat web start`, http://127.0.0.1:3000) that shows the agents working, the findings as they arrive, the verdict with its gates and caps, and a link to the full report. It runs in Docker, reads `runs/` read-only, and is reused across runs (a busy port moves to the next free one). `./bin/e2eat web status|stop`. The site is optional: if Docker or the port is unavailable the evaluation continues without it. After changing `web/package.json` run `./bin/e2eat web lock` (regenerates `web/package-lock.json` in a container).

## Options
| Option | Values | Meaning |
|---|---|---|
| `--profile` | `adopt` (default) | Is it safe and solid enough for enterprise/client work? Verdict Adopt / Trial / Assess / Hold |
| | `radar` | What is it good for and how good is it? Weighted toward function, performance, momentum |
| | `audit` | Is this code production-ready? Verdict Production-ready / Needs work / Not ready |
| `--depth` | `quick` ≈ 15 min · `standard` ≈ 45 min · `deep` ≈ 90 min | Journeys, load duration, scanners, cross-exam size |
| `--resume` | `<run-id>` | Continue an interrupted run |

Sources: `https://github.com/o/r`, `…/tree/<branch>`, `git@github.com:o/r.git`, any `https://…/*.git`, a local folder, or a `.zip/.tar.gz/.tgz/.tar` archive.

## Output
`runs/<run-id>/report.html` (self-contained, light/dark) and `report.md`, plus `scores.json`, `usecases.json`, and the full blackboard with every piece of evidence.

## Safety
- Evaluated code runs **only in Docker** with CPU/memory/pid limits, no privileges, a per-run network, and ports bound to 127.0.0.1. Host package managers are denied in `.claude/settings.json`.
- A **PreToolUse guard hook** (`./bin/e2eat guard`, wired in `.claude/settings.json`) applies to Bash and to the Read/Write/Edit/Grep/Glob tools, and fails closed. It parses commands quote-aware (subshells, substitutions, heredocs, `sh -c`, `sudo`/`env`/`timeout`/`xargs`), allows only read/inspect/stop Docker commands on `e2eat-<run-id>-*` containers (raw `docker run/create/build/compose` are blocked: services, load tests and test runs go through `./bin/e2eat sandbox`), allows `curl`/`wget` only to loopback hosts, and blocks reading the secrets files, raw git or `cd` into evaluated code, running evaluated code on the host, and writes to the files `e2eat` owns (`finding-status.json`, `scores.json`, `run.json`, the evaluated repo). It is defence in depth, not a sandbox: the isolation is Docker plus the validation inside the `e2eat sandbox` commands (image/name/env validation, mount allowlist, dropped capabilities).
- Repo compose files are never executed; services are recreated through the sandbox. Mounts of the evaluated repo are read-only.
- Imported `.git` metadata is neutralized (config reset, hooks removed, gitdir redirects dropped) and host git runs only through the hardened, read-only `./bin/e2eat git`.
- Finding status lives in an orchestrator-owned ledger (`finding-status.json`); agents cannot confirm their own findings.
- Symlinks escaping the repo are removed; archives with path traversal are rejected; credentials in clone URLs are stripped before anything is stored.
- Only the secrets a project needs **and you approved at the briefing** are passed to its containers, through a per-run env file in `.secrets.d/` (mode 600, outside `runs/`, deleted at teardown). Secret values are scrubbed from evidence, the ledger and generated config before rendering.
- Every container/network/volume/image of a run is labeled `e2eat.run=<run-id>` and torn down at the end; named volumes are per-run. `./bin/e2eat sandbox stale --except <run-id>` cleans up old runs, and a `SessionEnd` hook runs `sandbox teardown-active` if a session dies. Exceptions by design: the live-view container/image (`e2eat.web=1`) and the shared Trivy cache volume.
- Limitations: containers have outbound internet access (needed for installs); run one `/evaluate` session at a time (the SessionEnd teardown covers every labelled run); the guard cannot see inside a script an agent writes and runs in a container.

## Disk and retention
Docker image builds need about 5 GiB free (`./bin/e2eat doctor` checks). Each run keeps ~100 MB under `runs/`. `./bin/e2eat runs list` shows runs with verdict and size; `./bin/e2eat runs prune --keep 10` shows what would be deleted and `--apply` deletes (runs in progress or owning containers are never removed).

## Development
```
uv run --project tools pytest tools/tests -q
uv run --project tools --with ruff ruff check tools
uv run --project tools --with mypy mypy --config-file tools/pyproject.toml tools/src/e2eat
./bin/e2eat web start --rebuild --no-open     # builds the live view in Docker (next build type-checks it)
```
CI (`.github/workflows/ci.yml`) runs the same checks plus `docker build web`. Host `npm`/`node` are denied in `.claude/settings.json`: the web app is built, locked and run in containers only.
The known-answer fixtures in `fixtures/` (see `fixtures/EXPECTED.md`) are pinned at the scoring level by `tools/tests/test_acceptance_scoring.py`; a live `/evaluate` of each is still a manual acceptance run.
