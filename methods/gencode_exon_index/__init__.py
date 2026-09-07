"""GENCODE v26 exon-index producer + loader.

Produces the `gencode-v26-exon-index-v1` derived-manifest artifact for the
data-catalog: per-exon rows from the GENCODE v26 primary_assembly GTF, keyed
by gene_id + transcript_id + exon_id + chromosome + start + end + strand.

Companion to methods/dge_deseq2/gene_lengths.py which produces per-gene
union-of-exons lengths (collapsed to one row per gene). The exon-index
retains per-exon rows so downstream consumers can:
  - Look up specific exon coordinates for splice-junction analysis (A2)
  - Compute alt-transcript-specific ECD boundaries (D-proxy)
  - Map genomic breakpoints to affected exons + transcripts (G-full-v2)
  - Select MANE-canonical transcripts

Modules:
    build   — parse GTF, emit per-exon Parquet; entry point for the
              catalog derived-manifest producer
    loader  — S3-catalogued read of the derived parquet with md5
              verification (mirrors gene_lengths.load_gene_lengths shape)
"""

METHOD_VERSION = "0.1.0"
