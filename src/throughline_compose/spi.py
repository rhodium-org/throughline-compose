# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The source-resolver interface — the single seam every authority is reached
through (SR-0011).

`tl-compose` composes a consumer's graph with items borrowed from other sources.
*How* a source's items are obtained — a git repository fetched at a tag, or, in
future, an issue tracker or wiki read over its API — is deliberately hidden behind
one small contract so that composition, union-building, validation and drift
detection never depend on a source's origin:

    given a source's coordinates and a pin (the edition to read),
    return that source's items projected as a throughline graph,
    together with a fingerprint of what was read.

The git-plus-ref resolution is the *reference implementation* of this contract
(see :mod:`throughline_compose.git_resolver`); it is registered by default so that
an ordinary ``path``/``url`` source resolves with no extra wiring. A non-git
authority ships its own :class:`Resolver` subclass in a connector package and
registers it — adding an authority is a matter of providing a resolver, not of
changing the composition engine (UR-0004). Resolvers only ever *read* their
sources; writing back to an authority is a connector concern, not composition
(NG-0002).
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from throughline.fingerprint import fingerprint
from throughline.model import Project

from .sources import Source


class ResolverError(Exception):
    """A source could not be resolved by any registered resolver — an authority
    with no resolver, a missing pin, or an authority-specific fetch failure. Fail
    fast (SR-0005)."""


@dataclass(frozen=True)
class ResolvedSource:
    """What a resolver returns for one source (SR-0011): the source's items
    projected as a throughline :class:`~throughline.model.Project`, plus a
    ``fingerprint`` of the exact edition that was read. The fingerprint is a stable
    digest of the resolved graph's normative content, so the same coordinates at
    the same pin resolve to the same fingerprint run to run and machine to machine
    (SR-0012), whatever authority produced the graph."""

    project: Project
    fingerprint: str


class Resolver(ABC):
    """The one interface `tl-compose` fetches a source through (SR-0011).

    A concrete resolver claims the sources it understands with :meth:`handles` and
    turns a claimed source into a :class:`ResolvedSource` with :meth:`resolve`. The
    reference implementation covers ``path`` and ``url`` (git) sources; a connector
    package subclasses this to reach a non-git authority and calls :func:`register`
    at import time. No other code path in `tl-compose` fetches a source."""

    @abstractmethod
    def handles(self, source: Source) -> bool:
        """True when this resolver knows how to reach ``source``."""

    @abstractmethod
    def resolve(self, source: Source, consumer_root: Path) -> ResolvedSource:
        """Fetch ``source`` at its pinned edition and return it as a
        :class:`ResolvedSource`. ``consumer_root`` locates a ``path`` source
        relative to the consumer project. Raises :class:`ResolverError` on any
        failure to reach or read the source."""


# Registered resolvers, consulted in order. The reference git resolver registers
# itself last (as a catch-all for path/url sources); a more specific authority
# resolver registered by a connector is consulted first and claims its own sources.
_REGISTRY: list[Resolver] = []


def register(resolver: Resolver, *, first: bool = True) -> Resolver:
    """Add ``resolver`` to the registry and return it (usable as a decorator on a
    subclass instance). Connector resolvers register ``first=True`` (the default)
    so an authority-specific resolver is consulted before the git catch-all; the
    reference resolver registers with ``first=False``."""
    if first:
        _REGISTRY.insert(0, resolver)
    else:
        _REGISTRY.append(resolver)
    return resolver


def resolver_for(source: Source) -> Resolver:
    """The registered resolver that handles ``source``, or a :class:`ResolverError`
    naming the source when none does — so an unreachable authority fails fast and
    reads in the composer's own vocabulary."""
    for resolver in _REGISTRY:
        if resolver.handles(source):
            return resolver
    raise ResolverError(
        f"no resolver handles source '{source.namespace}' — its authority has no "
        "registered resolver")


def content_fingerprint(project: Project) -> str:
    """A stable digest of a resolved source's normative content (SR-0011/SR-0012).

    Built from the core per-item :func:`~throughline.fingerprint.fingerprint` of
    every item, ordered by UID so the digest is independent of scan order. Two
    resolutions of the same edition yield the same value, and any real change to a
    borrowed item's normative content moves it — an authority-agnostic edition
    marker that a git commit hash or an issue-tracker revision id can stand behind."""
    schema = project.schema
    per_item = sorted(
        f"{item.uid}\x1f{fingerprint(item, schema)}" for item in project.items())
    digest = hashlib.sha256("\x1e".join(per_item).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
