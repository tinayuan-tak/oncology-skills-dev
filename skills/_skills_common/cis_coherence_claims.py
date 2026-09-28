"""cis_coherence_claims — cis-feature-coherence's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT LEG
decomposition of the locus→expression→dependency coherence cross-tab into orthogonal (signal ×
corroboration) claims with citable atoms.

A concrete claim_vector_core instance. The cis_coherence VERDICT is a 2×2 INTERACTION (cross-tab
of separable legs), so the claim_vector is the LEG DECOMPOSITION — NOT a verdict echo. Four axes:

  CIS_DOSAGE   leg-1:     CN → own-expression cis-dosage       (cis-feature-expression-coherence)
  SILENCING    leg-1 LoF: promoter methylation → LOW expression (cellline-methylation-expression-coherence)
  EXPR_DEP     leg-2:     expression → dependency correlation    (expression-dependency-correlation)
  CONJOINT     leg-2:     amp∩overexpr conjoint addiction        (amp-expr-stratified-dependency)

CROSS-GRAIN corroboration MIGRATED to envelope-v0 concordance claims (SK#1781 CIS_DOSAGE, SK#1782
SILENCING; epic #1779 / parent #1507): the CIS_DOSAGE and SILENCING LEG axes now score PLAIN single-
source corroboration (the cell-line class alone, like EXPR_DEP / CONJOINT — one arm is never
corroboration), and the principled cross-grain cell-line × patient integration for each property lives in
its OWN verdict-INERT envelope concordance claim on the claim_vector (docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md):
  * `_cis_dosage_concordance_claim`            → `cis_dosage_concordance`            (property cis_dosage_coupling)
  * `_methylation_silencing_concordance_claim` → `methylation_silencing_concordance` (property methylation_silencing_coupling)
The pre-envelope `patient_dosage_agrees_with_cellline` / `patient_silencing_agrees_with_cellline` booleans
still feed run.py's caveats; only their use AS the leg-axis folds was retired.

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
        # RETIRED (SK#1782, mirroring #1781's CIS_DOSAGE migration): the bespoke `_patient_corr` cross-grain
        # fold — a boolean that reached `high` from ONE `patient_silencing_agrees_with_cellline` flag — is the
        # pre-envelope anti-pattern (one arm is never corroboration). The principled cross-grain (model ×
        # patient) silencing corroboration now lives in the dedicated `_methylation_silencing_concordance`
        # envelope claim (measured-arm frame, ARM_FLOOR-aware, key-omitted when neither grain resolves, with
        # the third `silencing_lineage_confounded` state routed to NO rung). The SILENCING leg axis reverts to
        # plain single-source corroboration (`single_arm` when the cell-line class is measured, else
        # `unmeasured`) like CIS_DOSAGE / EXPR_DEP / CONJOINT. The run.py `patient_silencing_agrees_with_cellline`
        # boolean is untouched (still feeds its verdict-inert caveats).
        _plain_corr(_C_METH, "methylation_silencing_class", _SILENCING_SIGNAL),
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
    "verdict echo. Each leg axis scores PLAIN single-source corroboration; the principled cross-grain "
    "cell-line × patient integration lives in the verdict-INERT envelope concordance claims "
    "(cis_dosage_concordance / methylation_silencing_concordance). SILENCING is therapeutically INVERSE "
    "(LoF/reactivation). `absent` = measured "
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

# ── SK#1783 A3: the PROTEIN cis-dosage arm — an assay-MODALITY facet WITHIN the cell-line grain ──────
# CN→PROTEIN cis-dosage read off `cis-feature-protein-coherence`.`cis_protein_dosage_class` (DepMap-Gygi
# mass-spec). It is a SECOND ASSAY MODALITY of the SAME cell-line sample-context grain as the RNA arm
# (bulk-RNA), NOT a third independent GRAIN: protein ⊥ mRNA at the MODALITY level, but they SHARE the
# cell-line grain. So the protein arm and the cell-line-RNA arm are ONE `dependence_group`
# (`cell_line_model`); only the patient arm is the cross-GRAIN corroborator. A same-grain modality
# restatement must NOT inflate `corroborating_independent_arm_count` the way a truly independent grain
# does — that count stays GRAIN-based; the protein modality only grows `resolved_source_count`.
_CIS_PROTEIN_CARD = "cis-feature-protein-coherence"
_CIS_PROTEIN_FIELD = "cis_protein_dosage_class"
# The mRNA-vs-protein slope RATIO is the dosage-BUFFERING fingerprint (classified into
# `cis_protein_dosage_class`): a PRESERVED slope (`prot_dosage_coupled_*`) → the protein CORROBORATES the
# RNA cis-dosage call; a strongly BUFFERED slope (`prot_dosage_uncoupled` — protein flat while mRNA tracks
# CN) is a QUALIFIED / non-corroborating arm surfaced as retained_quantitative, NEVER a silent agree (real
# biology: post-transcriptional buffering tempers ADC / degrader payload expectations, not a failure).
_CIS_PROTEIN_COUPLED = frozenset({"prot_dosage_coupled_strong", "prot_dosage_coupled_moderate"})
_CIS_PROTEIN_BUFFERED = frozenset({"prot_dosage_uncoupled"})


def _mrna_vs_protein_slope_ratio(protein_slope, mrna_slope):
    """mRNA-vs-protein dosage-buffering ratio = protein_slope / mrna_slope (verdict-inert fingerprint;
    mirrors cis-feature-coherence run.py `_slope_ratio`). None when either slope is missing or the mRNA
    slope is ~0 (ratio undefined / uninformative). ~1 = dosage preserved (genuine cis-driver); ≪1 =
    post-transcriptionally BUFFERED."""
    if protein_slope is None or mrna_slope is None:
        return None
    try:
        m = float(mrna_slope)
        p = float(protein_slope)
    except (TypeError, ValueError):
        return None
    if abs(m) < 1e-6:
        return None
    return round(p / m, 4)


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
    # ── SK#1783 A3: the PROTEIN cis-dosage arm — a SECOND ASSAY MODALITY of the SAME cell-line grain. ──
    # Read the protein cis-dosage CLASS via the inline arm idiom so the #1704 oracle counts it as the
    # THIRD (card, field) arm — a DISTINCT card + DISTINCT modality, NEVER a re-read of the RNA card. The
    # raw protein metrics (slope etc.) are pulled off a LOCAL binding below, so they are NOT read as arms.
    prot_class = (c.get("cis-feature-protein-coherence") or {}).get("cis_protein_dosage_class")
    prot_coupled = prot_class in _CIS_PROTEIN_COUPLED  # preserved slope → protein CORROBORATES the RNA call
    prot_buffered = prot_class in _CIS_PROTEIN_BUFFERED  # flat protein slope → QUALIFIED, never a false agree
    prot_resolved = prot_coupled or prot_buffered  # a MEASURED protein read (coupled OR buffered); else drops

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

    # The envelope's TWO COUNTS. `corroborating_independent_arm_count` is the count of INDEPENDENT GRAINS
    # consulted (cell-line model / patient tumour) — the protein arm SHARES the cell-line grain (a same-
    # grain modality restatement), so it NEVER adds an independent replicate here (the #1783 crux).
    # `resolved_source_count` counts DISTINCT RESOLVED SOURCES, so a measured protein modality (a genuinely
    # second source) grows it by one — keeping independent arms a strict subset of resolved sources.
    corroborating_independent_arm_count = len(resolved)
    resolved_source_count = corroborating_independent_arm_count + (1 if prot_resolved else 0)

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

    # ── SK#1783 A3: the protein MODALITY arm — ADDITIVE, appended ONLY when the protein source resolves,
    # so the protein-absent path stays BYTE-STABLE to the #1781 two-arm claim. It shares the cell-line
    # grain with the RNA arm (dependence_group `cell_line_model`) — independent by MODALITY, NOT a second
    # independent grain — so it enriches the read WITHOUT inflating corroborating_independent_arm_count.
    protein_modality_corroboration = None
    if prot_resolved:
        _prot_card = c.get("cis-feature-protein-coherence") or {}
        _prot_slope_ratio = _mrna_vs_protein_slope_ratio(
            _prot_card.get("cn_prot_slope_log2abundance_per_cn"),
            _cl_card.get("cn_expr_slope_log2tpm_per_cn"),
        )
        source_support.append(
            {
                "source": "cell_line_protein",
                "grain": "cell_line_model",  # SAME first-class sample-context grain as the RNA arm
                "dependence_group": "cell_line_model",  # same group as cell-line RNA — NOT an independent replicate
                "assay_modality": "ms_protein",  # the axis of independence: MS-protein vs bulk-RNA
                "value": prot_class,
                "dosage_direction": "coupled" if prot_coupled else "buffered",
                "resolved": True,  # a MEASURED protein read (coupled OR buffered) — buffering is real biology
                "quality_eligible": True,
                # a COUPLED protein modality corroborates WITHIN the grain; a BUFFERED one is a QUALIFIED
                # quantitative view (retained_quantitative), NEVER counted as agreement (never a false agree).
                "corroboration_eligible": prot_coupled,
                "independent_replicate": False,  # same-grain modality — never a third independent grain-arm
                "provenance": {
                    "card_id": _CIS_PROTEIN_CARD,
                    "field": _CIS_PROTEIN_FIELD,
                    "grain_context": _CIS_DOSAGE_GRAIN["cell_line_model"],
                    "modality": "DepMap-Gygi mass-spec protein (CN->own-protein cis-dosage)",
                },
                "retained_quantitative": {
                    "cis_protein_dosage_class": prot_class,
                    "cn_prot_spearman_r": _prot_card.get("cn_prot_spearman_r"),
                    "cn_prot_slope_log2abundance_per_cn": _prot_card.get("cn_prot_slope_log2abundance_per_cn"),
                    "delta_log2abundance_amplified_vs_neutral": _prot_card.get(
                        "delta_log2abundance_amplified_vs_neutral"
                    ),
                    "n_paired_models_cn_protein": _prot_card.get("n_paired_models_cn_protein"),
                    "mrna_vs_protein_dosage_slope_ratio": _prot_slope_ratio,  # the dosage-buffering fingerprint
                },
            }
        )
        if prot_coupled:
            protein_modality_corroboration = {
                "status": "protein_corroborates",
                "statement": (
                    "MS-protein cis-dosage AGREES with the cell-line RNA call: copy number drives own PROTEIN "
                    "abundance (slope preserved). A WITHIN-cell-line-grain SECOND-MODALITY corroboration "
                    "(independent by ASSAY MODALITY, MS-protein vs bulk-RNA), NOT a second independent grain — "
                    "it strengthens the cell-line reading WITHOUT adding to corroborating_independent_arm_count."
                ),
                "source": "cell_line_protein",
                "dependence_group": "cell_line_model",
                "mrna_vs_protein_dosage_slope_ratio": _prot_slope_ratio,
            }
        else:  # prot_buffered
            protein_modality_corroboration = {
                "status": "protein_buffered_qualified",
                "statement": (
                    "MS-protein cis-dosage is BUFFERED: mRNA tracks copy number but protein stays flat "
                    "(post-transcriptional buffering). A QUALIFIED quantitative view — REAL BIOLOGY that tempers "
                    "ADC / degrader payload expectations, NOT a measurement failure — surfaced as "
                    "retained_quantitative and DELIBERATELY NOT counted as agreement (never a false agree)."
                ),
                "source": "cell_line_protein",
                "dependence_group": "cell_line_model",
                "mrna_vs_protein_dosage_slope_ratio": _prot_slope_ratio,
            }

    # The cell-line dependence GROUP folds in the protein modality (same grain, distinct assay) ONLY when
    # protein resolves; absent protein, the groups are byte-identical to the #1781 two-arm claim.
    _cell_line_group = (
        {
            "members": ["cell_line_model", "cell_line_protein"],
            "relationship": "shared_cell_line_grain_distinct_modality",
        }
        if prot_resolved
        else {"members": ["cell_line_model"], "relationship": "independent_sample_context"}
    )
    evidence_dependence = {
        "groups": [
            _cell_line_group,
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
        # SK#1783: the protein-modality descriptor is ADDITIVE — present ONLY when the protein arm resolves,
        # so the protein-absent path stays byte-stable to the #1781 two-arm claim.
        **(
            {"protein_modality_corroboration": protein_modality_corroboration}
            if protein_modality_corroboration is not None
            else {}
        ),
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


# ── L2b CROSS-GRAIN concordance claim (SK#1782, epic #1779 / parent #1507) ──────────────────────────
# The SECOND cis-domain concordance property: promoter-methylation → own-LOW-expression SILENCING measured
# at two DIFFERENT sample-context grains —
#   * cell-line MODEL grain — `cellline-methylation-expression-coherence`.`methylation_silencing_class`
#   * patient TUMOUR grain  — `patient-cis-coherence`.`patient_methylation_silencing_class`
#
# ★★ EXPLICIT CLASS→ARM MAPPING (the correctness crux). Unlike the cis-dosage arm (a single SHARED
# coupled/uncoupled vocabulary on both grains), the two SILENCING vocabularies DIFFER and each carries
# state(s) that are MEASURED-BUT-UNINTERPRETABLE or UNCOVERED and must route to NO rung — neither
# corroborating NOR disagreeing. So each grain enumerates EVERY vocabulary member to one of THREE arm
# outcomes; the DROP set is DELIBERATELY enumerated (not left to `arm_from_class`'s off-roster fall-through)
# so a new/renamed token fails LOUD in `test_silencing_concordance_vocab_is_fully_mapped` rather than
# silently leaving the arm frame:
#   * SILENCED     (agrees=True)  — a coupled methylation→low-expression call.
#   * NOT_SILENCED (disagrees=False) — a MEASURED not-silenced floor (tested, no silencing separation).
#   * DROP (None)  — routed to NO rung. `silencing_lineage_confounded` (a large pan-panel contrast that
#     COLLAPSES within lineage — measured, but NOT interpretable as cis silencing, per SKILL.md Boundaries:
#     it must read as evidence NEITHER for NOR against silencing; mapping it to `disagrees` would falsely
#     drive corroboration to `low`), `methylation_invariant_panel` (untestable — no hypermethylated subset),
#     patient `insufficient_methylation_data` (uncovered/underpowered cohort, indication-scoped), and
#     `data_unavailable` (a TRUTHY string — mapped EXPLICITLY, never via falsiness;
#     feedback_nonfinite_sentinel_is_a_number).
_SILENCING_SILENCED = "silenced"
_SILENCING_NOT_SILENCED = "not_silenced"
_SILENCING_DROP = "drop"  # routed to NO rung — neither corroborates nor disagrees (leaves the arm frame)

# Cell-line vocabulary (cellline-methylation-expression-coherence.methylation_silencing_class, card v1.1.0).
_CELLLINE_SILENCING_ARM = {
    "silencing_coupled_strong": _SILENCING_SILENCED,
    "silencing_coupled_moderate": _SILENCING_SILENCED,
    "methylation_uncoupled": _SILENCING_NOT_SILENCED,  # MEASURED: tested within lineage, not silenced
    "silencing_lineage_confounded": _SILENCING_DROP,  # measured, NOT interpretable as cis silencing
    "methylation_invariant_panel": _SILENCING_DROP,  # untestable — no hypermethylated subset
    "data_unavailable": _SILENCING_DROP,  # TRUTHY sentinel — mapped explicitly
}
# Patient vocabulary (patient-cis-coherence.patient_methylation_silencing_class) — a DIFFERENT, indication-
# scoped roster. `insufficient_methylation_data` (< 5 methylated OR < 5 unmethylated cases) DROPS.
_PATIENT_SILENCING_ARM = {
    "epigenetic_silencing": _SILENCING_SILENCED,  # methylated cases express >= 1 log2 unit LOWER
    "no_silencing_signal": _SILENCING_NOT_SILENCED,  # MEASURED: no silencing separation
    "insufficient_methylation_data": _SILENCING_DROP,  # uncovered/underpowered cohort
    "data_unavailable": _SILENCING_DROP,  # TRUTHY sentinel — mapped explicitly (not in the card enum, safe)
}


def _silencing_arms(mapping: dict) -> "tuple[frozenset, frozenset]":
    """Derive (agrees, disagrees) frozensets from an explicit class→arm mapping — the DROP-mapped tokens
    are in NEITHER set, so `arm_from_class` returns None (they leave the arm frame). The mapping is the
    single source of truth the vocab-coverage test pins."""
    agrees = frozenset(k for k, v in mapping.items() if v == _SILENCING_SILENCED)
    disagrees = frozenset(k for k, v in mapping.items() if v == _SILENCING_NOT_SILENCED)
    return agrees, disagrees


_CL_SILENCING_AGREES, _CL_SILENCING_DISAGREES = _silencing_arms(_CELLLINE_SILENCING_ARM)
_PT_SILENCING_AGREES, _PT_SILENCING_DISAGREES = _silencing_arms(_PATIENT_SILENCING_ARM)

_C_PATIENT = "patient-cis-coherence"
_SILENCING_GRAIN = {
    "cell_line_model": "cell-line model (DepMap panel)",
    "patient_tumour": "patient tumour cohort (TCGA)",
}
_SILENCING_CARD = {
    "cell_line_model": _C_METH,
    "patient_tumour": _C_PATIENT,
}
_SILENCING_FIELD = {
    "cell_line_model": "methylation_silencing_class",
    "patient_tumour": "patient_methylation_silencing_class",
}


def _methylation_silencing_concordance_claim(c: dict) -> "dict | None":
    """L2b CROSS-GRAIN integration claim: `methylation_silencing_concordance` — the SECOND envelope-v0
    concordance claim for the cis_coherence domain (docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md), property_id
    `methylation_silencing_coupling`.

    Integrates the two cross-GRAIN arms of the SAME epigenetic-silencing property by an EXPLICIT
    DETERMINISTIC rule (no LLM; L2b is reproducible by contract):
      * cell-line MODEL grain — `cellline-methylation-expression-coherence`.`methylation_silencing_class`;
      * patient TUMOUR grain  — `patient-cis-coherence`.`patient_methylation_silencing_class` (TCGA cohort).
    Both resolve whether promoter methylation drives own LOW expression (epigenetic silencing), emitting:
      * methylation_silencing_concordant_silenced   — both grains resolve and AGREE silencing holds;
      * methylation_silencing_concordant_unsilenced  — both resolve and AGREE a MEASURED not-silenced floor;
      * methylation_silencing_grain_discordant        — one grain is silenced, the other a measured not-
        silenced floor (a which-grain-silences payload — INFORMATIVE, never collapsed/averaged);
      * methylation_silencing_single_grain_only       — exactly ONE grain resolves, the other a gap: the
        degraded read that names the resolved grain, NOT a concordance claim.

    ★★ The two silencing vocabularies are NOT identical, so the arms are read through an EXPLICIT per-grain
    class→arm mapping (`_CELLLINE_SILENCING_ARM` / `_PATIENT_SILENCING_ARM`). Crucially the cell-line
    `silencing_lineage_confounded` (measured but NOT interpretable as cis silencing) + `methylation_invariant_
    panel` and the patient `insufficient_methylation_data` (uncovered cohort) route to NO rung — they DROP
    (None arm), they do NOT fabricate a disagreeing arm (which would falsely drive corroboration to `low`).

    GRAIN is FIRST-CLASS (model vs patient), recorded per source in `source_support[].grain`; a same-grain
    restatement is never a second arm — the #1704 arm-commensurability oracle pins the two DISTINCT (card,
    field) arms so a re-pointed arm reds.

    Corroboration is on the shared MEASURED-ARM frame: two agreeing grains → high, a disagreement → low, one
    measured grain with the other unresolved → single_arm (below CORROBORATION_ARM_FLOOR). A single-grain
    mutation only DEGRADES to `methylation_silencing_single_grain_only`; ERASING the claim (key omitted,
    byte-stable) takes defeating BOTH grain supplies. There is NO dependent/derived source (the two grains
    are genuinely independent), so nothing resurrects the claim once both arms are gone.

    VERDICT-INERT: carries NO `signal` key, reads no verdict, feeds no rule; the `cis_coherence_verdict` +
    resolver golden stay byte-stable. Returns None — key omitted — when NEITHER grain resolves."""
    # ARM READS — the INLINE `(c.get("<card>") or {}).get("<field>")` idiom the #1704 oracle pins as the two
    # commensurate arms. Raw metrics are pulled off a LOCAL card binding below (never this idiom) so they are
    # NOT mistaken for a third arm.
    cl_class = (c.get("cellline-methylation-expression-coherence") or {}).get("methylation_silencing_class")
    pt_class = (c.get("patient-cis-coherence") or {}).get("patient_methylation_silencing_class")

    # Resolve each grain's token → silenced(True) / not_silenced(False) / drop-or-unresolved(None) via the
    # shared arm reader over the EXPLICIT per-grain agrees/disagrees sets (DROP tokens are in NEITHER set).
    cl = arm_from_class(cl_class, agrees=_CL_SILENCING_AGREES, disagrees=_CL_SILENCING_DISAGREES)
    pt = arm_from_class(pt_class, agrees=_PT_SILENCING_AGREES, disagrees=_PT_SILENCING_DISAGREES)

    resolved = [(name, v) for name, v in (("cell_line_model", cl), ("patient_tumour", pt)) if v is not None]
    if not resolved:
        return None  # neither grain resolves (or both DROP) → key omitted (byte-stable)

    if len(resolved) == 1:
        concordance = "methylation_silencing_single_grain_only"
    elif cl == pt:
        concordance = (
            "methylation_silencing_concordant_silenced" if cl else "methylation_silencing_concordant_unsilenced"
        )
    else:
        concordance = "methylation_silencing_grain_discordant"

    # Corroboration over the two grains. A discordance is [True, False] → low; a concordance [True, True] or
    # [False, False] → high; one grain unresolved is [x, None] → single_arm (below the arm floor).
    if concordance == "methylation_silencing_grain_discordant":
        cl_arm, pt_arm = True, False
    else:
        cl_arm = True if cl is not None else None
        pt_arm = True if pt is not None else None
    corroboration = corroboration_from_arms([cl_arm, pt_arm])

    # The envelope's TWO COUNTS. Both grains are genuinely INDEPENDENT (no pooled / derived superset), so the
    # counts coincide — emitted separately to keep the envelope shape uniform with families that DO carry a
    # dependent source.
    corroborating_independent_arm_count = len(resolved)
    resolved_source_count = corroborating_independent_arm_count

    def _dir(v):
        return "silenced" if v is True else ("not_silenced" if v is False else None)

    _class = {"cell_line_model": cl_class, "patient_tumour": pt_class}
    _val = {"cell_line_model": cl, "patient_tumour": pt}

    # which-grain payload — the disagreement or the degraded single grain is NAMED, never collapsed.
    if concordance == "methylation_silencing_grain_discordant":
        silenced_in = "cell_line_model" if cl else "patient_tumour"
        unsilenced_in = "patient_tumour" if cl else "cell_line_model"
        concordance_support = {"silenced_in": silenced_in, "unsilenced_in": unsilenced_in}
    elif concordance == "methylation_silencing_single_grain_only":
        name, v = resolved[0]
        concordance_support = {"resolved_by": name, "resolved_call": _class[name], "resolved_direction": _dir(v)}
    else:
        concordance_support = {"agreed_direction": _dir(cl)}

    # ── uniform per-source support + retained_quantitative (raw metrics DEMOTED, not dropped) ──────────
    # Raw metrics off a LOCAL card binding (NOT the inline `c.get(...)` arm idiom) so the #1704 oracle sees
    # exactly the two class-field arms and no incommensurate third pair.
    _cl_card = c.get("cellline-methylation-expression-coherence") or {}
    _pt_card = c.get("patient-cis-coherence") or {}
    _retained = {
        "cell_line_model": {
            "subset_median_delta_log2tpm": _cl_card.get("subset_median_delta_log2tpm"),
            "subset_within_lineage_delta_log2tpm": _cl_card.get("subset_within_lineage_delta_log2tpm"),
            "lineage_collapse_ratio": _cl_card.get("lineage_collapse_ratio"),
            "subset_mannwhitney_p": _cl_card.get("subset_mannwhitney_p"),
            "methyl_expr_spearman_r": _cl_card.get("methyl_expr_spearman_r"),
            "broad_quartile_delta_log2tpm": _cl_card.get("broad_quartile_delta_log2tpm"),
            "n_hypermethylated": _cl_card.get("n_hypermethylated"),
        },
        "patient_tumour": {
            "delta_log2tpm_methylated_vs_unmethylated": _pt_card.get("delta_log2tpm_methylated_vs_unmethylated"),
            "n_methylated": _pt_card.get("n_methylated"),
            "n_unmethylated": _pt_card.get("n_unmethylated"),
            "mean_log2tpm_methylated": _pt_card.get("mean_log2tpm_methylated"),
            "mean_log2tpm_unmethylated": _pt_card.get("mean_log2tpm_unmethylated"),
            "n_cases_methylation": _pt_card.get("n_cases_methylation"),
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
            "silencing_direction": _dir(v),
            # THREE separate source notions — no single overloaded boolean smuggles two meanings.
            "resolved": v is not None,
            "quality_eligible": v is not None,
            "corroboration_eligible": True,  # both grains are independent replication arms
            "provenance": {
                "card_id": _SILENCING_CARD[source],
                "field": _SILENCING_FIELD[source],
                "grain_context": _SILENCING_GRAIN[source],
            },
            # retained_quantitative: the raw silencing metrics DEMOTED not deleted (fidelity/recoverability) —
            # the bespoke fold's numbers are preserved here rather than dropped when it is retired.
            "retained_quantitative": _retained[source],
        }

    # Both grains ALWAYS appear (an absent/dropped grain shows resolved:False), keeping the two-count / grain
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
        "methylation_silencing_concordant_silenced": "AGREE promoter methylation silences own expression",
        "methylation_silencing_concordant_unsilenced": "AGREE it is a measured NOT-silenced floor",
        "methylation_silencing_grain_discordant": "DISAGREE — silencing replicates in only one grain",
        "methylation_silencing_single_grain_only": "only one grain resolves",
    }

    # ── PRESENTATION-SUPPORT (SK#1782 L2b surface) — two-directional structured fields + a deterministic
    # boundary-sensitivity flag so a question_table answer can SURFACE the cross-grain read WITHOUT
    # prose-parsing `evidence`. NONE route a verdict, name a signal tier (no `signal` key), or feed a rule.
    boundary_sensitive = corroboration != "high"
    if concordance == "methylation_silencing_concordant_silenced":
        _pos_source, _pos = (
            "cell_line_model",
            (
                "Both the cell-line MODEL and patient TUMOUR grains AGREE promoter methylation silences the "
                "target's own expression — a cross-grain-corroborated epigenetic-silencing read (therapeutically "
                "INVERSE: LoF / reactivation hypothesis, not direct inhibition)."
            ),
        )
    elif concordance == "methylation_silencing_concordant_unsilenced":
        _pos_source, _pos = (
            "cell_line_model",
            (
                "Both grains AGREE methylation does NOT silence expression (a measured NOT-silenced floor across "
                "model and patient) — cross-grain corroborated."
            ),
        )
    elif concordance == "methylation_silencing_grain_discordant":
        _pos_source = concordance_support["silenced_in"]
        _pos = (
            f"{_SILENCING_GRAIN[_pos_source]} reports epigenetic SILENCING — methylation→low-expression is "
            "present in this grain."
        )
    else:  # methylation_silencing_single_grain_only
        _pos_source = concordance_support["resolved_by"]
        _pos = (
            f"{_SILENCING_GRAIN[_pos_source]} reports {concordance_support['resolved_direction']} silencing "
            f"({concordance_support['resolved_call']}) — the sole grain that resolves."
        )
    positive_signal = {"statement": _pos, "source": _pos_source, "provenance_ref": _pos_source}

    if concordance in ("methylation_silencing_concordant_silenced", "methylation_silencing_concordant_unsilenced"):
        qualifying_signal = None
    elif concordance == "methylation_silencing_grain_discordant":
        _neg = concordance_support["unsilenced_in"]
        qualifying_signal = {
            "statement": (
                f"{_SILENCING_GRAIN[_neg]} does NOT replicate the silencing — the grains DISAGREE. This is "
                "INFORMATIVE (culture vs tumour-microenvironment, purity, cohort composition differ), not an "
                "error, and never equated with a biological absence."
            ),
            "source": _neg,
            "provenance_ref": _neg,
        }
    else:  # single_grain_only
        _gap = "patient_tumour" if concordance_support["resolved_by"] == "cell_line_model" else "cell_line_model"
        qualifying_signal = {
            "statement": (
                f"Only {_SILENCING_GRAIN[concordance_support['resolved_by']]} resolves; "
                f"{_SILENCING_GRAIN[_gap]} is a gap (unmeasured, lineage-confounded, or an uncovered cohort) — a "
                "degraded single-grain read, NOT cross-grain corroboration."
            ),
            "source": _gap,
            "provenance_ref": _gap,
        }

    return {
        "property_id": "methylation_silencing_coupling",
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
            "cross-grain epigenetic-silencing concordance — a promoter-methylation→low-expression call that "
            "BOTH the DepMap cell-line model and the TCGA patient tumour agree on is far more credible than a "
            "single-grain call; a grain disagreement is the informative datum, never averaged. Silencing is "
            "therapeutically INVERSE (SL / reactivation), not a direct-inhibition claim."
        ),
        "evidence": (
            f"cell-line {cl_class or 'data_unavailable'} × patient {pt_class or 'data_unavailable'}: "
            + _PHRASE[concordance]
        ),
        "provenance": {
            "sources": source_support,
            "independence_note": (
                "The cell-line methylation_silencing_class (DepMap model panel) and patient "
                "patient_methylation_silencing_class (TCGA cohort) are measured on genuinely INDEPENDENT sample "
                "contexts, so their agreement is real cross-grain corroboration of the SAME epigenetic-silencing "
                "property. VOCABULARY CAVEAT: the two silencing rosters are NOT identical — the cell-line "
                "silencing_lineage_confounded / methylation_invariant_panel and the patient "
                "insufficient_methylation_data states are measured-but-uninterpretable / uncovered and route to "
                "NO rung (they DROP, never fabricating a disagreeing arm). GRAIN CAVEAT: culture vs tumour-"
                "microenvironment / purity / cohort composition differ; the two are comparable in DIRECTION "
                "(silenced vs not), not exact thresholds. Grain is first-class so a same-grain restatement is "
                "never counted as a second arm."
            ),
        },
        "_disclaimer": (
            "L2b CROSS-GRAIN integration claim (deterministic, no LLM) — verdict-INERT provenance: never a "
            "signal tier, never averaged into a claim, never feeds the cis_coherence_verdict."
        ),
    }


# ── L2b SAME-GRAIN CROSS-MODALITY concordance claim (SK#1784, epic #1779 A4 / parent #1507) ─────────
# The THIRD cis-domain concordance property: does the target's own EXPRESSION / ABUNDANCE predict its
# DepMap dependency (higher own-omics ⇒ more dependent)? measured by TWO independent ASSAY MODALITIES of
# the SAME cell-line sample-context grain —
#   * mRNA modality    — `expression-dependency-correlation`.`correlation_class`   (bulk-RNA vs Chronos)
#   * protein modality — `abundance-dependency`.`abundance_dependency_class`       (MS-protein vs Chronos)
#
# ★★ SAME-GRAIN, MODALITY-ONLY INDEPENDENCE (the #1784 crux, WEAKER than #1781's cross-grain). Both arms
# are DepMap cell-line correlations against the SAME Chronos dependency readout, so they SHARE the
# cell-line sample-context grain — culture / lineage / panel-composition confounds are NOT broken by their
# agreement. Their independence is by ASSAY MODALITY ONLY (bulk-RNA expression measurement ⊥ MS-protein
# abundance measurement). So two agreeing modalities corroborate that own-omics predicts dependency ACROSS
# assay platforms (not a single-measurement artefact), but establish NO patient-context generalisation.
# `grain` is `cell_line_model` on BOTH arms (first-class); `dependence_group` is the MODALITY, so the two
# arms are two INDEPENDENT-BY-MODALITY groups — and a same-MODALITY restatement (re-reading the mRNA card)
# is NEVER counted as a second arm (the #1704 oracle pins the two DISTINCT (card, field) modality arms; a
# re-pointed protein arm reds).
#
# ★★ EXPLICIT CLASS→ARM MAPPING (mirrors SK#1782 — the two vocabularies DIFFER). Each modality enumerates
# EVERY token to predictive(True) / not_predictive(False, a MEASURED not-predictive floor) / DROP(None).
# DROP = routed to NO rung: protein `insufficient_paired_models` (< 20 paired CN/protein models) is
# UNDERPOWERED, and `data_unavailable` (a TRUTHY sentinel) is mapped EXPLICITLY — never via falsiness. A
# dropped / absent modality never fabricates a disagreeing arm (which would falsely drive corroboration to
# `low`). The mRNA `positive_anomaly` (a MEASURED WRONG-direction read — higher expression ⇒ LESS
# dependent, e.g. paralog compensation) is a MEASURED not-predictive floor: it genuinely refutes the
# predictive coupling, so it disagrees, it does NOT drop.
_EXPRDEP_PREDICTIVE = "predictive"  # own-omics predicts dependency (agrees)
_EXPRDEP_NOT_PREDICTIVE = "not_predictive"  # MEASURED not-predictive floor (disagrees)
_EXPRDEP_DROP = "drop"  # routed to NO rung — neither corroborates nor disagrees (leaves the arm frame)

# mRNA vocabulary (expression-dependency-correlation.correlation_class). Mirrors _EXPR_DEP_SIGNAL's
# measured/gap split but resolves to the predictive/not-predictive/drop arm frame.
_RNA_EXPRDEP_ARM = {
    "strong_negative": _EXPRDEP_PREDICTIVE,
    "moderate_negative": _EXPRDEP_PREDICTIVE,
    "weak_negative": _EXPRDEP_PREDICTIVE,  # a weak but real expression→dependency link
    "no_correlation": _EXPRDEP_NOT_PREDICTIVE,  # MEASURED: tested across the panel, no link
    "positive_anomaly": _EXPRDEP_NOT_PREDICTIVE,  # MEASURED WRONG direction — refutes the coupling
    "data_unavailable": _EXPRDEP_DROP,  # TRUTHY sentinel — mapped explicitly
}
# protein vocabulary (abundance-dependency.abundance_dependency_class) — a DIFFERENT roster; the buffered/
# underpowered floor (`insufficient_paired_models`, < min_paired_models=20) DROPS.
_PROTEIN_EXPRDEP_ARM = {
    "protein_predicts_dependency": _EXPRDEP_PREDICTIVE,
    "weak_protein_dependency_link": _EXPRDEP_PREDICTIVE,  # a weak but real link (mirrors weak_negative)
    "no_protein_dependency_link": _EXPRDEP_NOT_PREDICTIVE,  # MEASURED: no link
    "insufficient_paired_models": _EXPRDEP_DROP,  # < 20 paired CN/protein models — underpowered
    "data_unavailable": _EXPRDEP_DROP,  # TRUTHY sentinel — mapped explicitly
}


def _exprdep_arms(mapping: dict) -> "tuple[frozenset, frozenset]":
    """Derive (agrees, disagrees) frozensets from an explicit class→arm mapping — the DROP-mapped tokens
    are in NEITHER set, so `arm_from_class` returns None (they leave the arm frame). The mapping is the
    single source of truth the vocab-coverage test pins."""
    agrees = frozenset(k for k, v in mapping.items() if v == _EXPRDEP_PREDICTIVE)
    disagrees = frozenset(k for k, v in mapping.items() if v == _EXPRDEP_NOT_PREDICTIVE)
    return agrees, disagrees


_RNA_EXPRDEP_AGREES, _RNA_EXPRDEP_DISAGREES = _exprdep_arms(_RNA_EXPRDEP_ARM)
_PROT_EXPRDEP_AGREES, _PROT_EXPRDEP_DISAGREES = _exprdep_arms(_PROTEIN_EXPRDEP_ARM)

_C_EXPRDEP_PROTEIN = "abundance-dependency"
_EXPRDEP_MODALITY = {
    "cell_line_rna": "cell-line bulk-RNA expression (DepMap panel, correlated vs Chronos dependency)",
    "cell_line_protein": "cell-line MS-protein abundance (DepMap-Gygi, correlated vs Chronos dependency)",
}
_EXPRDEP_ASSAY = {
    "cell_line_rna": "bulk_rna",
    "cell_line_protein": "ms_protein",
}
_EXPRDEP_CARD = {
    "cell_line_rna": _C_CORR,
    "cell_line_protein": _C_EXPRDEP_PROTEIN,
}
_EXPRDEP_FIELD = {
    "cell_line_rna": "correlation_class",
    "cell_line_protein": "abundance_dependency_class",
}


def _expression_dependency_concordance_claim(c: dict) -> "dict | None":
    """L2b SAME-GRAIN CROSS-MODALITY integration claim: `expression_dependency_concordance` — the THIRD
    envelope-v0 concordance claim for the cis_coherence domain (docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md),
    property_id `expression_abundance_dependency_coupling`.

    Integrates the two ASSAY-MODALITY arms of the SAME expression/abundance→dependency-coupling property by
    an EXPLICIT DETERMINISTIC rule (no LLM; L2b is reproducible by contract):
      * mRNA modality    — `expression-dependency-correlation`.`correlation_class` (bulk-RNA vs Chronos);
      * protein modality — `abundance-dependency`.`abundance_dependency_class`     (MS-protein vs Chronos).
    Both correlate the target's own-omics abundance against the SAME DepMap Chronos dependency readout on the
    SAME cell-line panel, emitting one of:
      * expression_dependency_concordant_coupled     — both modalities resolve and AGREE own-omics predicts
        dependency (a cross-assay-corroborated expression-biomarker-of-dependency read);
      * expression_dependency_concordant_uncoupled   — both resolve and AGREE a MEASURED not-predictive floor;
      * expression_dependency_modality_discordant     — one modality predicts, the other a measured not-
        predictive floor (a which-assay-predicts payload — INFORMATIVE: the RNA-vs-protein disagreement is
        exactly what picks the preferred dependency-biomarker assay, never collapsed / averaged);
      * expression_dependency_single_modality_only    — exactly ONE modality resolves, the other a gap: the
        degraded read that names the resolved modality, NOT a concordance claim.

    ★★ SAME-GRAIN, MODALITY-ONLY INDEPENDENCE (WEAKER than #1781's cross-grain). Both arms SHARE the
    cell-line sample-context grain (`grain` = `cell_line_model` on BOTH), so shared culture / lineage /
    panel-composition confounds are NOT broken by their agreement; independence is by ASSAY MODALITY ONLY
    (bulk-RNA vs MS-protein), recorded per source in `source_support[].dependence_group`. `corroborating_
    independent_arm_count` counts INDEPENDENT MODALITIES — 2 legitimately when both resolve — but a same-
    MODALITY restatement (re-reading the mRNA card) is never a second arm: the #1704 oracle pins the two
    DISTINCT (card, field) modality arms so a re-pointed protein arm reds.

    ★★ The two vocabularies DIFFER, so each modality token is routed through an EXPLICIT class→arm mapping
    (`_RNA_EXPRDEP_ARM` / `_PROTEIN_EXPRDEP_ARM`). The protein `insufficient_paired_models` (underpowered
    cohort) DROPS (None arm) — it does NOT fabricate a disagreeing arm (which would falsely drive
    corroboration to `low`); a BUFFERED / discordant protein modality never fabricates a false agree.

    Corroboration is on the shared MEASURED-ARM frame: two agreeing modalities → high, a disagreement →
    low, one measured modality with the other unresolved → single_arm (below CORROBORATION_ARM_FLOOR). A
    single-modality mutation only DEGRADES to `expression_dependency_single_modality_only`; ERASING the
    claim (key omitted, byte-stable) takes defeating BOTH modality supplies. There is NO dependent / derived
    source (the two modalities are genuinely independent measurements), so nothing resurrects the claim once
    both arms are gone.

    VERDICT-INERT: carries NO `signal` key, reads no verdict, feeds no rule; the `cis_coherence_verdict` +
    resolver golden stay byte-stable. Returns None — key omitted — when NEITHER modality resolves."""
    # ARM READS — the INLINE `(c.get("<card>") or {}).get("<field>")` idiom the #1704 oracle pins as the two
    # commensurate modality arms. Raw metrics are pulled off a LOCAL card binding below (never this idiom) so
    # they are NOT mistaken for a third arm.
    rna_class = (c.get("expression-dependency-correlation") or {}).get("correlation_class")
    prot_class = (c.get("abundance-dependency") or {}).get("abundance_dependency_class")

    # Resolve each modality's token → predictive(True) / not_predictive(False) / drop-or-unresolved(None) via
    # the shared arm reader over the EXPLICIT per-modality agrees/disagrees sets (DROP tokens are in NEITHER).
    rna = arm_from_class(rna_class, agrees=_RNA_EXPRDEP_AGREES, disagrees=_RNA_EXPRDEP_DISAGREES)
    prot = arm_from_class(prot_class, agrees=_PROT_EXPRDEP_AGREES, disagrees=_PROT_EXPRDEP_DISAGREES)

    resolved = [(name, v) for name, v in (("cell_line_rna", rna), ("cell_line_protein", prot)) if v is not None]
    if not resolved:
        return None  # neither modality resolves (or both DROP) → key omitted (byte-stable)

    if len(resolved) == 1:
        concordance = "expression_dependency_single_modality_only"
    elif rna == prot:
        concordance = (
            "expression_dependency_concordant_coupled" if rna else "expression_dependency_concordant_uncoupled"
        )
    else:
        concordance = "expression_dependency_modality_discordant"

    # Corroboration over the two modalities. A discordance is [True, False] → low; a concordance [True, True]
    # or [False, False] → high; one modality unresolved is [x, None] → single_arm (below the arm floor).
    if concordance == "expression_dependency_modality_discordant":
        rna_arm, prot_arm = True, False
    else:
        rna_arm = True if rna is not None else None
        prot_arm = True if prot is not None else None
    corroboration = corroboration_from_arms([rna_arm, prot_arm])

    # The envelope's TWO COUNTS. `corroborating_independent_arm_count` counts INDEPENDENT MODALITIES (bulk-RNA
    # / MS-protein) consulted — the two arms are genuinely independent assays (no pooled / derived superset),
    # so the counts coincide. They are emitted separately to keep the envelope shape uniform with families
    # that DO carry a dependent source, and — crucially here — because independence is MODALITY-only: a same-
    # modality restatement would never lift this count (it is not a second measurement of a distinct assay).
    corroborating_independent_arm_count = len(resolved)
    resolved_source_count = corroborating_independent_arm_count

    def _dir(v):
        return "predictive" if v is True else ("not_predictive" if v is False else None)

    _class = {"cell_line_rna": rna_class, "cell_line_protein": prot_class}
    _val = {"cell_line_rna": rna, "cell_line_protein": prot}

    # which-modality payload — the disagreement or the degraded single modality is NAMED, never collapsed.
    if concordance == "expression_dependency_modality_discordant":
        predictive_in = "cell_line_rna" if rna else "cell_line_protein"
        not_predictive_in = "cell_line_protein" if rna else "cell_line_rna"
        concordance_support = {"predictive_in": predictive_in, "not_predictive_in": not_predictive_in}
    elif concordance == "expression_dependency_single_modality_only":
        name, v = resolved[0]
        concordance_support = {"resolved_by": name, "resolved_call": _class[name], "resolved_direction": _dir(v)}
    else:
        concordance_support = {"agreed_direction": _dir(rna)}

    # ── uniform per-source support + retained_quantitative (raw metrics DEMOTED, not dropped) ──────────
    # Raw metrics off a LOCAL card binding (NOT the inline `c.get(...)` arm idiom) so the #1704 oracle sees
    # exactly the two class-field modality arms and no incommensurate third pair.
    _rna_card = c.get("expression-dependency-correlation") or {}
    _prot_card = c.get("abundance-dependency") or {}
    _retained = {
        "cell_line_rna": {
            "pearson_r": _rna_card.get("pearson_r"),
            "pearson_p": _rna_card.get("pearson_p"),
            "spearman_r": _rna_card.get("spearman_r"),
            "spearman_p": _rna_card.get("spearman_p"),
            "n_cell_lines_evaluated": _rna_card.get("n_cell_lines_evaluated"),
            "delta_chronos_top_vs_bottom_quartile": _rna_card.get("delta_chronos_top_vs_bottom_quartile"),
        },
        "cell_line_protein": {
            "protein_dependency_pearson_r": _prot_card.get("protein_dependency_pearson_r"),
            "protein_dependency_pearson_p": _prot_card.get("protein_dependency_pearson_p"),
            "protein_dependency_spearman_r": _prot_card.get("protein_dependency_spearman_r"),
            "n_paired_models": _prot_card.get("n_paired_models"),
            "n_dependent_models": _prot_card.get("n_dependent_models"),
        },
    }

    def _support(source):
        v = _val[source]
        return {
            "source": source,
            "grain": "cell_line_model",  # first-class: BOTH modalities share the cell-line grain
            "dependence_group": source,  # the axis of independence is the ASSAY MODALITY (rna vs protein)
            "assay_modality": _EXPRDEP_ASSAY[source],
            "value": _class[source],
            "dependency_direction": _dir(v),
            # THREE separate source notions — no single overloaded boolean smuggles two meanings.
            "resolved": v is not None,
            "quality_eligible": v is not None,
            "corroboration_eligible": True,  # both modalities are independent replication arms (by assay)
            "provenance": {
                "card_id": _EXPRDEP_CARD[source],
                "field": _EXPRDEP_FIELD[source],
                "modality": _EXPRDEP_MODALITY[source],
            },
            # retained_quantitative: the raw correlation metrics DEMOTED not deleted (fidelity/recoverability).
            "retained_quantitative": _retained[source],
        }

    # Both modalities ALWAYS appear (an absent / dropped modality shows resolved:False), keeping the two-count
    # structure legible. They SHARE the cell-line grain — independence is by MODALITY only (NOT an independent
    # sample context), so the dependence relationship names that explicitly (weaker than #1781's cross-grain).
    source_support = [_support("cell_line_rna"), _support("cell_line_protein")]
    evidence_dependence = {
        "groups": [
            {"members": ["cell_line_rna"], "relationship": "independent_assay_modality_shared_cell_line_grain"},
            {"members": ["cell_line_protein"], "relationship": "independent_assay_modality_shared_cell_line_grain"},
        ],
        "derived_sources": {},
    }

    _PHRASE = {
        "expression_dependency_concordant_coupled": "AGREE own-omics abundance predicts dependency",
        "expression_dependency_concordant_uncoupled": "AGREE it is a measured NOT-predictive floor",
        "expression_dependency_modality_discordant": "DISAGREE — the link replicates in only one assay",
        "expression_dependency_single_modality_only": "only one assay modality resolves",
    }

    # ── PRESENTATION-SUPPORT (SK#1784 L2b surface) — two-directional structured fields + a deterministic
    # boundary-sensitivity flag so a question_table answer can SURFACE the cross-modality read WITHOUT
    # prose-parsing `evidence`. NONE route a verdict, name a signal tier (no `signal` key), or feed a rule.
    boundary_sensitive = corroboration != "high"
    if concordance == "expression_dependency_concordant_coupled":
        _pos_source, _pos = (
            "cell_line_rna",
            (
                "Both the bulk-RNA and MS-protein assay modalities AGREE the target's own-omics abundance "
                "predicts its DepMap dependency (higher abundance ⇒ more dependent) — a cross-ASSAY-corroborated "
                "expression-biomarker-of-dependency read on the shared cell-line panel."
            ),
        )
    elif concordance == "expression_dependency_concordant_uncoupled":
        _pos_source, _pos = (
            "cell_line_rna",
            (
                "Both modalities AGREE own-omics abundance does NOT predict dependency (a measured NOT-predictive "
                "floor across the RNA and protein assays) — cross-assay corroborated."
            ),
        )
    elif concordance == "expression_dependency_modality_discordant":
        _pos_source = concordance_support["predictive_in"]
        _pos = (
            f"{_EXPRDEP_MODALITY[_pos_source]} reports own-omics PREDICTS dependency — the expression→dependency "
            "link is present in this assay."
        )
    else:  # expression_dependency_single_modality_only
        _pos_source = concordance_support["resolved_by"]
        _pos = (
            f"{_EXPRDEP_MODALITY[_pos_source]} reports {concordance_support['resolved_direction']} "
            f"({concordance_support['resolved_call']}) — the sole assay modality that resolves."
        )
    positive_signal = {"statement": _pos, "source": _pos_source, "provenance_ref": _pos_source}

    if concordance in (
        "expression_dependency_concordant_coupled",
        "expression_dependency_concordant_uncoupled",
    ):
        qualifying_signal = None
    elif concordance == "expression_dependency_modality_discordant":
        _neg = concordance_support["not_predictive_in"]
        qualifying_signal = {
            "statement": (
                f"{_EXPRDEP_MODALITY[_neg]} does NOT replicate the link — the assays DISAGREE. This is "
                "INFORMATIVE — it is exactly the RNA-vs-protein disagreement that picks the preferred "
                "dependency-biomarker assay (post-transcriptional buffering, MS coverage), never an error and "
                "never equated with a biological absence."
            ),
            "source": _neg,
            "provenance_ref": _neg,
        }
    else:  # single_modality_only
        _gap = "cell_line_protein" if concordance_support["resolved_by"] == "cell_line_rna" else "cell_line_rna"
        qualifying_signal = {
            "statement": (
                f"Only {_EXPRDEP_MODALITY[concordance_support['resolved_by']]} resolves; "
                f"{_EXPRDEP_MODALITY[_gap]} is a gap (unmeasured or an underpowered paired-model cohort) — a "
                "degraded single-assay read, NOT cross-modality corroboration."
            ),
            "source": _gap,
            "provenance_ref": _gap,
        }

    return {
        "property_id": "expression_abundance_dependency_coupling",
        "concordance_class": concordance,
        "corroboration": corroboration,
        # DETERMINISTIC, reproducible-by-contract: an explicit rule over the two modality tokens, never an LLM.
        "integration_method": "explicit_deterministic",
        # GRAIN first-class: the integration is SAME-GRAIN (both cell-line model), spanning ASSAY MODALITIES.
        "grain": "same_cell_line_grain_cross_modality",
        "resolved_source_count": resolved_source_count,
        "corroborating_independent_arm_count": corroborating_independent_arm_count,
        "concordance_support": concordance_support,
        "source_support": source_support,
        "positive_signal": positive_signal,
        "qualifying_signal": qualifying_signal,
        "boundary_sensitive": boundary_sensitive,
        "boundary_note": (
            "concordance class rests on a single measured assay modality (single_arm / low corroboration) — "
            "treat as near-boundary, not a flat cross-assay assertion"
            if boundary_sensitive
            else "concordance corroborated by BOTH the bulk-RNA and MS-protein assay modalities agreeing"
        ),
        "evidence_dependence": evidence_dependence,
        "informs": (
            "same-grain cross-MODALITY expression/abundance→dependency-coupling concordance — an own-omics-"
            "predicts-dependency call that BOTH the bulk-RNA and MS-protein assays agree on is more credible "
            "than a single-assay call (not a single-measurement artefact); an assay disagreement is the "
            "informative datum (which biomarker assay to prefer), never averaged. Independence is by ASSAY "
            "MODALITY only — the shared cell-line grain means this is NOT patient-context generalisation."
        ),
        "evidence": (
            f"RNA {rna_class or 'data_unavailable'} × protein {prot_class or 'data_unavailable'}: "
            + _PHRASE[concordance]
        ),
        "provenance": {
            "sources": source_support,
            "independence_note": (
                "The mRNA arm (expression-dependency-correlation.correlation_class, bulk-RNA) and the protein "
                "arm (abundance-dependency.abundance_dependency_class, DepMap-Gygi MS) are BOTH measured on the "
                "SAME cell-line sample-context grain (DepMap panel), each correlated against the SAME Chronos "
                "dependency readout. Their independence is by ASSAY MODALITY ONLY (bulk-RNA expression vs "
                "MS-protein abundance) — WEAKER than the cross-GRAIN independence of a model-vs-patient "
                "replication: a shared cell-line grain means shared culture / lineage / panel-composition "
                "confounds are NOT broken by this corroboration. So two agreeing modalities corroborate that "
                "own-omics predicts dependency ACROSS assay platforms (not one measurement artefact), but do "
                "NOT establish patient-context generalisation. GRAIN is first-class (both cell_line_model); a "
                "same-MODALITY restatement (re-reading the mRNA card) is NEVER counted as a second arm — the "
                "two arms are two DISTINCT (card, field) modalities. VOCABULARY CAVEAT: the two rosters differ; "
                "protein insufficient_paired_models (underpowered) routes to NO rung (DROP), never a false "
                "disagreement, and a discordant / buffered protein modality never fabricates a false agree."
            ),
        },
        "_disclaimer": (
            "L2b SAME-GRAIN CROSS-MODALITY integration claim (deterministic, no LLM) — verdict-INERT "
            "provenance: never a signal tier, never averaged into a claim, never feeds the cis_coherence_verdict."
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
    _by_id = cards_by_id(cards)
    _cd = _cis_dosage_concordance_claim(_by_id)
    if _cd is not None:
        vec["cis_dosage_concordance"] = _cd
    # L2b CROSS-GRAIN integration claim (SK#1782, epic #1779 / parent #1507): cell-line × patient
    # methylation-silencing concordance. Same verdict-INERT/byte-stable/key-omitted contract as
    # cis_dosage_concordance; OMITTED unless at least one grain resolves (the FULL read requires BOTH),
    # and each grain token is routed through an EXPLICIT class→arm mapping (DROP states leave the frame).
    _ms = _methylation_silencing_concordance_claim(_by_id)
    if _ms is not None:
        vec["methylation_silencing_concordance"] = _ms
    # L2b SAME-GRAIN CROSS-MODALITY integration claim (SK#1784, epic #1779 A4 / parent #1507): bulk-RNA ×
    # MS-protein own-omics→dependency-coupling concordance. Same verdict-INERT/byte-stable/key-omitted
    # contract as the other two concordance claims; OMITTED unless at least one modality resolves (the FULL
    # read requires BOTH). Independence is by ASSAY MODALITY only (both share the cell-line grain), and each
    # modality token is routed through an EXPLICIT class→arm mapping (DROP states leave the frame). Does NOT
    # touch the EXPR_DEP leg (plain single-source `_plain_corr`, its 5-key output byte-stability-pinned).
    _ed = _expression_dependency_concordance_claim(_by_id)
    if _ed is not None:
        vec["expression_dependency_concordance"] = _ed
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
