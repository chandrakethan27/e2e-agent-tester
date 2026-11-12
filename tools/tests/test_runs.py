from datetime import datetime, timedelta, timezone

import pytest

from e2eat.cli import main
from e2eat.runs import list_runs, prune_runs
from e2eat.workspace import init_run, set_phase

T0 = datetime(2026, 10, 15, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path, sample_repo):
    runs = tmp_path / "runs"
    for i in range(4):
        init_run(str(sample_repo), "adopt", "quick", runs, now=T0 + timedelta(hours=i))
    (runs / "stray-folder").mkdir()
    (runs / "stray-folder" / "run.json").write_text('{"run_id": "other"}')
    return runs


def test_list_is_newest_first_and_ignores_non_runs(root):
    runs = list_runs(root)
    assert [r["run_id"][-6:] for r in runs] == ["120000", "110000", "100000", "090000"]
    assert all(r["size_mb"] >= 0 and r["finished"] is False for r in runs)


def test_prune_is_a_dry_run_by_default(root):
    result = prune_runs(root, keep=2)
    assert result["applied"] is False and len(result["would_remove"]) == 2 and len(result["kept"]) == 2
    assert len(list_runs(root)) == 4


def test_prune_apply_deletes_only_the_oldest(root):
    kept = [r["run_id"] for r in list_runs(root)[:2]]
    result = prune_runs(root, keep=2, apply=True)
    assert len(result["removed"]) == 2
    assert [r["run_id"] for r in list_runs(root)] == kept
    assert (root / "stray-folder").exists()  # not a run: never touched


def test_runs_in_progress_or_owning_containers_are_never_pruned(root):
    oldest, second = list_runs(root)[-1]["run_id"], list_runs(root)[-2]["run_id"]
    set_phase(root / oldest, "assess", "running")
    result = prune_runs(root, keep=1, apply=True, busy={second})
    assert sorted(result["skipped_in_use"]) == sorted([oldest, second])
    assert (root / oldest).exists() and (root / second).exists() and len(result["removed"]) == 1


def test_prune_rejects_negative_keep(root):
    with pytest.raises(ValueError):
        prune_runs(root, keep=-1)


def test_cli(root, monkeypatch, capsys):
    monkeypatch.setenv("E2EAT_HOME", str(root.parent))
    monkeypatch.setattr("e2eat.cli.runs_cmds.labelled_run_ids", lambda: set())
    assert main(["runs", "list"]) == 0
    assert len(__import__("json").loads(capsys.readouterr().out)) == 4
    assert main(["runs", "prune", "--keep", "3"]) == 0
    assert "would_remove" in capsys.readouterr().out and len(list_runs(root)) == 4
