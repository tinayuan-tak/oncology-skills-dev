"""Producer compute logic on a tiny synthetic organoid matrix (no S3).

Validates per-gene dependency counts, fractions, central-tendency, and the organoid-cohort
dependency percentile orientation (more-negative median → higher percentile).
"""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

BUILD = (Path(__file__).resolve().parents[3] / "methods"
         / "organoid_dependency_precompute" / "build.py")


def _load():
    spec = importlib.util.spec_from_file_location("organoid_build", BUILD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _synthetic_matrix(tmp_path):
    # 4 models × 3 genes, headers in 'SYMBOL (ENTREZ)' form.
    #   ESS  : essential everywhere (all < -1.0)      → pan-essential, most dependent
    #   SEL  : dependent in 2/4, one strongly         → selective
    #   NEUT : never dependent (near 0), one NaN      → not dependent, least dependent
    df = pd.DataFrame({
        "ModelID": ["ACH-1", "ACH-2", "ACH-3", "ACH-4"],
        "ESS (100)": [-1.5, -1.2, -1.8, -1.1],
        "SEL (200)": [-0.9, -0.2, -1.2, -0.1],
        "NEUT (300)": [0.05, -0.1, 0.0, None],
    }).set_index("ModelID")
    p = tmp_path / "OrganoidGeneEffect.csv"
    df.to_csv(p)
    return p


def test_build_per_gene_stats(tmp_path):
    b = _load()
    # model_uri points at a nonexistent path → cohort log is skipped gracefully (advisory only).
    out = b.build(str(_synthetic_matrix(tmp_path)), str(tmp_path / "no_model.csv"))
    out = out.set_index("gene_symbol")

    # ESS: 4/4 dependent (< -0.5), 4/4 strong (< -1.0)
    assert out.loc["ESS", "n_models_screened"] == 4
    assert out.loc["ESS", "frac_dependent"] == pytest.approx(1.0)
    assert out.loc["ESS", "frac_strongly_dependent"] == pytest.approx(1.0)
    assert out.loc["ESS", "entrez_gene_id"] == "100"

    # SEL: -0.9 and -1.2 are < -0.5 → 2/4 dependent; only -1.2 < -1.0 → 1/4 strong
    assert out.loc["SEL", "n_dependent"] == 2
    assert out.loc["SEL", "frac_dependent"] == pytest.approx(0.5)
    assert out.loc["SEL", "n_strongly_dependent"] == 1

    # NEUT: one value is NaN → screened in 3 models, none dependent
    assert out.loc["NEUT", "n_models_screened"] == 3
    assert out.loc["NEUT", "n_dependent"] == 0
    assert out.loc["NEUT", "frac_dependent"] == pytest.approx(0.0)


def test_dependency_percentile_orientation(tmp_path):
    b = _load()
    out = b.build(str(_synthetic_matrix(tmp_path)), str(tmp_path / "no_model.csv")).set_index("gene_symbol")
    # more-negative median → higher percentile. ESS (most dependent) top, NEUT (least) bottom.
    assert out.loc["ESS", "organoid_dependency_percentile"] > out.loc["SEL", "organoid_dependency_percentile"]
    assert out.loc["SEL", "organoid_dependency_percentile"] > out.loc["NEUT", "organoid_dependency_percentile"]
    assert (out["n_models_total"] == 4).all()
    assert (out["n_genes"] == 3).all()


def test_write_roundtrip_schema(tmp_path):
    b = _load()
    df = b.build(str(_synthetic_matrix(tmp_path)), str(tmp_path / "no_model.csv"))
    out = tmp_path / "summary.parquet"
    meta = b.write(df, out)
    assert meta["n_rows"] == 3 and meta["size_bytes"] > 0 and len(meta["md5"]) == 32
    rt = pd.read_parquet(out)
    assert list(rt.columns) == [
        "gene_symbol", "entrez_gene_id", "n_models_screened", "n_dependent",
        "n_strongly_dependent", "frac_dependent", "frac_strongly_dependent", "mean_gene_effect",
        "median_gene_effect", "min_gene_effect", "organoid_dependency_percentile",
        "n_models_total", "n_genes"]
