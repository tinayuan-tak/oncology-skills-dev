#!/usr/bin/env python3
"""gdc_somatic_hotspot CLI — aggregate TCGA MC3 MAF into a hotspot-frequency Parquet.

MC3 (TCGA Multi-Center Mutation Calling, v0.2.8 PUBLIC) is the canonical pan-TCGA
pre-aggregated MAF — one 750MB file covering ~10K aliquots across 33 cancer types.
This CLI streams MC3, filters non-synonymous variants, groups by TCGA project (via
Tumor_Sample_Barcode TSS prefix), and emits a derived Parquet keyed by:

  indication, gene_symbol, n_samples_in_indication, n_samples_mutated,
  overall_mutation_frequency, hotspot_protein_change, hotspot_n_samples, hotspot_frequency

The aggregator runs ONCE per MC3 release (rare; MC3 v0.2.8 is the canonical PanCanAtlas
reference). read.py queries the resulting Parquet with per-gene predicate pushdown.

Usage:
    python -m methods.gdc_somatic_hotspot.cli \\
        --indication COADREAD \\
        --out /tmp/coadread_mc3_hotspots.parquet
"""

from __future__ import annotations

import gzip
import os
import sys
from collections import defaultdict
from pathlib import Path

import click

DEFAULT_AWS_PROFILE = "cbg"
MC3_S3_BUCKET = "onc-compbio"
MC3_S3_KEY = "data-catalog/sources/synapse/tcga-mc3-public/mc3.v0.2.8.PUBLIC.maf.gz"

# Indication → list of TCGA project codes that compose it (canonical OncoTree mapping).
INDICATION_TO_TCGA_PROJECTS = {
    "COADREAD": ["TCGA-COAD", "TCGA-READ"],
    # Pancreatic: PAAD is the framework CANONICAL OncoTree code (indication_crosswalk.yaml);
    # PDAC is the CPTAC-cohort spelling. Dual-keyed (mirrors dge_deseq2) so a skill invoked
    # with either resolves — the earlier PDAC-only key silently produced an EMPTY product for a
    # canonical PAAD query. The `indication` column stamps whatever the caller passed, so build
    # with --indication PAAD to write the canonical value the PAAD-querying reader filters on.
    "PAAD": ["TCGA-PAAD"],
    "PDAC": ["TCGA-PAAD"],
    "NSCLC": ["TCGA-LUAD", "TCGA-LUSC"],
    "SCLC": [],
    "GC": ["TCGA-STAD"],
}

# TCGA Tissue Source Site (TSS) code → project mapping for iter-1b priority indications.
# The 2nd 2-character segment of a TCGA barcode (TCGA-XX-...) is the TSS code.
# Source: NCI/GDC tissue source site code list (https://gdc.cancer.gov/resources-tcga-users/tcga-code-tables/tissue-source-site-codes).
# This is method-local knowledge: the method knows how to map MC3's barcode-encoded
# project information to a project_id. Limited to iter-1b priority indications.
TSS_CODE_TO_TCGA_PROJECT = {
    # TCGA-COAD (colon adenocarcinoma)
    "3L": "TCGA-COAD", "4N": "TCGA-COAD", "4T": "TCGA-COAD", "5M": "TCGA-COAD",
    "A6": "TCGA-COAD", "AA": "TCGA-COAD", "AD": "TCGA-COAD", "AM": "TCGA-COAD",
    "AU": "TCGA-COAD", "AY": "TCGA-COAD", "AZ": "TCGA-COAD", "CA": "TCGA-COAD",
    "CK": "TCGA-COAD", "CM": "TCGA-COAD", "D5": "TCGA-COAD", "DM": "TCGA-COAD",
    "F4": "TCGA-COAD", "G4": "TCGA-COAD", "NH": "TCGA-COAD", "QG": "TCGA-COAD",
    "QL": "TCGA-COAD", "RU": "TCGA-COAD", "SS": "TCGA-COAD", "T9": "TCGA-COAD",
    "WS": "TCGA-COAD",
    # TCGA-READ (rectum adenocarcinoma)
    "AF": "TCGA-READ", "AG": "TCGA-READ", "AH": "TCGA-READ", "BM": "TCGA-READ",
    "CI": "TCGA-READ", "CL": "TCGA-READ", "DC": "TCGA-READ", "DT": "TCGA-READ",
    "DY": "TCGA-READ", "EF": "TCGA-READ", "EI": "TCGA-READ", "F5": "TCGA-READ",
    "G5": "TCGA-READ",
    # TCGA-PAAD (pancreatic adenocarcinoma)
    "2J": "TCGA-PAAD", "2L": "TCGA-PAAD", "3A": "TCGA-PAAD", "3E": "TCGA-PAAD",
    "F2": "TCGA-PAAD", "FB": "TCGA-PAAD", "H6": "TCGA-PAAD", "H8": "TCGA-PAAD",
    "HV": "TCGA-PAAD", "HZ": "TCGA-PAAD", "IB": "TCGA-PAAD", "L1": "TCGA-PAAD",
    "LB": "TCGA-PAAD", "M8": "TCGA-PAAD", "OE": "TCGA-PAAD", "PZ": "TCGA-PAAD",
    "Q3": "TCGA-PAAD", "RB": "TCGA-PAAD", "RL": "TCGA-PAAD", "RV": "TCGA-PAAD",
    "S4": "TCGA-PAAD", "US": "TCGA-PAAD", "XD": "TCGA-PAAD", "XN": "TCGA-PAAD",
    "YB": "TCGA-PAAD", "YH": "TCGA-PAAD", "YY": "TCGA-PAAD", "Z5": "TCGA-PAAD",
    # TCGA-LUAD (lung adenocarcinoma)
    "05": "TCGA-LUAD", "35": "TCGA-LUAD", "38": "TCGA-LUAD", "44": "TCGA-LUAD",
    "49": "TCGA-LUAD", "4B": "TCGA-LUAD", "50": "TCGA-LUAD", "53": "TCGA-LUAD",
    "55": "TCGA-LUAD", "62": "TCGA-LUAD", "64": "TCGA-LUAD", "67": "TCGA-LUAD",
    "69": "TCGA-LUAD", "71": "TCGA-LUAD", "73": "TCGA-LUAD", "75": "TCGA-LUAD",
    "78": "TCGA-LUAD", "80": "TCGA-LUAD", "83": "TCGA-LUAD", "86": "TCGA-LUAD",
    "91": "TCGA-LUAD", "93": "TCGA-LUAD", "95": "TCGA-LUAD", "97": "TCGA-LUAD",
    "99": "TCGA-LUAD", "J2": "TCGA-LUAD", "L4": "TCGA-LUAD", "L9": "TCGA-LUAD",
    "MN": "TCGA-LUAD", "MP": "TCGA-LUAD", "NJ": "TCGA-LUAD", "O1": "TCGA-LUAD",
    "S2": "TCGA-LUAD", "T6": "TCGA-LUAD",
    # TCGA-LUSC (lung squamous cell carcinoma)
    "18": "TCGA-LUSC", "21": "TCGA-LUSC", "22": "TCGA-LUSC", "33": "TCGA-LUSC",
    "34": "TCGA-LUSC", "37": "TCGA-LUSC", "39": "TCGA-LUSC", "43": "TCGA-LUSC",
    "46": "TCGA-LUSC", "51": "TCGA-LUSC", "52": "TCGA-LUSC", "56": "TCGA-LUSC",
    "58": "TCGA-LUSC", "60": "TCGA-LUSC", "63": "TCGA-LUSC", "66": "TCGA-LUSC",
    "68": "TCGA-LUSC", "6A": "TCGA-LUSC", "70": "TCGA-LUSC", "77": "TCGA-LUSC",
    "79": "TCGA-LUSC", "82": "TCGA-LUSC", "85": "TCGA-LUSC", "8C": "TCGA-LUSC",
    "90": "TCGA-LUSC", "92": "TCGA-LUSC", "94": "TCGA-LUSC", "96": "TCGA-LUSC",
    "98": "TCGA-LUSC", "J1": "TCGA-LUSC", "LA": "TCGA-LUSC", "MF": "TCGA-LUSC",
    "NC": "TCGA-LUSC", "NK": "TCGA-LUSC", "O2": "TCGA-LUSC", "XC": "TCGA-LUSC",
    "ZE": "TCGA-LUSC",
    # TCGA-STAD (stomach adenocarcinoma)
    "B7": "TCGA-STAD", "BR": "TCGA-STAD", "CD": "TCGA-STAD", "CG": "TCGA-STAD",
    "D7": "TCGA-STAD", "EQ": "TCGA-STAD", "F1": "TCGA-STAD", "FP": "TCGA-STAD",
    "HF": "TCGA-STAD", "HJ": "TCGA-STAD", "HU": "TCGA-STAD", "IN": "TCGA-STAD",
    "IP": "TCGA-STAD", "KB": "TCGA-STAD", "MX": "TCGA-STAD", "R5": "TCGA-STAD",
    "RD": "TCGA-STAD", "SW": "TCGA-STAD", "VQ": "TCGA-STAD", "ZA": "TCGA-STAD",
    "ZQ": "TCGA-STAD",
}

# Non-synonymous variant classifications.
NON_SYNONYMOUS_CLASSES = {
    "Missense_Mutation",
    "Nonsense_Mutation",
    "Frame_Shift_Ins",
    "Frame_Shift_Del",
    "In_Frame_Ins",
    "In_Frame_Del",
    "Splice_Site",
    "Translation_Start_Site",
    "Nonstop_Mutation",
}


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _barcode_to_project(barcode: str) -> str | None:
    """Parse a TCGA barcode's TSS code (2nd 2-char segment) → TCGA project."""
    parts = barcode.split("-")
    if len(parts) < 2:
        return None
    tss = parts[1]
    return TSS_CODE_TO_TCGA_PROJECT.get(tss)


def _barcode_to_sample(barcode: str) -> str:
    """Reduce a TCGA aliquot barcode to a sample-level identifier.
    TCGA-AA-3678-01A-01D-... → TCGA-AA-3678-01 (case + sample-type, drops vial/portion/aliquot).
    This deduplicates multiple aliquots from the same tumor sample."""
    parts = barcode.split("-")
    if len(parts) < 4:
        return barcode
    sample_type = parts[3][:2] if len(parts[3]) >= 2 else parts[3]
    return f"{parts[0]}-{parts[1]}-{parts[2]}-{sample_type}"


def _barcode_to_patient(barcode: str) -> str:
    """Reduce a TCGA aliquot barcode to the PATIENT (case) identifier.
    TCGA-AA-3678-01A-01D-... → TCGA-AA-3678 (3-segment case barcode).

    This is the join key for the subgroup-assignments shards
    (tcga-subgroup-assignments-*), which key on the 3-segment case barcode
    (e.g. TCGA-A6-2672), NOT the 4-segment sample id `_barcode_to_sample`
    emits. The subgroup-panorama reader does `sample_id.isin(member_ids)`
    against the shard's case barcodes, so the per-sample MAF this producer
    writes MUST use the case barcode as `sample_id` or the join silently
    matches nothing (the subgroup_n=0 failure). See subgroup-stratification
    sample-id-mismatch trap."""
    parts = barcode.split("-")
    if len(parts) < 3:
        return barcode
    return f"{parts[0]}-{parts[1]}-{parts[2]}"


def aggregate_indication(indication: str) -> "pa.Table":
    """Aggregate MC3 mutations for an indication's TCGA project(s). Returns a pyarrow
    Table sorted by (gene_symbol, -hotspot_n_samples) for efficient predicate pushdown
    downstream.

    Output schema:
      indication, gene_symbol, n_samples_in_indication, n_samples_mutated,
      overall_mutation_frequency, hotspot_protein_change, hotspot_n_samples,
      hotspot_frequency. Gene-level summary rows have null hotspot fields.
    """
    import boto3
    import pyarrow as pa

    _ensure_aws_profile()

    projects = set(INDICATION_TO_TCGA_PROJECTS.get(indication, []))
    if not projects:
        return pa.Table.from_pylist([], schema=_output_schema())

    s3 = boto3.client("s3")
    click.echo(f"Streaming MC3 from s3://{MC3_S3_BUCKET}/{MC3_S3_KEY}...", err=True)
    obj = s3.get_object(Bucket=MC3_S3_BUCKET, Key=MC3_S3_KEY)
    body = obj["Body"]

    # Stream-decompress the gzipped MAF and process line-by-line. The decompression
    # is in-memory; the MAF is large but tractable.
    gz = gzip.GzipFile(fileobj=body)

    gene_data: dict = defaultdict(lambda: {"mutated_samples": set(), "hotspots": defaultdict(set)})
    indication_samples: set = set()
    rejected_unmapped_tss = 0
    rejected_other_project = 0
    n_lines = 0
    hdr_col_idx = None

    for raw_line in gz:
        n_lines += 1
        if n_lines % 500000 == 0:
            click.echo(f"  Processed {n_lines:,} MAF lines, {len(indication_samples)} samples in scope so far...", err=True)
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        if not line or line.startswith("#"):
            continue
        if hdr_col_idx is None:
            cols = line.split("\t")
            try:
                hdr_col_idx = {
                    "Hugo_Symbol": cols.index("Hugo_Symbol"),
                    "Variant_Classification": cols.index("Variant_Classification"),
                    "HGVSp_Short": cols.index("HGVSp_Short"),
                    "Tumor_Sample_Barcode": cols.index("Tumor_Sample_Barcode"),
                }
            except ValueError as e:
                raise RuntimeError(f"MC3 header missing required column: {e}")
            continue

        parts = line.split("\t")
        if len(parts) < max(hdr_col_idx.values()) + 1:
            continue

        barcode = parts[hdr_col_idx["Tumor_Sample_Barcode"]]
        project = _barcode_to_project(barcode)
        if project is None:
            rejected_unmapped_tss += 1
            continue
        if project not in projects:
            rejected_other_project += 1
            continue

        sample = _barcode_to_sample(barcode)
        indication_samples.add(sample)

        vc = parts[hdr_col_idx["Variant_Classification"]]
        if vc not in NON_SYNONYMOUS_CLASSES:
            continue

        gene = parts[hdr_col_idx["Hugo_Symbol"]]
        if not gene or gene in (".", ""):
            continue

        gene_data[gene]["mutated_samples"].add(sample)
        hgvs = parts[hdr_col_idx["HGVSp_Short"]] or "unknown"
        gene_data[gene]["hotspots"][hgvs].add(sample)

    click.echo(f"\nMC3 streamed: {n_lines:,} lines total", err=True)
    click.echo(f"  Samples in {indication} ({projects}): {len(indication_samples)}", err=True)
    click.echo(f"  Genes with ≥1 non-synonymous mutation: {len(gene_data)}", err=True)
    click.echo(f"  Lines rejected (unmapped TSS): {rejected_unmapped_tss:,}", err=True)
    click.echo(f"  Lines rejected (other TCGA project): {rejected_other_project:,}", err=True)

    n_total = len(indication_samples)
    rows = []
    for gene in sorted(gene_data.keys()):
        gd = gene_data[gene]
        n_mutated = len(gd["mutated_samples"])
        overall_freq = n_mutated / n_total if n_total > 0 else 0.0
        rows.append({
            "indication": indication,
            "gene_symbol": gene,
            "n_samples_in_indication": n_total,
            "n_samples_mutated": n_mutated,
            "overall_mutation_frequency": overall_freq,
            "hotspot_protein_change": None,
            "hotspot_n_samples": None,
            "hotspot_frequency": None,
        })
        for hs, hs_samples in gd["hotspots"].items():
            hs_n = len(hs_samples)
            rows.append({
                "indication": indication,
                "gene_symbol": gene,
                "n_samples_in_indication": n_total,
                "n_samples_mutated": n_mutated,
                "overall_mutation_frequency": overall_freq,
                "hotspot_protein_change": hs,
                "hotspot_n_samples": hs_n,
                "hotspot_frequency": hs_n / n_total if n_total > 0 else 0.0,
            })

    rows.sort(key=lambda r: (r["gene_symbol"], -(r["hotspot_n_samples"] or 0)))
    return pa.Table.from_pylist(rows, schema=_output_schema())


def _output_schema() -> "pa.Schema":
    import pyarrow as pa
    return pa.schema([
        pa.field("indication", pa.string()),
        pa.field("gene_symbol", pa.string()),
        pa.field("n_samples_in_indication", pa.int64()),
        pa.field("n_samples_mutated", pa.int64()),
        pa.field("overall_mutation_frequency", pa.float64()),
        pa.field("hotspot_protein_change", pa.string()),
        pa.field("hotspot_n_samples", pa.int64()),
        pa.field("hotspot_frequency", pa.float64()),
    ])


def _per_sample_schema() -> "pa.Schema":
    import pyarrow as pa
    return pa.schema([
        pa.field("sample_id", pa.string()),       # 3-segment PATIENT barcode (joins the assignments shard)
        pa.field("gene_symbol", pa.string()),
        pa.field("protein_change", pa.string()),  # HGVSp_Short (or "unknown")
        pa.field("project", pa.string()),          # TCGA-COAD / TCGA-READ / ...
    ])


def per_sample_maf(indication: str) -> "pa.Table":
    """Stream MC3 and emit the PER-SAMPLE non-synonymous MAF for an indication —
    the raw substrate the subgroup-stratified-mutation-frequency panorama recomputes
    frequency WITHIN each stratum member-set from (compute-rerun, not read-side filter).

    Distinct from `aggregate_indication`, which COLLAPSES these rows into per-gene
    frequency summaries. Same stream, same non-synonymous filter, same TSS→project
    map; the difference is (a) rows are kept per (sample, gene, protein_change)
    instead of aggregated, and (b) `sample_id` is the 3-segment PATIENT barcode
    (`_barcode_to_patient`) so it JOINS the tcga-subgroup-assignments-* shards, which
    key on the case barcode. Emitting the 4-segment sample id (as the aggregate's
    internal dedup does) would make the panorama's `.isin(member_ids)` match nothing.

    Deduplicated on (sample_id, gene_symbol, protein_change): multiple aliquots of the
    same case collapse to one row, so a per-stratum `nunique(sample_id)` counts patients.

    Output schema: sample_id, gene_symbol, protein_change, project (see _per_sample_schema).
    """
    import boto3
    import pyarrow as pa

    _ensure_aws_profile()

    projects = set(INDICATION_TO_TCGA_PROJECTS.get(indication, []))
    if not projects:
        return pa.Table.from_pylist([], schema=_per_sample_schema())

    s3 = boto3.client("s3")
    click.echo(f"Streaming MC3 (per-sample) from s3://{MC3_S3_BUCKET}/{MC3_S3_KEY}...", err=True)
    obj = s3.get_object(Bucket=MC3_S3_BUCKET, Key=MC3_S3_KEY)
    gz = gzip.GzipFile(fileobj=obj["Body"])

    # Dedup key: (patient, gene, protein_change) → project. A set of tuples keeps memory
    # bounded (one entry per distinct call, not per aliquot line).
    seen: dict = {}
    patients: set = set()
    n_lines = 0
    hdr_col_idx = None

    for raw_line in gz:
        n_lines += 1
        if n_lines % 500000 == 0:
            click.echo(f"  Processed {n_lines:,} MAF lines, {len(patients)} patients in scope so far...", err=True)
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        if not line or line.startswith("#"):
            continue
        if hdr_col_idx is None:
            cols = line.split("\t")
            try:
                hdr_col_idx = {
                    "Hugo_Symbol": cols.index("Hugo_Symbol"),
                    "Variant_Classification": cols.index("Variant_Classification"),
                    "HGVSp_Short": cols.index("HGVSp_Short"),
                    "Tumor_Sample_Barcode": cols.index("Tumor_Sample_Barcode"),
                }
            except ValueError as e:
                raise RuntimeError(f"MC3 header missing required column: {e}")
            continue

        parts = line.split("\t")
        if len(parts) < max(hdr_col_idx.values()) + 1:
            continue

        barcode = parts[hdr_col_idx["Tumor_Sample_Barcode"]]
        project = _barcode_to_project(barcode)
        if project is None or project not in projects:
            continue

        patient = _barcode_to_patient(barcode)
        patients.add(patient)

        vc = parts[hdr_col_idx["Variant_Classification"]]
        if vc not in NON_SYNONYMOUS_CLASSES:
            continue
        gene = parts[hdr_col_idx["Hugo_Symbol"]]
        if not gene or gene in (".", ""):
            continue
        hgvs = parts[hdr_col_idx["HGVSp_Short"]] or "unknown"
        seen[(patient, gene, hgvs)] = project

    click.echo(f"\nMC3 streamed: {n_lines:,} lines total", err=True)
    click.echo(f"  Patients in {indication} ({projects}): {len(patients)}", err=True)
    click.echo(f"  Distinct (patient, gene, protein_change) calls: {len(seen):,}", err=True)

    rows = [
        {"sample_id": p, "gene_symbol": g, "protein_change": hs, "project": proj}
        for (p, g, hs), proj in seen.items()
    ]
    rows.sort(key=lambda r: (r["gene_symbol"], r["sample_id"]))
    return pa.Table.from_pylist(rows, schema=_per_sample_schema())


@click.command()
@click.option("--indication", required=True, help="Indication code (COADREAD, PDAC, NSCLC, GC).")
@click.option("--out", required=True, type=click.Path(dir_okay=False, path_type=Path),
              help="Output Parquet path (local).")
@click.option("--per-sample", is_flag=True, default=False,
              help="Emit the PER-SAMPLE non-synonymous MAF (sample_id/gene_symbol/protein_change/"
                   "project) instead of the per-gene hotspot aggregate. This is the substrate the "
                   "subgroup-stratified-mutation-frequency panorama recomputes per-stratum from; "
                   "sample_id is the 3-segment PATIENT barcode so it joins the assignments shards.")
def main(indication: str, out: Path, per_sample: bool) -> int:
    import pyarrow.parquet as pq
    if per_sample:
        table = per_sample_maf(indication)
        row_group = 8192   # narrow 4-col rows; larger groups are fine
    else:
        table = aggregate_indication(indication)
        row_group = 1024
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="snappy", row_group_size=row_group)
    click.echo(f"\nWrote {table.num_rows:,} rows → {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
