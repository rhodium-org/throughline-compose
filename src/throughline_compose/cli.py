# Copyright (c) 2026 Time Back Solutions Limited
# SPDX-License-Identifier: Apache-2.0
"""The ``tl-compose`` entry point.

Design intent (SR-0003): ``tl-compose`` is a strict superset of ``tl``. Every
local-graph command is forwarded to throughline's CLI unchanged; the union-aware
command ``check`` is layered on top. When a project declares no ``[[sources]]``,
``check`` too is a pure pass-through, so ``tl-compose`` over an ordinary project
behaves exactly like ``tl``.

`check` composes the consumer with its declared sources into one union graph
(union.py), runs the *unchanged* core validator over it (SR-0004), and translates
findings back into ``<namespace>:<UID>`` vocabulary before printing.
"""
from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from throughline.cli import build_parser, cmd_check, cmd_docs
from throughline.storage import ProjectError, load_project
from throughline.validate import ERROR, validate

from .resolve import ResolveError, resolve_source
from .resolver import UnionResolver
from .sources import SourceError, parse_sources
from .union import ComposeError, build_union, translate_finding

OK, FINDINGS, USAGE = 0, 1, 2


def _err(msg: str) -> int:
    print(f"tl-compose: {msg}", file=sys.stderr)
    return USAGE


def _pkg(name: str) -> str:
    try:
        return _pkg_version(name)
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        return "0.0.0+unknown"


def _version_string() -> str:
    # tl-compose is its own front door; report its version and the throughline core
    # it composes over, not throughline's (build_parser wires `--version` to `tl`).
    return f"tl-compose {_pkg('throughline-compose')} (throughline {_pkg('throughline')})"


def _load_sources(sources, root) -> dict:
    """Resolve and load each declared source into a namespace -> Project map.
    Raises :class:`ResolveError` / :class:`ProjectError` for the caller to
    report; a source that will not load is named in the composer's vocabulary."""
    loaded = {}
    for s in sources:
        src_dir = resolve_source(s, root)
        try:
            loaded[s.namespace] = load_project(src_dir)
        except ProjectError as e:
            where = f"{s.url}@{s.ref}" if s.is_remote else s.path
            raise ProjectError(f"source '{s.namespace}' at {where}: {e}") from e
    return loaded


def _compose_check(args) -> int:
    from pathlib import Path

    try:
        consumer = load_project(args.path)
    except ProjectError as e:
        return _err(str(e))
    try:
        sources = parse_sources(consumer)
    except SourceError as e:
        return _err(str(e))

    # No sources declared: this is a plain throughline project. Defer to the core
    # check verbatim so the superset holds exactly (SR-0003).
    if not sources:
        return cmd_check(args)

    try:
        loaded = _load_sources(sources, Path(args.path))
    except (ResolveError, ProjectError) as e:
        return _err(str(e))

    try:
        union = build_union(consumer, loaded)
    except ComposeError as e:
        return _err(str(e))

    findings = validate(union.project, strict=args.strict)
    pattern = union.pattern()
    findings = [translate_finding(f, union, pattern) for f in findings]

    if getattr(args, "format", "text") == "json":
        import json
        print(json.dumps([f.to_dict() for f in findings], indent=2))
        return FINDINGS if any(f.severity == ERROR for f in findings) else OK

    for f in sorted(findings, key=lambda x: (x.severity != ERROR, x.uid)):
        print(f)
    sys.stdout.flush()
    errs = sum(1 for f in findings if f.severity == ERROR)
    warns = len(findings) - errs
    if not getattr(args, "quiet", False):
        names = ", ".join(
            f"{s.namespace} ({s.url}@{s.ref})" if s.is_remote
            else f"{s.namespace} ({s.path})"
            for s in sources)
        print(f"\ntl-compose check · {len(sources)} source(s) composed: {names}",
              file=sys.stderr)
    tally = f"\n{errs} error(s), {warns} warning(s)"
    if not getattr(args, "quiet", False) and errs == 0:
        tally += "  — composed graph is sound" + (" (strict)" if args.strict else "")
    print(tally, file=sys.stderr)
    return FINDINGS if any(f.severity == ERROR for f in findings) else OK


def _compose_docs(args) -> int:
    """Inject the consumer's documents, resolving tl:matrix target cells over the
    union of the consumer and its declared sources (SR-0110). Injection is over
    the *local* consumer project — counts, tables and rows are byte-identical to
    ``tl docs`` — but a namespace-qualified matrix target can render the borrowed
    clause's own reference number. With no sources declared this is a pure
    pass-through to core ``tl docs`` (SR-0003)."""
    from pathlib import Path

    try:
        consumer = load_project(args.path)
    except ProjectError as e:
        return _err(str(e))
    try:
        sources = parse_sources(consumer)
    except SourceError as e:
        return _err(str(e))

    if not sources:
        return cmd_docs(args)

    try:
        loaded = _load_sources(sources, Path(args.path))
    except (ResolveError, ProjectError) as e:
        return _err(str(e))

    return cmd_docs(args, resolver=UnionResolver(consumer, loaded))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.prog = "tl-compose"
    for action in parser._actions:
        if "--version" in action.option_strings:
            action.version = _version_string()
    args = parser.parse_args(argv)
    if getattr(args, "cmd", None) == "check":
        try:
            return _compose_check(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
    if getattr(args, "cmd", None) == "docs":
        try:
            return _compose_docs(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        return USAGE


if __name__ == "__main__":
    raise SystemExit(main())
