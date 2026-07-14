#!/usr/bin/env python3
"""gtex-tpm-precompute — materialize the recount3-derived GTEx TPM matrix.

Streams each recount3 GTEx tissue's gene_sums matrix once, computes per-sample
log2(TPM+1) for every gene, restricts the OUTPUT to HGNC-mappable genes
(the ~41k genes carrying an HGNC symbol in the Ensembl-116 map — the same
gene universe the on-demand dge_deseq2 reader uses; this is broader than
strict protein-coding because the id-map has no biotype column, and
includes lncRNAs/antisense/etc. that carry HGNC symbols), and writes a wide
genes×samples parquet + a sample→tissue sidecar to the derived prefix.

See methods/gtex_tpm_precompute/__init__.py for the TPM definition and the
denominator invariant.

Usage:
    # Smoke-test a single tissue locally (no upload)
    python -m methods.gtex_tpm_precompute.cli --tissues COLON --no-upload

    # Full 31-tissue matrix, upload to S3
    python -m methods.gtex_tpm_precompute.cli
"""

from __future__ import annotations

import gzip
import hashlib
import io
import time
from pathlib import Path

import click

DEPMAP_S3_BUCKET = "onc-compbio"
RECOUNT3_S3_PREFIX = "data-catalog/sources/recount3/tcga-gtex-2023-01-04"
ENSEMBL_ID_MAP_S3 = ("data-catalog/sources/ensembl-id-mapping/"
                     "release-116-snapshot-2026-06-18/hsapiens_gene_id_map_release-116.tsv")
OUTPUT_S3_PREFIX = "data-catalog/derived/gtex-tpm-recount3-per-sample-v1"

# recount3 GTEx tissues (31 real; STUDY_NA is a catch-all with no tissue-of-
# origin and is excluded — its samples lack a usable SMTS classification).
GTEX_TISSUES = [
    "ADIPOSE_TISSUE", "ADRENAL_GLAND", "BLADDER", "BLOOD", "BLOOD_VESSEL",
    "BONE_MARROW", "BRAIN", "BREAST", "CERVIX_UTERI", "COLON", "ESOPHAGUS",
    "FALLOPIAN_TUBE", "HEART", "KIDNEY", "LIVER", "LUNG", "MUSCLE", "NERVE",
    "OVARY", "PANCREAS", "PITUITARY", "PROSTATE", "SALIVARY_GLAND", "SKIN",
    "SMALL_INTESTINE", "SPLEEN", "STOMACH", "TESTIS", "THYROID", "UTERUS",
    "VAGINA",
]

# Local RPK-sum cache shared with dge_deseq2.read (same path + filename scheme
# so a run of either warms the other).
RPK_CACHE_DIR = Path.home() / ".cache" / "framework-recount3-rpk-sums"


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _load_ensembl_hgnc_map(s3) -> dict[str, str]:
    """Fetch Ensembl-116 ID map → {ENSG_stem: HGNC symbol}. Protein-coding /
    HGNC-mappable genes are exactly the ones with a symbol here."""
    import pandas as pd
    body = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=ENSEMBL_ID_MAP_S3)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t")
    df = df.dropna(subset=["Gene stable ID", "HGNC symbol"])
    return dict(zip(df["Gene stable ID"], df["HGNC symbol"]))


def _stream_gene_sums(s3, tissue: str):
    """Yield (gene_stem, counts:np.ndarray) rows from a GTEx tissue's gene_sums,
    after first yielding the sample-id header list.

    First yielded item is ('__header__', list[str] of sample_ids). Subsequent
    items are (gene_id_stem, np.float64 counts array aligned to the header).
    """
    import numpy as np
    key = f"{RECOUNT3_S3_PREFIX}/gtex/{tissue}/gene_sums/gtex.gene_sums.{tissue}.G026.gz"
    body = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=key)["Body"].read()
    with gzip.open(io.BytesIO(body), "rt") as f:
        line = f.readline()
        while line.startswith("##"):
            line = f.readline()
        header = line.rstrip("\n").split("\t")
        sample_cols = header[1:]
        yield ("__header__", sample_cols)
        for line in f:
            gid_end = line.find("\t")
            gene_stem = line[:gid_end].split(".")[0]
            counts = np.fromstring(line[gid_end + 1:].rstrip("\n"),
                                   dtype=np.float64, sep="\t")
            yield (gene_stem, counts)


def _fetch_gtex_metadata(s3, tissue: str):
    """Return DataFrame [external_id, SMTS, SMTSD] for a GTEx tissue."""
    import pandas as pd
    key = f"{RECOUNT3_S3_PREFIX}/gtex/{tissue}/metadata/gtex.gtex.{tissue}.MD.gz"
    body = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=key)["Body"].read()
    return pd.read_csv(io.BytesIO(gzip.decompress(body)), sep="\t",
                       low_memory=False, usecols=["external_id", "SMTS", "SMTSD"])


def compute_tissue_log2tpm(
    s3, tissue: str, gene_lengths: dict[str, int],
    ensembl_to_hgnc: dict[str, str],
):
    """Stream one tissue's gene_sums once; return (log2tpm_df, sample_ids).

    log2tpm_df: index = ensembl_gene_id (HGNC-mappable output genes only),
                columns = sample_ids, values = log2(TPM+1) float32.
    The TPM denominator (rpk_sum per sample) is accumulated over ALL
    length-having genes regardless of output filtering.
    """
    import numpy as np
    import pandas as pd

    gen = _stream_gene_sums(s3, tissue)
    _, sample_ids = next(gen)
    n_samples = len(sample_ids)

    rpk_sum = np.zeros(n_samples, dtype=np.float64)   # denominator, ALL biotypes
    # Accumulate rpk per output-gene STEM. GENCODE encodes pseudoautosomal
    # (PAR) genes as two feature lines whose versioned IDs differ only by a
    # `_PAR_Y` suffix (e.g. ENSG…13 and ENSG…13_PAR_Y); both strip to the same
    # stem. Summing their rpk into one stem matches the on-demand reader's
    # `all_counts += counts` multi-locus aggregation and yields a unique key.
    out_rpk: dict[str, np.ndarray] = {}
    n_denom_genes = 0
    n_len_missing = 0
    n_par_merged = 0

    for gene_stem, counts in gen:
        length_bp = gene_lengths.get(gene_stem)
        if not length_bp or length_bp <= 0:
            n_len_missing += 1
            continue
        length_kb = length_bp / 1000.0
        rpk = counts / length_kb
        rpk_sum += rpk                                # denominator: ALL genes
        n_denom_genes += 1
        # Retain the rpk row only for HGNC-mappable output genes.
        if gene_stem in ensembl_to_hgnc:
            if gene_stem in out_rpk:
                out_rpk[gene_stem] += rpk             # PAR / multi-locus merge
                n_par_merged += 1
            else:
                out_rpk[gene_stem] = rpk

    if not out_rpk:
        raise RuntimeError(f"{tissue}: no HGNC-mappable output genes matched")

    out_stems = list(out_rpk.keys())
    rpk_mat = np.vstack([out_rpk[s] for s in out_stems])  # (n_out_genes, n_samples)
    # TPM = rpk / rpk_sum * 1e6 (per-sample denominator); guard zero columns.
    safe_denom = np.where(rpk_sum > 0, rpk_sum, np.nan)
    tpm = rpk_mat / safe_denom[None, :] * 1e6
    log2tpm = np.log2(np.nan_to_num(tpm, nan=0.0) + 1.0).astype(np.float32)

    df = pd.DataFrame(log2tpm, index=out_stems, columns=sample_ids)
    df.index.name = "ensembl_gene_id"
    _log(f"    {tissue}: {n_samples:,} samples | denom over {n_denom_genes:,} "
         f"length-having genes ({n_len_missing:,} skipped) | "
         f"{len(out_stems):,} HGNC-mappable output rows "
         f"({n_par_merged} PAR/multi-locus merged)")
    return df, sample_ids


def _load_gene_lengths_from_repo() -> dict[str, int]:
    """Load Gencode-v26 union-of-exon gene lengths via dge_deseq2.gene_lengths
    (the same source the on-demand reader uses, so values match the plot)."""
    from methods.dge_deseq2.gene_lengths import load_gene_lengths
    return load_gene_lengths()


def _sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324 — content-integrity only
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@click.command()
@click.option("--tissues", default=None,
              help="Comma-separated GTEx tissue subset (default: all 31). "
                   "Use e.g. --tissues COLON for a smoke test.")
@click.option("--local-dir", type=click.Path(file_okay=False, path_type=Path),
              default=Path.home() / "dev" / "framework-runs" / "gtex-tpm-precompute-v1",
              help="Local staging directory.")
@click.option("--no-upload", is_flag=True,
              help="Write parquet locally only; skip S3 upload.")
@click.option("--row-group-size", type=int, default=64,
              help="Parquet row-group size (genes per group) for per-gene pushdown.")
def main(tissues: str | None, local_dir: Path, no_upload: bool,
         row_group_size: int) -> None:
    """Materialize the recount3-derived GTEx log2(TPM+1) matrix."""
    import boto3
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    s3 = boto3.client("s3")
    tissue_list = ([t.strip().upper() for t in tissues.split(",")]
                   if tissues else list(GTEX_TISSUES))
    local_dir.mkdir(parents=True, exist_ok=True)

    _log(f"\n=== GTEx TPM precompute (recount3-derived) — {len(tissue_list)} tissue(s) ===")
    _log(f"  Output: s3://{DEPMAP_S3_BUCKET}/{OUTPUT_S3_PREFIX}/ "
         f"(upload={'no' if no_upload else 'yes'})")

    _log("\n[1/4] Loading Ensembl→HGNC map + Gencode-v26 gene lengths")
    ensembl_to_hgnc = _load_ensembl_hgnc_map(s3)
    gene_lengths = _load_gene_lengths_from_repo()
    _log(f"  {len(ensembl_to_hgnc):,} HGNC-mappable genes | "
         f"{len(gene_lengths):,} gene lengths")

    _log("\n[2/4] Streaming tissues + computing log2(TPM+1)")
    per_tissue_frames = []
    sample_tissue_rows = []
    t0 = time.monotonic()
    for i, tissue in enumerate(tissue_list, 1):
        _log(f"  [{i}/{len(tissue_list)}] {tissue}")
        df, sample_ids = compute_tissue_log2tpm(s3, tissue, gene_lengths, ensembl_to_hgnc)
        per_tissue_frames.append(df)
        md = _fetch_gtex_metadata(s3, tissue).set_index("external_id")
        for sid in sample_ids:
            smts = md["SMTS"].get(sid, "") if sid in md.index else ""
            smtsd = md["SMTSD"].get(sid, "") if sid in md.index else ""
            sample_tissue_rows.append({
                "sample_id": sid, "tissue": tissue,
                "SMTS": smts or "", "SMTSD": smtsd or "",
            })
    _log(f"  Streamed {len(tissue_list)} tissues in {time.monotonic()-t0:.0f}s")

    _log("\n[3/4] Assembling wide matrix (genes × samples)")
    # Genes axis is identical across tissues (same Gencode v26 annotation), but
    # a tissue may drop a gene if its length was missing — outer-join on the
    # gene index (union) to be safe, then fill absent cells with 0.0 (= log2(0+1),
    # i.e. "not expressed / not measured" — consistent with the plot's fillna(0)).
    matrix = pd.concat(per_tissue_frames, axis=1)   # align on ensembl_gene_id index
    matrix = matrix.fillna(0.0).astype(np.float32)
    matrix = matrix.reset_index()                    # ensembl_gene_id → column
    matrix.insert(0, "gene_symbol",
                  matrix["ensembl_gene_id"].map(ensembl_to_hgnc))
    matrix = matrix.dropna(subset=["gene_symbol"])
    matrix = matrix.sort_values("gene_symbol").reset_index(drop=True)
    sample_cols = [c for c in matrix.columns
                   if c not in ("gene_symbol", "ensembl_gene_id")]
    _log(f"  Matrix: {len(matrix):,} genes × {len(sample_cols):,} samples")

    sample_tissue = pd.DataFrame(sample_tissue_rows)
    # Guard: sample columns must match the sidecar rows exactly.
    assert set(sample_cols) == set(sample_tissue["sample_id"]), \
        "sample column / sidecar mismatch"

    _log("\n[4/4] Writing parquet + sidecar")
    # Wide matrix: gene_symbol + ensembl_gene_id (string) then float32 samples.
    fields = [pa.field("gene_symbol", pa.string()),
              pa.field("ensembl_gene_id", pa.string())]
    fields += [pa.field(c, pa.float32()) for c in sample_cols]
    schema = pa.schema(fields)
    table = pa.Table.from_pandas(matrix[["gene_symbol", "ensembl_gene_id"] + sample_cols],
                                 schema=schema, preserve_index=False)
    matrix_path = local_dir / "gtex_tpm_log2.parquet"
    pq.write_table(table, str(matrix_path), compression="snappy",
                   row_group_size=row_group_size)
    matrix_size = matrix_path.stat().st_size
    _log(f"  Wrote {matrix_path} ({matrix_size/1e6:.1f} MB)")

    sidecar_path = local_dir / "gtex_sample_tissue.parquet"
    sidecar_tbl = pa.Table.from_pandas(
        sample_tissue.sort_values(["tissue", "sample_id"]).reset_index(drop=True),
        preserve_index=False,
    )
    pq.write_table(sidecar_tbl, str(sidecar_path), compression="snappy")
    sidecar_size = sidecar_path.stat().st_size
    _log(f"  Wrote {sidecar_path} ({sidecar_size/1e3:.1f} kB)")

    # Content-integrity stamps (printed for the manifest author).
    matrix_md5 = _md5_hex(matrix_path)
    sidecar_md5 = _md5_hex(sidecar_path)
    _log(f"\n  gtex_tpm_log2.parquet     size={matrix_size} md5={matrix_md5}")
    _log(f"  gtex_sample_tissue.parquet size={sidecar_size} md5={sidecar_md5}")
    _log(f"  n_genes={len(matrix)} n_samples={len(sample_cols)} n_tissues={len(tissue_list)}")

    if not no_upload:
        for p, md5 in [(matrix_path, matrix_md5), (sidecar_path, sidecar_md5)]:
            key = f"{OUTPUT_S3_PREFIX}/{p.name}"
            _log(f"  Uploading → s3://{DEPMAP_S3_BUCKET}/{key}")
            s3.upload_file(str(p), DEPMAP_S3_BUCKET, key,
                           ExtraArgs={"Metadata": {"md5": md5}})

    _log("\n=== GTEx TPM precompute complete ===")


if __name__ == "__main__":
    main()
