# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""End-to-end CLI tests over materialised fixtures: the two-tool contract
(SR-0003, SR-0005) — bare `tl` fails fast, `tl-compose` resolves and passes."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import throughline_compose
from throughline.cli import main as tl_main
from throughline.storage import load_project
from throughline_compose.cli import main as tlc_main
from throughline_compose.seam import apply_seam


def test_version_reports_compose_not_core(capsys):
    # `--version` must speak as tl-compose, not forward throughline's `tl X` string.
    with pytest.raises(SystemExit) as exc:
        tlc_main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("tl-compose ")
    assert "throughline " in out  # names the core it composes over


def test_both_reported_versions_mark_a_working_tree(capsys, monkeypatch):
    """A composed run is judged by core's validator, so the pair is what someone is
    trying to establish when they ask. A mismatched pair is invisible while each half
    reports a clean release number it has departed from (SR-0027), so the marker has
    to reach the core version too — not just tl-compose's own."""
    from throughline import version as version_mod

    monkeypatch.setattr(version_mod, "_editable_from_direct_url", lambda _d: True)
    with pytest.raises(SystemExit):
        tlc_main(["--version"])

    out = capsys.readouterr().out
    # Both packages named in the line, both marked — the rule is applied to each.
    assert out.count("+editable") == 2, out


def test_the_version_rule_is_cores_and_is_not_restated_here():
    """The rule lived in three places — library, CLI, and again here. SR-0027 mirrors
    SR-0164's objection to that, so this consumes core's helper rather than keeping a
    fourth copy that can drift on its own."""
    import inspect

    from throughline.version import distribution_version
    from throughline_compose import cli

    assert cli.distribution_version is distribution_version
    # No local re-implementation reading distribution metadata behind our back.
    assert "PackageNotFoundError" not in inspect.getsource(cli)


def test_bare_tl_check_fails_fast_on_qualified_reference(consumer_dir, capsys):
    # The core cannot resolve `toy:SR-0001`; it must signpost tl-compose (SR-0005).
    rc = tl_main(["-C", str(consumer_dir), "check", "--base", ""])
    assert rc == 1
    assert "namespace-unresolved" in capsys.readouterr().out


def test_compose_check_resolves_and_passes(consumer_dir, capsys):
    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", ""])
    assert rc == 0
    assert "composed graph is sound" in capsys.readouterr().err


def test_compose_check_prints_union_summary_split_local_borrowed(consumer_dir, capsys):
    # SR-0022: the composed check prints core's graph summary computed over the
    # union (2 consumer items + 3 borrowed toy items = 5), then a Local line that
    # splits the consumer's own items from the borrowed ones.
    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", ""])
    assert rc == 0
    err = capsys.readouterr().err
    assert "tl check ·" in err            # the same header core prints
    assert "Items      5 live" in err     # union totals
    assert "Grounding  " in err           # full core summary, not just a tally
    assert "Local      2 of 5 local" in err
    assert "3 borrowed" in err


def test_grounding_figure_counts_only_what_the_consumer_can_act_on(
    lean_consumer_dir, capsys
):
    """SR-0029: the grounding headline is scoped to the consumer's own items.

    The lean consumer does not adopt `implements` as a grounding link, so the toy
    source's SR — which grounds through it — reaches no root under this schema.
    Counted over the union that reads as 2 of 3; counted over what the consumer can
    actually link, it is 1 of 1. The union figure would print a shortfall directly
    above a verdict of zero errors, with no act available to close it.
    """
    rc = tlc_main(["-C", str(lean_consumer_dir), "check", "--base", ""])
    assert rc == 0
    err = capsys.readouterr().err

    assert "Grounding  1/1 local non-root items trace to a root" in err
    assert "1/1 local delivery roots served" in err
    # The union figure is the one this requirement exists to stop printing.
    assert "2/3" not in err
    # The line says what it counts, so its scope is not inferred from its size.
    assert "local non-root items" in err
    # Union totals stay: a composer still sees the size of what was validated.
    assert "Items      5 live" in err
    assert "Local      2 of 5 local" in err
    assert "3 borrowed" in err


def test_the_borrowed_orphan_is_real_but_not_the_consumers_to_answer(
    lean_consumer_dir, capsys
):
    """The premise of the test above: the borrowed item genuinely does not reach a
    root under the consumer's schema, and the seam is what keeps it out of the
    report (SR-0026). Without this, a scoped headline of 1/1 could be passing for
    the trivial reason that nothing was ungrounded in the first place."""
    from throughline.graph import Index
    from throughline.validate import validate
    from throughline_compose.cli import _resolve_sources
    from throughline_compose.sources import parse_sources
    from throughline_compose.union import build_union

    consumer = load_project(str(lean_consumer_dir))
    res = _resolve_sources(parse_sources(consumer), Path(lean_consumer_dir))
    union = build_union(consumer, res.projects(), res.ns_aliases)

    raw = validate(union.project, strict=False)
    assert any(f.rule == "orphan" for f in raw), (
        "expected core to report the borrowed item as an orphan under this schema"
    )
    kept, suppressed, _rescued = apply_seam(
        raw, union, union.project.schema, Index.build(union.project)
    )
    assert any(f.rule == "orphan" for f in suppressed)
    assert not any(f.rule == "orphan" for f in kept)


def test_core_still_labels_the_grounding_line(source_dir):
    """The rescope finds core's grounding line by its label rather than its
    position. If core ever renames or reformats it, that must fail here — loudly,
    at build time — rather than degrade a user's report quietly at runtime."""
    from throughline.cli import _check_summary
    from throughline_compose.cli import _GROUNDING_LABEL

    lines = _check_summary(load_project(str(source_dir)))
    labelled = [ln for ln in lines if ln.startswith(_GROUNDING_LABEL)]
    assert len(labelled) == 1, (
        f"core's summary no longer has exactly one {_GROUNDING_LABEL!r} line: {lines}"
    )


def test_compose_check_quiet_suppresses_summary(consumer_dir, capsys):
    # SR-0022: the summary obeys the existing quiet flag, exactly as core does.
    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", "", "--quiet"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "tl check ·" not in err
    assert "Local " not in err


def test_compose_check_json_output_has_no_summary(consumer_dir, capsys):
    # SR-0022: the machine-readable json output is unaffected by the summary.
    import json
    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", "", "--format", "json"])
    assert rc == 0
    cap = capsys.readouterr()
    assert "Local " not in cap.out and "tl check ·" not in cap.err
    assert isinstance(json.loads(cap.out), list)  # stdout is the findings array


def test_compose_check_passthrough_without_sources(source_dir):
    # A source project has no [[sources]] — tl-compose check must behave like tl.
    rc = tlc_main(["-C", str(source_dir), "check", "--base", ""])
    assert rc == 0


def test_compose_check_resolves_url_source(consumer_dir, source_dir, tmp_path,
                                           monkeypatch, capsys):
    # Same composition, but the source is pinned by url+ref (SR-0006): tag the toy
    # source as a git origin, point the consumer at it by url, and compose.
    monkeypatch.setenv("TL_COMPOSE_CACHE", str(tmp_path / "cache"))

    def git(*a):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
                       cwd=str(source_dir), check=True, capture_output=True)
    git("init", "-b", "main"); git("add", "."); git("commit", "-m", "edition")
    git("tag", "v4.0.3")

    toml = consumer_dir / "throughline.toml"
    toml.write_text(toml.read_text().replace(
        'path = "../toy-source"', f'url = "{source_dir}"\nref = "v4.0.3"'))

    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", ""])
    assert rc == 0
    assert "composed graph is sound" in capsys.readouterr().err


def test_compose_check_translates_dangling_cross_source(consumer_dir, capsys):
    sr = consumer_dir / "system-requirements" / "SR-0001.yml"
    sr.write_text(sr.read_text().replace("toy:SR-0001", "toy:SR-9999"))
    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", ""])
    assert rc == 1
    out = capsys.readouterr().out
    assert "toy:SR-9999" in out       # the composer's own vocabulary
    assert "TOYSR-9999" not in out    # never the mangled internal form


def test_compose_trace_resolves_cross_source(consumer_dir, capsys):
    # SR-0010: the consumer's SR-0001 relates to toy:SR-0001. Bare `tl trace` sees
    # only local items and dead-ends that edge at (unresolved); tl-compose walks the
    # union, so the borrowed clause resolves into its source and reads in namespace
    # vocabulary — never the mangled internal form, never (unresolved).
    rc = tlc_main(["-C", str(consumer_dir), "trace", "SR-0001"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "(relates) toy:SR-0001" in out
    assert "A normative clause the source offers" in out  # borrowed clause's own title
    assert "(unresolved)" not in out
    assert "TOYSR-0001" not in out  # never the mangled internal UID


def test_compose_trace_starts_from_qualified_uid(consumer_dir, capsys):
    # SR-0010: the composer may trace starting from a borrowed clause itself.
    rc = tlc_main(["-C", str(consumer_dir), "trace", "toy:SR-0001"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("toy:SR-0001  [system_requirement/approved]")
    assert "TOYSR-0001" not in out


def test_compose_trace_dangling_cross_source_stays_unresolved(consumer_dir, capsys):
    # SR-0010: a namespace-qualified target with no clause at the pinned edition is
    # still (unresolved) — but in the composer's own vocabulary, never mangled.
    sr = consumer_dir / "system-requirements" / "SR-0001.yml"
    sr.write_text(sr.read_text().replace("toy:SR-0001", "toy:SR-9999"))
    rc = tlc_main(["-C", str(consumer_dir), "trace", "SR-0001"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "toy:SR-9999 (unresolved)" in out
    assert "TOYSR-9999" not in out


def test_compose_trace_passthrough_without_sources(source_dir, capsys):
    # A source project declares no [[sources]]: tl-compose trace must behave like
    # bare tl trace over the local graph.
    rc = tlc_main(["-C", str(source_dir), "trace", "SR-0001"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("SR-0001  [system_requirement/approved]")
    assert "(implements) UR-0001" in out


def test_compose_docs_renders_borrowed_target_attribute(consumer_dir):
    # SR-0007/SR-0110: a matrix cell whose target is a namespace-qualified borrowed
    # clause renders that clause's own attribute, resolved through the union — not a
    # UID the reader cannot look up. The toy source's SR-0001 carries priority: must.
    spec = consumer_dir / "spec.md"
    spec.write_text(
        "<!-- tl:matrix outgoing:relates@uid(priority) uid == 'SR-0001' -->\n"
        "<!-- tl:end -->\n", encoding="utf-8")
    rc = tlc_main(["-C", str(consumer_dir), "docs", str(spec)])
    assert rc == 0
    out = spec.read_text(encoding="utf-8")
    assert "toy:SR-0001 (must)" in out


def test_compose_docs_default_target_is_qualified_uid(consumer_dir):
    # With no @ suffix the cell is the namespace-qualified UID, exactly as core.
    spec = consumer_dir / "spec.md"
    spec.write_text(
        "<!-- tl:matrix outgoing:relates uid == 'SR-0001' -->\n"
        "<!-- tl:end -->\n", encoding="utf-8")
    rc = tlc_main(["-C", str(consumer_dir), "docs", str(spec)])
    assert rc == 0
    assert "toy:SR-0001" in spec.read_text(encoding="utf-8")


def test_compose_docs_passthrough_without_sources(source_dir):
    # A source project declares no [[sources]]: tl-compose docs must behave like tl
    # docs — inject over the local graph with no resolver.
    spec = source_dir / "spec.md"
    spec.write_text("<!-- tl:item INT-0001 -->\n<!-- tl:end -->\n", encoding="utf-8")
    rc = tlc_main(["-C", str(source_dir), "docs", str(spec)])
    assert rc == 0
    assert "Toy source purpose" in spec.read_text(encoding="utf-8")


def test_compose_docs_item_block_shows_borrowed_link_reference(consumer_dir):
    # SR-0113: an item block lists its outgoing links resolver-enriched. The
    # consumer's SR-0001 relates to toy:SR-0001, whose source_ref is V1.1.1, so the
    # block shows the reference number a reader could not derive from a UID alone.
    spec = consumer_dir / "spec.md"
    spec.write_text("<!-- tl:item SR-0001 -->\n<!-- tl:end -->\n", encoding="utf-8")
    rc = tlc_main(["-C", str(consumer_dir), "docs", str(spec)])
    assert rc == 0
    out = spec.read_text(encoding="utf-8")
    assert "*Relates:* toy:SR-0001 (V1.1.1)" in out
    assert "*Derives from:* INT-0001" in out


def test_compose_docs_sourced_mirrors_borrowed_clause(consumer_dir):
    # SR-0039: tl:sourced mirrors, in full, the external clause the consumer's items
    # reference — toy:SR-0001's own block, drawn from its source.
    ref = consumer_dir / "reference.md"
    ref.write_text(
        "<!-- tl:sourced uid == 'SR-0001' -->\n<!-- tl:end -->\n", encoding="utf-8")
    rc = tlc_main(["-C", str(consumer_dir), "docs", str(ref)])
    assert rc == 0
    out = ref.read_text(encoding="utf-8")
    assert "A normative clause the source offers" in out
    assert "The source shall provide one concrete, testable clause." in out


def test_compose_docs_sourced_states_qualified_identity(consumer_dir):
    """SR-0039: the mirrored clause is stated under the identity the citing document
    uses for it — namespace-qualified, with its reference number — never under the
    source's own local UID, which the consumer's unrelated SR-0001 also carries."""
    ref = consumer_dir / "reference.md"
    ref.write_text(
        "<!-- tl:sourced uid == 'SR-0001' -->\n<!-- tl:end -->\n", encoding="utf-8")
    assert tlc_main(["-C", str(consumer_dir), "docs", str(ref)]) == 0
    out = ref.read_text(encoding="utf-8")
    assert "**toy:SR-0001 (V1.1.1) — A normative clause the source offers**" in out
    # The defect this fixes: the borrowed clause published under a bare SR-0001, the
    # same heading the consumer's own unrelated SR-0001 renders under.
    assert "**SR-0001 — A normative clause the source offers**" not in out


def test_compose_docs_sourced_qualifies_the_mirrored_clauses_links(consumer_dir):
    """SR-0039: a mirrored clause's own outgoing links render namespace-qualified, so
    a target internal to the source is never shown as though it named a consumer
    item."""
    ref = consumer_dir / "reference.md"
    ref.write_text(
        "<!-- tl:sourced uid == 'SR-0001' -->\n<!-- tl:end -->\n", encoding="utf-8")
    assert tlc_main(["-C", str(consumer_dir), "docs", str(ref)]) == 0
    out = ref.read_text(encoding="utf-8")
    body = out.split("A normative clause the source offers", 1)[1]
    for line in body.splitlines():
        if line.startswith("*") and ":*" in line and "Rationale" not in line:
            for target in line.split(":*", 1)[1].split(","):
                target = target.strip()
                if target:
                    assert target.startswith("toy:"), f"unqualified target: {line}"


def test_compose_docs_sourced_placeholder_when_nothing_is_referenced(source_dir):
    # SR-0039: the selected items reference no external clause, so there is nothing
    # to mirror and a clear placeholder is rendered rather than an error.
    ref = source_dir / "reference.md"
    ref.write_text(
        "<!-- tl:sourced uid == 'SR-0001' -->\n<!-- tl:end -->\n", encoding="utf-8")
    rc = tlc_main(["-C", str(source_dir), "docs", str(ref)])
    assert rc == 0
    assert "reference no external clause" in ref.read_text(encoding="utf-8")


def test_bare_tl_docs_refuses_a_composed_document(consumer_dir):
    """SR-0039/throughline SR-0186: running bare `tl docs` over an already-rendered
    composed document fails and overwrites nothing, instead of silently replacing the
    mirrored clauses with a placeholder and exiting 0.

    In this process throughline_compose is imported, so the directive is registered
    and the failure is the missing sources; a real `tl` process has no registration
    and reports the directive as unprovided (covered by throughline's own suite).
    Both paths must leave the document untouched, which is what this asserts."""
    from throughline.cli import main as tl_main
    ref = consumer_dir / "reference.md"
    ref.write_text(
        "<!-- tl:sourced uid == 'SR-0001' -->\n<!-- tl:end -->\n", encoding="utf-8")
    assert tlc_main(["-C", str(consumer_dir), "docs", str(ref)]) == 0
    rendered = ref.read_text(encoding="utf-8")
    assert "A normative clause the source offers" in rendered

    assert tl_main(["-C", str(consumer_dir), "docs", str(ref)]) == 2
    assert ref.read_text(encoding="utf-8") == rendered  # nothing was overwritten


def test_compose_docs_sourced_fails_on_an_unmirrorable_reference(consumer_dir):
    """SR-0039: a referenced clause that cannot be rendered from its declared source
    fails injection rather than being quietly dropped."""
    from throughline_compose.directives import render_sourced
    from throughline.inject import InjectError

    class _NoSources:
        def mirror_block(self, uid):
            return None

    class _Item:
        uid = "SR-0001"
        is_deleted = False
        links = [type("L", (), {"target": "toy:SR-9999", "type": "relates"})()]

    class _Proj:
        def items(self):
            return [_Item()]

    import throughline_compose.directives as d
    real = d.matching
    d.matching = lambda project, expr: [_Item()]
    try:
        with pytest.raises(InjectError) as ei:
            render_sourced(_Proj(), "uid == 'SR-0001'", _NoSources())
        assert "toy:SR-9999" in str(ei.value)
    finally:
        d.matching = real


def _write_sr(consumer_dir: Path, uid: str, links: list[tuple[str, str]]) -> Path:
    """Materialise a consumer system_requirement with the given grounding links,
    used to exercise the ratify gate over composition."""
    body = (f"uid: {uid}\ntype: system_requirement\nstatus: proposed\n"
            f"title: {uid} fixture clause\n"
            f"text: A consumer clause used to exercise the ratify gate.\n")
    if links:
        body += "links:\n" + "".join(
            f"- target: {t}\n  type: {k}\n" for t, k in links)
    body += "attrs:\n  priority: must\n  origin: human\n"
    p = consumer_dir / "system-requirements" / f"{uid}.yml"
    p.write_text(body, encoding="utf-8")
    return p


def test_source_ratification_is_not_stale_just_because_we_relabelled_it(
        source_dir, consumer_dir, capsys):
    # SR-0024: the source's own graph signs SR-0001 and stamps the fingerprint of
    # the item as *it* holds it. Composition mangles that UID to keep identity
    # unique in the union, and the UID is the first field the fingerprint covers —
    # so before this fix every signature in every source read as drifted in every
    # consumer of it, on content nobody had touched.
    assert tl_main(["-C", str(source_dir), "ratify", "SR-0001", "--by", "tester"]) == 0
    capsys.readouterr()
    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", "", "--strict"])
    assert "ratified-stale" not in capsys.readouterr().out
    assert rc == 0


def test_drift_in_a_source_is_still_reported_through_composition(
        source_dir, consumer_dir, capsys):
    # The seam excuses the label and nothing else: rewrite the signed text in the
    # source and the consumer must still be told the accepted wording has moved.
    assert tl_main(["-C", str(source_dir), "ratify", "SR-0001", "--by", "tester"]) == 0
    capsys.readouterr()
    clause = source_dir / "system-requirements" / "SR-0001.yml"
    clause.write_text(
        clause.read_text(encoding="utf-8")
        .replace("The source shall provide one concrete, testable clause.",
                 "The source shall provide something else entirely."),
        encoding="utf-8")
    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", "", "--strict"])
    out = capsys.readouterr().out
    assert rc == 1
    # ...and named in the composer's own vocabulary, not the synthetic prefix.
    assert "toy:SR-0001" in out and "ratified-stale" in out


def test_bare_tl_ratify_refuses_cross_source_grounded_item(consumer_dir, capsys):
    # Grounded only through the source: bare `tl` sees toy:INT-0001 as unresolved and
    # refuses to ratify what is, under composition, a properly grounded item (SR-0005).
    _write_sr(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    rc = tl_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "tester"])
    assert rc == 2
    assert "not grounded to a root" in capsys.readouterr().err


def test_compose_ratify_resolves_cross_source_grounding(consumer_dir, capsys):
    # The fix (SR-0004): tl-compose runs the accountability gate over the union, where
    # the grounding chain into the source resolves, then persists the accepted status
    # to the consumer's own file — never the read-only source (NG-0002).
    p = _write_sr(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    rc = tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "tester"])
    assert rc == 0
    assert "SR-0002 ratified by tester" in capsys.readouterr().out
    text = p.read_text(encoding="utf-8")
    assert "status: ratified" in text
    assert "ratified_by: tester" in text


def test_compose_ratify_binds_the_signature_to_the_content(consumer_dir, capsys):
    # SR-0004: core `grounding.ratify` writes the whole record, so a composed
    # sign-off carries the content fingerprint that binds it (core SR-0148) — the
    # thing the hand-rolled copy this replaced never wrote. Proof it is the real
    # stamp and not a plausible string: the validator recomputes it and is silent.
    p = _write_sr(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    assert tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "tester"]) == 0
    capsys.readouterr()
    assert "ratified_fingerprint:" in p.read_text(encoding="utf-8")
    assert tlc_main(["-C", str(consumer_dir), "check", "--base", "", "--strict"]) == 0
    assert "ratified-stale" not in capsys.readouterr().out


def test_compose_ratify_reads_the_configured_ratified_status(consumer_dir, capsys):
    # The copy hardcoded `item.status = "ratified"`, which happens to be right only
    # while a project names that status "ratified". Core resolves the *role* against
    # the project's own [status.roles], so a graph that calls it something else is
    # ratified into its own vocabulary, not ours.
    cfg = consumer_dir / "throughline.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8")
                   .replace('"ratified", "rejected"', '"accepted", "rejected"')
                   .replace('ratified = "ratified"', 'ratified = "accepted"'),
                   encoding="utf-8")
    p = _write_sr(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    assert tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "tester"]) == 0
    text = p.read_text(encoding="utf-8")
    assert "status: accepted" in text
    assert "status: ratified" not in text


def test_compose_ratify_refuses_to_resign_unchanged_item(consumer_dir, capsys):
    # Core refuses a second signature on content that has not moved (SR-0148):
    # it would accept nothing while quietly replacing the name of whoever did.
    # The copy had no such guard, so it overwrote the ratifier without trace.
    p = _write_sr(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    assert tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "alice"]) == 0
    capsys.readouterr()
    rc = tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "mallory"])
    assert rc == 2
    assert "nothing to accept" in capsys.readouterr().err
    text = p.read_text(encoding="utf-8")
    assert "ratified_by: alice" in text        # the real signatory survives
    assert "mallory" not in text


def test_compose_ratify_restamps_once_the_content_moves(consumer_dir, capsys):
    # The counterpart: when the words change, the old signature no longer covers
    # them, so re-ratifying is exactly what should happen — and rebinds the stamp.
    p = _write_sr(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    assert tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "alice"]) == 0
    first = [ln for ln in p.read_text(encoding="utf-8").splitlines()
             if "ratified_fingerprint:" in ln][0]
    p.write_text(p.read_text(encoding="utf-8").replace(
        "A consumer clause used to exercise the ratify gate.",
        "The consumer shall do something materially different."), encoding="utf-8")
    capsys.readouterr()
    assert tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "bob"]) == 0
    text = p.read_text(encoding="utf-8")
    assert "ratified_by: bob" in text
    assert first not in text                   # bound to the new wording, not the old


def test_compose_ratify_refuses_ambiguous_item(consumer_dir, capsys):
    # The other half of core's gate, reached through the composed path: an item
    # flagged ambiguous is not signable however well it grounds over the union.
    p = _write_sr(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    p.write_text(p.read_text(encoding="utf-8") + "  ambiguous: true\n", encoding="utf-8")
    rc = tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "tester"])
    assert rc == 2
    assert "ambiguous" in capsys.readouterr().err


def test_compose_ratify_still_refuses_ungrounded_item(consumer_dir, capsys):
    # The gate is preserved, only relocated to the union: an item that reaches no root
    # anywhere is still refused — composition widens what counts as grounded, it does
    # not weaken the accountability rule.
    _write_sr(consumer_dir, "SR-0002", [])
    rc = tlc_main(["-C", str(consumer_dir), "ratify", "SR-0002", "--by", "tester"])
    assert rc == 2
    assert "not grounded to a root" in capsys.readouterr().err


def test_compose_ratify_passthrough_without_sources(source_dir, capsys):
    # No [[sources]]: tl-compose ratify behaves exactly like core tl ratify over the
    # local graph (SR-0003). The toy source's UR-0001 grounds locally (derives INT).
    rc = tlc_main(["-C", str(source_dir), "ratify", "UR-0001", "--by", "tester"])
    assert rc == 0
    assert "UR-0001 ratified by tester" in capsys.readouterr().out


# ---- migrate: unbound records judged over the union (SR-0003, SR-0004) --------

def _unbound_record(consumer_dir: Path, uid: str, links: list[tuple[str, str]],
                    by: str = "tester", **attrs) -> Path:
    """A consumer item in the shape a graph ratified before the fingerprint existed
    carries on disk: a ratified status and a named ratifier, but no stamp binding
    that name to what was signed."""
    p = _write_sr(consumer_dir, uid, links)
    body = p.read_text(encoding="utf-8").replace(
        "status: proposed", "status: ratified")
    body += f"  ratified_by: {by}\n"
    body += "".join(f"  {k}: {v}\n" for k, v in attrs.items())
    p.write_text(body, encoding="utf-8")
    return p


def test_bare_tl_migrate_declines_a_record_grounded_through_a_source(consumer_dir):
    # Grounded only through the source, so bare `tl` sees toy:INT-0001 as unresolved
    # and the item as orphaned. Declining to complete its record is core working, not
    # failing — it must not bind what it cannot justify (throughline SR-0152).
    p = _unbound_record(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    assert tl_main(["-C", str(consumer_dir), "migrate"]) == 0
    assert "ratified_fingerprint" not in p.read_text(encoding="utf-8")


def test_compose_migrate_binds_a_record_grounded_through_a_source(consumer_dir, capsys):
    # The fix (SR-0004): tl-compose hands the union to the *unchanged* core repair
    # (throughline SR-0153), which completes the very record it declined without one.
    p = _unbound_record(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    assert tlc_main(["-C", str(consumer_dir), "migrate"]) == 0

    out = capsys.readouterr().out
    assert "grounded through a composed source" in out
    assert "SR-0002 = sha256:" in out
    text = p.read_text(encoding="utf-8")
    assert "ratified_fingerprint: sha256:" in text
    assert "ratified_backfilled: true" in text
    assert "ratified_by: tester" in text          # reused verbatim, never reattributed


def test_compose_migrate_still_declines_what_core_would_refuse(consumer_dir, capsys):
    # Composition widens what counts as grounded; it does not weaken the rule. An
    # ambiguous item is refused on the same predicate, union or no union.
    p = _unbound_record(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")],
                        ambiguous="true")
    assert tlc_main(["-C", str(consumer_dir), "migrate"]) == 0
    assert "ratified_fingerprint" not in p.read_text(encoding="utf-8")
    assert "grounded through a composed source" not in capsys.readouterr().out


def test_compose_migrate_is_idempotent(consumer_dir, capsys):
    # Both passes are idempotent by requirement (throughline SR-0137), so a second
    # run neither restamps nor re-reports — it cannot bless content that drifted
    # after sign-off.
    p = _unbound_record(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    tlc_main(["-C", str(consumer_dir), "migrate"])
    first = p.read_text(encoding="utf-8")
    capsys.readouterr()

    assert tlc_main(["-C", str(consumer_dir), "migrate"]) == 0
    assert "grounded through a composed source" not in capsys.readouterr().out
    assert p.read_text(encoding="utf-8") == first


def test_compose_migrate_upgrades_before_it_can_consult_the_union(consumer_dir, capsys):
    # The order is forced, not chosen: a project below the current major cannot be
    # loaded, so its [[sources]] cannot be read and no union exists until the upgrade
    # has run. One command still does both — core upgrades and binds what it can,
    # then the union pass completes what only composition can justify.
    p = _unbound_record(consumer_dir, "SR-0002", [("toy:INT-0001", "derives_from")])
    cfg = consumer_dir / "throughline.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(
        "format_version = 3", "format_version = 2"), encoding="utf-8")

    assert tlc_main(["-C", str(consumer_dir), "migrate"]) == 0
    out = capsys.readouterr().out
    assert "migrated project from format version 2 to 3" in out
    assert "grounded through a composed source" in out
    assert "ratified_fingerprint: sha256:" in p.read_text(encoding="utf-8")


def test_compose_migrate_passthrough_without_sources(source_dir, capsys):
    # No [[sources]]: tl-compose migrate behaves exactly like core tl migrate over
    # the local graph, and says nothing about composition (SR-0003).
    assert tlc_main(["-C", str(source_dir), "migrate"]) == 0
    out = capsys.readouterr().out
    assert "already at format version 3" in out
    assert "composed source" not in out


# ---- link/new: cross-source targets resolve over the union (SR-0004) -----------

def test_bare_tl_link_refuses_cross_source_destination(consumer_dir, capsys):
    # Bare `tl` cannot see toy:UR-0001; it refuses a link into a borrowed clause.
    rc = tl_main(["-C", str(consumer_dir), "link", "SR-0001", "toy:UR-0001",
                  "--type", "relates"])
    assert rc == 2
    assert "does not exist" in capsys.readouterr().err


def test_compose_link_resolves_cross_source_destination(consumer_dir, capsys):
    # The fix: tl-compose validates the destination over the union and stores the
    # link namespace-qualified on the consumer's own item — the source is untouched.
    rc = tlc_main(["-C", str(consumer_dir), "link", "SR-0001", "toy:UR-0001",
                   "--type", "relates"])
    assert rc == 0
    assert "linked SR-0001 --relates--> toy:UR-0001" in capsys.readouterr().out
    sr = (consumer_dir / "system-requirements" / "SR-0001.yml").read_text()
    assert "target: toy:UR-0001" in sr


def test_compose_link_refuses_dangling_cross_source_destination(consumer_dir, capsys):
    rc = tlc_main(["-C", str(consumer_dir), "link", "SR-0001", "toy:SR-9999",
                   "--type", "relates"])
    assert rc == 2
    assert "toy:SR-9999 does not exist" in capsys.readouterr().err


def test_compose_link_local_destination_unchanged(consumer_dir, capsys):
    # A purely local link resolves in the union verbatim — behaviour-identical to core.
    rc = tlc_main(["-C", str(consumer_dir), "link", "SR-0001", "INT-0001",
                   "--type", "relates"])
    assert rc == 0
    assert "linked SR-0001 --relates--> INT-0001" in capsys.readouterr().out


def test_compose_link_passthrough_without_sources(source_dir, capsys):
    rc = tlc_main(["-C", str(source_dir), "link", "SR-0001", "INT-0001",
                   "--type", "derives_from"])
    assert rc == 0
    assert "linked SR-0001 --derives_from--> INT-0001" in capsys.readouterr().out


def test_bare_tl_new_refuses_cross_source_ground(consumer_dir, capsys):
    rc = tl_main(["-C", str(consumer_dir), "new", "SR", "--type", "system_requirement",
                  "--status", "proposed", "--title", "grounded into a source",
                  "--ground", "toy:INT-0001", "--no-interactive"])
    assert rc == 2
    assert "grounding target toy:INT-0001 does not exist" in capsys.readouterr().err


def test_compose_new_grounds_into_source_and_checks(consumer_dir, capsys):
    # The fix: an item can be grounded into a borrowed clause at birth; the result
    # is a properly grounded consumer item the composed check accepts.
    rc = tlc_main(["-C", str(consumer_dir), "new", "SR", "--type", "system_requirement",
                   "--status", "proposed", "--title", "grounded into a source",
                   "--ground", "toy:INT-0001", "--no-interactive"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "grounded: SR-0002 --derives_from--> toy:INT-0001" in out
    created = (consumer_dir / "system-requirements" / "SR-0002.yml").read_text()
    assert "target: toy:INT-0001" in created
    assert tlc_main(["-C", str(consumer_dir), "check", "--base", ""]) == 0


def test_compose_new_refuses_dangling_cross_source_ground(consumer_dir, capsys):
    rc = tlc_main(["-C", str(consumer_dir), "new", "SR", "--type", "system_requirement",
                   "--ground", "toy:SR-9999", "--no-interactive"])
    assert rc == 2
    assert "grounding target toy:SR-9999 does not exist" in capsys.readouterr().err


def test_compose_new_local_ground_passthrough(consumer_dir, capsys):
    # A local-only --ground defers to core new (no cross-source target to resolve).
    rc = tlc_main(["-C", str(consumer_dir), "new", "SR", "--type", "system_requirement",
                   "--ground", "INT-0001", "--no-interactive"])
    assert rc == 0
    assert "grounded: SR-0002 --derives_from--> INT-0001" in capsys.readouterr().out


# --- context / agentinfo brief (SR-0016) -------------------------------------

def test_context_appends_composition_section_and_live_sources(consumer_dir, capsys):
    # SR-0016: over a project that declares sources, `context` emits the core brief
    # first (the IDD contract) and then the composition section plus the live listing
    # of the sources this project actually declares.
    rc = tlc_main(["-C", str(consumer_dir), "context"])
    out = capsys.readouterr().out
    assert rc == 0
    # Core brief passed through unchanged.
    assert "The contract: Intent-Driven Development" in out
    # Composition section appended.
    assert "Composition: working this project with `tl-compose`" in out
    assert "Re-export and alias" in out
    # Live listing names the declared source and its location.
    assert "## Sources this project declares" in out
    assert "`toy`" in out and "path `../toy-source`" in out


def test_agentinfo_is_identical_to_context(consumer_dir, capsys):
    # SR-0016: `agentinfo` is an alias for `context` — byte-identical output.
    tlc_main(["-C", str(consumer_dir), "context"])
    ctx = capsys.readouterr().out
    tlc_main(["-C", str(consumer_dir), "agentinfo"])
    agent = capsys.readouterr().out
    assert agent == ctx
    assert agent  # non-empty


def test_context_without_sources_is_core_plus_short_note(source_dir, capsys):
    # SR-0016: with no sources declared the brief stays the core's plus a short
    # 'composition available but unused' note — not the full composition manual.
    rc = tlc_main(["-C", str(source_dir), "context"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "The contract: Intent-Driven Development" in out
    assert "declares no `[[sources]]`" in out
    # The full manual's headings are absent.
    assert "Re-export and alias" not in out
    assert "## Sources this project declares" not in out


def test_every_union_command_is_described_in_the_brief(consumer_dir, capsys):
    """SR-0025: a command given union behaviour without being described fails here
    rather than passing silently.

    The dispatch table is the only route to union behaviour and the brief is
    rendered from it, so this should hold by construction — but 'by construction'
    is a claim about today's code, and this is the check that keeps it true. If it
    fails, the command was routed some other way; put it in `_UNION_COMMANDS` with
    the sentence an agent needs, rather than describing it twice."""
    from throughline_compose.cli import _UNION_COMMANDS, _compose_uncovered

    assert _compose_uncovered() == []
    rc = tlc_main(["-C", str(consumer_dir), "context"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Union-aware commands" in out
    for name, (_, note) in _UNION_COMMANDS.items():
        assert f"- **`{name}`**" in out, f"{name} is not described in the brief"
        assert note in out


def test_brief_states_the_cache_never_refetches_a_moved_ref(consumer_dir, capsys):
    """SR-0025: an agent that has not been told the cache never refetches a moved
    ref will report a clean check that proves nothing, because the content it
    validated is stale. The live cache path is rendered so the fix is actionable."""
    from throughline_compose.resolve import cache_root

    rc = tlc_main(["-C", str(consumer_dir), "context"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## The source cache — a moved ref is **not** refetched" in out
    assert "keep using the content it fetched the" in out
    assert str(cache_root()) in out


def test_brief_states_what_a_consumer_may_write(consumer_dir, capsys):
    """SR-0025: composition widens the view, never the authority. An agent that has
    not been told may try to ratify a borrowed clause."""
    rc = tlc_main(["-C", str(consumer_dir), "context"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## What you may write in a consuming project" in out
    # Whitespace-normalised: where the prose happens to wrap is cosmetic, and a test
    # that pins it would fail on a reflow that changed nothing an agent reads.
    flat = " ".join(out.split())
    assert "You write only to your own registers" in flat
    assert "never ratified by you" in flat
    assert "the link is stored on *your* item" in flat.lower()


# --- the reported version (SR-0027) ------------------------------------------

def test_the_reported_version_is_the_installed_distributions():
    """0.9.0 shipped saying "0.8.0" because the release bumped the packaging
    metadata and not the literal beside it. Deriving the value is what makes that
    class of drift impossible rather than merely unlikely."""
    from importlib.metadata import version as dist_version

    assert throughline_compose.__version__ == dist_version("throughline-compose")


def test_an_uninstalled_source_tree_declines_to_name_a_release(monkeypatch):
    """The other half of the obligation. Asked from a tree that was never
    installed, the honest answer is that this is not a release — guessing at the
    nearest one would recreate, from the other direction, the very claim the
    literal used to make."""
    import importlib
    import importlib.metadata

    def _absent(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _absent)
    try:
        assert importlib.reload(throughline_compose).__version__ == "0.0.0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(throughline_compose)
