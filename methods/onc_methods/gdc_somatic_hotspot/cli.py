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
    python -m onc_methods.gdc_somatic_hotspot.cli \\
        --indication COADREAD \\
        --out /tmp/coadread_mc3_hotspots.parquet
"""

from __future__ import annotations

import gzip
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import click

# Figure generation constants
DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

MC3_S3_BUCKET = "onc-compbio"
MC3_S3_KEY = "data-catalog/sources/synapse/tcga-mc3-public/mc3.v0.2.8.PUBLIC.maf.gz"

# The authoritative barcode → TCGA `cancer type` crosswalk (merged_sample_quality_annotations.tsv) —
# the SAME PanCanAtlas annotation tcga_patient_cn / tcga_aneuploidy_burden / functional_gene_state use
# for their indication join. Preferred over the hardcoded TSS table below (which only covers 4
# indications' source sites): it maps EVERY TCGA aliquot to its cohort, so the all-cohort aggregate can
# cover all 33 projects from one source of truth. See _load_barcode_cancer_type.
SAMPLE_ANNOT_KEY = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/merged_sample_quality_annotations.tsv"

# TCGA `cancer type` code (as it appears in merged_sample_quality_annotations) → framework CANONICAL
# indication (target-contracts indication_crosswalk.yaml canonical_code), i.e. the value the
# patient-cohort SNV product stamps in its `indication` column and the read side filters on after
# indication_aliases.to_cohort_canonical. The three POOLED canonicals mirror to_cohort_canonical's
# UP-pooling (COAD+READ→COADREAD, LUAD+LUSC→NSCLC, STAD→GC); LAML→AML is the one heme remap; every other
# TCGA cohort is identity (its own canonical partition). Covers all 33 GDC PanCanAtlas cohorts.
CANCER_TYPE_TO_INDICATION = {
    "COAD": "COADREAD",
    "READ": "COADREAD",
    "LUAD": "NSCLC",
    "LUSC": "NSCLC",
    "STAD": "GC",
    "PAAD": "PAAD",
    "LAML": "AML",
    "GBM": "GBM",
    "LGG": "LGG",
    "BRCA": "BRCA",
    "HNSC": "HNSC",
    "ESCA": "ESCA",
    "OV": "OV",
    "PRAD": "PRAD",
    "SKCM": "SKCM",
    "UCEC": "UCEC",
    "BLCA": "BLCA",
    "KIRC": "KIRC",
    "KIRP": "KIRP",
    "KICH": "KICH",
    "LIHC": "LIHC",
    "SARC": "SARC",
    "MESO": "MESO",
    "THCA": "THCA",
    "DLBC": "DLBC",
    "CESC": "CESC",
    "ACC": "ACC",
    "UVM": "UVM",
    "PCPG": "PCPG",
    "CHOL": "CHOL",
    "TGCT": "TGCT",
    "THYM": "THYM",
    "UCS": "UCS",
}

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

# TCGA Tissue Source Site (TSS) code → project mapping for the priority indications.
# The 2nd 2-character segment of a TCGA barcode (TCGA-XX-...) is the TSS code.
# Source: NCI/GDC tissue source site code list (https://gdc.cancer.gov/resources-tcga-users/tcga-code-tables/tissue-source-site-codes).
# This is method-local knowledge: the method knows how to map MC3's barcode-encoded
# project information to a project_id. Limited to the priority indications.
TSS_CODE_TO_TCGA_PROJECT = {
    # TCGA-COAD (colon adenocarcinoma)
    "3L": "TCGA-COAD",
    "4N": "TCGA-COAD",
    "4T": "TCGA-COAD",
    "5M": "TCGA-COAD",
    "A6": "TCGA-COAD",
    "AA": "TCGA-COAD",
    "AD": "TCGA-COAD",
    "AM": "TCGA-COAD",
    "AU": "TCGA-COAD",
    "AY": "TCGA-COAD",
    "AZ": "TCGA-COAD",
    "CA": "TCGA-COAD",
    "CK": "TCGA-COAD",
    "CM": "TCGA-COAD",
    "D5": "TCGA-COAD",
    "DM": "TCGA-COAD",
    "F4": "TCGA-COAD",
    "G4": "TCGA-COAD",
    "NH": "TCGA-COAD",
    "QG": "TCGA-COAD",
    "QL": "TCGA-COAD",
    "RU": "TCGA-COAD",
    "SS": "TCGA-COAD",
    "T9": "TCGA-COAD",
    "WS": "TCGA-COAD",
    # TCGA-READ (rectum adenocarcinoma)
    "AF": "TCGA-READ",
    "AG": "TCGA-READ",
    "AH": "TCGA-READ",
    "BM": "TCGA-READ",
    "CI": "TCGA-READ",
    "CL": "TCGA-READ",
    "DC": "TCGA-READ",
    "DT": "TCGA-READ",
    "DY": "TCGA-READ",
    "EF": "TCGA-READ",
    "EI": "TCGA-READ",
    "F5": "TCGA-READ",
    "G5": "TCGA-READ",
    # TCGA-PAAD (pancreatic adenocarcinoma)
    "2J": "TCGA-PAAD",
    "2L": "TCGA-PAAD",
    "3A": "TCGA-PAAD",
    "3E": "TCGA-PAAD",
    "F2": "TCGA-PAAD",
    "FB": "TCGA-PAAD",
    "H6": "TCGA-PAAD",
    "H8": "TCGA-PAAD",
    "HV": "TCGA-PAAD",
    "HZ": "TCGA-PAAD",
    "IB": "TCGA-PAAD",
    "L1": "TCGA-PAAD",
    "LB": "TCGA-PAAD",
    "M8": "TCGA-PAAD",
    "OE": "TCGA-PAAD",
    "PZ": "TCGA-PAAD",
    "Q3": "TCGA-PAAD",
    "RB": "TCGA-PAAD",
    "RL": "TCGA-PAAD",
    "RV": "TCGA-PAAD",
    "S4": "TCGA-PAAD",
    "US": "TCGA-PAAD",
    "XD": "TCGA-PAAD",
    "XN": "TCGA-PAAD",
    "YB": "TCGA-PAAD",
    "YH": "TCGA-PAAD",
    "YY": "TCGA-PAAD",
    "Z5": "TCGA-PAAD",
    # TCGA-LUAD (lung adenocarcinoma)
    "05": "TCGA-LUAD",
    "35": "TCGA-LUAD",
    "38": "TCGA-LUAD",
    "44": "TCGA-LUAD",
    "49": "TCGA-LUAD",
    "4B": "TCGA-LUAD",
    "50": "TCGA-LUAD",
    "53": "TCGA-LUAD",
    "55": "TCGA-LUAD",
    "62": "TCGA-LUAD",
    "64": "TCGA-LUAD",
    "67": "TCGA-LUAD",
    "69": "TCGA-LUAD",
    "71": "TCGA-LUAD",
    "73": "TCGA-LUAD",
    "75": "TCGA-LUAD",
    "78": "TCGA-LUAD",
    "80": "TCGA-LUAD",
    "83": "TCGA-LUAD",
    "86": "TCGA-LUAD",
    "91": "TCGA-LUAD",
    "93": "TCGA-LUAD",
    "95": "TCGA-LUAD",
    "97": "TCGA-LUAD",
    "99": "TCGA-LUAD",
    "J2": "TCGA-LUAD",
    "L4": "TCGA-LUAD",
    "L9": "TCGA-LUAD",
    "MN": "TCGA-LUAD",
    "MP": "TCGA-LUAD",
    "NJ": "TCGA-LUAD",
    "O1": "TCGA-LUAD",
    "S2": "TCGA-LUAD",
    "T6": "TCGA-LUAD",
    # TCGA-LUSC (lung squamous cell carcinoma)
    "18": "TCGA-LUSC",
    "21": "TCGA-LUSC",
    "22": "TCGA-LUSC",
    "33": "TCGA-LUSC",
    "34": "TCGA-LUSC",
    "37": "TCGA-LUSC",
    "39": "TCGA-LUSC",
    "43": "TCGA-LUSC",
    "46": "TCGA-LUSC",
    "51": "TCGA-LUSC",
    "52": "TCGA-LUSC",
    "56": "TCGA-LUSC",
    "58": "TCGA-LUSC",
    "60": "TCGA-LUSC",
    "63": "TCGA-LUSC",
    "66": "TCGA-LUSC",
    "68": "TCGA-LUSC",
    "6A": "TCGA-LUSC",
    "70": "TCGA-LUSC",
    "77": "TCGA-LUSC",
    "79": "TCGA-LUSC",
    "82": "TCGA-LUSC",
    "85": "TCGA-LUSC",
    "8C": "TCGA-LUSC",
    "90": "TCGA-LUSC",
    "92": "TCGA-LUSC",
    "94": "TCGA-LUSC",
    "96": "TCGA-LUSC",
    "98": "TCGA-LUSC",
    "J1": "TCGA-LUSC",
    "LA": "TCGA-LUSC",
    "MF": "TCGA-LUSC",
    "NC": "TCGA-LUSC",
    "NK": "TCGA-LUSC",
    "O2": "TCGA-LUSC",
    "XC": "TCGA-LUSC",
    "ZE": "TCGA-LUSC",
    # TCGA-STAD (stomach adenocarcinoma)
    "B7": "TCGA-STAD",
    "BR": "TCGA-STAD",
    "CD": "TCGA-STAD",
    "CG": "TCGA-STAD",
    "D7": "TCGA-STAD",
    "EQ": "TCGA-STAD",
    "F1": "TCGA-STAD",
    "FP": "TCGA-STAD",
    "HF": "TCGA-STAD",
    "HJ": "TCGA-STAD",
    "HU": "TCGA-STAD",
    "IN": "TCGA-STAD",
    "IP": "TCGA-STAD",
    "KB": "TCGA-STAD",
    "MX": "TCGA-STAD",
    "R5": "TCGA-STAD",
    "RD": "TCGA-STAD",
    "SW": "TCGA-STAD",
    "VQ": "TCGA-STAD",
    "ZA": "TCGA-STAD",
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


from onc_methods.target_id_sidecar import ensure_aws_profile


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

    ensure_aws_profile()

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
            click.echo(
                f"  Processed {n_lines:,} MAF lines, {len(indication_samples)} samples in scope so far...", err=True
            )
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
        rows.append(
            {
                "indication": indication,
                "gene_symbol": gene,
                "n_samples_in_indication": n_total,
                "n_samples_mutated": n_mutated,
                "overall_mutation_frequency": overall_freq,
                "hotspot_protein_change": None,
                "hotspot_n_samples": None,
                "hotspot_frequency": None,
            }
        )
        for hs, hs_samples in gd["hotspots"].items():
            hs_n = len(hs_samples)
            rows.append(
                {
                    "indication": indication,
                    "gene_symbol": gene,
                    "n_samples_in_indication": n_total,
                    "n_samples_mutated": n_mutated,
                    "overall_mutation_frequency": overall_freq,
                    "hotspot_protein_change": hs,
                    "hotspot_n_samples": hs_n,
                    "hotspot_frequency": hs_n / n_total if n_total > 0 else 0.0,
                }
            )

    rows.sort(key=lambda r: (r["gene_symbol"], -(r["hotspot_n_samples"] or 0)))
    return pa.Table.from_pylist(rows, schema=_output_schema())


def _load_barcode_cancer_type() -> dict:
    """{patient_barcode: TCGA cancer-type code} from merged_sample_quality_annotations — the authoritative
    PanCanAtlas crosswalk (all 33 cohorts), the same one tcga_patient_cn/tcga_aneuploidy_burden join on.
    Raises on a transient/broken read or an empty map (absence-discipline: a silent {} would make the
    all-cohort build emit ZERO rows and look like a successful no-op)."""
    import io

    import boto3
    import pandas as pd

    ensure_aws_profile()
    s3 = boto3.client("s3")
    raw = s3.get_object(Bucket=MC3_S3_BUCKET, Key=SAMPLE_ANNOT_KEY)["Body"].read()
    df = pd.read_csv(io.BytesIO(raw), sep="\t", usecols=["patient_barcode", "cancer type"], dtype=str)
    df = df.dropna(subset=["patient_barcode", "cancer type"])
    out = dict(zip(df["patient_barcode"].str.strip(), df["cancer type"].str.strip()))
    if not out:
        raise RuntimeError(
            f"barcode→cancer-type crosswalk s3://{MC3_S3_BUCKET}/{SAMPLE_ANNOT_KEY} produced an EMPTY map"
        )
    return out


def aggregate_all_cohorts() -> "pa.Table":
    """Single-pass all-cohort MC3 aggregate: stream the 750 MB MAF ONCE, route each aliquot to its
    framework CANONICAL indication via the authoritative barcode→cancer-type crosswalk (all 33 TCGA
    cohorts), and emit the same per-(indication, gene, hotspot) schema as aggregate_indication for every
    indication in one table. Replaces 33 separate full-MAF streams. Rows sorted (indication, gene_symbol,
    -hotspot_n_samples) for pushdown."""
    import boto3
    import pyarrow as pa

    ensure_aws_profile()
    annot = _load_barcode_cancer_type()

    s3 = boto3.client("s3")
    click.echo(f"Streaming MC3 from s3://{MC3_S3_BUCKET}/{MC3_S3_KEY} (all cohorts)...", err=True)
    gz = gzip.GzipFile(fileobj=s3.get_object(Bucket=MC3_S3_BUCKET, Key=MC3_S3_KEY)["Body"])

    # per indication: {samples:set, genes:{gene:{mutated:set, hotspots:{hgvs:set}}}}
    per: dict = defaultdict(
        lambda: {"samples": set(), "genes": defaultdict(lambda: {"mutated": set(), "hotspots": defaultdict(set)})}
    )
    n_lines = 0
    rejected_unmapped = 0
    hdr_col_idx = None
    for raw_line in gz:
        n_lines += 1
        if n_lines % 500000 == 0:
            click.echo(f"  Processed {n_lines:,} MAF lines...", err=True)
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
        cancer_type = annot.get(_barcode_to_patient(barcode))
        indication = CANCER_TYPE_TO_INDICATION.get(cancer_type) if cancer_type else None
        if indication is None:
            rejected_unmapped += 1
            continue
        sample = _barcode_to_sample(barcode)
        bucket = per[indication]
        bucket["samples"].add(sample)
        vc = parts[hdr_col_idx["Variant_Classification"]]
        if vc not in NON_SYNONYMOUS_CLASSES:
            continue
        gene = parts[hdr_col_idx["Hugo_Symbol"]]
        if not gene or gene in (".", ""):
            continue
        g = bucket["genes"][gene]
        g["mutated"].add(sample)
        g["hotspots"][parts[hdr_col_idx["HGVSp_Short"]] or "unknown"].add(sample)

    click.echo(
        f"\nMC3 streamed: {n_lines:,} lines; {len(per)} indications; {rejected_unmapped:,} unmapped-cohort lines",
        err=True,
    )
    rows = []
    for indication in sorted(per):
        bucket = per[indication]
        n_total = len(bucket["samples"])
        click.echo(f"  {indication}: {n_total} samples, {len(bucket['genes'])} mutated genes", err=True)
        for gene in sorted(bucket["genes"]):
            gd = bucket["genes"][gene]
            n_mutated = len(gd["mutated"])
            overall_freq = n_mutated / n_total if n_total > 0 else 0.0
            rows.append(
                {
                    "indication": indication,
                    "gene_symbol": gene,
                    "n_samples_in_indication": n_total,
                    "n_samples_mutated": n_mutated,
                    "overall_mutation_frequency": overall_freq,
                    "hotspot_protein_change": None,
                    "hotspot_n_samples": None,
                    "hotspot_frequency": None,
                }
            )
            for hs, hs_samples in gd["hotspots"].items():
                hs_n = len(hs_samples)
                rows.append(
                    {
                        "indication": indication,
                        "gene_symbol": gene,
                        "n_samples_in_indication": n_total,
                        "n_samples_mutated": n_mutated,
                        "overall_mutation_frequency": overall_freq,
                        "hotspot_protein_change": hs,
                        "hotspot_n_samples": hs_n,
                        "hotspot_frequency": hs_n / n_total if n_total > 0 else 0.0,
                    }
                )
    # sort_key = gene_symbol (matches the product manifest + aggregate_indication): per-gene predicate
    # pushdown prunes row-groups on gene_symbol; indication + hotspot rank are secondary.
    rows.sort(key=lambda r: (r["gene_symbol"], r["indication"], -(r["hotspot_n_samples"] or 0)))
    return pa.Table.from_pylist(rows, schema=_output_schema())


def _output_schema() -> "pa.Schema":
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("indication", pa.string()),
            pa.field("gene_symbol", pa.string()),
            pa.field("n_samples_in_indication", pa.int64()),
            pa.field("n_samples_mutated", pa.int64()),
            pa.field("overall_mutation_frequency", pa.float64()),
            pa.field("hotspot_protein_change", pa.string()),
            pa.field("hotspot_n_samples", pa.int64()),
            pa.field("hotspot_frequency", pa.float64()),
        ]
    )


def _per_sample_schema() -> "pa.Schema":
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("sample_id", pa.string()),  # 3-segment PATIENT barcode (joins the assignments shard)
            pa.field("gene_symbol", pa.string()),
            pa.field("protein_change", pa.string()),  # HGVSp_Short (or "unknown")
            pa.field("project", pa.string()),  # TCGA-COAD / TCGA-READ / ...
        ]
    )


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

    ensure_aws_profile()

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
        {"sample_id": p, "gene_symbol": g, "protein_change": hs, "project": proj} for (p, g, hs), proj in seen.items()
    ]
    rows.sort(key=lambda r: (r["gene_symbol"], r["sample_id"]))
    return pa.Table.from_pylist(rows, schema=_per_sample_schema())


# ============================================================================
# FIGURE EMITTERS (hotspot lollipop + driver recurrence context)
# ============================================================================


def emit_hotspot_lollipop(
    hotspot_frequencies: list[dict],
    target: str,
    indication: str,
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
    *,
    top_n: int = 15,
) -> Optional[Path]:
    """Emit a lollipop plot showing top hotspot protein changes and their frequencies.

    Each hotspot is a vertical stem with a circle at the frequency value. Hotspots are
    sorted by frequency descending. Returns the path to the saved SVG, or None if no
    hotspots to plot.

    Args:
        hotspot_frequencies: list of {protein_change, frequency, n_samples} dicts
        target: gene symbol
        indication: indication code (e.g., COADREAD)
        out_path: directory to write figure_hotspot_lollipop.svg
        contracts_root: path to target-contracts repo (for styling)
        top_n: max number of hotspots to display
    """
    if not hotspot_frequencies:
        return None

    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import (
            OKABE_ITO,
            REFLINE_NEUTRAL,
            figure_frame,
        )
    except ImportError:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7.0, 3.5))
        ax.text(0.5, 0.5, "takeda_palette not available", ha="center", va="center", transform=ax.transAxes)
        svg_path = out_path / "figure_hotspot_lollipop.svg"
        fig.savefig(svg_path, bbox_inches="tight")
        plt.close(fig)
        return svg_path

    sorted_hotspots = sorted(hotspot_frequencies, key=lambda h: h.get("frequency", 0) or 0, reverse=True)[:top_n]
    if not sorted_hotspots:
        return None

    n_hotspots = len(sorted_hotspots)
    labels = [h.get("protein_change", "?") for h in sorted_hotspots]
    freqs = [h.get("frequency", 0) or 0 for h in sorted_hotspots]
    n_samples = [h.get("n_samples", 0) or 0 for h in sorted_hotspots]

    max_freq = max(freqs) if freqs else 0.1
    top_hotspot = sorted_hotspots[0] if sorted_hotspots else {}
    top_pct = (top_hotspot.get("frequency", 0) or 0) * 100

    takeaway_text = (
        f"Top hotspot {top_hotspot.get('protein_change', '?')} occurs in {top_pct:.1f}% of {indication} samples "
        f"(n={top_hotspot.get('n_samples', 0)})."
    ) if top_hotspot else None

    svg_path = out_path / "figure_hotspot_lollipop.svg"
    fig_height = max(3.0, 0.25 * n_hotspots + 1.5)

    with figure_frame(
        target,
        indication,
        view="mutation hotspot frequency",
        out_path=svg_path,
        kind="single",
        provenance=f"TCGA MC3 v0.2.8 · {indication}",
        takeaway=takeaway_text,
        figsize=(7.0, fig_height),
        left=0.28,
    ) as F:
        ax = F.ax
        y_pos = range(n_hotspots)

        for i, (freq, n) in enumerate(zip(freqs, n_samples)):
            color = OKABE_ITO[0] if i == 0 else OKABE_ITO[1]
            ax.hlines(y=i, xmin=0, xmax=freq, color=color, linewidth=1.5, zorder=2)
            ax.scatter([freq], [i], s=80, c=color, zorder=3, edgecolors="white", linewidths=0.8)
            ax.annotate(
                f"n={n} ({freq*100:.1f}%)",
                xy=(freq, i),
                xytext=(5, 0),
                textcoords="offset points",
                fontsize=7,
                va="center",
                color="#666666",
            )

        ax.set_yticks(list(y_pos))
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()

        ax.axvline(x=0, **REFLINE_NEUTRAL, zorder=1)
        ax.set_xlim(left=-0.005, right=max_freq * 1.15)
        ax.grid(axis="x", alpha=0.3)

        F.axis_label("x", "Mutation Frequency", "fraction of samples")

    return svg_path



def emit_mutation_frequency_stacked(
    target: str,
    indication: str,
    target_frequency_indication: float,
    indication_gene_frequencies: list[tuple[str, float]],
    target_frequency_pancancer: float,
    pancancer_gene_frequencies: list[tuple[str, float]],
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
    *,
    min_frequency: float = 0.05,
) -> Optional[Path]:
    """Emit a stacked figure with indication-specific (top) and pan-cancer (bottom) mutation frequency.

    Args:
        target: gene symbol
        indication: indication code (e.g., COADREAD)
        target_frequency_indication: target's frequency in the indication
        indication_gene_frequencies: list of (gene, freq) for indication
        target_frequency_pancancer: target's frequency pan-cancer
        pancancer_gene_frequencies: list of (gene, freq) for pan-cancer
        out_path: directory to write figure
        contracts_root: path to target-contracts repo
        min_frequency: minimum frequency threshold (default 5%)
    """
    if not indication_gene_frequencies and not pancancer_gene_frequencies:
        return None

    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import (
            REFLINE_NEUTRAL,
            figure_title,
            provenance_tag,
            takeaway,
        )
    except ImportError:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7.0, 6.0))
        ax.text(0.5, 0.5, "takeda_palette not available", ha="center", va="center", transform=ax.transAxes)
        svg_path = out_path / "figure_mutation_frequency_stacked.svg"
        fig.savefig(svg_path, bbox_inches="tight")
        plt.close(fig)
        return svg_path

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    def filter_and_sort(gene_freqs, target_freq):
        if gene_freqs and isinstance(gene_freqs[0], (list, tuple)):
            pairs = [(g, f) for g, f in gene_freqs if f is not None and f > 0]
        else:
            pairs = [(f"gene_{i}", f) for i, f in enumerate(gene_freqs) if f is not None and f > 0]
        frequent = [(g, f) for g, f in pairs if f >= min_frequency]
        frequent.sort(key=lambda x: x[1])
        return frequent, len(pairs)

    ind_genes, ind_total = filter_and_sort(indication_gene_frequencies, target_frequency_indication)
    pan_genes, pan_total = filter_and_sort(pancancer_gene_frequencies, target_frequency_pancancer)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.0, 7.0))
    fig.subplots_adjust(top=0.88, bottom=0.12, left=0.12, right=0.95, hspace=0.35)

    bar_width = 0.6

    def plot_panel(ax, genes, target_freq, panel_title, total_genes):
        if len(genes) == 0:
            ax.text(0.5, 0.5, f"No genes ≥{min_frequency*100:.0f}%", ha="center", va="center",
                    transform=ax.transAxes, fontsize=10, color="#666666")
            ax.set_xticks([])
            ax.set_title(panel_title, fontsize=10, fontweight="bold", loc="left", color="#33383D")
            return

        x_positions = np.arange(len(genes))
        frequencies = [f for _, f in genes]

        colors = []
        target_in_panel = False
        target_idx = None
        for i, (gene, freq) in enumerate(genes):
            if gene == target or abs(freq - target_freq) < 1e-9:
                colors.append("#B22222")
                target_in_panel = True
                target_idx = i
            else:
                colors.append("#A9C5DB")

        ax.bar(x_positions, frequencies, color=colors, edgecolor="none", width=bar_width, zorder=2)

        for i, (gene, freq) in enumerate(genes):
            is_target_gene = gene == target or abs(freq - target_freq) < 1e-9
            if is_target_gene:
                ax.annotate(
                    f"{gene} ({freq*100:.1f}%)",
                    xy=(i, freq),
                    xytext=(0, 4),
                    textcoords="offset points",
                    fontsize=7,
                    fontweight="bold",
                    color="#B22222",
                    ha="center",
                    va="bottom",
                    rotation=90,
                )
            else:
                ax.annotate(
                    f"{gene} ({freq*100:.1f}%)",
                    xy=(i, freq),
                    xytext=(0, 4),
                    textcoords="offset points",
                    fontsize=5,
                    color="#888888",
                    ha="center",
                    va="bottom",
                    rotation=90,
                )

        if not target_in_panel and target_freq is not None:
            ax.text(
                0.5, 0.85,
                f"{target} ({target_freq*100:.1f}%) — below {min_frequency*100:.0f}% threshold",
                ha="center", va="top", transform=ax.transAxes,
                fontsize=8, fontweight="bold", color="#B22222",
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#FFEEEE", edgecolor="#B22222", linewidth=1),
            )

        ax.axhline(y=min_frequency, **REFLINE_NEUTRAL, zorder=1)
        ax.set_xlim(-0.5, len(genes) - 0.5)
        ax.set_ylim(bottom=0)
        ax.set_xticks([])
        ax.grid(axis="y", alpha=0.3)
        ax.set_ylabel("Frequency", fontsize=9, color="#33383D")
        ax.set_title(f"{panel_title} ({len(genes)} genes ≥{min_frequency*100:.0f}%)",
                     fontsize=10, fontweight="bold", loc="left", color="#33383D")

    plot_panel(ax1, ind_genes, target_frequency_indication, indication, ind_total)
    plot_panel(ax2, pan_genes, target_frequency_pancancer, "Pan-Cancer", pan_total)

    figure_title(fig, target, None, "mutation frequency", y=0.96)
    provenance_tag(fig, f"TCGA MC3 v0.2.8 · genes mutated in ≥{min_frequency*100:.0f}% of samples", y=0.93)

    def get_rank(genes, target_name, target_freq):
        """Get 1-based rank (1 = most frequent) among genes >= threshold."""
        sorted_desc = sorted(genes, key=lambda x: x[1], reverse=True)
        for i, (gene, freq) in enumerate(sorted_desc):
            if gene == target_name or abs(freq - target_freq) < 1e-9:
                return i + 1
        return None

    ind_rank = get_rank(ind_genes, target, target_frequency_indication) if ind_genes else None
    pan_rank = get_rank(pan_genes, target, target_frequency_pancancer) if pan_genes else None

    def ordinal(n):
        if n is None:
            return None
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    if ind_rank and pan_rank:
        take_text = (f"{target} is the {ordinal(ind_rank)} most frequently mutated gene in {indication} "
                     f"and the {ordinal(pan_rank)} most frequently mutated gene pan-cancer.")
    elif ind_rank:
        take_text = (f"{target} is the {ordinal(ind_rank)} most frequently mutated gene in {indication} "
                     f"but is below the {min_frequency*100:.0f}% threshold pan-cancer.")
    elif pan_rank:
        take_text = (f"{target} is the {ordinal(pan_rank)} most frequently mutated gene pan-cancer "
                     f"but is below the {min_frequency*100:.0f}% threshold in {indication}.")
    else:
        take_text = (f"{target} is below the {min_frequency*100:.0f}% mutation frequency threshold "
                     f"in both {indication} and pan-cancer.")
    takeaway(fig, take_text, y=0.02)

    svg_path = out_path / "figure_mutation_frequency_stacked.svg"
    fig.savefig(svg_path)
    plt.close(fig)
    return svg_path


def emit_mutation_frequency_pie(
    target: str,
    indication: str,
    target_frequency_indication: float,
    indication_gene_frequencies: list[tuple[str, float]],
    target_frequency_pancancer: float,
    pancancer_gene_frequencies: list[tuple[str, float]],
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
    *,
    min_frequency: float = 0.05,
    top_n: int = 100,
) -> Optional[Path]:
    """Emit dual pie charts showing mutation frequency in indication vs pan-cancer.

    Two donut-style pie charts side by side: indication (red) on left, pan-cancer
    (black) on right. Captions below show the gene's rank in each context.

    Args:
        target: gene symbol
        indication: indication code (e.g., COADREAD)
        target_frequency_indication: target's frequency in the indication
        indication_gene_frequencies: list of (gene, freq) for indication
        target_frequency_pancancer: target's frequency pan-cancer
        out_path: directory to write figure
        contracts_root: path to target-contracts repo
        min_frequency: minimum frequency threshold (default 5%)
        top_n: number of top genes to display in waterfall (default 500)
    """
    if not indication_gene_frequencies:
        return None

    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import (
            REFLINE_NEUTRAL,
            figure_title,
            provenance_tag,
            takeaway,
        )
    except ImportError:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7.0, 5.0))
        ax.text(0.5, 0.5, "takeda_palette not available", ha="center", va="center", transform=ax.transAxes)
        svg_path = out_path / "figure_mutation_frequency_pie.svg"
        fig.savefig(svg_path, bbox_inches="tight")
        plt.close(fig)
        return svg_path

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    # Filter and sort genes
    if indication_gene_frequencies and isinstance(indication_gene_frequencies[0], (list, tuple)):
        gene_freq_pairs = [(g, f) for g, f in indication_gene_frequencies if f is not None and f > 0]
    else:
        gene_freq_pairs = [(f"gene_{i}", f) for i, f in enumerate(indication_gene_frequencies) if f is not None and f > 0]

    if len(gene_freq_pairs) == 0:
        return None

    # Take top N most frequently mutated genes (no min_frequency filter), sorted ascending for display
    gene_freq_pairs.sort(key=lambda x: x[1], reverse=True)  # Sort descending first
    top_genes = gene_freq_pairs[:top_n]  # Take top N
    top_genes.sort(key=lambda x: x[1])  # Then sort ascending for display

    # Find target in the list
    target_in_list = False
    target_idx = None
    for i, (gene, freq) in enumerate(top_genes):
        if gene == target:
            target_in_list = True
            target_idx = i
            break

    # Create square figure with two pie charts
    fig = plt.figure(figsize=(5.5, 5.0))
    fig.subplots_adjust(top=0.85, bottom=0.15, left=0.10, right=0.90)

    # Two pie chart axes - indication on left, pan-cancer on right
    ax_pie_ind = fig.add_axes([0.08, 0.35, 0.38, 0.50])
    ax_pie_pan = fig.add_axes([0.54, 0.35, 0.38, 0.50])

    # === Draw Pie Charts ===
    # Indication pie chart (red)
    if target_frequency_indication is not None:
        ind_pct = target_frequency_indication * 100
        ind_not_mutated = 100 - ind_pct

        pie_colors_ind = ["#B22222", "#E8E8E8"]
        ax_pie_ind.pie(
            [ind_pct, ind_not_mutated],
            colors=pie_colors_ind,
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1),
        )

        ax_pie_ind.text(
            0, 0,
            f"{ind_pct:.1f}%",
            ha="center", va="center",
            fontsize=12, fontweight="bold", color="#B22222",
        )

        ax_pie_ind.text(
            0, -1.1,
            f"{indication}",
            ha="center", va="top",
            fontsize=9, fontweight="bold", color="#B22222",
        )

        ax_pie_ind.set_aspect("equal")

    # Pan-cancer pie chart (black)
    if target_frequency_pancancer is not None:
        pan_pct = target_frequency_pancancer * 100
        pan_not_mutated = 100 - pan_pct

        pie_colors_pan = ["#333333", "#E8E8E8"]
        ax_pie_pan.pie(
            [pan_pct, pan_not_mutated],
            colors=pie_colors_pan,
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1),
        )

        ax_pie_pan.text(
            0, 0,
            f"{pan_pct:.1f}%",
            ha="center", va="center",
            fontsize=12, fontweight="bold", color="#333333",
        )

        ax_pie_pan.text(
            0, -1.1,
            f"Pan-Cancer",
            ha="center", va="top",
            fontsize=9, fontweight="bold", color="#333333",
        )

        ax_pie_pan.set_aspect("equal")

    # === Title and annotations ===
    figure_title(fig, target, None, "mutation frequency", y=0.94)
    provenance_tag(fig, "TCGA MC3 v0.2.8", y=0.90)

    # Helper for ordinal numbers
    def ordinal(n):
        if n is None:
            return None
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    # Calculate indication rank
    all_sorted_ind = sorted(gene_freq_pairs, key=lambda x: x[1], reverse=True)
    ind_rank = None
    for i, (gene, freq) in enumerate(all_sorted_ind):
        if gene == target:
            ind_rank = i + 1
            break

    # Calculate pan-cancer rank
    pan_rank = None
    if pancancer_gene_frequencies:
        if isinstance(pancancer_gene_frequencies[0], (list, tuple)):
            pan_pairs = [(g, f) for g, f in pancancer_gene_frequencies if f is not None and f > 0]
        else:
            pan_pairs = [(f"gene_{i}", f) for i, f in enumerate(pancancer_gene_frequencies) if f is not None and f > 0]
        all_sorted_pan = sorted(pan_pairs, key=lambda x: x[1], reverse=True)
        for i, (gene, freq) in enumerate(all_sorted_pan):
            if gene == target:
                pan_rank = i + 1
                break

    # Caption below pie charts (moved closer to charts)
    caption_y = 0.28
    line_spacing = 0.05

    # Indication caption - rank highlighted in red bold
    if ind_rank:
        fig.text(0.5, caption_y,
                 f"{target} is the {ordinal(ind_rank)} most frequently mutated gene in {indication}",
                 ha="center", va="top", fontsize=10, color="#B22222", fontweight="bold")
    else:
        fig.text(0.5, caption_y,
                 f"{target} mutation frequency in {indication}: {target_frequency_indication*100:.1f}%",
                 ha="center", va="top", fontsize=10, color="#B22222", fontweight="bold")

    # Pan-cancer caption - rank highlighted in black bold
    if pan_rank:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} is the {ordinal(pan_rank)} most frequently mutated gene pan-cancer",
                 ha="center", va="top", fontsize=10, color="#333333", fontweight="bold")
    else:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} mutation frequency pan-cancer: {target_frequency_pancancer*100:.1f}%",
                 ha="center", va="top", fontsize=10, color="#333333", fontweight="bold")

    svg_path = out_path / "figure_mutation_frequency_pie.svg"
    fig.savefig(svg_path)
    plt.close(fig)
    return svg_path


def emit_plot_data(
    hotspot_frequencies: list[dict],
    target: str,
    indication: str,
    overall_frequency: float,
    all_gene_frequencies: list,
    out_path: Path,
) -> Path:
    """Emit plot_data.parquet for offline figure re-rendering.

    Persists the data needed by emit_hotspot_lollipop and emit_driver_recurrence_context
    so figures can be regenerated without re-querying the source data.

    Args:
        all_gene_frequencies: list of (gene_symbol, frequency) tuples OR list of floats
    """
    import pandas as pd

    rows = []
    for h in (hotspot_frequencies or []):
        rows.append({
            "target": target,
            "indication": indication,
            "gene_symbol": target,
            "protein_change": h.get("protein_change"),
            "frequency": h.get("frequency"),
            "n_samples": h.get("n_samples"),
            "row_type": "hotspot",
        })

    rows.append({
        "target": target,
        "indication": indication,
        "gene_symbol": target,
        "protein_change": None,
        "frequency": overall_frequency,
        "n_samples": None,
        "row_type": "target_summary",
    })

    for item in (all_gene_frequencies or []):
        if isinstance(item, (list, tuple)):
            gene_name, freq = item
        else:
            gene_name, freq = None, item
        rows.append({
            "target": target,
            "indication": indication,
            "gene_symbol": gene_name,
            "protein_change": None,
            "frequency": freq,
            "n_samples": None,
            "row_type": "all_genes_context",
        })

    df = pd.DataFrame(rows)
    parquet_path = out_path / "plot_data.parquet"
    df.to_parquet(parquet_path, index=False)
    return parquet_path


@click.command()
@click.option("--indication", default=None, help="Indication code (COADREAD, PDAC, NSCLC, GC). Omit with --all.")
@click.option(
    "--all",
    "all_cohorts",
    is_flag=True,
    default=False,
    help="Build the ALL-COHORT aggregate in ONE MC3 pass (all 33 TCGA cohorts, framework-canonical "
    "indications) — the full tcga-mc3-hotspot-frequency-v1 product. Ignores --indication/--per-sample.",
)
@click.option(
    "--out", required=True, type=click.Path(dir_okay=False, path_type=Path), help="Output Parquet path (local)."
)
@click.option(
    "--per-sample",
    is_flag=True,
    default=False,
    help="Emit the PER-SAMPLE non-synonymous MAF (sample_id/gene_symbol/protein_change/"
    "project) instead of the per-gene hotspot aggregate. This is the substrate the "
    "subgroup-stratified-mutation-frequency panorama recomputes per-stratum from; "
    "sample_id is the 3-segment PATIENT barcode so it joins the assignments shards.",
)
def main(indication: str | None, all_cohorts: bool, out: Path, per_sample: bool) -> int:
    import pyarrow.parquet as pq

    if all_cohorts:
        table = aggregate_all_cohorts()
        row_group = 1024
    elif per_sample:
        if not indication:
            raise click.UsageError("--per-sample requires --indication")
        table = per_sample_maf(indication)
        row_group = 8192  # narrow 4-col rows; larger groups are fine
    else:
        if not indication:
            raise click.UsageError("pass --indication or --all")
        table = aggregate_indication(indication)
        row_group = 1024
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="snappy", row_group_size=row_group)
    click.echo(f"\nWrote {table.num_rows:,} rows → {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
