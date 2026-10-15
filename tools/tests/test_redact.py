from e2eat.redact import parse_env_file, redact_run, redact_text


def test_parse_env_file(tmp_path):
    env = tmp_path / "secrets.env"
    env.write_text("# comment\nexport OPENAI_API_KEY='sk-test-123456'\nEMPTY=\nPLAIN=abc\n\nBAD LINE\n")
    assert parse_env_file(env) == {"OPENAI_API_KEY": "sk-test-123456", "EMPTY": "", "PLAIN": "abc"}


def test_redact_text_handles_regex_chars_overlaps_and_short_values():
    secrets = {"A": "p@ss.w*rd(1)", "B": "p@ss", "SHORT": "ab"}
    text = "login p@ss.w*rd(1) then p@ss and ab"
    assert redact_text(text, secrets) == "login [REDACTED:A] then [REDACTED:B] and ab"


def test_redact_run_scrubs_blackboard_and_outputs_but_not_repo(run_dir):
    log = run_dir / "blackboard/evidence/runner-agent/build.log"
    log.parent.mkdir(parents=True)
    log.write_text("key=sk-live-999999\n")
    png = run_dir / "blackboard/evidence/functional-tester/shot.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    (run_dir / "report.md").write_text("token sk-live-999999")
    (run_dir / "repo/config.txt").write_text("sk-live-999999")
    changed = redact_run(run_dir, {"STRIPE_KEY": "sk-live-999999"})
    assert changed == ["blackboard/evidence/runner-agent/build.log", "report.md"]
    assert log.read_text() == "key=[REDACTED:STRIPE_KEY]\n"
    assert (run_dir / "repo/config.txt").read_text() == "sk-live-999999"


def test_parse_env_file_inline_comments_and_multiline_values(tmp_path):
    env = tmp_path / "secrets.env"
    env.write_text('A=abc123 # rotated monthly\nPEM="-----BEGIN KEY-----\nMIIBOgIBAAJBAKj\n-----END KEY-----"\nB="quoted # kept"\n')
    assert parse_env_file(env) == {"A": "abc123", "PEM": "", "B": "quoted # kept"}


def test_redaction_keeps_json_valid_and_skips_literal_values(run_dir):
    scores = run_dir / "scores.json"
    scores.write_text('{"covered": true, "note": "token q\\"uote\\\\back here"}')
    changed = redact_run(run_dir, {"DEBUG": "true", "TOKEN": 'q"uote\\back'})
    assert changed == ["scores.json"]
    assert scores.read_text().count("true") == 1 and "[REDACTED:TOKEN]" in scores.read_text()
    import json

    json.loads(scores.read_text())


def test_redaction_handles_non_utf8_files_and_run_json(run_dir):
    log = run_dir / "blackboard/evidence/runner-agent/build.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"\xff\xfe secret=sk-live-999999\n")
    run_json = run_dir / "run.json"
    run_json.write_text(run_json.read_text().replace('"notes": []', '"notes": ["leaked sk-live-999999"]'))
    changed = redact_run(run_dir, {"K": "sk-live-999999"})
    assert set(changed) == {"blackboard/evidence/runner-agent/build.log", "run.json"}
    assert b"sk-live" not in log.read_bytes()
