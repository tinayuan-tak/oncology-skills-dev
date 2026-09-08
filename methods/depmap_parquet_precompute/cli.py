#!/usr/bin/env python3
"""depmap-parquet-precompute — batch job: DepMap 26Q1 CSVs → parquet on S3.

Design decisions:
  - Numeric matrices (CRISPR, TPM, CN-WES, CN-WGS, DEMETER2): write as WIDE
    parquet (cell-line rows × gene cols) with SNAPPY compression. pyarrow's
    parquet writer supports column projection natively — a per-gene-column read
    goes from parsing a 500 MB CSV to reading a 1-2 MB parquet column chunk.

  - MAF (OmicsSomaticMutations): write LONG parquet SORTED by HugoSymbol so
    row-group predicate pushdown skips 99%+ of row groups when querying per-gene.
    Also cast dtypes aggressively (VariantInfo → categorical; ProteinChange →
    string) for further compression.

  - Small metadata tables (Model.csv, ModelCondition.csv, sample_info.csv): NOT
    parquet-ified. They're small enough that the CSV+LRU-cache in depmap_common
    already solves the fetch overhead.

  - Compression: SNAPPY over gzip. Snappy decompresses ~3-5x faster; gzip only
    matters if network is very slow. On SageMaker + S3 (10+ Gbps), snappy wins.

  - Output prefix VERSIONED: depmap-26q1-parquet-v1/. If we regenerate with
    different compression / schema, bump to -v2/ and refactor readers.

WALL TIME: ~15-30 min for full precompute (dominated by S3 downloads of the
source CSVs; parquet conversion is quick).
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click

DEPMAP_S3_BUCKET = "onc-compbio"
DEPMAP_SOURCE_PREFIX_CRISPR = "data-catalog/sources/depmap-consortium/dmc-26q1"
DEPMAP_SOURCE_PREFIX_RNAI = "data-catalog/sources/depmap-consortium/dmc-26q1-rnai"
DEFAULT_OUTPUT_PREFIX = "data-catalog/derived/depmap-26q1-parquet-v1"

# Files to precompute: (source_prefix, filename, output_parquet_name, index_col, dtype_hint)
# WIDE matrices (cell-line rows × gene cols): CRISPR, TPM, CN. LONG: MAF.
# TRANSPOSED (gene rows × cell-line cols): DEMETER2 (needs transpose during write).
PRECOMPUTE_TARGETS = [
    {
        "source_key": f"{DEPMAP_SOURCE_PREFIX_CRISPR}/CRISPRGeneEffect.csv",
        "output_name": "CRISPRGeneEffect.parquet",
        "orientation": "wide",
        "index_col_name": None,  # unnamed row-index in CSV
        "notes": "cell-line rows × gene columns; first col unnamed row-index (ModelID)",
    },
    {
        # Sanger-inclusive combined Chronos (Project Score) — the cross-consortium comparator to
        # CRISPRGeneEffect (Broad Achilles) above. Identical shape (cell-line rows × gene cols, first
        # col unnamed ModelID); lets cross_consortium_dependency read one gene's column by projection
        # instead of downloading the 685 MB CSV. Consumed by cross-consortium-dependency.
        "source_key": f"{DEPMAP_SOURCE_PREFIX_CRISPR}/ScreenGeneEffect.csv",
        "output_name": "ScreenGeneEffect.parquet",
        "orientation": "wide",
        "index_col_name": None,  # unnamed row-index in CSV
        "notes": "cell-line rows × gene columns; first col unnamed row-index (ModelID); Sanger-inclusive combined Chronos (Project Score)",
    },
    {
        "source_key": f"{DEPMAP_SOURCE_PREFIX_CRISPR}/OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv",
        "output_name": "OmicsExpressionTPMLogp1HumanProteinCodingGenes.parquet",
        "orientation": "wide_with_metadata",
        "index_col_name": None,
        "notes": "First 5 cols: SequencingID, ModelConditionID, ModelID, IsDefaultEntryForModel, IsDefaultEntryForMC",
    },
    {
        "source_key": f"{DEPMAP_SOURCE_PREFIX_CRISPR}/OmicsCNGeneMC_WES.csv",
        "output_name": "OmicsCNGeneMC_WES.parquet",
        "orientation": "wide_with_metadata",
        "index_col_name": "ModelConditionID",
        "notes": "First 2 cols: ModelConditionID, IsDefaultEntryForMC",
    },
    {
        "source_key": f"{DEPMAP_SOURCE_PREFIX_CRISPR}/OmicsCNGeneWGS.csv",
        "output_name": "OmicsCNGeneWGS.parquet",
        "orientation": "wide_with_metadata",
        "index_col_name": "ModelConditionID",
        "notes": "WGS gene-level CN; fallback panel for genes absent from WES",
    },
    {
        "source_key": f"{DEPMAP_SOURCE_PREFIX_RNAI}/D2_combined_gene_dep_scores.csv",
        "output_name": "D2_combined_gene_dep_scores.parquet",
        "orientation": "transposed_wide",
        "index_col_name": None,  # gene labels in row 0
        "notes": "DEMETER2 combined; TRANSPOSED (gene rows × cell-line cols). Write AS-IS keeping orientation; readers know shape.",
    },
    {
        "source_key": f"{DEPMAP_SOURCE_PREFIX_CRISPR}/OmicsSomaticMutations.csv",
        "output_name": "OmicsSomaticMutations.parquet",
        "orientation": "long_partitioned",
        "index_col_name": None,
        "notes": "MAF; sorted by HugoSymbol for row-group pushdown; VariantInfo cast to categorical",
    },
    {
        "source_key": f"{DEPMAP_SOURCE_PREFIX_CRISPR}/OmicsSomaticMutationsMatrixHotspot.csv",
        "output_name": "OmicsSomaticMutationsMatrixHotspot.parquet",
        "orientation": "wide_with_metadata",
        "index_col_name": "ModelID",
        "notes": "Binary hotspot mutation matrix (cell-line rows × gene cols); ~554 gene cols (COSMIC-anchored). Consumed by mutation-stratified-dependency card.",
    },
    {
        "source_key": f"{DEPMAP_SOURCE_PREFIX_CRISPR}/OmicsSomaticMutationsMatrixDamaging.csv",
        "output_name": "OmicsSomaticMutationsMatrixDamaging.parquet",
        "orientation": "wide_with_metadata",
        "index_col_name": "ModelID",
        "notes": "Binary damaging (LOF) mutation matrix (cell-line rows × gene cols); ~2233 gene cols. Consumed by mutation-stratified-dependency card.",
    },
]


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _sha256_bytes(b: bytes, chunk_size: int = 8_388_608) -> str:
    """Compute SHA-256 of bytes in chunks for memory-safety on very large files."""
    h = hashlib.sha256()
    view = memoryview(b)
    for i in range(0, len(view), chunk_size):
        h.update(view[i : i + chunk_size])
    return h.hexdigest()


def _fetch_source(s3, source_key: str) -> tuple[bytes, str, int]:
    """Fetch a source CSV from S3. Returns (bytes, sha256_hex, size_bytes)."""
    _log(f"  Fetching s3://{DEPMAP_S3_BUCKET}/{source_key}")
    obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=source_key)
    body = obj["Body"].read()
    sha256 = _sha256_bytes(body)
    _log(f"    {len(body) / 1e6:.1f} MB, sha256={sha256[:12]}...")
    return body, sha256, len(body)


def _convert_wide_matrix(body: bytes, index_col_name: Optional[str]) -> "pyarrow.Table":
    """Parse a wide-format CSV (cell-line rows × gene cols) and return a pyarrow Table.

    Metadata columns detected by dtype: pandas reads string columns as object,
    numeric as float/int. Cast all NON-OBJECT columns to float32 (Chronos/DEMETER2/
    TPM/CN precision is far below float32 quantization; saves 50% memory + size).
    Object columns (SequencingID, ModelID, IsDefaultEntryForModel, etc.) preserved
    as-is.
    """
    import pandas as pd
    import pyarrow as pa

    df = pd.read_csv(BytesIO(body))
    # Canonicalize the unnamed row-index column (pandas defaults to 'Unnamed: 0').
    # CRISPRGeneEffect has this shape: first column is unnamed and contains ModelIDs.
    if df.columns[0] == "Unnamed: 0":
        # Peek at first value to distinguish ModelID (ACH-XXXXXX) vs ModelConditionID (MC-XXX)
        sample_val = str(df.iloc[0, 0]) if len(df) > 0 else ""
        if sample_val.startswith("ACH-") or sample_val.startswith("SC-"):
            # ACH- = Broad model id (CRISPRGeneEffect); SC-... = Sanger screen/sample id
            # (ScreenGeneEffect). Both are the per-line row key → the "ModelID" column that
            # get_matrix_column_by_model_id projects (it returns None if "ModelID" is absent).
            df.rename(columns={"Unnamed: 0": "ModelID"}, inplace=True)
        elif sample_val.startswith("MC-"):
            df.rename(columns={"Unnamed: 0": "ModelConditionID"}, inplace=True)
        else:
            # Unknown; leave as-is but strip the pandas artifact
            df.rename(columns={"Unnamed: 0": "row_id"}, inplace=True)
    # Cast NUMERIC columns to float32 (Chronos/DEMETER2/TPM/CN precision is far below float32
    # quantization; saves ~50% memory + size). Use a dtype-KIND check rather than `!= object` so a
    # string identifier column read under pandas' pyarrow string backend (dtype 'string[pyarrow]',
    # NOT object) is still recognized as metadata and preserved — the prior `!= object` test tried to
    # float-cast such an id column (e.g. the Sanger 'SC-002730.CD02' ModelID) and raised.
    import pandas.api.types as _ptypes

    for c in df.columns:
        if _ptypes.is_numeric_dtype(df[c]):
            df[c] = df[c].astype("float32")
    return pa.Table.from_pandas(df, preserve_index=False)


def _convert_transposed_wide_matrix(body: bytes) -> "pyarrow.Table":
    """Parse the DEMETER2 combined file (gene rows × cell-line cols) AS-IS.

    Do NOT transpose (would blow up column count to 700 per cell line -> unwieldy
    parquet schema). Instead, keep gene-row orientation but add a `gene_symbol`
    column for easy filtering. Loader-side does the target-lookup by row.
    """
    import pandas as pd
    import pyarrow as pa

    df = pd.read_csv(BytesIO(body), index_col=0, na_values=["NA", ""])
    # Extract gene symbol from index format "SYMBOL (entrez_id)"
    import re

    _re = re.compile(r"^([A-Za-z0-9._-]+)\s*\(\d+\)$")
    df.reset_index(inplace=True)
    df.rename(columns={df.columns[0]: "gene_label"}, inplace=True)
    df["gene_symbol"] = df["gene_label"].apply(
        lambda x: _re.match(str(x).strip('"')).group(1) if _re.match(str(x).strip('"')) else None
    )
    # Cast all cell-line columns to float32
    for c in df.columns:
        if c not in ("gene_label", "gene_symbol"):
            df[c] = df[c].astype("float32")
    return pa.Table.from_pandas(df, preserve_index=False)


def _convert_maf(body: bytes) -> "pyarrow.Table":
    """Parse OmicsSomaticMutations.csv → sorted-by-HugoSymbol pyarrow Table.

    Cast VariantInfo + VariantType to categorical (dictionary encoding) for
    compression + fast filtering. Sort by HugoSymbol so row-group predicate
    pushdown skips most row groups on gene queries.
    """
    import pandas as pd
    import pyarrow as pa

    # Read only the columns downstream methods use — MAF is 738 MB but E4 + E3-strat
    # only need these 7 columns.
    keep_cols = [
        "ModelID",
        "ModelConditionID",
        "IsDefaultEntryForModel",
        "IsDefaultEntryForMC",
        "HugoSymbol",
        "VariantType",
        "VariantInfo",
        "ProteinChange",
    ]
    df = pd.read_csv(BytesIO(body), usecols=keep_cols)
    # Sort by HugoSymbol for row-group pushdown
    df.sort_values(["HugoSymbol", "ModelID"], inplace=True)
    # Categorical dtypes → dictionary encoded in parquet (huge compression win)
    for c in ("HugoSymbol", "VariantType", "VariantInfo", "IsDefaultEntryForModel", "IsDefaultEntryForMC"):
        df[c] = df[c].astype("category")
    return pa.Table.from_pandas(df, preserve_index=False)


def _write_parquet_local(table, local_path: Path) -> int:
    """Write pyarrow.Table to a local parquet file with snappy compression.
    Returns file size in bytes."""
    import pyarrow.parquet as pq

    local_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(local_path), compression="snappy")
    return local_path.stat().st_size


def _upload_to_s3(s3, local_path: Path, s3_key: str) -> None:
    """Upload a local file to S3."""
    _log(
        f"  Uploading {local_path.name} ({local_path.stat().st_size / 1e6:.1f} MB) -> s3://{DEPMAP_S3_BUCKET}/{s3_key}"
    )
    with open(local_path, "rb") as f:
        s3.upload_fileobj(f, DEPMAP_S3_BUCKET, s3_key)


def precompute_one(s3, target_spec: dict, local_dir: Path, output_prefix: str, upload: bool = True) -> dict:
    """Precompute one file: fetch CSV → convert to parquet → write locally → upload."""
    source_key = target_spec["source_key"]
    output_name = target_spec["output_name"]
    orientation = target_spec["orientation"]

    body, sha256, csv_size = _fetch_source(s3, source_key)

    _log(f"  Converting to parquet (orientation={orientation})")
    if orientation in ("wide", "wide_with_metadata"):
        table = _convert_wide_matrix(body, target_spec.get("index_col_name"))
    elif orientation == "transposed_wide":
        table = _convert_transposed_wide_matrix(body)
    elif orientation == "long_partitioned":
        table = _convert_maf(body)
    else:
        raise ValueError(f"Unknown orientation: {orientation}")

    local_path = local_dir / output_name
    parquet_size = _write_parquet_local(table, local_path)
    _log(f"    wrote {local_path} ({parquet_size / 1e6:.1f} MB) [compression ratio: {csv_size / parquet_size:.1f}x]")

    s3_key = f"{output_prefix.rstrip('/')}/{output_name}"
    if upload:
        _upload_to_s3(s3, local_path, s3_key)

    return {
        "source_key": source_key,
        "source_sha256": sha256,
        "source_size_bytes": csv_size,
        "output_name": output_name,
        "output_s3_key": s3_key,
        "parquet_size_bytes": parquet_size,
        "compression_ratio": csv_size / parquet_size,
        "n_rows": table.num_rows,
        "n_columns": table.num_columns,
        "orientation": orientation,
        "notes": target_spec.get("notes", ""),
    }


def write_manifest(entries: list[dict], local_dir: Path, output_prefix: str, s3, upload: bool = True) -> Path:
    """Write manifest.yaml documenting the derived-product state."""
    import yaml

    manifest = {
        "derived_product_id": "depmap-26q1-parquet-v1",
        "release_pin": "26q1",
        "framework_version": "v2",
        "generated_by": "methods.depmap_parquet_precompute.cli",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_s3_prefix": f"s3://{DEPMAP_S3_BUCKET}/{output_prefix.rstrip('/')}/",
        "compression": "snappy",
        "notes": (
            "Parquet-converted DepMap 26Q1 numeric matrices + MAF. Consumed by "
            "methods.depmap_common.parquet loaders. Column-projection reads (via "
            "pyarrow.dataset) drop per-fetch size ~100-500x vs the source CSVs."
        ),
        "files": entries,
    }
    manifest_path = local_dir / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False, default_flow_style=False)
    if upload:
        s3_key = f"{output_prefix.rstrip('/')}/manifest.yaml"
        _upload_to_s3(s3, manifest_path, s3_key)
    return manifest_path


@click.command()
@click.option("--release-pin", default="26q1")
@click.option(
    "--output-prefix", default=DEFAULT_OUTPUT_PREFIX, help="S3 prefix (relative to bucket) where parquets get written."
)
@click.option(
    "--local-dir",
    type=click.Path(file_okay=False, writable=True, path_type=Path),
    default=Path.home() / "dev" / "framework-runs" / "depmap-parquet-precompute-local",
    help="Local staging dir where parquets are written before S3 upload.",
)
@click.option("--targets", multiple=True, help="Optional subset of source filenames to precompute. If omitted, all.")
@click.option("--no-upload", is_flag=True, help="Skip S3 upload; write local parquets only. Useful for testing.")
def main(release_pin: str, output_prefix: str, local_dir: Path, targets: tuple[str, ...], no_upload: bool) -> None:
    """CLI entry point: fetch DepMap CSVs → convert to parquet → upload to S3."""
    import boto3

    s3 = boto3.client("s3")

    # Filter to selected targets if specified
    if targets:
        wanted = set(targets)
        to_process = [
            t for t in PRECOMPUTE_TARGETS if any(w in t["source_key"] or w in t["output_name"] for w in wanted)
        ]
        if not to_process:
            click.echo(f"No matching targets for --targets {targets}", err=True)
            sys.exit(1)
    else:
        to_process = PRECOMPUTE_TARGETS

    local_dir.mkdir(parents=True, exist_ok=True)
    _log(f"Precompute starting: {len(to_process)} files → {output_prefix}")
    _log(f"Local staging: {local_dir}")
    if no_upload:
        _log("(--no-upload set; skipping S3 upload)")

    entries = []
    for i, target_spec in enumerate(to_process, 1):
        _log(f"\n[{i}/{len(to_process)}] {target_spec['output_name']}")
        entry = precompute_one(s3, target_spec, local_dir, output_prefix, upload=not no_upload)
        entries.append(entry)

    manifest_path = write_manifest(entries, local_dir, output_prefix, s3, upload=not no_upload)
    _log("\n=== Precompute complete ===")
    _log(f"  {len(entries)} files precomputed")
    _log(f"  manifest: {manifest_path}")
    for e in entries:
        _log(
            f"  {e['output_name']}: {e['n_rows']} rows × {e['n_columns']} cols, "
            f"{e['parquet_size_bytes'] / 1e6:.1f} MB ({e['compression_ratio']:.1f}x compression)"
        )


if __name__ == "__main__":
    main()
