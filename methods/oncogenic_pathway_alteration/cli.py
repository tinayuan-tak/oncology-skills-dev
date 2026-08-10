#!/usr/bin/env python3
"""oncogenic_pathway_alteration — per-indication oncogenic-pathway ALTERATION context (Sanchez-Vega 2018).

A verdict-INERT context facet: how frequently is each of the 10 canonical oncogenic signaling pathways
ALTERED in an indication's TCGA cohort, and which pathway(s) does a target belong to? A PRE-INTEGRATED
multi-omics RESULT — Sanchez-Vega 2018 already fused curated driver mutations + GISTIC CN + fusions
against expert pathway templates to a per-sample binary "pathway altered" call.

Complements PROGENy pathway-ACTIVITY (transcriptional footprint) — this is pathway ALTERATION (genomic).
Both are cohort mechanism-context; routes into Mechanism (D) + Altered (E).

BUILD (per-indication rollup, read grain pre-aggregated → O(1) skill reads):
  - mmc4 "Pathway level": SAMPLE_BARCODE x 10 pathways, binary altered (9,124 tumors).
  - barcode → indication via merged_sample_quality_annotations (the SAME bridge DDR/aneuploidy use).
  - per-(pathway x indication): fraction of cohort with the pathway altered.
  - mmc3 pathway templates: gene → pathway membership (so a target maps to its pathway).
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pandas as pd

METHOD_VERSION = "0.1.0"

# Resolver seam: manifest_ids resolve to their authoritative s3_uri via the data-catalog manifests
# (single source of truth), rather than hand-typed literals that can drift on a re-emit. Both source
# manifests carry a DIRECTORY s3_uri (trailing slash); the per-file key is the dir + filename.
SANCHEZ_SOURCE_MANIFEST_ID = "sanchez-vega-oncogenic-pathways-2018"
_MMC4_FILE = "Sanchez-Vega_2018_mmc4_genomic_alteration_matrices.xlsx"
_MMC3_FILE = "Sanchez-Vega_2018_mmc3_pathway_templates.xlsx"
# merged_sample_quality_annotations.tsv is documented as a files: entry in gdc-pancanatlas-clinical-2018
# (four gdc-pancanatlas manifests share the same dir; clinical is the one that lists this file).
BRIDGE_SOURCE_MANIFEST_ID = "gdc-pancanatlas-clinical-2018"
_BRIDGE_FILE = "merged_sample_quality_annotations.tsv"


def _join(base: str, filename: str) -> str:
    return base + filename if base.endswith("/") else f"{base}/{filename}"


def _resolve_src_dir() -> str:
    from methods.catalog_query.read import s3_uri_for
    return s3_uri_for(SANCHEZ_SOURCE_MANIFEST_ID)


def _resolve_bridge_uri() -> str:
    from methods.catalog_query.read import s3_uri_for
    return _join(s3_uri_for(BRIDGE_SOURCE_MANIFEST_ID), _BRIDGE_FILE)

PATHWAYS = ["Cell Cycle", "HIPPO", "MYC", "NOTCH", "NRF2", "PI3K", "RTK RAS", "TP53", "TGF-Beta", "WNT"]
MIN_COHORT_N = 15
HIGH_ALT_FRAC = 0.50     # >= 50% of cohort altered → pathway-frequently-altered in this indication


def _s3_bytes(uri: str) -> bytes:
    return subprocess.run(["aws", "s3", "cp", uri, "-"], capture_output=True).stdout


def _load_barcode_to_indication() -> dict:
    """{sample_barcode(TCGA-XX-XXXX-01) -> cancer type} from merged_sample_quality_annotations."""
    df = pd.read_csv(io.BytesIO(_s3_bytes(_resolve_bridge_uri())), sep="\t", low_memory=False,
                     usecols=["aliquot_barcode", "cancer type"])
    # mmc4 SAMPLE_BARCODE is TCGA-OR-A5J1-01 (patient + sample-type); the aliquot is longer. Join on the
    # PATIENT barcode (first 3 fields) — verified 100% coverage of the 9,125 mmc4 samples.
    df["patient"] = df["aliquot_barcode"].str.split("-").str[:3].str.join("-")
    df = df.dropna(subset=["cancer type"]).drop_duplicates("patient")
    return dict(zip(df["patient"], df["cancer type"]))


def load_gene_pathway_map() -> dict:
    """{gene_symbol -> [pathways]} from the mmc3 pathway templates (one sheet per pathway)."""
    xl = pd.ExcelFile(io.BytesIO(_s3_bytes(_join(_resolve_src_dir(), _MMC3_FILE))))
    out: dict = {}
    for pw in PATHWAYS:
        if pw not in xl.sheet_names:
            continue
        df = xl.parse(pw, header=0)
        gcol = "Gene" if "Gene" in df.columns else df.columns[0]
        for g in df[gcol].dropna().astype(str):
            out.setdefault(g.strip(), []).append(pw)
    return out


def build_per_indication_table() -> pd.DataFrame:
    """Per-(pathway x indication) alteration frequency. Returns long DataFrame
    [indication, pathway, n_samples, frac_altered, pathway_alteration_class]."""
    xl = pd.ExcelFile(io.BytesIO(_s3_bytes(_join(_resolve_src_dir(), _MMC4_FILE))))
    pl = xl.parse("Pathway level", header=0)   # row 0 IS the header (SAMPLE_BARCODE + 10 pathways)
    bc2ind = _load_barcode_to_indication()
    pl["indication"] = pl["SAMPLE_BARCODE"].str.split("-").str[:3].str.join("-").map(bc2ind)
    pl = pl.dropna(subset=["indication"])
    pw_cols = [c for c in pl.columns if c in PATHWAYS]
    rows = []
    for ind, g in pl.groupby("indication"):
        n = len(g)
        if n < MIN_COHORT_N:
            continue
        for pw in pw_cols:
            vals = pd.to_numeric(g[pw], errors="coerce").dropna()
            if vals.empty:
                continue
            frac = float((vals > 0).mean())
            rows.append({
                "indication": str(ind), "pathway": pw, "n_samples": int(n),
                "frac_altered": round(frac, 4),
                "pathway_alteration_class": ("frequently_altered" if frac >= HIGH_ALT_FRAC
                                             else "occasionally_altered" if frac >= 0.10
                                             else "rarely_altered"),
            })
    return pd.DataFrame(rows).sort_values(["indication", "pathway"]).reset_index(drop=True)


try:
    import click

    @click.command()
    @click.option("--out", type=click.Path(path_type=Path), required=True)
    def main(out):
        tbl = build_per_indication_table()
        out.parent.mkdir(parents=True, exist_ok=True)
        tbl.to_parquet(out, index=False)
        click.echo(f"wrote {len(tbl)} (pathway x indication) rows, {tbl['indication'].nunique()} indications -> {out}")

    if __name__ == "__main__":
        main()
except ImportError:
    pass
