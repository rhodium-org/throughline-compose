# throughline-compose

The **composition** design for [throughline](https://github.com/rhodium-org/throughline):
how one project's requirements graph is *assembled* from many reusable sources
instead of re-authored.

This repository is itself a throughline project — its design is captured as a
grounded IDD spine under [`vision/`](vision), [`goals/`](goals),
[`user-requirements/`](user-requirements), and
[`system-requirements/`](system-requirements), and published to
[`docs/spec.md`](docs/spec.md). `tl check --strict` gates the graph and
`tl docs --check` gates the document's freshness.

## The idea

A team should be able to pull in existing throughlines — a house style guide, a
platform standard, a regulatory baseline — alongside the requirements they write
themselves, and work against the combined graph as one. Two rules make that safe:

- **Imported items keep their source-native UID** ([SR-0002](system-requirements/SR-0002.yml)).
  Composition never renumbers or copies. Canonical identity is the pair
  `(source-namespace, UID)`, so the same `SR-0001` may legitimately exist in two
  sources without collision — the immutable-UID rule is never violated.
- **The composer controls the namespaces** ([SR-0001](system-requirements/SR-0001.yml)).
  The consumer's own `throughline.toml` binds each source to a short name it
  chooses (`import X as Y`). A qualified reference like `gds:SR-0001` denotes a
  borrowed item; a bare UID is always local. Renaming a namespace is a
  local-only change with a bounded blast radius.

## Working here

```sh
pip install throughline
tl context           # agent brief, generated from throughline.toml
tl check --strict    # gate the whole graph
tl docs --check      # gate published-document freshness
tl docs              # regenerate docs/spec.md from the graph
```
