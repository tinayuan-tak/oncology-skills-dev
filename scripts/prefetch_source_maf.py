#!/usr/bin/env python3
"""prefetch_source_maf.py — pull + indication-filter + normalize a mutation
source into the per-indication MAF parquet the subgroup_assigner_maf_filter
method reads from cache.

Codifies the ad-hoc pull/filter/parquet steps used to land the MC3 + GENIE
CRC shards (2026-07-15) into a reusable, source-parameterized driver.

Supported sources (--source):
  tcga_mc3            — Synapse MC3 pan-cancer MAF (mc3.v0.2.8.PUBLIC.maf.gz).
                        Indication-filtered via the TCGA marker-paper patient
                        list (patient barcode intersection). ~750 MB pull.
  genie_public_v19    — GENIE public v19 data_mutations_extended.txt (1.12 GB).
                        Indication-filtered via data_clinical_sample.txt
                        CANCER_TYPE. ~271K samples pan-cancer → per-indication.
  genie_bpc_crc       — GENIE-BPC CRC v2.0 curated cohort MAF (7.7 MB).
                        Already CRC-only; no filter needed. Carries treatment
                        metadata in companion regimen files (not pulled here —
                        see prefetch_genie_bpc_regimens.py for LOT strata).
  depmap_somatic      — DepMap OmicsSomaticMutationsMAF.maf (190 MB).
                        Indication-filtered via Model.csv OncotreeLineage.

Output: ~/.cache/framework-<source-cache-dir>/<indication_lower>-<tag>.parquet
with columns normalized to the resolver convention:
  sample_id, patient_id, source_native_id, gene_symbol, protein_change, effect

Invocation:
    python -m scripts.prefetch_source_maf --source genie_public_v19 --indication COADREAD
    python -m scripts.prefetch_source_maf --source tcga_mc3 --indication COADREAD
    python -m scripts.prefetch_source_maf --source depmap_somatic --indication COADREAD

    DRY_RUN=1 python -m scripts.prefetch_source_maf --source genie_public_v19 --indication COADREAD

DRY_RUN=1 prints the plan (S3 keys, filter strategy, output path) without
pulling or writing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import click


# --- Source configuration table --------------------------------------------
# Each source declares: S3 keys, the cache dir, the output-parquet tag, the
# MAF column names to normalize from, and the filter strategy.

@dataclass(frozen=True)
class SourceConfig:
    cache_dir: str                      # ~/.cache/framework-<cache_dir>/
    maf_s3_key: str                     # S3 key of the MAF file
    maf_filename: str                   # local filename for the MAF
    out_tag: str                        # output parquet: {indication}-{out_tag}.parquet
    gene_col: str                       # source column → gene_symbol
    protein_col: str                    # source column → protein_change
    effect_col: str                     # source column → effect
    sample_col: str                     # source column → sample_id
    filter_strategy: str                # 'tcga_patient_list' | 'genie_cancer_type' | 'depmap_lineage' | 'none'
    comment_char: str = ""              # '#' for cBioPortal-style headers, '' otherwise


SOURCE_CONFIGS = {
    "tcga_mc3": SourceConfig(
        cache_dir="tcga-mc3-public",
        maf_s3_key="data-catalog/sources/synapse/tcga-mc3-public/mc3.v0.2.8.PUBLIC.maf.gz",
        maf_filename="mc3.v0.2.8.PUBLIC.maf.gz",
        out_tag="mc3",
        # Output goes to the gdc-pancohort-somatic cache dir the assigner reads
        gene_col="Hugo_Symbol", protein_col="HGVSp_Short",
        effect_col="Variant_Classification", sample_col="Tumor_Sample_Barcode",
        filter_strategy="tcga_patient_list",
    ),
    "genie_public_v19": SourceConfig(
        cache_dir="genie-public-v19",
        maf_s3_key="data-catalog/sources/synapse/genie-public-v19-0/data_mutations_extended.txt",
        maf_filename="data_mutations_extended.txt",
        out_tag="genie-maf",
        gene_col="Hugo_Symbol", protein_col="HGVSp_Short",
        effect_col="Variant_Classification", sample_col="Tumor_Sample_Barcode",
        filter_strategy="genie_cancer_type",
    ),
    "genie_bpc_crc": SourceConfig(
        cache_dir="genie-bpc-crc-v2",
        maf_s3_key="data-catalog/sources/synapse/genie-bpc-crc-v2.0/cBioPortal_files/data_mutations_extended.txt",
        maf_filename="data_mutations_extended.txt",
        out_tag="genie-bpc-maf",
        gene_col="Hugo_Symbol", protein_col="HGVSp_Short",
        effect_col="Variant_Classification", sample_col="Tumor_Sample_Barcode",
        filter_strategy="none",   # BPC-CRC is already CRC-only
    ),
    "depmap_somatic": SourceConfig(
        cache_dir="depmap-26q1",
        maf_s3_key="data-catalog/sources/depmap-consortium/dmc-26q1/OmicsSomaticMutationsMAF.maf",
        maf_filename="OmicsSomaticMutationsMAF.maf",
        out_tag="depmap-maf",
        gene_col="Hugo_Symbol", protein_col="Protein_Change",   # DepMap uses Protein_Change
        effect_col="Variant_Classification", sample_col="ModelID",
        filter_strategy="depmap_lineage",
    ),
}

S3_BUCKET = "onc-compbio"

# Indication → filter parameters per strategy.
GENIE_CANCER_TYPE = {"COADREAD": "Colorectal Cancer"}
DEPMAP_LINEAGE = {"COADREAD": "Bowel"}


def _log(msg: str) -> None:
    click.echo(f"[prefetch-source-maf] {msg}", err=True)


def _cache_path(cfg: SourceConfig, filename: str) -> Path:
    return Path.home() / ".cache" / f"framework-{cfg.cache_dir}" / filename


def _s3_download(key: str, dest: Path, dry_run: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _log(f"cache hit: {dest} (skip download)")
        return
    if dry_run:
        _log(f"DRY_RUN: would download s3://{S3_BUCKET}/{key} → {dest}")
        return
    _log(f"downloading s3://{S3_BUCKET}/{key} → {dest}")
    r = subprocess.run(
        ["aws", "s3", "cp", f"s3://{S3_BUCKET}/{key}", str(dest), "--no-progress"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        _log(f"download FAILED: {r.stderr}")
        sys.exit(r.returncode)


def _filter_samples(cfg: SourceConfig, indication: str, dry_run: bool):
    """Return the set of sample IDs to keep, or None for no-filter sources."""
    import pandas as pd

    if cfg.filter_strategy == "none":
        return None

    if cfg.filter_strategy == "tcga_patient_list":
        # Intersect with TCGA marker-paper patient list for the indication
        mp = Path.home() / ".cache" / "framework-tcga-marker-paper" / indication.lower() / "subtypes.csv"
        if not mp.exists():
            _log(f"WARNING: TCGA marker-paper file for {indication} not at {mp}; "
                 f"cannot build patient list. Run the directly-tagged prefetch first.")
            if dry_run:
                return set()
            sys.exit(1)
        patients = set(pd.read_csv(mp)["patient"])
        _log(f"TCGA patient list for {indication}: {len(patients)} patients")
        return patients

    if cfg.filter_strategy == "genie_cancer_type":
        clin = _cache_path(cfg, "data_clinical_sample.txt")
        _s3_download(
            "data-catalog/sources/synapse/genie-public-v19-0/data_clinical_sample.txt",
            clin, dry_run,
        )
        if dry_run and not clin.exists():
            return set()
        df = pd.read_csv(clin, sep="\t", comment="#")
        cancer_type = GENIE_CANCER_TYPE.get(indication)
        if not cancer_type:
            _log(f"No GENIE CANCER_TYPE mapping for {indication}; add to GENIE_CANCER_TYPE.")
            sys.exit(1)
        samples = set(df[df["CANCER_TYPE"] == cancer_type]["SAMPLE_ID"])
        _log(f"GENIE {cancer_type} samples: {len(samples):,}")
        return samples

    if cfg.filter_strategy == "depmap_lineage":
        model = _cache_path(cfg, "Model.csv")
        _s3_download(
            "data-catalog/sources/depmap-consortium/dmc-26q1/Model.csv", model, dry_run,
        )
        if dry_run and not model.exists():
            return set()
        df = pd.read_csv(model)
        lineage = DEPMAP_LINEAGE.get(indication)
        if not lineage:
            _log(f"No DepMap lineage mapping for {indication}; add to DEPMAP_LINEAGE.")
            sys.exit(1)
        samples = set(df[df["OncotreeLineage"] == lineage]["ModelID"])
        _log(f"DepMap {lineage} cell lines: {len(samples):,}")
        return samples

    raise ValueError(f"Unknown filter_strategy: {cfg.filter_strategy}")


@click.command()
@click.option("--source", required=True, type=click.Choice(list(SOURCE_CONFIGS)))
@click.option("--indication", required=True)
def main(source: str, indication: str) -> int:
    """Prefetch + filter + normalize a mutation source into a per-indication MAF parquet."""
    import pandas as pd

    dry_run = bool(os.environ.get("DRY_RUN"))
    cfg = SOURCE_CONFIGS[source]

    out_path = _cache_path(
        # tcga_mc3 output lands in the gdc-pancohort cache dir the assigner reads
        SourceConfig(**{**cfg.__dict__, "cache_dir": "gdc-pancohort-somatic"}) if source == "tcga_mc3" else cfg,
        f"{indication.lower()}-{cfg.out_tag}.parquet",
    )

    _log(f"=== prefetch {source} × {indication} ===")
    _log(f"  MAF s3 key:    {cfg.maf_s3_key}")
    _log(f"  filter:        {cfg.filter_strategy}")
    _log(f"  output:        {out_path}")

    # 1. Determine sample filter
    keep_samples = _filter_samples(cfg, indication, dry_run)

    # 2. Download the MAF
    maf_local = _cache_path(cfg, cfg.maf_filename)
    _s3_download(cfg.maf_s3_key, maf_local, dry_run)

    if dry_run:
        _log("DRY_RUN: skipping MAF parse + parquet write")
        return 0

    # 3. Load MAF (only the columns we need)
    usecols = [cfg.gene_col, cfg.protein_col, cfg.effect_col, cfg.sample_col]
    read_kwargs = {"sep": "\t", "usecols": usecols, "low_memory": False}
    if cfg.comment_char:
        read_kwargs["comment"] = cfg.comment_char
    if cfg.maf_filename.endswith(".gz"):
        read_kwargs["compression"] = "gzip"
    _log(f"loading MAF ({maf_local.stat().st_size / 1e6:.0f} MB)...")
    maf = pd.read_csv(maf_local, **read_kwargs)
    _log(f"  full MAF: {maf.shape}")

    # 4. Filter to indication samples
    if keep_samples is not None:
        # For TCGA MC3: match on patient barcode (truncate aliquot to 12 chars)
        if cfg.filter_strategy == "tcga_patient_list":
            maf["_patient"] = maf[cfg.sample_col].str[:12]
            maf = maf[maf["_patient"].isin(keep_samples)]
            maf = maf.drop(columns=["_patient"])
        else:
            maf = maf[maf[cfg.sample_col].isin(keep_samples)]
    _log(f"  filtered MAF: {len(maf):,} rows, {maf[cfg.sample_col].nunique():,} unique samples")

    # 5. Normalize columns to resolver-product convention
    out = maf.rename(columns={
        cfg.gene_col: "gene_symbol",
        cfg.protein_col: "protein_change",
        cfg.effect_col: "effect",
        cfg.sample_col: "sample_id",
    })
    out["source_native_id"] = out["sample_id"]
    # patient_id: TCGA truncates to barcode; others null
    if cfg.filter_strategy == "tcga_patient_list":
        out["patient_id"] = out["sample_id"].str[:12]
        out["sample_id"] = out["patient_id"]   # marker-paper is patient-level; align
        out["source_native_id"] = out["source_native_id"]  # keep aliquot as native
    else:
        out["patient_id"] = None

    # 6. Write parquet
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    _log(f"wrote {out_path}: {len(out):,} rows, {out_path.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
