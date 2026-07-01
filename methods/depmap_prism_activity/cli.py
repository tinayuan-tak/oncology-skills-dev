#!/usr/bin/env python3
"""depmap-prism-activity CLI (E6 — thin lookup on the PRISM gene-aggregate parquet).

Reads ONE row from the frozen derived parquet
`s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v2/prism_activity_per_gene.parquet`
via pyarrow predicate pushdown. The parquet is produced by the sibling
`methods.depmap_prism_precompute`.

Three figure emitters:
  1. top_compounds_bar — horizontal bar of the top-K compounds by activity, colored
     by clinical status (prioritized vs tool), with drug name + MOA labels.
     Primary "what compounds exist" panel.
  2. lineage_activity_bar (v2) — per-lineage median LFC for the gene, colored by
     whether the lineage is 'active' (median < -0.5). Direct visual of lineage-
     stratified activity that pan-cancer median can mask (e.g. KRAS Bowel signal).
  3. activity_vocab_panel — text card showing the class + granular fields (compound
     count, median LFC, highest phase, polyselective flags, lineage-selectivity).

Card carries its OWN release_pin (prism-activity-v2); NOT the 26q1 CRISPR pin.

v2 (2026-07-01, PRISM lineage stratification build):
  - Adds per_lineage_activity + prism_lineage_selectivity to summary_fields
  - Reads depmap-prism-activity-v2 (bumped derived product)
  - New lineage_activity_bar figure
  - Backwards compatible with v1 parquets (gracefully missing lineage fields
    surface as empty / data_unavailable).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.2.0"

DEFAULT_TARGET_CONTRACTS = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)

# Release-pin → parquet S3 URI. Carries multiple pin aliases (data + framework
# release) for testability. `prism-activity-v2` is the canonical framework pin.
# v1 kept for backwards-compat lookup (test fixtures may still reference it).
RELEASE_PIN_TO_PARQUET = {
    "prism-activity-v2": "s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v2/prism_activity_per_gene.parquet",
    "prism-activity-v1": "s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v1/prism_activity_per_gene.parquet",
}

# Vocabulary constants — mirror precompute definitions for read-side self-check.
CLASS_CLINICALLY_ACTIVE = "clinically_active"
CLASS_TOOL_COMPOUND_ONLY = "tool_compound_only"
CLASS_WEAKLY_ACTIVE = "weakly_active"
CLASS_NO_COMPOUNDS_FOUND = "no_compounds_found"
CLASS_DATA_UNAVAILABLE = "data_unavailable"

# v2 lineage-selectivity vocabulary
LINEAGE_SEL_SELECTIVE = "lineage_selective"
LINEAGE_SEL_BROADLY_ACTIVE = "broadly_active"
LINEAGE_SEL_NO_SIGNAL = "no_lineage_signal"
LINEAGE_SEL_DATA_UNAVAILABLE = "data_unavailable"

# Threshold for coloring per-lineage bars 'active' (kept in-sync with precompute)
LINEAGE_ACTIVE_LFC_THRESHOLD = -0.5


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    if p.scheme != "s3" or not p.netloc:
        raise ValueError(f"Not an S3 URI: {uri}")
    return p.netloc, p.path.lstrip("/")


def fetch_prism_row(parquet_uri: str, gene: str) -> Optional[dict]:
    """Pyarrow predicate-pushdown read for ONE gene row. Returns dict or None."""
    import pyarrow.parquet as pq
    if parquet_uri.startswith("s3://"):
        import pyarrow.fs as pafs
        bucket, key = _parse_s3_uri(parquet_uri)
        fs = pafs.S3FileSystem()
        path = f"{bucket}/{key}"
    else:
        fs = None
        path = parquet_uri
    table = pq.read_table(path, filesystem=fs,
                            filters=[("gene_symbol", "=", gene)])
    if table.num_rows == 0:
        return None
    if table.num_rows > 1:
        raise RuntimeError(f"Multiple rows for {gene!r}; parquet violated uniqueness")
    return {col: table[col][0].as_py() for col in table.column_names}


def compute_summary(row: Optional[dict], target: str) -> dict:
    """Map a parquet row → the card's summary_fields shape.

    Two data-availability modes:
      - Target not in aggregate at all → data_unavailable (target was never PRISM-annotated
        anywhere; framework's default assumption for HGNC-valid genes without a compound).
        We STILL surface no_compounds_found rather than data_unavailable when the target's
        row IS in the parquet but n_compounds_targeting = 0 — but the precompute doesn't
        emit rows for zero-compound genes, so in practice `row is None` → no_compounds_found.
      - Target row present → hydrate all summary_fields from the row directly.
    """
    if row is None:
        return {
            "prism_activity_class": CLASS_NO_COMPOUNDS_FOUND,
            "_data_note": (f"Target {target!r} has no PRISM-annotated compounds across "
                           "either OncRef 25Q4 or Repurposing 24Q2. First-in-class opportunity, "
                           "not a data-availability gap."),
            "n_compounds_targeting": 0,
            "highest_clinical_phase": None,
            "median_lfc_across_compounds": None,
            "top_compounds": [],
            "per_lineage_activity": [],
            "prism_lineage_selectivity": LINEAGE_SEL_DATA_UNAVAILABLE,
        }
    med = row.get("median_lfc_across_compounds")
    # NaN → None so warning predicates and vocab panels get the same "no data" treatment
    # as a genuinely-absent value. Precompute writes NaN when no compound has an LFC edge.
    if med is not None and isinstance(med, float) and med != med:
        med = None
    return {
        "prism_activity_class": row.get("prism_activity_class"),
        "n_compounds_targeting": int(row.get("n_compounds_targeting") or 0),
        "highest_clinical_phase": row.get("highest_clinical_phase"),
        "median_lfc_across_compounds": med,
        "top_compounds": row.get("top_compounds") or [],
        # v2 fields — safe-default when reading a v1 parquet without these columns
        "per_lineage_activity": row.get("per_lineage_activity") or [],
        "prism_lineage_selectivity": row.get("prism_lineage_selectivity") or LINEAGE_SEL_DATA_UNAVAILABLE,
    }


def _load_takeda_palette(target_contracts_dir: Path):
    import matplotlib.pyplot as plt
    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette
    return takeda_palette


def _placeholder_svg(msg_lines: list[str], out_path: Path, pal) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    y = 0.7
    for line in msg_lines:
        ax.text(0.5, y, line, transform=ax.transAxes, ha="center",
                 fontsize=10 if y == 0.7 else 8, color="#444" if y == 0.7 else "#777")
        y -= 0.1
    ax.set_axis_off()
    fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_top_compounds_bar(summary: dict, target: str, out_dir: Path,
                              target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS) -> Path:
    """Horizontal bar of top-K compounds by activity, colored by clinical status.

    Bar length = -median_lfc (so more-negative LFC → longer bar, "kills more").
    Color: navy for prioritized OncRef (clinical); ochre for tool/Repurposing.
    Annotations: drug_name (y-axis label), MOA + polyselective flag (right of bar).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_top_compounds_bar.svg"
    cls = summary.get("prism_activity_class")

    top = summary.get("top_compounds") or []
    if cls == CLASS_NO_COMPOUNDS_FOUND or not top:
        return _placeholder_svg([
            f"{target} — no PRISM-annotated compounds",
            "first-in-class opportunity, not a data-availability gap"
        ], out_path, pal)

    # Compounds with numeric LFC first (sorted most-active first); others after
    with_lfc = [c for c in top if c.get("median_lfc") is not None]
    without_lfc = [c for c in top if c.get("median_lfc") is None]
    with_lfc.sort(key=lambda c: (not c.get("prioritized", False), c["median_lfc"]))
    ordered = with_lfc + without_lfc

    names = [c["drug_name"] for c in ordered]
    lfcs = [(-c["median_lfc"]) if c.get("median_lfc") is not None else 0.0 for c in ordered]
    colors = ["#0a2540" if c.get("prioritized") else "#f0a020" for c in ordered]

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.barh(range(len(names)), lfcs, color=colors, edgecolor="white")
    for i, c in enumerate(ordered):
        moa = c.get("moa") or ""
        moa = (moa[:40] + "…") if len(moa) > 40 else moa
        poly_tag = f" [poly:{c['n_annotated_targets']}]" if c.get("polyselective") else ""
        annot = f"{moa}{poly_tag}"
        if c.get("median_lfc") is None:
            annot = f"{moa} (no LFC data)"
        ax.text(max(lfcs + [0.01]) * 0.02, i, annot, va="center", fontsize=7, color="#333")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("−median LFC across screened lines  (larger = more toxic)")

    # Legend
    handles = [
        plt.Rectangle((0, 0), 1, 1, color="#0a2540", label="Prioritized (OncRef 25Q4)"),
        plt.Rectangle((0, 0), 1, 1, color="#f0a020", label="Tool / Repurposing 24Q2"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=7, framealpha=0.9)

    n = summary.get("n_compounds_targeting", 0)
    phase = summary.get("highest_clinical_phase") or "unknown"
    med = summary.get("median_lfc_across_compounds")
    med_txt = f"median LFC={med:.2f}" if isinstance(med, (int, float)) else "median LFC=NA"
    class_label = (cls or "unknown").replace("_", " ")
    ax.set_title(f"{target} — {n} PRISM compounds ({class_label}, phase≥{phase}, {med_txt})",
                    fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_lineage_activity_bar(summary: dict, target: str, out_dir: Path,
                                 target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS,
                                 top_k: int = 10) -> Path:
    """Per-lineage median LFC horizontal bar (v2).

    Bar length = -median_lfc (larger = more active). Color:
      - navy for lineages with median LFC < LINEAGE_ACTIVE_LFC_THRESHOLD (active)
      - gray for lineages above the threshold (inactive)

    Sorted most-active-first, top_k lineages shown. Each bar annotated with the
    top compound name in that lineage + (n_lines_screened) count.

    Placeholder rendering when:
      - per_lineage_activity is empty (v1-parquet or no evaluable lineages)
      - card is no_compounds_found / data_unavailable
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_lineage_activity_bar.svg"

    entries = summary.get("per_lineage_activity") or []
    lineage_sel = summary.get("prism_lineage_selectivity") or LINEAGE_SEL_DATA_UNAVAILABLE

    if not entries:
        return _placeholder_svg([
            f"{target} — no per-lineage activity data",
            "(lineage stratification unavailable in this precompute)"
        ], out_path, pal)

    # Already sorted most-active-first in the precompute; head off top_k
    top = entries[:top_k]
    lineages = [e["lineage"] for e in top]
    lfcs = [-e["median_lfc"] if e.get("median_lfc") is not None else 0.0 for e in top]
    colors = [
        "#0a2540" if (e.get("median_lfc") is not None and e["median_lfc"] < LINEAGE_ACTIVE_LFC_THRESHOLD)
        else "#bbbbbb"
        for e in top
    ]

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.barh(range(len(lineages)), lfcs, color=colors, edgecolor="white")
    for i, e in enumerate(top):
        top_cmp = e.get("top_compound_in_lineage") or ""
        annot = f"{top_cmp} (n={e.get('n_lines_screened', 0)})"
        ax.text(max(lfcs + [0.01]) * 0.02, i, annot, va="center", fontsize=7, color="#333")
    ax.set_yticks(range(len(lineages)))
    ax.set_yticklabels(lineages, fontsize=8)
    ax.invert_yaxis()
    ax.axvline(-LINEAGE_ACTIVE_LFC_THRESHOLD, color="#888", linestyle="--", linewidth=0.7)
    ax.set_xlabel("−median LFC in lineage  (dashed = active threshold |LFC|=0.5)")

    handles = [
        plt.Rectangle((0, 0), 1, 1, color="#0a2540", label=f"Active (median LFC < {LINEAGE_ACTIVE_LFC_THRESHOLD})"),
        plt.Rectangle((0, 0), 1, 1, color="#bbbbbb", label="Inactive or borderline"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=7, framealpha=0.9)

    n_lineages = len(entries)
    sel_label = lineage_sel.replace("_", " ")
    ax.set_title(f"{target} — per-lineage PRISM activity  ({n_lineages} evaluable lineages · {sel_label})",
                    fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_activity_vocabulary_panel(summary: dict, target: str, out_dir: Path,
                                        target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS) -> Path:
    """Text summary card: class + granular fields + polyselective breakdown.

    Complements the compounds bar with the vocabulary-driven headline. This is
    the figure that renders when the top-compounds bar is a placeholder but the
    framework still wants a "here's what the card says" panel.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_activity_vocab_panel.svg"

    cls = summary.get("prism_activity_class") or "data_unavailable"
    n = summary.get("n_compounds_targeting", 0)
    phase = summary.get("highest_clinical_phase") or "—"
    med = summary.get("median_lfc_across_compounds")
    med_txt = f"{med:+.2f}" if isinstance(med, (int, float)) else "NA"
    top = summary.get("top_compounds") or []
    n_poly = sum(1 for c in top if c.get("polyselective"))
    lineage_entries = summary.get("per_lineage_activity") or []
    lineage_sel = summary.get("prism_lineage_selectivity") or LINEAGE_SEL_DATA_UNAVAILABLE
    n_lineages_active = sum(
        1 for e in lineage_entries
        if e.get("median_lfc") is not None and e["median_lfc"] < LINEAGE_ACTIVE_LFC_THRESHOLD
    )

    lines = [
        f"{target}  ·  PRISM activity",
        "",
        f"class:               {cls.replace('_', ' ')}",
        f"n_compounds:         {n}",
        f"highest_phase:       {phase}",
        f"median LFC (pan):    {med_txt}",
        f"polyselective (top): {n_poly}/{len(top)}",
        f"lineage selectivity: {lineage_sel.replace('_', ' ')}",
        f"lineages active/eval: {n_lineages_active}/{len(lineage_entries)}",
    ]
    color = {
        CLASS_CLINICALLY_ACTIVE: "#0a2540",
        CLASS_WEAKLY_ACTIVE: "#f0a020",
        CLASS_TOOL_COMPOUND_ONLY: "#7fa7c0",
        CLASS_NO_COMPOUNDS_FOUND: "#888888",
        CLASS_DATA_UNAVAILABLE: "#bbbbbb",
    }.get(cls, "#444")

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    y = 0.9
    for i, line in enumerate(lines):
        weight = "bold" if i == 0 else "normal"
        size = 11 if i == 0 else 9
        ax.text(0.05, y, line, transform=ax.transAxes, ha="left",
                 fontsize=size, weight=weight,
                 color=color if i == 0 else "#333",
                 family="monospace" if i > 0 else "sans-serif")
        y -= 0.10
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_manifest(target: str, release_pin: str, summary: dict,
                    out_dir: Path, parquet_uri: str) -> Path:
    import yaml
    manifest = {
        "method_id": "depmap-prism-activity",
        "method_version": METHOD_VERSION,
        "card_id": "prism-compound-activity",
        "target": target,
        "release_pin": release_pin,
        "derived_product_uri": parquet_uri,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prism_activity_class": summary.get("prism_activity_class"),
        "n_compounds_targeting": summary.get("n_compounds_targeting"),
        "highest_clinical_phase": summary.get("highest_clinical_phase"),
        "median_lfc_across_compounds": summary.get("median_lfc_across_compounds"),
        # v2
        "prism_lineage_selectivity": summary.get("prism_lineage_selectivity"),
        "n_lineages_evaluated": len(summary.get("per_lineage_activity") or []),
    }
    out_file = out_dir / "manifest.yaml"
    with open(out_file, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return out_file


@click.command()
@click.option("--target", required=True, help="HGNC symbol")
@click.option("--release-pin", default="prism-activity-v2", show_default=True,
              type=click.Choice(list(RELEASE_PIN_TO_PARQUET.keys())))
@click.option("--parquet-uri", default=None,
              help="Override the parquet URI (for testing / local fixture).")
@click.option("--out", required=True, type=click.Path(file_okay=False, writable=True, path_type=Path))
def main(target, release_pin, parquet_uri, out):
    out.mkdir(parents=True, exist_ok=True)
    parquet_uri = parquet_uri or RELEASE_PIN_TO_PARQUET[release_pin]
    try:
        row = fetch_prism_row(parquet_uri, target)
        summary = compute_summary(row, target)
    except Exception as e:
        summary = {
            "_live_read_error": "derived_product_read_failed",
            "_remediation": f"Could not read {parquet_uri}: {type(e).__name__}: {e}",
            "prism_activity_class": CLASS_DATA_UNAVAILABLE,
            "n_compounds_targeting": 0,
            "highest_clinical_phase": None,
            "median_lfc_across_compounds": None,
            "top_compounds": [],
            "per_lineage_activity": [],
            "prism_lineage_selectivity": LINEAGE_SEL_DATA_UNAVAILABLE,
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_top_compounds_bar(summary, target, out)
    emit_lineage_activity_bar(summary, target, out)
    emit_activity_vocabulary_panel(summary, target, out)
    emit_manifest(target, release_pin, summary, out, parquet_uri)
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
