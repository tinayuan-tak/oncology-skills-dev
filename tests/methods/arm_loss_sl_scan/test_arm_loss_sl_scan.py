"""Offline tests for arm_loss_sl_scan — pure core (sl_arm_scan) + gene_arm_map. No S3."""

import pandas as pd
import pytest

from methods.arm_loss_sl_scan.scan import (
    BYSTANDER_MAP_COLUMNS,
    SCAN_COLUMNS,
    bystander_map,
    sl_arm_scan,
)
from methods.pancan_arm_cnv.read import gene_arm_map

# --- fixtures --------------------------------------------------------------


def _sl_pairs():
    # T1 has two experimental partners: P1 on 3p, P2 on 5q; P3 on an UNMAPPED arm.
    return pd.DataFrame(
        [
            {"target": "T1", "partner": "P1", "evidence_tier": "experimental", "has_experimental": True},
            {"target": "T1", "partner": "P2", "evidence_tier": "experimental", "has_experimental": True},
            {"target": "T1", "partner": "P3", "evidence_tier": "computational", "has_experimental": False},
        ]
    )


def _gene_to_arm():
    return {"P1": "3p", "P2": "5q"}  # P3 deliberately absent -> must be dropped


def _arm_ind_freq():
    # 3p strongly lost in KIRC (0.85), not in LUAD (0.10); 5q flat in KIRC (0.05).
    return pd.DataFrame(
        [
            {
                "chromosome_arm": "3p",
                "indication": "KIRC",
                "n_samples": 100,
                "loss_frequency": 0.85,
                "gain_frequency": 0.0,
            },
            {
                "chromosome_arm": "3p",
                "indication": "LUAD",
                "n_samples": 100,
                "loss_frequency": 0.10,
                "gain_frequency": 0.0,
            },
            {
                "chromosome_arm": "5q",
                "indication": "KIRC",
                "n_samples": 100,
                "loss_frequency": 0.05,
                "gain_frequency": 0.0,
            },
        ]
    )


def _baseline():
    return {"3p": 0.30, "5q": 0.10}


# --- gene_arm_map ----------------------------------------------------------


def test_gene_arm_map_parses_and_uppercases():
    meta = pd.DataFrame(
        {
            "Gene Symbol": ["gene1", "GENE2", "GENE3"],
            "Cytoband": ["3p21.1", "5q11.2", None],  # None -> dropped
        }
    )
    m = gene_arm_map(meta)
    assert m["GENE1"] == "3p"  # upper-cased key
    assert m["GENE2"] == "5q"
    assert "GENE3" not in m  # unparseable cytoband dropped


def test_gene_arm_map_requires_columns():
    with pytest.raises(KeyError):
        gene_arm_map(pd.DataFrame({"Gene Symbol": ["X"]}))


# --- sl_arm_scan -----------------------------------------------------------


def test_scan_nominates_enriched_arm_only():
    hits = sl_arm_scan(
        _sl_pairs(),
        _arm_ind_freq(),
        _baseline(),
        _gene_to_arm(),
        twohit_loss_freq={("P1", "KIRC"): 0.80},
        min_loss_freq=0.5,
        fdr_alpha=0.05,
    )
    assert list(hits.columns) == SCAN_COLUMNS
    # Only 3p-in-KIRC clears BOTH the FDR and the 0.5 floor.
    assert len(hits) == 1
    row = hits.iloc[0]
    assert (row["target"], row["sl_partner"], row["partner_arm"], row["indication"]) == ("T1", "P1", "3p", "KIRC")
    assert row["q_value"] <= 0.05
    assert row["arm_loss_freq"] == 0.85
    assert row["coloss_concordance"] == "confirmed"  # twohit 0.80 >= floor
    assert row["rank"] == 1


def test_min_loss_freq_floor_drops_significant_but_low():
    # Make LUAD 3p significant vs a tiny baseline, but keep it below the floor.
    freq = pd.DataFrame(
        [
            {
                "chromosome_arm": "3p",
                "indication": "LUAD",
                "n_samples": 500,
                "loss_frequency": 0.15,
                "gain_frequency": 0.0,
            },
        ]
    )
    hits = sl_arm_scan(_sl_pairs(), freq, {"3p": 0.02}, _gene_to_arm(), min_loss_freq=0.5, fdr_alpha=0.05)
    assert hits.empty  # 0.15 significant vs 0.02 baseline but < 0.5 floor


def test_unmapped_partner_dropped_no_error():
    # Only P3 (unmapped) as a pair -> no candidates, clean empty frame.
    pairs = pd.DataFrame([{"target": "T1", "partner": "P3", "evidence_tier": "c", "has_experimental": False}])
    hits = sl_arm_scan(pairs, _arm_ind_freq(), _baseline(), _gene_to_arm(), min_loss_freq=0.5, fdr_alpha=0.05)
    assert hits.empty
    assert list(hits.columns) == SCAN_COLUMNS


def test_concordance_labels():
    # arm_only (twohit below floor) and no_twohit_data (missing) branches.
    hits = sl_arm_scan(
        _sl_pairs(),
        _arm_ind_freq(),
        _baseline(),
        _gene_to_arm(),
        twohit_loss_freq={("P1", "KIRC"): 0.05},  # below the 0.5 floor
        min_loss_freq=0.5,
        fdr_alpha=0.05,
    )
    assert hits.iloc[0]["coloss_concordance"] == "arm_only"

    hits2 = sl_arm_scan(
        _sl_pairs(),
        _arm_ind_freq(),
        _baseline(),
        _gene_to_arm(),
        twohit_loss_freq={},  # nothing for P1/KIRC
        min_loss_freq=0.5,
        fdr_alpha=0.05,
    )
    assert hits2.iloc[0]["coloss_concordance"] == "no_twohit_data"


def test_discovery_components_emitted():
    hits = sl_arm_scan(
        _sl_pairs(),
        _arm_ind_freq(),
        _baseline(),
        _gene_to_arm(),
        twohit_loss_freq={("P1", "KIRC"): 0.80},
        arm_bystander={("3p", "KIRC"): 100.0},
        min_loss_freq=0.5,
        fdr_alpha=0.05,
    )
    row = hits.iloc[0]
    assert row["selectivity"] == round(0.85 / 0.30, 3)  # freq / pancan baseline
    assert row["focality_ratio"] == round(0.80 / 0.85, 3)  # partner gene-loss / arm-loss
    assert row["bystander_density"] == 100.0
    # discovery_value = 0.85 * selectivity * min(focality,5) / (1+log10(100))
    assert 0.70 < row["discovery_value"] < 0.80


def test_discovery_value_ranks_focal_narrow_over_diffuse_broad():
    # Two hits, SAME arm_loss_freq (0.60) and SAME selectivity (3.0). P1 on 3p is focal+narrow;
    # P2 on 5q is a diffuse passenger on a broad arm. discovery_value must rank P1 first.
    freq = pd.DataFrame(
        [
            {
                "chromosome_arm": "3p",
                "indication": "KIRC",
                "n_samples": 100,
                "loss_frequency": 0.60,
                "gain_frequency": 0.0,
            },
            {
                "chromosome_arm": "5q",
                "indication": "KIRC",
                "n_samples": 100,
                "loss_frequency": 0.60,
                "gain_frequency": 0.0,
            },
        ]
    )
    hits = sl_arm_scan(
        _sl_pairs(),
        freq,
        {"3p": 0.20, "5q": 0.20},
        _gene_to_arm(),
        twohit_loss_freq={("P1", "KIRC"): 0.60, ("P2", "KIRC"): 0.30},
        arm_bystander={("3p", "KIRC"): 50.0, ("5q", "KIRC"): 500.0},
        min_loss_freq=0.5,
        fdr_alpha=0.05,
    )
    assert len(hits) == 2
    top = hits.sort_values("rank").iloc[0]
    assert top["sl_partner"] == "P1" and top["partner_arm"] == "3p"  # focal + narrow wins
    assert top["discovery_value"] > hits[hits.sl_partner == "P2"].iloc[0]["discovery_value"]


def test_robust_arm_yields_no_hit():
    # Arm loss AT baseline -> not enriched -> no hit even above the floor.
    freq = pd.DataFrame(
        [
            {
                "chromosome_arm": "3p",
                "indication": "KIRC",
                "n_samples": 100,
                "loss_frequency": 0.60,
                "gain_frequency": 0.0,
            },
        ]
    )
    hits = sl_arm_scan(_sl_pairs(), freq, {"3p": 0.60}, _gene_to_arm(), min_loss_freq=0.5, fdr_alpha=0.05)
    assert hits.empty


# --- bystander_map (Paradigm-B re-grain) -----------------------------------


def _two_context_pairs():
    return pd.DataFrame(
        [
            {"target": "TA", "partner": "P1", "evidence_tier": "experimental", "has_experimental": True},
            {
                "target": "TB",
                "partner": "P1",
                "evidence_tier": "experimental",
                "has_experimental": True,
            },  # shares P1/3p
            {"target": "TC", "partner": "P2", "evidence_tier": "experimental", "has_experimental": True},  # 5q
        ]
    )


def test_bystander_map_regrains_and_dedups():
    freq = pd.DataFrame(
        [
            {
                "chromosome_arm": "3p",
                "indication": "KIRC",
                "n_samples": 100,
                "loss_frequency": 0.80,
                "gain_frequency": 0.0,
            },
            {
                "chromosome_arm": "5q",
                "indication": "KIRC",
                "n_samples": 100,
                "loss_frequency": 0.60,
                "gain_frequency": 0.0,
            },
        ]
    )
    hits = sl_arm_scan(
        _two_context_pairs(),
        freq,
        {"3p": 0.20, "5q": 0.20},
        _gene_to_arm(),
        arm_bystander={("3p", "KIRC"): 800.0, ("5q", "KIRC"): 100.0},
        min_loss_freq=0.5,
        fdr_alpha=0.05,
    )
    bmap = bystander_map(hits)
    assert list(bmap.columns) == BYSTANDER_MAP_COLUMNS
    # 3 nominations (TA/P1, TB/P1 on 3p; TC/P2 on 5q) collapse to 2 (arm, indication) contexts.
    assert len(bmap) == 2
    ctx3p = bmap[bmap.chromosome_arm == "3p"].iloc[0]
    assert ctx3p["n_targets_nominated"] == 2  # TA + TB share the 3p/KIRC context
    assert ctx3p["n_sl_partners"] == 1  # both via P1
    assert ctx3p["sl_partners"] == ["P1"]
    assert sorted(ctx3p["top_targets"]) == ["TA", "TB"]
    # PARADIGM-B (bystander-POSITIVE): 3p (freq .80, sel 4.0, bystander 800) outranks 5q despite
    # 5q being narrower — the rich bystander surface is rewarded, not penalized.
    assert bmap.sort_values("rank").iloc[0]["chromosome_arm"] == "3p"
    assert ctx3p["pb_discovery_value"] == round(0.80 * 4.0 * 800.0, 4)


def test_bystander_map_empty_hits():
    assert bystander_map(pd.DataFrame(columns=SCAN_COLUMNS)).empty
