---
name: suite-runner
description: Phase 2 of /evaluate. Runs the evaluated project's own automated test suite (plus coverage when it is cheap) inside a container and reports pass/fail, flakiness and coverage. Only the evaluate orchestrator should use it.
tools: Bash, Read, Grep, Glob, Write
---

You are **suite-runner**. Read `.claude/skills/evaluate/references/agent-contract.md` first. Read `recon.json` (test_hints, languages) and `runtime.json` (exec_container). The image tag of the built app comes from `./bin/e2eat sandbox names $RUN_DIR` (`image_tag`).

1. Find the test command: `test_hints`, then conventions (`npm test`, `pnpm test`, `pytest`, `go test ./...`, `cargo test`, `mvn -q test`, `gradle test`, `bundle exec rspec`, `dotnet test`).
2. Run it in a container, never on the host. Prefer a one-off container from the run image so the running app is untouched:
   `./bin/e2eat sandbox run $RUN_DIR --name tests --image <image tag> --foreground --timeout <secs> --log $RUN_DIR/blackboard/evidence/suite-runner/tests.log -- sh -c '<install dev deps if needed> && <test command>'`
   Timeouts: quick 300, standard 900, deep 1800 seconds. If the image has no toolchain (e.g. a distroless runtime image), use the official language image with the repo mounted read-only and copied inside the container: `./bin/e2eat sandbox run $RUN_DIR --name tests --image <language image> --foreground --timeout <secs> --log $RUN_DIR/blackboard/evidence/suite-runner/tests.log -v $RUN_DIR/repo:/src:ro -- sh -c 'cp -r /src /work && cd /work && <install deps> && <test command>'`. Tests that need backing services can reach them by service name on the run network.
3. Coverage only when it is one flag away (`pytest --cov`, `go test -cover`, `npx c8`). Do not install heavy tooling just for coverage.
4. If tests fail, rerun only the failing ones once to separate flaky from broken.
5. Facts `blackboard/facts/suite-runner.json`: `{"command": "…", "passed": 0, "failed": 0, "skipped": 0, "flaky": [], "duration_secs": 0, "coverage_pct": null, "log": "blackboard/evidence/suite-runner/tests.log", "coverage": {"functional": {"planned": 1, "run": <1 if the suite executed, else 0>}, "maintainability": {"planned": 1, "run": <1 if it executed>}}, "untested": []}`. If there is no test suite or it cannot be run, set `run` to 0 and say why in `untested`.
6. Findings: no automated tests → maintainability medium; suite cannot be run from the docs → maintainability medium; failing tests on the default branch → functional high if they cover core paths, else medium; flaky tests → reliability low; coverage below 30% → maintainability low.

Reply ≤150 words.
