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
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

from methods.catalog_query.read import bucket_key_for, bucket_prefix_for

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


_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton. Constructing one costs ~0.4s (region probe +
    client init) and read_pan_cancer_by_tissue fires several times per card render (the three figure
    emitters share it), so we build it ONCE. pyarrow's S3FileSystem is safe to share across threads
    for reads (the parallel card-read path since skills PR #515); double-checked locking so
    concurrent first-callers build a single instance. Region pinned to us-east-1 (the onc-compbio
    bucket) to skip the region-probe round-trip. Mirrors the sibling
    tcga_gtex_expression_distribution reader's _get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as fs

                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


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
        from methods.target_id_sidecar import is_definitively_absent

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


# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
def emit_by_tissue_distribution(
    target: str,
    out_dir: Path,
    target_contracts_dir=os.environ.get("TARGET_CONTRACTS_ROOT")
    or str(Path(__file__).resolve().parents[2].parent / "rnd-computational-biology-oncology-target-contracts"),
    *,
    presampled=None,
) -> Path:
    """Pan-cancer by-tissue tumor-vs-normal distribution boxplot for `target`, drawn from the
    precomputed quantile product. TCGA tumor (per study) + GTEx normal (per tissue) share ONE
    log2(TPM+1) axis. Tumor boxes (navy) on top, normal boxes (blue) below, each block sorted by
    median descending. Returns the SVG path (placeholder SVG if the gene is absent).

    OFFLINE seam (figure-consolidation Stage 6): pass `presampled` — the persisted quantile-rows
    DataFrame (columns match read_pan_cancer_by_tissue) — to render from it with NO S3 re-read.
    When None the legacy live read (read_pan_cancer_by_tissue) is taken."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Reuse the takeda style if present (best-effort; identical helper to the CPTAC emitter).
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

    tumor_rows, normal_rows = _ordered_rows(df)
    # Build ax.bxp stat lists; tumor block on top (higher y), normal block below.
    n_total = len(tumor_rows) + len(normal_rows)
    fig_h = min(max(3.5, n_total * 0.32 + 1.0), 12.0)
    fig, ax = plt.subplots(figsize=(8.4, fig_h))

    positions, stats, colors = [], [], []
    y = n_total
    for r in tumor_rows:
        stats.append(_bxp_stat(r, f"{r['group']} (n={_n(r)})"))
        positions.append(y)
        colors.append((_TUMOR_FILL, _TUMOR_LINE))
        y -= 1
    # small gap between the tumor block and the normal block
    y -= 0.6
    for r in normal_rows:
        stats.append(_bxp_stat(r, f"{r['group']} (n={_n(r)})"))
        positions.append(y)
        colors.append((_NORMAL_FILL, _NORMAL_LINE))
        y -= 1

    bp = ax.bxp(
        stats,
        positions=positions,
        orientation="horizontal",
        widths=0.62,
        patch_artist=True,
        showfliers=False,
        manage_ticks=True,
    )
    for patch, (fill, line) in zip(bp["boxes"], colors):
        patch.set(facecolor=fill, edgecolor=line, linewidth=1.0)
    for i, med in enumerate(bp["medians"]):
        med.set(color="white" if colors[i][0] == _TUMOR_FILL else _NORMAL_LINE, linewidth=1.3)
    for whisker in bp["whiskers"]:
        whisker.set(color="#888", linewidth=0.8)
    for cap in bp["caps"]:
        cap.set(color="#888", linewidth=0.8)

    ax.set_xlabel("log2(TPM + 1)  —  recount3 / GENCODE v26 (TCGA tumor + GTEx normal, one axis)")
    ax.set_title(f"{target} — pan-cancer expression by tissue: TCGA tumor vs GTEx normal")
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(facecolor=_TUMOR_FILL, edgecolor=_TUMOR_LINE, label="TCGA tumor (per study)"),
            Patch(facecolor=_NORMAL_FILL, edgecolor=_NORMAL_LINE, label="GTEx normal (per tissue)"),
        ],
        loc="lower right",
        fontsize=8,
        frameon=True,
    )
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
    target_contracts_dir=os.environ.get("TARGET_CONTRACTS_ROOT")
    or str(Path(__file__).resolve().parents[2].parent / "rnd-computational-biology-oncology-target-contracts"),
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
