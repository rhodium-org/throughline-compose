# Copyright (c) 2026 Time Back Solutions Limited
# SPDX-License-Identifier: Apache-2.0
"""The ``tl-compose`` entry point.

Design intent (SR-0003): ``tl-compose`` is a strict superset of ``tl``. Local-graph
commands are forwarded to throughline's CLI unchanged; the union-aware commands
(`check`, `docs`) and the source commands (declare, pin, update) are layered on top.

This is a pre-alpha scaffold: it currently forwards everything to throughline so the
console script exists and the superset holds for local commands. The composition
overrides are not yet implemented.
"""
from __future__ import annotations

from throughline.cli import main as _tl_main


def main(argv: list[str] | None = None) -> int:
    return _tl_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
