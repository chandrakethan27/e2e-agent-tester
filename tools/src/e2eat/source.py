"""Turn a user-supplied source (GitHub URL, git URL, directory, archive) into a local copy."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar", ".zip")
COPY_IGNORE = shutil.ignore_patterns("node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox")

_GITHUB = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?"
    r"(?:/tree/(?P<ref>[^?#]+?))?/?(?:[?#].*)?$"
)
_GITHUB_SSH = re.compile(r"^git@github\.com:(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$")
_GIT_URL = re.compile(r"^https?://\S+\.git/?$")
_USERINFO = re.compile(r"^(https?://)[^/@\s]+@")
# Imported .git metadata is attacker-controlled; host-side git must never see its config or hooks.
SAFE_GIT_CONFIG = "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n"


@dataclass(frozen=True)
class Source:
    kind: str  # "git" | "dir" | "archive"
    location: str  # clone URL or absolute local path
    slug: str  # safe for run ids, docker names and compose projects
    ref: str | None = None


def strip_userinfo(url: str) -> str:
    """Hide user:token@ in URLs before they are stored or shown."""
    return _USERINFO.sub(r"\1***@", url)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "project"


def _archive_stem(name: str) -> str | None:
    lower = name.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return None


def parse_source(raw: str) -> Source:
    text = raw.strip()
    if not text:
        raise ValueError("source is empty")
    for pattern in (_GITHUB, _GITHUB_SSH):
        if m := pattern.match(text):
            owner, repo = m["owner"], m["repo"]
            url = f"https://github.com/{owner}/{repo}.git"
            return Source("git", url, slugify(f"{owner}-{repo}"), m.groupdict().get("ref"))
    if _GIT_URL.match(text):
        parts = text.rstrip("/").removesuffix(".git").split("/")
        return Source("git", text, slugify("-".join(parts[-2:])))
    path = Path(text).expanduser().resolve()
    if path.is_dir():
        return Source("dir", str(path), slugify(path.name))
    if path.is_file() and (stem := _archive_stem(path.name)) is not None:
        return Source("archive", str(path), slugify(stem))
    raise ValueError(f"not a GitHub/git URL, directory, or .zip/.tar.gz/.tgz/.tar archive: {raw}")


def fetch_source(source: Source, dest: Path, runner: Callable[..., object] = subprocess.run) -> None:
    if source.kind == "git":
        cmd = ["git", "clone", "--no-tags"]  # full history: secret scanners need old blobs offline
        if source.ref:
            cmd += ["--branch", source.ref]
        runner([*cmd, source.location, str(dest)], check=True)
        if strip_userinfo(source.location) != source.location:
            runner(["git", "-C", str(dest), "remote", "set-url", "origin", strip_userinfo(source.location)], check=True)
    elif source.kind == "dir":
        shutil.copytree(source.location, dest, symlinks=True, ignore=COPY_IGNORE)
    elif source.kind == "archive":
        extract_archive(Path(source.location), dest)
    else:
        raise ValueError(f"unknown source kind {source.kind!r}")


def extract_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True)
    root = dest.resolve()
    if archive.name.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if not (root / member).resolve().is_relative_to(root):
                    raise ValueError(f"unsafe path in archive: {member}")
            zf.extractall(dest)
    else:
        try:
            with tarfile.open(archive) as tf:
                tf.extractall(dest, filter="data")  # rejects absolute paths, '..' and links leaving dest
        except tarfile.FilterError as exc:
            raise ValueError(f"unsafe archive member: {exc}") from exc
    _unwrap_single_dir(dest)


def _unwrap_single_dir(dest: Path) -> None:
    """GitHub-style archives wrap everything in one folder; lift its contents up a level."""
    shutil.rmtree(dest / "__MACOSX", ignore_errors=True)
    entries = list(dest.iterdir())
    if len(entries) != 1 or not entries[0].is_dir() or entries[0].is_symlink():
        return
    inner = entries[0].rename(dest / f".e2eat-unwrap-{uuid.uuid4().hex}")
    for child in inner.iterdir():
        child.rename(dest / child.name)
    inner.rmdir()


def drop_escaping_symlinks(root: Path) -> list[str]:
    """Delete symlinks that point outside root so no agent or build can read host files through them."""
    root = Path(root).resolve()
    dropped: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            path = Path(dirpath) / name
            if path.is_symlink() and not path.resolve().is_relative_to(root):
                dropped.append(path.relative_to(root).as_posix())
                path.unlink()
                if name in dirnames:
                    dirnames.remove(name)
    return sorted(dropped)


def neutralize_git_dir(root: Path) -> list[str]:
    """Drop gitdir redirects and hooks, and reset config, so host git cannot run repo-controlled commands."""
    git = Path(root) / ".git"
    if git.is_symlink() or git.is_file():
        git.unlink()
        return ["removed .git file (gitdir redirect) from the source"]
    if git.is_dir():
        shutil.rmtree(git / "hooks", ignore_errors=True)
        (git / "config").write_text(SAFE_GIT_CONFIG, encoding="utf-8")
        return ["reset imported .git/config and removed .git/hooks"]
    return []
