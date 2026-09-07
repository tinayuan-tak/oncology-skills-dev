#!/usr/bin/env python3
"""pancan_mutation_ccf CLI — aggregate TCGA-MC3 mutations into per-(gene, indication) CLONALITY.

Streams MC3 (VAF), joins the PanCanAtlas ABSOLUTE per-sample purity table, computes each mutation's
cancer-cell fraction (ccf = VAF * 2 / purity; diploid CN=2, multiplicity=1 — see __init__ for the
validation + the v2 local-CN refinement), and aggregates per gene into a clonality signal. Runs ONCE
per (indication) and materializes a small parquet (like gdc_somatic_hotspot); the read side + card
consume it per (gene, indication).

Usage:
    pixi run python -m methods.pancan_mutation_ccf.cli --indication COADREAD --out /tmp/coadread_ccf.parquet
"""

from __future__ import annotations

import gzip
import io
import statistics as _st
from collections import defaultdict

import click

# REUSE the single-sourced TSS -> TCGA-project -> indication filter + non-synonymous set.
from methods.gdc_somatic_hotspot.cli import (
    INDICATION_TO_TCGA_PROJECTS,
    TSS_CODE_TO_TCGA_PROJECT,
    NON_SYNONYMOUS_CLASSES,
)

MC3_S3_BUCKET = "onc-compbio"
MC3_S3_KEY = "data-catalog/sources/synapse/tcga-mc3-public/mc3.v0.2.8.PUBLIC.maf.gz"
ABS_S3_KEY = (
    "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/TCGA_mastercalls.abs_tables_JSedit.fixed.txt"
)

MIN_DEPTH = 10  # drop low-coverage calls (VAF unreliable)
CLONAL_CCF_CUT = 0.8  # a mutation is clonal if ccf >= this (standard threshold)
MIN_MUTANT_SAMPLES = 10  # below this the clonality fraction is not reported (insufficient)
CCF_CAP = 1.5  # cap ccf (purity/CN noise can push it >1)


from methods.target_id_sidecar import ensure_aws_profile


def load_purity() -> dict:
    """{sample-level barcode (first 15 chars) -> ABSOLUTE purity}."""
    import boto3

    ensure_aws_profile()
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=MC3_S3_BUCKET, Key=ABS_S3_KEY)
    text = obj["Body"].read().decode("utf-8", errors="replace")
    pur: dict = {}
    rd = io.StringIO(text)
    header = rd.readline().rstrip("\n").split("\t")
    try:
        i_array = header.index("array")
        i_pur = header.index("purity")
    except ValueError as e:
        raise RuntimeError(f"abs_tables missing expected column: {e}")
    for line in rd:
        cols = line.rstrip("\n").split("\t")
        if len(cols) <= max(i_array, i_pur):
            continue
        s = cols[i_array][:15]
        try:
            p = float(cols[i_pur])
        except ValueError:
            continue
        if s and 0.0 < p <= 1.0:
            pur[s] = p
    return pur


def aggregate_clonality(indication: str) -> list[dict]:
    """Stream MC3 for the indication's TCGA projects, compute per-mutation ccf, aggregate per gene.
    Returns a list of {indication, gene_symbol, n_mutant_samples, clonal_fraction, median_ccf,
    clonality_class, evidence_tier} dicts."""
    import boto3

    ensure_aws_profile()

    projects = set(INDICATION_TO_TCGA_PROJECTS.get(indication, []))
    if not projects:
        return []
    purity = load_purity()

    s3 = boto3.client("s3")
    click.echo(f"Streaming MC3 for {indication} {sorted(projects)} ...", err=True)
    obj = s3.get_object(Bucket=MC3_S3_BUCKET, Key=MC3_S3_KEY)
    gz = gzip.GzipFile(fileobj=obj["Body"])

    idx = None
    # per (patient, gene) keep the MAX ccf (the clonal-most call) — one call per patient-gene.
    patient_gene_ccf: dict = {}
    n_lines = 0
    for raw in gz:
        n_lines += 1
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if idx is None:
            try:
                idx = {
                    c: cols.index(c)
                    for c in ("Hugo_Symbol", "Tumor_Sample_Barcode", "t_depth", "t_alt_count", "Variant_Classification")
                }
            except ValueError as e:
                raise RuntimeError(f"MC3 header missing required column: {e}")
            continue
        if cols[idx["Variant_Classification"]] not in NON_SYNONYMOUS_CLASSES:
            continue
        bc = cols[idx["Tumor_Sample_Barcode"]]
        # TSS code = 2nd barcode segment (TCGA-XX-...). Filter to this indication's projects.
        seg = bc.split("-")
        if len(seg) < 2 or TSS_CODE_TO_TCGA_PROJECT.get(seg[1]) not in projects:
            continue
        sample15 = bc[:15]
        p = purity.get(sample15)
        if p is None:
            continue
        try:
            depth = float(cols[idx["t_depth"]])
            alt = float(cols[idx["t_alt_count"]])
        except ValueError:
            continue
        if depth < MIN_DEPTH:
            continue
        vaf = alt / depth
        ccf = min(vaf * 2.0 / p, CCF_CAP)  # diploid CN=2, multiplicity=1
        patient = "-".join(seg[:3])  # patient-level dedup (TCGA-XX-XXXX)
        gene = cols[idx["Hugo_Symbol"]]
        key = (patient, gene)
        if ccf > patient_gene_ccf.get(key, -1.0):
            patient_gene_ccf[key] = ccf

    click.echo(f"MC3 streamed: {n_lines:,} lines; {len(patient_gene_ccf):,} (patient,gene) calls in scope", err=True)

    by_gene: dict = defaultdict(list)
    for (patient, gene), ccf in patient_gene_ccf.items():
        by_gene[gene].append(ccf)

    rows: list[dict] = []
    for gene, ccfs in by_gene.items():
        n = len(ccfs)
        if n < MIN_MUTANT_SAMPLES:
            cls, clonal_frac, med = "insufficient", None, None
        else:
            clonal_frac = round(sum(1 for c in ccfs if c >= CLONAL_CCF_CUT) / n, 4)
            med = round(_st.median(ccfs), 4)
            cls = (
                "predominantly_clonal"
                if clonal_frac >= 0.7
                else "mixed_clonality"
                if clonal_frac >= 0.4
                else "predominantly_subclonal"
            )
        rows.append(
            {
                "indication": indication,
                "gene_symbol": gene,
                "n_mutant_samples": n,
                "clonal_fraction": clonal_frac,
                "median_ccf": med,
                "clonality_class": cls,
                "evidence_tier": "inferred_diploid",
            }
        )
    rows.sort(key=lambda r: (-(r["n_mutant_samples"]), r["gene_symbol"]))
    return rows


@click.command()
@click.option("--indication", required=True, help="Framework indication code (e.g. COADREAD).")
@click.option("--out", required=True, type=click.Path(), help="Output parquet path.")
def main(indication: str, out: str):
    rows = aggregate_clonality(indication)
    if not rows:
        click.echo(f"No TCGA projects mapped for indication {indication!r} — empty product.", err=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = (
        pa.Table.from_pylist(rows)
        if rows
        else pa.table(
            {
                "indication": [],
                "gene_symbol": [],
                "n_mutant_samples": [],
                "clonal_fraction": [],
                "median_ccf": [],
                "clonality_class": [],
                "evidence_tier": [],
            }
        )
    )
    pq.write_table(table, out)
    click.echo(f"wrote {len(rows)} gene rows -> {out}")


if __name__ == "__main__":
    main()
