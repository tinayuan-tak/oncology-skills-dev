"""LIVE capture tool for the tumor-protein-abundance-cptac T3 recomputation anchor (#2045, batch C).

NOT collected by pytest (no ``test_`` prefix): it needs live product reads (AWS ``cbg`` creds); the
committed sibling test ``test_cptac_protein_abundance_recomputation.py`` is fully offline and reads
only the fixtures this tool writes.

tumor-protein-abundance-cptac is the per-INDICATION CPTAC protein tumor-vs-normal card, produced by
``methods.cptac_protein_deg.read.read_target_summary(target, indication)``. Its aggregation is the
INDICATION -> CPTAC-cohort resolution + the representative-cohort pick among the resolved cohorts
(largest |Cohen's d|, the cross-cohort-COMPARABLE axis, #1664 F1), then ``_row_to_summary`` +
``_standardized_effect`` on the picked cohort's row, plus the WITHIN-cohort all-gene effect percentile
(``_allgene_effect_percentile``).

WHAT IT FREEZES (the read-path's irreproducible input), for each anchored (target, indication):
  1. the target's raw per-cohort df rows exactly as ``_load_indexed`` materializes them
     (``df.iloc[i].to_dict()`` for every cohort the target was quantified in) — the substrate the
     representative-cohort pick + row->summary consume — committed as a lossless parquet under
     ``dge_rows/``.
  2. the matched cohort's all-gene ``protein_effect_size`` null (the WITHIN-cohort percentile
     denominator ``_allgene_effect_percentile`` ranks the target against) — committed as a lossless
     parquet (cohort, protein_effect_size) under ``dge_rows/``.

and RE-DERIVES the card summary through the REAL ``read_target_summary`` (monkeypatching only the S3
load seam ``_load_indexed`` to the reconstructed-from-frozen structures) — so the offline test
validates the READ/AGGREGATION path (indication->cohort resolution, representative-cohort pick,
_row_to_summary, _standardized_effect, within-cohort all-gene percentile), NOT the upstream MSstatsTMT
DEG run (that provenance belongs to data-catalog).

WITHIN-COHORT SEMANTICS (#1512/#1664): CPTAC TMT effect sizes are pooled-reference-relative RATIOS.
Every anchored indication here is a LEAF indication -> a SINGLE CPTAC cohort, so the representative-
cohort pick is over one candidate and NO cross-cohort aggregation of non-comparable ratios occurs on
this verdict-bearing path. The #1664-flagged cross-cohort aggregation is confined to the umbrella
(NSCLC->LUAD+LSCC) and indication-FREE pan-cancer paths, where the #1664 F1 fix ranks on the
comparable |Cohen's d| axis. The all-gene percentile is a within-cohort rank (no pooling across
cohorts). Blood-derived-normal folding (#1664 F3) is upstream-by-design; this anchor validates only
what the reader emits.

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

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
AM_ROOT = HERE.parents[2]
if str(AM_ROOT) not in sys.path:
    sys.path.insert(0, str(AM_ROOT))

import methods.cptac_protein_deg.read as cp  # noqa: E402

ANCHOR_DIR = HERE / "anchors"
FIXTURE_DIR = HERE / "dge_rows"

# EPCAM/COADREAD flagship (the only pair with a committed tumor-presence golden to bridge against),
# plus panel targets spanning >=2 protein_expression_class values. All are LEAF indications -> a single
# CPTAC cohort (within-cohort semantics; no cross-cohort aggregation on this path).
TARGETS: tuple[tuple[str, str], ...] = (
    ("EPCAM", "COADREAD"),
    ("ERBB2", "BRCA"),
    ("KRAS", "COADREAD"),
    ("TACSTD2", "COADREAD"),
)

# The full card summary field set read_target_summary emits (via _row_to_summary + _standardized_effect).
_CARD_FIELDS = (
    "cohort",
    "protein_expression_class",
    "protein_contrast_estimable",
    "protein_effect_size",
    "allgene_percentile",
    "allgene_percentile_class",
    "allgene_percentile_context",
    "protein_bh_q_value",
    "protein_p_value",
    "protein_median_log2_tumor",
    "protein_median_log2_normal",
    "n_tumor_samples",
    "n_normal_samples",
    "protein_effect_size_se",
    "protein_effect_standardized_t",
    "protein_effect_cohens_d",
    "protein_effect_standardized_class",
    "protein_effect_standardized_method",
    "stat_test_used",
    "method_version",
    "_data_source",
)


def _coerce(v):
    """numpy/pandas scalar -> plain python (NaN/None preserved). Lossless for the fields the reader
    consumes."""
    if v is None:
        return None
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return item()
        except (ValueError, TypeError):
            return v
    return v


def _rederive_target_summary(
    target_rows: list[dict], matched_cohort: str, null_effects: list, target: str, indication: str
) -> dict:
    """Re-derive read_target_summary(target, indication) OFFLINE by reconstructing the (df,
    cohort_gene_idx, gene_idx, cohort_effect_null) tuple _load_indexed returns — from the frozen
    target rows + matched-cohort all-gene null — and monkeypatching ONLY that S3-load seam. Every
    downstream step (indication->cohort resolution, representative-cohort pick, _row_to_summary,
    _standardized_effect, _allgene_effect_percentile) runs unmodified.

    Reconstruction mirrors _load_indexed's own indexing exactly (str().strip().upper() keys).

    IDENTICAL to the helper in test_cptac_protein_abundance_recomputation.py — the capture-time
    fidelity guard proves it reproduces the live read; the offline test replays it against the same
    frozen bytes.
    """
    from unittest import mock

    import pandas as pd

    df = pd.DataFrame(target_rows)
    cohort_gene_idx: dict[tuple, int] = {}
    gene_idx: dict[str, list[int]] = {}
    cohort_col = df["cohort"].values
    gene_col = df["gene_symbol"].values
    for idx in range(len(df)):
        cohort = str(cohort_col[idx]).strip().upper()
        gene = str(gene_col[idx]).strip().upper()
        if not cohort or not gene:
            continue
        cohort_gene_idx[(cohort, gene)] = idx
        gene_idx.setdefault(gene, []).append(idx)
    cohort_effect_null = {matched_cohort.strip().upper(): list(null_effects)}
    with mock.patch.object(cp, "_load_indexed", lambda: (df, cohort_gene_idx, gene_idx, cohort_effect_null)):
        return cp.read_target_summary(target, indication)


def _write_parquet(name: str, table: pa.Table) -> tuple[str, str]:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / name
    pq.write_table(table, path)
    rel = str(path.relative_to(HERE))
    return rel, hashlib.md5(path.read_bytes()).hexdigest()


def main() -> None:
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    df, cohort_gene_idx, gene_idx, cohort_effect_null = cp._load_indexed()
    if df is None or df.empty:
        raise SystemExit("ABORT: CPTAC per-cohort product unavailable (empty df) — cannot capture anchors")

    classes: set[str] = set()
    n_written = 0

    for target, indication in TARGETS:
        sym = target.upper().strip()
        live = cp.read_target_summary(target, indication)
        matched_cohort = live.get("cohort")
        if matched_cohort is None or live.get("protein_expression_class") == "data_unavailable":
            print(f"SKIP {target}/{indication}: {live.get('protein_expression_class')}", file=sys.stderr)
            continue

        # Freeze the target's raw per-cohort df rows (every cohort it was quantified in) + the matched
        # cohort's all-gene effect null.
        idxs = gene_idx.get(sym, [])
        target_rows = [{k: _coerce(v) for k, v in df.iloc[i].to_dict().items()} for i in idxs]
        null_effects = [_coerce(v) for v in cohort_effect_null.get(matched_cohort.strip().upper(), [])]
        if not target_rows or not null_effects:
            print(f"SKIP {target}/{indication}: empty rows/null", file=sys.stderr)
            continue

        rows_rel, rows_md5 = _write_parquet(
            f"{target.lower()}.cptac_target_rows.parquet", pa.Table.from_pylist(target_rows)
        )
        null_rel, null_md5 = _write_parquet(
            f"{target.lower()}_{matched_cohort.lower()}.cptac_allgene_effect_null.parquet",
            pa.Table.from_pydict(
                {"cohort": [matched_cohort.strip().upper()] * len(null_effects), "protein_effect_size": null_effects}
            ),
        )

        # Fidelity guard: re-derive from the RELOADED frozen bytes (proves the parquet round-trip is
        # lossless) and require it to equal the live read on every emitted field.
        reloaded_rows = pq.read_table(FIXTURE_DIR / f"{target.lower()}.cptac_target_rows.parquet").to_pylist()
        reloaded_null = (
            pq.read_table(FIXTURE_DIR / f"{target.lower()}_{matched_cohort.lower()}.cptac_allgene_effect_null.parquet")
            .column("protein_effect_size")
            .to_pylist()
        )
        off = _rederive_target_summary(reloaded_rows, matched_cohort, reloaded_null, target, indication)
        for f in _CARD_FIELDS:
            if off.get(f) != live.get(f):
                raise SystemExit(
                    f"ABORT [{target}/{indication}] offline re-derivation != live on {f!r}: "
                    f"{off.get(f)!r} != {live.get(f)!r} — the frozen rows/null lost information"
                )

        classes.add(live["protein_expression_class"])
        anchor = {
            "target": target,
            "indication": indication,
            "matched_cohort": matched_cohort,
            "product_id": cp.DERIVED_MANIFEST_ID,
            "reader": "methods.cptac_protein_deg.read.read_target_summary(target, indication)",
            "target_rows_fixture": rows_rel,
            "target_rows_fixture_md5": rows_md5,
            "allgene_effect_null_fixture": null_rel,
            "allgene_effect_null_fixture_md5": null_md5,
            "n_cohort_rows": len(target_rows),
            "n_allgene_null": len(null_effects),
            "expected": {f: live.get(f) for f in _CARD_FIELDS},
            "_source": {
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "boundary": (
                    "validates the read/aggregation path (indication->CPTAC-cohort resolution, the "
                    "representative-cohort pick on the |Cohen's d| axis, _row_to_summary, "
                    "_standardized_effect, and the WITHIN-cohort all-gene effect percentile), NOT the "
                    "upstream MSstatsTMT DEG run. #1664/#1512: CPTAC TMT effect sizes are pooled-"
                    "reference-relative ratios; every anchored indication is a LEAF -> a single cohort, "
                    "so no cross-cohort aggregation of non-comparable ratios occurs on this path. The "
                    "all-gene percentile is a within-cohort rank."
                ),
            },
        }
        (ANCHOR_DIR / f"{target.lower()}_{matched_cohort.lower()}.cptac_protein_abundance.json").write_text(
            json.dumps(anchor, indent=2) + "\n"
        )
        n_written += 1
        print(
            f"  {target:8}/{indication:9} cohort={matched_cohort:6} class={live['protein_expression_class']:15} "
            f"effect={live['protein_effect_size']:+.4f} pctile={live['allgene_percentile']}"
        )

    print(f"wrote {n_written} anchor(s); protein_expression_class spanned ({len(classes)}): {sorted(classes)}")
    if n_written < 2:
        raise SystemExit(f"ABORT: only {n_written} anchor(s) written; need >= 2 (EPCAM + >=1 other)")
    if len(classes) < 2:
        raise SystemExit(f"ABORT: anchor set spans only {len(classes)} protein_expression_class(es); need >= 2")


if __name__ == "__main__":
    main()
