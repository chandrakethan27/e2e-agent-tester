import tarfile
import zipfile

import pytest

from e2eat.source import Source, drop_escaping_symlinks, extract_archive, fetch_source, parse_source


@pytest.mark.parametrize(
    "raw, location, slug, ref",
    [
        ("https://github.com/vercel/next.js", "https://github.com/vercel/next.js.git", "vercel-next-js", None),
        ("github.com/vercel/next.js/", "https://github.com/vercel/next.js.git", "vercel-next-js", None),
        ("http://www.github.com/Owner/Repo.git", "https://github.com/Owner/Repo.git", "owner-repo", None),
        ("https://github.com/o/r/tree/feature/x", "https://github.com/o/r.git", "o-r", "feature/x"),
        ("git@github.com:o/r.git", "https://github.com/o/r.git", "o-r", None),
        ("https://gitlab.com/group/sub/proj.git", "https://gitlab.com/group/sub/proj.git", "sub-proj", None),
    ],
)
def test_parse_git_sources(raw, location, slug, ref):
    src = parse_source(raw)
    assert (src.kind, src.location, src.slug, src.ref) == ("git", location, slug, ref)


def test_parse_directory(sample_repo):
    src = parse_source(str(sample_repo))
    assert (src.kind, src.slug, src.location) == ("dir", "my-sample-repo", str(sample_repo.resolve()))


def test_parse_archive(tmp_path):
    archive = tmp_path / "Cool_App-main.tar.gz"
    archive.write_bytes(b"")
    assert parse_source(str(archive)) == Source("archive", str(archive.resolve()), "cool-app-main")


@pytest.mark.parametrize("raw", ["https://github.com/o/r/issues/5", "/definitely/not/here", "  "])
def test_parse_rejects_unknown(raw):
    with pytest.raises(ValueError):
        parse_source(raw)


def test_fetch_dir_skips_heavy_dirs(sample_repo, tmp_path):
    dest = tmp_path / "copy"
    fetch_source(parse_source(str(sample_repo)), dest)
    assert (dest / "src" / "app.py").exists()
    assert not (dest / "node_modules").exists()


def test_fetch_git_builds_clone_command(tmp_path):
    calls = []
    fetch_source(parse_source("https://github.com/o/r/tree/dev"), tmp_path / "x", runner=lambda cmd, check: calls.append(cmd))
    assert calls == [
        ["git", "clone", "--filter=blob:none", "--no-tags", "--branch", "dev", "https://github.com/o/r.git", str(tmp_path / "x")]
    ]


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def test_extract_zip_unwraps_single_top_folder(tmp_path):
    archive = tmp_path / "proj-main.zip"
    _zip(archive, {"proj-main/README.md": "hi", "proj-main/proj-main/inner.txt": "same name nested"})
    dest = tmp_path / "out"
    extract_archive(archive, dest)
    assert (dest / "README.md").read_text() == "hi"
    assert (dest / "proj-main" / "inner.txt").exists()


def test_extract_zip_rejects_traversal(tmp_path):
    archive = tmp_path / "evil.zip"
    _zip(archive, {"../escape.txt": "x"})
    with pytest.raises(ValueError, match="unsafe"):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_extract_tar_rejects_escaping_symlink(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)
    with pytest.raises(ValueError, match="unsafe"):
        extract_archive(archive, tmp_path / "out")


def test_drop_escaping_symlinks(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ok.txt").write_text("x")
    (root / "inside").symlink_to(root / "ok.txt")
    (root / "outside").symlink_to(tmp_path)
    assert drop_escaping_symlinks(root) == ["outside"]
    assert (root / "inside").is_symlink()
    assert not (root / "outside").is_symlink()
