#!/usr/bin/env python3
"""capture_hpa_pathology_ihc_anchor.py — T3 recomputation anchor for the hpa-pathology-cancer-ihc
card (#2046, batch D).

BOUNDARY (honestly stated): read.read_target_summary(target, indication) is a LOOKUP, not an
aggregation. The per-(gene, cancer_type) patient-count aggregation (n_high/n_medium/n_low ->
fraction_detected / staining_score / protein_presence_class) is precomputed at BUILD time in the
data-catalog product hpa-pathology-cancer-ihc-per-gene-v1; NO aggregation arithmetic lives in
analysis-methods (the module is __init__.py + read.py only). So this anchor validates the READ path
this reader owns — the OncoTree->HPA cancer-type resolution (INDICATION_TO_HPA_CANCER), the
gene-symbol predicate pushdown, the cancer_type row selection, the field projection, and the
absence-safety — NOT the upstream patient-count aggregation (that belongs to data-catalog).

The irreproducible substrate is the set of per-cancer-type rows the product holds for the target
gene (all ~20 HPA cancer types). The anchor stores those rows (lossless); the offline test replays
them through read_target_summary by monkeypatching the S3 read seam (pyarrow.parquet.read_table +
_get_s3fs), so the reader's real resolution + selection + projection runs offline.

Round-trip guard: capture re-runs read_target_summary through the reconstructed rows (the exact mock
the offline test uses) and asserts it equals the live read before writing.

Hits S3, NOT run in CI. Run once with live creds:

    cd <analysis-methods repo>
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        pixi run python tests/calibration/recomputation/capture_hpa_pathology_ihc_anchor.py \\
        EPCAM/COADREAD KRAS/COADREAD

Writes into tests/calibration/recomputation/{hpa_ihc_rows,anchors}/. Commit the outputs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROWS_DIR = HERE / "hpa_ihc_rows"
ANCHORS = HERE / "anchors"

_FIELDS = (
    "protein_presence_class",
    "fraction_detected",
    "fraction_moderate_strong",
    "staining_score",
    "n_high",
    "n_medium",
    "n_low",
    "n_not_detected",
    "n_patients_total",
    "prognostic_type",
    "prognostic_is_significant",
    "prognostic_p_value",
    "hpa_cancer_type",
)


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — fixture drift guard, not security


def _read_module():
    import onc_methods.hpa_pathology_cancer_ihc.read as hp  # noqa: PLC0415

    return hp


def _make_replay(local_parquet: Path):
    """Return a read_table replacement that serves the committed local parquet through the reader's
    real column-projection + gene predicate, delegating to the genuine pyarrow read_table."""
    import pyarrow.parquet as pq

    orig = pq.read_table

    def _replay(_uri, filesystem=None, columns=None, filters=None):  # noqa: ARG001
        return orig(str(local_parquet), columns=columns, filters=filters)

    return _replay


def capture(target: str, indication: str) -> None:
    import pyarrow.parquet as pq

    hp = _read_module()
    sym = target.upper().strip()
    # Fetch ALL per-cancer-type rows for the gene (superset of the reader's projection + gene_symbol
    # so the offline replay can honor the pushdown predicate).
    cols = list(hp._READ_COLUMNS) + ["gene_symbol"]  # noqa: SLF001
    uri = f"{hp.S3_BUCKET}/{hp.DERIVED_S3_KEY}"
    tbl = pq.read_table(uri, filesystem=hp._get_s3fs(), columns=cols, filters=[("gene_symbol", "=", sym)])  # noqa: SLF001
    if tbl.num_rows == 0:
        raise SystemExit(f"{sym}: absent from HPA pathology product")

    live = hp.read_target_summary(target, indication)
    if live.get("protein_presence_class") in (None, "data_unavailable"):
        raise SystemExit(f"{target}/{indication}: HPA IHC not measurable ({live.get('protein_presence_class')})")

    ROWS_DIR.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    rows_name = f"{target.lower()}.hpa_pathology_cancer_ihc.rows.parquet"
    pq.write_table(tbl, ROWS_DIR / rows_name)

    # Round-trip guard: replay the committed rows through the real read_target_summary (mock the S3
    # read seam) and confirm it reproduces the live read.
    with (
        mock.patch.object(hp, "_get_s3fs", lambda: None),
        mock.patch("pyarrow.parquet.read_table", _make_replay(ROWS_DIR / rows_name)),
    ):
        recon = hp.read_target_summary(target, indication)
    for k in _FIELDS:
        assert recon.get(k) == live.get(k), (
            f"{target}/{indication}: HPA round-trip mismatch on {k}: {recon.get(k)!r} != {live.get(k)!r}"
        )

    anchor = {
        "target": sym,
        "indication": indication.upper(),
        "skill": "tumor-presence",
        "card_id": "hpa-pathology-cancer-ihc",
        "class_field": "protein_presence_class",
        "rows_fixture": f"hpa_ihc_rows/{rows_name}",
        "rows_md5": _md5(ROWS_DIR / rows_name),
        "n_cancer_type_rows": int(tbl.num_rows),
        "hpa_cancer_type": live["hpa_cancer_type"],
        "expected": {k: live.get(k) for k in _FIELDS},
        "boundary": (
            "validates the READ path (OncoTree->HPA cancer-type resolution + gene predicate pushdown + "
            "cancer_type row selection + field projection). The n_*/fraction/protein_presence_class "
            "aggregation is precomputed upstream in data-catalog's hpa-pathology-cancer-ihc-per-gene-v1 "
            "build; no aggregation arithmetic exists in analysis-methods."
        ),
        "_captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_provenance": (
            f"live cbg read of hpa-pathology-cancer-ihc-per-gene-v1 filtered to gene_symbol=={sym!r}; fixture = "
            "the per-cancer-type rows for the gene; re-derive with "
            "onc_methods.hpa_pathology_cancer_ihc.read.read_target_summary (mock the pyarrow read_table seam)."
        ),
    }
    anchor_name = f"{target.lower()}_{indication.lower()}.hpa_pathology_cancer_ihc.json"
    (ANCHORS / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + hpa_ihc_rows/{rows_name}")
    print(
        f"  class={anchor['expected']['protein_presence_class']}  frac_detected={anchor['expected']['fraction_detected']}  "
        f"staining={anchor['expected']['staining_score']}  n_patients={anchor['expected']['n_patients_total']}  "
        f"hpa_type={anchor['hpa_cancer_type']!r}  n_rows={anchor['n_cancer_type_rows']}"
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
