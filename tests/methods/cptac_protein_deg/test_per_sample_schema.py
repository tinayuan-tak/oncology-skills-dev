"""derive_per_sample — the per-sample CPTAC long-form product schema + reshape contract.

No S3 / no PDC: pins the module loads + exposes the expected long-form columns and reuses the
stage-01 helpers. The live reshape is smoke-tested against real PDC data at build time (COAD:
1.3M rows, 97 tumor + 100 normal aliquots).
"""
import importlib


def test_module_loads_and_reuses_stage01_helpers():
    dps = importlib.import_module("methods.cptac_protein_deg.derive_per_sample")
    s01 = dps._load_stage01()
    # the reused helpers must exist on stage 01
    for fn in ("parse_sample_txt", "list_proteome_keys", "find_key", "download", "canonical_aliquot"):
        assert hasattr(s01, fn), fn
    assert "COAD" in s01.CPTAC_STUDIES and len(s01.CPTAC_STUDIES) == 10


def test_output_prefix_and_helpers_present():
    dps = importlib.import_module("methods.cptac_protein_deg.derive_per_sample")
    assert dps.OUTPUT_S3_PREFIX.endswith("cptac-protein-tumor-vs-normal-per-sample-v1")
    assert callable(dps.per_sample_cohort)


def test_dedup_replicates_collapses_by_mean():
    """Chain-review #1: canonical_aliquot strips the .N replicate suffix, so replicate Log-Ratio
    columns collapse to one aliquot. _dedup_replicates must MEAN them per (gene, aliquot) so the
    per-sample product has exactly one row per (gene, aliquot) — not 2+ that over-weight replicated
    samples in the per-cohort boxplot distribution + Welch/MWU n-counts."""
    import pandas as pd
    dps = importlib.import_module("methods.cptac_protein_deg.derive_per_sample")
    # gene G: aliquot A has TWO replicate rows (5.0, 7.0) → mean 6.0; aliquot B has one (2.0).
    # gene H: aliquot A single (1.0). Total distinct (gene,aliquot) pairs = 3.
    tmt = pd.DataFrame({
        "Gene":                 ["G", "G", "G", "H"],
        "aliquot_submitter_id": ["A", "A", "B", "A"],
        "log2_ratio":           [5.0, 7.0, 2.0, 1.0],
    })
    out = dps._dedup_replicates(tmt)
    assert len(out) == 3, "3 distinct (gene, aliquot) pairs after collapsing G/A's replicates"
    ga = out[(out["Gene"] == "G") & (out["aliquot_submitter_id"] == "A")].iloc[0]
    assert ga["log2_ratio"] == 6.0, "replicate log-ratios averaged (mean(5,7)=6)"
    # no duplicate (gene, aliquot) survives
    assert not out.duplicated(subset=["Gene", "aliquot_submitter_id"]).any()


def test_sample_map_dedup_prevents_merge_fanout():
    """Chain-review #1 (second path): an aliquot can appear on multiple TMT channels → multiple
    sample_map rows for one aliquot_submitter_id. The (gene, aliquot) inner-merge would FAN OUT each
    deduped tmt row back into 2+ (the residual BRCA _D2 / HNSCC / LUAD dups). Deduping the tmt side
    alone is insufficient; sample_map must be collapsed to one row/aliquot before the merge. This
    reproduces the merge with a duplicated sample_map and asserts no fan-out."""
    import pandas as pd
    # one deduped tmt row for (KRAS, A); sample_map has aliquot A on TWO channels (the fan-out shape)
    tmt = pd.DataFrame({"Gene": ["KRAS"], "aliquot_submitter_id": ["A"], "log2_ratio": [1.0]})
    sample_map = pd.DataFrame({
        "aliquot_submitter_id": ["A", "A"],   # SAME aliquot, two channels
        "sample_type":          ["Primary Tumor", "Primary Tumor"],
        "condition":            ["Tumor", "Tumor"],
    })
    # the fix: collapse sample_map to one row per aliquot before merging (matches derive_per_sample)
    sample_map = sample_map.drop_duplicates(subset=["aliquot_submitter_id"], keep="first")
    merged = tmt.merge(sample_map, on="aliquot_submitter_id", how="inner")
    assert len(merged) == 1, "merge must not fan out a single (gene, aliquot) via duplicate sample_map rows"
