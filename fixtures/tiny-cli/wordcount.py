"""wc-lite: count lines, words and characters."""

import argparse
import sys


def count(text: str) -> tuple[int, int, int]:
    return text.count("\n"), len(text.split()), len(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="wc-lite", description=__doc__)
    parser.add_argument("files", nargs="*", help="files to count (default: stdin)")
    args = parser.parse_args(argv)
    for name in args.files or ["-"]:
        try:
            text = sys.stdin.read() if name == "-" else open(name, encoding="utf-8").read()
        except OSError as exc:
            print(f"wc-lite: {exc}", file=sys.stderr)
            return 1
        lines, words, chars = count(text)
        print(f"{lines} {words} {chars} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
