# wc-lite

A tiny `wc` clone in pure Python with no dependencies.

    python wordcount.py notes.txt
    cat notes.txt | python wordcount.py

- Prints lines, words and characters for each file.
- Reads standard input when no file is given.
- Exits with code 1 when a file cannot be read.

Tests: `pip install -r requirements-dev.txt && pytest`
