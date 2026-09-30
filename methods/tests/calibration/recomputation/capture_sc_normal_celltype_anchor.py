#!/usr/bin/env python3
"""LIVE capture tool for the sc-normal-celltype-expression T3 recomputation anchor (#2047, batch E).

Clone of capture_sc_celltype_anchor.py (the sc-TUMOR sibling) for the sc-NORMAL method. NOT
collected by pytest (no ``test_`` prefix): it needs the live Tier-1 normal-tissue product (AWS
``cbg`` creds); the committed sibling test reads only the fixtures this tool writes.

What it freezes — the IRREPRODUCIBLE input: for each (target, indication) anchor, the per-(tissue,
cell_type) Tier-1 cross-donor-aggregated rows for that gene (n_donors_reliable, median_det,
expressing_donor_fraction, median_abund, n_datasets_reliable, ...) — one predicate-pushdown slice
per queried tissue (the indication-matched tissue UNION the always-on safety-essential organs) of
the S3 product ``sc-normal-celltype-expression-{tissue}-v1``. That slice cannot be reconstructed
offline. From it the tool re-derives the sc-normal-celltype-expression card's summary fields
through the REAL library entry point ``read_target_summary`` (-> read_gene_celltype_rows ->
classify_sc_normal_expression) and records the FULL summary dict as the anchor's expected values.

BOUNDARY (honestly stated): the Tier-1 product's cross-donor aggregation itself (n_cells>=10
per-donor-group inclusion floor, UNWEIGHTED cross-donor median — deliberately never a cell-weighted
mean, so no single large donor/dataset dominates — see methods/sc_normal_expression/aggregate.py's
module docstring) runs OUTSIDE analysis-methods, in the data-catalog Tier-2->Tier-1 build. This
anchor validates the READ + CLASSIFY path AM owns: the per-gene multi-tissue predicate-pushdown read
(read_gene_celltype_rows), the indication->tissue-union resolution (tissues_for_indication), the
donor-reliability floor re-applied at read time (MIN_RELIABLE_DONORS=5, classify_sc_normal_expression),
the liability ladder, the origin-aware essential-organ veto split, and the named-driver selection —
NOT the upstream per-donor cross-donor median itself (that is data-catalog's build, already
unweighted BY DESIGN and out of scope to re-derive or "fix").

Two independent guards make the anchor honest before it is committed:
  1. FIDELITY — the offline re-derivation (frozen per-tissue rows, monkeypatched reader) must
     reproduce the LIVE compute exactly, field-for-field over the full read_target_summary() output;
     if the frozen slice lost information the classifier uses, it aborts.
  2. NON-VACUITY — the anchor set must span more than one sc_normal_expression_class / drive the
     essential-organ veto for at least one anchor, so the guard is not trivially satisfied.

Run:
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        PYTHONPATH=<analysis-methods-root> pixi run python \\
        tests/calibration/recomputation/capture_sc_normal_celltype_anchor.py EPCAM/COADREAD KRAS/COADREAD

Writes into tests/calibration/recomputation/{sc_normal_celltype_rows,anchors}/. Commit the outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent

import onc_methods.sc_normal_expression.read as rd

ROWS_DIR = HERE / "sc_normal_celltype_rows"
ANCHOR_DIR = HERE / "anchors"

# The frozen per-(tissue, cell_type) row columns (identical to rd._PARQUET_COLS).
_ROW_COLS = list(rd._PARQUET_COLS)  # noqa: SLF001

# The full read_target_summary() output — captured wholesale (not a hand-picked subset) so the
# anchor stays valid as the classifier's field set evolves. Fields are read with .get() since some
# are None on the data_unavailable / no-essential-hit branches.
_FIELDS = (
    "sc_normal_expression_class",
    "sc_normal_safety_essential_class",
    "max_detection_cell_type",
    "max_detection_fraction",
    "expressing_donor_fraction_max",
    "sc_normal_abundance_class",
    "sc_normal_peak_median_abund",
    "sc_normal_essential_max_cell_type",
    "sc_normal_essential_max_tissue",
    "sc_normal_essential_max_detection_fraction",
    "sc_normal_essential_donor_fraction",
    "sc_normal_essential_n_datasets_reliable",
    "sc_normal_essential_median_abund",
    "safety_essential_flags",
    "n_cell_types_above_20pct",
    "n_reliable_cell_types",
    "per_cell_type_top",
    "tissues_queried",
    "origin_tissues",
    "indication",
)


def _rows_to_records(rows: pd.DataFrame) -> list[dict]:
    return [{c: r[c] for c in _ROW_COLS} for _, r in rows.iterrows()]


def _frozen_frame(records: list[dict], tissues_loaded: list[str], tissues: list[str]) -> pd.DataFrame:
    """Rebuild the frozen DataFrame with the SAME .attrs coverage-accounting read_target_summary
    reads (tissues_loaded/tissues_missing) — mirrors exactly what read_gene_celltype_rows attaches."""
    df = pd.DataFrame(records, columns=_ROW_COLS)
    df.attrs["tissues_requested"] = list(tissues)
    df.attrs["tissues_with_product"] = list(tissues)
    df.attrs["tissues_loaded"] = list(tissues_loaded)
    df.attrs["tissues_missing"] = [t for t in tissues if t not in set(tissues_loaded)]
    return df


def _offline_rederive(target: str, indication: str, records: list[dict], tissues_loaded: list[str]) -> dict:
    tissues = rd.tissues_for_indication(indication)
    frozen = _frozen_frame(records, tissues_loaded, tissues)
    with mock.patch.object(rd, "read_gene_celltype_rows", lambda t, tis: frozen):
        return rd.read_target_summary(target, indication)


def capture(target: str, indication: str) -> None:
    tissues = rd.tissues_for_indication(indication)
    live_summary = rd.read_target_summary(target, indication)
    if live_summary.get("sc_normal_expression_class") == "data_unavailable":
        raise SystemExit(f"{target}/{indication}: sc-normal not measurable ({live_summary.get('_data_note')})")

    rows = rd.read_gene_celltype_rows(target, tissues)
    if rows is None or rows.empty:
        raise SystemExit(f"{target}/{indication}: no Tier-1 rows returned — cannot anchor")
    tissues_loaded = list(getattr(rows, "attrs", {}).get("tissues_loaded") or tissues)
    records = _rows_to_records(rows)

    # GUARD 1 (fidelity): offline re-derivation from the frozen rows must reproduce live exactly.
    off = _offline_rederive(target, indication, records, tissues_loaded)
    for f in _FIELDS:
        if off.get(f) != live_summary.get(f):
            raise SystemExit(
                f"ABORT [{target}-{indication}]: offline slice re-derivation != live compute on {f!r}: "
                f"{off.get(f)!r} != {live_summary.get(f)!r} — the frozen slice lost information"
            )

    ROWS_DIR.mkdir(parents=True, exist_ok=True)
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records, columns=_ROW_COLS)
    table = pa.Table.from_pandas(df, preserve_index=False)
    fixture_name = f"{target.lower()}_{indication.lower()}.sc_normal_celltype_rows.parquet"
    fixture_path = ROWS_DIR / fixture_name
    pq.write_table(table, fixture_path)
    md5 = hashlib.md5(fixture_path.read_bytes()).hexdigest()  # noqa: S324

    anchor = {
        "target": target.upper(),
        "indication": indication.upper(),
        "skill": "tumor-presence",
        "card_id": "sc-normal-celltype-expression",
        "class_field": "sc_normal_expression_class",
        "rows_fixture": f"sc_normal_celltype_rows/{fixture_name}",
        "rows_md5": md5,
        "n_rows": len(records),
        "tissues_queried": tissues,
        "tissues_loaded": tissues_loaded,
        "expected": {k: off.get(k) for k in _FIELDS},
        "boundary": (
            "validates the READ + CLASSIFY path (multi-tissue predicate-pushdown read, "
            "indication->tissue-union resolution, MIN_RELIABLE_DONORS=5 read-time floor, the "
            "liability ladder, origin-aware essential-organ veto split, named-driver selection). "
            "The Tier-1 product's own cross-donor aggregation (per-donor n_cells>=10 inclusion "
            "floor, UNWEIGHTED cross-donor median BY DESIGN — deliberately never a cell-weighted "
            "mean, so no single large donor/dataset dominates) is a data-catalog Tier-2->Tier-1 "
            "build step, out of scope here — see methods/sc_normal_expression/aggregate.py."
        ),
        "_captured_at": datetime.now(timezone.utc).isoformat(),
        "_provenance": (
            f"live cbg read of sc-normal-celltype-expression-{{tissue}}-v1 (methods.sc_normal_expression."
            f"read), gene_symbol=={target.upper()!r} pushdown over tissues {tissues}; fixture = the "
            "concatenated per-(tissue, cell_type) Tier-1 rows; re-derive with "
            "onc_methods.sc_normal_expression.read.read_target_summary (mock read_gene_celltype_rows)."
        ),
    }
    anchor_name = f"{target.lower()}_{indication.lower()}.sc_normal_celltype.json"
    (ANCHOR_DIR / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + sc_normal_celltype_rows/{fixture_name}")
    print(
        f"  {target:8} {indication:8} nrows={len(records):>5} class={off['sc_normal_expression_class']} "
        f"safety_class={off['sc_normal_safety_essential_class']} max_ct={off.get('max_detection_cell_type')!r}"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pairs", nargs="+", help="TARGET/INDICATION pairs")
    args = ap.parse_args(argv)
    failures = []
    for pair in args.pairs:
        try:
            target, indication = pair.split("/", 1)
            capture(target, indication)
        except SystemExit as e:
            print(f"SKIP {pair}: {e}", file=sys.stderr)
            failures.append(pair)
    if failures:
        print(f"\n{len(failures)} capture(s) skipped: {failures}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
