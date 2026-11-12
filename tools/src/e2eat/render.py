"""Render report.md and a self-contained report.html from a run's artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from jinja2 import ChainableUndefined, Environment, PackageLoader

from .blackboard import load_findings, severity_rank
from .jsonio import read_json, read_json_or, read_json_strict
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


def testing_notice(run: dict, runtime: dict, scores: dict | None = None) -> dict | None:
    """Tell the reader when the verdict rests on less than a full run of the project."""
    if runtime.get("status") == "static-only":
        return {"level": "STATIC ONLY", "title": "Static review chosen: the project was not run",
                "text": "At your request nothing was executed. This verdict comes from reading the code, dependencies, configuration and "
                        "repository health; behaviour, performance and reliability are unverified."}
    if runtime.get("status") != "running":
        return {"level": "NOT RUN", "title": "The project was NOT run",
                "text": "This verdict comes from static review only (code, dependencies, configuration, repository health). "
                        "No journeys, load or reliability checks ran against a live instance, so behaviour is unverified."}
    failed = {name: entry.get("note", "no reason recorded") for name, entry in run.get("agents", {}).items() if entry.get("status") == "failed"}
    if failed:
        return {"level": "PARTIAL", "title": "Some checks did not complete",
                "text": "The project ran, but these agents failed, so their areas are untested: "
                        + "; ".join(f"{name} ({note})" for name, note in sorted(failed.items())) + "."}
    caps = (scores or {}).get("caps") or []
    if caps:
        return {"level": "PARTIAL", "title": "Some checks did not complete",
                "text": "The project ran, but the verdict is limited: " + "; ".join(str(c) for c in caps) + "."}
    return None


def _claims_ledger(recon: dict, facts: object) -> list[dict]:
    """Every claim the README makes with its result: pass, fail or untested (the default, never an implied pass)."""
    results = {c.get("claim_id"): c for c in (facts.get("claims") if isinstance(facts, dict) else None) or [] if isinstance(c, dict)}
    ledger = []
    for claim in recon.get("claims") or []:
        if not isinstance(claim, dict) or "id" not in claim:
            continue
        found = results.get(claim["id"], {})
        evidence = [e for e in found.get("evidence") or [] if isinstance(e, str)]
        ledger.append({"id": claim["id"], "text": claim.get("text", ""), "result": str(found.get("result", "untested")),
                       "note": found.get("note", ""), "evidence": evidence})
    return ledger


def gather(run_dir: Path, now: datetime | None = None) -> dict:
    run_dir = Path(run_dir)
    facts = run_dir / "blackboard" / "facts"
    findings = load_findings(run_dir)
    confirmed = sorted((f for f in findings if f.get("status") == "confirmed"), key=lambda f: (severity_rank(f), f["id"]))
    run = read_json(run_dir / "run.json")
    # A missing file renders as an empty section; a malformed one is an error the reader must hear about, not a blank.
    runtime = read_json_strict(facts / "runtime.json", {}, dict)
    recon = read_json_strict(facts / "recon.json", {}, dict)
    scores = read_json_strict(run_dir / "scores.json", {}, dict)
    report = read_json_strict(run_dir / "report.json", {}, dict)
    functional = read_json_or(facts / "functional-tester.json", {})
    ids = {f["id"] for f in confirmed}
    listed = [i for i in report.get("top_risks") or [] if isinstance(i, str)]
    dropped = [f for f in findings if f.get("status") == "dropped"]
    return {
        "notice": testing_notice(run, runtime, scores),
        "run": run,
        "recon": recon,
        "runtime": runtime,
        "scores": scores,
        "usecases": read_json_strict(run_dir / "usecases.json", {}, dict),
        "report": report,
        "briefing": read_json_strict(facts / "briefing.json", {}, dict),
        "claims": _claims_ledger(recon, functional),
        "journeys": [j for j in (functional.get("journeys") if isinstance(functional, dict) else None) or [] if isinstance(j, dict)],
        "top_risks": [i for i in listed if i in ids],
        "top_risks_removed": sum(1 for i in listed if i not in ids),
        "findings": confirmed,
        "dropped": dropped,
        "dropped_count": len(dropped),
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
