# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The ``tl-compose`` entry point.

Design intent (SR-0003): ``tl-compose`` is a strict superset of ``tl``. Every
local-graph command is forwarded to throughline's CLI unchanged; the union-aware
commands are layered on top. Which commands those are is not restated here — the
one place that knows is :data:`_UNION_COMMANDS`, which both dispatches them and
supplies the agent brief's description of each (SR-0025). When a project declares
no ``[[sources]]``, those too are pure pass-throughs, so ``tl-compose`` over an
ordinary project behaves exactly like ``tl``.

`check` composes the consumer with its declared sources into one union graph
(union.py), runs the *unchanged* core validator over it (SR-0004), and translates
findings back into ``<namespace>:<UID>`` vocabulary before printing.

`migrate` (SR-0004) hands the union to the unchanged core repair as its grounding
view, so a ratification record whose item is justified only through a composed
source is completed rather than declined. Core runs first and alone: a project
below the current major cannot be loaded, so no union exists until it is upgraded.

`ratify` (SR-0004) does the same for the accountability gate: core's own
``grounding.ratify`` decides and records, taking the union only as the grounding
view it judges against, so a composed sign-off is the identical act — same
refusals, same fingerprint — merely able to see further.

`trace` (SR-0010) walks that same union so a link into a borrowed clause resolves
into the source and reads in ``<namespace>:<UID>`` vocabulary, instead of the
dead-end ``(unresolved)`` bare ``tl`` prints for anything outside the local graph.

`query` (SR-0037) lists over the union, in that same vocabulary, and says which
scope it answered over. It is the command a composer discovers a borrowed clause
with, so while it answered over the local graph alone the tool accepted references
— ``--ground asvs:V2.1.1`` — that it gave no way to find, and reported the absence
as ``0 item(s)``.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

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
    cmd_query,
    cmd_ratify,
    cmd_trace,
    force_utf8_io,
    render_trace,
)
from throughline.fingerprint import fingerprint
from throughline.graph import Index
from throughline.grounding import GroundingError, ratify
from throughline.identity import RATIFIED_ID_ATTR, IdentityError, default_ratifier
from throughline.inject import referenced_uids
from throughline.model import Item, Link
from throughline.storage import (
    ProjectError,
    load_project,
    migrate_project,
    write_item,
)
from throughline.uid import UidError, next_uid, parse_uid
from throughline.validate import (
    ERROR,
    FilterError,
    eval_filter,
    is_namespace_qualified,
    validate,
)
from throughline.version import distribution_version

from . import git_resolver  # noqa: F401 — registers the reference git resolver (SR-0011)
from .resolve import cache_root
from .resolver import UnionResolver
from .seam import SeamError, apply_seam, is_borrowed, parse_seam
from .sources import Source, SourceError, parse_sources
from .spi import ResolvedSource, ResolverError, resolver_for
from .union import ComposeError, build_union, translate_finding

OK, FINDINGS, USAGE = 0, 1, 2

# Core's own aliases for a union-aware command, mapped to the name `_UNION_COMMANDS`
# holds it under (SR-0037).
_CMD_ALIASES = {"ls": "query"}


def _err(msg: str) -> int:
    print(f"tl-compose: {msg}", file=sys.stderr)
    return USAGE


def _version_string() -> str:
    # tl-compose is its own front door; report its version and the throughline core
    # it composes over, not throughline's (build_parser wires `--version` to `tl`).
    #
    # Both are read through throughline's own helper rather than restated here
    # (SR-0027). A composed run is judged by core's validator, so the pair is what
    # someone is actually trying to establish when they ask — and a mismatched pair
    # is invisible while each half reports a clean release number it has departed
    # from. Whichever of the two is a working tree says so.
    return (
        f"tl-compose {distribution_version('throughline-compose')} "
        f"(throughline {distribution_version('throughline')})"
    )


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


# The line of core's summary that composition must rescope. Located by its label
# rather than by position, and asserted by a test against core's real output, so a
# change to core's format fails the build loudly instead of degrading a user's report
# quietly. Nothing else in the summary is touched.
_GROUNDING_LABEL = "  Grounding  "


def _local_grounding(union, schema, index, local) -> tuple[int, int, int, int]:
    """The grounding figures for the consumer's own items (SR-0029).

    The terminus is widened exactly as ``apply_seam`` widens it — "a root, or
    anything borrowed" — so the headline and the findings answer the same question
    and cannot disagree. A local item grounded through a source counts as grounded
    in both, because it is one walk of core's own ``Index.reaches``, not a second
    grounding engine (SR-0026, NG-0001).
    """
    non_roots = [it for it in local if not schema.is_root(it)]
    grounded = sum(
        1 for it in non_roots
        if index.reaches(
            it.uid,
            lambda i: schema.is_root(i) or is_borrowed(union, i.uid),
            schema.ground_link_types,
        )
    )
    # A local delivery root may be served by a borrowed item, so the in-links are
    # read over the whole union even though the roots counted are the consumer's.
    delivery = [it for it in local if it.type in schema.delivery_roots]
    served = sum(
        1 for it in delivery
        if any(lt in schema.ground_link_types for _o, lt in index.in_links(it.uid))
    )
    return grounded, len(non_roots), served, len(delivery)


def _compose_check_summary(union, index=None) -> list[str]:
    """The graph summary ``check`` prints over the composed union (SR-0022, SR-0029).

    The item, status and link lines are byte-identical to what core ``tl check``
    prints but computed over the union, so a composer sees the size of what was
    actually validated. A trailing ``Local`` line then splits the consumer's own
    items from the ones borrowed through a source (a union item is local exactly
    when its UID is not a mangled, source-owned one).

    The grounding line is the exception, and is rescoped to the consumer's own items
    (SR-0029). Counted over the union it reports a shortfall no reader can close:
    borrowed items ground under the model of the graph that owns them, which a
    consumer is no longer obliged to restate since SR-0026, so they read as orphans
    of a model that was never theirs. Printed directly above a verdict of zero
    errors, that figure teaches the reader to distrust the verdict — the harm
    SR-0026 names for findings, arriving one line higher. The line says what it
    counts so its scope is never inferred from its size.
    """
    lines = list(_check_summary(union.project))
    live = [it for it in union.project.items() if not it.is_deleted]
    local = [it for it in live if union.qualified(it.uid) == it.uid]
    borrowed = len(live) - len(local)

    if index is None:
        index = Index.build(union.project)
    grounded, non_roots, served, delivery = _local_grounding(
        union, union.project.schema, index, local
    )
    scoped = (
        f"{_GROUNDING_LABEL}{grounded}/{non_roots} local non-root items trace to a "
        f"root · {served}/{delivery} local delivery roots served"
    )
    for i, line in enumerate(lines):
        if line.startswith(_GROUNDING_LABEL):
            lines[i] = scoped
            break
    else:  # core's format moved; keep the honest figure rather than lose it
        lines.append(scoped)

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

    # The consumer's own widening of the seam, read before anything is judged so a
    # misspelled rule name is refused rather than left silently never firing
    # (SR-0035).
    try:
        extra_seam_rules = parse_seam(consumer)
    except SeamError as e:
        return _err(str(e))

    # Publication coverage is core's, but the set of published documents is not
    # something the validator reads for itself — `check` hands it in, and omitting it
    # leaves the `unpublished` rule (SR-0096) inert rather than failing, which is
    # indistinguishable from a graph that is fully published. Read over the union so
    # a document may cite a borrowed item, and by the same `[docs] paths` the
    # consumer already configured for `docs`.
    published = referenced_uids(union.project)  # None unless [docs] paths configured
    findings = validate(union.project, strict=args.strict, published=published)
    # Report against a borrowed item only what this consumer can act on, and let a
    # local item grounded through a source count as grounded (SR-0026), widened by
    # any rule the consumer declared under [seam] (SR-0035). The same index then
    # serves the summary, so the headline and the findings are walked over one graph
    # rather than two builds of it (SR-0029).
    index = Index.build(union.project)
    findings, suppressed, rescued = apply_seam(
        findings, union, union.project.schema, index, extra_seam_rules
    )
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
        for line in _compose_check_summary(union, index):
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


def _query_dict(item) -> dict:
    """One matched item of the display view as data (SR-0037). The item already
    names itself as the composer does; what the dict adds is the owning source as
    its own field, so a consumer of the JSON reads provenance rather than parsing
    it back out of a UID."""
    d = item.to_dict()
    d["source"] = item.uid.split(":", 1)[0] if is_namespace_qualified(item.uid) else None
    return d


def _compose_query(args) -> int:
    """List the items matching a filter over the composed union (SR-0037).

    Every other union-aware command already answers over the composed graph, while
    the one command whose purpose is to show a composer what exists answered over
    the consumer's own graph alone — and said nothing about having done so. The
    second half is the worse one: a filter naming a type only a source holds printed
    `0 item(s)`, which reads as a clean bill of health rather than as a question that
    was never asked. So the union is the default here as it is everywhere else, and
    ``--local`` is how a composer narrows the answer deliberately.

    ``--local`` narrows *which items are listed*, not which graph they are judged
    in: the filter's link predicates are evaluated over the union either way, so a
    local item counts as verified by a borrowed test under both scopes. Narrowing
    the graph as well would make ``--local`` a second, quieter validator with its
    own answers, which is the divergence SR-0003 exists to refuse.

    The scope line is printed in JSON mode too, where core prints no count at all.
    It goes to stderr, so it cannot corrupt the document on stdout, and a listing
    that states its scope in one mode and not the other would leave the reader to
    discover which they were in. With no sources declared this is a pure
    pass-through to core ``tl query`` (SR-0003).
    """
    try:
        consumer = load_project(args.path)
    except ProjectError as e:
        return _err(str(e))
    try:
        sources = parse_sources(consumer)
    except SourceError as e:
        return _err(str(e))

    if not sources:
        return cmd_query(args)

    try:
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))
    try:
        union = build_union(consumer, res.projects(), res.ns_aliases)
    except ComposeError as e:
        return _err(str(e))

    view = union.displayed()
    live = [it for it in view.items() if args.all or not it.is_deleted]
    local = [it for it in live if not is_namespace_qualified(it.uid)]
    pool = local if args.local else live

    index = Index.build(view)
    try:
        matched = [it for it in pool if eval_filter(it, args.expr, index)]
    except FilterError as e:
        return _err(f"bad filter expression: {e}")
    # Local UIDs are uppercase and namespaces lowercase, so sorting by the name the
    # composer reads lists their own items first, then groups each source together.
    matched.sort(key=lambda it: it.uid)

    if args.format == "json":
        import json
        print(json.dumps([_query_dict(it) for it in matched], indent=2, default=str))
    else:
        for it in matched:
            title = f"  {it.title}" if it.title else ""
            print(f"{it.uid}  [{it.type}/{it.status}]{title}")
        sys.stdout.flush()

    n_sources = len(res.resolved)
    if args.local:
        scope = (f"local only · {len(live) - len(local)} borrowed item(s) across "
                 f"{n_sources} source(s) not searched — drop --local to search them")
    else:
        borrowed = sum(1 for it in matched if is_namespace_qualified(it.uid))
        scope = (f"composed graph · {len(matched) - borrowed} local · "
                 f"{borrowed} borrowed from {n_sources} source(s)")
    print(f"\n{len(matched)} item(s) ({scope})", file=sys.stderr)
    return OK


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
    """Ratify an item, handing core's accountability gate the union as its
    grounding view (SR-0004).

    A human takes accountability only for an unambiguous, grounded item. Core
    `tl ratify` enforces that gate over the bare local graph, so it wrongly
    refuses an item whose grounding chain reaches a root only *through* a
    composed source — the namespace-qualified target (`base:RISK-0001`) reads as
    unresolved and the item looks orphaned. The fix is to widen what the gate can
    *see*, not to restate it: :func:`~throughline.grounding.ratify` accepts the
    union index through the seam built for this caller (core SR-0151), judges the
    consumer's own item against it, and writes the acceptance record itself. We
    then persist that item to the consumer's own register — the union is a
    read-only view (NG-0002), never an authority we write into.

    This function used to copy core's body instead, and the copy drifted in
    precisely the way SR-0004 forbids it for. It recorded `ratified_by` with no
    `ratified_fingerprint`, so every signature it made was unbound to the content
    signed (core SR-0148); it hardcoded the status string rather than reading the
    configured role, and assigned it directly, bypassing the declared transition;
    and it lacked the guard that refuses to overwrite an existing ratifier
    without trace. A copy is not covered by the tests of its original, so none of
    that failed anything here. With no sources declared this is a pure
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
    if consumer.get(uid) is None:  # fail before resolving sources over the network
        return _err(f"{uid} does not exist")
    # The same default core offers (SR-0003): the identity this repository already
    # signs with, not the operating-system account name. Restating core's choice
    # here is what let the two drift apart — for a while `tl-compose ratify`
    # offered a different ratifier depending only on whether the project happened
    # to declare a source, which is precisely the divergence SR-0003 forbids.
    by = _resolve_value(args.by, "ratifier", "--by",
                        default=default_ratifier(args.path))
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

    try:
        # `by_id` travels with the name for the same reason the union does: core
        # owns what a ratification record contains (SR-0004), and a composed
        # sign-off that quietly dropped the identifier would be a weaker record
        # than the identical bare-`tl` one.
        item = ratify(consumer, uid, by, index=Index.build(union.project),
                      by_id=getattr(args, "by_id", None))
    except IdentityError as e:
        return _err(str(e))
    except GroundingError as e:
        return _err(str(e))
    write_item(item, consumer.register_of(uid))
    identifier = item.attrs.get(RATIFIED_ID_ATTR)
    print(f"{uid} ratified by {by}" + (f" ({identifier})" if identifier else ""))
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

`[[sources]]` is config, so it is the one part of a composed project you edit by
hand — there is no CLI subcommand that writes it. Everything about the *graph
itself* stays CLI-only; see **What you may write in a consuming project**, below.

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

@@UNION_COMMANDS@@

## The source cache — a moved ref is **not** refetched

A `url` + `ref` source is fetched once into a per-user cache, keyed by that exact
`(url, ref)` pair, and is offline and unchanged thereafter. That is what makes a
composed check reproducible, and it has one consequence you must know:

> **If you move a git tag, `tl-compose` will keep using the content it fetched the
> first time.** The check will pass, and it will have proved nothing about the new
> content.

To pick up changed content behind a ref you already used, either bump the `ref` to a
new edition (the intended route — an edition is meant to be immutable), or delete
that source's cache directory. This project's cache lives at:

```
@@CACHE_ROOT@@
```

## What you may write in a consuming project

A source is **read-only** (NG-0002). Composition gives you a wider *view*, never a
wider *authority*, so in a consuming project:

- **You write only to your own registers.** Every item you create, link, restatus or
  ratify is yours. A borrowed clause is never edited, never restatused, and **never
  ratified by you** — its own graph owns its accountability record, and a
  `<namespace>:<UID>` argument to a writing command is a mistake, not a shortcut.
- **You may point *at* a source freely.** `--ground base:RISK-0001`, `link SR-0007
  base:RISK-0001 --type mitigates` — the link is stored on *your* item, namespace-
  qualified exactly as typed.
- **`[[sources]]` is the one thing you hand-edit,** because it is config, not graph.
  Items, links, statuses and UIDs stay CLI-only exactly as the core brief says: use
  `tl-compose new`/`link`/`ratify`, never hand-edit a `<UID>.yml` or a
  `.register.yml`.

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
            "(`[[sources]]`, re-export, and union-aware "
            + "/".join(f"`{n}`" for n in sorted(_UNION_COMMANDS))
            + ") becomes available the moment you add a source; run "
            "`tl-compose agentinfo` again then for the full composition brief.\n")
    else:
        sys.stdout.write("\n" + _compose_brief() + "\n"
                         + _ctx_sources(sources) + "\n")
    sys.stdout.flush()
    return OK


# Every command whose behaviour differs over the composed union, bound in one place
# to *both* the handler that makes it differ and the sentence the brief tells an
# agent about it (SR-0025). `main` dispatches through this table and the brief is
# rendered from it, so a command cannot be given union behaviour without also being
# described — the two cannot drift, because there is only one of them. What this
# replaced was an if-chain in `main` beside a hand-written bullet list: the chain
# had grown to eight commands while the list still named three, and the five it had
# lost — `ratify` and `new` among them — were the ones an agent most needed, since
# they are the commands that *write*.
_UNION_COMMANDS: dict[str, tuple[Callable[[argparse.Namespace], int], str]] = {
    "check": (
        _compose_check,
        "composes consumer + sources, validates the union with core's own "
        "validator, and reports every finding in `<namespace>:<UID>` vocabulary."),
    "query": (
        _compose_query,
        "lists over the composed graph, so a borrowed clause is findable and is "
        "shown as `<namespace>:<UID>`; `--local` narrows to your own items, and "
        "either way the count says which scope it answered over. `ls` is an alias "
        "for it, and `--format json` carries each item's owning source as a field."),
    "docs": (
        _compose_docs,
        "a `tl:matrix` target cell pointing at a borrowed clause renders that "
        "clause's own reference number."),
    "trace": (
        _compose_trace,
        "a link into a borrowed clause is followed *into* the source (with its own "
        "type, status and title) instead of dead-ending at `(unresolved)`."),
    "new": (
        _compose_new,
        "a `--ground` target naming a borrowed clause is validated against the "
        "union, so an item can be grounded *into* a source at birth. The item is "
        "written to your project only."),
    "link": (
        _compose_link,
        "a destination inside a source resolves over the union instead of being "
        "refused as unknown. The link is stored on *your* item, namespace-"
        "qualified exactly as typed; the source is never written."),
    "ratify": (
        _compose_ratify,
        "core's accountability gate judges your item against the union, so one "
        "grounded only *through* a source is no longer refused as orphaned. It is "
        "the identical act — same refusals, same fingerprint — merely able to see "
        "further, and it signs **your** item, never a borrowed one."),
    "migrate": (
        _compose_migrate,
        "core's repair runs first and alone (a project below the current major "
        "cannot be loaded, so no union exists yet), then a second pass offers it "
        "the union so a record it declined as ungrounded can be completed."),
    "context": (
        _compose_context,
        "emits the core brief unchanged, then this composition section and your "
        "live source listing. `agentinfo` is an alias for it."),
}


def _ctx_union_commands() -> str:
    """The union-aware command section, rendered from the dispatch table rather than
    kept by hand (SR-0025)."""
    return "\n".join([
        "## Union-aware commands",
        "",
        "These operate over the composed union rather than the bare local graph. "
        "With **no** `[[sources]]` declared every one of them is a pure pass-through "
        "to core `tl` (SR-0003):",
        "",
        *(f"- **`{name}`** — {note}"
          for name, (_, note) in sorted(_UNION_COMMANDS.items())),
    ])


def _compose_brief() -> str:
    """The composition section, with its derived parts filled in (SR-0025).

    Substitution is by literal replacement rather than ``str.format`` because the
    prose contains TOML examples with braces in them; a formatting pass over
    hand-written documentation is a trap that goes off the next time someone adds an
    inline table to an example."""
    return (_CTX_COMPOSE
            .replace("@@UNION_COMMANDS@@", _ctx_union_commands())
            .replace("@@CACHE_ROOT@@", str(cache_root())))


def _compose_uncovered() -> list[str]:
    """Union-aware commands the brief would not describe (SR-0025). Empty by
    construction while the dispatch table is the only route to union behaviour;
    returned rather than raised so the test that gates it decides how to fail, and
    kept as a check because 'by construction' is a claim, not a guarantee."""
    rendered = _ctx_union_commands()
    return [name for name in _UNION_COMMANDS if f"`{name}`" not in rendered]


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
    # `--local` narrows a listing to the consumer's own items (SR-0037). The flag is
    # added to core's own `query` subparser rather than declared in core, which knows
    # nothing of borrowed items and so has nothing for it to mean. `ls` is core's
    # alias for that same parser object, so both spellings gain it in one call.
    sub.choices["query"].add_argument(
        "--local", action="store_true",
        help="list only this project's own items, not the ones it borrows")
    args = parser.parse_args(argv)
    # argparse records the spelling that was typed, so an alias of a union-aware
    # command arrives under a name the table does not hold — and would fall through
    # to the local-only core pass-through, silently, for the one command whose whole
    # complaint was silence (SR-0037). `agentinfo` escapes this only by fixing `cmd`
    # above, which the aliases core owns cannot do.
    cmd = _CMD_ALIASES.get(getattr(args, "cmd", None), getattr(args, "cmd", None))
    entry = _UNION_COMMANDS.get(cmd)
    try:
        return entry[0](args) if entry else args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        return USAGE


if __name__ == "__main__":
    raise SystemExit(main())
