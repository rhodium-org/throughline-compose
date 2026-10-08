# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""This package is deprecated and says so (SR-0054)."""
from __future__ import annotations

import importlib
import sys
from importlib.metadata import metadata

import pytest

MODULES = ("sources", "spi", "git_resolver", "resolve", "union", "seam", "resolver",
           "directives", "cli")


def _fresh_import():
    for name in [n for n in sys.modules if n.split(".")[0] == "throughline_compose"]:
        del sys.modules[name]
    return importlib.import_module("throughline_compose")


def test_importing_the_package_warns_and_names_throughline():
    with pytest.warns(DeprecationWarning, match="import these names from throughline"):
        _fresh_import()


def test_every_re_export_still_imports():
    with pytest.warns(DeprecationWarning):
        _fresh_import()
    for name in MODULES:
        module = importlib.import_module(f"throughline_compose.{name}")
        assert module.__all__, name
        for exported in module.__all__:
            assert hasattr(module, exported), f"{name}.{exported}"


def test_the_metadata_marks_the_package_inactive():
    meta = metadata("throughline-compose")
    assert "Development Status :: 7 - Inactive" in meta.get_all("Classifier")
    assert meta["Summary"].startswith("Deprecated")
