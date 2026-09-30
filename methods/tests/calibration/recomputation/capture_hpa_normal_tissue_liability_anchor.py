#!/usr/bin/env python3
"""capture_hpa_normal_tissue_liability_anchor.py — T3 recomputation anchor for the
normal-tissue-liability card (#2047, batch E).

BOUNDARY (honestly stated): `hpa_normal_tissue_liability.cli.compute_summary(gene, row)` is a
LOOKUP + pure classification over ONE HPA master-TSV row, not an aggregation over many rows — the
per-gene IHC breadth/specificity calls are pathologist-scored and precomputed upstream by HPA itself
(source manifest `hpa-v25-1`); no aggregation arithmetic lives in analysis-methods. This anchor
validates the READ path this reader owns: the gene lookup (`_gene_index` / `_gene_index_default`),
the breadth classification (`classify_breadth`), the tissue-enrichment parse
(`parse_specific_tissues`), the essential/GI-tissue membership test, the antibody-reliability
qualifier, and the `essential_tissue_flag` trichotomy — NOT the upstream IHC scoring itself.

The irreproducible substrate is the target gene's single raw row from the HPA master TSV (the 5
columns `compute_summary` consumes: Gene, Protein tissue distribution, Protein tissue specificity,
Protein tissue specific Intensity, Reliability (IH)). The anchor stores that row (lossless, as
JSON — it is a handful of scalar strings, no parquet needed); the offline test replays it directly
through the REAL `compute_summary(gene, row)` — no S3/zip seam needs mocking since compute_summary
is a pure function of its `row` argument.

Round-trip guard: capture re-runs compute_summary through the captured row and asserts it equals
the live `load_and_classify(gene)` read before writing.

Hits S3, NOT run in CI. Run once with live creds:

    cd <analysis-methods repo>
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        pixi run python tests/calibration/recomputation/capture_hpa_normal_tissue_liability_anchor.py \\
        EPCAM/COADREAD KRAS/COADREAD

Writes into tests/calibration/recomputation/{hpa_normal_liability_rows,anchors}/. Commit the outputs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROWS_DIR = HERE / "hpa_normal_liability_rows"
ANCHORS = HERE / "anchors"

# The fields compute_summary(gene, row) returns — captured verbatim as the anchor's `expected`.
_FIELDS = (
    "normal_tissue_breadth_class",
    "essential_tissue_flag",
    "hpa_tissue_distribution",
    "hpa_tissue_specificity",
    "hpa_ihc_reliability",
    "essential_tissue_low_reliability",
    "n_essential_tissues_with_expression",
    "essential_tissues_flagged",
    "n_specific_tissues",
    "specific_tissues",
    "safety_tissue_flags",
    "method_version",
)


def _md5_of(obj) -> str:
    return hashlib.md5(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()  # noqa: S324


def _read_module():
    import onc_methods.hpa_normal_tissue_liability.cli as cli  # noqa: PLC0415

    return cli


def capture(target: str, indication: str) -> None:
    cli = _read_module()
    sym = target.strip()
    key = sym.upper()

    index = cli._gene_index_default()  # noqa: SLF001 — live process-wide gene index off the HPA TSV
    row = index.get(key)
    if row is None:
        raise SystemExit(f"{sym}: absent from HPA master TSV — no row to anchor")

    live = cli.load_and_classify(sym)
    if live.get("normal_tissue_breadth_class") == "data_unavailable":
        raise SystemExit(f"{target}/{indication}: HPA normal-tissue liability not measurable")

    # Round-trip guard: replay the captured raw row through the REAL compute_summary and confirm it
    # reproduces the live read exactly (no S3/zip seam to mock — compute_summary is pure over `row`).
    recon = cli.compute_summary(sym, dict(row))
    for f in _FIELDS:
        if recon.get(f) != live.get(f):
            raise SystemExit(
                f"{target}/{indication}: round-trip mismatch on {f!r}: {recon.get(f)!r} != {live.get(f)!r} — "
                "the captured row lost information compute_summary consumes"
            )

    ROWS_DIR.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    row_name = f"{sym.lower()}.hpa_normal_tissue_liability.row.json"
    frozen_row = {k: row.get(k) for k in cli.HPA_COLS}
    (ROWS_DIR / row_name).write_text(json.dumps(frozen_row, indent=2, sort_keys=True) + "\n")

    anchor = {
        "target": key,
        "indication": indication.upper(),
        "skill": "tumor-presence",
        "card_id": "normal-tissue-liability",
        "class_field": "normal_tissue_breadth_class",
        "row_fixture": f"hpa_normal_liability_rows/{row_name}",
        "row_md5": _md5_of(frozen_row),
        "expected": {k: recon.get(k) for k in _FIELDS},
        "boundary": (
            "validates the READ path (gene-symbol lookup over the HPA master TSV row index + "
            "breadth classification + tissue-enrichment parse + essential/GI membership test + "
            "antibody-reliability qualifier + essential_tissue_flag trichotomy). The IHC "
            "distribution/specificity/reliability CALLS themselves are precomputed upstream by HPA "
            "(source manifest hpa-v25-1); no aggregation arithmetic exists in analysis-methods."
        ),
        "_captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_provenance": (
            f"live cbg read of hpa-v25-1 (methods.hpa_normal_tissue_liability.cli), gene index row for "
            f"{key!r}; fixture = the single raw HPA row; re-derive with "
            "onc_methods.hpa_normal_tissue_liability.cli.compute_summary(gene, row) directly — no seam mock "
            "needed, compute_summary is pure."
        ),
    }
    anchor_name = f"{sym.lower()}_{indication.lower()}.hpa_normal_tissue_liability.json"
    (ANCHORS / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + hpa_normal_liability_rows/{row_name}")
    print(
        f"  breadth={anchor['expected']['normal_tissue_breadth_class']}  "
        f"essential_flag={anchor['expected']['essential_tissue_flag']}  "
        f"flagged={anchor['expected']['essential_tissues_flagged']}  "
        f"method_version={anchor['expected']['method_version']}"
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
