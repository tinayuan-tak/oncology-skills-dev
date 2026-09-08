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
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from methods.catalog_query.read import bucket_prefix_for, s3_uri_for

DATA_CATALOG = Path(
    os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
)
DEFAULT_AWS_PROFILE = "cbg"


from methods.target_id_sidecar import ensure_aws_profile

_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton. Constructing one costs ~0.4s (region probe +
    client init) and this reader's functions fire several times per run for the cards it backs
    (the tumor-vs-normal-selectivity verdict read + the all-gene-percentile null scans + the
    GTEx-long facet), so we build it ONCE instead of per read. pyarrow's S3FileSystem is safe to
    share across threads for reads (the parallel card-read path, skills PR #515); double-checked
    locking so concurrent first-callers build a single instance. Region is pinned to us-east-1 (the
    onc-compbio bucket) to skip the region-probe round-trip. Mirrors the sibling
    tcga_gtex_expression_distribution reader's _get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as fs

                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _load_manifest(manifest_id: str) -> dict:
    """Load a derived manifest YAML from the data-catalog."""
    candidates = list((DATA_CATALOG / "manifests" / "derived").glob(f"{manifest_id}.yaml"))
    if not candidates:
        raise FileNotFoundError(f"Derived manifest not found in data-catalog/manifests/derived/: {manifest_id!r}")
    with candidates[0].open() as f:
        return yaml.safe_load(f)


def _s3_uri_to_path(s3_uri: str) -> str:
    return s3_uri[5:] if s3_uri.startswith("s3://") else s3_uri


@lru_cache(maxsize=8)
def _allgene_log2fc_null(manifest_id: str, column: str = "log2FoldChange") -> tuple:
    """All genes' log2FoldChange from a DGE product — the context-matched null for the
    tumor-vs-adjacent percentile. Cached per manifest_id, so the null is ALWAYS the
    target's own indication product (never pooled — the #1 correctness risk). One added
    full-column scan of a gene-sorted parquet (~30-34k rows); amortized across targets.
    Returns a tuple (hashable/cache-safe); empty on any failure → percentile is None."""
    import pyarrow.parquet as pq

    ensure_aws_profile()
    try:
        manifest = _load_manifest(manifest_id)
        s3_uri = manifest.get("s3_uri")
        if not s3_uri:
            return tuple()
        path = _s3_uri_to_path(s3_uri)
        s3 = _get_s3fs()
        table = pq.read_table(path, filesystem=s3, columns=[column])
        return tuple(v for v in table[column].to_pylist() if v is not None)
    except Exception:  # absence-discipline: exempt -- deliberate percentile-null; empty→percentile None, verdict comes from the sibling cell (additive context, verdict-inert)
        return tuple()


def _dge_allgene_percentile(manifest_id: str, log2_fc, cutoffs: dict = None):
    """Percentile + class of this gene's log2_fc among all genes in the SAME manifest."""
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))  # methods/ on path
    from methods.percentile_null import classify_percentile, percentile_rank

    null_vec = _allgene_log2fc_null(manifest_id)
    pct = percentile_rank(log2_fc, null_vec)
    return pct, classify_percentile(pct, cutoffs)


@lru_cache(maxsize=24)
def _sensitivity_cell_null(manifest_id: str, s3_uri: str, column: str) -> tuple:
    """All genes' log2FC for ONE sensitivity cell (log2fc_A/B/C) from a sensitivity product —
    the context-matched null for the tumor-vs-normal SELECTIVITY percentile. Each cell is a
    DISTINCT comparator (A/B = TCGA-adjacent raw/ComBat, C = GTEx), so each gets its OWN
    null over its OWN column — pooling A and C would mix comparator scales. Cached per
    (manifest, column); one added full-column scan per cell. Empty on failure."""
    import pyarrow.parquet as pq

    ensure_aws_profile()
    try:
        path = _s3_uri_to_path(s3_uri)
        s3 = _get_s3fs()
        table = pq.read_table(path, filesystem=s3, columns=[column])
        return tuple(v for v in table[column].to_pylist() if v is not None)
    except Exception:  # absence-discipline: exempt -- deliberate per-cell percentile-null; empty→percentile None, selectivity verdict comes from the sibling cells (additive context, verdict-inert)
        return tuple()


def _dge_sensitivity_cell_percentile(manifest_id: str, s3_uri: str, column: str, log2fc, cutoffs: dict = None):
    """Percentile + class of one cell's log2FC among all genes in the SAME sensitivity product,
    keyed to the SAME comparator column (never pooled across cells)."""
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from methods.percentile_null import classify_percentile, percentile_rank

    null_vec = _sensitivity_cell_null(manifest_id, s3_uri, column)
    pct = percentile_rank(log2fc, null_vec)
    return pct, classify_percentile(pct, cutoffs)


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
    import pyarrow.parquet as pq

    ensure_aws_profile()

    manifest = _load_manifest(manifest_id)
    s3_uri = manifest.get("s3_uri")
    if not s3_uri:
        raise ValueError(f"Manifest {manifest_id!r} has no s3_uri field")
    path = _s3_uri_to_path(s3_uri)

    s3 = _get_s3fs()
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
        # (removed dead tumor_mean_tpm/adjacent_mean_tpm=None keys — undeclared and never populated;
        #  the DESeq2 product carries no per-sample TPM/CPM. The tumor-rna-vs-adjacent card's
        #  per-cohort median display fields were removed in the paired contracts change.)
        "n_tumor": raw.get("n_tumor"),
        "n_adjacent": raw.get("n_normal"),
        "base_mean": raw.get("baseMean"),
        "is_significant_provider_call": raw.get("is_significant"),
        "is_actionable_provider_call": raw.get("is_actionable"),
        "is_upregulated_provider_call": raw.get("is_upregulated"),
        # Card v2 descriptive categorical — drives Tier-2 rules directly
        "expression_call_class": _classify_expression_call(log2_fc, q_value),
        # All-gene percentile null (additive): where this gene's log2FC falls among ALL
        # genes in the SAME per-indication DGE product. Context-matched by manifest_id.
        # One-directional display facet; never moves expression_call_class / presence_verdict.
        **dict(zip(("allgene_percentile", "allgene_percentile_class"), _dge_allgene_percentile(manifest_id, log2_fc))),
        "allgene_percentile_context": f"{manifest_id} metric=log2FoldChange",
        "_data_source": manifest_id,
        "_data_s3_uri": s3_uri,
    }


def _classify_expression_call(log2_fc, q_value) -> str:
    """Map (log2_fc, q_value) → expression_call_class categorical.

    Vocabulary matches target-contracts/cards/tumor-rna-vs-adjacent.card.yaml
    summary_fields_vocabulary.expression_call_class. Tier-2 rules in
    interpretation-rules/intracellular-intrinsic.rules.yaml consume these labels.

    Thresholds — SYMMETRIC up/down (2026-07-21: added the down-side; previously a significantly
    NEGATIVE log2_fc mislabelled as not_informative, hiding tumor-depletion — e.g. KRAS COADREAD
    log2_fc=-0.62, q=4e-11 is a real down signal, not "uninformative"):
      strong_upregulation:    q < 0.05 AND log2_fc >= 1.5
      modest_upregulation:    q < 0.05 AND  0.5 <= log2_fc < 1.5
      not_informative:        q >= 0.05 OR -0.5 < log2_fc < 0.5      (truly flat / non-significant)
      modest_downregulation:  q < 0.05 AND -1.5 < log2_fc <= -0.5
      strong_downregulation:  q < 0.05 AND log2_fc <= -1.5
      data_unavailable:       log2_fc or q_value is None/NaN
    Direction is the SIGN of log2_fc (a positive lfc below 1.5 is still UP, just modest — not down).
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
    if q < 0.05:
        if lfc >= 1.5:
            return "strong_upregulation"
        if lfc >= 0.5:
            return "modest_upregulation"
        if lfc <= -1.5:
            return "strong_downregulation"
        if lfc <= -0.5:
            return "modest_downregulation"
    return "not_informative"


# ---------------------------------------------------------------------------
# recount3 per-sample expression (for figure emission, not stats)
# ---------------------------------------------------------------------------

# recount3 substrate — TCGA + GTEx counts + metadata at Gencode v26 gene level.
# Structure: sources/recount3/tcga-gtex-2023-01-04/{tcga,gtex}/{TISSUE}/
#              gene_sums/{tcga|gtex}.gene_sums.{TISSUE}.G026.gz  (raw counts)
#              metadata/{tcga|gtex}.{tcga|gtex}.{TISSUE}.MD.gz    (sample annotations)
# source prefixes/keys resolved from the data-catalog manifests (single source of truth);
# rstrip('/') keeps the existing f"{RECOUNT3_S3_PREFIX}/tcga/..." idiom byte-identical.
RECOUNT3_S3_PREFIX = bucket_prefix_for("recount3-tcga-gtex-2023-01-04")[1].rstrip("/")
ENSEMBL_ID_MAP_S3 = (
    f"{bucket_prefix_for('ensembl-id-mapping-release-116-snapshot-2026-06-18')[1]}hsapiens_gene_id_map_release-116.tsv"
)

# Indication → recount3 TCGA study codes. Some framework indications map to
# multiple recount3 studies (COADREAD = COAD + READ).
INDICATION_TO_TCGA_STUDIES = {
    "COADREAD": ["COAD", "READ"],
    "COAD": ["COAD"],
    "READ": ["READ"],
    "NSCLC": ["LUAD", "LUSC"],  # composite: pooled LUAD+LUSC (study-adjusted DGE, see 06_four_cell_driver.R)
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
    ensure_aws_profile()
    import io

    import boto3
    import pandas as pd

    s3 = boto3.client("s3")
    body = s3.get_object(Bucket="onc-compbio", Key=ENSEMBL_ID_MAP_S3)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t")
    df = df.dropna(subset=["Gene stable ID", "HGNC symbol"])
    _ENSEMBL_HGNC_MAP_CACHE = dict(zip(df["Gene stable ID"], df["HGNC symbol"]))
    return _ENSEMBL_HGNC_MAP_CACHE


_ENSEMBL_HGNC_MAP_CACHE = None
_SYMBOL_TO_ENSEMBL_CACHE: "Optional[dict]" = None


def _ensembl_ids_for_symbol(symbol: str) -> "Optional[list]":
    """Return list of Ensembl IDs for a gene symbol using the reverse of the HGNC map.
    Populates lazily from the same Ensembl-116 map as _load_ensembl_hgnc_map.
    Returns None if the map is unavailable (S3 down / no creds)."""
    global _SYMBOL_TO_ENSEMBL_CACHE
    if _SYMBOL_TO_ENSEMBL_CACHE is None:
        fwd = _load_ensembl_hgnc_map()
        rev: dict = {}
        for eid, sym in fwd.items():
            rev.setdefault(sym, []).append(eid)
        _SYMBOL_TO_ENSEMBL_CACHE = rev
    ids = _SYMBOL_TO_ENSEMBL_CACHE.get(symbol)
    return ids or None


@lru_cache(maxsize=64)
def _fetch_recount3_metadata(study: str) -> "pd.DataFrame":
    """Fetch + parse TCGA study metadata from recount3 (gdc_file_id, sample_type).
    Returns DataFrame with columns [gdc_file_id, sample_type, submitter_id].

    Memoized per study (perf, chain-review retrieval-opt #1): the metadata is a per-study
    CONSTANT — target-independent — so it must not be re-streamed for every gene/target. Callers
    only .merge() the result (which copies), so returning the cached object is safe. maxsize 64 >
    the 33 TCGA studies."""
    ensure_aws_profile()
    import gzip
    import io

    import boto3
    import pandas as pd

    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/tcga/{study}/metadata/tcga.tcga.{study}.MD.gz"
    body = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()
    df = pd.read_csv(
        io.BytesIO(gzip.decompress(body)),
        sep="\t",
        low_memory=False,
        usecols=["gdc_file_id", "gdc_cases.samples.sample_type", "gdc_cases.submitter_id"],
    )
    return df.rename(
        columns={
            "gdc_cases.samples.sample_type": "sample_type",
            "gdc_cases.submitter_id": "submitter_id",
        }
    )


def _fetch_recount3_gene_row(study: str, target_ensembl_ids: set[str]) -> "pd.DataFrame":
    """Fetch the recount3 counts file for one TCGA study, return counts for the
    target's Ensembl-ID(s) as a Series indexed by sample UUID.

    recount3 count files use Gencode v26 versioned IDs (ENSG00000133703.13); the
    ID-map returns unversioned. Match on the stem before the '.'.
    """
    ensure_aws_profile()
    import gzip
    import io

    import boto3
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
    return pd.DataFrame(
        {
            "sample_id": sample_cols,
            "count": all_counts,
            "gene_id": [matched_rows[0][0]] * len(sample_cols),
        }
    )


@lru_cache(maxsize=64)
def _fetch_recount3_library_sizes(study: str) -> "pd.Series":
    """Column-sums of the counts matrix for a study, indexed by sample UUID.
    Needed for CPM normalization. Streams through the file summing per-column.

    Memoized per study (perf, chain-review retrieval-opt #1): library sizes are a per-study
    CONSTANT (target-independent), previously re-streamed — a full ~50 MB gz download — on every
    gene. Callers .reset_index()/.merge() the result (both copy), so caching is safe."""
    ensure_aws_profile()
    import gzip
    import io

    import boto3
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


# --- TPM support (Gencode v26 gene-length normalization) ------------------

RPK_CACHE_DIR = Path.home() / ".cache" / "framework-recount3-rpk-sums"


def _fetch_recount3_rpk_sums(
    cohort: str,
    code: str,
) -> "pd.Series":
    """Per-sample sum(count_j / length_kb_j) for a study or GTEx tissue.

    This is the denominator for TPM normalization: TPM = (count / length_kb)
    / sum(count_j / length_kb_j) * 1e6. Computed by streaming the recount3
    gene_sums matrix once per (cohort, code), dividing each row by its
    Gencode-v26 gene length in kb, and accumulating per-column sums.

    Cached as parquet at ~/.cache/framework-recount3-rpk-sums/{cohort}-{code}.parquet
    (~10 KB per file). First-time computation is ~30-60 sec of S3 fetch +
    ~10 sec of numpy work; subsequent calls load the parquet directly.

    Args:
        cohort: 'tcga' or 'gtex'
        code: TCGA study code ('COAD') or GTEx tissue code ('COLON')

    Returns:
        pandas.Series indexed by sample UUID → per-sample RPK-sum (float64)
    """
    import pandas as pd

    RPK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RPK_CACHE_DIR / f"{cohort}-{code}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)["rpk_sum"]

    from .gene_lengths import load_gene_lengths

    gene_lengths = load_gene_lengths()  # unversioned Ensembl → bp

    ensure_aws_profile()
    import gzip
    import io

    import boto3
    import numpy as np

    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/{cohort}/{code}/gene_sums/{cohort}.gene_sums.{code}.G026.gz"
    body = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()

    with gzip.open(io.BytesIO(body), "rt") as f:
        line = f.readline()
        while line.startswith("##"):
            line = f.readline()
        header = line.rstrip("\n").split("\t")
        sample_cols = header[1:]
        totals = np.zeros(len(sample_cols), dtype=np.float64)
        n_rows = 0
        n_length_missing = 0
        for line in f:
            gid_end = line.find("\t")
            gene_id_versioned = line[:gid_end]
            gene_id = gene_id_versioned.split(".")[0]
            length_bp = gene_lengths.get(gene_id)
            if length_bp is None or length_bp <= 0:
                n_length_missing += 1
                continue
            length_kb = length_bp / 1000.0
            row_counts = np.fromstring(line[gid_end + 1 :].rstrip("\n"), dtype=np.float64, sep="\t")
            totals += row_counts / length_kb
            n_rows += 1

    rpk = pd.Series(totals, index=sample_cols, name="rpk_sum")
    rpk.to_frame().to_parquet(cache_path)
    print(
        f"[read] cached RPK sums for {cohort}/{code}: "
        f"{n_rows:,} genes contributed, {n_length_missing:,} genes had no "
        f"Gencode-v26 length (skipped) → {cache_path}"
    )
    return rpk


def read_tumor_vs_normal_selectivity(
    target: str,
    indication: str,
) -> dict:
    """Composite dispatcher for the tumor-vs-normal-selectivity card (v3).

    Reads the four-cell sensitivity product and maps it to the card v3.0.0
    summary_fields shape. Trust anchor is cells_supporting (0-4) +
    dominant_direction; selectivity_class assigned by
    `_classify_selectivity_from_sensitivity`. Never returns None — always a
    dict with `selectivity_class` set (data_unavailable when the product is
    inaccessible). Live-mode dispatcher for compose-dashboard.

    Backward-compat: if the four-cell sensitivity product is not yet in S3 for
    this indication (batch expansion pending), falls back to the legacy v2
    two-product path (tumor-vs-adjacent + tumor-vs-GTEx) and synthesizes a
    v3-shaped record with cells_ran=2 so downstream renderers still function.
    """
    row = read_tumor_vs_normal_sensitivity_gene_row(target, indication)
    if row:
        return {
            "cells_ran": row.get("cells_ran"),
            "cells_supporting": row.get("cells_supporting"),
            "dominant_direction": row.get("dominant_direction"),
            "sig_all_cells": row.get("sig_all_cells"),
            "discordant": row.get("discordant"),
            "max_abs_log2fc": row.get("max_abs_log2fc"),
            "log2fc_cell_a": row.get("log2fc_cell_a"),
            "q_value_cell_a": row.get("q_value_cell_a"),
            "log2fc_cell_b": row.get("log2fc_cell_b"),
            "q_value_cell_b": row.get("q_value_cell_b"),
            "log2fc_cell_c": row.get("log2fc_cell_c"),
            "q_value_cell_c": row.get("q_value_cell_c"),
            "log2fc_cell_d": row.get("log2fc_cell_d"),
            "q_value_cell_d": row.get("q_value_cell_d"),
            "n_tumor": None,  # cohort-level n lives in provenance.yaml, not per-gene
            "n_adjacent": None,
            "n_gtex_normal": None,
            # Forward the SEL-1 selectivity all-gene percentile the gene_row reader computes.
            # The card dispatcher calls THIS composite (not the gene_row reader directly), so an
            # explicit field-map here silently dropped the percentile — the orphaned-signal pattern
            # one layer up. Forward all cells (A primary + B/C corroboration) + class + context.
            "selectivity_allgene_percentile": row.get("selectivity_allgene_percentile"),
            "selectivity_allgene_percentile_class": row.get("selectivity_allgene_percentile_class"),
            "selectivity_allgene_percentile_context": row.get("selectivity_allgene_percentile_context"),
            "selectivity_allgene_percentile_cell_b": row.get("selectivity_allgene_percentile_cell_b"),
            "selectivity_allgene_percentile_cell_c": row.get("selectivity_allgene_percentile_cell_c"),
            "selectivity_class": _classify_selectivity_from_sensitivity(row),
            # DERIVED: do the TCGA-adjacent (A/B) and GTEx (C) comparator families agree? Exposes the
            # cross-comparator robustness cells_supporting collapses to a count (slice-4 finding #3).
            "comparator_concordance": _comparator_concordance(row),
            "_data_source": row.get("_data_source"),
            "_schema": "v3_four_cell",
        }

    # --- legacy v2 fallback (sensitivity product not yet built) --------------
    return _read_tvn_selectivity_v2_fallback(target, indication)


def _read_tvn_selectivity_v2_fallback(target: str, indication: str) -> dict:
    """Legacy v2 two-product composite, reshaped into the v3 field envelope.

    Used only until the four-cell sensitivity product lands for `indication`.
    Maps the two independent contrasts onto cells A (adjacent) and C (GTEx),
    marks cells_ran=2, and derives cells_supporting from the two q-values.
    """
    adj_manifest = _INDICATION_TO_ADJ_MANIFEST.get(indication.upper())
    adj = None
    if adj_manifest:
        try:
            adj = read_dge_gene_row(target, adj_manifest)
        except Exception:
            adj = None
    try:
        gtex = read_tumor_vs_gtex_gene_row(target, indication)
    except Exception:
        gtex = None

    lfc_a = (adj or {}).get("log2_fc")
    q_a = (adj or {}).get("q_value")
    lfc_c = (gtex or {}).get("log2_fc")
    q_c = (gtex or {}).get("q_value")

    # supporting = # of the 2 available contrasts sig<0.05 in the dominant dir
    sig = []
    if lfc_a is not None and q_a is not None and q_a == q_a:
        sig.append((lfc_a, q_a))
    if lfc_c is not None and q_c is not None and q_c == q_c:
        sig.append((lfc_c, q_c))
    lfcs = [v for v in [lfc_a, lfc_c] if v is not None and v == v]
    if not lfcs:
        row = None
    else:
        dom = "up" if sum(lfcs) > 0 else ("down" if sum(lfcs) < 0 else "none")
        supporting = sum(1 for lfc, q in sig if q < 0.05 and ((lfc > 0) == (dom == "up")))
        any_up = any(lfc > 0 and q < 0.05 for lfc, q in sig)
        any_down = any(lfc < 0 and q < 0.05 for lfc, q in sig)
        row = {
            "cells_ran": 2,
            "cells_supporting": supporting,
            "dominant_direction": dom,
            "sig_all_cells": supporting == 2,
            "discordant": any_up and any_down,
            "max_abs_log2fc": max(abs(v) for v in lfcs),
            # Per-cell LFC/q keys the classifier needs: _classify_selectivity_from_sensitivity
            # reads log2fc_cell_a / log2fc_cell_c for its RAW-comparator magnitude gates
            # (>=1.5 strong / >=0.5 modest) and log2fc_cell_c for the field-effect branch.
            # Without them raw_max_lfc collapses to 0.0 and every fallback call degrades to
            # not_informative/discordant. Cell A = TCGA-adjacent, cell C = GTEx (see docstring).
            "log2fc_cell_a": lfc_a,
            "q_value_cell_a": q_a,
            "log2fc_cell_b": None,
            "q_value_cell_b": None,
            "log2fc_cell_c": lfc_c,
            "q_value_cell_c": q_c,
        }

    return {
        "cells_ran": 2 if row else None,
        "cells_supporting": (row or {}).get("cells_supporting"),
        "dominant_direction": (row or {}).get("dominant_direction"),
        "sig_all_cells": (row or {}).get("sig_all_cells"),
        "discordant": (row or {}).get("discordant"),
        "max_abs_log2fc": (row or {}).get("max_abs_log2fc"),
        "log2fc_cell_a": lfc_a,
        "q_value_cell_a": q_a,
        "log2fc_cell_b": None,
        "q_value_cell_b": None,
        "log2fc_cell_c": lfc_c,
        "q_value_cell_c": q_c,
        "log2fc_cell_d": None,
        "q_value_cell_d": None,
        "n_tumor": (gtex or {}).get("n_tumor") or (adj or {}).get("n_tumor"),
        "n_adjacent": (adj or {}).get("n_adjacent"),
        "n_gtex_normal": (gtex or {}).get("n_gtex_normal"),
        # The v2 fallback reads legacy per-product rows that lack the sensitivity product's
        # all-gene columns, so the SEL-1 selectivity percentile is genuinely uncomputable here —
        # emit data_unavailable/None honestly (the field always exists, distinct from a real value).
        "selectivity_allgene_percentile": None,
        "selectivity_allgene_percentile_class": "data_unavailable",
        "selectivity_allgene_percentile_context": "v2_fallback: sensitivity product not landed; percentile uncomputable",
        "selectivity_allgene_percentile_cell_b": None,
        "selectivity_allgene_percentile_cell_c": None,
        "selectivity_class": _classify_selectivity_from_sensitivity(row),
        # v2 fallback carries cell A (TCGA-adjacent) + cell C (GTEx) — the two families — so
        # comparator_concordance is still meaningful (single_comparator when only one product landed).
        "comparator_concordance": _comparator_concordance(
            {"log2fc_cell_a": lfc_a, "q_value_cell_a": q_a, "log2fc_cell_c": lfc_c, "q_value_cell_c": q_c}
        ),
        "_data_source": "v2_fallback",
        "_schema": "v2_two_product_fallback",
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
    import pyarrow.parquet as pq

    ensure_aws_profile()
    s3fs = _get_s3fs()
    try:
        # Resolve the product URI from its data-catalog manifest (single source of truth).
        # Indications without a landed manifest raise FileNotFoundError → caught → None,
        # matching the prior "product absent → None" behavior.
        s3_uri = s3_uri_for(f"{indication.lower()}-dge-tumor-vs-gtex-v1")
        path = _s3_uri_to_path(s3_uri)
        table = pq.read_table(path, filesystem=s3fs, filters=[("gene_symbol", "=", target)])
    except Exception as e:
        # Genuine absence only (no landed manifest / missing object → FileNotFoundError, or
        # NoSuchKey/404) → None. A transient-S3 / creds / broken-env error must NOT be masked as
        # "product absent" — re-raise it so the caller does not silently degrade (RD3: keeps
        # read_tumor_vs_normal_selectivity from falling back v3→legacy-v2 on a transient failure).
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
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
        "expression_call_class": _classify_expression_call(raw.get("log2_fc"), raw.get("q_value")),
        "_data_source": f"{indication.lower()}-dge-tumor-vs-gtex-v1",
        "_data_s3_uri": s3_uri,
    }


def read_tumor_vs_normal_sensitivity_gene_row(target: str, indication: str) -> Optional[dict]:
    """Read one gene's row from the four-cell sensitivity DEG parquet.

    Product: {indication.lower()}-dge-tumor-vs-normal-sensitivity-v1 at
    s3://onc-compbio/data-catalog/derived/
      {indication}-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet

    The parquet columns use uppercase cell tags (log2fc_A..D, padj_A..D) — the
    driver's native output. This reader maps them to the card's lowercase
    summary_field names (log2fc_cell_a etc). Returns None if the row/product is
    absent.
    """
    import pyarrow.parquet as pq

    ensure_aws_profile()
    manifest_id = f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1"
    s3fs = _get_s3fs()
    try:
        # Resolve the product URI from its data-catalog manifest (single source of truth).
        # Indications without a landed manifest raise FileNotFoundError → caught → None.
        s3_uri = s3_uri_for(manifest_id)
        path = _s3_uri_to_path(s3_uri)
        table = pq.read_table(path, filesystem=s3fs, filters=[("gene_symbol", "=", target)])
    except Exception as e:
        # Genuine absence only (no landed manifest / missing object → FileNotFoundError, or
        # NoSuchKey/404) → None. A transient-S3 / creds / broken-env error must NOT be masked as
        # "product absent" — re-raise it so read_tumor_vs_normal_selectivity does not silently fall
        # back v3→legacy-v2 on a transient failure (RD3).
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return None
    if table.num_rows == 0:
        return None
    raw = {col: table[col][0].as_py() for col in table.column_names}
    # SELECTIVITY all-gene percentile (SEL-1, 2026-08-05) — the Axis-1 analog for the
    # tumor-vs-normal CONTRAST: where does this gene's log2FC sit among ALL genes in this
    # sensitivity product? Answers "is +1.9 an unusually selective fold-change here, or middling?"
    # Namespaced `selectivity_allgene_percentile*` (NOT the bare `allgene_percentile` the presence
    # tumor-rna-vs-adjacent reader emits) — same name, different semantics (selectivity contrast vs
    # abundance rank); the namespace prevents a silent collision in the composed target-profile.
    # Cell A is the PRIMARY comparator (TCGA tumor-vs-adjacent, the same frame the class keys on);
    # B (ComBat) + C (GTEx) are corroborating, each ranked against its OWN column (never pooled).
    pct_a, pct_a_class = _dge_sensitivity_cell_percentile(manifest_id, s3_uri, "log2fc_A", raw.get("log2fc_A"))
    pct_b, _ = _dge_sensitivity_cell_percentile(manifest_id, s3_uri, "log2fc_B", raw.get("log2fc_B"))
    pct_c, _ = _dge_sensitivity_cell_percentile(manifest_id, s3_uri, "log2fc_C", raw.get("log2fc_C"))
    return {
        "gene_symbol": raw.get("gene_symbol"),
        "selectivity_allgene_percentile": pct_a,  # cell-A (TCGA tumor-vs-adjacent) — PRIMARY
        "selectivity_allgene_percentile_class": pct_a_class,
        "selectivity_allgene_percentile_context": f"{manifest_id} metric=log2fc_A(tumor-vs-adjacent, primary)",
        "selectivity_allgene_percentile_cell_b": pct_b,  # cell-B (TCGA-adjacent ComBat) corroboration
        "selectivity_allgene_percentile_cell_c": pct_c,  # cell-C (GTEx population) corroboration
        "cells_ran": raw.get("cells_ran"),
        "cells_supporting": raw.get("cells_supporting"),
        "dominant_direction": raw.get("dominant_direction"),
        "sig_all_cells": raw.get("sig_all_cells"),
        "discordant": raw.get("discordant"),
        "max_abs_log2fc": raw.get("max_abs_log2fc"),
        # per-cell log2fc / padj → lowercase card field names
        "log2fc_cell_a": raw.get("log2fc_A"),
        "q_value_cell_a": raw.get("padj_A"),
        "log2fc_cell_b": raw.get("log2fc_B"),
        "q_value_cell_b": raw.get("padj_B"),
        "log2fc_cell_c": raw.get("log2fc_C"),
        "q_value_cell_c": raw.get("padj_C"),
        "log2fc_cell_d": raw.get("log2fc_D"),
        "q_value_cell_d": raw.get("padj_D"),
        "_data_source": f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1",
        "_data_s3_uri": s3_uri,
    }


def _classify_selectivity_from_sensitivity(row: dict) -> str:
    """Assign the v3 selectivity_class from a sensitivity gene row.

    Trust anchor is cells_supporting (0-cells_ran) + dominant_direction;
    magnitude (max_abs_log2fc) is the secondary gate. Mirrors the card v3.0.0
    vocabulary (cards/tumor-vs-normal-selectivity.card.yaml). Renderer language
    MUST mirror this rule (per dashboard-rendering-discipline).

    Thresholds are expressed as fractions of cells_ran so the classifier reads
    correctly whether the product ran 3 cells (current design after cell D
    retirement) or is extended to N in the future — a 3/3 is `strong` if the
    magnitude clears 1.5, same as a 4/4 would be.

    CALIBRATION FIXES (2026-08-07, backtest-driven — see feedback_selectivity_calibration_backtest):
      FIX 1 (ComBat de-weight): the magnitude gate now keys on the RAW comparators (cell A
        TCGA-adjacent-raw + cell C GTEx-raw), NOT max-across-all-cells. The ComBat cell B was
        found to INFLATE / sign-flip log2FC (GAPDH/COADREAD B=4.8 vs A=1.0/C=1.5; EPCAM A=-0.3→B=1.7),
        driving housekeeping false-positives when B alone cleared 1.5. Cell B still counts toward
        direction/support, but may not by itself confer `strong`/`modest` magnitude.
      FIX 2 (field-effect-aware discordant): a discordant row whose signature is
        adjacent-flat/down (cells A+B) BUT GTEx strongly up (cell C) is the FIELD-CANCERIZATION
        pattern (adjacent 'normal' already over-expresses — e.g. CEACAM5/EPCAM in COADREAD). Rather
        than collapse a validated tumour antigen to neutral, defer to the population-normal comparator:
        classify `field_effect_tumor_selective` (a tumour-selective subclass, GTEx-anchored, flagged).

    KNOWN LIMITATIONS (2026-08-13 review — documented, not silently fixed; a rescore needs a backtest):
      * cells_supporting counts cells A and B as TWO supporting votes, but they are the SAME
        tumour-vs-adjacent comparison (A = raw, B = ComBat robustness re-run — see 06_four_cell_driver.R),
        NOT two independent comparators. So the `modest` tier (supporting_frac >= 2/3) can be cleared by
        A+B alone WITHOUT any GTEx (cell C) concurrence — i.e. one distinct comparator, counted twice.
        The genuine cross-comparator agreement (TCGA-adjacent family vs GTEx family) is exposed
        separately via _family_direction / _ADJACENT_CELLS vs _GTEX_CELLS; a consumer wanting
        independent-comparator corroboration should read that, not the raw cells_supporting count.
      * `field_effect_tumor_selective` (FIX 2) rests on cell C (TCGA-tumour vs GTEx-population), which
        carries a platform/batch confound (the reason cell D was retired) — it is GTEx-anchored and
        FLAGGED, but a batch artefact flat in adjacent yet up vs GTEx can present as this class.
      * Magnitude thresholds (modest raw_max_lfc >= 0.5 ~ 1.41-fold; strong >= 1.5 ~ 2.83-fold) are
        the load-bearing discriminator because padj < 0.05 is near-universal at TCGA n (significance
        != actionability). They are user-set (2026-08-07, ~30-gene backtest); no formal power/ROC
        derivation — treat `modest` as a screen, not a decision.
    """
    if not row:
        return "data_unavailable"
    supporting = row.get("cells_supporting")
    direction = row.get("dominant_direction")
    cells_ran = row.get("cells_ran")
    # FIX 1: RAW-comparator magnitude (A=TCGA-adjacent-raw, C=GTEx-raw); exclude ComBat cell B.
    raw_lfcs = [
        abs(row.get(k))
        for k in ("log2fc_cell_a", "log2fc_cell_c")
        if isinstance(row.get(k), (int, float)) and row.get(k) == row.get(k)
    ]
    raw_max_lfc = max(raw_lfcs) if raw_lfcs else 0.0

    if row.get("discordant"):
        # FIX 2: distinguish the field-effect signature from a genuine comparator conflict.
        adj = _family_direction(row, _ADJACENT_CELLS)  # TCGA-adjacent (A+B)
        gtex = _family_direction(row, _GTEX_CELLS)  # GTEx population-normal (C)
        c_lfc = row.get("log2fc_cell_c")
        gtex_strong_up = gtex == "up" and isinstance(c_lfc, (int, float)) and c_lfc >= 1.5
        if gtex_strong_up and adj in (None, "down"):
            # adjacent flat/down + GTEx strongly up = field cancerization; the GTEx (population)
            # normal is the trustworthy reference here. Tumour-selective vs true normal, flagged.
            return "field_effect_tumor_selective"
        return "discordant_across_comparators"

    if supporting is None or cells_ran is None or cells_ran == 0:
        return "data_unavailable"
    supporting_frac = supporting / cells_ran
    if direction == "down" and supporting_frac >= 1.0:
        return "not_selective"
    if direction == "up" and supporting_frac >= 1.0 and raw_max_lfc >= 1.5:
        return "strong_tumor_selective"
    if direction == "up" and supporting_frac >= 2 / 3 and raw_max_lfc >= 0.5:
        return "modest_tumor_selective"
    # FIX 3 (field-effect, adjacent-FLAT variant — 2026-09-03, FAP/PDAC-driven):
    # FIX 2 above rescues the DISCORDANT adjacent-DOWN + GTEx-strongly-up field-cancerization signature.
    # The SAME high-normal-baseline biology also presents NON-discordantly as adjacent-FLAT — the adjacent
    # comparator RAN but reached no significance (so it is neither a support vote nor a discordant down-vote)
    # while GTEx (cell C) is SIGNIFICANTLY + strongly up. Without this, such a row collapses to
    # not_informative on the low support count (single_comparator), hiding a target that IS tumour-selective
    # vs population-normal — and leaving the normal-breadth / stromal-confound veto armed-but-moot (the
    # FAP/PDAC stroma-driven false window read not_informative instead of field_effect → veto → stromal-
    # confound). Gated on cell C being significantly up AND >= 1.5 so a weak/non-significant single comparator
    # still reads not_informative (batch-artifact guard; same GTEx-anchored caveat as FIX 2).
    c_lfc = row.get("log2fc_cell_c")
    if (
        direction == "up"
        and _family_direction(row, _GTEX_CELLS) == "up"
        and isinstance(c_lfc, (int, float))
        and c_lfc >= 1.5
        and _family_direction(row, _ADJACENT_CELLS) in (None, "down")
    ):
        return "field_effect_tumor_selective"
    if supporting <= 1:
        return "not_informative"
    # 2/3 supporting but below magnitude/direction gates → not_informative
    return "not_informative"


# The two comparator FAMILIES the selectivity design brackets: TCGA-adjacent (cells A + B,
# within-patient margin — carries field-effect) vs GTEx-population (cell C — carries the
# TCGA-vs-GTEx source confound). cells_supporting collapses agreement to a COUNT; this exposes
# whether the two INDEPENDENT comparator types actually concur — the cross-comparator robustness
# the four-/three-cell design exists to produce (audit finding: "whether TCGA-adjacent and GTEx
# agree is invisible downstream"). Cell D retired; the GTEx family is cell C alone.
_ADJACENT_CELLS = (("log2fc_cell_a", "q_value_cell_a"), ("log2fc_cell_b", "q_value_cell_b"))
_GTEX_CELLS = (("log2fc_cell_c", "q_value_cell_c"),)
_CONCORDANCE_Q = 0.05


def _family_direction(row: dict, cells) -> Optional[str]:
    """Dominant significant direction (up|down) for a comparator family, or None if no cell in the
    family ran or reached significance. A family is 'up' if a sig cell is up (and none sig down),
    'down' if sig down (and none sig up), None if it has no sig cell, 'mixed' if it self-disagrees."""
    up = down = False
    for lfc_k, q_k in cells:
        lfc = row.get(lfc_k)
        q = row.get(q_k)
        if lfc is None or q is None or q != q or lfc != lfc:
            continue
        if q < _CONCORDANCE_Q:
            if lfc > 0:
                up = True
            elif lfc < 0:
                down = True
    if up and down:
        return "mixed"
    if up:
        return "up"
    if down:
        return "down"
    return None


def _comparator_concordance(row: dict) -> str:
    """Do the two INDEPENDENT comparator families (TCGA-adjacent A/B vs GTEx C) agree?

    Returns:
      concordant       — both families significant in the SAME direction (robust to "which normal?")
      discordant       — both significant but in OPPOSITE directions (the field-effect failure mode)
      single_comparator — only one family ran / reached significance (cross-comparator agreement UNTESTED)
    This is DERIVED (computed here in the reader from the per-cell fields the summary already carries),
    never in a rule/resolver — it's a categorical the card exposes + the renderer surfaces."""
    if not row:
        return "single_comparator"
    adj = _family_direction(row, _ADJACENT_CELLS)
    gtex = _family_direction(row, _GTEX_CELLS)
    if adj is None or gtex is None:
        return "single_comparator"
    if adj == "mixed" or gtex == "mixed":
        return "discordant"  # a family self-disagrees → not a clean concordance
    return "concordant" if adj == gtex else "discordant"


# GTEx indication → tissue-of-origin (mirrors dge_tcga_gtex_precompute.cli).
INDICATION_TO_GTEX_TISSUE = {
    "COADREAD": "COLON",
    "COAD": "COLON",
    "READ": "COLON",
    "NSCLC": "LUNG",
    "LUAD": "LUNG",
    "LUSC": "LUNG",
    "BRCA": "BREAST",
    "PAAD": "PANCREAS",
    "PDAC": "PANCREAS",
    "SKCM": "SKIN",
    "STAD": "STOMACH",
    "PRAD": "PROSTATE",
    "OV": "OVARY",
    "KIRC": "KIDNEY",
    "GBM": "BRAIN",
    "LGG": "BRAIN",
    "BLCA": "BLADDER",
    "LIHC": "LIVER",
    "CESC": "CERVIX_UTERI",
    "ESCA": "ESOPHAGUS",
}


# NOTE: the three on-demand recount3 GTEx helpers below
# (_fetch_recount3_gtex_metadata, _fetch_recount3_gtex_gene_row,
# _fetch_recount3_gtex_library_sizes) are no longer called by
# read_per_sample_expression_all_three_groups after the switch to the derived
# product gtex-tpm-recount3-long-v1. They are retained (not deleted) because
# they are legitimate utilities for anyone needing sample-metadata (SMTS/SMTSD)
# or library-size denominators directly from the recount3 substrate — e.g.
# batch precomputes, ad-hoc analyses, or a future consumer that needs raw
# counts rather than TPM. Grep for their names before removing.


def _fetch_recount3_gtex_metadata(tissue: str) -> "pd.DataFrame":
    """Fetch GTEx tissue metadata; returns DataFrame with external_id + SMTS + SMTSD."""
    ensure_aws_profile()
    import gzip
    import io

    import boto3
    import pandas as pd

    s3 = boto3.client("s3")
    key = f"{RECOUNT3_S3_PREFIX}/gtex/{tissue}/metadata/gtex.gtex.{tissue}.MD.gz"
    body = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()
    return pd.read_csv(
        io.BytesIO(gzip.decompress(body)),
        sep="\t",
        low_memory=False,
        usecols=["external_id", "SMTS", "SMTSD"],
    )


def _fetch_recount3_gtex_gene_row(tissue: str, target_ensembl_ids: set) -> "pd.DataFrame":
    """Fetch GTEx counts for target's Ensembl-IDs from the gzipped tissue matrix."""
    ensure_aws_profile()
    import gzip
    import io

    import boto3
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
    return pd.DataFrame(
        {
            "sample_id": sample_cols,
            "count": all_counts,
            "gene_id": [matched_rows[0][0]] * len(sample_cols),
        }
    )


def _fetch_recount3_gtex_library_sizes(tissue: str) -> "pd.Series":
    """GTEx per-sample library sizes for CPM normalization."""
    ensure_aws_profile()
    import gzip
    import io

    import boto3
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
        totals = np.zeros(len(sample_cols))
        for line in f:
            parts = line.rstrip("\n").split("\t", 1)
            totals += np.fromstring(parts[1], dtype=np.float64, sep="\t")
    return pd.Series(totals, index=sample_cols, name="library_size")


# resolved from the data-catalog manifest (single source of truth).
GTEX_TPM_LONG_S3_URI = s3_uri_for("gtex-tpm-recount3-long-v1")


def _fetch_gtex_samples_from_long_product(
    target: str,
    gtex_tissue: str,
) -> "list[dict]":
    """Predicate-pushdown read of the long GTEx TPM product for one (gene, tissue).

    Replaces the multi-stream on-demand recount3 compute (gene_row + library_sizes
    + rpk_sums + tissue metadata + gene_lengths join + TPM formula) with a single
    pq.read_table call against the derived product gtex-tpm-recount3-long-v1.

    Returns [] if no rows match. Values are bit-identical to what the on-demand
    path would have produced for the same (target, gtex_tissue) — verified at
    the long product's emit time (see manifests/derived/gtex-tpm-recount3-long-v1.yaml).
    """
    ensure_aws_profile()
    import pyarrow.parquet as pq

    # The long product lives on S3 alongside the wide v1; open via pyarrow's
    # S3FileSystem so predicate pushdown short-circuits before full download.
    bucket, key = GTEX_TPM_LONG_S3_URI.replace("s3://", "").split("/", 1)
    s3fs = _get_s3fs()
    # Primary filter on ensembl_gene_id (the sort key — enables row-group pruning).
    # The GTEx long product is globally sorted by ensembl_gene_id so an IN-list filter
    # against the Ensembl map prunes to 2–3 row-groups out of ~12k.
    ensembl_ids = _ensembl_ids_for_symbol(target)
    if ensembl_ids:
        gene_filter = [("ensembl_gene_id", "in", ensembl_ids), ("tissue", "=", gtex_tissue)]
    else:
        gene_filter = [("gene_symbol", "=", target), ("tissue", "=", gtex_tissue)]
    table = pq.read_table(
        f"{bucket}/{key}",
        filesystem=s3fs,
        filters=gene_filter,
        columns=["ensembl_gene_id", "sample_id", "log2_tpm"],
    )
    if table.num_rows == 0:
        return []
    df = table.to_pandas()
    # tissue_subregion (SMTSD) is not stored in the long product — the current
    # consumer (emit_pan_tissue) does not read it, so we emit an empty string
    # for backward-compat. If a future consumer needs SMTSD, join the wide v1
    # sidecar (gtex_sample_tissue.parquet) which carries SMTS + SMTSD.
    # log2_cpm is likewise not carried in the long product; the caller
    # (_log2tpm_or_cpm in emit_pan_tissue) prefers log2_tpm and only falls back
    # to log2_cpm when every sample has log2_tpm=None — which never happens on
    # this path because the long product stores concrete float32 values (0.0
    # for length-missing genes, matching the upstream wide product's semantics).
    return [
        {
            "sample_id": r["sample_id"],
            "tissue_subregion": "",
            "log2_cpm": None,
            "log2_tpm": float(r["log2_tpm"]),
            "tpm": None,
            "_gene_ensembl_id": r["ensembl_gene_id"],
        }
        for _, r in df.iterrows()
    ]


def read_per_sample_expression_all_three_groups(
    target: str,
    indication: str,
) -> Optional[dict]:
    """Fetch per-sample expression for tumor + adjacent-normal + GTEx-normal.

    Returns dict:
      {
        "tumor_samples":     list<{sample_id, submitter_id, log2_cpm, log2_tpm, tpm, study}>,
        "adjacent_samples":  list<{sample_id, submitter_id, log2_cpm, log2_tpm, tpm, study}>,
        "gtex_samples":      list<{sample_id, tissue_subregion, log2_cpm, log2_tpm, tpm}>,
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

    The GTEx branch reads the derived product gtex-tpm-recount3-long-v1 (single
    per-gene pq.read_table with predicate pushdown; 3-8s cold-cache vs ~10-20s
    for the previous on-demand recount3 stream). The TCGA branch is unchanged
    — it continues to stream recount3 counts + compute TPM on demand.
    """
    two_group = read_per_sample_expression_tumor_vs_adjacent(target, indication)
    if two_group is None:
        return None

    gtex_tissue = INDICATION_TO_GTEX_TISSUE.get(indication.upper())
    if gtex_tissue is None:
        # No canonical GTEx mapping for this indication; return two-group + empty gtex
        return {
            **two_group,
            "gtex_samples": [],
            "n_gtex": 0,
            "gtex_tissue": None,
        }

    gtex_records = _fetch_gtex_samples_from_long_product(target, gtex_tissue)
    return {
        **two_group,
        "gtex_samples": gtex_records,
        "n_gtex": len(gtex_records),
        "gtex_tissue": gtex_tissue,
    }


@lru_cache(maxsize=32)
def read_per_sample_expression_tumor_vs_adjacent(
    target: str,
    indication: str,
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
    per study. First call takes ~10-20s. This function is @lru_cache'd on
    (target, indication) so a second consumer in the same process — e.g. the
    tumor-vs-adjacent figure AND the selectivity figure (via
    read_per_sample_expression_all_three_groups) — reuses the result instead of
    re-running the whole per-study fan-out. The two target-INDEPENDENT per-study
    streams (_fetch_recount3_library_sizes, _fetch_recount3_metadata) are
    additionally @lru_cache'd on `study`, and the RPK-sums are disk-cached, so a
    DIFFERENT target in the same indication re-streams only the gene-row counts,
    not the library sizes / metadata / rpk-sums.
    NOTE the returned dict + its sample lists are the CACHED objects — callers
    must treat them as read-only (all current callers do: they shallow-copy the
    dict and iterate the lists without mutation).
    """
    studies = INDICATION_TO_TCGA_STUDIES.get(indication.upper())
    if not studies:
        return None
    # HGNC → ENSG lookup (using the Ensembl-116 ID map)
    ensembl_map = _load_ensembl_hgnc_map()
    target_ensembl_ids = {eid for eid, sym in ensembl_map.items() if sym == target}
    if not target_ensembl_ids:
        return None

    import numpy as np
    import pandas as pd

    from .gene_lengths import load_gene_lengths

    gene_lengths = load_gene_lengths()

    per_sample = []
    for study in studies:
        # Get gene counts + library sizes + RPK-sums + metadata for this study
        gene_df = _fetch_recount3_gene_row(study, target_ensembl_ids)
        if gene_df.empty:
            continue
        lib_sizes = _fetch_recount3_library_sizes(study)
        rpk_sums = _fetch_recount3_rpk_sums("tcga", study)
        md = _fetch_recount3_metadata(study)
        # Merge counts + library-size + RPK-sum + sample-type
        merged = gene_df.merge(
            lib_sizes.reset_index().rename(columns={"index": "sample_id"}),
            on="sample_id",
        )
        merged = merged.merge(
            rpk_sums.reset_index().rename(columns={"index": "sample_id"}),
            on="sample_id",
        )
        merged = merged.merge(md, left_on="sample_id", right_on="gdc_file_id", how="left")
        # CPM (kept for backward compat + DEG-consistent view)
        merged["cpm"] = merged["count"] / merged["library_size"].replace(0, np.nan) * 1e6
        merged["log2_cpm"] = np.log2(merged["cpm"].fillna(0) + 1.0)
        # TPM (gene-length + library normalized; comparable across tissues)
        # ENSG id column carries versioned form; strip .N for length lookup.
        # Since we filtered to target_ensembl_ids (all resolve to the same gene),
        # we take the first gene_id, look up its unversioned length, apply uniformly.
        target_ens_versioned = merged["gene_id"].iloc[0] if "gene_id" in merged.columns else None
        target_ens_unversioned = (
            target_ens_versioned.split(".")[0] if target_ens_versioned else next(iter(target_ensembl_ids))
        )
        length_bp = gene_lengths.get(target_ens_unversioned)
        if length_bp and length_bp > 0:
            length_kb = length_bp / 1000.0
            rpk_per_sample = merged["count"] / length_kb
            merged["tpm"] = np.where(
                merged["rpk_sum"] > 0,
                rpk_per_sample / merged["rpk_sum"] * 1e6,
                0.0,
            )
            merged["log2_tpm"] = np.log2(merged["tpm"].fillna(0) + 1.0)
        else:
            merged["tpm"] = np.nan
            merged["log2_tpm"] = np.nan
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
                "log2_tpm": float(r["log2_tpm"]) if r["log2_tpm"] == r["log2_tpm"] else None,
                "tpm": float(r["tpm"]) if r["tpm"] == r["tpm"] else None,
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


# ---------------------------------------------------------------------------
# Per-subgroup tumor-vs-normal selectivity (2026-08-18)
# ---------------------------------------------------------------------------
# The read side of unblocking the `tumor-vs-normal-selectivity` card for
# molecular subgroups. Consumes the emit-time per-subgroup DESeq2 product
# (07_stratified_four_cell_driver.R → `{indication}-dge-tumor-vs-normal-
# sensitivity-by-subgroup-v1`), a tall per-gene × per-stratum sensitivity
# table, and projects it into a DESCRIPTIVE subgroup panorama: one card-shaped
# record per stratum + cross-stratum reducer scalars.
#
# It reads a PRE-BAKED product (each stratum's log2FC came from a full DESeq2
# fit restricted to that stratum's tumor set), so — unlike the peer
# @subgroup_iterable readers (gdc_somatic_hotspot / depmap_chronos) that filter
# per-sample source data at read time — there is NO read-time recompute here.
# The per-stratum record reuses the SAME classifier + concordance helpers as
# the whole-cohort card (_classify_selectivity_from_sensitivity /
# _comparator_concordance), so a stratum's selectivity_class means exactly what
# it means whole-cohort.

# Parquet emits uppercase cell tags (log2fc_A, padj_A); the card summary + the
# classifier/concordance helpers key on lowercase (log2fc_cell_a, q_value_cell_a).
_STRATUM_CELL_MAP = {
    "log2fc_A": "log2fc_cell_a",
    "padj_A": "q_value_cell_a",
    "log2fc_B": "log2fc_cell_b",
    "padj_B": "q_value_cell_b",
    "log2fc_C": "log2fc_cell_c",
    "padj_C": "q_value_cell_c",
}


def _stratum_row_to_card_fields(r) -> dict:
    """Map one per-stratum sensitivity row (pandas Series) to a card-shaped record.

    Reuses the whole-cohort classifier + comparator-concordance so a stratum's
    selectivity_class / comparator_concordance carry identical semantics. Adds
    the subgroup grain fields (stratum_id, subgroup_n, floor_met, evidence_state).
    """
    from methods.subgroup_common.panorama import SUBGROUP_N_FLOOR, evidence_state

    def _num(v):
        # NaN-safe passthrough (pandas NaN → None so the classifier's `x == x`
        # guard and the reducer's None-filter behave).
        try:
            import math

            if v is None or (isinstance(v, float) and math.isnan(v)):
                return None
        except Exception:
            pass
        return v

    row = {
        "cells_ran": _num(r.get("cells_ran")),
        "cells_supporting": _num(r.get("cells_supporting")),
        "dominant_direction": r.get("dominant_direction"),
        "sig_all_cells": bool(r.get("sig_all_cells")) if r.get("sig_all_cells") is not None else None,
        "discordant": bool(r.get("discordant")) if r.get("discordant") is not None else None,
        "max_abs_log2fc": _num(r.get("max_abs_log2fc")),
    }
    for up, lo in _STRATUM_CELL_MAP.items():
        row[lo] = _num(r.get(up))

    n = r.get("subgroup_n_tumor")
    n = int(n) if n is not None and n == n else 0
    floor_met = n >= SUBGROUP_N_FLOOR
    row.update(
        {
            "stratum": r.get("stratum_id"),
            "subgroup_n": n,
            "subgroup_n_floor_met": floor_met,
            "evidence_state": evidence_state(n, floor_met),
            "selectivity_class": _classify_selectivity_from_sensitivity(row),
            "comparator_concordance": _comparator_concordance(row),
            "source_cohort": f"recount3 TCGA-tumor∈{r.get('stratum_id')} vs shared normals "
            f"(adjacent n={r.get('n_adjacent')}, GTEx n={r.get('n_gtex')})",
        }
    )
    return row


def read_stratified_tumor_vs_normal_selectivity(
    target: str,
    indication: str,
    subgroup_axis: Optional[str] = None,
) -> dict:
    """Descriptive per-subgroup tumor-vs-normal selectivity panorama for a target.

    Product: `{indication.lower()}-dge-tumor-vs-normal-sensitivity-by-subgroup-v1`
    (tall per-gene × per-stratum sensitivity parquet). Returns the card v3.5.0
    subgroup envelope:

      {target, indication, subgroup_axis, status,
       per_subgroup_metrics: [ {stratum, subgroup_n, evidence_state,
                                selectivity_class, comparator_concordance,
                                max_abs_log2fc, log2fc_cell_a..c, ...}, ... ],
       n_subgroups_with_data, max_subgroup_log2fc, min_subgroup_log2fc,
       cross_subgroup_delta_log2fc, selectivity_class_by_subgroup,
       cross_subgroup_selectivity_divergence, any_subgroup_strong_selective}

    Purely DESCRIPTIVE (panorama semantics — shows the landscape, emits no
    signal / verdict change). `status='data_unavailable'` when the per-subgroup
    product is not accessible for `indication` (never raises for a genuine
    absence; a transient S3/creds error DOES propagate — RD3 discipline).
    """
    import pyarrow.parquet as pq

    from methods.subgroup_common.panorama import delta_reducer

    ensure_aws_profile()
    manifest_id = f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-by-subgroup-v1"

    def _empty(status: str) -> dict:
        return {
            "target": target,
            "indication": indication,
            "subgroup_axis": subgroup_axis,
            "status": status,
            "per_subgroup_metrics": [],
            "n_subgroups_with_data": 0,
            "max_subgroup_log2fc": None,
            "min_subgroup_log2fc": None,
            "cross_subgroup_delta_log2fc": None,
            "selectivity_class_by_subgroup": {},
            "cross_subgroup_selectivity_divergence": None,
            "any_subgroup_strong_selective": None,
            "_data_source": manifest_id,
        }

    s3fs = _get_s3fs()
    try:
        s3_uri = s3_uri_for(manifest_id)
        path = _s3_uri_to_path(s3_uri)
        table = pq.read_table(path, filesystem=s3fs, filters=[("gene_symbol", "=", target)])
    except Exception as e:
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return _empty("data_unavailable")

    if table.num_rows == 0:
        return _empty("data_unavailable")

    df = table.to_pandas()
    if subgroup_axis:
        df = df[df["subgroup_axis"] == subgroup_axis]
    if df.empty:
        return _empty("data_unavailable")

    records = [_stratum_row_to_card_fields(r) for _, r in df.iterrows()]

    # Cross-stratum reduction. Numeric spread via the shared delta_reducer
    # (max/min/delta of max_abs_log2fc across measured strata); categorical
    # divergence = do the strata land in different selectivity classes?
    # Surface the axis: honor the caller's filter, else read it off the product
    # (a single-axis product carries one distinct subgroup_axis value).
    axes = {a for a in df["subgroup_axis"].dropna().unique()} if "subgroup_axis" in df else set()
    resolved_axis = subgroup_axis or (next(iter(axes)) if len(axes) == 1 else None)
    envelope = {
        "target": target,
        "indication": indication,
        "subgroup_axis": resolved_axis,
        "status": "live",
        "per_subgroup_metrics": records,
        "_data_source": manifest_id,
        "_data_s3_uri": s3_uri,
    }
    envelope.update(delta_reducer(records, metric_key="max_abs_log2fc", label="log2fc"))

    measured = [r for r in records if r.get("evidence_state") == "measured"]
    class_by = {r["stratum"]: r["selectivity_class"] for r in records}
    measured_classes = {r["selectivity_class"] for r in measured}
    strong = {"strong_tumor_selective", "field_effect_tumor_selective"}
    envelope.update(
        {
            "selectivity_class_by_subgroup": class_by,
            # divergence judged over MEASURED (floor-clearing) strata only — an
            # underpowered stratum's class is an unknown, not a real difference.
            "cross_subgroup_selectivity_divergence": (len(measured_classes) > 1) if measured else None,
            "any_subgroup_strong_selective": bool(measured_classes & strong) if measured else None,
        }
    )
    return envelope
