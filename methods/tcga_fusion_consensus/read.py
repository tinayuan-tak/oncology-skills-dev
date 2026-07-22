"""read.py — per-caller loaders for the TCGA fusion consensus product.

Each loader returns a long DataFrame with a common canonical schema:

    sample_key     str  TCGA sample-level barcode, TCGA-{tss}-{part}-{sample_num}
                        (vial letter dropped so all 3 callers join)
    gene_symbol    str  gene involved in the fusion (either 5' or 3' partner)
    partner_gene   str  the OTHER gene in the fusion event (may be None if unknown)
    partner_side   str  '5prime' if gene_symbol is 5', '3prime' if 3'
    tissue         str  TCGA disease code (LUAD/LUSC/BRCA/…); may be None for
                        cBioPortal (derived from studyId at merge time)
    frame_pred     str  frame prediction as reported by the caller: In-frame /
                        Frame-shift / Frame-preserved / … / None (varies by caller)
    caller         str  {'tumorfusions','gao_2018','cbioportal'}
    event_id       str  caller-native identifier for the fusion event row
                        (for provenance; consumers should NOT join on this)

Sample-key normalization: TCGA barcode format is
    TCGA-{tss}-{participant}-{sample_num}{vial}-{portion}{analyte}-{plate}-{center}
Different callers publish different suffix lengths:
    TumorFusions:  'TCGA-05-4244-01A'                     (through vial)
                   'TCGA-50-8460-01A-11R-2326-07'         (full aliquot; both occur)
    Gao 2018:      'TCGA-05-4244-01A-11R-A29S-07'         (full aliquot)
    cBioPortal:    'TCGA-05-4244-01'                      (sample-only, vial stripped)
The one common granularity is sample-level with the vial letter dropped —
'TCGA-05-4244-01' — which is what we normalize to. Validated 2026-07-22:
after this normalization the three callers achieve 724 samples in all three,
827 in >=2, 895 union across LUAD+LUSC alone (was 0 with a naive first-4-segment cut).
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Iterator, Iterable

import pandas as pd

# ---------- barcode normalization ----------

_SAMPLE_KEY_RE = re.compile(r'^(TCGA-[A-Z0-9]+-[A-Z0-9]+-\d{2})')


def sample_key(barcode: str | None) -> str | None:
    """Normalize a TCGA barcode to sample level (TCGA-tss-participant-sampleNum)."""
    if not isinstance(barcode, str):
        return None
    m = _SAMPLE_KEY_RE.match(barcode)
    return m.group(1) if m else None


# ---------- TumorFusions (Hu 2018 NAR) ----------

def load_tumorfusions(xlsx_path: str | Path) -> pd.DataFrame:
    """Load File007 'Cancer fusions' sheet (20,731 rows across 33 TCGA tissue types).

    The source columns of interest: Tissue, Sample, Gene_A (5'), Gene_B (3'),
    Frame Prediction (In-frame/Frame-shift/…). Emitted long-form: TWO rows per
    fusion event (one for gene_symbol=Gene_A partner_side=5prime, one for Gene_B/3prime).
    """
    # converters force str on gene columns — prevents Excel auto-date mangling
    # of gene names like SEPT1, MARCH1 into datetime.datetime objects.
    df = pd.read_excel(xlsx_path, sheet_name="Cancer fusions",
                       converters={"Gene_A": str, "Gene_B": str, "Sample": str})
    # Two rows per event: one per side.
    a = df.rename(columns={"Gene_A": "gene_symbol", "Gene_B": "partner_gene",
                           "Frame Prediction": "frame_pred"})
    a = a[["Tissue", "Sample", "gene_symbol", "partner_gene", "frame_pred"]].copy()
    a["partner_side"] = "5prime"
    b = df.rename(columns={"Gene_B": "gene_symbol", "Gene_A": "partner_gene",
                           "Frame Prediction": "frame_pred"})
    b = b[["Tissue", "Sample", "gene_symbol", "partner_gene", "frame_pred"]].copy()
    b["partner_side"] = "3prime"
    out = pd.concat([a, b], ignore_index=True)
    out["sample_key"] = out["Sample"].map(sample_key)
    out = out.rename(columns={"Tissue": "tissue"})
    out["caller"] = "tumorfusions"
    out["event_id"] = out["Sample"].astype(str) + "|" + out["gene_symbol"].astype(str) + "--" + out["partner_gene"].astype(str)
    out = out[out["sample_key"].notna() & out["gene_symbol"].notna()]
    return out[["sample_key", "gene_symbol", "partner_gene", "partner_side",
                "tissue", "frame_pred", "caller", "event_id"]]


# ---------- Gao 2018 (Cell Reports) ----------

def load_gao_2018(xlsx_path: str | Path) -> pd.DataFrame:
    """Load 'Final fusion call set' sheet (25,664 rows, 33 TCGA cancer types).

    Header row is row 2 (skiprows=1). Columns: Cancer, Sample, Fusion (5'--3'),
    Junction, Spanning, Breakpoint1, Breakpoint2. Fusion string 'A--B' splits into
    5' and 3' partners. NO frame prediction column — emitted as None."""
    df = pd.read_excel(xlsx_path, sheet_name="Final fusion call set", skiprows=1,
                       converters={"Sample": str, "Fusion": str})
    # Parse 'A--B' -> 5', 3'
    fus = df["Fusion"].astype(str).str.split("--", n=1, expand=True)
    df = df.assign(gene_5p=fus[0], gene_3p=fus[1])
    a = df.rename(columns={"gene_5p": "gene_symbol", "gene_3p": "partner_gene",
                           "Cancer": "tissue"})
    a = a[["tissue", "Sample", "gene_symbol", "partner_gene", "Fusion"]].copy()
    a["partner_side"] = "5prime"
    b = df.rename(columns={"gene_3p": "gene_symbol", "gene_5p": "partner_gene",
                           "Cancer": "tissue"})
    b = b[["tissue", "Sample", "gene_symbol", "partner_gene", "Fusion"]].copy()
    b["partner_side"] = "3prime"
    out = pd.concat([a, b], ignore_index=True)
    out["sample_key"] = out["Sample"].map(sample_key)
    out["frame_pred"] = None  # Gao 2018 does not publish frame predictions.
    out["caller"] = "gao_2018"
    out["event_id"] = out["Sample"].astype(str) + "|" + out["Fusion"].astype(str)
    out = out[out["sample_key"].notna() & out["gene_symbol"].notna() & (out["gene_symbol"] != "nan")]
    return out[["sample_key", "gene_symbol", "partner_gene", "partner_side",
                "tissue", "frame_pred", "caller", "event_id"]]


# ---------- cBioPortal TCGA PanCancer Atlas (32 studies) ----------

_STUDY_TO_TISSUE = {
    # cBioPortal study prefix -> TCGA disease code
    "acc_": "ACC", "blca_": "BLCA", "brca_": "BRCA", "cesc_": "CESC",
    "chol_": "CHOL", "coadread_": "COADREAD", "dlbc_": "DLBC", "esca_": "ESCA",
    "gbm_": "GBM", "hnsc_": "HNSC", "kich_": "KICH", "kirc_": "KIRC",
    "kirp_": "KIRP", "laml_": "LAML", "lgg_": "LGG", "lihc_": "LIHC",
    "luad_": "LUAD", "lusc_": "LUSC", "meso_": "MESO", "ov_": "OV",
    "paad_": "PAAD", "pcpg_": "PCPG", "prad_": "PRAD", "sarc_": "SARC",
    "skcm_": "SKCM", "stad_": "STAD", "tgct_": "TGCT", "thca_": "THCA",
    "thym_": "THYM", "ucec_": "UCEC", "ucs_": "UCS", "uvm_": "UVM",
}


def _cbio_study_tissue(study_id: str) -> str | None:
    for prefix, code in _STUDY_TO_TISSUE.items():
        if study_id.startswith(prefix):
            return code
    return None


def load_cbioportal_sv(jsonl_gz_path: str | Path, study_id: str) -> pd.DataFrame:
    """Load one cBioPortal study's structural_variants.jsonl.gz.

    Emitted long-form: two rows per SV event (one per site). Frame prediction:
    cBioPortal's `site2EffectOnFrame` is a per-event scalar (In_frame / Frame_Shift /
    None) — replicated to both sides so schema is consistent."""
    rows = []
    with gzip.open(jsonl_gz_path, "rt") as f:
        for line in f:
            r = json.loads(line)
            sid = sample_key(r.get("sampleId"))
            if not sid:
                continue
            frame = r.get("site2EffectOnFrame") or None
            eid = f"{r.get('sampleId')}|{r.get('site1HugoSymbol')}--{r.get('site2HugoSymbol')}"
            g1, g2 = r.get("site1HugoSymbol"), r.get("site2HugoSymbol")
            if g1:
                rows.append((sid, g1, g2, "5prime", frame, eid))
            if g2:
                rows.append((sid, g2, g1, "3prime", frame, eid))
    df = pd.DataFrame(rows, columns=[
        "sample_key", "gene_symbol", "partner_gene", "partner_side",
        "frame_pred", "event_id"])
    df["tissue"] = _cbio_study_tissue(study_id)
    df["caller"] = "cbioportal"
    return df[["sample_key", "gene_symbol", "partner_gene", "partner_side",
               "tissue", "frame_pred", "caller", "event_id"]]


def load_cbioportal_all(base_dir: str | Path) -> pd.DataFrame:
    """Load all 32 cBioPortal PanCancer Atlas studies from a local dir with
    `{study_id}/structural_variants.jsonl.gz` sub-paths. Returns concatenated
    long-form."""
    base = Path(base_dir)
    parts: list[pd.DataFrame] = []
    for study_dir in sorted(base.iterdir()):
        if not study_dir.is_dir():
            continue
        sv = study_dir / "structural_variants.jsonl.gz"
        if not sv.exists():
            continue
        parts.append(load_cbioportal_sv(sv, study_dir.name))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------- sample-coverage tables (denominator for is_member=false vs null) ----------

def tumorfusions_assayed_samples(xlsx_path: str | Path) -> pd.DataFrame:
    """Which samples did TumorFusions ATTEMPT to profile? (Denominator for
    false-vs-null.) Comes from File006 'All sample IDs' (10,655 rows).
    Column `barcode` is the full aliquot barcode; return sample-level keys."""
    df = pd.read_excel(xlsx_path, sheet_name="All sample IDs",
                       converters={"barcode": str})
    df = df.rename(columns={"Disease": "tissue"})
    df["sample_key"] = df["barcode"].map(sample_key)
    df = df[df["sample_key"].notna()]
    df["caller"] = "tumorfusions"
    return df[["sample_key", "tissue", "caller"]].drop_duplicates()


def gao_2018_assayed_samples(xlsx_path: str | Path) -> pd.DataFrame:
    """Which samples did Gao 2018 include? Comes from sheet 'TCGA samples used
    in this study'. Header on row 2 (skiprows=1)."""
    df = pd.read_excel(xlsx_path, sheet_name="TCGA samples used in this study",
                       skiprows=1, dtype=str)
    # Column names on row 2 vary — normalize by position for the first two cols.
    df = df.rename(columns={df.columns[0]: "Sample", df.columns[1]: "tissue"})
    df["sample_key"] = df["Sample"].map(sample_key)
    df = df[df["sample_key"].notna()]
    df["caller"] = "gao_2018"
    return df[["sample_key", "tissue", "caller"]].drop_duplicates()


def cbioportal_assayed_samples(base_dir: str | Path) -> pd.DataFrame:
    """Which samples does cBioPortal include per study? From `samples.jsonl.gz`
    per study (the roster; not the SV file, which only lists samples with events)."""
    base = Path(base_dir)
    rows = []
    for study_dir in sorted(base.iterdir()):
        if not study_dir.is_dir():
            continue
        smp = study_dir / "samples.jsonl.gz"
        if not smp.exists():
            continue
        tissue = _cbio_study_tissue(study_dir.name)
        with gzip.open(smp, "rt") as f:
            for line in f:
                r = json.loads(line)
                sid = sample_key(r.get("sampleId"))
                if sid:
                    rows.append((sid, tissue, "cbioportal"))
    return pd.DataFrame(rows, columns=["sample_key", "tissue", "caller"]).drop_duplicates()
