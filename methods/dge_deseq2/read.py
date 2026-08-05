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
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

DATA_CATALOG = Path(os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"))
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


@lru_cache(maxsize=8)
def _allgene_log2fc_null(manifest_id: str, column: str = "log2FoldChange") -> tuple:
    """All genes' log2FoldChange from a DGE product — the context-matched null for the
    tumor-vs-adjacent percentile. Cached per manifest_id, so the null is ALWAYS the
    target's own indication product (never pooled — the #1 correctness risk). One added
    full-column scan of a gene-sorted parquet (~30-34k rows); amortized across targets.
    Returns a tuple (hashable/cache-safe); empty on any failure → percentile is None."""
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    _ensure_aws_profile()
    try:
        manifest = _load_manifest(manifest_id)
        s3_uri = manifest.get("s3_uri")
        if not s3_uri:
            return tuple()
        path = _s3_uri_to_path(s3_uri)
        s3 = fs.S3FileSystem()
        table = pq.read_table(path, filesystem=s3, columns=[column])
        return tuple(v for v in table[column].to_pylist() if v is not None)
    except Exception:
        return tuple()


def _dge_allgene_percentile(manifest_id: str, log2_fc, cutoffs: dict = None):
    """Percentile + class of this gene's log2_fc among all genes in the SAME manifest."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))  # methods/ on path
    from percentile_null import percentile_rank, classify_percentile
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
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    _ensure_aws_profile()
    try:
        path = _s3_uri_to_path(s3_uri)
        s3 = fs.S3FileSystem()
        table = pq.read_table(path, filesystem=s3, columns=[column])
        return tuple(v for v in table[column].to_pylist() if v is not None)
    except Exception:
        return tuple()


def _dge_sensitivity_cell_percentile(manifest_id: str, s3_uri: str, column: str,
                                     log2fc, cutoffs: dict = None):
    """Percentile + class of one cell's log2FC among all genes in the SAME sensitivity product,
    keyed to the SAME comparator column (never pooled across cells)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from percentile_null import percentile_rank, classify_percentile
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
        # All-gene percentile null (additive): where this gene's log2FC falls among ALL
        # genes in the SAME per-indication DGE product. Context-matched by manifest_id.
        # One-directional display facet; never moves expression_call_class / presence_verdict.
        **dict(zip(("allgene_percentile", "allgene_percentile_class"),
                   _dge_allgene_percentile(manifest_id, log2_fc))),
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


@lru_cache(maxsize=64)
def _fetch_recount3_library_sizes(study: str) -> "pd.Series":
    """Column-sums of the counts matrix for a study, indexed by sample UUID.
    Needed for CPM normalization. Streams through the file summing per-column.

    Memoized per study (perf, chain-review retrieval-opt #1): library sizes are a per-study
    CONSTANT (target-independent), previously re-streamed — a full ~50 MB gz download — on every
    gene. Callers .reset_index()/.merge() the result (both copy), so caching is safe."""
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


# --- TPM support (Gencode v26 gene-length normalization) ------------------

RPK_CACHE_DIR = Path.home() / ".cache" / "framework-recount3-rpk-sums"


def _fetch_recount3_rpk_sums(
    cohort: str, code: str,
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

    _ensure_aws_profile()
    import boto3, gzip, io
    import numpy as np
    s3 = boto3.client("s3")
    key = (
        f"{RECOUNT3_S3_PREFIX}/{cohort}/{code}/gene_sums/"
        f"{cohort}.gene_sums.{code}.G026.gz"
    )
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
            row_counts = np.fromstring(
                line[gid_end + 1:].rstrip("\n"), dtype=np.float64, sep="\t"
            )
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
    target: str, indication: str,
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
            "cells_ran":          row.get("cells_ran"),
            "cells_supporting":   row.get("cells_supporting"),
            "dominant_direction": row.get("dominant_direction"),
            "sig_all_cells":      row.get("sig_all_cells"),
            "discordant":         row.get("discordant"),
            "max_abs_log2fc":     row.get("max_abs_log2fc"),
            "log2fc_cell_a":  row.get("log2fc_cell_a"),
            "q_value_cell_a": row.get("q_value_cell_a"),
            "log2fc_cell_b":  row.get("log2fc_cell_b"),
            "q_value_cell_b": row.get("q_value_cell_b"),
            "log2fc_cell_c":  row.get("log2fc_cell_c"),
            "q_value_cell_c": row.get("q_value_cell_c"),
            "log2fc_cell_d":  row.get("log2fc_cell_d"),
            "q_value_cell_d": row.get("q_value_cell_d"),
            "n_tumor":       None,  # cohort-level n lives in provenance.yaml, not per-gene
            "n_adjacent":    None,
            "n_gtex_normal": None,
            # Forward the SEL-1 selectivity all-gene percentile the gene_row reader computes.
            # The card dispatcher calls THIS composite (not the gene_row reader directly), so an
            # explicit field-map here silently dropped the percentile — the orphaned-signal pattern
            # one layer up. Forward all cells (A primary + B/C corroboration) + class + context.
            "selectivity_allgene_percentile":         row.get("selectivity_allgene_percentile"),
            "selectivity_allgene_percentile_class":   row.get("selectivity_allgene_percentile_class"),
            "selectivity_allgene_percentile_context": row.get("selectivity_allgene_percentile_context"),
            "selectivity_allgene_percentile_cell_b":  row.get("selectivity_allgene_percentile_cell_b"),
            "selectivity_allgene_percentile_cell_c":  row.get("selectivity_allgene_percentile_cell_c"),
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
        supporting = sum(1 for lfc, q in sig if q < 0.05 and
                         ((lfc > 0) == (dom == "up")))
        any_up = any(lfc > 0 and q < 0.05 for lfc, q in sig)
        any_down = any(lfc < 0 and q < 0.05 for lfc, q in sig)
        row = {
            "cells_ran": 2, "cells_supporting": supporting,
            "dominant_direction": dom,
            "sig_all_cells": supporting == 2,
            "discordant": any_up and any_down,
            "max_abs_log2fc": max(abs(v) for v in lfcs),
        }

    return {
        "cells_ran":          2 if row else None,
        "cells_supporting":   (row or {}).get("cells_supporting"),
        "dominant_direction": (row or {}).get("dominant_direction"),
        "sig_all_cells":      (row or {}).get("sig_all_cells"),
        "discordant":         (row or {}).get("discordant"),
        "max_abs_log2fc":     (row or {}).get("max_abs_log2fc"),
        "log2fc_cell_a": lfc_a, "q_value_cell_a": q_a,
        "log2fc_cell_b": None,  "q_value_cell_b": None,
        "log2fc_cell_c": lfc_c, "q_value_cell_c": q_c,
        "log2fc_cell_d": None,  "q_value_cell_d": None,
        "n_tumor":       (gtex or {}).get("n_tumor") or (adj or {}).get("n_tumor"),
        "n_adjacent":    (adj or {}).get("n_adjacent"),
        "n_gtex_normal": (gtex or {}).get("n_gtex_normal"),
        # The v2 fallback reads legacy per-product rows that lack the sensitivity product's
        # all-gene columns, so the SEL-1 selectivity percentile is genuinely uncomputable here —
        # emit data_unavailable/None honestly (the field always exists, distinct from a real value).
        "selectivity_allgene_percentile":         None,
        "selectivity_allgene_percentile_class":   "data_unavailable",
        "selectivity_allgene_percentile_context": "v2_fallback: sensitivity product not landed; percentile uncomputable",
        "selectivity_allgene_percentile_cell_b":  None,
        "selectivity_allgene_percentile_cell_c":  None,
        "selectivity_class": _classify_selectivity_from_sensitivity(row),
        # v2 fallback carries cell A (TCGA-adjacent) + cell C (GTEx) — the two families — so
        # comparator_concordance is still meaningful (single_comparator when only one product landed).
        "comparator_concordance": _comparator_concordance({
            "log2fc_cell_a": lfc_a, "q_value_cell_a": q_a,
            "log2fc_cell_c": lfc_c, "q_value_cell_c": q_c}),
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
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    _ensure_aws_profile()
    s3_uri = (f"s3://onc-compbio/data-catalog/derived/"
              f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1/"
              f"sensitivity.parquet")
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
    manifest_id = f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1"
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
        "gene_symbol":        raw.get("gene_symbol"),
        "selectivity_allgene_percentile":       pct_a,          # cell-A (TCGA tumor-vs-adjacent) — PRIMARY
        "selectivity_allgene_percentile_class": pct_a_class,
        "selectivity_allgene_percentile_context": f"{manifest_id} metric=log2fc_A(tumor-vs-adjacent, primary)",
        "selectivity_allgene_percentile_cell_b": pct_b,         # cell-B (TCGA-adjacent ComBat) corroboration
        "selectivity_allgene_percentile_cell_c": pct_c,         # cell-C (GTEx population) corroboration
        "cells_ran":          raw.get("cells_ran"),
        "cells_supporting":   raw.get("cells_supporting"),
        "dominant_direction": raw.get("dominant_direction"),
        "sig_all_cells":      raw.get("sig_all_cells"),
        "discordant":         raw.get("discordant"),
        "max_abs_log2fc":     raw.get("max_abs_log2fc"),
        # per-cell log2fc / padj → lowercase card field names
        "log2fc_cell_a":  raw.get("log2fc_A"),
        "q_value_cell_a": raw.get("padj_A"),
        "log2fc_cell_b":  raw.get("log2fc_B"),
        "q_value_cell_b": raw.get("padj_B"),
        "log2fc_cell_c":  raw.get("log2fc_C"),
        "q_value_cell_c": raw.get("padj_C"),
        "log2fc_cell_d":  raw.get("log2fc_D"),
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
    """
    if not row:
        return "data_unavailable"
    if row.get("discordant"):
        return "discordant_across_comparators"
    supporting = row.get("cells_supporting")
    direction = row.get("dominant_direction")
    max_lfc = row.get("max_abs_log2fc")
    cells_ran = row.get("cells_ran")
    if supporting is None or cells_ran is None or cells_ran == 0:
        return "data_unavailable"
    supporting_frac = supporting / cells_ran
    if direction == "down" and supporting_frac >= 1.0:
        return "not_selective"
    if direction == "up" and supporting_frac >= 1.0 and (max_lfc or 0) >= 1.5:
        return "strong_tumor_selective"
    if direction == "up" and supporting_frac >= 2 / 3 and (max_lfc or 0) >= 0.5:
        return "modest_tumor_selective"
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
        return "discordant"          # a family self-disagrees → not a clean concordance
    return "concordant" if adj == gtex else "discordant"


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


GTEX_TPM_LONG_S3_URI = (
    "s3://onc-compbio/data-catalog/derived/gtex-tpm-recount3-long-v1/"
    "gtex_tpm_long.parquet"
)


def _fetch_gtex_samples_from_long_product(
    target: str, gtex_tissue: str,
) -> "list[dict]":
    """Predicate-pushdown read of the long GTEx TPM product for one (gene, tissue).

    Replaces the multi-stream on-demand recount3 compute (gene_row + library_sizes
    + rpk_sums + tissue metadata + gene_lengths join + TPM formula) with a single
    pq.read_table call against the derived product gtex-tpm-recount3-long-v1.

    Returns [] if no rows match. Values are bit-identical to what the on-demand
    path would have produced for the same (target, gtex_tissue) — verified at
    the long product's emit time (see manifests/derived/gtex-tpm-recount3-long-v1.yaml).
    """
    _ensure_aws_profile()
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    # The long product lives on S3 alongside the wide v1; open via pyarrow's
    # S3FileSystem so predicate pushdown short-circuits before full download.
    bucket, key = GTEX_TPM_LONG_S3_URI.replace("s3://", "").split("/", 1)
    s3fs = fs.S3FileSystem()
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
    target: str, indication: str,
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

    import pandas as pd
    import numpy as np
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
