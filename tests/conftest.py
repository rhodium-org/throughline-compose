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

# These link rules are a superset: they cover the shapes the toy source uses
# internally (`UR derives_from INT`) as well as the consumer's own
# (`SR derives_from INT`). SR-0026 does not ask for that — adopting a source costs
# the `[[sources]]` block and no restatement of its model — so this is a choice the
# fixture makes, to exercise the path where a borrowed item does ground under the
# consumer's schema. `_LEAN_CONSUMER` below is the same graph without the choice.
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


# A consumer carrying a coverage rule that no intent in the union satisfies — the
# local intent and the borrowed one both lack an incoming `relates`. It is the
# smallest graph that tells the two halves of SR-0035 apart, because the finding is
# identical either side of the seam and only the seam decides which is reported.
_COVERAGE_RULE = """
[[rules.coverage]]
filter = "type == 'intent'"
needs = "incoming:relates"
severity = "warning"
"""

_COVERAGE_CONSUMER: dict[str, str] = dict(
    _CONSUMER,
    **{"throughline.toml": _CONSUMER["throughline.toml"] + _COVERAGE_RULE},
)

# The same graph, with the consumer declaring that its coverage rule is one it can
# answer across the seam (SR-0035).
_WIDENED_CONSUMER: dict[str, str] = dict(
    _CONSUMER,
    **{
        "throughline.toml": _CONSUMER["throughline.toml"]
        + _COVERAGE_RULE
        + '\n[seam]\nreport_on_borrowed = ["coverage"]\n'
    },
)


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    return _write(tmp_path / "toy-source", _SOURCE)


@pytest.fixture
def consumer_dir(tmp_path: Path, source_dir: Path) -> Path:
    return _write(tmp_path / "consumer", _CONSUMER)


@pytest.fixture
def coverage_consumer_dir(tmp_path: Path, source_dir: Path) -> Path:
    """A coverage rule over the union, with the seam left at its default."""
    return _write(tmp_path / "consumer", _COVERAGE_CONSUMER)


@pytest.fixture
def widened_consumer_dir(tmp_path: Path, source_dir: Path) -> Path:
    """The same, with ``[seam] report_on_borrowed = ["coverage"]``."""
    return _write(tmp_path / "consumer", _WIDENED_CONSUMER)


@pytest.fixture
def lean_consumer_dir(tmp_path: Path, source_dir: Path) -> Path:
    return _write(tmp_path / "consumer", _LEAN_CONSUMER)
