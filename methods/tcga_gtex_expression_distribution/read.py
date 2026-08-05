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

# The ONLY file this module legitimately caches on disk is the small sidecar (~448 KB).
# Everything else is streamed from S3 via HTTP range requests (see _read_gene). A prior
# version of this reader (removed 2026-07-24, PR #115) full-downloaded the multi-GB long
# products into CACHE_DIR; a long-lived process still holding that old code in memory can
# silently re-bloat this dir to ~16 GB. We can't edit a running process's memory, so we make
# the CURRENT code self-healing instead: on first read per process, sweep anything in
# CACHE_DIR that isn't the allowed sidecar. This bounds the leak — an old kernel's re-download
# never SURVIVES the next current-code run. Future-proof: keyed on an allowlist, not the
# stale filenames, so it also catches boto3 in-progress temps (<name>.<8-hex>) and any later
# accidental full-download.
_CACHE_ALLOWED_NAMES = frozenset({_SIDECAR_CACHE.name})
_STALE_CACHE_SWEPT = False


def _sweep_stale_cache(cache_dir: Path, keep: frozenset[str]) -> list[str]:
    """Remove any file in cache_dir whose name is not in `keep`; return the removed names.

    Pure + S3-free (operates on the filesystem only) so it is unit-testable against a tmp dir.
    Silent on a missing dir (nothing cached yet) and best-effort per file (a concurrent reader
    holding a handle must never break a read — the invariant is 'don't accumulate', not 'atomic')."""
    removed: list[str] = []
    if not cache_dir.is_dir():
        return removed
    for entry in cache_dir.iterdir():
        if entry.is_file() and entry.name not in keep:
            try:
                entry.unlink()
                removed.append(entry.name)
            except OSError:  # noqa: PERF203 - best-effort; a held handle just defers cleanup one run
                pass
    return removed


def _sweep_stale_cache_once() -> None:
    """Run the stale-cache sweep at most once per process (idempotent, cheap after the first)."""
    global _STALE_CACHE_SWEPT
    if _STALE_CACHE_SWEPT:
        return
    _STALE_CACHE_SWEPT = True
    _sweep_stale_cache(CACHE_DIR, _CACHE_ALLOWED_NAMES)

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

# indication → landed TCGA MAF-FILTER (genomic-strata) assignment shard. The base map above carries the
# directly-tagged molecular/histology strata (HPV, site, Bass/Moffitt subtype, etc.); this map carries
# the ORTHOGONAL genomic strata (driver-mutation status: TP53_mut, KRAS_G12C/G12D/WT, PIK3CA_mut) from
# the maf_filter assigner. Deliberately PARTIAL — only the 4 indications with a landed -maf shard whose
# strata are VERIFIED powered (>=SUBGROUP_N_FLOOR members): HNSC (TP53_mut/PIK3CA_mut), ESCA (TP53_mut),
# PAAD (TP53_mut/KRAS_G12D/KRAS_WT), NSCLC (KRAS_G12C only — thin but real). COADREAD/STAD have no -maf
# shard yet. The genomic + directly-tagged strata are UNIONED per indication (disjoint stratum_ids), so
# a subtype landscape shows molecular AND genomic subtypes side by side. Absence here = base strata only
# (honest — never a false empty). Same lockstep + verify-emitted-not-audit discipline as the base map.
INDICATION_TO_TUMOR_MAF_MANIFEST = {
    "HNSC": "tcga-subgroup-assignments-hnsc-maf-v1",
    "HNSCC": "tcga-subgroup-assignments-hnsc-maf-v1",
    "NSCLC": "tcga-subgroup-assignments-nsclc-maf-v1",
    "LUAD": "tcga-subgroup-assignments-nsclc-maf-v1",
    "LUSC": "tcga-subgroup-assignments-nsclc-maf-v1",
    "ESCA": "tcga-subgroup-assignments-esca-maf-v1",
    "PAAD": "tcga-subgroup-assignments-paad-maf-v1",
    "PDAC": "tcga-subgroup-assignments-paad-maf-v1",
}


def _load_subtype_assignments(indication: str):
    """Load the UNION of an indication's directly-tagged (base) + maf-filter (genomic) assignment
    shards as one DataFrame, so the subtype engine enumerates BOTH strata families in one pass.

    Returns (assignments_df, base_manifest_id) — base_manifest_id is None when the indication has no
    landed base shard (the caller treats that as subtype_axis_unavailable, unchanged). The maf shard is
    OPTIONAL: absent → base strata only; present-but-unfetchable → base strata only (never fail the
    whole landscape on the genomic add-on). The two shards carry DISJOINT stratum_ids and identical
    schema (sample_id/stratum_id/is_member/...), so a plain row-concat is correct — no dedup needed."""
    from methods.subgroup_common.loaders import load_assignments
    import pandas as _pd
    key = indication.upper().strip()
    base_manifest = INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST.get(key)
    if base_manifest is None:
        return None, None
    frames = [load_assignments(base_manifest)]
    maf_manifest = INDICATION_TO_TUMOR_MAF_MANIFEST.get(key)
    if maf_manifest is not None:
        try:
            frames.append(load_assignments(maf_manifest))
        except Exception:  # noqa: BLE001 — genomic add-on is best-effort; base strata still stand
            pass
    merged = _pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    return merged, base_manifest

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

# PROXY normal tissues — for indications with NO true GTEx tissue-of-origin (e.g. HNSC: GTEx has no
# head-and-neck track). A proxy is NOT a matched normal: the window computed against it is
# HISTOLOGICALLY-ANALOGOUS, weaker evidence, and MUST be reported on a labeled proxy channel — never
# in matched_normal_tissue. Only populated where INDICATION_TO_GTEX_TISSUE has no entry (a true normal
# always wins). Ordered by histological closeness. HNSC = squamous epithelium → esophageal mucosa
# (non-keratinized stratified squamous, the closest architectural match) + skin (epidermal squamous)
# + salivary gland (sub-site-specific). Each carries a rationale surfaced in the output.
INDICATION_TO_PROXY_NORMAL_TISSUES = {
    "HNSC":  [("ESOPHAGUS", "non-keratinized stratified squamous mucosa — closest architectural match to oral/pharyngeal epithelium"),
              ("SKIN", "epidermal squamous epithelium — shared keratinocyte transcriptomic profile"),
              ("SALIVARY_GLAND", "sub-site proxy for salivary-gland-origin H&N tumors")],
    "HNSCC": [("ESOPHAGUS", "non-keratinized stratified squamous mucosa — closest architectural match to oral/pharyngeal epithelium"),
              ("SKIN", "epidermal squamous epithelium — shared keratinocyte transcriptomic profile"),
              ("SALIVARY_GLAND", "sub-site proxy for salivary-gland-origin H&N tumors")],
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

    # Self-heal any stale full-download residue before we stream (see _sweep_stale_cache).
    # Once per process; a no-op on the common case (only the sidecar present).
    _sweep_stale_cache_once()

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


def _tumor_allgene_percentile(target: str, studies: list) -> dict:
    """All-gene percentile of the target's tumor MEDIAN within the indication's TCGA
    study/studies (Phase 1C). A single-gene predicate-pushdown lookup of the precomputed
    allgene-tumor-rank-v1 (NO re-scan of the multi-GB long products); the per-study
    percentiles are averaged (COADREAD → COAD+READ) into one scalar, with every study
    named in the context string. Additive/display — never flips tumor_expression_class.
    data_unavailable-safe (any failure → None percentile)."""
    try:
        from methods.allgene_percentile_precompute.lookup import tumor_allgene_percentile
        ensembl_ids = _symbol_to_ensembl_ids(target) or []
        return tumor_allgene_percentile(ensembl_ids, studies)
    except Exception:  # noqa: BLE001 — enrichment best-effort
        return {"allgene_percentile": None, "allgene_percentile_class": "data_unavailable",
                "allgene_percentile_context": None, "allgene_percentile_by_study": {}}


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
                "allgene_percentile": None, "allgene_percentile_class": "data_unavailable",
                "allgene_percentile_context": None,
                "_data_note": "target absent from TCGA long product for this indication",
                "studies": studies}
    return {**_distribution_summary(tumor), **_tumor_allgene_percentile(target, studies),
            "studies": studies}


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


def _stratum_clears_window(rec: dict) -> bool:
    """Does this stratum clear its matched-normal OR any proxy p95 in >=50% of its tumors?"""
    if (rec.get("fraction_tumor_above_normal_p95") or 0) >= 0.5:
        return True
    return any((pw.get("fraction_tumor_above_proxy_p95") or 0) >= 0.5
               for pw in (rec.get("proxy_normal_windows") or []))


def classify_subtype_stratification(landscape: list) -> str:
    """Graded patient-selection class from a subtype landscape — the biomarker facet's stratification
    input (NOT the presence verdict; one-directional). A subtype_restricted target (present in ONE
    subtype, absent pooled) is the selection signal; graded by whether a restricted subtype ALSO clears
    its normal/proxy window (present + therapeutic window in a defined subpopulation = strongest):
      subtype_restricted_with_window > subtype_restricted > subtype_enriched > pan_subtype_uniform
      > subtype_axis_unavailable (no measured strata). A subtype_DEPLETED stratum is NOT a positive
      selection opportunity (it does not raise the class). Pure fn — read.py + tests share it (no drift)."""
    measured = [r for r in landscape if r.get("evidence_state") == "measured"]
    restricted = [r for r in measured if r.get("subtype_signal") == "subtype_restricted"]
    enriched = [r for r in measured if r.get("subtype_signal") == "subtype_enriched"]
    if restricted and any(_stratum_clears_window(r) for r in restricted):
        return "subtype_restricted_with_window"
    if restricted:
        return "subtype_restricted"
    if enriched:
        return "subtype_enriched"
    if measured:
        return "pan_subtype_uniform"
    return "subtype_axis_unavailable"


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

    pooled = read_tumor_expression_distribution(target, indication)

    base = dict(pooled)
    base["spotlight_subtype"] = subtype
    # UNION of directly-tagged (molecular/histology) + maf-filter (genomic driver-status) strata.
    try:
        assignments, manifest = _load_subtype_assignments(indication)
    except Exception as e:  # noqa: BLE001 — base shard itself unfetchable
        assignments, manifest = None, INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST.get(indication.upper().strip())
        if manifest is not None:
            base.update({"subtype_axis_available": False, "subtype_landscape": [],
                         "n_subtypes_measured": 0, "n_subtypes_enriched": 0, "n_subtypes_restricted": 0,
                         "subtype_stratification_class": "subtype_axis_unavailable",
                         "_subtype_note": f"assignment shard unavailable: {type(e).__name__}"})
            return base
    if manifest is None or pooled.get("tumor_expression_class") == "data_unavailable":
        base.update({"subtype_axis_available": False, "subtype_landscape": [],
                     "n_subtypes_measured": 0, "n_subtypes_enriched": 0, "n_subtypes_restricted": 0,
                     "subtype_stratification_class": "subtype_axis_unavailable",
                     "_subtype_note": ("no landed tumor assignment shard for this indication"
                                       if manifest is None
                                       else "target absent — no per-subtype distribution")})
        return base

    bridged = read_tumor_samples_with_case(target, indication)  # DataFrame[case, log2_tpm]

    strata = sorted(assignments.loc[assignments["is_member"] == True, "stratum_id"].unique().tolist())
    pooled_median = pooled.get("median_log2tpm")
    pooled_detectable = pooled.get("detectable_fraction")

    # Matched-normal vector for the per-subtype therapeutic-WINDOW enrichment (Option 2, 2026-08-04).
    # Fetched ONCE and reused for every stratum: GTEx normal tissue has no tumor molecular subtype, so
    # the SAME normal p95/p99 threshold applies to each tumor stratum (a subtype's tumors are compared
    # against the indication's whole matched-normal). This is the per-subtype analogue of the pooled
    # read_tumor_vs_normal_percentile_crossing — same _stats primitive, subtype tumor vector as input.
    normal_vals, normal_tissue = read_normal_samples(target, indication)

    # PROXY-normal panel (2026-08-04) — ONLY when there is no true matched normal (e.g. HNSC). Reads
    # each configured proxy tissue's vector once; the per-stratum loop computes the window against EACH
    # so the reader sees window-SENSITIVITY to proxy choice. Kept strictly OFF the matched-normal
    # channel: a proxy window is histologically-analogous, weaker evidence, explicitly labeled.
    proxy_specs = INDICATION_TO_PROXY_NORMAL_TISSUES.get(indication.upper().strip(), [])
    proxy_normals = {}   # {tissue: (values, rationale)}
    if not normal_vals and proxy_specs:
        _all_tissues = read_all_normal_tissues(target)   # {tissue: [values]} one read, all tissues
        for tissue, rationale in proxy_specs:
            vals_t = _all_tissues.get(tissue) or []
            if vals_t:
                proxy_normals[tissue] = (vals_t, rationale)

    landscape = []
    powered_vectors = {}   # {stratum_id: [log2tpm]} for POWERED strata — the omnibus input
    for stratum_id in strata:
        member_cases = set(assignments.loc[
            (assignments["stratum_id"] == stratum_id) & (assignments["is_member"] == True),
            "sample_id"])
        sub = bridged[bridged["case"].isin(member_cases)]
        vals = sub["log2_tpm"].tolist()
        n = len(vals)
        floor_met = n >= _SUBGROUP_N_FLOOR
        if floor_met:
            powered_vectors[stratum_id] = vals
        state = _evstate(n, floor_met)
        # join-coverage guard: warns on the <5% id-convention-mismatch signature.
        cov = compute_join_coverage(bridged, "case", stratum_id, manifest, warn=True)
        rec = {"stratum_id": stratum_id, "evidence_state": state,
               "subgroup_n_floor_met": floor_met, "n_tumor_samples": n,
               "match_rate": cov.match_rate}
        if n > 0:
            summary = _distribution_summary(vals)
            # Option 1 (2026-08-04): project the FULL distribution block per stratum (was 5 fields) so
            # a per-subtype record has the same absolute-level depth as the pooled record — percentiles
            # + spread. _distribution_summary already computes these; this just stops dropping them.
            rec.update({k: summary[k] for k in
                        ("median_log2tpm", "p95_log2tpm", "p99_log2tpm", "min_log2tpm",
                         "max_log2tpm", "coefficient_of_variation", "detectable_fraction",
                         "high_fraction", "moderate_fraction", "distribution_pattern",
                         "tumor_expression_class")})
            # Option 2 (2026-08-04): per-subtype matched-normal WINDOW — fraction of this subtype's
            # tumors clearing the (indication-wide) matched-normal Nth percentile. The decision-relevant
            # patient-selection signal, now answerable per subtype (was pooled-only). Null when the
            # indication has no matched GTEx normal (honest gap), NOT zero.
            if normal_vals:
                for pct in (95, 99):
                    fa = _stats.fraction_above_normal_percentile(vals, normal_vals, pct)
                    rec[f"fraction_tumor_above_normal_p{pct}"] = fa["fraction_tumor_above"]
                    rec[f"normal_p{pct}_log2tpm"] = fa["normal_pN"]
                rec["distribution_overlap_tumor_normal"] = _stats.distribution_overlap(vals, normal_vals)
            else:
                rec.update({"fraction_tumor_above_normal_p95": None,
                            "fraction_tumor_above_normal_p99": None,
                            "normal_p95_log2tpm": None, "normal_p99_log2tpm": None,
                            "distribution_overlap_tumor_normal": None})
            # PROXY window panel (labeled, never the matched channel). One entry per proxy tissue:
            # this subtype's tumors vs that proxy's p95/p99 + overlap. Empty list when a true normal
            # exists (proxies not needed) or none configured — the caller reads this as "proxy-only".
            proxy_windows = []
            for tissue, (pvals, rationale) in proxy_normals.items():
                pw = {"proxy_tissue": tissue, "rationale": rationale}
                for pct in (95, 99):
                    fa = _stats.fraction_above_normal_percentile(vals, pvals, pct)
                    pw[f"fraction_tumor_above_proxy_p{pct}"] = fa["fraction_tumor_above"]
                    pw[f"proxy_p{pct}_log2tpm"] = fa["normal_pN"]
                pw["distribution_overlap_tumor_proxy"] = _stats.distribution_overlap(vals, pvals)
                proxy_windows.append(pw)
            rec["proxy_normal_windows"] = proxy_windows
            # subtype signal is only trustworthy when the stratum clears the floor;
            # underpowered strata carry stats for context but a null signal.
            rec["subtype_signal"] = (_classify_subtype_signal(
                summary["median_log2tpm"], pooled_median,
                summary["detectable_fraction"], pooled_detectable)
                if floor_met else None)
        else:
            rec.update({"median_log2tpm": None, "p95_log2tpm": None, "p99_log2tpm": None,
                        "min_log2tpm": None, "max_log2tpm": None, "coefficient_of_variation": None,
                        "detectable_fraction": None, "high_fraction": None, "moderate_fraction": None,
                        "distribution_pattern": None, "tumor_expression_class": "data_unavailable",
                        "fraction_tumor_above_normal_p95": None, "fraction_tumor_above_normal_p99": None,
                        "normal_p95_log2tpm": None, "normal_p99_log2tpm": None,
                        "distribution_overlap_tumor_normal": None, "proxy_normal_windows": [],
                        "subtype_signal": None})
        landscape.append(rec)

    n_measured = sum(1 for r in landscape if r["evidence_state"] == "measured")
    n_enriched = sum(1 for r in landscape if r.get("subtype_signal") == "subtype_enriched")
    # Rollup of the per-subtype WINDOW signal (Option 2): how many measured subtypes clear the
    # matched-normal p95 in a majority of their tumors (fraction_above >= 0.5) — the count of subtypes
    # with a real therapeutic window. None when there is no matched normal (window not computable).
    n_window = (sum(1 for r in landscape
                    if r["evidence_state"] == "measured"
                    and (r.get("fraction_tumor_above_normal_p95") or 0) >= 0.5)
                if normal_vals else None)
    # Per-PROXY rollup (2026-08-04): the matched rollup above is a single count, but proxy windows are
    # MULTI-VALUED (one per proxy tissue) — a squamous-TF target can clear the salivary window in most
    # subtypes yet the skin window in few (the TP63/HNSC case). A single proxy count would over-simplify
    # that, so this is a {proxy_tissue: n_measured_subtypes_clearing_its_p95_in_>=50%} map, mirroring the
    # matched threshold. None when there is no proxy channel (a matched or absent comparator).
    n_window_by_proxy = None
    if proxy_normals:
        n_window_by_proxy = {}
        for tissue in proxy_normals:
            n_window_by_proxy[tissue] = sum(
                1 for r in landscape if r["evidence_state"] == "measured"
                and any((pw.get("proxy_tissue") == tissue
                         and (pw.get("fraction_tumor_above_proxy_p95") or 0) >= 0.5)
                        for pw in (r.get("proxy_normal_windows") or [])))
    # Comparator provenance: matched (true tissue-of-origin), proxy (histological analogue, weaker),
    # or none (neither available). Kept explicit so a consumer NEVER mistakes a proxy for a matched
    # normal — the window numbers mean different things and must be weighted differently.
    comparator_type = ("matched" if normal_vals else
                       "proxy" if proxy_normals else "none")

    # STRATIFICATION signal (2026-08-04) — graded patient-selection class for the biomarker facet.
    n_restricted = sum(1 for r in landscape
                       if r["evidence_state"] == "measured" and r.get("subtype_signal") == "subtype_restricted")
    subtype_stratification_class = classify_subtype_stratification(landscape)

    # ACROSS-SUBTYPE OMNIBUS (Phase 3, 2026-08-05) — Kruskal-Wallis H + ε² variance-explained
    # over the POWERED strata's per-sample vectors. Answers "is subtype a patient-selection axis
    # for this target, and how much of the expression variance does it explain?" The per-stratum
    # subtype_signal above is a PAIRWISE-vs-pooled call; this is the single OMNIBUS across all
    # strata. Effect-size class bins on ε² ONLY (p is display-only: at TCGA n's KW p is near-always
    # significant, so significance != actionability). One-directional context — like the rest of
    # this card, never moves presence_verdict.
    omnibus = _stats.kruskal_epsilon_squared(powered_vectors)

    base.update({"subtype_axis_available": True, "subtype_landscape": landscape,
                 "assignment_manifest": manifest, "matched_normal_tissue": normal_tissue,
                 "normal_comparator_type": comparator_type,
                 "proxy_normal_tissues": sorted(proxy_normals.keys()) if proxy_normals else [],
                 "n_subtypes_measured": n_measured, "n_subtypes_enriched": n_enriched,
                 "n_subtypes_restricted": n_restricted,
                 "subtype_stratification_class": subtype_stratification_class,
                 "n_subtypes_clearing_normal_window": n_window,
                 "n_subtypes_clearing_proxy_window_by_tissue": n_window_by_proxy,
                 **omnibus})
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

    pooled_vals = read_tumor_samples(target, indication)
    base_manifest = INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST.get(indication.upper().strip())
    if base_manifest is None or not pooled_vals:
        return {"available": False, "pooled_values": pooled_vals or [], "pooled_median": None,
                "strata": [], "_note": ("no landed tumor assignment shard for this indication"
                                        if base_manifest is None else "target absent")}
    import statistics as _st
    pooled_median = _st.median(pooled_vals)
    bridged = read_tumor_samples_with_case(target, indication)
    # UNION of directly-tagged + maf-filter (genomic) strata — same helper as the landscape reader.
    try:
        assignments, manifest = _load_subtype_assignments(indication)
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
