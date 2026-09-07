#!/usr/bin/env python3
"""tcga-tpm-precompute — materialize the recount3-derived per-sample TCGA TUMOR TPM matrix.

The TUMOR analogue of gtex_tpm_precompute (which does GTEx normals). Streams each recount3 TCGA
study's gene_sums matrix once, FILTERS to Primary Tumor aliquots (the one genuinely new step vs
GTEx — GTEx is healthy-donor by design), computes per-sample log2(TPM+1) for every gene, restricts
the OUTPUT to HGNC-mappable genes (the same ~41k universe as GTEx + the on-demand dge_deseq2
reader), and writes a wide genes×samples parquet + a sample→study sidecar to the derived prefix.

TPM (not CPM): the per-sample product places TCGA tumor + GTEx normal on the SAME cross-gene,
cross-cohort log2(TPM+1) axis (the pan-tissue distribution plot), so full gene-length normalization
is required. See methods/tcga_tpm_precompute/__init__.py for the definition + the denominator
invariant (rpk_sum over ALL length-having genes, not just the output rows).

Usage:
    # Smoke-test a single study locally (no upload)
    python -m methods.tcga_tpm_precompute.cli --studies COAD --no-upload

    # Full 33-study matrix, upload to S3
    python -m methods.tcga_tpm_precompute.cli
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
ENSEMBL_ID_MAP_S3 = (
    "data-catalog/sources/ensembl-id-mapping/release-116-snapshot-2026-06-18/hsapiens_gene_id_map_release-116.tsv"
)
OUTPUT_S3_PREFIX = "data-catalog/derived/tcga-tumor-tpm-per-sample-v1"

# recount3 TCGA studies (33 real projects; 'NA' is a catch-all with no project-of-origin and is
# excluded — mirrors the GTEx emitter's STUDY_NA exclusion).
TCGA_STUDIES = [
    "ACC",
    "BLCA",
    "BRCA",
    "CESC",
    "CHOL",
    "COAD",
    "DLBC",
    "ESCA",
    "GBM",
    "HNSC",
    "KICH",
    "KIRC",
    "KIRP",
    "LAML",
    "LGG",
    "LIHC",
    "LUAD",
    "LUSC",
    "MESO",
    "OV",
    "PAAD",
    "PCPG",
    "PRAD",
    "READ",
    "SARC",
    "SKCM",
    "STAD",
    "TGCT",
    "THCA",
    "THYM",
    "UCEC",
    "UCS",
    "UVM",
]

# recount3 sample_type values that count as PRIMARY tumor for this product (the one new filter vs
# GTEx). Solid tumors are "Primary Tumor"; blood cancers (LAML, DLBC) type their primary samples
# differently — LAML is "Primary Blood Derived Cancer - Peripheral Blood" with NO "Primary Tumor"
# row, so a solid-only filter would crash the run. Include the primary blood-cancer types.
# EXCLUDED: Metastatic, Recurrent, and all *Normal types (this is a primary-tumor distribution).
PRIMARY_TUMOR_SAMPLE_TYPES = {
    "Primary Tumor",
    "Primary Blood Derived Cancer - Peripheral Blood",
    "Primary Blood Derived Cancer - Bone Marrow",
}
# Label stamped on the sidecar (the specific type is preserved per-sample via the metadata join).
PRIMARY_TUMOR_LABEL = "Primary Tumor"


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _load_ensembl_hgnc_map(s3) -> dict[str, str]:
    """Fetch Ensembl-116 ID map → {ENSG_stem: HGNC symbol} (same universe as the GTEx product)."""
    import pandas as pd

    body = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=ENSEMBL_ID_MAP_S3)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t")
    df = df.dropna(subset=["Gene stable ID", "HGNC symbol"])
    return dict(zip(df["Gene stable ID"], df["HGNC symbol"]))


def _stream_gene_sums(s3, study: str):
    """Yield (gene_stem, counts:np.ndarray) rows from a TCGA study's gene_sums, after first
    yielding ('__header__', list[str] of gdc_file_id sample columns). Identical shape to the GTEx
    stream; only the path substitutes tcga/{study}."""
    import numpy as np

    key = f"{RECOUNT3_S3_PREFIX}/tcga/{study}/gene_sums/tcga.gene_sums.{study}.G026.gz"
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
            counts = np.fromstring(line[gid_end + 1 :].rstrip("\n"), dtype=np.float64, sep="\t")
            yield (gene_stem, counts)


def _fetch_tcga_metadata(s3, study: str):
    """Return DataFrame [gdc_file_id, sample_type, submitter_id] for a TCGA study — the Primary-Tumor
    filter source (the recount3 gene_sums column headers ARE the gdc_file_id UUIDs)."""
    import pandas as pd

    key = f"{RECOUNT3_S3_PREFIX}/tcga/{study}/metadata/tcga.tcga.{study}.MD.gz"
    body = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=key)["Body"].read()
    df = pd.read_csv(
        io.BytesIO(gzip.decompress(body)),
        sep="\t",
        low_memory=False,
        usecols=["gdc_file_id", "gdc_cases.samples.sample_type", "gdc_cases.submitter_id"],
    )
    return df.rename(columns={"gdc_cases.samples.sample_type": "sample_type", "gdc_cases.submitter_id": "submitter_id"})


def _primary_tumor_ids(metadata) -> set[str]:
    """gdc_file_ids whose sample_type is a PRIMARY tumor type (solid or blood-cancer primary)."""
    m = metadata[metadata["sample_type"].isin(PRIMARY_TUMOR_SAMPLE_TYPES)]
    return set(m["gdc_file_id"].astype(str))


def compute_study_log2tpm(s3, study: str, gene_lengths: dict[str, int], ensembl_to_hgnc: dict[str, str]):
    """Stream one study's gene_sums once; return (log2tpm_df, tumor_sample_ids, meta).

    Filters columns to Primary Tumor BEFORE computing TPM. TPM denominator (rpk_sum per sample) is
    accumulated over ALL length-having genes, on the tumor-filtered columns. Mirrors
    gtex_tpm_precompute.compute_tissue_log2tpm with the tumor filter added."""
    import numpy as np
    import pandas as pd

    meta = _fetch_tcga_metadata(s3, study)
    tumor_ids = _primary_tumor_ids(meta)
    if not tumor_ids:
        # No primary tumor aliquots at all (shouldn't happen for the 33 studies, but skip-with-warning
        # rather than crash the whole run — one bad study must not lose the other 32).
        _log(f"    {study}: SKIPPED — no primary-tumor aliquots (types: {sorted(meta['sample_type'].unique())})")
        return None, [], meta.set_index("gdc_file_id")

    gen = _stream_gene_sums(s3, study)
    _, all_sample_ids = next(gen)
    # column mask: keep only primary-tumor sample columns (positional, aligned to the header)
    keep_idx = [i for i, sid in enumerate(all_sample_ids) if sid in tumor_ids]
    if not keep_idx:
        _log(f"    {study}: SKIPPED — primary-tumor ids don't intersect gene_sums columns")
        return None, [], meta.set_index("gdc_file_id")
    sample_ids = [all_sample_ids[i] for i in keep_idx]
    keep_arr = np.array(keep_idx, dtype=np.intp)
    n_samples = len(sample_ids)

    rpk_sum = np.zeros(n_samples, dtype=np.float64)  # denominator, ALL length-having genes
    out_rpk: dict[str, np.ndarray] = {}
    n_denom_genes = n_len_missing = n_par_merged = 0

    for gene_stem, counts in gen:
        length_bp = gene_lengths.get(gene_stem)
        if not length_bp or length_bp <= 0:
            n_len_missing += 1
            continue
        counts = counts[keep_arr]  # tumor-only columns
        length_kb = length_bp / 1000.0
        rpk = counts / length_kb
        rpk_sum += rpk
        n_denom_genes += 1
        if gene_stem in ensembl_to_hgnc:
            if gene_stem in out_rpk:
                out_rpk[gene_stem] += rpk  # PAR / multi-locus merge (sum-by-stem)
                n_par_merged += 1
            else:
                out_rpk[gene_stem] = rpk

    if not out_rpk:
        raise RuntimeError(f"{study}: no HGNC-mappable output genes matched")

    out_stems = list(out_rpk.keys())
    rpk_mat = np.vstack([out_rpk[s] for s in out_stems])
    safe_denom = np.where(rpk_sum > 0, rpk_sum, np.nan)
    tpm = rpk_mat / safe_denom[None, :] * 1e6
    log2tpm = np.log2(np.nan_to_num(tpm, nan=0.0) + 1.0).astype(np.float32)

    df = pd.DataFrame(log2tpm, index=out_stems, columns=sample_ids)
    df.index.name = "ensembl_gene_id"
    _log(
        f"    {study}: {n_samples:,} primary-tumor samples (of {len(all_sample_ids):,}) | "
        f"denom over {n_denom_genes:,} length-having genes ({n_len_missing:,} skipped) | "
        f"{len(out_stems):,} HGNC-mappable output rows ({n_par_merged} PAR/multi-locus merged)"
    )
    return df, sample_ids, meta.set_index("gdc_file_id")


def _load_gene_lengths_from_repo() -> dict[str, int]:
    """Gencode-v26 union-of-exon gene lengths (the SAME source the GTEx product + on-demand reader
    use, so TCGA + GTEx TPMs are directly comparable)."""
    from methods.dge_deseq2.gene_lengths import load_gene_lengths

    return load_gene_lengths()


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324 — content-integrity only
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@click.command()
@click.option(
    "--studies", default=None, help="Comma-separated TCGA study subset (default: all 33). e.g. --studies COAD."
)
@click.option(
    "--local-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.home() / "dev" / "framework-runs" / "tcga-tpm-precompute-v1",
    help="Local staging directory.",
)
@click.option("--no-upload", is_flag=True, help="Write parquet locally only; skip S3 upload.")
@click.option(
    "--row-group-size", type=int, default=64, help="Parquet row-group size (genes per group) for per-gene pushdown."
)
def main(studies: str | None, local_dir: Path, no_upload: bool, row_group_size: int) -> None:
    """Materialize the recount3-derived per-sample TCGA tumor log2(TPM+1) matrix."""
    import boto3
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    s3 = boto3.client("s3")
    study_list = [s.strip().upper() for s in studies.split(",")] if studies else list(TCGA_STUDIES)
    local_dir.mkdir(parents=True, exist_ok=True)

    _log(f"\n=== TCGA tumor TPM precompute (recount3-derived) — {len(study_list)} study(ies) ===")
    _log(f"  Output: s3://{DEPMAP_S3_BUCKET}/{OUTPUT_S3_PREFIX}/ (upload={'no' if no_upload else 'yes'})")

    _log("\n[1/4] Loading Ensembl→HGNC map + Gencode-v26 gene lengths")
    ensembl_to_hgnc = _load_ensembl_hgnc_map(s3)
    gene_lengths = _load_gene_lengths_from_repo()
    _log(f"  {len(ensembl_to_hgnc):,} HGNC-mappable genes | {len(gene_lengths):,} gene lengths")

    _log("\n[2/4] Streaming studies + computing per-sample log2(TPM+1) (Primary Tumor only)")
    per_study_frames = []
    sample_study_rows = []
    t0 = time.monotonic()
    skipped = []
    for i, study in enumerate(study_list, 1):
        _log(f"  [{i}/{len(study_list)}] {study}")
        df, sample_ids, meta = compute_study_log2tpm(s3, study, gene_lengths, ensembl_to_hgnc)
        if df is None:  # study skipped (no primary-tumor aliquots)
            skipped.append(study)
            continue
        per_study_frames.append(df)
        for sid in sample_ids:
            row_meta = meta.loc[sid] if sid in meta.index else None
            sample_study_rows.append(
                {
                    "sample_id": sid,
                    "study": study,
                    # preserve the ACTUAL sample_type (solid "Primary Tumor" vs blood-cancer primary)
                    "sample_type": (str(row_meta["sample_type"]) if row_meta is not None else PRIMARY_TUMOR_LABEL),
                    "submitter_id": (str(row_meta["submitter_id"]) if row_meta is not None else ""),
                }
            )
    _log(
        f"  Streamed {len(study_list) - len(skipped)} studies in {time.monotonic() - t0:.0f}s"
        + (f" (skipped: {', '.join(skipped)})" if skipped else "")
    )

    _log("\n[3/4] Assembling wide matrix (genes × tumor samples)")
    matrix = pd.concat(per_study_frames, axis=1)  # align on ensembl_gene_id index
    matrix = matrix.fillna(0.0).astype(np.float32).reset_index()
    matrix.insert(0, "gene_symbol", matrix["ensembl_gene_id"].map(ensembl_to_hgnc))
    matrix = matrix.dropna(subset=["gene_symbol"]).sort_values("gene_symbol").reset_index(drop=True)
    sample_cols = [c for c in matrix.columns if c not in ("gene_symbol", "ensembl_gene_id")]
    _log(f"  Matrix: {len(matrix):,} genes × {len(sample_cols):,} tumor samples")

    sample_study = pd.DataFrame(sample_study_rows)
    assert set(sample_cols) == set(sample_study["sample_id"]), "sample column / sidecar mismatch"

    _log("\n[4/4] Writing parquet + sidecar")
    fields = [pa.field("gene_symbol", pa.string()), pa.field("ensembl_gene_id", pa.string())]
    fields += [pa.field(c, pa.float32()) for c in sample_cols]
    table = pa.Table.from_pandas(
        matrix[["gene_symbol", "ensembl_gene_id"] + sample_cols], schema=pa.schema(fields), preserve_index=False
    )
    matrix_path = local_dir / "tcga_tpm_log2.parquet"
    pq.write_table(table, str(matrix_path), compression="snappy", row_group_size=row_group_size)
    matrix_size = matrix_path.stat().st_size
    _log(f"  Wrote {matrix_path} ({matrix_size / 1e6:.1f} MB)")

    sidecar_path = local_dir / "tcga_sample_study.parquet"
    pq.write_table(
        pa.Table.from_pandas(
            sample_study.sort_values(["study", "sample_id"]).reset_index(drop=True), preserve_index=False
        ),
        str(sidecar_path),
        compression="snappy",
    )
    sidecar_size = sidecar_path.stat().st_size
    _log(f"  Wrote {sidecar_path} ({sidecar_size / 1e3:.1f} kB)")

    matrix_md5, sidecar_md5 = _md5_hex(matrix_path), _md5_hex(sidecar_path)
    _log(f"\n  tcga_tpm_log2.parquet      size={matrix_size} md5={matrix_md5}")
    _log(f"  tcga_sample_study.parquet  size={sidecar_size} md5={sidecar_md5}")
    _log(f"  n_genes={len(matrix)} n_samples={len(sample_cols)} n_studies={len(study_list)}")

    if not no_upload:
        for p, md5 in [(matrix_path, matrix_md5), (sidecar_path, sidecar_md5)]:
            key = f"{OUTPUT_S3_PREFIX}/{p.name}"
            _log(f"  Uploading → s3://{DEPMAP_S3_BUCKET}/{key}")
            s3.upload_file(str(p), DEPMAP_S3_BUCKET, key, ExtraArgs={"Metadata": {"md5": md5}})

    _log("\n=== TCGA tumor TPM precompute complete ===")


if __name__ == "__main__":
    main()
