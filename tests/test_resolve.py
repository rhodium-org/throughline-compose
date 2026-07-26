# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""Resolver tests (SR-0006): local paths, and url sources fetched by pinned ref
into a cache outside the project tree. A throwaway local git repo stands in for a
remote origin — git clones a filesystem path exactly as it would a URL."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from throughline_compose.resolve import ResolveError, resolve_source
from throughline_compose.sources import Source

_TOML = '[project]\nname = "src"\nformat_version = 2\n'


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=True, capture_output=True, text=True)


def _origin(tmp_path: Path, tag: str = "v4.0.3", subdir: str | None = None) -> Path:
    """A minimal throughline project in a git repo, tagged like a source edition.

    When ``subdir`` is given the throughline.toml lives under that subpath, standing
    in for a graph inside a larger application repo (SR-0008)."""
    repo = tmp_path / "origin"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    proj = repo / subdir if subdir else repo
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "throughline.toml").write_text(_TOML)
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "edition", cwd=repo)
    _git("tag", tag, cwd=repo)
    return repo


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TL_COMPOSE_CACHE", str(tmp_path / "cache"))


def test_local_path_resolves(tmp_path):
    src = tmp_path / "local"
    src.mkdir()
    (src / "throughline.toml").write_text(_TOML)
    got = resolve_source(Source(namespace="s", path="local"), tmp_path)
    assert got == src.resolve()


def test_local_path_missing_fails(tmp_path):
    with pytest.raises(ResolveError, match="does not exist"):
        resolve_source(Source(namespace="s", path="nope"), tmp_path)


def test_url_ref_fetched_into_cache(tmp_path):
    origin = _origin(tmp_path)
    src = Source(namespace="asvs", url=str(origin), ref="v4.0.3")
    got = resolve_source(src, tmp_path)
    # Materialised outside the consumer tree, with the source's content present.
    assert (got / "throughline.toml").is_file()
    assert tmp_path / "consumer" not in got.parents
    assert str(tmp_path / "cache") in str(got)


def test_url_ref_is_idempotent(tmp_path):
    origin = _origin(tmp_path)
    src = Source(namespace="asvs", url=str(origin), ref="v4.0.3")
    first = resolve_source(src, tmp_path)
    marker = first / "RESOLVED_ONCE"
    marker.write_text("x")  # survives only if the second call does not refetch
    second = resolve_source(src, tmp_path)
    assert second == first
    assert marker.is_file()


def test_bad_ref_fails_fast(tmp_path):
    origin = _origin(tmp_path)
    src = Source(namespace="asvs", url=str(origin), ref="v9.9.9")
    with pytest.raises(ResolveError):
        resolve_source(src, tmp_path)


def test_url_subdir_resolves_to_subproject(tmp_path):  # SR-0008
    origin = _origin(tmp_path, subdir="requirements")
    src = Source(namespace="console", url=str(origin), ref="v4.0.3",
                 subdir="requirements")
    got = resolve_source(src, tmp_path)
    assert got.name == "requirements"
    assert (got / "throughline.toml").is_file()


def test_url_subdir_missing_fails(tmp_path):  # SR-0008
    origin = _origin(tmp_path, subdir="requirements")
    src = Source(namespace="console", url=str(origin), ref="v4.0.3",
                 subdir="nope")
    with pytest.raises(ResolveError, match="does not exist"):
        resolve_source(src, tmp_path)


def test_url_subdir_without_toml_fails(tmp_path):  # SR-0008
    # A repo whose root IS a project, but the named subdir is not a throughline dir.
    origin = _origin(tmp_path)
    (origin / "docs").mkdir()
    (origin / "docs" / "README.md").write_text("# docs\n")
    _git("add", ".", cwd=origin)
    _git("commit", "-m", "docs", cwd=origin)
    _git("tag", "v5", cwd=origin)
    src = Source(namespace="console", url=str(origin), ref="v5", subdir="docs")
    with pytest.raises(ResolveError, match="not a throughline project"):
        resolve_source(src, tmp_path)


def test_local_path_subdir_resolves(tmp_path):  # SR-0008
    root = tmp_path / "app"
    (root / "requirements").mkdir(parents=True)
    (root / "requirements" / "throughline.toml").write_text(_TOML)
    got = resolve_source(
        Source(namespace="console", path="app", subdir="requirements"), tmp_path)
    assert got == (root / "requirements").resolve()
