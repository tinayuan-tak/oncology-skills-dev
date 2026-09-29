"""LIVE capture tool for the tumor-elevation-breadth T3 recomputation anchor (#2044, batch B).

NOT collected by pytest (no ``test_`` prefix): it needs live product reads (AWS ``cbg`` creds); the
committed sibling test ``test_tumor_elevation_breadth_recomputation.py`` is fully offline and reads
only the fixtures this tool writes.

tumor-elevation-breadth is a TWO-LAYER card (primary reader named in the product->reader binding):
  - PROTEIN (primary, drives tumor_elevation_breadth_class): CPTAC per-cohort product
    ``cptac-protein-tumor-vs-normal-per-cohort-v1`` -> ``methods.cptac_protein_deg.read``:
    ``read_tumor_elevation_breadth`` (built on ``read_all_cohorts``).
  - RNA (parallel ``rna_*`` fields): the stacked ``pancan-dge-tumor-vs-normal-v1`` product ->
    ``methods.dge_deseq2.derive_pancan_stack.read_rna_tumor_elevation_breadth``.

WHAT IT FREEZES (the read-path's irreproducible input):
  1. the target's per-cohort CPTAC rows exactly as ``read_all_cohorts`` returns them (protein layer
     input), committed as a lossless parquet under ``dge_rows/``.
  2. the target's stacked pancan RNA rows exactly as ``read_rna_tumor_elevation_breadth`` reads them
     BEFORE the composite-indication dedupe (RNA layer input), committed as a lossless parquet.

and RE-DERIVES the breadth roll-up through the REAL readers — so the offline test validates the
READ/AGGREGATION path (elevated-cohort counting, the read-time pan-cohort BH/FDR, the composite-
indication dedupe, the breadth-class ladder), NOT the upstream DEG/DESeq2 runs (that provenance
belongs to data-catalog).

Known upstream gap (#1663, documented — no fabrication): the four-cell sensitivity family has no n
columns, but this card's protein layer is the CPTAC per-cohort product (which DOES carry
n_normal_samples) and its RNA layer is the pancan stack — neither is the four-cell family, so no
n-field is fabricated here; the anchor asserts only the fields the readers actually emit.

Run:
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        PYTHONPATH=<analysis-methods-root> python3 <this file>
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
AM_ROOT = HERE.parents[2]
if str(AM_ROOT) not in sys.path:
    sys.path.insert(0, str(AM_ROOT))

import methods.cptac_protein_deg.read as cp  # noqa: E402
import methods.dge_deseq2.derive_pancan_stack as ps  # noqa: E402

ANCHOR_DIR = HERE / "anchors"
FIXTURE_DIR = HERE / "dge_rows"

TARGETS = ["EPCAM", "KRAS", "ERBB2", "TACSTD2"]

_PROTEIN_FIELDS = (
    "tumor_elevation_breadth_class",
    "n_cohorts_tested",
    "n_cohorts_elevated",
    "n_cohorts_sig_up_effect_negligible",
    "n_cohorts_sig_up_pan_cohort_fdr_fail",
    "fraction_elevated",
    "median_effect_across_elevated",
    "median_standardized_effect_across_elevated",
    "most_elevated_cohorts",
    "cohorts_tested",
    "cohorts_unestimable",
)
_RNA_FIELDS = (
    "rna_tumor_elevation_breadth_class",
    "n_indications_tested",
    "n_indications_elevated",
    "fraction_elevated",
    "median_max_log2fc_across_elevated",
    "most_elevated_indications",
    "indications_tested",
)


def _coerce(v):
    """numpy/pandas scalar -> plain python (NaN preserved as float nan). Lossless for the fields the
    breadth readers consume."""
    if v is None:
        return None
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return item()
        except (ValueError, TypeError):
            return v
    return v


def _write_rows_fixture(name: str, rows: list[dict]) -> tuple[str, str]:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    coerced = [{k: _coerce(v) for k, v in r.items()} for r in rows]
    table = pa.Table.from_pylist(coerced)
    path = FIXTURE_DIR / name
    pq.write_table(table, path)
    rel = str(path.relative_to(HERE))
    return rel, hashlib.md5(path.read_bytes()).hexdigest()


def _read_raw_rna_rows(target: str) -> list[dict]:
    """Replicate read_rna_tumor_elevation_breadth's raw read (BEFORE dedupe): the stacked product rows
    for this gene, exactly as the reader materializes them via to_pandas().to_dict(records)."""
    import pyarrow.fs as pafs

    read_path = ps._RNA_STACKED_S3_URI[len("s3://") :]
    s3 = pafs.S3FileSystem()
    table = pq.read_table(read_path, filesystem=s3, filters=[("gene_symbol", "=", target)])
    return table.to_pandas().to_dict(orient="records")


def _offline_rederive_protein(cohort_rows: list[dict]) -> dict:
    with mock.patch.object(cp, "read_all_cohorts", lambda t: [dict(r) for r in cohort_rows]):
        return cp.read_tumor_elevation_breadth("FROZEN")


def _offline_rederive_rna(rna_rows: list[dict]) -> dict:
    import pyarrow.fs as pafs

    frozen = pa.Table.from_pylist([{k: _coerce(v) for k, v in r.items()} for r in rna_rows])

    def _fake_read_table(*_a, **_k):
        return frozen

    ps.read_rna_tumor_elevation_breadth.cache_clear()
    with (
        mock.patch.object(pafs, "S3FileSystem", lambda *a, **k: None),
        mock.patch("pyarrow.parquet.read_table", _fake_read_table),
    ):
        try:
            return ps.read_rna_tumor_elevation_breadth("FROZEN")
        finally:
            ps.read_rna_tumor_elevation_breadth.cache_clear()


def main() -> None:
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    protein_classes: set[str] = set()
    n_written = 0

    for target in TARGETS:
        cohort_rows = cp.read_all_cohorts(target)
        live_protein = cp.read_tumor_elevation_breadth(target)
        if not cohort_rows or live_protein.get("tumor_elevation_breadth_class") == "data_unavailable":
            print(f"SKIP {target}: protein layer data_unavailable", file=sys.stderr)
            continue

        rna_rows = _read_raw_rna_rows(target)
        live_rna = ps.read_rna_tumor_elevation_breadth(target)
        if not rna_rows or live_rna.get("rna_tumor_elevation_breadth_class") == "data_unavailable":
            print(f"SKIP {target}: RNA layer data_unavailable", file=sys.stderr)
            continue

        # Fidelity guards.
        off_protein = _offline_rederive_protein(cohort_rows)
        for f in _PROTEIN_FIELDS:
            if off_protein.get(f) != live_protein.get(f):
                raise SystemExit(
                    f"ABORT [{target}] protein: offline re-derivation != live on {f!r}: "
                    f"{off_protein.get(f)!r} != {live_protein.get(f)!r} — the frozen rows lost information"
                )
        off_rna = _offline_rederive_rna(rna_rows)
        for f in _RNA_FIELDS:
            if off_rna.get(f) != live_rna.get(f):
                raise SystemExit(
                    f"ABORT [{target}] rna: offline re-derivation != live on {f!r}: "
                    f"{off_rna.get(f)!r} != {live_rna.get(f)!r} — the frozen rows lost information"
                )

        cohort_rel, cohort_md5 = _write_rows_fixture(f"{target.lower()}.cptac_cohort_rows.parquet", cohort_rows)
        rna_rel, rna_md5 = _write_rows_fixture(f"{target.lower()}.rna_stack_rows.parquet", rna_rows)

        protein_classes.add(live_protein["tumor_elevation_breadth_class"])
        anchor = {
            "target": target,
            "protein_product_id": "cptac-protein-tumor-vs-normal-per-cohort-v1",
            "rna_product_id": "pancan-dge-tumor-vs-normal-v1",
            "cptac_cohort_rows_fixture": cohort_rel,
            "cptac_cohort_rows_fixture_md5": cohort_md5,
            "rna_stack_rows_fixture": rna_rel,
            "rna_stack_rows_fixture_md5": rna_md5,
            "expected_protein": {f: live_protein.get(f) for f in _PROTEIN_FIELDS},
            "expected_rna": {f: live_rna.get(f) for f in _RNA_FIELDS},
            "_source": {
                "protein_reader": "methods.cptac_protein_deg.read.read_tumor_elevation_breadth (on read_all_cohorts)",
                "rna_reader": "methods.dge_deseq2.derive_pancan_stack.read_rna_tumor_elevation_breadth",
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "boundary": (
                    "validates the read/aggregation path (elevated-cohort counting + pan-cohort BH/FDR "
                    "on the protein layer; composite-indication dedupe + K-of-N roll-up on the RNA layer), "
                    "NOT the upstream DEG/DESeq2 runs. #1663: no n-field fabricated — the readers emit only "
                    "the fields asserted here."
                ),
            },
        }
        (ANCHOR_DIR / f"{target.lower()}.tumor_elevation_breadth.json").write_text(json.dumps(anchor, indent=2) + "\n")
        n_written += 1
        print(
            f"  {target:8} protein={live_protein['tumor_elevation_breadth_class']} "
            f"({live_protein['n_cohorts_elevated']}/{live_protein['n_cohorts_tested']}) "
            f"rna={live_rna['rna_tumor_elevation_breadth_class']} "
            f"({live_rna['n_indications_elevated']}/{live_rna['n_indications_tested']})"
        )

    print(f"wrote {n_written} anchor(s); protein classes spanned ({len(protein_classes)}): {sorted(protein_classes)}")
    if n_written < 2:
        raise SystemExit(f"ABORT: only {n_written} anchor(s) written; need >= 2 (EPCAM + >=1 other)")
    if len(protein_classes) < 2:
        raise SystemExit(f"ABORT: anchor set spans only {len(protein_classes)} protein breadth class(es); need >= 2")


if __name__ == "__main__":
    main()
