# throughline-compose

**Compose one requirements graph from many reusable
[throughline](https://github.com/rhodium-org/throughline) sources** — a house style
guide, a platform standard, a regulatory baseline — alongside the requirements you
write yourself, and work the combined graph as one.

This repository is itself a throughline project: its own design is captured as a
grounded IDD spine of <!-- tl:count.inline type == 'user_requirement' -->7<!-- tl:end --> user requirements and <!-- tl:count.inline type == 'system_requirement' -->27<!-- tl:end --> system requirements 
under [`idd/vision/`](https://github.com/rhodium-org/throughline-compose/tree/main/idd/vision), [`idd/goals/`](https://github.com/rhodium-org/throughline-compose/tree/main/idd/goals),
[`idd/user-requirements/`](https://github.com/rhodium-org/throughline-compose/tree/main/idd/user-requirements),
[`idd/system-requirements/`](https://github.com/rhodium-org/throughline-compose/tree/main/idd/system-requirements), and [`idd/non-goals/`](https://github.com/rhodium-org/throughline-compose/tree/main/idd/non-goals), and
published to [`idd/docs/spec.md`](https://github.com/rhodium-org/throughline-compose/blob/main/idd/docs/spec.md). The graph is gated by `tl-compose -C idd check
--strict` and the document by `tl-compose -C idd docs --check`; these two counts are
rendered from the live spine by the `tl:count` directive, so they cannot drift.

> **Status: alpha.** The composition engine is built. `tl-compose -C idd check` composes the
> declared `[[sources]]` into a union graph and validates it, and `tl-compose -C idd docs`
> renders the published document over that same union, resolving borrowed
> (`namespace:UID`) targets ([SR-0007](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0007.yml)). Each source
> resolves from either a local `path` or a pinned git `url` + `ref` into a per-user
> cache ([SR-0006](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0006.yml)). Still pending: the
> `tl-compose source add/update/pin` subcommands for managing source declarations from
> the CLI (today you edit the `[[sources]]` tables by hand).

## The idea

A team should be able to adopt standard requirement sets *by reference*, not by
copy-paste, and receive upstream revisions without ever forking. Two identity rules
make that safe:

- **Imported items keep their source-native UID** ([SR-0002](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0002.yml)).
  Composition never renumbers or copies. Canonical identity is the pair
  `(source-namespace, UID)`, so the same `SR-0001` may legitimately exist in two
  sources without collision — the immutable-UID rule is never violated.
- **The composer controls the namespaces** ([SR-0001](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0001.yml)).
  The consumer's own `throughline.toml` binds each source to a short name it chooses
  (`import X as Y`). A qualified reference like `gds:SR-0001` denotes a borrowed item;
  a bare UID is always local. Renaming a namespace is a local-only change with a
  bounded blast radius.

## Declaring sources

A consumer names the sources it composes in an array of `[[sources]]` tables in its
own `throughline.toml`. Each entry binds a `namespace` to one source, located either
by a pinned git `url` or by a local `path` ([SR-0006](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0006.yml)):

```toml
# Adopt a published standard by reference, pinned to an edition.
[[sources]]
namespace = "asvs"
url = "https://github.com/rhodium-org/throughline-asvs"
ref = "v4.0.3"                       # a git tag (normal form), branch, or commit SHA

# Develop a source and its consumer side by side.
[[sources]]
namespace = "house-style"
path = "../house-style"              # a directory relative to this project
```

- **`url` + `ref` is the durable, shareable form.** The `ref` pins the exact edition
  — normally a release tag, but any git ref (branch or commit SHA) works. `tl-compose`
  fetches the source from its origin on first use into a per-user cache that lives
  *outside* any project tree (`$TL_COMPOSE_CACHE`, else `$XDG_CACHE_HOME`, else
  `~/.cache/throughline-compose/sources/`), keyed by `(url, ref)`. Resolution is
  idempotent and offline thereafter: a source already cached at the pinned ref is
  reused, never refetched. Nothing is vendored into your repo, so your own item scan
  never ingests a borrowed graph.
- **`path` is for local development.** A directory, relative to the consumer, for
  working on a source alongside the project that consumes it.
- **The two are mutually exclusive, and a `url` must carry a `ref`.** Declaring both
  `path` and `url`, or a `url` with no `ref`, is rejected at check time — a dependency
  can never silently track a moving default. (A `ref` alongside a `path` is likewise
  rejected: a ref only pins a `url`.)

### Re-exporting a transitive source

Composition is one level deep and flat: if a source you adopt *itself* cites another
namespace — say `house-style` internally references `asvs:SR-0001` — that `asvs` must
be a namespace *your* consumer also declares, or the compose fails on an undeclared
namespace. A **re-export** lets you pull that transitive source forward through the
intermediate one without restating its `url`/`ref`
([SR-0014](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0014.yml)):

```toml
[[sources]]
namespace = "house-style"
path = "../house-style"
reexport = ["asvs"]                   # pull house-style's `asvs` forward, same name
```

The re-exported source **inherits the intermediate source's pin** — you do not (and
cannot) restate its edition here; it is whatever `house-style` itself declared. An
array re-exports each namespace under its own name; a table binds a
consumer-chosen **alias** instead ([UR-0005](https://github.com/rhodium-org/throughline-compose/blob/main/idd/user-requirements/UR-0005.yml)):

```toml
reexport = { asvs = "owasp" }         # the same source, bound in your union as `owasp`
```

Every reference the intermediate source wrote against its own label (`asvs:SR-0001`)
resolves to the aliased union namespace. Re-export is opt-in and per-namespace:
nothing is hoisted automatically, so adopting a source never silently expands your
union.

**A namespace bound to two different editions fails fast** — never a silent merge or
an arbitrary winner ([SR-0015](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0015.yml)). If you declare
`asvs` directly at one `ref` and also re-export a source's `asvs` at a different
edition, the compose stops and names both the *why* (the same namespace reaches your
union at two editions) and the *fix* (pin `asvs` explicitly to one edition, or alias
the two apart so they coexist).

Moving to a new upstream edition is a one-line change to the `ref`; the borrowed graph
is never edited. See [`rhodium-org/idd-example`](https://github.com/rhodium-org/idd-example)
for a complete worked consumer that adopts `throughline-asvs` this way.

## One tool, one set of guarantees

In a composed project you drive everything through **`tl-compose`**, never `tl`
directly ([UR-0002](https://github.com/rhodium-org/throughline-compose/blob/main/idd/user-requirements/UR-0002.yml)). The architecture keeps that
honest:

- **`tl-compose` is a strict superset of `tl`** ([SR-0003](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0003.yml)).
  Local-graph commands are forwarded to the throughline library unchanged; the
  union-aware `check` and `docs` are overridden to compose, validate, and render the
  combined graph. (The `source` subcommands for editing declarations are the remaining
  superset surface — see the status note above.) The core command set is obtained
  programmatically, so the two surfaces cannot drift apart.
- **Composition reuses throughline unchanged** ([SR-0004](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0004.yml)).
  It merges the sources into one in-memory `Project` and runs throughline's existing
  `validate`, `Index`, and `fingerprint` over that union — no second validation
  engine. A composed graph is exactly as sound as a native one.
- **Bare `tl check` fails fast on unresolved cross-source refs**
  ([SR-0005](https://github.com/rhodium-org/throughline-compose/blob/main/idd/system-requirements/SR-0005.yml)). If you run core `tl` in a composed
  repo by habit, a namespace-qualified reference it cannot resolve makes it stop and
  point you at `tl-compose` — never a false clean result. Free external references (a
  URL, a linked standard) stay opaque, as intended.

Composition deliberately lives here, not in the throughline core
([NG-0001](https://github.com/rhodium-org/throughline-compose/blob/main/idd/non-goals/NG-0001.yml)) — the core stays a single-purpose, offline tool
over one graph, consumed here as a library.

## Working here

```sh
pip install .                  # pulls throughline transitively; installs tl and tl-compose
tl-compose -C idd context      # agent brief, generated from idd/throughline.toml
tl-compose -C idd check --strict # gate the whole graph
tl-compose -C idd docs --check # gate published-document freshness
tl-compose -C idd docs         # regenerate idd/docs/spec.md from the graph
```

## License

Created by Dr Henry J Grech-Cini ([ORCID 0009-0007-1565-7530](https://orcid.org/0009-0007-1565-7530)).
Copyright © 2026 Henry J Grech-Cini. Released under the Apache License 2.0 — see
[`LICENSE`](https://github.com/rhodium-org/throughline-compose/blob/main/LICENSE) and [`NOTICE`](https://github.com/rhodium-org/throughline-compose/blob/main/NOTICE).
