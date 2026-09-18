# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The source declaration, as the Tool reads it (SR-0053: re-exports)."""
from throughline import Source, SourceError, parse_sources
from throughline.sources import withdrawn_declarations

__all__ = ["Source", "SourceError", "parse_sources", "withdrawn_declarations"]
