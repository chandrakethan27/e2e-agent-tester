from pathlib import Path

import pytest

from e2eat.blackboard import update_finding
from e2eat.render import evidence_href, render_run
from e2eat.score import score_run
from e2eat.workspace import set_agent
from helpers import add_finding, write_json


@pytest.mark.parametrize(
    "ref, href",
    [
        ("repo/src/app.py:12", "./repo/src/app.py"),
        ("blackboard/evidence/x.log#L3", "./blackboard/evidence/x.log"),
        ("blackboard/evidence/javascript:alert(1)", "./blackboard/evidence/javascript%3Aalert%281%29"),
        ("javascript:alert(1)", None),
        (" javascript:alert(1)", None),
        ("\tjavascript:alert(1)", None),
        ("java\tscript:alert(1)", None),
        ("/etc/passwd", None),
        ("../x", None),
        ("%2e%2e/x", None),
        ("https://evil.example", None),
    ],
)
def test_evidence_href(run_dir, ref, href):
    evidence = run_dir / "blackboard/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "x.log").write_text("x")
    (evidence / "javascript:alert(1)").write_text("x")
    assert evidence_href(run_dir, ref) == href


def test_render_full_report_escapes_repo_text(run_dir):
    set_agent(run_dir, "security-agent", "done")
    shot = run_dir / "blackboard/evidence/functional-tester/shot.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    add_finding(
        run_dir,
        with_evidence=False,
        title="<script>alert(1)</script> in search",
        evidence=["blackboard/evidence/functional-tester/shot.png", "javascript:alert(1)", "repo/src/app.py:1"],
    )
    add_finding(run_dir, id="F-security-002")
    update_finding(run_dir, "F-security-001", status="confirmed")
    update_finding(run_dir, "F-security-002", status="dropped")
    score_run(run_dir)
    write_json(run_dir / "usecases.json", {
        "use_cases": [{"title": "Internal catalog search", "scenario": "Ops team lookups", "industries": ["retail"], "fit": "medium",
                       "why": "Fast reads", "integration_sketch": "Behind the gateway", "prerequisites": ["Fix F-security-001"], "risks": ["SQLi"]}],
        "anti_use_cases": [{"title": "Public internet", "why": "Injection risk"}],
        "alternatives": [{"name": "Evil", "url": "javascript:alert(2)", "when_better": "never", "when_worse": "always"}],
        "integration_patterns": ["Read-only service behind an API gateway"],
    })
    write_json(run_dir / "report.json", {
        "executive_summary": "A small shop API with a serious injection flaw.", "verdict_rationale": "Security gate.",
        "highlights": ["Starts in 2 seconds"], "top_risks": ["F-security-001"], "coverage_notes": ["Perf not tested"],
        "next_steps": ["Fix the SQL injection"],
    })
    paths = render_run(run_dir)
    html = Path(paths["html"]).read_text()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert" not in html
    assert 'href="./blackboard/evidence/functional-tester/shot.png"' in html
    assert '<img src="./blackboard/evidence/functional-tester/shot.png"' in html
    assert 'href="./repo/src/app.py"' in html
    assert 'href="javascript:' not in html
    assert "Internal catalog search" in html and "Read-only service behind an API gateway" in html
    md = Path(paths["markdown"]).read_text()
    assert "## Findings (1 confirmed, 1 dropped)" in md
    assert "**Verdict:" in md


def test_render_with_missing_artifacts(run_dir):
    html = Path(render_run(run_dir)["html"]).read_text()
    assert "Not scored" in html and "No confirmed findings." in html


def test_banner_warns_when_project_was_never_run(run_dir):
    write_json(run_dir / "blackboard/facts/runtime.json", {"status": "could-not-run", "strategy": "none"})
    html = Path(render_run(run_dir)["html"]).read_text()
    md = Path(run_dir / "report.md").read_text()
    assert "NOT RUN" in html and "static review only" in html
    assert "NOT RUN" in md and "static review only" in md


def test_banner_warns_when_runtime_facts_are_missing(run_dir):
    assert "NOT RUN" in Path(render_run(run_dir)["html"]).read_text()


def test_banner_lists_failed_agents_when_run_was_partial(run_dir):
    write_json(run_dir / "blackboard/facts/runtime.json", {"status": "running", "strategy": "repo-docker"})
    set_agent(run_dir, "suite-runner", "failed", note="disk full")
    html = Path(render_run(run_dir)["html"]).read_text()
    assert "PARTIAL" in html and "suite-runner" in html and "disk full" in html
    assert "NOT RUN" not in html


def test_no_banner_for_a_complete_run(run_dir):
    write_json(run_dir / "blackboard/facts/runtime.json", {"status": "running", "strategy": "repo-docker"})
    set_agent(run_dir, "security-agent", "done")
    html = Path(render_run(run_dir)["html"]).read_text()
    assert "NOT RUN" not in html and "PARTIAL" not in html
