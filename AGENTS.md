<!--
  This project is composed with throughline-compose (Git-native requirements,
  Intent-Driven Development). This file is the CANONICAL agent-guidance document;
  CLAUDE.md, GEMINI.md, .github/copilot-instructions.md and .cursor/rules all
  point here so there is one source of truth, not N drifting copies.

  The operative rules for the graph are GENERATED FROM THE LIVE CONFIG by
  `tl-compose context` — do not paste a static copy into this file.
-->

# Working with throughline-compose (for AI agents)

This repository is **throughline-compose**, the composition layer for
[throughline](https://github.com/rhodium-org/throughline) (CLI `tl-compose`, a
strict superset of `tl`). It lets a project compose one requirements graph from
its own items **plus** reusable throughline sources adopted *by reference* — a
house style, a platform standard, a regulatory baseline — and work the union as
one. It is also *self-hosting*: its own requirements live under [`idd/`](idd).
Read the hat that matches what you're doing:

- **Using throughline-compose inside another project?** → [Using it](#using-throughline-compose-in-a-project).
- **Changing throughline-compose itself?** → [Working on this repo](#working-on-this-repo-contributing).

---

## Using throughline-compose in a project

`tl-compose` is a **strict superset of `tl`**: local-graph commands forward to
throughline unchanged; the union-aware `check` and `docs` compose the declared
sources into one graph, validate it with throughline's own validator, and render
documents over the union. In a composed project **drive everything through
`tl-compose`, never `tl` directly** (a bare `tl` fails fast on unresolved
cross-source references rather than giving a false clean result).

### 1. Keep the graph in a folder named `idd/` (best practice)

Put the requirements graph — including its `[[sources]]` declarations — in a
top-level `idd/` directory, separate from source code. Every command below assumes
it; drive with `-C idd`, e.g. `tl-compose -C idd check --strict`.

```
your-project/
  idd/
    throughline.toml     # your items + [[sources]] you compose
    <register folders>/…
  src/  …
```

### 2. Read the generated brief FIRST — never a hand-written copy

The authoritative agent brief is **generated from the project's live
`throughline.toml`**, and the compose brief extends the core one with the
composition model (namespaces, sources, borrowed vs. local items):

```
tl-compose -C idd context
```

Read it before creating or editing any item; trust it over any static list
(including this file).

### 3. Composing a source

A consumer binds each source to a **namespace** it chooses, located by a pinned
git `url` + `ref` (durable, shareable) or a local `path` (side-by-side dev):

```toml
# idd/throughline.toml
[[sources]]
namespace = "asvs"
url = "https://github.com/rhodium-org/throughline-asvs"
ref = "v4.0.3"            # pin the exact edition (tag, branch, or commit SHA)
```

A borrowed item is referenced as `namespace:UID` (e.g. `asvs:SR-0001`); a bare
UID is always local. Composition never renumbers or copies — imported items keep
their source-native UID. Composition is **one level deep**: if a source you adopt
itself cites another namespace, you must also declare that namespace (or
`reexport` it through the intermediate source). A moved git tag is **not**
refetched from cache — bump the `ref`, or clear
`~/.cache/throughline-compose/sources/…@<ref>`, to pick up changed content.

**Adopting a source costs the `[[sources]]` block and nothing else**
([SR-0026](idd/system-requirements/SR-0026.yml)) — never copy the source's model
into your `throughline.toml`. Its statuses, attributes, link vocabulary and
endpoint rules stay its business: a finding whose only remedy is a commit in the
graph that owns the item is not raised in your project, so you will not see one
and be tempted to widen your schema until it goes away. Copied declarations are
inert, unattributed, and wrong the moment the pin moves. Your own items are
judged under your own model in full, and the seam strictly — a reference into a
source must resolve, a stamp you recorded on a borrowed clause must still match
it, and a chain that leaves your graph and grounds inside a source counts as
grounded. If a borrowed item is genuinely wrong, the remedy is to move the pin or
tell the owner.

### 4. Starting throughline-compose on a project

- **New project:** `tl-compose -C idd init`, then declare `[[sources]]` and author
  your own items.
- **Existing codebase — reverse-engineer (offer this to the user):** read the code
  and **propose** the requirements it already implements — grounding them against
  your own roots and, where relevant, against clauses of a composed standard
  (`derives_from → asvs:SR-0001`). Create them as machine-origin items
  (`--origin ai`), which enter `proposed`; then **stop and hand off** to a named
  human to ratify (`tl-compose ratify <UID> --by <name>`, or the
  [`tl-ratify`](https://github.com/rhodium-org/throughline-ratify) cockpit, which
  is compose-aware and grounds over the union).

### 5. The working loop

1. **Author the why first** — create the grounded, machine-origin requirement
   (`proposed`, awaiting ratification) before you build.
2. **Implement.**
3. **Cite the item UID** in the commit message.
4. **Gate:** keep `tl-compose -C idd check --strict` green (and
   `tl-compose -C idd docs --check` if you publish documents). Exit codes:
   `0` ok · `1` findings · `2` usage.

## Ratification is a human act — never sign on someone's behalf

`tl-compose ratify <UID> --by <who>` records that a **named human** took
accountability for an item. If you do not know who is ratifying, **ask and use
exactly what they give you** — never invent, guess, or reuse a name. A fabricated
`ratified_by` is a false accountability record, the one thing this toolchain
exists to prevent.

## How to guide an agent to *use* the tool (the pattern)

Don't hand-write a brief that rots. In the *consuming* project add a short
`AGENTS.md` (the vendor-neutral standard) that says: *"This project is composed
with throughline-compose. Run `tl-compose -C idd context` and follow it. Ground
every item upward before you build it; only a named human ratifies
machine-proposed items; drive everything through `tl-compose`, never bare `tl`."*
Let each framework's own file (`CLAUDE.md`, `GEMINI.md`,
`.github/copilot-instructions.md`, `.cursor/rules/…`) be a **one-line pointer** to
that `AGENTS.md`, never a copy. This repo does exactly that.

---

## Working on this repo (contributing)

throughline-compose is open source (Apache-2.0) and contributions are welcome. It
is a pure-Python package (`src/throughline_compose`, CLI `tl-compose`) that reuses
throughline as an unmodified library.

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"        # NB: resolves throughline from PyPI — see below
pytest -q
tl-compose -C idd check --strict   # this repo's own composed graph — keep it green
```

### If you are also working on throughline itself — chain the editable installs

`pip install -e ".[dev]"` makes *this* package editable and resolves
[throughline](https://github.com/rhodium-org/throughline) **from PyPI**. If you are
changing both, you will be editing compose while running the *published* core, and
every version string will still agree — so the same command in the same repo can
give you and a colleague different answers, and the argument that follows will be
about the graph rather than about the toolchain.

Check both out side by side and chain them in a **single** command, so the resolver
never reaches the index:

```sh
pip install -e ../throughline -e ".[dev]"
```

Then verify rather than assume — the path must be your checkout, not `site-packages`:

```sh
python -c "import throughline as m; print(m.__file__)"
```

Composition is especially exposed to this: a change to the seam lands in compose but
is *judged* by core's validator, so a mismatched pair silently reports findings the
other build would not. The same applies to
[throughline-ratify](https://github.com/rhodium-org/throughline-ratify), which
installs both. throughline's own
[AGENTS.md](https://github.com/rhodium-org/throughline/blob/main/AGENTS.md#working-on-more-than-one-package-at-once--chain-the-editable-installs)
carries the full recipe, including the two silent traps in `pipx inject`.

Changes here follow the same IDD discipline: ground the change in an `idd/` item
(create + ratify if new), cite the UID in your commit, and keep
`tl-compose -C idd check --strict` and `tl-compose -C idd docs --check` green.
