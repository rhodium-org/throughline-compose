# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The git reference resolver — the reference implementation of the source-resolver
interface (SR-0011).

Every source `tl-compose` composes today is reached this way: a local ``path`` (a
source developed beside its consumer) or a ``url`` + ``ref`` git origin pinned to
an edition and fetched into a per-user cache (SR-0006). This module is a thin
adapter — it delegates the fetch/cache mechanics to :mod:`throughline_compose.resolve`
and the graph loading to the throughline core, then wraps the result in a
:class:`~throughline_compose.spi.ResolvedSource` with a content fingerprint of the
edition read. It exists so that the *existing* git resolution is one implementation
behind the interface, and no other code path fetches a source (SR-0011). The pin
guarantees SR-0012 names — an explicit, immutable ``ref`` (a ``url`` without one is
rejected at parse time) and reproducible, offline-after-first-fetch resolution —
are already met by the git origin, so a non-git resolver has a concrete bar to
meet.
"""
from __future__ import annotations

from pathlib import Path

from throughline.storage import ProjectError, read_project

from .resolve import ResolveError, resolve_source
from .sources import Source
from .spi import ResolvedSource, Resolver, ResolverError, content_fingerprint, register


class GitResolver(Resolver):
    """Resolve ``path`` and ``url`` (git) sources — the reference resolver."""

    def handles(self, source: Source) -> bool:
        # Every declared source is a path or a url today; a future authority
        # resolver claims its own sources ahead of this catch-all.
        return source.path is not None or source.url is not None

    def resolve(self, source: Source, consumer_root: Path) -> ResolvedSource:
        try:
            src_dir = resolve_source(source, consumer_root)
        except ResolveError as e:
            raise ResolverError(str(e)) from e
        try:
            # A source is read-only: load it through the tolerant multi-major reader
            # (SR-0017), so a source pinned at an older on-disk major composes without
            # being forced to migrate first (UR-0006). The strict single-major gate
            # applies only to the consumer project being operated on, never here.
            project = read_project(src_dir)
        except ProjectError as e:
            where = f"{source.url}@{source.ref}" if source.is_remote else source.path
            raise ResolverError(
                f"source '{source.namespace}' at {where}: {e}") from e
        return ResolvedSource(
            project=project, fingerprint=content_fingerprint(project))


# The reference resolver is the catch-all: registered last so a connector's
# authority-specific resolver is consulted first (spi.register default).
register(GitResolver(), first=False)
