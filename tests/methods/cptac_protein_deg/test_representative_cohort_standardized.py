"""#1664 F1: the cross-cohort representative-cohort pick must rank on the COMPARABLE standardized axis
(largest |Cohen's d|), NOT the non-comparable within-cohort raw |protein_effect_size| TMT ratio.

The product manifest states the raw TMT log2 magnitude is not cross-cohort comparable (per-plex
reference pool, per-cohort Tumor-Normal contrast); q-values / Cohen's d are the sound cross-cohort
currency. read_target_summary previously picked the single cohort with the largest |raw effect| as
representative — comparing a quantity the producer says is not comparable. These tests pin the pick
to Cohen's d for BOTH the pan-cancer (target-only) fallback and the multi-leaf umbrella path, and
confirm |raw effect| survives only as a deterministic tiebreak when the standardized axis is flat.
No S3 — the loader is monkeypatched to synthetic multi-cohort rows.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RD = importlib.import_module("methods.cptac_protein_deg.read")


def _prow(cohort, gene, effect, p, n_tumor, n_normal, cls="strong_up"):
    return {
        "cohort": cohort,
        "gene_symbol": gene,
        "protein_effect_size": effect,
        "protein_bh_q_value": p,
        "protein_p_value": p,
        "protein_effect_size_se": None,  # force the p-value z-score approximation path
        "protein_median_log2_tumor": 5.0,
        "protein_median_log2_normal": 3.0,
        "n_tumor_samples": n_tumor,
        "n_normal_samples": n_normal,
        "protein_expression_class": cls,
        "stat_test_used": "msstatstmt_limma_ebayes_moderated",
        "method_version": "1.0.0",
    }


def _patch(monkeypatch, rows):
    df = pd.DataFrame(rows)
    gene_idx, cohort_gene_idx, cohort_effect_null = {}, {}, {}
    for i, row in enumerate(rows):
        g = str(row["gene_symbol"]).upper()
        c = str(row["cohort"]).upper()
        gene_idx.setdefault(g, []).append(i)
        cohort_gene_idx[(c, g)] = i
        cohort_effect_null.setdefault(c, []).append(row["protein_effect_size"])
    monkeypatch.setattr(RD, "_load_indexed", lambda: (df, cohort_gene_idx, gene_idx, cohort_effect_null))


def test_pan_cancer_pick_uses_cohens_d_not_raw_effect_F1(monkeypatch):
    # BRCA: LARGER raw effect (3.0) but SMALL Cohen's d (huge n, marginal p -> d ~0.16, negligible).
    # LUAD: SMALLER raw effect (1.6) but LARGE Cohen's d (tiny p at small n -> d ~2.4).
    # The old raw-|effect| pick would report BRCA; the standardized pick must report LUAD.
    rows = [
        _prow("BRCA", "G", 3.0, 0.02, 400, 400),
        _prow("LUAD", "G", 1.6, 1e-9, 12, 12),
    ]
    _patch(monkeypatch, rows)
    # guard the premise: BRCA really is the raw-|effect| winner but the Cohen's-d loser
    brca, luad = rows[0], rows[1]
    assert RD._finite_effect_or_nan(brca) > RD._finite_effect_or_nan(luad)
    assert RD._finite_cohens_d_or_nan(brca) < RD._finite_cohens_d_or_nan(luad)
    s = RD.read_target_summary("G")  # no indication -> pan-cancer fallback
    assert str(s["cohort"]).upper() == "LUAD", f"expected LUAD (larger Cohen's d); got {s!r}"
    assert s["protein_effect_size"] == 1.6


def test_umbrella_pick_uses_cohens_d_among_own_leaves_F1(monkeypatch):
    # NSCLC umbrella -> LUAD + LSCC (both are NSCLC's own leaves; not a cross-indication leak). LSCC has
    # the larger raw effect but a small Cohen's d; LUAD the larger Cohen's d. The umbrella pick must
    # report LUAD on the comparable axis. (OV carries a huge raw effect but is NOT an NSCLC leaf, so it
    # can never be picked regardless of axis.)
    rows = [
        _prow("LUAD", "G", 1.6, 1e-9, 12, 12),  # large d
        _prow("LSCC", "G", 3.0, 0.02, 400, 400),  # small d, large raw effect
        _prow("OV", "G", 9.9, 1e-9, 12, 12),  # not an NSCLC leaf
    ]
    _patch(monkeypatch, rows)
    s = RD.read_target_summary("G", "NSCLC")
    assert str(s["cohort"]).upper() == "LUAD", f"expected LUAD leaf on Cohen's d; got {s!r}"
    assert "Cohen's d" in str(s.get("_data_note", ""))


def test_raw_effect_only_breaks_ties_when_standardized_axis_flat_F1(monkeypatch):
    # When Cohen's d cannot separate the cohorts (here: both unstandardizable -> d absent), the pick
    # falls back to the deterministic |raw effect| tiebreak, reproducing the prior behaviour.
    rows = [
        {"cohort": "BRCA", "gene_symbol": "H", "protein_effect_size": 3.0, "protein_expression_class": "strong_up"},
        {"cohort": "LUAD", "gene_symbol": "H", "protein_effect_size": 1.2, "protein_expression_class": "strong_up"},
    ]
    _patch(monkeypatch, rows)
    assert RD._finite_cohens_d_or_nan(rows[0]) == -1.0  # unstandardizable (no p/se/n)
    assert RD._finite_cohens_d_or_nan(rows[1]) == -1.0
    s = RD.read_target_summary("H")
    assert str(s["cohort"]).upper() == "BRCA", f"flat standardized axis -> raw-effect tiebreak; got {s!r}"
