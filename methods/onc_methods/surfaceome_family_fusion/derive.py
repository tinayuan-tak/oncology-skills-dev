"""surfaceome_family_fusion.derive — 4-source ETL into the family-classification parquet.

Fuses SURFY 2018 + HPA v25.1 + UniProt SwissProt EC + IUPHAR gtop-2026-2
into a per-UniProt-AC parquet with:
  - `is_surface_protein` — union of SURFY-positive OR HPA plasma-membrane
  - `surface_protein_family` — categorical, source precedence:
      HPA `Protein class` (source-of-truth for family, per card contract)
      → IUPHAR `Type` (fallback)
      → UniProt EC-derived (Kinase if 2.7.*, else Enzyme)
      → "Other" if surface / "Not_surface" if not
  - `surfaceome_confidence_score` — sources_agreeing_on_surface / sources_reporting
    (additive scoring per card contract, NOT a probabilistic posterior)
  - `family_class` — rules-firing shorthand for the rules engine
  - `fusion_provenance` — list<str> like ["surfy:surface", "hpa:surface,Kinases",
    "uniprot_ec:2.7.10.1", "iuphar:Catalytic Receptor"]

Column names match the CONSUMER contract at
methods/surfaceome_family_fusion/read.py:104-114.

Runtime: ~90s cold end-to-end (SURFY 3s, HPA 30s decompress+parse,
UniProt DAT 40s Bio.SwissProt.parse, IUPHAR 2s, fusion 5s, write 3s).

## Resolver-integration status (v1 vs. v2)

**v1 (this implementation): joins on RAW UniProt AC across all 4 sources.**
Works today because all 4 sources publish UniProt AC as a column. Limitation:
does NOT normalize deprecated ACs, isoform-suffixed ACs (P12345-2), or
cross-species contamination. HPA has a target-resolution sidecar at
`s3://onc-compbio/data-catalog/sources/hpa/v25-1/proteinatlas.tsv.zip.target_resolution.parquet`
(20,151 rows, resolver_v1.0.0) but this derive does NOT consume it yet.

**v2 follow-up (planned)**: extend derive schema ADDITIVELY with resolver
columns:
  - hgnc_id, hgnc_primary_symbol_at_resolution (canonical HGNC identity)
  - ensembl_gene_id, ensembl_gene_version
  - entrez_id
  - uniprot_canonical (may differ from raw uniprot_ac when a deprecated
    or isoform AC gets normalized)
  - resolution_status ('resolved' | 'deprecated' | 'unresolved')
Requires: (a) HPA sidecar reads (already exists), (b) resolver sidecars
for SURFY / UniProt / IUPHAR (data-catalog follow-up work). Read.py
schema unchanged; consumers gain new fields when v2 lands.

Usage:
    python -m onc_methods.surfaceome_family_fusion.derive \\
        --out /tmp/surfaceome_family.parquet
"""

from __future__ import annotations

import argparse
import gzip
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Iterable

import pandas as pd

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# Source S3 keys (all landed sources per data-catalog audit).
SURFY_S3_KEY = "data-catalog/sources/surfacome-ethz-2018/table_S3_surfaceome.xlsx"
HPA_S3_KEY = "data-catalog/sources/hpa/v25-1/proteinatlas.tsv.zip"
UNIPROT_DAT_S3_KEY = "data-catalog/sources/uniprot-sprot-human/2026_02-snapshot-2026-06-18/uniprot_sprot_human.dat.gz"
IUPHAR_S3_KEY = "data-catalog/sources/iuphar-gtop/2026-2/targets_and_families.csv"


# HPA `Protein class` value → our family taxonomy. HPA emits multiple
# classes comma-separated per row; we pick the first match in this map,
# in insertion order. ORDER MATTERS: most-specific therapy-relevant classes
# come first, generic membrane-adjacent classes last. HPA labels many
# CD-molecules and RTKs with BOTH the specific class AND the generic
# "Transporters" tag (ITGA6 example: "CD markers, ..., Transporters" —
# CD_molecule must win over Transporter).
_HPA_CLASS_TO_FAMILY: dict[str, str] = {
    # Tier 1 — most specific therapeutic classes
    "CD markers": "CD_molecule",
    "GPCRs": "GPCR",
    "Integrins": "Adhesion",
    "Cadherins": "Adhesion",
    "Cell adhesion": "Adhesion",
    "Adhesion": "Adhesion",
    "Growth factor receptors": "Growth_factor",
    "Cytokine receptors": "Growth_factor",
    "Immunoglobulin superfamily": "Immune_receptor",
    "T-cell receptors": "Immune_receptor",
    "Fc receptors": "Immune_receptor",
    "Complement receptors": "Immune_receptor",
    # Tier 2 — kinases (many overlap with CD/receptor classes but RTKs are
    # both "Kinases" AND "Growth factor receptors"; we want Kinase to
    # win over generic "Enzymes" but NOT over CD/GF/receptor classes above)
    "Kinases": "Kinase",
    "RAS pathway related proteins": "Kinase",
    # Tier 3 — generic transporters / channels
    "Voltage-gated ion channels": "Transporter",
    "Ion channels": "Transporter",
    "SLC transporters": "Transporter",
    "ABC transporters": "Transporter",
    "Transporters": "Transporter",
    # Tier 4 — fallback: broad "Enzymes" tag
    "Enzymes": "Enzyme",
}

# IUPHAR `Type` value → our family taxonomy. IUPHAR emits a single canonical
# receptor-class assignment per target, so this is a simple 1:1 mapping.
_IUPHAR_TYPE_TO_FAMILY: dict[str, str] = {
    "gpcr": "GPCR",
    "ion channel": "Transporter",
    "vgic": "Transporter",  # voltage-gated
    "lgic": "Transporter",  # ligand-gated
    "other ion channel": "Transporter",
    "transporter": "Transporter",
    "enzyme": "Enzyme",
    "catalytic receptor": "Growth_factor",
    "nhr": "Other",  # nuclear hormone receptor (usually intracellular)
    "nuclear hormone receptor": "Other",
    "other protein target": "Other",
}

# IUPHAR types that imply surface-presence even if HPA/SURFY didn't flag it
_IUPHAR_SURFACE_TYPES = {
    "gpcr",
    "ion channel",
    "vgic",
    "lgic",
    "other ion channel",
    "catalytic receptor",
    "transporter",
}


def _boto3_client():
    import boto3

    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


# ---------------------------------------------------------------------------
# Per-source loaders
# ---------------------------------------------------------------------------


def _load_surfy(local_path: Path) -> pd.DataFrame:
    """Load SURFY SurfaceomeMasterTable sheet. Handles the title-comment first row.

    Returns DataFrame with columns:
        uniprot_ac (from `UniProt accession`), surface_present_surfy (bool),
        surfy_confidence_score (float, ML score).
    """
    # First row is a title comment; row 1 (0-indexed) is the real header.
    df = pd.read_excel(local_path, sheet_name="SurfaceomeMasterTable", header=1)
    # Column canonicalization. NOTE: SURFY has THREE MachineLearning-prefixed
    # columns (trainingset, score, FPR class); we match ONLY the `score` one.
    col_map: dict[str, str] = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in ("uniprot accession", "uniprot"):
            col_map[c] = "uniprot_ac"
        elif cl in ("surfaceome label", "class label"):
            col_map[c] = "surfy_label"
        elif cl == "machinelearning score":
            col_map[c] = "surfy_confidence_score"
    df = df.rename(columns=col_map)
    if "uniprot_ac" not in df.columns:
        raise RuntimeError(f"SURFY: uniprot column not found. Available: {list(df.columns)[:8]}")
    df["uniprot_ac"] = df["uniprot_ac"].astype(str).str.strip()
    if "surfy_label" in df.columns:
        df["surface_present_surfy"] = (
            df["surfy_label"].astype(str).str.lower().str.strip().isin({"surface", "yes", "true"})
        )
    else:
        # Master-table lists both surface and non-surface; SURFY score >0.5 = surface fallback
        df["surface_present_surfy"] = df.get("surfy_confidence_score", 0).fillna(0) >= 0.5
    keep_cols = ["uniprot_ac", "surface_present_surfy"]
    if "surfy_confidence_score" in df.columns:
        df["surfy_confidence_score"] = pd.to_numeric(df["surfy_confidence_score"], errors="coerce")
        keep_cols.append("surfy_confidence_score")
    df = df[keep_cols].drop_duplicates("uniprot_ac", keep="first")
    return df


def _load_hpa(local_path: Path) -> pd.DataFrame:
    """Load HPA proteinatlas.tsv from the zipped source, extract relevant cols.

    Returns DataFrame with columns:
        uniprot_ac (from `Uniprot`), gene_symbol (from `Gene`),
        hpa_protein_class_verbatim (from `Protein class`),
        source_hpa_plasma_membrane (bool, derived from `Subcellular main location`),
        hpa_family (categorical, derived from `Protein class`).
    """
    with zipfile.ZipFile(local_path) as z:
        with z.open("proteinatlas.tsv") as f:
            df = pd.read_csv(f, sep="\t", low_memory=False, dtype=str)

    # Handle multi-UniProt cells: HPA emits comma-separated ACs when a gene
    # maps to multiple UniProt entries. We split + explode.
    df = df[["Uniprot", "Gene", "Protein class", "Subcellular main location"]].copy()
    df.columns = ["uniprot_ac", "gene_symbol", "hpa_protein_class_verbatim", "hpa_subcell"]
    df["uniprot_ac"] = df["uniprot_ac"].fillna("").str.strip()
    df["gene_symbol"] = df["gene_symbol"].fillna("").str.strip()
    df["hpa_protein_class_verbatim"] = df["hpa_protein_class_verbatim"].fillna("")
    df["hpa_subcell"] = df["hpa_subcell"].fillna("")

    # Multi-AC explode
    df = df.assign(uniprot_ac=df["uniprot_ac"].str.split(",")).explode("uniprot_ac")
    df["uniprot_ac"] = df["uniprot_ac"].str.strip()
    df = df[df["uniprot_ac"] != ""].copy()

    # Surface flag: Plasma membrane in subcellular main location
    df["source_hpa_plasma_membrane"] = df["hpa_subcell"].str.contains("Plasma membrane", case=False, na=False)

    # Family from Protein class. HPA is multi-label; a target like ERBB2 may
    # be tagged as both "Kinases" AND "CD markers" AND "Transporters" — we
    # want Kinase to win. Adhesion molecules like ITGA6 are tagged "CD markers"
    # AND "Cell adhesion" — we want Adhesion. Priority order below reflects
    # therapy-modality relevance: Kinase > Adhesion > GPCR > Growth_factor
    # > Immune_receptor > CD_molecule > Transporter > Enzyme.
    _FAMILY_PRIORITY = [
        "Kinase",
        "Adhesion",
        "GPCR",
        "Growth_factor",
        "Immune_receptor",
        "CD_molecule",
        "Transporter",
        "Enzyme",
    ]

    def pick_family(cls_str: str) -> str:
        if not cls_str:
            return ""
        classes = {c.strip() for c in cls_str.split(",")}
        # Collect ALL families this row's HPA classes map to
        family_hits = set()
        for hpa_key, family in _HPA_CLASS_TO_FAMILY.items():
            if hpa_key in classes:
                family_hits.add(family)
        if not family_hits:
            return ""
        # Return the highest-priority family that got a hit
        for family in _FAMILY_PRIORITY:
            if family in family_hits:
                return family
        return ""

    df["hpa_family"] = df["hpa_protein_class_verbatim"].apply(pick_family)
    return df.drop(columns=["hpa_subcell"]).drop_duplicates("uniprot_ac", keep="first")


def _iter_uniprot_ec(local_path: Path) -> Iterable[tuple[str, str]]:
    """Yield (accession, ec_number) pairs from UniProt SwissProt DAT file.

    Uses Bio.SwissProt.parse per the reusable pattern in
    methods/topology_predictions_tmbed/prepare_fasta.py.

    EC numbers appear in the `description` field as `EC=X.X.X.X;` — regex-extract.
    """
    from Bio import SwissProt

    ec_re = re.compile(r"EC=([\d.\-nN]+)")
    with gzip.open(local_path, "rt") as f:
        for record in SwissProt.parse(f):
            ac = record.accessions[0] if record.accessions else ""
            if not ac:
                continue
            desc = record.description or ""
            m = ec_re.search(desc)
            ec = m.group(1) if m else ""
            yield ac, ec


def _load_uniprot_ec(local_path: Path) -> pd.DataFrame:
    """Return DataFrame with columns: uniprot_ac, source_uniprot_ec_number."""
    records = list(_iter_uniprot_ec(local_path))
    df = pd.DataFrame(records, columns=["uniprot_ac", "source_uniprot_ec_number"])
    return df.drop_duplicates("uniprot_ac", keep="first")


def _load_iuphar(local_path: Path) -> pd.DataFrame:
    """Load IUPHAR targets_and_families.csv. Handles title-comment first row.

    Returns DataFrame with columns:
        uniprot_ac (from `Human SwissProt`),
        source_iuphar_family (from `Type`, then Family-name refinement),
        iuphar_type_lower (helper for surface flag).

    Family-name refinement (fixes ITGA6-class failures):
    IUPHAR's `Type` = catalytic_receptor is a signaling-mode label; the
    more-specific molecular class lives in `Family name`. When `Family name`
    contains 'Integrin' or 'cadherin' (not "Adhesion Class GPCRs", which
    is a GPCR subclass), we override the Type-derived family to Adhesion.
    """
    # First row is title comment; real header on row 1
    df = pd.read_csv(local_path, skiprows=1, low_memory=False, dtype=str)
    if "Human SwissProt" not in df.columns:
        raise RuntimeError(f"IUPHAR: 'Human SwissProt' column not found. Available: {list(df.columns)[:8]}")
    df = df[["Human SwissProt", "Type", "Family name"]].copy()
    df.columns = ["uniprot_ac", "iuphar_type", "iuphar_family_name"]
    df["uniprot_ac"] = df["uniprot_ac"].fillna("").str.strip()
    df["iuphar_type"] = df["iuphar_type"].fillna("").str.strip()
    df["iuphar_family_name"] = df["iuphar_family_name"].fillna("").str.strip()
    # Multi-AC handling: some rows have "P12345|Q98765" — split + explode
    df = df.assign(uniprot_ac=df["uniprot_ac"].str.split("|")).explode("uniprot_ac")
    df["uniprot_ac"] = df["uniprot_ac"].str.strip()
    df = df[df["uniprot_ac"] != ""].copy()
    df["iuphar_type_lower"] = df["iuphar_type"].str.lower()

    # Base assignment from Type
    df["source_iuphar_family"] = df["iuphar_type_lower"].map(_IUPHAR_TYPE_TO_FAMILY).fillna("")

    # Family-name override for Adhesion: matches 'Integrin' or 'cadherin'
    # BUT NOT 'Adhesion Class GPCRs' (a GPCR subclass).
    fam_lower = df["iuphar_family_name"].str.lower()
    is_adhesion = ((fam_lower.str.contains("integrin", na=False)) | (fam_lower.str.contains("cadherin", na=False))) & (
        ~fam_lower.str.contains("gpcr", na=False)
    )
    df.loc[is_adhesion, "source_iuphar_family"] = "Adhesion"

    return df[["uniprot_ac", "source_iuphar_family", "iuphar_type_lower", "iuphar_family_name"]].drop_duplicates(
        "uniprot_ac", keep="first"
    )


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def _classify_family(row) -> str:
    """Family assignment across 4 sources.

    Precedence (refined during biology validation):
      1. UniProt EC 2.7.* (kinase EC) WINS — even over HPA's family
         assignment. Rationale: HPA v25.1 under-annotates the Kinases class
         (ERBB2 lacks it despite EC 2.7.10.1). UniProt EC is authoritative
         for kinase identity.
      2. IUPHAR Adhesion/Growth_factor — WINS over HPA when HPA under-
         labels adhesion molecules (ITGA6 lacks Adhesion in HPA v25.1).
         (Applied via check on iuphar_type_lower before falling to HPA.)
      3. HPA family (if non-empty) — source-of-truth for the remaining
         cases; per the card contract.
      4. IUPHAR family (fallback if HPA silent).
      5. UniProt EC non-kinase → Enzyme.
      6. Other (if surface) / Not_surface.
    """
    ec = row.get("source_uniprot_ec_number") or ""
    iuphar_fam = row.get("source_iuphar_family") or ""
    hpa_fam = row.get("hpa_family") or ""

    # Rule 1: kinase EC wins (fixes ERBB2 — HPA v25.1 misses Kinases class)
    if ec.startswith("2.7."):
        return "Kinase"
    # Rule 2: IUPHAR Adhesion overrides HPA (fixes ITGA6 — HPA + IUPHAR-Type
    # both under-annotate; IUPHAR Family-name has 'Integrin'/'cadherin')
    if iuphar_fam == "Adhesion":
        return "Adhesion"
    # Rule 3/4: HPA (source-of-truth per card) then IUPHAR
    if hpa_fam:
        return hpa_fam
    if iuphar_fam:
        return iuphar_fam
    # Rule 5: any other EC → Enzyme
    if ec:
        return "Enzyme"
    # Rule 6: fallback
    if row.get("is_surface_protein"):
        return "Other"
    return "Not_surface"


def _classify_family_class(row) -> str:
    """Rules-firing shorthand. is_surface + family → snake_case category."""
    family = row.get("surface_protein_family", "")
    is_surface = bool(row.get("is_surface_protein"))
    if not is_surface:
        return "not_surface"
    return {
        "Kinase": "kinase_surface",
        "Enzyme": "enzyme_surface",
        "Transporter": "transporter",
        "CD_molecule": "cd_molecule",
        "Adhesion": "adhesion",
        "GPCR": "gpcr",
        "Growth_factor": "growth_factor_receptor",
        "Immune_receptor": "immune_receptor",
        "Other": "other_surface",
    }.get(family, "other_surface")


def _build_provenance(row) -> list[str]:
    prov = []
    if row.get("_surfy_reported"):
        prov.append(f"surfy:{'surface' if row.get('source_surfy_positive') else 'not_surface'}")
    if row.get("_hpa_reported"):
        hpa_call = "surface" if row.get("source_hpa_plasma_membrane") else "not_surface"
        family = row.get("hpa_family") or ""
        prov.append(f"hpa:{hpa_call}" + (f",{family}" if family else ""))
    ec = row.get("source_uniprot_ec_number") or ""
    if ec:
        prov.append(f"uniprot_ec:{ec}")
    iuphar_fam = row.get("source_iuphar_family") or ""
    if iuphar_fam:
        prov.append(f"iuphar:{iuphar_fam}")
    return prov


def fuse(
    surfy_df: pd.DataFrame,
    hpa_df: pd.DataFrame,
    uniprot_df: pd.DataFrame,
    iuphar_df: pd.DataFrame,
) -> pd.DataFrame:
    """Outer-join the 4 sources on uniprot_ac, compute additive fusion columns."""
    # Track "reported" flags to compute source-agreement denominator
    surfy_df = surfy_df.assign(_surfy_reported=True)
    hpa_df = hpa_df.assign(_hpa_reported=True)

    df = surfy_df.merge(hpa_df, on="uniprot_ac", how="outer")
    df = df.merge(uniprot_df, on="uniprot_ac", how="outer")
    df = df.merge(iuphar_df, on="uniprot_ac", how="outer")

    df["_surfy_reported"] = df["_surfy_reported"].fillna(False)
    df["_hpa_reported"] = df["_hpa_reported"].fillna(False)
    df["source_surfy_positive"] = df.get("surface_present_surfy", False).fillna(False)
    df["source_hpa_plasma_membrane"] = df.get("source_hpa_plasma_membrane", False).fillna(False)
    df["source_uniprot_ec_number"] = df.get("source_uniprot_ec_number", "").fillna("")
    df["source_iuphar_family"] = df.get("source_iuphar_family", "").fillna("")
    df["hpa_family"] = df.get("hpa_family", "").fillna("")
    df["hpa_protein_class_verbatim"] = df.get("hpa_protein_class_verbatim", "").fillna("")
    df["gene_symbol"] = df.get("gene_symbol", "").fillna("")
    df["iuphar_type_lower"] = df.get("iuphar_type_lower", "").fillna("")
    df["iuphar_family_name"] = df.get("iuphar_family_name", "").fillna("")

    # is_surface_protein: union of SURFY-positive OR HPA-plasma-membrane OR
    # (IUPHAR surface-implying type)
    surfy_pos = df["source_surfy_positive"].astype(bool)
    hpa_pm = df["source_hpa_plasma_membrane"].astype(bool)
    iuphar_surface = df["iuphar_type_lower"].isin(_IUPHAR_SURFACE_TYPES)
    df["is_surface_protein"] = surfy_pos | hpa_pm | iuphar_surface

    # surfaceome_confidence_score: agreement fraction. Denominator is number
    # of sources that REPORTED on surface status (SURFY + HPA); IUPHAR is
    # inference-only for surface (doesn't report an explicit "is-surface" bit).
    reported = df["_surfy_reported"].astype(int) + df["_hpa_reported"].astype(int)
    agreeing = (df["_surfy_reported"] & (df["source_surfy_positive"] == df["is_surface_protein"])).astype(int) + (
        df["_hpa_reported"] & (df["source_hpa_plasma_membrane"] == df["is_surface_protein"])
    ).astype(int)
    df["surfaceome_confidence_score"] = agreeing / reported.where(reported > 0, 1)
    df.loc[reported == 0, "surfaceome_confidence_score"] = None

    # Family assignment
    df["surface_protein_family"] = df.apply(_classify_family, axis=1)
    df["family_class"] = df.apply(_classify_family_class, axis=1)
    df["fusion_provenance"] = df.apply(_build_provenance, axis=1)
    df["method_version"] = "0.1.0"

    return df


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _download_source(local_dir: Path, s3_key: str) -> Path:
    """Download s3_key to local_dir if not already present. Returns local path."""
    filename = Path(s3_key).name
    local = local_dir / filename
    if local.exists() and local.stat().st_size > 0:
        return local
    local.parent.mkdir(parents=True, exist_ok=True)
    s3 = _boto3_client()
    s3.download_file(S3_BUCKET, s3_key, str(local))
    return local


def derive_surfaceome_family(out_parquet: Path, local_cache_dir: Path) -> pd.DataFrame:
    """Full ETL. Downloads sources if missing, fuses, writes parquet."""
    local_cache_dir.mkdir(parents=True, exist_ok=True)

    print("[surfaceome_family_fusion.derive] downloading sources...", file=sys.stderr)
    t0 = time.perf_counter()
    surfy_local = _download_source(local_cache_dir, SURFY_S3_KEY)
    hpa_local = _download_source(local_cache_dir, HPA_S3_KEY)
    uniprot_local = _download_source(local_cache_dir, UNIPROT_DAT_S3_KEY)
    iuphar_local = _download_source(local_cache_dir, IUPHAR_S3_KEY)
    print(
        f"[surfaceome_family_fusion.derive] downloads: {time.perf_counter() - t0:.1f}s",
        file=sys.stderr,
    )

    print("[surfaceome_family_fusion.derive] parsing SURFY...", file=sys.stderr)
    t0 = time.perf_counter()
    surfy_df = _load_surfy(surfy_local)
    print(
        f"[surfaceome_family_fusion.derive]   SURFY rows: {len(surfy_df):,} ({time.perf_counter() - t0:.1f}s)",
        file=sys.stderr,
    )

    print("[surfaceome_family_fusion.derive] parsing HPA...", file=sys.stderr)
    t0 = time.perf_counter()
    hpa_df = _load_hpa(hpa_local)
    print(
        f"[surfaceome_family_fusion.derive]   HPA rows: {len(hpa_df):,} ({time.perf_counter() - t0:.1f}s)",
        file=sys.stderr,
    )

    print("[surfaceome_family_fusion.derive] parsing UniProt DAT (EC)...", file=sys.stderr)
    t0 = time.perf_counter()
    uniprot_df = _load_uniprot_ec(uniprot_local)
    print(
        f"[surfaceome_family_fusion.derive]   UniProt records: {len(uniprot_df):,} ({time.perf_counter() - t0:.1f}s)",
        file=sys.stderr,
    )

    print("[surfaceome_family_fusion.derive] parsing IUPHAR...", file=sys.stderr)
    t0 = time.perf_counter()
    iuphar_df = _load_iuphar(iuphar_local)
    print(
        f"[surfaceome_family_fusion.derive]   IUPHAR rows: {len(iuphar_df):,} ({time.perf_counter() - t0:.1f}s)",
        file=sys.stderr,
    )

    print("[surfaceome_family_fusion.derive] fusing...", file=sys.stderr)
    t0 = time.perf_counter()
    fused = fuse(surfy_df, hpa_df, uniprot_df, iuphar_df)
    print(
        f"[surfaceome_family_fusion.derive]   fused rows: {len(fused):,} ({time.perf_counter() - t0:.1f}s)",
        file=sys.stderr,
    )

    # Final schema in the exact order + columns read.py consumes
    output_cols = [
        "uniprot_ac",
        "gene_symbol",
        "surface_protein_family",
        "surfaceome_confidence_score",
        "is_surface_protein",
        "source_surfy_positive",
        "source_hpa_plasma_membrane",
        "source_uniprot_ec_number",
        "source_iuphar_family",
        "hpa_protein_class_verbatim",
        "fusion_provenance",
        "family_class",
        "method_version",
    ]
    if "surfy_confidence_score" in fused.columns:
        output_cols.insert(5, "surfy_confidence_score")

    fused = fused[output_cols].sort_values("gene_symbol").reset_index(drop=True)

    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    fused.to_parquet(out_parquet, engine="pyarrow", compression="snappy", index=False)
    print(
        f"[surfaceome_family_fusion.derive] wrote {len(fused):,} rows "
        f"({out_parquet.stat().st_size / 1e6:.1f}MB) -> {out_parquet}",
        file=sys.stderr,
    )

    # Coverage stats
    print("[surfaceome_family_fusion.derive] coverage:", file=sys.stderr)
    print("  family_class value counts:", file=sys.stderr)
    print(fused["family_class"].value_counts().to_string(), file=sys.stderr)
    print(f"  n_surface_protein: {int(fused['is_surface_protein'].sum()):,}", file=sys.stderr)
    return fused


def _main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="Output parquet path")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "framework-surfaceome-family-sources",
        help="Local directory for source-file caching",
    )
    args = ap.parse_args(argv)

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    derive_surfaceome_family(args.out, args.cache_dir)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
