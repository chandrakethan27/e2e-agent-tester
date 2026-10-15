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
  Phase 1  runner-agent         build & start it in Docker (or prove it can't run)
  Phase 2  in parallel          functional-tester · suite-runner · security-agent
                                perf-agent · architecture-agent · viability-agent
           wave 2               browser timings, restart/kill reliability checks
  Phase 3  skeptic-agent        challenges weak findings; owners defend or concede
  Phase 4  use-case-strategist  where to use it, where not, alternatives
           report-writer        executive summary, risks, next steps
  Phase 5  score · redact · render · teardown  →  runs/<run-id>/report.html
```

Agents share a file **blackboard** (`runs/<run-id>/blackboard/`): facts everyone reads, findings with evidence, and directed questions between agents. Every finding needs evidence (logs, transcripts, screenshots, code lines) and must survive cross-examination before it counts. Scores are computed deterministically by `e2eat score`, never by an agent.

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
- Symlinks escaping the repo are removed; archives with path traversal are rejected.
- Only the secrets a project needs are passed to its containers; secret values are scrubbed from evidence before rendering.
- Every container/network/volume/image is labeled `e2eat.run=<run-id>` and torn down at the end (`./bin/e2eat sandbox stale` cleans up interrupted runs).
- Limitation: containers have outbound internet access (needed for installs).

## Development
```
uv run --project tools pytest tools/tests -q
```
Try the known-answer fixtures in `fixtures/` (see `fixtures/EXPECTED.md`).
