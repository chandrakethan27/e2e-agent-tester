import json

from e2eat.cli import main


def test_cli_init_phase_agent(tmp_path, sample_repo, capsys):
    args = ["init", str(sample_repo), "--profile", "audit", "--depth", "quick", "--runs-root", str(tmp_path / "runs")]
    assert main(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["run_id"].startswith("my-sample-repo-")
    run_dir = out["run_dir"]
    assert main(["phase", run_dir, "intake", "running"]) == 0
    assert json.loads(capsys.readouterr().out)["intake"] == "running"
    assert main(["agent", run_dir, "recon-agent", "running", "--agent-id", "a1"]) == 0
    assert json.loads(capsys.readouterr().out)["agent_id"] == "a1"


def test_cli_reports_errors(tmp_path, capsys):
    assert main(["init", str(tmp_path / "missing"), "--runs-root", str(tmp_path)]) == 2
    assert "e2eat: error" in capsys.readouterr().err
