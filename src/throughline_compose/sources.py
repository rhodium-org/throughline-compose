# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""Declared external sources (SR-0001, SR-0002, SR-0006).

A consuming project names the throughline sources it composes in an array of
``[[sources]]`` tables in its ``throughline.toml``. Each entry binds an
importer-chosen *namespace* (SR-0001) to a standalone throughline source whose UIDs
are its own (SR-0002). Clauses are then referenced from the consumer as
``<namespace>:<UID>``.

A source is located one of two ways (SR-0006):

- ``url`` + ``ref`` — a git origin pinned to an edition (normally a tag). The
  durable, shareable form; resolved into a per-user cache by ``resolve.py``.
- ``path`` — a local directory, for developing a source and its consumer side by
  side.

The two are mutually exclusive; a ``url`` without a ``ref`` is rejected so a
dependency can never silently track a moving default. Either form may carry an
optional ``subdir`` (SR-0008) naming a directory, relative to the fetched
repository root (or the local ``path``), that holds the throughline project — so a
graph living under a subpath of a larger repo is a first-class source. This module
is pure config parsing — it does not fetch or load anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# The namespace grammar mirrors the core's namespace-qualified reference token
# (throughline SR-0107): a lowercase name a reference can carry before the colon.
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class SourceError(ValueError):
    """A malformed or ambiguous ``[[sources]]`` declaration — fail fast (SR-0005)."""


@dataclass(frozen=True)
class Source:
    namespace: str
    path: str | None = None
    url: str | None = None
    ref: str | None = None
    subdir: str | None = None
    # SR-0014: transitive namespaces this source re-exports into the consuming
    # union, mapping the source's *own* namespace to the union namespace the
    # consumer binds it to (an alias, or the same name for an identity re-export).
    # Empty for a source that re-exports nothing.
    reexport: dict[str, str] = field(default_factory=dict)

    @property
    def is_remote(self) -> bool:
        return self.url is not None


def _parse_subdir(ns: str, subdir) -> str | None:
    """Validate an optional ``subdir`` (SR-0008): a relative path within the tree.

    An absolute path, or one that escapes the fetched root with a parent segment,
    fails fast — a source may only compose from inside its own tree.
    """
    if subdir is None:
        return None
    if not isinstance(subdir, str) or not subdir.strip():
        raise SourceError(f"source '{ns}' has a non-string or empty 'subdir'")
    subdir = subdir.strip()
    parts = PurePosixPath(subdir).parts
    if PurePosixPath(subdir).is_absolute() or subdir.startswith(("/", "\\")):
        raise SourceError(
            f"source '{ns}' has an absolute 'subdir' — it must be relative to the "
            "source root (SR-0008)")
    if ".." in parts:
        raise SourceError(
            f"source '{ns}' has a 'subdir' that escapes the source root with '..' "
            "(SR-0008)")
    return subdir


def _parse_reexport(ns: str, raw) -> dict[str, str]:
    """Validate an optional ``reexport`` (SR-0014): the transitive namespaces this
    source pulls forward into the consuming union.

    Two forms are accepted. An array — ``reexport = ["asvs"]`` — pulls each named
    namespace forward under its own name (an identity re-export). A table —
    ``reexport = { asvs = "owasp" }`` — binds each transitive namespace to a
    consumer-chosen alias (UR-0001's label-ownership, now across depth). Both keys
    and aliases must be valid namespace names; a namespace re-exported twice fails
    fast. Whether the source actually *declares* the named namespace is checked at
    resolve time, once the source's own configuration has been read.
    """
    if raw is None:
        return {}
    if isinstance(raw, list):
        pairs = [(x, x) for x in raw]
    elif isinstance(raw, dict):
        pairs = list(raw.items())
    else:
        raise SourceError(
            f"source '{ns}' has a 'reexport' that is neither an array of namespaces "
            "nor a table of namespace = alias (SR-0014)")
    mapping: dict[str, str] = {}
    for internal, alias in pairs:
        if not isinstance(internal, str) or not _NAMESPACE_RE.match(internal):
            raise SourceError(
                f"source '{ns}' re-exports an invalid namespace '{internal}' "
                "(lowercase letter, then letters/digits/-/_)")
        if not isinstance(alias, str) or not _NAMESPACE_RE.match(alias):
            raise SourceError(
                f"source '{ns}' re-exports '{internal}' under an invalid alias "
                f"'{alias}'")
        if internal in mapping:
            raise SourceError(
                f"source '{ns}' re-exports '{internal}' more than once")
        mapping[internal] = alias
    return mapping


def parse_sources(project) -> list[Source]:
    """Read the ``[[sources]]`` array from a loaded consumer project's config.

    Returns an empty list when none are declared — a project with no sources is
    an ordinary throughline project and ``tl-compose`` behaves exactly like ``tl``
    over it (SR-0003).
    """
    raw = project.config.get("sources", [])
    if not isinstance(raw, list):
        raise SourceError("[[sources]] must be an array of tables")
    out: list[Source] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise SourceError(f"[[sources]] entry {i} is not a table")

        ns = entry.get("namespace")
        if not ns or not isinstance(ns, str):
            raise SourceError(f"[[sources]] entry {i} is missing a 'namespace'")
        if not _NAMESPACE_RE.match(ns):
            raise SourceError(
                f"namespace '{ns}' is not a valid namespace name "
                "(lowercase letter, then letters/digits/-/_)")
        if ns in seen:
            raise SourceError(
                f"namespace '{ns}' is declared twice — a namespace binds one source")

        path = entry.get("path")
        url = entry.get("url")
        ref = entry.get("ref")
        subdir = _parse_subdir(ns, entry.get("subdir"))
        reexport = _parse_reexport(ns, entry.get("reexport"))

        has_path = bool(path)
        has_url = bool(url)
        if has_path and has_url:
            raise SourceError(
                f"source '{ns}' declares both 'path' and 'url' — they are mutually "
                "exclusive (SR-0006)")
        if not has_path and not has_url:
            raise SourceError(
                f"source '{ns}' must declare either a 'path' or a 'url'")

        if has_path:
            if not isinstance(path, str):
                raise SourceError(f"source '{ns}' has a non-string 'path'")
            if ref:
                raise SourceError(
                    f"source '{ns}' declares a 'ref' with a local 'path' — a ref "
                    "only pins a 'url' (SR-0006)")
            src = Source(namespace=ns, path=path, subdir=subdir, reexport=reexport)
        else:
            if not isinstance(url, str):
                raise SourceError(f"source '{ns}' has a non-string 'url'")
            if not ref or not isinstance(ref, str):
                raise SourceError(
                    f"source '{ns}' has a 'url' but no 'ref' — pin the edition with "
                    "a git tag, branch, or commit (SR-0006)")
            src = Source(namespace=ns, url=url, ref=ref, subdir=subdir,
                         reexport=reexport)

        seen.add(ns)
        out.append(src)
    return out
