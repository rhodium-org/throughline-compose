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

from throughline.cli import build_parser, cmd_check
from throughline.storage import ProjectError, load_project
from throughline.validate import ERROR, validate

from .resolve import ResolveError, resolve_source
from .sources import SourceError, parse_sources
from .union import ComposeError, build_union, translate_finding

OK, FINDINGS, USAGE = 0, 1, 2


def _err(msg: str) -> int:
    print(f"tl-compose: {msg}", file=sys.stderr)
    return USAGE


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

    root = Path(args.path)
    loaded = {}
    for s in sources:
        try:
            src_dir = resolve_source(s, root)
        except ResolveError as e:
            return _err(str(e))
        try:
            loaded[s.namespace] = load_project(src_dir)
        except ProjectError as e:
            where = f"{s.url}@{s.ref}" if s.is_remote else s.path
            return _err(f"source '{s.namespace}' at {where}: {e}")

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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "cmd", None) == "check":
        try:
            return _compose_check(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        return USAGE


if __name__ == "__main__":
    raise SystemExit(main())
