"""gene_lengths — Gencode v26 gene-length loader for TPM computation.

recount3 tcga-gtex-2023-01-04 counts are aligned to Gencode v26 (G026).
For TPM normalization we need the effective gene length per gene, computed
as the union-of-exons length across all transcripts for each gene (the
standard "gene length" convention used by RSEM, Salmon-tximport in
'lengthScaledTPM' mode, and TCGA's own TPM pipelines).

This module:
  1. Downloads the Gencode v26 primary_assembly annotation GTF on first
     call (~30 MB gzipped from GENCODE FTP)
  2. Parses exon coordinates per gene, computes union-of-exons length
  3. Caches result as a small parquet (~1 MB) in ~/.cache/framework-gencode-v26/
  4. On subsequent calls loads the cache directly

Returns a pandas.Series indexed by unversioned Ensembl gene_id →
effective_length_bp (int).

Design note: recount3's raw gene_sums are actually monorail read-COUNTS
(not fractional coverage), so TPM = (count / length_kb) / sum(count_j /
length_kb_j) * 1e6. This is the same formula RSEM uses for its
effective-length TPM output. For consistency with DepMap's log2(TPM+1)
convention, downstream consumers can wrap with np.log2(tpm + 1.0).
"""

from __future__ import annotations

import gzip
import io
import os
import urllib.request
from pathlib import Path
from typing import Optional


CACHE_DIR = Path.home() / ".cache" / "framework-gencode-v26"
CACHE_FILE = CACHE_DIR / "gene_lengths_v26.parquet"

# Gencode v26 primary_assembly GTF — matches recount3 G026 annotation exactly.
# Version confirmed via recount3 Bioconductor docs + monorail README.
GENCODE_V26_GTF_URL = (
    "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/"
    "release_26/gencode.v26.primary_assembly.annotation.gtf.gz"
)


def _download_gtf(local_path: Path) -> Path:
    """Fetch Gencode v26 GTF to local_path. Idempotent."""
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[gene_lengths] downloading Gencode v26 GTF (~30 MB) → {local_path}")
    with urllib.request.urlopen(GENCODE_V26_GTF_URL, timeout=120) as resp:
        with local_path.open("wb") as f:
            while True:
                chunk = resp.read(1 << 20)  # 1 MB
                if not chunk:
                    break
                f.write(chunk)
    return local_path


def _parse_gtf_to_gene_lengths(gtf_gz_path: Path) -> "pd.Series":
    """Parse Gencode GTF, return Series indexed by unversioned Ensembl
    gene_id → effective_length_bp (union-of-exons length).

    Union-of-exons: for each gene, take the union of all exon intervals
    across all transcripts and sum their disjoint lengths. This is
    RSEM's default gene-length convention and matches TCGA GDC's TPM
    pipeline.
    """
    import pandas as pd
    # Map gene_id (unversioned) → set of (chrom, start, end) exon intervals.
    # We'll dedupe intervals per gene at the end via a merge-intervals pass.
    per_gene_exons: dict[str, list[tuple[int, int]]] = {}

    with gzip.open(gtf_gz_path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 9 or fields[2] != "exon":
                continue
            start = int(fields[3])
            end = int(fields[4])
            attrs = fields[8]
            # Extract gene_id from attribute string. Format is
            # `gene_id "ENSG00000XXX.Y"; ...`
            gid_start = attrs.find('gene_id "')
            if gid_start < 0:
                continue
            gid_start += len('gene_id "')
            gid_end = attrs.find('"', gid_start)
            gene_id_versioned = attrs[gid_start:gid_end]
            gene_id = gene_id_versioned.split(".")[0]  # strip .N version suffix
            per_gene_exons.setdefault(gene_id, []).append((start, end))

    # Merge overlapping exon intervals per gene, sum disjoint lengths.
    lengths: dict[str, int] = {}
    for gene_id, intervals in per_gene_exons.items():
        intervals.sort()
        merged_len = 0
        cur_s, cur_e = intervals[0]
        for s, e in intervals[1:]:
            if s <= cur_e:
                cur_e = max(cur_e, e)
            else:
                merged_len += cur_e - cur_s + 1
                cur_s, cur_e = s, e
        merged_len += cur_e - cur_s + 1
        lengths[gene_id] = merged_len

    return pd.Series(lengths, name="effective_length_bp").astype("int32")


def load_gene_lengths(refresh: bool = False) -> "pd.Series":
    """Load Gencode v26 gene lengths (unversioned Ensembl ID → bp) with cache.

    First call downloads the GTF + computes exon unions (~30-60 sec on
    a warm connection). Subsequent calls load the cached parquet
    directly (~50 ms).

    Args:
        refresh: force re-download + re-parse even if cache exists.

    Returns:
        pandas.Series indexed by unversioned Ensembl gene_id (e.g.
        "ENSG00000133703") → int32 effective_length_bp.
    """
    import pandas as pd

    if CACHE_FILE.exists() and not refresh:
        return pd.read_parquet(CACHE_FILE)["effective_length_bp"]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    gtf_path = CACHE_DIR / "gencode.v26.primary_assembly.annotation.gtf.gz"
    _download_gtf(gtf_path)
    lengths = _parse_gtf_to_gene_lengths(gtf_path)
    # Persist as parquet (small — ~60K genes × 4 bytes = well under 1 MB)
    lengths.to_frame().to_parquet(CACHE_FILE)
    print(f"[gene_lengths] cached {len(lengths):,} gene lengths → {CACHE_FILE}")
    return lengths


def counts_to_tpm(
    counts: "np.ndarray | pd.Series",
    gene_ids: "list[str]",
    gene_lengths: Optional["pd.Series"] = None,
) -> "np.ndarray":
    """Convert a vector of per-sample counts (for one gene across samples)
    OR a per-sample vector of counts for many genes → TPM.

    Signature note: this function is designed for the per-sample use case
    the compositional skills need — "given target's counts across the
    samples in a cohort, plus library-scale info for each sample, compute
    TPM per sample." That requires the FULL count matrix per sample to
    compute the per-sample RPK-sum denominator, not just the target's
    counts.

    For the single-gene use case that the target-profile per-sample
    reader currently uses, callers should use `count_to_tpm_single_gene`
    which uses pre-computed per-sample RPK sums (fetched once via
    _fetch_recount3_*_rpk_sums).

    Args:
        counts: raw integer counts (per sample) for one or more genes
        gene_ids: parallel list of unversioned Ensembl IDs
        gene_lengths: optional override (else load_gene_lengths())

    Returns:
        numpy array of TPM values, same shape as counts.
    """
    import numpy as np
    import pandas as pd

    if gene_lengths is None:
        gene_lengths = load_gene_lengths()
    lengths_kb = pd.Series(
        [gene_lengths.get(gid, np.nan) for gid in gene_ids],
        index=gene_ids,
    ) / 1000.0

    if lengths_kb.isna().any():
        # Genes not in Gencode v26 (e.g. non-standard chroms, decoys) —
        # their TPM is undefined; return NaN for those rows/positions.
        pass  # falls through; NaN in lengths_kb → NaN in output

    counts_arr = np.asarray(counts, dtype=np.float64)
    if counts_arr.ndim == 1:
        # Single-gene single-sample-vector (or single-sample multi-gene)
        rpk = counts_arr / lengths_kb.to_numpy()
        denom = np.nansum(rpk)
        return rpk / denom * 1e6 if denom > 0 else np.zeros_like(rpk)
    # 2D: samples × genes (or genes × samples)
    raise NotImplementedError(
        "2D counts_to_tpm needs an explicit axis argument; use "
        "count_to_tpm_single_gene for the compositional-skill use case."
    )


def count_to_tpm_single_gene(
    gene_id: str,
    per_sample_counts: "pd.Series",
    per_sample_rpk_sums: "pd.Series",
    gene_lengths: Optional["pd.Series"] = None,
) -> "pd.Series":
    """Compute TPM for ONE gene across samples, using pre-computed per-
    sample RPK denominators.

    This is the correct signature for the compositional-skill use case:
    the target gene's counts are fetched (one row of the recount3
    gene_sums matrix), and per-sample RPK sums (sum of count_j /
    length_kb_j across all genes j, for each sample) are fetched once
    per (indication, tissue) pair and cached.

    Args:
        gene_id: unversioned Ensembl ID (e.g. "ENSG00000133703")
        per_sample_counts: Series indexed by sample_id → int count
        per_sample_rpk_sums: Series indexed by sample_id → float RPK sum
        gene_lengths: optional override (else load_gene_lengths())

    Returns:
        pandas.Series indexed by sample_id → float TPM
    """
    import numpy as np

    if gene_lengths is None:
        gene_lengths = load_gene_lengths()
    length_bp = gene_lengths.get(gene_id)
    if length_bp is None or length_bp <= 0:
        # Gene not in Gencode v26 or invalid — return zeros (TPM undefined)
        return per_sample_counts.astype(float) * 0.0
    length_kb = length_bp / 1000.0

    # Align on sample_id (inner join guards against sample-set drift)
    aligned = per_sample_counts.to_frame("count").join(
        per_sample_rpk_sums.to_frame("rpk_sum"),
        how="inner",
    )
    rpk = aligned["count"].astype(float) / length_kb
    tpm = np.where(
        aligned["rpk_sum"] > 0,
        rpk / aligned["rpk_sum"] * 1e6,
        0.0,
    )
    import pandas as pd
    return pd.Series(tpm, index=aligned.index, name="tpm")
