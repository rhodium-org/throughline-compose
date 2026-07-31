# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The ``tl-compose`` entry point.

Design intent (SR-0003): ``tl-compose`` is a strict superset of ``tl``. Every
local-graph command is forwarded to throughline's CLI unchanged; the union-aware
commands ``check``, ``docs`` and ``trace`` are layered on top. When a project
declares no ``[[sources]]``, those too are pure pass-throughs, so ``tl-compose``
over an ordinary project behaves exactly like ``tl``.

`check` composes the consumer with its declared sources into one union graph
(union.py), runs the *unchanged* core validator over it (SR-0004), and translates
findings back into ``<namespace>:<UID>`` vocabulary before printing.

`migrate` (SR-0004) hands the union to the unchanged core repair as its grounding
view, so a ratification record whose item is justified only through a composed
source is completed rather than declined. Core runs first and alone: a project
below the current major cannot be loaded, so no union exists until it is upgraded.

`trace` (SR-0010) walks that same union so a link into a borrowed clause resolves
into the source and reads in ``<namespace>:<UID>`` vocabulary, instead of the
dead-end ``(unresolved)`` bare ``tl`` prints for anything outside the local graph.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

import getpass

from throughline.cli import (
    _by_count,
    _check_summary,
    _resolve_uid,
    _resolve_value,
    build_parser,
    cmd_check,
    cmd_context,
    cmd_docs,
    cmd_link,
    cmd_migrate,
    cmd_new,
    cmd_ratify,
    cmd_trace,
    force_utf8_io,
    render_trace,
)
from throughline.fingerprint import fingerprint
from throughline.graph import Index
from throughline.grounding import reaches_root
from throughline.model import Item, Link
from throughline.storage import (
    ProjectError,
    load_project,
    migrate_project,
    write_item,
)
from throughline.uid import UidError, next_uid, parse_uid
from throughline.validate import ERROR, is_namespace_qualified, validate

from . import git_resolver  # noqa: F401 — registers the reference git resolver (SR-0011)
from .resolver import UnionResolver
from .sources import Source, SourceError, parse_sources
from .spi import ResolvedSource, ResolverError, resolver_for
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


def _source_location(s: Source) -> str:
    """A human-readable origin for a source, for summaries and conflict messages."""
    return f"{s.url}@{s.ref}" if s.is_remote else f"path {s.path}"


def _conflict_message(ns: str, where_a: str, fp_a: str,
                      where_b: str, fp_b: str) -> str:
    """The advisory a two-edition namespace collision fails with (SR-0015): the why
    (namespace, both editions, where each came from) and the fix (pin explicitly, or
    alias apart) — never a suggestion to merge, which the model cannot honour."""
    short = lambda fp: fp.removeprefix("sha256:")[:12]  # noqa: E731
    return (
        f"namespace '{ns}' is bound to two different editions and tl-compose will "
        f"neither merge them nor pick one for you:\n"
        f"  - {where_a} [{short(fp_a)}]\n"
        f"  - {where_b} [{short(fp_b)}]\n"
        f"fix it by either: pinning '{ns}' explicitly in your own [[sources]] to the "
        f"single edition you intend, so one binding governs every reference to it; "
        f"or aliasing the two to distinct namespaces (for example "
        f"reexport = {{ {ns} = \"{ns}-alt\" }}) so both editions compose side by side "
        f"as the two separate sources they are"
    )


class _Resolution:
    """The outcome of resolving a consumer's sources plus any re-exports: the
    namespace -> :class:`ResolvedSource` map, the union namespace remaps each
    re-exporting source needs (SR-0014), and a human origin per bound namespace."""

    def __init__(self):
        self.resolved: dict[str, ResolvedSource] = {}
        self.ns_aliases: dict[str, dict[str, str]] = {}
        self.locations: dict[str, str] = {}

    def bind(self, ns: str, rs: ResolvedSource, where: str) -> None:
        """Bind ``ns`` to a resolved source, or fail fast when ``ns`` is already
        bound to a different edition (SR-0015). Binding the same edition twice — a
        namespace both declared and re-exported at one pin — resolves to the one
        source (SR-0014)."""
        existing = self.resolved.get(ns)
        if existing is not None:
            if existing.fingerprint != rs.fingerprint:
                raise ResolverError(_conflict_message(
                    ns, self.locations[ns], existing.fingerprint,
                    where, rs.fingerprint))
            return  # same edition — a single bound source
        self.resolved[ns] = rs
        self.locations[ns] = where

    def projects(self) -> dict:
        """The namespace -> Project view the union engine consumes (SR-0004)."""
        return {ns: rs.project for ns, rs in self.resolved.items()}


def _resolve_sources(sources, root) -> _Resolution:
    """Resolve each declared source, and each transitive source it re-exports,
    through the registered resolvers (SR-0011) into a :class:`_Resolution`. Every
    fetch goes through the one resolver interface; no other code path reaches a
    source. Re-export is one level and opt-in (SR-0014): a source's own sources are
    pulled forward only where the consumer named them. A namespace bound to two
    editions fails fast (SR-0015). Raises :class:`ResolverError` for the caller to
    report, so a source that will not resolve is named in the composer's vocabulary."""
    out = _Resolution()

    # 1. Directly declared sources.
    for s in sources:
        out.bind(s.namespace, resolver_for(s).resolve(s, root), _source_location(s))

    # 2. Re-exported transitive sources — resolved from the intermediate source's
    #    own declaration so the pin is inherited, never restated (SR-0014).
    for s in sources:
        if not s.reexport:
            continue
        intermediate = out.resolved[s.namespace].project
        declared = {d.namespace: d for d in parse_sources(intermediate)}
        src_root = Path(intermediate.path)
        for internal_ns, alias in s.reexport.items():
            dep = declared.get(internal_ns)
            if dep is None:
                raise ResolverError(
                    f"source '{s.namespace}' re-exports namespace '{internal_ns}', "
                    f"which '{s.namespace}' does not itself declare as a source")
            derived = replace(dep, namespace=alias, reexport={})
            where = f"{_source_location(dep)} (re-exported from '{s.namespace}')"
            out.bind(alias, resolver_for(derived).resolve(derived, src_root), where)
            if alias != internal_ns:
                out.ns_aliases.setdefault(s.namespace, {})[internal_ns] = alias

    return out


def _compose_check_summary(union) -> list[str]:
    """The graph summary ``check`` prints over the composed union (SR-0022).

    The first lines are byte-identical to what core ``tl check`` prints — items by
    type, status breakdown, link breakdown and grounding coverage — but computed
    over the union, so a composer gets the same picture of what was validated whether
    or not the project declares sources. A trailing ``Local`` line then splits the
    consumer's own items from the ones borrowed through a source (a union item is
    local exactly when its UID is not a mangled, source-owned one), reporting both
    the union totals and the local subset so the composer can read their own graph at
    a glance without the borrowed clauses drowning it."""
    lines = list(_check_summary(union.project))
    live = [it for it in union.project.items() if not it.is_deleted]
    local = [it for it in live if union.qualified(it.uid) == it.uid]
    borrowed = len(live) - len(local)
    breakdown = _by_count(it.type for it in local) if local else "none"
    lines.append(
        f"  Local      {len(local)} of {len(live)} local   {breakdown}"
        f"  ·  {borrowed} borrowed"
    )
    return lines


def _compose_check(args) -> int:
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
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))

    try:
        union = build_union(consumer, res.projects(), res.ns_aliases)
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
        for line in _compose_check_summary(union):
            print(line, file=sys.stderr)

        def _describe(ns: str) -> str:
            fp = res.resolved[ns].fingerprint.removeprefix("sha256:")[:12]
            return f"{ns} ({res.locations[ns]}) [{fp}]"
        names = ", ".join(_describe(ns) for ns in sorted(res.resolved))
        print(f"\ntl-compose check · {len(res.resolved)} source(s) composed: {names}",
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
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))

    return cmd_docs(args, resolver=UnionResolver(consumer, res.projects()))


def _union_uid(union, requested: str) -> str:
    """The union's key for a UID the composer typed. A consumer-local UID or an
    already-mangled UID is present verbatim; a namespace-qualified one (``gds:SR-0019``)
    is matched by its reconstructed display form. Returns ``requested`` unchanged when
    nothing matches, so the caller reports it as not-found in the composer's own
    vocabulary."""
    if union.project.get(requested) is not None:
        return requested
    for it in union.project.items():
        if union.qualified(it.uid) == requested:
            return it.uid
    return requested


def _compose_trace(args) -> int:
    """Walk an item to its 'why' over the composed union (SR-0010). Injection is the
    same tree bare ``tl trace`` prints, but a link whose target is a borrowed clause
    resolves *into* that source — displayed in ``<namespace>:<UID>`` vocabulary with
    the clause's own type/status/title — instead of dead-ending at ``(unresolved)``. A
    genuinely dangling cross-source reference stays ``(unresolved)`` in that same
    qualified vocabulary. With no sources declared this is a pure pass-through to core
    ``tl trace`` (SR-0003)."""
    try:
        consumer = load_project(args.path)
    except ProjectError as e:
        return _err(str(e))
    try:
        sources = parse_sources(consumer)
    except SourceError as e:
        return _err(str(e))

    if not sources:
        return cmd_trace(args)

    uid = _resolve_uid(consumer, args.uid, "trace", "UID")
    if uid is None:
        return USAGE

    try:
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))
    try:
        union = build_union(consumer, res.projects(), res.ns_aliases)
    except ComposeError as e:
        return _err(str(e))

    project = union.project
    start = _union_uid(union, uid)
    if project.get(start) is None:
        return _err(f"{uid} does not exist")

    # Show a borrowed clause but stop at the source boundary (SR-0020): a
    # consumer item expands into its links; a composed source clause is rendered
    # in the source's own vocabulary and its source-internal links are not walked.
    local_uids = {it.uid for it in consumer.items()}
    render_trace(project, start, direction=args.direction, max_depth=args.depth or 0,
                 uid_display=union.qualified, expand=lambda u: u in local_uids)
    return OK


def _compose_ratify(args) -> int:
    """Ratify an item, resolving its grounding over the composed union (SR-0004).

    A human takes accountability only for an unambiguous, grounded item. Core
    `tl ratify` enforces that gate over the bare local graph, so it wrongly
    refuses an item whose grounding chain reaches a root only *through* a
    composed source — the namespace-qualified target (`base:RISK-0001`) reads as
    unresolved and the item looks orphaned. tl-compose runs the same gate over
    the union, where that chain resolves, then writes the accepted status back to
    the consumer's own register — the union is a read-only view (NG-0002), never
    an authority we persist into. With no sources declared this is a pure
    pass-through to core `tl ratify` (SR-0003)."""
    try:
        consumer = load_project(args.path)
    except ProjectError as e:
        return _err(str(e))
    try:
        sources = parse_sources(consumer)
    except SourceError as e:
        return _err(str(e))

    if not sources:
        return cmd_ratify(args)

    uid = _resolve_uid(consumer, args.uid, "ratify", "UID")
    if uid is None:
        return USAGE
    item = consumer.get(uid)
    if item is None:
        return _err(f"{uid} does not exist")
    by = _resolve_value(args.by, "ratifier", "--by", default=getpass.getuser())
    if by is None:
        return USAGE

    try:
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))
    try:
        union = build_union(consumer, res.projects(), res.ns_aliases)
    except ComposeError as e:
        return _err(str(e))

    # The accountability gate (grounding.ratify), but evaluated over the union so a
    # grounding chain that only reaches a root through a source is seen, not orphaned.
    if item.attrs.get("ambiguous"):
        return _err(f"{uid} is flagged ambiguous and cannot be ratified until clarified")
    schema = union.project.schema
    union_item = union.project.get(uid)
    if union_item is None:  # pragma: no cover — consumer items are present verbatim
        return _err(f"{uid} does not exist")
    if not schema.is_root(union_item) and not reaches_root(Index.build(union.project),
                                                           schema, uid):
        return _err(f"{uid} is not grounded to a root and cannot be ratified")

    item.status = "ratified"
    item.attrs["ratified_by"] = by
    write_item(item, consumer.register_of(uid))
    print(f"{uid} ratified by {by}")
    return OK


def _compose_migrate(args) -> int:
    """Migrate the consumer, judging its ratification records over the union
    (SR-0003, SR-0004).

    Core `tl migrate` binds a record that names a ratifier but carries no
    fingerprint, and rightly declines any item it cannot justify: one whose
    grounding chain reaches a root only *through* a composed source reads as
    orphaned to the bare tool. throughline 1.6.0 (SR-0153) opened the same seam on
    the repair that SR-0151 gave `ratify`, so tl-compose supplies the union as the
    grounding view and the unchanged core repair completes those records too.

    **The order is forced, not chosen.** A project below the current major cannot
    be loaded at all — which is precisely the state `migrate` exists to leave — so
    its `[[sources]]` cannot be read and no union can be built until the upgrade
    has run. Core therefore goes first and does the whole job it can do alone,
    reporting in its own words; only then is the union available to justify what
    it declined. The second pass is safe because the repair is idempotent by
    requirement (SR-0137): a bound record carries a fingerprint and never matches
    again, so nothing is restamped and the union pass can only *add*. It can only
    add, too, because a union grounds a superset of what the bare graph grounds —
    it never withdraws a justification.

    With no sources declared this is a pure pass-through to core `tl migrate`
    (SR-0003)."""
    rc = cmd_migrate(args)
    if rc != OK:
        return rc

    # The project is loadable from here — core has upgraded it if it needed it.
    try:
        consumer = load_project(args.path)
    except ProjectError as e:  # pragma: no cover - cmd_migrate would have failed first
        return _err(str(e))
    try:
        sources = parse_sources(consumer)
    except SourceError as e:
        return _err(str(e))
    if not sources:
        return OK

    try:
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))
    try:
        union = build_union(consumer, res.projects(), res.ns_aliases)
    except ComposeError as e:
        return _err(str(e))

    try:
        bound = migrate_project(args.path,
                                index=Index.build(union.project)).bound
    except ProjectError as e:  # pragma: no cover - the first pass proved it migrates
        return _err(str(e))

    # Reported separately, and in tl-compose's own words rather than a copy of
    # core's: what distinguishes these records is *why* they could be completed —
    # the composition justified an item the consumer's own graph could not.
    if bound:
        print(f"bound {len(bound)} further ratification record(s) whose item is "
              "grounded through a composed source, and so could not be justified "
              "by this graph alone:")
        for uid, stamp in bound.items():
            print(f"  {uid} = {stamp}")
    return OK


def _compose_link(args) -> int:
    """Add a link, resolving a cross-source destination over the union (SR-0004).

    Core `tl link` refuses a destination it cannot find in the bare local graph, so a
    link up into a borrowed clause (`base:RISK-0001`) — the ordinary way a consumer
    references a source — is rejected. tl-compose validates the destination over the
    union (the clause is real, just not local), then stores the link, namespace-
    qualified exactly as typed, on the consumer's own item; the source is never
    written (NG-0002). A local destination resolves in the union verbatim, so this
    stays behaviour-identical for a link between two local items. With no sources
    declared it is a pure pass-through to core `tl link` (SR-0003)."""
    try:
        consumer = load_project(args.path)
    except ProjectError as e:
        return _err(str(e))
    try:
        sources = parse_sources(consumer)
    except SourceError as e:
        return _err(str(e))

    if not sources:
        return cmd_link(args)

    src_uid = _resolve_uid(consumer, args.src, "link from (source)", "SRC")
    if src_uid is None:
        return USAGE
    dst_uid = _resolve_uid(consumer, args.dst, "link to (destination)", "DST")
    if dst_uid is None:
        return USAGE
    src = consumer.get(src_uid)
    if src is None:  # you may only link *from* one of your own items
        return _err(f"source {src_uid} does not exist")

    try:
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))
    try:
        union = build_union(consumer, res.projects(), res.ns_aliases)
    except ComposeError as e:
        return _err(str(e))

    dst = union.project.get(_union_uid(union, dst_uid))
    if dst is None:
        return _err(f"target {dst_uid} does not exist")

    link_types = sorted(consumer.schema.link_types) if consumer.schema.link_types else None
    ltype = _resolve_value(args.type, "link type", "--type", options=link_types)
    if ltype is None:
        return USAGE
    stamp = fingerprint(dst, union.project.schema) if args.stamp else None
    src.links.append(Link(target=dst_uid, type=ltype, stamp=stamp))
    write_item(src, consumer.register_of(src.uid))
    print(f"linked {src_uid} --{ltype}--> {dst_uid}" + (" (stamped)" if stamp else ""))
    return OK


def _compose_new(args) -> int:
    """Create an item, resolving an explicit cross-source ``--ground`` target over the
    union (SR-0004). Identical to core `tl new` except that a grounding target naming a
    borrowed clause (`base:RISK-0001`) is validated against the union rather than the
    bare local graph, so an item can be grounded *into* a source at birth. The item is
    written to the consumer only. When no sources are declared, or no requested
    ``--ground`` target is namespace-qualified, it defers to core `tl new` unchanged —
    so local grounding and the interactive picker keep the core's exact behaviour
    (SR-0003)."""
    try:
        consumer = load_project(args.path)
    except ProjectError as e:
        return _err(str(e))
    try:
        sources = parse_sources(consumer)
    except SourceError as e:
        return _err(str(e))

    qualified_grounds = [t for t in (args.ground or []) if is_namespace_qualified(t)]
    if not sources or not qualified_grounds:
        return cmd_new(args)  # nothing cross-source to resolve — core owns this path

    try:
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))
    try:
        union = build_union(consumer, res.projects(), res.ns_aliases)
    except ComposeError as e:
        return _err(str(e))

    reg = consumer.registers.get(args.prefix)
    if reg is None:
        return _err(f"no register with prefix '{args.prefix}' (run `tl register new`)")
    if args.uid:
        try:
            pfx, _ = parse_uid(args.uid)
        except UidError as e:
            return _err(str(e))
        if pfx != args.prefix:
            return _err(f"--uid {args.uid} does not match prefix {args.prefix}")
        if consumer.get(args.uid) is not None:
            return _err(f"{args.uid} already exists")
        uid = args.uid
    else:
        uid = next_uid(reg)

    # The birth status comes from the project's 'initial' role, never a value fixed
    # in code (SR-0131, SR-0019); --status overrides it explicitly.
    status = args.status if args.status is not None \
        else consumer.schema.status_role("initial")
    item = Item(uid=uid, type=args.type, status=status,
                title=args.title or "", text=args.text or "")
    if args.origin:
        item.attrs["origin"] = args.origin
    item._register_prefix = reg.prefix

    # Explicit grounding is always honored and never silently dropped (SR-0091): a
    # local target must exist locally, a namespace-qualified one in the union.
    default_type = args.ground_type or "derives_from"
    grounds: list[tuple[str, str]] = []
    for target in args.ground:
        exists = (union.project.get(_union_uid(union, target)) is not None
                  if is_namespace_qualified(target)
                  else consumer.get(target) is not None)
        if not exists:
            return _err(f"grounding target {target} does not exist")
        grounds.append((target, default_type))
    for target, ltype in grounds:
        item.links.append(Link(target=target, type=ltype))

    reg.items[uid] = item
    path = write_item(item, reg)
    print(f"created {uid} -> {path}")
    for target, ltype in grounds:
        print(f"  grounded: {uid} --{ltype}--> {target}")
    return OK


# --------------------------------------------------------- agent context (SR-0016)

# The composition half of the agent brief. `tl-compose context` (alias `agentinfo`)
# emits the unchanged core `tl context` brief first — every rule above is the core's
# and holds, because tl-compose is a strict superset (SR-0003) — and then appends this
# section, which describes the part composition adds and the core cannot know about.
_CTX_COMPOSE = """\
---

# Composition: working this project with `tl-compose`

Everything above is the core `tl` brief and holds **unchanged**: `tl-compose` is a
strict superset of `tl` (SR-0003) — every command listed works exactly as described,
and this project's own graph is validated by the very same rules. What follows is the
part composition adds, which the core brief cannot describe.

## What composition does

A composed project stays a normal throughline graph, but it may **reference clauses
that live in *other* throughline graphs** — a published standard (OWASP ASVS, GOV.UK,
WCAG), a sibling requirement set, a content-style axis — without copying them in.
Those external graphs are **sources**. A clause in a source is referenced from your
graph as `<namespace>:<UID>` (for example `asvs:V2.1.1`), where the *namespace* is a
label **you** choose. `tl-compose check` merges the consumer and its sources into one
**union graph**, runs the unchanged core validator over it, and reports every finding
back in `<namespace>:<UID>` vocabulary — so a link from a local requirement up into a
borrowed clause is validated, never left dangling.

## Declaring sources

Sources are declared as an array of `[[sources]]` tables in `throughline.toml`. Each
binds a namespace to one external graph:

```toml
[[sources]]
namespace = "asvs"                 # the label you reference it by
url = "https://github.com/rhodium-org/throughline-asvs"
ref = "v5.0.0"                     # REQUIRED for a url — pins the edition
```

- **`url` + `ref`** — a git origin pinned to an edition (normally a tag). The durable,
  shareable form; fetched into a per-user cache. A `url` **must** carry a `ref` — an
  unpinned dependency is rejected so a source can never silently track a moving branch.
- **`path`** — a local directory instead of a `url`, for developing a source and its
  consumer side by side (`url`/`ref` and `path` are mutually exclusive; a `path` takes
  no `ref`).
- **`subdir`** — optional, on either form: the graph lives in this directory relative
  to the repository (or `path`) root.

`[[sources]]` is config, so it is the one part of a composed project you edit in
`throughline.toml` by hand — there is no CLI subcommand that writes it. Everything
about the *graph itself* — items, links, statuses, UIDs — is still CLI-only, exactly
as the core brief says: use `tl-compose new`/`link`/`ratify`, never hand-edit a
`<UID>.yml` or a `.register.yml`.

## Declare every namespace you reference — composition is *not* transitive

If your graph references `asvs:…`, you must declare an `asvs` source. This holds
**transitively**: if a source you compose itself references `asvs:…` internally, that
does **not** import `asvs` for you — you must **also** declare `asvs` at the same
edition, or pull it forward with re-export (below). A reference to an undeclared
namespace fails the check; that is deliberate — the composer, not a source, owns which
editions are in play.

## Re-export and alias (SR-0014, SR-0015)

A source can pull *its own* sources forward into your union, so you don't restate a pin
you don't control:

```toml
[[sources]]
namespace = "gds"
url = "..."
ref = "v2026-07"
reexport = ["asvs"]                # pull gds's own asvs source forward, same name
# or:  reexport = { asvs = "owasp" }  # ...forward under an alias you choose
```

Re-export is **one level and opt-in**: only the namespaces you name are pulled forward,
and each inherits the intermediate source's pin — you never restate the ref. The array
form re-exports under the same name; the table form binds it to an alias you choose.

If a single namespace ends up bound to **two different editions** — declared at one ref
and re-exported at another — `tl-compose` will neither merge them nor silently pick
one: it fails fast, names both editions and where each came from, and states the fix
(pin the namespace explicitly to the one edition you intend, or alias the two apart so
they compose side by side).

## Union-aware commands

These operate over the composed union rather than the bare local graph; with **no**
`[[sources]]` declared they are pure pass-throughs to core `tl` (SR-0003):

- **`check`** — composes consumer + sources, validates the union, reports findings in
  `<namespace>:<UID>` vocabulary.
- **`docs`** — a `tl:matrix` target cell pointing at a borrowed clause renders that
  clause's own reference number.
- **`trace`** — a link into a borrowed clause is followed *into* the source (shown with
  its own type/status/title) instead of dead-ending at `(unresolved)`.

## The boundary (NG-0001, NG-0002)

Composition lives **only** in `tl-compose`; the `tl` core stays a single-purpose,
offline tool over one graph. And the check/union pipeline is **read-only** over its
sources — `tl-compose` never writes back to an external authority. Storing a link
*inside* a source, an issue tracker, or a wiki is a connector's job, not composition's.
"""


def _source_line(s: Source) -> str:
    """One human-readable bullet describing a declared source for the live listing."""
    where = f"`{s.url}` @ `{s.ref}`" if s.is_remote else f"path `{s.path}`"
    if s.subdir:
        where += f" (subdir `{s.subdir}`)"
    extra = ""
    if s.reexport:
        parts = [k if k == v else f"{k}→{v}" for k, v in sorted(s.reexport.items())]
        extra = f" · re-exports {', '.join(f'`{p}`' for p in parts)}"
    return f"- **`{s.namespace}`** — {where}{extra}"


def _ctx_sources(sources: list[Source]) -> str:
    """The live 'sources this project declares' section — the composition analogue of
    the core brief's live graph snapshot (SR-0016): read from this project's own
    config so the brief describes the composition the agent is really working in."""
    if not sources:
        return (
            "## Sources this project declares\n\n"
            "_None. This project declares no `[[sources]]`, so it is an ordinary "
            "throughline graph and every command behaves exactly as core `tl`. The "
            "composition machinery above becomes live the moment you add a source._"
        )
    lines = ["## Sources this project declares\n"]
    lines.extend(_source_line(s) for s in sources)
    return "\n".join(lines)


def _compose_context(args) -> int:
    """Emit the core `tl context` brief verbatim, then append the composition section
    and this project's live source listing (SR-0016). The core brief is captured from
    the unchanged core command so the superset holds byte-for-byte; only when the
    project declares sources is the full composition manual appended — with none
    declared the brief stays the core's plus a short 'composition available but unused'
    note, keeping the strict-superset promise (SR-0003)."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_context(args)
    sys.stdout.write(buf.getvalue())
    if rc != OK:
        return rc

    try:
        consumer = load_project(args.path)
        sources = parse_sources(consumer)
    except (ProjectError, SourceError):
        sources = []

    if not sources:
        sys.stdout.write(
            "\n---\n\n"
            "# Composition (`tl-compose`)\n\n"
            "This project declares no `[[sources]]`, so `tl-compose` behaves exactly "
            "as `tl` here — everything above is the whole brief. Composition "
            "(`[[sources]]`, union-aware `check`/`docs`/`trace`, re-export) becomes "
            "available the moment you add a source; run `tl-compose agentinfo` again "
            "then for the full composition brief.\n")
    else:
        sys.stdout.write("\n" + _CTX_COMPOSE + "\n" + _ctx_sources(sources) + "\n")
    sys.stdout.flush()
    return OK


def main(argv: list[str] | None = None) -> int:
    force_utf8_io()
    parser = build_parser()
    parser.prog = "tl-compose"
    for action in parser._actions:
        if "--version" in action.option_strings:
            action.version = _version_string()
    # `agentinfo` — an alias for `context` (SR-0016). The core parser owns the
    # `context` subcommand; register the alias here so it stays a compose concern.
    sub = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    ai = sub.add_parser(
        "agentinfo",
        help="alias for `context` — emit the agent brief (IDD + composition)")
    ai.set_defaults(func=cmd_context, cmd="context")
    args = parser.parse_args(argv)
    if getattr(args, "cmd", None) in ("context", "agentinfo"):
        try:
            return _compose_context(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
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
    if getattr(args, "cmd", None) == "trace":
        try:
            return _compose_trace(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
    if getattr(args, "cmd", None) == "ratify":
        try:
            return _compose_ratify(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
    if getattr(args, "cmd", None) == "migrate":
        try:
            return _compose_migrate(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
    if getattr(args, "cmd", None) == "link":
        try:
            return _compose_link(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
    if getattr(args, "cmd", None) == "new":
        try:
            return _compose_new(args)
        except KeyboardInterrupt:  # pragma: no cover
            return USAGE
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        return USAGE


if __name__ == "__main__":
    raise SystemExit(main())
