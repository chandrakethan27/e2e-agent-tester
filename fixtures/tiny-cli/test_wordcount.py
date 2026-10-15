from wordcount import count, main


def test_count_basic():
    assert count("hello world\nbye\n") == (2, 3, 16)


def test_main_reads_file(tmp_path, capsys):
    f = tmp_path / "a.txt"
    f.write_text("one two\n")
    assert main([str(f)]) == 0
    assert capsys.readouterr().out.strip() == f"1 2 8 {f}"


def test_missing_file_exit_code():
    assert main(["/nope/missing.txt"]) == 1
