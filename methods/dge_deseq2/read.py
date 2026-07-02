"""dge_deseq2.read — read functions for existing DGE Parquet outputs.

This module is the *consumption* side of dge_deseq2; the existing `cli.py` is the
*production* side (runs the R pipeline). Both live in the methods repo because both
are deterministic data operations — neither makes orchestration decisions.

Per the framework's layer-distinction discipline (plan § Dashboard, Interpretation,
Inference Layers), reading a Parquet from S3 + filtering to a gene + normalizing
columns is *compute*, not *orchestration*. It belongs here, not in skills/.

Consumers:
  - compose-dashboard skill (via subprocess CLI or library import)
  - Jupyter notebooks doing ad-hoc DGE analysis
  - Future non-Claude consumers (AgenticBoost, Tina's dashboards, batch jobs)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

DATA_CATALOG = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
DEFAULT_AWS_PROFILE = "cbg"


def _ensure_aws_profile():
    """The onc-compbio bucket requires the cbg profile; the default SSO role lacks access."""
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _load_manifest(manifest_id: str) -> dict:
    """Load a derived manifest YAML from the data-catalog."""
    candidates = list((DATA_CATALOG / "manifests" / "derived").glob(f"{manifest_id}.yaml"))
    if not candidates:
        raise FileNotFoundError(
            f"Derived manifest not found in data-catalog/manifests/derived/: {manifest_id!r}"
        )
    with candidates[0].open() as f:
        return yaml.safe_load(f)


def _s3_uri_to_path(s3_uri: str) -> str:
    return s3_uri[5:] if s3_uri.startswith("s3://") else s3_uri


def read_dge_gene_row(
    target: str,
    manifest_id: str,
    return_field_map: bool = True,
) -> Optional[dict]:
    """Read a single gene's row from a DGE Parquet output, with predicate pushdown.

    Args:
      target: HGNC symbol (e.g., 'KRAS')
      manifest_id: Derived manifest ID (e.g., 'coadread-dge-df06320')
      return_field_map: If True, normalize column names to card-spec convention
        (log2_fc, q_value, n_tumor, n_adjacent). If False, return raw Parquet columns.

    Returns:
      Dict with gene's DGE summary, OR None if target not in Parquet.
      Includes _data_source + _data_s3_uri provenance keys.
    """
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    _ensure_aws_profile()

    manifest = _load_manifest(manifest_id)
    s3_uri = manifest.get("s3_uri")
    if not s3_uri:
        raise ValueError(f"Manifest {manifest_id!r} has no s3_uri field")
    path = _s3_uri_to_path(s3_uri)

    s3 = fs.S3FileSystem()
    table = pq.read_table(path, filesystem=s3, filters=[("gene_symbol", "=", target)])

    if table.num_rows == 0:
        return None

    raw = {col: table[col][0].as_py() for col in table.column_names}

    if not return_field_map:
        raw["_data_source"] = manifest_id
        raw["_data_s3_uri"] = s3_uri
        return raw

    log2_fc = raw.get("log2FoldChange")
    q_value = raw.get("padj")

    # Normalize to card-spec convention (v2)
    return {
        "log2_fc": log2_fc,
        "q_value": q_value,
        "tumor_mean_tpm": None,  # not in this product
        "adjacent_mean_tpm": None,
        "n_tumor": raw.get("n_tumor"),
        "n_adjacent": raw.get("n_normal"),
        "base_mean": raw.get("baseMean"),
        "is_significant_provider_call": raw.get("is_significant"),
        "is_actionable_provider_call": raw.get("is_actionable"),
        "is_upregulated_provider_call": raw.get("is_upregulated"),
        # Card v2 descriptive categorical — drives Tier-2 rules directly
        "expression_call_class": _classify_expression_call(log2_fc, q_value),
        "_data_source": manifest_id,
        "_data_s3_uri": s3_uri,
    }


def _classify_expression_call(log2_fc, q_value) -> str:
    """Map (log2_fc, q_value) → expression_call_class categorical.

    Vocabulary matches target-contracts/cards/expression-tumor-vs-adjacent.card.yaml
    summary_fields_vocabulary.expression_call_class. Tier-2 rules in
    interpretation-rules/intracellular-intrinsic.rules.yaml consume these labels.

    Thresholds identical to the pre-v2 interpretation_hints block:
      strong_upregulation:  q < 0.05 AND log2_fc >= 1.5
      modest_upregulation:  q < 0.05 AND 0.5 <= log2_fc < 1.5
      not_informative:      q >= 0.05 OR log2_fc < 0.5
      data_unavailable:     log2_fc or q_value is None/NaN
    """
    if log2_fc is None or q_value is None:
        return "data_unavailable"
    try:
        lfc = float(log2_fc)
        q = float(q_value)
    except (TypeError, ValueError):
        return "data_unavailable"
    # NaN check
    if lfc != lfc or q != q:
        return "data_unavailable"
    if q < 0.05 and lfc >= 1.5:
        return "strong_upregulation"
    if q < 0.05 and 0.5 <= lfc < 1.5:
        return "modest_upregulation"
    return "not_informative"


# ---------------------------------------------------------------------------
# recount3 per-sample expression (for figure emission, not stats)
# ---------------------------------------------------------------------------

# recount3 substrate — TCGA + GTEx counts + metadata at Gencode v26 gene level.
# Structure: sources/recount3/tcga-gtex-2023-01-04/{tcga,gtex}/{TISSUE}/
#              gene_sums/{tcga|gtex}.gene_sums.{TISSUE}.G026.gz  (raw counts)
#              metadata/{tcga|gtex}.{tcga|gtex}.{TISSUE}.MD.gz    (sample annotations)
RECOUNT3_S3_PREFIX = "data-catalog/sources/recount3/tcga-gtex-2023-01-04"
ENSEMBL_ID_MAP_S3 = ("data-catalog/sources/ensembl-id-mapping/"
                     "release-116-snapshot-2026-06-18/hsapiens_gene_id_map_release-116.tsv")

# Indication → recount3 TCGA study codes. Some framework indications map to
# multiple recount3 studies (COADREAD = COAD + READ).
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


def _load_ensembl_hgnc_map():
    """Fetch the Ensembl-116 ID map (ENSG → HGNC symbol). Cached in-process.
    Returns dict {ensembl_id_no_version: hgnc_symbol}."""
    global _ENSEMBL_HGNC_MAP_CACHE
    if _ENSEMBL_HGNC_MAP_CACHE is not None:
        return _ENSEMBL_HGNC_MAP_CACHE
    _ensure_aws_profile()
    import boto3, io
    import pandas as pd
    s3 = boto3.client("s3")
    body = s3.get_object(Bucket="onc-compbio", Key=ENSEMBL_ID_MAP_S3)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t")
    df = df.dropna(subset=["Gene stable ID", "HGNC symbol"])
    _ENSEMBL_HGNC_MAP_CACHE = dict(zip(df["Gene stable ID"], df["HGNC symbol"]))
    return _ENSEMBL_HGNC_MAP_CACHE


_ENSEMBL_HGNC_MAP_CACHE = None


def _fetch_recount3_metadata(study: str) -> "pd.DataFrame":
    """Fetch + parse TCGA study metadata from recount3 (gdc_file_id, sample_type).
    Returns DataFrame with columns [gdc_file_id, sample_type, submitter_id]."""
    _ensure_aws_profile()
    import boto3, gzip, io
    import pandas as pd
    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/tcga/{study}/metadata/tcga.tcga.{study}.MD.gz"
    body = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()
    df = pd.read_csv(io.BytesIO(gzip.decompress(body)), sep="\t", low_memory=False,
                     usecols=["gdc_file_id", "gdc_cases.samples.sample_type",
                              "gdc_cases.submitter_id"])
    return df.rename(columns={
        "gdc_cases.samples.sample_type": "sample_type",
        "gdc_cases.submitter_id": "submitter_id",
    })


def _fetch_recount3_gene_row(study: str, target_ensembl_ids: set[str]) -> "pd.DataFrame":
    """Fetch the recount3 counts file for one TCGA study, return counts for the
    target's Ensembl-ID(s) as a Series indexed by sample UUID.

    recount3 count files use Gencode v26 versioned IDs (ENSG00000133703.13); the
    ID-map returns unversioned. Match on the stem before the '.'.
    """
    _ensure_aws_profile()
    import boto3, gzip, io
    import pandas as pd
    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/tcga/{study}/gene_sums/tcga.gene_sums.{study}.G026.gz"
    body = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()
    # Iterate through the ~63k rows; keep only target-matching ones.
    with gzip.open(io.BytesIO(body), "rt") as f:
        line = f.readline()
        while line.startswith("##"):
            line = f.readline()
        header = line.rstrip("\n").split("\t")
        sample_cols = header[1:]
        matched_rows = []
        for line in f:
            parts = line.rstrip("\n").split("\t", 1)
            gene_id_versioned = parts[0]
            gene_id_stem = gene_id_versioned.split(".")[0]
            if gene_id_stem in target_ensembl_ids:
                counts = [float(x) for x in parts[1].split("\t")]
                matched_rows.append((gene_id_stem, counts))
                if len(matched_rows) == len(target_ensembl_ids):
                    break
    if not matched_rows:
        return pd.DataFrame(columns=["sample_id", "count", "gene_id"])
    # Aggregate across matched Ensembl IDs (usually 1 hit; some genes have multi-loci
    # ENSG entries — sum counts across them for the same HGNC symbol).
    import numpy as np
    all_counts = np.zeros(len(sample_cols))
    for _gid, counts in matched_rows:
        all_counts += np.array(counts)
    return pd.DataFrame({
        "sample_id": sample_cols,
        "count": all_counts,
        "gene_id": [matched_rows[0][0]] * len(sample_cols),
    })


def _fetch_recount3_library_sizes(study: str) -> "pd.Series":
    """Column-sums of the counts matrix for a study, indexed by sample UUID.
    Needed for CPM normalization. Streams through the file summing per-column."""
    _ensure_aws_profile()
    import boto3, gzip, io
    import numpy as np
    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/tcga/{study}/gene_sums/tcga.gene_sums.{study}.G026.gz"
    body = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()
    with gzip.open(io.BytesIO(body), "rt") as f:
        line = f.readline()
        while line.startswith("##"):
            line = f.readline()
        header = line.rstrip("\n").split("\t")
        sample_cols = header[1:]
        totals = np.zeros(len(sample_cols))
        for line in f:
            parts = line.rstrip("\n").split("\t", 1)
            row_counts = np.fromstring(parts[1], dtype=np.float64, sep="\t")
            totals += row_counts
    import pandas as pd
    return pd.Series(totals, index=sample_cols, name="library_size")


def read_per_sample_expression_tumor_vs_adjacent(
    target: str, indication: str,
) -> Optional[dict]:
    """Read per-sample log2(CPM+1) for `target` across TCGA `indication`, split by
    sample_type (Primary Tumor vs Solid Tissue Normal). Uses recount3 substrate.

    Returns dict:
      {
        "tumor_samples":     list<{sample_id, submitter_id, log2_cpm}>,
        "adjacent_samples":  list<{sample_id, submitter_id, log2_cpm}>,
        "gene_ensembl_id":   str,
        "n_tumor":           int,
        "n_adjacent":        int,
        "studies_used":      list<str>,   # e.g. ["COAD","READ"] for COADREAD
        "_data_source":      "recount3-tcga-gtex-2023-01-04",
      }
    or None if the indication has no recount3 study mapping OR the target's HGNC
    symbol resolves to no Ensembl ID in the release-116 map.

    Live-fetch (no persistent derived product); the counts file is ~50MB gzipped
    per study. First call takes ~10-20s; subsequent calls in the same process
    reuse the streamed data via lru caches inside the helper functions.
    """
    studies = INDICATION_TO_TCGA_STUDIES.get(indication.upper())
    if not studies:
        return None
    # HGNC → ENSG lookup (using the Ensembl-116 ID map)
    ensembl_map = _load_ensembl_hgnc_map()
    target_ensembl_ids = {eid for eid, sym in ensembl_map.items() if sym == target}
    if not target_ensembl_ids:
        return None

    import pandas as pd
    per_sample = []
    for study in studies:
        # Get gene counts + library sizes + metadata for this study
        gene_df = _fetch_recount3_gene_row(study, target_ensembl_ids)
        if gene_df.empty:
            continue
        lib_sizes = _fetch_recount3_library_sizes(study)
        md = _fetch_recount3_metadata(study)
        # Merge counts + library-size + sample-type
        merged = gene_df.merge(lib_sizes.reset_index().rename(columns={"index": "sample_id"}),
                                on="sample_id")
        merged = merged.merge(md, left_on="sample_id", right_on="gdc_file_id", how="left")
        # CPM + log-transform
        import numpy as np
        merged["cpm"] = merged["count"] / merged["library_size"].replace(0, np.nan) * 1e6
        merged["log2_cpm"] = np.log2(merged["cpm"].fillna(0) + 1.0)
        merged["study"] = study
        per_sample.append(merged)

    if not per_sample:
        return None
    all_samples = pd.concat(per_sample, ignore_index=True)
    tumor = all_samples[all_samples["sample_type"] == "Primary Tumor"]
    adj = all_samples[all_samples["sample_type"] == "Solid Tissue Normal"]

    def _to_records(df):
        return [
            {
                "sample_id": r["sample_id"],
                "submitter_id": r.get("submitter_id") or "",
                "log2_cpm": float(r["log2_cpm"]),
                "study": r["study"],
            }
            for _, r in df.iterrows()
            if r["log2_cpm"] == r["log2_cpm"]  # drop NaN
        ]

    return {
        "tumor_samples": _to_records(tumor),
        "adjacent_samples": _to_records(adj),
        "gene_ensembl_id": next(iter(target_ensembl_ids)),
        "n_tumor": len(tumor),
        "n_adjacent": len(adj),
        "studies_used": studies,
        "_data_source": "recount3-tcga-gtex-2023-01-04",
    }
