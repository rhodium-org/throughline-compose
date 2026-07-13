# throughline-compose — specification

This project's own IDD, self-hosted. The item blocks below are **generated from
the graph** by `tl docs`; the section headings are the only hand-owned structure.
Regenerate with `tl docs` and gate freshness in CI with `tl docs --check`.

## Intent

<!-- tl:item INT-0001 -->
**INT-0001 — One project IDD composed from many reusable sources** — `intent`, status `approved`

> A project's requirements graph is assembled, not re-authored. A team pulls in one or more existing throughlines — a house style guide, a platform standard, a regulatory baseline — alongside the requirements they write themselves, and works against the combined graph as if it were one. Reuse never copies or renumbers the borrowed items — each keeps the permanent identity it was born with in its own source, so the combined graph is a view over independent, separately versioned sources rather than a fork of them.

**origin**: human
<!-- tl:end -->

## Business need

<!-- tl:item BN-0001 -->
**BN-0001 — Reuse standard IDDs without re-authoring** — `business_need`, status `approved`

> Standard requirement sets — GDS service standards, a security baseline, a platform's tenancy rules — should be adopted by reference, not by copy-paste. A consumer project must be able to depend on such a source, ground its own items onto items in that source, and receive upstream revisions, without ever forking or re-numbering the borrowed graph.

**origin**: human
<!-- tl:end -->

## User requirements

<!-- tl:item UR-0001 -->
**UR-0001 — The composer controls source namespaces** — `user_requirement`, status `approved`

> The consumer project — not the sources — shall decide the short name by which each source is referenced. When a project pulls in two sources it shall be able to bind one to the namespace "gds" and the other to "public-facing" in its own configuration, and thereafter refer to a borrowed item as "gds:SR-0001". Changing a namespace later is the composer's prerogative; they accept that generated documents change to match. Sources shall not need to know, agree on, or coordinate the names their consumers give them.

**origin**: human · **priority**: must · **verification**: demonstration
<!-- tl:end -->

## System requirements

<!-- tl:item SR-0001 -->
**SR-0001 — Importer-assigned source namespaces in the consumer toml** — `system_requirement`, status `approved`

> The consumer project shall declare each source it composes in its own throughline.toml, binding that source to a namespace the consumer chooses — the "import X as Y" model. A reference to a borrowed item is written with that namespace as a qualifier (for example gds:SR-0001); a bare, unqualified UID always denotes a local item. The binding is the single point of control — the blast radius of renaming a namespace, or repointing it at a different source, is confined to the consumer's own configuration and the documents it generates, and touches nothing in any source. Input shall be lenient in that a bare UID that is locally defined is never ambiguous; output — generated documents, exports, matrices — shall always render cross-source references in fully qualified form so a reader can tell at a glance which source an item came from.

*Rationale:* A consultant standing up a new GDS-compliant service pulls in the GDS standard and a public-facing baseline and wants to name them "gds" and "public-facing" without asking either source's authors for permission. Self-declared source identity would force every source to pick a globally unique name and would break the moment two projects disagreed; importer-assigned namespaces put naming where the authority actually is — with the composer — and keep each source reusable by any number of consumers under any number of local names.

**origin**: human · **priority**: must · **verification**: demonstration
<!-- tl:end -->

<!-- tl:item SR-0002 -->
**SR-0002 — Imported items keep their source-native UID** — `system_requirement`, status `approved`

> An item pulled in from a source shall retain the exact UID it holds in that source; composition shall never renumber, remint, or copy it. The canonical identity of any item in the combined graph is the pair (source-namespace, UID) — the local project being one source among several. Because identity is a pair, the same bare UID occurring in two different sources (both may legitimately hold an SR-0001) is not a collision; the two are distinguished by their namespaces. A reference that is ambiguous — a bare UID that matches items in more than one source, or a qualified UID whose namespace is unbound — shall fail fast at check time rather than resolve silently to one candidate. Rebuilding the combined graph from unchanged sources shall be idempotent — no identity in the result depends on scan order, register position, or how many items a source has accumulated since.

*Rationale:* The immutable-UID rule is the foundation the whole tool rests on, and any scheme that re-derived a fresh sequential index across composed sources would break it the instant a source gained an item — the same real requirement would silently change number. Anchoring identity to the source-native UID and qualifying by namespace keeps every borrowed item's identity permanent and makes cross-source same-number coexistence a normal, expected condition rather than an error to reconcile.

**origin**: human · **priority**: must · **verification**: test
<!-- tl:end -->

## Traceability

Every user requirement maps to the system requirements that `implements` it.
The table is generated from the graph, so it cannot drift from the actual links.

<!-- tl:matrix incoming:implements type == 'user_requirement' -->
| UID | Title | Implements (incoming) |
|---|---|---|
| UR-0001 | The composer controls source namespaces | SR-0001, SR-0002 |
<!-- tl:end -->
