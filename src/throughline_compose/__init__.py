# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""throughline-compose — compose one requirements graph from many reusable sources.

Builds on ``throughline`` as an unmodified library (SR-0004): it prepares a union
``Project`` from the declared sources and runs throughline's own ``validate``,
``Index``, and ``fingerprint`` over it. The ``tl-compose`` CLI is a strict superset
of ``tl`` (SR-0003) — it forwards local commands to throughline unchanged and
overrides only the union-aware ones.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _dist_version

# Read from the installed distribution, never restated here (SR-0027). Held as a
# literal it is a second copy of a fact that already lives in pyproject.toml, and
# the two drift in silence: 0.9.0 shipped reporting "0.8.0" because the release
# bumped one and not the other, and nothing failed — the wrong answer was simply
# returned to whoever asked.
try:
    __version__ = _dist_version("throughline-compose")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0+unknown"

# Registering the directives this layer provides is an import side effect, so any
# entry into the package — the CLI, or a caller using it as a library — renders
# tl:sourced, while a bare `tl` reports it as unprovided (SR-0039).
from . import directives as _directives  # noqa: E402,F401

__all__ = ["__version__"]
