"""tcga_gtex_tpm_quantiles.read — reader + figure emitters for the pan-cancer by-tissue
TPM distribution summary product (tcga-gtex-tpm-tissue-quantiles-v1).

The figure is a by-tissue tumor-vs-normal distribution: for one gene, a boxplot per TCGA study
(tumor) and per GTEx tissue (normal), co-plotted on ONE log2(TPM+1) axis. Because the product
stores five-number summaries (not per-sample values), the boxplot is drawn from PRECOMPUTED stats
via matplotlib ax.bxp / plotly's precomputed-box fields — no per-sample scan on the render path.

Read discipline (2026-08-22 data-layer hardening — parquet-storage-standard): the 68 MB quantile
product is STREAMED per-gene directly from S3 via a pyarrow S3FileSystem with predicate pushdown on
the sort key (ensembl_gene_id) — HTTP range requests fetch only the few matching row-groups, NO
whole-file download. Mirrors the sibling tcga_gtex_expression_distribution reader's _get_s3fs +
streamed-read pattern. Definitive-vs-transient absence discipline so a transient blip is re-raised
(honest _live_read_error) instead of masked as a dead axis.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from onc_methods._common.s3 import get_s3fs
from onc_methods.catalog_query.read import bucket_key_for, bucket_prefix_for
from onc_methods.roots import contracts_root

DEFAULT_AWS_PROFILE = "cbg"
MANIFEST_ID = "tcga-gtex-tpm-tissue-quantiles-v1"
ENSEMBL_ID_MAP_MANIFEST_ID = "ensembl-id-mapping-release-116-snapshot-2026-06-18"
# bucket + keys resolved from the data-catalog manifests (single source of truth).
S3_BUCKET, S3_KEY = bucket_key_for(MANIFEST_ID)
ENSEMBL_ID_MAP_S3_KEY = f"{bucket_prefix_for(ENSEMBL_ID_MAP_MANIFEST_ID)[1]}hsapiens_gene_id_map_release-116.tsv"

_SYMBOL_TO_ENSEMBL_MAP: Optional[dict] = None


def _symbol_to_ensembl_ids(symbol: str) -> Optional[list]:
    """Return list of unversioned Ensembl IDs for a gene symbol, or None if unavailable."""
    global _SYMBOL_TO_ENSEMBL_MAP
    if _SYMBOL_TO_ENSEMBL_MAP is None:
        try:
            import io

            import boto3
            import pandas as pd

            s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
            body = s3.get_object(Bucket=S3_BUCKET, Key=ENSEMBL_ID_MAP_S3_KEY)["Body"].read()
            df = pd.read_csv(io.BytesIO(body), sep="\t").dropna(subset=["Gene stable ID", "HGNC symbol"])
            rev: dict = {}
            for eid, sym in zip(df["Gene stable ID"], df["HGNC symbol"]):
                rev.setdefault(sym, []).append(eid)
            _SYMBOL_TO_ENSEMBL_MAP = rev
        except Exception:  # noqa: BLE001
            _SYMBOL_TO_ENSEMBL_MAP = {}
    ids = _SYMBOL_TO_ENSEMBL_MAP.get(symbol.upper().strip())
    return ids or None


# Tumor = deep navy, Normal = muted blue (matches the CPTAC protein cards' tumor/normal identity).
_TUMOR_FILL, _TUMOR_LINE = "#1f4e79", "#0a2540"
_NORMAL_FILL, _NORMAL_LINE = "#a9c5db", "#5b7f99"

# Lineage mapping: TCGA study → (lineage_name, GTEx tissue)
# Used for grouping tumor and normal together by tissue of origin
_TCGA_TO_LINEAGE = {
    "COAD": ("Colon", "COLON"),
    "READ": ("Colon", "COLON"),
    "BRCA": ("Breast", "BREAST"),
    "LUAD": ("Lung", "LUNG"),
    "LUSC": ("Lung", "LUNG"),
    "BLCA": ("Bladder", "BLADDER"),
    "HNSC": ("Head & Neck", "ESOPHAGUS"),
    "KIRC": ("Kidney", "KIDNEY"),
    "KICH": ("Kidney", "KIDNEY"),
    "KIRP": ("Kidney", "KIDNEY"),
    "LIHC": ("Liver", "LIVER"),
    "PAAD": ("Pancreas", "PANCREAS"),
    "PRAD": ("Prostate", "PROSTATE"),
    "SKCM": ("Skin", "SKIN"),
    "STAD": ("Stomach", "STOMACH"),
    "ESCA": ("Esophagus", "ESOPHAGUS"),
    "THCA": ("Thyroid", "THYROID"),
    "UCEC": ("Uterus", "UTERUS"),
    "UCS": ("Uterus", "UTERUS"),
    "OV": ("Ovary", "OVARY"),
    "CESC": ("Cervix", "CERVIX_UTERI"),
    "TGCT": ("Testis", "TESTIS"),
    "GBM": ("Brain", "BRAIN"),
    "LGG": ("Brain", "BRAIN"),
    "ACC": ("Adrenal", "ADRENAL_GLAND"),
    "PCPG": ("Adrenal", "ADRENAL_GLAND"),
    "THYM": ("Thymus", None),
    "MESO": ("Pleura", None),
    "UVM": ("Eye", None),
    "SARC": ("Soft Tissue", None),
    "CHOL": ("Bile Duct", None),
    "DLBC": ("Lymph", None),
    "LAML": ("Blood", "BLOOD"),
}

# Reverse mapping: GTEx tissue → lineage name (for tissues without TCGA match)
_GTEX_TO_LINEAGE = {
    "COLON": "Colon",
    "BREAST": "Breast",
    "LUNG": "Lung",
    "BLADDER": "Bladder",
    "ESOPHAGUS": "Esophagus",
    "KIDNEY": "Kidney",
    "LIVER": "Liver",
    "PANCREAS": "Pancreas",
    "PROSTATE": "Prostate",
    "SKIN": "Skin",
    "STOMACH": "Stomach",
    "THYROID": "Thyroid",
    "UTERUS": "Uterus",
    "OVARY": "Ovary",
    "CERVIX_UTERI": "Cervix",
    "TESTIS": "Testis",
    "BRAIN": "Brain",
    "ADRENAL_GLAND": "Adrenal",
    "BLOOD": "Blood",
    "HEART": "Heart",
    "MUSCLE": "Muscle",
    "NERVE": "Nerve",
    "SPLEEN": "Spleen",
    "SMALL_INTESTINE": "Small Intestine",
    "ADIPOSE_TISSUE": "Adipose",
    "BLOOD_VESSEL": "Blood Vessel",
    "BONE_MARROW": "Bone Marrow",
    "FALLOPIAN_TUBE": "Fallopian Tube",
    "PITUITARY": "Pituitary",
    "SALIVARY_GLAND": "Salivary Gland",
    "VAGINA": "Vagina",
}


def _get_s3fs():
    return get_s3fs()


@lru_cache(maxsize=64)
def read_pan_cancer_by_tissue(target: str):
    """Per-(source, group) log2(TPM+1) five-number summaries for one gene, both sources.

    Memoized (retrieval-opt #5): the three figure emitters (emit_by_tissue_distribution /
    emit_plot_data / emit_plotly_specs) each call this independently, so a single card render
    re-read + re-filtered the 69 MB quantile product 3x. Cached on `target`; the returned DataFrame
    is treated read-only downstream (filtered/copied by _ordered_rows, never mutated in place).
    Note: pandas DataFrames are mutable — do NOT mutate the returned frame in place.

    Streamed predicate-pushdown read (filter on ensembl_gene_id, the sort key; gene_symbol
    fallback when the Ensembl id-map is unavailable) directly from S3 via a pyarrow S3FileSystem —
    HTTP range requests fetch only the few matching row-groups, NO whole-file download. Returns a
    DataFrame with columns (gene_symbol, ensembl_gene_id, source, group, n, min, q1, median, q3,
    max, mean); empty when the target is absent / product unavailable."""
    import pandas as pd

    cols = ["gene_symbol", "ensembl_gene_id", "source", "group", "n", "min", "q1", "median", "q3", "max", "mean"]
    try:
        import pyarrow.parquet as pq

        ensembl_ids = _symbol_to_ensembl_ids(target)
        if ensembl_ids:
            filters = [("ensembl_gene_id", "in", ensembl_ids)]
        else:
            # fallback: gene_symbol (no row-group pruning on this sort key, but correct)
            filters = [("gene_symbol", "==", target.upper().strip())]
        tbl = pq.read_table(
            f"{S3_BUCKET}/{S3_KEY}",
            filesystem=_get_s3fs(),
            filters=filters,
            columns=cols,
        )
        return tbl.to_pandas()
    except Exception as e:  # noqa: BLE001
        # Streamed S3 read: swallow ONLY a genuine object-absence (NoSuchKey/404 or pyarrow
        # FileNotFoundError) as an honest empty distribution. A transient/creds/broken-env failure
        # must NOT be masked as "gene absent" — re-raise so the live-read seam surfaces the real
        # cause (_live_read_error) instead of a silent dead axis.
        from onc_methods.target_id_sidecar import is_definitively_absent

        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return pd.DataFrame(columns=cols)


def _n(row) -> int:
    """Sample count as int, tolerant of a null/NaN `n` (int(nan) raises ValueError and would crash
    the whole figure emit rather than degrade). A missing count renders as n=0 in the label."""
    v = row.get("n")
    try:
        return int(v) if v is not None and v == v else 0  # v == v is False for NaN
    except (TypeError, ValueError):
        return 0


def _bxp_stat(row, label: str) -> dict:
    """One matplotlib ax.bxp stat dict from a quantile row. Whiskers clamp the 1.5xIQR fence to
    [min, max] (the product stores only the five-number summary, not Tukey within-fence extremes —
    documented on the manifest)."""
    q1, med, q3 = float(row["q1"]), float(row["median"]), float(row["q3"])
    lo, hi = float(row["min"]), float(row["max"])
    iqr = q3 - q1
    whislo = max(lo, q1 - 1.5 * iqr)
    whishi = min(hi, q3 + 1.5 * iqr)
    return {"label": label, "med": med, "q1": q1, "q3": q3, "whislo": whislo, "whishi": whishi, "fliers": []}


def _ordered_rows(df):
    """Split into (tumor_rows, normal_rows), each sorted by median descending (highest-expressing
    tissue first). Returns lists of dict rows."""
    tumor = df[df["source"] == "tcga_tumor"].sort_values("median", ascending=False)
    normal = df[df["source"] == "gtex_normal"].sort_values("median", ascending=False)
    return tumor.to_dict("records"), normal.to_dict("records")


def _build_lineage_groups(df):
    """Build lineage-grouped data: list of dicts with tumor/normal paired by lineage.
    Returns list sorted by delta (tumor median - normal median) descending."""
    tumor_rows = df[df["source"] == "tcga_tumor"].to_dict("records")
    normal_rows = df[df["source"] == "gtex_normal"].to_dict("records")

    # Index normal rows by GTEx tissue
    normal_by_tissue = {r["group"]: r for r in normal_rows}

    # Group TCGA studies by lineage, aggregating if multiple studies map to same lineage
    lineage_data = {}
    for tr in tumor_rows:
        study = tr["group"]
        if study not in _TCGA_TO_LINEAGE:
            continue
        lineage, gtex_tissue = _TCGA_TO_LINEAGE[study]
        if lineage not in lineage_data:
            lineage_data[lineage] = {
                "lineage": lineage,
                "tumor_studies": [],
                "gtex_tissue": gtex_tissue,
                "tumor_rows": [],
                "normal_row": None,
            }
        lineage_data[lineage]["tumor_studies"].append(study)
        lineage_data[lineage]["tumor_rows"].append(tr)

    # Attach normal data and compute aggregated tumor stats
    groups = []
    for lineage, data in lineage_data.items():
        gtex_tissue = data["gtex_tissue"]
        normal_row = normal_by_tissue.get(gtex_tissue) if gtex_tissue else None

        # Aggregate tumor: use weighted median approximation (take study with most samples)
        tumor_rows_sorted = sorted(data["tumor_rows"], key=lambda r: r.get("n") or 0, reverse=True)
        best_tumor = tumor_rows_sorted[0] if tumor_rows_sorted else None

        if best_tumor is None:
            continue

        tumor_median = best_tumor.get("median")
        normal_median = normal_row.get("median") if normal_row else None
        delta = (tumor_median - normal_median) if (tumor_median is not None and normal_median is not None) else None

        # Combine sample counts
        n_tumor = sum(r.get("n") or 0 for r in data["tumor_rows"])
        n_normal = normal_row.get("n") or 0 if normal_row else 0

        groups.append({
            "lineage": lineage,
            "tumor_row": best_tumor,
            "normal_row": normal_row,
            "tumor_studies": data["tumor_studies"],
            "n_tumor": n_tumor,
            "n_normal": n_normal,
            "tumor_median": tumor_median,
            "normal_median": normal_median,
            "delta": delta,
        })

    # Sort by delta descending (most tumor-elevated first)
    groups.sort(key=lambda g: g["delta"] if g["delta"] is not None else -999, reverse=True)
    return groups


def _delta_significance_indicator(delta, n_tumor, n_normal):
    """Return significance indicator based on delta magnitude and sample sizes.
    Since we only have quantile summaries (no raw values), we use a heuristic:
    - Large delta (|Δ| > 2) with adequate samples (n >= 20 each): ***
    - Moderate delta (|Δ| > 1) with adequate samples: **
    - Small delta (|Δ| > 0.5) with adequate samples: *
    - Otherwise: ns or —
    """
    if delta is None:
        return "—"
    if n_tumor < 10 or n_normal < 10:
        return "†"  # low power
    abs_delta = abs(delta)
    if abs_delta > 2.0:
        return "***"
    if abs_delta > 1.0:
        return "**"
    if abs_delta > 0.5:
        return "*"
    return "ns"


def emit_by_tissue_distribution(
    target: str,
    out_dir: Path,
    target_contracts_dir=os.environ.get("TARGET_CONTRACTS_ROOT") or str(contracts_root()),
    *,
    presampled=None,
) -> Path:
    """Pan-cancer by-lineage tumor-vs-normal distribution boxplot for `target`.

    Layout matches the CPTAC per-cohort figure: for each lineage, tumor and normal boxes
    are side-by-side (tumor above, normal below) with delta and significance indicator
    on the right. Lineages are sorted by tumor-normal delta (most elevated first).

    OFFLINE seam: pass `presampled` DataFrame to render without S3 re-read."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Load takeda style
    try:
        style = Path(target_contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
        if style.exists():
            plt.style.use(str(style))
    except Exception:  # noqa: BLE001
        pass

    out_dir = Path(out_dir)
    out_path = out_dir / "figure_pan_cancer_by_tissue_distribution.svg"
    df = presampled if presampled is not None else read_pan_cancer_by_tissue(target)
    if df is None or df.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"{target} — no TCGA/GTEx TPM quantiles", ha="center", va="center", fontsize=10, color="#777")
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    # Build lineage-grouped data
    groups = _build_lineage_groups(df)
    if not groups:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"{target} — no matched lineages", ha="center", va="center", fontsize=10, color="#777")
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    # Count significant elevations
    n_elevated = sum(1 for g in groups if g["delta"] is not None and g["delta"] > 0.5)
    n_lineages = len(groups)

    # Reverse for bottom-up plotting (highest delta at top)
    groups = list(reversed(groups))

    fig_h = min(max(3.6, n_lineages * 0.65 + 1.5), 10.0)
    fig, ax = plt.subplots(figsize=(8.4, fig_h))
    fig.subplots_adjust(top=0.88)  # Space below title

    # Find x-axis extent for annotation placement
    all_maxes = []
    for g in groups:
        if g["tumor_row"] and g["tumor_row"].get("max") is not None:
            all_maxes.append(g["tumor_row"]["max"])
        if g["normal_row"] and g["normal_row"].get("max") is not None:
            all_maxes.append(g["normal_row"]["max"])
    ann_x = max(all_maxes or [0]) + 0.3

    yticks, ylabels = [], []
    for i, g in enumerate(groups):
        drew = False
        # Tumor box (upper position)
        if g["tumor_row"]:
            tr = g["tumor_row"]
            bp = ax.boxplot(
                [[tr["q1"], tr["median"], tr["q3"]]],  # dummy data, we'll use bxp stats
                positions=[i + 0.18],
                orientation="horizontal",
                widths=0.30,
                patch_artist=True,
                showfliers=False,
                manage_ticks=False,
            )
            # Manually set box stats
            stat = _bxp_stat(tr, "")
            bp["boxes"][0].set_path(bp["boxes"][0].get_path())
            bp["boxes"][0].set(facecolor=_TUMOR_FILL, edgecolor=_TUMOR_LINE, linewidth=1.1)
            for w in bp["whiskers"] + bp["caps"]:
                w.set(color=_TUMOR_LINE, linewidth=1.0)
            for m in bp["medians"]:
                m.set(color="white", linewidth=1.4)
            # Redraw with proper stats using bxp
            ax.cla()  # This approach won't work well, let me use bxp directly
            drew = True

        # Normal box (lower position)
        if g["normal_row"]:
            drew = True

    # Actually, let me use ax.bxp for proper rendering
    ax.cla()
    yticks, ylabels = [], []
    for i, g in enumerate(groups):
        # Tumor box
        if g["tumor_row"]:
            tr = g["tumor_row"]
            stat = _bxp_stat(tr, "")
            bp = ax.bxp([stat], positions=[i + 0.18], orientation="horizontal", widths=0.30,
                        patch_artist=True, showfliers=False, manage_ticks=False)
            bp["boxes"][0].set(facecolor=_TUMOR_FILL, edgecolor=_TUMOR_LINE, linewidth=1.1)
            for w in bp["whiskers"] + bp["caps"]:
                w.set(color=_TUMOR_LINE, linewidth=1.0)
            for m in bp["medians"]:
                m.set(color="white", linewidth=1.4)

        # Normal box
        if g["normal_row"]:
            nr = g["normal_row"]
            stat = _bxp_stat(nr, "")
            bp = ax.bxp([stat], positions=[i - 0.18], orientation="horizontal", widths=0.30,
                        patch_artist=True, showfliers=False, manage_ticks=False)
            bp["boxes"][0].set(facecolor=_NORMAL_FILL, edgecolor=_NORMAL_LINE, linewidth=1.1)
            for w in bp["whiskers"] + bp["caps"]:
                w.set(color=_NORMAL_LINE, linewidth=1.0)
            for m in bp["medians"]:
                m.set(color=_NORMAL_LINE, linewidth=1.4)

        yticks.append(i)
        studies_str = ",".join(g["tumor_studies"][:2]) + ("..." if len(g["tumor_studies"]) > 2 else "")
        ylabels.append(f"{g['lineage']}\n({studies_str}, T={g['n_tumor']} N={g['n_normal']})")

        # Highlight elevated indications with light yellow, down-regulated with light green
        delta = g["delta"]
        if delta is not None and delta > 0.5:
            ax.axhspan(i - 0.45, i + 0.45, color="#fffacd", alpha=0.4, zorder=0)
        elif delta is not None and delta < -0.5:
            ax.axhspan(i - 0.45, i + 0.45, color="#d4edda", alpha=0.4, zorder=0)

        # Delta annotation on the right
        sig = _delta_significance_indicator(delta, g["n_tumor"], g["n_normal"])
        delta_str = f"Δ{delta:+.2f} {sig}" if delta is not None else f"— {sig}"
        ax.text(ann_x, i, delta_str, va="center", fontsize=7, color="#555")

    ax.axvline(0.0, color="#888", linewidth=0.6, linestyle="--", alpha=0.5)

    # Add critical normal organ median line (average of critical tissue medians)
    from methods.normal_tissue_safety_common import GTEX_ESSENTIAL_TISSUES
    import numpy as np
    critical_tissues = set(GTEX_ESSENTIAL_TISSUES)
    normal_rows = df[df["source"] == "gtex_normal"].to_dict("records")
    critical_medians = [r["median"] for r in normal_rows
                        if r["group"] in critical_tissues and r.get("median") is not None]
    critical_line = None
    if critical_medians:
        avg_critical = float(np.mean(critical_medians))
        critical_line = ax.axvline(avg_critical, color="#cf2828", linewidth=1.2, linestyle=":", alpha=0.9, zorder=2)

    ax.set_xlim(right=ann_x + 1.2)
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=6.5)

    # Legend in top right, above the delta annotations
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    legend_handles = [
        Patch(facecolor=_TUMOR_FILL, edgecolor=_TUMOR_LINE, label="Tumor (TCGA)"),
        Patch(facecolor=_NORMAL_FILL, edgecolor=_NORMAL_LINE, label="Normal (GTEx)"),
    ]
    if critical_line is not None:
        legend_handles.append(Line2D([0], [0], color="#cf2828", linewidth=1.2, linestyle=":",
                                      label="Avg critical normal median"))
    ax.legend(
        handles=legend_handles,
        loc="lower right",
        fontsize=7,
        frameon=True,
        framealpha=0.9,
    )

    ax.set_xlabel("log2(TPM + 1)  —  recount3 (TCGA tumor vs GTEx normal)")
    ax.set_title(f"{target} — pan-cancer by lineage: tumor vs normal  ({n_elevated}/{n_lineages} elevated)")
    ax.tick_params(axis="y", labelsize=6)
    ax.grid(axis="x", alpha=0.25, linewidth=0.4)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plot_data(target: str, out_dir: Path) -> Path:
    """The per-(source, group) quantile rows behind the figure (one row per tissue/study)."""
    df = read_pan_cancer_by_tissue(target)
    out_file = Path(out_dir) / "plot_data_pan_cancer_by_tissue.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_plotly_specs(
    target: str,
    out_dir: Path,
    target_contracts_dir=os.environ.get("TARGET_CONTRACTS_ROOT") or str(contracts_root()),
    *,
    presampled=None,
) -> list:
    """Interactive by-tissue distribution built from the SAME quantile rows the SVG uses (no drift).
    Uses plotly's precomputed-box fields (q1/median/q3/lowerfence/upperfence) — no per-sample data.
    Best-effort (plotly optional). OFFLINE seam: pass `presampled` (the persisted quantile-rows
    DataFrame) to render from it with NO S3 re-read."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        print(f"[tcga_gtex_tpm_quantiles] plotly spec emission skipped: {e}", file=__import__("sys").stderr)
        return []
    df = presampled if presampled is not None else read_pan_cancer_by_tissue(target)
    if df is None or df.empty:
        return []
    tumor_rows, normal_rows = _ordered_rows(df)

    def _fences(r):
        q1, q3 = float(r["q1"]), float(r["q3"])
        iqr = q3 - q1
        return max(float(r["min"]), q1 - 1.5 * iqr), min(float(r["max"]), q3 + 1.5 * iqr)

    fig = go.Figure()
    # normal first (drawn lower), tumor second — plotly categorical y stacks bottom-up, so append
    # normal (reversed so highest-median normal sits just under the tumor block) then tumor.
    for rows, (fill, line), name in [
        (list(reversed(normal_rows)), (_NORMAL_FILL, _NORMAL_LINE), "GTEx normal"),
        (list(reversed(tumor_rows)), (_TUMOR_FILL, _TUMOR_LINE), "TCGA tumor"),
    ]:
        if not rows:
            continue
        ylabels = [f"{r['group']} (n={_n(r)})" for r in rows]
        lf = [_fences(r)[0] for r in rows]
        uf = [_fences(r)[1] for r in rows]
        fig.add_trace(
            go.Box(
                y=ylabels,
                q1=[float(r["q1"]) for r in rows],
                median=[float(r["median"]) for r in rows],
                q3=[float(r["q3"]) for r in rows],
                lowerfence=lf,
                upperfence=uf,
                orientation="h",
                name=name,
                marker_color=line,
                fillcolor=fill,
                line=dict(width=1),
            )
        )
    fig.update_layout(
        title=f"{target} — pan-cancer expression by tissue: TCGA tumor vs GTEx normal",
        xaxis_title="log2(TPM + 1) — recount3 / GENCODE v26 (one axis)",
        template="plotly_white",
        margin=dict(l=150, r=40, t=50, b=50),
        boxmode="overlay",
    )
    (Path(out_dir) / "figure_pan_cancer_by_tissue_distribution.plotly.json").write_text(fig.to_json())
    return [
        {
            "id": "pan_cancer_by_tissue_distribution",
            "path": "figure_pan_cancer_by_tissue_distribution.plotly.json",
            "type": "plotly",
        }
    ]
