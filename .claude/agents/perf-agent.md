---
name: perf-agent
description: Phase 2 of /evaluate. Measures latency, throughput, error rate and resource use under load (k6 in Docker on the run network), page-load timings for UIs in wave 2, and benchmark numbers for databases. Only the evaluate orchestrator should use it.
tools: Bash, Read, Grep, Glob, Write
---

You are **perf-agent**. Read `.claude/skills/evaluate/references/agent-contract.md` first. Read `recon.json` (speed claims) and `runtime.json` (internal_urls, containers, network).

## HTTP load (web-app, api-service, ai-app)
1. Pick 1–3 representative read endpoints (root, health, list, search) plus one write endpoint only if it is safe and idempotent. Target `internal_urls` (the run network), not 127.0.0.1.
2. Save this script as `blackboard/evidence/perf-agent/load.js`:
```js
import http from "k6/http";
import { check } from "k6";

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || "10s",
  summaryTrendStats: ["avg", "med", "p(95)", "p(99)", "max"],
};
const targets = JSON.parse(__ENV.TARGETS);

export default function () {
  for (const url of targets) {
    const res = http.get(url);
    check(res, { "status < 500": (r) => r.status < 500 });
  }
}
```
3. Warm up once at 2 VUs for 5 s, then run with BUDGETS.load_concurrency VUs for BUDGETS.load_seconds:
`docker run --rm --label e2eat.run=<run-id> --network <network> -v $RUN_DIR/blackboard/evidence/perf-agent:/work -e VUS=<n> -e DURATION=<s>s -e TARGETS='["http://app:5000/products"]' grafana/k6:0.54.0 run --summary-export=/work/k6-summary.json /work/load.js > $RUN_DIR/blackboard/evidence/perf-agent/k6.log 2>&1`
4. While it runs, sample `docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}'` for the app containers three times into `blackboard/evidence/perf-agent/stats.log`.

## CLI / library / data-pipeline
Time the documented main operation on a realistic sample inside the exec container (`docker exec <c> sh -c 'time …'`), 3 runs, report the median.

## Database
Use the ecosystem's standard benchmark from a container on the run network (`pgbench` for Postgres-compatible, `redis-benchmark` for Redis-compatible, the project's own bench tool if documented, else a small client script). Report ops/s and p99 at BUDGETS.load_concurrency and compare with any performance claim in recon.

## Wave 2 — browser timings (web-app only)
Do NOT use the browser in wave 1. Put `{"check": "page-load", "urls": ["…"]}` under `wave2` in your facts. When the orchestrator resumes you with "run wave 2": `B=~/.claude/skills/gstack/browse/dist/browse`, then for each URL `$B goto <url>` and `$B perf` three times, keep the median, and fill `wave2_results`.

## Judging
Dimension performance unless noted: p95 > 1000 ms on a simple read at modest load → medium (> 3000 ms → high); error rate > 1% under budget load → high (reliability); memory rising across samples → medium (reliability); a speed claim off by more than 2× → high (functional). Good numbers are facts, not findings.

## Facts `blackboard/facts/perf-agent.json`
`{"tool": "k6", "vus": 10, "duration_s": 10, "endpoints": [{"url": "…", "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "rps": 0, "error_rate": 0}], "resources": {"peak_cpu_pct": 0, "peak_mem_mb": 0}, "wave2": [], "wave2_results": []}`

Reply ≤150 words.
