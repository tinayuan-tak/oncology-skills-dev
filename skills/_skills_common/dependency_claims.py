"""dependency_claims — functional-requirement's CLAIM VECTOR + KEY SIGNALS: a modality-blind,
verdict-INERT projection of the dependency cards into (signal × corroboration) per orthogonal claim.

A concrete instance of the shared claim_vector_core contract.
Declares functional-requirement's four axes as a ClaimSpec list:

  DEP  genetic dependency          — CRISPR distribution (dependency_class), RNAi as an orthogonal-LoF
                                      within-claim corroboration; corroboration is QUORUM-aware over the
                                      independent perturbation channels — CRISPR×RNAi concordance + PRISM
                                      chemical-genetic triangulation + Broad↔Sanger cross-consortium
                                      replication + omics-predictability.
  SEL  context-selectivity         — lineage-selectivity enrichment_class; corroboration from n lineages.
  COND conditional / synthetic-SL  — partner-conditional-dependency (WRN×MSI-style rescue); corroboration
                                      from the partner-deficient stratification q + n.
  CHEM chemical-genetic confirm.   — prism-crispr-concordance triangulation; corroboration from PRISM n.

KEY FIT (why dependency validates the shape): functional-requirement ALREADY separates SIGNAL from
CONFIDENCE — it resolves the verdict from CRISPR/RNAi/concordance, and carries dependency-predictability
+ cross-consortium-dependency as CONFIDENCE ANNOTATIONS, never the verdict. Those map DIRECTLY onto the
corroboration axis, so (signal × corroboration) is a natural fit here, not a presence-specific one.

Verdict-INERT: reads the ALREADY-computed _headline; never feeds the dependency resolver. The
KRAS/COADREAD offline replay guard freezes dependency_verdict byte-stable with or without this.

All inputs are read from the `headline` dict (populated by run.py::_headline via get_card_field, so the
headline-fields drift guard covers every class the claims key on); the `cards` param is accepted for
contract-uniformity with presence_claims but unused here.
"""

from __future__ import annotations

import functools
from pathlib import Path

from _skills_common.claim_vector_core import (
    ClaimSpec,
    build_claim_vector,
    build_key_signals,
    build_summary_atom,
    bump_corroboration,
    cap_corroboration,
    cards_by_id,
    corroboration_from_arms,
    sig_ge,
)
from _skills_common.reliability import _derive_reliability

# ── enum → tier maps (grounded in the target-contracts card summary_fields_vocabulary) ────────────
# CRISPR dependency_class: common_essential | common_essential_underpowered | strongly_selective |
#                          broadly_dependent | non_dependent | non_dependent_underpowered | data_unavailable
_DEP_SIGNAL = {
    "strongly_selective": "strong",
    "common_essential": "strong",  # strong dependency MAGNITUDE (broad-tox caveat, see conflict)
    "broadly_dependent": "moderate",
    "non_dependent": "absent",  # a MEASURED pooled floor
    # both underpowered classes are admissibility GAPS (tiny-panel / diluted-pooled), NOT trusted calls
    "non_dependent_underpowered": "unmeasured",
    "common_essential_underpowered": "unmeasured",
    "data_unavailable": "unmeasured",
}
_RNAI_DEP = {"strongly_selective", "broadly_dependent", "common_essential"}
_RNAI_NONDEP = {"non_dependent"}
# CRISPR×RNAi concordance_class → base corroboration
_CONCORDANCE_REL = {
    "strongly_concordant_dependent": "high",
    "moderately_concordant_dependent": "moderate",
    "strongly_concordant_non_dependent": "moderate",
    "moderately_concordant_non_dependent": "moderate",
    "discordant": "low",
    # NOT `low`: `partially_assayed` means the second arm was never assayed. That is one arm, not two that
    # disagree, and `low` would file every partially-assayed target as a framework-internal disagreement.
    "partially_assayed": "single_arm",
    "data_unavailable": "unmeasured",
}
# lineage enrichment_class: lineage_selective | broadly_lineage_dependent | no_lineage_enrichment | data_unavailable
_SEL_SIGNAL = {
    "lineage_selective": "strong",
    "broadly_lineage_dependent": "weak",  # dependent across lineages = NOT selective (low window value)
    "no_lineage_enrichment": "absent",
    "data_unavailable": "unmeasured",
}
# partner_stratification_class
_COND_SIGNAL = {
    "partner_conditional_strongly_dependent": "strong",
    "partner_conditional_moderately_dependent": "moderate",  # rescue-firing for the WRN×MSI family
    "partner_neutral_strongly_dependent": "absent",  # dependent, but NOT conditional → no SL signal
    "not_partner_stratified": "absent",
    "insufficient_partner_deficient_rate": "unmeasured",
    "no_partner_mapped": "unmeasured",  # GAP: no curated partner (extend partner_map)
    "data_unavailable": "unmeasured",
}
# crispr_prism_concordance_class
_CHEM_SIGNAL = {
    "triangulated_target_engaged": "strong",  # CRISPR AND RNAi BOTH track compound kill
    "crispr_confirmed_engagement": "moderate",
    "rnai_confirmed_engagement": "moderate",
    "mixed_engagement": "weak",
    "discordant_off_target_likely": "negative",  # compound kills, but NOT via the target
    "thin_evidence": "unmeasured",
    "data_unavailable": "unmeasured",
}

# Verdicts where a MEASURED absence (or CRISPR/RNAi disagreement) could be a paralog-masking artifact —
# the case where a `partial` paralog buffer is the competing explanation worth surfacing in key_signals.
_ABSENCE_VERDICTS = frozenset({"non_dependent", "discordant"})

_INFORMS = {
    "DEP": "genetic dependency — the core actionability signal (is loss of the target lethal?)",
    "SEL": "context-selectivity — therapeutic-window / patient-selection lens (which lineages)",
    "COND": "conditional / synthetic-lethal — biomarker-stratified patient selection (partner-deficient)",
    "CHEM": "chemical-genetic confirmation — small-molecule tractability (is the dependency drug-confirmable?)",
}


# ── the four claims (signal_fn -> (tier, evidence, conflict); corroboration_fn -> tier) ─────────────
def _dep_signal(h, c):
    cls = h.get("crispr_call")
    sig = _DEP_SIGNAL.get(cls, "unmeasured")
    rnai = h.get("rnai_call")
    ev = f"CRISPR {cls or 'data_unavailable'}" + (f"; RNAi {rnai}" if rnai else "")
    conflict = None
    if cls == "common_essential":
        conflict = (
            "pan-essential — strong dependency magnitude but a broad-toxicity liability "
            "(low selective window; also routes to on-target-safety)"
        )
    elif sig_ge(sig, "moderate") and rnai in _RNAI_NONDEP:
        conflict = "RNAi (orthogonal LoF) does not corroborate the CRISPR dependency"
    return sig, ev, conflict


def _dep_corroboration(h, c):
    base = _CONCORDANCE_REL.get(h.get("concordance_call"), "unmeasured")
    if base == "unmeasured" and h.get("crispr_call") not in (None, "data_unavailable"):
        base = "single_arm"  # a single CRISPR arm with no concordance read — thin, but not contradicted
    crispr_dep = sig_ge(_DEP_SIGNAL.get(h.get("crispr_call")), "moderate")
    rnai = h.get("rnai_call")
    # sub-additive: independent orthogonal-assay (RNAi) agreement lifts corroboration one step
    base = bump_corroboration(base, crispr_dep and rnai in _RNAI_DEP)
    # QUORUM-awareness (2026-09-03): the PRISM chemical-genetic arm is a THIRD independent perturbation
    # channel (small-molecule kill vs genetic LoF). `triangulated_target_engaged` = BOTH CRISPR and RNAi
    # track the compound kill → an orthogonal agreeing arm that lifts corroboration one step (never the
    # signal tier). Gated on the genetic dependency being present (crispr_dep) so a compound-kill read on
    # a genetically non-dependent target does not manufacture DEP corroboration. Placed BEFORE the
    # disagreement cap below, so an RNAi non-corroboration still caps the quorum (no over-claim).
    base = bump_corroboration(base, crispr_dep and h.get("prism_concordance_class") == "triangulated_target_engaged")
    # independent CONSORTIUM replication (Sanger Project Score vs Broad) — stronger than intra-Broad
    cc = h.get("cross_consortium_class")
    if cc == "concordant_dependent":
        base = bump_corroboration(base, True)
    elif cc == "discordant":
        base = cap_corroboration(base, "low")
    # a disagreeing orthogonal assay caps corroboration
    if crispr_dep and rnai in _RNAI_NONDEP:
        base = cap_corroboration(base, "moderate")
    # omics-predictability meta-signal: own-omics-driven is a biomarker handle → confidence. `arm=False`:
    # the predictability model is FITTED ON this same CRISPR dependency, so it is a property of that one
    # arm (how predictable it is from the target's own omics), not an independent second read of whether
    # the dependency is real. It may refine a tier whose arms were compared, but it must not lift a lone
    # CRISPR arm to `high` — which is what it did before 2026-09-14.
    if h.get("predictability_class") == "own_omics_driven":
        base = bump_corroboration(base, True, arm=False)
    # paralog buffering (2026-09-06): a STRONG redundant paralog is a competing explanation that LOWERS
    # confidence in the dependency CALL — a present dependency may be masked/compensated (Dede 2020;
    # Parrish 2021) or need combined paralog loss to be fully realised. Independent of the CRISPR/RNAi/PRISM
    # arms above → caps corroboration (the non_dependent_paralog_buffered rung owns the verdict; this makes
    # the buffering visible to the claim projection instead of a key_signals caveat string only). Verdict-INERT.
    if h.get("paralog_buffering_class") == "strong":
        base = cap_corroboration(base, "moderate")
    return base


def _sel_signal(h, c):
    cls = h.get("lineage_selectivity")
    ev = (
        f"lineage enrichment: {cls or 'data_unavailable'}"
        " (target-grain — selective to SOME lineage, not necessarily the queried indication)"
    )
    return _SEL_SIGNAL.get(cls, "unmeasured"), ev, None


def _sel_corroboration(h, c):
    n = h.get("n_lineages_evaluated")
    if not isinstance(n, (int, float)):
        return "unmeasured"
    # ONE arm (the DepMap lineage-enrichment scan). `n_lineages_evaluated` is the BREADTH of that single
    # scan, not a count of independent arms — evaluating 20 lineages in one panel is still one panel, so
    # the old n>=20 -> `high` reported cross-source agreement that no second source ever provided.
    return "single_arm"


def _cond_signal(h, c):
    cls = h.get("partner_conditional_class")
    ev = {
        "no_partner_mapped": "no curated partner in partner_map.yaml (a GAP, not evidence against SL)",
        "insufficient_partner_deficient_rate": "too few partner-deficient cell lines to test",
    }.get(cls, f"partner-conditional: {cls or 'data_unavailable'}")
    return _COND_SIGNAL.get(cls, "unmeasured"), ev, None


def _cond_corroboration(h, c):
    if _COND_SIGNAL.get(h.get("partner_conditional_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    # ONE arm (the partner-stratified dependency test). `n_partner_deficient` is that test's SAMPLE SIZE
    # and `partner_stratification_q` its significance — both grade the single arm's strength, neither is a
    # second opinion. Cohort size buying `high` corroboration is how a well-powered single test came to
    # read as though independent sources concurred.
    return "single_arm"


def _chem_signal(h, c):
    cls = h.get("prism_concordance_class")
    conflict = (
        "PRISM compound kill does not track the CRISPR/RNAi dependency — likely off-target"
        if cls == "discordant_off_target_likely"
        else None
    )
    return _CHEM_SIGNAL.get(cls, "unmeasured"), f"PRISM×CRISPR: {cls or 'data_unavailable'}", conflict


def _chem_corroboration(h, c):
    if _CHEM_SIGNAL.get(h.get("prism_concordance_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    # ONE arm (the PRISM×CRISPR concordance read). `n_compounds_evaluated` is that read's breadth.
    return "single_arm"


# ── citable evidence atoms (claim_vector_core atom_fn) ──────────────────────────────────────────────
# Each atom binds the axis's load-bearing NUMERIC values to their source {card_id, fields} + entity
# keys, so a downstream reasoner (e.g. cross-evidence-hypothesis) can cite the value by a discrete
# token — satisfying its traceability HARD RULE — and JOIN across axes on the entity. Verdict-inert
# provenance: the ordinal signal/corroboration tiers are untouched (the atom is never averaged). These
# read the raw card summaries from `c` (cards_by_id); returns None when the source card is absent, so
# the axis stays byte-stable (no evidence_atom key).
def _atom(card_id: str, summary: dict, keys: tuple, entity: dict, read) -> dict | None:
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _dep_atom(h, c):
    cid = "pan-cancer-crispr-dependency-distribution"
    return _atom(
        cid,
        c.get(cid) or {},
        (
            "bimodality_coefficient",
            "distribution_shape",
            "fraction_strongly_dependent",
            "median_chronos_panel",
            "p5_chronos_panel",
            "n_cell_lines_evaluated",
            "selectivity_index",
            "dep_control_position_class",
        ),
        {"measurement_type": "crispr_lof_dependency", "sample_context": "cell_line", "stratum": "pan_cancer"},
        h.get("crispr_call"),
    )


def _sel_atom(h, c):
    cid = "dependency-lineage-selectivity"
    return _atom(
        cid,
        c.get(cid) or {},
        (
            "enrichment_class",
            "lineage_variance_explained",
            "lineage_omnibus_kruskal_h",
            "lineage_omnibus_effect_size_class",
            "n_enriched_lineages",
            "n_lineages_evaluated",
        ),
        {"measurement_type": "crispr_lof_dependency", "sample_context": "cell_line", "grain": "target_lineage"},
        h.get("lineage_selectivity"),
    )


def _cond_atom(h, c):
    cid = "partner-conditional-dependency"
    return _atom(
        cid,
        c.get(cid) or {},
        ("partner_stratification_class", "n_partner_deficient", "partner_stratification_q"),
        {"sample_context": "cell_line", "stratum": "partner_deficient"},
        h.get("partner_conditional_class"),
    )


def _chem_atom(h, c):
    cid = "prism-crispr-concordance"
    return _atom(
        cid,
        c.get(cid) or {},
        (
            "crispr_prism_concordance_class",
            "n_compounds_evaluated",
            "n_dual_responders",
            "best_spearman_r_crispr",
            "best_spearman_r_rnai",
        ),
        {"sample_context": "cell_line", "stratum": "pan_cancer"},
        h.get("prism_concordance_class"),
    )


DEPENDENCY_CLAIM_SPEC = [
    ClaimSpec("DEP", "genetic dependency", _dep_signal, _dep_corroboration, _INFORMS["DEP"], _dep_atom),
    ClaimSpec("SEL", "context-selectivity", _sel_signal, _sel_corroboration, _INFORMS["SEL"], _sel_atom),
    ClaimSpec(
        "COND", "conditional / synthetic-lethal", _cond_signal, _cond_corroboration, _INFORMS["COND"], _cond_atom
    ),
    ClaimSpec("CHEM", "chemical-genetic confirmation", _chem_signal, _chem_corroboration, _INFORMS["CHEM"], _chem_atom),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the dependency cards into orthogonal claims "
    "(DEP genetic-dependency / SEL context-selectivity / COND conditional-SL / CHEM chemical-genetic-"
    "confirmation), each signal×corroboration. Claims are NOT additive; a weak SEL does not degrade a "
    "strong DEP. Reliability carries the confidence annotations functional-requirement already separates "
    "from its verdict (CRISPR×RNAi concordance, Broad↔Sanger cross-consortium replication, omics-"
    "predictability). Never feeds the dependency_verdict."
)


# ── L2b-2: cross-source essentiality concordance (CRISPR × RNAi) (SK#1533, evidence-property arch #1507) ─
# The SECOND cross-source INTEGRATED claim (L2b), and the FIRST on a NON-expression property (essentiality
# depth) — the chosen probe because it is the cleanest concordance test in the fleet: CRISPR Chronos and
# RNAi DEMETER2 are two ORTHOGONAL loss-of-function assays that already emit the SAME essentiality
# vocabulary BY DESIGN, so agreement/disagreement is directly readable WITHOUT any vocabulary
# reconciliation. Integrates two ALREADY-EMITTED properties neither assay could integrate alone:
#   * CRISPR essentiality — pan-cancer-crispr-dependency-distribution.dependency_class (Chronos)
#   * RNAi  essentiality  — pan-cancer-rnai-dependency-distribution.rnai_dependency_class (DEMETER2)
# HARD RULE (L2b reproducibility): a DETERMINISTIC explicit rule over the two tokens — NO llm_inference
# (L2b is L3-only for LLM inference).
#
# The shared classifier vocabulary (both assays; see analysis-methods _classify_dependency /
# _classify_rnai_dependency): common_essential | common_essential_underpowered | strongly_selective |
# broadly_dependent | non_dependent | non_dependent_underpowered (CRISPR only) | data_unavailable.
# DEPENDENT tokens read as a positive requirement call; `non_dependent` is a MEASURED floor; the
# `*_underpowered` / `data_unavailable` tokens are admissibility GAPS — the arm WAS consulted but could
# not resolve a trusted call, so the arm is UNRESOLVED (mirrors _DEP_SIGNAL's `unmeasured`), never a floor.
_ESS_DEPENDENT = frozenset({"common_essential", "broadly_dependent", "strongly_selective"})
_ESS_NONDEPENDENT = frozenset({"non_dependent"})
# `strongly_selective` is a dependency, but a SELECTIVE one (essential in a subset of lines) — distinct
# from a pan/broad requirement. Carried in the payload rather than collapsed into a bare `dependent`.
_ESS_SELECTIVE = frozenset({"strongly_selective"})
_ASSAY_NAME = {"crispr": "crispr_chronos", "rnai": "rnai_demeter"}


def _ess_resolve(token) -> str | None:
    """Categorise one assay's essentiality token → 'dependent' | 'nondependent' | None (unresolved gap).

    None covers data_unavailable / *_underpowered / a missing field / an off-roster value — the arm did
    not resolve a trusted call. `data_unavailable` is a TRUTHY string, so the membership test (not an
    `if token:` guard) is what keeps it out of the resolved buckets."""
    if token in _ESS_DEPENDENT:
        return "dependent"
    if token in _ESS_NONDEPENDENT:
        return "nondependent"
    return None


def _essentiality_concordance_claim(c: dict) -> dict | None:
    """L2b-2 CROSS-SOURCE integration claim: `crispr_rnai_essentiality_concordance`.

    Reads the two orthogonal-assay essentiality tokens and integrates them by an EXPLICIT DETERMINISTIC
    rule (no LLM — L2b is reproducible by contract):
      * essentiality_concordant_dependent    — both assays call a dependency (agree, dependent);
      * essentiality_concordant_nondependent  — both call non_dependent (agree, not a dependency);
      * essentiality_assay_discordant          — one assay dependent, the other non_dependent (with a
        which-assay-supports payload — the disagreement neither collapses nor is averaged);
      * essentiality_single_assay_only         — exactly ONE assay resolves and the other is an
        admissibility gap (data_unavailable / underpowered / absent): the degraded read that names the
        resolved arm (recoverable), NOT a concordance claim.
    The selective-vs-common distinction (`strongly_selective` on either arm) is CARRIED in the payload
    (`selective_assays` + the raw tokens in provenance), never collapsed to a bare `dependent`.

    Corroboration is on the shared MEASURED-ARM contract: two agreeing arms → high, a disagreement →
    low, one measured arm with the other unresolved → single_arm. So a SINGLE-arm mutation only DEGRADES
    the read to `essentiality_single_assay_only`; ERASING the concordance conclusion (key omitted) takes
    defeating BOTH assay supplies (the M3-vs-M4 fidelity / reach discipline).

    VERDICT-INERT: carries NO `signal` key (never a chip, never a tier, never averaged), reads no
    verdict, feeds no rule. Returns None — key omitted, byte-stable — when NEITHER assay resolves."""
    crispr = (c.get("pan-cancer-crispr-dependency-distribution") or {}).get("dependency_class")
    rnai = (c.get("pan-cancer-rnai-dependency-distribution") or {}).get("rnai_dependency_class")
    crispr_dir = _ess_resolve(crispr)
    rnai_dir = _ess_resolve(rnai)
    # Neither arm resolves → no claim (key omitted → byte-stable). This is the ONLY erasing state: it
    # takes defeating BOTH assay supplies, matching the atom discipline for the DEP/SEL/COND/CHEM axes.
    if crispr_dir is None and rnai_dir is None:
        return None

    resolved = [d for d in (crispr_dir, rnai_dir) if d is not None]
    if len(resolved) == 1:
        concordance = "essentiality_single_assay_only"
    elif crispr_dir == rnai_dir:
        concordance = (
            "essentiality_concordant_dependent" if crispr_dir == "dependent" else "essentiality_concordant_nondependent"
        )
    else:
        concordance = "essentiality_assay_discordant"

    # Corroboration on the measured-arm frame: for a discordance the two arms point opposite ([True,
    # False] → low); for a concordance both agree ([True, True] → high); with one arm unresolved the
    # measured arm is unopposed ([True, None] → single_arm, below the arm floor).
    if concordance == "essentiality_assay_discordant":
        crispr_arm, rnai_arm = True, False
    else:
        crispr_arm = True if crispr_dir is not None else None
        rnai_arm = True if rnai_dir is not None else None
    corroboration = corroboration_from_arms([crispr_arm, rnai_arm])

    # which-assay-supports / resolved-arm payload — the disagreement or the degraded single arm is named,
    # never collapsed.
    if concordance == "essentiality_assay_discordant":
        dep_assay = _ASSAY_NAME["crispr"] if crispr_dir == "dependent" else _ASSAY_NAME["rnai"]
        nondep_assay = _ASSAY_NAME["rnai"] if crispr_dir == "dependent" else _ASSAY_NAME["crispr"]
        assay_support = {"dependency_supported_by": dep_assay, "nondependency_supported_by": nondep_assay}
    elif concordance == "essentiality_single_assay_only":
        if crispr_dir is not None:
            assay_support = {
                "resolved_by": _ASSAY_NAME["crispr"],
                "resolved_call": crispr,
                "resolved_direction": crispr_dir,
            }
        else:
            assay_support = {"resolved_by": _ASSAY_NAME["rnai"], "resolved_call": rnai, "resolved_direction": rnai_dir}
    else:
        assay_support = {"agreed_direction": crispr_dir}  # both arms resolved to the same direction
    # selective-vs-common distinction (do not collapse): which assay(s) read strongly_selective.
    selective_assays = [
        name for tok, name in ((crispr, _ASSAY_NAME["crispr"]), (rnai, _ASSAY_NAME["rnai"])) if tok in _ESS_SELECTIVE
    ]

    _PHRASE = {
        "essentiality_concordant_dependent": "AGREE the target is a dependency",
        "essentiality_concordant_nondependent": "AGREE the target is NOT a dependency",
        "essentiality_assay_discordant": "DISAGREE on the dependency call",
        "essentiality_single_assay_only": "only one assay resolves",
    }
    return {
        "concordance_class": concordance,
        "corroboration": corroboration,
        # DETERMINISTIC, reproducible-by-contract: an explicit rule over two tokens, never an LLM.
        "integration_method": "explicit_deterministic",
        # NO `reliability` facet on this L2b island (#2306): the locked shape derives an arm's reliability
        # FROM THAT ARM'S OWN anchors and does not restate the L2a values. This island reads only the two
        # categorical per-assay DIRECTION tokens (CRISPR/RNAi dependency calls) with no per-arm anchor
        # list, so there is nothing to derive from → the facet is honestly OMITTED (byte-stable), not a
        # thin restate of the L2a `powered`. Per-arm L2b reliability lands at the presence-style islands
        # that carry per-arm anchors/retained_quantitative (a later #2306 step).
        "assay_support": assay_support,
        "selective_assays": selective_assays,
        "informs": (
            "cross-source essentiality concordance — the core actionability signal, corroborated (or "
            "contradicted) across two genuinely INDEPENDENT loss-of-function assays: a dependency both "
            "CRISPR and RNAi see is far more credible than a single-assay call"
        ),
        "evidence": (
            f"CRISPR {crispr or 'data_unavailable'} × RNAi {rnai or 'data_unavailable'}: "
            + _PHRASE[concordance]
            + (f" (selective: {', '.join(selective_assays)})" if selective_assays else "")
        ),
        # Provenance graph: BOTH source properties + an independence note. CRISPR (genetic knockout) and
        # RNAi (knockdown) are measured on genuinely INDEPENDENT perturbation assays, so their
        # (dis)agreement is a real cross-source corroboration, not a within-assay echo. NOT the reserved
        # single-card `evidence_atom` key — this records TWO-card cross-source provenance, and carries the
        # raw per-assay tokens so the VALUES (not just the key) are recoverable.
        "provenance": {
            "sources": [
                {
                    "property": "crispr_essentiality",
                    "assay": _ASSAY_NAME["crispr"],
                    "card_id": "pan-cancer-crispr-dependency-distribution",
                    "fields": {"dependency_class": crispr},
                },
                {
                    "property": "rnai_essentiality",
                    "assay": _ASSAY_NAME["rnai"],
                    "card_id": "pan-cancer-rnai-dependency-distribution",
                    "fields": {"rnai_dependency_class": rnai},
                },
            ],
            "independence_note": (
                "CRISPR Chronos (genetic knockout) and RNAi DEMETER2 (RNA knockdown) are measured on "
                "genuinely INDEPENDENT loss-of-function perturbation assays; their agreement is a real "
                "cross-source corroboration of essentiality, not a within-assay restatement."
            ),
        },
        "_disclaimer": (
            "L2b CROSS-SOURCE integration claim (deterministic, no LLM) — verdict-INERT provenance: "
            "never a signal tier, never averaged into a claim, never feeds the dependency_verdict."
        ),
    }


# ── L2a NAMED source_properties map — DEPENDENCY domain (PR-1b, epic #2210 Wave 1 / #1507) ──────────
# The dependency generalisation of the tumour-presence reference vertical
# (`presence_claims.py::_SOURCE_PROPERTY_RECIPES`), replicating the shape the safety seed (PR-1a,
# safety_claims.py::_SOURCE_PROPERTY_RECIPES_SAFETY) proved end-to-end. Lifts the per-source
# observational (L2a) properties — until now embedded implicitly inside the four claim signal blocks —
# into a NAMED, typed map, one entry per source/grain, matching the architecture's `source_properties:`
# export shape (docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md). Each entry carries the L1 card it resolves
# from, the resolved observational class (the SAME class the claim axes read from that source), the
# RETAINED quantitative anchors (value + scale + ledger-declared disposition typing), and comparability
# metadata so a downstream reader can tell which entries are commensurable.
#
# PURE PROJECTION over the already-computed card summaries: no LLM, no new measurement, no re-derivation.
# Like every other L2a/L2b facet on this vector it carries NO `signal` key, is read by no
# rule/verdict/ladder, and every property reconstructs to its L1 card field via {card_id, property_field,
# property}. VERDICT-INERT.
#
# TWO deliberate divergences from the safety seed, each an honest property of THIS domain, not an
# oversight — both stated because 1c-1e will face the same two calls:
#
#   (1) NO `comparability.valence` marker. Safety is INVERSE-valence (a strong read is a liability), so it
#       had to mint the marker or a "higher = better" reader would invert it. Dependency is the DEFAULT
#       frame: a strong dependency is the efficacy signal the domain is looking for, so a generic
#       higher-is-stronger reading is CORRECT and no marker is needed. Minting `valence: efficacy` here
#       would introduce a SECOND valence token — precisely the ungoverned drift the safety seed's own
#       comment warns 1b-1e against ("must NOT invent a second valence token without governing it
#       first"; there is no `valence` slot in the property-catalog validator's closed ENTRY_KEYS). So the
#       marker is OMITTED, and its absence IS the default-valence declaration. ⚠️ Note the cross-domain
#       twist this makes safe: `crispr_essentiality` is READ at LIABILITY valence by the safety
#       PAN_ESSENTIAL axis, but safety deliberately does not re-emit it as a safety L2a property, so no
#       single emitted entry ever carries two valences.
#
#   (2) NO `interpretation` provenance object on any entry. Safety emitted it on the one source whose
#       class comes from a genuine skills-side multi-arm disjunction (`_normaltissue_sig`). Every one of
#       the six dependency classes below is a VERBATIM read of the card summary field — the producing
#       disjunct (where one exists) was decided upstream in methods/ and is not recoverable from the
#       summary. Emitting a fabricated `disjunct_fired` would assert provenance this domain does not
#       have; omitting it is the honest state (safety's discipline for its own seven verbatim entries).
#       The section-fidelity test PINS this absence so a future disjunction-resolved class is a
#       deliberate decision, not silent drift.

# The scale/unit slot for each retained quantitative anchor (envelope-v0: a raw value + its declared
# scale, never a `decision_weight`/`modality_relevance`). Absent → "raw".
_DEPENDENCY_ANCHOR_SCALE = {
    # CRISPR Chronos gene-effect scores: a normalised dependency scale where ~ -1 is the median common-
    # essential gene and 0 is non-essential. Panel median and 5th percentile are on the SAME scale.
    "median_chronos_panel": "chronos_gene_effect",
    "p5_chronos_panel": "chronos_gene_effect",
    # RNAi DEMETER2 dependency scores — a DIFFERENT scale from Chronos (strong cut -0.5 vs Chronos -1.0),
    # named distinctly so a consumer never compares a Chronos value with a DEMETER2 one.
    "rnai_median_dep_score": "demeter2_dependency_score",
    "rnai_p5_dep_score": "demeter2_dependency_score",
    # Strongly-dependent fractions — fraction of the evaluated panel below the strong-dependency cut.
    "fraction_strongly_dependent": "fraction",
    "rnai_fraction_strongly_dependent": "fraction",
    # Selectivity indices — a tail-vs-background magnitude ratio in [0, 1] (higher = more selective).
    "selectivity_index": "selectivity_index",
    "rnai_selectivity_index": "selectivity_index",
    # Lineage-selectivity omnibus statistics.
    "lineage_variance_explained": "epsilon_squared",  # Kruskal-Wallis effect size (variance fraction)
    "lineage_omnibus_kruskal_h": "kruskal_h_statistic",
    # Partner-conditional stratification — a BH-corrected q-value over the partner-deficient contrast.
    "partner_stratification_mannwhitney_q": "bh_q_value",
    # PRISM×CRISPR chemical-genetic concordance — best Spearman correlations across compounds.
    "best_spearman_r_crispr": "spearman_r",
    "best_spearman_r_rnai": "spearman_r",
    # Paralog buffering — the dual-KO additional lethality over the stronger single, on the Chronos scale.
    "strongest_paralog_delta": "chronos_gene_effect_delta",
    # COUNTS across the domain — cell lines, lineages, compounds, dual responders, paralogs. All raw
    # integer counts, never rates.
    "n_cell_lines_evaluated": "cell_line_count",
    "rnai_n_cell_lines_evaluated": "cell_line_count",
    "n_lineages_evaluated": "lineage_count",
    "n_enriched_lineages": "lineage_count",
    "n_partner_deficient": "cell_line_count",
    "n_compounds_evaluated": "compound_count",
    "n_dual_responders": "compound_count",
    "n_paralogs_annotated": "paralog_count",
    "n_paralogs_functionally_buffering": "paralog_count",
}

# Data-driven recipe (keyed by the L2a property name from the architecture's source_properties shape).
# `property_field` is the resolved observational class of that source; `anchors` are its retained
# quantitative anchors, in reading order; `context` fields are retained categorical/label qualifiers that
# orient the anchors but are not themselves quantities. Every `card_id`/`property_field`/anchor/context
# name below was verified against `contracts/cards/<card_id>.card.yaml` `outputs.summary_fields`.
#
# TWO plan-table anchors CORRECTED against the cards (the arc's plan table was authority on intent, the
# card YAML on fact; PR-1a corrected a ClinVar field name the same way):
#   * crispr_essentiality dropped `bimodality_coefficient` — it is COMPUTED inside the classifier
#     (depmap_chronos_distribution/cli.py:337) but NOT emitted in the card's summary_fields, so it does
#     not reconstruct to L1 and cannot be an anchor. The distribution-shape facet it captured is
#     retained categorically via `distribution_shape` context.
#   * partner_conditional_dependency reads `partner_stratification_mannwhitney_q` — the card's real
#     field name; the plan's `partner_stratification_q` is not a summary field.
#
# A source whose card is absent (or whose class does not resolve) emits NO entry, and the whole
# `source_properties` key is omitted when nothing resolves — keeping a card-absent run byte-stable,
# matching the concordance-atom discipline on this vector.
#
# NOT here, deliberately:
#   * NO separate "dependency prevalence" / "pan-essentiality" entry. The prevalence facet is the
#     `fraction_strongly_dependent` anchor ON `crispr_essentiality`, and the pan-essential read is that
#     property's `common_essential` class token — read at LIABILITY valence by the SAFETY domain's
#     PAN_ESSENTIAL axis. It is ONE shared measurement, recorded via `dependence_group` in the catalog
#     and cited by both FR's DEP and safety's PAN_ESSENTIAL; minting a second entry would make one card
#     look like two independent sources.
_SOURCE_PROPERTY_RECIPES_DEPENDENCY = (
    {
        "name": "crispr_essentiality",
        "card_id": "pan-cancer-crispr-dependency-distribution",
        "property_field": "dependency_class",
        "anchors": (
            "median_chronos_panel",
            "p5_chronos_panel",
            "fraction_strongly_dependent",
            "selectivity_index",
            "n_cell_lines_evaluated",
        ),
        "context": ("distribution_shape", "pan_essential_fraction_call", "broad_dependency_band"),
        "comparability": {
            "measurement_type": "crispr_chronos_dependency",
            "sample_context": "pan_cancer_cell_line_panel",
            "grain": "target",
        },
        # n_effective = the CRISPR panel size (the denominator behind the distribution + fractions).
        "reliability": {"n_effective_anchor": "n_cell_lines_evaluated"},
    },
    {
        "name": "rnai_essentiality",
        "card_id": "pan-cancer-rnai-dependency-distribution",
        "property_field": "rnai_dependency_class",
        "anchors": (
            "rnai_median_dep_score",
            "rnai_p5_dep_score",
            "rnai_fraction_strongly_dependent",
            "rnai_selectivity_index",
            "rnai_n_cell_lines_evaluated",
        ),
        "context": ("rnai_distribution_shape",),
        "comparability": {
            "measurement_type": "rnai_demeter2_dependency",
            "sample_context": "pan_cancer_cell_line_panel",
            "grain": "target",
        },
        # n_effective = the RNAi (DEMETER2) panel size — materially smaller than the CRISPR panel.
        "reliability": {"n_effective_anchor": "rnai_n_cell_lines_evaluated"},
    },
    {
        "name": "dependency_lineage_selectivity",
        "card_id": "dependency-lineage-selectivity",
        "property_field": "enrichment_class",
        "anchors": (
            "lineage_variance_explained",
            "lineage_omnibus_kruskal_h",
            "n_enriched_lineages",
            "n_lineages_evaluated",
        ),
        "context": ("indication_dependency_class", "lineage_omnibus_effect_size_class", "which_lineages_separate"),
        "comparability": {
            "measurement_type": "crispr_chronos_lineage_selectivity",
            "sample_context": "pan_cancer_cell_line_panel",
            "grain": "target",
        },
        # n_effective = the number of lineages evaluated (the denominator behind n_enriched_lineages).
        "reliability": {"n_effective_anchor": "n_lineages_evaluated"},
    },
    {
        "name": "partner_conditional_dependency",
        "card_id": "partner-conditional-dependency",
        "property_field": "partner_stratification_class",
        "anchors": ("n_partner_deficient", "partner_stratification_mannwhitney_q"),
        "context": ("partner", "deficiency_type"),
        "comparability": {
            "measurement_type": "crispr_partner_stratified_dependency",
            "sample_context": "partner_stratified_cell_line_panel",
            "grain": "target",
        },
        # n_effective = the partner-deficient stratum size (the count the stratification test rests on).
        "reliability": {"n_effective_anchor": "n_partner_deficient"},
    },
    {
        "name": "chemical_genetic_engagement",
        "card_id": "prism-crispr-concordance",
        "property_field": "crispr_prism_concordance_class",
        "anchors": ("n_compounds_evaluated", "n_dual_responders", "best_spearman_r_crispr", "best_spearman_r_rnai"),
        "context": (),
        "comparability": {
            "measurement_type": "prism_crispr_chemical_genetic_concordance",
            "sample_context": "pan_cancer_cell_line_panel",
            "grain": "target",
        },
        # n_effective = the number of PRISM compounds evaluated for the CRISPR/RNAi concordance.
        "reliability": {"n_effective_anchor": "n_compounds_evaluated"},
    },
    {
        "name": "paralog_buffering",
        "card_id": "paralog-buffering",
        "property_field": "paralog_buffering_class",
        "anchors": ("n_paralogs_annotated", "n_paralogs_functionally_buffering", "strongest_paralog_delta"),
        "context": ("strongest_paralog_symbol", "strongest_paralog_ohnolog_status"),
        "comparability": {
            "measurement_type": "paralog_dual_ko_buffering",
            "sample_context": "pan_cancer_cell_line_panel",
            "grain": "target",
        },
        # n_effective = the number of paralogs annotated (the denominator behind those buffering).
        "reliability": {"n_effective_anchor": "n_paralogs_annotated"},
    },
)

_DEPENDENCY_SKILL = "functional-requirement"


@functools.lru_cache(maxsize=None)
def _dependency_reach_map(skills_root: "str | None" = None) -> dict:
    """{(card_id, field): interpretation_reach} for the functional-requirement ledger — the SECOND
    disposition axis (SK#1525), read-only, sourced the same way `role_for` sources the first axis.

    Returns {} when this skill's ledger declares the reach axis on no row (the mechanism is wired anyway
    and proven by a test pointing it at a ledger that DOES declare it, so anchors type themselves the day
    the FR ledger gains reach rows). Empty when the ledger is absent, so anchor typing stays
    additive/byte-stable where the source is missing. Mirrors safety_claims._safety_reach_map."""
    from _skills_common.field_disposition_contract import INTERPRETATION_REACH
    from _skills_common.field_disposition_ledger import (
        LEDGER_NAME,
        _default_skills_root,
        iter_rows,
        load_ledger,
    )

    root = Path(skills_root) if skills_root else _default_skills_root()
    path = root / _DEPENDENCY_SKILL / LEDGER_NAME
    if not path.exists():
        return {}
    doc = load_ledger(path)
    return {
        (cid, field): spec["interpretation_reach"]
        for cid, field, spec in iter_rows(doc)
        if spec.get("interpretation_reach") in INTERPRETATION_REACH
    }


def _typed_dependency_anchor(card_id, field, value, *, skills_root=None):
    """One retained quantitative anchor: {field, value, scale} + the ledger-declared disposition typing
    (semantic_role via the role axis, interpretation_reach via the reach axis, #1525) when this skill's
    ledger declares them. Typing keys are OMITTED when the ledger does not classify the field, so the
    anchor never fabricates a disposition it cannot source."""
    from _skills_common.field_disposition_ledger import role_for

    anchor = {"field": field, "value": value, "scale": _DEPENDENCY_ANCHOR_SCALE.get(field, "raw")}
    role = role_for(card_id, field, _DEPENDENCY_SKILL, skills_root=Path(skills_root) if skills_root else None)
    if role is not None:
        anchor["semantic_role"] = role
    reach = _dependency_reach_map(skills_root).get((card_id, field))
    if reach is not None:
        anchor["interpretation_reach"] = reach
    return anchor


def _source_properties(c: dict, *, skills_root=None) -> "dict | None":
    """The NAMED, typed L2a source_properties map for the DEPENDENCY domain (PR-1b): one entry per
    source/grain, lifting the per-source observational properties out of the four claim signal blocks
    into an explicit, recoverable object. Returns None when no source resolves (whole key omitted →
    byte-stable), matching the atom discipline on this vector. Pure projection, verdict-inert, carries no
    signal tier. Takes the cards-by-id map only: every dependency class is a verbatim card read, so
    unlike the safety domain there is no headline-evaluated disjunction to report."""
    out = {}
    for recipe in _SOURCE_PROPERTY_RECIPES_DEPENDENCY:
        summ = c.get(recipe["card_id"], {}) or {}
        prop = summ.get(recipe["property_field"])
        # A source with no card / no resolved observational class emits no entry (byte-stable).
        if not prop or prop == "data_unavailable":
            continue
        entry = {
            "card_id": recipe["card_id"],
            # The L1 card field the class token was read from — NAMED on the entry (following the safety
            # seed) so every entry reconstructs to L1 as {card_id, property_field, property}.
            "property_field": recipe["property_field"],
            "property": prop,
            "anchors": [
                _typed_dependency_anchor(recipe["card_id"], f, summ[f], skills_root=skills_root)
                for f in recipe["anchors"]
                if summ.get(f) is not None
            ],
            "comparability": dict(recipe["comparability"]),
        }
        # Retained categorical qualifiers that orient the anchors without being quantities themselves.
        # OMITTED entirely when the card supplies none, keeping a partial-card run byte-stable.
        context = {f: summ[f] for f in recipe["context"] if summ.get(f) is not None}
        if context:
            entry["context"] = context
        # The typed `reliability` facet (#2306 step 2): a PURE projection over the entry's OWN retained
        # anchors + this recipe's n-anchor spec. Verdict-inert (SK#2091). Always present (powered is
        # required); every OTHER field on the entry stays byte-identical. See _skills_common/reliability.py.
        entry["reliability"] = _derive_reliability(entry["anchors"], recipe["reliability"])
        out[recipe["name"]] = entry
    return out or None


def dependency_claim_vector(headline: dict, cards: list) -> dict:
    """The modality-blind claim vector {DEP,SEL,COND,CHEM: {signal, corroboration, evidence, conflict,
    informs}, _disclaimer}. Verdict-inert projection over the computed headline."""
    vec = build_claim_vector(DEPENDENCY_CLAIM_SPEC, headline, cards, _DISCLAIMER)
    # L2b-2 cross-source integration claim (SK#1533): CRISPR × RNAi essentiality concordance. Carries NO
    # `signal` key → not a chip, not a tier; OMITTED (byte-stable) unless at least one assay resolves —
    # and the FULL concordance/discordance read requires BOTH. Reads the two assay cards directly (the
    # DEP/SEL/COND/CHEM axes read their signals off the HEADLINE and cite OTHER CRISPR-card fields, so this
    # never perturbs them). Matches the presence L2b-1 (`bulk_vs_singlecell_coverage_concordance`) pattern.
    _ess = _essentiality_concordance_claim(cards_by_id(cards))
    if _ess is not None:
        vec["crispr_rnai_essentiality_concordance"] = _ess
    # L2a NAMED source_properties map (PR-1b, #2210): the per-source observational properties lifted out
    # of the four claim signal blocks into a named, typed, L1-reconstructable object. Carries NO `signal`
    # key on any entry → not a chip, not a tier, read by no rule/verdict/ladder. OMITTED entirely
    # (byte-stable) when no source resolves, matching the concordance-claim discipline directly above.
    _props = _source_properties(cards_by_id(cards))
    if _props is not None:
        vec["source_properties"] = _props
    return vec


def dependency_key_signals(headline: dict, cards: list) -> dict:
    """A brief, direct, CITED read (deterministic; available without the LLM)."""
    vec = dependency_claim_vector(headline, cards)
    h = headline

    def sup_dep(claim):
        cc = h.get("cross_consortium_class")
        bits = [f"CRISPR {h.get('crispr_call')}"]
        if h.get("rnai_call"):
            bits.append(f"RNAi {h['rnai_call']}")
        cite = "[CRISPR + RNAi distributions" + (
            "; Broad↔Sanger cross-consortium]" if cc == "concordant_dependent" else "]"
        )
        tail = " — independently corroborated across consortia" if cc == "concordant_dependent" else ""
        return f"Genetic dependency — {', '.join(bits)}{tail} {cite}"

    def sup_sel(claim):
        return (
            f"Lineage-selective dependency ({h.get('lineage_selectivity')}, "
            f"{h.get('n_lineages_evaluated')} lineages) [dependency-lineage-selectivity]"
        )

    def sup_cond(claim):
        return (
            f"Partner-conditional (synthetic-lethal) dependency — {h.get('partner_conditional_class')} "
            f"[partner-conditional-dependency]"
        )

    def sup_chem(claim):
        return (
            f"Chemical-genetic confirmation — {h.get('prism_concordance_class')} across "
            f"{h.get('n_compounds_evaluated')} PRISM compounds [prism-crispr-concordance]"
        )

    def cav_dep(claim):
        return f"Weak/absent genetic dependency — CRISPR {h.get('crispr_call')} [CRISPR + RNAi distributions]"

    def cav_sel(claim):
        return (
            f"Not lineage-selective — {h.get('lineage_selectivity')}; the dependency (if any) is not "
            f"lineage-concentrated [dependency-lineage-selectivity]"
        )

    def cav_chem(claim):
        if h.get("prism_concordance_class") == "discordant_off_target_likely":
            return "PRISM compound kill does not track the genetic dependency — likely off-target [prism-crispr-concordance]"
        return (
            f"Chemical-genetic confirmation thin/absent — {h.get('prism_concordance_class')} [prism-crispr-concordance]"
        )

    def head(v, supports):
        dep, sel, chem, cond = (v["DEP"]["signal"], v["SEL"]["signal"], v["CHEM"]["signal"], v["COND"]["signal"])
        # The DEP claim already carries the decisive caveat as its `conflict` (dependency_claims._dep_signal):
        # pan-essential (broad-toxicity liability) or an RNAi non-corroboration. head() must READ it — else a
        # pan-essential (resolved verdict pan_essential_killer, "argues AGAINST") reads as a bare "Strong
        # genetic dependency." win, and a CRISPR-dependent+RNAi-disagreeing case (verdict discordant) does the
        # same. This is the tumor-selectivity #862 over-claim class. Verdict-INERT: the resolver owns the
        # verdict; this only aligns the human-facing headline with the conflict the claim vector already found.
        dep_conflict = v["DEP"].get("conflict") or ""
        if dep_conflict.startswith("pan-essential"):
            # a broad-toxicity LIABILITY, not a selective-dependency win — mirrors the pan_essential_killer
            # verdict phrase; the ", chemically confirmed" suffix is not meaningful framing for a liability.
            return "Pan-essential dependency — broad-toxicity liability, not a selective target."
        rnai_disagrees = "does not corroborate" in dep_conflict
        if sig_ge(dep, "moderate") and sig_ge(sel, "strong"):
            base = "Selective genetic dependency."
        elif sig_ge(dep, "strong"):
            base = "Strong genetic dependency."
        elif sig_ge(dep, "moderate"):
            base = "Genetic dependency, with caveats."
        elif sig_ge(cond, "moderate"):
            base = "Conditional (synthetic-lethal) dependency."
        elif dep == "absent":
            base = "Not a genetic dependency in the pooled panel."
        else:
            base = "Dependency largely unmeasured or not distinguishing."
        if rnai_disagrees and sig_ge(dep, "moderate"):
            base = base.rstrip(".") + ", but RNAi (orthogonal LoF) does not corroborate."
        if sig_ge(chem, "moderate") and sig_ge(dep, "moderate"):
            base = base.rstrip(".") + ", chemically confirmed."
        return base

    ks = build_key_signals(
        vec,
        rank_keys=("DEP", "SEL", "COND", "CHEM"),
        support_fns={"DEP": sup_dep, "SEL": sup_sel, "COND": sup_cond, "CHEM": sup_chem},
        critical_keys=("DEP", "SEL", "CHEM"),  # COND is a positive-only rescue; not a critical caveat axis
        caveat_fns={"DEP": cav_dep, "SEL": cav_sel, "CHEM": cav_chem},
        headline_fn=head,
    )
    # Surface the DEP `conflict` (pan-essential broad-tox / RNAi non-corroboration) as the caveat when present:
    # it is the decision-critical caveat, but build_key_signals only surfaces a weak-tier critical claim's
    # caveat, so for a STRONG-tier DEP with a conflict (exactly the pan-essential / discordant cases) it would
    # otherwise be dropped in favour of a lesser SEL caveat. Verdict-inert (a display-surface reconciliation).
    dep_conflict = (vec.get("DEP") or {}).get("conflict")
    if dep_conflict:
        ks["caveat"] = dep_conflict
    # Paralog-buffering caveat (2026-09-03): a STRONG paralog buffer is a decision-relevant caveat the
    # claim vector's four axes do not carry — a single-gene KO/KD dependency can be UNDER-called because a
    # redundant paralog compensates (Dede 2020; Parrish 2021), and a present dependency may need combined
    # paralog loss or an upstream pan-family node (e.g. RAS→SOS1/SHP2; Hofmann 2021) to be fully realised.
    # Surfaced ONLY when there is no MORE-critical DEP conflict (pan-essential broad-tox / RNAi
    # non-corroboration outrank it) so it never masks the sharper caveat. Verdict-INERT: the resolver's
    # non_dependent_paralog_buffered rung already owns the veto-suppression; this only surfaces the note.
    # Gated on the paralog_buffering_class HEADLINE field → no-op when absent (byte-stable on fixtures that
    # omit it, incl. the KRAS/COADREAD unit fixture); fires on the live run (KRAS paralog=strong, NRAS).
    elif h.get("paralog_buffering_class") == "strong":
        _par = h.get("strongest_paralog_symbol")
        ks["caveat"] = (
            "Strong paralog buffering"
            + (f" ({_par})" if _par else "")
            + " — the single-gene dependency may be redundancy-masked; combined paralog loss "
            "or an upstream pan-family node may be required [paralog-buffering]"
        )
    # PARTIAL paralog buffer on an ABSENCE verdict (2026-09-04): when CRISPR/RNAi read the target as
    # non-dependent OR discordant AND a paralog exists (even at `partial`), the apparent absence may be a
    # paralog-masking artifact — single-gene KO under-calls a vulnerability that shifts to the redundant
    # paralog (the SMARCA4→SMARCA2 SL class; Hoffman 2014; Helming 2014). Scoped to absence verdicts so a
    # weak `partial` paralog on a POSITIVE call (e.g. BRAF/MAP3K7 lineage_selective) does not add noise;
    # `strong` on any verdict is already caught above. Gated on paralog_buffering_class + dependency_verdict
    # HEADLINE fields → no-op on the KRAS unit fixture (omits both). Verdict-INERT (the resolver's
    # non_dependent_paralog_buffered rung fires only on STRONG buffering; this only surfaces the caveat).
    elif h.get("paralog_buffering_class") == "partial" and h.get("dependency_verdict") in _ABSENCE_VERDICTS:
        _par = h.get("strongest_paralog_symbol")
        ks["caveat"] = (
            "Non-dependent/discordant read, but a paralog buffer"
            + (f" ({_par}, partial)" if _par else " (partial)")
            + " may under-call a paralog-buffered vulnerability — the absence reflects direct "
            "single-gene requirement, not the paralog node; check the paralog synthetic-lethal "
            "(COND axis) [paralog-buffering]"
        )
    return ks


__all__ = ["dependency_claim_vector", "dependency_key_signals", "DEPENDENCY_CLAIM_SPEC"]
