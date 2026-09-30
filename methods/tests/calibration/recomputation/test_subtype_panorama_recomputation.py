"""T3 recomputation anchors -- batch-F (#2088): the 4 subtype-panorama / procan cards.

  1. cellline-protein-abundance-procan   -- onc_methods.procan_protein_abundance.cli.load_and_classify
  2. cellline-rna-distribution-by-subtype -- onc_methods.depmap_expression_distribution.read.build_expression_subtype_panorama
  3. tumor-protein-distribution-by-subtype -- onc_methods.cptac_protein_distribution.read.build_protein_subtype_panorama
  4. tumor-rna-distribution-by-subtype    -- onc_methods.tcga_gtex_expression_distribution.cli.build_subtype_panorama

Clone of the batch A-E recomputation tests (see test_protein_abundance_recomputation.py /
test_sc_normal_celltype_recomputation.py for the pattern). Each anchor stores the IRREPRODUCIBLE raw
input the reader's own S3-load seam(s) returned (never a derived value), captured live by
capture_subtype_panorama_anchor.py. This test reconstructs those inputs from the committed fixtures,
monkeypatches ONLY the seam(s), and re-runs the REAL reader -- asserting the re-derived summary
equals the anchor's `expected` block byte-exact. The capture tool already proved this equality once
online (its own fidelity guard); this replays it OFFLINE against the same frozen bytes, so a fixture
that silently drifts (or a reader change that silently changes behavior) is caught in CI.

OFFLINE -- reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from unittest import mock

import pandas as pd
import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _deep_close(a, b, abs_tol: float = 1e-9) -> bool:
    """Structural equality with a TIGHT float tolerance on leaf numbers. The anchors freeze DERIVED
    floats (e.g. coefficient_of_variation = sd/mean) captured on one host; the reader recomputes them
    on another (CI), where BLAS/numpy summation-order re-association shifts the last ULP (~1e-15). An
    exact `==` on such a leaf reds across hosts for a purely representational difference — this compares
    leaf floats with abs_tol=1e-9 (a real drift, incl. every teeth mutation, moves values by orders of
    magnitude more) while keeping ints/strings/bools/None and container SHAPE byte-exact."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=abs_tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_deep_close(a[k], b[k], abs_tol) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_deep_close(x, y, abs_tol) for x, y in zip(a, b))
    return a == b


# =====================================================================================
# 1) cellline-protein-abundance-procan
# =====================================================================================

from onc_methods.procan_protein_abundance import cli as pcli  # noqa: PLC0415,E402

PROCAN_ANCHORS = sorted(ANCHOR_DIR.glob("*.procan_protein_abundance.json"))
_PROCAN_FIELDS = (
    "protein_expression_class",
    "protein_high_abundance_class_cutoff",
    "n_cell_lines_evaluated",
    "n_cell_lines_in_panel",
    "fraction_detected",
    "median_log2_abundance_panel",
    "p5_log2_abundance_panel",
    "p25_log2_abundance_panel",
    "p75_log2_abundance_panel",
    "p95_log2_abundance_panel",
    "log2_abundance_iqr",
    "n_lineages_evaluated",
    "per_lineage_stats",
    "n_lineage_restricted_lineages",
    "method_version",
    "protein_abundance_source",
    "allgene_percentile",
    "allgene_percentile_class",
    "allgene_percentile_context",
)

pytestmark_procan = pytest.mark.skipif(not PROCAN_ANCHORS, reason="no procan anchors committed")


@pytest.mark.skipif(not PROCAN_ANCHORS, reason="no procan anchors committed")
@pytest.mark.parametrize("anchor_path", PROCAN_ANCHORS, ids=lambda p: p.stem)
def test_procan_rederives_from_raw_rows(anchor_path: Path):
    anchor = _load(anchor_path)
    # Symbol->UniProt resolution is a separate live/cached lookup seam (the general uniprot_hugo map),
    # not part of the ProCan abundance re-derivation under test — pin it to the anchor's captured
    # accession so the classification is re-derived purely from the frozen rows + null, network-free.
    with mock.patch.object(pcli, "resolve_accessions", lambda target: [anchor["accession"]]):
        off = pcli.load_and_classify(
            anchor["target"],
            product_path=str(HERE / anchor["rows_fixture"]),
            null_path=str(HERE / anchor["null_fixture"]),
        )
    for f in _PROCAN_FIELDS:
        assert _deep_close(off.get(f), anchor["expected"][f]), f"{anchor_path.stem}: {f} != anchor"


@pytest.mark.skipif(not PROCAN_ANCHORS, reason="no procan anchors committed")
def test_procan_fixture_md5_matches_anchors():
    for anchor_path in PROCAN_ANCHORS:
        anchor = _load(anchor_path)
        assert _md5(HERE / anchor["rows_fixture"]) == anchor["rows_md5"], f"{anchor_path.stem}: rows md5 drift"
        assert _md5(HERE / anchor["null_fixture"]) == anchor["null_md5"], f"{anchor_path.stem}: null md5 drift"


@pytest.mark.skipif(not PROCAN_ANCHORS, reason="no procan anchors committed")
@pytest.mark.parametrize("anchor_path", PROCAN_ANCHORS, ids=lambda p: p.stem)
def test_procan_teeth_silencing_rows_forces_data_unavailable(anchor_path: Path):
    """Teeth: an empty rows fixture must collapse the class to data_unavailable -- proving the class
    is a live function of the frozen rows, not echoed from the anchor."""

    anchor = _load(anchor_path)
    empty = HERE / "procan_vectors" / "_empty_teeth.parquet"
    table = pq.read_table(HERE / anchor["rows_fixture"])
    pq.write_table(table.slice(0, 0), empty)
    try:
        with mock.patch.object(pcli, "resolve_accessions", lambda target: [anchor["accession"]]):
            off = pcli.load_and_classify(
                anchor["target"], product_path=str(empty), null_path=str(HERE / anchor["null_fixture"])
            )
        assert off["protein_expression_class"] == "data_unavailable"
        assert off["protein_expression_class"] != anchor["expected"]["protein_expression_class"]
    finally:
        empty.unlink(missing_ok=True)


# =====================================================================================
# 2) cellline-rna-distribution-by-subtype
# =====================================================================================

from onc_methods.depmap_expression_distribution import read as cellline_rd  # noqa: PLC0415,E402
from onc_methods.subgroup_common import scoping  # noqa: PLC0415,E402

CELLLINE_RNA_ANCHORS = sorted(ANCHOR_DIR.glob("*.cellline_rna_subtype.json"))
_CELLLINE_RNA_FIELDS = (
    "target",
    "indication",
    "per_subgroup_metrics",
    "subtype_axis_available",
    "subtype_axis_quality",
    "n_subtypes_measured",
    "n_subtypes_enriched",
    "n_subtypes_depleted",
    "subtype_stratification_class",
    "spotlight_subtype",
    "pooled_lineage_median_log2tpm",
    "assignment_manifest",
    "_data_source",
)


def _load_cellline_rna_inputs(anchor: dict):
    tpm_by_model = json.loads((HERE / anchor["tpm_fixture"]).read_text())
    assignments = pq.read_table(HERE / anchor["assignments_fixture"]).to_pandas()
    return tpm_by_model, assignments


def _rederive_cellline_rna(anchor: dict, tpm_by_model: dict, assignments: pd.DataFrame) -> dict:
    def _fake_cached_tpm(t, release_pin):
        return dict(tpm_by_model), False

    def _fake_load_assignments(manifest_id, data_catalog_repo=None):
        return assignments.copy()

    with (
        mock.patch.object(cellline_rd, "_cached_tpm", _fake_cached_tpm),
        mock.patch.object(scoping, "load_assignments", _fake_load_assignments),
    ):
        return cellline_rd.build_expression_subtype_panorama(
            anchor["target"], anchor["indication"], anchor["strata"], anchor["manifest"]
        )


@pytest.mark.skipif(not CELLLINE_RNA_ANCHORS, reason="no cellline-rna-subtype anchors committed")
@pytest.mark.parametrize("anchor_path", CELLLINE_RNA_ANCHORS, ids=lambda p: p.stem)
def test_cellline_rna_rederives_from_raw_substrate(anchor_path: Path):
    anchor = _load(anchor_path)
    tpm_by_model, assignments = _load_cellline_rna_inputs(anchor)
    off = _rederive_cellline_rna(anchor, tpm_by_model, assignments)
    for f in _CELLLINE_RNA_FIELDS:
        assert _deep_close(off.get(f), anchor["expected"][f]), f"{anchor_path.stem}: {f} != anchor"


@pytest.mark.skipif(not CELLLINE_RNA_ANCHORS, reason="no cellline-rna-subtype anchors committed")
def test_cellline_rna_fixture_md5_matches_anchors():
    for anchor_path in CELLLINE_RNA_ANCHORS:
        anchor = _load(anchor_path)
        assert _md5(HERE / anchor["tpm_fixture"]) == anchor["tpm_md5"], f"{anchor_path.stem}: tpm md5 drift"
        assert _md5(HERE / anchor["assignments_fixture"]) == anchor["assignments_md5"], (
            f"{anchor_path.stem}: assignments md5 drift"
        )


@pytest.mark.skipif(not CELLLINE_RNA_ANCHORS, reason="no cellline-rna-subtype anchors committed")
@pytest.mark.parametrize("anchor_path", CELLLINE_RNA_ANCHORS, ids=lambda p: p.stem)
def test_cellline_rna_teeth_zeroing_tpm_collapses_signal(anchor_path: Path):
    """Teeth: zeroing every model's log2(TPM+1) must move the measured strata's per-stratum class
    away from the anchor's pinned value (or drop out of `measured`) -- proving the per-stratum stats
    are a live scan of the frozen TPM dict, not echoed."""
    anchor = _load(anchor_path)
    tpm_by_model, assignments = _load_cellline_rna_inputs(anchor)
    if anchor["expected"]["n_subtypes_measured"] == 0:
        pytest.skip("no measured stratum to perturb")
    zeroed = {m: 0.0 for m in tpm_by_model}
    off = _rederive_cellline_rna(anchor, zeroed, assignments)
    measured = [r for r in off["per_subgroup_metrics"] if r["evidence_state"] == "measured"]
    anchor_measured = [r for r in anchor["expected"]["per_subgroup_metrics"] if r["evidence_state"] == "measured"]
    assert measured, "mutation should not remove measured strata (n unaffected by value)"
    assert any(r["class"] != m["class"] for r, m in zip(measured, anchor_measured)) or measured != anchor_measured


# =====================================================================================
# 3) tumor-protein-distribution-by-subtype
# =====================================================================================

from onc_methods.cptac_protein_deg import read as deg_read  # noqa: PLC0415,E402
from onc_methods.cptac_protein_distribution import read as cptac_rd  # noqa: PLC0415,E402

CPTAC_PROTEIN_ANCHORS = sorted(ANCHOR_DIR.glob("*.tumor_protein_subtype.json"))
_CPTAC_PROTEIN_FIELDS = (
    "target",
    "indication",
    "per_subgroup_metrics",
    "subtype_axis_available",
    "subtype_axis_quality",
    "n_subtypes_measured",
    "n_subtypes_enriched",
    "n_subtypes_depleted",
    "subtype_stratification_class",
    "pooled_cohort_median_log2_ratio",
    "assignment_manifest",
)


def _load_cptac_protein_inputs(anchor: dict):
    per_sample = pq.read_table(HERE / anchor["sample_fixture"]).to_pandas()
    assignments = pq.read_table(HERE / anchor["assignments_fixture"]).to_pandas()
    return per_sample, assignments


def _rederive_cptac_protein(anchor: dict, per_sample: pd.DataFrame, assignments: pd.DataFrame) -> dict:
    def _fake_read_per_sample(t):
        return per_sample.copy()

    def _fake_load_assignments(manifest_id, data_catalog_repo=None):
        return assignments.copy()

    with (
        mock.patch.object(deg_read, "read_per_sample", _fake_read_per_sample),
        mock.patch.object(scoping, "load_assignments", _fake_load_assignments),
    ):
        return cptac_rd.build_protein_subtype_panorama(
            anchor["target"], anchor["indication"], anchor["strata"], anchor["manifest"]
        )


@pytest.mark.skipif(not CPTAC_PROTEIN_ANCHORS, reason="no tumor-protein-subtype anchors committed")
@pytest.mark.parametrize("anchor_path", CPTAC_PROTEIN_ANCHORS, ids=lambda p: p.stem)
def test_cptac_protein_rederives_from_raw_substrate(anchor_path: Path):
    anchor = _load(anchor_path)
    per_sample, assignments = _load_cptac_protein_inputs(anchor)
    off = _rederive_cptac_protein(anchor, per_sample, assignments)
    for f in _CPTAC_PROTEIN_FIELDS:
        assert _deep_close(off.get(f), anchor["expected"][f]), f"{anchor_path.stem}: {f} != anchor"


@pytest.mark.skipif(not CPTAC_PROTEIN_ANCHORS, reason="no tumor-protein-subtype anchors committed")
def test_cptac_protein_fixture_md5_matches_anchors():
    for anchor_path in CPTAC_PROTEIN_ANCHORS:
        anchor = _load(anchor_path)
        assert _md5(HERE / anchor["sample_fixture"]) == anchor["sample_md5"], f"{anchor_path.stem}: sample md5 drift"
        assert _md5(HERE / anchor["assignments_fixture"]) == anchor["assignments_md5"], (
            f"{anchor_path.stem}: assignments md5 drift"
        )


@pytest.mark.skipif(not CPTAC_PROTEIN_ANCHORS, reason="no tumor-protein-subtype anchors committed")
@pytest.mark.parametrize("anchor_path", CPTAC_PROTEIN_ANCHORS, ids=lambda p: p.stem)
def test_cptac_protein_teeth_emptying_samples_collapses_axis(anchor_path: Path):
    """Teeth: dropping every per-sample row must collapse subtype_axis_available to False (no rows
    to stratify) -- proving the axis is a live read of the frozen per-sample rows, not echoed."""
    anchor = _load(anchor_path)
    per_sample, assignments = _load_cptac_protein_inputs(anchor)
    empty = per_sample.iloc[0:0]
    off = _rederive_cptac_protein(anchor, empty, assignments)
    assert off["n_subtypes_measured"] == 0
    assert (
        off["n_subtypes_measured"] != anchor["expected"]["n_subtypes_measured"]
        or anchor["expected"]["n_subtypes_measured"] == 0
    )


# =====================================================================================
# 4) tumor-rna-distribution-by-subtype (heaviest)
# =====================================================================================

from onc_methods.expression_purity_confound import read as purity_read  # noqa: PLC0415,E402
from onc_methods.tcga_gtex_expression_distribution import cli as tcli  # noqa: PLC0415,E402
from onc_methods.tcga_gtex_expression_distribution import read as tumor_rd  # noqa: PLC0415,E402

TUMOR_RNA_ANCHORS = sorted(ANCHOR_DIR.glob("*.tumor_rna_subtype.json"))
_TUMOR_RNA_FIELDS = (
    "target",
    "indication",
    "subtype_axis_available",
    "subtype_axis_quality",
    "purity_source",
    "subtype_purity_spread",
    "spotlight_subtype",
    "assignment_manifest",
    "n_subtypes_measured",
    "n_subtypes_enriched",
    "n_subtypes_clearing_normal_window",
    "n_subtypes_clearing_proxy_window_by_tissue",
    "n_subtypes_restricted",
    "subtype_stratification_class",
    "matched_normal_tissue",
    "normal_comparator_type",
    "proxy_normal_tissues",
    "subtype_omnibus_kruskal_h",
    "subtype_omnibus_p",
    "subtype_variance_explained",
    "subtype_effect_size_class",
    "which_subtypes_separate",
    "subtype_omnibus_driving_axis",
    "subtype_omnibus_by_axis",
    "per_subgroup_metrics",
    "method_version",
)


def _load_tumor_rna_inputs(anchor: dict):
    tcga_df = pq.read_table(HERE / anchor["tcga_fixture"]).to_pandas()
    gtex_df = pq.read_table(HERE / anchor["gtex_fixture"]).to_pandas()
    sidecar_df = pq.read_table(HERE / anchor["sidecar_fixture"]).to_pandas()
    assignments_df = pq.read_table(HERE / anchor["assignments_fixture"]).to_pandas()
    purity_by_case = json.loads((HERE / anchor["purity_fixture"]).read_text())
    allgene_pct = json.loads((HERE / anchor["allgene_percentile_fixture"]).read_text())
    return tcga_df, gtex_df, sidecar_df, assignments_df, purity_by_case, allgene_pct


def _rederive_tumor_rna(
    anchor: dict, tcga_df, gtex_df, sidecar_df, assignments_df, purity_by_case, allgene_pct
) -> dict:
    def _fake_read_gene(which, t):
        if which == "gtex":
            return gtex_df.copy()
        return tcga_df.copy()

    def _fake_load_sidecar():
        df = sidecar_df[["sample_id", "submitter_id"]].copy()
        df["case"] = df["submitter_id"].map(tumor_rd._tcga_case)  # noqa: SLF001
        return df

    def _fake_load_subtype_assignments(ind):
        return assignments_df.copy(), anchor["base_manifest"]

    def _fake_allgene_percentile(t, studies):
        return dict(allgene_pct)

    def _fake_load_purity():
        return dict(purity_by_case)

    def _fake_load_assignments(manifest_id, data_catalog_repo=None):
        # The landscape reader's per-stratum join-coverage guard (scoping.compute_join_coverage)
        # re-loads the assignment shard a SECOND time, independently of the _load_subtype_assignments
        # seam above — an S3 fetch in a cache-cold environment (e.g. CI). It only reads per-stratum
        # member sample_ids for the molecular strata, identical between the base shard and the
        # maf-unioned frame the landscape iterates, so feeding the frozen union reproduces every
        # match_rate exactly while keeping the re-derivation network-free.
        return assignments_df.copy()

    with (
        mock.patch.object(tumor_rd, "_read_gene", _fake_read_gene),
        mock.patch.object(tumor_rd, "_load_sidecar", _fake_load_sidecar),
        mock.patch.object(tumor_rd, "_load_subtype_assignments", _fake_load_subtype_assignments),
        mock.patch.object(tumor_rd, "_tumor_allgene_percentile", _fake_allgene_percentile),
        mock.patch.object(purity_read, "_load_purity_by_case", _fake_load_purity),
        mock.patch.object(scoping, "load_assignments", _fake_load_assignments),
    ):
        return tcli.build_subtype_panorama(anchor["target"], anchor["indication"])


@pytest.mark.skipif(not TUMOR_RNA_ANCHORS, reason="no tumor-rna-subtype anchors committed")
@pytest.mark.parametrize("anchor_path", TUMOR_RNA_ANCHORS, ids=lambda p: p.stem)
def test_tumor_rna_rederives_from_raw_substrate(anchor_path: Path):
    anchor = _load(anchor_path)
    inputs = _load_tumor_rna_inputs(anchor)
    off = _rederive_tumor_rna(anchor, *inputs)
    for f in _TUMOR_RNA_FIELDS:
        assert _deep_close(off.get(f), anchor["expected"][f]), f"{anchor_path.stem}: {f} != anchor"


@pytest.mark.skipif(not TUMOR_RNA_ANCHORS, reason="no tumor-rna-subtype anchors committed")
def test_tumor_rna_fixture_md5_matches_anchors():
    for anchor_path in TUMOR_RNA_ANCHORS:
        anchor = _load(anchor_path)
        for key, md5key in (
            ("tcga_fixture", "tcga_md5"),
            ("gtex_fixture", "gtex_md5"),
            ("sidecar_fixture", "sidecar_md5"),
            ("assignments_fixture", "assignments_md5"),
            ("purity_fixture", "purity_md5"),
        ):
            assert _md5(HERE / anchor[key]) == anchor[md5key], f"{anchor_path.stem}: {key} md5 drift"


@pytest.mark.skipif(not TUMOR_RNA_ANCHORS, reason="no tumor-rna-subtype anchors committed")
@pytest.mark.parametrize("anchor_path", TUMOR_RNA_ANCHORS, ids=lambda p: p.stem)
def test_tumor_rna_teeth_emptying_tcga_collapses_axis(anchor_path: Path):
    """Teeth: an empty TCGA long-product slice must collapse the pooled read to data_unavailable,
    which propagates to subtype_axis_available=False -- proving the axis genuinely depends on the
    frozen tcga fixture rather than being echoed from the anchor."""
    anchor = _load(anchor_path)
    tcga_df, gtex_df, sidecar_df, assignments_df, purity_by_case, allgene_pct = _load_tumor_rna_inputs(anchor)
    empty_tcga = tcga_df.iloc[0:0]
    off = _rederive_tumor_rna(anchor, empty_tcga, gtex_df, sidecar_df, assignments_df, purity_by_case, allgene_pct)
    assert off["subtype_axis_available"] is False
    assert off["subtype_axis_available"] != anchor["expected"]["subtype_axis_available"]


def test_anchor_set_is_not_vacuous():
    """Non-vacuity floor across all 4 batch-F card families: at least 2 targets per family, and the
    axis-available / subtype-measured paths are exercised (not every anchor is a trivial 0-stratum
    read)."""
    families = {
        "procan": PROCAN_ANCHORS,
        "cellline_rna_subtype": CELLLINE_RNA_ANCHORS,
        "tumor_protein_subtype": CPTAC_PROTEIN_ANCHORS,
        "tumor_rna_subtype": TUMOR_RNA_ANCHORS,
    }
    for name, files in families.items():
        assert len(files) >= 2, f"{name}: need >= 2 anchors, found {len(files)}"
    for files in (CELLLINE_RNA_ANCHORS, CPTAC_PROTEIN_ANCHORS, TUMOR_RNA_ANCHORS):
        assert any(_load(p)["expected"]["subtype_axis_available"] for p in files), (
            "no anchor in this family exercises a live subtype axis"
        )
