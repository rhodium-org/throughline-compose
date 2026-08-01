"""Report against a borrowed item only what the consumer can act on (SR-0026).

The union is validated by throughline's own unmodified validator, which knows one
graph and judges every item in it alike. That is right for the core and wrong for a
consumer: a finding about a borrowed item's internals names no act its reader can
take, because the remedy is a commit in the graph that owns the item. This module is
composition's own work over that unchanged result — it decides which findings survive
into a consumer's report, and re-puts the one grounding question that composition
changes the answer to.

Two rules, both stated in SR-0026:

  * A finding on a borrowed item survives only if its rule is a *seam* rule. The
    allowlist is deliberately the small set rather than its complement, so a rule
    added to core later is suppressed on borrowed items until someone decides it is
    actionable in a consumer. Defaulting the other way would let the next core rule
    reintroduce exactly the noise this closes.
  * An ``orphan`` on a *local* item is re-asked of core's own walk with the terminus
    widened to "a root, or anything borrowed", so a grounding chain that leaves the
    consumer and enters a source counts as grounded. No second grounding engine —
    ``Index.reaches`` already takes the predicate and the link types as arguments
    (SR-0004, NG-0001).
"""
from __future__ import annotations

# Rules whose remedy lies at the seam or in the union itself, and which therefore
# name an act the consumer can take — resolve the reference, drop the citation,
# declare the namespace, move the pin. These are reported on borrowed items too.
SEAM_RULES = frozenset({
    # The consumer's reference into a source must land on something real.
    "dangling-link",
    "deleted-link-target",
    "malformed-link",
    "namespace-unresolved",
    # The union the consumer assembled must be coherent.
    "prefix-collision",
    "uid-collision",
    # A signature on a borrowed clause no longer covering its wording is the
    # consumer's business, not only the owner's — the edition they pinned has moved
    # away from what was accepted, and the remedy (move the pin, or tell the owner)
    # is theirs to take. SR-0026 names it in the seam for that reason.
    "ratified-stale",
    # Whole-graph verdicts that belong to nobody's single item.
    "empty-graph",
    "no-status-roles",
})

# Everything else — statuses and transitions, attributes, link vocabulary and
# endpoint rules, grounding, ratification, content quality — is the owning graph's
# business and is suppressed on a borrowed item.


def is_borrowed(union, uid: str) -> bool:
    """Whether ``uid`` names an item this project borrowed through a source.

    A union item is local exactly when its UID is not a mangled, source-owned one,
    which is the same test ``check``'s own summary uses to split the two.
    """
    return union.qualified(uid) != uid


def apply_seam(findings, union, schema, index):
    """Filter ``findings`` to what the consumer can act on, and rescue local items
    grounded through a source. Returns ``(kept, suppressed, rescued)`` so the caller
    can report the verdict and a test can audit the reasoning rather than trust it.
    """
    kept, suppressed, rescued = [], [], []
    for f in findings:
        if is_borrowed(union, f.uid) and f.rule not in SEAM_RULES:
            suppressed.append(f)
            continue
        if f.rule == "orphan" and not is_borrowed(union, f.uid):
            if index.reaches(
                f.uid,
                lambda it: schema.is_root(it) or is_borrowed(union, it.uid),
                schema.ground_link_types,
            ):
                rescued.append(f)
                continue
        kept.append(f)
    return kept, suppressed, rescued
