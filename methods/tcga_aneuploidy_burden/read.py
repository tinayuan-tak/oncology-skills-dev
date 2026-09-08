"""tcga_aneuploidy_burden.read — per-indication genome-instability burden summary.

Reads PanCanAtlas seg_based_scores.tsv (per-sample frac_altered = fraction of genome CN-altered),
scopes to an indication's TCGA project(s) via merged_sample_quality_annotations (patient_barcode →
cancer type — the SAME join functional_gene_state uses), and summarizes the cohort's aneuploidy
burden distribution + a coarse cohort class. Indication-level (aneuploidy is genome-wide, not per-gene).
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import s3_uri_for

# Precomputed per-indication HRD-scar product (tcga-hrd-scar-per-indication-v1): materializes exactly
# what hrd_score_for_indication computes, so the reader can read ONE indication's row (~kB) instead of
# streaming + parsing the full ~253 MB PanCanAtlas ABSOLUTE segtabs on every call (the dominant cost of
# the genomic-instability-state card's HRD arm). Resolved lazily (not a module-level constant) so import
# never breaks before the manifest is registered.
_HRD_PRODUCT_ID = "tcga-hrd-scar-per-indication-v1"
_HRD_PRODUCT_FIELDS = (
    "hrd_class",
    "hrd_high_fraction",
    "n_hrd_high",
    "median_hrd_score",
    "p75_hrd_score",
    "n_samples",
    "hrd_context",
    "method_version",
    "_data_source",
)

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
PANCAN_PREFIX = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27"
SEG_SCORES_KEY = f"{PANCAN_PREFIX}/seg_based_scores.tsv"
SAMPLE_ANNOT_KEY = f"{PANCAN_PREFIX}/merged_sample_quality_annotations.tsv"
# ABSOLUTE per-sample purity/ploidy/genome-doublings (the WGD source — sibling of seg_based_scores
# in the SAME PanCanAtlas snapshot). `array` = sample-level barcode (TCGA-OR-A5J1-01), joined to
# cancer type via the same _barcode_to_patient truncation + merged_sample_quality_annotations.
ABSOLUTE_KEY = f"{PANCAN_PREFIX}/TCGA_mastercalls.abs_tables_JSedit.fixed.txt"
# ABSOLUTE allele-specific SEGMENTS (Modal_HSCN_1/2, LOH, Length) — the HRD genomic-scar substrate.
# Sibling of abs_tables in the SAME snapshot; the ~1.9M-row per-segment table (one row per CN segment,
# ~11K samples). The HRD scar counts (LOH/LST/ntAI) are computed from these; see hrd.py.
ABSOLUTE_SEGTABS_KEY = f"{PANCAN_PREFIX}/TCGA_mastercalls.abs_segtabs.fixed.txt"
# Cohort WGD-prevalence class cutoffs on the FRACTION of samples with >=1 genome doubling
# (Genome doublings >= 1). Pan-cancer WGD prevalence is ~30-40% (Bielski 2018); a cohort well
# above that is WGD-enriched, well below is WGD-rare.
_WGD_HIGH_FRACTION = 0.50
_WGD_LOW_FRACTION = 0.20

# framework indication → TCGA `cancer type` code(s) in merged_sample_quality_annotations
# (mirrors functional_gene_state.INDICATION_TO_TCGA; kept local to avoid cross-method coupling).
INDICATION_TO_TCGA = {
    "COADREAD": ("COAD", "READ"),
    "COAD": ("COAD",),
    "READ": ("READ",),
    "NSCLC": ("LUAD", "LUSC"),
    "LUAD": ("LUAD",),
    "LUSC": ("LUSC",),
    "PAAD": ("PAAD",),
    "PDAC": ("PAAD",),
    "GC": ("STAD",),
    "STAD": ("STAD",),
    "BRCA": ("BRCA",),
    "HNSC": ("HNSC",),
    "HNSCC": ("HNSC",),
    "ESCA": ("ESCA",),
    "OV": ("OV",),
    "PRAD": ("PRAD",),
    "SKCM": ("SKCM",),
}
# Cohort aneuploidy-burden class cutoffs on MEDIAN frac_altered (fraction of genome CN-altered).
# Anchored to the pan-cancer spread (Taylor 2018: quiet genomes ~<0.1, highly aneuploid >~0.4).
_HIGH_MEDIAN = 0.40
_LOW_MEDIAN = 0.10

# MSI (microsatellite instability) is patient-side available ONLY for CRC + STAD (the two TCGA
# marker papers that ship an MSI status column). This is a genuine coverage boundary, NOT a wiring
# gap — every OTHER indication returns msi_class=data_unavailable (never a fabricated 0% MSI-H).
# Each entry: framework indication → (marker-paper CSV, MSI column name). The column differs by file
# (CRC: MSI_status "MSI-H"/"MSI-L"/"MSS"; STAD: "MSI.status" same values).
_MARKER_PAPER_PREFIX = "data-catalog/sources/tcga-marker-papers/subtypes-2018"
MSI_LABEL_SOURCE = {
    "COADREAD": (f"{_MARKER_PAPER_PREFIX}/tcga_subtype_CRC.csv", "MSI_status"),
    "COAD": (f"{_MARKER_PAPER_PREFIX}/tcga_subtype_CRC.csv", "MSI_status"),
    "READ": (f"{_MARKER_PAPER_PREFIX}/tcga_subtype_CRC.csv", "MSI_status"),
    "GC": (f"{_MARKER_PAPER_PREFIX}/tcga_subtype_STAD.csv", "MSI.status"),
    "STAD": (f"{_MARKER_PAPER_PREFIX}/tcga_subtype_STAD.csv", "MSI.status"),
}
# Cohort MSI class cutoffs on the FRACTION of samples that are MSI-HIGH. MSI-H prevalence is ~14%
# in CRC and ~22% in STAD (TCGA marker papers); a cohort above the high bar is MSI-enriched.
_MSI_HIGH_FRACTION = 0.15
_MSI_LOW_FRACTION = 0.05

# MODEL-side MSI (DepMap cell lines) — the complementary arm to the patient marker-paper labels.
# OmicsGlobalSignatures.csv carries MSIScore (MSIsensor2) per ModelID for ALL lineages, so the model
# arm COVERS the indications the patient labels miss (NSCLC/PAAD have no patient MSI, but DO have
# cell-line MSIScore). Cell-line MSI is a MODEL-cohort property, distinct from patient prevalence.
DEPMAP_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1"
DEPMAP_GLOBAL_SIGNATURES_KEY = f"{DEPMAP_PREFIX}/OmicsGlobalSignatures.csv"
DEPMAP_MODEL_KEY = f"{DEPMAP_PREFIX}/Model.csv"
# MSIsensor2 MSI-H threshold: score >= 20 (the standard MSIsensor2 cutoff; the MSIScore distribution
# is bimodal with a clean gap between the MSS bulk (~2 median) and the MSI-H cluster (>>20)).
_MODEL_MSI_HIGH_SCORE = 20.0
# framework indication → DepMap OncotreeLineage (26q1 STRINGS — release-correct; note the subgroup
# assigner's INDICATION_TO_DEPMAP_LINEAGE is STALE for 26q1: 26q1 merged Stomach+Esophagus into
# "Esophagus/Stomach" and Ovary into "Ovary/Fallopian Tube", so STAD/GC map to the merged lineage
# (broader than gastric alone — includes esophageal, mirroring the GENIE Esophagogastric breadth note).
INDICATION_TO_DEPMAP_LINEAGE = {
    "COADREAD": ("Bowel",),
    "COAD": ("Bowel",),
    "READ": ("Bowel",),
    "NSCLC": ("Lung",),
    "LUAD": ("Lung",),
    "LUSC": ("Lung",),
    "SCLC": ("Lung",),
    "PAAD": ("Pancreas",),
    "PDAC": ("Pancreas",),
    "GC": ("Esophagus/Stomach",),
    "STAD": ("Esophagus/Stomach",),
    "ESCA": ("Esophagus/Stomach",),
    "HNSC": ("Head and Neck",),
    "HNSCC": ("Head and Neck",),
    "OV": ("Ovary/Fallopian Tube",),
    "UCEC": ("Uterus",),
}

# MODEL-side mutational-SIGNATURE arm (DepMap OmicsMolecularSignatureMatrix, SBS exposure COUNTS per
# ModelID). The decision-useful, therapeutically-actionable etiologies:
#   - MMR-deficiency signatures → an INDEPENDENT cross-validation of the MSI axis (different signal:
#     mutation spectrum vs microsatellite length). Tracks the MSI arm closely (Uterus/Bowel high).
#   - HRD signature SBS3 → a WEAK PARP-sensitivity proxy. SBS3 is flat/featureless and rarely DOMINATES
#     a cell line's spectrum (swamped by clock-like SBS40), so it is reported at a LOW presence
#     threshold + explicitly caveated; a real HRD score needs a scarHRD-style genomic-scar derivation
#     (deferred). We do NOT overclaim HRD from SBS3 alone.
DEPMAP_SIGNATURE_MATRIX_KEY = f"{DEPMAP_PREFIX}/OmicsMolecularSignatureMatrix.csv"
# COSMIC SBS → etiology groups (from MolecularSignatureEtiologies.csv; the actionable subset).
_MMR_SIGNATURES = ("SBS6", "SBS14", "SBS15", "SBS20", "SBS21", "SBS26", "SBS44")  # mismatch-repair-deficiency
_HRD_SIGNATURE = "SBS3"  # defective homologous recombination
# A cell line is "MMR-signature-high" when MMR signatures make up >= 20% of its SBS burden (a
# dominant MMR spectrum); the cohort class is the FRACTION of lines that clear it (mirrors MSI —
# MMR-deficiency is a subset phenomenon, so the median is uninformative; the tail carries the signal).
_MMR_SIG_HIGH_FRACTION = 0.20  # per-model: MMR-signature fraction >= this = MMR-sig-high line
_MMR_COHORT_HIGH = 0.15  # cohort: >= this fraction of lines MMR-sig-high → mmr_signature_enriched
_MMR_COHORT_LOW = 0.05  # cohort: <= this → mmr_signature_rare
# HRD (SBS3) presence: LOW per-model threshold (SBS3 rarely dominates), reported as a weak proxy only.
_HRD_SIG_PRESENT_FRACTION = 0.10  # per-model: SBS3 >= 10% of burden = "HRD-signature-present" (weak)


from methods.target_id_sidecar import ensure_aws_profile


def _s3_read_bytes(key: str) -> bytes:
    import boto3

    ensure_aws_profile()
    s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")
    return s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()


def _barcode_to_patient(sample: str) -> str:
    """seg_based_scores Sample is a 4-segment barcode (TCGA-02-0001-01); the annotation table keys
    on the 3-segment patient barcode (TCGA-02-0001). Truncate to join."""
    parts = str(sample).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(sample)


@lru_cache(maxsize=1)
def _load_sample_cancer_types() -> dict:
    """{patient_barcode: cancer_type} from merged_sample_quality_annotations — the SHARED barcode→
    cancer-type crosswalk that gates EVERY sample's indication join here and in tcga_patient_cn.

    A crosswalk either loads or it does NOT (ref methods/target_id_sidecar.read_resolver_sidecar_map):
      * transient / creds / broken-env failure (throttle, ExpiredToken, missing pandas) -> re-raise so
        the live-read seam surfaces an honest _live_read_error rather than collapsing the join;
      * a well-formed read that yields an EMPTY map -> raise too, because returning {} would silently
        collapse every join to "no samples" (the null-strata bug class — mirrors the empty-crosswalk
        guard);
      * ONLY a genuine NoSuchKey/404 on the annotation object is a real absence -> {}.
    """
    import pandas as pd

    from methods.target_id_sidecar import is_definitively_absent

    try:
        raw = _s3_read_bytes(SAMPLE_ANNOT_KEY)
        df = pd.read_csv(io.BytesIO(raw), sep="\t", usecols=["patient_barcode", "cancer type"], dtype=str)
        df = df.dropna(subset=["patient_barcode", "cancer type"])
        out = dict(zip(df["patient_barcode"], df["cancer type"]))
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return {}
        raise
    if not out:
        raise ValueError(
            f"sample→cancer-type crosswalk s3://{S3_BUCKET}/{SAMPLE_ANNOT_KEY} produced an EMPTY map "
            "(well-formed read, no usable barcode→cancer-type pairs) — a broken/empty product, NOT a "
            "data gap; returning {} here would silently collapse every indication join."
        )
    return out


@lru_cache(maxsize=1)
def _load_seg_scores():
    """seg_based_scores.tsv → DataFrame (Sample, frac_altered, n_segs, n_extrema). Empty on failure."""
    import pandas as pd

    try:
        raw = _s3_read_bytes(SEG_SCORES_KEY)
        return pd.read_csv(io.BytesIO(raw), sep="\t")
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return pd.DataFrame()  # genuine object-absence → honest empty (verdict-inert)
        raise  # broken-env / transient / creds → honest _live_read_error


@lru_cache(maxsize=1)
def _load_absolute():
    """ABSOLUTE abs_tables → DataFrame (array=sample barcode, purity, ploidy, Genome doublings, …).
    The WGD/ploidy source. Empty on failure."""
    import pandas as pd

    try:
        raw = _s3_read_bytes(ABSOLUTE_KEY)
        return pd.read_csv(io.BytesIO(raw), sep="\t")
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return pd.DataFrame()  # genuine object-absence → honest empty (verdict-inert)
        raise  # broken-env / transient / creds → honest _live_read_error


@lru_cache(maxsize=1)
def _load_absolute_segtabs():
    """ABSOLUTE allele-specific segtabs → DataFrame (Sample, Chromosome, Start, End, Length,
    Modal_HSCN_1, Modal_HSCN_2, LOH, …). The HRD genomic-scar substrate (~1.9M rows). Empty on
    failure. Only the columns HRD scoring needs are read (keeps the ~130 MB file lean)."""
    import pandas as pd

    try:
        raw = _s3_read_bytes(ABSOLUTE_SEGTABS_KEY)
        return pd.read_csv(
            io.BytesIO(raw),
            sep="\t",
            usecols=["Sample", "Chromosome", "Start", "End", "Length", "Modal_HSCN_1", "Modal_HSCN_2", "LOH"],
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return pd.DataFrame()  # genuine object-absence → honest empty (verdict-inert)
        raise  # broken-env / transient / creds → honest _live_read_error


def _hrd_from_product(indication: str):
    """Read ONE indication's HRD summary from the precomputed product (per-indication pushdown, ~kB).

    Returns the summary dict (SAME shape/values _hrd_score_for_indication_live produces — the product
    materialized that fn's output) or None when the product is UNREACHABLE (manifest not registered →
    s3_uri_for raises; object absent → FileNotFoundError/404) OR the indication is not in the product
    (→ live fallback covers indications added after the last build). A transient/creds error re-raises."""
    try:
        uri = s3_uri_for(_HRD_PRODUCT_ID)
    except Exception:  # noqa: BLE001  # absence-discipline: exempt -- LOCAL catalog manifest lookup, not an S3 read; a raise means the derived manifest is not registered → fall back to the live segtabs computation
        return None
    try:
        import pandas as pd
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        path = uri.replace("s3://", "", 1)
        df = pq.read_table(
            path, filesystem=fs.S3FileSystem(), filters=[("indication", "=", str(indication or "").upper().strip())]
        ).to_pandas()
        if df.empty:
            return None  # indication not in the product → live fallback
        row = df.iloc[0]

        def _num(v, cast):
            return None if pd.isna(v) else cast(v)

        # Reconstruct the EXACT python types _hrd_score_for_indication_live returns (parquet round-trips
        # numpy types) so the emitted card summary is byte-identical to the live path.
        return {
            "hrd_class": None if pd.isna(row["hrd_class"]) else str(row["hrd_class"]),
            "hrd_high_fraction": _num(row["hrd_high_fraction"], float),
            "n_hrd_high": int(row["n_hrd_high"]),
            "median_hrd_score": _num(row["median_hrd_score"], float),
            "p75_hrd_score": _num(row["p75_hrd_score"], float),
            "n_samples": int(row["n_samples"]),
            "hrd_context": None if pd.isna(row["hrd_context"]) else str(row["hrd_context"]),
            "method_version": str(row["method_version"]),
            "_data_source": None if pd.isna(row["_data_source"]) else str(row["_data_source"]),
        }
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return None  # product object genuinely absent → live segtabs fallback


def hrd_score_for_indication(indication: str) -> dict:
    """Per-indication homologous-recombination-deficiency (HRD) genomic-scar summary — a scar
    score (HRD-LOH + LST + ntAI). Cohort-level, target-independent.

    Prefers the precomputed per-indication product (tcga-hrd-scar-per-indication-v1; ~kB pushdown);
    falls back to the live ~253 MB ABSOLUTE-segtabs computation when the product is unreachable or the
    indication is absent from it. Byte-identical either way (the product materialized this fn's output)."""
    prod = _hrd_from_product(indication)
    if prod is not None:
        return prod
    return _hrd_score_for_indication_live(indication)


def _hrd_score_for_indication_live(indication: str) -> dict:
    """LIVE HRD computation from the PanCanAtlas ABSOLUTE allele-specific segtabs (the fallback + the
    substrate the product is built from). NOTE: prior to the product, this was hrd_score_for_indication.

    Computes the three-component HRD score per sample from the PanCanAtlas ABSOLUTE allele-specific
    segments (see hrd.py), scopes to the indication's TCGA project(s) via the same barcode→cancer-type
    join, and returns the cohort HRD-high prevalence (score >= 42, Myriad myChoice cutoff) + the
    score distribution. data_unavailable when the file/indication is unresolvable."""
    import numpy as np

    from . import hrd as _hrd

    codes = INDICATION_TO_TCGA.get(str(indication or "").upper().strip())
    if not codes:
        return _hrd_unavailable(f"no TCGA project mapping for indication={indication!r}")
    seg = _load_absolute_segtabs()
    if seg is None or seg.empty or "Modal_HSCN_1" not in seg.columns:
        return _hrd_unavailable("ABSOLUTE allele-specific segtabs unavailable")
    cancer = _load_sample_cancer_types()
    if not cancer:
        return _hrd_unavailable("sample→cancer-type annotation unavailable")

    seg = seg.copy()
    seg["_patient"] = seg["Sample"].map(_barcode_to_patient)
    seg["_ctype"] = seg["_patient"].map(cancer)
    sub = seg[seg["_ctype"].isin(set(codes))]
    if sub.empty:
        return _hrd_unavailable(f"no ABSOLUTE segment samples for {indication} ({codes})")

    scores: list[int] = []
    for _sample, grp in sub.groupby("Sample"):
        scars = _hrd.hrd_scars_for_sample(grp.to_dict("records"))
        scores.append(scars["hrd_score"])
    scores_arr = np.array(scores, dtype=float)
    n = len(scores_arr)
    n_high = int((scores_arr >= _hrd.HRD_HIGH_SCORE).sum())
    frac = n_high / n if n else None
    return {
        "hrd_class": _hrd.classify_hrd_cohort(frac),
        "hrd_high_fraction": frac,
        "n_hrd_high": n_high,
        "median_hrd_score": float(np.median(scores_arr)) if n else None,
        "p75_hrd_score": float(np.percentile(scores_arr, 75)) if n else None,
        "n_samples": n,
        "hrd_context": (
            f"{indication}: {frac:.0%} of {n} PanCanAtlas ABSOLUTE samples are HRD-high "
            f"(genomic-scar score >= {_hrd.HRD_HIGH_SCORE}: HRD-LOH + LST + ntAI; median score "
            f"{np.median(scores_arr):.0f}); cohort-level PARP-sensitivity context, target-independent. "
            f"A real genomic-scar score — supersedes the SBS3 weak proxy."
        ),
        "method_version": "0.3.0",
        "_data_source": "gdc-pancanatlas-cnv-2018",
    }


def _hrd_unavailable(note: str) -> dict:
    return {
        "hrd_class": "data_unavailable",
        "hrd_high_fraction": None,
        "n_hrd_high": 0,
        "median_hrd_score": None,
        "p75_hrd_score": None,
        "n_samples": 0,
        "hrd_context": None,
        "method_version": "0.3.0",
        "_data_note": note,
    }


def _classify_wgd(wgd_fraction: Optional[float]) -> str:
    if wgd_fraction is None:
        return "data_unavailable"
    if wgd_fraction >= _WGD_HIGH_FRACTION:
        return "wgd_enriched"
    if wgd_fraction <= _WGD_LOW_FRACTION:
        return "wgd_rare"
    return "wgd_intermediate"


def wgd_summary_for_indication(indication: str) -> dict:
    """Per-indication whole-genome-doubling (WGD) prevalence + ploidy summary from PanCanAtlas
    ABSOLUTE. Cohort-level, target-independent (genome-wide phenotype — sibling of the aneuploidy
    burden). Returns wgd_class {wgd_enriched / wgd_intermediate / wgd_rare / data_unavailable},
    the WGD fraction (samples with >=1 genome doubling), median ploidy + purity, n_samples.
    data_unavailable when the file/indication is unresolvable."""
    import numpy as np

    codes = INDICATION_TO_TCGA.get(str(indication or "").upper().strip())
    if not codes:
        return _wgd_unavailable(f"no TCGA project mapping for indication={indication!r}")
    absol = _load_absolute()
    if absol is None or absol.empty or "Genome doublings" not in absol.columns:
        return _wgd_unavailable("ABSOLUTE abs_tables unavailable")
    cancer = _load_sample_cancer_types()
    if not cancer:
        return _wgd_unavailable("sample→cancer-type annotation unavailable")

    df = absol.copy()
    df["_patient"] = df["array"].map(_barcode_to_patient)
    df["_ctype"] = df["_patient"].map(cancer)
    sub = df[df["_ctype"].isin(set(codes))]
    gd = sub["Genome doublings"].dropna().astype(float)
    if len(gd) == 0:
        return _wgd_unavailable(f"no ABSOLUTE samples for {indication} ({codes})")

    wgd_fraction = float((gd >= 1).mean())
    ploidy = sub["ploidy"].dropna().astype(float) if "ploidy" in sub.columns else np.array([])
    purity = sub["purity"].dropna().astype(float) if "purity" in sub.columns else np.array([])
    return {
        "wgd_class": _classify_wgd(wgd_fraction),
        "wgd_fraction": wgd_fraction,
        "n_wgd_samples": int((gd >= 1).sum()),
        "median_ploidy": float(np.median(ploidy)) if len(ploidy) else None,
        "median_purity": float(np.median(purity)) if len(purity) else None,
        "n_samples": int(len(gd)),
        "wgd_context": (
            f"{indication}: {wgd_fraction:.0%} of {len(gd)} PanCanAtlas ABSOLUTE samples carry "
            f">=1 whole-genome doubling (median ploidy "
            f"{('%.1f' % np.median(ploidy)) if len(ploidy) else 'n/a'}); cohort-level, "
            f"target-independent genome-state context"
        ),
        "method_version": "0.2.0",
        "_data_source": "gdc-pancanatlas-cnv-2018",
    }


def _wgd_unavailable(note: str) -> dict:
    return {
        "wgd_class": "data_unavailable",
        "wgd_fraction": None,
        "n_wgd_samples": 0,
        "median_ploidy": None,
        "median_purity": None,
        "n_samples": 0,
        "wgd_context": None,
        "method_version": "0.2.0",
        "_data_note": note,
    }


@lru_cache(maxsize=4)
def _load_msi_labels(key: str, column: str) -> tuple:
    """(MSI-status, ...) values from a marker-paper subtype CSV. Cached per (file, column).
    Returns a tuple of raw status strings (MSI-H / MSI-L / MSS / …). Empty on failure."""
    import pandas as pd

    try:
        raw = _s3_read_bytes(key)
        df = pd.read_csv(io.BytesIO(raw))
        if column not in df.columns:
            return tuple()
        return tuple(df[column].dropna().astype(str))
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return tuple()  # genuine object-absence → honest empty (verdict-inert)
        raise  # broken-env / transient / creds → honest _live_read_error


def _classify_msi(msi_high_fraction: Optional[float]) -> str:
    if msi_high_fraction is None:
        return "data_unavailable"
    if msi_high_fraction >= _MSI_HIGH_FRACTION:
        return "msi_high_enriched"
    if msi_high_fraction <= _MSI_LOW_FRACTION:
        return "mss_dominant"
    return "msi_intermediate"


def msi_summary_for_indication(indication: str) -> dict:
    """Per-indication microsatellite-instability (MSI) prevalence from the TCGA marker-paper
    subtype labels. Cohort-level, target-independent. PATIENT-SIDE COVERAGE IS CRC + STAD ONLY —
    every other indication returns data_unavailable (a coverage boundary, NOT a measured 0%).

    Returns msi_class {msi_high_enriched / msi_intermediate / mss_dominant / data_unavailable} +
    the MSI-high fraction, MSI-H/MSI-L/MSS counts, n_samples."""
    ind = str(indication or "").upper().strip()
    src = MSI_LABEL_SOURCE.get(ind)
    if src is None:
        return _msi_unavailable(
            f"no patient-side MSI labels for {indication!r} (CRC + STAD only in TCGA marker papers)"
        )
    key, column = src
    labels = _load_msi_labels(key, column)
    if not labels:
        return _msi_unavailable(f"MSI label file/column unresolvable ({key}::{column})")

    # Normalize: MSI-H / MSI-L / MSS (marker papers use these; treat anything else as non-evaluable).
    def _norm(v):
        u = v.upper().replace(" ", "").replace("_", "-")
        if u in ("MSI-H", "MSIH"):
            return "MSI-H"
        if u in ("MSI-L", "MSIL"):
            return "MSI-L"
        if u in ("MSS",):
            return "MSS"
        return None

    normed = [n for n in (_norm(v) for v in labels) if n is not None]
    n = len(normed)
    if n == 0:
        return _msi_unavailable(f"no evaluable MSI labels for {indication}")
    n_high = sum(1 for x in normed if x == "MSI-H")
    n_low = sum(1 for x in normed if x == "MSI-L")
    n_mss = sum(1 for x in normed if x == "MSS")
    frac = n_high / n
    return {
        "msi_class": _classify_msi(frac),
        "msi_high_fraction": frac,
        "n_msi_high": n_high,
        "n_msi_low": n_low,
        "n_mss": n_mss,
        "n_samples": n,
        "msi_context": (
            f"{indication}: {frac:.0%} MSI-high ({n_high}/{n} evaluable TCGA marker-paper samples; "
            f"{n_low} MSI-L, {n_mss} MSS); cohort-level, target-independent. MSI patient-labels are "
            f"CRC + STAD only."
        ),
        "method_version": "0.2.0",
        "_data_source": "tcga-marker-papers-subtypes-2018",
    }


def _msi_unavailable(note: str) -> dict:
    return {
        "msi_class": "data_unavailable",
        "msi_high_fraction": None,
        "n_msi_high": 0,
        "n_msi_low": 0,
        "n_mss": 0,
        "n_samples": 0,
        "msi_context": None,
        "method_version": "0.2.0",
        "_data_note": note,
    }


@lru_cache(maxsize=1)
def _load_model_msi_by_lineage():
    """{OncotreeLineage: [MSIScore, ...]} from DepMap OmicsGlobalSignatures joined to Model.csv,
    deduped to one row per ModelID. Empty on failure. The model-side MSI substrate (all lineages)."""
    import pandas as pd

    try:
        sig = pd.read_csv(io.BytesIO(_s3_read_bytes(DEPMAP_GLOBAL_SIGNATURES_KEY)))
        model = pd.read_csv(io.BytesIO(_s3_read_bytes(DEPMAP_MODEL_KEY)), usecols=["ModelID", "OncotreeLineage"])
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return {}  # genuine object-absence → honest empty (verdict-inert)
        raise  # broken-env / transient / creds → honest _live_read_error
    if "MSIScore" not in sig.columns or "ModelID" not in sig.columns:
        return {}
    sig = sig.dropna(subset=["MSIScore"]).drop_duplicates(subset=["ModelID"])  # one row per model
    merged = sig.merge(model, on="ModelID", how="inner")
    out: dict = {}
    for lineage, grp in merged.groupby("OncotreeLineage"):
        out[str(lineage)] = [float(v) for v in grp["MSIScore"]]
    return out


def model_msi_summary_for_indication(indication: str) -> dict:
    """Per-indication MODEL-side (DepMap cell-line) MSI prevalence from OmicsGlobalSignatures MSIScore
    (MSIsensor2). The complement to the patient marker-paper labels — covers ALL lineages (incl. the
    NSCLC/PAAD that patient labels miss). Cell-line cohort property, target-independent.

    Returns model_msi_class {msi_high_enriched / msi_intermediate / mss_dominant / data_unavailable}
    on the fraction of cell lines with MSIScore >= 20 (MSIsensor2 MSI-H), + model_msi_high_fraction,
    n_model_msi_high, n_model_lines. data_unavailable when no lineage mapping or the DepMap file is
    unresolvable (NOT a fabricated 0%)."""
    lineages = INDICATION_TO_DEPMAP_LINEAGE.get(str(indication or "").upper().strip())
    if not lineages:
        return _model_msi_unavailable(f"no DepMap lineage mapping for {indication!r}")
    by_lin = _load_model_msi_by_lineage()
    if not by_lin:
        return _model_msi_unavailable("DepMap OmicsGlobalSignatures/Model unresolvable")
    scores = [s for lin in lineages for s in by_lin.get(lin, [])]
    n = len(scores)
    if n == 0:
        return _model_msi_unavailable(f"no DepMap cell lines for {indication} ({lineages})")
    n_high = sum(1 for s in scores if s >= _MODEL_MSI_HIGH_SCORE)
    frac = n_high / n
    return {
        "model_msi_class": _classify_msi(frac),  # reuse the same 0.15/0.05 fraction cutoffs
        "model_msi_high_fraction": frac,
        "n_model_msi_high": n_high,
        "n_model_lines": n,
        "model_msi_context": (
            f"{indication}: {frac:.0%} of {n} DepMap {'/'.join(lineages)} cell lines are MSI-high "
            f"(MSIsensor2 MSIScore >= {_MODEL_MSI_HIGH_SCORE:.0f}); MODEL-cohort property, "
            f"target-independent — the all-lineage complement to the CRC+STAD-only patient labels."
        ),
        "method_version": "0.2.0",
        "_data_source": "depmap-consortium-26q1",
    }


def _model_msi_unavailable(note: str) -> dict:
    return {
        "model_msi_class": "data_unavailable",
        "model_msi_high_fraction": None,
        "n_model_msi_high": 0,
        "n_model_lines": 0,
        "model_msi_context": None,
        "method_version": "0.2.0",
        "_data_note": note,
    }


@lru_cache(maxsize=1)
def _load_model_signatures_by_lineage():
    """{OncotreeLineage: DataFrame[mmr_frac, hrd_frac]} from DepMap OmicsMolecularSignatureMatrix.
    SBS columns are per-model exposure COUNTS → normalized to per-model FRACTIONS (signature /
    that model's total SBS burden) so a hypermutator doesn't dominate. Deduped per ModelID. Empty
    on failure. Returns a dict of lineage → list of (mmr_frac, hrd_frac) tuples."""
    import numpy as np
    import pandas as pd

    try:
        sig = pd.read_csv(io.BytesIO(_s3_read_bytes(DEPMAP_SIGNATURE_MATRIX_KEY)))
        model = pd.read_csv(io.BytesIO(_s3_read_bytes(DEPMAP_MODEL_KEY)), usecols=["ModelID", "OncotreeLineage"])
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return {}  # genuine object-absence → honest empty (verdict-inert)
        raise  # broken-env / transient / creds → honest _live_read_error
    sbs = [c for c in sig.columns if c.startswith("SBS")]
    if not sbs or "ModelID" not in sig.columns:
        return {}
    sig = sig.drop_duplicates(subset=["ModelID"]).copy()
    total = sig[sbs].sum(axis=1).replace(0, np.nan)
    mmr_cols = [c for c in _MMR_SIGNATURES if c in sbs]
    sig["_mmr_frac"] = sig[mmr_cols].sum(axis=1).div(total) if mmr_cols else np.nan
    sig["_hrd_frac"] = sig[_HRD_SIGNATURE].div(total) if _HRD_SIGNATURE in sbs else np.nan
    merged = sig.merge(model, on="ModelID", how="inner").dropna(subset=["_mmr_frac"])
    out: dict = {}
    for lineage, grp in merged.groupby("OncotreeLineage"):
        out[str(lineage)] = list(zip(grp["_mmr_frac"], grp["_hrd_frac"]))
    return out


def _classify_mmr_signature(cohort_high_fraction):
    if cohort_high_fraction is None:
        return "data_unavailable"
    if cohort_high_fraction >= _MMR_COHORT_HIGH:
        return "mmr_signature_enriched"
    if cohort_high_fraction <= _MMR_COHORT_LOW:
        return "mmr_signature_rare"
    return "mmr_signature_intermediate"


def model_signature_summary_for_indication(indication: str) -> dict:
    """Per-indication MODEL-side (DepMap) mutational-SIGNATURE summary from OmicsMolecularSignatureMatrix.
    Two therapeutically-actionable etiologies, cohort-level, target-independent:
      - model_mmr_signature_class: fraction of lineage cell lines whose MMR-deficiency signatures make
        up >= 20% of their SBS burden → enriched/intermediate/rare. An INDEPENDENT cross-validation of
        the MSI axis (mutation-spectrum signal, not microsatellite length).
      - model_hrd_signature_present_fraction: fraction of lines with SBS3 (defective-HR) >= 10% of burden
        — a WEAK PARP-sensitivity proxy (SBS3 rarely dominates; a real HRD score needs scarHRD, deferred).
    data_unavailable when no lineage mapping or the DepMap file is unresolvable."""
    lineages = INDICATION_TO_DEPMAP_LINEAGE.get(str(indication or "").upper().strip())
    if not lineages:
        return _model_signature_unavailable(f"no DepMap lineage mapping for {indication!r}")
    by_lin = _load_model_signatures_by_lineage()
    if not by_lin:
        return _model_signature_unavailable("DepMap OmicsMolecularSignatureMatrix/Model unresolvable")
    pairs = [p for lin in lineages for p in by_lin.get(lin, [])]
    n = len(pairs)
    if n == 0:
        return _model_signature_unavailable(f"no DepMap cell lines for {indication} ({lineages})")
    mmr_high = sum(1 for mmr, _hrd in pairs if mmr >= _MMR_SIG_HIGH_FRACTION)
    hrd_present = sum(1 for _mmr, hrd in pairs if hrd is not None and hrd >= _HRD_SIG_PRESENT_FRACTION)
    mmr_cohort_frac = mmr_high / n
    hrd_cohort_frac = hrd_present / n
    return {
        "model_mmr_signature_class": _classify_mmr_signature(mmr_cohort_frac),
        "model_mmr_signature_high_fraction": mmr_cohort_frac,
        "n_model_mmr_signature_high": mmr_high,
        "model_hrd_signature_present_fraction": hrd_cohort_frac,
        "n_model_hrd_signature_present": hrd_present,
        "n_model_signature_lines": n,
        "model_signature_context": (
            f"{indication}: {mmr_cohort_frac:.0%} of {n} DepMap {'/'.join(lineages)} cell lines are "
            f"MMR-signature-high (MMR SBS >= {_MMR_SIG_HIGH_FRACTION:.0%} of burden — cross-validates MSI); "
            f"{hrd_cohort_frac:.0%} carry an HRD signature (SBS3 >= {_HRD_SIG_PRESENT_FRACTION:.0%}, a WEAK "
            f"PARP-sensitivity proxy — a real HRD/genomic-scar score is deferred). MODEL-cohort, target-independent."
        ),
        "method_version": "0.2.0",
        "_data_source": "depmap-consortium-26q1",
    }


def _model_signature_unavailable(note: str) -> dict:
    return {
        "model_mmr_signature_class": "data_unavailable",
        "model_mmr_signature_high_fraction": None,
        "n_model_mmr_signature_high": 0,
        "model_hrd_signature_present_fraction": None,
        "n_model_hrd_signature_present": 0,
        "n_model_signature_lines": 0,
        "model_signature_context": None,
        "method_version": "0.2.0",
        "_data_note": note,
    }


def _classify_burden(median_frac: Optional[float]) -> str:
    if median_frac is None:
        return "data_unavailable"
    if median_frac >= _HIGH_MEDIAN:
        return "highly_aneuploid"
    if median_frac <= _LOW_MEDIAN:
        return "quiet_genome"
    return "intermediate_aneuploidy"


def aneuploidy_burden_for_indication(indication: str) -> dict:
    """Per-indication genome-instability burden summary from PanCanAtlas seg-based scores.

    Returns cohort aneuploidy_burden_class {highly_aneuploid / intermediate_aneuploidy /
    quiet_genome / data_unavailable} + the frac_altered distribution (median/p25/p75/n_samples).
    Indication-level (genome-wide phenotype); target-independent context. data_unavailable when the
    file/indication is unresolvable."""
    import numpy as np

    codes = INDICATION_TO_TCGA.get(str(indication or "").upper().strip())
    if not codes:
        return _unavailable(f"no TCGA project mapping for indication={indication!r}")
    seg = _load_seg_scores()
    if seg is None or seg.empty or "frac_altered" not in seg.columns:
        return _unavailable("seg_based_scores unavailable")
    cancer = _load_sample_cancer_types()
    if not cancer:
        return _unavailable("sample→cancer-type annotation unavailable")

    seg = seg.copy()
    seg["_patient"] = seg["Sample"].map(_barcode_to_patient)
    seg["_ctype"] = seg["_patient"].map(cancer)
    sub = seg[seg["_ctype"].isin(set(codes))]
    vals = sub["frac_altered"].dropna().astype(float)
    if len(vals) == 0:
        return _unavailable(f"no seg-score samples for {indication} ({codes})")

    median = float(np.median(vals))
    return {
        "aneuploidy_burden_class": _classify_burden(median),
        "median_fraction_genome_altered": median,
        "p25_fraction_genome_altered": float(np.percentile(vals, 25)),
        "p75_fraction_genome_altered": float(np.percentile(vals, 75)),
        "n_samples": int(len(vals)),
        "aneuploidy_burden_context": (
            f"{indication}: median {median:.2f} of the genome CN-altered across {len(vals)} "
            f"PanCanAtlas samples (per-sample seg-based frac_altered; genome-wide CIN burden, "
            f"target-independent)"
        ),
        "method_version": "0.1.0",
        "_data_source": "gdc-pancanatlas-cnv-2018",
    }


def _unavailable(note: str) -> dict:
    return {
        "aneuploidy_burden_class": "data_unavailable",
        "median_fraction_genome_altered": None,
        "p25_fraction_genome_altered": None,
        "p75_fraction_genome_altered": None,
        "n_samples": 0,
        "aneuploidy_burden_context": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Concurrent cache prewarm (latency-only; output byte-identical)
# ─────────────────────────────────────────────────────────────────────────────
def _safe_prewarm(fn, *args) -> None:
    """Call one lru_cache'd loader, swallowing errors. Best-effort ONLY: a broken-env / transient
    failure here just leaves that loader cold, and the real per-axis read re-attempts it and applies
    its OWN error handling (honest _live_read_error vs data_unavailable). Never let a prewarm failure
    surface as this axis's result."""
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 — prewarm is a pure latency optimization
        pass


def prewarm(indication: Optional[str] = None) -> None:
    """Populate the module's lru_cache'd S3 substrate loaders CONCURRENTLY.

    The genomic-instability-state dispatcher calls six per-axis functions (aneuploidy burden, WGD, MSI,
    model-MSI, model-signature, HRD) back-to-back; each reads its own DISJOINT PanCanAtlas / DepMap
    object, and several share the barcode->cancer-type map. Running them serially serialises those large,
    independent S3 GETs (the ABSOLUTE segtabs alone is 253 MB). This prewarm fires every cached loader
    ONCE, in parallel, so the subsequent serial axis reads all hit warm caches — folding the card's wall
    clock toward ~max(single read).

    PURELY a latency optimization: every axis function is UNCHANGED and still computes its own result, so
    the emitted summary is byte-identical to a cold run. Each loader is invoked exactly once here (no
    double-compute of the same lru_cache key), and MSI is warmed only when the indication actually has a
    patient-side label source (CRC + STAD). Best-effort throughout (see _safe_prewarm). Verdict-inert."""
    from concurrent.futures import ThreadPoolExecutor

    # NOTE: _load_absolute_segtabs (the ~253 MB HRD substrate) is intentionally NOT prewarmed — HRD now
    # reads the per-indication product (_hrd_from_product), so warming the segtabs would download 253 MB
    # for nothing. It is loaded ONLY on the live fallback (product unreachable), which warms it itself.
    argless = (
        _load_sample_cancer_types,
        _load_seg_scores,
        _load_absolute,
        _load_model_msi_by_lineage,
        _load_model_signatures_by_lineage,
    )
    ind = str(indication or "").upper().strip()
    src = MSI_LABEL_SOURCE.get(ind)  # (key, column) for CRC/STAD; None otherwise → no MSI read

    with ThreadPoolExecutor(max_workers=len(argless) + 1) as ex:
        futs = [ex.submit(_safe_prewarm, fn) for fn in argless]
        if src is not None:
            futs.append(ex.submit(_safe_prewarm, _load_msi_labels, src[0], src[1]))
        for f in futs:
            f.result()
