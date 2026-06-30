#!/usr/bin/env python3
"""depmap-mutation-type-counts CLI — cell-line mutation-type analysis.

Consumes DepMap 26Q1 OmicsSomaticMutations.csv (raw MAF, ~738 MB) and emits per-
variant-class mutation counts + landscape-class label.

DISTINCT FROM the existing mutation-hotspot-frequency card (TCGA-patient-cohort,
codon-resolution). This card is CELL-LINE-cohort, variant-class-resolution.

CLASSIFICATION:
  mutation_landscape_class ∈ {missense_dominant, lof_dominant, mixed,
                              no_mutations, data_unavailable}
  - missense_dominant: ≥70% missense among coding variants → oncogene pattern
  - lof_dominant: ≥50% LOF (nonsense + frameshift + splice) → tumor suppressor
  - mixed: neither single class dominates → dual-role (e.g. TP53)
  - no_mutations: <5 cell lines mutated → insufficient signal
  - data_unavailable: MAF unreachable or target absent
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_TARGET_CONTRACTS = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)
DEPMAP_S3_BUCKET = "onc-compbio"
DEPMAP_S3_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1"

# VEP severity ranking — used to resolve compound entries like 'stop_gained&frameshift_variant'
VEP_SEVERITY = {
    "transcript_ablation": 1,
    "splice_acceptor_variant": 2,
    "splice_donor_variant": 3,
    "stop_gained": 4,
    "frameshift_variant": 5,
    "stop_lost": 6,
    "start_lost": 7,
    "transcript_amplification": 8,
    "inframe_insertion": 9,
    "inframe_deletion": 10,
    "missense_variant": 11,
    "protein_altering_variant": 12,
    "splice_region_variant": 13,
    "incomplete_terminal_codon_variant": 14,
    "start_retained_variant": 15,
    "stop_retained_variant": 16,
    "synonymous_variant": 17,
    "coding_sequence_variant": 18,
    "mature_miRNA_variant": 19,
    "5_prime_UTR_variant": 20,
    "3_prime_UTR_variant": 21,
    "non_coding_transcript_exon_variant": 22,
    "intron_variant": 23,
    "NMD_transcript_variant": 24,
    "non_coding_transcript_variant": 25,
    "upstream_gene_variant": 26,
    "downstream_gene_variant": 27,
    "TFBS_ablation": 28,
    "TFBS_amplification": 29,
    "TF_binding_site_variant": 30,
    "regulatory_region_ablation": 31,
    "regulatory_region_amplification": 32,
    "regulatory_region_variant": 33,
    "feature_elongation": 34,
    "feature_truncation": 35,
    "intergenic_variant": 36,
}


# Class groupings for the descriptive vocabulary
def _resolve_dominant_variant_class(variant_info: str) -> Optional[str]:
    """Resolve a (possibly-compound) VEP VariantInfo string to its single most-severe
    sequence-ontology class. Returns None only for empty/non-string input. Unknown
    VEP terms are RETURNED as-is (mapped to 'other' category downstream) rather
    than silently dropped — preserves observation counts when DepMap adds new terms.
    """
    if not isinstance(variant_info, str) or not variant_info:
        return None
    parts = [p.strip() for p in variant_info.split("&") if p.strip()]
    if not parts:
        return None
    # Use <= so an unknown term that's the sole candidate still wins
    best = parts[0]
    best_sev = VEP_SEVERITY.get(best, 999)
    for p in parts[1:]:
        sev = VEP_SEVERITY.get(p, 999)
        if sev < best_sev:
            best_sev = sev
            best = p
    return best


def _category_for_class(variant_class: str) -> str:
    """Map a VEP class to one of our 7 framework categories."""
    if not variant_class:
        return "other"
    if variant_class == "missense_variant":
        return "missense"
    if variant_class == "stop_gained":
        return "nonsense"
    if variant_class == "frameshift_variant":
        return "frameshift"
    if variant_class in ("splice_acceptor_variant", "splice_donor_variant", "splice_region_variant"):
        return "splice"
    if variant_class in ("inframe_insertion", "inframe_deletion"):
        return "inframe_indel"
    if variant_class == "synonymous_variant":
        return "synonymous"
    return "other"


def load_mutation_data(release_pin: str, target_symbol: str) -> tuple[list, dict, int, list]:
    """Load all MAF rows for target_symbol + Model.csv metadata.

    Returns:
        target_rows: list of dicts, one per mutation observation in target
                     (filtered to IsDefaultEntryForModel='Yes' to collapse multi-MC lines)
        model_metadata: {model_id -> meta dict (OncotreeLineage, CCLEName, ...)}
        n_cell_lines_total: total cell-lines-in-MAF count (denominator for mutation rate)
        load_errors: list of structured errors (empty on success)
    """
    import pandas as pd
    load_errors = []
    try:
        import boto3
        s3 = boto3.client("s3")

        click.echo(f"  Fetching s3://{DEPMAP_S3_BUCKET}/{DEPMAP_S3_PREFIX}/Model.csv", err=True)
        model_obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=f"{DEPMAP_S3_PREFIX}/Model.csv")
        model_df = pd.read_csv(BytesIO(model_obj["Body"].read()))

        click.echo(f"  Fetching s3://{DEPMAP_S3_BUCKET}/{DEPMAP_S3_PREFIX}/OmicsSomaticMutations.csv", err=True)
        maf_obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=f"{DEPMAP_S3_PREFIX}/OmicsSomaticMutations.csv")
        # Read only the columns we need to keep memory under control
        maf_df = pd.read_csv(
            BytesIO(maf_obj["Body"].read()),
            usecols=["ModelID", "HugoSymbol", "VariantType", "VariantInfo", "ProteinChange",
                     "IsDefaultEntryForModel"],
        )
    except ImportError as e:
        load_errors.append({"_live_read_error": "boto3_not_available", "detail": str(e)})
        return [], {}, 0, load_errors
    except Exception as e:
        load_errors.append({"_live_read_error": "s3_read_failed", "detail": str(e)})
        return [], {}, 0, load_errors

    # Filter to default entries only (one row per model per mutation)
    maf_df = maf_df[maf_df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])]

    # Denominator: distinct cell lines with at least one entry in the (filtered) MAF
    n_cell_lines_total = int(maf_df["ModelID"].nunique())

    # Target filter
    target_df = maf_df[maf_df["HugoSymbol"] == target_symbol]
    target_rows = target_df.to_dict(orient="records")

    # Model metadata
    model_metadata = {}
    if "ModelID" in model_df.columns:
        model_metadata = {row["ModelID"]: row.to_dict() for _, row in model_df.iterrows()}

    return target_rows, model_metadata, n_cell_lines_total, load_errors


def compute_summary_stats(target_rows: list, model_metadata: dict, n_cell_lines_total: int,
                            min_mutated: int = 5,
                            missense_dominant_fraction: float = 0.70,
                            lof_dominant_fraction: float = 0.50) -> dict:
    """Compute per-class mutation counts + landscape-class label."""
    import pandas as pd

    # Aggregate counts per framework category
    counts = {"missense": 0, "nonsense": 0, "frameshift": 0, "splice": 0,
               "inframe_indel": 0, "synonymous": 0, "other": 0}
    per_class_counts = []

    mutated_cell_lines = set()
    for row in target_rows:
        mutated_cell_lines.add(row.get("ModelID"))
        vc = _resolve_dominant_variant_class(row.get("VariantInfo", ""))
        cat = _category_for_class(vc)
        counts[cat] = counts.get(cat, 0) + 1
        per_class_counts.append({"model_id": row.get("ModelID"),
                                  "variant_class": vc,
                                  "category": cat,
                                  "protein_change": row.get("ProteinChange")})

    n_mutated = len(mutated_cell_lines)
    n_total_mutations = len(target_rows)
    mutation_rate = n_mutated / n_cell_lines_total if n_cell_lines_total > 0 else 0.0

    # Coding-variant subtotal (excludes synonymous + other for fraction calculations)
    coding_total = counts["missense"] + counts["nonsense"] + counts["frameshift"] + counts["splice"] + counts["inframe_indel"]
    lof_total = counts["nonsense"] + counts["frameshift"] + counts["splice"]

    fraction_missense = (counts["missense"] / coding_total) if coding_total > 0 else 0.0
    fraction_lof = (lof_total / coding_total) if coding_total > 0 else 0.0
    fraction_inframe_indel = (counts["inframe_indel"] / coding_total) if coding_total > 0 else 0.0

    # Dominant class
    if n_mutated < min_mutated:
        dominant_class = "none"
        landscape_class = "no_mutations"
    else:
        # Identify the single largest coding category
        coding_counts = {
            "missense": counts["missense"],
            "lof": lof_total,
            "inframe_indel": counts["inframe_indel"],
        }
        dominant_class = max(coding_counts, key=coding_counts.get) if max(coding_counts.values()) > 0 else "none"

        if fraction_missense >= missense_dominant_fraction:
            landscape_class = "missense_dominant"
        elif fraction_lof >= lof_dominant_fraction:
            landscape_class = "lof_dominant"
        else:
            landscape_class = "mixed"

    # Per-class ordered list for the figure
    ordered_classes = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    mut_per_class_counts = [{"variant_class": k, "n": v} for k, v in ordered_classes if v > 0]

    # Per-lineage stratification — top 10 lineages by mutation count
    top_lineages = []
    if target_rows and model_metadata:
        lineage_stats = {}
        for row in target_rows:
            mid = row.get("ModelID")
            meta = model_metadata.get(mid, {})
            lin = meta.get("OncotreeLineage") or "unknown"
            if lin not in lineage_stats:
                lineage_stats[lin] = {"n_mutated_lines": set(), "n_observations": 0, "by_class": {}}
            lineage_stats[lin]["n_mutated_lines"].add(mid)
            lineage_stats[lin]["n_observations"] += 1
            vc = _resolve_dominant_variant_class(row.get("VariantInfo", ""))
            cat = _category_for_class(vc)
            lineage_stats[lin]["by_class"][cat] = lineage_stats[lin]["by_class"].get(cat, 0) + 1
        for lin, stats in lineage_stats.items():
            top_lineages.append({
                "lineage": lin,
                "n_mutated_lines": len(stats["n_mutated_lines"]),
                "n_observations": stats["n_observations"],
                "by_class": stats["by_class"],
            })
        top_lineages.sort(key=lambda x: x["n_mutated_lines"], reverse=True)

    summary = {
        "mut_n_cell_lines_total": int(n_cell_lines_total),
        "mut_n_cell_lines_mutated": int(n_mutated),
        "mut_mutation_rate": float(mutation_rate),
        "mut_total_mutations": int(n_total_mutations),
        "mut_n_missense": int(counts["missense"]),
        "mut_n_nonsense": int(counts["nonsense"]),
        "mut_n_frameshift": int(counts["frameshift"]),
        "mut_n_splice": int(counts["splice"]),
        "mut_n_inframe_indel": int(counts["inframe_indel"]),
        "mut_n_synonymous": int(counts["synonymous"]),
        "mut_n_other": int(counts["other"]),
        "mut_fraction_missense": float(fraction_missense),
        "mut_fraction_lof": float(fraction_lof),
        "mut_fraction_inframe_indel": float(fraction_inframe_indel),
        "mut_dominant_mutation_class": dominant_class,
        "mutation_landscape_class": landscape_class,
        "mut_top_mutated_lineages": top_lineages[:10],
        "mut_per_class_counts": mut_per_class_counts,
    }
    return summary


def _load_takeda_style(target_contracts_dir: Path):
    import matplotlib.pyplot as plt
    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette  # type: ignore
    return takeda_palette


# Color palette for variant classes — keeps a consistent visual language across cards
VARIANT_CLASS_COLORS = {
    "missense": "#0a2540",      # Takeda navy — oncogene-pattern marker
    "nonsense": "#cf2828",      # red — LOF
    "frameshift": "#f0a020",    # orange — LOF
    "splice": "#9b3192",        # purple — LOF (splice disruption)
    "inframe_indel": "#7fa7c0", # light blue
    "synonymous": "#aaaaaa",    # gray
    "other": "#dddddd",         # light gray
}


def emit_mutation_class_bar(summary: dict, target_symbol: str,
                              out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit horizontal stacked bar of variant-class counts — PRIMARY figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_style(target_contracts_dir)

    class_order = ["missense", "nonsense", "frameshift", "splice",
                    "inframe_indel", "synonymous", "other"]
    counts_dict = {entry["variant_class"]: entry["n"] for entry in summary.get("mut_per_class_counts", [])}
    counts = [counts_dict.get(c, 0) for c in class_order]
    colors = [VARIANT_CLASS_COLORS[c] for c in class_order]

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    bars = ax.barh(range(len(class_order)), counts, color=colors, edgecolor="white")
    for i, c in enumerate(counts):
        if c > 0:
            ax.text(c + max(counts) * 0.01, i, str(c),
                    va="center", fontsize=8, color="#222222")
    ax.set_yticks(range(len(class_order)))
    ax.set_yticklabels([c.replace("_", " ") for c in class_order], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Mutation observations in DepMap panel")
    ax.set_title(
        f"{target_symbol} — mutation-type counts "
        f"(n_mutated={summary.get('mut_n_cell_lines_mutated', 0)}, "
        f"class={summary.get('mutation_landscape_class', 'unknown').replace('_', ' ')})"
    )
    fig.tight_layout()
    out_path = out_dir / "figure_mutation_class_bar.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_lineage_class_bar(summary: dict, target_symbol: str,
                             out_dir: Path, target_contracts_dir: Path) -> Path:
    """Per-lineage stacked bar — top 10 lineages by mutation count."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    pal = _load_takeda_style(target_contracts_dir)

    top_lineages = summary.get("mut_top_mutated_lineages", [])[:10]
    if not top_lineages:
        fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
        ax.text(0.5, 0.5, "No per-lineage mutation data",
                transform=ax.transAxes, ha="center", fontsize=10, color="#666666")
        out_path = out_dir / "figure_mutation_lineage_bar.svg"
        fig.savefig(out_path); plt.close(fig)
        return out_path

    class_order = ["missense", "nonsense", "frameshift", "splice",
                    "inframe_indel", "synonymous", "other"]
    lineages = [t["lineage"] for t in top_lineages]
    matrix = np.array([[t["by_class"].get(c, 0) for c in class_order] for t in top_lineages])

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    left = np.zeros(len(lineages))
    for j, cls in enumerate(class_order):
        ax.barh(range(len(lineages)), matrix[:, j], left=left,
                color=VARIANT_CLASS_COLORS[cls], edgecolor="white",
                label=cls.replace("_", " "))
        left += matrix[:, j]
    ax.set_yticks(range(len(lineages)))
    ax.set_yticklabels(lineages, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Mutation observations")
    ax.set_title(f"{target_symbol} — per-lineage mutation-class distribution (top 10 lineages)")
    ax.legend(loc="lower right", fontsize=7, ncol=2, framealpha=0.9)
    fig.tight_layout()
    out_path = out_dir / "figure_mutation_lineage_bar.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plot_data(target_rows: list, model_metadata: dict, out_path: Path) -> Path:
    """Emit per-cell-line per-class Parquet."""
    import pandas as pd
    records = []
    for row in target_rows:
        mid = row.get("ModelID")
        meta = model_metadata.get(mid, {})
        vc = _resolve_dominant_variant_class(row.get("VariantInfo", ""))
        cat = _category_for_class(vc)
        records.append({
            "model_id": mid,
            "ccle_name": meta.get("CCLEName"),
            "lineage": meta.get("OncotreeLineage"),
            "variant_class": vc,
            "category": cat,
            "protein_change": row.get("ProteinChange"),
        })
    df = pd.DataFrame(records)
    out_file = out_path / "plot_data_mutation_types.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_manifest(target_symbol: str, release_pin: str, summary: dict,
                   out_dir: Path, load_errors: list) -> Path:
    import yaml
    manifest = {
        "method_id": "depmap-mutation-type-counts",
        "method_version": METHOD_VERSION,
        "card_id": "mutation-type-counts",
        "target": target_symbol,
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_cell_lines_total": summary.get("mut_n_cell_lines_total", 0),
        "n_cell_lines_mutated": summary.get("mut_n_cell_lines_mutated", 0),
        "mutation_landscape_class": summary.get("mutation_landscape_class", "data_unavailable"),
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
    target_rows, model_metadata, n_total, load_errors = load_mutation_data(release_pin, target)
    if load_errors:
        err = {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "mutation_landscape_class": "data_unavailable",
        }
        (out / "summary.json").write_text(json.dumps(err, indent=2))
        sys.exit(1)
    summary = compute_summary_stats(target_rows, model_metadata, n_total)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_mutation_class_bar(summary, target, out, DEFAULT_TARGET_CONTRACTS)
    emit_lineage_class_bar(summary, target, out, DEFAULT_TARGET_CONTRACTS)
    emit_plot_data(target_rows, model_metadata, out)
    emit_manifest(target, release_pin, summary, out, [])
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
