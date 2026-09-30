"""Offline unit tests for MSK-CHORD panel-coverage helpers (scope-coherence Phase 2)."""

from __future__ import annotations

import onc_methods.msk_panel_coverage.read as m


def test_panel_id_normalization():
    # MSK-CHORD matrix uses BARE ids; the GENIE gene-panel files are MSK-prefixed.
    assert m._normalize_panel_id("IMPACT468") == "MSK-IMPACT468"
    assert m._normalize_panel_id("IMPACT341") == "MSK-IMPACT341"
    assert m._normalize_panel_id("MSK-IMPACT505") == "MSK-IMPACT505"  # already-prefixed left alone
    assert m._normalize_panel_id("") == "" and m._normalize_panel_id("  ") == ""


def test_indication_map_covers_pan_cancer_incl_gc():
    # MSK-IMPACT-50k is PAN-CANCER (unlike CHORD), so GC/STAD IS carried (Esophagogastric Cancer).
    assert m.MSK_CANCER_TYPE["COADREAD"] == "Colorectal Cancer"
    assert m.MSK_CANCER_TYPE["NSCLC"] == "Non-Small Cell Lung Cancer"
    assert m.MSK_CANCER_TYPE["BRCA"] == "Breast Cancer"
    assert m.MSK_CANCER_TYPE["GC"] == "Esophagogastric Cancer"
    assert m.MSK_CANCER_TYPE["STAD"] == "Esophagogastric Cancer"


def test_covered_gene_frequencies_recomputes_within_cohort(monkeypatch):
    """msk_covered_gene_frequencies joins the MAF numerator to the coverage denominator. Stub the three
    S3-backed inputs and confirm n_cov = cohort samples whose panel covers the gene, n_mut = distinct
    mutated samples."""
    import pandas as pd

    # 3 samples, all on IMPACT468 which covers {KRAS, TP53}; a 4th sample on a panel that lacks KRAS.
    monkeypatch.setattr(m, "msk_indication_cohort", lambda ind: ("S1", "S2", "S3", "S4"))
    monkeypatch.setattr(
        m,
        "load_msk_sample_panel_map",
        lambda: {"S1": "MSK-IMPACT468", "S2": "MSK-IMPACT468", "S3": "MSK-IMPACT468", "S4": "MSK-IMPACT341"},
    )
    import onc_methods.genie_panel_coverage.read as gp

    monkeypatch.setattr(
        gp,
        "load_panel_gene_sets",
        lambda: {"MSK-IMPACT468": frozenset({"KRAS", "TP53"}), "MSK-IMPACT341": frozenset({"TP53"})},
    )
    monkeypatch.setattr(
        m,
        "_load_msk_maf",
        lambda ind: pd.DataFrame({"sample_id": ["S1", "S2", "S4"], "gene_symbol": ["KRAS", "KRAS", "TP53"]}),
    )
    m.msk_covered_gene_frequencies.cache_clear()
    out = dict((g, (nm, nc)) for g, nm, nc in m.msk_covered_gene_frequencies("COADREAD"))
    # KRAS: mutated in S1,S2 (n_mut 2); covered by S1,S2,S3 (IMPACT468), NOT S4 → n_cov 3
    assert out["KRAS"] == (2, 3)
    # TP53: mutated in S4 (n_mut 1); covered by all 4 → n_cov 4
    assert out["TP53"] == (1, 4)
