"""dge_deseq2.build_qc_index — cross-indication QC index over the per-run bundles.

S3b (github analysis-methods#702). The R drivers (06 whole-cohort, 07 stratified)
emit, for every DE performed, a per-run QC bundle beside that contrast's parquet:

    <run-out-dir>/qc/<cell>/figures/*.png
    <run-out-dir>/qc/<cell>/metrics.csv
    <run-out-dir>/qc/qc_summary.csv          # one row per cell that ran in the run

This module concatenates the per-run ``qc_summary.csv`` files found under a set of
roots into a single cross-indication index table (``qc_index.parquet``), so the
whole corpus's DE QC is inspectable in one place. It is pure compute (glob + read
+ concat), not orchestration — hence it lives in the method package.

The index is *reconciled by count*: :func:`build_qc_index` records, per source
summary file, how many rows it contributed, and the CLI reports the totals so a
silently-empty run (a summary that produced zero rows) is visible rather than
absorbed. This is the same anti-"green-on-empty" discipline the R bundle uses.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

QC_SUMMARY_NAME = "qc_summary.csv"

# The columns each per-run summary row carries (mirror four_cell_summary_row in
# r/live/_qc_figures.R). Used to validate a summary is well-formed before it is
# folded into the index — a truncated / header-only file is rejected, not merged.
EXPECTED_COLUMNS = (
    "indication",
    "substrate",
    "cell",
    "n_tumor",
    "n_normal",
    "genes_pre_filter",
    "genes_post_filter",
    "n_filtered_indep",
    "n_filtered_cooks",
    "n_sig_fdr05",
    "n_sig_fdr10",
    "median_abs_lfc_sig",
    "size_factor_min",
    "size_factor_max",
    "size_factor_ratio",
    "n_tested",
    "n_figures",
    "figures",
)


def find_qc_summaries(roots: list[Path]) -> list[Path]:
    """Return every ``qc_summary.csv`` under any of ``roots`` (recursive), sorted.

    Both driver layouts are covered by the recursive search: 06 writes
    ``<out>/qc/qc_summary.csv`` and 07 writes ``<out>/_strat_<s>/qc/qc_summary.csv``.
    """
    found: set[Path] = set()
    for root in roots:
        root = Path(root)
        if root.is_file() and root.name == QC_SUMMARY_NAME:
            found.add(root.resolve())
            continue
        if not root.is_dir():
            continue
        found.update(p.resolve() for p in root.rglob(QC_SUMMARY_NAME))
    return sorted(found)


def _read_one_summary(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path}: QC summary is missing required column(s) {missing}; it is not a valid four_cell_summary_row table"
        )
    # Provenance: which per-run summary each index row came from.
    df = df.copy()
    df.insert(0, "source_summary", str(path))
    return df


def build_qc_index(summary_paths: list[Path]) -> pd.DataFrame:
    """Concatenate per-run QC summaries into one cross-indication index frame.

    Raises if ``summary_paths`` is empty (an index built from nothing is a defect,
    not an empty success) or if any summary contributes zero rows (a header-only
    file that would be silently absorbed).
    """
    if not summary_paths:
        raise ValueError(
            "build_qc_index: no qc_summary.csv files given — refusing to build an "
            "empty index (did the driver emit any QC bundles?)"
        )
    frames = []
    for path in summary_paths:
        df = _read_one_summary(Path(path))
        if len(df) == 0:
            raise ValueError(
                f"{path}: QC summary has zero rows — a run that emitted a "
                "header-only summary is a defect, not an empty index contribution"
            )
        frames.append(df)
    index = pd.concat(frames, ignore_index=True)
    index = index.sort_values(["indication", "substrate", "cell"]).reset_index(drop=True)
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the cross-indication DGE QC index from per-run qc_summary.csv files."
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="One or more directories to search recursively for qc_summary.csv (or the files themselves).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path to write the qc_index.parquet.",
    )
    args = parser.parse_args(argv)

    summaries = find_qc_summaries(args.roots)
    if not summaries:
        print(
            f"[build_qc_index] no {QC_SUMMARY_NAME} found under: " + ", ".join(str(r) for r in args.roots),
            file=sys.stderr,
        )
        return 1
    index = build_qc_index(summaries)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    index.to_parquet(args.out, index=False)
    print(f"[build_qc_index] wrote {args.out}: {len(index)} contrast row(s) from {len(summaries)} run summary file(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
