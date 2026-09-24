"""The S4 diagnostic data-package emitter (analysis-methods#697, parent #690).

`emit_data_package` lands the two byproducts `run_indication_batch.sh` never uploaded — the
cell-AG `adj_vs_gtex.parquet` (S2 #695) and the per-run `qc/` bundle (S3b #702) — as the AG
package's OWN catalogued derivation plus a QC sidecar riding in its prefix.

The invariants under test:

* **Verdict-invisibility** (mirrors `test_xenatoil_product_is_verdict_invisible.py`): the AG id
  must never end in the sensitivity discovery suffix, on EITHER substrate, or a diagnostic-only
  normal-vs-normal contrast would leak into the pancan verdict path.
* **Three-way id equality** (the S4 acceptance invariant): emitted sidecar `id` == S3 key
  directory stem == data-catalog manifest `id`. Nothing in `validate_catalog.py` enforces it, so
  the emitter asserts it fail-loud and these tests pin every leg — including the manifest-basename
  leg against the exact strings the data-catalog manifests are authored under.
* **Fail-loud on a degenerate package**: an empty/absent QC bundle, or an AG cell that did not
  run, must STOP the emit rather than land an empty sidecar (the green-on-nothing failure mode).

Hermetic: a synthetic run out-dir stands in for a live compute; no S3, no DESeq2.
"""

from __future__ import annotations

import csv

import pytest
import yaml

from methods.dge_deseq2 import derive_pancan_stack as dps
from methods.dge_deseq2 import emit_data_package as edp

# The exact catalog ids the three data-catalog manifests are authored under (S4). Pinning them
# here closes the manifest leg of three-way id equality from the analysis-methods side: if the
# emitter's id construction drifts from these, the manifests it points at no longer exist.
_MANIFEST_IDS = {
    ("COADREAD", "recount3"): "coadread-dge-adj-vs-gtex-v1",
    ("COADREAD", "xena_toil"): "coadread-dge-adj-vs-gtex-xenatoil-v1",
}
_QC_INDEX_MANIFEST_ID = "dge-deseq2-qc-index-v1"


def _write_run_dir(root, *, substrate="xena_toil", ag_ran=True, cells=("A", "C", "AG"), with_qc=True):
    """Materialize a minimal but structurally-real four-cell run out-dir under `root`."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "adj_vs_gtex.parquet").write_bytes(b"PAR1fake-parquet-bytes")
    prov = {
        "substrate": "xena-toil/tcga-target-gtex-snapshot (GENCODE v23)" if substrate == "xena_toil" else "recount3",
        "tcga_studies": ["COAD", "READ"],
        "gtex_tissue": "Colon",
        "cells_ran": list(cells),
        "n_tumor": 379,
        "n_adjacent": 51,
        "n_gtex": 307,
        "min_normals": 3,
        "adj_vs_gtex": {
            "ran": ag_ran,
            "byproduct": "adj_vs_gtex.parquet",
            "positive_group": "TCGA_adjacent_normal",
            "reference_group": "GTEx_normal",
            "classifier_input": False,
        },
        "deseq2_version": "1.50.2",
        "apeglm_version": "1.32.0",
        "sva_version": "3.58.0",
        "schema_version": "2",
    }
    (root / "provenance.yaml").write_text(yaml.safe_dump(prov, sort_keys=False))
    if with_qc:
        for cell in cells:
            figs = root / "qc" / cell / "figures"
            figs.mkdir(parents=True)
            (figs / "volcano.png").write_bytes(b"\x89PNG-fake")
            (figs / "ma_plot.png").write_bytes(b"\x89PNG-fake")
            with (root / "qc" / cell / "metrics.csv").open("w", newline="") as fh:
                csv.writer(fh).writerow(["cell", cell])
        with (root / "qc" / "qc_summary.csv").open("w", newline="") as fh:
            csv.writer(fh).writerow(["cell", "n_sig"])
    return root


# --------------------------------------------------------------------------- #
# verdict-invisibility (mirror of the S1b guard)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("substrate", ["recount3", "xena_toil"])
def test_ag_id_never_matches_the_discovery_suffix(substrate):
    cid = edp.adj_vs_gtex_catalog_id("COADREAD", substrate)
    assert not cid.endswith(dps._SENSITIVITY_SUFFIX), (
        f"AG id {cid!r} ends in the sensitivity discovery suffix — a diagnostic-only "
        "normal-vs-normal contrast would be picked up as a verdict input"
    )


def test_ag_ids_are_substrate_distinct():
    r = edp.adj_vs_gtex_catalog_id("COADREAD", "recount3")
    x = edp.adj_vs_gtex_catalog_id("COADREAD", "xena_toil")
    assert r == "coadread-dge-adj-vs-gtex-v1"
    assert x == "coadread-dge-adj-vs-gtex-xenatoil-v1"
    assert r != x, "the two substrates must land on distinct AG keys (recount3 bare, xena_toil infixed)"


def test_unknown_substrate_is_rejected():
    with pytest.raises(ValueError, match="unknown substrate"):
        edp.adj_vs_gtex_catalog_id("COADREAD", "microarray")


# --------------------------------------------------------------------------- #
# three-way id equality
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("ind", "substrate"), sorted(_MANIFEST_IDS))
def test_emitter_id_matches_authored_manifest_id(ind, substrate):
    # The manifest leg: the id the emitter builds must equal the exact catalog manifest basename.
    assert edp.adj_vs_gtex_catalog_id(ind, substrate) == _MANIFEST_IDS[(ind, substrate)]


def test_qc_index_id_matches_authored_manifest_id():
    assert edp.qc_index_catalog_id() == _QC_INDEX_MANIFEST_ID


def test_prefix_stem_round_trips():
    cid = edp.adj_vs_gtex_catalog_id("COADREAD", "xena_toil")
    uri = f"{edp.derived_prefix(cid)}/adj_vs_gtex.parquet"
    assert edp.prefix_stem_of(uri) == cid


def test_assert_three_way_passes_when_aligned():
    cid = edp.adj_vs_gtex_catalog_id("COADREAD", "recount3")
    uri = f"{edp.derived_prefix(cid)}/adj_vs_gtex.parquet"
    edp.assert_three_way_id_equality(cid, uri, manifest_id=_MANIFEST_IDS[("COADREAD", "recount3")])


def test_assert_three_way_catches_stem_mismatch():
    # A key placed under the wrong prefix (the orphan-ingest failure mode) must be caught.
    bad = f"{edp.DERIVED_BASE}/some-other-package/adj_vs_gtex.parquet"
    with pytest.raises(AssertionError, match="id/s3 stem mismatch"):
        edp.assert_three_way_id_equality("coadread-dge-adj-vs-gtex-v1", bad)


def test_assert_three_way_catches_manifest_mismatch():
    cid = "coadread-dge-adj-vs-gtex-v1"
    uri = f"{edp.derived_prefix(cid)}/adj_vs_gtex.parquet"
    with pytest.raises(AssertionError, match="id/manifest mismatch"):
        edp.assert_three_way_id_equality(cid, uri, manifest_id="coadread-dge-adj-vs-gtex-xenatoil-v1")


def test_prefix_stem_rejects_non_derived_uri():
    with pytest.raises(ValueError, match="not a derived"):
        edp.prefix_stem_of("s3://onc-compbio/data-catalog/source/foo/bar.parquet")


# --------------------------------------------------------------------------- #
# sidecar construction
# --------------------------------------------------------------------------- #
def test_sidecar_carries_id_and_holds_three_way(tmp_path):
    out = _write_run_dir(tmp_path / "run", substrate="xena_toil")
    sidecar = edp.build_adj_vs_gtex_sidecar(out, "COADREAD", "xena_toil", git_sha="deadbeef")
    assert sidecar["id"] == "coadread-dge-adj-vs-gtex-xenatoil-v1"
    # The sidecar's own id and s3_uri must be mutually consistent (the emit-time anchor).
    edp.assert_three_way_id_equality(sidecar["id"], sidecar["s3_uri"])
    assert sidecar["classifier_input"] is False
    assert sidecar["positive_group"] == "TCGA_adjacent_normal"
    assert sidecar["reference_group"] == "GTEx_normal"
    assert sidecar["generated_by"] == "methods/dge_deseq2@deadbeef"
    # QC inventory: 3 cells x (2 figs + 1 metrics) + qc_summary = 10 files.
    assert sidecar["qc_bundle"]["n_files"] == 10
    assert "qc/qc_summary.csv" in sidecar["qc_bundle"]["files"]


def test_sidecar_fails_loud_when_ag_did_not_run(tmp_path):
    out = _write_run_dir(tmp_path / "run", ag_ran=False)
    with pytest.raises(AssertionError, match="adj_vs_gtex did not run"):
        edp.build_adj_vs_gtex_sidecar(out, "COADREAD", "xena_toil", git_sha="x")


def test_sidecar_fails_loud_on_empty_qc_bundle(tmp_path):
    out = _write_run_dir(tmp_path / "run", with_qc=False)
    with pytest.raises(FileNotFoundError, match="QC bundle dir"):
        edp.build_adj_vs_gtex_sidecar(out, "COADREAD", "xena_toil", git_sha="x")


def test_missing_run_provenance_fails_loud(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "adj_vs_gtex.parquet").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="provenance.yaml missing"):
        edp.build_adj_vs_gtex_sidecar(out, "COADREAD", "xena_toil", git_sha="x")


# --------------------------------------------------------------------------- #
# upload plan
# --------------------------------------------------------------------------- #
def test_upload_plan_covers_parquet_sidecar_and_all_qc(tmp_path):
    out = _write_run_dir(tmp_path / "run", substrate="recount3")
    sidecar = edp.build_adj_vs_gtex_sidecar(out, "COADREAD", "recount3", git_sha="x")
    sidecar_path = edp.write_adj_vs_gtex_sidecar(out, sidecar)
    plan = edp.plan_adj_vs_gtex_upload(out, "COADREAD", "recount3", sidecar_path)

    cid = "coadread-dge-adj-vs-gtex-v1"
    # 1 parquet + 1 sidecar + 10 QC files.
    assert len(plan) == 12
    # Every key lands under the package's OWN prefix — no escape (the three-way anchor).
    uris = {u for _, u in plan}
    for uri in uris:
        assert edp.prefix_stem_of(uri) == cid
    assert f"{edp.derived_prefix(cid)}/adj_vs_gtex.parquet" in uris
    assert f"{edp.derived_prefix(cid)}/provenance.yaml" in uris
    assert f"{edp.derived_prefix(cid)}/qc/qc_summary.csv" in uris
    # The sidecar is uploaded under the canonical provenance.yaml name, not its local filename.
    assert not any(u.endswith("adj_vs_gtex.provenance.yaml") for u in uris)


def test_upload_plan_fails_loud_without_ag_parquet(tmp_path):
    out = _write_run_dir(tmp_path / "run")
    (out / "adj_vs_gtex.parquet").unlink()
    sidecar_path = out / "adj_vs_gtex.provenance.yaml"
    sidecar_path.write_text("id: x\n")
    with pytest.raises(FileNotFoundError, match="AG cell did not emit"):
        edp.plan_adj_vs_gtex_upload(out, "COADREAD", "recount3", sidecar_path)
