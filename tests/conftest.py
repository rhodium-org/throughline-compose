# Copyright (c) 2026 Henry J Grech-Cini
# SPDX-License-Identifier: Apache-2.0
"""Materialise the CLI fixtures into a tmp dir.

The fixtures are *loadable throughline projects*. They must not live inside the
throughline-compose repo tree: the loader discovers registers by walking for
``.register.yml`` files, so an on-disk fixture project would collide with this
repo's own IDD spine when ``tl-compose check`` runs at the root. Writing them into
``tmp_path`` keeps the repo tree a single, clean project.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# path (relative to a project root) -> file body.
_SOURCE: dict[str, str] = {
    "throughline.toml": """\
[project]
name = "toy"
format_version = 3

[grounding]
root_types = ["intent"]
delivery_roots = ["intent"]
ground_link_types = ["derives_from", "implements"]

[status]
values = ["proposed", "draft", "approved", "ratified", "rejected", "suspect", "deleted"]

[status.roles]
initial = "draft"
ratified = "ratified"
invalidated = "rejected"
suspect = "suspect"
tombstone = "deleted"
""",
    "intents/.register.yml": "prefix: INT\ndigits: 4\n",
    "user-requirements/.register.yml": "prefix: UR\ndigits: 4\n",
    "system-requirements/.register.yml": "prefix: SR\ndigits: 4\n",
    "intents/INT-0001.yml": """\
uid: INT-0001
type: intent
status: approved
title: Toy source purpose
text: The toy source exists to exercise composition end to end.
normative: false
""",
    "user-requirements/UR-0001.yml": """\
uid: UR-0001
type: user_requirement
status: approved
title: A grouping the source offers
text: The source shall expose a grouping that consumers can build on.
links:
- target: INT-0001
  type: derives_from
attrs:
  priority: must
  origin: human
""",
    "system-requirements/SR-0001.yml": """\
uid: SR-0001
type: system_requirement
status: approved
title: A normative clause the source offers
text: The source shall provide one concrete, testable clause.
links:
- target: UR-0001
  type: implements
attrs:
  priority: must
  source_ref: V1.1.1
  origin: human
""",
}

_CONSUMER: dict[str, str] = {
    "throughline.toml": """\
[project]
name = "consumer"
format_version = 3

[[sources]]
namespace = "toy"
path = "../toy-source"

[grounding]
root_types = ["intent"]
delivery_roots = ["intent"]
ground_link_types = ["derives_from", "implements"]

[links]
types = ["derives_from", "implements", "relates"]

# The consumer's schema governs the whole union, so its link rules must be a
# superset covering the shapes its sources use internally (here the toy source's
# `UR derives_from INT`) as well as the consumer's own (`SR derives_from INT`).
[link_rules]
implements   = { from = ["system_requirement"], to = ["user_requirement"] }
derives_from = { from = ["system_requirement", "user_requirement"], to = ["intent"] }

[status]
values = ["proposed", "draft", "approved", "ratified", "rejected", "suspect", "deleted"]

[status.roles]
initial = "draft"
ratified = "ratified"
invalidated = "rejected"
suspect = "suspect"
tombstone = "deleted"
""",
    "intents/.register.yml": "prefix: INT\ndigits: 4\n",
    "system-requirements/.register.yml": "prefix: SR\ndigits: 4\n",
    "intents/INT-0001.yml": """\
uid: INT-0001
type: intent
status: approved
title: Consumer purpose
text: The consumer builds on a composed source.
normative: false
""",
    "system-requirements/SR-0001.yml": """\
uid: SR-0001
type: system_requirement
status: approved
title: Consumer clause building on the source
text: The consumer shall ground itself while relating to a source clause.
links:
- target: INT-0001
  type: derives_from
- target: toy:SR-0001
  type: relates
attrs:
  priority: must
  origin: human
""",
}


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(body, encoding="utf-8")
    return root


# A consumer that does NOT restate the source's model, which is what SR-0026 made
# legal and therefore what a consumer now looks like. It differs from _CONSUMER by
# one line: `implements` is not one of *its* grounding links. The toy source grounds
# its SR through `implements`, so under this schema that borrowed item reaches no
# root — not a defect in either graph, just a model the consumer never adopted and
# cannot be asked to fix. It is the smallest graph that tells a union-wide grounding
# figure apart from a local one (SR-0029).
_LEAN_CONSUMER: dict[str, str] = dict(
    _CONSUMER,
    **{
        "throughline.toml": _CONSUMER["throughline.toml"].replace(
            'ground_link_types = ["derives_from", "implements"]',
            'ground_link_types = ["derives_from"]',
        )
    },
)


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    return _write(tmp_path / "toy-source", _SOURCE)


@pytest.fixture
def consumer_dir(tmp_path: Path, source_dir: Path) -> Path:
    return _write(tmp_path / "consumer", _CONSUMER)


@pytest.fixture
def lean_consumer_dir(tmp_path: Path, source_dir: Path) -> Path:
    return _write(tmp_path / "consumer", _LEAN_CONSUMER)
