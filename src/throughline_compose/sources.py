# Copyright (c) 2026 Time Back Solutions Limited
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
dependency can never silently track a moving default. This module is pure config
parsing — it does not fetch or load anything.
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
    path: str | None = None
    url: str | None = None
    ref: str | None = None

    @property
    def is_remote(self) -> bool:
        return self.url is not None


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
            src = Source(namespace=ns, path=path)
        else:
            if not isinstance(url, str):
                raise SourceError(f"source '{ns}' has a non-string 'url'")
            if not ref or not isinstance(ref, str):
                raise SourceError(
                    f"source '{ns}' has a 'url' but no 'ref' — pin the edition with "
                    "a git tag, branch, or commit (SR-0006)")
            src = Source(namespace=ns, url=url, ref=ref)

        seen.add(ns)
        out.append(src)
    return out
