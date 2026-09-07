#!/usr/bin/env python3
"""precog_prognostic — per-(gene x indication) PRECOG prognostic meta-Z facet (Gentles 2015 + 2026 NAR).

A verdict-INERT prognostic-association facet: for a target in an indication, is high expression
associated (across 166 datasets / ~18k patients) with WORSE or BETTER overall survival? PRECOG's
meta-Z is the pan-cancer META-ANALYTIC prognostic prior — far better powered than any single-cohort
univariate split — so it CORROBORATES the single-cohort expression-clinical-association card.

  meta-Z sign convention (PRECOG): POSITIVE = high expression -> WORSE survival (candidate
  poor-prognosis / aggressive-disease marker); NEGATIVE = high expression -> BETTER survival.

BUILD: read the PRECOG-metaZ.pcl matrix (gene x 39 cancer-type), map each of the 27 crosswalked
framework indications to its PRECOG cancer-type column, and melt to a long per-(gene x indication)
table [gene, indication, meta_z, precog_source_column, precog_indication_approx]. The pan-cancer
meta-Z column is carried as indication='PANCAN' for a pan-cancer fallback view.

CROSSWALK (the scientific judgment; see INDICATION_TO_PRECOG below): PRECOG's cancer-type vocabulary
is idiosyncratic and its granularity does not always match ours. Exact 1:1 maps (OV->Ovarian_cancer,
LUAD->Lung_cancer_ADENO) carry precog_indication_approx=False. Approximations — composites with no
PRECOG equivalent (COADREAD->Colon_cancer: no rectal split; NSCLC->Lung_cancer_ADENO: representative
histology) — carry precog_indication_approx=True so the card can caveat them. Unmapped indications
return data_unavailable at read time.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pandas as pd

METHOD_VERSION = "0.1.0"

_SRC_S3 = "s3://onc-compbio/data-catalog/sources/precog-metaz-gentles/snapshot-2026-08-10/PRECOG-metaZ.pcl"

# The three non-cancer-type columns in the PCL matrix.
_META_COLS = ("Name", "Unweighted_meta-Z_of_all_cancers")
_PANCAN_COL = "Unweighted_meta-Z_of_all_cancers"

# framework indication code -> (PRECOG cancer-type column, is_approximation)
# Exact = the PRECOG column is the same disease at the same granularity.
# Approx = a documented granularity/composite mismatch (see module docstring).
INDICATION_TO_PRECOG: dict[str, tuple[str, bool]] = {
    # ---- exact 1:1 ----
    "ACC": ("Adrenocortical_cancer", False),
    "BLCA": ("Bladder_cancer", False),
    "GBM": ("Glioblastoma", False),
    "LGG": ("Glioma", False),
    "BRCA": ("Breast_cancer", False),
    "COAD": ("Colon_cancer", False),
    "STAD": ("Gastric_cancer", False),
    "TGCT": ("Germ_cell_tumors", False),
    "HNSC": ("Head_and_neck_cancer", False),
    "ESCA": ("Oesophageal_cancer", False),
    "AML": ("AML", False),
    "DLBC": ("DLBCL", False),
    "KIRC": ("Kidney_cancer", False),
    "LIHC": ("Liver_cancer", False),
    "LUAD": ("Lung_cancer_ADENO", False),
    "LUSC": ("Lung_cancer_SCC", False),
    "SCLC": ("Lung_cancer_SCLC", False),
    "SKCM": ("Melanoma", False),
    "MESO": ("Mesothelioma", False),
    "OV": ("Ovarian_cancer", False),
    "PAAD": ("Pancreatic_cancer", False),
    "PRAD": ("Prostate_cancer", False),
    # ---- documented approximations (granularity / composite mismatch) ----
    "COADREAD": ("Colon_cancer", True),  # PRECOG has no rectal split
    "GC": ("Gastric_cancer", True),  # alias of STAD
    "PDAC": ("Pancreatic_cancer", True),  # alias of PAAD
    "NSCLC": ("Lung_cancer_ADENO", True),  # representative histology (ADENO); LUAD/LUSC served exactly
    "SARC": ("Sarcoma_Osteosarcoma", True),  # PRECOG splits Ewing/Osteo; osteosarcoma as representative
}

# significance band on |meta-Z| (a z-score; |z|>=1.96 ~ two-sided p<0.05).
META_Z_SIGNIF = 1.96


def _classify(meta_z: float) -> str:
    """PRECOG meta-Z -> prognostic_class (mirrors expression-clinical-association's vocabulary)."""
    if meta_z != meta_z:  # NaN
        return "data_unavailable"
    if meta_z >= META_Z_SIGNIF:
        return "expression_high_worse_survival"
    if meta_z <= -META_Z_SIGNIF:
        return "expression_high_better_survival"
    return "no_prognostic_association"


def _load_matrix() -> pd.DataFrame:
    """Read the PRECOG-metaZ.pcl (gene x cancer-type) matrix from S3."""
    raw = subprocess.run(["aws", "s3", "cp", _SRC_S3, "-"], capture_output=True).stdout
    df = pd.read_csv(io.BytesIO(raw), sep="\t")
    return df


def build_long_table() -> pd.DataFrame:
    """Melt the PRECOG matrix to a long per-(gene x indication) meta-Z table.

    Returns [gene, indication, meta_z, prognostic_class, precog_source_column,
             precog_indication_approx]. Includes indication='PANCAN' (the pan-cancer meta-Z).
    """
    mat = _load_matrix().set_index("Gene")
    rows = []
    # every crosswalked framework indication
    for indication, (col, approx) in INDICATION_TO_PRECOG.items():
        if col not in mat.columns:
            continue
        z = pd.to_numeric(mat[col], errors="coerce")
        for gene, val in z.items():
            rows.append((str(gene), indication, float(val) if val == val else float("nan"), col, approx))
    # pan-cancer view (always exact; approx=False)
    zp = pd.to_numeric(mat[_PANCAN_COL], errors="coerce")
    for gene, val in zp.items():
        rows.append((str(gene), "PANCAN", float(val) if val == val else float("nan"), _PANCAN_COL, False))
    df = pd.DataFrame(
        rows, columns=["gene", "indication", "meta_z", "precog_source_column", "precog_indication_approx"]
    )
    df = df.dropna(subset=["meta_z"]).reset_index(drop=True)
    df["meta_z"] = df["meta_z"].round(4)
    df["prognostic_class"] = df["meta_z"].map(_classify)
    return df.sort_values(["indication", "gene"]).reset_index(drop=True)


try:
    import click

    @click.command()
    @click.option("--out", type=click.Path(path_type=Path), required=True)
    def main(out):
        tbl = build_long_table()
        out.parent.mkdir(parents=True, exist_ok=True)
        tbl.to_parquet(out, index=False)
        click.echo(f"wrote {len(tbl)} (gene x indication) rows [{tbl['indication'].nunique()} indications] -> {out}")

    if __name__ == "__main__":
        main()
except ImportError:
    pass
