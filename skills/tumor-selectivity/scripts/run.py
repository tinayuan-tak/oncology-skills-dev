#!/usr/bin/env python3
"""tumor-selectivity — tumor-vs-normal selectivity for a single (target, indication).

A thin orchestration shell: it declares the cards it consumes, the verdict logic, and the
headline projection, then hands off to the shared ``run_wired_skill`` dispatcher (the same
live-read path the compose-dashboard engine uses, so the two never drift). The verdict itself
is delegated to the shared declarative resolver plus a shared normal-breadth veto clamp.

See CHANGELOG.md for the version history.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import card_summary
from _skills_common.dispatcher import run_wired_skill
from _skills_common.resolver import resolve_or_raise
from _skills_common.synthesis_selectivity import synthesize_selectivity
from _skills_common.selectivity_claims import selectivity_claim_vector, selectivity_key_signals
from _skills_common.selectivity_hero import emit_selectivity_hero
# The normal-breadth VETO clamp is single-sourced in _skills_common.selectivity_veto so that BOTH
# this standalone skill AND the compose-dashboard engine (compose_core.resolve_gate_spine) apply the
# identical clamp. The names are re-exported here for this skill's own tests + local readability.
from _skills_common.selectivity_veto import (  # noqa: F401
    _AXIS_A_SELECTIVE, _NORMAL_BREADTH_VETO_RULES, _WINDOW_VETO_RULE,
    _FULL_NORMAL_VETO_RULE, _SC_NORMAL_VETO_RULE, apply_normal_breadth_veto,
)


SKILL_NAME = "tumor-selectivity"
# This constant is stamped into provenance.yaml and MUST equal SKILL.md metadata.version
# (tests/test_version_parity.py guards the equality). Bump both together; log the change in CHANGELOG.md.
SKILL_VERSION = "1.11.1"

# ── Cards consumed, grouped by the role each plays in the answer ──────────────────────────────────
# The selectivity RESOLVER is keyed only to the aggregate tumor-vs-normal-selectivity card (the
# verdict spine is byte-stable); every other card either feeds the normal-breadth veto clamp or is a
# verdict-inert display facet, as noted per card below.
CARDS = [
    # ── VERDICT-DRIVING ──
    "tumor-vs-normal-selectivity",           # The aggregate axis-A verdict: tumor-vs-tissue-of-origin
                                             # over-expression from the four-cell DESeq2 sensitivity
                                             # design (TCGA-adjacent raw + ComBat, GTEx-population).
    "tumor-vs-normal-percentile-crossing",   # Per-sample corroboration — fraction of tumors above the
                                             # matched-normal p95 (corroborates the aggregate log2FC at
                                             # per-sample resolution). Its crossing rules emit SM/degrader
                                             # signals; the resolver stays keyed to the aggregate card, so
                                             # this is additive signal/rationale (verdict byte-stable).
    "modality-therapeutic-window",           # NORMAL-BREADTH VETO instrument. therapeutic_window_class ==
                                             # no_therapeutic_window (tumor below the worst critical normal)
                                             # fires a veto that DOWNGRADES a selective axis-A call to
                                             # selective_but_broadly_normal: over-expression vs the tissue
                                             # of origin is necessary but NOT sufficient — the real window
                                             # is tumor-to-WORST-normal (the housekeeping GAPDH/TROP2 fix).
    "sc-normal-celltype-expression",         # NORMAL-BREADTH VETO instrument (cell-type-resolved normal
                                             # safety). sc_normal_safety_essential_class ==
                                             # critical_organ_liability — target highly detected in an
                                             # essential cell type of a NON-origin critical organ
                                             # (cardiomyocyte/hepatocyte/renal-tubule/HSC/neuron) that bulk
                                             # tissue medians dilute — fires a veto → downgrade.
                                             # origin_tissue_liability does NOT veto.
    # ── ADDITIVE FACETS (verdict-inert; feed no resolver rung / no clamp) ──
    "expression-purity-confound",            # Is the selectivity signal tumor-cell-intrinsic or driven by
                                             # stromal/immune (microenvironment) content? The four-cell
                                             # DESeq2 design has no purity covariate, so a CAF/stromal gene
                                             # high in bulk tumor can read tumor_selective. Display-only
                                             # caveat; microenvironment_confounded flags a possible false
                                             # ADC/degrader window from stromal expression.
    "surface-abundance-density",             # Absolute surface DENSITY (copies/cell): the Tier-1 calibrated
                                             # anchor (grade A/B curated corpus) + its floor standing
                                             # (soluble-TCE 1000/cell, ADC 10000/cell). Below-floor is a
                                             # MODALITY caveat, NOT a target killer (CD19 ~110/cell is a
                                             # validated CAR-T antigen). Un-anchored targets → unmeasured
                                             # (abstain; absence != low density).
    "tumor-protein-abundance-cptac",         # RNA→PROTEIN CORROBORATION (verdict-inert): does the
                                             # tumor-vs-normal signal hold at the PROTEIN layer? Emits
                                             # protein_effect_size (median_log2_tumor - median_log2_normal)
                                             # + protein_bh_q_value from CPTAC per-cohort TMT-MS
                                             # (cptac-protein-tumor-vs-normal-per-cohort-v1). Closes the
                                             # aggregate card's caveat #5 (RNA selectivity != protein
                                             # selectivity — the RNA-up/protein-flat false-positive). Feeds
                                             # no resolver rung / no clamp; data_unavailable off the ~10
                                             # CPTAC cohorts (honest abstain).
    # ── SINGLE-CELL + IN-SITU SPATIAL (tumor side; verdict-inert) ──
    # The bulk four-cell DESeq2 axis-A signal cannot tell whether a "tumor_selective" call is
    # MALIGNANT-cell-intrinsic or driven by CAF/stromal/immune microenvironment content (the purity
    # confound expression-purity-confound only PROXIES via bulk deconvolution). These cards MEASURE the
    # tumor compartment directly, at single-cell and in-situ resolution.
    "tumor-scrna-celltype-expression",       # Tumor single-cell per-compartment expression. Its
                                             # malignant_detection_fraction + caf_vs_malignant_class resolve
                                             # whether the selective bulk signal is malignant-cell-intrinsic
                                             # (real, druggable) or microenvironment-driven (a false ADC/TCE
                                             # window). This is the signal the roadmap stromal-confound veto
                                             # will key on (SKILL.md § Roadmap). Measured for COADREAD/NSCLC/
                                             # LUSC/PAAD/HNSC/KIRC/OV/STAD (8 cubes), else sc_expression_class ==
                                             # data_unavailable (abstain).
    "spatial-region-rna-expression",         # In-situ spatial (GeoMx WTA) tumour-vs-microenvironment RNA
                                             # enrichment — a deconvolution-free, orthogonal confirmation of
                                             # tumour-compartment selectivity (spatial_rna_class).
    "spatial-tumor-normal-colocalization",   # In-situ spatial colocalization — is target-high tumour
                                             # immune-excluded / adjacent to NORMAL EPITHELIUM
                                             # (normal_epithelium_adjacency_fraction = bystander/off-tumour
                                             # risk bulk cannot see)? A spatial selectivity/safety dimension.
    "spatial-surface-protein-abundance",     # In-situ spatial PROTEIN (GeoMx DSP) tumour-vs-microenvironment
                                             # enrichment — protein-layer selectivity for biologics. GeoMx
                                             # protein panels are sparse, so spatial_protein_class ==
                                             # data_unavailable for most indications (honest abstain).
]

QUESTION = ("How selectively is {target} expressed in {indication} tumor "
            "tissue, and how robust is that call across independent tumor-vs-"
            "normal comparators (TCGA-adjacent raw + ComBat, GTEx-population "
            "raw)?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Tumor-vs-normal selectivity verdict.

    Delegates to the shared declarative resolver (resolvers/selectivity.resolver.yaml in
    target-contracts, evaluated by the one interpreter both engines call), then applies the shared
    normal-breadth veto clamp. A missing resolver spec raises — the resolver is the single source of
    truth, with no silent fallback to a stale copy. Guarded by tests/test_verdict.py (resolver mapping
    + all three veto arms) and _skills_common/tests/test_compose_core.py (the engine applies the same
    clamp)."""
    verdict, driving = resolve_or_raise(fired, "selectivity")
    # NORMAL-BREADTH VETO: the resolver verdict (axis-A tumor-vs-origin over-expression) is NECESSARY
    # but NOT SUFFICIENT — a gene with no therapeutic window vs the worst critical normal (housekeeping
    # GAPDH/ACTB, or the TROP2/TACSTD2 broadly-normal surface archetype) is not a target regardless of
    # fold-change. This one-directional clamp downgrades a selective axis-A call to
    # selective_but_broadly_normal when any normal-breadth veto rule fired.
    return apply_normal_breadth_veto(verdict, driving, fired)


def _rna_protein_tvn_concordance(rna_direction, protein_effect_size, protein_q):
    """DERIVED, verdict-INERT: does the CPTAC tumor-vs-normal PROTEIN signal agree with the RNA call?

    Surfaces the RNA-up / protein-flat false-positive the aggregate RNA card explicitly flags as its
    own caveat (#5). Returns one of:
      rna_protein_concordant     — protein significant (BH q<0.05) in the SAME direction as RNA
      rna_protein_discordant     — protein significant but the OPPOSITE direction (RNA-up/protein-down)
      protein_not_significant    — protein measured but BH q>=0.05 (no protein-layer confirmation)
      protein_unmeasured         — no CPTAC tumor-vs-normal protein value for this cohort (abstain)
    Never feeds a rule/clamp; a projection over the two card summaries the headline already carries."""
    if protein_effect_size is None or protein_effect_size != protein_effect_size:   # None or NaN
        return "protein_unmeasured"
    if protein_q is None or protein_q != protein_q or protein_q >= 0.05:
        return "protein_not_significant"
    rna_up = rna_direction == "up"
    protein_up = protein_effect_size > 0
    return "rna_protein_concordant" if protein_up == rna_up else "rna_protein_discordant"


def _headline(cards, fired, verdict_pair):
    # Fetch each card summary once (card_summary scans the card list, so look up by id, not position —
    # robust to card order — and reuse the result rather than re-scanning per field).
    def _summary(cid):
        return card_summary(cards, cid)
    tvn = _summary("tumor-vs-normal-selectivity")             # aggregate axis-A verdict
    pcx = _summary("tumor-vs-normal-percentile-crossing")     # per-sample corroboration
    purity = _summary("expression-purity-confound")
    density = _summary("surface-abundance-density")
    protein_tvn = _summary("tumor-protein-abundance-cptac")   # RNA→protein corroboration (verdict-inert)
    sc_normal = _summary("sc-normal-celltype-expression")     # veto instrument (normal side)
    sc_tumor = _summary("tumor-scrna-celltype-expression")    # tumor side, single-cell
    spatial_rna = _summary("spatial-region-rna-expression")
    spatial_coloc = _summary("spatial-tumor-normal-colocalization")
    spatial_protein = _summary("spatial-surface-protein-abundance")

    # RESOLVED verdict from _verdict (includes any normal-breadth veto downgrade). The headline
    # selectivity_class is the resolved value — a veto-downgraded target reads
    # selective_but_broadly_normal — while the raw pre-veto axis-A class is preserved separately for
    # transparency/audit (and so the synthesis narrator cannot over-claim off the pre-veto class).
    resolved_verdict, resolved_driving = (verdict_pair or (tvn.get("selectivity_class"), None))
    hl = {
        "selectivity_class":  resolved_verdict,               # RESOLVED (post-veto) — the audit spine
        "driving_rule_id":    resolved_driving,               # the rule that set it (e.g. the veto rule)
        "axis_a_selectivity_class": tvn.get("selectivity_class"),  # raw tumor-vs-origin class (pre-veto)
        "cells_supporting":   tvn.get("cells_supporting"),
        "cells_ran":          tvn.get("cells_ran"),
        "dominant_direction": tvn.get("dominant_direction"),
        "discordant":         tvn.get("discordant"),
        "sig_all_cells":      tvn.get("sig_all_cells"),
        "max_abs_log2fc":     tvn.get("max_abs_log2fc"),
        "data_schema":        tvn.get("_schema"),
        # Relative-selectivity context: where this gene's fold-change ranks among ALL genes in the
        # indication. Display facet, verdict-inert (also read by the synthesis prompt).
        "selectivity_allgene_percentile":       tvn.get("selectivity_allgene_percentile"),
        "selectivity_allgene_percentile_class": tvn.get("selectivity_allgene_percentile_class"),
        # Per-sample percentile-crossing (namespaced to avoid the selectivity_class collision):
        "percentile_crossing_class":       pcx.get("selectivity_class"),
        "fraction_tumor_above_normal_p95": pcx.get("fraction_tumor_above_normal_p95"),
        "distribution_overlap_tumor_normal": pcx.get("distribution_overlap_tumor_normal"),
        # Purity-confound facet (verdict-inert): is the selectivity signal tumor-cell-intrinsic or
        # driven by stromal/immune microenvironment content the bulk DESeq2 design can't separate?
        "purity_confound_class":       purity.get("purity_confound_class"),
        "expression_purity_pearson_r": purity.get("expression_purity_pearson_r"),
        # Absolute-density facet (verdict-inert): Tier-1 calibrated copies/cell + floor standing +
        # modality-viability flags. below_tce_floor is a MODALITY caveat, not a downgrade (CD19
        # counterexample). density_floor_verdict == 'unmeasured' for un-anchored targets.
        "absolute_surface_density_class":   density.get("absolute_density_class"),
        "absolute_copies_per_cell":         density.get("absolute_copies_per_cell"),
        "absolute_density_grade":           density.get("absolute_density_grade"),
        "density_floor_verdict":            density.get("density_floor_verdict"),
        "is_tce_viable":                    density.get("is_tce_viable"),
        "is_adc_high_payload_viable":       density.get("is_adc_high_payload_viable"),
        # RNA→PROTEIN corroboration facet (verdict-inert): does the tumor-vs-normal signal hold at the
        # protein layer? protein_effect_size = median_log2_tumor - median_log2_normal (CPTAC per-cohort
        # TMT-MS). rna_protein_tvn_concordance is a DERIVED, spine-inert read (does the protein direction
        # agree with the RNA dominant_direction at BH q<0.05?) — surfaces the RNA-up/protein-flat
        # false-positive the aggregate RNA card cannot see (its own caveat #5).
        "protein_tumor_vs_normal_effect_size": protein_tvn.get("protein_effect_size"),
        "protein_tumor_vs_normal_q_value":     protein_tvn.get("protein_bh_q_value"),
        "rna_protein_tvn_concordance":         _rna_protein_tvn_concordance(
            tvn.get("dominant_direction"),
            protein_tvn.get("protein_effect_size"),
            protein_tvn.get("protein_bh_q_value")),
        # Single-cell (NORMAL side) facet — the sc-normal veto's own inputs, surfaced for transparency.
        # This card is verdict-DRIVING via the veto (sc_normal_safety_essential_class ==
        # critical_organ_liability), but a reader of decision['headline'] alone could not otherwise see
        # WHICH normal cell type / organ drove (or nearly drove) a veto. Display; the spine is byte-stable.
        "sc_normal_expression_class":       sc_normal.get("sc_normal_expression_class"),
        "sc_normal_safety_essential_class": sc_normal.get("sc_normal_safety_essential_class"),
        "sc_normal_max_detection_cell_type": sc_normal.get("max_detection_cell_type"),
        "sc_normal_max_detection_fraction": sc_normal.get("max_detection_fraction"),
        "sc_normal_n_cell_types_above_20pct": sc_normal.get("n_cell_types_above_20pct"),
        # Single-cell (TUMOR side) facet (verdict-inert): resolves the purity confound at single-cell
        # resolution — is the selective bulk signal malignant-cell-intrinsic or stroma/CAF-driven?
        # malignant_detection_fraction high + caf_vs_malignant_class == caf_low → real,
        # tumor-cell-intrinsic (the CEACAM5/COADREAD read: 0.76 malignant vs 0.03 stromal).
        "sc_tumor_expression_class":        sc_tumor.get("sc_expression_class"),
        "sc_malignant_detection_fraction":  sc_tumor.get("malignant_detection_fraction"),
        "sc_top_microenvironment_compartment":       sc_tumor.get("top_microenvironment_compartment"),
        "sc_top_microenvironment_detection_fraction": sc_tumor.get("top_microenvironment_detection_fraction"),
        "sc_caf_vs_malignant_class":        sc_tumor.get("caf_vs_malignant_class"),
        "sc_tce_homogeneity_class":         sc_tumor.get("tce_homogeneity_class"),
        # In-situ spatial facets (verdict-inert): deconvolution-free tumour-compartment confirmation
        # (region RNA) + bystander-adjacency-to-normal-epithelium risk (colocalization) + protein-layer
        # spatial enrichment. data_unavailable where the spatial atlas doesn't cover the indication.
        "spatial_rna_class":                spatial_rna.get("spatial_rna_class"),
        "spatial_tumour_vs_tme_delta":      spatial_rna.get("tumour_vs_tme_delta"),
        "spatial_coloc_class":              spatial_coloc.get("spatial_coloc_class"),
        "spatial_normal_epithelium_adjacency_fraction": spatial_coloc.get("normal_epithelium_adjacency_fraction"),
        "spatial_protein_class":            spatial_protein.get("spatial_protein_class"),
    }
    # Additive, verdict-INERT: the claim vector (WIN/DIST/INT/SAFE signal×corroboration) + a brief
    # cited key-signals read — the WITHIN-lens evidence integration this subskill owns, built on the
    # SHARED claim_vector_core contract (tumor-selectivity is the third concrete after presence +
    # dependency). Both are projections over the headline just built; they NEVER touch the
    # selectivity_class spine or the normal-breadth veto (byte-stable, frozen by the CEACAM5/TACSTD2
    # replay guard). See _skills_common/selectivity_claims.py + claim_vector_core.py.
    hl["claim_vector"] = selectivity_claim_vector(hl, cards)
    hl["key_signals"] = selectivity_key_signals(hl, cards)
    return hl


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # Opt-in --synthesize narrates through the SELECTIVITY lens (its own tool schema + prompt).
        # Two-slot / verdict-inert.
        synthesize_fn=synthesize_selectivity,
        # Opt-in --figures skill-level HERO: the selectivity evidence-strip (verdict banner + the
        # independent comparator axes incl. the normal-tissue WINDOW veto) over decision['headline'].
        # Additive / display-only; reads no S3; decision.json byte-identical whether or not it runs.
        skill_figures_fn=emit_selectivity_hero,
    ))
