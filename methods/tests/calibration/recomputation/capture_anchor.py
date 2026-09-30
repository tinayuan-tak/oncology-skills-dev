#!/usr/bin/env python3
"""capture_anchor.py — capture a T3 recomputation anchor for the tumor-vs-normal
selectivity all-gene percentile.

WHAT A T3 ANCHOR IS (plan foamy-bird, Stage I / tier T3). Tiers T1/T2 (the emission
ledger in target-contracts) prove a value is *reachable* and *self-consistent*; they
cannot prove the NUMBER is right — that needs re-derivation from the irreproducible
raw input. The calibration snapshots this sits beside store hand-minimized *derived*
values, which by construction can never catch a wrong computation (a fixture asserted
against its own output). T3 fixes that for known anchors: it stores the IRREPRODUCIBLE
INPUT and re-derives the field in-test through the REAL method code.

For `selectivity_allgene_percentile` the computation is (dge_deseq2/read.py):

    pct = percentile_rank(target_log2fc_A, null_vector) ; class = classify_percentile(pct)

where `null_vector` is the FULL log2fc_A column across all ~30k genes in the
indication's `-dge-tumor-vs-normal-sensitivity-v1` product — a genuinely
irreproducible S3 slice. That null is the wrong-denominator / pooling risk the plan
names (the #1468 3x threshold drift lives one classifier over). So the anchor stores:

  * the full null column (a parquet, shared across every anchor in the same
    indication+cell — the null is per (manifest, cell), not per gene), and
  * a small JSON per (target, indication) with the target's own log2fc_A, the
    live-captured expected percentile + class, the target-contracts snapshot class
    for cross-reference, and full provenance (manifest, s3_uri, sibling SHAs, date).

DOWNSAMPLING OR ROUNDING THE NULL IS FORBIDDEN — it is the wrong-denominator bug this
tier exists to catch. The column is stored at full float64 precision (parquet is
lossless), so the in-test re-derivation reproduces the live value exactly.

This tool hits S3 and is NOT run in CI. Run it once per anchor with live creds:

    cd <analysis-methods repo>
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        pixi run python tests/calibration/recomputation/capture_anchor.py CEACAM5 COADREAD

It writes into tests/calibration/recomputation/{nulls,anchors}/. Commit the outputs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import subprocess
import sys
from pathlib import Path


def _json_num(v):
    """Belt-and-suspenders: non-finite floats are not valid JSON. Store them as null.
    (T3 is numeric-only — capture() aborts a non-finite target below — so this only ever
    fires defensively, keeping allow_nan=False from raising on a surprise value.)"""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return v


def _finite(values):
    return [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]


HERE = Path(__file__).resolve().parent
NULLS = HERE / "nulls"
ANCHORS = HERE / "anchors"
# analysis-methods repo root (tests/calibration/recomputation -> parents[3])
AM_ROOT = HERE.parents[2]
# target-contracts snapshot dir (sibling repo) for the cross-reference class.
TC_SNAPSHOTS = (
    AM_ROOT.parent / "rnd-computational-biology-oncology-target-contracts" / "tests" / "calibration" / "snapshots"
)

CELL_COLUMN = "log2fc_A"  # cell A = TCGA tumor-vs-adjacent, the PRIMARY comparator the class keys on


def _sibling_shas() -> dict:
    out = {}
    for name, repo in (
        ("analysis-methods", AM_ROOT),
        ("data-catalog", AM_ROOT.parent / "rnd-computational-biology-oncology-data-catalog"),
    ):
        try:
            sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], text=True).strip()
            out[name] = sha
        except Exception:
            out[name] = "unknown"
    return out


def _snapshot_class(target: str, indication: str) -> str | None:
    """The selectivity_allgene_percentile_class recorded in the target-contracts calibration
    snapshot, if present — an independent record of the same value, for cross-reference."""
    snap = TC_SNAPSHOTS / f"{target.lower()}_{indication.lower()}.tumor-selectivity.json"
    if not snap.exists():
        return None
    try:
        d = json.loads(snap.read_text())
        return (d.get("headline") or {}).get("selectivity_allgene_percentile_class")
    except Exception:
        return None


def capture(target: str, indication: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from onc_methods.dge_deseq2 import read as dge
    from onc_methods.percentile_null import classify_percentile, percentile_rank

    manifest_id = f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1"
    row = dge.read_tumor_vs_normal_sensitivity_gene_row(target, indication)
    if not row:
        raise SystemExit(f"no sensitivity row for {target}/{indication} (product absent or gene missing)")
    s3_uri = dge.s3_uri_for(manifest_id)
    null = list(dge._sensitivity_cell_null(manifest_id, s3_uri, CELL_COLUMN))
    # Count FINITE values, not raw length: a comparator-less indication (e.g. SCLC has no TCGA
    # tumor-vs-adjacent arm) returns a full-length but all-NaN column — a vacuous distribution.
    if len(_finite(null)) < 1000:
        raise SystemExit(
            f"null has only {len(_finite(null))} finite values (of {len(null)}) — no real comparator "
            f"distribution; this is data_unavailable, not a numeric T3 anchor."
        )

    target_log2fc = row.get("log2fc_cell_a")
    if target_log2fc is None or not math.isfinite(float(target_log2fc)):
        raise SystemExit(
            f"{target}/{indication} log2fc_A is non-finite ({target_log2fc!r}) ⇒ selectivity is "
            f"data_unavailable, not a numeric T3 anchor (covered by T4 biology + percentile_null unit test)."
        )
    expected_pct = percentile_rank(target_log2fc, null)
    expected_class = classify_percentile(expected_pct)
    # Sanity: the reader's own value must equal our re-derivation from the same null.
    assert expected_pct == row.get("selectivity_allgene_percentile"), (
        expected_pct,
        row.get("selectivity_allgene_percentile"),
    )
    assert expected_class == row.get("selectivity_allgene_percentile_class")

    NULLS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    null_name = f"{manifest_id}__{CELL_COLUMN}.parquet"
    pq.write_table(pa.table({CELL_COLUMN: pa.array(null, type=pa.float64())}), NULLS / null_name)

    anchor = {
        "target": target.upper(),
        "indication": indication.upper(),
        "skill": "tumor-selectivity",
        "field": "selectivity_allgene_percentile",
        "class_field": "selectivity_allgene_percentile_class",
        "manifest_id": manifest_id,
        "cell_column": CELL_COLUMN,
        "null_fixture": f"nulls/{null_name}",
        "n_null": len(null),
        "target_log2fc": _json_num(target_log2fc),
        "expected_percentile": _json_num(expected_pct),
        "expected_class": expected_class,
        "snapshot_class_cross_ref": _snapshot_class(target, indication),
        "_captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_sibling_shas": _sibling_shas(),
        "_s3_uri": s3_uri,
        "_provenance": (
            f"live cbg read of {s3_uri}; null = full {CELL_COLUMN} column "
            f"({len(null)} non-null genes); re-derive with methods.percentile_null.percentile_rank."
        ),
    }
    anchor_name = f"{target.lower()}_{indication.lower()}.selectivity_percentile.json"
    # allow_nan=False: refuse to emit non-conforming JSON (NaN/Infinity) — forces every
    # non-finite value through _json_num first, so a committed anchor is always valid JSON.
    (ANCHORS / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + nulls/{null_name}")
    print(f"  target_log2fc={target_log2fc}  pct={expected_pct}  class={expected_class}")
    print(f"  snapshot cross-ref class={anchor['snapshot_class_cross_ref']}  n_null={len(null)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target")
    ap.add_argument("indication")
    args = ap.parse_args(argv)
    capture(args.target, args.indication)
    return 0


if __name__ == "__main__":
    sys.exit(main())
