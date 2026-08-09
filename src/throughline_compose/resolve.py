# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""Resolve a declared source to a local directory (SR-0006).

A ``path`` source resolves to a directory relative to the consumer project. A
``url`` + ``ref`` source is fetched from its git origin at the pinned ref into a
cache that lives *outside* any project tree — a shared, per-user store keyed by
origin URL and ref, so a consumer's own item scan never ingests a resolved source
(the reason a resolved source must not live under the project root, per SR-0006).

Resolution is idempotent and offline after the first fetch: a source already
present in the cache at the pinned ref is reused, never refetched.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .sources import Source

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _announce(msg: str) -> None:
    """Say what is being fetched, while it is being fetched (SR-0031).

    Standard error, so machine-readable output on stdout is unaffected. Only the
    cold-cache path calls this, which is what keeps it honest as a progress notice
    rather than noise: a run that prints nothing is a run that had nothing slow to
    do, and every run that does have a network fetch ahead of it says so first."""
    print(f"tl-compose: {msg}", file=sys.stderr, flush=True)


class ResolveError(Exception):
    """A source could not be resolved — bad path, or a git fetch that failed."""


def cache_root() -> Path:
    """The per-user source cache, outside any project tree (SR-0006).

    Honours ``TL_COMPOSE_CACHE`` for tests and CI; otherwise ``XDG_CACHE_HOME`` or
    ``~/.cache``.
    """
    override = os.environ.get("TL_COMPOSE_CACHE")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "throughline-compose" / "sources"


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text).strip("-") or "x"


def _cache_dir(url: str, ref: str) -> Path:
    # Key by (url, ref). A short hash guarantees uniqueness; a readable slug of the
    # url's last segment and the ref makes the directory legible on disk.
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    tail = _slug(url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))
    return cache_root() / f"{tail}-{digest}@{_slug(ref)}"


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True, text=True,
        )
    except FileNotFoundError as e:  # pragma: no cover - git absent
        raise ResolveError("git is not installed; it is required to fetch url sources") from e


def _fetch(url: str, ref: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".fetch-", dir=dest.parent))
    try:
        # --branch accepts a tag or branch name; a bare commit SHA needs a second
        # step, so fall back to a full clone + checkout when the pinned clone fails.
        r = _git("clone", "--depth", "1", "--branch", ref, url, str(tmp))
        if r.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            tmp = Path(tempfile.mkdtemp(prefix=".fetch-", dir=dest.parent))
            r = _git("clone", url, str(tmp))
            if r.returncode != 0:
                raise ResolveError(
                    f"could not clone {url}: {r.stderr.strip() or 'git clone failed'}")
            co = _git("checkout", ref, cwd=tmp)
            if co.returncode != 0:
                raise ResolveError(
                    f"ref '{ref}' not found in {url}: "
                    f"{co.stderr.strip() or 'git checkout failed'}")
        # Publish atomically: dest only ever appears fully materialised.
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def _descend(root: Path, source: Source) -> Path:
    """Apply an optional ``subdir`` (SR-0008), returning the project directory.

    ``subdir`` is validated relative and non-escaping at parse time; here we also
    confirm it stays within ``root`` after resolution (defence in depth against a
    symlink in the fetched tree) and that it is itself a throughline project.
    """
    if not source.subdir:
        return root
    target = (root / source.subdir).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ResolveError(
            f"source '{source.namespace}' subdir '{source.subdir}' escapes the "
            "source root")
    if not target.is_dir():
        raise ResolveError(
            f"source '{source.namespace}' subdir '{source.subdir}' does not exist")
    return target


def resolve_source(source: Source, consumer_root: Path) -> Path:
    """Return the local directory a source composes from.

    ``path`` sources resolve relative to ``consumer_root``; ``url`` sources are
    fetched (once) into the per-user cache. An optional ``subdir`` then selects the
    throughline project within that tree (SR-0008).
    """
    if not source.is_remote:
        assert source.path is not None
        local = (consumer_root / source.path).resolve()
        if not local.is_dir():
            raise ResolveError(
                f"source '{source.namespace}' path does not exist: {local}")
        project = _descend(local, source)
        if not (project / "throughline.toml").is_file():
            raise ResolveError(
                f"source '{source.namespace}' at {project} is not a throughline "
                "project (no throughline.toml)")
        return project

    assert source.url is not None and source.ref is not None
    dest = _cache_dir(source.url, source.ref)
    if not (dest.is_dir() and (dest / ".git").exists()):
        if dest.exists():  # partial/corrupt leftover
            shutil.rmtree(dest, ignore_errors=True)
        # The clone is the only slow thing composition does, and it happens before
        # any checking has begun — so a first run against an unfetched source used
        # to sit silent for the whole of it (SR-0031). Announced before, not after.
        _announce(f"resolving source '{source.namespace}' from "
                  f"{source.url}@{source.ref} (not cached — fetching)")
        _fetch(source.url, source.ref, dest)
        _announce(f"resolved source '{source.namespace}'")
    # Resolved once at this pinned ref — idempotent, offline thereafter.
    project = _descend(dest, source)
    if not (project / "throughline.toml").is_file():
        loc = f"{source.url}@{source.ref}"
        if source.subdir:
            loc += f" (subdir '{source.subdir}')"
        raise ResolveError(
            f"source '{source.namespace}' at {loc} is not a throughline project "
            "(no throughline.toml)")
    return project
