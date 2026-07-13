# Copyright (c) 2026 Time Back Solutions Limited
# SPDX-License-Identifier: Apache-2.0
"""Declared external sources (SR-0001, SR-0002).

A consuming project names the throughline sources it composes in an array of
``[[sources]]`` tables in its ``throughline.toml``. Each entry binds an
importer-chosen *namespace* (SR-0001) to a local *path* — the root of a standalone
throughline project whose UIDs are its own (SR-0002). Clauses are then referenced
from the consumer as ``<namespace>:<UID>``.

This module is pure config parsing — it does not load or resolve anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The namespace grammar mirrors the core's namespace-qualified reference token
# (throughline SR-0107): a lowercase name a reference can carry before the colon.
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class SourceError(ValueError):
    """A malformed or ambiguous ``[[sources]]`` declaration — fail fast (SR-0005)."""


@dataclass(frozen=True)
class Source:
    namespace: str
    path: str


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
    seen: dict[str, str] = {}
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise SourceError(f"[[sources]] entry {i} is not a table")
        ns = entry.get("namespace")
        path = entry.get("path")
        if not ns or not isinstance(ns, str):
            raise SourceError(f"[[sources]] entry {i} is missing a 'namespace'")
        if not _NAMESPACE_RE.match(ns):
            raise SourceError(
                f"namespace '{ns}' is not a valid namespace name "
                "(lowercase letter, then letters/digits/-/_)")
        if not path or not isinstance(path, str):
            raise SourceError(f"source '{ns}' is missing a 'path'")
        if ns in seen:
            raise SourceError(
                f"namespace '{ns}' is declared twice — a namespace binds one source")
        seen[ns] = path
        out.append(Source(namespace=ns, path=path))
    return out
