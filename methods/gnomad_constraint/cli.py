"""gnomad_constraint.cli — loader + deterministic constraint classifier + CLI.

Source: gnomad-constraint-snapshot-2026-07-02 (data-catalog), file
`gnomad.v4.1.constraint_metrics.tsv` (gene+transcript, ~19,700 genes). Per-gene
representative row = canonical OR mane_select. Emits the card contract fields for
`gnomad-lof-constraint` (constraint_class + pLI/LOEUF/mis_z/syn_z/obs_lof/exp_lof).

Thresholds are the card's (target-contracts/cards/gnomad-lof-constraint.card.yaml):
  high_pli 0.9 / high_loeuf 0.35 ; moderate_pli 0.5 / moderate_loeuf 0.6.
LOEUF is the primary metric (Karczewski 2020); pLI corroborates.
"""

from __future__ import annotations

import os
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for

METHOD_VERSION = "0.1.0"

# --- source location (landed manifest gnomad-constraint-snapshot-2026-07-02) ---
SOURCE_MANIFEST_ID = "gnomad-constraint-snapshot-2026-07-02"
# bucket + key resolved from the data-catalog manifest (single source of truth);
# was a hand-typed literal with no manifest_id constant to tie it back.
S3_BUCKET, _SOURCE_PREFIX = bucket_prefix_for(SOURCE_MANIFEST_ID)
S3_KEY = f"{_SOURCE_PREFIX}gnomad.v4.1.constraint_metrics.tsv"
DEFAULT_AWS_PROFILE = "cbg"

# --- v4.1 column names (per the source manifest content-schema) ---
COL_GENE = "gene"
COL_CANONICAL = "canonical"
COL_MANE = "mane_select"
COL_PLI = "lof.pLI"
COL_LOEUF = "lof.oe_ci.upper"      # this IS LOEUF in v4.1
COL_MIS_Z = "mis.z_score"
COL_SYN_Z = "syn.z_score"
COL_OBS_LOF = "lof.obs"
COL_EXP_LOF = "lof.exp"

# --- card thresholds ---
HIGH_PLI, HIGH_LOEUF = 0.9, 0.35
MOD_PLI, MOD_LOEUF = 0.5, 0.6


def classify_constraint(pli: Optional[float], loeuf: Optional[float]) -> str:
    """Map (pLI, LOEUF) → constraint_class per the card vocabulary.

    Vocabulary: highly_constrained | moderately_constrained | tolerant | indeterminate.
    LOEUF is primary; a gene qualifies for a band if EITHER metric clears it (LOEUF
    preferred, pLI corroborating), so an outlier-missing metric doesn't silently
    downgrade a genuinely constrained gene. `indeterminate` = neither metric present
    (gene absent from the constraint table / filtered).
    """
    if pli is None and loeuf is None:
        return "indeterminate"
    high = (loeuf is not None and loeuf <= HIGH_LOEUF) or (pli is not None and pli >= HIGH_PLI)
    if high:
        return "highly_constrained"
    moderate = (loeuf is not None and loeuf <= MOD_LOEUF) or (pli is not None and pli >= MOD_PLI)
    if moderate:
        return "moderately_constrained"
    return "tolerant"


def _to_float(v):
    try:
        if v is None or v == "" or (isinstance(v, str) and v.upper() in ("NA", "NAN")):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    f = _to_float(v)
    return int(f) if f is not None else None


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _local_cache_path() -> str:
    root = os.environ.get("FRAMEWORK_CACHE_ROOT") or os.path.expanduser("~/.cache/framework-gnomad")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "gnomad.v4.1.constraint_metrics.tsv")


def _download_source(dest: str) -> None:
    """S3 read-through: download the constraint TSV to the local cache if absent."""
    import boto3  # local import — framework runtime shouldn't require boto3 unless a live read happens
    _ensure_aws_profile()
    boto3.client("s3").download_file(S3_BUCKET, S3_KEY, dest)


def load_constraint_row(gene_symbol: str, tsv_path: Optional[str] = None) -> Optional[dict]:
    """Return the per-gene representative constraint row (canonical/MANE) or None.

    tsv_path override is for tests (a synthetic TSV); production streams from S3 cache.
    Picks the mane_select row if present, else canonical, else the first matching row.
    """
    import csv
    path = tsv_path or _local_cache_path()
    if tsv_path is None and not os.path.exists(path):
        _download_source(path)
    matches = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if (row.get(COL_GENE) or "").strip().upper() == gene_symbol.strip().upper():
                matches.append(row)
    if not matches:
        return None
    def _truthy(row, col):
        return str(row.get(col, "")).strip().lower() in ("true", "1", "yes", "t")
    for col in (COL_MANE, COL_CANONICAL):
        for row in matches:
            if _truthy(row, col):
                return row
    return matches[0]


def compute_summary(row: Optional[dict], gene_symbol: str) -> dict:
    """Build the card-contract summary dict from a constraint row (or None → indeterminate)."""
    if row is None:
        return {
            "constraint_class": "indeterminate",
            "pli_score": None, "loeuf_score": None,
            "mis_z_score": None, "syn_z_score": None,
            "obs_lof_count": None, "exp_lof_count": None, "gene_length_bp": None,
            "method_version": METHOD_VERSION,
            "_note": f"{gene_symbol} not in gnomAD v4.1 constraint table (indeterminate).",
        }
    pli = _to_float(row.get(COL_PLI))
    loeuf = _to_float(row.get(COL_LOEUF))
    return {
        "constraint_class": classify_constraint(pli, loeuf),
        "pli_score": pli,
        "loeuf_score": loeuf,
        "mis_z_score": _to_float(row.get(COL_MIS_Z)),
        "syn_z_score": _to_float(row.get(COL_SYN_Z)),
        "obs_lof_count": _to_int(row.get(COL_OBS_LOF)),
        "exp_lof_count": _to_float(row.get(COL_EXP_LOF)),
        "gene_length_bp": None,  # not in the constraint TSV; card field kept for contract, null
        "method_version": METHOD_VERSION,
    }


def _load_takeda_style(target_contracts_dir):
    """Load the Takeda mplstyle + palette (idempotent). Returns the palette module."""
    import sys as _sys
    import matplotlib.pyplot as plt
    from pathlib import Path as _Path
    style_path = _Path(target_contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    _sys.path.insert(0, str(_Path(target_contracts_dir) / "plot_styles"))
    import takeda_palette  # type: ignore
    return takeda_palette


def emit_constraint_gauge(summary: dict, target_symbol: str, out_dir, target_contracts_dir):
    """Emit the constraint_scores_gauge_panel figure for gnomad-lof-constraint.

    Two horizontal gauges (pLI 0-1, LOEUF 0-2) with the card's constraint-band
    reference lines (pLI>=0.9 / LOEUF<=0.35 = highly-constrained safety concern).
    Summary-driven (thin lookup) — draws from pli_score/loeuf_score/constraint_class
    already in the summary; no data reload. On indeterminate/missing scores, emits a
    placeholder panel explaining the gap (so the dashboard shows a cell, not nothing).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path as _Path

    pal = _load_takeda_style(target_contracts_dir)
    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "figure_constraint_scores_gauge_panel.svg"

    pli = summary.get("pli_score")
    loeuf = summary.get("loeuf_score")
    klass = summary.get("constraint_class", "indeterminate")

    fig, axes = plt.subplots(2, 1, figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    concern = klass == "highly_constrained"
    bar_color = pal.REFLINE_KILLER["color"] if concern else "#0a2540"

    if pli is None and loeuf is None:
        for ax in axes:
            ax.axis("off")
        axes[0].text(0.5, 0.5, f"{target_symbol}: no gnomAD constraint scores\n"
                     f"(constraint_class = {klass})", ha="center", va="center", fontsize=10)
        fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
        return out_path

    # pLI gauge (0-1; >=0.9 = constrained)
    ax = axes[0]
    ax.barh([0], [pli if pli is not None else 0], color=bar_color, height=0.5)
    ax.axvline(HIGH_PLI, color=pal.REFLINE_KILLER["color"], linestyle="--", linewidth=1,
               label=f"high-constraint (pLI≥{HIGH_PLI})")
    ax.set_xlim(0, 1); ax.set_yticks([]); ax.set_xlabel("pLI (prob. LoF-intolerant)")
    ax.set_title(f"{target_symbol} — gnomAD LoF constraint  [{klass}]")
    ax.legend(loc="lower right", fontsize=7)

    # LOEUF gauge (0-2; <=0.35 = constrained — LOWER is more constrained)
    ax = axes[1]
    ax.barh([0], [loeuf if loeuf is not None else 0], color=bar_color, height=0.5)
    ax.axvline(HIGH_LOEUF, color=pal.REFLINE_KILLER["color"], linestyle="--", linewidth=1,
               label=f"high-constraint (LOEUF≤{HIGH_LOEUF})")
    ax.set_xlim(0, 2); ax.set_yticks([]); ax.set_xlabel("LOEUF (obs/exp LoF upper CI)")
    ax.legend(loc="lower right", fontsize=7)

    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="gnomAD LoF-constraint lookup for a gene.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--tsv", default=None, help="local TSV override (tests); default streams from S3")
    args = ap.parse_args()
    row = load_constraint_row(args.target, tsv_path=args.tsv)
    print(json.dumps(compute_summary(row, args.target), indent=2))
