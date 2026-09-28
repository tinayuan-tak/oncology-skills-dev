"""cis_coherence_claims — cis-feature-coherence's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT LEG
decomposition of the locus→expression→dependency coherence cross-tab into orthogonal (signal ×
corroboration) claims with citable atoms.

A concrete claim_vector_core instance. The cis_coherence VERDICT is a 2×2 INTERACTION (cross-tab
of separable legs), so the claim_vector is the LEG DECOMPOSITION — NOT a verdict echo. Four axes:

  CIS_DOSAGE   leg-1:     CN → own-expression cis-dosage       (cis-feature-expression-coherence)
  SILENCING    leg-1 LoF: promoter methylation → LOW expression (cellline-methylation-expression-coherence)
  EXPR_DEP     leg-2:     expression → dependency correlation    (expression-dependency-correlation)
  CONJOINT     leg-2:     amp∩overexpr conjoint addiction        (amp-expr-stratified-dependency)

DISTINCTIVE — a REAL corroboration arm: unlike the flat "moderate-if-measured" of other concretes,
SILENCING draws corroboration from the pre-computed cross-grain PATIENT agreement boolean (does the
TCGA patient arm replicate the cell-line call?) — a genuine second evidence leg.

CIS_DOSAGE's cross-grain corroboration was MIGRATED (SK#1781, epic #1779 / parent #1507): its LEG axis
now scores plain single-source corroboration (the cell-line cis_dosage_class alone), and the cross-grain
cell-line × patient integration lives in the FIRST envelope-v0 concordance claim for this domain,
`_cis_dosage_concordance_claim` → the verdict-INERT `cis_dosage_concordance` key on the claim_vector
(docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md). The pre-envelope `patient_dosage_agrees_with_cellline` boolean
still feeds run.py's caveats; only its use AS the CIS_DOSAGE fold was retired.

VALENCE: CIS_DOSAGE / EXPR_DEP / CONJOINT are positive (cis-driven addiction); SILENCING is DESCRIPTIVE
(a coherent silencing signal is therapeutically INVERSE — LoF / SL-reactivation, not direct inhibition;
meaning in the atom). `absent` = measured uncoupled / no-correlation; `negative` = a MEASURED wrong-
direction read (positive_anomaly / amp_expr_negative_more_dependent — paralog compensation / masking);
`unmeasured` = invariant/untestable panel or gap (the resolver ABSTAINS here — never `absent`).

DIRECTION (card v1.1.0): CIS_DOSAGE's tier says leg-1 is intact, not which CN arm carries it — an amplicon
oncogene and a deleted suppressor both read cn_dosage_coupled_*. The direction (`cis_dosage_direction` +
its basis) travels in the CIS_DOSAGE atom and is what makes the tier's GoF reading legitimate; only
amplification_coupled is a gain-driven addiction claim, so the axis label stays direction-neutral here and
the atom carries the arm. SILENCING gained a third state, `silencing_lineage_confounded` → `unmeasured`
(measured, but not interpretable as cis silencing — see _SILENCING_SIGNAL).

Verdict-INERT: reads the already-computed _headline (+ source cards) and never feeds resolve_or_raise.
"""

from __future__ import annotations

from _skills_common.claim_vector_core import (
    ClaimSpec,
    arm_from_class,
    build_claim_vector,
    build_key_signals,
    cards_by_id,
    corroboration_from_arms,
)
from _skills_common.claim_vector_core import corr as _plain_corr

_CIS_DOSAGE_SIGNAL = {
    "cn_dosage_coupled_strong": "strong",
    "cn_dosage_coupled_moderate": "moderate",
    "cn_dosage_uncoupled": "absent",  # MEASURED: expression is CN-independent
    "cn_invariant_panel": "unmeasured",  # untestable (no CN variation) — resolver abstains
    "data_unavailable": "unmeasured",
}
_SILENCING_SIGNAL = {
    "silencing_coupled_strong": "strong",
    "silencing_coupled_moderate": "moderate",
    "methylation_uncoupled": "absent",  # MEASURED negative: tested within lineage, not silenced
    # card v1.1.0 THIRD state: a large pan-panel hypermethylated-vs-rest contrast that COLLAPSES once
    # conditioned on lineage (CDH1 -4.44 → -0.45; MET -4.99 → -0.85), i.e. what was measured is lineage
    # separation, not promoter silencing. `unmeasured`, NOT `absent`: a within-lineage-POWERED silencing test
    # has not been run, so this is neither a silencing claim nor a refutation of one, and calling it a
    # measured floor would let it read as evidence against silencing. The tier is a gap; the atom's read
    # string still names the class, so it stays distinguishable from data_unavailable in the output.
    "silencing_lineage_confounded": "unmeasured",
    "methylation_invariant_panel": "unmeasured",
    "data_unavailable": "unmeasured",
}
_EXPR_DEP_SIGNAL = {
    "strong_negative": "strong",
    "moderate_negative": "moderate",
    "weak_negative": "weak",
    "no_correlation": "absent",
    "positive_anomaly": "negative",  # MEASURED wrong direction (paralog compensation)
    "data_unavailable": "unmeasured",
}
_CONJOINT_SIGNAL = {
    "amplified_overexpressed_strongly_dependent": "strong",
    "amplified_overexpressed_moderately_dependent": "moderate",
    "not_amp_expr_stratified": "absent",
    "amp_expr_negative_more_dependent": "negative",  # MEASURED: amp-expr subset is LESS dependent
    "insufficient_amp_expr_rate": "unmeasured",
    "data_unavailable": "unmeasured",
}

_INFORMS = {
    "CIS_DOSAGE": (
        "leg-1 — CN→own-expression cis-dosage coupling, DIRECTION-resolved (amplification_coupled = "
        "gain-driven expression, the GoF/addiction reading; deletion_coupled = loss-driven low expression, "
        "an LoF reading that cannot support a direct-inhibition claim)"
    ),
    "SILENCING": (
        "leg-1 LoF — promoter-methylation→LOW-expression silencing (therapeutically INVERSE: "
        "SL/reactivation hypothesis, not direct inhibition)"
    ),
    "EXPR_DEP": "leg-2 — expression→dependency correlation (higher expression ⇒ more dependent)",
    "CONJOINT": "leg-2 — amp∩overexpr conjoint addiction (the amplified-overexpressed subset is more dependent)",
}

_C_CIS = "cis-feature-expression-coherence"
_C_METH = "cellline-methylation-expression-coherence"
_C_CORR = "expression-dependency-correlation"
_C_AMPX = "amp-expr-stratified-dependency"

_E_CIS = {
    "measurement_type": "cis_feature_expression_coherence",
    "grain": "target_indication",
    "sample_context": "cell_line",
}
_E_METH = {
    "measurement_type": "methylation_expression_coherence",
    "grain": "target_indication",
    "sample_context": "cell_line",
}
_E_CORR = {
    "measurement_type": "expression_dependency_correlation",
    "grain": "target_indication",
    "sample_context": "cell_line",
}
_E_AMPX = {
    "measurement_type": "amp_expr_stratified_dependency",
    "grain": "target_indication",
    "sample_context": "cell_line",
}


def _sig(card, field, smap, neg_conflict=None):
    def fn(h, c):
        cls = (c.get(card) or {}).get(field)
        tier = smap.get(cls, "unmeasured")
        conflict = neg_conflict if (tier == "negative" and neg_conflict) else None
        return tier, f"{card}: {cls or 'data_unavailable'}", conflict

    return fn


def _patient_corr(card, field, smap, agree_key):
    """Corroboration from the cross-grain PATIENT agreement boolean — a real second arm, so this axis
    can legitimately reach the top of the ladder: `high` when the TCGA patient arm AGREES, `low` on
    explicit DISAGREEMENT, `unmeasured` when the cell-line class is a gap, and `single_arm` when the
    patient arm was never read (`agree_key` absent) — the cell-line call then stands alone and must not
    be reported as corroborated. That last rung used to be `moderate`, which manufactured partial
    agreement out of a missing arm."""

    def fn(h, c):
        if smap.get((c.get(card) or {}).get(field), "unmeasured") == "unmeasured":
            return "unmeasured"
        agree = h.get(agree_key)
        if agree is True:
            return "high"
        if agree is False:
            return "low"
        return "single_arm"  # no patient arm read at all — the cell-line call stands alone

    return fn


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, entity, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _mk_atom(card, field, keys, entity):
    def fn(h, c):
        s = c.get(card) or {}
        return _atom(card, s, keys, entity, s.get(field))

    return fn


CIS_COHERENCE_CLAIM_SPEC = [
    ClaimSpec(
        "CIS_DOSAGE",
        "CN→expression cis-dosage",
        _sig(_C_CIS, "cis_dosage_class", _CIS_DOSAGE_SIGNAL),
        # RETIRED (SK#1781): the bespoke `_patient_corr` cross-grain fold — a boolean that reached `high`
        # from ONE patient-agreement flag on the cell-line arm — is the pre-envelope anti-pattern. The
        # principled cross-grain (model × patient) corroboration now lives in the dedicated
        # `_cis_dosage_concordance` envelope claim (measured-arm frame, ARM_FLOOR-aware, key-omitted when
        # neither grain resolves). The CIS_DOSAGE leg axis reverts to the plain single-source corroboration
        # (`single_arm` when the cell-line class is measured, else `unmeasured`) like EXPR_DEP / CONJOINT.
        # SILENCING keeps its `_patient_corr` fold until its own concordance claim lands.
        _plain_corr(_C_CIS, "cis_dosage_class", _CIS_DOSAGE_SIGNAL),
        _INFORMS["CIS_DOSAGE"],
        _mk_atom(
            _C_CIS,
            "cis_dosage_class",
            (
                "cis_dosage_class",
                # DIRECTION + basis (card v1.1.0): the class alone cannot separate an amplicon driver from a
                # deleted suppressor, so the citable atom carries which arm the coupling came off.
                "cis_dosage_direction",
                "cis_dosage_direction_basis",
                "cn_expr_spearman_r",
                "cn_expr_spearman_p",
                "cn_expr_slope_log2tpm_per_cn",
                "delta_log2tpm_amplified_vs_neutral",
                # the LINEAGE-controlled version of that contrast — the one a cis claim has to survive
                "subset_within_lineage_delta_log2tpm",
                "n_amplified",
                "deleted_subset_delta_log2tpm",
                "n_deleted",
                "relative_cn_iqr",
                "evidence_scope",
                "n_cell_lines_evaluated",
            ),
            _E_CIS,
        ),
    ),
    ClaimSpec(
        "SILENCING",
        "methylation→low-expression",
        _sig(_C_METH, "methylation_silencing_class", _SILENCING_SIGNAL),
        _patient_corr(
            _C_METH, "methylation_silencing_class", _SILENCING_SIGNAL, "patient_silencing_agrees_with_cellline"
        ),
        _INFORMS["SILENCING"],
        _mk_atom(
            _C_METH,
            "methylation_silencing_class",
            (
                "methylation_silencing_class",
                "silencing_driver",
                "subset_median_delta_log2tpm",
                # the LINEAGE-controlled contrast + the collapse RATIO (within/pan) that produced the
                # silencing_lineage_confounded class (card v1.1.0) — cited so a reader can see whether the
                # pan-panel delta survived conditioning on lineage.
                "subset_within_lineage_delta_log2tpm",
                "lineage_collapse_ratio",
                "subset_mannwhitney_p",
                "methyl_expr_spearman_r",
                "broad_quartile_delta_log2tpm",
                "n_hypermethylated",
            ),
            _E_METH,
        ),
    ),
    ClaimSpec(
        "EXPR_DEP",
        "expression→dependency",
        _sig(
            _C_CORR,
            "correlation_class",
            _EXPR_DEP_SIGNAL,
            neg_conflict=(
                "positive_anomaly — expression correlates with LESS dependency (wrong direction; "
                "possible paralog compensation), NOT a cis-driven addiction"
            ),
        ),
        _plain_corr(_C_CORR, "correlation_class", _EXPR_DEP_SIGNAL),
        _INFORMS["EXPR_DEP"],
        _mk_atom(
            _C_CORR,
            "correlation_class",
            (
                "correlation_class",
                "pearson_r",
                "pearson_p",
                "spearman_r",
                "delta_chronos_top_vs_bottom_quartile",
                "n_cell_lines_evaluated",
            ),
            _E_CORR,
        ),
    ),
    ClaimSpec(
        "CONJOINT",
        "amp∩overexpr addiction",
        _sig(
            _C_AMPX,
            "amp_expr_stratification_class",
            _CONJOINT_SIGNAL,
            neg_conflict=(
                "amp_expr_negative_more_dependent — the amplified-overexpressed subset is LESS "
                "dependent (wrong direction), NOT conjoint addiction"
            ),
        ),
        _plain_corr(_C_AMPX, "amp_expr_stratification_class", _CONJOINT_SIGNAL),
        _INFORMS["CONJOINT"],
        _mk_atom(
            _C_AMPX,
            "amp_expr_stratification_class",
            (
                "amp_expr_stratification_class",
                "delta_chronos_amp_expr_vs_rest",
                "amp_expr_mannwhitney_q",
                "amp_expr_effect_size",
                "n_amplified_overexpressed",
                "n_comparator",
                "evidence_scope",
            ),
            _E_AMPX,
        ),
    ),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT LEG DECOMPOSITION of the cis-coherence cross-tab into orthogonal claims "
    "(CIS_DOSAGE / SILENCING / EXPR_DEP / CONJOINT), each signal×corroboration. The cis_coherence VERDICT is "
    "an INTERACTION of these legs (owned by the resolver) — this is the decomposition + citable atoms, NOT a "
    "verdict echo. CIS_DOSAGE/SILENCING corroboration draws on the cross-grain TCGA patient-agreement arm "
    "(a real second leg). SILENCING is therapeutically INVERSE (LoF/reactivation). `absent` = measured "
    "uncoupled/no-correlation; `negative` = a measured WRONG-direction read; `unmeasured` = invariant/untestable "
    "or gap (the resolver abstains, never `absent`). Claims are NOT averaged; never feeds the verdict."
)


# ── L2b CROSS-GRAIN concordance claim (SK#1781, epic #1779 / parent #1507) ──────────────────────────
# The shared cis-dosage token vocabulary (identical on BOTH grains: `cis_dosage_class` on the cell-line
# card and `patient_cis_dosage_class` on the patient card — both produced by the SAME `compute_cis_dosage`
# kernel, so the two arms score the SAME property). Coupled tokens AGREE that CN drives own-expression; the
# measured `cn_dosage_uncoupled` floor DISAGREES (a real not-coupled call, not a gap). `cn_invariant_panel`
# (untestable — no CN variation) and `data_unavailable` / any off-roster token are UNRESOLVED (None): they
# leave the arm frame rather than voting, per `arm_from_class`.
_CIS_DOSAGE_COUPLED = frozenset({"cn_dosage_coupled_strong", "cn_dosage_coupled_moderate"})
_CIS_DOSAGE_UNCOUPLED = frozenset({"cn_dosage_uncoupled"})

_CIS_DOSAGE_GRAIN = {
    "cell_line_model": "cell-line model (DepMap panel)",
    "patient_tumour": "patient tumour cohort (TCGA)",
}
_CIS_DOSAGE_CARD = {
    "cell_line_model": _C_CIS,
    "patient_tumour": "patient-cis-coherence",
}
_CIS_DOSAGE_FIELD = {
    "cell_line_model": "cis_dosage_class",
    "patient_tumour": "patient_cis_dosage_class",
}


def _cis_dosage_concordance_claim(c: dict) -> "dict | None":
    """L2b CROSS-GRAIN integration claim: `cis_dosage_concordance` — the FIRST envelope-v0 concordance
    claim for the cis_coherence domain (docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md), property_id
    `cis_dosage_coupling`.

    Integrates the two cross-GRAIN arms of the SAME cis-dosage-coupling property by an EXPLICIT
    DETERMINISTIC rule (no LLM; L2b is reproducible by contract):
      * cell-line MODEL grain — `cis-feature-expression-coherence`.`cis_dosage_class` (DepMap panel);
      * patient TUMOUR grain  — `patient-cis-coherence`.`patient_cis_dosage_class` (TCGA cohort).
    Both are produced by the SAME `compute_cis_dosage` kernel (per-model / per-case GISTIC CN vs TPM), so
    this is a genuine cross-grain replication of ONE property, emitting one of:
      * cis_dosage_concordant_coupled    — both grains resolve and AGREE the CN→expression coupling holds;
      * cis_dosage_concordant_uncoupled   — both resolve and AGREE it is a measured NOT-coupled floor;
      * cis_dosage_grain_discordant        — one grain couples, the other does not (a which-grain-couples
        payload — the disagreement is INFORMATIVE, culture vs TME/purity/cohort, never collapsed/averaged);
      * cis_dosage_single_grain_only       — exactly ONE grain resolves, the other is a gap: the degraded
        read that names the resolved grain (recoverable), NOT a concordance claim.

    GRAIN is FIRST-CLASS: the two arms are DELIBERATELY at DIFFERENT sample-context grains (cell-line model
    vs patient tumour), recorded per source in `source_support[].grain`. A same-grain restatement (e.g. a
    second cell-line read) would NOT be a second independent arm — the #1704 arm-commensurability oracle
    pins the two DISTINCT (card, field) arms so a re-pointed arm reds. Patient thresholds are coarser (the
    amplified edge is GISTIC +1 (any gain) vs the cell-line focal-amp cut) so the two are comparable in
    DIRECTION, not exact thresholds — carried in `provenance.independence_note`.

    Corroboration is on the shared MEASURED-ARM frame: two agreeing grains → high, a disagreement → low,
    one measured grain with the other unresolved → single_arm (below CORROBORATION_ARM_FLOOR: a lone grain
    is never corroborated). So a single-grain mutation only DEGRADES the read to `cis_dosage_single_grain_
    only`; ERASING the claim (key omitted, byte-stable) takes defeating BOTH grain supplies. There is NO
    dependent/derived source here (the two grains are genuinely independent), so nothing can resurrect the
    claim once both arms are gone (the M3 all-supply-fidelity discipline).

    VERDICT-INERT: carries NO `signal` key (never a chip, never a tier, never averaged), reads no verdict,
    feeds no rule; the `cis_coherence_verdict` + resolver golden stay byte-stable. Returns None — key
    omitted (byte-stable) — when NEITHER grain resolves."""
    # ARM READS — the INLINE `(c.get("<card>") or {}).get("<field>")` idiom the #1704 oracle pins as the
    # two commensurate arms. Read ONLY the two class fields this way; raw metrics are pulled off a LOCAL
    # card binding below so they are NOT mistaken for a third arm.
    cl_class = (c.get("cis-feature-expression-coherence") or {}).get("cis_dosage_class")
    pt_class = (c.get("patient-cis-coherence") or {}).get("patient_cis_dosage_class")

    # Resolve each grain's token → coupled(True) / uncoupled(False) / unresolved(None) via the shared
    # arm reader (handles the truthy `data_unavailable` sentinel + off-roster/`cn_invariant_panel` → None).
    cl = arm_from_class(cl_class, agrees=_CIS_DOSAGE_COUPLED, disagrees=_CIS_DOSAGE_UNCOUPLED)
    pt = arm_from_class(pt_class, agrees=_CIS_DOSAGE_COUPLED, disagrees=_CIS_DOSAGE_UNCOUPLED)

    resolved = [(name, v) for name, v in (("cell_line_model", cl), ("patient_tumour", pt)) if v is not None]
    if not resolved:
        return None  # neither grain resolves → key omitted (byte-stable)

    if len(resolved) == 1:
        concordance = "cis_dosage_single_grain_only"
    elif cl == pt:
        concordance = "cis_dosage_concordant_coupled" if cl else "cis_dosage_concordant_uncoupled"
    else:
        concordance = "cis_dosage_grain_discordant"

    # Corroboration over the two grains. For a discordance the arms point opposite ([True, False] → low);
    # for a concordance both agree ([True, True] → high); with one grain unresolved the measured grain is
    # unopposed ([True, None] → single_arm, below the arm floor).
    if concordance == "cis_dosage_grain_discordant":
        cl_arm, pt_arm = True, False
    else:
        cl_arm = True if cl is not None else None
        pt_arm = True if pt is not None else None
    corroboration = corroboration_from_arms([cl_arm, pt_arm])

    # The envelope's TWO COUNTS. Both grains are genuinely INDEPENDENT (no pooled / derived superset here),
    # so the counts coincide — but they are emitted separately to keep the envelope shape uniform with the
    # families that DO carry a dependent source (e.g. recurrence's pooled arm).
    corroborating_independent_arm_count = len(resolved)
    resolved_source_count = corroborating_independent_arm_count

    def _dir(v):
        return "coupled" if v is True else ("uncoupled" if v is False else None)

    _class = {"cell_line_model": cl_class, "patient_tumour": pt_class}
    _val = {"cell_line_model": cl, "patient_tumour": pt}

    # which-grain payload — the disagreement or the degraded single grain is NAMED, never collapsed.
    if concordance == "cis_dosage_grain_discordant":
        coupled_in = "cell_line_model" if cl else "patient_tumour"
        uncoupled_in = "patient_tumour" if cl else "cell_line_model"
        concordance_support = {"coupled_in": coupled_in, "uncoupled_in": uncoupled_in}
    elif concordance == "cis_dosage_single_grain_only":
        name, v = resolved[0]
        concordance_support = {"resolved_by": name, "resolved_call": _class[name], "resolved_direction": _dir(v)}
    else:
        concordance_support = {"agreed_direction": _dir(cl)}

    # ── uniform per-source support + retained_quantitative (raw metrics DEMOTED, not dropped) ──────────
    # Raw metrics are read off a LOCAL card binding (NOT the inline `c.get(...)` arm idiom) so the #1704
    # oracle sees exactly the two class-field arms and no incommensurate third pair.
    _cl_card = c.get("cis-feature-expression-coherence") or {}
    _pt_card = c.get("patient-cis-coherence") or {}
    _retained = {
        "cell_line_model": {
            "cn_expr_spearman_r": _cl_card.get("cn_expr_spearman_r"),
            "cn_expr_spearman_p": _cl_card.get("cn_expr_spearman_p"),
            "cn_expr_slope_log2tpm_per_cn": _cl_card.get("cn_expr_slope_log2tpm_per_cn"),
            "delta_log2tpm_amplified_vs_neutral": _cl_card.get("delta_log2tpm_amplified_vs_neutral"),
            "subset_within_lineage_delta_log2tpm": _cl_card.get("subset_within_lineage_delta_log2tpm"),
            "n_amplified": _cl_card.get("n_amplified"),
            "relative_cn_iqr": _cl_card.get("relative_cn_iqr"),
        },
        "patient_tumour": {
            "cn_expr_spearman_r": _pt_card.get("cn_expr_spearman_r"),
            "cn_expr_spearman_p": _pt_card.get("cn_expr_spearman_p"),
            "delta_log2tpm_amplified_vs_neutral": _pt_card.get("delta_log2tpm_amplified_vs_neutral"),
            "n_amplified": _pt_card.get("n_amplified"),
            "n_cases_expression": _pt_card.get("n_cases_expression"),
        },
    }

    def _support(source):
        v = _val[source]
        return {
            "source": source,
            "grain": source,  # first-class sample-context grain (cell_line_model | patient_tumour)
            "dependence_group": source,
            "value": _class[source],
            "dosage_direction": _dir(v),
            # THREE separate source notions — no single overloaded boolean smuggles two meanings.
            "resolved": v is not None,
            "quality_eligible": v is not None,  # a resolved read is usable evidence, shown & preserved
            "corroboration_eligible": True,  # both grains are independent replication arms
            "provenance": {
                "card_id": _CIS_DOSAGE_CARD[source],
                "field": _CIS_DOSAGE_FIELD[source],
                "grain_context": _CIS_DOSAGE_GRAIN[source],
            },
            # retained_quantitative: the raw dosage metrics DEMOTED not deleted (fidelity/recoverability) —
            # the bespoke fold's numbers are preserved here rather than dropped when it is retired.
            "retained_quantitative": _retained[source],
        }

    # Both grains ALWAYS appear (an absent grain shows resolved:False), keeping the two-count / grain
    # structure legible; they are genuinely independent sample contexts (no derived superset).
    source_support = [_support("cell_line_model"), _support("patient_tumour")]
    evidence_dependence = {
        "groups": [
            {"members": ["cell_line_model"], "relationship": "independent_sample_context"},
            {"members": ["patient_tumour"], "relationship": "independent_sample_context"},
        ],
        "derived_sources": {},
    }

    _PHRASE = {
        "cis_dosage_concordant_coupled": "AGREE the CN→expression cis-dosage coupling holds",
        "cis_dosage_concordant_uncoupled": "AGREE the CN→expression coupling is a measured NOT-coupled floor",
        "cis_dosage_grain_discordant": "DISAGREE — the coupling replicates in only one grain",
        "cis_dosage_single_grain_only": "only one grain resolves",
    }

    # ── PRESENTATION-SUPPORT (SK#1781 L2b surface) — two-directional structured fields + a deterministic
    # boundary-sensitivity flag so a question_table answer can SURFACE the cross-grain read WITHOUT
    # prose-parsing `evidence`. NONE route a verdict, name a signal tier (no `signal` key), or feed a rule.
    boundary_sensitive = corroboration != "high"
    if concordance == "cis_dosage_concordant_coupled":
        _pos_source, _pos = (
            "cell_line_model",
            (
                "Both the cell-line MODEL and patient TUMOUR grains AGREE the target's copy number drives its "
                "own expression (cis-dosage coupled) — a cross-grain-corroborated read."
            ),
        )
    elif concordance == "cis_dosage_concordant_uncoupled":
        _pos_source, _pos = (
            "cell_line_model",
            (
                "Both grains AGREE the copy number does NOT drive expression (a measured cis-dosage-UNCOUPLED "
                "floor across model and patient) — cross-grain corroborated."
            ),
        )
    elif concordance == "cis_dosage_grain_discordant":
        _pos_source = concordance_support["coupled_in"]
        _pos = (
            f"{_CIS_DOSAGE_GRAIN[_pos_source]} reports cis-dosage COUPLING — the CN→expression link is "
            "present in this grain."
        )
    else:  # cis_dosage_single_grain_only
        _pos_source = concordance_support["resolved_by"]
        _pos = (
            f"{_CIS_DOSAGE_GRAIN[_pos_source]} reports {concordance_support['resolved_direction']} cis-dosage "
            f"({concordance_support['resolved_call']}) — the sole grain that resolves."
        )
    positive_signal = {"statement": _pos, "source": _pos_source, "provenance_ref": _pos_source}

    if concordance in ("cis_dosage_concordant_coupled", "cis_dosage_concordant_uncoupled"):
        qualifying_signal = None
    elif concordance == "cis_dosage_grain_discordant":
        _neg = concordance_support["uncoupled_in"]
        qualifying_signal = {
            "statement": (
                f"{_CIS_DOSAGE_GRAIN[_neg]} does NOT replicate the coupling — the grains DISAGREE. This is "
                "INFORMATIVE (culture vs tumour-microenvironment, purity, cohort composition differ; patient "
                "thresholds are coarser), not an error, and never equated with a biological absence."
            ),
            "source": _neg,
            "provenance_ref": _neg,
        }
    else:  # single_grain_only
        _gap = "patient_tumour" if concordance_support["resolved_by"] == "cell_line_model" else "cell_line_model"
        qualifying_signal = {
            "statement": (
                f"Only {_CIS_DOSAGE_GRAIN[concordance_support['resolved_by']]} resolves; "
                f"{_CIS_DOSAGE_GRAIN[_gap]} is a gap — a degraded single-grain read, NOT cross-grain "
                "corroboration."
            ),
            "source": _gap,
            "provenance_ref": _gap,
        }

    return {
        "property_id": "cis_dosage_coupling",
        "concordance_class": concordance,
        "corroboration": corroboration,
        # DETERMINISTIC, reproducible-by-contract: an explicit rule over the two grain tokens, never an LLM.
        "integration_method": "explicit_deterministic",
        # GRAIN first-class: the integration SPANS grains; the per-grain sample-context is on each source.
        "grain": "cross_grain_model_vs_patient",
        "resolved_source_count": resolved_source_count,
        "corroborating_independent_arm_count": corroborating_independent_arm_count,
        "concordance_support": concordance_support,
        "source_support": source_support,
        "positive_signal": positive_signal,
        "qualifying_signal": qualifying_signal,
        "boundary_sensitive": boundary_sensitive,
        "boundary_note": (
            "concordance class rests on a single measured grain (single_arm / low corroboration) — treat as "
            "near-boundary, not a flat cross-grain assertion"
            if boundary_sensitive
            else "concordance corroborated by BOTH the model and patient grains agreeing"
        ),
        "evidence_dependence": evidence_dependence,
        "informs": (
            "cross-grain cis-dosage-coupling concordance — a CN→expression coupling that BOTH the DepMap "
            "cell-line model and the TCGA patient tumour agree on is far more credible than a single-grain "
            "call; a grain disagreement is the informative datum (culture vs tumour context), never averaged"
        ),
        "evidence": (
            f"cell-line {cl_class or 'data_unavailable'} × patient {pt_class or 'data_unavailable'}: "
            + _PHRASE[concordance]
        ),
        "provenance": {
            "sources": source_support,
            "independence_note": (
                "The cell-line cis_dosage_class (DepMap model panel) and patient patient_cis_dosage_class "
                "(TCGA cohort) are measured on genuinely INDEPENDENT sample contexts, so their agreement is "
                "real cross-grain corroboration of the SAME property (both from the compute_cis_dosage "
                "kernel). GRAIN CAVEAT: culture vs tumour-microenvironment / purity / cohort composition "
                "differ, and the patient amplified edge is GISTIC +1 (any gain), coarser than the cell-line "
                "focal-amp cut — the two are comparable in DIRECTION, not in exact thresholds. Grain is "
                "first-class so a same-grain restatement is never counted as a second arm."
            ),
        },
        "_disclaimer": (
            "L2b CROSS-GRAIN integration claim (deterministic, no LLM) — verdict-INERT provenance: never a "
            "signal tier, never averaged into a claim, never feeds the cis_coherence_verdict."
        ),
    }


def cis_coherence_claim_vector(headline: dict, cards: list) -> dict:
    vec = build_claim_vector(CIS_COHERENCE_CLAIM_SPEC, headline, cards, _DISCLAIMER)
    # L2b CROSS-GRAIN integration claim (SK#1781, epic #1779 / parent #1507): cell-line × patient
    # cis-dosage-coupling concordance. Carries NO `signal` key → not a chip, not a tier; OMITTED
    # (byte-stable) unless at least one grain resolves — and the FULL concordance read requires BOTH.
    # Reads the two source cards directly (the CIS_DOSAGE/... leg axes read their signals off the card
    # summaries too, so this never perturbs them). Mirrors the dependency L2b-2
    # (`crispr_rnai_essentiality_concordance`) attach pattern EXACTLY.
    _cd = _cis_dosage_concordance_claim(cards_by_id(cards))
    if _cd is not None:
        vec["cis_dosage_concordance"] = _cd
    return vec


def cis_coherence_key_signals(headline: dict, cards: list) -> dict:
    vec = cis_coherence_claim_vector(headline, cards)
    keys = ("CIS_DOSAGE", "CONJOINT", "EXPR_DEP", "SILENCING")
    return build_key_signals(
        vec,
        rank_keys=keys,
        support_fns={k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})") for k in keys},
        critical_keys=("CIS_DOSAGE", "EXPR_DEP"),
        caveat_fns={},
        headline_fn=lambda v, s: (
            "Cis-coherence leg substrate present."
            if s
            else "Limited cis-coherence leg signal (or untestable/unmeasured panel)."
        ),
        fallback_caveat_fn=lambda: None,
        max_supports=4,
    )


__all__ = ["cis_coherence_claim_vector", "cis_coherence_key_signals", "CIS_COHERENCE_CLAIM_SPEC"]
