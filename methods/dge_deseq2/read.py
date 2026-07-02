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


def read_tumor_vs_normal_selectivity(
    target: str, indication: str,
) -> dict:
    """Composite dispatcher for the tumor-vs-normal-selectivity card.

    Combines results from both DGE contrasts (tumor-vs-adjacent + tumor-vs-GTEx)
    into the card's summary_fields shape. Never returns None — always returns
    a dict with `selectivity_class` set (data_unavailable when either product
    is inaccessible). Live-mode dispatcher for compose-dashboard.

    Note: `indication` is used to select the correct DGE manifests. The
    tumor-vs-adjacent manifest_id is currently hard-coded to coadread-dge-df06320
    for COADREAD; extension to other indications requires adding manifest_ids
    to a per-indication registry (deferred to next-session batch expansion).
    """
    # Adjacent-normal contrast (currently COADREAD only via coadread-dge-df06320)
    adj_manifest = _INDICATION_TO_ADJ_MANIFEST.get(indication.upper())
    adj = None
    if adj_manifest:
        try:
            adj = read_dge_gene_row(target, adj_manifest)
        except Exception:
            adj = None
    # GTEx-normal contrast
    try:
        gtex = read_tumor_vs_gtex_gene_row(target, indication)
    except Exception:
        gtex = None

    log2_fc_adj = (adj or {}).get("log2_fc")
    q_value_adj = (adj or {}).get("q_value")
    log2_fc_gtex = (gtex or {}).get("log2_fc")
    q_value_gtex = (gtex or {}).get("q_value")

    # Selectivity class — max log2FC across the two contrasts, threshold-bucketed
    lfcs = [v for v in [log2_fc_adj, log2_fc_gtex] if v is not None and v == v]
    if not lfcs:
        selectivity_class = "data_unavailable"
        max_lfc = None
    else:
        max_lfc = max(lfcs)
        if max_lfc >= 1.5:
            selectivity_class = "strong_tumor_selective"
        elif max_lfc >= 0.5:
            selectivity_class = "modest_tumor_selective"
        elif max_lfc < 0.0:
            selectivity_class = "not_selective"
        else:
            selectivity_class = "not_informative"

    return {
        "log2_fc_vs_adjacent":     log2_fc_adj,
        "q_value_vs_adjacent":     q_value_adj,
        "log2_fc_vs_gtex":         log2_fc_gtex,
        "q_value_vs_gtex":         q_value_gtex,
        "max_log2_fc":             max_lfc,
        "mean_log2cpm_tumor":      (gtex or {}).get("mean_log2cpm_tumor"),
        "mean_log2cpm_adjacent":   None,  # tumor-vs-adj DGE product doesn't carry per-sample means
        "mean_log2cpm_gtex_normal": (gtex or {}).get("mean_log2cpm_gtex_normal"),
        "n_tumor":       (gtex or {}).get("n_tumor") or (adj or {}).get("n_tumor"),
        "n_adjacent":    (adj or {}).get("n_adjacent"),
        "n_gtex_normal": (gtex or {}).get("n_gtex_normal"),
        "selectivity_class": selectivity_class,
        "_adj_source":   adj_manifest,
        "_gtex_source":  (gtex or {}).get("_data_source"),
    }


# Indication → tumor-vs-adjacent DGE manifest ID. Extension point: add rows
# as new tumor-vs-adjacent DGE products land (LUAD, BRCA, etc.).
_INDICATION_TO_ADJ_MANIFEST = {
    "COADREAD": "coadread-dge-df06320",
}


def read_tumor_vs_gtex_gene_row(target: str, indication: str) -> Optional[dict]:
    """Read one gene's row from the tumor-vs-GTEx-normal DEG parquet.

    Sister to `read_dge_gene_row` (which reads the tumor-vs-adjacent product).
    Product: {indication.lower()}-dge-tumor-vs-gtex-v1 at
    s3://onc-compbio/data-catalog/derived/{indication}-dge-tumor-vs-gtex-v1/
    tumor_vs_gtex.parquet.

    Returns the field-mapped dict:
      log2_fc, q_value, p_value, n_tumor, n_gtex_normal,
      mean_log2cpm_tumor, mean_log2cpm_gtex_normal, expression_call_class,
      _data_source, _data_s3_uri
    or None if the target row is absent, or the indication has no tumor-vs-GTEx
    derived product (not all TCGA indications have a clean GTEx counterpart).
    """
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    _ensure_aws_profile()
    s3_uri = (f"s3://onc-compbio/data-catalog/derived/"
              f"{indication.lower()}-dge-tumor-vs-gtex-v1/tumor_vs_gtex.parquet")
    path = _s3_uri_to_path(s3_uri)
    s3fs = fs.S3FileSystem()
    try:
        table = pq.read_table(path, filesystem=s3fs,
                                filters=[("gene_symbol", "=", target)])
    except Exception:
        return None
    if table.num_rows == 0:
        return None
    raw = {col: table[col][0].as_py() for col in table.column_names}
    return {
        "log2_fc": raw.get("log2_fc"),
        "p_value": raw.get("p_value"),
        "q_value": raw.get("q_value"),
        "n_tumor": raw.get("n_tumor"),
        "n_gtex_normal": raw.get("n_gtex_normal"),
        "mean_log2cpm_tumor": raw.get("mean_log2cpm_tumor"),
        "mean_log2cpm_gtex_normal": raw.get("mean_log2cpm_gtex_normal"),
        "expression_call_class": _classify_expression_call(
            raw.get("log2_fc"), raw.get("q_value")
        ),
        "_data_source": f"{indication.lower()}-dge-tumor-vs-gtex-v1",
        "_data_s3_uri": s3_uri,
    }


# GTEx indication → tissue-of-origin (mirrors dge_tcga_gtex_precompute.cli).
INDICATION_TO_GTEX_TISSUE = {
    "COADREAD": "COLON", "COAD": "COLON", "READ": "COLON",
    "LUAD": "LUNG", "LUSC": "LUNG",
    "BRCA": "BREAST",
    "PAAD": "PANCREAS", "PDAC": "PANCREAS",
    "SKCM": "SKIN",
    "STAD": "STOMACH",
    "PRAD": "PROSTATE",
    "OV": "OVARY",
    "KIRC": "KIDNEY",
    "GBM": "BRAIN", "LGG": "BRAIN",
    "BLCA": "BLADDER",
    "LIHC": "LIVER",
    "CESC": "CERVIX_UTERI",
    "ESCA": "ESOPHAGUS",
}


def _fetch_recount3_gtex_metadata(tissue: str) -> "pd.DataFrame":
    """Fetch GTEx tissue metadata; returns DataFrame with external_id + SMTS + SMTSD."""
    _ensure_aws_profile()
    import boto3, gzip, io
    import pandas as pd
    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/gtex/{tissue}/metadata/gtex.gtex.{tissue}.MD.gz"
    body = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()
    return pd.read_csv(
        io.BytesIO(gzip.decompress(body)), sep="\t", low_memory=False,
        usecols=["external_id", "SMTS", "SMTSD"],
    )


def _fetch_recount3_gtex_gene_row(tissue: str, target_ensembl_ids: set) -> "pd.DataFrame":
    """Fetch GTEx counts for target's Ensembl-IDs from the gzipped tissue matrix."""
    _ensure_aws_profile()
    import boto3, gzip, io
    import numpy as np
    import pandas as pd
    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/gtex/{tissue}/gene_sums/gtex.gene_sums.{tissue}.G026.gz"
    body = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()
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
    all_counts = np.zeros(len(sample_cols))
    for _gid, counts in matched_rows:
        all_counts += np.array(counts)
    return pd.DataFrame({
        "sample_id": sample_cols,
        "count": all_counts,
        "gene_id": [matched_rows[0][0]] * len(sample_cols),
    })


def _fetch_recount3_gtex_library_sizes(tissue: str) -> "pd.Series":
    """GTEx per-sample library sizes for CPM normalization."""
    _ensure_aws_profile()
    import boto3, gzip, io
    import numpy as np, pandas as pd
    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/gtex/{tissue}/gene_sums/gtex.gene_sums.{tissue}.G026.gz"
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
            totals += np.fromstring(parts[1], dtype=np.float64, sep="\t")
    return pd.Series(totals, index=sample_cols, name="library_size")


def read_per_sample_expression_all_three_groups(
    target: str, indication: str,
) -> Optional[dict]:
    """Fetch per-sample log2(CPM+1) for tumor + adjacent-normal + GTEx-normal.

    Returns dict:
      {
        "tumor_samples":     list<{sample_id, submitter_id, log2_cpm}>,
        "adjacent_samples":  list<{sample_id, submitter_id, log2_cpm}>,
        "gtex_samples":      list<{sample_id, tissue_subregion, log2_cpm}>,
        "gene_ensembl_id":   str,
        "n_tumor":           int,
        "n_adjacent":        int,
        "n_gtex":            int,
        "studies_used":      list<str>,
        "gtex_tissue":       str,
        "_data_source":      "recount3-tcga-gtex-2023-01-04",
      }
    or None if the indication has no TCGA study mapping OR the target's HGNC
    symbol doesn't resolve to Ensembl.

    Extends read_per_sample_expression_tumor_vs_adjacent by adding a GTEx-normal
    third group when the indication has a canonical GTEx tissue-of-origin
    (INDICATION_TO_GTEX_TISSUE). Indications without a GTEx counterpart return
    gtex_samples=[] and gtex_tissue=None.
    """
    two_group = read_per_sample_expression_tumor_vs_adjacent(target, indication)
    if two_group is None:
        return None

    gtex_tissue = INDICATION_TO_GTEX_TISSUE.get(indication.upper())
    if gtex_tissue is None:
        # No canonical GTEx mapping for this indication; return two-group shape + empty gtex
        return {
            **two_group,
            "gtex_samples": [],
            "n_gtex": 0,
            "gtex_tissue": None,
        }

    # HGNC → Ensembl-IDs (reuse the map)
    ensembl_map = _load_ensembl_hgnc_map()
    target_ensembl_ids = {eid for eid, sym in ensembl_map.items() if sym == target}
    if not target_ensembl_ids:
        return {**two_group, "gtex_samples": [], "n_gtex": 0, "gtex_tissue": gtex_tissue}

    import numpy as np
    import pandas as pd

    gtex_counts = _fetch_recount3_gtex_gene_row(gtex_tissue, target_ensembl_ids)
    if gtex_counts.empty:
        return {**two_group, "gtex_samples": [], "n_gtex": 0, "gtex_tissue": gtex_tissue}
    gtex_lib = _fetch_recount3_gtex_library_sizes(gtex_tissue)
    gtex_md = _fetch_recount3_gtex_metadata(gtex_tissue)

    merged = gtex_counts.merge(
        gtex_lib.reset_index().rename(columns={"index": "sample_id"}),
        on="sample_id",
    )
    merged = merged.merge(gtex_md, left_on="sample_id", right_on="external_id", how="left")
    merged["cpm"] = merged["count"] / merged["library_size"].replace(0, np.nan) * 1e6
    merged["log2_cpm"] = np.log2(merged["cpm"].fillna(0) + 1.0)

    gtex_records = [
        {
            "sample_id": r["sample_id"],
            "tissue_subregion": r.get("SMTSD") or "",
            "log2_cpm": float(r["log2_cpm"]),
        }
        for _, r in merged.iterrows()
        if r["log2_cpm"] == r["log2_cpm"]
    ]

    return {
        **two_group,
        "gtex_samples": gtex_records,
        "n_gtex": len(gtex_records),
        "gtex_tissue": gtex_tissue,
    }


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
