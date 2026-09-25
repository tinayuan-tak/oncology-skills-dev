"""dge_deseq2.emit_data_package — land the diagnostic DGE data-packages to S3.

S4 (github analysis-methods#697, parent #690). The four-cell driver
(``r/live/06_four_cell_driver.R``) already writes, into a run's out-dir, the
diagnostic products the classifier never reads:

    <out-dir>/adj_vs_gtex.parquet        # cell AG (S2 #695): normal-vs-normal QC
    <out-dir>/qc/<cell>/figures/*.png    # S3b #702 per-run QC bundle
    <out-dir>/qc/<cell>/metrics.csv
    <out-dir>/qc/qc_summary.csv

but ``scripts/run_indication_batch.sh`` only ever uploaded the sensitivity
product + its two byproducts + ``provenance.yaml`` to the *sensitivity* S3
prefix — so ``adj_vs_gtex.parquet`` and the whole ``qc/`` bundle were never
landed (the S2/S3b gap this module closes).

This module emits the AG *data-package* as its OWN catalogued derivation, with
an id deliberately kept off the pancan discovery suffix so it can never be
picked up as a verdict input (mirrors the ``-xenatoil`` secondary-substrate
discipline of S1b). The per-run QC bundle rides along as a **sidecar** under the
AG prefix (no id of its own); the cross-indication ``qc_index.parquet`` is its
own package. It NEVER touches the sensitivity manifests (the recount3
sensitivity product is a verdict input and a pre-S-fix orphan — out of scope).

Three-way id equality (the S4 acceptance invariant): for every package,

    emitted sidecar ``id``  ==  S3 key directory stem  ==  data-catalog manifest ``id``

Nothing in data-catalog's ``validate_catalog.py`` enforces this, so it is
asserted here, fail-loud, at emit time (:func:`assert_three_way_id_equality`),
and pinned by ``tests/test_emit_data_package.py`` against the landed manifests.

Design: the planning surface (ids, sidecar dict, the file→key upload plan) is
pure and unit-tested; the only impure part is :func:`_aws_cp`, a thin
``aws s3 cp`` wrapper exercised only on a real live-S3 landing.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

import yaml

from .config import substrates as _substrates_config
from .derive_pancan_stack import _SENSITIVITY_SUFFIX

S3_BUCKET = "onc-compbio"
DERIVED_BASE = f"s3://{S3_BUCKET}/data-catalog/derived"

# recount3 is the classifier substrate (bare id); xena_toil is the S1b
# secondary/diagnostic substrate and carries a -xenatoil infix so its packages
# land on distinct S3 keys / catalog ids (analysis-methods#694). Projected from
# config/substrates.yaml (analysis-methods#733) rather than hard-coded here.
_SUBSTRATE_INFIX = {name: attrs["s3_key_infix"] for name, attrs in _substrates_config().items()}

_ADJ_VS_GTEX_PARQUET = "adj_vs_gtex.parquet"
_SIDECAR_NAME = "provenance.yaml"  # same filename as the sensitivity family's inline sidecar
_QC_INDEX_PARQUET = "qc_index.parquet"


# --------------------------------------------------------------------------- #
# ids + the three-way equality invariant
# --------------------------------------------------------------------------- #
def adj_vs_gtex_catalog_id(indication: str, substrate: str) -> str:
    """`{ind}-dge-adj-vs-gtex[-xenatoil]-v1` — the AG package's catalog id.

    Deliberately does NOT end in ``_SENSITIVITY_SUFFIX`` so the pancan discovery
    glob / roster check / single-gene verdict reader can never pick it up
    (asserted below).
    """
    try:
        infix = _SUBSTRATE_INFIX[substrate]
    except KeyError:
        raise ValueError(f"unknown substrate {substrate!r} (expected one of {sorted(_SUBSTRATE_INFIX)})")
    cid = f"{indication.lower()}-dge-adj-vs-gtex{infix}-v1"
    if cid.endswith(_SENSITIVITY_SUFFIX):
        # Would make a diagnostic-only package visible to the verdict path.
        raise AssertionError(f"AG id {cid!r} collides with the sensitivity discovery suffix {_SENSITIVITY_SUFFIX!r}")
    return cid


def qc_index_catalog_id() -> str:
    """`dge-deseq2-qc-index-v1` — the cross-indication QC index package id."""
    return "dge-deseq2-qc-index-v1"


def derived_prefix(catalog_id: str) -> str:
    """S3 prefix (no trailing slash) for a derived package's own directory."""
    return f"{DERIVED_BASE}/{catalog_id}"


def prefix_stem_of(s3_uri: str) -> str:
    """The `<id>` directory stem of a `.../derived/<id>/<file>` S3 uri."""
    marker = "/data-catalog/derived/"
    if marker not in s3_uri:
        raise ValueError(f"not a derived s3_uri: {s3_uri!r}")
    return s3_uri.split(marker, 1)[1].split("/", 1)[0]


def assert_three_way_id_equality(catalog_id: str, s3_uri: str, manifest_id: str | None = None) -> None:
    """Fail-loud unless catalog_id == s3_uri directory stem [== manifest_id].

    ``manifest_id`` is optional at emit time (the manifest is authored in the
    data-catalog repo afterward); the test passes it to close the third leg.
    """
    stem = prefix_stem_of(s3_uri)
    if stem != catalog_id:
        raise AssertionError(f"id/s3 stem mismatch: catalog_id={catalog_id!r} but s3 stem={stem!r} ({s3_uri!r})")
    if manifest_id is not None and manifest_id != catalog_id:
        raise AssertionError(f"id/manifest mismatch: catalog_id={catalog_id!r} but manifest id={manifest_id!r}")


# --------------------------------------------------------------------------- #
# sidecar + upload planning (pure)
# --------------------------------------------------------------------------- #
def _read_run_provenance(out_dir: Path) -> dict:
    p = out_dir / "provenance.yaml"
    if not p.is_file():
        raise FileNotFoundError(f"run provenance.yaml missing under {out_dir} — did the four-cell driver run?")
    return yaml.safe_load(p.read_text())


def _relative_qc_files(out_dir: Path) -> list[Path]:
    """Every file in the per-run QC bundle, relative to out_dir, sorted.

    Fail-loud on an absent/empty bundle: an empty QC sidecar is exactly the
    green-on-nothing failure the S3b R emitter already guards against.
    """
    qc_root = out_dir / "qc"
    if not qc_root.is_dir():
        raise FileNotFoundError(f"QC bundle dir {qc_root} missing — expected S3b qc/ under the run out-dir")
    files = sorted(p.relative_to(out_dir) for p in qc_root.rglob("*") if p.is_file())
    if not files:
        raise AssertionError(f"QC bundle under {qc_root} is empty — refusing to land an empty sidecar")
    if not (qc_root / "qc_summary.csv").is_file():
        raise AssertionError(f"QC bundle under {qc_root} has no qc_summary.csv")
    return files


def build_adj_vs_gtex_sidecar(out_dir: Path, indication: str, substrate: str, git_sha: str) -> dict:
    """Build the id-carrying inline sidecar for the AG package.

    Transcribes the run's cohort + AG sign-convention from the driver's
    ``provenance.yaml`` and adds ``id`` + ``s3_uri`` (the three-way anchor) and
    an inventory of the QC-bundle sidecar files riding along in the prefix.
    """
    catalog_id = adj_vs_gtex_catalog_id(indication, substrate)
    parquet_uri = f"{derived_prefix(catalog_id)}/{_ADJ_VS_GTEX_PARQUET}"
    assert_three_way_id_equality(catalog_id, parquet_uri)

    prov = _read_run_provenance(out_dir)
    ag = prov.get("adj_vs_gtex", {})
    if not ag.get("ran"):
        raise AssertionError(
            f"run provenance for {indication}/{substrate} reports adj_vs_gtex did not run — no AG package to land"
        )
    qc_files = _relative_qc_files(out_dir)
    sidecar = {
        "id": catalog_id,
        "s3_uri": parquet_uri,
        "type": "derived",
        "role": "secondary-diagnostic",
        "classifier_input": False,
        "indication": indication.upper(),
        "substrate": prov.get("substrate"),
        "tcga_studies": prov.get("tcga_studies"),
        "gtex_tissue": prov.get("gtex_tissue"),
        "n_adjacent": prov.get("n_adjacent"),
        "n_gtex": prov.get("n_gtex"),
        "min_normals": prov.get("min_normals"),
        "positive_group": ag.get("positive_group"),
        "reference_group": ag.get("reference_group"),
        "log2fc_sign_convention": "positive = higher in TCGA adjacent-normal than GTEx normal",
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


def write_adj_vs_gtex_sidecar(out_dir: Path, sidecar: dict) -> Path:
    """Write the AG sidecar next to the run outputs (uploaded as provenance.yaml)."""
    p = out_dir / "adj_vs_gtex.provenance.yaml"
    p.write_text(yaml.safe_dump(sidecar, sort_keys=False))
    return p


def plan_adj_vs_gtex_upload(
    out_dir: Path, indication: str, substrate: str, sidecar_path: Path
) -> list[tuple[Path, str]]:
    """Return the ordered [(local_path, s3_uri)] plan for the AG package.

    Uploads: the AG parquet (primary), the id-carrying sidecar (as
    ``provenance.yaml``), and the whole QC bundle under ``qc/`` — none of which
    ``run_indication_batch.sh`` uploaded before S4.
    """
    catalog_id = adj_vs_gtex_catalog_id(indication, substrate)
    prefix = derived_prefix(catalog_id)

    parquet = out_dir / _ADJ_VS_GTEX_PARQUET
    if not parquet.is_file():
        raise FileNotFoundError(f"{parquet} missing — the AG cell did not emit a parquet")

    plan: list[tuple[Path, str]] = [
        (parquet, f"{prefix}/{_ADJ_VS_GTEX_PARQUET}"),
        (sidecar_path, f"{prefix}/{_SIDECAR_NAME}"),
    ]
    for rel in _relative_qc_files(out_dir):
        plan.append((out_dir / rel, f"{prefix}/{rel.as_posix()}"))
    # Every planned key lands under the package's own prefix — the three-way anchor.
    for _, uri in plan:
        if prefix_stem_of(uri) != catalog_id:
            raise AssertionError(f"planned key {uri!r} escapes the {catalog_id!r} prefix")
    return plan


# --------------------------------------------------------------------------- #
# impure: the actual upload
# --------------------------------------------------------------------------- #
def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _aws_cp(local: Path, s3_uri: str) -> None:
    cmd = ["aws", "s3", "cp", str(local), s3_uri, "--metadata", f"md5={_md5(local)}", "--no-progress"]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def _git_sha(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Land the diagnostic AG data-package (+ QC sidecar) for a completed DGE run."
    )
    ap.add_argument("--out-dir", type=Path, required=True, help="Completed four-cell run out-dir.")
    ap.add_argument("--indication", required=True)
    ap.add_argument("--substrate", required=True, choices=sorted(_SUBSTRATE_INFIX))
    ap.add_argument("--git-sha", default=None, help="Provenance git sha (default: HEAD of this repo).")
    ap.add_argument("--no-upload", action="store_true", help="Plan + write the sidecar only; skip S3 writes.")
    args = ap.parse_args(argv)

    git_sha = args.git_sha or _git_sha(Path(__file__).resolve().parents[2])
    sidecar = build_adj_vs_gtex_sidecar(args.out_dir, args.indication, args.substrate, git_sha)
    sidecar_path = write_adj_vs_gtex_sidecar(args.out_dir, sidecar)
    plan = plan_adj_vs_gtex_upload(args.out_dir, args.indication, args.substrate, sidecar_path)

    print(f"[emit_data_package] id={sidecar['id']} — {len(plan)} object(s) to {derived_prefix(sidecar['id'])}/")
    if args.no_upload:
        for local, uri in plan:
            print(f"  (plan) {local}  ->  {uri}")
        return 0
    for local, uri in plan:
        _aws_cp(local, uri)
    print(
        f"[emit_data_package] uploaded {len(plan)} object(s); parquet md5={_md5(args.out_dir / _ADJ_VS_GTEX_PARQUET)}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
