"""depmap_protein_abundance.cli — cell-line protein-abundance distribution + classifier.

The PROTEIN twin of depmap_expression_distribution. Reads the DepMap 26Q1
proteomics Gygi Lab CCLE TMT MS matrix (harmonized_MS_CCLE_Gygi.csv — a
ModelID x UniProt-accession whole-proteome matrix, ~12,558 proteins) and reports
the per-target abundance distribution across cell lines + a per-lineage breakdown.

Emits the `cellline-protein-abundance` card contract fields, primary categorical
`protein_expression_class` ∈ {broadly_high | broadly_moderate | lineage_restricted
| broadly_low | data_unavailable} — the SAME distribution vocab as
cellline-rna-distribution (NOT the tumor-vs-normal contrast vocab of
tumor-protein-abundance-cptac).

Two resolution jobs (both via already-landed catalog artifacts):
  1. target symbol → UniProt accession (the matrix COLUMN) via the source's
     target_resolution sidecar (`native_row_key` = accession,
     `hgnc_primary_symbol_at_resolution` = symbol). Same convention as the
     topology reader — the payload has no symbol column.
  2. ModelID (the matrix ROW) → OncotreeLineage via Model.csv, for the per-lineage
     groupby (read-side, cheap — proteomics is per-ModelID at read time).

MS detection is sparse (shotgun TMT under-samples membrane/low-abundance proteins),
so `fraction_detected` is a first-class signal and `broadly_low` keys off detection
fraction, not just abundance magnitude. A protein absent from the matrix →
`data_unavailable` (coverage gap, NOT a measured negative).
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

METHOD_VERSION = "0.1.0"

S3_BUCKET = "onc-compbio"
_PROT_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1-proteomics"
MATRIX_KEY = f"{_PROT_PREFIX}/harmonized_MS_CCLE_Gygi.csv"
SIDECAR_KEY = f"{_PROT_PREFIX}/harmonized_MS_CCLE_Gygi.csv.target_resolution.parquet"
# Model.csv (ModelID -> OncotreeLineage) lives in the sister RNA/omics source.
MODEL_KEY = "data-catalog/sources/depmap-consortium/dmc-26q1/Model.csv"
DEFAULT_AWS_PROFILE = "cbg"

# --- card thresholds (mirror cellline-protein-abundance.card.yaml) ---
BROADLY_DETECTED_FRACTION = 0.70   # detected in >70% of panel
LOW_DETECTION_FRACTION = 0.30      # detected in <30% → broadly_low
LINEAGE_RESTRICTED_MIN = 0.10
LINEAGE_RESTRICTED_MAX = 0.70
HIGH_ABUNDANCE_PERCENTILE = 0.70   # panel-relative "high" cutoff
MIN_LINEAGE_SIZE = 5


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


@lru_cache(maxsize=8)
def _cached_csv(path_or_none, bucket, key):
    """Read a CSV substrate (whole file) ONCE per (path/key) per process (retrieval-opt #3).

    The Gygi MS matrix + Model.csv are large and target-INDEPENDENT — the summary pass and the
    figure pass both read them in full, so without caching one card did ≥2 full reads (the review
    measured the Gygi CSV read twice + Model.csv twice, uncached). Keyed on the identity args only
    (no **kw), so callers must not pass read_csv kwargs through this path — the two large substrates
    here need none. Returns the SHARED DataFrame; callers treat it read-only (they select columns /
    filter, never mutate in place)."""
    import pandas as pd
    if path_or_none is not None:
        return pd.read_csv(path_or_none)
    _ensure_aws_profile()
    import boto3
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_csv(io.BytesIO(body))


def _read_csv(path_or_none, bucket, key, **kw):
    import pandas as pd
    # Uncached path preserved for callers that pass read_csv kwargs (e.g. usecols/dtype); the two
    # large target-independent substrates (matrix, Model.csv) go through _cached_csv instead.
    if kw:
        if path_or_none is not None:
            return pd.read_csv(path_or_none, **kw)
        _ensure_aws_profile()
        import boto3
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return pd.read_csv(io.BytesIO(body), **kw)
    return _cached_csv(path_or_none, bucket, key)


@lru_cache(maxsize=8)
def _read_parquet(path_or_none, bucket, key):
    """Read a parquet substrate (whole file) ONCE per (path/key) per process (retrieval-opt #3).
    The Gygi target_resolution sidecar is read by resolve_accession on both the summary + figure
    pass; caching removes the duplicate read. Returned frame is treated read-only by callers."""
    import pandas as pd
    if path_or_none is not None:
        return pd.read_parquet(path_or_none)
    _ensure_aws_profile()
    import boto3
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def resolve_accession(target: str, sidecar_path=None) -> Optional[str]:
    """target (HGNC symbol) → UniProt accession (matrix column) via the sidecar.

    The Gygi matrix columns are UniProt accessions (native_row_key); the payload
    carries no symbol column, so we MUST join via the sidecar (same discipline as
    the topology reader)."""
    df = _read_parquet(sidecar_path, S3_BUCKET, SIDECAR_KEY)
    sym = target.strip().upper()
    col = "hgnc_primary_symbol_at_resolution"
    if col not in df.columns or "native_row_key" not in df.columns:
        return None
    hit = df[df[col].astype(str).str.upper() == sym]
    if not len(hit):
        return None
    val = hit.iloc[0]["native_row_key"]
    return str(val) if val is not None and str(val) != "nan" else None


def load_abundance_column(accession: str, matrix_path=None):
    """Return (abundance_by_model, panel_size) for the protein column.

    abundance_by_model = {ModelID: log2_abundance} dropping NaNs (undetected);
    panel_size = total ModelID rows in the matrix (the detection denominator).
    The matrix is ModelID-rows x accession-cols; the first column is the ModelID
    (ACH-*). Returns (None, panel_size) if the accession is absent from the matrix.
    Single read of the matrix (panel size + column come from the same load)."""
    import pandas as pd
    df = _read_csv(matrix_path, S3_BUCKET, MATRIX_KEY)
    id_col = df.columns[0]  # unnamed index col holding ACH-* ids
    panel_size = len(df)
    # accession columns may be isoform-suffixed (e.g. Q8WY21-3); prefer the exact
    # canonical accession, else the first column whose base (pre-'-') matches.
    cols = [c for c in df.columns if c != id_col]
    if accession in cols:
        target_col = accession
    else:
        base_matches = [c for c in cols if str(c).split("-")[0] == accession]
        if not base_matches:
            return None, panel_size
        target_col = base_matches[0]
    out = {}
    for _, row in df[[id_col, target_col]].iterrows():
        v = row[target_col]
        if v is not None and pd.notna(v):
            out[str(row[id_col])] = float(v)
    return out, panel_size


def load_model_lineage(model_path=None) -> dict:
    """ModelID → OncotreeLineage from Model.csv."""
    df = _read_csv(model_path, S3_BUCKET, MODEL_KEY)
    id_col = "ModelID" if "ModelID" in df.columns else df.columns[0]
    lin_col = "OncotreeLineage" if "OncotreeLineage" in df.columns else None
    if lin_col is None:
        return {}
    return {str(r[id_col]): (str(r[lin_col]) if r[lin_col] is not None else None)
            for _, r in df[[id_col, lin_col]].iterrows()}


def classify_protein_abundance(fraction_detected: float,
                               median_abundance: Optional[float],
                               per_lineage: list,
                               high_cutoff: Optional[float]) -> str:
    """Distribution vocab (mirrors cellline-rna-distribution's expression_class).

    - broadly_low:        detected in < LOW_DETECTION_FRACTION of the panel (MS-absent)
    - broadly_high:       detected in > BROADLY_DETECTED_FRACTION AND median >= panel high cutoff
    - broadly_moderate:   detected in > BROADLY_DETECTED_FRACTION but not high
    - lineage_restricted: LINEAGE_RESTRICTED_MIN <= detection <= LINEAGE_RESTRICTED_MAX
    - data_unavailable:   handled upstream (protein absent from matrix)
    """
    f = fraction_detected
    if f < LOW_DETECTION_FRACTION:
        return "broadly_low"
    if f > BROADLY_DETECTED_FRACTION:
        if high_cutoff is not None and median_abundance is not None and median_abundance >= high_cutoff:
            return "broadly_high"
        return "broadly_moderate"
    # middle band → lineage-restricted candidate
    if LINEAGE_RESTRICTED_MIN <= f <= LINEAGE_RESTRICTED_MAX:
        return "lineage_restricted"
    return "broadly_moderate"


def _percentiles(values: list) -> dict:
    import statistics
    if not values:
        return {}
    s = sorted(values)
    def pct(p):
        if len(s) == 1:
            return s[0]
        idx = p * (len(s) - 1)
        lo = int(idx)
        frac = idx - lo
        if lo + 1 < len(s):
            return s[lo] * (1 - frac) + s[lo + 1] * frac
        return s[lo]
    return {
        "median": statistics.median(s),
        "p5": pct(0.05), "p25": pct(0.25), "p75": pct(0.75), "p95": pct(0.95),
    }


def compute_summary(target: str, abundance_by_model: Optional[dict],
                    lineage_by_model: dict, n_panel: Optional[int] = None) -> dict:
    """Build the cellline-protein-abundance card summary."""
    if abundance_by_model is None:
        return {
            "protein_expression_class": "data_unavailable",
            "n_cell_lines_evaluated": 0,
            "n_cell_lines_in_panel": n_panel,
            "fraction_detected": 0.0,
            "median_log2_abundance_panel": None,
            "protein_effect_size": None,
            "n_lineages_evaluated": 0,
            "per_lineage_stats": [],
            "n_lineage_restricted_lineages": 0,
            "method_version": METHOD_VERSION,
        }
    vals = list(abundance_by_model.values())
    n_eval = len(vals)
    # panel denominator: total MS lines. If not supplied, use n_eval (detection=1.0
    # would be wrong) — the reader passes the true panel size.
    denom = n_panel if (n_panel and n_panel > 0) else n_eval
    fraction_detected = (n_eval / denom) if denom else 0.0
    pcts = _percentiles(vals)
    median_abund = pcts.get("median")
    # panel-relative high cutoff = the HIGH_ABUNDANCE_PERCENTILE of the panel.
    high_cutoff = None
    if vals:
        hp = _percentiles(vals)
        # HIGH_ABUNDANCE_PERCENTILE quantile of the detected distribution
        s = sorted(vals)
        idx = HIGH_ABUNDANCE_PERCENTILE * (len(s) - 1)
        lo = int(idx); frac = idx - lo
        high_cutoff = s[lo] * (1 - frac) + s[min(lo + 1, len(s) - 1)] * frac

    # per-lineage groupby
    by_lin: dict = {}
    for mid, v in abundance_by_model.items():
        lin = lineage_by_model.get(mid)
        if lin:
            by_lin.setdefault(lin, []).append(v)
    # detection per lineage needs the lineage panel size; approximate detected-only
    # here (lineage denominator = detected lines in that lineage in the MS matrix).
    per_lineage = []
    n_lineage_restricted = 0
    for lin, lv in by_lin.items():
        if len(lv) < MIN_LINEAGE_SIZE:
            continue
        import statistics
        per_lineage.append({
            "lineage": lin, "n": len(lv),
            "median_log2_abundance": statistics.median(lv),
            # detection here is within-detected; a true fraction needs lineage panel
            # size (Model.csv total per lineage) — computed by the reader when it has
            # the full model table. Left as n for the card's descriptive table.
        })
    per_lineage.sort(key=lambda d: d["median_log2_abundance"], reverse=True)

    klass = classify_protein_abundance(fraction_detected, median_abund, per_lineage, high_cutoff)
    return {
        "protein_expression_class": klass,
        "n_cell_lines_evaluated": n_eval,
        "n_cell_lines_in_panel": denom,
        "fraction_detected": round(fraction_detected, 4),
        "median_log2_abundance_panel": median_abund,
        "p5_log2_abundance_panel": pcts.get("p5"),
        "p25_log2_abundance_panel": pcts.get("p25"),
        "p75_log2_abundance_panel": pcts.get("p75"),
        "p95_log2_abundance_panel": pcts.get("p95"),
        "log2_abundance_iqr": (pcts.get("p75") - pcts.get("p25"))
                              if (pcts.get("p75") is not None and pcts.get("p25") is not None) else None,
        "protein_effect_size": median_abund,     # parity w/ tumor-protein-abundance-cptac field
        "n_lineages_evaluated": len(per_lineage),
        "per_lineage_stats": per_lineage,
        "n_lineage_restricted_lineages": n_lineage_restricted,
        "method_version": METHOD_VERSION,
    }


DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))


def _load_takeda_style(target_contracts_dir: Path):
    """Load the Takeda mplstyle + palette module (mirror depmap_expression_distribution)."""
    import sys as _sys
    import matplotlib.pyplot as plt
    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    _sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette
    return takeda_palette


@lru_cache(maxsize=2)
def _all_protein_median_null(matrix_path=None) -> tuple:
    """Per-protein median-abundance vector across ALL proteins in the Gygi matrix —
    the all-gene null for the cellline-protein-abundance percentile.

    The matrix is WIDE (cell-lines × protein columns), so this is one column-median
    pass (axis=0) over the already-cached matrix. lru_cached (built once). Returned as
    a tuple so it stays hashable/cache-safe. Zero new I/O beyond the matrix read that
    load_abundance_column already does."""
    try:
        df = _read_csv(matrix_path, S3_BUCKET, MATRIX_KEY)
        id_col = df.columns[0]
        med = df.drop(columns=[id_col]).median(axis=0, numeric_only=True)  # one median per protein col
        return tuple(float(x) for x in med.tolist())
    except Exception:
        return tuple()


def target_allgene_percentile(median_abund, matrix_path=None):
    """Percentile + class of this target's median abundance among ALL proteins' medians."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # methods/ on path
    from percentile_null import percentile_rank, classify_percentile
    null_vec = _all_protein_median_null(matrix_path)
    pct = percentile_rank(median_abund, null_vec)
    return pct, classify_percentile(pct)


def _panel_high_cutoff(vals: list) -> Optional[float]:
    """Panel-relative HIGH cutoff = HIGH_ABUNDANCE_PERCENTILE quantile of detected values.
    MS abundance has no absolute expressed/highly-expressed thresholds like RNA log2(TPM+1);
    the reference line is panel-relative (mirrors compute_summary's high_cutoff)."""
    if not vals:
        return None
    s = sorted(vals)
    idx = HIGH_ABUNDANCE_PERCENTILE * (len(s) - 1)
    lo = int(idx); frac = idx - lo
    return s[lo] * (1 - frac) + s[min(lo + 1, len(s) - 1)] * frac


def emit_density_protein(abundance_by_model: dict, target_symbol: str, summary: dict,
                         out_dir: Path, target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS) -> Path:
    """PRIMARY figure: KDE + histogram of log2 protein abundance across detected DepMap lines,
    with the panel-relative HIGH cutoff + the panel median as reference lines. Sparse MS detection
    means the x-axis is detected-lines-only; fraction_detected (in the title) is load-bearing."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy.stats import gaussian_kde

    _load_takeda_style(target_contracts_dir)
    out_path = out_dir / "figure_density_protein_abundance.svg"
    vals = np.array(list((abundance_by_model or {}).values()), dtype=float)
    if vals.size == 0:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"{target_symbol} — not quantified in the Gygi MS panel",
                ha="center", va="center", fontsize=10, color="#777"); ax.set_axis_off()
        fig.savefig(out_path); plt.close(fig); return out_path

    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.hist(vals, bins=40, density=True, alpha=0.45, color="#0a2540", edgecolor="white")
    if vals.size >= 10:
        kde = gaussian_kde(vals)
        xs = np.linspace(vals.min() - 0.2, vals.max() + 0.2, 500)
        ax.plot(xs, kde(xs), color="#cf2828", linewidth=2)
    med = summary.get("median_log2_abundance_panel")
    hi = _panel_high_cutoff(list(vals))
    if med is not None:
        ax.axvline(med, color="#888", linestyle=":", linewidth=1, label=f"panel median ({med:.2f})")
    if hi is not None:
        ax.axvline(hi, color="#f0a020", linestyle="--", linewidth=1,
                   label=f"panel-high (p70={hi:.2f})")
    frac = summary.get("fraction_detected")
    ax.set_xlabel("log2 protein abundance (Gygi TMT MS)")
    ax.set_ylabel("Density")
    ax.set_title(f"{target_symbol} — cell-line protein abundance "
                 f"(n={vals.size} detected"
                 + (f", {frac:.0%} of panel)" if frac is not None else ")"))
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_lineage_strip_protein(abundance_by_model: dict, lineage_by_model: dict,
                               target_symbol: str, summary: dict, out_dir: Path,
                               target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS) -> Path:
    """Per-lineage strip plot of log2 protein abundance, lineages ordered by median desc (n>=5)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    pal = _load_takeda_style(target_contracts_dir)
    out_path = out_dir / "figure_lineage_strip_protein.svg"
    records = [{"lineage": lineage_by_model.get(mid) or "unknown", "abund": v}
               for mid, v in (abundance_by_model or {}).items()]
    df = pd.DataFrame(records)
    if df.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"{target_symbol} — no MS detection", ha="center", va="center",
                fontsize=10, color="#777"); ax.set_axis_off()
        fig.savefig(out_path); plt.close(fig); return out_path

    lm = df.groupby("lineage")["abund"].agg(["median", "count"])
    lm = lm[lm["count"] >= MIN_LINEAGE_SIZE].sort_values("median", ascending=False)
    ordered = list(lm.index)
    fig_h = min(max(3.5, len(ordered) * 0.2), 7.0)
    fig, ax = plt.subplots(figsize=(7, fig_h))
    for i, lin in enumerate(ordered):
        scores = df[df["lineage"] == lin]["abund"].values
        jitter = np.random.RandomState(42 + i).uniform(-0.15, 0.15, size=len(scores))
        color = pal.get_lineage_color(lin) if hasattr(pal, "get_lineage_color") else "#0a2540"
        ax.scatter(scores, np.full(len(scores), i) + jitter, alpha=0.5, s=8, color=color)
        ax.scatter([np.median(scores)], [i], color="#B22222", s=30, marker="|", zorder=5)
    hi = _panel_high_cutoff(list(df["abund"].values))
    if hi is not None:
        ax.axvline(hi, color="#f0a020", linestyle="--", linewidth=1)
    ax.set_yticks(range(len(ordered))); ax.set_yticklabels(ordered, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("log2 protein abundance (Gygi TMT MS)")
    ax.set_title(f"{target_symbol} — per-lineage protein abundance (n≥5; top=highest median)")
    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_plot_data_protein(abundance_by_model: dict, lineage_by_model: dict,
                           out_dir: Path) -> Path:
    """Per-cell-line long-format parquet (the card's declared plot_data:
    per_cell_line_protein_abundance_with_lineage_tags) — SAME series the SVGs/plotly draw."""
    import pandas as pd
    rows = [{"model_id": mid, "lineage": lineage_by_model.get(mid),
             "log2_abundance": v} for mid, v in (abundance_by_model or {}).items()]
    df = pd.DataFrame(rows)
    out_file = out_dir / "plot_data_protein_abundance.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


# Indication → DepMap OncotreeLineage (mirrors depmap_expression_distribution.INDICATION_LINEAGE) —
# DepMap has no per-indication axis, so the indication-relevant cell-line signal IS its lineage.
INDICATION_LINEAGE = {
    "COADREAD": "Bowel", "COAD": "Bowel", "READ": "Bowel", "LUAD": "Lung", "LUSC": "Lung",
    "NSCLC": "Lung", "BRCA": "Breast", "PAAD": "Pancreas", "PDAC": "Pancreas", "SKCM": "Skin",
    "STAD": "Stomach", "PRAD": "Prostate", "OV": "Ovary", "KIRC": "Kidney", "GBM": "CNS/Brain",
    "LGG": "CNS/Brain", "HNSC": "Head and Neck", "BLCA": "Bladder/Urinary Tract", "LIHC": "Liver",
    "ESCA": "Esophagus/Stomach", "CESC": "Cervix",
}


def emit_plotly_specs(abundance_by_model: dict, lineage_by_model: dict, target_symbol: str,
                      summary: dict, out_dir: Path,
                      target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS,
                      indication: str = None) -> list:
    """Interactive Plotly siblings (dynamic-dashboard Phase A) built from the SAME
    abundance_by_model the SVGs use — no drift. Writes:
      - figure_density_protein_abundance.plotly.json   (histogram + relative abundance BUCKETS)
      - figure_waterfall_protein_abundance.plotly.json (ranked per-cell-line bars)
      - figure_lineage_protein_abundance.plotly.json   (per-lineage box, n>=5; indication highlighted)
    Mirrors the RNA depmap_expression_distribution emitter (item #2). Protein abundance is on a
    RELATIVE scale (Gygi TMT log2-ratio), so density buckets shade relative to the panel median +
    panel-high p70 cutoff (not absolute thresholds like RNA's 1.0/5.0). Best-effort."""
    try:
        import numpy as np
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        print(f"[cellline-protein-abundance] plotly spec emission skipped: {e}", file=__import__("sys").stderr)
        return []
    if not abundance_by_model:
        return []
    written = []
    vals = list(abundance_by_model.values())
    hi = _panel_high_cutoff(vals)
    med = summary.get("median_log2_abundance_panel")
    reflines = [(med, "#888", "dot", "panel median"), (hi, "#f0a020", "dash", "panel-high p70")]
    # density histogram + RELATIVE abundance buckets (item #2)
    try:
        arr = np.array(vals, dtype=float)
        xmin, xmax = float(arr.min()) - 0.3, float(arr.max()) + 0.3
        fig = go.Figure(go.Histogram(x=vals, histnorm="probability density", nbinsx=40,
                        marker_color="#0a2540", marker_line_color="white", marker_line_width=0.5,
                        opacity=0.55,
                        hovertemplate="log2 abundance %{x:.2f}<br>density %{y:.3f}<extra></extra>"))
        # Shade abundance regimes RELATIVE to the panel (protein MS has no absolute expressed cutoff):
        # below median / median→p70 / ≥p70 (panel-high). Skipped if med/hi absent.
        if med is not None and hi is not None and hi > med:
            for x0, x1, fill, lab in [
                (xmin, med, "rgba(150,160,170,0.10)", "below median"),
                (med, hi, "rgba(240,160,32,0.09)", "moderate"),
                (hi, xmax, "rgba(207,40,40,0.09)", "panel-high"),
            ]:
                if x1 > x0:
                    fig.add_vrect(x0=x0, x1=x1, fillcolor=fill, line_width=0, layer="below",
                                  annotation_text=lab, annotation_position="top",
                                  annotation=dict(font_size=9, font_color="#8a94a0"))
        for xv, col, dash, lab in reflines:
            if xv is not None:
                fig.add_vline(x=xv, line=dict(color=col, dash=dash, width=1.5))
        fig.update_layout(title=dict(text=f"{target_symbol} — cell-line protein abundance "
                                          f"(n={len(vals)} detected)", font_size=13),
                          xaxis_title="log2 protein abundance (Gygi TMT MS)", yaxis_title="Density",
                          template="plotly_white", showlegend=False, height=300,
                          margin=dict(l=54, r=16, t=40, b=44), font=dict(size=11))
        (out_dir / "figure_density_protein_abundance.plotly.json").write_text(fig.to_json())
        written.append({"id": "density_protein_abundance",
                        "path": "figure_density_protein_abundance.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[cellline-protein-abundance] density plotly skipped: {e}", file=__import__("sys").stderr)
    # ranked waterfall
    try:
        rows = sorted(((mid, v, (lineage_by_model.get(mid) or "unknown"))
                       for mid, v in abundance_by_model.items()), key=lambda r: r[1])
        y = [v for _, v, _ in rows]
        names = [mid for mid, _, _ in rows]
        lins = [lg for _, _, lg in rows]
        fig = go.Figure(go.Bar(x=list(range(len(rows))), y=y, marker_color="#0a2540",
                        customdata=list(zip(names, lins)),
                        hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>log2 abundance %{y:.2f}<extra></extra>"))
        if hi is not None:
            fig.add_hline(y=hi, line=dict(color="#f0a020", dash="dash", width=1.5),
                          annotation_text="panel-high p70", annotation_position="top left")
        fig.update_layout(title=f"{target_symbol} — cell-line protein abundance (ranked)",
                          xaxis_title=f"Cell lines (n={len(rows)}, sorted)",
                          yaxis_title="log2 protein abundance", template="plotly_white",
                          showlegend=False, bargap=0, margin=dict(l=60, r=20, t=50, b=50))
        (out_dir / "figure_waterfall_protein_abundance.plotly.json").write_text(fig.to_json())
        written.append({"id": "waterfall_protein_abundance",
                        "path": "figure_waterfall_protein_abundance.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[cellline-protein-abundance] waterfall plotly skipped: {e}", file=__import__("sys").stderr)
    # per-lineage box (item #2 — mirrors the RNA lineage plot; n>=5, ordered by median, indication
    # lineage highlighted red). The indication-relevant cell-line protein view IS its DepMap lineage.
    try:
        by_lineage: dict = {}
        for mid, v in abundance_by_model.items():
            lg = lineage_by_model.get(mid) or "unknown"
            by_lineage.setdefault(lg, []).append(v)
        lins2 = [(lg, lv) for lg, lv in by_lineage.items() if len(lv) >= 5]
        lins2.sort(key=lambda lv: float(np.median(lv[1])))   # ascending → highest median at top
        target_lineage = INDICATION_LINEAGE.get((indication or "").upper()) if indication else None
        fig = go.Figure()
        for lg, lv in lins2:
            is_target = (lg == target_lineage)
            fig.add_trace(go.Box(
                x=lv, name=lg, orientation="h", boxpoints="all", jitter=0.4, pointpos=0,
                marker=dict(size=3, opacity=0.5, color="#cf2828" if is_target else "#0a2540"),
                line=dict(color="#cf2828" if is_target else "#7fa7c0", width=2 if is_target else 1),
                hovertemplate=f"{lg}<br>log2 abundance %{{x:.2f}}<extra></extra>"))
        for xv, col, dash, lab in reflines:
            if xv is not None:
                fig.add_vline(x=xv, line=dict(color=col, dash=dash, width=1.2))
        ttl = f"{target_symbol} — per-lineage protein abundance (n≥5)"
        if target_lineage:
            ttl += f" · {target_lineage} highlighted"
        fig.update_layout(title=dict(text=ttl, font_size=13),
                          xaxis_title="log2 protein abundance (Gygi TMT MS)", template="plotly_white",
                          showlegend=False, margin=dict(l=130, r=16, t=40, b=40), font=dict(size=11),
                          height=max(260, 18 * len(lins2) + 70))
        (out_dir / "figure_lineage_protein_abundance.plotly.json").write_text(fig.to_json())
        written.append({"id": "lineage_protein_abundance",
                        "path": "figure_lineage_protein_abundance.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[cellline-protein-abundance] lineage plotly skipped: {e}", file=__import__("sys").stderr)
    return written


def load_and_classify(target: str, matrix_path=None, sidecar_path=None,
                      model_path=None) -> dict:
    """Full pipeline for one target: resolve accession → read column → classify.
    Panel size (detection denominator) comes from the same matrix read."""
    acc = resolve_accession(target, sidecar_path=sidecar_path)
    if acc is None:
        return compute_summary(target, None, {}, n_panel=None)
    col, panel_size = load_abundance_column(acc, matrix_path=matrix_path)
    if col is None:
        return compute_summary(target, None, {}, n_panel=panel_size)
    lineage = load_model_lineage(model_path=model_path)
    return compute_summary(target, col, lineage, n_panel=panel_size)


def _main(argv=None):
    import argparse, json
    ap = argparse.ArgumentParser(description="Cell-line protein-abundance distribution for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--matrix-path", default=None)
    ap.add_argument("--sidecar-path", default=None)
    ap.add_argument("--model-path", default=None)
    args = ap.parse_args(argv)
    out = load_and_classify(args.target, matrix_path=args.matrix_path,
                            sidecar_path=args.sidecar_path, model_path=args.model_path)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    _main()
