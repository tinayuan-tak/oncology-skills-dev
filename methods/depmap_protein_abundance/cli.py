"""depmap_protein_abundance.cli — cell-line protein-abundance distribution + classifier.

The PROTEIN twin of depmap_expression_distribution. Reads the DepMap 26Q1
proteomics Gygi Lab CCLE TMT MS matrix (harmonized_MS_CCLE_Gygi.csv — a
ModelID x UniProt-accession whole-proteome matrix, ~12,558 proteins) and reports
the per-target abundance distribution across cell lines + a per-lineage breakdown.

Emits the `protein-abundance-celline` card contract fields, primary categorical
`protein_expression_class` ∈ {broadly_high | broadly_moderate | lineage_restricted
| broadly_low | data_unavailable} — the SAME distribution vocab as
expression-distribution (NOT the tumor-vs-normal contrast vocab of
protein-presence-cptac).

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
from typing import Optional

METHOD_VERSION = "0.1.0"

S3_BUCKET = "onc-compbio"
_PROT_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1-proteomics"
MATRIX_KEY = f"{_PROT_PREFIX}/harmonized_MS_CCLE_Gygi.csv"
SIDECAR_KEY = f"{_PROT_PREFIX}/harmonized_MS_CCLE_Gygi.csv.target_resolution.parquet"
# Model.csv (ModelID -> OncotreeLineage) lives in the sister RNA/omics source.
MODEL_KEY = "data-catalog/sources/depmap-consortium/dmc-26q1/Model.csv"
DEFAULT_AWS_PROFILE = "cbg"

# --- card thresholds (mirror protein-abundance-celline.card.yaml) ---
BROADLY_DETECTED_FRACTION = 0.70   # detected in >70% of panel
LOW_DETECTION_FRACTION = 0.30      # detected in <30% → broadly_low
LINEAGE_RESTRICTED_MIN = 0.10
LINEAGE_RESTRICTED_MAX = 0.70
HIGH_ABUNDANCE_PERCENTILE = 0.70   # panel-relative "high" cutoff
MIN_LINEAGE_SIZE = 5


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _read_csv(path_or_none, bucket, key, **kw):
    import pandas as pd
    if path_or_none is not None:
        return pd.read_csv(path_or_none, **kw)
    _ensure_aws_profile()
    import boto3
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_csv(io.BytesIO(body), **kw)


def _read_parquet(path_or_none, bucket, key):
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
    """Distribution vocab (mirrors expression-distribution's expression_class).

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
    """Build the protein-abundance-celline card summary."""
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
        "protein_effect_size": median_abund,     # parity w/ protein-presence-cptac field
        "n_lineages_evaluated": len(per_lineage),
        "per_lineage_stats": per_lineage,
        "n_lineage_restricted_lineages": n_lineage_restricted,
        "method_version": METHOD_VERSION,
    }


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
