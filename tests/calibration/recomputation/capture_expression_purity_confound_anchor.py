#!/usr/bin/env python3
"""capture_expression_purity_confound_anchor.py — T3 recomputation anchor for the
expression-purity-confound card (#2046, batch D).

read.read_expression_purity_confound(target, indication) joins per-sample tumor expression
({case: log2_tpm}, recount3 case-bridged) with per-case ABSOLUTE tumor purity ({case: purity}) on
the TCGA case barcode, correlates (Pearson r(log2TPM, ABSOLUTE purity) + Spearman), and classifies
purity_confound_class. NO regression slope is computed or emitted — the reader emits Pearson r,
Pearson p, Spearman r, median purity, and the IQR spread qualifier only.

The two irreproducible substrates are:
  expr    = read_tumor_samples_with_case(target, indication)  -> DataFrame[case, log2_tpm]
  purity  = _load_purity_by_case()                            -> {case: purity} (ABSOLUTE, static
            TCGA pancanatlas snapshot 2018-snapshot-2026-06-27)

The anchor stores the per-sample expression rows (lossless [case, log2_tpm]) and the purity for the
cases present in the expression frame (the join's relevant slice — cases absent from the expression
frame never enter the correlation). The offline test reconstructs both and monkeypatches
read_tumor_samples_with_case + _load_purity_by_case (the two S3-load seams) + ensure_aws_profile, so
the whole reader — case-collapse (mean log2_tpm per case), purity join, dropna, Pearson/Spearman,
classification, IQR power gate — runs offline. Validates the READ/JOIN/CORRELATION path, NOT the
upstream recount3 / ABSOLUTE generation.

Round-trip guard: capture re-runs the reader through the reconstructed inputs (the exact mock the
offline test uses) and asserts it equals the live compute before writing.

Hits S3, NOT run in CI. Run once with live creds:

    cd <analysis-methods repo>
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        pixi run python tests/calibration/recomputation/capture_expression_purity_confound_anchor.py \\
        EPCAM/COADREAD KRAS/COADREAD

Writes into tests/calibration/recomputation/{purity_confound_vectors,anchors}/. Commit the outputs.
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
VECTORS = HERE / "purity_confound_vectors"
ANCHORS = HERE / "anchors"
AM_ROOT = HERE.parents[2]

_FIELDS = (
    "purity_confound_class",
    "expression_purity_pearson_r",
    "expression_purity_pearson_p",
    "expression_purity_spearman_r",
    "n_paired_samples",
    "n_expr_samples",
    "median_purity",
    "purity_range_iqr",
    "purity_spread_underpowered",
)


def _json_num(v):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return float(v)


def _expected(summary: dict) -> dict:
    return {k: (_json_num(summary[k]) if isinstance(summary.get(k), float) else summary.get(k)) for k in _FIELDS}


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — fixture drift guard, not security


def _read_modules():
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    import methods.expression_purity_confound.read as epc  # noqa: PLC0415
    import methods.tcga_gtex_expression_distribution.read as exprmod  # noqa: PLC0415

    return epc, exprmod


def capture(target: str, indication: str) -> None:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    epc, exprmod = _read_modules()
    epc.ensure_aws_profile()
    expr = exprmod.read_tumor_samples_with_case(target.upper().strip(), indication)
    if expr is None or len(expr) == 0:
        raise SystemExit(f"{target}/{indication}: no per-sample expression")
    purity_by_case = epc._load_purity_by_case()  # noqa: SLF001
    if not purity_by_case:
        raise SystemExit(f"{target}/{indication}: ABSOLUTE purity table unavailable")

    live = epc.read_expression_purity_confound(target, indication)
    if live.get("purity_confound_class") in (None, "data_unavailable"):
        raise SystemExit(f"{target}/{indication}: purity confound not measurable ({live.get('purity_confound_class')})")

    VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    expr_rows = expr[["case", "log2_tpm"]].copy()
    expr_name = f"{target.lower()}_{indication.lower()}.expression_purity_confound.expr.parquet"
    pq.write_table(pa.Table.from_pandas(expr_rows, preserve_index=False), VECTORS / expr_name)

    # Purity for the cases in the expression frame (the only cases that can enter the join).
    expr_cases = sorted(set(expr_rows["case"].tolist()))
    purity_pairs = [(c, float(purity_by_case[c])) for c in expr_cases if c in purity_by_case]
    purity_name = f"{target.lower()}_{indication.lower()}.expression_purity_confound.purity.parquet"
    pq.write_table(
        pa.table(
            {
                "case": pa.array([c for c, _ in purity_pairs], type=pa.string()),
                "purity": pa.array([p for _, p in purity_pairs], type=pa.float64()),
            }
        ),
        VECTORS / purity_name,
    )

    # Round-trip guard: reconstruct EXACTLY as the offline test will and mock the two S3-load seams
    # + ensure_aws_profile, then confirm the reader reproduces the live numbers.
    recon_expr = pd.read_parquet(VECTORS / expr_name)
    recon_purity = {c: p for c, p in purity_pairs}
    with (
        mock.patch.object(epc, "ensure_aws_profile", lambda: None),
        mock.patch.object(exprmod, "read_tumor_samples_with_case", lambda t, i: recon_expr),
        mock.patch.object(epc, "_load_purity_by_case", lambda: recon_purity),
    ):
        recon = epc.read_expression_purity_confound(target, indication)
    for k in _FIELDS:
        assert recon[k] == live[k], (
            f"{target}/{indication}: purity round-trip mismatch on {k}: {recon[k]!r} != {live[k]!r}"
        )

    anchor = {
        "target": target.upper(),
        "indication": indication.upper(),
        "skill": "tumor-presence",
        "card_id": "expression-purity-confound",
        "class_field": "purity_confound_class",
        "expr_fixture": f"purity_confound_vectors/{expr_name}",
        "purity_fixture": f"purity_confound_vectors/{purity_name}",
        "expr_md5": _md5(VECTORS / expr_name),
        "purity_md5": _md5(VECTORS / purity_name),
        "n_expr_rows": int(len(expr_rows)),
        "n_purity_cases": len(purity_pairs),
        "n_paired_samples": int(live["n_paired_samples"]),
        "expected": _expected(live),
        "_captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_provenance": (
            f"live cbg read via read_tumor_samples_with_case({target!r}, {indication!r}) (recount3 tumor, "
            "case-bridged) + _load_purity_by_case() (ABSOLUTE pancanatlas static snapshot); fixtures = the "
            "per-sample [case, log2_tpm] rows + the per-case ABSOLUTE purity for those cases; re-derive with "
            "methods.expression_purity_confound.read.read_expression_purity_confound (mock the two loaders)."
        ),
    }
    anchor_name = f"{target.lower()}_{indication.lower()}.expression_purity_confound.json"
    (ANCHORS / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + 2 vectors")
    print(
        f"  class={anchor['expected']['purity_confound_class']}  pearson_r={anchor['expected']['expression_purity_pearson_r']}  "
        f"spearman_r={anchor['expected']['expression_purity_spearman_r']}  n_paired={anchor['n_paired_samples']}  "
        f"median_purity={anchor['expected']['median_purity']}"
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
