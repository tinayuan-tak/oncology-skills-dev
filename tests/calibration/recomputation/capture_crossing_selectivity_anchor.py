"""LIVE capture tool for the tumor-vs-normal percentile-crossing T3 recomputation anchor.

NOT collected by pytest (no ``test_`` prefix): it needs live recount3/GTEx expression (AWS ``cbg``
creds); the committed sibling test ``test_crossing_selectivity_recomputation.py`` is fully offline and
reads only the fixtures this tool writes.

What it freezes — the IRREPRODUCIBLE input: for each (target, indication) anchor, the per-sample tumor
log2(TPM+1) vector (recount3 TCGA / non-TCGA long product, restricted to the indication's studies) AND
the per-sample matched-normal GTEx log2(TPM+1) vector for the indication's tissue-of-origin. Those two
per-sample matrices cannot be reconstructed offline. From them the tool re-derives the
tumor-vs-normal-percentile-crossing card's summary fields through the REAL library entry point
``read_tumor_vs_normal_percentile_crossing`` and records them as the anchor's expected values.

Two independent guards make the anchor honest before it is committed:
  1. FIDELITY — the offline re-derivation (frozen vectors, monkeypatched sample readers) must reproduce
     the LIVE compute exactly; if the frozen slice lost information the classifier uses, it aborts.
  2. CROSS-REPO — for every anchor the tumor-selectivity calibration roster records, the re-derived
     ``selectivity_class`` must equal that snapshot's independently-captured ``percentile_crossing_class``
     (the same value under its headline name); a drift aborts rather than silently re-baselining.

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

import methods.tcga_gtex_expression_distribution.read as rd  # noqa: E402

FIXTURE_REL = "tumor_normal_tpm/recount3_gtex__percentile_crossing_vectors.parquet"
ANCHOR_DIR = HERE / "anchors"

# Anchor (target, indication) pairs. ALL ten are the tumor-selectivity calibration roster's own pairs (so
# the choice is grounded in the committed roster, not invented) and ALL ten carry a
# `percentile_crossing_class` headline, so every anchor is cross-referenced. The set is designed to span
# >= 3 selectivity_class branches; the actual classes are whatever the real compute returns and are
# asserted non-vacuous below, never assumed. Live probe (2026-09-21): not_enriched (APC), enriched_subset
# (ERBB2, KLK3), strongly_tumor_enriched (CEACAM5/EPCAM/FOLR1/MET/MSLN/TACSTD2), data_unavailable (DLL3 —
# SCLC has no matched GTEx normal).
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

CONTRACTS_ROOT = AM_ROOT.parent / "rnd-computational-biology-oncology-target-contracts"
SNAPSHOT_DIR = CONTRACTS_ROOT / "tests" / "calibration" / "snapshots"

# The fields this anchor re-derives (all produced by read_tumor_vs_normal_percentile_crossing). The two
# normal_pN fields are absent from the data_unavailable branch, so they are read with .get().
_FIELDS = (
    "selectivity_class",
    "n_tumor_samples",
    "n_normal_samples",
    "matched_normal_tissue",
    "fraction_tumor_above_normal_p95",
    "fraction_tumor_above_normal_p99",
    "distribution_overlap_tumor_normal",
    "normal_p95_log2tpm",
    "normal_p99_log2tpm",
)


def _live_load() -> dict:
    """Live-read each anchor's per-sample tumor + matched-normal vectors and the live summary."""
    out: dict[tuple[str, str], dict] = {}
    for target, indication in ANCHORS:
        tumor = rd.read_tumor_samples(target, indication)
        normal, tissue = rd.read_normal_samples(target, indication)
        if not tumor:
            raise SystemExit(
                f"ABORT: {target}-{indication} has no tumor samples — confirm HGNC symbol / indication mapping"
            )
        live_summary = rd.read_tumor_vs_normal_percentile_crossing(target, indication)
        out[(target, indication)] = {
            "tumor": [float(x) for x in tumor],
            "normal": [float(x) for x in normal],
            "tissue": tissue,
            "live_summary": live_summary,
        }
    return out


def _offline_rederive(target: str, indication: str, tumor: list, normal: list, tissue) -> dict:
    """Re-derive through the REAL read_tumor_vs_normal_percentile_crossing using ONLY the frozen vectors —
    the identical seam the committed offline test uses. read_tumor_samples → the frozen tumor list;
    read_normal_samples → (frozen normal list, frozen tissue)."""
    with (
        mock.patch.object(rd, "read_tumor_samples", lambda t, i: list(tumor)),
        mock.patch.object(rd, "read_normal_samples", lambda t, i: (list(normal), tissue)),
    ):
        return rd.read_tumor_vs_normal_percentile_crossing(target, indication)


def _snapshot_class(target: str, indication: str) -> dict | None:
    """The roster snapshot's headline percentile_crossing_class — the same value my selectivity_class
    carries, under its downstream name."""
    path = SNAPSHOT_DIR / f"{target.lower()}_{indication.lower()}.tumor-selectivity.json"
    if not path.exists():
        return None
    headline = json.loads(path.read_text()).get("headline", {})
    if "percentile_crossing_class" not in headline:
        return None
    return {
        "source": str(path.relative_to(CONTRACTS_ROOT.parent)),
        "percentile_crossing_class": headline["percentile_crossing_class"],
    }


def main() -> None:
    live = _live_load()

    # --- write the frozen slice: one row per (target, indication, cohort, sample) ---
    rows_t, rows_i, rows_c, rows_v = [], [], [], []
    for (target, indication), rec in live.items():
        for v in rec["tumor"]:
            rows_t.append(target)
            rows_i.append(indication)
            rows_c.append("tumor")
            rows_v.append(v)
        for v in rec["normal"]:
            rows_t.append(target)
            rows_i.append(indication)
            rows_c.append("normal")
            rows_v.append(v)
    table = pa.table(
        {
            "target": pa.array(rows_t, pa.string()),
            "indication": pa.array(rows_i, pa.string()),
            "cohort": pa.array(rows_c, pa.string()),
            "log2_tpm": pa.array(rows_v, pa.float64()),
        }
    )
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
        tumor, normal, tissue = rec["tumor"], rec["normal"], rec["tissue"]
        live_summary = rec["live_summary"]

        # GUARD 1 (fidelity): the offline re-derivation from the frozen vectors must reproduce live exactly.
        off = _offline_rederive(target, indication, tumor, normal, tissue)
        for f in _FIELDS:
            if off.get(f) != live_summary.get(f):
                raise SystemExit(
                    f"ABORT [{target}-{indication}]: offline slice re-derivation != live compute on {f!r}: "
                    f"{off.get(f)!r} != {live_summary.get(f)!r} — the frozen slice lost information"
                )

        # GUARD 2 (cross-repo): the roster snapshot's percentile_crossing_class must equal the re-derived
        # selectivity_class — two independent records of the same categorical.
        snap = _snapshot_class(target, indication)
        if snap is not None and snap["percentile_crossing_class"] != off["selectivity_class"]:
            raise SystemExit(
                f"ABORT [{target}-{indication}]: re-derived selectivity_class={off['selectivity_class']!r} "
                f"disagrees with committed snapshot {snap['source']} percentile_crossing_class="
                f"{snap['percentile_crossing_class']!r} — investigate drift, do not re-baseline"
            )

        classes.add(off["selectivity_class"])
        anchor = {
            "target": target,
            "indication": indication,
            "vectors_fixture": FIXTURE_REL,
            "matched_normal_tissue": off["matched_normal_tissue"],
            "n_tumor_samples": off["n_tumor_samples"],
            "n_normal_samples": off["n_normal_samples"],
            "expected_selectivity_class": off["selectivity_class"],
            "expected_fraction_tumor_above_normal_p95": off["fraction_tumor_above_normal_p95"],
            "expected_fraction_tumor_above_normal_p99": off["fraction_tumor_above_normal_p99"],
            "expected_normal_p95_log2tpm": off.get("normal_p95_log2tpm"),
            "expected_normal_p99_log2tpm": off.get("normal_p99_log2tpm"),
            "expected_distribution_overlap_tumor_normal": off["distribution_overlap_tumor_normal"],
            "snapshot_cross_ref": snap,
            "_source": {
                "product": "recount3 TCGA/non-TCGA tumor long product + GTEx matched-normal (recount3/GENCODE-v26)",
                "captured_utc": captured_utc,
                "vectors_fixture_md5": md5,
            },
        }
        (ANCHOR_DIR / f"{target.lower()}_{indication.lower()}.percentile_crossing.json").write_text(
            json.dumps(anchor, indent=2) + "\n"
        )
        fp95 = off["fraction_tumor_above_normal_p95"]
        ov = off["distribution_overlap_tumor_normal"]
        print(
            f"  {target:8} {indication:8} nT={off['n_tumor_samples']:>4} nN={off['n_normal_samples']:>4} "
            f"fp95={('%.4f' % fp95) if fp95 is not None else 'None':>7} "
            f"ov={('%.4f' % ov) if ov is not None else 'None':>7} "
            f"class={off['selectivity_class']}{' [x-ref roster]' if snap else ''}"
        )
    print(f"classes spanned ({len(classes)}): {sorted(classes)}")
    if len(classes) < 3:
        raise SystemExit(f"ABORT: anchor set spans only {len(classes)} selectivity_class branch(es); need >= 3")

    # Anti-vacuity for GUARD 2 itself: at least one anchor must cross-check against a roster snapshot. If
    # NONE did, the target-contracts sibling is unreachable (a missing symlink) and the cross-repo guard
    # silently did nothing — refuse to ship a toothless anchor rather than record every cross_ref as null.
    n_xref = sum(1 for t, i in ANCHORS if _snapshot_class(t, i) is not None)
    if n_xref == 0:
        raise SystemExit(
            "ABORT: no anchor cross-checked against a roster percentile_crossing_class — the target-contracts "
            "sibling is unreachable, so GUARD 2 never ran. Symlink it beside the worktree and re-capture."
        )
    print(f"cross-referenced against roster: {n_xref} anchor(s)")


if __name__ == "__main__":
    main()
