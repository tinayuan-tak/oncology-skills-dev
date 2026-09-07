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
'TCGA-05-4244-01' — which is what we normalize to. After this normalization the
three callers overlap on hundreds of samples (a naive first-4-segment cut yields
zero overlap).
"""

from __future__ import annotations

import gzip
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from methods.catalog_query.read import bucket_key_for

METHOD_VERSION = "0.3.0"  # 0.3.0: + GENIE-SV breadth fields (genie_sv_*) — pan-cohort display sibling
#                            0.2.0: + per-target read_target_summary over the derived S3 product

# ---------- per-target read over the derived consensus product ----------
# The builders above (load_*/build_consensus in cli.py) EMIT the derived product; this reader
# CONSUMES it per-(target, indication) for the fusion-rearrangement-landscape card. Reads the S3
# object with the definitive-vs-transient cache latch used by every other derived reader.
DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "tcga-fusion-consensus-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth) —
# was a hand-typed literal parallel to DERIVED_MANIFEST_ID that could silently drift.
S3_BUCKET, DERIVED_S3_KEY = bucket_key_for(DERIVED_MANIFEST_ID)
_DERIVED_STATUS: Optional[bool] = None

# Recurrence threshold: a fusion is a RECURRENT driver in an indication when it recurs across samples.
# Fusion counts are small (spec: ~5 ALK in LUAD), so the bar is low but > sporadic-singleton.
_RECURRENT_MIN_SAMPLES = 3
# Consensus floor: only count a (sample, gene) fusion supported by >= this many callers, to avoid
# single-caller false positives inflating recurrence. This product is a 3-CALLER CONSENSUS and
# preserves caller_count precisely so the floor can be enforced; the default is therefore MAJORITY
# (>= 2 callers), not the union. A consumer that explicitly wants the 1-caller union passes
# min_callers=1. (A default of 1 would discard the consensus — a single-caller fusion in
# >= _RECURRENT_MIN_SAMPLES samples would be promoted to recurrent_fusion_driver, defeating the
# whole point of a 3-caller product.)
_DEFAULT_MIN_CALLERS = 2


# ---------- streamed S3 read (pyarrow S3FileSystem; NO whole-file download) ----------
# 2026-08-22 data-layer hardening (parquet-storage-standard): the derived consensus payload + its
# sample_coverage sibling are STREAMED over a process-wide pyarrow S3FileSystem
# (pq.read_table over `bucket/key`), replacing the prior boto3 download_file-to-local-cache.
# Both _load_consensus and _load_coverage are ALL-ROWS seams — read_target_summary AND the
# subgroup-stratified panorama in stratified.py each filter the WHOLE frame by their own
# gene/tissue/stratum predicates and reuse it process-wide — so this streams the whole table
# (no filters= pushdown on gene_symbol, which the manifest flags as a low-selectivity secondary
# sort key anyway). The ~1 MB payload / ~0.12 MB coverage transit ONCE per process via the
# lru_cache seam. Mirrors methods/dge_deseq2/read.py:_get_s3fs +
# methods/depmap_common/parquet.py:_stream_table.
import threading

_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1, the onc-compbio bucket).
    Constructing one costs a region-probe + client init, so build it ONCE and share it — pyarrow's
    S3FileSystem is safe for concurrent reads (the parallel card-read pool relies on that)."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs

                _S3FS = pafs.S3FileSystem(region="us-east-1")
    return _S3FS


def _stream_parquet(bucket: str, key: str):
    """Streamed whole-table read of a remote parquet -> pandas (same DataFrame pd.read_parquet
    produced from the downloaded copy — both go through pyarrow's read_table(...).to_pandas()).
    Errors PROPAGATE: a missing object surfaces as pyarrow FileNotFoundError (definitive absence);
    a transient/creds/broken-env error propagates so the caller's absence latch re-raises the real
    cause. No whole-file download."""
    import pyarrow.parquet as pq

    return pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs()).to_pandas()


@lru_cache(maxsize=1)
def _load_consensus():
    """Whole tcga-fusion-consensus-v1 payload as a DataFrame (streamed once, cached process-wide).
    Genuine object-absence (NoSuchKey / 404 / pyarrow FileNotFoundError) latches _DERIVED_STATUS
    and yields an empty frame (honest data_unavailable); a corrupt-parquet / broken-env / transient
    / creds error PROPAGATES (never masked as empty), per the reader-absence-discipline guard."""
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return pd.DataFrame()
    try:
        df = _stream_parquet(S3_BUCKET, DERIVED_S3_KEY)
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            _DERIVED_STATUS = False
            return pd.DataFrame()
        raise
    _DERIVED_STATUS = True
    return df


# sample_coverage.parquet is a SIBLING of the payload at the SAME S3 prefix (not a separate
# manifest) — the assayed-sample denominator (columns: sample_key, tissue, caller). Basename-swap
# the payload key; STREAM it (no download) and degrade to empty on genuine absence so a missing
# companion just keeps freq=None. Small (~0.12 MB) but streamed for consistency with the payload
# seam and to drop the boto3 download_file — read_table over the shared S3FileSystem, no local cache.
_COVERAGE_KEY = DERIVED_S3_KEY.rsplit("/", 1)[0] + "/sample_coverage.parquet"
_COVERAGE_STATUS: Optional[bool] = None


@lru_cache(maxsize=1)
def _load_coverage():
    """Whole sample_coverage sibling as a DataFrame (streamed once, cached). Absence discipline
    mirrors _load_consensus: genuine object-absence -> empty (freq stays None); corrupt / broken-env
    / transient / creds error PROPAGATES."""
    global _COVERAGE_STATUS
    if _COVERAGE_STATUS is False:
        return pd.DataFrame()
    try:
        df = _stream_parquet(S3_BUCKET, _COVERAGE_KEY)
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            _COVERAGE_STATUS = False
            return pd.DataFrame()
        raise
    _COVERAGE_STATUS = True
    return df


def _n_assayed_in_tissue(indication: Optional[str]) -> Optional[int]:
    """Distinct fusion-ASSAYED samples in the indication's tissue(s) — the honest fusion-frequency
    denominator. None when coverage is unavailable OR no indication is given (a pan-tissue frequency
    has no meaningful single denominator → keep freq=None rather than divide by an unknown cohort)."""
    ind = str(indication or "").upper().strip()
    if not ind:
        return None
    cov = _load_coverage()
    if cov is None or cov.empty or "tissue" not in cov.columns:
        return None
    codes = _indication_tissue_codes(ind)
    hit = cov[cov["tissue"].astype(str).str.upper().isin(codes)]
    n = hit["sample_key"].nunique()
    return int(n) if n > 0 else None


# GENIE-SV breadth keys — the pan-cohort (271k panel tumors) complement to the TCGA-consensus
# fusion facts. Panel-coverage-correct DISPLAY facet (verdict-inert). TCGA is deep-tissue but shallow
# (LUAD ~5 ALK); GENIE surfaces 774 ALK-SV NSCLC samples with EML4 the dominant partner.
_GENIE_SV_KEYS = (
    "genie_sv_recurrence_class",
    "genie_sv_recurrence_percentile",
    "genie_sv_frequency",
    "n_sv_samples",
    "n_sv_covered",
    "genie_sv_recurrent_partners",
    "genie_sv_context",
)


def _genie_sv_fields(target: str, indication: Optional[str]) -> dict:
    """The GENIE panel-coverage-correct SV-recurrence fields for the fusion-rearrangement-landscape
    card — the higher-N sibling of the TCGA-consensus fusion facts. Lazily imports genie_sv_recurrence
    and always returns the keys (graceful data_unavailable on any failure/absence), so the card gains
    the GENIE breadth comparator without ever breaking the TCGA path. No indication → no GENIE cohort."""
    default = {
        "genie_sv_recurrence_class": "data_unavailable",
        "genie_sv_recurrence_percentile": None,
        "genie_sv_frequency": None,
        "n_sv_samples": None,
        "n_sv_covered": None,
        "genie_sv_recurrent_partners": [],
        "genie_sv_context": None,
    }
    if not indication:
        return default
    try:
        from methods.genie_sv_recurrence.read import genie_sv_recurrence_for_gene

        g = genie_sv_recurrence_for_gene(target, indication)
        return {k: g.get(k) for k in _GENIE_SV_KEYS}
    except Exception:  # noqa: BLE001
        return default


def _empty_summary(note: str, target: str = None, indication: str = None) -> dict:
    out = {
        "n_samples_with_fusion": 0,
        "fusion_frequency": None,
        "recurrent_partners": [],
        "fusion_class": "data_unavailable",
        "fusion_recurrence_confidence": None,
        "method_version": METHOD_VERSION,
        "_data_note": note,
        "_data_source": DERIVED_MANIFEST_ID,
    }
    # Even when the TCGA product is silent for this target/indication, GENIE-SV breadth may still
    # carry a signal (its cohort is 271k panel tumors, not the 33 TCGA tissues) — surface it.
    out.update(_genie_sv_fields(target, indication) if target else {k: None for k in _GENIE_SV_KEYS})
    return out


def read_target_summary(target: str, indication: str = None, min_callers: int = _DEFAULT_MIN_CALLERS) -> dict:
    """Per-(target, indication) fusion-recurrence summary for the fusion-rearrangement-landscape card.

    Reads the tcga-fusion-consensus-v1 derived product (S3, cached), filters to the target gene and —
    when given — the indication's TCGA tissue code, keeps only (sample, gene) rows with >= min_callers
    caller support, and computes the card contract:
        n_samples_with_fusion  — distinct samples with the target fused (>= min_callers)
        fusion_frequency       — n_samples_with_fusion / n_samples_assayed_in_tissue (None if unknown)
        recurrent_partners     — partner genes seen in >= _RECURRENT_MIN_SAMPLES samples, count-desc
        fusion_class           — recurrent_fusion_driver | sporadic_fusion | no_recurrent_fusion |
                                 data_unavailable
        fusion_recurrence_confidence — high_recurrent_partner | moderate_promiscuous | None
                                 (VERDICT-INERT tier for a recurrent_fusion_driver call; see the
                                 confidence-tier note where fusion_class is assigned)
    data_unavailable (never a fabricated call) when the product is absent or the target has no rows."""
    df = _load_consensus()
    if df is None or df.empty:
        return _empty_summary("fusion_consensus_product_unavailable", target, indication)

    sym = str(target or "").upper().strip()
    sub = df[df["gene_symbol"].astype(str).str.upper() == sym]
    if min_callers > 1:
        sub = sub[sub["caller_count"] >= min_callers]
    # indication → TCGA tissue filter (the product's tissue col is the TCGA disease code)
    ind = str(indication or "").upper().strip()
    if ind:
        # accept COADREAD↔COAD/READ style: match tissue prefix membership loosely
        sub = sub[sub["tissue"].astype(str).str.upper().isin(_indication_tissue_codes(ind))]

    if sub.empty:
        # target present in the product but not in this indication (or filtered out) → no recurrent call
        # (distinct from product-absent: this is a real measured-negative for the indication)
        note = "target_not_fused_in_indication" if ind else "target_not_in_fusion_product"
        out = _empty_summary(note, target, indication)
        out["fusion_class"] = "no_recurrent_fusion" if _target_in_product(df, sym) else "data_unavailable"
        return out

    n_samples = sub["sample_key"].nunique()

    # recurrent partners: aggregate partner lists across all callers, count distinct samples per partner
    partner_samples: dict = {}
    for _, row in sub.iterrows():
        parts = set()
        for col in ("partners_tumorfusions", "partners_gao_2018", "partners_cbioportal"):
            v = row.get(col)
            if v is not None and hasattr(v, "__len__") and not isinstance(v, str):
                parts.update(str(p) for p in v if p)
        for p in parts:
            partner_samples.setdefault(p, set()).add(row["sample_key"])
    recurrent = sorted(
        ((p, len(s)) for p, s in partner_samples.items() if len(s) >= _RECURRENT_MIN_SAMPLES),
        key=lambda x: (-x[1], x[0]),
    )
    recurrent_partners = [{"partner": p, "n_samples": n} for p, n in recurrent]

    # Recurrence confidence tier — VERDICT-INERT, additive.
    #   high_recurrent_partner  = the SAME partner recurs across >= _RECURRENT_MIN_SAMPLES samples
    #                             (EML4-ALK, TMPRSS2-ERG, BCR-ABL1, PML-RARA, ...). Highly precise:
    #                             every driver with a recurrent partner is real; no amplification-driven
    #                             passenger reaches it.
    #   moderate_promiscuous    = the target recurs but no single partner does. A GENUINELY MIXED
    #                             branch: real promiscuous kinase fusions (ROS1, NTRK1, FGFR2,
    #                             BRAF-melanoma — a constant kinase, varying 5' partner) AND
    #                             amplification-driven passenger SVs at an amplified oncogene locus
    #                             (ERBB2, MDM2/SARC) both land here.
    # No structural feature in this product separates the two: neither frequency nor partner-count
    # dispersion distinguishes them. The only real discriminator is gene biology (fusion-competent
    # kinase/TF vs amplification-driven oncogene), which needs an orthogonal signal (OncoKB
    # fusion-competence or a copy-number cross-reference) — out of scope for this product. So we DO NOT
    # demote the promiscuous branch (that would turn ROS1/NTRK1/FGFR2 true drivers into false
    # negatives); we keep fusion_class as-is and expose the confidence tier so a downstream consumer
    # can weight a high vs moderate recurrent call.
    fusion_recurrence_confidence = None
    if recurrent_partners:
        fclass = "recurrent_fusion_driver"
        fusion_recurrence_confidence = "high_recurrent_partner"
    elif n_samples >= _RECURRENT_MIN_SAMPLES:
        fclass = "recurrent_fusion_driver"
        fusion_recurrence_confidence = "moderate_promiscuous"
    else:
        fclass = "sporadic_fusion"

    # frequency = fused samples / ASSAYED samples in the indication tissue (sample_coverage sibling).
    # None when coverage is unavailable or no indication given — never divide by an unknown cohort.
    n_assayed = _n_assayed_in_tissue(indication)
    freq = (n_samples / n_assayed) if n_assayed else None
    return {
        "n_samples_with_fusion": int(n_samples),
        "fusion_frequency": freq,
        "n_assayed_in_tissue": n_assayed,
        "recurrent_partners": recurrent_partners,
        "fusion_class": fclass,
        "fusion_recurrence_confidence": fusion_recurrence_confidence,
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
        "_min_callers": min_callers,
        "_n_events_total": int(sub[["n_events_tumorfusions", "n_events_gao_2018", "n_events_cbioportal"]].sum().sum()),
        # GENIE-SV breadth (pan-cohort, panel-coverage-correct) — additive display sibling.
        **_genie_sv_fields(target, indication),
    }


def _target_in_product(df: pd.DataFrame, sym: str) -> bool:
    return bool((df["gene_symbol"].astype(str).str.upper() == sym).any())


# indication (OncoTree-ish) → set of TCGA disease codes present in the product's `tissue` column.
_INDICATION_TISSUE = {
    "COADREAD": {"COAD", "READ", "COADREAD"},
    "COAD": {"COAD", "COADREAD"},
    "READ": {"READ", "COADREAD"},
    "NSCLC": {"LUAD", "LUSC"},
    "LUAD": {"LUAD"},
    "LUSC": {"LUSC"},
    "HNSC": {"HNSC"},
    "HNSCC": {"HNSC"},
    "BRCA": {"BRCA"},
    "PRAD": {"PRAD"},
    "PAAD": {"PAAD"},
    "STAD": {"STAD"},
    "OV": {"OV"},
    "GBM": {"GBM"},
    "LGG": {"LGG"},
    "BLCA": {"BLCA"},
    "KIRC": {"KIRC"},
    "KIRP": {"KIRP"},
    "KICH": {"KICH"},
    "LIHC": {"LIHC"},
    "SKCM": {"SKCM"},
    "THCA": {"THCA"},
    "UCEC": {"UCEC"},
    "CESC": {"CESC"},
    "ESCA": {"ESCA"},
    "SARC": {"SARC"},
}


def _indication_tissue_codes(ind: str) -> set:
    """Map an indication code to the TCGA disease codes it covers; fall back to the code itself."""
    return _INDICATION_TISSUE.get(ind, {ind})


# ---------- barcode normalization ----------

_SAMPLE_KEY_RE = re.compile(r"^(TCGA-[A-Z0-9]+-[A-Z0-9]+-\d{2})")


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
    df = pd.read_excel(xlsx_path, sheet_name="Cancer fusions", converters={"Gene_A": str, "Gene_B": str, "Sample": str})
    # Two rows per event: one per side.
    a = df.rename(columns={"Gene_A": "gene_symbol", "Gene_B": "partner_gene", "Frame Prediction": "frame_pred"})
    a = a[["Tissue", "Sample", "gene_symbol", "partner_gene", "frame_pred"]].copy()
    a["partner_side"] = "5prime"
    b = df.rename(columns={"Gene_B": "gene_symbol", "Gene_A": "partner_gene", "Frame Prediction": "frame_pred"})
    b = b[["Tissue", "Sample", "gene_symbol", "partner_gene", "frame_pred"]].copy()
    b["partner_side"] = "3prime"
    out = pd.concat([a, b], ignore_index=True)
    out["sample_key"] = out["Sample"].map(sample_key)
    out = out.rename(columns={"Tissue": "tissue"})
    out["caller"] = "tumorfusions"
    out["event_id"] = (
        out["Sample"].astype(str) + "|" + out["gene_symbol"].astype(str) + "--" + out["partner_gene"].astype(str)
    )
    out = out[out["sample_key"].notna() & out["gene_symbol"].notna()]
    return out[
        ["sample_key", "gene_symbol", "partner_gene", "partner_side", "tissue", "frame_pred", "caller", "event_id"]
    ]


# ---------- Gao 2018 (Cell Reports) ----------


def load_gao_2018(xlsx_path: str | Path) -> pd.DataFrame:
    """Load 'Final fusion call set' sheet (25,664 rows, 33 TCGA cancer types).

    Header row is row 2 (skiprows=1). Columns: Cancer, Sample, Fusion (5'--3'),
    Junction, Spanning, Breakpoint1, Breakpoint2. Fusion string 'A--B' splits into
    5' and 3' partners. NO frame prediction column — emitted as None."""
    df = pd.read_excel(
        xlsx_path, sheet_name="Final fusion call set", skiprows=1, converters={"Sample": str, "Fusion": str}
    )
    # Parse 'A--B' -> 5', 3'
    fus = df["Fusion"].astype(str).str.split("--", n=1, expand=True)
    df = df.assign(gene_5p=fus[0], gene_3p=fus[1])
    a = df.rename(columns={"gene_5p": "gene_symbol", "gene_3p": "partner_gene", "Cancer": "tissue"})
    a = a[["tissue", "Sample", "gene_symbol", "partner_gene", "Fusion"]].copy()
    a["partner_side"] = "5prime"
    b = df.rename(columns={"gene_3p": "gene_symbol", "gene_5p": "partner_gene", "Cancer": "tissue"})
    b = b[["tissue", "Sample", "gene_symbol", "partner_gene", "Fusion"]].copy()
    b["partner_side"] = "3prime"
    out = pd.concat([a, b], ignore_index=True)
    out["sample_key"] = out["Sample"].map(sample_key)
    out["frame_pred"] = None  # Gao 2018 does not publish frame predictions.
    out["caller"] = "gao_2018"
    out["event_id"] = out["Sample"].astype(str) + "|" + out["Fusion"].astype(str)
    out = out[out["sample_key"].notna() & out["gene_symbol"].notna() & (out["gene_symbol"] != "nan")]
    return out[
        ["sample_key", "gene_symbol", "partner_gene", "partner_side", "tissue", "frame_pred", "caller", "event_id"]
    ]


# ---------- cBioPortal TCGA PanCancer Atlas (32 studies) ----------

_STUDY_TO_TISSUE = {
    # cBioPortal study prefix -> TCGA disease code
    "acc_": "ACC",
    "blca_": "BLCA",
    "brca_": "BRCA",
    "cesc_": "CESC",
    "chol_": "CHOL",
    "coadread_": "COADREAD",
    "dlbc_": "DLBC",
    "esca_": "ESCA",
    "gbm_": "GBM",
    "hnsc_": "HNSC",
    "kich_": "KICH",
    "kirc_": "KIRC",
    "kirp_": "KIRP",
    "laml_": "LAML",
    "lgg_": "LGG",
    "lihc_": "LIHC",
    "luad_": "LUAD",
    "lusc_": "LUSC",
    "meso_": "MESO",
    "ov_": "OV",
    "paad_": "PAAD",
    "pcpg_": "PCPG",
    "prad_": "PRAD",
    "sarc_": "SARC",
    "skcm_": "SKCM",
    "stad_": "STAD",
    "tgct_": "TGCT",
    "thca_": "THCA",
    "thym_": "THYM",
    "ucec_": "UCEC",
    "ucs_": "UCS",
    "uvm_": "UVM",
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
    df = pd.DataFrame(
        rows, columns=["sample_key", "gene_symbol", "partner_gene", "partner_side", "frame_pred", "event_id"]
    )
    df["tissue"] = _cbio_study_tissue(study_id)
    df["caller"] = "cbioportal"
    return df[
        ["sample_key", "gene_symbol", "partner_gene", "partner_side", "tissue", "frame_pred", "caller", "event_id"]
    ]


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
    df = pd.read_excel(xlsx_path, sheet_name="All sample IDs", converters={"barcode": str})
    df = df.rename(columns={"Disease": "tissue"})
    df["sample_key"] = df["barcode"].map(sample_key)
    df = df[df["sample_key"].notna()]
    df["caller"] = "tumorfusions"
    return df[["sample_key", "tissue", "caller"]].drop_duplicates()


def gao_2018_assayed_samples(xlsx_path: str | Path) -> pd.DataFrame:
    """Which samples did Gao 2018 include? Comes from sheet 'TCGA samples used
    in this study'. Header on row 2 (skiprows=1)."""
    df = pd.read_excel(xlsx_path, sheet_name="TCGA samples used in this study", skiprows=1, dtype=str)
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
