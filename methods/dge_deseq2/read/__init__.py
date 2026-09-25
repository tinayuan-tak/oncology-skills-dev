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
from methods.dge_deseq2.config import (
    indication_to_gtex_tissue,
    indication_to_tcga_studies,
    substrate_source_manifest_id,
)

# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
# NOTE: this reader is a *package* (methods/dge_deseq2/read/__init__.py), one directory deeper
# than the flat sibling readers (methods/<name>/read.py, e.g. catalog_query). So the anchor is
# parents[3] (the analysis-methods repo root) .parent (the sibling-clone dir) — one more level up
# than the flat readers' parents[2].parent. Must equal catalog_query.read.DATA_CATALOG; a
# regression here is masked in CI (skip_if_no_data swallows the S3 error before the catalog lookup),
# so it is pinned hermetically in tests/test_data_catalog_resolution.py. (#728, S0 reorg #692.)
DATA_CATALOG = Path(
    os.environ.get("DATA_CATALOG_ROOT")
    or Path(__file__).resolve().parents[3].parent / "rnd-computational-biology-oncology-data-catalog"
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
    """All genes' log2FC for ONE sensitivity cell (log2fc_A / log2fc_C) from a sensitivity product —
    the context-matched null for the tumor-vs-normal SELECTIVITY percentile. Each cell is a
    DISTINCT comparator (A = TCGA-adjacent, C = GTEx; the ComBat cell B was removed in #727), so
    each gets its OWN null over its OWN column — pooling A and C would mix comparator scales. Cached
    per (manifest, column); one added full-column scan per cell. Empty on failure."""
    import pyarrow.parquet as pq

    ensure_aws_profile()
    try:
        path = _s3_uri_to_path(s3_uri)
        s3 = _get_s3fs()
        table = pq.read_table(path, filesystem=s3, columns=[column])
        return tuple(v for v in table[column].to_pylist() if v is not None)
    except Exception:  # absence-discipline: exempt -- deliberate per-cell percentile-null; empty→percentile None, selectivity verdict comes from the sibling cells (additive context, verdict-inert)
        return tuple()


# ── SUBSTRATE / METHOD provenance (2026-09-15) ────────────────────────────────────────────────────
# A sensitivity product's trustworthiness turns on TWO INDEPENDENT things, and only the first was
# exposed downstream:
#   1. how many comparator FAMILIES ran   → selectivity_evidence_independence (_independence_fields)
#   2. whether the ONE substrate is internally COMPARABLE → this block
# They are genuinely orthogonal, and conflating them hid a real distinction: MEASURED over the 29
# shipped plain `*-dge-tumor-vs-normal-sensitivity-v1` manifests (32 counting the 3 `-by-subgroup-v1`
# siblings the stratified reader consumes), `population_normal_only` is returned for
# ACC/LGG/OV/TGCT/UCS *and* for SCLC — but the first five are DESeq2 NB-GLM on raw integer counts
# from the SINGLE recount3-tcga-gtex-2023-01-04 substrate (tumor and normal uniformly reprocessed by
# one Monorail pipeline on one gene model), whereas SCLC is a Welch t-test on log2(TPM+1) across TWO
# parents on DIFFERENT genome builds and gene models (George-2015 hg19/FPKM via cBioPortal tumors vs
# GTEx hg38/recount3 GENCODE-v26 normals). Same independence label, materially different rigor.
#
# WHY DERIVED FROM THE MANIFEST rather than an indication set hard-coded here: the product manifest
# ALREADY records every fact this needs (parameters.statistical_test, parameters.derived_from,
# parameters.cross_cohort_batch_confound, parameters.measured_global_offset). Reading them means the
# basis cannot drift from the product it describes, and a FUTURE non-DESeq2 or multi-parent product
# is flagged the day it lands rather than the day someone remembers to add it to a list. The
# `_SUBSTRATE_UNKNOWN` default is deliberate: an unrecognised shape must NOT silently inherit the
# reassuring within-pipeline label.
_SUBSTRATE_WITHIN_PIPELINE = "within_pipeline_deseq2_counts"
_SUBSTRATE_CROSS_COHORT = "cross_cohort_non_deseq2"
_SUBSTRATE_UNKNOWN = "unknown_substrate"


@lru_cache(maxsize=64)
def _substrate_provenance(manifest_id: str) -> tuple:
    """(basis, caveat) for a sensitivity product, derived from its OWN data-catalog manifest.

    basis  — one of the _SUBSTRATE_* vocabulary above.
    caveat — None when the substrate is internally comparable; otherwise a one-line string naming
             the confound AND the measured size of it, so a consumer never has to open the manifest
             to learn that the absolute log2FC is not on a trustworthy scale.

    `load_manifest` is uncached and re-parses the YAML, so this is a SECOND parse of a file the
    caller already read for `s3_uri_for` — but only once per manifest_id per process, which is why
    the lru_cache is here and not a per-gene concern.

    Fail-soft to (_SUBSTRATE_UNKNOWN, None) on any manifest-read failure — an unresolvable manifest
    must not be reported as a clean substrate, but it also must not break a working data read.

    ⚠️ CROSS_COHORT is asserted only on POSITIVE evidence for BOTH of its conjuncts, and every
    unmatched shape falls through to UNKNOWN. The first cut of this function instead used
    `len(derived_from) == 1` as a proxy for "one substrate" and let unmatched shapes fall through to
    CROSS_COHORT. MEASURED over the 32 shipped sensitivity manifests, that mislabelled 3 of the 4 it
    fired on: coadread/nsclc/stad `-by-subgroup-v1` are DESeq2 NB GLM on the SINGLE
    recount3-tcga-gtex-2023-01-04 substrate, and their extra `derived_from` entries are
    `tcga-subgroup-assignments-*` LABEL sidecars, not second expression cohorts. They were handed a
    caveat reading "the contrast is DESeq2 NB GLM + Wald test, not DESeq2 on raw counts" — a sentence
    that contradicts itself — plus a false claim that tumour and normal came from different
    pipelines. `derived_from` is a HETEROGENEOUS list (expression parents + annotation sidecars), so
    its arity can never stand in for the number of expression substrates, and no manifest key
    distinguishes the two (`type:` is only source-release/derived). It is therefore used below to
    NAME the parents inside the caveat, never to decide the basis.
    """
    from methods.catalog_query.read import load_manifest

    try:
        doc = load_manifest(manifest_id) or {}
        params = doc.get("parameters") or {}
        derived_from = doc.get("derived_from") or []
    except Exception:  # absence-discipline: exempt -- provenance annotation only; an unresolvable
        # manifest yields the conservative UNKNOWN label and never blocks the data read it describes.
        return _SUBSTRATE_UNKNOWN, None

    test = str(params.get("statistical_test") or "")
    cross = bool(params.get("cross_cohort_batch_confound"))
    is_deseq2 = test.strip().upper().startswith("DESEQ2")

    if not cross and is_deseq2:
        return _SUBSTRATE_WITHIN_PIPELINE, None
    if not (cross and not is_deseq2):
        # Unrecognised shape: a non-DESeq2 kernel with no declared confound, a DESeq2 kernel that
        # DOES declare one (only half of what `_SUBSTRATE_CROSS_COHORT` asserts), or no kernel
        # recorded at all. None of these may inherit the reassuring within-pipeline label, and none
        # may be handed a caveat asserting a conjunct the manifest does not support.
        return _SUBSTRATE_UNKNOWN, None

    # Cross-cohort: build the caveat from the manifest's OWN measured numbers so the string can
    # never overstate or understate a confound the producer already quantified.
    offset = params.get("measured_global_offset") or {}
    bits = []
    median = offset.get("median_log2fc_c")
    frac_up = offset.get("frac_genes_up")
    if median is not None:
        bits.append(f"median log2FC offset {float(median):+.2f}")
    if frac_up is not None:
        bits.append(f"{float(frac_up) * 100:.1f}% of genes read up")
    measured = "; ".join(bits) or "offset not quantified in manifest"
    kernel = test.split("(")[0].strip() or "non-DESeq2 kernel"
    return (
        _SUBSTRATE_CROSS_COHORT,
        (
            f"Cross-cohort substrate ({' + '.join(derived_from) or 'multi-parent'}): tumor and normal "
            f"come from DIFFERENT pipelines/gene models, and the contrast is {kernel}, not DESeq2 on raw "
            f"counts. Measured platform offset: {measured}. Absolute log2FC is NOT comparable to the "
            f"DESeq2 siblings and NOT a trustworthy magnitude — read "
            f"selectivity_allgene_percentile_cell_c (the rank), which separates biology from the offset."
        ),
    )


def _substrate_fields(manifest_id: Optional[str]) -> dict:
    """The two summary_fields that make a product's substrate/method basis VISIBLE downstream.

    Emitted by every reader that emits `selectivity_class`, for the same reason
    `_independence_fields` is: the class string alone cannot be audited — `modest_tumor_selective`
    computed by DESeq2 within one pipeline and the same string computed by a Welch test across two
    genome builds are indistinguishable without this.
    """
    if not manifest_id:
        return {
            "selectivity_substrate_basis": _SUBSTRATE_UNKNOWN,
            "selectivity_substrate_caveat": None,
        }
    basis, caveat = _substrate_provenance(manifest_id)
    return {"selectivity_substrate_basis": basis, "selectivity_substrate_caveat": caveat}


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

    # Schema-drift guard (D1-D): the row exists (num_rows>0, genuine absence already
    # handled above), so a missing verdict-bearing column here means the provider parquet
    # renamed/dropped it -- NOT that the gene is absent. `.get()` would silently return
    # None for every gene and collapse the whole indication to data_unavailable with no
    # signal that anything broke. Raise loud instead, matching the
    # target_id_sidecar.read_resolver_sidecar_map schema-drift pattern.
    _required_cols = ("log2FoldChange", "padj")
    _missing = [c for c in _required_cols if c not in table.column_names]
    if _missing:
        raise ValueError(
            f"schema drift: manifest {manifest_id!r} ({s3_uri}) missing expected column(s) "
            f"{_missing!r} (present: {table.column_names})"
        )

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
# rstrip('/') keeps the existing f"{RECOUNT3_S3_PREFIX}/tcga/..." idiom byte-identical. The
# manifest id itself is projected from config/substrates.yaml (analysis-methods#733) rather
# than hard-coded here.
RECOUNT3_S3_PREFIX = bucket_prefix_for(substrate_source_manifest_id("recount3"))[1].rstrip("/")
ENSEMBL_ID_MAP_S3 = (
    f"{bucket_prefix_for('ensembl-id-mapping-release-116-snapshot-2026-06-18')[1]}hsapiens_gene_id_map_release-116.tsv"
)

# Indication → recount3 TCGA study codes. Some framework indications map to
# multiple recount3 studies (COADREAD = COAD + READ). Consolidated into
# config/indications.yaml (S1, #693) — the read-map entries (with their tcga_studies)
# project into this dict; add or edit an indication there, not here.
INDICATION_TO_TCGA_STUDIES = indication_to_tcga_studies()


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

    from ..gene_lengths import load_gene_lengths

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
    summary_fields shape. Trust anchor is agreement between the two INDEPENDENT
    comparator FAMILIES (adjacent A vs GTEx C) + dominant_direction — NOT the
    product's own cells_supporting (see `_classify_selectivity_from_sensitivity`,
    FIX 4). Cell B (the ComBat re-run of A that used to double-count the adjacent
    comparison) was removed in analysis-methods#727. The
    denominator actually used is emitted as comparator_families_ran /
    comparator_families_supporting / adjacent_arm_measured /
    selectivity_evidence_independence.

    Independence is only HALF the audit, and the other half used to be missing: it says how many
    comparator families ran, never whether the one substrate is internally comparable. SCLC and
    ACC/LGG/OV/TGCT/UCS all read `population_normal_only`, but only SCLC is a Welch test across two
    genome builds — see `_substrate_provenance`. `selectivity_substrate_basis` +
    `selectivity_substrate_caveat` carry that second axis. Never returns None — always a
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
            # one layer up. Forward all cells (A primary + C corroboration) + class + context.
            "selectivity_allgene_percentile": row.get("selectivity_allgene_percentile"),
            "selectivity_allgene_percentile_class": row.get("selectivity_allgene_percentile_class"),
            "selectivity_allgene_percentile_context": row.get("selectivity_allgene_percentile_context"),
            "selectivity_allgene_percentile_cell_c": row.get("selectivity_allgene_percentile_cell_c"),
            "selectivity_class": _classify_selectivity_from_sensitivity(row),
            # DERIVED: do the TCGA-adjacent (A) and GTEx (C) comparator families agree? Exposes the
            # cross-comparator robustness cells_supporting collapses to a count (slice-4 finding #3).
            "comparator_concordance": _comparator_concordance(row),
            # Recomputed from `row`'s per-cell fields rather than forwarded, so this composite can
            # never publish a class whose stated evidence base came from a different computation.
            **_independence_fields(row),
            # Forwarded (not recomputed) — the gene_row reader derived these from the manifest of the
            # product it actually read, which is the only thing that can describe that substrate.
            "selectivity_substrate_basis": row.get("selectivity_substrate_basis"),
            "selectivity_substrate_caveat": row.get("selectivity_substrate_caveat"),
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
    from methods.target_id_sidecar import is_definitively_absent

    def _is_genuine_absence(e: Exception) -> bool:
        # Mirrors RD3 (read_tumor_vs_gtex_gene_row, #783): a missing manifest / missing S3
        # object is honest data_unavailable; anything else (creds, throttling, broken env)
        # must surface as a loud _live_read_error, never a silently-clean absence (#797).
        return isinstance(e, FileNotFoundError) or is_definitively_absent(e)

    live_read_errors = []

    adj_manifest = _INDICATION_TO_ADJ_MANIFEST.get(indication.upper())
    adj = None
    if adj_manifest:
        try:
            adj = read_dge_gene_row(target, adj_manifest)
        except Exception as e:
            if not _is_genuine_absence(e):
                live_read_errors.append(f"adj:{type(e).__name__}:{e}")
            adj = None
    gtex = None
    try:
        gtex = read_tumor_vs_gtex_gene_row(target, indication)
    except Exception as e:
        if not _is_genuine_absence(e):
            live_read_errors.append(f"gtex:{type(e).__name__}:{e}")
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
            "log2fc_cell_c": lfc_c,
            "q_value_cell_c": q_c,
        }

    out = {
        "cells_ran": 2 if row else None,
        "cells_supporting": (row or {}).get("cells_supporting"),
        "dominant_direction": (row or {}).get("dominant_direction"),
        "sig_all_cells": (row or {}).get("sig_all_cells"),
        "discordant": (row or {}).get("discordant"),
        "max_abs_log2fc": (row or {}).get("max_abs_log2fc"),
        "log2fc_cell_a": lfc_a,
        "q_value_cell_a": q_a,
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
        "selectivity_allgene_percentile_cell_c": None,
        "selectivity_class": _classify_selectivity_from_sensitivity(row),
        # v2 fallback carries cell A (TCGA-adjacent) + cell C (GTEx) — the two families — so
        # comparator_concordance is still meaningful (single_comparator when only one product landed).
        "comparator_concordance": _comparator_concordance(
            {"log2fc_cell_a": lfc_a, "q_value_cell_a": q_a, "log2fc_cell_c": lfc_c, "q_value_cell_c": q_c}
        ),
        # Cell A alone IS the adjacent family (as it is everywhere since #727 removed the ComBat cell
        # B), so the family denominator is the honest one here and `adjacent_only` /
        # `population_normal_only` correctly marks which legacy product actually landed for this indication.
        **_independence_fields(row),
        # The v2 fallback stitches cells A and C from TWO SEPARATE legacy products, so its substrate is
        # cross-product by construction and there is no single manifest to characterise it from. Emit
        # UNKNOWN with the reason rather than a reassuring within-pipeline label the path cannot earn.
        "selectivity_substrate_basis": _SUBSTRATE_UNKNOWN,
        "selectivity_substrate_caveat": (
            "v2_fallback: cells A and C were read from two SEPARATE legacy products, not one "
            "sensitivity product, so substrate comparability is unestablished."
        ),
        "_data_source": "v2_fallback",
        "_schema": "v2_two_product_fallback",
    }
    if live_read_errors:
        # A non-definitive child failure (transient/creds/broken-env) must surface as an honest
        # loud error, never as a clean data_unavailable-shaped record (#797) — mirrors the
        # `_live_read_error` breadcrumb convention the skill layer checks for.
        out["_live_read_error"] = "; ".join(live_read_errors)
    return out


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

    The parquet columns use uppercase cell tags (log2fc_A/log2fc_C, padj_A/padj_C)
    — the driver's native output. (Cell B was removed in analysis-methods#727 and
    cell D was retired earlier, so neither column is emitted; the `.get` lookups
    below tolerate their absence on any older product still carrying them.) This
    reader maps them to the card's lowercase summary_field names (log2fc_cell_a
    etc). Returns None if the row/product is absent.
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
    # C (GTEx) is corroborating, ranked against its OWN column (never pooled).
    pct_a, pct_a_class = _dge_sensitivity_cell_percentile(manifest_id, s3_uri, "log2fc_A", raw.get("log2fc_A"))
    pct_c, _ = _dge_sensitivity_cell_percentile(manifest_id, s3_uri, "log2fc_C", raw.get("log2fc_C"))
    out = {
        "gene_symbol": raw.get("gene_symbol"),
        "selectivity_allgene_percentile": pct_a,  # cell-A (TCGA tumor-vs-adjacent) — PRIMARY
        "selectivity_allgene_percentile_class": pct_a_class,
        "selectivity_allgene_percentile_context": f"{manifest_id} metric=log2fc_A(tumor-vs-adjacent, primary)",
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
        "log2fc_cell_c": raw.get("log2fc_C"),
        "q_value_cell_c": raw.get("padj_C"),
        "log2fc_cell_d": raw.get("log2fc_D"),
        "q_value_cell_d": raw.get("padj_D"),
        "_data_source": f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1",
        "_data_s3_uri": s3_uri,
    }
    # Comparator-independence provenance: computed from the per-cell fields just mapped above, so it
    # cannot drift from what the classifier reads.
    out.update(_independence_fields(out))
    # Substrate/method provenance: the ORTHOGONAL axis independence cannot express (see
    # _substrate_provenance). Derived from THIS product's manifest, so it describes the bytes just read.
    out.update(_substrate_fields(manifest_id))
    return out


def _classify_selectivity_from_sensitivity(row: dict) -> str:
    """Assign the v3 selectivity_class from a sensitivity gene row.

    Trust anchor is agreement between the two INDEPENDENT comparator families
    (TCGA-adjacent = cell A, GTEx-population = cell C) + dominant_direction;
    magnitude on the RAW comparators is the secondary gate. Mirrors the card v3.0.0
    vocabulary (cards/tumor-vs-normal-selectivity.card.yaml). Renderer language
    MUST mirror this rule (per dashboard-rendering-discipline).

    CELL B REMOVED (analysis-methods#727): cell B was the ComBat-seq re-run of cell A on the SAME
    tumour-vs-adjacent samples — a robustness re-run, not an independent comparator. With it gone
    the product's `cells_ran`/`cells_supporting` count exactly cells A and C, which ARE the two
    independent families, so the cell-vs-family distinction FIX 4 introduced no longer bites for
    fresh products. The family-based denominator is retained regardless (below), and older products
    that still carry log2fc_B/padj_B are simply not read. The FIX narratives below are kept as the
    calibration history that shaped the surviving gates.

    NOTE the product's own `cells_supporting`/`cells_ran` are still NOT used as the
    denominator (they were until FIX 4 below); `comparator_families_ran`/
    `comparator_families_supporting` expose what this classifier actually used.

    CALIBRATION FIXES (2026-08-07, backtest-driven — see feedback_selectivity_calibration_backtest):
      FIX 1 (ComBat de-weight): the magnitude gate keys on the RAW comparators (cell A
        TCGA-adjacent-raw + cell C GTEx-raw), NOT max-across-all-cells. The ComBat cell B was
        found to INFLATE / sign-flip log2FC (GAPDH/COADREAD B=4.8 vs A=1.0/C=1.5; EPCAM A=-0.3→B=1.7),
        driving housekeeping false-positives when B alone cleared 1.5 — one of the reasons B was
        later removed entirely (#727).
      FIX 2 (field-effect-aware discordant): a discordant row whose signature is
        adjacent-flat/down (cell A) BUT GTEx strongly up (cell C) is the FIELD-CANCERIZATION
        pattern (adjacent 'normal' already over-expresses — e.g. CEACAM5/EPCAM in COADREAD). Rather
        than collapse a validated tumour antigen to neutral, defer to the population-normal comparator:
        classify `field_effect_tumor_selective` (a tumour-selective subclass, GTEx-anchored, flagged).

      FIX 4 (comparator INDEPENDENCE, 2026-09-12 — measured on all 29 shipped sensitivity products,
        890,801 rows; supersedes the first two KNOWN LIMITATIONS below, which are now fixed rather
        than documented):
        FIX 4a — the support fraction counts comparator FAMILIES, not cells. Cells A and B WERE the
          SAME tumour-vs-adjacent comparison (A raw, B the ComBat-seq robustness re-run, since
          removed in #727), so the old per-cell count was wrong in BOTH directions, and the measured
          damage was mostly the direction the 2026-08-13 note did not anticipate:
            * it MANUFACTURED support — 12,492 rows reached `modest` (frac 2/3) on cells A+B alone,
              one comparator counted twice, with cell C measured and NOT agreeing; and
            * it DESTROYED support — 7,084 rows were held at `modest` because a NON-SIGNIFICANT
              ComBat cell B diluted a genuine cell-A + cell-C agreement to 2/3. Those are real
              two-independent-comparator `strong` calls, and they include MSLN/PAAD (A +0.03 q=0.22,
              B +5.64 q=1.5e-09, C +8.12 q=6.8e-166), NECTIN4/BLCA, UPK1B/BLCA and ERBB2/STAD —
              four clinically validated antigens under-called by a robustness re-run's null result.
          The inflation never reached `strong` (that needed frac >= 1.0, i.e. all three cells), which
          is why the effect on the strong tier is net POSITIVE once the denominator is right.
        FIX 4b — `strong_tumor_selective` now requires the TCGA-adjacent family to have MEASURED the
          gene and to support the direction. Seven shipped products (ACC, LGG, OV, SKCM, TGCT, UCS,
          and SCLC whose adjacent columns are present but entirely null) have no adjacent-normal arm
          at all, so every row was cells_ran=1 / cells_supporting=1 → frac 1.0 → `strong` on cell C
          ALONE: 32,784 strong calls resting entirely on the TCGA-vs-GTEx contrast that cell D was
          RETIRED for carrying a platform/batch confound. They now read `modest` (demoted, not
          deleted — the biology is often real, e.g. CLDN6/OV C=+12.18, FOLR1/OV C=+9.95,
          DLL3/SCLC C=+5.02, CTAG1B/LUAD C=+5.79; it is the EVIDENCE that is single-armed).
          NOTE the deliberate ASYMMETRY: the adjacent family is required, a second family is not, so
          4,785 `strong` calls still rest on the adjacent arm alone (HNSC 2,304 — that product has no
          cell C at all). That is intentional — adjacent-normal is the trustworthy arm and requiring
          GTEx would delete HNSC entirely — but it is no longer INVISIBLE: read
          `selectivity_evidence_independence`.

    KNOWN LIMITATIONS (2026-08-13 review — documented, not silently fixed; a rescore needs a backtest):
      * `field_effect_tumor_selective` (FIX 2) rests on cell C (TCGA-tumour vs GTEx-population), which
        carries a platform/batch confound (the reason cell D was retired) — it is GTEx-anchored and
        FLAGGED, but a batch artefact flat in adjacent yet up vs GTEx can present as this class.
        MEASURED 2026-09-12: no SHIPPED row currently mints field_effect on an absent adjacent arm
        (0 of 890,801, before or after FIX 4) — a single-cell row is never flagged `discordant`, and
        the non-discordant rescue needs |cell C| >= 1.5 on a row that would already have exited at
        the magnitude gate. But "no current data reaches it" is not "it cannot fire": the invariant
        sweep in tests/methods/dge_deseq2/test_comparator_independence.py DID reach the discordant
        rescue with a synthetic `discordant=True` + adjacent-absent row, so FIX 4c guards that path
        for real (see below). The non-discordant rescue is left unguarded deliberately — the same
        sweep cannot reach it, and a branch no input can take is a guard that cannot protect
        anything (feedback_vacuous_pass_unreachable_fail_branch); the test, not a dead `if`, is what
        goes red if a future product shape opens it.
      * Magnitude thresholds (modest raw_max_lfc >= 0.5 ~ 1.41-fold; strong >= 1.5 ~ 2.83-fold) are
        the load-bearing discriminator because padj < 0.05 is near-universal at TCGA n (significance
        != actionability). They are user-set (2026-08-07, ~30-gene backtest); no formal power/ROC
        derivation — treat `modest` as a screen, not a decision.
    """
    if not row:
        return "data_unavailable"
    direction = row.get("dominant_direction")
    # FIX 1: RAW-comparator magnitude (A=TCGA-adjacent-raw, C=GTEx-raw). (Cell B, the ComBat re-run
    # this used to exclude from the magnitude gate, was removed in analysis-methods#727.)
    raw_lfcs = [
        abs(row.get(k))
        for k in ("log2fc_cell_a", "log2fc_cell_c")
        if isinstance(row.get(k), (int, float)) and row.get(k) == row.get(k)
    ]
    raw_max_lfc = max(raw_lfcs) if raw_lfcs else 0.0

    if row.get("discordant"):
        # FIX 2: distinguish the field-effect signature from a genuine comparator conflict.
        adj = _family_direction(row, _ADJACENT_CELLS)  # TCGA-adjacent (A)
        gtex = _family_direction(row, _GTEX_CELLS)  # GTEx population-normal (C)
        c_lfc = row.get("log2fc_cell_c")
        gtex_strong_up = gtex == "up" and isinstance(c_lfc, (int, float)) and c_lfc >= 1.5
        # (FIX 2b removed with cell B in analysis-methods#727: it rescued a "mixed" adjacent family —
        # raw cell A sig-down/flat while the ComBat cell B flipped sig-up. With cell B gone the adjacent
        # family is cell A alone, so it can never be "mixed"; the raw adjacent-down/absent path is now
        # the only field-effect signature and FIX 2 base handles it.)
        if gtex_strong_up and adj in (None, "down"):
            # FIX 4c: `adj is None` above means "the adjacent family reached no significance" OR
            # "the adjacent family was never measured" — _family_direction cannot tell them apart.
            # Field cancerization is a claim ABOUT the adjacent tissue ("the margin already
            # over-expresses"), so it is unmakeable when the margin was never sequenced. No shipped
            # row reaches this (a single-cell row is never flagged `discordant`), but the input space
            # does — see test_no_field_effect_class_ever_rests_on_an_unmeasured_adjacent_arm, which
            # FOUND this path — so the guard is real, not decorative.
            if not _family_ran(row, _ADJACENT_CELLS):
                return "discordant_across_comparators"
            # adjacent flat/down (or raw-down + ComBat-up-flipped) + GTEx strongly up = field
            # cancerization; the GTEx (population) normal is the trustworthy reference here.
            return "field_effect_tumor_selective"
        return "discordant_across_comparators"

    # FIX 4a: the denominator is comparator FAMILIES that RAN, not cells. See the docstring.
    supporting, families_ran = _independent_support(row, direction)
    if families_ran == 0:
        # No family produced an estimate for this gene — nothing was measured either way.
        return "data_unavailable"
    # With a two-FAMILY denominator the fraction can only be 0, 1/2 or 1, so the old per-cell
    # `>= 2/3` tier collapses into "every family that ran agrees". Spell that out rather than leave
    # a 2/3 literal that reads as "2 of 3 cells": a 1-of-2 split (one comparator up, the other
    # measured and NOT agreeing) is no longer support — it falls through to not_informative, which
    # is the 12,492 rows that used to reach `modest` on cells A+B with cell C dissenting.
    unanimous = supporting == families_ran
    if direction == "down" and unanimous:
        return "not_selective"
    if direction == "up" and unanimous:
        if raw_max_lfc >= 1.5:
            # FIX 4b: `strong` is the band the nomination gate weights DOMINANT
            # (nomination_verdict_gate.yaml) and the only band the surface-/intracellular-intrinsic
            # rules fire on. It may not rest on the GTEx arm ALONE — that is the confounded arm cell
            # D was retired for. Require the within-patient adjacent comparison to have MEASURED
            # this gene and to agree; single-armed GTEx evidence reads one tier down.
            if _family_ran(row, _ADJACENT_CELLS) and _family_direction(row, _ADJACENT_CELLS) == direction:
                return "strong_tumor_selective"
            return "modest_tumor_selective"
        if raw_max_lfc >= 0.5:
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
    # `_family_direction(...) in (None, "down")` below still conflates an ABSENT adjacent arm with a
    # flat one. Unlike the discordant rescue above (which FIX 4c guards, because the invariant sweep
    # reached it), this one is unreachable with an absent adjacent arm by ARITHMETIC, not just by
    # current data: an adjacent-absent row is unanimous over its one family, so it exits at the
    # magnitude gates unless raw_max_lfc = |cell C| < 0.5, which contradicts the c_lfc >= 1.5 test
    # here. Guarding it would add a branch no input can take. The invariant is asserted in
    # tests/methods/dge_deseq2/test_comparator_independence.py, which sweeps this branch's input
    # space and goes RED if a future product shape opens it.
    c_lfc = row.get("log2fc_cell_c")
    if (
        direction == "up"
        and _family_direction(row, _GTEX_CELLS) == "up"
        and isinstance(c_lfc, (int, float))
        and c_lfc >= 1.5
        and _family_direction(row, _ADJACENT_CELLS) in (None, "down")
    ):
        return "field_effect_tumor_selective"
    # Everything left is either non-unanimous across independent comparators, or unanimous below the
    # magnitude floor. (The shipped code branched on `supporting <= 1` here and returned
    # not_informative from BOTH arms — a distinction that never distinguished anything; with a
    # family denominator `supporting <= 1` would also be true of every legitimate single-family row,
    # so it is dropped rather than re-pointed.)
    return "not_informative"


# The two comparator FAMILIES the selectivity design brackets: TCGA-adjacent (cell A,
# within-patient margin — carries field-effect) vs GTEx-population (cell C — carries the
# TCGA-vs-GTEx source confound). cells_supporting collapses agreement to a COUNT; this exposes
# whether the two INDEPENDENT comparator types actually concur — the cross-comparator robustness
# the design exists to produce (audit finding: "whether TCGA-adjacent and GTEx
# agree is invisible downstream"). Cell B removed (#727) and cell D retired; each family is now
# a single cell (adjacent = A, GTEx = C), so a family can no longer self-disagree ("mixed").
_ADJACENT_CELLS = (("log2fc_cell_a", "q_value_cell_a"),)
_GTEX_CELLS = (("log2fc_cell_c", "q_value_cell_c"),)
_CONCORDANCE_Q = 0.05


def _family_ran(row: dict, cells) -> bool:
    """Did this comparator family produce an ESTIMATE at all?

    This is the distinction `_family_direction` deliberately collapses and that the selectivity
    classifier needs kept apart: `_family_direction` returns None BOTH when the family's columns
    are absent (the comparison was never run — the indication has no adjacent normals, so the
    sensitivity product ships without log2fc_A/padj_A entirely) AND when the family ran but reached
    no significance. Those are opposite epistemic states: "we did not look" vs "we looked and saw
    nothing". Conflating them is what let `strong_tumor_selective` be minted for 7 indications on
    the GTEx arm alone (see the classifier docstring, FIX 4b).
    """
    for lfc_k, _q_k in cells:
        v = row.get(lfc_k)
        if v is not None and v == v:
            return True
    return False


def _independent_support(row: dict, direction) -> tuple:
    """(supporting_families, families_ran) — the INDEPENDENT-comparator support fraction.

    Replaces the per-CELL count for classification. The adjacent family (cell A, TCGA
    tumour-vs-adjacent) and the GTEx family (cell C, TCGA-tumour vs GTEx population) are the two
    INDEPENDENT comparators. (Cell B — the ComBat-seq re-run of A on the same samples — was removed
    in analysis-methods#727; while it existed, counting it separately counted the adjacent
    comparison twice.) The denominator is the number of families that RAN, so an indication with no
    adjacent normals scores 1/1 rather than being silently credited with a unanimous vote.
    """
    ran = supporting = 0
    for family in (_ADJACENT_CELLS, _GTEX_CELLS):
        if not _family_ran(row, family):
            continue
        ran += 1
        if _family_direction(row, family) == direction:
            supporting += 1
    return supporting, ran


def _selectivity_evidence_independence(row: dict) -> str:
    """Which comparator families actually MEASURED this gene — the provenance of the class.

    `comparator_concordance` answers "do the families agree?" and returns `single_comparator` for
    both "only one family ran" and "the second family ran but reached no significance". This field
    answers the prior question — "how many independent comparators produced an estimate at all?" —
    so a consumer can tell a two-comparator call from a one-comparator call without re-deriving it
    from the per-cell nulls.

    Vocabulary (kept exhaustive by tests/methods/dge_deseq2/test_comparator_independence.py, which
    asserts every value is reachable AND that no other value is ever emitted — the class of guard
    that would have caught the `ns` literal death in surfaceome_cohort_ranking):
      two_independent_comparators — TCGA-adjacent AND GTEx both estimated (the design's intent)
      adjacent_only              — TCGA-adjacent only; no GTEx arm for this indication (e.g. HNSC)
      population_normal_only     — GTEx only; NO adjacent normals exist (ACC/LGG/OV/SCLC/SKCM/TGCT/UCS)
      none                       — neither family produced an estimate
    """
    if not row:
        return "none"
    adj = _family_ran(row, _ADJACENT_CELLS)
    gtex = _family_ran(row, _GTEX_CELLS)
    if adj and gtex:
        return "two_independent_comparators"
    if adj:
        return "adjacent_only"
    if gtex:
        return "population_normal_only"
    return "none"


def _independence_fields(row: dict) -> dict:
    """The four summary_fields that make the classifier's denominator VISIBLE downstream.

    Emitted by every reader that emits `selectivity_class`, because the class alone cannot be
    audited: `strong` on two agreeing comparators and `strong` on the adjacent arm alone are the
    same string.

    ⚠️ MEASURED 2026-09-15: these four are emitted but declared in NO card and carry NO
    display_gloss entry, so they are inert downstream — the exact failure this docstring previously
    asserted was avoided ("Declared in cards/tumor-vs-normal-selectivity.card.yaml") while being an
    instance of it. A pointer that never resolves reads like a working one. The companion
    target-contracts branch feat/declare-selectivity-substrate-provenance declares all four
    (+ the two `_substrate_fields`); until it lands, treat these as computed-but-unread and do not
    infer from their presence here that a consumer can see them.
    """
    if not row:
        return {
            "comparator_families_ran": 0,
            "comparator_families_supporting": 0,
            "adjacent_arm_measured": False,
            "selectivity_evidence_independence": "none",
        }
    supporting, ran = _independent_support(row, row.get("dominant_direction"))
    return {
        "comparator_families_ran": ran,
        "comparator_families_supporting": supporting,
        "adjacent_arm_measured": _family_ran(row, _ADJACENT_CELLS),
        "selectivity_evidence_independence": _selectivity_evidence_independence(row),
    }


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
    """Do the two INDEPENDENT comparator families (TCGA-adjacent A vs GTEx C) agree?

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


# GTEx indication → tissue-of-origin (mirrors dge_tcga_gtex_precompute.cli). Consolidated into
# config/indications.yaml (S1, #693); HNSC has no clean GTEx match so it carries gtex_tissue: null
# there and is deliberately absent from this map.
INDICATION_TO_GTEX_TISSUE = indication_to_gtex_tissue()


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

    from ..gene_lengths import load_gene_lengths

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
            # Present on the empty envelope too, so a consumer never has to branch on whether the
            # field exists — an absent key and a known-unknown basis are different statements.
            **_substrate_fields(manifest_id),
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
        # Substrate/method basis of the ONE product all these strata came from. Emitted at the
        # ENVELOPE level, not inside each per_subgroup_metrics record: every stratum is read from the
        # same manifest, so a per-record copy would be a provenance field that never varies within the
        # list it sits in — invisible where it matters and noisy where it doesn't.
        **_substrate_fields(manifest_id),
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
