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

__version__ = "0.4.1"

__all__ = ["__version__"]
