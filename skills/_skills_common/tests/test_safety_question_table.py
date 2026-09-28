"""On-target-safety question-table hero — deterministic projection over a synthetic
on-target-safety-liability headline. Verdict-inert; no I/O. Polarity is INVERTED: strong = LoF-tolerant
(safe), absent = a liability."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # skills/ for _skills_common

from _skills_common.presence_question_table import render_question_table_html
from _skills_common.safety_claims import safety_claim_vector
from _skills_common.safety_question_table import (
    _normal_liability_concordance_integrated_signal,
    safety_question_table,
)


def _safe_headline():
    # a LoF-tolerant (safe) target on every leg → all strong (incl. a MEASURED-clean normal-tissue leg)
    return {
        "safety_verdict": "lof_tolerant_low_concern",
        "constraint_class": "tolerant",
        "burden_safety_class": "no_burden_signal",
        "dosage_sensitivity_class": "dosage_sufficient",
        "mouse_ko_phenotype_class": "no_phenotype",
        "clinvar_pathogenic_class": "no_pathogenic_signal",
        "dependency_class": "non_dependent",  # not broadly essential → window exists → safe-valence strong
        "essential_tissue_flag": "absent",  # measured clean → safe-valence strong
    }


def _liability_headline():
    # a constrained / essential target → the legs read as liabilities (absent = concern)
    return {
        "safety_verdict": "lof_intolerant_high_concern",
        "constraint_class": "highly_constrained",
        "burden_safety_class": "lof_risk_phenotype",
        "dosage_sensitivity_class": "autosomal_dominant_loss",
        "mouse_ko_phenotype_class": "lethal_ko",
        "clinvar_pathogenic_class": "germline_pathogenic",
        "dependency_class": "common_essential",  # broadly essential → broad-tox liability → absent
        "essential_tissue_flag": "present",  # essential-tissue protein → liability → absent
    }


def test_rows_in_order():
    rows = safety_question_table(_safe_headline())
    assert [r["id"] for r in rows] == [
        "Constraint",
        "Burden",
        "Dosage",
        "Mouse-KO",
        "ClinVar",
        "Pan-essential",
        "Normal-tissue",
    ]


def test_safe_target_all_strong():
    rows = safety_question_table(_safe_headline())
    assert all(r["signal"]["tier"] == "strong" for r in rows)


def test_liability_target_all_absent():
    rows = safety_question_table(_liability_headline())
    # inverted polarity: a liability on every leg → absent (a concern), NOT strong
    assert all(r["signal"]["tier"] == "absent" for r in rows)


def test_indeterminate_and_missing_are_unmeasured():
    h = {"constraint_class": "indeterminate", "burden_safety_class": "insufficient"}  # rest missing
    rows = {r["id"]: r for r in safety_question_table(h)}
    assert rows["Constraint"]["signal"]["tier"] == "unmeasured"
    assert rows["Burden"]["signal"]["tier"] == "unmeasured"
    assert rows["ClinVar"]["signal"]["tier"] == "unmeasured"  # missing field → named gap
    assert rows["Pan-essential"]["signal"]["tier"] == "unmeasured"  # missing dependency_class → named gap
    assert rows["Normal-tissue"]["signal"]["tier"] == "unmeasured"  # no flag/breadth → named gap
    assert "integrated_signal" not in rows["Normal-tissue"]  # no claim → no annotation (row byte-stable)


# ── SK#1582 G3.2: the Normal-tissue leg + its surfaced L2b-3 integrated_signal ─────────────────────
def _liab_cards(gtex="critical_organ_liability", sc="critical_organ_liability", hpa="present"):
    """The three normal-tissue source cards carrying raw tokens; None OMITS a source (M3 supply-defeat)."""
    cards = []
    if gtex is not None:
        cards.append({"card_id": "normal-tissue-liability-gtex", "summary": {"liability_class": gtex}})
    if sc is not None:
        cards.append({"card_id": "sc-normal-celltype-expression", "summary": {"sc_normal_safety_essential_class": sc}})
    if hpa is not None:
        cards.append({"card_id": "normal-tissue-liability", "summary": {"essential_tissue_flag": hpa}})
    return cards


def _headline_with_claim(gtex="critical_organ_liability", sc="critical_organ_liability", hpa="present", flag=None):
    """A safety headline whose claim_vector carries a resolved L2b-3 claim (built by the REAL builder from
    the source cards) — the same seam run.py uses (it sets headline['claim_vector'] before the table)."""
    cards = _liab_cards(gtex, sc, hpa)
    h = {"safety_verdict": "lof_tolerant_low_concern"}
    if flag is not None:
        h["essential_tissue_flag"] = flag
    h["claim_vector"] = safety_claim_vector(h, cards)
    return h, cards


def test_normal_tissue_row_carries_integrated_signal_when_claim_resolves():
    # concordant_low (all three lenses read clean) → integrated_signal with a POSITIVE (reassuring) lead.
    h, _ = _headline_with_claim(gtex="restricted_normal", sc="none", hpa="absent", flag="absent")
    row = {r["id"]: r for r in safety_question_table(h)}["Normal-tissue"]
    integ = row["integrated_signal"]
    assert integ["kind"] == "normal_liability_concordance"
    assert integ["concordance_class"] == "liability_concordant_low"
    assert integ["positive_signal"] and integ["qualifying_signal"] is None
    assert integ["provenance_ref"] == "claim_vector.normal_liability_concordance"
    assert integ["headline"].startswith(integ["positive_signal"]["statement"])
    # verdict-INERT: the annotation carries no tier/polarity/fill — the meter cell is the leg's own read.
    assert "tier" not in integ and "polarity" not in integ and "fill" not in integ
    assert row["signal"]["tier"] == "strong"  # measured-clean flag drives the meter, not the claim


def test_integrated_signal_absent_when_claim_omitted():
    # defeat ALL THREE source supplies → the claim is omitted → no integrated_signal, row still emitted.
    h, _ = _headline_with_claim(gtex=None, sc=None, hpa=None)
    assert "normal_liability_concordance" not in h["claim_vector"]
    row = {r["id"]: r for r in safety_question_table(h)}["Normal-tissue"]
    assert "integrated_signal" not in row
    assert row["id"] == "Normal-tissue"  # the leg is never omitted (full-axis contract)


def test_integrated_signal_directional_qualifying_classes():
    # concordant_high / discordant / single_source_only all lead with a QUALIFYING caveat, positive null.
    for gtex, sc, hpa, klass in (
        ("critical_organ_liability", "critical_organ_liability", "present", "liability_concordant_high"),
        ("critical_organ_liability", "none", "absent", "liability_assay_discordant"),
        ("data_unavailable", "data_unavailable", "present", "liability_single_source_only"),
    ):
        h, _ = _headline_with_claim(gtex=gtex, sc=sc, hpa=hpa)
        integ = {r["id"]: r for r in safety_question_table(h)}["Normal-tissue"]["integrated_signal"]
        assert integ["concordance_class"] == klass, klass
        assert integ["positive_signal"] is None and integ["qualifying_signal"], klass
        assert integ["headline"].startswith(integ["qualifying_signal"]["statement"]), klass


def test_integrated_signal_discordant_names_split_and_is_boundary_sensitive():
    # a discordance must NAME which lens flags vs reads clean (never collapse) and flag boundary-sensitive
    # (corroboration != high) so the alarming read is never a flat assertion.
    h, _ = _headline_with_claim(gtex="critical_organ_liability", sc="none", hpa="absent")
    integ = {r["id"]: r for r in safety_question_table(h)}["Normal-tissue"]["integrated_signal"]
    ss = integ["source_support"]
    assert ss["liability_flagged_by"] == ["gtex_bulk_rna"]
    assert ss["read_clean_by"] == ["hpa_ihc_protein", "sc_normal_rna"]
    assert integ["boundary_sensitive"] is True
    assert "boundary-sensitive" in integ["headline"]


def test_integrated_signal_mutation_flips_positive_vs_qualifying():
    # DIRECTIONAL mutation through the whole seam: mutate the scRNA-normal token from clean → high with a
    # bulk liability already present, flipping the surfaced read from a discordance caveat to a corroborated
    # concern; the source_support and headline track it. (bulk drives the flagged arm either way.)
    disc = {
        r["id"]: r for r in safety_question_table(_headline_with_claim("critical_organ_liability", "none", "absent")[0])
    }
    conc = {
        r["id"]: r
        for r in safety_question_table(
            _headline_with_claim("critical_organ_liability", "critical_organ_liability", "present")[0]
        )
    }
    assert disc["Normal-tissue"]["integrated_signal"]["concordance_class"] == "liability_assay_discordant"
    assert conc["Normal-tissue"]["integrated_signal"]["concordance_class"] == "liability_concordant_high"
    assert conc["Normal-tissue"]["integrated_signal"]["corroboration"] == "high"
    assert conc["Normal-tissue"]["integrated_signal"]["boundary_sensitive"] is False


def test_integrated_signal_helper_is_pure_projection():
    # the builder is a pure projection of the claim's presentation fields — no I/O, no verdict read.
    h, _ = _headline_with_claim(gtex="restricted_normal", sc="none", hpa="absent")
    claim = h["claim_vector"]["normal_liability_concordance"]
    integ = _normal_liability_concordance_integrated_signal(claim)
    assert integ["positive_signal"] is claim["positive_signal"]
    assert integ["source_support"] is claim["source_support"]
    assert integ["boundary_note"] == claim["boundary_note"]


# ── SK#1792: per-leg confidence graded from the claim vector's corroboration, never flat `moderate` ──
def test_leg_confidence_graded_from_claim_vector_corroboration():
    """Mutation teeth: each measured leg's confidence cell carries the claim vector's OWN corroboration
    tier for that leg (with its dots), not the former flat `moderate`. Reverting `_leg_conf` to the flat
    constant RED-fails on every non-moderate rung here."""
    h = _safe_headline()
    h["claim_vector"] = {
        "CONSTRAINT": {"corroboration": "high"},  # s_het-corroborated, two arms agree
        "BURDEN": {"corroboration": "single_arm"},  # one unopposed arm
        "DOSAGE": {"corroboration": "low"},  # arms compared and disagreed
        "MOUSE_KO": {"corroboration": "moderate"},
    }
    rows = {r["id"]: r for r in safety_question_table(h)}
    assert rows["Constraint"]["confidence"] == {"tier": "high", "dots": 3, "label": "corroboration: high"}
    assert rows["Burden"]["confidence"] == {"tier": "single_arm", "dots": 1, "label": "corroboration: single_arm"}
    assert rows["Dosage"]["confidence"] == {"tier": "low", "dots": 1, "label": "corroboration: low"}
    assert rows["Mouse-KO"]["confidence"]["tier"] == "moderate"


def test_leg_confidence_conservative_fallthrough_when_claim_atom_absent():
    """A MEASURED leg whose claim atom is absent (or carries no corroboration) degrades to `unmeasured`
    confidence (0 dots) — absence never reassures. Under the reverted flat `moderate` every one of these
    measured legs would render 2 reassuring dots with no claim support at all — RED."""
    h = _safe_headline()  # every leg measured, NO claim_vector attached
    for row in safety_question_table(h):
        assert row["signal"]["tier"] == "strong"  # the legs ARE measured...
        assert row["confidence"]["tier"] == "unmeasured" and row["confidence"]["dots"] == 0  # ...support unknown


def test_unmeasured_leg_confidence_stays_unmeasured_regardless_of_claim():
    """An unmeasured leg never borrows confidence from a (stale/foreign) claim atom."""
    h = {"constraint_class": "indeterminate", "claim_vector": {"CONSTRAINT": {"corroboration": "high"}}}
    rows = {r["id"]: r for r in safety_question_table(h)}
    assert rows["Constraint"]["signal"]["tier"] == "unmeasured"
    assert rows["Constraint"]["confidence"]["tier"] == "unmeasured"


def test_normal_tissue_leg_confidence_graded_from_normal_tissue_axis():
    """The Normal-tissue row grades from the NORMAL_TISSUE claim axis like the other six."""
    h = {"essential_tissue_flag": "absent", "claim_vector": {"NORMAL_TISSUE": {"corroboration": "moderate"}}}
    row = {r["id"]: r for r in safety_question_table(h)}["Normal-tissue"]
    assert row["signal"]["tier"] == "strong"
    assert row["confidence"] == {"tier": "moderate", "dots": 2, "label": "corroboration: moderate"}


def test_renders_html_via_shared_renderer():
    html = render_question_table_html(
        safety_question_table(_safe_headline()), verdict="lof_tolerant_low_concern", title="On-target safety"
    )
    assert "<table" in html and "On-target safety at a glance" in html
