import argparse

from e2eat.cli import build_parser

EXPECTED = {
    "init", "phase", "agent", "validate", "schema", "next-id", "findings", "messages", "set-status",
    "apply-crossexam", "finalize-findings", "status", "squad", "score", "redact", "render", "sandbox", "scan", "doctor", "git", "guard", "web",
    "reconfigure", "static-only",
}


def test_all_command_groups_registered():
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == EXPECTED
