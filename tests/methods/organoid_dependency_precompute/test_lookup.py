"""Read-side organoid CRISPR dependency accessor (fixture-only, no S3).

Loads the lookup module and monkeypatches its S3-reading inner function (_organoid_row) so the
classification + summary-assembly + audit-string logic is tested deterministically offline. The
pushdown read itself is exercised by the live smoke in the PR description, not here.
"""

import importlib.util
from pathlib import Path

import pytest

LOOKUP = Path(__file__).resolve().parents[3] / "methods" / "organoid_dependency_precompute" / "lookup.py"


def _load():
    spec = importlib.util.spec_from_file_location("organoid_lookup", LOOKUP)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# _organoid_row tuple order (see lookup._organoid_row):
# (entrez, n_screened, n_dep, n_strong, frac_dep, frac_strong, mean_eff, median_eff, min_eff,
#  pct, n_total, n_genes)
def _row(frac_dep, *, n_screened=114, frac_strong=0.3, median_eff=-0.8, pct=95.0, n_total=114):
    return (
        "1234",
        n_screened,
        int(frac_dep * n_screened),
        int(frac_strong * n_screened),
        frac_dep,
        frac_strong,
        median_eff - 0.05,
        median_eff,
        -2.5,
        pct,
        n_total,
        18159,
    )


# ---- classification bands (pure) -----------------------------------------


@pytest.mark.parametrize(
    "frac,expected",
    [
        (0.99, "pan_organoid_essential"),
        (0.90, "pan_organoid_essential"),
        (0.75, "broad_organoid_dependency"),
        (0.50, "broad_organoid_dependency"),
        (0.30, "selective_organoid_dependency"),
        (0.20, "selective_organoid_dependency"),
        (0.10, "rare_organoid_dependency"),
        (0.05, "rare_organoid_dependency"),
        (0.01, "not_organoid_dependent"),
        (0.0, "not_organoid_dependent"),
        (None, "data_unavailable"),
    ],
)
def test_classify_dependency_bands(frac, expected):
    assert _load().classify_dependency(frac) == expected


# ---- build_summary assembly + audit --------------------------------------


def test_build_summary_broad_dependency_classifies_and_audits(monkeypatch):
    lk = _load()
    monkeypatch.setattr(lk, "_organoid_row", lambda sym: _row(0.746, median_eff=-0.87, pct=94.4))
    out = lk.build_summary("KRAS", "PAAD")
    assert out["organoid_dependency_class"] == "broad_organoid_dependency"
    assert out["frac_dependent"] == pytest.approx(0.746)
    assert out["median_gene_effect"] == pytest.approx(-0.87)
    assert out["n_models_screened"] == 114
    # audit string names the product + the cohort size — the anti-pooling guard.
    ctx = out["organoid_dependency_context"]
    assert "organoid-crispr-dependency-26q1-v1" in ctx and "114/114" in ctx


def test_build_summary_pan_essential(monkeypatch):
    lk = _load()
    monkeypatch.setattr(lk, "_organoid_row", lambda sym: _row(1.0, median_eff=-2.6, pct=99.6))
    out = lk.build_summary("RPL9")
    assert out["organoid_dependency_class"] == "pan_organoid_essential"


def test_build_summary_absent_gene_is_data_unavailable(monkeypatch):
    lk = _load()
    monkeypatch.setattr(lk, "_organoid_row", lambda sym: None)
    out = lk.build_summary("MADE_UP_GENE")
    assert out["organoid_dependency_class"] == "data_unavailable"
    assert out["frac_dependent"] is None
    assert "target absent or product unavailable" in out["organoid_dependency_context"]
    assert "_data_note" in out


def _lin(lineage, frac_dep, *, n=20):
    # a _lineage_rows dict (see lookup._lineage_rows return shape)
    return {
        "lineage": lineage,
        "n_lineage_cohort": n,
        "n_models_screened": n,
        "n_dependent": int(frac_dep * n),
        "frac_dependent": frac_dep,
        "n_strongly_dependent": int(frac_dep * n),
        "median_gene_effect": -0.8,
    }


def test_build_summary_target_grain_invariant_but_lineage_indication_conditioned(monkeypatch):
    """The PAN-organoid (target-grain) result must NOT change with indication, but the v2 per-lineage
    fields ARE indication-conditioned (COADREAD->Bowel vs STAD->Esophagus/Stomach). Regression: the
    old test asserted the WHOLE dict was indication-invariant, which broke when per-lineage landed."""
    lk = _load()
    monkeypatch.setattr(lk, "_organoid_row", lambda sym: _row(0.30))
    monkeypatch.setattr(lk, "_lineage_rows", lambda sym: (_lin("Bowel", 0.9), _lin("Esophagus/Stomach", 0.2)))
    a = lk.build_summary("EGFR", "COADREAD")
    b = lk.build_summary("EGFR", "STAD")
    # target-grain fields are identical across indications
    for k in (
        "organoid_dependency_class",
        "frac_dependent",
        "mean_gene_effect",
        "per_lineage_stats",
        "n_lineages_evaluated",
    ):
        assert a[k] == b[k], k
    # but the indication-conditioned lineage lens differs
    assert a["organoid_lineage"] == "Bowel"
    assert b["organoid_lineage"] == "Esophagus/Stomach"
    assert a != b


def test_build_summary_empty_target_is_data_unavailable(monkeypatch):
    lk = _load()
    monkeypatch.setattr(lk, "_organoid_row", lambda sym: None)
    out = lk.build_summary("")
    assert out["organoid_dependency_class"] == "data_unavailable"
    assert out["target"] == ""
