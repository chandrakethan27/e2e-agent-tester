"""Render report.md and a self-contained report.html from a run's artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from jinja2 import ChainableUndefined, Environment, PackageLoader

from .blackboard import load_findings, severity_rank
from .jsonio import read_json, read_json_or
from .score import DIMENSIONS
from .validate import LINE_SUFFIX, evidence_problem

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
VERDICT_TONE = {"Adopt": "good", "Production-ready": "good", "Trial": "ok", "Needs work": "ok",
                "Assess": "warn", "Hold": "bad", "Not ready": "bad"}


def evidence_href(run_dir: Path, ref: str) -> str | None:
    """Link only evidence that exists inside the run folder, percent-encoded so a browser cannot read it as a URL scheme."""
    if evidence_problem(run_dir, ref) is not None:
        return None
    return "./" + quote(LINE_SUFFIX.sub("", ref))


def verdict_tone(verdict: object) -> str:
    return VERDICT_TONE.get(str(verdict or "").split(" (")[0], "neutral")


def gather(run_dir: Path, now: datetime | None = None) -> dict:
    run_dir = Path(run_dir)
    facts = run_dir / "blackboard" / "facts"
    findings = load_findings(run_dir)
    confirmed = sorted((f for f in findings if f.get("status") == "confirmed"), key=lambda f: (severity_rank(f), f["id"]))
    return {
        "run": read_json(run_dir / "run.json"),
        "recon": read_json_or(facts / "recon.json", {}),
        "runtime": read_json_or(facts / "runtime.json", {}),
        "scores": read_json_or(run_dir / "scores.json", {}),
        "usecases": read_json_or(run_dir / "usecases.json", {}),
        "report": read_json_or(run_dir / "report.json", {}),
        "findings": confirmed,
        "dropped_count": sum(1 for f in findings if f.get("status") == "dropped"),
        "dimensions": DIMENSIONS,
        "generated_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC"),
    }


def _environment(autoescape: bool, run_dir: Path) -> Environment:
    env = Environment(
        loader=PackageLoader("e2eat", "templates"),
        autoescape=autoescape,
        undefined=ChainableUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["evidence_href"] = lambda ref: evidence_href(run_dir, ref)
    env.filters["tone"] = verdict_tone
    env.tests["image"] = lambda ref: (evidence_href(run_dir, ref) or "").lower().endswith(IMAGE_SUFFIXES)
    return env


def render_run(run_dir: Path, now: datetime | None = None) -> dict[str, str]:
    run_dir = Path(run_dir)
    context = gather(run_dir, now)
    html_path, md_path = run_dir / "report.html", run_dir / "report.md"
    html_path.write_text(_environment(True, run_dir).get_template("report.html.j2").render(**context), encoding="utf-8")
    md_path.write_text(_environment(False, run_dir).get_template("report.md.j2").render(**context), encoding="utf-8")
    return {"html": str(html_path), "markdown": str(md_path)}
