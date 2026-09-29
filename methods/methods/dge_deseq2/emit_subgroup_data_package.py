"""dge_deseq2.emit_subgroup_data_package — land the by-subgroup sensitivity data-package to S3.

The by-subgroup analogue of :mod:`emit_data_package` (analysis-methods#738). The multi-axis
orchestrator (:mod:`run_subgroup_dge_batch`) concatenates the per-axis
``sensitivity_by_subgroup.parquet`` shards into one product per indication and aggregates the
per-axis provenance into ``provenance_by_subgroup.yaml``. This module lands that product as its OWN
catalogued derivation:

    <ind>-dge-tumor-vs-normal-sensitivity-by-subgroup-v1

with the per-run QC bundle riding along as a sidecar under the package prefix. The id is deliberately
kept off the pooled sensitivity discovery suffix (``-dge-tumor-vs-normal-sensitivity-v1``) so it can
never be picked up as a pooled-verdict input — it ends in ``-by-subgroup-v1``, asserted fail-loud.

Three-way id equality (the S4 acceptance invariant, reused here): emitted sidecar ``id`` == S3 key
directory stem == data-catalog manifest ``id``. The pure planning surface (ids, sidecar dict, the
file->key upload plan) is unit-tested; the only impure part is :func:`_aws_cp`.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from .derive_pancan_stack import _SENSITIVITY_SUFFIX

# Reuse the AG emitter's prefix / three-way-equality / QC-inventory / upload primitives rather than
# duplicate them — the two packages share the same derived/<id>/ discipline.
from .emit_data_package import (
    _aws_cp,
    _git_sha,
    _md5,
    _relative_qc_files,
    assert_three_way_id_equality,
    derived_prefix,
    prefix_stem_of,
)

_SUBGROUP_PARQUET = "sensitivity_by_subgroup.parquet"
_SUBGROUP_PROVENANCE = "provenance_by_subgroup.yaml"  # what the orchestrator/driver writes
_SIDECAR_NAME = "provenance.yaml"  # uploaded canonical name (same as the sensitivity family)
_SIDECAR_LOCAL = "sensitivity_by_subgroup.provenance.yaml"  # local id-carrying sidecar

_ID_RE = re.compile(r"^[a-z]+-dge-tumor-vs-normal-sensitivity-by-subgroup-v1$")


# --------------------------------------------------------------------------- #
# id + the three-way equality invariant
# --------------------------------------------------------------------------- #
def subgroup_catalog_id(indication: str) -> str:
    """`{ind}-dge-tumor-vs-normal-sensitivity-by-subgroup-v1` — the by-subgroup package's id.

    Fail-loud (mirrors the AG emitter): the id must match the by-subgroup pattern AND must NOT end in
    the pooled sensitivity discovery suffix (``_SENSITIVITY_SUFFIX``) — otherwise a per-subgroup
    diagnostic would leak into the pooled single-gene verdict path. It also must not equal the pooled
    sensitivity id for the same indication.
    """
    cid = f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-by-subgroup-v1"
    if not _ID_RE.match(cid):
        raise AssertionError(f"by-subgroup id {cid!r} does not match {_ID_RE.pattern!r}")
    pooled = f"{indication.lower()}{_SENSITIVITY_SUFFIX}"
    if cid == pooled:
        raise AssertionError(f"by-subgroup id {cid!r} collides with the pooled sensitivity id {pooled!r}")
    if cid.endswith(_SENSITIVITY_SUFFIX):
        raise AssertionError(
            f"by-subgroup id {cid!r} ends in the pooled sensitivity discovery suffix "
            f"{_SENSITIVITY_SUFFIX!r} — a stratified diagnostic would leak into the verdict path"
        )
    return cid


# --------------------------------------------------------------------------- #
# sidecar + upload planning (pure)
# --------------------------------------------------------------------------- #
def _read_subgroup_provenance(out_dir: Path) -> dict:
    p = out_dir / _SUBGROUP_PROVENANCE
    if not p.is_file():
        raise FileNotFoundError(
            f"{_SUBGROUP_PROVENANCE} missing under {out_dir} — did the multi-axis orchestrator run?"
        )
    return yaml.safe_load(p.read_text())


def build_subgroup_sidecar(out_dir: Path, indication: str, git_sha: str) -> dict:
    """Build the id-carrying inline sidecar for the by-subgroup package.

    Transcribes the aggregated cohort / stratification provenance from
    ``provenance_by_subgroup.yaml`` and adds ``id`` + ``s3_uri`` (the three-way anchor) plus an
    inventory of the QC-bundle sidecar files riding along in the prefix.
    """
    catalog_id = subgroup_catalog_id(indication)
    parquet_uri = f"{derived_prefix(catalog_id)}/{_SUBGROUP_PARQUET}"
    assert_three_way_id_equality(catalog_id, parquet_uri)

    prov = _read_subgroup_provenance(out_dir)
    qc_files = _relative_qc_files(out_dir)
    sidecar = {
        "id": catalog_id,
        "s3_uri": parquet_uri,
        "type": "derived",
        "role": "stratified-diagnostic",
        "classifier_input": False,
        "indication": indication.upper(),
        "substrate": prov.get("substrate"),
        "tcga_studies": prov.get("tcga_studies"),
        "gtex_tissue": prov.get("gtex_tissue"),
        "subgroup_axes": prov.get("subgroup_axes"),
        "strata_emitted": prov.get("strata_emitted"),
        "n_tumor_by_stratum": prov.get("n_tumor_by_stratum"),
        "n_adjacent": prov.get("n_adjacent"),
        "n_gtex": prov.get("n_gtex"),
        "cells_ran": prov.get("cells_ran"),
        "min_subgroup_tumor": prov.get("min_subgroup_tumor"),
        "deseq2_version": prov.get("deseq2_version"),
        "apeglm_version": prov.get("apeglm_version"),
        "sva_version": prov.get("sva_version"),
        "qc_bundle": {
            "prefix": "qc/",
            "n_files": len(qc_files),
            "files": [str(f) for f in qc_files],
        },
        "generated_by": f"methods/dge_deseq2@{git_sha}",
        "schema_version": "1",
    }
    return sidecar


def write_subgroup_sidecar(out_dir: Path, sidecar: dict) -> Path:
    """Write the by-subgroup sidecar next to the run outputs (uploaded as provenance.yaml)."""
    p = out_dir / _SIDECAR_LOCAL
    p.write_text(yaml.safe_dump(sidecar, sort_keys=False))
    return p


def plan_subgroup_upload(out_dir: Path, indication: str, sidecar_path: Path) -> list[tuple[Path, str]]:
    """Return the ordered [(local_path, s3_uri)] plan for the by-subgroup package.

    Uploads: the concatenated by-subgroup parquet (primary), the id-carrying sidecar (as
    ``provenance.yaml``), and the whole merged QC bundle under ``qc/``. Every planned key is asserted
    to land under the package's own prefix — the three-way anchor.
    """
    catalog_id = subgroup_catalog_id(indication)
    prefix = derived_prefix(catalog_id)

    parquet = out_dir / _SUBGROUP_PARQUET
    if not parquet.is_file():
        raise FileNotFoundError(f"{parquet} missing — the multi-axis concat did not emit a parquet")

    plan: list[tuple[Path, str]] = [
        (parquet, f"{prefix}/{_SUBGROUP_PARQUET}"),
        (sidecar_path, f"{prefix}/{_SIDECAR_NAME}"),
    ]
    for rel in _relative_qc_files(out_dir):
        plan.append((out_dir / rel, f"{prefix}/{rel.as_posix()}"))
    for _, uri in plan:
        if prefix_stem_of(uri) != catalog_id:
            raise AssertionError(f"planned key {uri!r} escapes the {catalog_id!r} prefix")
    return plan


# --------------------------------------------------------------------------- #
# impure: the actual upload
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Land the by-subgroup sensitivity data-package (+ QC sidecar) for a completed run."
    )
    ap.add_argument("--out-dir", type=Path, required=True, help="Completed multi-axis run out-dir.")
    ap.add_argument("--indication", required=True)
    ap.add_argument("--git-sha", default=None, help="Provenance git sha (default: HEAD of this repo).")
    ap.add_argument("--no-upload", action="store_true", help="Plan + write the sidecar only; skip S3 writes.")
    args = ap.parse_args(argv)

    git_sha = args.git_sha or _git_sha(Path(__file__).resolve().parents[2])
    sidecar = build_subgroup_sidecar(args.out_dir, args.indication, git_sha)
    sidecar_path = write_subgroup_sidecar(args.out_dir, sidecar)
    plan = plan_subgroup_upload(args.out_dir, args.indication, sidecar_path)

    print(
        f"[emit_subgroup_data_package] id={sidecar['id']} — {len(plan)} object(s) to {derived_prefix(sidecar['id'])}/"
    )
    if args.no_upload:
        for local, uri in plan:
            print(f"  (plan) {local}  ->  {uri}")
        return 0
    for local, uri in plan:
        _aws_cp(local, uri)
    print(
        f"[emit_subgroup_data_package] uploaded {len(plan)} object(s); "
        f"parquet md5={_md5(args.out_dir / _SUBGROUP_PARQUET)}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
