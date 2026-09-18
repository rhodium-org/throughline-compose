# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""The resolver interface and its registry (SR-0053: re-exports).

``register`` is the Tool's ``register_resolver`` under the name this package gave it.
"""
from throughline import (
    ResolvedSource,
    Resolver,
    ResolverError,
    content_fingerprint,
    resolver_for,
)
from throughline import register_resolver as register

__all__ = [
    "ResolvedSource", "Resolver", "ResolverError", "content_fingerprint", "register",
    "resolver_for",
]
