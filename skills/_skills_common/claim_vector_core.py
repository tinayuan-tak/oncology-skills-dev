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
  * ONE ARM IS NOT CORROBORATION, and coverage is not priced into the tier. Corroboration is computed
    over MEASURED arms only — an unmeasured arm leaves both sides of the comparison instead of scoring
    as partial agreement — and a claim below `CORROBORATION_ARM_FLOOR` measured arms is capped at
    `single_arm` (confidence `weak`) however strong its one arm is. This is `gap ≠ absent` applied one
    level up: unmeasured is not CORROBORATED, just as absent is not measured. Enforced by
    `corroboration_from_arms`, not re-derived per axis. The matching coverage COUNT
    (`n_arms_measured`) is defined here but deliberately NOT emitted yet — see its docstring; the tier
    is therefore trustworthy about agreement and silent about breadth.

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

# Ordinal CORROBORATION tiers. `single_arm` is the rung for "measured, but by exactly ONE arm" — the
# state that has no second arm to agree or disagree with. It exists because `moderate` used to serve
# double duty: it meant BOTH "two arms partly agree" AND "nobody looked for a second arm", so a third
# of the fleet reported partial agreement for evidence that was never corroborated (see `corr` below).
#
# `single_arm` sits ABOVE `low` and that ordering is load-bearing in two directions:
#   * ABOVE `low` because `low` means arms were compared and DISAGREED — negative agreement. A single
#     unopposed arm is thin, not contradicted; ranking it at/below a conflict would price a coverage
#     gap as a conflict.
#   * BELOW `moderate` because one arm must never read as corroborated. This is the CAP: a claim below
#     the measured-arm threshold cannot exceed `single_arm`, which `headline_core._CORR_TO_CONF`
#     projects to confidence `weak`.
# `eval/build_discordance_ledger._DISAGREEMENT_CORROBORATION` stays {"low"} — `single_arm` is
# deliberately NOT a disagreement, and a test pins that so this rung cannot decay into a rename.
CORROBORATION_ORD = {"high": 4, "moderate": 3, "single_arm": 2, "low": 1, "unmeasured": None}

# The measured-arm frame (user decision, 2026-09-13). Corroboration is computed over MEASURED arms
# ONLY: an absent arm leaves BOTH the numerator and the denominator, rather than being scored as a
# neutral/partial agreement. Coverage is then reported SEPARATELY (`n_arms_measured`) instead of being
# folded into the tier, so "two arms agree" and "one arm, nothing to compare" stay distinguishable.
#
# THE FLOOR IS 2 BECAUSE THE SUBSTRATE ADMITS NO OTHER VALUE — measured, not assumed (2026-09-14).
# `corroboration_from_arms` has four production call sites and three of them pass exactly two arms:
# genomic SNV `[True, genie_arm, multi_cohort_arm]` (3), genomic CN `[True, patient_arm]`, genomic FUS
# `[True, sv_arm]`, literature-context `[True, multi_disease_arm]`. So a floor of 3 would make `high`
# UNREACHABLE on three of the four axes — a vacuity dressed as a stricter standard, not a higher bar.
# Raising the floor is therefore not a knob: it requires a THIRD arm to exist on those axes first.
# What the floor buys is the cap below, and `high` here means precisely "two arms agree" — it does NOT
# mean "extensively corroborated", and the display gloss must not imply breadth the frame cannot see.
CORROBORATION_ARM_FLOOR = 2  # measured arms required for anything above `single_arm`
_CORR_MEASURED_RUNGS = ["low", "single_arm", "moderate", "high"]


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
# Explicit rather than an index walk over `_CORR_MEASURED_RUNGS`, because a second arm does NOT move
# every rung by one step — the rungs answer different questions, so their successors differ:
#   * `single_arm` (n=1) + an agreeing arm  -> n=2 and they all agree, which is `high` by definition
#     (exactly what `corroboration_from_arms([True, True])` returns). Not `moderate`: `moderate` is the
#     partial-agreement rung, and nothing here partially agrees.
#   * `low` (n>=2, they DISAGREED) + an agreeing arm -> `moderate`: a majority now agrees, but the
#     disagreement happened and is not erased by a later arm.
# An index walk would instead send `low` to `single_arm` — reporting a CONFLICT as a one-armed claim.
# A rung absent from this map (`unmeasured`, anything unknown) is a deliberate no-op: a gap cannot be
# corroborated into confidence.
_CORR_BUMP = {"low": "moderate", "single_arm": "high", "moderate": "high", "high": "high"}


# The table above is only sound when the thing that fired is genuinely a SECOND ARM. It is not always:
# some axes bump on a SAME-ARM QUALIFIER — a fact that makes the one arm they already have better, not a
# second opinion about it. Two such sites exist (2026-09-14, audited across all 12 production bump
# calls): `genomic_claims._dep_corroboration`'s within-indication localisation (WHERE the pharmacology
# arm's evidence was measured) and `dependency_claims._dep_corroboration`'s `own_omics_driven`
# predictability meta-signal (a model FIT on the very CRISPR arm it would be corroborating, so it cannot
# be independent of it). Routed through the default they took `single_arm` to `high`, i.e. they cleared
# the arm floor with one arm — reintroducing, one call site over, exactly the over-claim this rung was
# added to remove. They now pass `arm=False`. The other ten sites are real orthogonal arms (RNAi, PRISM,
# Sanger-vs-Broad, GDSC, PRECOG, s_het, GTEx, scRNA antigen escape) and are unchanged.
def bump_corroboration(rel: str, corroborated: bool, *, arm: bool = True) -> str:
    """SUB-ADDITIVE within-claim corroboration: an independent AGREEING arm raises the tier, NEVER the
    signal tier. No-op on `unmeasured` — a gap cannot be corroborated into confidence.

    The steps are NOT uniform, because the rungs answer different questions (see the comment above
    `_CORR_BUMP`): `single_arm -> high` (n=1 becomes n=2 in agreement, which IS `high`), `low ->
    moderate` (a majority now agrees, but the disagreement happened), `moderate/high -> high`.

    `arm=False` marks a SAME-ARM QUALIFIER rather than a second arm — a localisation, a model fit, a
    strength grade. A qualifier may refine a tier whose arms were already compared, but it can never
    lift `single_arm` across CORROBORATION_ARM_FLOOR: one arm is not corroborated by being described
    better. (`low` is left bumpable by a qualifier because `low` already HAS >= 2 arms; whether a
    qualifier should erase a recorded conflict is a separate open question, deliberately not decided
    here — it is not a floor breach.)"""
    if not corroborated:
        return rel
    if not arm and rel == "single_arm":
        return rel
    return _CORR_BUMP.get(rel, rel)


def cap_corroboration(rel: str, ceiling: str) -> str:
    """Conflict penalty: a DISAGREEING arm caps corroboration at `ceiling` (never raises it). No-op on
    `unmeasured`. `single_arm` is capped to `low` by a disagreeing arm — correctly, since a second arm
    that disagrees means the claim is no longer one-armed at all."""
    order = _CORR_MEASURED_RUNGS
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
    reads `field` off `card`'s summary, maps it through `smap`, and yields `single_arm` when that maps
    to a MEASURED tier (anything other than `unmeasured`), else `unmeasured`.

    This factory backs 22 of the fleet's 61 ClaimSpecs, and it used to return `moderate` — its own
    docstring said "intra-source presence is the corroboration signal (never a second arm)". But
    intra-source presence is MEASUREDNESS, not corroboration: there is exactly one arm here, so there
    is nothing for it to agree with. Reporting `moderate` made a third of the fleet claim partial
    agreement that was never sought, and made `moderate` unable to distinguish "two arms partly agree"
    from "one arm, nobody looked for a second". These axes are one-armed BY CONSTRUCTION, so they sit
    at the cap permanently — an axis that wants above `single_arm` must find a genuine second arm."""

    def fn(h, c):
        measured = smap.get((c.get(card) or {}).get(field), "unmeasured") != "unmeasured"
        return "single_arm" if measured else "unmeasured"

    return fn


def corroboration_from_arms(arms) -> str:
    """The MEASURED-ARM frame (user decision, 2026-09-13), as one shared helper so the 39 bespoke
    corroboration_fns stop each re-deriving it — and each re-deriving it differently.

    `arms` is an iterable of per-arm agreement verdicts, one entry per arm the axis CONSULTED:
    True (this arm agrees), False (this arm disagrees), or None (this arm was not measured).

    * ABSENT ARMS LEAVE BOTH SIDES. A None arm is dropped before anything is counted, so it neither
      raises nor lowers the tier. It is NOT scored as neutral/partial agreement — that conflation is
      the whole defect: `moderate` was the value for "no second arm found" and for "arms partly
      agree" alike.
    * COVERAGE IS NOT PRICED IN — and is NOT YET REPORTED EITHER. Dropping the None arms means the
      tier alone cannot say how many arms were consulted: `single_arm` is one measured arm out of one
      and one out of four alike. `n_arms_measured(arms)` computes the missing number and is the
      intended second channel, but NOTHING EMITS IT TODAY, so do not read its existence as evidence
      that a reader can recover coverage. Emitting it is a separate, ORDERED change: it adds a sixth
      key to the claim record, which trips the 5-key byte-stability pins in test_claim_vector_core and
      needs a target-contracts declaration to land FIRST (the record is validated
      `additionalProperties: false` downstream), and the per-axis counts are not even reachable at
      build time until `ClaimSpec.corroboration_fn` returns more than a bare string. Until then, the
      honest reading of this frame is: the tier is trustworthy about AGREEMENT and silent about BREADTH.
    * BELOW THE FLOOR, THE TIER IS CAPPED. Fewer than CORROBORATION_ARM_FLOOR measured arms cannot
      exceed `single_arm` however strong the measured arm is — one arm is never corroboration.

    Returns `unmeasured` for zero measured arms (a gap, never `absent`), `low` on any disagreement,
    `single_arm` below the floor, else `high`.

    Deliberately does NOT return `moderate`: with the floor at 2, "partial agreement" over exactly two
    arms IS one agreeing and one disagreeing, which is a conflict and belongs at `low` — the same place
    the pre-existing `cap_corroboration(rel, "low")` disagreement idiom puts it. Routing it to
    `moderate` instead would make `moderate` reachable only at n>=3 with a majority, i.e. an almost
    unreachable rung whose text nobody would ever see. `moderate` stays owned by the bespoke fns that
    grade a single arm's STRENGTH (cohort counts, p-values) and by `bump_corroboration`."""
    measured = [a for a in arms if a is not None]
    if not measured:
        return "unmeasured"
    if not all(measured):
        # A measured arm that disagrees is a CONFLICT, and stays one even at n=1: if the single arm we
        # have contradicts the signal, that is a comparison that happened and failed, not a gap.
        return "low"
    if len(measured) < CORROBORATION_ARM_FLOOR:
        return "single_arm"
    return "high"


def arm_from_class(value, *, agrees, disagrees) -> Optional[bool]:
    """Read ONE arm off an enum-valued class field, for `corroboration_from_arms`.

    Returns True (this arm agrees), False (it disagrees), or None (it was not measured on this frame).

    Two traps this exists to encode once rather than per axis:
      * `data_unavailable` is a TRUTHY STRING. Any `if value:` guard admits it as a real reading, so the
        sentinel is compared explicitly. Same for `None` (the field was never emitted).
      * AN OFF-ROSTER VALUE IS UNASKABLE, NOT AGREED — and equally not DISAGREED. A token in neither set
        (a vocabulary addition, a typo, a renamed rung) leaves the frame rather than being folded into
        either side. Reading it as agreement inflates corroboration; reading it as disagreement
        manufactures a conflict out of a value nobody has classified yet, which the eval ledger would
        then file as a sharp discordance. Both are worse than declining to count it."""
    if value is None or value == "data_unavailable":
        return None
    if value in agrees:
        return True
    if value in disagrees:
        return False
    return None


def n_arms_measured(arms) -> int:
    """COVERAGE, to be reported alongside corroboration rather than folded into it. Counts arms that
    were actually measured (True/False), dropping the None arms nobody looked at.

    NO PRODUCTION CALLER YET — exercised only by tests. See `corroboration_from_arms` for why emitting
    it is a separately ordered change (sixth record key, contracts declaration first). It lives here
    now so the arm frame has one definition of "measured" rather than two when that change lands; it is
    deliberately NOT wired into `build_claim_vector`, because a half-wired coverage channel that some
    axes populate and others silently omit would be worse than none."""
    return sum(1 for a in arms if a is not None)


def signal_from_class(card, field, smap):
    """Single-source signal factory (the most-copied claims-module leaf helper): returns a
    signal_fn(headline, cards_by_id) that reads `field` off `card`'s summary, maps the class through
    `smap` (default 'unmeasured'), and yields (tier, "<card>: <class-or-data_unavailable>", None)."""

    def fn(h, c):
        cls = (c.get(card) or {}).get(field)
        return smap.get(cls, "unmeasured"), f"{card}: {cls or 'data_unavailable'}", None

    return fn


# ── the shared evidence-atom builder ───────────────────────────────────────────────────────────────
def build_atom(*, card_id, values, read, entity, exclude_fields=()):
    """The SINGLE canonical CITABLE evidence atom — one shared shape for every axis's atom_fn,
    replacing the ~13 per-module hand-rolled `_atom`/`_patom`/`_mk_atom` builders (which had drifted
    only in their `fields`-exclusion + entity handling → a drift risk with no structural guard).

    Returns {read, values, cite:{card_id, fields}, entity}, or None when `values` is empty (an
    absent-card axis stays byte-stable — no `evidence_atom` key). `values` insertion order is
    PRESERVED (JSON key order is part of the byte output) and None values are dropped. `fields` is the
    sorted value keys minus `exclude_fields` — the list-valued keys some axes omit from the citation
    (combination's `partners`/`top_partners`/`sl_partner_symbols`, immune's `tumor_studies`)."""
    vals = {k: v for k, v in values.items() if v is not None}
    if not vals:
        return None
    excl = set(exclude_fields)
    return {
        "read": read,
        "values": vals,
        "cite": {"card_id": card_id, "fields": sorted(k for k in vals if k not in excl)},
        "entity": entity,
    }


def build_summary_atom(*, card_id, summary, keys, read, entity, exclude_fields=()):
    """Standard archetype: derive `values` from `summary` over `keys` (non-None, in `keys` order) then
    delegate to build_atom. Reproduces the former per-module `_atom(card_id, summary, keys, entity,
    read)` byte-for-byte (same comprehension, order, None-return)."""
    return build_atom(
        card_id=card_id,
        values={k: summary[k] for k in keys if summary.get(k) is not None},
        read=read,
        entity=entity,
        exclude_fields=exclude_fields,
    )


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


def build_key_signals(
    claim_vector: dict,
    *,
    rank_keys: Sequence[str],
    support_fns: dict,
    critical_keys: Sequence[str],
    caveat_fns: dict,
    headline_fn: Callable,
    fallback_caveat_fn: Optional[Callable] = None,
    max_supports: int = 3,
) -> dict:
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


__all__ = [
    "SIGNAL_ORD",
    "CORROBORATION_ORD",
    "ClaimSpec",
    "build_atom",
    "build_summary_atom",
    "build_claim_vector",
    "build_key_signals",
    "cards_by_id",
    "fmt",
    "sig_ge",
    "bump_corroboration",
    "cap_corroboration",
    "corroboration_from_arms",
    "n_arms_measured",
    "CORROBORATION_ARM_FLOOR",
    "weakest",
    "corr",
]
