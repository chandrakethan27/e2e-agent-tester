"""Fixture projects exist and ingest cleanly as local sources."""

from pathlib import Path

import pytest

from e2eat.workspace import init_run

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.mark.parametrize("name, marker", [("vuln-flask", "app.py"), ("tiny-cli", "wordcount.py"), ("broken-build", "package.json")])
def test_fixture_ingests(tmp_path, name, marker):
    run_dir = init_run(str(FIXTURES / name), "adopt", "quick", tmp_path / "runs")
    assert (run_dir / "repo" / marker).exists()


def test_expectations_documented():
    text = (FIXTURES / "EXPECTED.md").read_text()
    for name in ("vuln-flask", "tiny-cli", "broken-build"):
        assert name in text
