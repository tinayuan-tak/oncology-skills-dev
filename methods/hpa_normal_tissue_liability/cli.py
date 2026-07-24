"""hpa_normal_tissue_liability.cli — normal-tissue on-target-off-tumor safety.

Reads the HPA master TSV (hpa-v25-1, already landed + consumed by 8 other cards)
IHC-derived protein-tissue fields and emits the `normal-tissue-liability` card
summary — the dominant biologics on-target-off-tumor safety signal.

Two fields:
  - `Protein tissue distribution` (Not detected | Detected in single | some | many
    | all) — pathologist-scored IHC BREADTH across normal tissues (~96% coverage).
    → normal_tissue_breadth_class (the primary categorical).
  - `Protein tissue specific Intensity` ("intestine: 2.3e5;lymphoid tissue: ...")
    — named-tissue list (~51% coverage, the tissue-enriched subset). Parsed to flag
    ESSENTIAL-tissue expression.

HPA uses a CLOSED 16-name tissue vocabulary in the specific-intensity field, so the
essential-tissue set is an EXACT membership test (no fuzzy matching). A gene absent
from HPA / with no tissue-distribution call → data_unavailable (coverage gap, NOT a
favorable window — do not read absence as safety).
"""

from __future__ import annotations

import io
import os
import sys
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

METHOD_VERSION = "0.1.0"

S3_BUCKET = "onc-compbio"
HPA_KEY = "data-catalog/sources/hpa/v25-1/proteinatlas.tsv.zip"
DEFAULT_AWS_PROFILE = "cbg"

# Perf Stage 3 (2026-07-23): the HPA master zip was previously re-downloaded from S3 on EVERY call
# (no lru, no disk cache) — paid multiple times per target-profile run (verdict pass + figure pass)
# and every process start. Add a disk cache (download once per machine) + an lru_cache on the parsed
# DataFrame (reuse across calls in a process). Mirrors the depmap_common/parquet.py disk-latch pattern.
HPA_CACHE_DIR = Path.home() / ".cache" / "framework-hpa-v25-1"
HPA_CACHE_ZIP = HPA_CACHE_DIR / "proteinatlas.tsv.zip"

HPA_GENE_COL = "Gene"
HPA_DIST_COL = "Protein tissue distribution"
HPA_SPEC_COL = "Protein tissue specificity"
HPA_INTENSITY_COL = "Protein tissue specific Intensity"

# HPA `Protein tissue distribution` → normal_tissue_breadth_class.
_DIST_TO_CLASS = {
    "detected in all":    "broad_normal_expression",
    "detected in many":   "broad_normal_expression",
    "detected in some":   "moderate_normal_expression",
    "detected in single": "restricted_normal_expression",
    "not detected":       "not_detected_in_normal",
}

# Essential-tissue set (exact membership over HPA's closed 16-name vocabulary):
# life-critical tissues where on-target-off-tumor toxicity is catastrophic. The
# strict-modality (BiTE/TCE/cell) killer keys off ANY hit here.
ESSENTIAL_TISSUES = {
    "cerebral cortex",   # CNS
    "bone marrow",       # hematopoietic
    "liver",
    "heart muscle",      # cardiac
    "lung",
    "kidney",
    "pancreas",          # endocrine/exocrine — DKA/tox risk
}
# GI epithelium — modality-dependent (ADC non-cleavable may tolerate; BiTE not).
GI_TISSUES = {"intestine", "stomach"}


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _ensure_hpa_cached() -> Path:
    """Download the HPA master zip to the local disk cache ONCE per machine; return the local path.
    Second-session / second-call runs are a no-op cache hit (mirrors depmap_common/parquet.py)."""
    HPA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if HPA_CACHE_ZIP.exists() and HPA_CACHE_ZIP.stat().st_size > 0:
        return HPA_CACHE_ZIP
    _ensure_aws_profile()
    import boto3
    print(f"[hpa] downloading s3://{S3_BUCKET}/{HPA_KEY} -> {HPA_CACHE_ZIP}", file=sys.stderr)
    boto3.client("s3").download_file(S3_BUCKET, HPA_KEY, str(HPA_CACHE_ZIP))
    return HPA_CACHE_ZIP


def _read_zip_cols(zip_path, cols):
    import pandas as pd
    z = zipfile.ZipFile(zip_path)
    with z.open(z.namelist()[0]) as f:
        return pd.read_csv(f, sep="\t", usecols=cols, dtype=str)


@lru_cache(maxsize=1)
def _read_hpa_cached_default():
    """The default (S3-backed) HPA read — parsed ONCE per process (lru) off the disk cache.
    Only used when no explicit hpa_path override is passed (the live path)."""
    cols = [HPA_GENE_COL, HPA_DIST_COL, HPA_SPEC_COL, HPA_INTENSITY_COL]
    return _read_zip_cols(_ensure_hpa_cached(), cols)


def _read_hpa(hpa_path=None):
    import pandas as pd
    cols = [HPA_GENE_COL, HPA_DIST_COL, HPA_SPEC_COL, HPA_INTENSITY_COL]
    if hpa_path is not None:
        # explicit override (tests / local file) — NOT cached (callers may vary the path)
        p = str(hpa_path)
        if p.endswith(".zip"):
            return _read_zip_cols(p, cols)
        return pd.read_csv(p, sep="\t", usecols=cols, dtype=str)
    # live path: disk-cache the zip + lru-cache the parse (return a copy so callers can't mutate
    # the shared cached frame).
    return _read_hpa_cached_default().copy()


def parse_specific_tissues(intensity_value: Optional[str]) -> list:
    """Parse 'intestine: 2.3e5;lymphoid tissue: 1.1e4' → [{tissue, intensity}]."""
    if not intensity_value or str(intensity_value) == "nan":
        return []
    out = []
    for part in str(intensity_value).split(";"):
        if ":" not in part:
            continue
        name, val = part.rsplit(":", 1)
        name = name.strip().lower()
        try:
            intensity = float(val.strip())
        except (ValueError, AttributeError):
            intensity = None
        if name:
            out.append({"tissue": name, "intensity": intensity})
    return out


def classify_breadth(dist_value: Optional[str]) -> str:
    """Protein tissue distribution → normal_tissue_breadth_class."""
    if dist_value is None or str(dist_value) == "nan":
        return "data_unavailable"
    return _DIST_TO_CLASS.get(str(dist_value).strip().lower(), "data_unavailable")


def compute_summary(gene: str, row: Optional[dict]) -> dict:
    """Build the normal-tissue-liability card summary from an HPA row."""
    if row is None:
        return {
            "normal_tissue_breadth_class": "data_unavailable",
            "essential_tissue_flag": "absent",
            "hpa_tissue_distribution": None,
            "hpa_tissue_specificity": None,
            "n_essential_tissues_with_expression": 0,
            "essential_tissues_flagged": [],
            "n_specific_tissues": 0,
            "specific_tissues": [],
            "safety_tissue_flags": [],
            "method_version": METHOD_VERSION,
        }
    dist = row.get(HPA_DIST_COL)
    dist = None if (dist is None or str(dist) == "nan") else str(dist)
    spec = row.get(HPA_SPEC_COL)
    spec = None if (spec is None or str(spec) == "nan") else str(spec)
    breadth = classify_breadth(dist)
    specific = parse_specific_tissues(row.get(HPA_INTENSITY_COL))
    names = {t["tissue"] for t in specific}
    essential = sorted(names & ESSENTIAL_TISSUES)
    gi = sorted(names & GI_TISSUES)

    flags = []
    if essential:
        flags.append("essential_tissue")
    if gi:
        flags.append("gi_tract")
    if breadth == "broad_normal_expression":
        flags.append("broad")

    return {
        "normal_tissue_breadth_class": breadth,
        # Scalar categorical the essential-tissue rule matches with `equals` (the rules
        # engine is categorical-only — no list-membership predicate; so the list→scalar
        # reduction happens here at emit time).
        "essential_tissue_flag": "present" if essential else "absent",
        "hpa_tissue_distribution": dist,
        "hpa_tissue_specificity": spec,
        "n_essential_tissues_with_expression": len(essential),
        "essential_tissues_flagged": essential,
        "n_specific_tissues": len(specific),
        "specific_tissues": specific,
        "safety_tissue_flags": flags,
        "method_version": METHOD_VERSION,
    }


def load_and_classify(gene: str, hpa_path=None) -> dict:
    """Full pipeline: look up the gene's HPA row → normal-tissue-liability summary."""
    import pandas as pd
    df = _read_hpa(hpa_path)
    hit = df[df[HPA_GENE_COL].astype(str).str.upper() == gene.strip().upper()]
    if not len(hit):
        return compute_summary(gene, None)
    return compute_summary(gene, hit.iloc[0].to_dict())


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


def emit_normal_tissue_bar(summary: dict, target_symbol: str, out_dir, target_contracts_dir):
    """Emit the normal_tissue_expression_heatmap figure for normal-tissue-liability.

    A horizontal bar of per-tissue IHC intensities (from specific_tissues), tissues
    colored RED if essential (on-target-off-tumor risk) else navy, sorted by intensity.
    Title carries the breadth class. Summary-driven (no reload). When there is no
    specific-tissue list (a broad gene, or Not detected), emits an informative panel
    stating the breadth class — because breadth, not the per-tissue list, carries the
    liability there.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path as _Path

    pal = _load_takeda_style(target_contracts_dir)
    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "figure_normal_tissue_expression_heatmap.svg"

    breadth = summary.get("normal_tissue_breadth_class", "data_unavailable")
    specific = summary.get("specific_tissues") or []
    essential_set = set(summary.get("essential_tissues_flagged") or [])

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    rows = [(t.get("tissue"), t.get("intensity")) for t in specific
            if t.get("intensity") is not None]
    rows.sort(key=lambda r: r[1], reverse=True)

    if not rows:
        ax.axis("off")
        msg = {
            "broad_normal_expression": "detected broadly across normal tissues (IHC 'all/many')\n— on-target-off-tumor liability; no tissue-specific list.",
            "not_detected_in_normal": "NOT detected in normal tissues (IHC)\n— favorable therapeutic window.",
        }.get(breadth, f"breadth class = {breadth}")
        ax.text(0.5, 0.5, f"{target_symbol} — normal-tissue liability\n{msg}",
                ha="center", va="center", fontsize=10)
        fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
        return out_path

    labels = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    colors = [pal.REFLINE_KILLER["color"] if lab in essential_set else "#0a2540"
              for lab in labels]
    ypos = range(len(labels))
    ax.barh(list(ypos), vals, color=colors, height=0.6)
    ax.set_yticks(list(ypos)); ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("HPA IHC tissue-specific intensity")
    ax.set_title(f"{target_symbol} — normal-tissue protein footprint  [{breadth}]\n"
                 f"(red = essential tissue)", fontsize=9)
    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


def _main(argv=None):
    import argparse, json
    ap = argparse.ArgumentParser(description="HPA normal-tissue liability for a target.")
    ap.add_argument("--gene", required=True)
    ap.add_argument("--hpa-path", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(load_and_classify(args.gene, hpa_path=args.hpa_path), indent=2, default=str))


if __name__ == "__main__":
    _main()
