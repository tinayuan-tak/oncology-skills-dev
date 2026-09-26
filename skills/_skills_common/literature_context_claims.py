"""literature_context_claims — the CLAIM VECTOR + KEY SIGNALS for the literature-context skill: a
verdict-INERT projection of the ONE cited-literature-evidence card (Open Targets europePMC
co-occurrence + PubTator3 typed relation direction) into orthogonal (signal × corroboration) claims.

literature-context is GATELESS (verdict_fn=None) and CONTEXT-tier: cited literature informs confidence,
NEVER a nomination gate (RISK_ASSESSMENT_INTEGRATION.md §4). The claim TIERS are DISPLAY tiers for a
descriptive skill (they feed the deterministic key_signals headline + the reader chips) — never a gate,
never averaged.

Three axes over the one card:
  VOLUME     co-occurrence volume        (paper_disease_mentions — how much is written about gene×indication)
  RECENCY    recent activity             (recent_mentions — is the literature current)
  RELATION   typed mechanistic relations (total_relation_publications + relation_types from PubTator3)

The whole vector is GATED by `cited_evidence_status`: `no_evidence` → the axes are a MEASURED `absent`
(the corpus was searched, nothing found); `insufficient` → capped at `weak` (thin); `data_unavailable`
/ missing → `unmeasured` (a coverage gap, never evidence against). Count cutoffs are display-only tiers
(literature volume is not vocabulary-pinned; PubTator/OT own the underlying corpora).
"""

from __future__ import annotations

from _skills_common.claim_vector_core import (
    ClaimSpec,
    build_atom,
    build_claim_vector,
    build_key_signals,
    corroboration_from_arms,
)

_C_LIT = "cited-literature-evidence"

# count → display tier cutoffs per axis (descriptive; NOT a gate). (strong_ge, moderate_ge, weak_ge)
_VOLUME_CUTS = (20, 5, 1)
_RECENCY_CUTS = (5, 2, 1)
_RELATION_CUTS = (10, 3, 1)


def _count_tier(n, cuts) -> str:
    """A count → display tier (strong/moderate/weak/absent) on the axis's own cutoffs. n is the MEASURED
    count under an `ok`/`insufficient` corpus status (the caller has already handled the gap/none gates)."""
    if n is None:
        return "unmeasured"
    strong, moderate, weak = cuts
    if n >= strong:
        return "strong"
    if n >= moderate:
        return "moderate"
    if n >= weak:
        return "weak"
    return "absent"


def _gated_tier(h, count_field, cuts) -> str:
    """Map a count to a tier, GATED by the corpus status: gap → unmeasured; no_evidence → absent
    (measured empty); insufficient → count tier capped at weak; ok → the count tier."""
    status = h.get("cited_evidence_status")
    if status in (None, "data_unavailable"):
        return "unmeasured"
    if status == "no_evidence":
        return "absent"
    tier = _count_tier(h.get(count_field), cuts)
    if status == "insufficient" and tier in ("strong", "moderate"):
        return "weak"  # a thin corpus cannot assert a strong/moderate volume
    return tier


def _sig(count_field, cuts, ev_fn):
    def fn(h, _c):
        return _gated_tier(h, count_field, cuts), ev_fn(h), None

    return fn


def _corr(count_field, cuts):
    """Corroboration: `unmeasured` on a coverage GAP; otherwise CAPPED at `single_arm`, because a single
    europePMC corpus read has nothing INDEPENDENT to agree with — literature is a one-armed axis, like the
    single-leg axes in translational_readiness_claims (`_one_arm`). #1600.

    This used to route `high` when the axis was `strong` AND `n_diseases>=3`, treating disease breadth as a
    genuine second arm. It is NOT one (arm-commensurability audit, epic #1507 / tracking #1703; same shape
    as #1667's non-independent superset arm):
      * NOT INDEPENDENT — the card documents (cited-literature-evidence.card.yaml `paper_disease_mentions`
        caveat) that `paper_disease_mentions` is SUMMED over the `n_diseases` disease subtypes ("a paper
        co-occurring with N subtypes counts N times"), so `n_diseases` is the DENOMINATOR the volume was
        summed across — a component of THIS SAME read, not an independent corroborating measurement.
        Folding it into `corroboration_from_arms` (the MEASURED-INDEPENDENT-ARM frame) double-counted one
        source, and nothing ever checked the disease contexts AGREED.
      * IT REWARDED PLEIOTROPY THE SKILL ITSELF FLAGS NEGATIVE — run.py's confidence caveat treats disease
        breadth as an OVER-CALL warning (`_PLEIOTROPY_MIN_DISEASES=8`, the "TP53 pattern": a promiscuous
        hub whose VOLUME is a LOW-SPECIFICITY signal). Using `n_diseases>=3` to UPGRADE corroboration to
        `high` contradicted that surface. Dropping the arm reconciles the two: run.py's negative treatment
        of disease breadth is now the SINGLE source of truth (claims.py no longer reads breadth as positive).
      * CROSS-AXIS MIS-WIRED — the same `n_diseases` (a VOLUME-scope field) was the second arm for the
        RECENCY and RELATION axes too, so a `high` RECENCY/RELATION corroboration asserted agreement on the
        basis of disease breadth from the volume read, which cannot corroborate a recency or typed-relation
        count.

    Note the `absent` tier keeps a MEASURED corroboration tier (`single_arm`) rather than reading
    `unmeasured`: `no_evidence` means the corpus WAS searched and came back empty, which the module gates
    to a measured `absent` precisely so it stays distinct from `data_unavailable`. Collapsing it here
    would re-merge on the corroboration axis the two states the signal axis works to keep apart. Feeding a
    single measured arm `[True]` to `corroboration_from_arms` yields `single_arm` for every measured tier
    (including `absent`), and only `unmeasured` short-circuits — preserving that distinction.

    (History: this fn used to return `low` for an `absent`/`weak` tier, which made "no papers found" read
    as CONFLICTING evidence — `eval/build_discordance_ledger._DISAGREEMENT_CORROBORATION == {"low"}` is the
    ledger's sharpness predicate — manufacturing a sharp discordance row on all three axes for every sparse
    corpus. The single-arm floor here keeps that fixed: `[True]` never routes a `False` arm, so `_corr`
    can never return `low`.)"""

    def fn(h, _c):
        tier = _gated_tier(h, count_field, cuts)
        if tier == "unmeasured":
            return "unmeasured"  # nobody searched — neither corroborated nor contradicted
        # ONE corpus read has nothing INDEPENDENT to agree with → capped at single_arm (see docstring).
        return corroboration_from_arms([True])

    return fn


_ATOM_FIELDS = (
    "paper_disease_mentions",
    "recent_mentions",
    "total_relation_publications",
    "relation_types",
    "n_diseases",
    "earliest_year",
    "latest_year",
    "literature_scope",
    "cited_evidence_status",
    "top_cited",
)


def _atom(read_field):
    """Citable atom for one axis — carries the cited-literature summary fields bound to the source card.
    `relation_types`/`top_cited` are list-valued → excluded from the citation `fields`."""

    def fn(h, _c):
        vals = {k: h.get(k) for k in _ATOM_FIELDS if h.get(k) is not None}
        return build_atom(
            card_id=_C_LIT,
            values=vals,
            read=h.get(read_field),
            entity="gene_indication",
            exclude_fields=("relation_types", "top_cited"),
        )

    return fn


def _volume_ev(h):
    n, nd = h.get("paper_disease_mentions"), h.get("n_diseases")
    return f"paper_disease_mentions={n}" + (f" across {nd} diseases" if nd is not None else "")


def _recency_ev(h):
    return f"recent_mentions={h.get('recent_mentions')}" + (
        f" (latest {h.get('latest_year')})" if h.get("latest_year") is not None else ""
    )


def _relation_ev(h):
    rts = [r for r in (h.get("relation_types") or []) if r]
    tail = f" — {', '.join(str(r) for r in rts[:5])}" if rts else ""
    return f"total_relation_publications={h.get('total_relation_publications')}{tail}"


LITERATURE_CONTEXT_CLAIM_SPEC = [
    ClaimSpec(
        "VOLUME",
        "co-occurrence volume",
        _sig("paper_disease_mentions", _VOLUME_CUTS, _volume_ev),
        _corr("paper_disease_mentions", _VOLUME_CUTS),
        "literature_context",
        _atom("paper_disease_mentions"),
    ),
    ClaimSpec(
        "RECENCY",
        "recent activity",
        _sig("recent_mentions", _RECENCY_CUTS, _recency_ev),
        _corr("recent_mentions", _RECENCY_CUTS),
        "literature_context",
        _atom("recent_mentions"),
    ),
    ClaimSpec(
        "RELATION",
        "typed mechanistic relations",
        _sig("total_relation_publications", _RELATION_CUTS, _relation_ev),
        _corr("total_relation_publications", _RELATION_CUTS),
        "literature_context",
        _atom("total_relation_publications"),
    ),
]

_DISCLAIMER = (
    "Verdict-INERT, CONTEXT-tier projection of the cited-literature-evidence card into orthogonal claims "
    "(VOLUME / RECENCY / RELATION), each signal × corroboration. GATED by cited_evidence_status: "
    "`no_evidence` → a MEASURED `absent` (searched, nothing found); `insufficient` → capped at weak; "
    "`data_unavailable` → `unmeasured` (a coverage gap, never evidence against). Count cutoffs are "
    "display-only tiers. literature-context is gateless and context-tier — this NEVER feeds a nomination "
    "gate (RISK_ASSESSMENT_INTEGRATION.md §4); literature informs confidence, not the call."
)


def literature_context_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-INERT literature claim vector {VOLUME,RECENCY,RELATION:
    {signal, corroboration, evidence, conflict, informs, evidence_atom?}, _disclaimer}."""
    return build_claim_vector(LITERATURE_CONTEXT_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def literature_context_key_signals(headline: dict, cards: list) -> dict:
    """A brief, deterministic, CITED read over the literature vector (available without the LLM)."""
    vec = literature_context_claim_vector(headline, cards)

    def _support(k):
        return lambda cl: f"{k}: {cl['signal']} ({cl['evidence']})"

    return build_key_signals(
        vec,
        rank_keys=("VOLUME", "RECENCY", "RELATION"),
        support_fns={k: _support(k) for k in ("VOLUME", "RECENCY", "RELATION")},
        critical_keys=("VOLUME",),
        caveat_fns={"VOLUME": lambda cl: f"thin cited-literature corpus ({cl['evidence']})"},
        headline_fn=lambda v, s: (
            "Cited literature present (co-occurrence + typed relations)."
            if s
            else "Sparse cited literature for this gene × indication."
        ),
        fallback_caveat_fn=lambda: None,
        max_supports=3,
    )


__all__ = ["literature_context_claim_vector", "literature_context_key_signals", "LITERATURE_CONTEXT_CLAIM_SPEC"]
