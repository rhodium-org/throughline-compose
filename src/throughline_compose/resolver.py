# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""A target resolver backed by a consumer's declared sources (SR-0110 seam).

``tl-compose docs`` injects over the *local* consumer project, exactly as ``tl
docs`` does, so counts, tables and matrix rows stay byte-identical. The one seam
is the target *cell* of a tl:matrix: a consumer clause that links to a borrowed
standard by a namespace-qualified target (``asvs:SR-0227``) can then render that
target's own reference number instead of a UID the reader cannot look up.

Core injection resolves target liveness and attributes through an optional
:class:`throughline.inject.TargetResolver` (SR-0110). This resolver overrides it
so a namespace-qualified target resolves against the loaded source for that
namespace; an unqualified target falls through to the consumer project, so
behaviour over local links is identical to the core default.
"""
from __future__ import annotations

import re

from throughline import is_namespace_qualified
from throughline.inject import TargetResolver, render_item

_NS_SPLIT = re.compile(r"^([a-z][a-z0-9_-]*):(.+)$")


class UnionResolver(TargetResolver):
    """Resolve tl:matrix target cells over a consumer plus its sources."""

    def __init__(self, consumer, sources: dict) -> None:
        super().__init__(consumer)
        self._sources = sources  # namespace -> loaded source Project

    def _delegate(self, uid: str) -> "TargetResolver | None":
        """A resolver over the source project owning ``uid``, or ``None`` when
        ``uid`` is not a namespace-qualified reference to a declared source."""
        if not is_namespace_qualified(uid):
            return None
        m = _NS_SPLIT.match(uid)
        src = self._sources.get(m.group(1))
        return TargetResolver(src) if src is not None else None

    def present(self, uid: str) -> bool:
        d = self._delegate(uid)
        return d.present(_local(uid)) if d else super().present(uid)

    def attr(self, uid: str, name: str):
        d = self._delegate(uid)
        return d.attr(_local(uid), name) if d else super().attr(uid, name)

    def link_display(self, uid: str) -> str:
        """Enrich a borrowed clause's link display with its own reference number
        (SR-0113): ``asvs:SR-0172`` reads ``asvs:SR-0172 (V7.1.1)`` when the source
        clause carries a ``source_ref``. A local target is the bare UID as before."""
        if not is_namespace_qualified(uid):
            return super().link_display(uid)
        ref = self.attr(uid, "source_ref")
        return f"{uid} ({ref})" if ref else uid

    def mirror_block(self, uid: str) -> str | None:
        """The borrowed clause's own full block, stated under the identity the citing
        document uses for it (SR-0039). Returns ``None`` for a local target or one
        whose namespace names no declared source, so the caller can report which
        reference it could not mirror rather than dropping it.

        The block is produced by core's item renderer (SR-0004) over the *source*
        project, with a resolver that qualifies every UID it renders: the heading
        through the identity seam (throughline SR-0187) and the clause's outgoing
        links through the link seam (throughline SR-0113). Without that, a mirrored
        clause would be published under the source's own local UID and collide with
        an unrelated consumer item of the same number."""
        src = self._source_for(uid)
        if src is None:
            return None
        local = _local(uid)
        if src.get(local) is None:
            return None
        ns = _NS_SPLIT.match(uid).group(1)
        return render_item(src, local, _MirrorResolver(src, ns))

    def _source_for(self, uid: str):
        """The loaded source project owning a namespace-qualified ``uid``, or None."""
        if not is_namespace_qualified(uid):
            return None
        return self._sources.get(_NS_SPLIT.match(uid).group(1))


class _MirrorResolver(TargetResolver):
    """Renders one source's items under the consumer's namespace for that source.

    A source graph knows nothing of the namespace a consumer binds it to, so every
    UID it would render — the clause's own, and each of its outgoing link targets —
    is qualified here (SR-0039). Reference numbers take the same ``UID (ref)`` form
    the consumer's citations already use (SR-0007), so the heading a reader arrives
    at matches the citation that sent them there."""

    def __init__(self, source, namespace: str) -> None:
        super().__init__(source)
        self._ns = namespace

    def _qualified(self, uid: str) -> str:
        """``uid`` under this source's namespace, with its reference number where the
        clause carries one. A target already qualified is a reference the source makes
        into a further namespace of its own and is left exactly as the source wrote
        it — re-qualifying it would claim it for the wrong graph."""
        if is_namespace_qualified(uid):
            return uid
        ref = self.attr(uid, "source_ref")
        return f"{self._ns}:{uid} ({ref})" if ref else f"{self._ns}:{uid}"

    def display(self, uid: str) -> str:
        return self._qualified(uid)

    def link_display(self, uid: str) -> str:
        return self._qualified(uid)


def _local(uid: str) -> str:
    """The source-local UID of a namespace-qualified reference (``asvs:SR-0227``
    → ``SR-0227``)."""
    return _NS_SPLIT.match(uid).group(2)
