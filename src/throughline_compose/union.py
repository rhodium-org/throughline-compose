# Copyright (c) 2026 Time Back Solutions Limited
# SPDX-License-Identifier: Apache-2.0
"""Build one throughline graph from a consumer plus its declared sources (SR-0004).

The core throughline validator is reused *unchanged* (SR-0004): rather than teach
`tl` about namespaces, `tl-compose` folds every source's items into a single union
:class:`~throughline.model.Project` and runs the ordinary `validate` over it. The
one trick is identity. A source's UIDs are its own (SR-0002), so two sources — or a
source and the consumer — may both hold ``SR-0001``. Before merging, each borrowed
UID is *mangled* to a synthetic prefix derived from its namespace (``gds:SR-0001``
→ ``GDSSR-0001``), so the union has globally-unique, grammar-valid UIDs. Every
namespace-qualified reference (SR-0001) and every source-internal reference is
rewritten to the mangled form, so the graph resolves with no colons left.

Findings from the core are then translated back: mangled UIDs in a finding's target
and message become their original ``<namespace>:<UID>`` form, so the composer reads
diagnostics in the vocabulary they wrote.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from throughline.model import Item, Project, Register
from throughline.uid import UID_RE, parse_uid

# The prefix a mangled UID may occupy: core UID grammar (throughline SR-0001).
_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}$")
# Split a namespace-qualified reference into (namespace, uid).
_NS_REF_RE = re.compile(r"^([a-z][a-z0-9_-]*):(.+)$")
# A namespace-qualified reference (throughline SR-0107): a namespace name, a colon,
# and an otherwise-valid UID (``gds:SR-0001``). Kept in step with core's own grammar.
_NAMESPACE_REF_RE = re.compile(r"^[a-z][a-z0-9_-]*:[A-Z][A-Z0-9]{1,15}-[0-9]+$")


def _is_external(target: str) -> bool:
    """A free-form external pointer — a URL, path, or anchor — that the core leaves
    opaque (throughline SR-0031). Classified here from throughline's *public* link
    grammar rather than its private internals, honouring the library contract (SR-0004)."""
    return "://" in target or "/" in target or "#" in target


def _is_namespace_qualified(target: str) -> bool:
    """A ``<namespace>:<UID>`` reference the core cannot resolve — composition's own
    syntax (throughline SR-0107). ``_is_external`` runs first, so a URL scheme like
    ``https:`` (tail starts ``//``) never reaches here."""
    return bool(_NAMESPACE_REF_RE.match(target))


class ComposeError(Exception):
    """Composition cannot proceed — an unbound namespace, a UID that will not
    mangle to a legal prefix, or a synthetic-prefix clash. Fail fast (SR-0005)."""


@dataclass
class Union:
    project: Project                    # merged graph, governed by consumer schema
    owners: dict[str, tuple[str, str]]  # synthetic prefix -> (namespace, source prefix)

    def qualified(self, uid: str) -> str:
        """Reconstruct the original ``<namespace>:<UID>`` for any union UID whose
        prefix is a mangled one — including a reference to a source clause that
        does *not* exist, so a dangling cross-source link reads in the composer's
        own vocabulary. A consumer-local UID is returned unchanged."""
        m = UID_RE.match(uid)
        if m and m.group(1) in self.owners:
            namespace, src_prefix = self.owners[m.group(1)]
            return f"{namespace}:{src_prefix}-{m.group(2)}"
        return uid

    def pattern(self) -> re.Pattern | None:
        """A regex matching any mangled UID token, for message translation."""
        if not self.owners:
            return None
        prefixes = "|".join(re.escape(p) for p in
                            sorted(self.owners, key=len, reverse=True))
        return re.compile(rf"(?:{prefixes})-[0-9]+")


def _sanitize_ns(namespace: str) -> str:
    """The uppercase, alphanumeric-only stem a namespace contributes to a mangled
    prefix. A namespace starts with a lowercase letter (sources.py), so the stem
    always starts with a letter and is a legal prefix head."""
    return re.sub(r"[^A-Z0-9]", "", namespace.upper())


class _Mangler:
    """Deterministic, collision-checked mapping from ``(namespace, source UID)`` to
    a unique, grammar-valid union UID. Only the prefix changes; the number is
    preserved verbatim so the width and value survive."""

    def __init__(self) -> None:
        # synthetic prefix -> (namespace, source prefix) that owns it, to catch two
        # distinct (namespace, prefix) pairs colliding on one synthetic prefix.
        self.owners: dict[str, tuple[str, str]] = {}

    def prefix(self, namespace: str, src_prefix: str) -> str:
        syn = _sanitize_ns(namespace) + src_prefix
        if not _PREFIX_RE.match(syn):
            raise ComposeError(
                f"namespace '{namespace}' + prefix '{src_prefix}' mangles to "
                f"'{syn}', which is not a legal UID prefix (max 16 chars) — "
                "import the source under a shorter namespace")
        owner = self.owners.setdefault(syn, (namespace, src_prefix))
        if owner != (namespace, src_prefix):
            raise ComposeError(
                f"namespaces '{owner[0]}' and '{namespace}' both mangle prefix "
                f"'{src_prefix}' to '{syn}' — import one under a distinct namespace")
        return syn

    def uid(self, namespace: str, uid: str) -> str:
        m = UID_RE.match(uid)
        if not m:
            return uid  # malformed target — leave for the core to flag as dangling
        pfx, num = m.group(1), m.group(2)
        return f"{self.prefix(namespace, pfx)}-{num}"


def _rewrite_target(target: str, current_ns: str | None,
                    namespaces: set[str], mangler: _Mangler) -> str:
    """Map one link target into union space.

    - External pointers (URLs, paths, anchors — SR-0031) stay opaque.
    - A namespace-qualified ``ns:UID`` resolves to that namespace's mangled UID;
      an undeclared namespace is a fail-fast :class:`ComposeError`.
    - A bare UID inside a *source* item is a source-internal reference and mangles
      into that source's namespace; inside the *consumer* it is a local UID and is
      left untouched.
    """
    if _is_external(target):
        return target
    if _is_namespace_qualified(target):
        m = _NS_REF_RE.match(target)
        ns, uid = m.group(1), m.group(2)
        if ns not in namespaces:
            raise ComposeError(
                f"reference '{target}' names namespace '{ns}', which is not a "
                "declared [[sources]] namespace")
        return mangler.uid(ns, uid)
    if current_ns is not None:
        return mangler.uid(current_ns, target)
    return target


def _rewrite_links(item: Item, current_ns: str | None,
                   namespaces: set[str], mangler: _Mangler) -> Item:
    new_links = [replace(link, target=_rewrite_target(
        link.target, current_ns, namespaces, mangler)) for link in item.links]
    return replace(item, links=new_links)


def build_union(consumer: Project, sources: dict[str, Project]) -> Union:
    """Fold ``sources`` (namespace -> loaded source project) into ``consumer`` and
    return the merged :class:`Union`. The union is governed by the *consumer's*
    schema — the consumer decides which types, links and statuses are legal for
    the composed graph."""
    namespaces = set(sources)
    mangler = _Mangler()

    union = Project(path=consumer.path, config=consumer.config)

    # Consumer items keep their own UIDs; only their ns-qualified references are
    # rewritten. Copy registers so the loaded consumer objects stay untouched.
    for prefix, reg in consumer.registers.items():
        items = {uid: _rewrite_links(it, None, namespaces, mangler)
                 for uid, it in reg.items.items()}
        union.registers[prefix] = replace(reg, items=items)

    # Each source's items are mangled into namespace-derived prefixes and merged.
    for namespace, source in sources.items():
        for reg in source.registers.values():
            for uid, it in reg.items.items():
                mangled_uid = mangler.uid(namespace, uid)
                mangled_prefix = parse_uid(mangled_uid)[0]
                rewritten = _rewrite_links(it, namespace, namespaces, mangler)
                merged = replace(rewritten, uid=mangled_uid,
                                 _register_prefix=mangled_prefix)
                target = union.registers.get(mangled_prefix)
                if target is None:
                    if mangled_prefix in consumer.registers:
                        raise ComposeError(
                            f"source '{namespace}' mangles to prefix "
                            f"'{mangled_prefix}', which the consumer already uses — "
                            "import the source under a distinct namespace")
                    target = Register(prefix=mangled_prefix,
                                      title=f"{namespace}:{reg.prefix}")
                    union.registers[mangled_prefix] = target
                target.items[mangled_uid] = merged

    return Union(project=union, owners=mangler.owners)


def translate_finding(finding, union: Union, pattern: re.Pattern | None):
    """Rewrite a core :class:`~throughline.validate.Finding` back into namespace
    vocabulary: its ``uid`` and any mangled UID token in its ``message`` become the
    original ``<namespace>:<UID>``. Returns a shallow copy; the original is
    untouched."""
    message = finding.message
    if pattern is not None:
        message = pattern.sub(lambda m: union.qualified(m.group(0)), message)
    return replace(finding, uid=union.qualified(finding.uid), message=message)
