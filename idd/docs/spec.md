# throughline-compose — specification

This project's own IDD, self-hosted. The item blocks below are **generated from
the graph** by `tl docs`; the section headings are the only hand-owned structure.
Regenerate with `tl docs` and gate freshness in CI with `tl docs --check`.

## Intent

<!-- tl:item INT-0001 -->
**INT-0001 — One project IDD composed from many reusable sources** — `intent`, status `ratified`

> A project's requirements graph is assembled, not re-authored. A team pulls in one or more existing sources — a house style guide, a platform standard, a regulatory baseline, most often themselves throughlines — alongside the requirements they write themselves, and works against the combined graph as if it were one. A source need not itself be a throughline — what matters is that it can be presented in throughline shape and kept separately versioned. Reuse never copies or renumbers the borrowed items — each keeps the permanent identity it was born with in its own source, so the combined graph is a view over independent, separately versioned sources rather than a fork of them.

**origin**: human · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:46eafa77e454450e76acf848a8227f98ca6aa108991f2657379cbe8aaadda8b1 · **ratified_backfilled**: True
<!-- tl:end -->

## Business need

<!-- tl:item BN-0001 -->
**BN-0001 — Reuse standard IDDs without re-authoring** — `business_need`, status `ratified`

> Standard requirement sets — GDS service standards, a security baseline, a platform's tenancy rules — should be adopted by reference, not by copy-paste. A consumer project must be able to depend on such a source, ground its own items onto items in that source, and receive upstream revisions, without ever forking or re-numbering the borrowed graph.

*Derives from:* INT-0001

**origin**: human · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:0da5f16328bf4ba7117e8d60c89397a91a1d814a0557529d9285bd2f9e631d31 · **ratified_backfilled**: True
<!-- tl:end -->

<!-- tl:item BN-0002 -->
**BN-0002 — A composed project is as trustworthy and frictionless as a native one** — `business_need`, status `ratified`

> Adoption depends on the composed project feeling like one project, not a toolchain. Working it should carry the same soundness guarantees a single throughline gives — the same validator, the same fail-fast on a broken graph — and should not impose a mental tax of remembering which tool does what or reasoning about the consequences of choosing wrong. If composition is more effort or less trustworthy than working native requirements, teams will copy-paste the sources instead, defeating the whole purpose.

*Derives from:* INT-0001

**origin**: human · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:0ba0ff70e6472758c174a7d5331d4b149bcf075f891a4581858d6c93609020db · **ratified_backfilled**: True
<!-- tl:end -->

## User requirements

<!-- tl:item UR-0001 -->
**UR-0001 — The composer controls source namespaces** — `user_requirement`, status `ratified`

> The consumer project — not the sources — shall decide the short name by which each source is referenced. When a project pulls in two sources it shall be able to bind one to the namespace "gds" and the other to "public-facing" in its own configuration, and thereafter refer to a borrowed item as "gds:SR-0001". Changing a namespace later is the composer's prerogative; they accept that generated documents change to match. Sources shall not need to know, agree on, or coordinate the names their consumers give them.

*Derives from:* BN-0001

**origin**: human · **priority**: must · **verification**: demonstration · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:9795c51b85c78f5c1ec224f3c0ab25df4e1739ffdae250907a61cecba0d8f2a7 · **ratified_backfilled**: True
<!-- tl:end -->

<!-- tl:item UR-0002 -->
**UR-0002 — A composed project is worked as one — one tool, one set of guarantees** — `user_requirement`, status `ratified`

> In a composed project the composer shall drive everything through a single command surface, never having to decide which of two tools performs a given action or to reason about the consequences of choosing wrong. Every operation available on a standalone throughline shall be available, unchanged, on the composed one; the composed graph shall be validated by exactly the same rules as a standalone graph; and no path shall let the composer receive a false clean result that hides an unresolved cross-source reference.

*Derives from:* BN-0002

**origin**: human · **priority**: must · **verification**: demonstration · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:06a6cc5243475631b13130bccca2d8f287f5a03ad3088e650c642e132159d726 · **ratified_backfilled**: True
<!-- tl:end -->

<!-- tl:item UR-0003 -->
**UR-0003 — A source is referenced by origin and pinned to an edition** — `user_requirement`, status `ratified`

> The consumer shall be able to name each source by where it lives — a git URL it can be fetched from — and pin the exact edition it depends on by a git ref, normally a tag. Composition against a pinned source shall be reproducible run to run and machine to machine, and adopting an upstream revision shall be a matter of moving the pin, never of editing the borrowed graph. A local filesystem path shall remain valid for developing a source and its consumer side by side, but the durable, shareable form of a dependency is an origin plus a pinned ref.

*Derives from:* BN-0001

**origin**: human · **priority**: must · **verification**: demonstration · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:9fd43fa2aef06d845f7d74ac4373983fcecab8955343c0db6988366c8a2bbe06 · **ratified_backfilled**: True
<!-- tl:end -->

## System requirements

<!-- tl:item SR-0001 -->
**SR-0001 — Importer-assigned source namespaces in the consumer toml** — `system_requirement`, status `ratified`

> The consumer project shall declare each source it composes in its own throughline.toml, binding that source to a namespace the consumer chooses — the "import X as Y" model. A reference to a borrowed item is written with that namespace as a qualifier (for example gds:SR-0001); a bare, unqualified UID always denotes a local item. The binding is the single point of control — the blast radius of renaming a namespace, or repointing it at a different source, is confined to the consumer's own configuration and the documents it generates, and touches nothing in any source. Input shall be lenient in that a bare UID that is locally defined is never ambiguous; output — generated documents, exports, matrices — shall always render cross-source references in fully qualified form so a reader can tell at a glance which source an item came from.

*Rationale:* A consultant standing up a new GDS-compliant service pulls in the GDS standard and a public-facing baseline and wants to name them "gds" and "public-facing" without asking either source's authors for permission. Self-declared source identity would force every source to pick a globally unique name and would break the moment two projects disagreed; importer-assigned namespaces put naming where the authority actually is — with the composer — and keep each source reusable by any number of consumers under any number of local names.

*Implements:* UR-0001

**origin**: human · **priority**: must · **verification**: demonstration · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:859afe02ce86da271a44cfc95b463a1507ac16cb62c4b41deef05187c91e87f9 · **ratified_backfilled**: True
<!-- tl:end -->

<!-- tl:item SR-0002 -->
**SR-0002 — Imported items keep their source-native UID** — `system_requirement`, status `ratified`

> An item pulled in from a source shall retain the exact UID it holds in that source; composition shall never renumber, remint, or copy it. The canonical identity of any item in the combined graph is the pair (source-namespace, UID) — the local project being one source among several. Because identity is a pair, the same bare UID occurring in two different sources (both may legitimately hold an SR-0001) is not a collision; the two are distinguished by their namespaces. A reference that is ambiguous — a bare UID that matches items in more than one source, or a qualified UID whose namespace is unbound — shall fail fast at check time rather than resolve silently to one candidate. Rebuilding the combined graph from unchanged sources shall be idempotent — no identity in the result depends on scan order, register position, or how many items a source has accumulated since.

*Rationale:* The immutable-UID rule is the foundation the whole tool rests on, and any scheme that re-derived a fresh sequential index across composed sources would break it the instant a source gained an item — the same real requirement would silently change number. Anchoring identity to the source-native UID and qualifying by namespace keeps every borrowed item's identity permanent and makes cross-source same-number coexistence a normal, expected condition rather than an error to reconcile.

*Implements:* UR-0001

**origin**: human · **priority**: must · **verification**: test · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:2f49c1a5eecfa987a8478fc79c84e66ac6d93969f03dab275afbf22d27fa6826 · **ratified_backfilled**: True
<!-- tl:end -->

<!-- tl:item SR-0003 -->
**SR-0003 — tl-compose is a strict superset of tl** — `system_requirement`, status `ratified`

> The composition CLI (`tl-compose`) shall expose every command of the core `tl` CLI, so that a composer in a composed project uses `tl-compose` for everything and never invokes `tl` directly. Commands that concern only the local graph (authoring, ratifying) shall be forwarded to the throughline library unchanged; only the commands whose meaning changes under composition — chiefly `check`, `docs` and `trace`, which must operate over the merged graph — shall be overridden, and `tl-compose` shall add the commands composition introduces (declaring, pinning, and updating sources). `tl-compose` shall obtain the core command set programmatically from the throughline library rather than re-declaring it, so a new core subcommand appears in `tl-compose` automatically and the two surfaces cannot drift apart.

*Rationale:* An earlier design split the work — `tl` for local actions, `tl-compose` for source-aware ones — but that forces the composer to learn a mapping and to reason about the consequences of running the wrong one, exactly the friction BN-0002 rejects. Making `tl-compose` a strict superset removes the decision — in a composed repo there is one surface. Composing the core command set programmatically keeps that superset honest as `tl` evolves, at no maintenance cost.

*Implements:* UR-0002
*Relates:* NG-0001

**origin**: human · **priority**: must · **verification**: demonstration · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:2b373a00ffea9407880e36f7a13cafd8cec6ed58c4acf2bb89d8192a66dadc34 · **ratified_backfilled**: True
<!-- tl:end -->

<!-- tl:item SR-0004 -->
**SR-0004 — Composition reuses the throughline library unchanged** — `system_requirement`, status `ratified`

> throughline-compose shall depend on `throughline` as a pinned library and build the composed graph by merging the sources' items and links into one in-memory `Project`, then run throughline's existing `validate`, `Index`, and `fingerprint` over that union without modification. Composition shall add no second validation engine, no forked copy of the graph model, and no divergent notion of soundness — the rules that hold for a standalone throughline are, by construction, the rules that hold for the composed one. Where composition must extend behaviour (resolving a namespace qualifier to a source's item before validation runs) it shall do so by preparing the union that the unchanged core then checks, not by reimplementing the check.

*Rationale:* The single strongest guarantee composition can offer is that a composed graph is exactly as sound as a native one (UR-0002, BN-0002). The cheapest and most durable way to guarantee that is to not reimplement it — reuse the same validator the core already ships and trusts. throughline's public surface (`Project`, `Index`, `validate`, `fingerprint`, `load_project`, the grounding ops) is deliberately shaped for exactly this kind of library consumer, so composition is assembly plus a thin resolution step, not a second engine. This is also what keeps composition out of the core (NG-0001) — core stays the one implementation of the rules.

*Implements:* UR-0002
*Relates:* NG-0001

**origin**: human · **priority**: must · **verification**: test · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:f0c0b60e3d61ae9af1439b398941c5501f6829a7b4d2c90d9f18d1b566d77138 · **ratified_backfilled**: True
<!-- tl:end -->

<!-- tl:item SR-0005 -->
**SR-0005 — Bare tl check fails fast on unresolved namespace-qualified references** — `system_requirement`, status `ratified`

> A namespace-qualified reference (for example `gds:SR-0001`) asserts that its target resolves inside a declared source namespace. The core `tl` does no composition and cannot resolve such a reference, so when `tl check` encounters one it shall fail fast with a message that points the user to `tl-compose`, rather than treat it as an opaque external and report a clean graph. Core shall reach this verdict from the reference's syntax alone — it shall not read the consumer's source configuration and shall remain entirely source-unaware. This rule is scoped to the namespace-qualified form only — a free external target such as a URL or a deliberately out-of-graph pointer (a linked standard, an issue tracker) shall stay opaque and shall not fail the check, because being unresolvable is that form's intended purpose. The resolving `tl-compose check` shall then do the real work — bind the namespace to its pinned source, confirm the target exists, and confirm the link is type-legal over the union.

*Rationale:* Without this rule a composer who ran bare `tl` in a composed repo — by habit or because a hook is wired to it — would get a false clean result that hides a dangling or type-illegal cross-source link, the silent-wrong outcome UR-0002 forbids. Failing fast turns the wrong tool into a signpost to the right one. The scope carve- out matters — a blanket rule of fail on anything unresolvable would break the legitimate and common practice of linking a requirement to an external standard or ticket, so the trigger is the namespace-qualified syntax specifically, which is why that syntax (SR-0001) is kept a distinct first-class token rather than folded into the external-reference form.

*Implements:* UR-0002
*Relates:* SR-0001

**origin**: human · **priority**: must · **verification**: test · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:d27afad348b2ba169790426f34ba0feec33f4fba41a72d7fa034d454ff3c587c · **ratified_backfilled**: True
<!-- tl:end -->

<!-- tl:item SR-0006 -->
**SR-0006 — Sources resolve from a pinned git URL into a local cache** — `system_requirement`, status `ratified`

> Each source entry shall accept, in place of a local path, a git URL together with a ref that pins the edition — a tag, branch, or commit — a tag being the normal form, since a source publishes its editions as tags. On check, tl-compose shall materialise each URL-pinned source by fetching that exact ref into a cache that lives outside the consumer's own project tree, keyed by the origin URL and ref, and compose from that checkout. The cache being outside the project tree is load-bearing, not incidental — the consumer's own item scan walks its whole directory, so a resolved source placed inside it would be wrongly ingested as local items; the cache is a shared, per-user store (like a package manager's) that no project scan ever sees. A source already present at the pinned ref shall not be refetched, so resolution is idempotent and offline after the first fetch. A url and a path shall be mutually exclusive for one source, and a url without a ref shall fail fast rather than silently track a moving default.

*Implements:* UR-0003

**origin**: human · **priority**: must · **verification**: test · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:7fa15eb0be77695296a19ae1b7ca208f4b963234df76a22ba81d551fe4043663 · **ratified_backfilled**: True
<!-- tl:end -->

## Non-goals

<!-- tl:item NG-0001 -->
**NG-0001 — Composition is not built into the tl core** — `non_goal`, status `ratified`

> Composition — source declaration, pinning, fetching, and merging — is deliberately not added to the `throughline` core or its `tl` command. The core stays a single-purpose, offline-by-default, self-contained tool over one graph; the network, lockfile, untrusted-source, and union concerns live entirely in throughline-compose, which consumes the core as a library. The only concession the core makes to composition is recognising the namespace-qualified reference syntax so it can fail fast on one (SR-0005) — it gains no ability to resolve, fetch, or merge. This is recorded negative space — it exists to keep later design honest, so that a proposal to "just add sources to tl" is measured against a decision already taken rather than reopened by default.

**origin**: human · **ratified_by**: Henry Grech-Cini · **ratified_fingerprint**: sha256:81fa00856e0b72a1b81005b3d7fd1e8997d99c15c50e1186299bbd62c0e59514 · **ratified_backfilled**: True
<!-- tl:end -->

## Traceability

Every user requirement maps to the system requirements that `implements` it.
The table is generated from the graph, so it cannot drift from the actual links.

<!-- tl:matrix incoming:implements type == 'user_requirement' -->
| UID | Title | Implements (incoming) |
|---|---|---|
| UR-0001 | The composer controls source namespaces | SR-0001, SR-0002, SR-0024 |
| UR-0002 | A composed project is worked as one — one tool, one set of guarantees | SR-0003, SR-0004, SR-0005, SR-0007, SR-0010, SR-0016, SR-0019, SR-0020, SR-0022, SR-0023 |
| UR-0003 | A source is referenced by origin and pinned to an edition | SR-0006, SR-0008, SR-0018 |
| UR-0004 | Non-git authorities are composed through pluggable resolvers | SR-0011, SR-0012, SR-0013 |
| UR-0005 | Transitive sources are pulled forward by re-export and alias, never silently merged | SR-0014, SR-0015 |
| UR-0006 | Composing tolerates a source at an older on-disk format major | SR-0017 |
| UR-0007 | The published distribution is trustworthy out of the box | SR-0021 |
<!-- tl:end -->
