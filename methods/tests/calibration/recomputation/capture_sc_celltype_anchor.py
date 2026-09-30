"""LIVE capture tool for the sc-tumor-expression-celltype T3 recomputation anchor.

NOT collected by pytest (no ``test_`` prefix): it needs the live single-cell pseudobulk product (AWS
``cbg`` creds); the committed sibling test ``test_sc_celltype_recomputation.py`` is fully offline and reads
only the fixtures this tool writes.

What it freezes — the IRREPRODUCIBLE input: for each (target, indication) anchor, the per-(dataset, donor,
compartment) pseudobulk rows for that gene (n_cells, detection_fraction, abundance_log1p_cp10k), one
predicate-pushdown slice of the S3 single-cell cube. That slice cannot be reconstructed offline. From it
the tool re-derives the sc-tumor-expression-celltype card's summary fields through the REAL library entry
point ``read_sc_expression_presence`` (→ compartment_summary → classify_sc_expression + caf_readout) and
records them as the anchor's expected values.

Two independent guards make the anchor honest before it is committed:
  1. FIDELITY — the offline re-derivation (frozen rows, monkeypatched reader) must reproduce the LIVE
     compute exactly; if the frozen slice lost information the classifier uses, it aborts.
  2. CROSS-REPO — for every anchor the tumor-selectivity calibration roster records, the re-derived
     sc_expression_class / malignant_detection_fraction / caf_vs_malignant_class must equal that snapshot's
     independently-captured headline (sc_tumor_expression_class / sc_malignant_detection_fraction /
     sc_caf_vs_malignant_class); a drift aborts rather than silently re-baselining.

Run:
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        PYTHONPATH=<analysis-methods-root> python3 <this file>
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
AM_ROOT = HERE.parents[2]

import onc_methods.sc_tumor_expression_celltype.read as rd

FIXTURE_REL = "sc_compartment_rows/sc_pseudobulk__compartment_rows.parquet"
ANCHOR_DIR = HERE / "anchors"

# Anchor (target, indication) pairs — ALL ten tumor-selectivity roster pairs (grounded in the committed
# roster, not invented). Every pair carries an sc_tumor_expression_class headline, so every anchor is
# cross-referenced. Live probe (2026-09-21): malignant_subset_detected (APC/MET/MSLN/TACSTD2),
# malignant_broadly_detected (CEACAM5/EPCAM/FOLR1), data_unavailable (DLL3/ERBB2/KLK3 — no landed sc
# pseudobulk product for those indications). The set spans 3 classes; the actual classes are whatever the
# real compute returns and are asserted non-vacuous below, never assumed.
ANCHORS = [
    ("APC", "COADREAD"),
    ("CEACAM5", "COADREAD"),
    ("DLL3", "SCLC"),
    ("EPCAM", "COADREAD"),
    ("FOLR1", "OV"),
    ("MET", "COADREAD"),
    ("MSLN", "PAAD"),
    ("TACSTD2", "COADREAD"),
]

CONTRACTS_ROOT = AM_ROOT.parent / "rnd-computational-biology-oncology-target-contracts"
SNAPSHOT_DIR = CONTRACTS_ROOT / "tests" / "calibration" / "snapshots"

# _PARQUET_COLS the real reader returns (the slice compartment_summary consumes).
_ROW_COLS = [
    "gene_symbol",
    "dataset_id",
    "donor_id",
    "compartment",
    "n_cells",
    "detection_fraction",
    "abundance_log1p_cp10k",
]

# The fields this anchor re-derives (all produced by read_sc_expression_presence). Some are None on the
# data_unavailable branch, so they are read with .get().
_FIELDS = (
    "sc_expression_class",
    "malignant_detection_fraction",
    "malignant_abundance_log1p_cp10k",
    "malignant_compartment_available",
    "malignant_n_donors",
    "malignant_n_cells",
    "n_compartments_measured",
    "top_microenvironment_compartment",
    "top_microenvironment_detection_fraction",
    "caf_vs_malignant_class",
    "caf_detection_fraction",
)

# The fields the roster snapshot records (headline names -> reader field). The two CATEGORICAL fields are
# the stable cross-repo invariants (the headline the downstream consumes) and must match EXACTLY. The
# continuous malignant_detection_fraction is a point-in-time independent capture ("live-phase-S+A4") and
# drifts with the pseudobulk product's vintage (measured 2026-09-21: all 7 measured roster pairs match
# class+CAF exactly, but the fraction drifts 0.0002-0.018 as donors/cells were added). So it is
# cross-checked within a SANITY tolerance — wide enough to tolerate a vintage refresh, tight enough that a
# wrong join / denominator / comparator (which moves the median far more) still aborts. The EXACT numeric
# proof of the fraction is the offline re-derivation from the frozen rows (GUARD 1 + test_rederives), not
# this older snapshot.
_XREF_EXACT = {
    "sc_tumor_expression_class": "sc_expression_class",
    "sc_caf_vs_malignant_class": "caf_vs_malignant_class",
}
_XREF_APPROX = {"sc_malignant_detection_fraction": "malignant_detection_fraction"}
_MDF_VINTAGE_TOL = 0.05  # >> observed max drift 0.018; << a real-bug shift
_XREF = {**_XREF_EXACT, **_XREF_APPROX}


def _rows_to_records(rows) -> list[dict]:
    """The frozen per-(dataset, donor, compartment) rows as a list of dicts over _ROW_COLS."""
    return [{c: r[c] for c in _ROW_COLS} for _, r in rows.iterrows()]


def _offline_rederive(target: str, indication: str, records: list[dict] | None) -> dict:
    """Re-derive through the REAL read_sc_expression_presence using ONLY the frozen rows — the identical
    seam the committed offline test uses. read_gene_compartment_rows -> the frozen DataFrame (or None to
    reproduce a no-product indication)."""
    import pandas as pd

    frozen = None if records is None else pd.DataFrame(records, columns=_ROW_COLS)
    with mock.patch.object(rd, "read_gene_compartment_rows", lambda t, i: frozen):
        return rd.read_sc_expression_presence(target, indication)


def _snapshot_xref(target: str, indication: str) -> dict | None:
    path = SNAPSHOT_DIR / f"{target.lower()}_{indication.lower()}.tumor-selectivity.json"
    if not path.exists():
        return None
    headline = json.loads(path.read_text()).get("headline", {})
    if not any(k in headline for k in _XREF):
        return None
    return {"source": str(path.relative_to(CONTRACTS_ROOT.parent)), **{k: headline.get(k) for k in _XREF}}


def main() -> None:
    import pandas as pd

    # --- live-read each anchor's row slice + live summary ---
    live: dict[tuple[str, str], dict] = {}
    for target, indication in ANCHORS:
        rows = rd.read_gene_compartment_rows(target, indication)
        live_summary = rd.read_sc_expression_presence(target, indication)
        if rows is not None and rows.empty:
            raise SystemExit(
                f"ABORT: {target}-{indication} product landed but gene absent (empty) — unexpected for roster"
            )
        records = None if rows is None else _rows_to_records(rows)
        live[(target, indication)] = {"records": records, "live_summary": live_summary}

    # --- write the frozen slice: one row per (anchor, dataset, donor, compartment) ---
    frames = []
    for (target, indication), rec in live.items():
        if rec["records"] is None:
            continue
        df = pd.DataFrame(rec["records"], columns=_ROW_COLS)
        df.insert(0, "anchor_indication", indication)
        df.insert(0, "anchor_target", target)
        frames.append(df)
    all_rows = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["anchor_target", "anchor_indication", *_ROW_COLS])
    )
    table = pa.Table.from_pandas(all_rows, preserve_index=False)
    fixture_path = HERE / FIXTURE_REL
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, fixture_path)
    md5 = hashlib.md5(fixture_path.read_bytes()).hexdigest()
    captured_utc = datetime.now(timezone.utc).isoformat()
    print(f"fixture: {fixture_path.name} rows={table.num_rows} md5={md5}")

    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    classes: set[str] = set()
    for target, indication in ANCHORS:
        rec = live[(target, indication)]
        records, live_summary = rec["records"], rec["live_summary"]

        # GUARD 1 (fidelity): the offline re-derivation from the frozen rows must reproduce live exactly.
        off = _offline_rederive(target, indication, records)
        for f in _FIELDS:
            if off.get(f) != live_summary.get(f):
                raise SystemExit(
                    f"ABORT [{target}-{indication}]: offline slice re-derivation != live compute on {f!r}: "
                    f"{off.get(f)!r} != {live_summary.get(f)!r} — the frozen slice lost information"
                )

        # GUARD 2 (cross-repo): the roster snapshot's categorical sc_* headline must match EXACTLY; the
        # continuous fraction must fall within the vintage-drift sanity band (a gross disagreement is a real
        # defect and aborts).
        snap = _snapshot_xref(target, indication)
        if snap is not None:
            for hk, rf in _XREF_EXACT.items():
                if snap.get(hk) != off.get(rf):
                    raise SystemExit(
                        f"ABORT [{target}-{indication}]: re-derived {rf!r}={off.get(rf)!r} disagrees with committed "
                        f"snapshot {snap['source']} {hk}={snap.get(hk)!r} — investigate drift, do not re-baseline"
                    )
            for hk, rf in _XREF_APPROX.items():
                sv, ov = snap.get(hk), off.get(rf)
                if sv is not None and ov is not None and abs(sv - ov) > _MDF_VINTAGE_TOL:
                    raise SystemExit(
                        f"ABORT [{target}-{indication}]: re-derived {rf!r}={ov!r} is {abs(sv - ov):.4f} off the "
                        f"snapshot {snap['source']} {hk}={sv!r} (> {_MDF_VINTAGE_TOL} vintage band) — too far to be a "
                        f"product refresh; investigate a wrong join/denominator, do not re-baseline"
                    )

        classes.add(off["sc_expression_class"])
        anchor = {
            "target": target,
            "indication": indication,
            "rows_fixture": FIXTURE_REL,
            "rows_kind": "none" if records is None else "rows",
            "n_rows": 0 if records is None else len(records),
            "expected_sc_expression_class": off["sc_expression_class"],
            "expected_malignant_detection_fraction": off.get("malignant_detection_fraction"),
            "expected_malignant_abundance_log1p_cp10k": off.get("malignant_abundance_log1p_cp10k"),
            "expected_malignant_compartment_available": off.get("malignant_compartment_available"),
            "expected_malignant_n_donors": off.get("malignant_n_donors"),
            "expected_malignant_n_cells": off.get("malignant_n_cells"),
            "expected_n_compartments_measured": off.get("n_compartments_measured"),
            "expected_top_microenvironment_compartment": off.get("top_microenvironment_compartment"),
            "expected_top_microenvironment_detection_fraction": off.get("top_microenvironment_detection_fraction"),
            "expected_caf_vs_malignant_class": off.get("caf_vs_malignant_class"),
            "expected_caf_detection_fraction": off.get("caf_detection_fraction"),
            "snapshot_cross_ref": snap,
            "_source": {
                "product": "single-cell pseudobulk compartment cube (per-donor detection/abundance by compartment)",
                "captured_utc": captured_utc,
                "rows_fixture_md5": md5,
            },
        }
        (ANCHOR_DIR / f"{target.lower()}_{indication.lower()}.sc_celltype.json").write_text(
            json.dumps(anchor, indent=2) + "\n"
        )
        mdf = off.get("malignant_detection_fraction")
        print(
            f"  {target:8} {indication:8} nrows={anchor['n_rows']:>4} mal_donors={off.get('malignant_n_donors')} "
            f"mdf={('%.4f' % mdf) if mdf is not None else 'None':>7} caf={off.get('caf_vs_malignant_class')} "
            f"class={off['sc_expression_class']}{' [x-ref roster]' if snap else ''}"
        )
    print(f"classes spanned ({len(classes)}): {sorted(classes)}")
    if len(classes) < 3:
        raise SystemExit(f"ABORT: anchor set spans only {len(classes)} sc_expression_class branch(es); need >= 3")

    # Anti-vacuity for GUARD 2 itself: at least one anchor must cross-check against a roster snapshot.
    n_xref = sum(1 for t, i in ANCHORS if _snapshot_xref(t, i) is not None)
    if n_xref == 0:
        raise SystemExit(
            "ABORT: no anchor cross-checked against a roster sc_* headline — the target-contracts sibling is "
            "unreachable, so GUARD 2 never ran. Symlink it beside the worktree and re-capture."
        )
    print(f"cross-referenced against roster: {n_xref} anchor(s)")


if __name__ == "__main__":
    main()
