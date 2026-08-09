# Contributing to throughline-compose

Thanks for your interest. `throughline-compose` (CLI `tl-compose`) is the
composition layer for [throughline][tl] — it lets a project build one requirements
graph from its own items **plus** reusable sources adopted by reference, and work
the union as one.

Contributions are welcome, including the kind that isn't code: composing a real
source set and reporting where it fought you is a genuine contribution.

## Set up your environment

```bash
git clone https://github.com/rhodium-org/throughline-compose.git
cd throughline-compose
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
```

That resolves [throughline][tl] from PyPI. Python 3.11 or later.

### If you're also working on throughline itself

Composition is especially exposed to a mismatched pair: a change to the seam lands
here but is *judged* by core's validator, so you can be editing compose while
running the **published** core — and every version string will still agree. The
same command in the same repo then gives you and a colleague different answers,
and the argument that follows is about the graph rather than about the toolchain.

Check both out side by side and chain them in a **single** command, so the resolver
never reaches the package index:

```bash
pip install -e ../throughline -e '.[dev]'
```

Then verify rather than assume — the path must be your checkout, not
`site-packages`:

```bash
python -c "import throughline as m; print(m.__file__)"
```

## Run the tests

```bash
python -m pytest
```

## Run the requirements gate

This repository manages its own requirements with the tool it provides — they live
in [`idd/`](idd), and the graph composes throughline's own as a pinned source:

```bash
tl-compose -C idd check --strict
tl-compose -C idd docs --check      # published documents must match the graph
```

Both run in CI on every pull request. The first run fetches the pinned source over
the network and says so while it does; later runs resolve from the cache and are
quiet.

## Making changes

This project follows **Intent-Driven Development** — the discipline the tool exists
to serve, applied to itself:

1. **Ground the change before you build it.** Find the `idd/` item that justifies
   the work. If none exists, author it first (`tl-compose new SR --ground <UID>`) as
   a `draft` — the version of a red test that applies to requirements: specified and
   justified, not yet built.
2. **Build it**, then move the item forward (`tl-compose status <UID> implemented`).
3. **Cite the UID in your commit message.** Every commit here names the item it
   supports.
4. **Keep both gates green**, and regenerate documents with `tl-compose -C idd docs`
   when you change an item that appears in one.

If you are an AI agent rather than a person, run `tl-compose -C idd context` first —
it prints the brief generated from this project's live configuration — and read
[`AGENTS.md`](AGENTS.md). Two rules are absolute: propose, never ratify, and never
invent a `--by` name. A fabricated ratifier is a false accountability record.

## Where to start

- Issues labelled `good first issue` or `help wanted`.
- Composing a real source set and reporting friction. A clear "the model fought me
  here" write-up is worth as much as a patch.
- [`README.md`](README.md) covers what composition does; [`AGENTS.md`](AGENTS.md)
  covers the discipline and how the packages fit together;
  [`idd/docs/spec.md`](idd/docs/spec.md) is the generated specification.

## Licensing of contributions

throughline-compose is released under the **Apache License 2.0**
([`LICENSE`](LICENSE)). By submitting a contribution you agree it is licensed under
those same terms, per section 5 of the licence, unless you arrange otherwise with
the maintainers. Please keep the SPDX header
(`# SPDX-License-Identifier: Apache-2.0`) on new source files.

Everyone participating is expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

[tl]: https://github.com/rhodium-org/throughline
