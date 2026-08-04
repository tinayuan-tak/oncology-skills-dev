"""Per-gene per-sample readers over the two long TPM products + the distribution assembler.

Reads tcga-tumor-tpm-recount3-long-v1 (tumor, per TCGA study) + gtex-tpm-recount3-long-v1 (normal,
per GTEx tissue) — both log2(TPM+1) on the SAME recount3/GENCODE-v26 axis, so tumor and normal are
directly comparable. Both long products are globally sorted by ensembl_gene_id, so per-gene reads
use pyarrow S3FileSystem + HTTP range requests to fetch only 2-3 row-groups rather than downloading
the full multi-GB file.

INDICATION_TO_TCGA_STUDIES / INDICATION_TO_GTEX_TISSUE mirror the dge_deseq2 maps — the matched
normal-tissue-of-origin per indication is the D2/D3 comparator.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import stats as _stats

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# Ensembl-116 gene ID map: HGNC symbol → frozenset of unversioned Ensembl IDs.
# Populated lazily on first call to _symbol_to_ensembl_ids(). Multiple Ensembl IDs
# per symbol arise from ~14 known collisions (e.g. PAR-region genes) — the filter
# uses an IN-list so all valid IDs are included and no true gene rows are dropped.
_SYMBOL_TO_ENSEMBL_MAP: Optional[dict] = None
ENSEMBL_ID_MAP_S3_KEY = ("data-catalog/sources/ensembl-id-mapping/"
                         "release-116-snapshot-2026-06-18/hsapiens_gene_id_map_release-116.tsv")


def _symbol_to_ensembl_ids(symbol: str) -> Optional[list]:
    """Return list of unversioned Ensembl IDs for a gene symbol, or None if unavailable.
    Builds the reverse of the HGNC map on first call and caches it in-process."""
    global _SYMBOL_TO_ENSEMBL_MAP
    if _SYMBOL_TO_ENSEMBL_MAP is None:
        try:
            import boto3
            import io
            import pandas as pd
            s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
            body = s3.get_object(Bucket=S3_BUCKET, Key=ENSEMBL_ID_MAP_S3_KEY)["Body"].read()
            df = pd.read_csv(io.BytesIO(body), sep="\t").dropna(
                subset=["Gene stable ID", "HGNC symbol"]
            )
            rev: dict = {}
            for eid, sym in zip(df["Gene stable ID"], df["HGNC symbol"]):
                rev.setdefault(sym, []).append(eid)
            _SYMBOL_TO_ENSEMBL_MAP = rev
        except Exception:  # noqa: BLE001
            _SYMBOL_TO_ENSEMBL_MAP = {}  # empty sentinel so we don't retry on every call
    ids = _SYMBOL_TO_ENSEMBL_MAP.get(symbol.upper().strip())
    return ids or None
TCGA_LONG_KEY = ("data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/tcga_tpm_long.parquet")
GTEX_LONG_KEY = ("data-catalog/derived/gtex-tpm-recount3-long-v1/gtex_tpm_long.parquet")
# The per-sample TPM product's companion sidecar: one row per tumor sample_id
# (recount3 gdc_file_id UUID) → study / sample_type / submitter_id (TCGA case
# barcode). This is the UUID↔barcode BRIDGE for tumor subtyping: the long product
# is UUID-keyed, but the subgroup-assignment shards are case-barcode-keyed, so a
# subtype join needs this hop. Verified 2026-07-22: 0 null lookups for KRAS/COADREAD.
TCGA_SIDECAR_KEY = ("data-catalog/derived/tcga-tumor-tpm-per-sample-v1/tcga_sample_study.parquet")
CACHE_DIR = Path.home() / ".cache" / "framework-tpm-long"
_SIDECAR_CACHE = CACHE_DIR / "tcga_sample_study.parquet"

_SIDECAR_STATUS: Optional[bool] = None

# indication → the landed subgroup-assignment shard (tumor / case-barcode family).
# ONLY COADREAD is materialized today (11 strata: MSI/MSS, sidedness, CMS1-4,
# CIMP×3). The other 7 catalogued indications are defined-but-unbuilt — emitting
# their shards is the extracted `subgroup-assignment-shards.md` workstream, NOT this
# reader. An indication absent here → subtype layer returns data_unavailable (honest).
# indication → landed TCGA tumor subtype-assignment shard. The subtype panorama engine below is
# INDICATION-AGNOSTIC (it fans over whatever strata the shard contains); this map is the explicit
# allowlist of indications whose shard has been VERIFIED to emit real, powered strata. Extended
# 2026-08-04 (COADREAD → +5) after confirming each shard's EMITTED contents (not just the declared-
# source audit — the emitter had already applied the audit's repoints, so several strata the audit
# scored "needs-repoint" resolve cleanly in the shipped parquet). Verified usable (>=SUBGROUP_N_FLOOR)
# strata per indication: COADREAD 7 (MSI/sidedness/stage) · HNSC 9 (Bass subtypes/site/HPV/CCND1_amp) ·
# STAD 4 (CIN/GS/HER2_amp/MSI_H) · NSCLC 3 (histology Adeno/SCC + TMB_high) · ESCA 2 (EAC/ESCC) ·
# PAAD 2 (Moffitt basal/classical). An indication absent here → subtype_axis_available:False (honest
# named gap). Add a new indication ONLY after inspecting its shard's per-stratum member counts.
INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST = {
    "COADREAD": "tcga-subgroup-assignments-coadread-v1",
    "COAD": "tcga-subgroup-assignments-coadread-v1",
    "READ": "tcga-subgroup-assignments-coadread-v1",
    "HNSC": "tcga-subgroup-assignments-hnsc-v1",
    "HNSCC": "tcga-subgroup-assignments-hnsc-v1",
    "STAD": "tcga-subgroup-assignments-stad-v1",
    "GC": "tcga-subgroup-assignments-stad-v1",
    "NSCLC": "tcga-subgroup-assignments-nsclc-v1",
    "LUAD": "tcga-subgroup-assignments-nsclc-v1",   # NSCLC shard carries the histology split (Adeno/SCC)
    "LUSC": "tcga-subgroup-assignments-nsclc-v1",
    "ESCA": "tcga-subgroup-assignments-esca-v1",
    "PAAD": "tcga-subgroup-assignments-paad-v1",
    "PDAC": "tcga-subgroup-assignments-paad-v1",
}

# indication → recount3 TCGA study codes (mirrors dge_deseq2.read.INDICATION_TO_TCGA_STUDIES).
INDICATION_TO_TCGA_STUDIES = {
    "COADREAD": ["COAD", "READ"], "COAD": ["COAD"], "READ": ["READ"],
    "LUAD": ["LUAD"], "LUSC": ["LUSC"], "BRCA": ["BRCA"], "PAAD": ["PAAD"], "PDAC": ["PAAD"],
    "SKCM": ["SKCM"], "STAD": ["STAD"], "PRAD": ["PRAD"], "OV": ["OV"], "KIRC": ["KIRC"],
    "GBM": ["GBM"], "LGG": ["LGG"], "HNSC": ["HNSC"], "BLCA": ["BLCA"], "LIHC": ["LIHC"],
    "CESC": ["CESC"], "ESCA": ["ESCA"],
}
# indication → matched GTEx normal tissue-of-origin (mirrors dge_deseq2.read.INDICATION_TO_GTEX_TISSUE).
INDICATION_TO_GTEX_TISSUE = {
    "COADREAD": "COLON", "COAD": "COLON", "READ": "COLON", "LUAD": "LUNG", "LUSC": "LUNG",
    "BRCA": "BREAST", "PAAD": "PANCREAS", "PDAC": "PANCREAS", "SKCM": "SKIN", "STAD": "STOMACH",
    "PRAD": "PROSTATE", "OV": "OVARY", "KIRC": "KIDNEY", "GBM": "BRAIN", "LGG": "BRAIN",
    "BLCA": "BLADDER", "LIHC": "LIVER", "CESC": "CERVIX_UTERI", "ESCA": "ESOPHAGUS",
}


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def _ensure_sidecar_cached() -> Optional[Path]:
    """Download+cache the sidecar (small: ~1 row per tumor sample). Definitive-vs-transient
    latch: 404/NoSuchKey marks absent permanently; 403 is transient (retried next call)."""
    global _SIDECAR_STATUS
    if _SIDECAR_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if _SIDECAR_CACHE.exists() and _SIDECAR_CACHE.stat().st_size > 0:
        return _SIDECAR_CACHE
    if _SIDECAR_STATUS is None:
        try:
            _boto3_client().download_file(S3_BUCKET, TCGA_SIDECAR_KEY, str(_SIDECAR_CACHE))
            _SIDECAR_STATUS = True
            return _SIDECAR_CACHE
        except Exception as e:  # noqa: BLE001
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (code in ("404", "NoSuchKey")
                          or e.__class__.__name__ in ("NoSuchKey", "404"))
            if definitive:
                _SIDECAR_STATUS = False
            return None
    return None


def _read_gene(which: str, target: str):
    """Stream one gene from a long product directly from S3 via HTTP range requests.

    Both long products are globally sorted by ensembl_gene_id (rg=65536), so an
    IN-list filter prunes to 2-3 row-groups via pyarrow predicate pushdown — no
    full-file download needed. Falls back to gene_symbol if the Ensembl map is
    unavailable (still correct, but scans the full file).
    """
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    import pandas as pd

    key = TCGA_LONG_KEY if which == "tcga" else GTEX_LONG_KEY
    group_col = "study" if which == "tcga" else "tissue"
    cols = ["gene_symbol", "ensembl_gene_id", "sample_id", group_col, "log2_tpm"]
    try:
        s3fs = fs.S3FileSystem(region="us-east-1")
        ensembl_ids = _symbol_to_ensembl_ids(target)
        if ensembl_ids:
            filters = [("ensembl_gene_id", "in", ensembl_ids)]
        else:
            # fallback: gene_symbol (no row-group pruning on this sort key, but correct)
            filters = [("gene_symbol", "==", target.upper().strip())]
        tbl = pq.read_table(
            f"{S3_BUCKET}/{key}",
            filesystem=s3fs,
            filters=filters,
            columns=cols,
        )
        return tbl.to_pandas()
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=cols)


def read_tumor_samples(target: str, indication: str):
    """Per-sample tumor log2(TPM+1) for target restricted to the indication's TCGA study/studies.
    Returns the log2_tpm list (empty if unmapped / absent)."""
    studies = INDICATION_TO_TCGA_STUDIES.get(indication.upper().strip())
    df = _read_gene("tcga", target)
    if df.empty or not studies:
        return []
    return df[df["study"].isin(studies)]["log2_tpm"].dropna().astype(float).tolist()


def _tcga_case(barcode) -> Optional[str]:
    """TCGA case barcode (TCGA-XX-XXXX) = the first three '-'-delimited fields of any
    aliquot/submitter barcode. The grain the subgroup-assignment shards key on."""
    if barcode is None:
        return None
    parts = str(barcode).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(barcode)


def _load_sidecar():
    """The UUID→barcode sidecar as a DataFrame (sample_id[UUID], submitter_id[barcode]),
    with a derived `case` column. Empty DataFrame if the sidecar is unavailable."""
    import pandas as pd
    path = _ensure_sidecar_cached()
    if path is None:
        return pd.DataFrame(columns=["sample_id", "submitter_id", "case"])
    try:
        import pyarrow.parquet as pq
        df = pq.read_table(str(path), columns=["sample_id", "submitter_id"]).to_pandas()
        df["case"] = df["submitter_id"].map(_tcga_case)
        return df
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["sample_id", "submitter_id", "case"])


def read_tumor_samples_with_case(target: str, indication: str):
    """Per-sample tumor rows for target in the indication, BRIDGED to the TCGA case
    barcode via the sidecar — the substrate for subtype stratification.

    Returns a DataFrame [case, log2_tpm] (one row per tumor sample; `case` is the
    barcode grain the assignment shards key on). Empty if unmapped/absent. The long
    product is UUID-keyed, so this joins UUID→submitter_id→case; the ~92% coverage
    (some recount3 UUIDs have no sidecar barcode / no stratum) is honest attrition,
    surfaced by the join-coverage guard in the stratified assembler."""
    import pandas as pd
    studies = INDICATION_TO_TCGA_STUDIES.get(indication.upper().strip())
    df = _read_gene("tcga", target)
    if df.empty or not studies:
        return pd.DataFrame(columns=["case", "log2_tpm"])
    df = df[df["study"].isin(studies)][["sample_id", "log2_tpm"]].dropna(subset=["log2_tpm"])
    if df.empty:
        return pd.DataFrame(columns=["case", "log2_tpm"])
    side = _load_sidecar()
    if side.empty:
        return pd.DataFrame(columns=["case", "log2_tpm"])
    merged = df.merge(side[["sample_id", "case"]], on="sample_id", how="left")
    merged = merged.dropna(subset=["case"])
    merged["log2_tpm"] = merged["log2_tpm"].astype(float)
    return merged[["case", "log2_tpm"]]


def read_normal_samples(target: str, indication: str):
    """Per-sample matched-normal GTEx log2(TPM+1) for the indication's tissue-of-origin.
    Returns (values, tissue) — tissue is None if the indication has no GTEx mapping."""
    tissue = INDICATION_TO_GTEX_TISSUE.get(indication.upper().strip())
    if tissue is None:
        return [], None
    df = _read_gene("gtex", target)
    if df.empty:
        return [], tissue
    return df[df["tissue"] == tissue]["log2_tpm"].dropna().astype(float).tolist(), tissue


def read_all_normal_tissues(target: str) -> dict:
    """Per-GTEx-tissue log2(TPM+1) for target across ALL tissues — the Q3 normal-tissue-liability
    substrate (the atlas the existing readers collapse to one tissue). {tissue: [values]}."""
    df = _read_gene("gtex", target)
    if df.empty:
        return {}
    return {t: sub["log2_tpm"].dropna().astype(float).tolist()
            for t, sub in df.groupby("tissue")}


def _distribution_summary(values: list) -> dict:
    """The distribution-stat block for a per-sample log2(TPM+1) vector. The ONE
    computation shared by the pooled assembler AND every per-subtype stratum — so
    `target_subtype` is a projection of the same primitives, never a re-derivation
    (the 'grain is a projection' pattern). Assumes a non-empty vector."""
    fn = _stats.five_number(values)
    fracs = _stats.expression_fractions(values)
    out = {
        "n_tumor_samples": fn["n"],
        "median_log2tpm": fn["median"], "p95_log2tpm": fn["p95"], "p99_log2tpm": fn["p99"],
        "min_log2tpm": fn["min"], "max_log2tpm": fn["max"],
        "coefficient_of_variation": _stats.coefficient_of_variation(values),
        "distribution_pattern": _stats.distribution_pattern(values),
        **fracs,
    }
    out["tumor_expression_class"] = _classify_tumor_expression(
        out["detectable_fraction"], out["high_fraction"], out["distribution_pattern"])
    return out


def read_tumor_vs_normal_percentile_crossing(target: str, indication: str) -> dict:
    """Q2 assembler: per-sample tumor-vs-matched-normal PERCENTILE-CROSSING selectivity for a
    (target, indication). The spec's headline enrichment metric — the fraction of tumors above the
    Nth percentile of matched-normal expression — computed on the directly-comparable per-sample
    matrices (recount3/GENCODE-v26). This is SELECTIVITY (Gate B), distinct from the aggregate
    log2FC on tumor-vs-normal-selectivity and from PRESENCE (Q1). data_unavailable-safe."""
    tumor = read_tumor_samples(target, indication)
    normal, tissue = read_normal_samples(target, indication)
    studies = INDICATION_TO_TCGA_STUDIES.get(indication.upper().strip(), [])
    if not tumor or not normal:
        return {"selectivity_class": "data_unavailable",
                "n_tumor_samples": len(tumor), "n_normal_samples": len(normal or []),
                "matched_normal_tissue": tissue,
                "fraction_tumor_above_normal_p95": None, "fraction_tumor_above_normal_p99": None,
                "distribution_overlap_tumor_normal": None, "studies": studies,
                "_data_note": ("no matched GTEx normal tissue for this indication" if not normal
                               else "target absent from TCGA long product for this indication")}
    out = {"n_tumor_samples": len(tumor), "n_normal_samples": len(normal),
           "matched_normal_tissue": tissue, "studies": studies}
    for pct in (95, 99):
        fa = _stats.fraction_above_normal_percentile(tumor, normal, pct)
        out[f"fraction_tumor_above_normal_p{pct}"] = fa["fraction_tumor_above"]
        out[f"normal_p{pct}_log2tpm"] = fa["normal_pN"]
    out["distribution_overlap_tumor_normal"] = _stats.distribution_overlap(tumor, normal)
    out["selectivity_class"] = _classify_percentile_crossing(
        out["fraction_tumor_above_normal_p95"], out["fraction_tumor_above_normal_p99"],
        out["distribution_overlap_tumor_normal"])
    return out


def _classify_percentile_crossing(frac_p95, frac_p99, overlap) -> str:
    """Categorical for the Q2 selectivity card/rules (per-sample percentile-crossing vocab):
      strongly_tumor_enriched — most tumors clear the normal p95 AND distributions separate
                                (frac_p95 >= 0.5 and overlap <= 0.4)
      enriched_subset         — a real tumor-high subset above normal p95 (frac_p95 >= 0.25)
      minimally_enriched      — few tumors exceed normal (frac_p95 < 0.25)
      not_enriched            — essentially no separation (frac_p95 < 0.05)
      data_unavailable        — handled by the caller."""
    if frac_p95 is None:
        return "data_unavailable"
    if frac_p95 >= 0.5 and (overlap is not None and overlap <= 0.4):
        return "strongly_tumor_enriched"
    if frac_p95 >= 0.25:
        return "enriched_subset"
    if frac_p95 < 0.05:
        return "not_enriched"
    return "minimally_enriched"


def read_normal_tissue_liability(target: str) -> dict:
    """Q3 assembler: normal-tissue-liability over the GTEx atlas (all tissues) for a target — the
    therapeutic-window / on-target-off-tumor question. Composes normal_tissue_liability over the
    per-tissue vectors from read_all_normal_tissues (recount3, same axis as the tumor TPM, so
    tumor-vs-normal ratios are directly comparable). target-grain (no indication). data-gap-safe."""
    atlas = read_all_normal_tissues(target)
    if not atlas:
        return {"liability_class": "data_unavailable", "n_tissues_tested": 0,
                "highest_tissue": None, "critical_organ_max": None,
                "_data_note": "target absent from GTEx long product"}
    summ = _stats.normal_tissue_liability(atlas)
    summ["liability_class"] = _classify_normal_liability(
        summ["critical_organ_max"], summ["highest_tissue_median"], summ["tissue_breadth_fraction"])
    return summ


def _classify_normal_liability(critical_organ_max, highest_median, breadth_fraction) -> str:
    """Categorical for the Q3 liability card/rules (therapeutic-window vocab):
      critical_organ_liability — a CRITICAL organ carries high expression (>= HIGH cutoff):
                                 on-target-off-tumor red flag regardless of tumor abundance
      broadly_expressed_normal — detectable across most normal tissues (breadth >= 0.7):
                                 narrow window (housekeeping-like)
      restricted_normal        — expressed in few normal tissues (breadth < 0.3): favorable window
      moderate_normal_breadth  — otherwise
      data_unavailable         — handled by the caller."""
    if breadth_fraction is None:
        return "data_unavailable"
    if critical_organ_max is not None and critical_organ_max >= _stats.HIGH_LOG2TPM:
        return "critical_organ_liability"
    if breadth_fraction >= 0.7:
        return "broadly_expressed_normal"
    if breadth_fraction < 0.3:
        return "restricted_normal"
    return "moderate_normal_breadth"


def read_tumor_expression_distribution(target: str, indication: str) -> dict:
    """Q1 assembler: the tumor per-sample distribution summary for a (target, indication).
    Composes the stats primitives into the spec's `tumor_expression` block. data_unavailable-safe."""
    tumor = read_tumor_samples(target, indication)
    studies = INDICATION_TO_TCGA_STUDIES.get(indication.upper().strip(), [])
    if not tumor:
        return {"tumor_expression_class": "data_unavailable",
                "n_tumor_samples": 0, "distribution_pattern": None,
                "coefficient_of_variation": None,
                "detectable_fraction": None, "moderate_fraction": None, "high_fraction": None,
                "_data_note": "target absent from TCGA long product for this indication",
                "studies": studies}
    return {**_distribution_summary(tumor), "studies": studies}


def _classify_tumor_expression(detectable_fraction, high_fraction, pattern) -> str:
    """Categorical for the card/rules (mirrors the DepMap distribution vocab, tumor-patient grain):
      broadly_high      — most tumors highly express (high_fraction >= 0.5)
      broadly_detected  — most tumors detectable but not high (detectable >= 0.7)
      subset_high       — a target-high subset (bimodal/long_tail with a real high minority)
      broadly_low       — detectable in a minority (detectable < 0.3)
      broadly_moderate  — otherwise (detectable in a middling fraction)
      data_unavailable  — handled by the caller."""
    if detectable_fraction is None:
        return "data_unavailable"
    if high_fraction is not None and high_fraction >= 0.5:
        return "broadly_high"
    if pattern in ("bimodal", "long_tail") and (high_fraction or 0.0) >= 0.1:
        return "subset_high"
    if detectable_fraction >= 0.7:
        return "broadly_detected"
    if detectable_fraction < 0.3:
        return "broadly_low"
    return "broadly_moderate"


# ---- Subtype layer ---------------------------------------------------------
# Per-subtype tumor expression, keyed on the TCGA case barcode via the assignment
# shards. COMPUTE-ALL-SPOTLIGHT-ONE (plan-decided): always compute EVERY stratum
# and emit the full `subtype_landscape`; a queried subtype moves the spotlight +
# verdict scope in the skill layer, never what's computed here. Subtype is
# confidence/context, NEVER a new veto — the one-directional gate is preserved.

# Per-stratum enrichment cutoff (log2TPM units) vs the indication's pooled median.
# A stratum whose median is >= this above/below pooled is enriched/depleted; within
# the band it's uniform. ~0.585 = log2(1.5) ≈ a 1.5x linear-TPM shift — matched to
# the modest-vs-strong grв convention used elsewhere, declared here (not hardcoded
# in rules) so the card's thresholds block can override.
SUBTYPE_ENRICH_LOG2_DELTA = 0.585


def _classify_subtype_signal(stratum_median, pooled_median, detectable_fraction,
                             pooled_detectable) -> str:
    """Per-stratum categorical vs the indication's pooled distribution:
      subtype_enriched   — stratum median >= pooled + SUBTYPE_ENRICH_LOG2_DELTA
      subtype_restricted — detectable in this stratum but broadly absent pooled
                           (stratum detectable >= 0.5 while pooled < 0.3)
      subtype_depleted   — stratum median <= pooled - SUBTYPE_ENRICH_LOG2_DELTA
      subtype_uniform    — within the band (no stratum-specific signal)
    """
    if stratum_median is None or pooled_median is None:
        return "subtype_uniform"
    if (detectable_fraction is not None and pooled_detectable is not None
            and detectable_fraction >= 0.5 and pooled_detectable < 0.3):
        return "subtype_restricted"
    if stratum_median >= pooled_median + SUBTYPE_ENRICH_LOG2_DELTA:
        return "subtype_enriched"
    if stratum_median <= pooled_median - SUBTYPE_ENRICH_LOG2_DELTA:
        return "subtype_depleted"
    return "subtype_uniform"


def read_tumor_expression_subtype_landscape(target: str, indication: str,
                                            subtype: Optional[str] = None) -> dict:
    """Subtype-stratified tumor expression for a (target, indication).

    COMPUTE-ALL: fans out over EVERY stratum of the indication's assignment shard,
    running the same `_distribution_summary` primitives per stratum, and returns a
    `subtype_landscape` list. `subtype` (optional) SPOTLIGHTS one stratum for the
    verdict scope in the caller — it does NOT change what is computed.

    Returns the pooled summary PLUS:
      subtype_axis_available: bool  — is there a shard for this indication?
      subtype_landscape: [ {stratum_id, subtype_signal, evidence_state,
                            subgroup_n_floor_met, n_tumor_samples, median_log2tpm,
                            detectable_fraction, high_fraction, distribution_pattern,
                            tumor_expression_class, match_rate}, ... ]
      spotlight_subtype: the queried stratum id (or None)
      n_subtypes_enriched / n_subtypes_measured: rollup counts
    data_unavailable-safe: no shard → subtype_axis_available False + empty landscape.
    """
    from methods.subgroup_common.panorama import (evidence_state as _evstate,
                                                   SUBGROUP_N_FLOOR as _SUBGROUP_N_FLOOR)
    from methods.subgroup_common.scoping import compute_join_coverage
    from methods.subgroup_common.loaders import load_assignments

    pooled = read_tumor_expression_distribution(target, indication)
    manifest = INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST.get(indication.upper().strip())

    base = dict(pooled)
    base["spotlight_subtype"] = subtype
    if manifest is None or pooled.get("tumor_expression_class") == "data_unavailable":
        base.update({"subtype_axis_available": False, "subtype_landscape": [],
                     "n_subtypes_measured": 0, "n_subtypes_enriched": 0,
                     "_subtype_note": ("no landed tumor assignment shard for this indication"
                                       if manifest is None
                                       else "target absent — no per-subtype distribution")})
        return base

    bridged = read_tumor_samples_with_case(target, indication)  # DataFrame[case, log2_tpm]
    try:
        assignments = load_assignments(manifest)
    except Exception as e:  # noqa: BLE001
        base.update({"subtype_axis_available": False, "subtype_landscape": [],
                     "n_subtypes_measured": 0, "n_subtypes_enriched": 0,
                     "_subtype_note": f"assignment shard unavailable: {type(e).__name__}"})
        return base

    strata = sorted(assignments.loc[assignments["is_member"] == True, "stratum_id"].unique().tolist())
    pooled_median = pooled.get("median_log2tpm")
    pooled_detectable = pooled.get("detectable_fraction")

    landscape = []
    for stratum_id in strata:
        member_cases = set(assignments.loc[
            (assignments["stratum_id"] == stratum_id) & (assignments["is_member"] == True),
            "sample_id"])
        sub = bridged[bridged["case"].isin(member_cases)]
        vals = sub["log2_tpm"].tolist()
        n = len(vals)
        floor_met = n >= _SUBGROUP_N_FLOOR
        state = _evstate(n, floor_met)
        # join-coverage guard: warns on the <5% id-convention-mismatch signature.
        cov = compute_join_coverage(bridged, "case", stratum_id, manifest, warn=True)
        rec = {"stratum_id": stratum_id, "evidence_state": state,
               "subgroup_n_floor_met": floor_met, "n_tumor_samples": n,
               "match_rate": cov.match_rate}
        if n > 0:
            summary = _distribution_summary(vals)
            rec.update({k: summary[k] for k in
                        ("median_log2tpm", "detectable_fraction", "high_fraction",
                         "distribution_pattern", "tumor_expression_class")})
            # subtype signal is only trustworthy when the stratum clears the floor;
            # underpowered strata carry stats for context but a null signal.
            rec["subtype_signal"] = (_classify_subtype_signal(
                summary["median_log2tpm"], pooled_median,
                summary["detectable_fraction"], pooled_detectable)
                if floor_met else None)
        else:
            rec.update({"median_log2tpm": None, "detectable_fraction": None,
                        "high_fraction": None, "distribution_pattern": None,
                        "tumor_expression_class": "data_unavailable", "subtype_signal": None})
        landscape.append(rec)

    n_measured = sum(1 for r in landscape if r["evidence_state"] == "measured")
    n_enriched = sum(1 for r in landscape if r.get("subtype_signal") == "subtype_enriched")
    base.update({"subtype_axis_available": True, "subtype_landscape": landscape,
                 "assignment_manifest": manifest,
                 "n_subtypes_measured": n_measured, "n_subtypes_enriched": n_enriched})
    return base


def read_tumor_subtype_values(target: str, indication: str) -> dict:
    """Per-stratum per-sample value VECTORS for the subtype-panel figure (the landscape
    carries summary stats; the box/strip panel needs the raw points). Shares the SAME
    bridge + shard as read_tumor_expression_subtype_landscape (no drift).

    Returns:
      {available: bool, pooled_values: [..], pooled_median: float|None,
       strata: [ {stratum_id, values: [..], subtype_signal, evidence_state,
                  subgroup_n_floor_met, n} ordered by median ], _note?: str}
    data_unavailable-safe (no shard / target absent → available False)."""
    from methods.subgroup_common.panorama import (evidence_state as _evstate,
                                                   SUBGROUP_N_FLOOR as _SUBGROUP_N_FLOOR)
    from methods.subgroup_common.loaders import load_assignments

    manifest = INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST.get(indication.upper().strip())
    pooled_vals = read_tumor_samples(target, indication)
    if manifest is None or not pooled_vals:
        return {"available": False, "pooled_values": pooled_vals or [], "pooled_median": None,
                "strata": [], "_note": ("no landed tumor assignment shard for this indication"
                                        if manifest is None else "target absent")}
    import statistics as _st
    pooled_median = _st.median(pooled_vals)
    bridged = read_tumor_samples_with_case(target, indication)
    try:
        assignments = load_assignments(manifest)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "pooled_values": pooled_vals, "pooled_median": pooled_median,
                "strata": [], "_note": f"assignment shard unavailable: {type(e).__name__}"}
    pooled_detectable = _stats.expression_fractions(pooled_vals)["detectable_fraction"]
    strata_ids = sorted(assignments.loc[assignments["is_member"] == True, "stratum_id"].unique().tolist())
    rows = []
    for sid in strata_ids:
        member_cases = set(assignments.loc[
            (assignments["stratum_id"] == sid) & (assignments["is_member"] == True), "sample_id"])
        vals = bridged[bridged["case"].isin(member_cases)]["log2_tpm"].tolist()
        n = len(vals)
        floor_met = n >= _SUBGROUP_N_FLOOR
        signal = None
        if n > 0 and floor_met:
            summ = _distribution_summary(vals)
            signal = _classify_subtype_signal(summ["median_log2tpm"], pooled_median,
                                              summ["detectable_fraction"], pooled_detectable)
        rows.append({"stratum_id": sid, "values": vals, "subtype_signal": signal,
                     "evidence_state": _evstate(n, floor_met),
                     "subgroup_n_floor_met": floor_met, "n": n,
                     "median": (_st.median(vals) if vals else None)})
    # order by median (ascending) so the panel reads as a gradient; null medians last.
    rows.sort(key=lambda r: (r["median"] is None, r["median"] if r["median"] is not None else 0.0))
    return {"available": True, "pooled_values": pooled_vals, "pooled_median": pooled_median,
            "strata": rows, "assignment_manifest": manifest}
