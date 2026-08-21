"""claim_vector_core — the SHARED (signal × corroboration) claim-vector contract for the subskill fleet.

WHAT THIS IS: the extracted, skill-agnostic MACHINERY behind a modality-blind, verdict-INERT claim
vector — a projection that stacks a subskill's heterogeneous card evidence into a set of ORTHOGONAL
claims, each carrying a signal tier and an INDEPENDENT corroboration tier, plus a brief cited read.

The SHAPE is uniform across skills; the AXES are declared per skill (a ClaimSpec list). This is
deliberately NOT presence's A/B/C/D — presence's abundance/elevation/malignant/generality axes and
functional-requirement's DEP/SEL/COND/CHEM axes share the (signal × corroboration) shape and the
combination discipline, NOT the axis set. Extracted from TWO concretes (presence_claims first, then
dependency_claims) per the rule-of-two, so the abstraction is factored from real instances rather than
speculated from one.

THE COMBINATION DISCIPLINE (the honesty rules this module reifies as shared helpers):
  * ORDINAL, not metric. Tiers preserve ORDER (strong>moderate>weak>absent); gaps are not distances.
  * gap ≠ absent. `unmeasured` (never measured / no anchor) is DISTINCT from `absent` (a measured
    floor) and `negative` (measured, wrong direction). A coverage gap is never evidence of absence.
  * claims are kept SEPARATE, never averaged. A weak claim on one axis does not degrade a strong claim
    on another — they are orthogonal projections, not a scalar score.
  * within a claim, corroboration is SUB-ADDITIVE: a second AGREEING arm raises CORROBORATION, never the
    signal tier; a DISAGREEING arm penalizes corroboration and is surfaced as a `conflict`.

WHAT THIS IS NOT: a verdict input. Every claim vector built here is a one-way VIEW over an
already-computed decision; it never feeds a rule, resolver, or gate. The consuming skill owns that
invariant (its verdict spine stays byte-identical), frozen by that skill's golden/replay test.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

# Ordinal signal tiers — SHARED across all skills. `negative` (measured, wrong direction) and `absent`
# (a measured floor) both rank 0 but read differently in text; `unmeasured` (a GAP) is None, NOT 0 — so
# it is never comparable/averageable and gap≠absent is enforced at the type level.
SIGNAL_ORD = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0, "negative": 0, "unmeasured": None}
CORROBORATION_ORD = {"high": 3, "moderate": 2, "low": 1, "unmeasured": None}


def cards_by_id(cards) -> dict:
    """{card_id: summary_dict} — tolerates None cards / missing summaries."""
    return {c["card_id"]: (c.get("summary") or {}) for c in (cards or [])}


def fmt(v, nd=2) -> str:
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


def sig_ge(tier: Optional[str], floor: str) -> bool:
    """Is signal `tier` at least `floor` on the ordinal scale? `unmeasured` is never >= anything."""
    o = SIGNAL_ORD.get(tier)
    return o is not None and o >= SIGNAL_ORD[floor]


# ── combination-discipline helpers ───────────────────────────────────────────────────────────────
def bump_corroboration(rel: str, corroborated: bool) -> str:
    """SUB-ADDITIVE within-claim corroboration: an independent AGREEING arm lifts corroboration one step
    (low->moderate->high), NEVER the signal tier. No-op on `unmeasured` — a gap cannot be corroborated
    into confidence."""
    order = ["low", "moderate", "high"]
    if not corroborated or rel not in order:
        return rel
    return order[min(order.index(rel) + 1, len(order) - 1)]


def cap_corroboration(rel: str, ceiling: str) -> str:
    """Conflict penalty: a DISAGREEING arm caps corroboration at `ceiling` (never raises it). No-op on
    `unmeasured`."""
    order = ["low", "moderate", "high"]
    if rel not in order or ceiling not in order:
        return rel
    return order[min(order.index(rel), order.index(ceiling))]


def weakest(tiers, ord_map) -> Optional[str]:
    """Weakest-link over ORDINAL tiers, ignoring `unmeasured` (None). Returns None if all unmeasured."""
    measured = [t for t in tiers if ord_map.get(t) is not None]
    if not measured:
        return None
    return min(measured, key=lambda t: ord_map[t])


def corr(card, field, smap):
    """Single-source corroboration factory: returns a corroboration_fn(headline, cards_by_id) that
    reads `field` off `card`'s summary, maps it through `smap`, and yields `moderate` when that maps
    to a MEASURED tier (anything other than `unmeasured`), else `unmeasured`. For axes with a single
    relational/evidence source, intra-source presence is the corroboration signal (never a second arm)."""
    def fn(h, c):
        return "moderate" if smap.get((c.get(card) or {}).get(field), "unmeasured") != "unmeasured" else "unmeasured"
    return fn


# ── the spec + builders ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ClaimSpec:
    """One orthogonal claim axis, declared per skill.

    signal_fn(headline, cards_by_id)         -> (signal_tier, evidence_str, conflict_or_None)
    corroboration_fn(headline, cards_by_id)  -> corroboration_tier
    informs: light-touch downstream-lens routing tag (NOT a gate).
    atom_fn(headline, cards_by_id) -> dict | None : OPTIONAL. When set, builds a CITABLE evidence
        atom for the axis — the specific load-bearing data VALUES bound to their source
        {card_id, fields} and entity keys — carried alongside the ordinal signal/corroboration tiers
        (which stay UNCHANGED; the atom is provenance, never averaged). Returns None when the source
        card is absent, so the axis stays byte-stable (no `evidence_atom` key). Skills opt in per axis;
        an axis with no atom_fn keeps the legacy 5-key shape exactly.
    """
    axis_key: str
    label: str
    signal_fn: Callable
    corroboration_fn: Callable
    informs: str
    atom_fn: Optional[Callable] = None


def build_claim_vector(spec: Sequence[ClaimSpec], headline: dict, cards, disclaimer: str) -> dict:
    """Assemble {axis_key: {signal, corroboration, evidence, conflict, informs}, _disclaimer} from a
    skill's ClaimSpec list. Pure projection — reads the already-computed headline + card summaries and
    writes nothing back to either.

    NOTE on `corroboration` (renamed from `reliability`): this is a WITHIN-CLAIM
    support-quality tier — how well the claim's OWN signal is corroborated across its arms (it MAY
    include verdict-driving arms, e.g. dependency DEP's CRISPR↔RNAi concordance). It is deliberately
    NOT the axis certainty: the authoritative, VERDICT-DISJOINT certainty is the separate per-axis
    `certainty_by_axis` sidecar (CERTAINTY_MODEL). The claim vector is the SIGNAL decomposition; this
    field is a local annotation, never the axis certainty."""
    c = cards_by_id(cards)
    vec: dict = {}
    for cs in spec:
        signal, evidence, conflict = cs.signal_fn(headline, c)
        vec[cs.axis_key] = {
            "signal": signal,
            "corroboration": cs.corroboration_fn(headline, c),
            "evidence": evidence,
            "conflict": conflict,
            "informs": cs.informs,
        }
        # OPTIONAL citable atom — added ONLY when the spec declares an atom_fn AND it returns a
        # value (source card present). An axis without an atom_fn, or whose card is absent, keeps the
        # legacy 5-key shape byte-for-byte, so un-migrated skills are unaffected.
        if cs.atom_fn is not None:
            atom = cs.atom_fn(headline, c)
            if atom is not None:
                vec[cs.axis_key]["evidence_atom"] = atom
    vec["_disclaimer"] = disclaimer
    return vec


def build_key_signals(claim_vector: dict, *, rank_keys: Sequence[str], support_fns: dict,
                      critical_keys: Sequence[str], caveat_fns: dict, headline_fn: Callable,
                      fallback_caveat_fn: Optional[Callable] = None, max_supports: int = 3) -> dict:
    """A brief, DETERMINISTIC, CITED read over a claim vector (available WITHOUT the LLM).

    Generic machinery (SHARED): rank axes by signal tier (desc); keep only the top axes at >= moderate
    as `supports`; pick the weakest MEASURED decision-critical claim (tier <= weak) as the single
    `caveat`; derive a deterministic headline. The domain-specific CITED TEXT is injected per axis via
    support_fns / caveat_fns / headline_fn — closures the skill builds over its own headline + cards.
    A support_fn / caveat_fn returning None drops that line (e.g. no citable numbers)."""
    def ordv(k):
        return SIGNAL_ORD.get(claim_vector[k]["signal"])

    ranked = sorted(rank_keys, key=lambda k: -(ordv(k) if ordv(k) is not None else -1))
    supports = []
    for k in ranked:
        o = ordv(k)
        if o is None or o < SIGNAL_ORD["moderate"]:
            continue
        text = support_fns.get(k, lambda claim: None)(claim_vector[k])
        if text:
            supports.append(text)
    supports = supports[:max_supports]

    # caveat = the weakest MEASURED decision-critical claim, surfaced only when genuinely weak (<= weak)
    crit = [(k, ordv(k)) for k in critical_keys if ordv(k) is not None]
    caveat = None
    if crit:
        k, tier = min(crit, key=lambda kv: kv[1])
        if tier <= SIGNAL_ORD["weak"]:
            caveat = caveat_fns.get(k, lambda claim: None)(claim_vector[k])
    if caveat is None and fallback_caveat_fn is not None:
        caveat = fallback_caveat_fn()

    return {"headline": headline_fn(claim_vector, supports), "supports": supports, "caveat": caveat}


__all__ = ["SIGNAL_ORD", "CORROBORATION_ORD", "ClaimSpec", "build_claim_vector", "build_key_signals",
           "cards_by_id", "fmt", "sig_ge", "bump_corroboration", "cap_corroboration", "weakest", "corr"]
