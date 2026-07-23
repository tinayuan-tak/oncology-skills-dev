#!/usr/bin/env python3
"""prefetch_marker_paper.py — stage the TCGA marker-paper subtype CSV the
subgroup_assigner_directly_tagged method reads from cache, composing
multi-histology indications from their per-cohort files.

Codifies the marker-paper staging that was previously ad-hoc. The MAF side has
prefetch_source_maf.py; this is its directly-tagged (Modality A) counterpart.

Why composition matters (NSCLC): the per-cohort marker-paper CSVs
(tcga_subtype_LUAD.csv, tcga_subtype_LUSC.csv) carry NO histology column —
histology is IMPLICIT in which cohort file a patient came from. NSCLC =
LUAD (adenocarcinoma) + LUSC (squamous). This script concatenates the cohort
files and adds a derived `histology` column from cohort provenance, so the
catalog's `clinical.histology == 'adenocarcinoma'` / `'squamous_cell_carcinoma'`
rules can fire. Single-histology indications (COADREAD → tcga_subtype_CRC.csv)
pass through unchanged.

  NOTE (sourcing upgrade path): the cross-indication audit (data-catalog PR #175)
  identifies gdc-pancanatlas-clinical-2018 as the cleaner long-term histology
  source. This cohort-provenance composition needs NO new ingestion and is the
  interim source; a future revision can repoint histology at the clinical manifest.

Output: ~/.cache/framework-tcga-marker-paper/{indication_lower}/subtypes.csv
with a `patient` column (the directly_tagged loader's join key) + the union of
per-cohort columns + `histology` for multi-cohort indications.

Invocation:
    python -m scripts.prefetch_marker_paper --indication NSCLC
    python -m scripts.prefetch_marker_paper --indication COADREAD
    DRY_RUN=1 python -m scripts.prefetch_marker_paper --indication NSCLC
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

S3_BUCKET = "onc-compbio"
S3_PREFIX = "data-catalog/sources/tcga-marker-papers/subtypes-2018"

# Indication → list of (marker-paper cohort file, histology label). Multi-entry
# indications are composed with a derived histology column; single-entry ones
# pass through (histology label is None → no column added).
INDICATION_COHORTS: dict[str, list[tuple[str, str | None]]] = {
    "COADREAD": [("tcga_subtype_CRC.csv", None)],
    "NSCLC": [
        ("tcga_subtype_LUAD.csv", "adenocarcinoma"),
        ("tcga_subtype_LUSC.csv", "squamous_cell_carcinoma"),
    ],
    "HNSC": [("tcga_subtype_HNSC.csv", None)],
    "STAD": [("tcga_subtype_STAD.csv", None)],
    "PAAD": [("tcga_subtype_PAAD.csv", None)],
}

# The per-cohort marker-paper CSVs carry only data-availability flags for some
# indications (HNSC/STAD/PAAD), NOT the published molecular subtype. Those live
# in the PanCanAtlas curated subtype table (pancan_curated.csv, Subtype_Selected,
# e.g. 'HNSC.Basal'). For indications listed here, join Subtype_Selected onto the
# marker-paper frame as a named column, stripping the '{CANCER}.' prefix so the
# value matches the catalog rule (clinical.hnsc_bass_subtype == 'Basal').
_PANCAN_CURATED_FILE = "pancan_atlas_subtypes_curated.csv"

# indication → (output column name, cancer.type filter, strip_prefix)
INDICATION_SUBTYPE_ENRICH: dict[str, tuple[str, str, str]] = {
    "HNSC": ("hnsc_bass_subtype", "HNSC", "HNSC."),
}

# Clinical fields (HPV status, anatomic site) are NOT in the marker-paper CSVs;
# they live in the PanCanAtlas clinical table (clinical_PANCAN_patient_with_
# followup.tsv, keyed on bcr_patient_barcode). For indications listed here, join
# normalized clinical columns onto the marker-paper frame so directly-tagged
# clinical rules (clinical.hpv_status == 'positive', clinical.anatomic_site ==
# 'oropharyngeal') fire without a separate emitter path.
_CLINICAL_S3 = ("data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/"
                "clinical_PANCAN_patient_with_followup.tsv")

# TCGA-HNSC anatomic_neoplasm_subdivision (fine-grained) → catalog site buckets.
# Oropharyngeal = HPV-enriched (tonsil, base of tongue, oropharynx); oral cavity
# = the rest of the mouth; larynx separate. Values not mapped → NaN (null).
_HNSC_SITE_GROUPING = {
    "Tonsil": "oropharyngeal",
    "Base of tongue": "oropharyngeal",
    "Oropharynx": "oropharyngeal",
    "Oral Tongue": "oral_cavity",
    "Floor of mouth": "oral_cavity",
    "Buccal Mucosa": "oral_cavity",
    "Alveolar Ridge": "oral_cavity",
    "Hard Palate": "oral_cavity",
    "Lip": "oral_cavity",
    "Larynx": "larynx",
    # Hypopharynx is neither oropharyngeal nor oral-cavity nor larynx in the
    # catalog's 3-bucket scheme → left unmapped (null for those strata).
}

# indication → clinical-enrichment spec. Each entry produces normalized columns
# on the marker-paper frame. `site_grouping` maps a raw site column to buckets;
# `hpv_col` is the raw p16 column normalized to positive/negative/null.
INDICATION_CLINICAL_ENRICH: dict[str, dict] = {
    "HNSC": {
        "hpv_col": "hpv_status_by_p16_testing",   # Positive/Negative/[Not Available]/...
        "site_col": "anatomic_neoplasm_subdivision",
        "site_grouping": _HNSC_SITE_GROUPING,
    },
}


def _log(msg: str) -> None:
    click.echo(f"[prefetch-marker-paper] {msg}", err=True)


def _s3_download_key(key: str, dest: Path, dry_run: bool) -> None:
    """Download an ARBITRARY S3 key (full path under the bucket), unlike
    _s3_download which prepends the marker-papers prefix. Used for the clinical
    table which lives under a different PanCanAtlas prefix."""
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


def _s3_download(filename: str, dest: Path, dry_run: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _log(f"cache hit: {dest} (skip download)")
        return
    key = f"{S3_PREFIX}/{filename}"
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


@click.command()
@click.option("--indication", required=True, help="iDAS indication code (e.g. NSCLC).")
def main(indication: str) -> int:
    dry_run = os.environ.get("DRY_RUN") == "1"
    ind = indication.upper()
    cohorts = INDICATION_COHORTS.get(ind)
    _log(f"=== prefetch marker-paper × {ind} ===")
    if cohorts is None:
        _log(f"No marker-paper cohort mapping for {ind}; add it to INDICATION_COHORTS. "
             f"(AML has no marker-paper LAML file — see the D7 audit.)")
        sys.exit(1)

    out_dir = Path.home() / ".cache" / "framework-tcga-marker-paper" / ind.lower()
    out_path = out_dir / "subtypes.csv"
    raw_dir = Path.home() / ".cache" / "framework-tcga-marker-paper" / "_raw"

    _log(f"  cohorts:  {[c[0] for c in cohorts]}")
    _log(f"  output:   {out_path}")
    if dry_run:
        for fn, _ in cohorts:
            _s3_download(fn, raw_dir / fn, dry_run=True)
        _log("DRY_RUN: skipping compose + write")
        return 0

    import pandas as pd

    frames = []
    for filename, histology in cohorts:
        local = raw_dir / filename
        _s3_download(filename, local, dry_run=False)
        df = pd.read_csv(local)
        if "patient" not in df.columns:
            _log(f"WARNING: {filename} has no `patient` column — the directly_tagged "
                 f"loader joins on it. Columns: {list(df.columns)[:6]}")
        if histology is not None:
            df["histology"] = histology
        frames.append(df)
        _log(f"  {filename}: {len(df)} rows"
             + (f" (histology={histology})" if histology else ""))

    composed = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    # Enrich with the published molecular subtype from the PanCanAtlas curated
    # table when the per-cohort file lacks it (HNSC Bass subtypes etc.). Joins on
    # patient barcode; strips the '{CANCER}.' prefix so the value matches the
    # catalog rule (e.g. 'HNSC.Basal' -> 'Basal').
    enrich = INDICATION_SUBTYPE_ENRICH.get(ind)
    if enrich is not None:
        out_col, cancer_type, strip_prefix = enrich
        curated_local = raw_dir / _PANCAN_CURATED_FILE
        _s3_download(_PANCAN_CURATED_FILE, curated_local, dry_run=False)
        cur = pd.read_csv(curated_local)
        cur = cur[cur["cancer.type"] == cancer_type][["pan.samplesID", "Subtype_Selected"]].copy()
        cur["patient"] = cur["pan.samplesID"].str[:12]
        cur[out_col] = cur["Subtype_Selected"].astype(str).str.replace(
            strip_prefix, "", regex=False)
        cur = cur[["patient", out_col]].drop_duplicates("patient")
        composed = composed.merge(cur, on="patient", how="left")
        _log(f"  enriched {out_col}: {composed[out_col].value_counts(dropna=False).to_dict()}")

    # Clinical enrichment (HPV status, anatomic site) from the PanCanAtlas
    # clinical table. Normalizes to the catalog rule vocabulary; unmapped/absent
    # → NaN so the directly-tagged evaluator emits tri-value null (not false).
    clin_spec = INDICATION_CLINICAL_ENRICH.get(ind)
    if clin_spec is not None:
        clin_local = raw_dir / "clinical_PANCAN_patient_with_followup.tsv"
        _s3_download_key(_CLINICAL_S3, clin_local, dry_run=False)
        clin = pd.read_csv(clin_local, sep="\t", low_memory=False, encoding="latin-1")
        csub = pd.DataFrame({"patient": clin["bcr_patient_barcode"]})
        if clin_spec.get("hpv_col"):
            raw_hpv = clin[clin_spec["hpv_col"]].astype(str).str.strip().str.lower()
            csub["hpv_status"] = raw_hpv.map({"positive": "positive", "negative": "negative"})
        if clin_spec.get("site_col"):
            csub["anatomic_site"] = clin[clin_spec["site_col"]].map(clin_spec["site_grouping"])
        csub = csub.drop_duplicates("patient")
        composed = composed.merge(csub, on="patient", how="left")
        if "hpv_status" in composed:
            _log(f"  enriched hpv_status: {composed['hpv_status'].value_counts(dropna=False).to_dict()}")
        if "anatomic_site" in composed:
            _log(f"  enriched anatomic_site: {composed['anatomic_site'].value_counts(dropna=False).to_dict()}")

    out_dir.mkdir(parents=True, exist_ok=True)
    composed.to_csv(out_path, index=False)
    hist_note = ""
    if "histology" in composed.columns:
        hist_note = f" | histology: {composed['histology'].value_counts().to_dict()}"
    _log(f"wrote {out_path}: {len(composed)} rows{hist_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
