"""Per-gene reader over the sc-normal-celltype-expression Tier-1 products.

Reads sc-normal-celltype-expression-{tissue}-v1 (one row per cell_type × gene, already
cross-donor-aggregated: median_det, expressing_donor_fraction, n_donors_reliable, etc.).
Products are gene-SORTED — a per-gene read uses pyarrow + predicate-pushdown to touch
few row-groups (same invariant as the bulk and sc_tumor readers).

Dependencies: pyarrow/pandas/boto3 ONLY — no scanpy/anndata/cellxgene-census at read time.
Credential discipline: prefer the onc-compbio `cbg` SSO profile (the Developer-Dev role lacks
GetObject on onc-compbio) but fall back to the ambient credential chain when `cbg` is not
configured (CI / prod / instance-role host) — see _get_s3fs. The former unconditional
`boto3.Session(profile_name="cbg")` crashed the whole read with ProfileNotFound in any non-cbg
env, silently darkening the on-target-safety veto.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import boto3
import pandas as pd
import pyarrow.fs as fs
import pyarrow.parquet as pq
from botocore.exceptions import ProfileNotFound

from onc_methods.normal_tissue_safety_common import SC_NORMAL_ESSENTIAL_TISSUES

from . import stats as _stats

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# Process-wide pyarrow S3FileSystem singleton (see _get_s3fs). Built once, shared across
# every read_gene_celltype_rows call so the SSO-credential resolution is not repeated per
# card/target. pyarrow's S3FileSystem is safe to share across threads for reads.
_S3FS = None
_S3FS_LOCK = threading.Lock()

# tissue name → landed Tier-1 product key.
# Only tissues with sc-normal-celltype-expression-{tissue}-v1 on S3 are listed.
# Others → data_unavailable (honest capability ceiling, never a silent fall-back).
# Keys are the hyphen-free tissue names; product IDs use hyphenated slugs.
# 2026-08-12: brain (critical fix — in card since #298 but missing here), plus 4 new tissues
# now on S3 (data-catalog PR #330 + the normal-tissue batch PRs #275–#286 + expansion set).
TISSUE_TO_PRODUCT = {
    "colon": "sc-normal-celltype-expression-colon-v1",
    "lung": "sc-normal-celltype-expression-lung-v1",
    "heart": "sc-normal-celltype-expression-heart-v1",
    "liver": "sc-normal-celltype-expression-liver-v1",
    "kidney": "sc-normal-celltype-expression-kidney-v1",
    "stomach": "sc-normal-celltype-expression-stomach-v1",
    "bone_marrow": "sc-normal-celltype-expression-bone-marrow-v1",
    "skin": "sc-normal-celltype-expression-skin-v1",
    "small_intestine": "sc-normal-celltype-expression-small-intestine-v1",
    # Added 2026-08-12:
    "brain": "sc-normal-celltype-expression-brain-v1",  # always-on CNS safety (36M cells, 172 types)
    "esophagus": "sc-normal-celltype-expression-esophagus-v1",  # ESCA; squamous-normal proxy for HNSC
    "pancreas": "sc-normal-celltype-expression-pancreas-v1",  # PAAD normal comparator
    "ovary": "sc-normal-celltype-expression-ovary-v1",  # OV normal comparator
    "prostate_gland": "sc-normal-celltype-expression-prostate-gland-v1",  # PRAD normal comparator
    # Added 2026-08-15: complete the map to all 19 landed normal-tissue shards so the card's
    # required_inputs can honestly declare the full atlas (readable via tissues_for_indication /
    # future indication maps; not yet in any indication's always-on scan set).
    "adrenal_gland": "sc-normal-celltype-expression-adrenal-gland-v1",
    "bladder_organ": "sc-normal-celltype-expression-bladder-organ-v1",
    "large_intestine": "sc-normal-celltype-expression-large-intestine-v1",
    "spleen": "sc-normal-celltype-expression-spleen-v1",
    "uterus": "sc-normal-celltype-expression-uterus-v1",
}

# SAFETY-ESSENTIAL tissues queried for EVERY target regardless of indication. On-target
# toxicity in these organs is catastrophic and modality-limiting whether the tumor is colon,
# lung, or anything else — a BiTE/ADC against a target expressed in cardiomyocytes, hepatocytes,
# nephron tubule, or hematopoietic progenitors is dangerous independent of the treated indication.
# So these are ALWAYS included in the liability read, in addition to the indication-matched tissue.
# SINGLE-SOURCED (cards review 2026-08-17, S1-3) from normal_tissue_safety_common — this promotes
# the BRAIN shard (advertised as "always-on CNS safety" but never actually queried → CNS on-target
# tox was silently unassessed for every target) and the ADRENAL_GLAND shard (endocrine hole) to the
# always-on set. Both shards already exist in TISSUE_TO_PRODUCT.
SAFETY_ESSENTIAL_TISSUES = list(SC_NORMAL_ESSENTIAL_TISSUES)

# indication → tumor-matched normal tissue(s). The matched tissue is queried IN ADDITION to the
# always-on SAFETY_ESSENTIAL_TISSUES (see tissues_for_indication).
# 2026-08-12: STAD/ESCA/PAAD/HNSC/OV/PRAD added as 3CA buckets land and new Tier-1 products are
# on S3. HNSC maps to esophagus — the best available squamous-normal proxy (oral/pharyngeal
# mucosa is not a distinct Census tissue_general; squamous esophagus is the closest lineage match).
INDICATION_TO_TISSUES = {
    "COADREAD": ["colon"],
    "COAD": ["colon"],
    "READ": ["colon"],
    "NSCLC": ["lung"],
    "LUAD": ["lung"],
    "LUSC": ["lung"],
    "STAD": ["stomach"],
    "ESCA": ["esophagus"],
    "PAAD": ["pancreas"],
    "HNSC": ["esophagus"],  # squamous-normal proxy (oral/pharyngeal mucosa absent from Census)
    "OV": ["ovary"],
    "PRAD": ["prostate_gland"],
    # 2026-09-04 coverage: (1) WIRE three landed-but-orphaned shards (bladder_organ / skin / uterus)
    # into use — they existed in TISSUE_TO_PRODUCT but no indication mapped to them, so they were never
    # queried; (2) fix ORIGIN-TISSUE correctness for tumors whose tissue-of-origin is an always-on
    # safety-essential organ (kidney/liver/brain) — previously these indications were unmapped, so the
    # origin organ was queried but as OFF-origin, wrongly reading its own-organ essential expression as
    # critical_organ_liability. Adding the origin map softens that to origin_tissue_liability (window-
    # arbitrated) — veto-monotonic (can only downgrade a veto, never create one).
    "BLCA": ["bladder_organ"],
    "SKCM": ["skin"],
    "UCEC": ["uterus"],
    "UCS": ["uterus"],
    "KIRC": ["kidney"],  # renal clear cell — kidney is the tissue-of-origin, not an off-target
    "KIRP": ["kidney"],
    "KICH": ["kidney"],
    "LIHC": ["liver"],  # hepatocellular — liver is the tissue-of-origin
    "GBM": ["brain"],  # glioblastoma — brain is the tissue-of-origin
    "LGG": ["brain"],
}


def tissues_for_indication(indication: str) -> list[str]:
    """Tissues to query for a (target, indication) liability read: the tumor-matched normal
    tissue(s) UNION the always-on safety-essential tissues, de-duplicated, order-stable.
    Safety-essential tissues are queried for EVERY indication (cross-tissue on-target-tox check);
    the matched tissue adds indication-local context. Unknown indication → safety-essential only
    (still a meaningful cross-tissue safety read, never an empty/abstain result)."""
    matched = INDICATION_TO_TISSUES.get(str(indication).upper().strip(), [])
    out: list[str] = []
    for t in matched + SAFETY_ESSENTIAL_TISSUES:
        if t not in out:
            out.append(t)
    return out


_PARQUET_COLS = [
    "gene_symbol",
    "ensembl_gene_id",
    "tissue",
    "cell_type",
    "n_donors_total",
    "n_donors_reliable",
    "n_datasets_reliable",
    "n_donors_expressing",
    "median_det",
    "q25_det",
    "q75_det",
    "expressing_donor_fraction",
    "median_abund",
    "q25_abund",
    "q75_abund",
    "detection_pct_rank",
    "n_cell_types_above_20pct",
]


def _s3_key(tissue: str) -> Optional[str]:
    prod = TISSUE_TO_PRODUCT.get(tissue.lower().strip())
    if not prod:
        return None
    return f"data-catalog/derived/{prod}/sc_normal_expression.parquet"


def _build_s3fs() -> "fs.S3FileSystem":
    """Construct a pyarrow S3FileSystem, preferring the onc-compbio `cbg` SSO profile but
    falling back to the ambient credential chain when `cbg` is not configured.

    The former code did `boto3.Session(profile_name="cbg").get_credentials().get_frozen_credentials()`
    unconditionally (AWS_PROFILE defaults to "cbg"). On a CI / prod / instance-role host the `cbg`
    SSO profile does not exist, so `get_credentials()` raised `ProfileNotFound` (or returned None →
    AttributeError) and the exception escaped the whole read — the skill seam then converted it to
    `_live_read_error`, silently darkening the on-target-safety veto for all tissues. This mirrors
    `target_id_sidecar.s3_client`'s ProfileNotFound→ambient fallback (and the sibling
    tcga_gtex `_get_s3fs`): try the preferred profile's frozen creds; if the profile is absent or
    yields no creds, use a bare S3FileSystem that resolves via the default chain (env / OIDC /
    instance role), exactly as the ambient path it degrades to."""
    profile = os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    creds = None
    try:
        creds = boto3.Session(profile_name=profile).get_credentials()
    except ProfileNotFound:
        creds = None  # cbg absent (CI / prod / instance-role) → ambient chain below
    if creds is not None:
        frozen = creds.get_frozen_credentials()
        return fs.S3FileSystem(
            region="us-east-1",
            access_key=frozen.access_key,
            secret_key=frozen.secret_key,
            session_token=frozen.token,
        )
    # No configured profile / no creds resolvable → ambient credential chain.
    return fs.S3FileSystem(region="us-east-1")


def _get_s3fs() -> "fs.S3FileSystem":
    """Process-wide S3FileSystem singleton (double-checked locking). Building one re-resolves the
    SSO credential chain, which is wasted work when this reader fires once per card/target across a
    run; build it once and share it (thread-safe for reads)."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                _S3FS = _build_s3fs()
    return _S3FS


def read_gene_celltype_rows(target: str, tissues: list[str]) -> Optional[pd.DataFrame]:
    """Per-cell_type Tier-1 rows for one gene across the requested tissues.

    Returns a concatenated DataFrame (possibly empty), or None when no Tier-1 product
    exists for ANY of the requested tissues. Empty (0-row) DataFrame means the gene is
    absent from the product(s); None means no product exists at all.

    Per-tissue coverage accounting is attached to the returned frame's `.attrs`
    (`tissues_requested` / `tissues_with_product` / `tissues_loaded` / `tissues_missing`) so the
    caller can distinguish an examined-clean tissue from a dropped (not-yet-landed) shard and never
    overstate coverage. A per-tissue read that raises a genuine object-absence (NoSuchKey / 404 /
    FileNotFound) is a coverage gap and is recorded in `tissues_missing`; a transient / creds /
    broken-env error is re-raised so the live-read seam surfaces `_live_read_error` rather than a
    false 'not expressed'."""
    s3fs = _get_s3fs()

    # The per-tissue reads are INDEPENDENT single-gene pushdowns against SEPARATE parquet shards
    # (origin tissue + the always-on safety-essential organs — 9 for COADREAD). Reading them in a
    # serial loop paid the sum of the shards' S3 latencies (~3.0s cold on CEACAM5/COADREAD) and made
    # this the tumor-selectivity / tumor-presence critical-path card. Fan the pushdowns out over a
    # bounded ThreadPoolExecutor so the wall collapses toward the SLOWEST single shard (~0.8s,
    # byte-identical rows): pyarrow.parquet.read_table over one shared S3FileSystem is thread-safe,
    # and the reads' I/O releases the GIL. The single-shared s3fs above is built ONCE and reused
    # across workers, so the SSO-credential resolution is not repeated per tissue.
    keyed = [(tissue, _s3_key(tissue)) for tissue in tissues]
    keyed = [(tissue, key) for tissue, key in keyed if key is not None]
    if not keyed:
        return None  # no Tier-1 product exists for ANY requested tissue
    filters = [("gene_symbol", "==", str(target).strip())]

    def _read_one(key: str) -> Optional[pd.DataFrame]:
        try:
            tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs, filters=filters, columns=_PARQUET_COLS)
            return tbl.to_pandas()
        except Exception as e:  # noqa: BLE001
            # Only a GENUINE object-absence (NoSuchKey / 404 / FileNotFound) is a coverage gap for
            # this tissue → None (recorded in tissues_missing). A transient / creds / broken-env
            # error must NOT masquerade as "shard absent" (which would drop the tissue and let the
            # veto be computed as if it were examined-clean) — re-raise so the seam reports
            # _live_read_error. Aligns with the shared is_definitively_absent predicate + the
            # tcga_gtex exemplar.
            from onc_methods.target_id_sidecar import is_definitively_absent

            if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
                raise
            return None  # product not yet on S3 for this tissue — treat as coverage gap

    # Preserve the original tissue ORDER in the concat (executor.map yields in submission order),
    # so the assembled frame is identical to the former serial loop, not completion-order-dependent.
    tissues_kept = [tissue for tissue, _key in keyed]
    with ThreadPoolExecutor(max_workers=len(keyed)) as pool:
        results = list(pool.map(_read_one, [key for _tissue, key in keyed]))
    # Per-tissue attempted/loaded accounting: a frame (even 0-row) = shard PRESENT and examined;
    # None = shard genuinely absent on S3 (dropped, a coverage gap). This distinction is what lets
    # read_target_summary avoid overstating coverage / flag a missing safety-essential shard.
    tissues_loaded = [tissue for tissue, df in zip(tissues_kept, results) if df is not None]
    tissues_missing = [tissue for tissue, df in zip(tissues_kept, results) if df is None]
    dfs = [df for df in results if df is not None]
    out = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    out.attrs["tissues_requested"] = list(tissues)
    out.attrs["tissues_with_product"] = tissues_kept  # had a Tier-1 product key
    out.attrs["tissues_loaded"] = tissues_loaded  # shard read OK (present, examined)
    out.attrs["tissues_missing"] = tissues_missing  # shard absent on S3 (coverage gap)
    return out


def read_target_summary(target: str, indication: str) -> dict:
    """Assemble the sc-normal-celltype-expression summary for a (target, indication).

    Queries the tumor-matched normal tissue(s) UNION the always-on safety-essential tissues
    (heart/liver/kidney/bone_marrow), reads the Tier-1 parquet via predicate-pushdown, classifies
    the normal-tissue liability across ALL queried cell types, and returns a summary dict with
    `sc_normal_expression_class` as the primary field. data_unavailable-safe on both "no product"
    and "gene absent from product". Because safety-essential tissues are always included, even an
    unknown indication yields a meaningful cross-tissue safety read (never an abstain-by-mapping-gap)."""
    tissues = tissues_for_indication(indication)
    rows = read_gene_celltype_rows(target, tissues)
    if rows is None:
        return _data_unavailable(
            target,
            indication,
            note=f"No sc-normal-celltype-expression product landed for "
            f"tissues {tissues}; coverage gap, not a safety pass.",
        )
    # Per-tissue coverage accounting (attrs absent on older / monkeypatched callers → degrade
    # gracefully to the un-split behavior).
    cov = getattr(rows, "attrs", None) or {}
    tissues_loaded = cov.get("tissues_loaded")  # None when unknown
    tissues_missing = cov.get("tissues_missing") or []
    essential_missing = [t for t in tissues_missing if t in set(SAFETY_ESSENTIAL_TISSUES)]
    if rows.empty:
        # Distinguish a genuine coverage gap (every shard was missing on S3) from a measured
        # absence (shards examined clean, gene simply not detected). The former must NOT be spelled
        # "not measured in the Census atlases" — that mislabels a coverage hole as a safety read.
        if tissues_loaded is not None and len(tissues_loaded) == 0:
            note = (
                f"No sc-normal-celltype-expression shard returned for tissues {tissues} "
                f"(all shards missing on S3: {tissues_missing}); coverage gap, not a safety pass."
            )
        else:
            note = (
                f"{target} absent from sc-normal-celltype-expression products "
                f"for tissues {tissues_loaded if tissues_loaded is not None else tissues} "
                f"(examined clean, not measured in the Census atlases)."
            )
        result = _data_unavailable(target, indication, note=note)
        result["tissues_loaded"] = tissues_loaded if tissues_loaded is not None else []
        result["tissues_missing"] = tissues_missing
        result["essential_tissues_missing"] = essential_missing
        return result
    # origin_tissues = the tumor's tissue-of-origin ONLY (matched normal), NOT the always-on
    # safety-essential organs — so the classifier can split origin-tissue essential expression
    # (on-tissue, therapeutic-window-arbitrated) from non-origin critical-organ expression (hard veto).
    origin_tissues = INDICATION_TO_TISSUES.get(str(indication).upper().strip(), [])
    result = _stats.classify_sc_normal_expression(rows, origin_tissues=origin_tissues)
    result["tissues_queried"] = tissues
    result["origin_tissues"] = origin_tissues
    result["indication"] = str(indication).upper().strip()
    # Coverage transparency: which requested tissues actually returned a shard vs were dropped, so
    # the veto/class is never read as a clean examination of a safety-essential organ whose shard
    # silently failed to load. Falls back to the full requested set when accounting is unavailable.
    result["tissues_loaded"] = tissues_loaded if tissues_loaded is not None else tissues
    result["tissues_missing"] = tissues_missing
    result["essential_tissues_missing"] = essential_missing
    if essential_missing:
        result["sc_normal_coverage_caveat"] = (
            f"safety-essential shard(s) {essential_missing} missing from S3; the essential-tissue "
            f"veto/class was computed over the examined tissues only ({tissues_loaded}), NOT a clean "
            f"read of those organs — treat the safety call as coverage-limited, not a clean pass."
        )
    return result


def _data_unavailable(target: str, indication: str, note: str) -> dict:
    base = _stats._data_unavailable_class(note=note)
    base["tissues_queried"] = tissues_for_indication(indication)
    # Mirror the success arm's `origin_tissues` (read_target_summary:success) so a consumer reading
    # that field does not KeyError on the abstention arm — the arms must carry the same schema.
    base["origin_tissues"] = INDICATION_TO_TISSUES.get(str(indication).upper().strip(), [])
    base["indication"] = str(indication).upper().strip()
    return base
