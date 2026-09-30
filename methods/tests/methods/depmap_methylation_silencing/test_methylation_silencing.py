"""depmap_methylation_silencing.compute_methylation_silencing — hermetic (synthetic methylation + TPM).

Pins the silencing classifier: high promoter methylation → LOW expression = NEGATIVE correlation →
silencing_coupled_* (MLH1/CDKN2A epigenetic-silencing archetype); methylation varies but expression
independent → methylation_uncoupled; uniformly (un)methylated panel → methylation_invariant_panel
(untestable, distinct from uncoupled); too few jointly-measured lines → data_unavailable.
"""

from __future__ import annotations

from onc_methods.depmap_methylation_silencing.cli import (
    HYPERMETHYLATION_THRESHOLD,
    MIN_HYPERMETHYLATED,
    compute_methylation_silencing,
)


def _silencing_panel(n=120, *, slope=8.0, noise=0.4, seed=0):
    """Methylation fraction spread 0..1; TPM = high - slope*methyl + noise → strong NEGATIVE coupling."""
    import random

    rng = random.Random(seed)
    meth, tpm = {}, {}
    for i in range(n):
        f = i / (n - 1)  # methylation fraction 0..1
        m = f"ACH-{i:05d}"
        meth[m] = f
        tpm[m] = 9.0 - slope * f + rng.uniform(-noise, noise)
    return meth, tpm


def test_silencing_coupled_strong():
    meth, tpm = _silencing_panel(noise=0.4)
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "silencing_coupled_strong"
    assert s["methyl_expr_spearman_r"] <= -0.4
    assert s["methyl_expr_spearman_p"] <= 0.01
    assert s["n_hypermethylated"] > 0
    assert s["delta_log2tpm_hyper_vs_unmethylated"] < 0  # hypermethylated lines UNDER-express
    assert s["hypermethylation_threshold"] == HYPERMETHYLATION_THRESHOLD


def test_subset_silencing_power_floor():
    """POWER FLOOR (calibration 2026-09-12): the subset silencing contrast requires >= MIN_HYPERMETHYLATED
    hypermethylated lines. A tiny hypermethylated minority (below the floor), against an otherwise
    unmethylated + expression-flat panel, must NOT fire a subset silencing call — it is an underpowered
    Mann-Whitney and (for amplicon oncogenes like ERBB2, 10/820) a lineage-confounded artifact. With no
    broad methylation variation the panel is methylation_invariant_panel, not silencing_coupled."""
    import random

    rng = random.Random(21)
    meth, tpm = {}, {}
    n_hyper = MIN_HYPERMETHYLATED - 5  # below the floor
    i = 0
    for _ in range(n_hyper):  # tiny hypermethylated minority, low expression
        m = f"ACH-{i:05d}"
        meth[m] = 0.9 + rng.uniform(-0.02, 0.02)
        tpm[m] = 1.0 + rng.uniform(-0.3, 0.3)
        i += 1
    for _ in range(200):  # unmethylated majority, high expression, no methylation spread
        m = f"ACH-{i:05d}"
        meth[m] = 0.02 + rng.uniform(-0.01, 0.01)
        tpm[m] = 8.0 + rng.uniform(-0.5, 0.5)
        i += 1
    s = compute_methylation_silencing(meth, tpm)
    assert s["n_hypermethylated"] == n_hyper
    assert s["methylation_silencing_class"] != "silencing_coupled_strong"
    assert s["silencing_driver"] != "subset_hypermethylation"


def test_subset_silencing_fires_at_the_floor():
    """A hypermethylated subset AT the floor (>= MIN_HYPERMETHYLATED) with deep under-expression DOES fire
    the subset silencing call (MLH1/CDKN2A archetype) — the floor keeps validated silenced TSGs."""
    import random

    rng = random.Random(22)
    meth, tpm = {}, {}
    i = 0
    for _ in range(MIN_HYPERMETHYLATED + 5):  # at/above the floor
        m = f"ACH-{i:05d}"
        meth[m] = 0.9 + rng.uniform(-0.02, 0.02)
        tpm[m] = 1.0 + rng.uniform(-0.3, 0.3)
        i += 1
    for _ in range(200):
        m = f"ACH-{i:05d}"
        meth[m] = 0.02 + rng.uniform(-0.01, 0.01)
        tpm[m] = 8.0 + rng.uniform(-0.5, 0.5)
        i += 1
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "silencing_coupled_strong"
    assert s["silencing_driver"] == "subset_hypermethylation"


def test_uncoupled_when_expression_independent_of_methylation():
    import random

    rng = random.Random(3)
    meth, tpm = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        meth[m] = i / 119  # real methylation spread
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)  # expression independent of methylation
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "methylation_uncoupled"
    assert s["methylation_p10_p90_spread"] >= 0.1


def test_methylation_invariant_panel_is_not_uncoupled():
    """Uniformly unmethylated panel (no methylation variation) → methylation_invariant_panel
    (untestable), NOT methylation_uncoupled."""
    import random

    rng = random.Random(5)
    meth, tpm = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        meth[m] = 0.02 + rng.uniform(-0.01, 0.01)  # essentially unmethylated everywhere (spread << 0.1)
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "methylation_invariant_panel"
    assert s["methylation_p10_p90_spread"] < 0.1
    assert s["methyl_expr_spearman_r"] is None


def test_data_unavailable_when_too_few_lines():
    meth, tpm = _silencing_panel(n=20)
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "data_unavailable"


def test_positive_correlation_not_mislabeled_silencing():
    """A POSITIVE methylation↔expression correlation (anomalous) must NOT read as silencing."""
    import random

    rng = random.Random(8)
    meth, tpm = {}, {}
    for i in range(120):
        f = i / 119
        m = f"ACH-{i:05d}"
        meth[m] = f
        tpm[m] = 2.0 + 6.0 * f + rng.uniform(-0.4, 0.4)  # methylation UP → expression UP (positive)
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "methylation_uncoupled"  # not silencing_coupled_*
    assert s["methyl_expr_spearman_r"] > 0


# --- per-gene MEAN product read path (perf: pushdown vs whole-gzip stream) ---------------------------
from onc_methods.depmap_methylation_silencing import read as R


def _write_product(tmp_path):
    """Synthetic product [gene_symbol, ccle_column, col_index, mean_beta] for two genes."""
    import pandas as pd

    rows = [
        # GENEA: two columns mapping to distinct models
        {"gene_symbol": "GENEA", "ccle_column": "AAA_LUNG", "col_index": 0, "mean_beta": 0.10},
        {"gene_symbol": "GENEA", "ccle_column": "BBB_SKIN", "col_index": 1, "mean_beta": 0.80},
        # GENEA: two columns whose STRIPPED name collides (CCC) → last col_index (3) must win
        {"gene_symbol": "GENEA", "ccle_column": "CCC_LUNG", "col_index": 2, "mean_beta": 0.20},
        {"gene_symbol": "GENEA", "ccle_column": "CCC_BONE", "col_index": 3, "mean_beta": 0.95},
        {"gene_symbol": "GENEB", "ccle_column": "AAA_LUNG", "col_index": 0, "mean_beta": 0.33},
    ]
    p = tmp_path / "prod.parquet"
    pd.DataFrame(rows).to_parquet(p, index=False)
    return str(p)


def test_product_reconstructs_last_column_wins(tmp_path):
    p = _write_product(tmp_path)
    s2m = {"AAA": "ACH-A", "BBB": "ACH-B", "CCC": "ACH-C"}  # stripped -> ModelID
    out = R._load_methylation_from_product("GENEA", s2m, product_path=p)
    assert out is not None
    methyl, err = out
    assert err is None
    assert methyl["ACH-A"] == 0.10 and methyl["ACH-B"] == 0.80
    assert methyl["ACH-C"] == 0.95  # col_index 3 (CCC_BONE) wins over col_index 2 (CCC_LUNG)


def test_product_unmapped_column_skipped(tmp_path):
    p = _write_product(tmp_path)
    s2m = {"AAA": "ACH-A"}  # BBB / CCC unmapped -> skipped (mirrors live n_unmapped)
    methyl, err = R._load_methylation_from_product("GENEA", s2m, product_path=p)
    assert err is None
    assert set(methyl) == {"ACH-A"} and methyl["ACH-A"] == 0.10


def test_product_absent_gene_returns_gene_not_in_ccle(tmp_path):
    p = _write_product(tmp_path)
    methyl, err = R._load_methylation_from_product("NOSUCHGENE", {"AAA": "ACH-A"}, product_path=p)
    assert methyl == {} and err == "gene_not_in_ccle_rrbs"


def test_product_unreachable_returns_none(tmp_path):
    # nonexistent local path → unreachable → None (caller falls back to the live whole-gzip read)
    assert (
        R._load_methylation_from_product("GENEA", {"AAA": "ACH-A"}, product_path=str(tmp_path / "nope.parquet")) is None
    )


def test_methylation_for_gene_falls_back_to_live_when_product_unreachable(monkeypatch):
    monkeypatch.setattr(R, "_load_methylation_from_product", lambda *a, **k: None)
    calls = {"n": 0}

    def _fake_live(target, s2m):
        calls["n"] += 1
        return {"ACH-X": 0.5}, None

    monkeypatch.setattr(R, "_load_ccle_methylation_for_gene", _fake_live)
    methyl, err = R._methylation_for_gene("GENEA", {"AAA": "ACH-A"})
    assert calls["n"] == 1 and methyl == {"ACH-X": 0.5} and err is None


# --- LINEAGE-COLLAPSE guard + broad-path effect floor (round-2 panel calibration 2026-09-12) -----------


def _lineage_confounded_silencing_panel(seed=41):
    """CDH1-analog: the hypermethylated group is simply the lineage that does not express the gene.

    Live CDH1 (26Q1): hypermethylated-vs-unmethylated median delta -4.44 log2TPM, WITHIN lineage -0.45
    (collapse ratio 0.10). MET -4.99 -> -0.85 (0.17) and EGFR -4.32 -> -0.11 (0.03) are the same shape.
    """
    import random

    rng = random.Random(seed)
    meth, tpm, lineage = {}, {}, {}
    i = 0
    for _ in range(60):  # hypermethylated AND non-expressing, one lineage
        m = f"ACH-{i:05d}"
        meth[m], tpm[m], lineage[m] = rng.uniform(0.6, 0.95), 1.0 + rng.uniform(-0.3, 0.3), "Lymphoid"
        i += 1
    for _ in range(40):  # SAME lineage, unmethylated, ALSO non-expressing → within-lineage delta ~0
        m = f"ACH-{i:05d}"
        meth[m], tpm[m], lineage[m] = rng.uniform(0.05, 0.4), 1.2 + rng.uniform(-0.3, 0.3), "Lymphoid"
        i += 1
    for _ in range(200):  # the expressing lineage, unmethylated → it creates the whole pan-panel delta
        m = f"ACH-{i:05d}"
        meth[m], tpm[m], lineage[m] = rng.uniform(0.05, 0.4), 7.0 + rng.uniform(-0.5, 0.5), "Epithelial"
        i += 1
    return meth, tpm, lineage


def test_subset_silencing_reported_as_lineage_confounded_when_the_effect_collapses():
    """REGRESSION (CDH1/MET/EGFR 2026-09-12): a large, significant subset delta that VANISHES within
    lineage is lineage separation, not promoter silencing → silencing_lineage_confounded (measured, and
    explicitly NOT interpretable as cis silencing) instead of silencing_coupled_strong."""
    meth, tpm, lineage = _lineage_confounded_silencing_panel()
    s = compute_methylation_silencing(meth, tpm, lineage_by_model=lineage)
    assert s["subset_median_delta_log2tpm"] <= -1.0  # the pan-panel delta IS large
    assert s["lineage_collapse_ratio"] < 0.35  # and it collapses within lineage
    assert s["methylation_silencing_class"] == "silencing_lineage_confounded"
    assert s["silencing_driver"] == "subset_hypermethylation"
    assert s["hypermethylated_dominant_lineage_fraction"] == 1.0  # all hypermethylated lines, one lineage


def test_collapse_guard_is_only_applied_when_lineage_labels_are_supplied():
    """No lineage labels → the classes are exactly as in v0.1.0, with the guard fields left None."""
    meth, tpm, _lineage = _lineage_confounded_silencing_panel()
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "silencing_coupled_strong"
    assert s["subset_within_lineage_delta_log2tpm"] is None
    assert s["lineage_collapse_ratio"] is None


def test_genuine_subset_silencing_survives_the_lineage_control():
    """MLH1-analog: hypermethylated lines are silenced WITHIN their own lineage (live MLH1 -4.62 pan ->
    -3.92 within, ratio 0.85; MGMT 0.84; CDKN2A 1.80; SOX10 0.88). Guards against over-correction."""
    import random

    rng = random.Random(43)
    meth, tpm, lineage = {}, {}, {}
    i = 0
    for lin in ("Bowel", "Lung", "Breast"):
        for _ in range(10):  # silenced subset inside each lineage
            m = f"ACH-{i:05d}"
            meth[m], tpm[m], lineage[m] = rng.uniform(0.6, 0.95), 1.5 + rng.uniform(-0.3, 0.3), lin
            i += 1
        for _ in range(40):
            m = f"ACH-{i:05d}"
            meth[m], tpm[m], lineage[m] = rng.uniform(0.05, 0.4), 7.0 + rng.uniform(-0.5, 0.5), lin
            i += 1
    s = compute_methylation_silencing(meth, tpm, lineage_by_model=lineage)
    assert s["methylation_silencing_class"] == "silencing_coupled_strong"
    assert s["lineage_collapse_ratio"] >= 0.35
    assert s["subset_n_lineages_compared"] == 3


def test_broad_path_requires_an_effect_size_not_just_significance():
    """REGRESSION (AR/PRAD + PDGFRA/GBM 2026-09-12): the pan-panel correlation path had NO effect-size
    floor, so a significant r on a vanishing expression difference read silencing_coupled_moderate (AR
    live: r=-0.38, p<1e-25, median hypermethylated-vs-unmethylated delta -0.075 log2TPM) and drove a
    coherent_epigenetic_silencing verdict. A monotone-but-tiny methylation effect must stay uncoupled."""
    import random

    rng = random.Random(47)
    meth, tpm = {}, {}
    for i in range(400):
        f = 0.05 + 0.4 * (i / 399)  # broad methylation variation, NO >0.5 hypermethylated subset
        m = f"ACH-{i:05d}"
        meth[m] = f
        tpm[m] = 6.0 - 0.5 * f + rng.uniform(-0.02, 0.02)  # monotone, significant, but ~0.2 log2 total
    s = compute_methylation_silencing(meth, tpm)
    assert s["methyl_expr_spearman_r"] <= -0.4 and s["methyl_expr_spearman_p"] <= 0.01
    assert s["n_hypermethylated"] == 0  # no subset → the broad path is the only candidate
    assert s["broad_quartile_delta_log2tpm"] > -0.5  # vacuous effect size
    assert s["methylation_silencing_class"] == "methylation_uncoupled"
    assert s["silencing_driver"] is None


def test_powered_subset_test_that_fails_the_floor_vetoes_the_broad_path():
    """The direct test wins: with a POWERED hypermethylated subset whose delta fails the moderate floor,
    a diluted panel-wide correlation must not resurrect the call (AR live: 164 hypermethylated lines,
    subset delta -0.08, yet r=-0.38 promoted it). The broad path is a fallback for genes with no subset."""
    import random

    rng = random.Random(53)
    meth, tpm = {}, {}
    i = 0
    for _ in range(60):  # powered hypermethylated subset, but expression barely differs
        m = f"ACH-{i:05d}"
        meth[m], tpm[m] = rng.uniform(0.55, 0.95), 5.9 + rng.uniform(-0.05, 0.05)
        i += 1
    for _ in range(300):  # unmethylated comparator, monotone tail that carries the correlation
        m = f"ACH-{i:05d}"
        f = 0.05 + 0.4 * (i / 300)
        meth[m], tpm[m] = f, 6.6 - 1.6 * f + rng.uniform(-0.05, 0.05)
        i += 1
    s = compute_methylation_silencing(meth, tpm)
    assert s["n_hypermethylated"] >= MIN_HYPERMETHYLATED  # the subset IS powered
    assert s["subset_median_delta_log2tpm"] > -0.5  # and it FAILS the moderate silencing floor
    assert s["methyl_expr_spearman_r"] <= -0.25 and s["methyl_expr_spearman_p"] <= 0.01  # r would qualify
    assert s["methylation_silencing_class"] == "methylation_uncoupled"
