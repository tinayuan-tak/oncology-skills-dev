"""Unit tests for tumor-selectivity's claim vector (skills/_skills_common/selectivity_claims.py), the
THIRD concrete over claim_vector_core. Pin the WIN/DIST/INT/SAFE tier maps + corroboration combination
(comparator-agreement cap, distribution-overlap, purity/CAF agreement, normal-side agreement) + the
deterministic key-signals read. Pure over a headline dict — no S3, no card reads.

The CEACAM5-shaped headline mirrors the frozen CEACAM5/COADREAD replay fixture
(tumor-selectivity/tests/fixtures/ceacam5_coadread.yaml) so the unit expectations track the replay.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import selectivity_claims as sel  # noqa: E402
from _skills_common.selectivity_claims import (  # noqa: E402
    selectivity_claim_vector,
    selectivity_key_signals,
)


def _ceacam5_headline():
    """CEACAM5/COADREAD-shaped: strong distributional + tumor-cell-intrinsic selectivity, but a weak
    (field-effect, discordant) tumor-vs-adjacent window and an origin-tissue normal liability."""
    return {
        "axis_a_selectivity_class": "field_effect_tumor_selective",
        "cells_supporting": 1.0,
        "cells_ran": 3.0,
        "discordant": True,
        "max_abs_log2fc": 2.94,
        "percentile_crossing_class": "strongly_tumor_enriched",
        "fraction_tumor_above_normal_p95": 0.758,
        "distribution_overlap_tumor_normal": 0.25,
        "sc_tumor_expression_class": "malignant_broadly_detected",
        "sc_malignant_detection_fraction": 0.756,
        "sc_caf_vs_malignant_class": "caf_low",
        "purity_confound_class": "purity_independent",
        "sc_normal_safety_essential_class": "origin_tissue_liability",
        "sc_normal_expression_class": "HIGH_LIABILITY",
        "sc_normal_n_cell_types_above_20pct": 26,
    }


def test_ceacam5_claim_vector_tiers():
    vec = selectivity_claim_vector(_ceacam5_headline(), [])
    # weak, discordant tumor-vs-adjacent window: comparator disagreement caps corroboration + flags conflict
    assert vec["WIN"]["signal"] == "weak" and vec["WIN"]["corroboration"] == "low"
    assert "DISAGREE" in (vec["WIN"]["conflict"] or "")
    # strong distributional separation. Corroboration is `single_arm`, not `high`: the old value was read
    # off `distribution_overlap_tumor_normal` alone, i.e. a banded overlap FRACTION. A small overlap says
    # the one tumour-vs-normal distribution comparison separated cleanly — that is the arm's STRENGTH, and
    # it belongs on the signal axis (where `fraction_tumor_above_normal_p95` already carries it). It is not
    # a second source agreeing, so it cannot be evidence of corroboration.
    assert vec["DIST"]["signal"] == "strong" and vec["DIST"]["corroboration"] == "single_arm"
    # tumor-cell-intrinsic (malignant-broad + caf_low + purity-independent → strong/high)
    assert vec["INT"]["signal"] == "strong" and vec["INT"]["corroboration"] == "high"
    # origin-tissue normal liability → weak window signal, high-confidence read
    assert vec["SAFE"]["signal"] == "weak" and vec["SAFE"]["corroboration"] == "high"


def test_ceacam5_key_signals():
    ks = selectivity_key_signals(_ceacam5_headline(), [])
    assert ks["headline"] == "Tumor-selective."
    # only DIST + INT are >= moderate → cited; WIN/SAFE (weak) gated out of supports
    assert len(ks["supports"]) == 2
    # the decision-critical caveat is the normal-tissue window liability (SAFE wins the tie)
    assert ks["caveat"] is not None and "therapeutic-window liability" in ks["caveat"]


def test_strong_clean_selective():
    h = _ceacam5_headline()
    h.update(
        {
            "axis_a_selectivity_class": "strong_tumor_selective",
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "sc_normal_safety_essential_class": "none",
            "sc_normal_expression_class": "NOT_EXPRESSED",
        }
    )
    vec = selectivity_claim_vector(h, [])
    # `single_arm`, not `high`. This fixture sets no `comparator_concordance` at all, so the GTEx-vs-adjacent
    # cross-family question was never asked — 3/3 `cells_supporting` is cells A and B voting on the SAME
    # tumor-vs-adjacent comparison. `high` now requires an explicitly `concordant` second family, which is
    # the only reading under which it means what it says. See
    # test_win_corroboration_reaches_high_when_a_second_comparator_family_concurs for the earned rung.
    assert vec["WIN"]["signal"] == "strong" and vec["WIN"]["corroboration"] == "single_arm"
    assert vec["SAFE"]["signal"] == "strong"
    ks = selectivity_key_signals(h, [])
    assert ks["headline"] == "Tumor-selective."
    assert ks["caveat"] is None  # all critical claims strong/clean


def test_critical_organ_liability_is_negative_window():
    h = _ceacam5_headline()
    h["sc_normal_safety_essential_class"] = "critical_organ_liability"
    vec = selectivity_claim_vector(h, [])
    assert vec["SAFE"]["signal"] == "negative"
    assert "veto" in (vec["SAFE"]["conflict"] or "")
    ks = selectivity_key_signals(h, [])
    assert ks["headline"] == "Selective signal, but a critical-organ normal-tissue liability."


def test_window_veto_floors_safe_negative_even_with_clean_sc_normal():
    """B1-02: a target the therapeutic-window veto KILLED (no window vs the worst critical/full normal —
    the housekeeping GAPDH / TROP2 broadly-normal archetype) must NOT read SAFE='strong' off a clean
    sc-normal side. The window arm floors SAFE at negative and flags the conflict."""
    h = _ceacam5_headline()
    h.update(
        {
            "axis_a_selectivity_class": "strong_tumor_selective",
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "sc_normal_safety_essential_class": "none",  # CLEAN sc-normal side
            "sc_normal_expression_class": "NOT_EXPRESSED",
            "therapeutic_window_class": "no_therapeutic_window",
        }
    )  # but the window veto KILLED it
    vec = selectivity_claim_vector(h, [])
    assert vec["SAFE"]["signal"] == "negative"
    assert "window" in (vec["SAFE"]["conflict"] or "")
    # a fired window veto is itself a measured normal-side read → corroboration is not unmeasured
    assert vec["SAFE"]["corroboration"] != "unmeasured"


def test_full_normal_window_veto_also_floors_safe():
    """The pan-normal window arm (full_normal_window_class == no_full_normal_window) floors SAFE too."""
    h = _ceacam5_headline()
    h.update(
        {
            "sc_normal_safety_essential_class": "none",
            "sc_normal_expression_class": "NOT_EXPRESSED",
            "full_normal_window_class": "no_full_normal_window",
        }
    )
    assert selectivity_claim_vector(h, [])["SAFE"]["signal"] == "negative"


def test_clean_window_leaves_safe_strong():
    """A clean therapeutic window must NOT downgrade a clean-sc-normal SAFE axis (no false negative)."""
    h = _ceacam5_headline()
    h.update(
        {
            "sc_normal_safety_essential_class": "none",
            "sc_normal_expression_class": "NOT_EXPRESSED",
            "therapeutic_window_class": "clean_window",
            "full_normal_window_class": "clean_full_normal_window",
        }
    )
    assert selectivity_claim_vector(h, [])["SAFE"]["signal"] == "strong"


def test_microenvironment_confounded_downgrades_and_flags():
    h = _ceacam5_headline()
    h["purity_confound_class"] = "microenvironment_confounded"
    vec = selectivity_claim_vector(h, [])
    # purity contradicts an apparent intrinsic single-cell signal → downgraded + conflict + low corroboration
    assert vec["INT"]["signal"] == "weak"
    assert "microenvironment" in (vec["INT"]["conflict"] or "")
    assert vec["INT"]["corroboration"] == "low"


def test_microenvironment_dominant_is_negative():
    h = _ceacam5_headline()
    h["sc_tumor_expression_class"] = "microenvironment_dominant"
    vec = selectivity_claim_vector(h, [])
    assert vec["INT"]["signal"] == "negative"
    ks = selectivity_key_signals(h, [])
    assert "microenvironment-driven" in ks["headline"]


def test_not_selective_case():
    h = {
        "axis_a_selectivity_class": "not_selective",
        "cells_supporting": 0.0,
        "cells_ran": 3.0,
        "discordant": False,
        "percentile_crossing_class": "not_enriched",
        "distribution_overlap_tumor_normal": 0.9,
        "sc_tumor_expression_class": "broadly_low",
        "purity_confound_class": "purity_independent",
        "sc_normal_safety_essential_class": "none",
        "sc_normal_expression_class": "NOT_EXPRESSED",
    }
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["signal"] == "absent" and vec["DIST"]["signal"] == "absent"
    ks = selectivity_key_signals(h, [])
    assert ks["headline"] == "Not tumor-selective."
    assert ks["supports"] == []


def test_not_selective_with_critical_organ_liability_is_not_selective():
    """REGRESSION (key_signals over-claim): a measured-NEGATIVE target (WIN+DIST absent) that also
    carries a near-universal critical-organ normal liability (SAFE negative) must NOT read
    "Selective signal, but …". The endothelial-marker archetype (PECAM1/VWF in COADREAD): not
    tumor-selective by every selectivity axis, yet expressed in critical normal organs."""
    h = {
        "axis_a_selectivity_class": "not_selective",
        "cells_supporting": 0.0,
        "cells_ran": 3.0,
        "discordant": False,
        "percentile_crossing_class": "not_enriched",
        "distribution_overlap_tumor_normal": 0.9,
        "sc_tumor_expression_class": "microenvironment_dominant",
        "purity_confound_class": "microenvironment_confounded",
        "sc_normal_safety_essential_class": "critical_organ_liability",
        "sc_normal_expression_class": "HIGH_LIABILITY",
    }
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["signal"] == "absent" and vec["DIST"]["signal"] == "absent"
    assert vec["SAFE"]["signal"] == "negative"
    ks = selectivity_key_signals(h, [])
    assert not ks["headline"].startswith("Selective signal")
    assert ks["headline"].startswith("Not tumor-selective")
    assert "normal-tissue liability" in ks["headline"]
    assert ks["supports"] == []


def test_weak_selectivity_with_liability_does_not_claim_selective():
    """REGRESSION: a discordant / weak-signal target (WIN+DIST weak, below the moderate bar) with a
    critical-organ liability (the KRAS/COADREAD archetype) must not lead with "Selective signal"."""
    h = _ceacam5_headline()
    h.update(
        {
            "axis_a_selectivity_class": "discordant_across_comparators",
            "cells_supporting": 1.0,
            "discordant": True,
            "percentile_crossing_class": "minimally_enriched",
            "fraction_tumor_above_normal_p95": 0.19,
            "distribution_overlap_tumor_normal": 0.7,
            "sc_tumor_expression_class": "malignant_subset_detected",
            "sc_normal_safety_essential_class": "critical_organ_liability",
        }
    )
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["signal"] == "weak" and vec["DIST"]["signal"] == "weak"
    assert vec["SAFE"]["signal"] == "negative"
    ks = selectivity_key_signals(h, [])
    assert not ks["headline"].startswith("Selective signal")
    assert "normal-tissue liability" in ks["headline"]


def test_selective_with_critical_organ_liability_unchanged():
    """BYTE-STABILITY guard: a genuinely selective target (DIST strong — the CEACAM5 shape) with a
    critical-organ liability KEEPS the prior "Selective signal, but …" wording. Complements
    test_critical_organ_liability_is_negative_window; pins that the fix does not regress selective cases."""
    h = _ceacam5_headline()
    h["sc_normal_safety_essential_class"] = "critical_organ_liability"
    ks = selectivity_key_signals(h, [])
    assert ks["headline"] == "Selective signal, but a critical-organ normal-tissue liability."


def test_win_corroboration_capped_by_single_comparator_family():
    """cells_supporting double-counts cells A (raw) + B (ComBat) as two votes of the same
    tumor-vs-adjacent comparison. A 3/3 support count with comparator_concordance == single_comparator
    (only the adjacent family reached significance; GTEx silent) must NOT read WIN corroboration 'high' —
    it rests on ONE independent comparator family. Verdict-inert.

    The pin is now `single_arm` rather than `moderate`, which is what the docstring's own reason asks for:
    ONE independent comparator family is one arm. `moderate` claimed partial agreement BETWEEN families
    when only a single family ever reported, and it also made this case indistinguishable from a genuinely
    conflicted two-family read that had been capped down to `moderate` from above."""
    h = _ceacam5_headline()
    h.update(
        {
            "axis_a_selectivity_class": "strong_tumor_selective",
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "comparator_concordance": "single_comparator",
        }
    )
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "single_arm"


def test_win_corroboration_reaches_high_when_a_second_comparator_family_concurs():
    """ANTI-VACUITY for the two pins above: WIN `high` must still be REACHABLE, or `single_arm` there is
    pinning a ladder whose top rung is dead code and the distinction carries no information.

    Byte-isolated to the one field under test — the headline is identical to
    test_win_corroboration_capped_by_single_comparator_family except that `comparator_concordance` reads
    `concordant` (the GTEx family independently agreed with the adjacent family) instead of
    `single_comparator`. That single token is the whole difference between one arm and two."""
    h = _ceacam5_headline()
    h.update(
        {
            "axis_a_selectivity_class": "strong_tumor_selective",
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "comparator_concordance": "concordant",
        }
    )
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "high"


def test_win_corroboration_high_when_families_concordant():
    """A 3/3 support count WITH genuine cross-comparator agreement (both families sig-up) keeps 'high'."""
    h = _ceacam5_headline()
    h.update(
        {
            "axis_a_selectivity_class": "strong_tumor_selective",
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "comparator_concordance": "concordant",
        }
    )
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "high"


def test_win_corroboration_unaffected_when_concordance_absent():
    """Byte-stability: with no comparator_concordance in the headline (older summaries) the cell-count
    tier is unchanged — the CEACAM5 fixture (discordant, 1/3) still reads 'low'."""
    assert selectivity_claim_vector(_ceacam5_headline(), [])["WIN"]["corroboration"] == "low"


def test_field_names_are_corroboration_not_reliability():
    """Post reliability→corroboration rename: the claim dicts carry `corroboration`."""
    vec = selectivity_claim_vector(_ceacam5_headline(), [])
    assert "corroboration" in vec["WIN"] and "reliability" not in vec["WIN"]


# ── PROTEIN-layer corroboration quorum for the WIN axis (CPTAC + TPHP tumor-vs-normal MS) ────────────
def _rna_up_concordant_win():
    """A clean RNA window (comparator-concordant, non-discordant) so the WIN corroboration base = high —
    isolating the protein-quorum effect."""
    h = _ceacam5_headline()
    h.update(
        {
            "axis_a_selectivity_class": "strong_tumor_selective",
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "comparator_concordance": "concordant",
        }
    )
    return h


def test_win_corroboration_capped_when_protein_contradicts():
    """RNA-up but the protein layer is significantly DOWN (rna_protein_discordant): an active
    cross-platform contradiction caps WIN corroboration at low and flags the conflict."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "rna_protein_discordant"
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["corroboration"] == "low"
    assert "CONTRADICTS" in (vec["WIN"]["conflict"] or "")


def test_win_corroboration_capped_when_two_protein_platforms_silent():
    """Both proteomic platforms (CPTAC + TPHP) fail to confirm the RNA window → a 2-platform
    non-corroboration caps WIN corroboration at low (the EPCAM/COADREAD signature)."""
    h = _rna_up_concordant_win()
    h.update(
        {
            "rna_protein_tvn_concordance": "protein_not_significant",
            "rna_protein_tvn_concordance_tphp": "protein_not_significant",
        }
    )
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["corroboration"] == "low"
    assert "does NOT corroborate" in (vec["WIN"]["conflict"] or "")


def test_win_corroboration_one_silent_protein_caps_moderate():
    """A single non-corroborating platform is a weaker signal than two → caps at moderate, not low."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "protein_not_significant"
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "moderate"


def test_win_corroboration_protein_corroborated_leaves_high():
    """A fully corroborating protein layer imposes NO cap — the clean RNA window stays high."""
    h = _rna_up_concordant_win()
    h.update(
        {
            "rna_protein_tvn_concordance": "rna_protein_concordant",
            "rna_protein_tvn_concordance_tphp": "rna_protein_concordant",
        }
    )
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "high"


def test_win_corroboration_unaffected_when_protein_unmeasured():
    """Byte-stability: no protein reads in the headline (the synthetic CEACAM5 fixture) → no cap, no
    conflict note (the enrichment is a no-op when its inputs are absent)."""
    h = _rna_up_concordant_win()  # no rna_protein_* keys
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["corroboration"] == "high"
    assert "protein" not in (vec["WIN"]["conflict"] or "")


# ── the TPHP arm's OWN two censoring fields gate what that arm is allowed to SAY ─────────────────────
# Both guards are the tumor-vs-normal-protein-abundance-tphp CARD's own declared warning predicates
# (`tphp_tvn_detection_incomplete` / `tphp_tvn_pan_cancer_extremum`), read off the card SUMMARY rather
# than a headline projection. Each is bracketed by a POSITIVE (the guard fires), a BOUNDARY (the same
# shape with only the field flipped, pinning the guard to the FIELD and not to the card's presence) and
# a control on the n-scaling consequence — because this quorum only ever PENALISES, so dropping an arm
# is the permissive direction and a censoring fix could otherwise become a back-door relaxation.
def _tphp_cards(**summary_over):
    """The TPHP tumor-vs-normal card summary the quorum now reads. Defaults mirror a real
    indication-mapped, fully-detected row; pass overrides to exercise one warning predicate at a time."""
    summary = {
        "protein_effect_size": -0.82,
        "protein_bh_q_value": 0.004,
        "cohort": "LUAD",
        "protein_detection_complete": True,
        "cohort_pick_basis": "indication_mapped",
    }
    summary.update(summary_over)
    return [{"card_id": "tumor-vs-normal-protein-abundance-tphp", "summary": summary}]


def test_censored_tphp_arm_cannot_contradict_a_complete_data_platform():
    """POSITIVE, guard 2 — the MKI67/LUAD shape. TPHP reads tumor-vs-normal protein DOWN on a row where
    `protein_detection_complete` is false, so its effect size is a median over DETECTED samples only and
    the card says to "read the DIRECTION as unreliable, not as loss". CPTAC read `concordant` on complete
    data, and two reads of one measurement cannot have opposite signs. The censored arm keeps its place
    in the denominator but loses its `contradicted` vote → mixed/moderate instead of a two-rung drop."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "rna_protein_concordant"
    h["rna_protein_tvn_concordance_tphp"] = "rna_protein_discordant"
    vec = selectivity_claim_vector(h, _tphp_cards(protein_detection_complete=False))
    assert vec["WIN"]["corroboration"] == "moderate"
    conflict = vec["WIN"]["conflict"] or ""
    assert "CENSORED" in conflict and "NOT counted as a contradiction" in conflict
    assert "CONTRADICTS" not in conflict  # the discount must not be reported as an active contradiction


def test_complete_detection_tphp_arm_still_contradicts():
    """BOUNDARY, guard 2 — the SAME shape with `protein_detection_complete` true. A fully-detected DOWN
    read is a real cross-platform contradiction and must still cap at low, which is what pins the
    discount to the FIELD rather than to the TPHP card merely being present in `cards`."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "rna_protein_concordant"
    h["rna_protein_tvn_concordance_tphp"] = "rna_protein_discordant"
    vec = selectivity_claim_vector(h, _tphp_cards(protein_detection_complete=True))
    assert vec["WIN"]["corroboration"] == "low"
    assert "CONTRADICTS" in (vec["WIN"]["conflict"] or "")


def test_censoring_discount_does_not_rescue_a_non_corroborating_arm():
    """NEGATIVE control, guard 2 — the discount must not turn into a relaxation. A censored row that
    simply failed to reach significance is still evidence of NON-corroboration; only its DIRECTION was
    unreliable. So it stays in the denominator and two silent platforms keep the n>=2 `low` cap."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "protein_not_significant"
    h["rna_protein_tvn_concordance_tphp"] = "protein_not_significant"
    vec = selectivity_claim_vector(h, _tphp_cards(protein_detection_complete=False))
    assert vec["WIN"]["corroboration"] == "low"
    assert "not significant on 2 MS platforms" in (vec["WIN"]["conflict"] or "")


def test_pan_cancer_extremum_tphp_arm_is_labelled_not_dropped():
    """POSITIVE, guard 1 — a `cohort_pick_basis` other than `indication_mapped` means the row is the
    pan-cancer cohort with the largest |log2FC|: "a most-extreme-cohort readout, NOT an indication-scoped
    answer". Such a row can neither corroborate nor contradict THIS indication's window, so it loses BOTH
    votes — but it KEEPS ITS PLACE IN THE DENOMINATOR, because "this platform was asked and did not
    corroborate THIS indication's window" is true of it. CPTAC corroborates, the TPHP arm is silent → a
    2-platform MIXED layer capping at moderate, NOT the uncapped `high` that dropping the arm would give.
    See `test_the_guards_never_shrink_the_denominator` for why dropping is the wrong shape."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "rna_protein_concordant"
    h["rna_protein_tvn_concordance_tphp"] = "rna_protein_discordant"
    cards = _tphp_cards(cohort_pick_basis="pan_cancer_max_abs_log2fc_detection_complete")
    vec = selectivity_claim_vector(h, cards)
    conflict = vec["WIN"]["conflict"] or ""
    assert vec["WIN"]["corroboration"] == "moderate"
    assert "NON-corroborating only" in conflict
    assert "pan_cancer_max_abs_log2fc_detection_complete" in conflict  # name the basis, not just the act
    assert "CONTRADICTS" not in conflict  # its DOWN direction is not attributable to this indication


def test_pan_cancer_extremum_arm_cannot_corroborate_either():
    """POSITIVE, guard 1, the OTHER direction — and the half a drop-based guard gets wrong silently. An
    off-indication row that AGREES with the RNA window must not be allowed to lift the tier: the card says
    "Do not attribute it to {indication.label}", which forbids crediting its agreement just as much as its
    disagreement. Two concordant reads would be `corroborated`/no-cap; with the TPHP row off-indication the
    layer is MIXED and caps at moderate."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "rna_protein_concordant"
    h["rna_protein_tvn_concordance_tphp"] = "rna_protein_concordant"
    assert selectivity_claim_vector(h, _tphp_cards())["WIN"]["corroboration"] == "high"  # both attributable
    off = _tphp_cards(cohort_pick_basis="pan_cancer_max_abs_log2fc_no_detection_complete_row")
    assert selectivity_claim_vector(h, off)["WIN"]["corroboration"] == "moderate"


def test_indication_mapped_tphp_arm_is_not_excluded():
    """BOUNDARY, guard 1 — the same DOWN read on an `indication_mapped` row IS this indication's answer,
    so the arm stays and no exclusion is reported. `None` is not an off-indication basis either; that
    case is covered by the data_unavailable control below."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "rna_protein_concordant"
    h["rna_protein_tvn_concordance_tphp"] = "rna_protein_discordant"
    vec = selectivity_claim_vector(h, _tphp_cards())  # defaults: indication_mapped + fully detected
    assert vec["WIN"]["corroboration"] == "low"
    # The arm STAYS and votes: an indication_mapped discordant read is counted as a real contradiction,
    # NOT relabelled off-indication. The old `"EXCLUDED" not in ...` guarded a token the producer NEVER
    # emits — the #1383 drop→relabel switch retired the drop path, leaving that clause vacuous — so
    # assert the positive tokens the arm's PRESENCE produces (a dropped/excluded arm yields no CONTRADICTS).
    conflict = vec["WIN"]["conflict"] or ""
    assert "CONTRADICTS" in conflict
    assert "pan-cancer extremum" not in conflict and "NON-corroborating only" not in conflict


def test_the_off_indication_guard_does_not_relax_the_n_scaled_cap():
    """NEGATIVE control, guard 1 — and the reason this guard LABELS instead of DROPPING. `not_corroborated`
    caps `low if n >= 2 else moderate`, an ABSOLUTE count, so removing an arm RELAXES the penalty: an
    earlier draft dropped the off-indication arm and, swept over the whole 5x5x3x3 input space, moved 30
    cells PERMISSIVE and 0 restrictive — a penalty instrument that fires LESS the less trustworthy its
    input. Same defect as a safety gate that drops an unsupported organ instead of labelling it. Keeping
    the arm in the denominator holds the cap at low either way."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "protein_not_significant"
    h["rna_protein_tvn_concordance_tphp"] = "protein_not_significant"
    strict = selectivity_claim_vector(h, _tphp_cards())["WIN"]["corroboration"]
    off_basis = _tphp_cards(cohort_pick_basis="pan_cancer_max_abs_log2fc_no_detection_complete_row")
    relaxed = selectivity_claim_vector(h, off_basis)["WIN"]["corroboration"]
    assert (strict, relaxed) == ("low", "low")


def test_the_guards_never_shrink_the_denominator():
    """THE STRUCTURAL INVARIANT, swept rather than sampled — this is what makes a future re-introduction
    of "just drop the arm" red. Neither guard may reduce `n_measured` below what the pre-guard quorum
    counted, for ANY combination of the two headline reads and the two card fields. Both guards withhold
    VOTES; only `protein_unmeasured` (an arm that was never measured) may reduce the count. 225 cells."""
    reads = [None, "protein_unmeasured", "protein_not_significant", "rna_protein_concordant", "rna_protein_discordant"]
    for cptac in reads:
        for tphp in reads:
            h = {}
            if cptac is not None:
                h["rna_protein_tvn_concordance"] = cptac
            if tphp is not None:
                h["rna_protein_tvn_concordance_tphp"] = tphp
            # what the quorum counts with NO card fields present == the pre-guard denominator
            baseline = sel._protein_window_quorum(h, {})["n_measured"]
            for complete in (None, True, False):
                for basis in (None, "indication_mapped", "pan_cancer_max_abs_log2fc_detection_complete"):
                    summary = {}
                    if complete is not None:
                        summary["protein_detection_complete"] = complete
                    if basis is not None:
                        summary["cohort_pick_basis"] = basis
                    c = {"tumor-vs-normal-protein-abundance-tphp": summary} if summary else {}
                    got = sel._protein_window_quorum(h, c)["n_measured"]
                    assert got == baseline, (cptac, tphp, complete, basis, baseline, got)


def test_tphp_summary_without_the_censoring_fields_keeps_prior_behaviour():
    """Byte-stability — both fields are null only on the card's `data_unavailable` path, and an older or
    synthetic summary omits them entirely. Either way the quorum must read exactly as it did before the
    guards existed: a MISSING flag is not `False`, and a `None` basis is not an off-indication basis."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "rna_protein_concordant"
    h["rna_protein_tvn_concordance_tphp"] = "rna_protein_discordant"
    for label, extra in (
        ("fields absent", {}),
        ("fields null", {"protein_detection_complete": None, "cohort_pick_basis": None}),
    ):
        summary = {"protein_effect_size": -0.82, "protein_bh_q_value": 0.004, "cohort": "LUAD", **extra}
        cards = [{"card_id": "tumor-vs-normal-protein-abundance-tphp", "summary": summary}]
        vec = selectivity_claim_vector(h, cards)
        assert vec["WIN"]["corroboration"] == "low", label
        conflict = vec["WIN"]["conflict"] or ""
        assert "CONTRADICTS" in conflict, label
        # A MISSING/`None` flag is not `False`: no `CENSORED` aside means the DOWN direction was not
        # discounted (this is the teeth of the byte-stability claim — a wrongly-`False`-treated missing
        # flag would surface `CENSORED`). `"EXCLUDED"` dropped: vacuous, the producer never emits it.
        assert "CENSORED" not in conflict, label


def test_win_evidence_surfaces_field_effect_from_per_cell_log2fc():
    """The adjacent-vs-distant split the collapsed class hides: cell A (adjacent) flat/down + cell C
    (distant GTEx) up → a high-normal-baseline field effect, surfaced in WIN evidence + conflict."""
    h = _ceacam5_headline()
    h["axis_a_selectivity_class"] = "discordant_across_comparators"
    cards = [{"card_id": "tumor-vs-normal-selectivity", "summary": {"log2fc_cell_a": -0.33, "log2fc_cell_c": 2.09}}]
    vec = selectivity_claim_vector(h, cards)
    assert "field effect" in (vec["WIN"]["evidence"] or "")
    assert "field effect" in (vec["WIN"]["conflict"] or "")


# ── in-situ SPATIAL region-RNA quorum for the INT axis ───────────────────────────────────────────────
def test_int_corroboration_lifted_by_agreeing_spatial():
    """A single-cell INT read of only moderate corroboration is LIFTED to high when in-situ spatial
    region-RNA independently agrees (tumour_enriched_rna) — single-cell + spatial quorum."""
    h = _ceacam5_headline()
    h.update(
        {
            "sc_caf_vs_malignant_class": "caf_low",
            "purity_confound_class": None,  # base = moderate
            "spatial_rna_class": "tumour_enriched_rna",
        }
    )
    vec = selectivity_claim_vector(h, [])
    assert vec["INT"]["corroboration"] == "high"
    assert "in-situ spatial" in (vec["INT"]["evidence"] or "")


def test_int_corroboration_capped_by_disagreeing_spatial():
    """A TME-enriched in-situ spatial read caps the INT corroboration and flags the attribution conflict."""
    h = _ceacam5_headline()
    h["spatial_rna_class"] = "tme_enriched_rna"  # base would be high (caf_low + purity_independent)
    vec = selectivity_claim_vector(h, [])
    assert vec["INT"]["corroboration"] == "low"
    assert "spatial" in (vec["INT"]["conflict"] or "")


def test_int_corroboration_unaffected_when_spatial_absent():
    """Byte-stability: no spatial read → INT corroboration is the single-cell base (high for CEACAM5)."""
    assert selectivity_claim_vector(_ceacam5_headline(), [])["INT"]["corroboration"] == "high"


# ── citable evidence atoms (values bound to {card_id, fields} + entity) ──────────────────────────────
def _selectivity_cards():
    """Minimal selectivity source-card summaries mirroring the real COADREAD package fields."""
    return [
        {
            "card_id": "tumor-vs-normal-selectivity",
            "summary": {
                "selectivity_class": "discordant_across_comparators",
                "max_abs_log2fc": 0.6398,
                "cells_supporting": 2,
                "cells_ran": 3,
                "comparator_concordance": "discordant",
            },
        },
        {
            "card_id": "tumor-vs-normal-percentile-crossing",
            "summary": {
                "selectivity_class": "minimally_enriched",
                "fraction_tumor_above_normal_p95": 0.1928,
                "distribution_overlap_tumor_normal": 0.6926,
                "n_tumor_samples": 669,
            },
        },
        {
            "card_id": "sc-normal-celltype-expression",
            "summary": {
                "sc_normal_safety_essential_class": "critical_organ_liability",
                "sc_normal_expression_class": "HIGH_LIABILITY",
                "n_cell_types_above_20pct": 499,
            },
        },
    ]


def test_selectivity_atoms_present_and_citable_with_cards():
    vec = selectivity_claim_vector(_ceacam5_headline(), _selectivity_cards())
    win = vec["WIN"]["evidence_atom"]
    assert win["cite"]["card_id"] == "tumor-vs-normal-selectivity"
    assert win["values"]["max_abs_log2fc"] == 0.6398  # effect size, citable
    assert vec["DIST"]["evidence_atom"]["values"]["distribution_overlap_tumor_normal"] == 0.6926
    # SAFE atom carries the normal-tissue window liability (the veto instrument's quantitative basis)
    safe = vec["SAFE"]["evidence_atom"]
    assert safe["cite"]["card_id"] == "sc-normal-celltype-expression"
    assert safe["values"]["n_cell_types_above_20pct"] == 499


def test_selectivity_atoms_absent_without_cards():
    vec = selectivity_claim_vector(_ceacam5_headline(), [])
    for ax in ("WIN", "DIST", "INT", "SAFE"):
        assert "evidence_atom" not in vec[ax], f"{ax} gained an atom with no source card"
