#!/usr/bin/env python3
"""LIVE capture tool for the batch-F T3 recomputation anchors (#2088):

  1. cellline-protein-abundance-procan  -- onc_methods.procan_protein_abundance.cli.load_and_classify
  2. cellline-rna-distribution-by-subtype -- onc_methods.depmap_expression_distribution.read.build_expression_subtype_panorama
  3. tumor-protein-distribution-by-subtype -- onc_methods.cptac_protein_distribution.read.build_protein_subtype_panorama
  4. tumor-rna-distribution-by-subtype -- onc_methods.tcga_gtex_expression_distribution.cli.build_subtype_panorama

Clone of the batch A-E capture_*_anchor.py tools (see capture_protein_abundance_anchor.py /
capture_sc_normal_celltype_anchor.py for the pattern this follows). Each `capture_*` function:
  (a) runs the REAL reader LIVE (cbg creds) to get the summary,
  (b) freezes the raw INPUT the reader's S3-load seam(s) returned into a committed fixture,
  (c) re-derives OFFLINE by monkeypatching ONLY the seam(s) with the frozen fixture and re-running
      the SAME real reader, and ABORTS (raises) if the offline re-derivation does not reproduce the
      live summary byte-exact -- so a committed anchor is guaranteed reproducible before it lands.

This tool hits S3 (+ requires the target-contracts sibling checkout for the tumor-RNA control-position
enrichment) and is NOT run in CI. Run it with live creds:

    cd <analysis-methods repo>/methods
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        python tests/calibration/recomputation/capture_subtype_panorama_anchor.py --all

or select specific cards:

    ... capture_subtype_panorama_anchor.py --procan MSLN EPCAM --cellline-rna KRAS/COADREAD EPCAM/COADREAD

Writes into tests/calibration/recomputation/{procan_vectors,subtype_panorama_vectors,anchors}/.
Commit the outputs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROCAN_VECTORS = HERE / "procan_vectors"
PANORAMA_VECTORS = HERE / "subtype_panorama_vectors"
ANCHORS = HERE / "anchors"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324


def _json_default(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, allow_nan=False, default=str) + "\n")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# =====================================================================================
# 1) cellline-protein-abundance-procan
# =====================================================================================

NULL_FIXTURE_NAME = "procan_allprotein_median_null.parquet"


def _procan_write_null_fixture(all_protein_medians: tuple) -> str:
    import pyarrow as pa
    import pyarrow.parquet as pq

    PROCAN_VECTORS.mkdir(parents=True, exist_ok=True)
    path = PROCAN_VECTORS / NULL_FIXTURE_NAME
    n = len(all_protein_medians)
    pq.write_table(
        pa.table(
            {
                "uniprot_base": pa.array([f"SYNTH_PROTEIN_{i:05d}" for i in range(n)], type=pa.string()),
                "log_abundance": pa.array([float(v) for v in all_protein_medians], type=pa.float64()),
            }
        ),
        path,
    )
    return NULL_FIXTURE_NAME


def capture_procan(target: str) -> None:
    import pyarrow.parquet as pq

    from onc_methods.procan_protein_abundance import cli as pcli

    accs = pcli.resolve_accessions(target)
    if not accs:
        raise SystemExit(f"{target}: not resolvable to a ProCan/UniProt accession")

    live = pcli.load_and_classify(target)
    if live.get("protein_expression_class") == "data_unavailable":
        raise SystemExit(f"{target}: load_and_classify returned data_unavailable live")

    # Freeze the target's rows (the accession that actually resolved a live column).
    bucket, key = pcli._derived_bucket_key()  # noqa: SLF001
    chosen_acc = None
    for acc in accs:
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=pcli._get_s3fs(), filters=[("uniprot_base", "=", acc)])  # noqa: SLF001
        if tbl.num_rows:
            chosen_acc = acc
            break
    if chosen_acc is None:
        raise SystemExit(f"{target}: no accession in {accs} resolved to live rows")

    PROCAN_VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    rows_name = f"{target.lower()}.procan_rows.parquet"
    pq.write_table(tbl, PROCAN_VECTORS / rows_name)

    # Freeze the shared, target-independent all-protein median null ONCE.
    null_vec = pcli._allprotein_median_null()  # noqa: SLF001 -- capture tool, live path
    null_name = (
        _procan_write_null_fixture(null_vec) if not (PROCAN_VECTORS / NULL_FIXTURE_NAME).exists() else NULL_FIXTURE_NAME
    )

    # GUARD (fidelity): offline re-derivation from the frozen rows+null must reproduce live exactly.
    off = pcli.load_and_classify(
        target, product_path=str(PROCAN_VECTORS / rows_name), null_path=str(PROCAN_VECTORS / null_name)
    )
    for f in _PROCAN_FIELDS:
        if off.get(f) != live.get(f):
            raise SystemExit(
                f"ABORT [{target}]: offline procan re-derivation != live on {f!r}: {off.get(f)!r} != {live.get(f)!r}"
            )

    anchor = {
        "target": target.upper(),
        "accession": chosen_acc,
        "skill": "tumor-presence",
        "card_id": "cellline-protein-abundance-procan",
        "class_field": "protein_expression_class",
        "rows_fixture": f"procan_vectors/{rows_name}",
        "null_fixture": f"procan_vectors/{null_name}",
        "rows_md5": _md5(PROCAN_VECTORS / rows_name),
        "null_md5": _md5(PROCAN_VECTORS / null_name),
        "expected": {k: off.get(k) for k in _PROCAN_FIELDS},
        "_captured_at": _now(),
        "_provenance": (
            f"live cbg pushdown read of procan-cellline-protein-abundance-per-protein-v1 "
            f"(uniprot_base=={chosen_acc!r}); fixture = the accession's per-model log_abundance rows "
            "+ the panel-wide all-protein median null (1 synthetic row per protein, at its own "
            "median); re-derive with onc_methods.procan_protein_abundance.cli.load_and_classify"
            "(product_path=, null_path=)."
        ),
    }
    anchor_name = f"{target.lower()}.procan_protein_abundance.json"
    _write_json(ANCHORS / anchor_name, anchor)
    print(f"wrote anchors/{anchor_name} + procan_vectors/{rows_name}")
    print(f"  {target:8} acc={chosen_acc} class={off['protein_expression_class']} n={off['n_cell_lines_evaluated']}")


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


# =====================================================================================
# 2) cellline-rna-distribution-by-subtype
# =====================================================================================

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


def _assignments_to_records(df) -> list:
    cols = [
        "sample_id",
        "patient_id",
        "source_native_id",
        "stratum_id",
        "is_member",
        "derivation_source",
        "derivation_value",
        "evaluated_at_release",
    ]
    cols = [c for c in cols if c in df.columns]
    return df[cols].to_dict("records")


def _write_assignments_fixture(df, path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    PANORAMA_VECTORS.mkdir(parents=True, exist_ok=True)
    cols = [
        "sample_id",
        "patient_id",
        "source_native_id",
        "stratum_id",
        "is_member",
        "derivation_source",
        "derivation_value",
        "evaluated_at_release",
    ]
    cols = [c for c in cols if c in df.columns]
    # is_member is object-dtype tri-value (True/False/None) in the live shard -- preserve as-is.
    table = pa.Table.from_pandas(df[cols].reset_index(drop=True), preserve_index=False)
    pq.write_table(table, path)


def capture_cellline_rna(target: str, indication: str) -> None:
    from onc_methods.depmap_expression_distribution import read as rd
    from onc_methods.subgroup_common import scoping

    manifest = f"depmap-subgroup-assignments-{indication.lower()}-v1"
    assignments = scoping.load_assignments(manifest)
    strata = sorted(assignments["stratum_id"].unique().tolist())

    live = rd.build_expression_subtype_panorama(target, indication, strata, manifest)
    if not live.get("subtype_axis_available"):
        raise SystemExit(f"{target}/{indication}: cellline-rna subtype axis unavailable live")

    tpm_by_model, is_absent = rd._cached_tpm(target, "26q3")  # noqa: SLF001
    if is_absent or not tpm_by_model:
        raise SystemExit(f"{target}/{indication}: no DepMap 26q3 expression for {target}")

    PANORAMA_VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    tpm_name = f"{target.lower()}.depmap_tpm_26q3.json"
    (PANORAMA_VECTORS / tpm_name).write_text(json.dumps(tpm_by_model, indent=0, sort_keys=True) + "\n")

    assign_name = f"{indication.lower()}.depmap_subgroup_assignments.parquet"
    assign_path = PANORAMA_VECTORS / assign_name
    if not assign_path.exists():
        _write_assignments_fixture(assignments, assign_path)

    off = _rederive_cellline_rna(target, indication, strata, manifest, tpm_by_model, assignments)
    for f in _CELLLINE_RNA_FIELDS:
        if f == "per_subgroup_metrics":
            if off.get(f) != live.get(f):
                raise SystemExit(f"ABORT [{target}-{indication}]: cellline-rna per_subgroup_metrics diverges offline")
            continue
        if off.get(f) != live.get(f):
            raise SystemExit(
                f"ABORT [{target}-{indication}]: cellline-rna offline != live on {f!r}: "
                f"{off.get(f)!r} != {live.get(f)!r}"
            )

    anchor = {
        "target": target.upper(),
        "indication": indication.upper(),
        "skill": "tumor-presence",
        "card_id": "cellline-rna-distribution-by-subtype",
        "manifest": manifest,
        "strata": strata,
        "release_pin": "26q3",
        "tpm_fixture": f"subtype_panorama_vectors/{tpm_name}",
        "assignments_fixture": f"subtype_panorama_vectors/{assign_name}",
        "tpm_md5": _md5(PANORAMA_VECTORS / tpm_name),
        "assignments_md5": _md5(assign_path),
        "expected": {k: off.get(k) for k in _CELLLINE_RNA_FIELDS},
        "_captured_at": _now(),
        "_provenance": (
            f"live cbg read via depmap_expression_distribution.read.build_expression_subtype_panorama"
            f"({target!r}, {indication!r}, strata={strata}, manifest={manifest!r}); fixtures = the "
            "target's per-ModelID log2(TPM+1) dict (_cached_tpm seam) + the DepMap subgroup-"
            "assignments shard (subgroup_common.scoping.load_assignments seam); re-derive by "
            "monkeypatching rd._cached_tpm and scoping.load_assignments."
        ),
    }
    anchor_name = f"{target.lower()}_{indication.lower()}.cellline_rna_subtype.json"
    _write_json(ANCHORS / anchor_name, anchor)
    print(f"wrote anchors/{anchor_name} + subtype_panorama_vectors/{tpm_name}")
    print(
        f"  {target:8} {indication:8} strat_class={off['subtype_stratification_class']} "
        f"n_measured={off['n_subtypes_measured']} n_strata={len(strata)}"
    )


def _rederive_cellline_rna(target, indication, strata, manifest, tpm_by_model, assignments_df) -> dict:
    from onc_methods.depmap_expression_distribution import read as rd
    from onc_methods.subgroup_common import scoping

    def _fake_cached_tpm(t, release_pin):
        return dict(tpm_by_model), False

    def _fake_load_assignments(manifest_id, data_catalog_repo=None):
        return assignments_df.copy()

    with (
        mock.patch.object(rd, "_cached_tpm", _fake_cached_tpm),
        mock.patch.object(scoping, "load_assignments", _fake_load_assignments),
    ):
        return rd.build_expression_subtype_panorama(target, indication, strata, manifest)


# =====================================================================================
# 3) tumor-protein-distribution-by-subtype
# =====================================================================================

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


def capture_cptac_protein(target: str, indication: str) -> None:
    from onc_methods.cptac_protein_deg import read as deg_read
    from onc_methods.cptac_protein_distribution import read as rd
    from onc_methods.subgroup_common import scoping

    manifest = rd.INDICATION_TO_CPTAC_ASSIGNMENT_MANIFEST.get(indication.upper().strip())
    if manifest is None:
        raise SystemExit(f"{indication}: no landed CPTAC subgroup-assignment manifest")
    assignments = scoping.load_assignments(manifest)
    strata = sorted(assignments["stratum_id"].unique().tolist())

    live = rd.build_protein_subtype_panorama(target, indication, strata, manifest)
    if not live.get("subtype_axis_available"):
        raise SystemExit(f"{target}/{indication}: cptac-protein subtype axis unavailable live")

    per_sample = deg_read.read_per_sample(target)
    if per_sample is None or per_sample.empty:
        raise SystemExit(f"{target}: no CPTAC per-sample rows for {target}")

    PANORAMA_VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    sample_name = f"{target.lower()}.cptac_per_sample.parquet"
    pq.write_table(
        pa.Table.from_pandas(per_sample.reset_index(drop=True), preserve_index=False), PANORAMA_VECTORS / sample_name
    )

    assign_name = f"{indication.lower()}.cptac_subgroup_assignments.parquet"
    assign_path = PANORAMA_VECTORS / assign_name
    if not assign_path.exists():
        _write_assignments_fixture(assignments, assign_path)

    off = _rederive_cptac_protein(target, indication, strata, manifest, per_sample, assignments)
    for f in _CPTAC_PROTEIN_FIELDS:
        if off.get(f) != live.get(f):
            raise SystemExit(
                f"ABORT [{target}-{indication}]: cptac-protein offline != live on {f!r}: "
                f"{off.get(f)!r} != {live.get(f)!r}"
            )

    anchor = {
        "target": target.upper(),
        "indication": indication.upper(),
        "skill": "tumor-presence",
        "card_id": "tumor-protein-distribution-by-subtype",
        "manifest": manifest,
        "strata": strata,
        "sample_fixture": f"subtype_panorama_vectors/{sample_name}",
        "assignments_fixture": f"subtype_panorama_vectors/{assign_name}",
        "sample_md5": _md5(PANORAMA_VECTORS / sample_name),
        "assignments_md5": _md5(assign_path),
        "expected": {k: off.get(k) for k in _CPTAC_PROTEIN_FIELDS},
        "_captured_at": _now(),
        "_provenance": (
            f"live cbg read via cptac_protein_distribution.read.build_protein_subtype_panorama"
            f"({target!r}, {indication!r}, strata={strata}, manifest={manifest!r}); fixtures = "
            "cptac_protein_deg.read.read_per_sample(target)'s per-aliquot rows + the CPTAC "
            "subgroup-assignments shard; re-derive by monkeypatching deg_read.read_per_sample and "
            "subgroup_common.scoping.load_assignments."
        ),
    }
    anchor_name = f"{target.lower()}_{indication.lower()}.tumor_protein_subtype.json"
    _write_json(ANCHORS / anchor_name, anchor)
    print(f"wrote anchors/{anchor_name} + subtype_panorama_vectors/{sample_name}")
    print(
        f"  {target:8} {indication:8} strat_class={off['subtype_stratification_class']} "
        f"n_measured={off['n_subtypes_measured']} n_strata={len(strata)}"
    )


def _rederive_cptac_protein(target, indication, strata, manifest, per_sample_df, assignments_df) -> dict:
    from onc_methods.cptac_protein_deg import read as deg_read
    from onc_methods.cptac_protein_distribution import read as rd
    from onc_methods.subgroup_common import scoping

    def _fake_read_per_sample(t):
        return per_sample_df.copy()

    def _fake_load_assignments(manifest_id, data_catalog_repo=None):
        return assignments_df.copy()

    with (
        mock.patch.object(deg_read, "read_per_sample", _fake_read_per_sample),
        mock.patch.object(scoping, "load_assignments", _fake_load_assignments),
    ):
        return rd.build_protein_subtype_panorama(target, indication, strata, manifest)


# =====================================================================================
# 4) tumor-rna-distribution-by-subtype  (heaviest)
# =====================================================================================

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


def capture_tumor_rna(target: str, indication: str) -> None:
    from onc_methods.tcga_gtex_expression_distribution import cli as tcli
    from onc_methods.tcga_gtex_expression_distribution import read as rd

    manifest_check = rd.INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST.get(indication.upper().strip())
    if manifest_check is None:
        raise SystemExit(f"{indication}: no landed tumor RNA subgroup-assignment manifest")

    live = tcli.build_subtype_panorama(target, indication)
    if not live.get("subtype_axis_available"):
        raise SystemExit(f"{target}/{indication}: tumor-rna subtype axis unavailable live")

    which_tcga, studies = rd._tumor_source(indication)  # noqa: SLF001
    tcga_df = rd._read_gene(which_tcga, target)  # noqa: SLF001
    gtex_df = rd._read_gene("gtex", target)  # noqa: SLF001
    sidecar_df = rd._load_sidecar()  # noqa: SLF001
    assignments_df, base_manifest = rd._load_subtype_assignments(indication)  # noqa: SLF001
    allgene_pct = rd._tumor_allgene_percentile(target, studies)  # noqa: SLF001

    from onc_methods.expression_purity_confound.read import _load_purity_by_case as load_purity

    purity_by_case = load_purity()

    PANORAMA_VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    tcga_name = f"{target.lower()}.tcga_long_{which_tcga}.parquet"
    pq.write_table(
        pa.Table.from_pandas(tcga_df.reset_index(drop=True), preserve_index=False), PANORAMA_VECTORS / tcga_name
    )
    gtex_name = f"{target.lower()}.gtex_long.parquet"
    pq.write_table(
        pa.Table.from_pandas(gtex_df.reset_index(drop=True), preserve_index=False), PANORAMA_VECTORS / gtex_name
    )

    sidecar_name = "tcga_uuid_barcode_sidecar.parquet"
    sidecar_path = PANORAMA_VECTORS / sidecar_name
    if not sidecar_path.exists():
        pq.write_table(
            pa.Table.from_pandas(
                sidecar_df[["sample_id", "submitter_id"]].reset_index(drop=True), preserve_index=False
            ),
            sidecar_path,
        )

    assign_name = f"{indication.lower()}.tcga_subtype_assignments_union.parquet"
    assign_path = PANORAMA_VECTORS / assign_name
    if not assign_path.exists():
        _write_assignments_fixture(assignments_df, assign_path)

    purity_name = "pancanatlas_purity_by_case.json"
    purity_path = PANORAMA_VECTORS / purity_name
    if not purity_path.exists():
        purity_path.write_text(json.dumps(purity_by_case, indent=0, sort_keys=True) + "\n")

    allgene_name = f"{target.lower()}_{indication.lower()}.tumor_allgene_percentile.json"
    (PANORAMA_VECTORS / allgene_name).write_text(json.dumps(allgene_pct, indent=2, sort_keys=True, default=str) + "\n")

    off = _rederive_tumor_rna(
        target, indication, tcga_df, gtex_df, sidecar_df, assignments_df, base_manifest, allgene_pct, purity_by_case
    )
    for f in _TUMOR_RNA_FIELDS:
        if off.get(f) != live.get(f):
            raise SystemExit(
                f"ABORT [{target}-{indication}]: tumor-rna offline != live on {f!r}: {off.get(f)!r} != {live.get(f)!r}"
            )

    anchor = {
        "target": target.upper(),
        "indication": indication.upper(),
        "skill": "tumor-presence",
        "card_id": "tumor-rna-distribution-by-subtype",
        "which_tcga": which_tcga,
        "tcga_fixture": f"subtype_panorama_vectors/{tcga_name}",
        "gtex_fixture": f"subtype_panorama_vectors/{gtex_name}",
        "sidecar_fixture": f"subtype_panorama_vectors/{sidecar_name}",
        "assignments_fixture": f"subtype_panorama_vectors/{assign_name}",
        "purity_fixture": f"subtype_panorama_vectors/{purity_name}",
        "allgene_percentile_fixture": f"subtype_panorama_vectors/{allgene_name}",
        "base_manifest": base_manifest,
        "tcga_md5": _md5(PANORAMA_VECTORS / tcga_name),
        "gtex_md5": _md5(PANORAMA_VECTORS / gtex_name),
        "sidecar_md5": _md5(sidecar_path),
        "assignments_md5": _md5(assign_path),
        "purity_md5": _md5(purity_path),
        "expected": {k: off.get(k) for k in _TUMOR_RNA_FIELDS},
        "_captured_at": _now(),
        "_provenance": (
            f"live cbg read via tcga_gtex_expression_distribution.cli.build_subtype_panorama"
            f"({target!r}, {indication!r}); fixtures = the tcga+gtex long-product per-gene slices "
            "(_read_gene seam), the UUID->barcode sidecar (_load_sidecar), the UNIONED tumor "
            "subgroup-assignment shard (_load_subtype_assignments, mocked directly), the "
            "PanCanAtlas tumor-purity-by-case dict (expression_purity_confound.read."
            "_load_purity_by_case), and the allgene-tumor-rank percentile lookup "
            "(_tumor_allgene_percentile, mocked directly since it hits a separate S3 precompute "
            "product out of this card's own scope). control_position_tumor (target-contracts "
            "sibling-repo local read, no S3) is left LIVE -- it is deterministic given the "
            "checked-out sibling repo and requires no network."
        ),
    }
    anchor_name = f"{target.lower()}_{indication.lower()}.tumor_rna_subtype.json"
    _write_json(ANCHORS / anchor_name, anchor)
    print(f"wrote anchors/{anchor_name} + subtype_panorama_vectors/{tcga_name}")
    print(
        f"  {target:8} {indication:8} strat_class={off['subtype_stratification_class']} "
        f"n_measured={off['n_subtypes_measured']} axis_quality={off['subtype_axis_quality']}"
    )


def _rederive_tumor_rna(
    target, indication, tcga_df, gtex_df, sidecar_df, assignments_df, base_manifest, allgene_pct, purity_by_case
) -> dict:
    from onc_methods.tcga_gtex_expression_distribution import cli as tcli
    from onc_methods.tcga_gtex_expression_distribution import read as rd

    which_tcga, _ = rd._tumor_source(indication)  # noqa: SLF001

    def _fake_read_gene(which, t):
        if which == "gtex":
            return gtex_df.copy()
        return tcga_df.copy()

    def _fake_load_sidecar():

        df = sidecar_df[["sample_id", "submitter_id"]].copy()
        df["case"] = df["submitter_id"].map(rd._tcga_case)  # noqa: SLF001
        return df

    def _fake_load_subtype_assignments(ind):
        return assignments_df.copy(), base_manifest

    def _fake_allgene_percentile(t, studies):
        return dict(allgene_pct)

    def _fake_load_purity():
        return dict(purity_by_case)

    from onc_methods.expression_purity_confound import read as purity_read
    from onc_methods.subgroup_common import scoping

    def _fake_load_assignments(manifest_id, data_catalog_repo=None):
        # The landscape reader's per-stratum join-coverage guard (scoping.compute_join_coverage)
        # re-loads the assignment shard a SECOND time, independently of _load_subtype_assignments.
        # It only reads per-stratum member sample_ids for the molecular strata (identical between the
        # base shard and the maf-unioned frame the landscape iterates), so feeding the frozen union
        # reproduces every match_rate exactly while keeping the re-derivation network-free.
        return assignments_df.copy()

    with (
        mock.patch.object(rd, "_read_gene", _fake_read_gene),
        mock.patch.object(rd, "_load_sidecar", _fake_load_sidecar),
        mock.patch.object(rd, "_load_subtype_assignments", _fake_load_subtype_assignments),
        mock.patch.object(rd, "_tumor_allgene_percentile", _fake_allgene_percentile),
        mock.patch.object(purity_read, "_load_purity_by_case", _fake_load_purity),
        mock.patch.object(scoping, "load_assignments", _fake_load_assignments),
    ):
        return tcli.build_subtype_panorama(target, indication)


# =====================================================================================
# CLI
# =====================================================================================


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--procan", nargs="*", default=[], metavar="TARGET", help="cellline-protein-abundance-procan targets"
    )
    ap.add_argument("--cellline-rna", nargs="*", default=[], metavar="TARGET/INDICATION")
    ap.add_argument("--cptac-protein", nargs="*", default=[], metavar="TARGET/INDICATION")
    ap.add_argument("--tumor-rna", nargs="*", default=[], metavar="TARGET/INDICATION")
    ap.add_argument(
        "--all",
        action="store_true",
        help="capture the standard batch-F roster: procan EPCAM+MSLN, the 3 subtype arms EPCAM/COADREAD + KRAS/COADREAD",
    )
    args = ap.parse_args(argv)

    if args.all:
        args.procan = ["EPCAM", "MSLN"]
        args.cellline_rna = ["EPCAM/COADREAD", "KRAS/COADREAD"]
        args.cptac_protein = ["EPCAM/COADREAD", "KRAS/COADREAD"]
        args.tumor_rna = ["EPCAM/COADREAD", "KRAS/COADREAD"]

    failures = []
    for t in args.procan:
        try:
            capture_procan(t)
        except SystemExit as e:
            print(f"SKIP procan {t}: {e}", file=sys.stderr)
            failures.append(("procan", t))
    for pair in args.cellline_rna:
        try:
            t, ind = pair.split("/", 1)
            capture_cellline_rna(t, ind)
        except SystemExit as e:
            print(f"SKIP cellline-rna {pair}: {e}", file=sys.stderr)
            failures.append(("cellline-rna", pair))
    for pair in args.cptac_protein:
        try:
            t, ind = pair.split("/", 1)
            capture_cptac_protein(t, ind)
        except SystemExit as e:
            print(f"SKIP cptac-protein {pair}: {e}", file=sys.stderr)
            failures.append(("cptac-protein", pair))
    for pair in args.tumor_rna:
        try:
            t, ind = pair.split("/", 1)
            capture_tumor_rna(t, ind)
        except SystemExit as e:
            print(f"SKIP tumor-rna {pair}: {e}", file=sys.stderr)
            failures.append(("tumor-rna", pair))

    if failures:
        print(f"\n{len(failures)} capture(s) skipped: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
