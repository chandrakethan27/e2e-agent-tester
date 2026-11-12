"""Run workspaces on disk: listing and retention. Each run is ~100 MB (repo, evidence, scanner output)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Collection

from .jsonio import read_json_or

IN_PROGRESS = ("running",)


def _size_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(dirpath) / name).lstat().st_size
            except OSError:
                pass
    return total


def list_runs(root: Path) -> list[dict]:
    """Newest first. Only directories holding a run.json whose run_id matches the folder name count as runs."""
    out = []
    for path in sorted(Path(root).iterdir()) if Path(root).is_dir() else []:
        run = read_json_or(path / "run.json", None)
        if not path.is_dir() or not isinstance(run, dict) or run.get("run_id") != path.name:
            continue
        scores = read_json_or(path / "scores.json", {})
        phases = run.get("phases") or {}
        out.append({
            "run_id": path.name,
            "created_at": run.get("created_at", ""),
            "profile": run.get("profile"),
            "depth": run.get("depth"),
            "verdict": scores.get("verdict") if isinstance(scores, dict) else None,
            "finished": phases.get("finalize") in ("done", "failed"),
            "in_progress": any(s in IN_PROGRESS for s in phases.values()),
            "size_mb": round(_size_bytes(path) / 1024**2, 1),
        })
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


def prune_runs(root: Path, keep: int, apply: bool = False, busy: Collection[str] = ()) -> dict:
    """Delete all but the newest `keep` runs. Dry run unless apply. Runs in progress or owning Docker resources stay."""
    if keep < 0:
        raise ValueError("--keep must be 0 or more")
    runs = list_runs(root)
    candidates = runs[keep:]
    skipped = [r["run_id"] for r in candidates if r["in_progress"] or r["run_id"] in busy]
    doomed = [r for r in candidates if r["run_id"] not in skipped]
    removed = []
    if apply:
        for r in doomed:
            shutil.rmtree(Path(root) / r["run_id"])
            removed.append(r["run_id"])
    return {
        "applied": apply,
        "kept": [r["run_id"] for r in runs if r not in doomed],
        "would_remove" if not apply else "removed": [r["run_id"] for r in doomed] if not apply else removed,
        "skipped_in_use": skipped,
        "freed_mb": round(sum(r["size_mb"] for r in doomed), 1),
    }
