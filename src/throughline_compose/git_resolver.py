# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The reference resolver (SR-0053: re-exports).

The Tool registers it as the catch-all when imported; importing this module is what
it always was, a way of making sure that has happened.
"""
from throughline import GitResolver

__all__ = ["GitResolver"]
