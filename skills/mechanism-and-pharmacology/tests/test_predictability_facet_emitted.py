"""Drift-guard: the DepMap dependency-predictability FEATURE-ATTRIBUTION facet must keep flowing through
mechanism-and-pharmacology's _headline. Predictability is a VERDICT-INERT data-driven complement to the
curated SIGNOR network: the genome-wide omics features that best predict the target's Chronos dependency,
filtered to mechanistically-plausible partner-gene classes and cross-referenced against SIGNOR partners.
It feeds NO resolver — this test pins BOTH that it is emitted AND that it never perturbs the verdict.
Offline: pure _headline over synthetic cards, no S3/reader.

_headline reads several cards via get_card_field (RAISES on a missing card_id) — so a valid call must
supply every card the skill declares (me.CARDS); we populate the predictability + SIGNOR ones.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

me = load_run_py(Path(__file__).resolve().parent.parent, "me_run")

# summary uses the reader's emitted field names (compute_summary): predictability_class,
# pred_dominant_feature_class, pred_top_features_rf (list of {feature, feature_class, importance}).
_PRED_SUMMARY = {
    "predictability_class": "context_or_driver_dependent",
    "pred_dominant_feature_class": "cross_gene_expression",
    "pred_top_features_rf": [
        {"feature": "expr_EDA2R", "feature_class": "cross_gene_expression", "importance": 0.42},
        {"feature": "cn_MYC",     "feature_class": "cross_gene_copy_number", "importance": 0.21},
        {"feature": "arm_chr8q",  "feature_class": "arm_level_cn",           "importance": 0.15},  # confounder -> dropped
        {"feature": "lineage_Bowel", "feature_class": "lineage",             "importance": 0.10},  # confounder -> dropped
        {"feature": "own_mut_hotspot", "feature_class": "own_mut_hotspot",   "importance": 0.05},  # self -> not a partner
    ],
}
# SIGNOR partners: EDA2R is a curated partner (convergence); MYC is NOT (data-driven-only hypothesis).
_SIGNOR_SUMMARY = {
    "upstream_regulators":  [{"partner_gene_symbol": "EDA2R"}],
    "downstream_effectors": [{"partner_symbol": "TP53BP1"}],   # defensive: alt key name still read
}


def _cards(pred_summary, signor_summary=None):
    cards = [{"card_id": cid, "summary": {}} for cid in me.CARDS]
    for c in cards:
        if c["card_id"] == "dependency-predictability":
            c["summary"] = dict(pred_summary)
        elif c["card_id"] == "signaling-network-mechanism" and signor_summary is not None:
            c["summary"] = dict(signor_summary)
    return cards


def test_predictability_card_registered():
    """facet-drop guard: the card must stay in the skill's CARDS list."""
    assert "dependency-predictability" in me.CARDS


def test_headline_emits_predictability_facet():
    h = me._headline(_cards(_PRED_SUMMARY, _SIGNOR_SUMMARY), [], None)
    assert h["pred_predictability_class"] == "context_or_driver_dependent"
    assert h["pred_dominant_feature_class"] == "cross_gene_expression"
    assert h["pred_self_driven"] is False
    genes = {pf["gene"] for pf in h["pred_mechanistic_partner_features"]}
    # cross-gene partners kept (gene symbol extracted); confounders (arm/lineage) + self (own_*) dropped
    assert genes == {"EDA2R", "MYC"}
    assert "own_mut_hotspot" not in genes and "chr8q" not in " ".join(genes)


def test_signor_cross_reference():
    """A predictive partner also in SIGNOR = curated+empirical convergence; one absent = data-driven-only."""
    h = me._headline(_cards(_PRED_SUMMARY, _SIGNOR_SUMMARY), [], None)
    assert h["pred_signor_corroborated_partners"] == ["EDA2R"]
    assert h["pred_n_signor_corroborated"] == 1
    by_gene = {pf["gene"]: pf for pf in h["pred_mechanistic_partner_features"]}
    assert by_gene["EDA2R"]["in_signor"] is True
    assert by_gene["MYC"]["in_signor"] is False


def test_self_driven_flag():
    """own_* dominant feature => pred_self_driven True (target's own omics predict its dependency)."""
    s = dict(_PRED_SUMMARY, pred_dominant_feature_class="own_mut_hotspot")
    h = me._headline(_cards(s, _SIGNOR_SUMMARY), [], None)
    assert h["pred_self_driven"] is True


def test_predictability_is_verdict_inert():
    """Display-only: mechanism_verdict identical with a populated vs empty predictability card, and the
    facet degrades (never raises) when the data is absent."""
    vp = ("well_characterized", "some-rule")
    with_pred = me._headline(_cards(_PRED_SUMMARY, _SIGNOR_SUMMARY), [], vp)
    empty_pred = me._headline(_cards({}), [], vp)
    assert with_pred["mechanism_verdict"] == empty_pred["mechanism_verdict"] == "well_characterized"
    assert empty_pred["pred_predictability_class"] is None
    assert empty_pred["pred_mechanistic_partner_features"] == []
    assert empty_pred["pred_n_signor_corroborated"] == 0
