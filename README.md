# throughline-compose

**Compose one requirements graph from many reusable
[throughline](https://github.com/rhodium-org/throughline) sources** — a house style
guide, a platform standard, a regulatory baseline — alongside the requirements you
write yourself, and work the combined graph as one.

This repository is itself a throughline project: its own design is captured as a
grounded IDD spine under [`vision/`](vision), [`goals/`](goals),
[`user-requirements/`](user-requirements),
[`system-requirements/`](system-requirements), and [`non-goals/`](non-goals), and
published to [`docs/spec.md`](docs/spec.md). The graph is gated by `tl-compose check
--strict` and the document by `tl-compose docs --check`.

> **Status: alpha.** The composition engine is built: `tl-compose check` composes the
> declared `[[sources]]` into a union graph and validates it, and each source resolves
> from either a local `path` or a pinned git `url` + `ref` into a per-user cache
> ([SR-0006](system-requirements/SR-0006.yml)). Still pending: union-aware
> `tl-compose docs` (a document over the composed union — `docs` today covers the local
> graph only) and the `tl-compose source add/update/pin` subcommands.

## The idea

A team should be able to adopt standard requirement sets *by reference*, not by
copy-paste, and receive upstream revisions without ever forking. Two identity rules
make that safe:

- **Imported items keep their source-native UID** ([SR-0002](system-requirements/SR-0002.yml)).
  Composition never renumbers or copies. Canonical identity is the pair
  `(source-namespace, UID)`, so the same `SR-0001` may legitimately exist in two
  sources without collision — the immutable-UID rule is never violated.
- **The composer controls the namespaces** ([SR-0001](system-requirements/SR-0001.yml)).
  The consumer's own `throughline.toml` binds each source to a short name it chooses
  (`import X as Y`). A qualified reference like `gds:SR-0001` denotes a borrowed item;
  a bare UID is always local. Renaming a namespace is a local-only change with a
  bounded blast radius.

## One tool, one set of guarantees

In a composed project you drive everything through **`tl-compose`**, never `tl`
directly ([UR-0002](user-requirements/UR-0002.yml)). The architecture keeps that
honest:

- **`tl-compose` is a strict superset of `tl`** ([SR-0003](system-requirements/SR-0003.yml)).
  Local-graph commands are forwarded to the throughline library unchanged; the
  union-aware `check` is overridden to compose and validate the combined graph.
  (Union-aware `docs` and the `source` subcommands are the remaining superset surface —
  see the status note above.) The core command set is obtained programmatically, so the
  two surfaces cannot drift apart.
- **Composition reuses throughline unchanged** ([SR-0004](system-requirements/SR-0004.yml)).
  It merges the sources into one in-memory `Project` and runs throughline's existing
  `validate`, `Index`, and `fingerprint` over that union — no second validation
  engine. A composed graph is exactly as sound as a native one.
- **Bare `tl check` fails fast on unresolved cross-source refs**
  ([SR-0005](system-requirements/SR-0005.yml)). If you run core `tl` in a composed
  repo by habit, a namespace-qualified reference it cannot resolve makes it stop and
  point you at `tl-compose` — never a false clean result. Free external references (a
  URL, a linked standard) stay opaque, as intended.

Composition deliberately lives here, not in the throughline core
([NG-0001](non-goals/NG-0001.yml)) — the core stays a single-purpose, offline tool
over one graph, consumed here as a library.

## Working here

```sh
pip install .            # pulls throughline transitively; installs tl and tl-compose
tl-compose context       # agent brief, generated from throughline.toml
tl-compose check --strict # gate the whole graph
tl-compose docs --check  # gate published-document freshness
tl-compose docs          # regenerate docs/spec.md from the graph
```
