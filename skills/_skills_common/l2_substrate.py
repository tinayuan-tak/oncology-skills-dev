"""Query the L2 record-grain substrate: group emitted claim_records by their context join key.

This is the FIRST consumer of the ``claim_record.context`` / ``identity`` block that the
tumor-presence pilot began emitting into ``evidence_package.json`` (contracts #804 decision #4,
populated in ``dispatcher._attach_l2_claim_record``). #804 shipped the schema; item 2 of the
substrate arc started *emitting* the join key; this module starts *reading* it — the step that turns
a flat pile of emitted packages from "the substrate exists" into "the substrate is queryable".

Two primitives:
  ``extract_records(packages)``      — pull the (optional) ``claim_record`` out of a collection of
                                       emitted package dicts, tolerating its absence (emission is
                                       best-effort: an unresolved hgnc_id / missing digest leaves a
                                       package with no record — see ``_attach_l2_claim_record``).
  ``group_records_by_context(...)``  — group records by any subset of the 4 context dimensions.

Grouping is SCOPE-AWARE by construction. Because each context dimension carries its own scope
(``SPECIFIC`` / ``ALL`` / ``NOT_STRATIFIED``) and the group key is the *canonical JSON of the
selected sub-context*, an ``ALL`` (pan-cancer / pan-subtype) claim can never silently share a bucket
with a ``SPECIFIC`` one — the empty-join that the indication-sentinel precedent records. Keys and
group order are DETERMINISTIC (canonical serialization + sorted iteration), so a view built from a
fixed set of records is byte-stable and golden-able.

Records that carry no usable ``context`` land in an explicit ``UNKEYED`` bucket rather than being
dropped — the same fail-soft posture the report IR takes (an empty slot becomes a visible
``unmeasured`` block, never silence).
"""

from __future__ import annotations

from typing import Iterable

# Reused, never re-spelled: the group key must serialize a sub-context byte-identically to the way
# derive_l2_identity serializes the full context, so a substrate key and an identity recompute can
# never disagree. Importing the single pinned serializer is the whole point (cf. _l2_canonical_json's
# own docstring: "Defined ONCE and reused ... so a context_id and its record_revision_id can never
# disagree on serialization").
from .claim_record import _l2_canonical_json

# The closed set of context dimensions, in the schema's declared order. A query may select any
# non-empty subset; an unknown name is a programming error (raise), not a silent empty view.
CONTEXT_DIMS: tuple[str, ...] = ("target", "indication", "subtype", "modality")

# Reserved bucket for records missing a usable context. A control character prefix keeps it from
# ever colliding with a real canonical-JSON key (which always begins with '{').
UNKEYED: str = "\x00unkeyed"


def extract_records(packages: Iterable[dict]) -> list[dict]:
    """Collect the ``claim_record`` blocks out of an iterable of emitted package dicts.

    Tolerates packages with no record (emission is best-effort) and non-dict junk. Order is
    preserved so a caller feeding packages in a deterministic order gets deterministic records.
    """
    out: list[dict] = []
    for pkg in packages or []:
        if not isinstance(pkg, dict):
            continue
        rec = pkg.get("claim_record")
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _selected_subcontext(context: dict, dims: tuple[str, ...]) -> dict | None:
    """The sub-mapping of ``context`` restricted to ``dims``. Returns None when the record carries no
    value for *every* selected dimension — such a record cannot be keyed and belongs in UNKEYED. A
    record missing *some* (but not all) selected dims still keys, on the dims it has, so a partially
    populated substrate degrades gracefully rather than collapsing everything into UNKEYED."""
    if not isinstance(context, dict):
        return None
    sub = {d: context[d] for d in dims if d in context and context[d] is not None}
    return sub or None


def group_records_by_context(
    records: Iterable[dict],
    dims: tuple[str, ...] = ("target",),
) -> dict[str, dict]:
    """Group L2 claim_records by the canonical key of their selected context dimensions.

    Returns an insertion-ordered mapping ``{key: {"context": <selected sub-context>, "records":
    [...]}}`` where groups are ordered by their canonical key (sorted), and the ``UNKEYED`` group,
    when present, always sorts last. Within a group, record order follows input order (stable).

    ``dims`` selects the grouping grain: ``("target",)`` answers "all records per target";
    ``("target", "indication")`` answers "per target-in-indication"; the full 4-tuple keys on the
    entire join context (one bucket per distinct logical claim context).
    """
    if not dims:
        raise ValueError("group_records_by_context: dims must name at least one context dimension")
    unknown = [d for d in dims if d not in CONTEXT_DIMS]
    if unknown:
        raise ValueError(f"group_records_by_context: unknown context dimension(s) {unknown!r}; allowed {CONTEXT_DIMS}")

    # Accumulate into keyed buckets first (input order within a bucket), then emit in sorted-key
    # order so the view is deterministic regardless of record arrival order.
    buckets: dict[str, dict] = {}
    for rec in records or []:
        context = rec.get("context") if isinstance(rec, dict) else None
        sub = _selected_subcontext(context, dims)
        if sub is None:
            key = UNKEYED
            group_context: dict = {}
        else:
            key = _l2_canonical_json(sub)
            group_context = sub
        slot = buckets.get(key)
        if slot is None:
            slot = buckets[key] = {"context": group_context, "records": []}
        slot["records"].append(rec)

    def _order(item: tuple[str, dict]) -> tuple[int, str]:
        # UNKEYED (leading NUL) would sort first lexicographically; force it last instead so a
        # reader scanning a view meets real contexts before the residual bucket.
        k = item[0]
        return (1, "") if k == UNKEYED else (0, k)

    return {k: v for k, v in sorted(buckets.items(), key=_order)}
