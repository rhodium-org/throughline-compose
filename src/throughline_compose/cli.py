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
from pathlib import Path

from throughline.cli import (
    _by_count,
    _check_summary,
    _parse_attrs,
    _resolve_uid,
    _resolve_value,
    _subgraph_json,
    birth_item,
    build_parser,
    cmd_check,
    cmd_context,
    cmd_docs,
    cmd_dump,
    cmd_link,
    cmd_migrate,
    cmd_new,
    cmd_query,
    cmd_ratify,
    cmd_subgraph,
    cmd_trace,
    context_item_section,
    force_utf8_io,
    render_subgraph,
    render_trace,
)
from throughline.dump import build_dump
from throughline.fingerprint import fingerprint
from throughline.graph import Index
from throughline.grounding import ratification_obstacle, GroundingError, ratify
from throughline.identity import RATIFIED_ID_ATTR, IdentityError, default_ratifier
from throughline.inject import referenced_uids
from throughline.model import Item, Link, Project
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
from .sources import Source, SourceError, parse_sources, withdrawn_declarations
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


def _chain(via: tuple[str, ...]) -> str:
    """The path that carried a namespace into the union, as the summary prints it."""
    return " › ".join(via)


def _origin(where: str, via: tuple[str, ...]) -> str:
    """Where a binding came from (SR-0015): its location and the chain of declared
    sources that carried it in, or the consumer's own declaration."""
    return f"{where} via {_chain(via)}" if via else f"{where}, declared by you"


def _conflict_message(ns: str, origin_a: str, fp_a: str,
                      origin_b: str, fp_b: str) -> str:
    """The advisory a two-edition namespace collision fails with (SR-0015): the why
    (namespace, both editions, the path each came by) and the fix (pin explicitly,
    or alias apart on the source carrying one of them) — never a suggestion to
    merge, which the model cannot honour."""
    short = lambda fp: fp.removeprefix("sha256:")[:12]  # noqa: E731
    return (
        f"namespace '{ns}' is bound to two different editions and tl-compose will "
        f"neither merge them nor pick one for you:\n"
        f"  - {origin_a} [{short(fp_a)}]\n"
        f"  - {origin_b} [{short(fp_b)}]\n"
        f"fix it by either: pinning '{ns}' explicitly in your own [[sources]] to the "
        f"single edition you intend, so one binding governs every reference to it; "
        f"or aliasing one of them apart — set alias = {{ {ns} = \"{ns}-alt\" }} on "
        f"the declared source carrying it — so both editions compose side by side "
        f"as the two separate sources they are"
    )


class _Resolution:
    """The outcome of resolving a consumer's sources and their closure (SR-0045):
    the namespace -> :class:`ResolvedSource` map in bind order, a human origin and
    the carrying path per bound namespace, the coordinates each was reached by,
    the label map each source's own references resolve through, and the notices
    the summary prints."""

    def __init__(self):
        self.resolved: dict[str, ResolvedSource] = {}
        self.locations: dict[str, str] = {}
        # The declaration each bound namespace was reached by — the consumer's own
        # for a declared source, the inherited one for a transitive source, so an
        # export can state every pin as data and not only as prose (SR-0040).
        self.coordinates: dict[str, Source] = {}
        # The chain of union namespaces that carried each binding in; empty for a
        # source the consumer declared itself.
        self.via: dict[str, tuple[str, ...]] = {}
        # Per bound namespace: the labels that source's own references may use —
        # its direct declarations and every label its sources hoisted into it —
        # mapped to the union namespace each was bound under (SR-0045).
        self.labels: dict[str, dict[str, str]] = {}
        # What the summary should say beyond the bindings: a same-edition
        # coalescence, or a withdrawn key found in a published edition.
        self.notices: list[str] = []
        # fingerprint -> the first namespace bound to that edition
        self._holder: dict[str, str] = {}
        # One resolution per coordinates however many paths reach them
        self._memo: dict[tuple, ResolvedSource] = {}

    def origin(self, ns: str) -> str:
        return _origin(self.locations[ns], self.via[ns])

    def bind(self, ns: str, rs: ResolvedSource, where: str, source: Source,
             via: tuple[str, ...] = ()) -> bool:
        """Bind ``ns`` to a resolved source and return True, or return False when
        ``ns`` is already bound to that same edition, or fail fast when it is
        bound to a different one (SR-0015)."""
        existing = self.resolved.get(ns)
        if existing is not None:
            if existing.fingerprint != rs.fingerprint:
                raise ResolverError(_conflict_message(
                    ns, self.origin(ns), existing.fingerprint,
                    _origin(where, via), rs.fingerprint))
            return False  # same edition — a single bound source
        self.resolved[ns] = rs
        self.locations[ns] = where
        self.coordinates[ns] = source
        self.via[ns] = tuple(via)
        self.labels.setdefault(ns, {})
        self._holder.setdefault(rs.fingerprint, ns)
        return True

    def walk(self, ns: str, rename: Callable[[str], str]) -> None:
        """Bind the closure of the source bound as ``ns`` (SR-0045), depth-first in
        its declared order.

        ``rename`` maps a label as it would appear in *that source's own* union to
        the namespace the consumer binds it under: the consumer's alias on the
        declared source, composed with each intermediate's own alias on the way
        down, so an alias applies throughout the subtree it was set on. A source
        already bound to the same edition under another label is not bound twice:
        the reference is folded into the existing binding and the summary says so.
        A source bound before is not walked again, which is also what ends a cycle.
        """
        rs = self.resolved[ns]
        carrier = self.coordinates[ns]
        via = self.via[ns] + (ns,)
        for dep_ns in withdrawn_declarations(rs.project):
            self.notices.append(
                f"'{ns}' ({self.locations[ns]}) declares 'reexport' on its source "
                f"'{dep_ns}', a key withdrawn by SR-0045 — ignored; the sources it "
                f"named are composed anyway")
        src_root = Path(rs.project.path)
        view = self.labels[ns]
        for d in parse_sources(rs.project, withdrawn="ignore"):
            if d.path is not None and carrier.is_remote:
                raise ResolverError(
                    f"source '{d.namespace}' is declared by '{ns}' with a path "
                    f"({d.path}), but '{ns}' was fetched by url "
                    f"({carrier.url}@{carrier.ref}) and a path resolves nowhere from "
                    f"the cache — a source published by url must pin its own sources "
                    f"by url + ref (reached via {_chain(via)})")
            resolved = self._resolve(d, src_root, via)
            union_name = rename(d.namespace)
            holder = self._holder.get(resolved.fingerprint)
            if holder is not None and holder != union_name:
                bound = holder
                self.notices.append(
                    f"'{union_name}' (via {_chain(via)}) is the same edition as "
                    f"'{holder}' ({self.origin(holder)}) — bound once as '{holder}'")
            else:
                bound = union_name
                if self.bind(union_name, resolved, _source_location(d), d, via):
                    self.walk(union_name,
                              lambda n, _r=rename, _a=d.alias: _r(_a.get(n, n)))
            # What this source's own references may name: its label for the
            # dependency, and every label the dependency hoisted into it, each as
            # this source would have bound it.
            view[d.namespace] = bound
            for label, target in self.labels.get(bound, {}).items():
                view.setdefault(d.alias.get(label, label), target)

    def _resolve(self, d: Source, root: Path, via: tuple[str, ...]) -> ResolvedSource:
        key = (d.url, d.ref, d.subdir,
               None if d.path is None else str((root / d.path).resolve()))
        hit = self._memo.get(key)
        if hit is None:
            try:
                hit = resolver_for(d).resolve(d, root)
            except ResolverError as e:
                raise ResolverError(f"{e} (reached via {_chain(via)})") from e
            self._memo[key] = hit
        return hit

    def projects(self) -> dict:
        """The namespace -> Project view the union engine consumes (SR-0004)."""
        return {ns: rs.project for ns, rs in self.resolved.items()}


def _resolve_sources(sources, root) -> _Resolution:
    """Resolve each declared source and its closure through the registered
    resolvers (SR-0011) into a :class:`_Resolution`. Every fetch goes through the
    one resolver interface; no other code path reaches a source. Composing a
    source composes what it composes (SR-0045): every source a declared source
    declares, to any depth, is bound under the label its declaring source gave it
    at the pin that source set, renamed only by an alias the consumer set on the
    declared source carrying it. A namespace bound to two editions fails fast
    (SR-0015). Raises :class:`ResolverError` for the caller to report, so a source
    that will not resolve is named in the composer's vocabulary."""
    out = _Resolution()

    # 1. Directly declared sources, resolved side by side (SR-0044). Each
    #    look-up of a pinned ref on its origin and each fetch runs beside the
    #    others, and the union is bound in declared order whatever order they
    #    finish in. Two sources sharing a URL and ref share a cache directory,
    #    so only the first of each such pair runs concurrently; the rest resolve
    #    afterwards from the warm cache, because two clones into one directory
    #    at once would corrupt it. The consumer's own declarations bind first,
    #    so a name the consumer chose always wins the label.
    for s, resolved in zip(sources, _resolve_side_by_side(sources, root)):
        out.bind(s.namespace, resolved, _source_location(s), s)

    # 2. Each declared source's closure, depth-first, in declared order.
    for s in sources:
        out.walk(s.namespace, lambda n, _a=s.alias: _a.get(n, n))

    return out


def _cache_key(s):
    """What two sources share when they share a cache directory: the URL and ref."""
    return (s.url, s.ref) if s.url is not None else None


def _resolve_side_by_side(sources, root):
    """Resolve declared sources concurrently, returning results in declared order.

    The first source for each cache key runs in the pool; a later source with the
    same key waits for the pool and resolves alone afterwards. An error is raised
    for the first failing source in declared order, so the report reads as it did
    when resolution was sequential (SR-0044).
    """
    from concurrent.futures import ThreadPoolExecutor

    results: list = [None] * len(sources)
    seen: set = set()
    first: list[int] = []
    later: list[int] = []
    for i, s in enumerate(sources):
        key = _cache_key(s)
        if key is None or key not in seen:
            seen.add(key)
            first.append(i)
        else:
            later.append(i)

    if first and _can_thread():
        try:
            with ThreadPoolExecutor(max_workers=min(8, len(first))) as pool:
                futures = {i: pool.submit(resolver_for(sources[i]).resolve, sources[i], root) for i in first}
                for i in first:  # declared order, so the first failure is the one reported
                    results[i] = futures[i].result()
        except RuntimeError as e:
            # A platform that has the module but cannot start a thread. Nothing
            # has been bound yet, so resolve every source in order as before.
            if "thread" not in str(e).lower():
                raise
            first = list(range(len(sources)))
            later = []
            for i in first:
                results[i] = resolver_for(sources[i]).resolve(sources[i], root)
            return results
    else:
        for i in first:
            results[i] = resolver_for(sources[i]).resolve(sources[i], root)
    for i in later:
        results[i] = resolver_for(sources[i]).resolve(sources[i], root)
    return results


def _can_thread() -> bool:
    """Whether this platform can run a thread beside the main one.

    Python under Pyodide — the throughline editor's worker — reports itself as
    emscripten and cannot start a thread, so there the sources resolve one after
    another as they did before SR-0044. The requirement is about running side by
    side where that is possible, not about requiring threads to exist.
    """
    import sys

    return sys.platform != "emscripten"


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
        union = build_union(consumer, res.projects(), res.labels)
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

        # Every bound namespace in bind order, a transitive one with the path that
        # carried it in, then what the walk folded or ignored (SR-0045, SR-0016).
        def _describe(ns: str) -> str:
            fp = res.resolved[ns].fingerprint.removeprefix("sha256:")[:12]
            line = f"{ns} ({res.locations[ns]}) [{fp}]"
            return f"{line} via {_chain(res.via[ns])}" if res.via[ns] else line
        names = ", ".join(_describe(ns) for ns in res.resolved)
        print(f"\ntl-compose check · {len(res.resolved)} source(s) composed: {names}",
              file=sys.stderr)
        for note in res.notices:
            print(f"  note: {note}", file=sys.stderr)
    tally = f"\n{errs} error(s), {warns} warning(s)"
    if not getattr(args, "quiet", False) and errs == 0:
        tally += "  — composed graph is sound" + (" (strict)" if args.strict else "")
    print(tally, file=sys.stderr)
    return FINDINGS if any(f.severity == ERROR for f in findings) else OK


def _owning_source(uid: str) -> str | None:
    """The namespace a displayed UID was borrowed from, or ``None`` when it is the
    consumer's own. Provenance as data rather than something a reader has to parse
    back out of a qualifier (SR-0037, SR-0040)."""
    return uid.split(":", 1)[0] if is_namespace_qualified(uid) else None


def _query_dict(item) -> dict:
    """One matched item of the display view as data (SR-0037). The item already
    names itself as the composer does; what the dict adds is the owning source as
    its own field, so a consumer of the JSON reads provenance rather than parsing
    it back out of a UID."""
    d = item.to_dict()
    d["source"] = _owning_source(item.uid)
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
        union = build_union(consumer, res.projects(), res.labels)
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


# The composition block's own schema version, independent of core's
# `dump_schema_version`: the two documents evolve on separate release cycles, and a
# reader that keyed off core's alone could not tell a composition change from none.
COMPOSE_DUMP_SCHEMA_VERSION = 1


def _local_view(view: Project, consumer: Project) -> Project:
    """``view`` narrowed to the consumer's own registers (SR-0040). Ownership is
    read from the consumer's own register set rather than inferred from the shape
    of a displayed name, so narrowing cannot disagree with what was loaded."""
    out = Project(path=view.path, config=view.config)
    for prefix, reg in view.registers.items():
        if prefix in consumer.registers:
            out.registers[prefix] = reg
    return out


def _dump_composition(res: _Resolution, view: Project, *, local: bool) -> dict:
    """The scope an export answered over (SR-0040): which sources were composed at
    which pinned edition, how many items are the consumer's own, and whether the
    document was narrowed.

    The counts are taken over the whole union even for a narrowed export, because
    what they exist to tell a reader is how much is *missing* — a partial export
    that reported only what it contains would state its restriction and then leave
    its size indistinguishable from a whole one's."""
    per_source = dict.fromkeys(res.resolved, 0)
    local_count = 0
    for it in view.items():
        ns = _owning_source(it.uid)
        if ns is None:
            local_count += 1
        else:
            per_source[ns] = per_source.get(ns, 0) + 1
    return {
        "compose_dump_schema_version": COMPOSE_DUMP_SCHEMA_VERSION,
        "scope": "local" if local else "composed",
        "local_item_count": local_count,
        "borrowed_item_count": sum(per_source.values()),
        "sources": [_dump_source(ns, res, per_source[ns])
                    for ns in sorted(res.resolved)],
    }


def _dump_source(ns: str, res: _Resolution, item_count: int) -> dict:
    """One composed source as data (SR-0040). The fingerprint is the edition that
    was actually read (SR-0012), which is what a mutable ref cannot be trusted to
    name on its own."""
    s = res.coordinates[ns]
    return {
        "namespace": ns,
        "url": s.url,
        "ref": s.ref,
        "path": s.path,
        "subdir": s.subdir,
        "origin": res.locations[ns],
        "fingerprint": res.resolved[ns].fingerprint,
        "item_count": item_count,
    }


def _compose_dump(args) -> int:
    """Export the composed graph as one JSON document (SR-0040).

    `dump` is the sanctioned interchange surface (core SR-0055) — the one command
    whose declared purpose is handing the graph to somebody else's tooling — so it
    is answered over the union, as every other union-aware command already is. Over
    the consumer's graph alone the document is not merely partial but unresolvable:
    it carries links to borrowed clauses it does not contain, and what a reader must
    then drop is precisely the record that a local requirement is grounded in a
    published standard.

    Items read in ``<namespace>:<UID>`` vocabulary and each carries its owning
    source as a field, so provenance is data rather than something parsed back out
    of a qualifier. The ``composition`` block states the scope that was answered
    over. ``--local`` narrows the document to the consumer's own items — a
    legitimate thing to want, since publishing your own graph should not oblige you
    to ship a standard's full text with it — and records the narrowing in the
    document, so partiality is a fact in the data rather than something the reader
    has to know already. With no sources declared this is a pure pass-through to
    core ``tl dump`` (SR-0003).
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
        return cmd_dump(args)

    try:
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))
    try:
        union = build_union(consumer, res.projects(), res.labels)
    except ComposeError as e:
        return _err(str(e))

    view = union.displayed()
    composition = _dump_composition(res, view, local=args.local)
    # `_version_string` names both layers, so the document says composition was
    # involved rather than leaving a reader to infer it from the extra block.
    data = build_dump(_local_view(view, consumer) if args.local else view,
                      _version_string())
    for item in data["items"]:
        item["source"] = _owning_source(item["uid"])
    data["composition"] = composition

    import json
    text = json.dumps(data, indent=2, default=str, sort_keys=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text)
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

    return cmd_docs(args, resolver=UnionResolver(consumer, res.projects(),
                                                 res.labels))


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
        union = build_union(consumer, res.projects(), res.labels)
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


def _compose_subgraph(args) -> int:
    """The neighbourhood of one item over the composed union (SR-0041).

    Both directed closures plus the links joining their members, in
    ``<namespace>:<UID>`` vocabulary, so the cross-source edges — the ones a
    composer most needs before changing anything — are part of the answer rather
    than ``(unresolved)`` stubs.

    The boundary is trace's (SR-0020) with one deliberate exception: the item the
    composer *named* is always walked, so `subgraph asvs:V2.1.1` can answer which
    local items adopt that clause. Everything reached from it is borrowed and is
    not walked in turn, so the view stays one step inside the source. With no
    sources declared this is a pure pass-through to core ``tl subgraph``
    (SR-0003).
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
        return cmd_subgraph(args)

    uid = _resolve_uid(consumer, args.uid, "show the neighbourhood of", "UID")
    if uid is None:
        return USAGE

    try:
        res = _resolve_sources(sources, Path(args.path))
    except ResolverError as e:
        return _err(str(e))
    try:
        union = build_union(consumer, res.projects(), res.labels)
    except ComposeError as e:
        return _err(str(e))

    project = union.project
    start = _union_uid(union, uid)
    if project.get(start) is None:
        return _err(f"{uid} does not exist")

    local_uids = {it.uid for it in consumer.items()}
    types = set(args.link_type) if args.link_type else None
    view = Index.build(project).subgraph(start, types, args.depth or 0,
                                         expand=lambda u: u in local_uids)
    if args.format == "json":
        import json
        print(json.dumps(_subgraph_json(project, view, union.qualified), indent=2))
    else:
        render_subgraph(project, view, uid_display=union.qualified)
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

    # Several items in one run, as core takes from 3.3.0 (throughline SR-0199,
    # this SR-0046); the picker still offers one when none is named.
    uids = list(args.uids)
    if not uids:
        uid = _resolve_uid(consumer, None, "ratify", "UID")
        if uid is None:
            return USAGE
        uids = [uid]
    for uid in uids:
        if consumer.get(uid) is None:  # fail before resolving sources over the network
            return _err(f"{uid} does not exist"
                        + (" — nothing in this run was ratified" if len(uids) > 1 else ""))
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
        union = build_union(consumer, res.projects(), res.labels)
    except ComposeError as e:
        return _err(str(e))

    # The union is built once for the run; every item is judged against the same
    # graph (SR-0046). The gate is asked for all of them before any is written, so a
    # run that cannot complete writes nothing — the property core gives a batch.
    index = Index.build(union.project)
    for uid in uids:
        obstacle = ratification_obstacle(consumer.schema, index, consumer.get(uid),
                                         replacing=getattr(args, "replacing", False))
        if obstacle is not None:
            return _err(obstacle + (" — nothing in this run was ratified" if len(uids) > 1 else ""))
    for uid in uids:
        try:
            # `by_id` travels with the name for the same reason the union does: core
            # owns what a ratification record contains (SR-0004), and a composed
            # sign-off that quietly dropped the identifier would be a weaker record
            # than the identical bare-`tl` one.
            # `replacing` travels too (core SR-0196): correcting an unpublished
            # ratifier is a mode of ratify, and a composed path that accepted the
            # flag and dropped it would refuse the correction with core's
            # "nothing to accept" while bare `tl` performed it (SR-0003).
            item = ratify(consumer, uid, by, index=index,
                          by_id=getattr(args, "by_id", None),
                          replacing=getattr(args, "replacing", False))
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
        union = build_union(consumer, res.projects(), res.labels)
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
        union = build_union(consumer, res.projects(), res.labels)
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
        union = build_union(consumer, res.projects(), res.labels)
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

    # The birth is core's, not a copy of it (SR-0047, throughline SR-0205): the
    # proposed status for a machine origin, the author's attributes, the schema's
    # defaults and the type's normative flag all come from the one function
    # `tl new` itself uses. Only the cross-source grounding below is ours.
    try:
        attrs = _parse_attrs(consumer.schema, args.type, args.attr, command="new")
    except UidError as e:
        return _err(str(e))
    item = birth_item(consumer.schema, reg, uid, item_type=args.type,
                      title=args.title or "", text=args.text or "",
                      status=args.status, origin=args.origin, attrs=attrs)

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

## Transitive sources — composing a source composes what it composes (SR-0045, SR-0015)

Every namespace a declared source declares — and every one *those* declare, to any
depth — is bound into your union under the label its declaring source gave it, at
the pin that source set. You declare only the sources you cite directly and choose
their labels; the rest arrive on their own, each edition inherited and never
restated. The check summary and the listing below name every bound namespace with
the path that carried it in (`regulation … via house › platform`), so the toml says
what you chose and the tool says what that composes.

Your one lever over a transitive label is `alias`, on the declared source that
carries it:

```toml
[[sources]]
namespace = "house"
url = "..."
ref = "v2026-07"
alias = { asvs = "asvs-v4" }       # house's `asvs`, and any `asvs` beneath it, binds as `asvs-v4`
```

An alias applies throughout that source's subtree. A source's own references always
resolve through its own declarations (renamed by your alias), never against a label
you happen to reuse — so a source that calls its dependency `platform` cannot be
captured by an unrelated `platform` you declared. Your own items may cite any bound
namespace, transitive or direct, by its bound label; a reference to a namespace
nothing binds fails, naming the item that carries it and listing what is bound.

Two labels reaching the union at **one edition** bind once, under the first label
bound, and the summary says which was folded into which. One label reaching the
union at **two different editions** — declared at one ref and carried in at another,
or two sources pinning the same standard differently — is refused: `tl-compose`
names both editions and the path each came by, and states the fix (pin it yourself
to the one edition you intend, or set an `alias` on the declared source carrying one
of them so both compose side by side). The old `reexport` key is refused in your own
toml and ignored, with a note, inside a source's.

@@UNION_COMMANDS@@

## The source cache — a moved ref **is** picked up

A `url` + `ref` source is fetched into a per-user cache keyed by that exact
`(url, ref)` pair, then reused rather than cloned again. Reuse is checked, never
assumed, because a pin is not the same thing as an immutable edition:

> **A commit id** names one commit for all time, so its checkout is reused with no
> network access at all.
>
> **A tag or a branch** is a name the origin can move, so `tl-compose` asks the
> origin what it points at now and refetches only when it has moved. An unmoved ref
> costs one ref advertisement and no download.

So moving a tag *is* picked up, on the next run, and you never need to clear the
cache to see changed content behind a ref you have already used. A ref the origin
resolves ambiguously is an error rather than a guess.

`TL_COMPOSE_OFFLINE=1` composes from the cache without contacting any origin, for a
genuinely disconnected machine; a source missing from the cache is then an error
rather than a fetch. Without it, an origin that cannot be reached fails the run — it
never falls back silently to whatever happens to be cached, because a check that
cannot see the content it is gating is not a gate. This project's cache lives at:

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


def _bound_line(res: _Resolution, ns: str) -> str:
    """One human-readable bullet describing a bound namespace for the live listing:
    its pin, and the path that carried it in or the alias set on it (SR-0016)."""
    s = res.coordinates[ns]
    where = f"`{s.url}` @ `{s.ref}`" if s.is_remote else f"path `{s.path}`"
    if s.subdir:
        where += f" (subdir `{s.subdir}`)"
    via = res.via[ns]
    if via:
        carried = " · via " + " › ".join(f"`{v}`" for v in via)
    else:
        carried = " · declared by you"
        if s.alias:
            parts = ", ".join(f"`{k}` → `{v}`" for k, v in sorted(s.alias.items()))
            carried += f" · alias {parts}"
    return f"- **`{ns}`** — {where}{carried}"


def _ctx_bound(res: _Resolution) -> str:
    """The live 'namespaces bound in this union' section — the composition analogue
    of the core brief's live graph snapshot (SR-0016, SR-0045): every namespace the
    union binds, the sources this project declares and every transitive source those
    carry, each with its pin and the path that carried it, so the brief describes
    the composition the agent is really working in."""
    lines = ["## Namespaces bound in this union\n"]
    lines.extend(_bound_line(res, ns) for ns in res.resolved)
    if res.notices:
        lines.append("")
        lines.extend(f"- _{note}_" for note in res.notices)
    return "\n".join(lines)


def _compose_context(args) -> int:
    """Emit the core `tl context` brief verbatim, then append the composition section
    and the live listing of every namespace this project's union binds (SR-0016).
    The core brief is captured from the unchanged core command so the superset holds
    byte-for-byte; only when the project declares sources is the full composition
    manual appended — with none declared the brief stays the core's plus a short
    'composition available but unused' note, keeping the strict-superset promise
    (SR-0003). The listing is read from the resolved closure, not the config, since
    what the config declares is no longer the whole of what the union binds
    (SR-0045); a source that will not resolve fails the brief rather than leaving
    it to describe a composition that does not exist.

    Given a UID, the item section is computed over the *union* (SR-0042). Left to
    core it would be computed over the bare local graph, printing every borrowed
    clause as ``(unresolved)`` and then asserting, a few lines below, that
    composition resolves them — a false clean result in the one document an agent
    is told to trust (SR-0005).
    """
    import contextlib
    import io

    try:
        consumer = load_project(args.path)
        sources = parse_sources(consumer)
    except (ProjectError, SourceError):
        consumer, sources = None, []

    uid = getattr(args, "uid", None)
    res = None
    if sources:
        try:
            res = _resolve_sources(sources, Path(args.path))
        except ResolverError as e:
            return _err(str(e))
    # Core renders the brief; when there is a union to answer over, the item section
    # is rendered here instead, so core is never handed a UID it would answer locally.
    composed_section = None
    if sources and uid is not None:
        try:
            union = build_union(consumer, res.projects(), res.labels)
        except ComposeError as e:
            return _err(str(e))
        start = _union_uid(union, uid)
        if union.project.get(start) is None:
            return _err(f"{uid} does not exist")
        local_uids = {it.uid for it in consumer.items()}
        view = Index.build(union.project).subgraph(
            start, expand=lambda u: u in local_uids)
        composed_section = context_item_section(
            union.project, view, uid_display=union.qualified)
        args.uid = None

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_context(args)
    sys.stdout.write(buf.getvalue())
    if rc != OK:
        return rc
    if composed_section is not None:
        sys.stdout.write("\n" + composed_section)

    if not sources:
        sys.stdout.write(
            "\n---\n\n"
            "# Composition (`tl-compose`)\n\n"
            "This project declares no `[[sources]]`, so `tl-compose` behaves exactly "
            "as `tl` here — everything above is the whole brief. Composition "
            "(`[[sources]]`, the transitive sources they carry, and union-aware "
            + "/".join(f"`{n}`" for n in sorted(_UNION_COMMANDS))
            + ") becomes available the moment you add a source; run "
            "`tl-compose agentinfo` again then for the full composition brief.\n")
    else:
        sys.stdout.write("\n" + _compose_brief() + "\n"
                         + _ctx_bound(res) + "\n")
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
    "dump": (
        _compose_dump,
        "exports the composed graph, so every link in the document resolves inside "
        "it; borrowed items read as `<namespace>:<UID>` and carry their owning "
        "source as a field, and a `composition` block states the scope — which "
        "sources at which pin, and how many items are your own. `--local` narrows "
        "the export to your own items and records that it did."),
    "docs": (
        _compose_docs,
        "a `tl:matrix` target cell pointing at a borrowed clause renders that "
        "clause's own reference number."),
    "trace": (
        _compose_trace,
        "a link into a borrowed clause is followed *into* the source (with its own "
        "type, status and title) instead of dead-ending at `(unresolved)`."),
    "subgraph": (
        _compose_subgraph,
        "an item's neighbourhood — both directions plus the links between its "
        "members — is built over the union, so cross-source edges are part of the "
        "answer. Naming a borrowed clause tells you which of *your* items adopt "
        "it; the walk then stops at the source boundary, as `trace` does."),
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
        "emits the core brief unchanged, then this composition section and the "
        "live listing of every namespace your union binds, with the path that "
        "carried each in. `agentinfo` is an alias for it."),
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
    # The same flag on `dump`, for the same reason and by the same route (SR-0040):
    # an export restricted to the consumer's own items, which says in the document
    # that it was restricted.
    sub.choices["dump"].add_argument(
        "--local", action="store_true",
        help="export only this project's own items, not the ones it borrows")
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
