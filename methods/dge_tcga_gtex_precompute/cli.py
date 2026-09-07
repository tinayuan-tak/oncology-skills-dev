#!/usr/bin/env python3
"""dge-tcga-gtex-precompute — batch DEG: TCGA-tumor vs GTEx-unmatched-normal.

Reads recount3 counts + metadata for a TCGA indication + matched GTEx tissue,
computes per-gene Welch's t-test on log2(CPM+1), BH-corrects across genes,
writes the frozen per-gene DEG parquet to
`s3://onc-compbio/data-catalog/derived/{INDICATION}-dge-tumor-vs-gtex-v1/`.

Runtime: ~30-60s per indication (dominated by S3 streams of the ~50-200 MB
gzipped counts files; DEG computation itself is <5s per indication).

Usage:
    python -m methods.dge_tcga_gtex_precompute.cli --indication COADREAD
    python -m methods.dge_tcga_gtex_precompute.cli --indication COADREAD --no-upload
"""

from __future__ import annotations

import gzip
import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path

import click


DEPMAP_S3_BUCKET = "onc-compbio"
RECOUNT3_S3_PREFIX = "data-catalog/sources/recount3/tcga-gtex-2023-01-04"
ENSEMBL_ID_MAP_S3 = ("data-catalog/sources/ensembl-id-mapping/"
                     "release-116-snapshot-2026-06-18/hsapiens_gene_id_map_release-116.tsv")

# Indication → TCGA study codes (may be multi-study for combined indications)
INDICATION_TO_TCGA_STUDIES = {
    "COADREAD": ["COAD", "READ"],
    "COAD": ["COAD"],
    "READ": ["READ"],
    "LUAD": ["LUAD"],
    "LUSC": ["LUSC"],
    "BRCA": ["BRCA"],
    "PAAD": ["PAAD"],
    "PDAC": ["PAAD"],
    "SKCM": ["SKCM"],
    "STAD": ["STAD"],
    "PRAD": ["PRAD"],
    "OV": ["OV"],
    "KIRC": ["KIRC"],
    "GBM": ["GBM"],
    "LGG": ["LGG"],
    "HNSC": ["HNSC"],
    "BLCA": ["BLCA"],
    "LIHC": ["LIHC"],
    "CESC": ["CESC"],
    "ESCA": ["ESCA"],
}

# Indication → GTEx tissue-of-origin. Some indications don't have a clean
# GTEx counterpart (LGG/GBM: brain has many subregions; SKCM: no dedicated
# skin tissue in GTEx — closest is 'SKIN' which has sun-exposed + not-sun-exposed
# sublocations). Best-effort canonical mapping.
INDICATION_TO_GTEX_TISSUE = {
    "COADREAD": "COLON",
    "COAD":     "COLON",
    "READ":     "COLON",
    "LUAD":     "LUNG",
    "LUSC":     "LUNG",
    "BRCA":     "BREAST",
    "PAAD":     "PANCREAS",
    "PDAC":     "PANCREAS",
    "SKCM":     "SKIN",
    "STAD":     "STOMACH",
    "PRAD":     "PROSTATE",
    "OV":       "OVARY",
    "KIRC":     "KIDNEY",
    "GBM":      "BRAIN",
    "LGG":      "BRAIN",
    "HNSC":     None,   # no clean GTEx match; head/neck is a mosaic of tissues
    "BLCA":     "BLADDER",
    "LIHC":     "LIVER",
    "CESC":     "CERVIX_UTERI",
    "ESCA":     "ESOPHAGUS",
}


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _sha256(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def _load_ensembl_hgnc_map(s3) -> dict[str, str]:
    """Fetch Ensembl-116 ID map → {ENSG_stem: HGNC symbol}."""
    import pandas as pd
    body = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=ENSEMBL_ID_MAP_S3)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t")
    df = df.dropna(subset=["Gene stable ID", "HGNC symbol"])
    return dict(zip(df["Gene stable ID"], df["HGNC symbol"]))


def _fetch_counts_matrix(s3, cohort: str, tissue_or_study: str) -> "pd.DataFrame":
    """Fetch recount3 counts matrix, return DataFrame (gene_id × sample_id) as int64.

    cohort ∈ {'tcga', 'gtex'}. tissue_or_study is 'COAD' etc for TCGA or 'COLON' for GTEx.
    """
    import pandas as pd
    key = f"{RECOUNT3_S3_PREFIX}/{cohort}/{tissue_or_study}/gene_sums/{cohort}.gene_sums.{tissue_or_study}.G026.gz"
    _log(f"    Fetching s3://{DEPMAP_S3_BUCKET}/{key}")
    body = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=key)["Body"].read()
    # Parse comment-header lines then table
    text_io = io.TextIOWrapper(io.BufferedReader(gzip.GzipFile(fileobj=io.BytesIO(body))))
    df = pd.read_csv(text_io, sep="\t", comment="#", dtype={"gene_id": str})
    _log(f"    Loaded {df.shape[0]:,} genes × {df.shape[1]-1:,} samples")
    return df


def _fetch_metadata(s3, cohort: str, tissue_or_study: str) -> "pd.DataFrame":
    """Fetch recount3 metadata for the cohort/tissue.
    Returns DataFrame with columns useful for group classification.
    """
    import pandas as pd
    key = f"{RECOUNT3_S3_PREFIX}/{cohort}/{tissue_or_study}/metadata/{cohort}.{cohort}.{tissue_or_study}.MD.gz"
    _log(f"    Fetching s3://{DEPMAP_S3_BUCKET}/{key}")
    body = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=key)["Body"].read()
    df = pd.read_csv(io.BytesIO(gzip.decompress(body)), sep="\t", low_memory=False)
    return df


def _tcga_tumor_sample_ids(metadata: "pd.DataFrame") -> set[str]:
    """Return the set of gdc_file_id values for Primary-Tumor samples in a TCGA metadata frame."""
    return set(metadata.loc[metadata["gdc_cases.samples.sample_type"] == "Primary Tumor",
                             "gdc_file_id"].astype(str))


def _gtex_sample_ids(metadata: "pd.DataFrame") -> set[str]:
    """Return the set of external_id values for GTEx samples. All GTEx samples in
    a tissue-of-origin file are healthy-donor; no filter needed."""
    return set(metadata["external_id"].astype(str))


def _log2cpm(counts_df: "pd.DataFrame", sample_cols: list[str]) -> "pd.DataFrame":
    """Convert raw counts (gene_id × sample) to log2(CPM+1). Modifies inputs.

    Returns a DataFrame with the same shape as counts_df but log2(CPM+1) values
    in sample_cols. gene_id column is preserved as-is.
    """
    import numpy as np
    lib_sizes = counts_df[sample_cols].sum(axis=0)
    # CPM = count / lib_size × 1e6; log2(CPM+1)
    cpm = counts_df[sample_cols].div(lib_sizes, axis=1) * 1e6
    log2cpm = np.log2(cpm + 1.0)
    out = counts_df[["gene_id"]].copy()
    for c in sample_cols:
        out[c] = log2cpm[c].values
    return out


def _welch_deg(log2cpm_a: "np.ndarray", log2cpm_b: "np.ndarray") -> tuple[float, float]:
    """Per-gene Welch's t-test between two log2(CPM+1) sample sets.

    Returns (log2_fold_change, p_value). log2_fold_change = mean(a) - mean(b).
    Positive log2FC means "a > b" (typically tumor > normal). NaN inputs allowed;
    variance-zero cases return (log2FC=0, p=1.0).
    """
    import numpy as np
    from scipy import stats
    a = log2cpm_a[~np.isnan(log2cpm_a)]
    b = log2cpm_b[~np.isnan(log2cpm_b)]
    if len(a) < 2 or len(b) < 2:
        return 0.0, 1.0
    mean_a = float(a.mean())
    mean_b = float(b.mean())
    lfc = mean_a - mean_b
    # Welch's t (unequal variances)
    if a.std(ddof=1) == 0 and b.std(ddof=1) == 0:
        return lfc, 1.0
    try:
        _tstat, p = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
        p = float(p) if p == p else 1.0   # guard against NaN
    except Exception:
        p = 1.0
    return lfc, p


def _bh_correct(pvals: "np.ndarray") -> "np.ndarray":
    """Benjamini-Hochberg FDR correction. Returns q-values same shape as input."""
    import numpy as np
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    q_ranked = ranked * n / (np.arange(n) + 1)
    # Enforce monotonic non-decreasing q ordering
    q_ranked = np.minimum.accumulate(q_ranked[::-1])[::-1]
    q_ranked = np.clip(q_ranked, 0, 1)
    q = np.empty_like(q_ranked)
    q[order] = q_ranked
    return q


def compute_dge_tumor_vs_gtex(
    tcga_studies: list[str],
    gtex_tissue: str,
    ensembl_to_hgnc: dict[str, str],
    s3,
) -> "pd.DataFrame":
    """Full pipeline: fetch counts + metadata → CPM → per-gene Welch's t + BH.

    Returns DataFrame with one row per HGNC-mappable Ensembl gene:
      gene_symbol, gene_id_ensembl, log2_fc, p_value, q_value,
      n_tumor, n_gtex_normal, mean_log2cpm_tumor, mean_log2cpm_gtex_normal,
      is_significant, is_upregulated_provider_call
    """
    import numpy as np
    import pandas as pd

    # 1. TCGA side — may be multi-study, concatenate horizontally on gene_id
    tcga_counts_frames = []
    tumor_sample_ids: set[str] = set()
    for study in tcga_studies:
        counts = _fetch_counts_matrix(s3, "tcga", study)
        md = _fetch_metadata(s3, "tcga", study)
        study_tumors = _tcga_tumor_sample_ids(md)
        keep_cols = [c for c in counts.columns if c == "gene_id" or c in study_tumors]
        tcga_counts_frames.append(counts[keep_cols])
        tumor_sample_ids.update(study_tumors)
    # Merge on gene_id
    tcga_counts = tcga_counts_frames[0]
    for other in tcga_counts_frames[1:]:
        tcga_counts = tcga_counts.merge(other, on="gene_id", how="outer")
    _log(f"  TCGA merged: {tcga_counts.shape[0]:,} genes × {tcga_counts.shape[1]-1:,} tumor samples")

    # 2. GTEx side
    gtex_counts = _fetch_counts_matrix(s3, "gtex", gtex_tissue)
    gtex_md = _fetch_metadata(s3, "gtex", gtex_tissue)
    gtex_samples = _gtex_sample_ids(gtex_md)
    gtex_keep = [c for c in gtex_counts.columns if c == "gene_id" or c in gtex_samples]
    gtex_counts = gtex_counts[gtex_keep]
    _log(f"  GTEx {gtex_tissue}: {gtex_counts.shape[0]:,} genes × {gtex_counts.shape[1]-1:,} samples")

    # 3. Join TCGA + GTEx on gene_id (INNER — drop genes not in both)
    tcga_sample_cols = [c for c in tcga_counts.columns if c != "gene_id"]
    gtex_sample_cols = [c for c in gtex_counts.columns if c != "gene_id"]
    joined = tcga_counts.merge(gtex_counts, on="gene_id", how="inner", suffixes=("_tcga", "_gtex"))
    _log(f"  Joined: {joined.shape[0]:,} genes (in both cohorts)")

    # 4. CPM-normalize per cohort separately (each cohort has its own library-size
    # normalization since sequencing depths differ)
    tcga_log2cpm = _log2cpm(joined[["gene_id"] + tcga_sample_cols], tcga_sample_cols)
    gtex_log2cpm = _log2cpm(joined[["gene_id"] + gtex_sample_cols], gtex_sample_cols)

    # 5. Map Ensembl versioned → HGNC symbol; drop rows without an HGNC mapping
    def _stem(gid): return str(gid).split(".")[0]
    joined["gene_stem"] = joined["gene_id"].map(_stem)
    joined["gene_symbol"] = joined["gene_stem"].map(ensembl_to_hgnc)
    hgnc_mask = joined["gene_symbol"].notna()
    _log(f"  HGNC-mappable: {hgnc_mask.sum():,}/{len(joined):,} genes")

    # 6. Per-gene Welch's t (tumor vs GTEx)
    tcga_arr = tcga_log2cpm[tcga_sample_cols].to_numpy(dtype=np.float64)
    gtex_arr = gtex_log2cpm[gtex_sample_cols].to_numpy(dtype=np.float64)
    n_genes = len(joined)
    log2_fcs = np.empty(n_genes)
    p_vals = np.empty(n_genes)
    for i in range(n_genes):
        log2_fcs[i], p_vals[i] = _welch_deg(tcga_arr[i], gtex_arr[i])
    # BH-correct across HGNC-mappable protein-coding genes (keep others but mark p only)
    q_vals = np.ones(n_genes)
    if hgnc_mask.sum() > 0:
        q_vals[hgnc_mask] = _bh_correct(p_vals[hgnc_mask])

    # 7. Assemble output frame
    result = pd.DataFrame({
        "gene_symbol": joined["gene_symbol"].values,
        "gene_id_ensembl": joined["gene_stem"].values,
        "log2_fc": log2_fcs,
        "p_value": p_vals,
        "q_value": q_vals,
        "n_tumor": len(tcga_sample_cols),
        "n_gtex_normal": len(gtex_sample_cols),
        "mean_log2cpm_tumor": tcga_arr.mean(axis=1),
        "mean_log2cpm_gtex_normal": gtex_arr.mean(axis=1),
    })
    # Provider-call flags — mirror the coadread-dge-df06320 schema
    result["is_significant"] = (result["q_value"] < 0.05)
    result["is_upregulated_provider_call"] = (result["log2_fc"] > 0) & result["is_significant"]
    # Drop genes without HGNC mapping (they don't participate in target-eval)
    result = result[result["gene_symbol"].notna()].reset_index(drop=True)
    # Sort by q_value ascending for parquet-side predicate-pushdown-friendly layout
    result = result.sort_values("gene_symbol").reset_index(drop=True)
    return result


def write_parquet(df: "pd.DataFrame", local_path: Path) -> int:
    """Write DEG DataFrame to parquet. Sorts by gene_symbol for predicate pushdown."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("gene_id_ensembl", pa.string()),
        pa.field("log2_fc", pa.float32()),
        pa.field("p_value", pa.float64()),
        pa.field("q_value", pa.float64()),
        pa.field("n_tumor", pa.int32()),
        pa.field("n_gtex_normal", pa.int32()),
        pa.field("mean_log2cpm_tumor", pa.float32()),
        pa.field("mean_log2cpm_gtex_normal", pa.float32()),
        pa.field("is_significant", pa.bool_()),
        pa.field("is_upregulated_provider_call", pa.bool_()),
    ])
    table = pa.Table.from_pydict({c.name: df[c.name].tolist() for c in schema}, schema=schema)
    table = table.sort_by("gene_symbol")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(local_path), compression="snappy", row_group_size=1024)
    return local_path.stat().st_size


def write_manifest(
    indication: str, tcga_studies: list[str], gtex_tissue: str,
    parquet_size: int, n_genes: int, local_dir: Path, s3_prefix: str,
    s3, upload: bool = True,
) -> Path:
    import yaml
    manifest = {
        "derived_product_id": f"{indication.lower()}-dge-tumor-vs-gtex-v1",
        "derived_product_version": "0.1.0",
        "framework_version": "v2",
        "generated_by": "methods.dge_tcga_gtex_precompute.cli",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_s3_prefix": f"s3://{DEPMAP_S3_BUCKET}/{s3_prefix.rstrip('/')}/",
        "compression": "snappy",
        "contrast": "tumor_vs_gtex_normal",
        "tumor_source": {
            "cohort": "TCGA (recount3 tcga-gtex-2023-01-04)",
            "studies": tcga_studies,
            "sample_type_filter": "gdc_cases.samples.sample_type == 'Primary Tumor'",
        },
        "normal_source": {
            "cohort": "GTEx (recount3 tcga-gtex-2023-01-04)",
            "tissue": gtex_tissue,
            "filter": "all-samples (healthy-donor by GTEx design)",
        },
        "stats_convention": {
            "normalization": "log2(CPM+1); library-size per-sample from column-sum",
            "test": "Welch's t-test (scipy.stats.ttest_ind, equal_var=False)",
            "multiple_testing_correction": "Benjamini-Hochberg (across HGNC-mappable genes)",
            "log2_fc_sign": "positive log2_fc = tumor > normal (upregulated in tumor)",
        },
        "gene_annotation": "Gencode v26 (recount3 default); Ensembl release 116 for HGNC map",
        "n_genes_hgnc_mapped": n_genes,
        "parquet": {
            "filename": "tumor_vs_gtex.parquet",
            "size_bytes": parquet_size,
        },
        "notes": (
            "TCGA-tumor vs GTEx-unmatched-normal DEG. Complements the existing "
            "TCGA-tumor-vs-paired-adjacent-normal DEG (methods/dge_deseq2 R "
            "pipeline). Paired-adjacent tests within-patient contrast (surgical-"
            "margin normal); GTEx tests tumor-vs-population-normal contrast. "
            "The two tests answer different biological questions: adjacent-normal "
            "captures early field-effect changes, GTEx captures selectivity vs "
            "canonical healthy tissue. Both inform tumor-vs-normal-selectivity card."
        ),
    }
    manifest_path = local_dir / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False, default_flow_style=False)
    if upload:
        s3_key = f"{s3_prefix.rstrip('/')}/manifest.yaml"
        _log(f"  Uploading manifest → s3://{DEPMAP_S3_BUCKET}/{s3_key}")
        with open(manifest_path, "rb") as f:
            s3.upload_fileobj(f, DEPMAP_S3_BUCKET, s3_key)
    return manifest_path


@click.command()
@click.option("--indication", required=True, type=str,
              help="Framework indication (e.g. COADREAD). Must be in INDICATION_TO_TCGA_STUDIES.")
@click.option("--local-dir", type=click.Path(file_okay=False, writable=True, path_type=Path),
              default=Path.home() / "dev" / "framework-runs" / "dge-tcga-gtex-precompute-local",
              help="Local staging directory.")
@click.option("--no-upload", is_flag=True,
              help="Skip S3 upload; write parquet locally only. Useful for dry-run / testing.")
def main(indication: str, local_dir: Path, no_upload: bool) -> None:
    """Batch precompute TCGA-tumor-vs-GTEx-normal DEG for one indication."""
    import boto3
    s3 = boto3.client("s3")

    tcga_studies = INDICATION_TO_TCGA_STUDIES.get(indication.upper())
    gtex_tissue = INDICATION_TO_GTEX_TISSUE.get(indication.upper())
    if not tcga_studies:
        raise click.ClickException(f"Unknown indication: {indication} (not in INDICATION_TO_TCGA_STUDIES)")
    if not gtex_tissue:
        raise click.ClickException(f"Indication {indication} has no GTEx mapping; skip this contrast.")

    local_dir = local_dir / indication.upper()
    local_dir.mkdir(parents=True, exist_ok=True)
    s3_prefix = f"data-catalog/derived/{indication.lower()}-dge-tumor-vs-gtex-v1"

    _log(f"\n=== DGE tumor-vs-GTEx precompute: {indication} ({tcga_studies}) vs GTEx {gtex_tissue} ===")
    _log(f"  Output: s3://{DEPMAP_S3_BUCKET}/{s3_prefix}/  (upload={'no' if no_upload else 'yes'})")

    _log("\n[1/3] Loading Ensembl → HGNC map (release 116)")
    ensembl_to_hgnc = _load_ensembl_hgnc_map(s3)
    _log(f"  {len(ensembl_to_hgnc):,} Ensembl → HGNC mappings")

    _log("\n[2/3] Computing DEG")
    dge_df = compute_dge_tumor_vs_gtex(tcga_studies, gtex_tissue, ensembl_to_hgnc, s3)
    _log(f"  DEG done: {len(dge_df):,} HGNC-mappable genes")
    _log(f"  Significant (q<0.05): {int(dge_df['is_significant'].sum()):,}")
    _log(f"  Upregulated in tumor (q<0.05 & log2FC>0): {int(dge_df['is_upregulated_provider_call'].sum()):,}")

    _log("\n[3/3] Writing parquet")
    parquet_path = local_dir / "tumor_vs_gtex.parquet"
    parquet_size = write_parquet(dge_df, parquet_path)
    _log(f"  Wrote {parquet_path} ({parquet_size / 1e6:.1f} MB)")

    if not no_upload:
        s3_key = f"{s3_prefix}/tumor_vs_gtex.parquet"
        _log(f"  Uploading parquet → s3://{DEPMAP_S3_BUCKET}/{s3_key}")
        with open(parquet_path, "rb") as f:
            s3.upload_fileobj(f, DEPMAP_S3_BUCKET, s3_key)

    write_manifest(indication, tcga_studies, gtex_tissue, parquet_size, len(dge_df),
                    local_dir, s3_prefix, s3, upload=not no_upload)

    _log(f"\n=== Precompute complete for {indication} ===")


if __name__ == "__main__":
    main()
