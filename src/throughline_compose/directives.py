# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The document directives throughline-compose provides (SR-0039).

Core recognises a marked region by its general form and resolves the kind through
a single registry, letting a front end register a directive of its own
(throughline SR-0186). ``tl:sourced`` is registered here rather than in core
because it needs the composed sources, which only this layer holds: a capability
depending on state core does not hold is provided by the layer that holds it,
never stubbed inside core (throughline NG-0007).

Importing this module registers the directive, so ``tl-compose docs`` renders it
and a bare ``tl docs`` over the same document reports it as unprovided instead of
silently replacing already-rendered clauses with a placeholder.
"""
from __future__ import annotations

from throughline import is_namespace_qualified
from throughline.inject import InjectError, matching, register_directive

_PLACEHOLDER = "_(the items this filter selects reference no external clause)_"


def render_sourced(project, expr: str, resolver) -> str:
    """A full-clause mirror (SR-0039): the distinct external clauses that the items
    matching ``expr`` reference by a namespace-qualified link target, each rendered
    in full, in target order, separated by a blank line.

    Each clause is stated under the identity the citing document uses for it — the
    namespace-qualified target and, where the clause carries one, its reference
    number — never under the source graph's own local UID. Where the matching items
    reference no external clause there is nothing to mirror and a placeholder is
    rendered; where a referenced clause cannot be rendered from its declared source,
    injection fails rather than quietly dropping it. A malformed filter fails
    injection (via ``matching``)."""
    targets = _external_targets(project, expr)
    if not targets:
        return _PLACEHOLDER

    mirror = getattr(resolver, "mirror_block", None)
    if mirror is None:
        # The document cites external clauses but the resolver holds no sources —
        # the composed union never reached injection. Saying so beats mirroring
        # nothing and leaving the reader a document that looks complete.
        raise InjectError(
            f"tl:sourced cannot mirror {', '.join(targets)} — no composed sources "
            "were available to this run")

    blocks = []
    for t in targets:
        b = mirror(t)
        if b is None:
            raise InjectError(
                f"tl:sourced cannot mirror '{t}' — its namespace names no declared "
                "source, or that source holds no such clause. Declare the namespace "
                "in [[sources]], or correct the reference.")
        blocks.append(b)
    return "\n\n".join(blocks)


def _external_targets(project, expr: str) -> list[str]:
    """The distinct namespace-qualified link targets of the items matching ``expr``,
    in target order — what the selected items borrow, deduplicated."""
    seen: set[str] = set()
    for it in matching(project, expr):
        for link in it.links:
            if is_namespace_qualified(link.target):
                seen.add(link.target)
    return sorted(seen)


def register() -> None:
    """Register every directive this layer provides. Idempotent: re-registering a
    name replaces the entry with an identical one."""
    # A mirrored clause belongs to its source, so the directive does not publish the
    # *local* items its filter selects for the coverage rule (throughline SR-0096) —
    # those items are selected only to discover what they borrow. Declaring that on
    # the registry entry is the only place it is said (throughline SR-0186).
    register_directive(
        "sourced", render_sourced, publishes=False,
        selects=lambda project, arg: [it.uid for it in matching(project, arg)])


register()
