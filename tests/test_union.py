# Copyright (c) 2026 Time Back Solutions Limited
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the composition engine (union.py, sources.py)."""
from __future__ import annotations

import pytest
from throughline.model import Item, Link, Project, Register
from throughline.validate import validate

from throughline_compose.sources import SourceError, parse_sources
from throughline_compose.union import ComposeError, build_union, translate_finding

# A permissive consumer schema so these unit tests exercise the merge, not the
# consumer's own type rules (those are covered by the on-disk fixtures).
_SCHEMA = {
    "project": {"name": "c", "format_version": 2},
    "grounding": {"root_types": ["intent"], "delivery_roots": ["intent"],
                  "ground_link_types": ["derives_from", "implements"]},
}


def _project(config: dict, regs: dict[str, list[Item]]) -> Project:
    p = Project(path=".", config=config)
    for prefix, items in regs.items():
        reg = Register(prefix=prefix)
        for it in items:
            it._register_prefix = prefix
            reg.items[it.uid] = it
        p.registers[prefix] = reg
    return p


def _source() -> Project:
    intent = Item(uid="INT-0001", type="intent", status="approved", normative=False)
    sr = Item(uid="SR-0001", type="system_requirement", status="approved",
              links=[Link(target="INT-0001", type="derives_from")])
    return _project({"project": {"name": "toy", "format_version": 2}},
                    {"INT": [intent], "SR": [sr]})


# --------------------------------------------------------------- sources parsing

def test_parse_sources_reads_declarations():
    p = _project({**_SCHEMA, "sources": [{"namespace": "toy", "path": "../toy"}]}, {})
    sources = parse_sources(p)
    assert [(s.namespace, s.path) for s in sources] == [("toy", "../toy")]


def test_no_sources_is_empty():
    assert parse_sources(_project(_SCHEMA, {})) == []


def test_bad_namespace_rejected():
    p = _project({**_SCHEMA, "sources": [{"namespace": "Toy", "path": "x"}]}, {})
    with pytest.raises(SourceError):
        parse_sources(p)


def test_duplicate_namespace_rejected():
    p = _project({**_SCHEMA, "sources": [
        {"namespace": "toy", "path": "a"}, {"namespace": "toy", "path": "b"}]}, {})
    with pytest.raises(SourceError):
        parse_sources(p)


# ------------------------------------------------------------------ union merge

def test_qualified_reference_rewritten_and_resolves():
    consumer = _project(_SCHEMA, {"SR": [Item(
        uid="SR-0001", type="system_requirement", status="approved",
        links=[Link(target="toy:SR-0001", type="relates")])]})
    union = build_union(consumer, {"toy": _source()})

    # The borrowed item is present under a mangled UID, mapped back to qualified.
    assert union.project.get("TOYSR-0001") is not None
    assert union.qualified("TOYSR-0001") == "toy:SR-0001"
    # The consumer's cross-source link now points at the mangled UID — no colon left.
    consumer_sr = union.project.get("SR-0001")
    assert consumer_sr.links[0].target == "TOYSR-0001"
    assert not any(":" in l.target for it in union.project.items() for l in it.links)


def test_source_internal_reference_rewritten():
    union = build_union(_project(_SCHEMA, {}), {"toy": _source()})
    # SR-0001 -> INT-0001 inside the source becomes TOYSR-0001 -> TOYINT-0001.
    assert union.project.get("TOYSR-0001").links[0].target == "TOYINT-0001"


def test_unbound_namespace_fails_fast():
    consumer = _project(_SCHEMA, {"SR": [Item(
        uid="SR-0001", type="system_requirement", status="approved",
        links=[Link(target="ghost:SR-0001", type="relates")])]})
    with pytest.raises(ComposeError, match="ghost"):
        build_union(consumer, {"toy": _source()})


def test_composed_graph_validates_clean():
    consumer = _project(_SCHEMA, {
        "INT": [Item(uid="INT-0001", type="intent", status="approved",
                     normative=False)],
        "SR": [Item(uid="SR-0001", type="system_requirement", status="approved",
                    links=[Link(target="INT-0001", type="derives_from"),
                           Link(target="toy:SR-0001", type="relates")])]})
    union = build_union(consumer, {"toy": _source()})
    errors = [f for f in validate(union.project) if f.severity == "error"]
    assert errors == [], errors


def test_dangling_cross_source_reference_translated_back():
    consumer = _project(_SCHEMA, {"SR": [Item(
        uid="SR-0001", type="system_requirement", status="approved",
        links=[Link(target="toy:SR-9999", type="relates")])]})
    union = build_union(consumer, {"toy": _source()})
    pattern = union.pattern()
    dangling = [translate_finding(f, union, pattern)
                for f in validate(union.project) if f.rule == "dangling-link"]
    assert dangling, "expected a dangling-link for the missing source clause"
    # The composer sees the reference in its own vocabulary, not the mangled form.
    assert "toy:SR-9999" in dangling[0].message
    assert "TOYSR-9999" not in dangling[0].message


# ------------------------------------------------------------- prefix collisions

def test_synthetic_prefix_collision_fails_fast():
    # Two namespaces that sanitise to the same stem and share a source prefix.
    src = _source()
    consumer = _project(_SCHEMA, {})
    with pytest.raises(ComposeError, match="distinct namespace"):
        build_union(consumer, {"g-s": src, "gs": _source()})
