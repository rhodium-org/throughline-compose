# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""throughline-compose — names for what throughline provides.

Since 0.22.0 this package installs no command and holds no implementation.
Composition lives in throughline 3.11.1 and later (throughline UR-0037, SR-0230 to
SR-0236): the union, the seam, the resolver interface with its registry and
reference resolver, the ``tl:sourced`` mirror and the union-aware commands.
``tl-compose`` and ``throughline-compose`` are names the Tool installs, and they run
the Tool. Every module here re-exports the Tool's names under the paths consumers
imported before the fold, so a consumer that has not moved keeps working unchanged
(SR-0053). The re-exports end with the Tool's next major release; import from
``throughline`` directly.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _dist_version

# Importing the Tool registers the reference resolver and the tl:sourced directive,
# which is the side effect entering this package used to have (SR-0039).
import throughline  # noqa: F401

# Read from the installed distribution, never restated here (SR-0027).
try:
    __version__ = _dist_version("throughline-compose")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
