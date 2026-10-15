import json
import subprocess
from pathlib import Path

import pytest

from e2eat.scan import run_scans, scan_cmd, scanner_args, summarize

RID = "o-r-20261015-093000"


def test_scan_cmd_mounts_repo_read_only_without_run_network(tmp_path):
    cmd = scan_cmd(RID, "gitleaks", tmp_path / "repo", tmp_path / "out", has_git=False)
    joined = " ".join(cmd)
    assert f"{tmp_path / 'repo'}:/src:ro" in joined
    assert f"--label e2eat.run={RID}" in joined
    assert "--network" not in joined
    args = scanner_args("gitleaks", False)
    assert cmd[-len(args):] == args
    assert scanner_args("gitleaks", True)[:2] == ["git", "/src"]
    assert "--redact" in args


@pytest.mark.parametrize(
    "tool, data, count",
    [
        ("gitleaks", [{"RuleID": "generic-api-key"}], 1),
        ("semgrep", {"results": [{}, {}]}, 2),
        ("trivy", {"Results": [{"Vulnerabilities": [{}, {}], "Misconfigurations": [{}]}, {"Vulnerabilities": None}]}, 3),
        ("osv", {"results": [{"packages": [{"vulnerabilities": [{}, {}]}, {"vulnerabilities": []}]}]}, 2),
        ("gitleaks", None, 0),
    ],
)
def test_summarize(tool, data, count):
    assert summarize(tool, data) == count


def test_run_scans_writes_summary(run_dir):
    def runner(cmd):
        out_dir = Path(next(v.split(":")[0] for v in cmd if v.endswith(":/out")))
        tool = "osv" if "osv-scanner" in " ".join(cmd) else "gitleaks"
        (out_dir / f"{tool}.json").write_text(json.dumps({"results": []} if tool == "osv" else []))
        return subprocess.CompletedProcess(cmd, 1 if tool == "osv" else 0, "", "")

    summary = run_scans(run_dir, ["gitleaks", "osv"], runner=runner)
    assert [(r["tool"], r["ok"], r["count"]) for r in summary["results"]] == [("gitleaks", True, 0), ("osv", True, 0)]
    assert (run_dir / "blackboard/evidence/security-agent/scan-summary.json").exists()


def test_run_scans_reports_missing_output(run_dir):
    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 2, "", "image pull failed")

    result = run_scans(run_dir, ["semgrep"], runner=runner)["results"][0]
    assert result["ok"] is False and "image pull failed" in result["error"]


def test_unknown_scanner(run_dir):
    with pytest.raises(ValueError):
        run_scans(run_dir, ["nmap"])


def test_partial_gitleaks_scan_is_not_ok(run_dir):
    def runner(cmd):
        out_dir = Path(next(v.split(":")[0] for v in cmd if v.endswith(":/out")))
        (out_dir / "gitleaks.json").write_text("[]")
        return subprocess.CompletedProcess(cmd, 0, "", "WRN partial scan completed in 1s\nINF no leaks found")

    result = run_scans(run_dir, ["gitleaks"], runner=runner)["results"][0]
    assert result["ok"] is False and "partial scan" in result["error"]
