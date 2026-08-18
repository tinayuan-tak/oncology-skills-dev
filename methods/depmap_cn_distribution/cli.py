#!/usr/bin/env python3
"""depmap-cn-distribution CLI — pan-cancer copy-number distribution analysis.

Mirrors the depmap_chronos_distribution + depmap_expression_distribution sibling
methods structurally; differences are documented inline.

LOAD STRATEGY (WES-primary + WGS-fallback):
  1. Try OmicsCNGeneMC_WES.csv first (n=1954 cell lines, 15391 genes from WES panel).
  2. If target gene is ABSENT from WES matrix, fall back to OmicsCNGeneWGS.csv
     (n=~800 cell lines, ~19000 genes — full genome). This closes the gap for
     genes outside the WES probe panel (e.g. MYC, BRAF in 26Q1).
  3. Returned summary's cn_assay_used field documents which source was used.

MATRIX SHAPE: WES CN matrix is cell-line-rows × gene-columns (similar to CRISPR).
  - First column: ModelConditionID
  - Second column: IsDefaultEntryForMC
  - Rest: gene columns named "SYMBOL (entrez_id)"
  Bridge: Model.csv carries ModelConditionID → ModelID + OncotreeLineage.

SCALE: raw relative copy number (median ~1.0 = diploid). NOT log2 ratio.

CLASSIFICATION VOCABULARY (copy_number_class):
  recurrently_amplified | recurrently_deleted | mixed | broadly_neutral |
  data_unavailable

`broadly_neutral` is the CORRECT call for mutation-driven oncogenes (KRAS, BRAF,
etc.); NOT a coverage gap. See card spec caveats.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click

from methods.catalog_query.read import bucket_prefix_for, s3_uri_for


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_CATALOG_REPO = Path(
    os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
)
DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
DEPMAP_SOURCE_MANIFEST_ID = "depmap-consortium-26q1"
# Resolved from the data-catalog manifest (single source of truth). DEPMAP_S3_PREFIX (s3://-form)
# feeds echo/provenance; _DEPMAP_KEY_PREFIX (bucket-relative) builds the get_object read keys below.
DEPMAP_S3_PREFIX = s3_uri_for(DEPMAP_SOURCE_MANIFEST_ID).rstrip("/")
_DEPMAP_KEY_PREFIX = bucket_prefix_for(DEPMAP_SOURCE_MANIFEST_ID)[1].rstrip("/")

# Threshold constants on raw relative-CN scale
DEEP_DEL = 0.5
SHALLOW_DEL = 0.92
NEUTRAL_HI = 1.07
FOCAL_AMP = 1.5
HIGH_AMP = 4.0

# Gene-column label regex: "SYMBOL (entrez_id)" -> SYMBOL
_GENE_LABEL_RE = re.compile(r'^([A-Za-z0-9._-]+)\s*\(\d+\)$')


def _parse_gene_symbol(label: str) -> Optional[str]:
    """Extract HGNC symbol from a 'SYMBOL (entrez_id)' column header."""
    if not isinstance(label, str):
        return None
    m = _GENE_LABEL_RE.match(label.strip().strip('"'))
    return m.group(1) if m else None


def _find_target_col(columns, target_symbol: str) -> Optional[str]:
    """Search column list for the column matching target_symbol via 'SYMBOL (entrez_id)' format."""
    for c in columns:
        sym = _parse_gene_symbol(c)
        if sym == target_symbol:
            return c
    return None


def load_cn_files(release_pin: str, target_symbol: str) -> tuple[dict, dict, str, list]:
    """Load CN data for target_symbol, trying WES first then falling back to WGS.

    Returns:
        cn_by_model_id: {model_id (ACH-XXXXXX) -> relative_cn (float)}
        model_metadata_by_id: {model_id -> metadata_dict (OncotreeLineage, etc.)}
        assay_used: 'wes' | 'wgs' | 'data_unavailable'
        load_errors: list of structured error dicts (empty on success)
    """
    import pandas as pd

    load_errors = []
    model_df = None

    try:
        import boto3
        # Model.csv + ModelCondition.csv via shared cached loaders. Model.csv (26Q1)
        # does NOT carry ModelConditionID — the bridge lives in ModelCondition.csv.
        from methods.depmap_common import load_model_csv, load_model_condition_csv
        model_df = load_model_csv(release_pin)
        model_condition_df = load_model_condition_csv(release_pin)

        # === TIER-2 PATH: parquet derived product (100-500× faster than CSV) ===
        try:
            from methods.depmap_common.parquet import get_cn_column_wes, get_cn_column_wgs
            wes_df = get_cn_column_wes(target_symbol, release_pin)
            if wes_df is not None:
                assay_used = "wes"
                chosen_df = wes_df
                target_col = next((c for c in wes_df.columns
                                     if c not in ("ModelConditionID", "IsDefaultEntryForMC")), None)
            else:
                wgs_df = get_cn_column_wgs(target_symbol, release_pin)
                if wgs_df is not None:
                    click.echo(f"  Target {target_symbol!r} absent from WES parquet; using WGS", err=True)
                    assay_used = "wgs"
                    chosen_df = wgs_df
                    target_col = next((c for c in wgs_df.columns
                                         if c not in ("ModelConditionID", "IsDefaultEntryForMC")), None)
                else:
                    load_errors.append({
                        "_live_read_error": "target_not_in_cn_panel",
                        "detail": f"Target {target_symbol!r} not found in WES or WGS gene-level CN matrices",
                        "remediation": "Confirm HGNC symbol spelling; this gene may not be captured by either CN platform.",
                    })
                    return {}, {}, "data_unavailable", load_errors
        except (FileNotFoundError, ImportError):
            # Parquet not available → fall through to CSV path
            s3 = boto3.client("s3")
            bucket = "onc-compbio"
            wes_key = f"{_DEPMAP_KEY_PREFIX}/OmicsCNGeneMC_WES.csv"
            click.echo(f"  Fetching s3://{bucket}/{wes_key}", err=True)
            wes_obj = s3.get_object(Bucket=bucket, Key=wes_key)
            wes_df = pd.read_csv(BytesIO(wes_obj["Body"].read()))
            target_col = _find_target_col(wes_df.columns, target_symbol)
            assay_used = "wes"
            chosen_df = wes_df
            if target_col is None:
                wgs_key = f"{_DEPMAP_KEY_PREFIX}/OmicsCNGeneWGS.csv"
                click.echo(f"  Target {target_symbol!r} absent from WES; falling back to WGS", err=True)
                wgs_obj = s3.get_object(Bucket=bucket, Key=wgs_key)
                wgs_df = pd.read_csv(BytesIO(wgs_obj["Body"].read()))
                target_col = _find_target_col(wgs_df.columns, target_symbol)
                if target_col is None:
                    load_errors.append({
                        "_live_read_error": "target_not_in_cn_panel",
                        "detail": f"Target {target_symbol!r} not found in WES or WGS gene-level CN matrices",
                    })
                    return {}, {}, "data_unavailable", load_errors
                assay_used = "wgs"
                chosen_df = wgs_df
    except ImportError as e:
        load_errors.append({"_live_read_error": "boto3_not_available", "detail": str(e)})
        return {}, {}, "data_unavailable", load_errors
    except Exception as e:
        load_errors.append({
            "_live_read_error": "s3_read_failed",
            "detail": str(e),
            "remediation": f"Ensure AWS credentials are set and {DEPMAP_S3_PREFIX} is accessible.",
        })
        return {}, {}, "data_unavailable", load_errors

    # Identify ID column — both WES and WGS use ModelConditionID as first column,
    # with IsDefaultEntryForMC immediately after. Apply IsDefault filter to keep
    # one row per cell-line.
    if "ModelConditionID" not in chosen_df.columns:
        load_errors.append({
            "_live_read_error": "cn_matrix_missing_modelconditionid",
            "detail": "CN matrix lacks ModelConditionID column; cannot bridge to ModelID.",
        })
        return {}, {}, "data_unavailable", load_errors

    if "IsDefaultEntryForMC" in chosen_df.columns:
        mask = chosen_df["IsDefaultEntryForMC"].isin([True, "Yes", "yes", "true", "TRUE"])
        chosen_df = chosen_df[mask]

    # Bridge ModelConditionID -> ModelID via ModelCondition.csv (NOT Model.csv;
    # Model.csv in 26Q1 doesn't carry MC-ID). A model can have multiple MC-IDs
    # (different culture conditions, passages); the CN matrix's IsDefaultEntryForMC
    # filter above already collapsed to one row per MC, but multiple MCs can map
    # to the same ModelID — we accept the last one as canonical for the lookup.
    if "ModelConditionID" in model_condition_df.columns and "ModelID" in model_condition_df.columns:
        mc_to_model = dict(zip(model_condition_df["ModelConditionID"], model_condition_df["ModelID"]))
    else:
        mc_to_model = {}

    # Build {model_id -> cn} dict
    cn_by_model_id = {}
    for _, row in chosen_df[["ModelConditionID", target_col]].iterrows():
        if pd.isna(row[target_col]):
            continue
        mc_id = row["ModelConditionID"]
        model_id = mc_to_model.get(mc_id, mc_id)  # fall back to MC ID if bridge fails
        cn_by_model_id[model_id] = float(row[target_col])

    # Model metadata keyed by ModelID
    if "ModelID" in model_df.columns:
        model_metadata_by_id = {row["ModelID"]: row.to_dict() for _, row in model_df.iterrows()}
    else:
        model_metadata_by_id = {}

    return cn_by_model_id, model_metadata_by_id, assay_used, load_errors


def _classify_cn(fraction_amp: float, fraction_del: float,
                  recurrent_threshold: float = 0.20,
                  dominant_ratio: float = 2.0) -> str:
    """Map per-event fractions to copy_number_class.

    Returns one of:
      recurrently_amplified | recurrently_deleted | mixed | broadly_neutral
    """
    amp_recurrent = fraction_amp >= recurrent_threshold
    del_recurrent = fraction_del >= recurrent_threshold
    if amp_recurrent and del_recurrent:
        # Both recurrent — call the dominant one if ratio ≥ dominant_ratio, else 'mixed'
        if fraction_amp >= fraction_del * dominant_ratio:
            return "recurrently_amplified"
        if fraction_del >= fraction_amp * dominant_ratio:
            return "recurrently_deleted"
        return "mixed"
    if amp_recurrent:
        return "recurrently_amplified"
    if del_recurrent:
        return "recurrently_deleted"
    return "broadly_neutral"


def _classify_shape(median_cn: float, iqr: float, frac_amp: float, frac_del: float) -> str:
    if frac_amp >= 0.20 and frac_del < 0.10:
        return "amp_dominant"
    if frac_del >= 0.20 and frac_amp < 0.10:
        return "del_dominant"
    if frac_amp >= 0.10 and frac_del >= 0.10:
        return "bimodal_mixed"
    if iqr < 0.15 and abs(median_cn - 1.0) < 0.1:
        return "tight_neutral"
    if iqr >= 0.15 and abs(median_cn - 1.0) < 0.15:
        return "dispersed_neutral"
    return "unclassified"


def compute_summary_stats(cn_by_model: dict, model_metadata: dict,
                            assay_used: str = "wes",
                            recurrent_threshold: float = 0.20) -> dict:
    """Compute decision-grade summary scalars for the CN card."""
    import numpy as np
    import pandas as pd

    if not cn_by_model:
        return {
            "cn_n_cell_lines_evaluated": 0,
            "cn_assay_used": "data_unavailable",
            "copy_number_class": "data_unavailable",
            "cn_homozygous_deletion_recurrent": "data_unavailable",
            "cn_distribution_shape": "unclassified",
        }

    cn_arr = np.array(list(cn_by_model.values()))
    n = len(cn_arr)

    # Per-event fractions
    frac_deep_del = float(np.mean(cn_arr < DEEP_DEL))
    frac_shallow_del = float(np.mean((cn_arr >= DEEP_DEL) & (cn_arr <= SHALLOW_DEL)))
    frac_neutral = float(np.mean((cn_arr > SHALLOW_DEL) & (cn_arr <= NEUTRAL_HI)))
    frac_shallow_amp = float(np.mean((cn_arr > NEUTRAL_HI) & (cn_arr <= FOCAL_AMP)))
    frac_focal_amp = float(np.mean((cn_arr > FOCAL_AMP) & (cn_arr <= HIGH_AMP)))
    frac_high_amp = float(np.mean(cn_arr > HIGH_AMP))

    # ASYMMETRY (KNOWN + BACKTESTED — see copy-number-distribution.card.yaml +
    # intracellular-intrinsic.rules.yaml cn-recurrently-*-supportive rationales):
    # the amp score counts ONLY focal/high gain (>1.5) while the del score counts
    # hemizygous/shallow loss (0.5-0.92) alongside deep loss. A 2026-08-14 focal-driver
    # backtest (curated COADREAD panel: 6 amp-drivers / 4 del-drivers / 4 mutation-only /
    # 3 LOH; the real _classify_cn, only band-membership varied) VALIDATED keeping these
    # thresholds — every symmetric alternative is STRICTLY WORSE:
    #   - +shallow-amp (symmetric-inclusive): amp-recall 2/6→6/6 BUT neutral-specificity
    #     3/4→0/4. Shallow gain is genome-wide background (mutation-only KRAS/BRAF/PIK3CA
    #     all carry shallow_amp 0.34-0.40), so including it calls everything amplified.
    #     focal_amp alone doesn't separate drivers either (ERBB2 focal 0.053 < KRAS 0.111)
    #     — amplification is indication-specific, diluted in this pan-cancer readout.
    #   - -shallow-del (symmetric-focal): del-recall 4/4→1/4 (erases SMAD4/PTEN/RB1, real
    #     TSG deletions seen as recurrent hemizygous loss in lines; only CDKN2A is deep).
    # The amp under-call is NOT a threshold bug: the real amp-driver signal belongs to the
    # indication-specific GISTIC patient_focal_cn_class + the copy-number-stratified-
    # dependency card (amplified-lines-more-dependent → biomarker_stratified_dependency),
    # NOT this pan-cancer distribution classifier. Do NOT re-tune these bands.
    fraction_recurrent_amp = frac_focal_amp + frac_high_amp   # focal + high (excludes shallow — validated)
    fraction_recurrent_del = frac_deep_del + frac_shallow_del  # deep + shallow (hemizygous — validated)

    median_cn = float(np.median(cn_arr))
    iqr = float(np.percentile(cn_arr, 75) - np.percentile(cn_arr, 25))

    summary = {
        "cn_n_cell_lines_evaluated": int(n),
        "cn_assay_used": assay_used,
        "cn_median_panel": median_cn,
        "cn_p25_panel": float(np.percentile(cn_arr, 25)),
        "cn_p75_panel": float(np.percentile(cn_arr, 75)),
        "cn_p5_panel": float(np.percentile(cn_arr, 5)),
        "cn_p95_panel": float(np.percentile(cn_arr, 95)),
        "cn_iqr": iqr,
        "cn_fraction_deep_deletion": frac_deep_del,
        "cn_fraction_shallow_deletion": frac_shallow_del,
        "cn_fraction_neutral": frac_neutral,
        "cn_fraction_shallow_amplification": frac_shallow_amp,
        "cn_fraction_focal_amplification": frac_focal_amp,
        "cn_fraction_high_amplification": frac_high_amp,
        "cn_recurrent_amplification_score": fraction_recurrent_amp,
        "cn_recurrent_deletion_score": fraction_recurrent_del,
    }

    summary["copy_number_class"] = _classify_cn(
        fraction_recurrent_amp, fraction_recurrent_del,
        recurrent_threshold=recurrent_threshold,
    )
    # Homozygous-deletion recurrence flag (2026-08-06, DISPLAY facet). copy_number_class folds deep +
    # shallow deletion into one `recurrently_deleted` value; this SEPARATE companion isolates recurrent
    # DEEP (homozygous, CN < DEEP_DEL) deletion — the degrader-relevant pattern (no protein to degrade).
    # Emitted as its OWN field, NOT a copy_number_class value: copy_number_class is verdict-driving (in
    # the genomic resolver), so splitting it would change the verdict for deep-del targets. This flag is
    # additive/verdict-inert — it surfaces "recurrently homozygously deleted" to render/LLM without
    # touching the resolver spine. (A degrader-not-viable KILLER rule keyed on it is a deferred follow-up.)
    summary["cn_homozygous_deletion_recurrent"] = (
        "recurrent_homozygous_deletion" if frac_deep_del >= recurrent_threshold
        else "not_recurrent_homozygous_deletion"
    )
    summary["cn_distribution_shape"] = _classify_shape(
        median_cn, iqr, fraction_recurrent_amp, fraction_recurrent_del
    )

    # Per-lineage stratification: identify lineages with significant amp or del
    lineage_records = []
    for model_id, cn in cn_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = (meta.get("OncotreeLineage") or meta.get("lineage")
                   or meta.get("PrimaryDisease") or "unknown")
        lineage_records.append({"model_id": model_id, "lineage": lineage, "cn": cn})
    lineage_df = pd.DataFrame(lineage_records)

    top_amp_lineages = []
    top_del_lineages = []
    if not lineage_df.empty:
        amp_tail_total = max(1, int((lineage_df["cn"] > FOCAL_AMP).sum()))
        del_tail_total = max(1, int((lineage_df["cn"] <= SHALLOW_DEL).sum()))
        for lin_name, subset in lineage_df.groupby("lineage"):
            if len(subset) < 5:
                continue
            n_in_lin = len(subset)
            frac_amp_lin = float((subset["cn"] > FOCAL_AMP).mean())
            frac_del_lin = float((subset["cn"] <= SHALLOW_DEL).mean())
            med_cn_lin = float(subset["cn"].median())
            if frac_amp_lin >= 0.10:
                top_amp_lineages.append({
                    "lineage": lin_name,
                    "n_in_lineage": int(n_in_lin),
                    "fraction_focal_amplified": frac_amp_lin,
                    "median_cn": med_cn_lin,
                    "fraction_of_amp_tail": float((subset["cn"] > FOCAL_AMP).sum() / amp_tail_total),
                })
            if frac_del_lin >= 0.10:
                top_del_lineages.append({
                    "lineage": lin_name,
                    "n_in_lineage": int(n_in_lin),
                    "fraction_deleted": frac_del_lin,
                    "median_cn": med_cn_lin,
                    "fraction_of_del_tail": float((subset["cn"] <= SHALLOW_DEL).sum() / del_tail_total),
                })
    top_amp_lineages.sort(key=lambda x: x["fraction_focal_amplified"], reverse=True)
    top_del_lineages.sort(key=lambda x: x["fraction_deleted"], reverse=True)
    summary["cn_top_amplified_lineages"] = top_amp_lineages[:5]
    summary["cn_top_deleted_lineages"] = top_del_lineages[:5]

    return summary


def _load_takeda_style(target_contracts_dir: Path):
    import matplotlib.pyplot as plt
    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette  # type: ignore
    return takeda_palette


def emit_density_plot(cn_by_model: dict, target_symbol: str, summary: dict,
                       out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit pan-cancer CN KDE + histogram density plot — PRIMARY figure.

    X-axis clipped to [0, max(5, p95+0.5)] so the diploid bulk + relevant threshold
    band (0.5-4.0) reads clearly. Extreme amplifications (CN > 5) compressed onto
    the right edge are surfaced as an annotation with the count + max value.
    Fixed lower bound = 0 enables visual cross-target comparison.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy.stats import gaussian_kde

    pal = _load_takeda_style(target_contracts_dir)
    scores = np.array(list(cn_by_model.values()))

    # Clip to a fixed-floor, adaptive-ceiling range so the threshold band (0.5-4.0)
    # is always readable AND outliers don't dominate. p95+0.5 gives some headroom
    # for amplified targets without letting extreme outliers (>10) stretch the axis.
    x_min = 0.0
    x_max = float(max(5.0, np.percentile(scores, 95) + 0.5))
    clipped_scores = scores[scores <= x_max]
    n_above_clip = int((scores > x_max).sum())
    max_score = float(scores.max())

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.hist(clipped_scores, bins=60, range=(x_min, x_max),
            density=True, alpha=0.45, color="#0a2540", edgecolor="white")
    if len(clipped_scores) >= 10:
        kde = gaussian_kde(clipped_scores)
        xs = np.linspace(x_min, x_max, 500)
        ax.plot(xs, kde(xs), color="#cf2828", linewidth=2)
    ax.axvline(SHALLOW_DEL, color="#f0a020", linestyle="--", linewidth=1, label=f"shallow del (≤{SHALLOW_DEL})")
    ax.axvline(FOCAL_AMP, color="#cf2828", linestyle="--", linewidth=1, label=f"focal amp (>{FOCAL_AMP})")
    ax.axvline(1.0, color="#666666", linestyle=":", linewidth=1, label="diploid (1.0)")
    ax.set_xlim(x_min, x_max)
    ax.set_xlabel(f"Relative copy number ({summary.get('cn_assay_used', 'wes').upper()} gene-level)")
    ax.set_ylabel("Density")
    ax.set_title(f"{target_symbol} — pan-cancer copy-number distribution (n={len(scores)})")
    ax.legend(loc="upper right", fontsize=7)

    # Annotate clipped tail
    if n_above_clip > 0:
        note = f"n={n_above_clip} lines with CN > {x_max:.1f} not shown\n(max CN = {max_score:.1f})"
        ax.text(0.98, 0.55, note, transform=ax.transAxes, fontsize=7,
                ha="right", va="top", color="#555555",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#cccccc", alpha=0.9))

    fig.tight_layout()
    out_path = out_dir / "figure_density_cn.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_waterfall_plot(cn_by_model: dict, model_metadata: dict, target_symbol: str,
                         summary: dict, out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit ranked-waterfall SVG — SECONDARY figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    pal = _load_takeda_style(target_contracts_dir)

    records = []
    for model_id, cn in cn_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = meta.get("OncotreeLineage") or "unknown"
        records.append({"model_id": model_id, "lineage": lineage, "cn": cn})
    df = pd.DataFrame(records).sort_values("cn").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.bar(range(len(df)), df["cn"], width=1.0, color="#0a2540", linewidth=0)
    ax.axhline(SHALLOW_DEL, color="#f0a020", linestyle="--", linewidth=1, label=f"shallow del (≤{SHALLOW_DEL})")
    ax.axhline(FOCAL_AMP, color="#cf2828", linestyle="--", linewidth=1, label=f"focal amp (>{FOCAL_AMP})")
    ax.axhline(1.0, color="#666666", linestyle=":", linewidth=1, label="diploid")
    ax.set_xlabel(f"Cell lines (n={len(df)}, sorted by CN)")
    ax.set_ylabel(f"Relative copy number ({summary.get('cn_assay_used', 'wes').upper()})")
    ax.set_title(f"{target_symbol} — pan-cancer CN (ranked waterfall)")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out_path = out_dir / "figure_waterfall_cn.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_lineage_strip(cn_by_model: dict, model_metadata: dict, target_symbol: str,
                        summary: dict, out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit per-lineage strip plot, lineages ordered by median CN descending."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    pal = _load_takeda_style(target_contracts_dir)

    records = []
    for model_id, cn in cn_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = meta.get("OncotreeLineage") or "unknown"
        records.append({"lineage": lineage, "cn": cn})
    df = pd.DataFrame(records)

    lineage_medians = df.groupby("lineage")["cn"].agg(["median", "count"])
    lineage_medians = lineage_medians[lineage_medians["count"] >= 5].sort_values("median", ascending=False)
    lineages_ordered = list(lineage_medians.index)

    fig_h = min(max(3.5, len(lineages_ordered) * 0.2), 7.0)
    fig, ax = plt.subplots(figsize=(pal.FIGSIZE_DOUBLE_COLUMN[0], fig_h))
    # Clip x-range to a fixed-floor, p95-derived ceiling so the threshold band
    # stays readable across targets. Outliers above the cap get drawn at the cap
    # position as triangle markers + a count annotation.
    x_min = 0.0
    x_max = float(max(5.0, np.percentile(df["cn"], 95) + 0.5))
    n_above_cap = int((df["cn"] > x_max).sum())
    max_score = float(df["cn"].max())

    for i, lin in enumerate(lineages_ordered):
        scores = df[df["lineage"] == lin]["cn"].values
        below_cap = scores[scores <= x_max]
        above_cap = scores[scores > x_max]
        lineage_color = pal.get_lineage_color(lin)
        jitter_below = np.random.RandomState(42 + i).uniform(-0.15, 0.15, size=len(below_cap))
        ax.scatter(below_cap, np.full(len(below_cap), i) + jitter_below,
                   alpha=0.5, s=8, color=lineage_color)
        if len(above_cap) > 0:
            jitter_above = np.random.RandomState(99 + i).uniform(-0.15, 0.15, size=len(above_cap))
            # Plot at the cap edge using triangle markers — signals "this is clipped"
            ax.scatter(np.full(len(above_cap), x_max - 0.05),
                       np.full(len(above_cap), i) + jitter_above,
                       marker=">", s=20, color=lineage_color, alpha=0.9, edgecolor="white", linewidth=0.3)
        # Median marker (dark red |) — distinct from lineage color so it stays legible
        ax.scatter([np.median(scores)], [i], color="#B22222", s=30, marker="|", zorder=5)
    ax.axvline(SHALLOW_DEL, color="#f0a020", linestyle="--", linewidth=1)
    ax.axvline(FOCAL_AMP, color="#cf2828", linestyle="--", linewidth=1)
    ax.axvline(1.0, color="#666666", linestyle=":", linewidth=1)
    ax.set_xlim(x_min, x_max)
    ax.set_yticks(range(len(lineages_ordered)))
    ax.set_yticklabels(lineages_ordered, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel(f"Relative copy number ({summary.get('cn_assay_used', 'wes').upper()})")
    ax.set_title(f"{target_symbol} — per-lineage CN (n≥5; ordered by median, top=highest)")
    if n_above_cap > 0:
        ax.text(0.98, 0.02,
                f"n={n_above_cap} cell lines with CN > {x_max:.1f}\nshown as ▶ at right edge (max={max_score:.1f})",
                transform=ax.transAxes, fontsize=7, ha="right", va="bottom",
                color="#555555", bbox=dict(boxstyle="round,pad=0.3",
                                           facecolor="white", edgecolor="#cccccc", alpha=0.9))
    fig.tight_layout()
    out_path = out_dir / "figure_lineage_strip_cn.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plot_data(cn_by_model: dict, model_metadata: dict, out_path: Path) -> Path:
    import pandas as pd
    records = []
    for model_id, cn in cn_by_model.items():
        meta = model_metadata.get(model_id, {})
        records.append({
            "model_id": model_id,
            "ccle_name": meta.get("CCLEName"),
            "lineage": meta.get("OncotreeLineage"),
            "relative_cn": cn,
            "is_deleted": cn <= SHALLOW_DEL,
            "is_amplified": cn > FOCAL_AMP,
        })
    df = pd.DataFrame(records)
    out_file = out_path / "plot_data_cn.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_manifest(target_symbol: str, release_pin: str, summary: dict,
                   out_dir: Path, load_errors: list) -> Path:
    import yaml
    manifest = {
        "method_id": "depmap-cn-distribution",
        "method_version": METHOD_VERSION,
        "card_id": "copy-number-distribution",
        "target": target_symbol,
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cn_assay_used": summary.get("cn_assay_used", "data_unavailable"),
        "n_cell_lines_evaluated": summary.get("cn_n_cell_lines_evaluated", 0),
        "copy_number_class": summary.get("copy_number_class", "data_unavailable"),
        "load_errors": load_errors,
    }
    out_file = out_dir / "manifest.yaml"
    with open(out_file, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return out_file


@click.command()
@click.option("--target", required=True, help="HGNC symbol")
@click.option("--release-pin", default="26q1")
@click.option("--out", required=True, type=click.Path(file_okay=False, writable=True, path_type=Path))
def main(target, release_pin, out):
    out.mkdir(parents=True, exist_ok=True)
    cn_by, mmeta, assay_used, load_errors = load_cn_files(release_pin, target)
    if load_errors:
        err = {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "copy_number_class": "data_unavailable",
            "cn_assay_used": assay_used,
        }
        (out / "summary.json").write_text(json.dumps(err, indent=2))
        sys.exit(1)
    summary = compute_summary_stats(cn_by, mmeta, assay_used=assay_used)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_density_plot(cn_by, target, summary, out, DEFAULT_TARGET_CONTRACTS)
    emit_waterfall_plot(cn_by, mmeta, target, summary, out, DEFAULT_TARGET_CONTRACTS)
    emit_lineage_strip(cn_by, mmeta, target, summary, out, DEFAULT_TARGET_CONTRACTS)
    emit_plot_data(cn_by, mmeta, out)
    emit_manifest(target, release_pin, summary, out, [])
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
