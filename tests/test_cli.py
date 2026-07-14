# Copyright (c) 2026 Time Back Solutions Limited
# SPDX-License-Identifier: Apache-2.0
"""End-to-end CLI tests over materialised fixtures: the two-tool contract
(SR-0003, SR-0005) — bare `tl` fails fast, `tl-compose` resolves and passes."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from throughline.cli import main as tl_main
from throughline_compose.cli import main as tlc_main


def test_version_reports_compose_not_core(capsys):
    # `--version` must speak as tl-compose, not forward throughline's `tl X` string.
    with pytest.raises(SystemExit) as exc:
        tlc_main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("tl-compose ")
    assert "throughline " in out  # names the core it composes over


def test_bare_tl_check_fails_fast_on_qualified_reference(consumer_dir, capsys):
    # The core cannot resolve `toy:SR-0001`; it must signpost tl-compose (SR-0005).
    rc = tl_main(["-C", str(consumer_dir), "check", "--base", ""])
    assert rc == 1
    assert "namespace-unresolved" in capsys.readouterr().out


def test_compose_check_resolves_and_passes(consumer_dir, capsys):
    rc = tlc_main(["-C", str(consumer_dir), "check", "--base", ""])
    assert rc == 0
    assert "composed graph is sound" in capsys.readouterr().err


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
