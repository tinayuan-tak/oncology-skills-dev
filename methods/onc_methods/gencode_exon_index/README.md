# gencode_exon_index

Per-exon-in-transcript index derived from the GENCODE v26 primary_assembly
GTF. Produces one Parquet file (~28 MB) that downstream skills load via
`load_exon_index()` for exon-level coordinate queries.

## Companion to `dge_deseq2/gene_lengths.py`

`gene_lengths.py` produces **union-of-exons length per gene** (one row per
gene). This module retains **per-exon-in-transcript rows** so consumers can
still answer:

- Which specific exon carries this residue? (D-proxy — ECD-boundary mapping)
- Which transcripts share this exon? (A2 — alt-splicing signals)
- What are the exon boundaries of transcript T? (G-full-v2 — breakpoint mapping)
- What are the MANE-canonical transcripts? (filter `gene_type=protein_coding`
  + `transcript_type=protein_coding` + prefer transcript-appris tags)

## Data-catalog artifacts

| Artifact | Location | Manifest |
|----------|----------|----------|
| Source GTF | `s3://onc-compbio/data-catalog/sources/gencode/gencode-v26-primary-assembly/gencode.v26.primary_assembly.annotation.gtf.gz` | `sources/gencode-v26-primary-assembly` |
| Derived Parquet | `s3://onc-compbio/data-catalog/derived/gencode-v26-exon-index-v1/exon_index_v26.parquet` | `derived/gencode-v26-exon-index-v1` |

## Usage

```python
from onc_methods.gencode_exon_index.loader import load_exon_index

df = load_exon_index()
# columns: gene_id, gene_id_versioned, gene_name, gene_type,
#          transcript_id, transcript_id_versioned, transcript_name,
#          transcript_type, exon_id, exon_id_versioned, exon_number,
#          chrom, start, end, strand

# Example: TP53 exons on canonical transcript
tp53 = df[(df.gene_name == "TP53") & (df.transcript_type == "protein_coding")]
```

## Rebuild (catalog maintainers only)

```bash
python -m onc_methods.gencode_exon_index.build \
  --gtf-gz /path/to/gencode.v26.primary_assembly.annotation.gtf.gz \
  --out-parquet exon_index_v26.parquet
```

Then update:
- `onc_methods/gencode_exon_index/loader.py` — `S3_MD5_PARQUET` pin
- `manifests/derived/gencode-v26-exon-index-v1.yaml` (data-catalog repo)
  — `md5`, `size_bytes`, `git_commit`

## Row count (v26)

- 58,233 unique genes with at least one exon
- 199,233 unique transcripts
- 680,731 unique exon IDs
- 1,194,802 exon-in-transcript rows
