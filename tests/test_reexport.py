# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""Transitive re-export and alias (UR-0005, SR-0014, SR-0015).

Composition is one level deep and flat: a consumer that composes a source which
internally cites ``asvs:SR-0001`` must itself declare ``asvs``. Re-export lets the
consumer pull that transitive source forward — inheriting the intermediate
source's pin — optionally under an alias, and a namespace bound to two editions
fails fast with an advisory that names the why and the fix.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from throughline.model import Item, Link, Project, Register

from throughline_compose.cli import main as tlc_main
from throughline_compose.sources import SourceError, parse_sources
from throughline_compose.union import ComposeError, build_union


# ---------------------------------------------------------------- reexport parsing

def _project(config: dict) -> Project:
    return Project(path=".", config=config)


def test_reexport_array_is_identity_mapping():
    p = _project({"sources": [
        {"namespace": "base", "path": "../base", "reexport": ["asvs", "gds"]}]})
    (s,) = parse_sources(p)
    assert s.reexport == {"asvs": "asvs", "gds": "gds"}


def test_reexport_table_binds_aliases():
    p = _project({"sources": [
        {"namespace": "base", "path": "../base", "reexport": {"asvs": "owasp"}}]})
    (s,) = parse_sources(p)
    assert s.reexport == {"asvs": "owasp"}


def test_no_reexport_is_empty():
    p = _project({"sources": [{"namespace": "base", "path": "../base"}]})
    (s,) = parse_sources(p)
    assert s.reexport == {}


def test_reexport_bad_namespace_rejected():
    p = _project({"sources": [
        {"namespace": "base", "path": "../base", "reexport": ["Asvs"]}]})
    with pytest.raises(SourceError):
        parse_sources(p)


def test_reexport_bad_alias_rejected():
    p = _project({"sources": [
        {"namespace": "base", "path": "../base", "reexport": {"asvs": "Owasp"}}]})
    with pytest.raises(SourceError):
        parse_sources(p)


def test_reexport_wrong_type_rejected():
    p = _project({"sources": [
        {"namespace": "base", "path": "../base", "reexport": "asvs"}]})
    with pytest.raises(SourceError):
        parse_sources(p)


# ------------------------------------------------------ union alias remap (SR-0014)

def _mk(config: dict, regs: dict[str, list[Item]]) -> Project:
    p = Project(path=".", config=config)
    for prefix, items in regs.items():
        reg = Register(prefix=prefix)
        for it in items:
            it._register_prefix = prefix
            reg.items[it.uid] = it
        p.registers[prefix] = reg
    return p


_SCHEMA = {"project": {"name": "c", "format_version": 2},
           "grounding": {"root_types": ["intent"], "delivery_roots": ["intent"],
                         "ground_link_types": ["derives_from"]}}


def _asvs() -> Project:
    return _mk({"project": {"name": "asvs", "format_version": 2}},
               {"SR": [Item(uid="SR-0001", type="system_requirement",
                            status="approved")]})


def _base_referencing_asvs() -> Project:
    # A source that internally cites another namespace by that namespace's own name.
    sr = Item(uid="SR-0001", type="system_requirement", status="approved",
              links=[Link(target="asvs:SR-0001", type="relates")])
    return _mk({"project": {"name": "base", "format_version": 2}}, {"SR": [sr]})


def test_alias_remaps_the_sources_internal_reference():
    consumer = _mk(_SCHEMA, {})
    sources = {"base": _base_referencing_asvs(), "owasp": _asvs()}
    # Without the alias map, base's `asvs:` reference names an undeclared namespace.
    with pytest.raises(ComposeError):
        build_union(consumer, sources)
    # With base's asvs re-exported as owasp, the reference resolves to owasp.
    union = build_union(consumer, sources, {"base": {"asvs": "owasp"}})
    base_sr = next(it for it in union.project.items()
                   if union.qualified(it.uid) == "base:SR-0001")
    (link,) = base_sr.links
    assert union.qualified(link.target) == "owasp:SR-0001"


# ------------------------------------------------------- end-to-end (materialised)

def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(body, encoding="utf-8")
    return root


def _leaf_source(name: str, clause_text: str) -> dict[str, str]:
    return {
        "throughline.toml": f'[project]\nname = "{name}"\nformat_version = 2\n',
        "intents/.register.yml": "prefix: INT\ndigits: 4\n",
        "system-requirements/.register.yml": "prefix: SR\ndigits: 4\n",
        "intents/INT-0001.yml": (
            "uid: INT-0001\ntype: intent\nstatus: approved\n"
            f"title: {name} root\ntext: The {name} source root.\nnormative: false\n"),
        "system-requirements/SR-0001.yml": (
            "uid: SR-0001\ntype: system_requirement\nstatus: approved\n"
            f"title: {name} clause\ntext: {clause_text}\n"
            "links:\n- target: INT-0001\n  type: derives_from\n"
            "attrs:\n  priority: must\n  origin: human\n"),
    }


_BASE = {
    "throughline.toml": (
        '[project]\nname = "base"\nformat_version = 2\n\n'
        '[[sources]]\nnamespace = "asvs"\npath = "../asvs-source"\n'),
    "intents/.register.yml": "prefix: INT\ndigits: 4\n",
    "system-requirements/.register.yml": "prefix: SR\ndigits: 4\n",
    "intents/INT-0001.yml": (
        "uid: INT-0001\ntype: intent\nstatus: approved\n"
        "title: base root\ntext: The base source root.\nnormative: false\n"),
    "system-requirements/SR-0001.yml": (
        "uid: SR-0001\ntype: system_requirement\nstatus: approved\n"
        "title: base clause leaning on asvs\ntext: The base clause.\n"
        "links:\n- target: INT-0001\n  type: derives_from\n"
        "- target: asvs:SR-0001\n  type: relates\n"
        "attrs:\n  priority: must\n  origin: human\n"),
}


def _consumer(reexport_line: str, ref_target: str) -> dict[str, str]:
    return {
        "throughline.toml": (
            '[project]\nname = "consumer"\nformat_version = 3\n\n'
            '[[sources]]\nnamespace = "base"\npath = "../base"\n'
            f"{reexport_line}\n\n"
            '[grounding]\nroot_types = ["intent"]\n'
            'delivery_roots = ["intent"]\nground_link_types = ["derives_from"]\n\n'
            '[links]\ntypes = ["derives_from", "relates"]\n\n'
            '[status]\nvalues = ["draft", "approved", "ratified", "rejected", '
            '"suspect", "deleted"]\n\n'
            '[status.roles]\ninitial = "draft"\nratified = "ratified"\n'
            'invalidated = "rejected"\nsuspect = "suspect"\ntombstone = "deleted"\n'),
        "intents/.register.yml": "prefix: INT\ndigits: 4\n",
        "system-requirements/.register.yml": "prefix: SR\ndigits: 4\n",
        "intents/INT-0001.yml": (
            "uid: INT-0001\ntype: intent\nstatus: approved\n"
            "title: consumer root\ntext: The consumer root.\nnormative: false\n"),
        "system-requirements/SR-0001.yml": (
            "uid: SR-0001\ntype: system_requirement\nstatus: approved\n"
            "title: consumer clause\ntext: The consumer clause.\n"
            "links:\n- target: INT-0001\n  type: derives_from\n"
            f"- target: {ref_target}\n  type: relates\n"
            "attrs:\n  priority: must\n  origin: human\n"),
    }


def _scene(tmp_path: Path, reexport_line: str, ref_target: str,
           asvs_text: str = "The asvs clause.") -> Path:
    _write(tmp_path / "asvs-source", _leaf_source("asvs", asvs_text))
    _write(tmp_path / "base", _BASE)
    return _write(tmp_path / "consumer", _consumer(reexport_line, ref_target))


def test_identity_reexport_pulls_transitive_source_forward(tmp_path, capsys):
    consumer = _scene(tmp_path, 'reexport = ["asvs"]', "asvs:SR-0001")
    rc = tlc_main(["-C", str(consumer), "check", "--base", ""])
    err = capsys.readouterr().err
    assert rc == 0
    assert "composed graph is sound" in err
    assert "asvs" in err  # the re-exported source appears in the summary


def test_missing_reexport_fails_undeclared_namespace(tmp_path, capsys):
    # Without re-export, the consumer's own `asvs:` reference is undeclared.
    consumer = _scene(tmp_path, "", "asvs:SR-0001")
    rc = tlc_main(["-C", str(consumer), "check", "--base", ""])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert rc != 0


def test_alias_reexport_binds_new_namespace(tmp_path, capsys):
    consumer = _scene(tmp_path, 'reexport = { asvs = "owasp" }', "owasp:SR-0001")
    rc = tlc_main(["-C", str(consumer), "check", "--base", ""])
    err = capsys.readouterr().err
    assert rc == 0
    assert "composed graph is sound" in err
    assert "owasp" in err


def test_two_editions_conflict_advises_why_and_fix(tmp_path, capsys):
    # The consumer declares `asvs` directly at one edition and re-exports base's
    # `asvs` at a different edition — the collision SR-0015 governs.
    _write(tmp_path / "asvs-two", _leaf_source("asvs", "A DIFFERENT asvs edition."))
    consumer_files = _consumer('reexport = ["asvs"]', "asvs:SR-0001")
    consumer_files["throughline.toml"] = consumer_files["throughline.toml"].replace(
        '[[sources]]\nnamespace = "base"\npath = "../base"\nreexport = ["asvs"]\n',
        '[[sources]]\nnamespace = "base"\npath = "../base"\nreexport = ["asvs"]\n\n'
        '[[sources]]\nnamespace = "asvs"\npath = "../asvs-two"\n')
    _write(tmp_path / "asvs-source", _leaf_source("asvs", "The asvs clause."))
    _write(tmp_path / "base", _BASE)
    consumer = _write(tmp_path / "consumer", consumer_files)

    rc = tlc_main(["-C", str(consumer), "check", "--base", ""])
    err = capsys.readouterr().err
    assert rc != 0
    assert "two different editions" in err          # the why
    assert "pinning 'asvs'" in err                  # fix 1
    assert "aliasing" in err                         # fix 2
    assert "merge" in err                            # states it will not merge


def test_reexport_of_undeclared_namespace_fails(tmp_path, capsys):
    # base does not declare `wcag`, so it cannot be re-exported through base.
    consumer = _scene(tmp_path, 'reexport = ["wcag"]', "INT-0001")
    rc = tlc_main(["-C", str(consumer), "check", "--base", ""])
    err = capsys.readouterr().err
    assert rc != 0
    assert "wcag" in err
