"""#1942: the mechanism-and-pharmacology predictability facet must SURFACE every top feature LABELED
rather than dropping the non-partner classes (arm/lineage/molsig/msi/metab). It reads the
producer-stamped `feature_label` when present and falls back to the raw `feature` for older pins.
Verdict-INERT: this adds a display field; the SIGNOR partner cross-reference is unchanged.

Offline: pure _headline over synthetic cards, no S3/reader.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

me = load_run_py(Path(__file__).resolve().parent.parent, "me_run")

# New-pin summary: producer already stamped `feature_label`. Mix partner + non-partner classes.
_PRED_LABELED = {
    "predictability_class": "context_or_driver_dependent",
    "pred_dominant_feature_class": "cross_gene_expression",
    "pred_top_features_rf": [
        {
            "feature": "expr_EDA2R",
            "feature_class": "cross_gene_expression",
            "feature_label": "EDA2R expression",
            "importance": 0.42,
        },
        {
            "feature": "arm_chr8q",
            "feature_class": "arm_level_cn",
            "feature_label": "chr8q arm-level copy-number",
            "importance": 0.15,
        },
        {
            "feature": "lineage_Bowel",
            "feature_class": "lineage",
            "feature_label": "lineage membership",
            "importance": 0.10,
        },
        {
            "feature": "molsig_SBS81",
            "feature_class": "mol_signature",
            "feature_label": "SBS81 mutational signature",
            "importance": 0.08,
        },
    ],
}

# Old-pin summary: NO feature_label stamped -> facet must fall back to the raw token, still not drop.
_PRED_OLD_PIN = {
    "predictability_class": "context_or_driver_dependent",
    "pred_dominant_feature_class": "arm_level_cn",
    "pred_top_features_rf": [
        {"feature": "arm_chr8q", "feature_class": "arm_level_cn", "importance": 0.30},
        {"feature": "expr_EDA2R", "feature_class": "cross_gene_expression", "importance": 0.20},
    ],
}


def _cards(pred_summary):
    cards = [{"card_id": cid, "summary": {}} for cid in me.CARDS]
    for c in cards:
        if c["card_id"] == "dependency-predictability":
            c["summary"] = dict(pred_summary)
    return cards


def test_all_top_features_surfaced_labeled_not_dropped():
    h = me._headline(_cards(_PRED_LABELED), [], None)
    labels = h["pred_top_feature_labels"]
    # every top feature is present (including arm/lineage/molsig that the partner list drops)
    feats = {row["feature"] for row in labels}
    assert feats == {"expr_EDA2R", "arm_chr8q", "lineage_Bowel", "molsig_SBS81"}
    by_feat = {row["feature"]: row for row in labels}
    assert by_feat["arm_chr8q"]["feature_label"] == "chr8q arm-level copy-number"
    assert by_feat["lineage_Bowel"]["feature_label"] == "lineage membership"
    assert by_feat["molsig_SBS81"]["feature_label"] == "SBS81 mutational signature"
    # partner list still keeps only partner-gene classes (arm/lineage/molsig excluded there)
    partner_classes = {pf["feature_class"] for pf in h["pred_mechanistic_partner_features"]}
    assert partner_classes == {"cross_gene_expression"}


def test_old_pin_falls_back_to_raw_token():
    h = me._headline(_cards(_PRED_OLD_PIN), [], None)
    by_feat = {row["feature"]: row for row in h["pred_top_feature_labels"]}
    # no feature_label on the struct -> label falls back to the raw feature token, never blank/crash
    assert by_feat["arm_chr8q"]["feature_label"] == "arm_chr8q"
    assert by_feat["expr_EDA2R"]["feature_label"] == "expr_EDA2R"


def test_empty_predictability_card_degrades():
    h = me._headline(_cards({}), [], None)
    assert h["pred_top_feature_labels"] == []
