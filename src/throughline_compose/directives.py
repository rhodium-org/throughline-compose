# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The ``tl:sourced`` directive (SR-0053: re-exports).

The Tool registers it when imported, so ``register`` has nothing left to do and is
kept only so that a caller who still calls it keeps working.
"""
from throughline import render_sourced
from throughline.inject import matching

__all__ = ["matching", "register", "render_sourced"]


def register() -> None:
    """Registered already, by the Tool, on import."""
