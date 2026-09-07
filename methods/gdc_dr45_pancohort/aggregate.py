"""gdc_dr45_pancohort.aggregate — manifest-driven per-aliquot MAF aggregator.

Drives off the gdc-pancohort-somatic-dr45-0 manifest file list (each entry pre-tagged with
project_id / case_id / sample_id / tumor-vs-normal in its description), so there is NO barcode
parsing — the catalog already labels every file. For a program, we stream each TUMOR MAF.gz,
collect non-synonymous (gene → set of mutated cases) + (gene → codon → set of cases), then emit
the per-gene frequency aggregate and the per-(case, gene, protein_change) rows.

Denominator = distinct TUMOR case_id in the program (dedups multi-aliquot cases to the patient).
"""

from __future__ import annotations

import gzip
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

import click

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DR45_MANIFEST = "gdc-pancohort-somatic-dr45-0"
DR45_S3_PREFIX = "data-catalog/sources/gdc/pancohort-somatic-dr45.0"

# Same non-synonymous filter as gdc_somatic_hotspot (GDC MAF v2 Variant_Classification vocab).
NON_SYNONYMOUS_CLASSES = {
    "Missense_Mutation",
    "Nonsense_Mutation",
    "Frame_Shift_Ins",
    "Frame_Shift_Del",
    "In_Frame_Ins",
    "In_Frame_Del",
    "Splice_Site",
    "Nonstop_Mutation",
    "Translation_Start_Site",
}


from methods.target_id_sidecar import ensure_aws_profile


def _boto3_client():
    import boto3

    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


def _load_manifest_files(program: str, data_catalog_repo: Optional[Path] = None) -> list[dict]:
    """Return the manifest file entries for a program's TUMOR MAFs (description names tumor).
    Manifest-driven: no barcode parsing — case_id/sample_id/project_id are pre-tagged."""
    import yaml

    repo = (
        Path(data_catalog_repo)
        if data_catalog_repo
        else Path.home() / "rnd-computational-biology-oncology-data-catalog"
    )
    mpath = repo / "manifests" / "sources" / f"{DR45_MANIFEST}.yaml"
    m = yaml.safe_load(mpath.read_text())
    out = []
    for f in m.get("files", []):
        if f.get("project_id") != program:
            continue
        if "tumor" not in (f.get("description") or "").lower():
            continue  # tumor samples only — normals/other are not a mutation denominator
        out.append(f)
    return out


def _stream_maf_genes(s3, key: str) -> list[tuple[str, str, str]]:
    """Stream one per-aliquot MAF.gz → list of (gene, protein_change, variant_class) for
    non-synonymous coding rows. hdr-indexed (GDC MAF v2)."""
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
    gz = gzip.GzipFile(fileobj=obj["Body"])
    rows: list[tuple[str, str, str]] = []
    hdr = None
    for raw in gz:
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if hdr is None:
            try:
                hdr = {c: parts.index(c) for c in ("Hugo_Symbol", "Variant_Classification", "HGVSp_Short")}
            except ValueError as e:
                raise RuntimeError(f"DR45 MAF {key} missing column: {e}")
            continue
        if len(parts) <= max(hdr.values()):
            continue
        vc = parts[hdr["Variant_Classification"]]
        if vc not in NON_SYNONYMOUS_CLASSES:
            continue
        gene = parts[hdr["Hugo_Symbol"]]
        if not gene or gene in (".", ""):
            continue
        hgvs = parts[hdr["HGVSp_Short"]] or "unknown"
        rows.append((gene, hgvs, vc))
    return rows


def _collect(program: str, data_catalog_repo: Optional[Path] = None, _max_files: Optional[int] = None):
    """Stream all tumor MAFs for a program → (n_cases, gene_data). gene_data[gene] =
    {mutated_cases: set, hotspots: {hgvs: set(cases)}}. Deduped to case_id (patient grain)."""
    ensure_aws_profile()
    s3 = _boto3_client()
    files = _load_manifest_files(program, data_catalog_repo)
    if _max_files:
        files = files[:_max_files]
    cases: set = set()
    gene_data: dict = defaultdict(lambda: {"mutated_cases": set(), "hotspots": defaultdict(set)})
    for f in files:
        case = f.get("case_id")
        cases.add(case)
        key = f"{DR45_S3_PREFIX}/{f['path']}"
        for gene, hgvs, _vc in _stream_maf_genes(s3, key):
            gene_data[gene]["mutated_cases"].add(case)
            gene_data[gene]["hotspots"][hgvs].add(case)
    return len(cases), gene_data


def aggregate_program(
    program: str, data_catalog_repo: Optional[Path] = None, _max_files: Optional[int] = None
) -> "object":
    """Per-gene frequency + hotspot aggregate for a DR45 program, in the SAME schema as
    gdc_somatic_hotspot._output_schema (indication/gene_symbol/n_samples_in_indication/
    n_samples_mutated/overall_mutation_frequency/hotspot_protein_change/hotspot_n_samples/
    hotspot_frequency), so read_hotspot_summary can consume it unchanged."""
    import pyarrow as pa

    indication = _resolve_indication(program)
    n_total, gene_data = _collect(program, data_catalog_repo, _max_files)
    rows = []
    for gene in sorted(gene_data):
        gd = gene_data[gene]
        n_mut = len(gd["mutated_cases"])
        freq = n_mut / n_total if n_total else 0.0
        rows.append(
            {
                "indication": indication,
                "gene_symbol": gene,
                "n_samples_in_indication": n_total,
                "n_samples_mutated": n_mut,
                "overall_mutation_frequency": freq,
                "hotspot_protein_change": None,
                "hotspot_n_samples": None,
                "hotspot_frequency": None,
            }
        )
        for hs, hs_cases in gd["hotspots"].items():
            hn = len(hs_cases)
            rows.append(
                {
                    "indication": indication,
                    "gene_symbol": gene,
                    "n_samples_in_indication": n_total,
                    "n_samples_mutated": n_mut,
                    "overall_mutation_frequency": freq,
                    "hotspot_protein_change": hs,
                    "hotspot_n_samples": hn,
                    "hotspot_frequency": hn / n_total if n_total else 0.0,
                }
            )
    rows.sort(key=lambda r: (r["gene_symbol"], -(r["hotspot_n_samples"] or 0)))
    return pa.Table.from_pylist(rows, schema=_agg_schema())


def _resolve_indication(program: str) -> str:
    from methods.gdc_dr45_pancohort import PROGRAM_TO_INDICATION

    ind = PROGRAM_TO_INDICATION.get(program)
    if ind is None:
        raise ValueError(
            f"program {program!r} has no PROGRAM_TO_INDICATION mapping "
            f"(only whole-program-single-disease programs are wired; "
            f"multi-disease programs like CPTAC-3 need a per-case disease join)"
        )
    return ind


def _agg_schema():
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


@click.command()
@click.option("--program", required=True, help="DR45 project_id (e.g. ALCHEMIST-ALCH).")
@click.option("--out", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--max-files", default=None, type=int, help="cap files (smoke/testing).")
def main(program: str, out: Path, max_files: Optional[int]) -> int:
    import pyarrow.parquet as pq

    table = aggregate_program(program, _max_files=max_files)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="snappy", row_group_size=1024)
    click.echo(f"\nWrote {table.num_rows:,} rows → {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
