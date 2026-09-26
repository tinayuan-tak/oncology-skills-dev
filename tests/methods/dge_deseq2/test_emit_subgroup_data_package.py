"""The by-subgroup diagnostic data-package emitter (analysis-methods#738).

Mirrors `methods/dge_deseq2/tests/test_emit_data_package.py` for the stratified product:

* **Verdict-invisibility**: the by-subgroup id ends in `-by-subgroup-v1`, never the pooled
  sensitivity discovery suffix, and never equals the pooled sensitivity id — else a per-subgroup
  diagnostic would leak into the pooled single-gene verdict path.
* **Three-way id equality**: emitted sidecar `id` == S3 key directory stem.
* **Upload plan**: parquet + sidecar (as provenance.yaml) + the whole merged QC bundle, every key
  under the package's own prefix.
* **Fail-loud** on an absent aggregated provenance or an empty QC bundle.

Hermetic: a synthetic run out-dir stands in for a live multi-axis compute; no S3, no DESeq2.
"""

from __future__ import annotations

import csv

import pytest
import yaml

from methods.dge_deseq2 import derive_pancan_stack as dps
from methods.dge_deseq2 import emit_subgroup_data_package as esub

_SIX = ["COADREAD", "ESCA", "HNSC", "NSCLC", "PAAD", "STAD"]


def _write_run_dir(root, *, with_prov=True, with_qc=True):
    """Materialize a minimal but structurally-real multi-axis run out-dir under `root`."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "sensitivity_by_subgroup.parquet").write_bytes(b"PAR1fake-parquet-bytes")
    if with_prov:
        prov = {
            "indication": "ESCA",
            "substrate": "recount3/tcga-gtex-2023-01-04 (G026)",
            "tcga_studies": ["ESCA"],
            "gtex_tissue": "ESOPHAGUS",
            "subgroup_axes": ["histology", "amplification", "driver_mutation"],
            "strata_emitted": {
                "histology": ["histology_ESCC", "histology_EAC"],
                "amplification": ["HER2_amp"],
                "driver_mutation": ["TP53_mut"],
            },
            "n_tumor_by_stratum": {
                "histology_ESCC": 90,
                "histology_EAC": 79,
                "HER2_amp": 28,
                "TP53_mut": 131,
            },
            "n_adjacent": 11,
            "n_gtex": 653,
            "cells_ran": ["A", "C"],
            "member_key": "patient_id",
            "min_subgroup_tumor": 10,
            "deseq2_version": "1.50.2",
            "apeglm_version": "1.32.0",
            "sva_version": "3.58.0",
            "schema_version": "1",
        }
        (root / "provenance_by_subgroup.yaml").write_text(yaml.safe_dump(prov, sort_keys=False))
    if with_qc:
        cell_dir = root / "qc" / "histology__histology_ESCC" / "A"
        cell_dir.mkdir(parents=True)
        (cell_dir / "volcano.png").write_bytes(b"\x89PNG-fake")
        with (root / "qc" / "qc_summary.csv").open("w", newline="") as fh:
            csv.writer(fh).writerow(["axis", "stratum", "cell", "n_sig"])
    return root


# ── ids + verdict-invisibility ───────────────────────────────────────────────
@pytest.mark.parametrize("indication", _SIX)
def test_subgroup_catalog_id_shape(indication):
    cid = esub.subgroup_catalog_id(indication)
    assert cid == f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-by-subgroup-v1"
    assert cid.endswith("-by-subgroup-v1")


@pytest.mark.parametrize("indication", _SIX)
def test_subgroup_id_never_matches_pooled_discovery(indication):
    cid = esub.subgroup_catalog_id(indication)
    pooled = f"{indication.lower()}{dps._SENSITIVITY_SUFFIX}"
    assert cid != pooled
    assert not cid.endswith(dps._SENSITIVITY_SUFFIX), (
        f"by-subgroup id {cid!r} ends in the pooled sensitivity suffix — it would leak into the verdict path"
    )


def test_three_way_id_equality_round_trips():
    cid = esub.subgroup_catalog_id("ESCA")
    uri = f"{esub.derived_prefix(cid)}/sensitivity_by_subgroup.parquet"
    assert esub.prefix_stem_of(uri) == cid
    esub.assert_three_way_id_equality(cid, uri)


# ── sidecar construction ─────────────────────────────────────────────────────
def test_sidecar_carries_id_and_holds_three_way(tmp_path):
    out = _write_run_dir(tmp_path / "run")
    sidecar = esub.build_subgroup_sidecar(out, "ESCA", git_sha="deadbeef")
    assert sidecar["id"] == "esca-dge-tumor-vs-normal-sensitivity-by-subgroup-v1"
    esub.assert_three_way_id_equality(sidecar["id"], sidecar["s3_uri"])
    assert sidecar["classifier_input"] is False
    assert sidecar["role"] == "stratified-diagnostic"
    assert sidecar["subgroup_axes"] == ["histology", "amplification", "driver_mutation"]
    assert sidecar["generated_by"] == "methods/dge_deseq2@deadbeef"
    assert sidecar["qc_bundle"]["n_files"] == 2  # 1 figure + qc_summary.csv
    assert "qc/qc_summary.csv" in sidecar["qc_bundle"]["files"]


def test_sidecar_fails_loud_on_missing_provenance(tmp_path):
    out = _write_run_dir(tmp_path / "run", with_prov=False)
    with pytest.raises(FileNotFoundError, match="provenance_by_subgroup.yaml missing"):
        esub.build_subgroup_sidecar(out, "ESCA", git_sha="x")


def test_sidecar_fails_loud_on_empty_qc_bundle(tmp_path):
    out = _write_run_dir(tmp_path / "run", with_qc=False)
    with pytest.raises(FileNotFoundError, match="QC bundle dir"):
        esub.build_subgroup_sidecar(out, "ESCA", git_sha="x")


# ── upload plan ──────────────────────────────────────────────────────────────
def test_upload_plan_covers_parquet_sidecar_and_qc_all_under_prefix(tmp_path):
    out = _write_run_dir(tmp_path / "run")
    sidecar = esub.build_subgroup_sidecar(out, "ESCA", git_sha="x")
    sidecar_path = esub.write_subgroup_sidecar(out, sidecar)
    plan = esub.plan_subgroup_upload(out, "ESCA", sidecar_path)

    cid = "esca-dge-tumor-vs-normal-sensitivity-by-subgroup-v1"
    # 1 parquet + 1 sidecar + 2 QC files (figure + qc_summary.csv).
    assert len(plan) == 4
    uris = {u for _, u in plan}
    for uri in uris:
        assert esub.prefix_stem_of(uri) == cid
    assert f"{esub.derived_prefix(cid)}/sensitivity_by_subgroup.parquet" in uris
    assert f"{esub.derived_prefix(cid)}/provenance.yaml" in uris
    assert f"{esub.derived_prefix(cid)}/qc/qc_summary.csv" in uris
    # Sidecar uploaded under the canonical provenance.yaml name, not its local filename.
    assert not any(u.endswith("sensitivity_by_subgroup.provenance.yaml") for u in uris)


def test_upload_plan_fails_loud_without_parquet(tmp_path):
    out = _write_run_dir(tmp_path / "run")
    (out / "sensitivity_by_subgroup.parquet").unlink()
    sidecar_path = out / "sensitivity_by_subgroup.provenance.yaml"
    sidecar_path.write_text("id: x\n")
    with pytest.raises(FileNotFoundError, match="concat did not emit"):
        esub.plan_subgroup_upload(out, "ESCA", sidecar_path)
