# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The command (SR-0053: re-exports).

``tl-compose`` runs the Tool. The two private names below are the resolution this
module used to hold, which throughline-ratify up to 0.8.0 reached for; they are the
Tool's ``Resolution`` and ``resolve_sources`` and go with the rest of the re-exports.
"""
from throughline import Resolution as _Resolution  # noqa: F401
from throughline import resolve_sources as _resolve_sources  # noqa: F401
from throughline.cli import main

__all__ = ["main"]
