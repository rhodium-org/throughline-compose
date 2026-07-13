# Copyright (c) 2026 Time Back Solutions Limited
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
import tempfile
from pathlib import Path

from .sources import Source

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


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


def resolve_source(source: Source, consumer_root: Path) -> Path:
    """Return the local directory a source composes from.

    ``path`` sources resolve relative to ``consumer_root``; ``url`` sources are
    fetched (once) into the per-user cache.
    """
    if not source.is_remote:
        assert source.path is not None
        local = (consumer_root / source.path).resolve()
        if not local.is_dir():
            raise ResolveError(
                f"source '{source.namespace}' path does not exist: {local}")
        return local

    assert source.url is not None and source.ref is not None
    dest = _cache_dir(source.url, source.ref)
    if dest.is_dir() and (dest / "throughline.toml").is_file():
        return dest  # already resolved at this pinned ref — idempotent, offline
    if dest.exists():  # partial/corrupt leftover
        shutil.rmtree(dest, ignore_errors=True)
    _fetch(source.url, source.ref, dest)
    if not (dest / "throughline.toml").is_file():
        raise ResolveError(
            f"source '{source.namespace}' at {source.url}@{source.ref} is not a "
            "throughline project (no throughline.toml)")
    return dest
