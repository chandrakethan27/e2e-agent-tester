"""Security scanners in throwaway containers against the run's repo (mounted read-only)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

from .jsonio import read_json, write_json
from .sandbox import LABEL, LIMITS, Runner, default_runner

SCANNER_IMAGES = {
    "gitleaks": "zricethezav/gitleaks:v8.21.2",
    "semgrep": "semgrep/semgrep:1.95.0",
    "trivy": "aquasec/trivy:0.57.0",
    "osv": "ghcr.io/google/osv-scanner:v1.9.1",
}
# The repo is owned by another uid inside the container; let git read it anyway.
GIT_SAFE_DIRECTORY = ("-e", "GIT_CONFIG_COUNT=1", "-e", "GIT_CONFIG_KEY_0=safe.directory", "-e", "GIT_CONFIG_VALUE_0=*")
TRIVY_CACHE = "e2eat-trivy-cache:/root/.cache/trivy"  # shared, unlabeled on purpose: survives teardown


def scanner_args(tool: str, has_git: bool) -> list[str]:
    if tool == "gitleaks":
        target = ["git", "/src"] if has_git else ["dir", "/src"]
        return [*target, "--redact", "--no-banner", "--report-format", "json", "--report-path", "/out/gitleaks.json", "--exit-code", "0"]
    if tool == "semgrep":
        return ["semgrep", "scan", "--config", "p/default", "--json", "--output", "/out/semgrep.json", "--metrics", "off", "--quiet", "/src"]
    if tool == "trivy":
        return ["fs", "--scanners", "vuln,misconfig", "--format", "json", "--output", "/out/trivy.json", "--quiet", "/src"]
    if tool == "osv":
        return ["--format", "json", "--output", "/out/osv.json", "-r", "/src"]
    raise ValueError(f"unknown scanner {tool!r}; choose from {', '.join(SCANNER_IMAGES)}")


def scan_cmd(run_id: str, tool: str, repo: Path, out_dir: Path, has_git: bool) -> list[str]:
    args = scanner_args(tool, has_git)
    cmd = ["docker", "run", "--rm", "--label", f"{LABEL}={run_id}", *LIMITS,
           "-v", f"{repo}:/src:ro", "-v", f"{out_dir}:/out", *GIT_SAFE_DIRECTORY]
    if tool == "trivy":
        cmd += ["-v", TRIVY_CACHE]
    return [*cmd, SCANNER_IMAGES[tool], *args]


def summarize(tool: str, data: object) -> int:
    """Number of raw results a scanner reported (before the security agent triages them)."""
    if not data:
        return 0
    if tool == "gitleaks":
        return len(data)
    if tool == "semgrep":
        return len(data.get("results") or [])
    if tool == "trivy":
        return sum(len(r.get("Vulnerabilities") or []) + len(r.get("Misconfigurations") or []) for r in data.get("Results") or [])
    if tool == "osv":
        return sum(len(p.get("vulnerabilities") or []) for res in data.get("results") or [] for p in res.get("packages") or [])
    raise ValueError(f"unknown scanner {tool!r}")


def run_scans(run_dir: Path, tools: Sequence[str], runner: Runner = default_runner) -> dict:
    unknown = [tool for tool in tools if tool not in SCANNER_IMAGES]
    if unknown:
        raise ValueError(f"unknown scanner(s) {', '.join(unknown)}; choose from {', '.join(SCANNER_IMAGES)}")
    run_dir = Path(run_dir).resolve()
    run_id = read_json(run_dir / "run.json")["run_id"]
    repo = run_dir / "repo"
    out_dir = run_dir / "blackboard" / "evidence" / "security-agent"
    out_dir.mkdir(parents=True, exist_ok=True)
    has_git = (repo / ".git").exists()

    def scan(tool: str) -> dict:
        output = out_dir / f"{tool}.json"
        output.unlink(missing_ok=True)
        proc = runner(scan_cmd(run_id, tool, repo, out_dir, has_git))
        result = {"tool": tool, "image": SCANNER_IMAGES[tool], "exit_code": proc.returncode,
                  "output": output.relative_to(run_dir).as_posix()}
        if not output.exists():
            return result | {"ok": False, "error": (proc.stderr or proc.stdout or "no output")[-2000:]}
        try:
            return result | {"ok": True, "count": summarize(tool, json.loads(output.read_text(encoding="utf-8") or "null"))}
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            return result | {"ok": False, "error": f"unparsable output: {exc}"}

    with ThreadPoolExecutor(max_workers=max(1, len(tools))) as pool:
        results = list(pool.map(scan, tools))
    summary = {"results": results}
    write_json(out_dir / "scan-summary.json", summary)
    return summary
