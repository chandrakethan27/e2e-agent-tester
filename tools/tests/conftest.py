from datetime import datetime, timezone
from pathlib import Path

import pytest

from e2eat.workspace import init_run


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "My.Sample Repo"
    (repo / "src").mkdir(parents=True)
    (repo / "README.md").write_text("# Sample\n")
    (repo / "src" / "app.py").write_text("print('hi')\n")
    (repo / "node_modules" / "left-pad").mkdir(parents=True)
    (repo / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1\n")
    return repo


@pytest.fixture
def run_dir(tmp_path: Path, sample_repo: Path) -> Path:
    now = datetime(2026, 10, 15, 9, 30, 0, tzinfo=timezone.utc)
    return init_run(str(sample_repo), "adopt", "quick", tmp_path / "runs", now=now)
