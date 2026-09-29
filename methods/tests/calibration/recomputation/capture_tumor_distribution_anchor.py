"""LIVE capture tool for the tumor-rna-distribution T3 recomputation anchor.

NOT collected by pytest (no ``test_`` prefix): it needs live recount3 expression (AWS ``cbg``
creds); the committed sibling test ``test_tumor_distribution_recomputation.py`` is fully offline
and reads only the fixtures this tool (and the earlier percentile-crossing capture) wrote.

REUSES the tumor-vs-normal-percentile-crossing anchor's own frozen input rather than minting a new
parquet: ``read_tumor_expression_distribution`` (the tumor-rna-distribution card's assembler) calls
the SAME ``read_tumor_samples`` per-sample reader as ``read_tumor_vs_normal_percentile_crossing`` —
the irreproducible slice is identical, only the downstream classifier differs (tumor-only
distribution shape/fractions vs a tumor-vs-normal contrast). So this tool does not freeze a second
copy of the tumor vector; it points its anchor's ``vectors_fixture`` at the ALREADY-COMMITTED
``tumor_normal_tpm/recount3_gtex__percentile_crossing_vectors.parquet`` and stores only the
tumor-rna-distribution card's own expected fields.

Guard (fidelity): the offline re-derivation from the frozen tumor vector (monkeypatched
``read_tumor_samples``) must reproduce the LIVE ``read_tumor_expression_distribution`` call exactly
on every distribution field; if the frozen slice lost information the classifier uses, it aborts.
(allgene_percentile / control_position are separate live products this tool does not freeze — the
card treats them as additive/display and degrades to data_unavailable offline; this anchor does not
assert on them.)

Run:
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        PYTHONPATH=<analysis-methods-root> python3 <this file>
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
AM_ROOT = HERE.parents[2]
if str(AM_ROOT) not in sys.path:
    sys.path.insert(0, str(AM_ROOT))

import methods.tcga_gtex_expression_distribution.read as rd  # noqa: E402

ANCHOR_DIR = HERE / "anchors"
VECTORS_FIXTURE = "tumor_normal_tpm/recount3_gtex__percentile_crossing_vectors.parquet"

# Same roster as the percentile-crossing anchors (the substrate is shared) — reuse every pair that
# has tumor samples (DLL3-SCLC has no matched normal but DOES have a tumor vector, so it is included
# here even though it is excluded from the selectivity roster for the normal-comparison card).
ANCHORS = [
    ("APC", "COADREAD"),
    ("CEACAM5", "COADREAD"),
    ("DLL3", "SCLC"),
    ("EPCAM", "COADREAD"),
    ("ERBB2", "BRCA"),
    ("FOLR1", "OV"),
    ("KLK3", "PRAD"),
    ("MET", "COADREAD"),
    ("MSLN", "PAAD"),
    ("TACSTD2", "COADREAD"),
]

_FIELDS = (
    "tumor_expression_class",
    "n_tumor_samples",
    "median_log2tpm",
    "p95_log2tpm",
    "p99_log2tpm",
    "min_log2tpm",
    "max_log2tpm",
    "coefficient_of_variation",
    "distribution_pattern",
    "detectable_fraction",
    "moderate_fraction",
    "high_fraction",
)


def _load_tumor_vector(target: str, indication: str) -> list[float]:
    table = pq.read_table(HERE / VECTORS_FIXTURE).to_pydict()
    out = []
    for t, i, cohort, val in zip(table["target"], table["indication"], table["cohort"], table["log2_tpm"], strict=True):
        if t == target and i == indication and cohort == "tumor":
            out.append(float(val))
    return out


def _offline_rederive(target: str, indication: str, tumor: list) -> dict:
    with mock.patch.object(rd, "read_tumor_samples", lambda t, i: list(tumor)):
        return rd.read_tumor_expression_distribution(target, indication)


def main() -> None:
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    classes: set[str] = set()
    n_written = 0
    for target, indication in ANCHORS:
        live_summary = rd.read_tumor_expression_distribution(target, indication)
        if live_summary.get("tumor_expression_class") == "data_unavailable":
            print(f"SKIP {target}-{indication}: live read is data_unavailable", file=sys.stderr)
            continue

        frozen_tumor = _load_tumor_vector(target, indication)
        if not frozen_tumor:
            raise SystemExit(
                f"ABORT [{target}-{indication}]: no frozen tumor vector in {VECTORS_FIXTURE} — capture the "
                "percentile-crossing anchor for this pair first (capture_crossing_selectivity_anchor.py)"
            )
        if len(frozen_tumor) != live_summary["n_tumor_samples"]:
            raise SystemExit(
                f"ABORT [{target}-{indication}]: frozen tumor vector n={len(frozen_tumor)} != live "
                f"n_tumor_samples={live_summary['n_tumor_samples']} — the frozen slice does not match live"
            )

        off = _offline_rederive(target, indication, frozen_tumor)
        for f in _FIELDS:
            if off.get(f) != live_summary.get(f):
                raise SystemExit(
                    f"ABORT [{target}-{indication}]: offline slice re-derivation != live compute on {f!r}: "
                    f"{off.get(f)!r} != {live_summary.get(f)!r} — the frozen slice lost information"
                )

        classes.add(off["tumor_expression_class"])
        anchor = {
            "target": target,
            "indication": indication,
            "vectors_fixture": VECTORS_FIXTURE,
            "vectors_fixture_cohort": "tumor",
            "n_tumor_samples": off["n_tumor_samples"],
            "expected_tumor_expression_class": off["tumor_expression_class"],
            "expected_median_log2tpm": off["median_log2tpm"],
            "expected_p95_log2tpm": off["p95_log2tpm"],
            "expected_p99_log2tpm": off["p99_log2tpm"],
            "expected_min_log2tpm": off["min_log2tpm"],
            "expected_max_log2tpm": off["max_log2tpm"],
            "expected_coefficient_of_variation": off["coefficient_of_variation"],
            "expected_distribution_pattern": off["distribution_pattern"],
            "expected_detectable_fraction": off["detectable_fraction"],
            "expected_moderate_fraction": off["moderate_fraction"],
            "expected_high_fraction": off["high_fraction"],
            "_source": {
                "product": "recount3 TCGA/non-TCGA tumor long product (same slice as the "
                "percentile_crossing anchor for this pair)",
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "note": "reuses the percentile_crossing anchor's committed vectors_fixture; no new parquet",
            },
        }
        (ANCHOR_DIR / f"{target.lower()}_{indication.lower()}.tumor_rna_distribution.json").write_text(
            json.dumps(anchor, indent=2) + "\n"
        )
        n_written += 1
        print(
            f"  {target:8} {indication:8} n={off['n_tumor_samples']:>4} "
            f"median={off['median_log2tpm']:.4f} class={off['tumor_expression_class']}"
        )
    print(f"wrote {n_written} anchor(s); classes spanned ({len(classes)}): {sorted(classes)}")
    if n_written < 2:
        raise SystemExit(f"ABORT: only {n_written} anchor(s) written; need >= 2 (EPCAM/COADREAD + >=1 other)")
    if len(classes) < 2:
        raise SystemExit(f"ABORT: anchor set spans only {len(classes)} tumor_expression_class branch(es); need >= 2")


if __name__ == "__main__":
    main()
