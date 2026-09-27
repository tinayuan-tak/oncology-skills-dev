"""cptac_protein_deg.read — CPTAC protein tumor-vs-normal DEG reader.

Consumer: tumor-protein-abundance-cptac + surface-abundance-density evidence cards
(Phase A + F). Emits per-(target, cohort) protein-level tumor-vs-normal
differential expression stats from CPTAC-PDC mass-spec data (10 cohorts).

Cohorts: BRCA, CCRCC, COAD, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.

Runtime discipline (v2, 2026-07-10):
  - Column-array iteration to build (cohort, gene) index (NOT df.iterrows —
    the pattern the kinome-atlas PR #7 refactored away from).
  - Lazy per-target row materialization: keep DataFrame in memory,
    materialize only the row(s) for a specific target at query time.
  - @lru_cache(maxsize=1) on load+index — cold path runs ONCE per process.
  - Module-level negative cache when derived not on S3.

Reads: derived parquet at
    s3://onc-compbio/data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/
Falls back to `data_unavailable` gracefully when derived product not on S3.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path
from statistics import NormalDist

_STD_NORMAL = NormalDist()


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def _is_finite_num(x) -> bool:
    """`_is_num` rejects ONLY NaN — it admits +/-Inf. MSstatsTMT signals an UNESTIMABLE contrast with
    log2FC = +/-Inf (see `_unestimable_reason`), so every guard whose job is to reject a non-computable
    effect needs THIS predicate. The distinction is not academic: on the shipped v1.2.0 product 1,618
    rows carry +/-Inf, and `isna()`-shaped guards let all 1,618 through as if they were measurements."""
    return _is_num(x) and math.isfinite(float(x))


def _finite_effect_or_nan(row) -> float:
    """|protein_effect_size| for RANKING, with a non-finite effect ranked LAST (never first).

    `abs(float(inf))` is `inf`, so an `max(..., key=abs-effect)` argmax over a target's cohort rows
    lets an UNESTIMABLE row beat every real measurement. Measured on the shipped product: 1,564 of the
    1,618 affected genes had their pan-cancer row hijacked by BRCA's unestimable contrast, and 32 of
    those shadowed a genuine strong_up call in another cohort (ESCO2 reported BRCA/unestimable instead
    of LUAD +3.30; CMTM3 instead of GBM +2.94; ADAM12 instead of GBM +2.37)."""
    v = row.get("protein_effect_size")
    return abs(float(v)) if _is_finite_num(v) else -1.0


def _finite_cohens_d_or_nan(row) -> float:
    """|Cohen's d| for CROSS-COHORT ranking on the COMPARABLE standardized axis (#1664 F1).

    `protein_effect_size` is a within-cohort, reference-pool-relative TMT log2 ratio; the product
    manifest states its magnitude is NOT cross-cohort comparable (per-plex reference pool, per-cohort
    Tumor-Normal contrast) and to treat cross-cohort magnitude comparisons as unreliable. Ranking
    cohorts by |raw effect| to pick a single "representative" therefore compares a quantity the producer
    says is not comparable. Cohen's d (variance-standardized, sample-size-INDEPENDENT) is the sound
    cross-cohort currency, so the representative-cohort pick ranks on it. A non-finite / unstandardizable
    effect ranks LAST (never wins an argmax), mirroring `_finite_effect_or_nan`. The Cohen's d is
    recomputed from the raw df row via `_standardized_effect` (raw p is materialized per gene x cohort,
    so d is computable for every ESTIMABLE row without a product rebuild)."""
    d = _standardized_effect(
        row.get("protein_effect_size"),
        row.get("protein_p_value"),
        row.get("protein_effect_size_se"),
        row.get("n_tumor_samples"),
        row.get("n_normal_samples"),
    ).get("protein_effect_cohens_d")
    return abs(float(d)) if _is_finite_num(d) else -1.0


def _cohens_d_rank_key(row):
    """Cross-cohort representative-pick key (#1664 F1): rank by |Cohen's d| (the comparable axis),
    with |raw effect| as a DETERMINISTIC tiebreak. The tiebreak only decides ties on the standardized
    axis (incl. the degenerate all-unstandardizable case where every d is -1), so the pick reduces to
    the prior raw-|effect| behaviour ONLY when the standardized axis cannot separate the cohorts."""
    return (_finite_cohens_d_or_nan(row), _finite_effect_or_nan(row))


def _cohens_d_class(d: float) -> str:
    ad = abs(d)
    if ad >= 0.8:
        return "large"
    if ad >= 0.5:
        return "medium"
    if ad >= 0.2:
        return "small"
    return "negligible"


def _standardized_effect(effect_size, p_value, se, n_tumor, n_normal) -> dict:
    """VARIANCE-STANDARDIZED companion to the raw log2 `protein_effect_size` (which the
    protein_expression_class thresholds on at fixed +/-0.5 / +/-1.5 cutoffs, blind to variance).

    Prefers the EXACT MSstatsTMT moderated standard error (`protein_effect_size_se`, carried by
    03_pool once rebuilt): standardized t = logFC / SE. When SE is absent (the pre-rebuild product),
    recovers an APPROXIMATE t from the two-sided p-value (z = sign(logFC) * Phi^-1(1 - p/2)) — exact
    for the z-scale, large-df approximation for the moderated t. Cohen's d (a sample-size-INDEPENDENT
    effect size) = t / sqrt(n_eff), n_eff = n_t*n_n/(n_t+n_n). The class bands are the conventional
    negligible/small/medium/large. All fields are display-only / verdict-inert."""
    out = {
        "protein_effect_size_se": (float(se) if _is_num(se) else None),
        "protein_effect_standardized_t": None,
        "protein_effect_cohens_d": None,
        "protein_effect_standardized_class": "data_unavailable",
        "protein_effect_standardized_method": "data_unavailable",
    }
    if not _is_num(effect_size):
        return out
    t = method = None
    if out["protein_effect_size_se"] is not None and out["protein_effect_size_se"] > 0:
        t, method = effect_size / out["protein_effect_size_se"], "moderated_se_exact"
    elif _is_num(p_value) and 0.0 <= p_value <= 1.0:
        # clamp the inv_cdf ARGUMENT into the open (0,1) interval — a raw p of 0 floors 1-p/2 to exactly
        # 1.0 in float, which NormalDist.inv_cdf rejects; this caps |z| at ~7.94 (display-grade).
        arg = min(max(1.0 - p_value / 2.0, 1e-15), 1.0 - 1e-15)
        z = _STD_NORMAL.inv_cdf(arg)  # |z| for a two-sided p
        t, method = math.copysign(z, effect_size), "pvalue_zscore_approx"
    if t is None:
        return out
    out["protein_effect_standardized_t"] = round(t, 4)
    out["protein_effect_standardized_method"] = method
    if _is_num(n_tumor) and _is_num(n_normal) and n_tumor > 0 and n_normal > 0:
        n_eff = (n_tumor * n_normal) / (n_tumor + n_normal)
        d = t / math.sqrt(n_eff)
        out["protein_effect_cohens_d"] = round(d, 4)
        out["protein_effect_standardized_class"] = _cohens_d_class(d)
    return out


from typing import Optional

from methods.catalog_query.read import bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "cptac-protein-tumor-vs-normal-per-cohort-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, DERIVED_S3_KEY = bucket_key_for(DERIVED_MANIFEST_ID)

# Per-SAMPLE product (cptac-protein-tumor-vs-normal-per-sample-v1): the per-aliquot
# log-ratios the per-cohort summary threw away. Backs the true tumor-vs-normal
# distribution boxplot + honest per-cohort statistics (Welch + Mann-Whitney). 127 MB,
# sorted by (gene_symbol, cohort) so a per-gene predicate-pushdown read (read_per_sample) STREAMS a
# few row-groups off S3 instead of downloading the whole product. See data-catalog manifest
# cptac-protein-tumor-vs-normal-per-sample-v1.
PER_SAMPLE_MANIFEST_ID = "cptac-protein-tumor-vs-normal-per-sample-v1"

_DERIVED_STATUS: Optional[bool] = None

# Indication → CPTAC cohort code mapping (some indications share codes)
INDICATION_TO_CPTAC = {
    "BRCA": "BRCA",
    "CCRCC": "CCRCC",
    "COAD": "COAD",
    "COADREAD": "COAD",
    "GBM": "GBM",
    "HNSC": "HNSCC",
    "HNSCC": "HNSCC",
    "LUSC": "LSCC",
    "LSCC": "LSCC",  # CPTAC uses LSCC for lung squamous
    "LUAD": "LUAD",
    "OV": "OV",
    "PAAD": "PDAC",
    "PDAC": "PDAC",
    "UCEC": "UCEC",
}


import threading

_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1 — the onc-compbio bucket).

    Constructing one costs ~0.4s (client init + region probe) and the per-sample distribution path
    fires several times per card render (the three figure emitters + per_cohort_distribution_stats),
    so we build it ONCE instead of per read. pyarrow's S3FileSystem is safe to share across threads
    for reads (the parallel card-read path); double-checked locking so concurrent first-callers build
    a single instance. Region is pinned to skip the region-probe round-trip. Mirrors the sibling
    methods/dge_deseq2/read.py::_get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as fs

                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _ensure_derived_cached() -> Optional[str]:
    """Resolve the STREAMABLE remote source ("bucket/key") for the per-cohort derived product.

    STREAMED read (2026-08-22 data-layer hardening): the old path did `s3.download_file(...)` of the
    whole ~9 MB per-cohort parquet to a local ~/.cache file and then `pd.read_parquet(local)`. This
    reader consumes the product in FULL — `_load_indexed` builds a process-wide (cohort, gene) index
    AND `_allgene_effect_percentile` needs every gene's effect_size within a cohort — so there is no
    single-target predicate to push down; but we STREAM the row-groups directly off S3 via a pyarrow
    S3FileSystem (see `_load_indexed`'s `pd.read_parquet(..., filesystem=_get_s3fs())`) instead of the
    local download + re-read (drops the disk round-trip; bucket/key stay resolved from the manifest).

    Returns the remote "bucket/key" URI when the object is PRESENT; None when it is DEFINITIVELY absent
    (a genuine 404 / NotFound -> honest data_unavailable, latched in `_DERIVED_STATUS` for the process).
    A TRANSIENT / creds / broken-env error is NOT latched (leaves `_DERIVED_STATUS` None so a later
    call retries) and PROPAGATES — never masked as a false data_unavailable (absence discipline; the
    stream read in `_load_indexed` must NOT swallow, so absence is classified here at the source probe).
    """
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    uri = f"{S3_BUCKET}/{DERIVED_S3_KEY}"
    if _DERIVED_STATUS is True:
        return uri
    # First call: probe existence so a genuinely-missing object latches data_unavailable exactly as
    # the old download_file 404 path did. get_file_info returns a NotFound FileInfo (no raise) for a
    # missing key; only creds/transient failures raise here.
    import pyarrow.fs as pafs

    try:
        info = _get_s3fs().get_file_info(uri)
    except Exception as e:  # noqa: BLE001
        # Absence discipline: latch False ONLY on a DEFINITIVE no-object (NoSuchKey/NoSuchBucket/404);
        # a TRANSIENT / creds / broken-env error (ExpiredToken, AccessDenied, throttling, missing
        # botocore) leaves _DERIVED_STATUS None (later call retries) and PROPAGATES as an honest
        # _live_read_error, never a silent data_unavailable for the process lifetime.
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e):
            _DERIVED_STATUS = False
            return None
        raise
    if info.type == pafs.FileType.NotFound:
        _DERIVED_STATUS = False
        return None
    _DERIVED_STATUS = True
    return uri


# Verdict-bearing columns the derived parquet must carry. A `.get(..., default)` read of any of
# these (the pre-#715 pattern) silently fabricates a value for EVERY gene on drift instead of
# raising — see the schema-drift guard in _load_indexed.
_REQUIRED_COLS = ("protein_expression_class", "protein_effect_size", "protein_effect_size_se")


@lru_cache(maxsize=1)
def _load_indexed():
    """Load derived parquet + build (cohort, gene) index + gene-only index + per-cohort null.

    Returns (df, cohort_gene_idx, gene_idx, cohort_effect_null):
        - df: pandas.DataFrame with all rows (~180K rows across 10 cohorts,
          fits trivially in memory).
        - cohort_gene_idx: dict[(cohort, gene_upper) -> row_index_in_df]
        - gene_idx: dict[gene_upper -> list[row_index_in_df]] (across cohorts)
        - cohort_effect_null: dict[cohort_upper -> list[protein_effect_size]], the per-cohort
          all-gene percentile null consumed by _allgene_effect_percentile (see below).
        Empty structures if load failed.
    """
    path = _ensure_derived_cached()
    if path is None:
        import pandas as pd

        return pd.DataFrame(), {}, {}, {}

    import pandas as pd

    # `path` is the remote "bucket/key" URI that _ensure_derived_cached resolved + existence-probed —
    # the S3 absence (404/NotFound) is latched THERE, returning path=None above (honest
    # data_unavailable). Here we STREAM the row-groups off S3 via the pyarrow S3FileSystem singleton
    # (no whole-file download to disk). A failure to read a PRESENT object is broken-env (missing
    # pyarrow), a corrupt product, or a transient/creds error — NOT data absence — so it must
    # PROPAGATE (surfaces as an honest _live_read_error at the compose-dashboard live-read seam),
    # never be masked as an empty frame. @lru_cache does not memoize an exception, so a raise here
    # also avoids the poison-on-failure the old return-empty caused (a cached empty result would have
    # dead-axed the process for its lifetime).
    df = pd.read_parquet(path, filesystem=_get_s3fs())

    # Schema-drift guard (#715 D): a present, non-empty-schema parquet missing one of the
    # verdict-bearing columns means the provider rebuild renamed/dropped it — NOT that every gene
    # is genuinely absent. `_row_to_summary`'s `row.get("protein_expression_class", "not_significant")`
    # would otherwise fabricate "tested, no difference" for every gene and a missing
    # protein_effect_size would silently collapse the whole product to data_unavailable, with no
    # signal anything broke. Raise loud instead, matching the target_id_sidecar
    # .read_resolver_sidecar_map / dge_deseq2.read_dge_gene_row (#712) schema-drift pattern. A
    # genuinely EMPTY product (0 rows, intact schema) still degrades cleanly below.
    _missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if _missing:
        raise ValueError(
            f"schema drift: manifest {DERIVED_MANIFEST_ID!r} missing expected column(s) "
            f"{_missing!r} (present: {list(df.columns)[:10]})"
        )

    if df.empty:
        return df, {}, {}, {}

    # Column-array iteration (NOT iterrows). Direct numpy access.
    cohort_gene_idx: dict[tuple, int] = {}
    gene_idx: dict[str, list[int]] = {}
    # Per-cohort all-gene percentile null (#715 O), built ONCE here (inside the lru_cache) instead
    # of via a `df["cohort"].str.upper() == cohort` full-column recompute on every
    # _allgene_effect_percentile call (a warm path fired once per gene query).
    cohort_effect_null: dict[str, list] = {}

    cohort_col = df["cohort"].values
    gene_col = df["gene_symbol"].values
    effect_col = df["protein_effect_size"].values
    for idx in range(len(df)):
        cohort = str(cohort_col[idx]).strip().upper()
        gene = str(gene_col[idx]).strip().upper()
        if not cohort or not gene:
            continue
        cohort_gene_idx[(cohort, gene)] = idx
        gene_idx.setdefault(gene, []).append(idx)
        cohort_effect_null.setdefault(cohort, []).append(effect_col[idx])

    return df, cohort_gene_idx, gene_idx, cohort_effect_null


def _unestimable_reason(row) -> Optional[str]:
    """Is this row's tumor-vs-normal contrast UNESTIMABLE rather than flat? Returns an audit reason, or
    None when the contrast was genuinely estimated.

    MSstatsTMT's `groupComparisonTMT` does not emit NA for a protein quantified in only ONE condition —
    it emits log2FC = +/-Inf with NA p-value / NA adj.pvalue / NA SE (its own `oneConditionMissing`
    issue). `Inf` is not `NaN`, so the `pd.isna(logfc) or pd.isna(q)` guard in
    steps/03_pool_and_write.py::classify falls through to its `q >= 0.05` arm and labels the row
    `not_significant` — "we tested this protein and found no tumor-vs-normal difference". That is the
    opposite of the truth: the ratio has no denominator, so no difference was ever tested.

    Measured on the shipped v1.2.0 product (101,013 rows): 1,618 rows are affected — BRCA 1,613 of
    10,491 (15.4%) and GBM 5 — and ALL 1,618 carry NaN q AND NaN SE, so finiteness of the effect size is
    a complete and sufficient discriminator. 1,616 lack the NORMAL median (quantified in zero normal
    aliquots) and 2 lack the TUMOR median. STEAP1/BRCA is the motivating case: quantified in 85 tumor
    aliquots and 0 of the cohort's normal aliquots, shipped as `not_significant`.

    Deliberately NOT rescued UPWARD to an elevated call. Zero quantifications across 18 (BRCA) normal
    aliquots is consistent with a tumor-restricted antigen, but whole-proteome TMT cannot assert
    per-gene absence at that n — the same reason the card's G2a note removed `not_detected` from this
    card's vocabulary. `data_unavailable` is the honest posture: absence of a measurement, carried as
    ignorance (it drops out of the certainty min and into unknown_mass) rather than as agreement."""
    eff = row.get("protein_effect_size")
    if _is_finite_num(eff):
        return None
    if not _is_num(eff):
        return "unestimable_contrast: no protein_effect_size (contrast not computed)"
    # +/-Inf: name the SIDE of the contrast that had no quantification, from the surviving median.
    if not _is_num(row.get("protein_median_log2_normal")):
        side = "quantified in ZERO normal aliquots"
    elif not _is_num(row.get("protein_median_log2_tumor")):
        side = "quantified in ZERO tumor aliquots"
    else:
        side = "one condition entirely missing"
    n_t, n_n = row.get("n_tumor_samples"), row.get("n_normal_samples")
    return (
        f"unestimable_contrast: MSstatsTMT log2FC={float(eff):+.0f} ({side}; cohort "
        f"n_tumor={n_t}, n_normal={n_n}) — no tumor-vs-normal difference was tested"
    )


def _row_to_summary(
    row: dict, matched_cohort: str, allgene_percentile: float = None, allgene_percentile_class: str = "data_unavailable"
) -> dict:
    # UNESTIMABLE CONTRAST -> data_unavailable, NOT `not_significant`. Every downstream numeric field is
    # nulled: an +Inf effect size is not JSON-serializable, distorts the all-gene percentile null, and
    # wins any |effect| argmax. The medians are PRESERVED — the one side that WAS quantified is a real
    # measurement and the only evidence a reader has about why the contrast failed.
    unestimable = _unestimable_reason(row)
    if unestimable:
        out = _empty(unestimable)
        out["cohort"] = matched_cohort
        out["protein_contrast_estimable"] = False
        # The median for the side that HAD no quantification is NaN. Carry the surviving one and null the
        # other: NaN is no more JSON-serializable than Inf, and `None` is the honest "not measured".
        med_t, med_n = row.get("protein_median_log2_tumor"), row.get("protein_median_log2_normal")
        out["protein_median_log2_tumor"] = float(med_t) if _is_finite_num(med_t) else None
        out["protein_median_log2_normal"] = float(med_n) if _is_finite_num(med_n) else None
        out["n_tumor_samples"] = row.get("n_tumor_samples")
        out["n_normal_samples"] = row.get("n_normal_samples")
        out["stat_test_used"] = row.get("stat_test_used", "msstatstmt_limma_ebayes_moderated")
        out["method_version"] = row.get("method_version", "1.0.0")
        out["_data_source"] = DERIVED_MANIFEST_ID
        # Keep the card-declared percentile trio present (declared-field mirror guard) but null — there is
        # no effect size to rank against the cohort null.
        out["allgene_percentile"] = None
        out["allgene_percentile_class"] = "data_unavailable"
        out["allgene_percentile_context"] = None
        return out
    return {
        "cohort": matched_cohort,
        "protein_expression_class": row.get("protein_expression_class", "not_significant"),
        "protein_contrast_estimable": True,
        "protein_effect_size": row.get("protein_effect_size"),
        # All-gene percentile null (additive, display + companion categorical): where the
        # target's protein_effect_size falls among ALL genes tested in THIS cohort.
        "allgene_percentile": allgene_percentile,
        "allgene_percentile_class": allgene_percentile_class,
        "allgene_percentile_context": (
            f"cptac-protein-tumor-vs-normal cohort={matched_cohort} metric=protein_effect_size"
        )
        if matched_cohort
        else None,
        "protein_bh_q_value": row.get("protein_bh_q_value"),
        "protein_p_value": row.get("protein_p_value"),
        "protein_median_log2_tumor": row.get("protein_median_log2_tumor"),
        "protein_median_log2_normal": row.get("protein_median_log2_normal"),
        "n_tumor_samples": row.get("n_tumor_samples"),
        "n_normal_samples": row.get("n_normal_samples"),
        # Variance-standardized companion to the raw log2 effect_size (the class thresholds on the raw
        # log2, blind to variance). Exact (logFC/SE) once the product is rebuilt with SE; p-value
        # approximation on the current product. Display-only / verdict-inert.
        **_standardized_effect(
            row.get("protein_effect_size"),
            row.get("protein_p_value"),
            row.get("protein_effect_size_se"),
            row.get("n_tumor_samples"),
            row.get("n_normal_samples"),
        ),
        "stat_test_used": row.get("stat_test_used", "msstatstmt_limma_ebayes_moderated"),
        "method_version": row.get("method_version", "1.0.0"),
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "cohort": None,
        "protein_expression_class": "data_unavailable",
        # None = "no row at all" (target/cohort absent); False = a row exists but its contrast is
        # unestimable (see _unestimable_reason); True = a real tumor-vs-normal estimate.
        "protein_contrast_estimable": None,
        "protein_effect_size": None,
        "protein_bh_q_value": None,
        "protein_p_value": None,
        "protein_median_log2_tumor": None,
        "protein_median_log2_normal": None,
        "n_tumor_samples": None,
        "n_normal_samples": None,
        "protein_effect_size_se": None,
        "protein_effect_standardized_t": None,
        "protein_effect_cohens_d": None,
        "protein_effect_standardized_class": "data_unavailable",
        "protein_effect_standardized_method": "data_unavailable",
        "stat_test_used": "skipped_low_n",
        "method_version": "1.0.0",
        "_data_note": note,
    }


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target CPTAC protein tumor-vs-normal DEG summary.

    Args:
        target: HGNC gene symbol.
        indication: If given, restrict to the CPTAC cohort mapped from this
            indication. Otherwise return the representative row across cohorts,
            chosen on the COMPARABLE standardized axis (largest |Cohen's d|,
            #1664 F1), not the non-comparable raw |protein_effect_size|.
    """
    # Do NOT wrap _load_indexed in a broad except -> _empty: a broken-env / corrupt-cache failure
    # would then be re-swallowed as data_unavailable, defeating the raise-on-broken-env discipline
    # in _load_indexed. Let it propagate to the live-read seam (honest _live_read_error). A genuine
    # absent product still yields an empty df below -> _empty (unchanged data_unavailable).
    df, cohort_gene_idx, gene_idx, cohort_effect_null = _load_indexed()
    if df is None or df.empty:
        return _empty("cptac_data_unavailable")

    sym = target.upper().strip()

    # Resolve indication → CPTAC cohort(s). An umbrella indication (NSCLC) expands to its LEAF cohorts
    # (LUAD + LSCC) — CPTAC has no pooled NSCLC row. A leaf indication resolves to a single cohort.
    from methods.indication_aliases import indication_leaf_codes

    cohorts: list[str] = []
    if indication:
        for leaf in indication_leaf_codes(indication):
            c = INDICATION_TO_CPTAC.get(leaf.upper().strip())
            if c and c not in cohorts:
                cohorts.append(c)

    # Primary path: indication-specific lookup. Among the resolved cohort(s) the target is present in,
    # report the largest-|effect_size| row. For a single cohort this is the exact prior behavior; for the
    # NSCLC umbrella the pick is restricted to NSCLC's OWN leaves (LUAD/LSCC ARE NSCLC → NOT a
    # cross-indication leak, unlike the indication-free pan-cancer fallback below).
    if cohorts:
        present = [(c, cohort_gene_idx[(c, sym)]) for c in cohorts if (c, sym) in cohort_gene_idx]
        if not present:
            return _empty(f"target_not_in_cptac_cohort_{'+'.join(cohorts)}")
        # Rank on the COMPARABLE standardized axis (largest |Cohen's d|, #1664 F1) with UNESTIMABLE /
        # unstandardizable rows last (_cohens_d_rank_key): the raw |effect| is a within-cohort TMT ratio the
        # producer flags as NOT cross-cohort comparable. |raw effect| remains only as a deterministic
        # tiebreak. Matters for a multi-cohort umbrella (NSCLC -> LUAD+LSCC); harmless for a single cohort.
        # Rank over `.to_dict()` rows (NOT the raw Series): an object-dtype row carries numpy scalars that
        # _is_num rejects, so Cohen's d would silently vanish and the pick would collapse to raw |effect| —
        # the same Python-native construction path _row_to_summary uses.
        present_rows = [(c, df.iloc[idx].to_dict()) for c, idx in present]
        best_c, row = max(present_rows, key=lambda cr: _cohens_d_rank_key(cr[1]))
        pct, pct_class = _allgene_effect_percentile(cohort_effect_null, best_c, row.get("protein_effect_size"))
        summ = _row_to_summary(row, matched_cohort=best_c, allgene_percentile=pct, allgene_percentile_class=pct_class)
        if len(cohorts) > 1:
            summ["_data_note"] = (
                f"{indication.upper().strip()} umbrella → {'+'.join(cohorts)}; "
                f"reporting {best_c} (largest |Cohen's d|, cross-cohort-comparable)"
            )
        return summ

    # A SUPPLIED but unmapped indication must NOT leak a different cohort's contrast. CPTAC is a
    # PER-COHORT tumor-vs-normal differential; returning the most-extreme OTHER cohort as if it were
    # the queried disease is a silent cross-indication data leak. Honest posture: data_unavailable (no
    # matching CPTAC cohort for this indication). The cross-cohort aggregate below is reserved for the
    # indication-FREE (target-only / pan-cancer) call.
    if indication:
        return _empty(f"indication_not_in_cptac_{indication.upper().strip()}")

    # Fallback (NO indication supplied — target-only / pan-cancer query): aggregate across all
    # cohorts, return the representative row on the COMPARABLE standardized axis (largest |Cohen's d|,
    # #1664 F1). Never reached when an indication is supplied (that path is resolved or data_unavailable
    # above).
    indices = gene_idx.get(sym, [])
    if not indices:
        return _empty("target_not_in_any_cptac_cohort")

    rows = df.iloc[indices].to_dict(orient="records")
    # Rank on |Cohen's d| (comparable) with |raw effect| as a deterministic tiebreak; unestimable /
    # unstandardizable rows rank LAST (this is also the path where +Inf did the most damage — 1,564
    # genes reported BRCA/unestimable instead of their real best cohort; see _finite_effect_or_nan).
    best_row = max(rows, key=_cohens_d_rank_key)
    best_cohort = str(best_row.get("cohort", "")).upper()
    pct, pct_class = _allgene_effect_percentile(cohort_effect_null, best_cohort, best_row.get("protein_effect_size"))
    return _row_to_summary(
        best_row, matched_cohort=best_cohort, allgene_percentile=pct, allgene_percentile_class=pct_class
    )


def _allgene_effect_percentile(cohort_effect_null: dict, cohort: str, effect_size):
    """Percentile of `effect_size` among ALL genes' protein_effect_size in this cohort.

    Context-matched by construction: the null is the cohort's own slice of the resident
    df (no pooling across cohorts). Zero new I/O — `cohort_effect_null` is built ONCE inside
    `_load_indexed`'s lru_cache (#715 O: previously this recomputed `df["cohort"].str.upper()`
    over the full ~101K-row column on every call — a warm path fired once per gene query)."""
    from methods.percentile_null import classify_percentile, percentile_rank

    null_vals = cohort_effect_null.get(cohort, [])
    # NOT affected by the unestimable-contrast defect, and deliberately left alone: percentile_null
    # already drops non-finite values from the null (percentile_null._finite) and already returns None for
    # a non-finite VALUE, so the +Inf mass never entered a percentile and never deflated a real gene.
    # Pinned by test_unestimable_contrast.py so a percentile_null refactor cannot silently regress it.
    pct = percentile_rank(effect_size, null_vals)
    return pct, classify_percentile(pct)


def read_all_cohorts(target: str) -> list[dict]:
    """Every CPTAC cohort row for a target — the per-cohort tumor-vs-normal panel data.

    The derived product is per-cohort SUMMARY statistics (no per-sample abundances), so this is the
    honest cross-cohort view: one record per cohort the target was tested in, sorted by effect size
    descending. Reused by (a) the per-cohort figure emitter, (b) the pan-cancer tumor_elevation_breadth
    measurement_type (Part 2). Empty list when the target is absent / product unavailable."""
    # Propagate broken-env/corrupt-cache from _load_indexed (honest _live_read_error) rather than
    # re-swallowing to []. Genuine absent product -> empty df -> [] (unchanged data_unavailable).
    df, _cohort_gene_idx, gene_idx, _cohort_effect_null = _load_indexed()
    if df is None or df.empty:
        return []
    indices = gene_idx.get(target.upper().strip(), [])
    if not indices:
        return []
    rows = [
        _row_to_summary(df.iloc[i].to_dict(), matched_cohort=str(df.iloc[i]["cohort"]).strip().upper()) for i in indices
    ]
    rows.sort(key=_finite_effect_or_nan, reverse=True)
    return rows


# --- per-sample distribution (per-sample product; backs the true boxplot) --------------------
# The per-cohort product above keeps only medians/effect/q; it CANNOT back a distribution plot.
# cptac-protein-tumor-vs-normal-per-sample-v1 persists the per-aliquot log-ratios so we can draw a
# real tumor-vs-normal boxplot AND recompute honest per-cohort statistics from the samples
# themselves (Welch's t on the log-ratios + a nonparametric Mann-Whitney U), rather than trusting a
# median dumbbell.

_PER_SAMPLE_COLS = ["gene_symbol", "cohort", "aliquot_submitter_id", "sample_type", "condition", "log2_ratio"]


def read_per_sample(target: str):
    """Per-aliquot CPTAC protein log-ratios for one target, all cohorts.

    STREAMED predicate-pushdown read over the (gene_symbol, cohort)-sorted per-sample parquet on S3
    (pyarrow S3FileSystem, filters=[("gene_symbol","=",target)]) — pyarrow prunes to the target's few
    row-groups (row_group_size 16384) and transfers only those column chunks, WITHOUT downloading the
    127 MB / ~15M-row product. Bucket/key resolved from the derived manifest (single source of truth).
    Returns a DataFrame with columns (gene_symbol, cohort, aliquot_submitter_id, sample_type,
    condition, log2_ratio); empty DataFrame when the target is absent / product unavailable."""
    sym = target.upper().strip()
    try:
        import pyarrow.parquet as pq

        bucket, key = bucket_key_for(PER_SAMPLE_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=[("gene_symbol", "=", sym)])
        return tbl.to_pandas()
    except Exception as e:  # noqa: BLE001
        # Absence discipline: swallow ONLY a genuine no-object (S3 NoSuchKey/404 or pyarrow
        # FileNotFoundError) as an honest data_unavailable (empty frame); RE-RAISE transient / creds
        # (AccessDenied) / broken-env (missing pyarrow) so the live-read seam surfaces a real
        # _live_read_error instead of a silent dead axis.
        from methods.target_id_sidecar import is_definitively_absent

        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        import pandas as pd

        return pd.DataFrame(columns=_PER_SAMPLE_COLS)


@lru_cache(maxsize=64)
def per_cohort_distribution_stats(target: str) -> list[dict]:
    """Per-cohort tumor-vs-normal distribution + honest statistics recomputed from the SAMPLES.

    Memoized (retrieval-opt #5): the three figure emitters (emit_per_cohort_panel / emit_plot_data /
    emit_plotly_specs) each call this independently, so a single card render recomputed the stats
    3x — including re-reading the per-sample product + re-running Welch/MWU. Cached on `target`;
    emitters treat the returned list read-only (they iterate to draw). cache_clear() in tests.

    For each cohort the target was quantified in, split the per-aliquot log-ratios into Tumor vs
    Normal and compute, FROM THE SAMPLES (not the summary product's precomputed q):
        - n_tumor / n_normal, tumor/normal median + quartiles (the boxplot geometry)
        - welch_p     Welch's t-test (unequal-variance), tumor vs normal log-ratios
        - mwu_p       Mann-Whitney U (nonparametric; robust to the log-ratio tails)
        - delta_median = tumor_median - normal_median
    Cohorts with <3 samples on either side are kept but their p-values are None (n too low to test)
    so the boxplot still shows the distribution honestly. Sorted by delta_median descending
    (most tumor-elevated first). Empty list when absent / unavailable.

    NOTE these p-values are per-cohort two-group tests on the SAMPLES — they will differ from the
    per-cohort product's MSstatsTMT limma-moderated q (different estimator); that is expected and
    the plot labels which test it used. This function is the plot's source of truth, self-consistent
    with the boxes it draws."""
    import numpy as np

    df = read_per_sample(target)
    if df is None or df.empty:
        return []

    def _quartiles(vals):
        a = np.asarray(vals, dtype=float)
        a = a[~np.isnan(a)]
        if a.size == 0:
            return (None, None, None, None, None)
        return (
            float(np.min(a)),
            float(np.percentile(a, 25)),
            float(np.median(a)),
            float(np.percentile(a, 75)),
            float(np.max(a)),
        )

    out = []
    for cohort, sub in df.groupby("cohort"):
        tvals = sub.loc[sub["condition"] == "Tumor", "log2_ratio"].to_numpy(dtype=float)
        nvals = sub.loc[sub["condition"] == "Normal", "log2_ratio"].to_numpy(dtype=float)
        tvals = tvals[~np.isnan(tvals)]
        nvals = nvals[~np.isnan(nvals)]
        n_t, n_n = int(tvals.size), int(nvals.size)
        t_lo, t_q1, t_med, t_q3, t_hi = _quartiles(tvals)
        n_lo, n_q1, n_med, n_q3, n_hi = _quartiles(nvals)

        welch_p = mwu_p = None
        if n_t >= 3 and n_n >= 3:
            try:
                from scipy import stats as _st

                welch_p = float(_st.ttest_ind(tvals, nvals, equal_var=False).pvalue)
                mwu_p = float(_st.mannwhitneyu(tvals, nvals, alternative="two-sided").pvalue)
            except Exception:
                welch_p = mwu_p = None

        delta = (t_med - n_med) if (t_med is not None and n_med is not None) else None
        out.append(
            {
                "cohort": str(cohort).upper(),
                "n_tumor": n_t,
                "n_normal": n_n,
                "tumor_min": t_lo,
                "tumor_q1": t_q1,
                "tumor_median": t_med,
                "tumor_q3": t_q3,
                "tumor_max": t_hi,
                "normal_min": n_lo,
                "normal_q1": n_q1,
                "normal_median": n_med,
                "normal_q3": n_q3,
                "normal_max": n_hi,
                "delta_median": delta,
                "welch_p": welch_p,
                "mwu_p": mwu_p,
                # raw arrays for the boxplot (kept out of any parquet emit; used only in-memory)
                "_tumor_values": tvals.tolist(),
                "_normal_values": nvals.tolist(),
            }
        )

    out.sort(key=lambda r: r["delta_median"] if r["delta_median"] is not None else -1e9, reverse=True)
    return out


# --- tumor_elevation_breadth (Slice B1, 2026-07-21) ------------------------------------------
# A TARGET-GRAIN roll-up: "elevated in K of the N CPTAC cohorts this target was quantified in."
# CONTRACT NOTE: this is breadth over INDICATIONS for ONE target (allowed — precedent
# normal_tissue_protein_breadth), NOT a ranking over TARGETS (forbidden — the
# surfaceome-cohort-ranking non-goal, DATA_TO_SKILL_CONTRACT.md:467). It gives a target-ONLY
# query (no indication) a real pan-cancer tumor signal instead of falling back to cell-line-only.
#
# "Elevated" reuses the already-significance-gated per-cohort protein_expression_class: strong_up
# (q<0.05, effect>=1.5) or modest_up (q<0.05, 0.5<=effect<1.5). No new statistics — a count over
# the existing classes. Down/ns/data_unavailable cohorts are NOT elevated.
#
# NOTE (M4 — cross-modality bar asymmetry): this PROTEIN elevated bar (q<0.05 AND effect>=0.5) is
# INTENTIONALLY DIFFERENT from the RNA elevated bar in dge_deseq2/derive_pancan_stack.py
# (|log2fc|>=1.0, >=2 concordant cells, no magnitude q-gate). The two layers are fused into
# breadth_layer_concordance skill-side; a "discordant" label can reflect this THRESHOLD asymmetry
# (RNA carries a stricter magnitude floor; protein is significance-gated) rather than a biological
# RNA-vs-protein disagreement. The asymmetry is by assay (TMT-MS vs bulk RNA-seq dynamic range), not
# oversight. See the mirror note in derive_pancan_stack.py.

_ELEVATED_CLASSES = frozenset({"strong_up", "modest_up"})

# Standardized-effect classes (Cohen's d bands from _standardized_effect) that count as a REAL effect for
# the breadth roll-up. `negligible` is the power-artifact class (cleared significance via large n at a
# tiny per-sample effect); `data_unavailable` means the effect could not be standardized (SE/p/n missing)
# and must NOT be penalized — it falls back to the significance-gated call.
_REAL_STANDARDIZED_EFFECTS = frozenset({"small", "medium", "large"})


def _cohort_elevated(row: dict) -> bool:
    """Is a per-cohort row 'elevated' for the pan-cancer breadth roll-up?

    G6 (tumor-presence expert review): significance-gated-up (protein_expression_class in
    _ELEVATED_CLASSES) is necessary but NOT sufficient — the raw K-of-N count otherwise conflates cohort
    POWER / adjacent-normal availability with pan-cancer biology, letting a low-effect protein clear
    q<0.05 in the best-powered cohorts on significance alone. A cohort is elevated only if it is ALSO not
    AFFIRMATIVELY effect-negligible by the variance-standardized Cohen's d (the sample-size-independent
    companion). A `data_unavailable` standardized class (SE/p/n missing — cannot standardize) falls back
    to the significance-gated call, so a genuine up-cohort is never dropped for missing metadata.

    This is the read-time realization of the review's "promote Cohen's d to the verdict path" (G6 + the
    actionable slice of G7). Re-baking the per-cohort protein_expression_class itself on a variance-aware
    classify() is a build-time change (steps/03_pool_and_write.py) requiring a product rebuild — tracked
    separately; here the roll-up consumes the already-read-time-computed standardized class."""
    if row.get("protein_expression_class") not in _ELEVATED_CLASSES:
        return False
    return row.get("protein_effect_standardized_class") != "negligible"


# --- pan-cohort FDR under the K-of-N breadth panel (#1664 F2) ---------------------------------
# Default family-wise alpha for the pan-cohort BH. Mirrors the per-cohort BH threshold baked into
# protein_expression_class (q<0.05), so the breadth panel is corrected at the same level the
# per-cohort significance call used — only the FAMILY differs (the K cohorts this ONE target is
# counted across, vs the ~10k proteins within one cohort).
_PAN_COHORT_FDR_ALPHA = 0.05


def _bh_reject(pvals: list, alpha: float) -> list:
    """Benjamini-Hochberg step-up on a list of p-values. Returns a boolean list aligned with `pvals`:
    True = the null is rejected at FDR `alpha` (the cohort PASSES the pan-cohort significance gate).

    Standard BH: sort ascending, find the largest rank k with p_(k) <= (k/m)*alpha, reject all p_(i)
    with rank <= k. Ties on p are handled by stable rank assignment (a tie cannot make a smaller p
    fail while a larger one passes because rejection is by rank threshold, not per-p). Empty input ->
    empty output."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    kmax = 0
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= (rank / m) * alpha:
            kmax = rank
    reject = [False] * m
    for rank, i in enumerate(order, start=1):
        if rank <= kmax:
            reject[i] = True
    return reject


def _pan_cohort_fdr_pass(estimable_rows: list, alpha: float = _PAN_COHORT_FDR_ALPHA) -> dict:
    """Read-time pan-cohort BH/FDR over the K cohorts a target was tested in (#1664 F2).

    Per-cohort `protein_bh_q_value` corrects across the ~10k proteins WITHIN one cohort; it does NOT
    control the family-wise error over the BREADTH PANEL — the K cohorts this ONE target is counted
    across in the K-of-N `tumor_elevation_breadth_class` roll-up. Without it a target significant-up in
    a few cohorts by chance inflates the breadth class with no multiplicity control over the panel.

    Applies BH to the K raw `protein_p_value`s (materialized per gene x cohort, so this is read-side —
    NO republish). Returns {cohort_upper: passes_pan_cohort_fdr} ONLY for cohorts that carry a finite
    raw p. A cohort with a missing / non-finite raw p is ABSENT from the map (not False): the caller
    then falls back to the significance-gated call for it, so missing metadata never fabricates an
    elevated call NOR silently strips one — exactly mirroring the `data_unavailable`-standardized
    fallback in `_cohort_elevated`."""
    pairs = [
        (str(row.get("cohort", "")).strip().upper(), float(row["protein_p_value"]))
        for row in estimable_rows
        if _is_finite_num(row.get("protein_p_value"))
    ]
    if not pairs:
        return {}
    rejects = _bh_reject([p for _c, p in pairs], alpha)
    return {c: bool(rej) for (c, _p), rej in zip(pairs, rejects)}


def read_tumor_elevation_breadth(target: str) -> dict:
    """Pan-cancer tumor-elevation breadth for a target across all CPTAC cohorts.

    Built on read_all_cohorts (the per-cohort summary list). Returns a target-grain
    breadth summary:
        {
          tumor_elevation_breadth_class,   # categorical (drives rules)
          n_cohorts_tested,                # cohorts the target was quantified in
          n_cohorts_elevated,              # of those, significance-gated-up (strong_up/modest_up) AND
                                           # not effect-negligible by Cohen's d (see _cohort_elevated, G6)
          n_cohorts_sig_up_effect_negligible,  # sig-up cohorts STRIPPED as power artifacts (Cohen's d negligible)
          n_cohorts_sig_up_pan_cohort_fdr_fail,  # sig-up+non-negligible cohorts STRIPPED by the pan-cohort FDR (#1664 F2)
          fraction_elevated,               # n_elevated / n_tested (None if n_tested == 0)
          median_effect_across_elevated,   # median RAW protein_effect_size over elevated cohorts (within-cohort,
                                           #   NOT cross-cohort comparable — retained for provenance; see #1664 F1)
          median_standardized_effect_across_elevated,  # median Cohen's d over elevated cohorts — the CROSS-COHORT
                                           #   COMPARABLE aggregate (#1664 F1); None when no elevated cohort has a d
          most_elevated_cohorts,           # [{cohort, protein_expression_class, protein_effect_size,
                                           #   protein_bh_q_value}] effect-desc, elevated only
          cohorts_tested,                  # sorted cohort codes with an ESTIMATED contrast (the denominator)
          cohorts_unestimable,             # sorted cohort codes present but with an UNESTIMABLE contrast
        }
    breadth_class ladder (default thresholds; interpretation lives in the card/rules but the
    class is computed here mirroring read_target_summary's protein_expression_class pattern):
        broadly_tumor_elevated  -> fraction_elevated >= 0.5 AND n_cohorts_elevated >= 3
        multi_tumor_elevated    -> n_cohorts_elevated >= 2
        single_tumor_elevated   -> n_cohorts_elevated == 1
        not_tumor_elevated      -> n_cohorts_tested >= 1 AND n_cohorts_elevated == 0
        data_unavailable        -> n_cohorts_tested == 0 (target absent, product unavailable, OR every
                                   cohort row present is an UNESTIMABLE contrast — `not_tumor_elevated`
                                   would be a positive claim of non-elevation drawn from no test)

    A cohort enters `n_cohorts_elevated` only if it is (a) significance-gated-up and not
    effect-negligible by Cohen's d (`_cohort_elevated`, G6) AND (b) passes the read-time pan-cohort
    BH/FDR over the K cohorts this target was tested in (`_pan_cohort_fdr_pass`, #1664 F2). (b)
    controls the family-wise error over the breadth PANEL that the per-cohort BH (multiplicity across
    proteins WITHIN a cohort) does not, so a target significant-up in a few cohorts by chance no longer
    inflates the breadth class.
    """
    rows = read_all_cohorts(target)
    # DENOMINATOR = cohorts where the contrast was actually ESTIMATED. A cohort row whose contrast is
    # unestimable (protein_contrast_estimable is False) can never enter the elevated numerator, so
    # counting it as "tested" deflates fraction_elevated and can demote broadly_ -> multi_tumor_elevated
    # on a coverage artifact. It stays in `rows` (and in cohorts_unestimable below) so the loss is
    # LEGIBLE rather than dropped.
    estimable = [row for row in rows if row.get("protein_contrast_estimable") is not False]
    unestimable = [row for row in rows if row.get("protein_contrast_estimable") is False]
    n_tested = len(estimable)
    if n_tested == 0:
        return {
            "tumor_elevation_breadth_class": "data_unavailable",
            "n_cohorts_tested": 0,
            "n_cohorts_elevated": 0,
            "fraction_elevated": None,
            "median_effect_across_elevated": None,
            "median_standardized_effect_across_elevated": None,
            "most_elevated_cohorts": [],
            "cohorts_tested": [],
            "cohorts_unestimable": sorted(str(row.get("cohort")) for row in unestimable),
        }

    # #1664 F2: read-time pan-cohort BH/FDR over the K cohorts this target was tested in (the breadth
    # PANEL). A cohort counts as elevated only if it clears the significance+effect bar (_cohort_elevated,
    # G6) AND passes the pan-cohort FDR. A cohort with no finite raw p is ABSENT from the pass-map and
    # falls back to the significance-gated call (never stripped for missing metadata) — mirroring the
    # data_unavailable-standardized fallback in _cohort_elevated.
    fdr_pass = _pan_cohort_fdr_pass(estimable)

    def _pan_cohort_ok(row) -> bool:
        return fdr_pass.get(str(row.get("cohort", "")).strip().upper(), True)

    elevated = [row for row in estimable if _cohort_elevated(row) and _pan_cohort_ok(row)]
    n_elevated = len(elevated)
    fraction = n_elevated / n_tested
    # Legibility (G6, no silent cap): cohorts that WERE significance-gated-up but were stripped from the
    # elevated set because their standardized effect is negligible (a power artifact, not biology).
    n_sig_up_effect_negligible = sum(
        1
        for row in rows
        if row.get("protein_expression_class") in _ELEVATED_CLASSES
        and row.get("protein_effect_standardized_class") == "negligible"
    )
    # Legibility (#1664 F2, no silent cap): cohorts that cleared the significance+effect bar but were
    # stripped from the elevated set ONLY by the pan-cohort FDR (a chance up-call over the breadth panel).
    n_sig_up_pan_cohort_fdr_fail = sum(1 for row in estimable if _cohort_elevated(row) and not _pan_cohort_ok(row))

    # median effect over the ELEVATED cohorts only (None when none elevated). TWO aggregates:
    #  - median_effect: RAW within-cohort TMT log2 ratio — NOT cross-cohort comparable, kept for provenance.
    #  - median_standardized_effect: median Cohen's d — the CROSS-COHORT COMPARABLE aggregate (#1664 F1).
    median_effect = None
    if elevated:
        effs = sorted(float(row.get("protein_effect_size") or 0.0) for row in elevated)
        m = len(effs)
        median_effect = effs[m // 2] if m % 2 else (effs[m // 2 - 1] + effs[m // 2]) / 2.0
    median_standardized_effect = None
    dvals = sorted(
        float(row["protein_effect_cohens_d"]) for row in elevated if _is_finite_num(row.get("protein_effect_cohens_d"))
    )
    if dvals:
        md = len(dvals)
        median_standardized_effect = dvals[md // 2] if md % 2 else (dvals[md // 2 - 1] + dvals[md // 2]) / 2.0

    if fraction >= 0.5 and n_elevated >= 3:
        cls = "broadly_tumor_elevated"
    elif n_elevated >= 2:
        cls = "multi_tumor_elevated"
    elif n_elevated == 1:
        cls = "single_tumor_elevated"
    else:
        cls = "not_tumor_elevated"

    # read_all_cohorts already sorts by |effect| desc; elevated preserves that order.
    most_elevated = [
        {
            "cohort": row.get("cohort"),
            "protein_expression_class": row.get("protein_expression_class"),
            "protein_effect_size": row.get("protein_effect_size"),
            "protein_bh_q_value": row.get("protein_bh_q_value"),
            # standardized effect + adjacent-normal n carried per cohort (G6 transparency): a reader can see
            # the sample-size-independent effect band and the paired-normal power behind each elevated call.
            "protein_effect_standardized_class": row.get("protein_effect_standardized_class"),
            "n_normal_samples": row.get("n_normal_samples"),
        }
        for row in elevated
    ]

    return {
        "tumor_elevation_breadth_class": cls,
        "n_cohorts_tested": n_tested,
        "n_cohorts_elevated": n_elevated,
        "n_cohorts_sig_up_effect_negligible": n_sig_up_effect_negligible,  # stripped power artifacts (G6)
        "n_cohorts_sig_up_pan_cohort_fdr_fail": n_sig_up_pan_cohort_fdr_fail,  # stripped by pan-cohort FDR (#1664 F2)
        "fraction_elevated": fraction,
        "median_effect_across_elevated": median_effect,
        "median_standardized_effect_across_elevated": median_standardized_effect,
        "most_elevated_cohorts": most_elevated,
        "cohorts_tested": sorted(str(row.get("cohort")) for row in estimable),
        "cohorts_unestimable": sorted(str(row.get("cohort")) for row in unestimable),
    }


# --- surface-abundance-density (Tier 1.2, 2026-07-23) ----------------------------------------
# The surface-abundance-density card asks: "estimated surface copies-per-cell of {target} in
# {indication} tumors, above the TCE-viability threshold (>1,000/cell, Slaga 2018 Sci Transl Med)?"
#
# ⚠ EVIDENCE GRADE D — INFERRED, order-of-magnitude PRIOR. NOT a calibrated absolute anchor.
# (Domain-expert review 2026-07-23; see .claude/plans/surface-density-multi-anchor.md.) This function
# is the INTERIM v0.1: it unblocks the surface-modality-fit gate (its dispatcher errored with no method
# behind it) with an HONEST Level-D inference, pending the tiered-evidence rebuild (HPA graded IHC →
# CCLE/949 whole-cell priors → CSPA enrichment → a governed calibrated-flow ladder that alone sets the
# absolute scale). It DELIBERATELY does NOT claim the three things a real density model must earn:
#   (1) it is NOT a universal calibration — IHC intensity ≠ copies/cell (antibody affinity, epitope
#       accessibility, prep, dynamic range, scoring all confound); the copies numbers below are an
#       ORDER-OF-MAGNITUDE prior, reported with wide bands, never a cross-antibody quantitative claim;
#   (2) the CPTAC log2FC is applied as a coarse relative shift on a Level-D prior — NOT a calibrated
#       mapping of whole-proteome tumor abundance onto an absolute surface-copy scale;
#   (3) is_tce_viable / is_adc_high_payload_viable are WORKING-PRIOR calls against literature threshold
#       priors (Slaga 1,000 / 10,000), NOT biological GATES — real thresholds depend on affinity,
#       epitope, internalization, payload potency, DAR, linker, bystander, TCE geometry, CD3 affinity,
#       E:T ratio, heterogeneity (→ future modality_density_requirements format parameters).
# Every emitted estimate carries density_evidence_level='D'; a target with no anchor is level 'E'
# (expression evidence only, NO density estimate → surface_density_class 'unmeasured', never fabricated).
#
# WHY ONLY INFERRED. Neither substrate measures absolute surface copies/cell:
#   - CPTAC mass-spec (read_target_summary) = RELATIVE whole-proteome tumor-vs-normal log2 (a SHIFT).
#   - HPA IHC (hpa_normal_tissue_liability) = pathologist-scored intensity/breadth in NORMAL tissue.
# Both are Tier-4 PRIORS in the evidence model, not absolute anchors. The Level-D inference is:
#       copies_tumor  ~=  order_of_magnitude_prior(HPA IHC class)  x  2 ** (CPTAC log2FC)
# RANGED (lower/median/upper); when the prior weakens (no tissue-of-origin IHC, CPTAC-only) the BAND
# WIDENS so the card's `wide_uncertainty_band` warning fires — the estimate fails toward "confirm with
# calibrated flow", never toward a confident call.
#
# HPA does NOT ship per-tissue High/Med/Low IHC levels in the ingested master (that's the Phase-1A
# ingest); it ships (a) `Protein tissue distribution` (all/many/some/single) — breadth, and (b) a
# tissue-enriched NUMERIC intensity list over a closed 16-name vocabulary (~51% coverage). We map:
#   - the tumor tissue-of-origin's ENRICHED numeric intensity (when present) → an ordinal IHC class
#     via fixed percentiles (verified live 2026-07-23: p33 ~= 8e5, p66 ~= 7.4e6 → low/med/high);
#   - else the breadth class (all/many → medium; some/single → low; not detected → not_detected) — a
#     weaker prior → wider band.
# Each ordinal class maps to an ORDER-OF-MAGNITUDE copies/cell prior center + a multiplicative
# uncertainty factor (loosely from HER2/EGFR-family flow ranges; NOT a per-antibody calibration):
#   high ~= 3e5 (/12..x12), medium ~= 3e4 (/12..x12), low ~= 3e3 (/16..x16), not_detected ~= 3e2.
# The governed calibrated-flow ladder (Phase 2) will REPLACE these priors as the real absolute anchor.

# Indication (OncoTree-ish code) → HPA normal tissue-of-origin name (closed 16-name enriched vocab
# where possible; None when the tissue-of-origin is not in HPA's enriched list → breadth-only anchor).
_INDICATION_TO_HPA_TISSUE = {
    "COAD": "intestine",
    "COADREAD": "intestine",
    "READ": "intestine",
    "STAD": "stomach",
    "ESCA": "stomach",
    "PAAD": "pancreas",
    "PDAC": "pancreas",
    "LIHC": "liver",
    "CHOL": "liver",
    "LUAD": "lung",
    "LUSC": "lung",
    "LSCC": "lung",
    "NSCLC": "lung",
    "MESO": "lung",
    "KIRC": "kidney",
    "CCRCC": "kidney",
    "KIRP": "kidney",
    "KICH": "kidney",
    "OV": "ovary",
    "GBM": "cerebral cortex",
    "LGG": "cerebral cortex",
    "DLBCL": "lymphoid tissue",
    "AML": "bone marrow",
    "SKCM": "skin",
    # tissue-of-origin NOT in HPA's enriched vocabulary → breadth-only anchor (wider band):
    "BRCA": None,
    "UCEC": None,
    "HNSC": None,
    "HNSCC": None,
    "PRAD": None,
    "BLCA": None,
}

# IHC intensity class → (copies_per_cell CENTER, multiplicative uncertainty factor).
# CENTERs calibrated to HER2/EGFR-family surface-antigen flow-cytometry ranges (Nathanson 2018;
# Slaga 2018 Sci Transl Med >1,000/cell TCE threshold). The factor sets lower=center/f, upper=center*f.
_IHC_CLASS_CALIBRATION = {
    "high": (3.0e5, 12.0),
    "medium": (3.0e4, 12.0),
    "low": (3.0e3, 16.0),  # straddles the 1,000/cell TCE threshold (wide by design)
    "not_detected": (3.0e2, 10.0),
}

# HPA enriched-intensity tertile cutoffs (verified live 2026-07-23: p33 8.05e5, p66 7.43e6 over
# n=14,311 enriched (tissue,intensity) pairs). A tissue-of-origin numeric intensity below p33 → low,
# below p66 → medium, else → high. Baked in (NOT recomputed at read time) so the class is stable.
_HPA_ENRICHED_P33 = 8.05e5
_HPA_ENRICHED_P66 = 7.43e6

# HPA breadth class → IHC anchor class (the weaker fallback when tissue-of-origin has no enriched
# numeric intensity). Broad/moderate/restricted NORMAL presence is a defensible order-of-magnitude
# proxy for baseline tissue-of-origin abundance (present at medium/low). But NORMAL-tissue ABSENCE
# (`not_detected_in_normal`) is DELIBERATELY OMITTED here: normal-tissue absence says NOTHING about
# TUMOR abundance — it is precisely the signature of an ideal tumor-restricted antigen (DLL3, MAGE-A,
# tumor-specific neoantigens). Mapping it to `not_detected` previously mis-anchored those antigens as
# tumor-absent (~3e2 copies/cell) AND — via hpa_ihc_intensity_class=not_detected → the surface
# `ihc-not-detected-killer` rung — false-killed the composed modality verdict to `neither_viable`
# (S1-2, cards review 2026-08-17; live-verified on DLL3/LUAD, an approved tarlatamab/Rova-T antigen).
# So normal-absence now ABSTAINS: `.get(breadth, "unmeasured")` returns `unmeasured` → no killer, and
# `_hpa_cptac_estimate` degrades to an honest grade-E `_empty_density` (a real tumor density comes from
# the CPTAC tumor measurement / the Tier-1 absolute-density ladder, not from a normal-tissue-absence
# inference). NOTE: with this omission the tissue_specific path only ever yields low/medium/high, so
# `hpa_ihc_intensity_class` is never `not_detected` — the `ihc-not-detected-killer` rung is now
# unreachable from HPA breadth (its only prior trigger was this false-kill). A GENUINE "antigen absent
# in the tumor too" kill belongs on the CPTAC-measured `protein_expression_class=not_detected` signal
# (absence in BOTH tumor + normal arms), tracked separately (G8-S2-3).
_BREADTH_TO_IHC_CLASS = {
    "broad_normal_expression": "medium",
    "moderate_normal_expression": "low",
    "restricted_normal_expression": "low",
    # "not_detected_in_normal": intentionally absent → abstains to "unmeasured" (see comment above).
}

_TCE_VIABILITY_COPIES = 1000.0  # Slaga 2018 Sci Transl Med
_ADC_HIGH_PAYLOAD_COPIES = 10000.0

_DENSITY_METHOD_VERSION = "0.1.0"


def _density_class(copies: Optional[float]) -> str:
    """copies-per-cell → surface_density_class (card vocabulary), MEDIAN-driven.

    high     > 10,000/cell   moderate 1,000-10,000   low 100-1,000   very_low < 100
    """
    if copies is None:
        return "unmeasured"
    if copies > _ADC_HIGH_PAYLOAD_COPIES:
        return "high"
    if copies >= _TCE_VIABILITY_COPIES:
        return "moderate"
    if copies >= 100.0:
        return "low"
    return "very_low"


def _hpa_ihc_anchor(target: str, indication: Optional[str]) -> dict:
    """Resolve the HPA IHC calibration anchor for a target in the tumor tissue-of-origin.

    Returns {hpa_ihc_intensity_class, hpa_ihc_anchor_used, anchor_strength} where anchor_strength
    is 'tissue_specific' (strong — numeric enriched intensity in the tissue-of-origin),
    'breadth_only' (weak — no tissue-of-origin enriched value, fell back to distribution breadth),
    or 'unmeasured' (HPA has no call at all). Never raises — HPA read failure degrades to unmeasured.
    """
    try:
        from methods.hpa_normal_tissue_liability import cli as _hpa

        summary = _hpa.load_and_classify(target)
    except Exception:
        return {"hpa_ihc_intensity_class": "unmeasured", "hpa_ihc_anchor_used": None, "anchor_strength": "unmeasured"}

    breadth = summary.get("normal_tissue_breadth_class")
    if breadth in (None, "data_unavailable"):
        return {"hpa_ihc_intensity_class": "unmeasured", "hpa_ihc_anchor_used": None, "anchor_strength": "unmeasured"}

    # Strong anchor: the tumor tissue-of-origin appears in HPA's enriched (numeric-intensity) list.
    tissue = _INDICATION_TO_HPA_TISSUE.get((indication or "").upper().strip())
    if tissue:
        for t in summary.get("specific_tissues") or []:
            if t.get("tissue") == tissue and t.get("intensity") is not None:
                v = float(t["intensity"])
                cls = "low" if v < _HPA_ENRICHED_P33 else "medium" if v < _HPA_ENRICHED_P66 else "high"
                return {
                    "hpa_ihc_intensity_class": cls,
                    "hpa_ihc_anchor_used": f"HPA enriched intensity in {tissue}",
                    "anchor_strength": "tissue_specific",
                }

    # Weak anchor: no tissue-of-origin enriched value → fall back to the distribution breadth class.
    cls = _BREADTH_TO_IHC_CLASS.get(breadth, "unmeasured")
    if cls == "unmeasured":
        return {"hpa_ihc_intensity_class": "unmeasured", "hpa_ihc_anchor_used": None, "anchor_strength": "unmeasured"}
    label = tissue or "distribution breadth (no tissue-of-origin map)"
    return {
        "hpa_ihc_intensity_class": cls,
        "hpa_ihc_anchor_used": f"HPA {breadth} ({label})",
        "anchor_strength": "breadth_only",
    }


def _empty_density(note: str) -> dict:
    """Honest unmeasured density card (no CPTAC coverage OR no HPA anchor).

    density_evidence_level='E' — expression evidence only, NO density estimate emitted (the honest
    floor of the evidence model; never a fabricated copies/cell number)."""
    return {
        "surface_density_class": "unmeasured",
        "density_evidence_level": "E",  # expression only; no density estimate
        "estimated_copies_per_cell_median": None,
        "estimated_copies_per_cell_lower": None,
        "estimated_copies_per_cell_upper": None,
        "hpa_ihc_anchor_used": None,
        "hpa_ihc_intensity_class": "unmeasured",
        "is_tce_viable": False,
        "is_adc_high_payload_viable": False,
        "method_version": _DENSITY_METHOD_VERSION,
        "_data_note": note,
    }


def _ladder_measurement(target: str, indication: Optional[str]) -> Optional[dict]:
    """If the governed absolute-density corpus has a MEASURED anchor for target, build the card summary
    from it (measured PRIMARY + the grade-D estimate retained as fallback context). Else None.

    Never raises — a missing ladder module / empty corpus / grade-E read all return None so the caller
    falls through to the HPA×CPTAC estimate. No fabrication: only a real admissible measurement wins."""
    try:
        from methods.surface_antigen_density_ladder import read_absolute_density
    except Exception:
        return None
    try:
        m = read_absolute_density(target, indication)
    except Exception:
        return None
    if not m or m.get("density_evidence_level") in (None, "E") or m.get("value_best") is None:
        return None

    density_class = m["absolute_density_class"]  # {high|moderate|low|very_low}
    grade = m["density_evidence_level"]  # A | A- | B | B-
    # The grade-D HPA×CPTAC estimate is still computed + reported alongside (context, not the verdict).
    est = _hpa_cptac_estimate(target, indication)
    return {
        "surface_density_class": density_class,  # PRIMARY — now from a MEASURED anchor
        "density_evidence_level": grade,
        # measured absolute anchor (the promotion): value + unit + semantics + provenance
        "absolute_value_best": m["value_best"],
        "absolute_reported_unit": m["reported_unit"],
        "absolute_value_qualifier": m.get("value_qualifier_best"),
        "absolute_measurement_semantics": m.get("measurement_semantics_best"),
        "absolute_record_partition": m.get("record_partition_best"),
        "absolute_n_measurements": m.get("n_admissible_measurements"),
        "absolute_n_patient": m.get("n_patient"),
        "absolute_n_cell_line": m.get("n_cell_line"),
        # card viability flags — now backed by a measured value, not a working-prior
        "is_tce_viable": density_class in ("high", "moderate"),
        "is_adc_high_payload_viable": density_class == "high",
        # grade-D estimate retained as FALLBACK context (so both are visible; grade says which to trust)
        "estimated_copies_per_cell_median": est.get("estimated_copies_per_cell_median"),
        "estimated_copies_per_cell_lower": est.get("estimated_copies_per_cell_lower"),
        "estimated_copies_per_cell_upper": est.get("estimated_copies_per_cell_upper"),
        "hpa_ihc_anchor_used": est.get("hpa_ihc_anchor_used"),
        "hpa_ihc_intensity_class": est.get("hpa_ihc_intensity_class"),
        "method_version": _DENSITY_METHOD_VERSION,
        "_density_source": "governed_ladder",
        "_estimate_grade_d_class": est.get("surface_density_class"),
    }


def read_abundance_density_summary(target: str, indication: str = None) -> dict:
    """surface-abundance-density card: estimated surface copies-per-cell + TCE/ADC viability.

    Anchors an absolute copies-per-cell scale on the HPA IHC intensity for the tumor tissue-of-
    origin, then shifts it by the CPTAC tumor-vs-normal protein log2FC:
        median = anchor_center x 2 ** log2FC
    and widens the band when the anchor is weak (breadth-only) or CPTAC is absent (anchor-only),
    so the card's `wide_uncertainty_band` warning fires honestly rather than emitting false
    precision. `unmeasured` (never a fabricated number) when EITHER substrate is missing:
    no HPA anchor OR no CPTAC coverage in the tissue-matched cohort.

    Returns the surface-abundance-density card summary_fields contract:
        surface_density_class in {high, moderate, low, very_low, unmeasured}   (PRIMARY)
        estimated_copies_per_cell_{median, lower, upper}
        hpa_ihc_anchor_used, hpa_ihc_intensity_class
        is_tce_viable (class in {high, moderate}),  is_adc_high_payload_viable (class == high)
        method_version

    LADDER OVERRIDE (2026-07-23): if the governed absolute-density corpus
    (surface_antigen_density_ladder) has a MEASURED value for this target (evidence grade A patient /
    B cell-line, directly-calibrated flow / single-molecule counting), that measurement is PRIMARY —
    surface_density_class is set from it, density_evidence_level reflects the measured grade, and the
    absolute_* field group carries the measured value + unit + semantics + provenance. The HPA×CPTAC
    grade-D estimate is retained as the FALLBACK (and still reported alongside a measurement, so a
    consumer sees both). This is the tiered-evidence promotion: a real calibrated anchor overrides an
    inferred prior. No fabrication — an empty/held corpus simply falls through to the grade-D estimate.
    """
    ladder = _ladder_measurement(target, indication)
    if ladder is not None:
        return ladder

    return _hpa_cptac_estimate(target, indication)


def _surface_accessibility(target: str) -> dict:
    """SURFACE-ACCESSIBILITY tier for the grade-D estimate — a SOFT, NON-SUPPRESSING gate.

    The grade-D estimate derives from HPA×CPTAC WHOLE-CELL proteomics, which cannot distinguish an
    antibody-ACCESSIBLE surface antigen from an intracellular / inner-leaflet / secreted protein. So
    before the whole-cell number may be CALLED a "surface density", we require POSITIVE
    extracellular-accessibility evidence — an actual membrane-spanning topology with an extracellular
    orientation, not mere "membrane" association.

    SIGNAL SWAP (2026-08-05, P8.1 Slice 1): this now keys on the TMbed predicted-topology product
    (`topology_predictions_tmbed.topology_class` + `ecd_orientation`) instead of the discredited
    `surfaceome_family_fusion.is_surface_protein` OR-union (SURFY | HPA-substring | IUPHAR). A
    2026-07-23 multiagent verification showed the OR-union was unreliable BOTH ways — intracellular
    false-POSITIVES (NRAS/GAPDH/APC/CTNNB1 via the naive HPA "Plasma membrane" substring) AND surface
    false-NEGATIVES at confidence 1.0 (STEAP1/TFRC/DR5/ENPP3). The topology product resolves ALL of
    these correctly: NRAS→no_transmembrane (0 TM), STEAP1→multi_pass + ecd outside, TFRC/DR5→single_pass
    + ecd outside (verified live against topology-predictions-tmbed-v1). Keying on an EXTRACELLULAR
    topological orientation — not "membrane presence" — is the decisive fix the accessibility plan
    (.claude/plans/surface-accessibility-tiered-classifier.md) specifies.

    Admissibility (whole-cell estimate is ALWAYS retained regardless — this labels, never suppresses):
        admissible   — a membrane-spanning class WITH extracellular orientation:
                       multi_pass / single_pass_type_1 / single_pass_type_2 (ecd 'outside').
        unsupported  — no_transmembrane: no membrane-spanning domain → NOT a surface density
                       (the NRAS/GAPDH case; whole-cell estimate retained, flagged not-a-surface-density).
        provisional  — membrane-spanning but orientation ambiguous (single_pass_type_other) OR
                       beta_barrel, OR topology data_unavailable / read error / not-in-table: absence is
                       NEVER negative evidence — the estimate stands, flagged provisional.

    GPI-ANCHOR RESCUE (P8.1 Slice 2, 2026-08-05): TMbed 1D topology cannot see a GPI anchor (no
    membrane-spanning segment), so GPI-anchored antigens (MSLN/FOLR1/CD59/ALPP) predict as
    `no_transmembrane`. Before calling those `unsupported`, we consult UniProt curated LIPID features
    (uniprot-gpi-anchored-v1) — a GPI-anchored target is RECLASSIFIED admissible (it IS displayed on
    the outer leaflet). The discriminator is specific: NRAS (cytoplasmic S-farnesyl lipid-anchor, NOT
    GPI) stays `unsupported`. GPI enrichment is best-effort — its absence/error never breaks the gate,
    and a genuine no_transmembrane non-GPI protein (NRAS/GAPDH) is still `unsupported` (whole-cell
    estimate retained, never suppressed). Never raises."""
    try:
        from methods.topology_predictions_tmbed.read import read_target_summary as _topo

        s = _topo(target)
    except Exception:
        return {
            "surface_density_admissibility": "provisional",
            "surface_accessibility_note": "topology_read_error_absence_not_negative_evidence",
            "_topology_class": None,
        }
    tclass = s.get("topology_class")
    if tclass in (None, "data_unavailable"):
        return {
            "surface_density_admissibility": "provisional",
            "surface_accessibility_note": "topology_unavailable_coverage_gap_not_negative",
            "_topology_class": tclass,
        }
    ecd_outside = str(s.get("ecd_orientation") or "").lower() == "outside"
    # Membrane-spanning + extracellular orientation → the whole-cell number may be a surface density.
    if tclass in ("multi_pass", "single_pass_type_1", "single_pass_type_2") and ecd_outside:
        return {
            "surface_density_admissibility": "admissible",
            "surface_accessibility_note": f"extracellular_topology_{tclass}_ecd_outside",
            "_topology_class": tclass,
        }
    # No membrane-spanning domain in TMbed's 1D topology. Before calling this not-a-surface-density,
    # check the GPI-ANCHOR RESCUE (P8.1 Slice 2): a GPI-anchored antigen (MSLN/FOLR1/CD59/ALPP) has NO
    # membrane-spanning segment — TMbed cannot see it — but IS displayed on the outer leaflet and IS a
    # biologics target. UniProt curated LIPID features (uniprot-gpi-anchored-v1) carry the fact TMbed
    # lacks, so a no_transmembrane target that is GPI-anchored is RECLASSIFIED admissible. GPI read is
    # best-effort: any error / not-GPI falls through to the unsupported call below (never breaks the gate).
    if tclass == "no_transmembrane":
        try:
            from methods.uniprot_gpi_anchor.read import read_gpi_anchor

            gpi = read_gpi_anchor(target)
        except Exception:  # noqa: BLE001 — GPI enrichment is best-effort; absence never negative
            gpi = None
        if gpi and gpi.get("is_gpi_anchored") is True:
            return {
                "surface_density_admissibility": "admissible",
                "surface_accessibility_note": (
                    f"gpi_anchored_external_{(gpi.get('gpi_lipid_note') or 'gpi_anchor').replace(' ', '_')}"
                ),
                "_topology_class": tclass,
                "_gpi_anchored": True,
            }
        # Not GPI (or GPI product unavailable) → genuinely no extracellular exposure (NRAS/GAPDH).
        return {
            "surface_density_admissibility": "unsupported",
            "surface_accessibility_note": (
                "no_transmembrane_domain_whole_cell_estimate_retained_not_a_surface_density"
            ),
            "_topology_class": tclass,
            "_gpi_anchored": False,
        }
    # Membrane-spanning but orientation ambiguous (single_pass_type_other) or beta_barrel → provisional.
    return {
        "surface_density_admissibility": "provisional",
        "surface_accessibility_note": f"membrane_spanning_orientation_uncertain_{tclass}",
        "_topology_class": tclass,
    }


def _hpa_cptac_estimate(target: str, indication: Optional[str] = None) -> dict:
    """The grade-D HPA-IHC × CPTAC-log2FC estimate (the fallback when the ladder has no measurement).

    Extracted so both the fallback path AND the ladder's alongside-context reuse one implementation.
    Order-of-magnitude prior, NOT a calibrated anchor — see read_abundance_density_summary docstring.

    SOFT surface-accessibility gate (NOT a veto): the estimate is always computed + returned, but
    tagged with `surface_density_admissibility` {admissible|unsupported|provisional} so a consumer
    knows whether a WHOLE-CELL-derived number may be treated as an antibody-accessible surface density.
    A non-surface target (KRAS) still gets its abundance estimate, but flagged `unsupported` — never
    silently zeroed (which would have discarded the observation AND risked suppressing a real
    STEAP1-like antigen the classifier under-calls). See _surface_accessibility."""
    access = _surface_accessibility(target)
    anchor = _hpa_ihc_anchor(target, indication)
    ihc_class = anchor["hpa_ihc_intensity_class"]
    if ihc_class == "unmeasured":
        out = _empty_density("no_hpa_ihc_anchor")
        out.update(access)
        return out

    center, base_factor = _IHC_CLASS_CALIBRATION[ihc_class]

    # CPTAC tumor shift (relative). read_target_summary returns the tissue-matched cohort row when an
    # indication maps to a cohort; else best-effect across cohorts. Missing coverage → anchor-only
    # (log2FC = 0) with a widened band, NOT unmeasured — the normal-tissue anchor alone is still an
    # audit-defensible first-pass, just less certain.
    cptac = read_target_summary(target, indication)
    log2fc = cptac.get("protein_effect_size")
    # A non-FINITE log2FC (inf/-inf/NaN) is a degenerate CPTAC value — inf arises when the normal-tissue
    # reference median is 0 (tumor-detected, normal-absent): meaningful biology, but nonsense as a 2**x
    # shift multiplier. Treat it as CPTAC-not-usable → anchor-only (shift=1) with the widened band, same
    # as the CPTAC-absent path. Guards STEAP1 (effect=inf → previously produced median=inf).
    import math

    _log2fc_finite = log2fc is not None and math.isfinite(float(log2fc))
    cptac_covered = cptac.get("protein_expression_class") not in (None, "data_unavailable") and _log2fc_finite
    shift = (2.0 ** float(log2fc)) if cptac_covered else 1.0

    median = center * shift

    # Band width: base multiplicative factor, WIDENED when the evidence is thinner. A tissue-specific
    # HPA anchor + CPTAC coverage is the tightest; breadth-only or CPTAC-absent each widen it (they
    # compound), so a doubly-weak estimate has the widest, most-honest band.
    factor = base_factor
    if anchor["anchor_strength"] == "breadth_only":
        factor *= 1.6
    if not cptac_covered:
        factor *= 1.6

    lower = median / factor
    upper = median * factor

    density_class = _density_class(median)
    # Surface-density ADMISSIBILITY gates the VIABILITY calls + the surface class LABEL, but NEVER the
    # abundance numbers (which are always retained). `unsupported` = a whole-cell estimate that is not
    # a valid surface density → surface_density_class is relabeled and the TCE/ADC flags are False
    # (you cannot be surface-modality-viable on a number that isn't a surface density). `admissible` /
    # `provisional` keep the whole-cell class as the surface estimate (provisional = weaker confidence).
    admissibility = access["surface_density_admissibility"]
    if admissibility == "unsupported":
        surface_class = "not_surface_density_whole_cell_estimate"
        tce_viable = adc_viable = False
    else:
        surface_class = density_class
        tce_viable = density_class in ("high", "moderate")
        adc_viable = density_class == "high"
    return {
        "surface_density_class": surface_class,
        # Evidence grade D: INFERRED from whole-cell/tissue PRIORS (IHC + CPTAC), no direct surface
        # calibration. NOT a calibrated absolute anchor (that is level A/B/C — calibrated flow). The
        # copies numbers are an order-of-magnitude prior; is_tce/adc flags are WORKING-PRIOR calls.
        "density_evidence_level": "D",
        # whole-cell abundance estimate — ALWAYS retained (visibility != admissibility)
        "estimated_copies_per_cell_median": round(median, 1),
        "estimated_copies_per_cell_lower": round(lower, 1),
        "estimated_copies_per_cell_upper": round(upper, 1),
        "hpa_ihc_anchor_used": anchor["hpa_ihc_anchor_used"],
        "hpa_ihc_intensity_class": ihc_class,
        "is_tce_viable": tce_viable,
        "is_adc_high_payload_viable": adc_viable,
        # surface-accessibility soft gate (admissible | unsupported | provisional) + note + topology_class
        **access,
        "method_version": _DENSITY_METHOD_VERSION,
        # provenance (leading underscore = not a card summary_field; for audit/debug only)
        "_whole_cell_class": density_class,  # the raw class before the admissibility relabel
        "_cptac_covered": cptac_covered,
        "_cptac_log2fc": log2fc if cptac_covered else None,
        "_cptac_cohort": cptac.get("cohort") if cptac_covered else None,
        "_anchor_strength": anchor["anchor_strength"],
        "_band_factor": round(factor, 2),
    }


# --- figure emitters (upgraded 2026-07-22: true distribution boxplots) -----------------------
# ORIGINALLY (Slice 7) this figure was a per-cohort DUMBBELL of tumor/normal MEDIANS, because the
# only product available was per-cohort SUMMARY (cptac-protein-tumor-vs-normal-per-cohort-v1). The
# per-SAMPLE product (cptac-protein-tumor-vs-normal-per-sample-v1) now persists the per-aliquot
# log-ratios, so we draw the honest figure the card originally wanted: a grouped tumor-vs-normal
# BOXPLOT per cohort, with per-cohort statistics (Welch's t + Mann-Whitney U) recomputed FROM THE
# SAMPLES the boxes are drawn from — no median-only dumbbell, no drift between the stat and the box.
# The figure id + path + emitter function names are unchanged so the card decl + skill dispatcher
# stay wired; only the content changed (dumbbell -> distribution).


def _load_takeda_style(target_contracts_dir):
    import sys as _sys

    import matplotlib.pyplot as plt

    style_path = Path(target_contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    _sys.path.insert(0, str(Path(target_contracts_dir) / "plot_styles"))
    try:
        import takeda_palette

        return takeda_palette
    except Exception:
        return None


def _sig_stars(p):
    """Significance stars from a p-value (Welch/MWU on the samples — NOT the summary q)."""
    if p is None or p != p:
        return ""
    if p < 1e-10:
        return "***"
    if p < 1e-4:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


# Tumor = deep navy, Normal = muted blue (matches the dumbbell's palette so the color identity of
# "tumor" vs "normal" is stable across the protein cards).
_TUMOR_FILL, _TUMOR_LINE = "#1f4e79", "#0a2540"
_NORMAL_FILL, _NORMAL_LINE = "#a9c5db", "#5b7f99"


# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
def emit_per_cohort_panel(
    target: str,
    out_dir: Path,
    target_contracts_dir=os.environ.get("TARGET_CONTRACTS_ROOT")
    or str(Path(__file__).resolve().parents[2].parent / "rnd-computational-biology-oncology-target-contracts"),
    *,
    presampled=None,
) -> Path:
    """Grouped tumor-vs-normal BOXPLOT per CPTAC cohort, drawn from the per-aliquot log-ratios
    (per-sample product), ordered by tumor-vs-normal median delta. Each cohort shows the true
    tumor + normal distributions side by side; the per-cohort Welch/Mann-Whitney significance
    (recomputed from the same samples) + n annotate each pair. Replaces the median-only dumbbell.

    OFFLINE seam (figure-consolidation Stage 6): pass `presampled` — the per-cohort stats list
    (as returned by per_cohort_distribution_stats, INCLUDING the raw `_tumor_values`/`_normal_values`
    arrays the boxes are drawn from) — to render from it with NO per-sample product re-read. When
    None the legacy live recompute (per_cohort_distribution_stats) is taken."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_style(target_contracts_dir)
    out_dir = Path(out_dir)
    out_path = out_dir / "figure_protein_per_cohort_tumor_vs_normal.svg"
    stats = presampled if presampled is not None else per_cohort_distribution_stats(target)
    if not stats or pal is None:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(
            0.5,
            0.5,
            f"{target} — not quantified in any CPTAC cohort",
            ha="center",
            va="center",
            fontsize=10,
            color="#777",
        )
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    tfill, tline = pal.TUMOR_FILL, pal.TUMOR_LINE
    nfill, nline = pal.NORMAL_FILL, pal.NORMAL_LINE

    # driving metric for the takeaway: how many cohorts are significantly tumor-elevated (MWU/Welch p<.05).
    def _p(s):
        return s["mwu_p"] if s.get("mwu_p") is not None else s.get("welch_p")

    n_cohorts = len(stats)
    n_up = sum(1 for s in stats if (s.get("delta_median") or 0) > 0 and (_p(s) is not None and _p(s) < 0.05))
    take = f"{target} protein is significantly elevated in tumor vs normal in {n_up}/{n_cohorts} CPTAC cohort(s)."

    stats = list(reversed(stats))  # most tumor-elevated (largest Δ) at TOP → reverse for bottom-up y
    fig_h = min(max(3.6, n_cohorts * 0.62 + 1.2), 8.4)
    ann_x = max([v for s in stats for v in (s["tumor_max"], s["normal_max"]) if v is not None] or [0]) + 0.15

    with pal.figure_frame(
        target,
        None,
        "tumor vs. normal protein",
        out_path=out_path,
        figsize=(7.4, fig_h),
        left=0.17,
        top=1 - 0.82 / fig_h,
        bottom=0.95 / fig_h,
        provenance=f"CPTAC TMT MS (whole-cell lysate)  ·  {n_cohorts} cohorts  ·  Δ = tumor − normal median",
        takeaway=take,
    ) as F:
        ax = F.ax
        yticks, ylabels = [], []
        for i, s in enumerate(stats):
            drew = False
            if s["_tumor_values"]:
                bp = ax.boxplot(
                    [s["_tumor_values"]],
                    positions=[i + 0.18],
                    orientation="horizontal",
                    widths=0.30,
                    patch_artist=True,
                    showfliers=False,
                    manage_ticks=False,
                )
                bp["boxes"][0].set(facecolor=tfill, edgecolor=tline, linewidth=1.1)
                for w in bp["whiskers"] + bp["caps"]:
                    w.set(color=tline, linewidth=1.0)
                for m in bp["medians"]:
                    m.set(color="white", linewidth=1.4)
                drew = True
            if s["_normal_values"]:
                bp = ax.boxplot(
                    [s["_normal_values"]],
                    positions=[i - 0.18],
                    orientation="horizontal",
                    widths=0.30,
                    patch_artist=True,
                    showfliers=False,
                    manage_ticks=False,
                )
                bp["boxes"][0].set(facecolor=nfill, edgecolor=nline, linewidth=1.1)
                for w in bp["whiskers"] + bp["caps"]:
                    w.set(color=nline, linewidth=1.0)
                for m in bp["medians"]:
                    m.set(color=nline, linewidth=1.4)
                drew = True
            if not drew:
                continue
            yticks.append(i)
            ylabels.append(f"{s['cohort']}\n(T={s['n_tumor']} N={s['n_normal']})")
            stars = _sig_stars(_p(s))
            d = s["delta_median"]
            ax.text(
                ann_x,
                i,
                (f"Δ{d:+.2f} {stars}" if d is not None else stars),
                va="center",
                fontsize=7,
                color=pal.INK_SECONDARY,
            )
        ax.axvline(0.0, **pal.REFLINE_NEUTRAL)
        ax.set_xlim(right=ann_x + 0.9)
        ax.set_yticks(yticks)
        ax.set_yticklabels(ylabels, fontsize=7)
        # DIRECT labels on the top cohort's pair (tumor = upper box, normal = lower) — the consistent
        # ordering makes this the key for every row; no legend box to collide with the Δ column/data.
        if yticks:
            top = max(yticks)
            ax.annotate(
                "tumor",
                xy=(0.008, top + 0.18),
                xycoords=("axes fraction", "data"),
                ha="left",
                va="center",
                fontsize=7.5,
                color=tline,
                weight="bold",
            )
            ax.annotate(
                "normal",
                xy=(0.008, top - 0.18),
                xycoords=("axes fraction", "data"),
                ha="left",
                va="center",
                fontsize=7.5,
                color=nline,
                weight="bold",
            )
        F.axis_label("x", "Tumor vs. normal protein", "log2 ratio (CPTAC TMT MS, per aliquot)")
    return out_path


def emit_plot_data(target: str, out_dir: Path) -> Path:
    """Per-cohort distribution-statistics parquet (one row per cohort tested): n_tumor/n_normal,
    tumor/normal quartiles, delta_median, welch_p, mwu_p, PLUS the raw per-aliquot arrays
    (`tumor_values`/`normal_values` list-columns) the boxes are drawn from — so the OFFLINE figure
    seam (figures.render_from_plot_data) can replay the boxplot with NO per-sample product re-read.
    The `_`-prefixed in-memory keys are persisted under public column names (tumor_values/
    normal_values); figures.render_from_plot_data maps them back."""
    import pandas as pd

    stats = per_cohort_distribution_stats(target)
    rows = []
    for s in stats:
        row = {k: v for k, v in s.items() if not k.startswith("_")}
        row["tumor_values"] = list(s.get("_tumor_values") or [])
        row["normal_values"] = list(s.get("_normal_values") or [])
        rows.append(row)
    df = pd.DataFrame(rows)
    out_file = Path(out_dir) / "plot_data_protein_per_cohort.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_plotly_specs(
    target: str,
    out_dir: Path,
    target_contracts_dir=os.environ.get("TARGET_CONTRACTS_ROOT")
    or str(Path(__file__).resolve().parents[2].parent / "rnd-computational-biology-oncology-target-contracts"),
    *,
    presampled=None,
) -> list:
    """Interactive grouped tumor-vs-normal boxplot per cohort, built from the SAME
    per_cohort_distribution_stats (and their raw per-aliquot arrays) the SVG uses — no drift.
    Best-effort (plotly optional). OFFLINE seam: pass `presampled` (the per-cohort stats list with
    raw `_tumor_values`/`_normal_values`) to render from it with NO per-sample product re-read."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        print(f"[cptac_protein_deg] plotly spec emission skipped: {e}", file=__import__("sys").stderr)
        return []
    stats = presampled if presampled is not None else per_cohort_distribution_stats(target)
    if not stats:
        return []
    # most tumor-elevated first (top of the plot); plotly categorical y stacks bottom-up so reverse
    stats = list(reversed(stats))
    # per-cohort y labels; the Δmedian + MWU significance is surfaced via right-margin annotations
    # below (add_annotation), matching the SVG — so no per-point hovertext is accumulated here.
    cohorts = [f"{s['cohort']} (T={s['n_tumor']} N={s['n_normal']})" for s in stats]

    fig = go.Figure()
    # tumor + normal as two box traces; y = cohort label, x = per-aliquot log-ratio
    t_y, t_x, n_y, n_x = [], [], [], []
    for label, s in zip(cohorts, stats):
        t_x.extend(s["_tumor_values"])
        t_y.extend([label] * len(s["_tumor_values"]))
        n_x.extend(s["_normal_values"])
        n_y.extend([label] * len(s["_normal_values"]))
    fig.add_trace(
        go.Box(
            x=n_x,
            y=n_y,
            name="normal",
            orientation="h",
            marker_color=_NORMAL_LINE,
            fillcolor=_NORMAL_FILL,
            line=dict(width=1),
            boxpoints=False,
        )
    )
    fig.add_trace(
        go.Box(
            x=t_x,
            y=t_y,
            name="tumor",
            orientation="h",
            marker_color=_TUMOR_LINE,
            fillcolor=_TUMOR_FILL,
            line=dict(width=1),
            boxpoints=False,
        )
    )
    # significance annotations at the right
    xr = max([v for s in stats for v in (s["tumor_max"], s["normal_max"]) if v is not None] or [0])
    for label, s in zip(cohorts, stats):
        p = s["mwu_p"] if s["mwu_p"] is not None else s["welch_p"]
        d = s["delta_median"]
        if d is None:
            continue
        fig.add_annotation(
            x=xr + 0.2, y=label, text=f"Δ{d:+.2f} {_sig_stars(p)}", showarrow=False, font=dict(size=9), xanchor="left"
        )
    fig.update_layout(
        title=f"{target} — tumor vs normal protein distribution, per CPTAC cohort",
        xaxis_title="log2 tumor-vs-reference protein ratio (CPTAC TMT MS, per aliquot)",
        boxmode="group",
        template="plotly_white",
        margin=dict(l=140, r=70, t=50, b=50),
    )
    (Path(out_dir) / "figure_protein_per_cohort_tumor_vs_normal.plotly.json").write_text(fig.to_json())
    return [
        {
            "id": "protein_per_cohort_tumor_vs_normal",
            "path": "figure_protein_per_cohort_tumor_vs_normal.plotly.json",
            "type": "plotly",
        }
    ]
