"""gdc_somatic_hotspot.read — read functions for the MC3-aggregated hotspot Parquet.

This module is the *consumption* side of gdc_somatic_hotspot; cli.py is the
*production* side (runs the MC3 aggregation). Both live in the methods repo because
both are deterministic data operations.

Consumes the Parquet produced by `python -m methods.gdc_somatic_hotspot.cli`
(typically at data-products-cache/gdc_hotspots/{indication}.parquet or registered
as a derived manifest in data-catalog).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from functools import lru_cache, partial

import yaml

from methods.subgroup_common.iteration import subgroup_iterable
from methods.subgroup_common.panorama import (
    SUBGROUP_N_FLOOR,
    build_panorama,
    delta_reducer,
    evidence_state,
)

DEFAULT_AWS_PROFILE = "cbg"

# Per-sample MC3 MAF cache (the raw substrate for subgroup-stratified frequency;
# distinct from the pre-aggregated hotspot Parquet read_hotspot_summary consumes).
DEFAULT_MC3_MAF_CACHE = Path.home() / ".cache" / "framework-gdc-pancohort-somatic"

# Registry of per-sample MAF sources the stratified reader can group by member-set.
# Each entry: (parquet-path template, cohort label). The same groupby-within-member-set
# logic serves both the TCGA molecular strata (MC3) and the GENIE-BPC LOT strata
# (GENIE-registry MAF, which carries KRAS calls for the BPC sample_ids).
MAF_SOURCES = {
    "tcga_mc3": {
        "path": DEFAULT_MC3_MAF_CACHE / "{ind}-mc3.parquet",
        "cohort": "TCGA-MC3",
    },
    "genie_registry": {
        "path": Path.home() / ".cache" / "framework-genie-public-v19" / "{ind}-genie-maf.parquet",
        "cohort": "GENIE-registry",
    },
}

# SUBGROUP_N_FLOOR + evidence_state are imported from subgroup_common.panorama
# (single source of truth shared across all stratified readers).

# Default cache location for aggregator outputs. Iter-2 may register these as
# proper derived manifests in data-catalog.
DEFAULT_CACHE_BASE = Path("/home/sagemaker-user/data-products-cache/gdc_hotspots")

# Indication → list of TCGA projects (same as cli.py — duplicated here to keep read.py
# importable without dragging in cli.py's click dependency).
INDICATION_TO_GDC_PROJECTS = {
    "COADREAD": ["TCGA-COAD", "TCGA-READ"],
    # PAAD = framework canonical (indication_crosswalk.yaml); PDAC = CPTAC spelling. Dual-keyed
    # to match cli.py — the PDAC-only key silently n/a'd a canonical PAAD query. See cli.py note.
    "PAAD": ["TCGA-PAAD"],
    "PDAC": ["TCGA-PAAD"],
    "NSCLC": ["TCGA-LUAD", "TCGA-LUSC"],
    "SCLC": [],
    "GC": ["TCGA-STAD"],
}


from methods.target_id_sidecar import ensure_aws_profile


# --- Derived-manifest resolution (2026-08-05) ---------------------------------
# The MC3 hotspot aggregate + per-sample MAF are now REGISTERED derived products
# (tcga-mc3-hotspot-frequency-v1 / tcga-mc3-per-sample-maf-v1). Resolve them from the
# data-catalog manifest → S3, so a fresh environment reads the durable product instead
# of a machine-local cache file. LOCAL-CACHE-FIRST: if the legacy local file exists it
# wins (preserves the fast path + byte-stability for already-provisioned environments),
# else fall back to the manifest's S3 payload. Both products carry an `indication`
# column, so a single pushdown filter on (indication[, gene_symbol]) works either way.
DATA_CATALOG = Path(os.environ.get(
    "DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"))

_HOTSPOT_FREQUENCY_MANIFEST = "tcga-mc3-hotspot-frequency-v1"
_PER_SAMPLE_MAF_MANIFEST = "tcga-mc3-per-sample-maf-v1"


def _load_manifest(manifest_id: str) -> dict:
    """Load a derived manifest YAML from the data-catalog (returns {} if absent, so the
    local-cache fallback still works in an environment without the catalog checked out)."""
    candidates = list((DATA_CATALOG / "manifests" / "derived").glob(f"{manifest_id}.yaml"))
    if not candidates:
        return {}
    with candidates[0].open() as f:
        return yaml.safe_load(f) or {}


def _manifest_s3_path(manifest_id: str) -> Optional[str]:
    """The manifest's s3_uri as a bucket/key path (no s3:// prefix), or None if unresolvable."""
    s3_uri = _load_manifest(manifest_id).get("s3_uri")
    if not s3_uri or not s3_uri.startswith("s3://"):
        return None
    return s3_uri[len("s3://"):]


def _read_product_table(local_path: Path, manifest_id: str, *, filters=None, columns=None):
    """Read a derived product as a pyarrow Table, LOCAL-CACHE-FIRST then S3-manifest.

    - If `local_path` exists → read it (the legacy fast path; byte-identical to pre-migration).
    - Else resolve the manifest's s3_uri and read from S3 with the same filters/columns.
    Returns None if neither is available (caller renders data_unavailable)."""
    import pyarrow.parquet as pq
    ensure_aws_profile()
    if local_path.exists():
        return pq.read_table(local_path, filters=filters, columns=columns)
    key = _manifest_s3_path(manifest_id)
    if key is None:
        return None
    import pyarrow.fs as fs
    try:
        return pq.read_table(key, filesystem=fs.S3FileSystem(), filters=filters, columns=columns)
    except Exception as e:  # noqa: BLE001
        # Distinguish DEFINITIVE ABSENCE (object genuinely not there → data_unavailable, graceful)
        # from a TRANSIENT/AUTH failure (creds expired, throttle, network) which must NOT be silently
        # masked as a coverage gap (the "bare-except masks broken env" bug class). Mirrors the
        # definitive-vs-transient discriminant in tcga_fusion_consensus/read.py.
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", "")) if hasattr(e, "response") else ""
        definitive = (code in ("404", "NoSuchKey", "NoSuchBucket")
                      or e.__class__.__name__ in ("NoSuchKey", "FileNotFoundError"))
        if definitive:
            return None            # real absence → caller renders data_unavailable
        raise                      # infra failure → surface it, do not mask as a coverage gap


def _resolve_aggregate_path(indication: str, cache_base: Path = DEFAULT_CACHE_BASE) -> Path:
    """Locate the LOCAL aggregated Parquet for an indication (the cache fast path). The
    registered product (tcga-mc3-hotspot-frequency-v1) is the S3 fallback — see
    _read_product_table. Kept as a function for the existing aggregate_path override contract."""
    return cache_base / f"{indication.lower()}_mc3_hotspots.parquet"


# --- Driver-recurrence percentile (Axis-1 analog, 2026-08-05) -----------------
# The all-gene contextualization axis for genomic alteration, mirroring what
# tumor-presence's allgene_percentile does for expression: turn the ABSOLUTE
# overall_mutation_frequency into a RELATIVE one — "is this gene's recurrence
# unusual among all mutated genes in THIS indication?" A raw 8% frequency is
# uninterpretable without a reference frame; the percentile supplies it.
#
# NULL SEMANTICS (the correctness-critical choices):
#   1. The MC3 aggregate has one gene-SUMMARY row per gene (hotspot_protein_change
#      is null) PLUS one row per hotspot codon. The null MUST use ONLY the summary
#      rows — otherwise a gene with many hotspots is over-counted in the reference.
#   2. The aggregate lists ONLY genes with >=1 non-synonymous mutation, so the
#      honest reference frame is "among genes mutated at all in this indication",
#      NOT "all ~20k genes". This is stated in driver_recurrence_context for audit.
#   3. Context-matched to the SAME indication aggregate the target row came from —
#      never pooled across indications (the #1 percentile-null risk).

@lru_cache(maxsize=16)
def _allgene_mutation_frequency_null(aggregate_path_str: str, indication: str = "") -> tuple:
    """All genes' overall_mutation_frequency (gene-summary rows only) for ONE indication —
    the context-matched null for the driver-recurrence percentile. Reads LOCAL-CACHE-FIRST
    then the registered S3 product (indication-filtered — the S3 concat holds all indications,
    the local per-indication file holds one; a redundant indication filter is harmless on both).
    Cached per (local path, indication); one added scan of a few columns. Returns a tuple
    (hashable/cache-safe); empty on any failure → percentile is None."""
    try:
        local = Path(aggregate_path_str)
        # gene-summary rows carry a null hotspot_protein_change; keep only those so each gene
        # contributes its frequency exactly ONCE. Filter to the indication (S3 concat carries all).
        filters = [("indication", "=", indication)] if indication else None
        table = _read_product_table(
            local, _HOTSPOT_FREQUENCY_MANIFEST,
            filters=filters,
            columns=["overall_mutation_frequency", "hotspot_protein_change"])
        if table is None:
            return tuple()
        df = table.to_pandas()
        summary = df[df["hotspot_protein_change"].isnull()]
        return tuple(
            float(v) for v in summary["overall_mutation_frequency"].tolist()
            if v is not None)
    except Exception:
        return tuple()


def _driver_recurrence_percentile(aggregate_path: Path, indication, overall_freq, cutoffs: dict = None):
    """Percentile + companion categorical of this gene's overall_mutation_frequency
    among all mutated genes in the SAME indication aggregate. DISPLAY facet — the
    class is emitted for render/LLM/rules-readiness but the skill does NOT wire a
    rule against it yet (verdict spine stays byte-stable). Returns (pct, class)."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # methods/ on path
    from percentile_null import percentile_rank, classify_percentile
    null_vec = _allgene_mutation_frequency_null(str(aggregate_path), indication or "")
    pct = percentile_rank(overall_freq, null_vec)
    return pct, classify_percentile(pct, cutoffs)


def _genie_recurrence_fields(target: str, indication: str) -> dict:
    """The GENIE panel-coverage-correct recurrence fields (genie_driver_recurrence_*) for the
    mutation-hotspot-frequency card — the higher-N sibling of the MC3 driver_recurrence_*. Lazily
    imports genie_panel_recurrence + always returns the 4 keys (graceful data_unavailable on any
    failure/absence), so the card gains the GENIE comparator without ever breaking the MC3 path."""
    keys = ("genie_driver_recurrence_percentile", "genie_driver_recurrence_class",
            "genie_mutation_frequency", "genie_recurrence_context")
    try:
        from methods.genie_panel_recurrence.read import genie_recurrence_for_gene
        g = genie_recurrence_for_gene(target, indication)
        return {k: g.get(k) for k in keys}
    except Exception:
        return {"genie_driver_recurrence_percentile": None,
                "genie_driver_recurrence_class": "data_unavailable",
                "genie_mutation_frequency": None,
                "genie_recurrence_context": None}


def read_hotspot_summary(
    target: str,
    indication: str,
    aggregate_path: Optional[Path] = None,
    top_n_hotspots: int = 5,
    top_n_cooccurring: int = 10,
) -> dict:
    """Query the MC3-aggregated hotspot Parquet for a target+indication.

    Returns dict matching the mutation-hotspot-frequency card_spec's summary_fields:
      overall_mutation_frequency, n_samples_in_indication, n_samples_mutated,
      hotspot_frequencies (list of {codon, frequency}), top_cooccurring_genes,
      top_mutually_exclusive_genes.

    `top_cooccurring_genes` and `top_mutually_exclusive_genes` are *iter-2 work*
    (requires co-mutation analysis across samples; iter-1b returns empty lists
    with a structured note).
    """
    ensure_aws_profile()
    if aggregate_path is None:
        aggregate_path = _resolve_aggregate_path(indication)

    # Predicate pushdown on (indication, gene_symbol) — LOCAL-CACHE-FIRST then the registered
    # S3 product (tcga-mc3-hotspot-frequency-v1). None → neither local file nor S3 resolvable.
    table = _read_product_table(
        aggregate_path, _HOTSPOT_FREQUENCY_MANIFEST,
        filters=[("indication", "=", indication), ("gene_symbol", "=", target)],
    )

    if table is None:
        return {
            "overall_mutation_frequency": None,
            "n_samples_in_indication": None,
            "n_samples_mutated": None,
            "driver_recurrence_percentile": None,
            "driver_recurrence_class": "data_unavailable",
            "driver_recurrence_context": None,
            # GENIE is a SEPARATE cohort/source — fetch it even when the MC3 aggregate is absent
            # (a gene missing from MC3 may still be mutated in GENIE's panel cohort; the comparators
            # are independent). Graceful data_unavailable if GENIE also lacks it.
            **_genie_recurrence_fields(target, indication),
            "hotspot_frequencies": [],
            "top_cooccurring_genes": [],
            "top_mutually_exclusive_genes": [],
            "_data_note": (
                f"No MC3 hotspot aggregate resolvable for {indication} (neither local cache "
                f"{aggregate_path} nor the {_HOTSPOT_FREQUENCY_MANIFEST} manifest/S3). "
                f"Run `python -m methods.gdc_somatic_hotspot.cli --indication {indication} "
                f"--out {aggregate_path}` to produce it, or check the data-catalog manifest."
            ),
        }

    if table.num_rows == 0:
        # Target has NO non-synonymous mutation in this indication — a real biological
        # zero, so it sits at the very bottom of the recurrence distribution. Rank the
        # 0.0 against the (mutated-gene) null: it lands below every mutated gene, which
        # the percentile correctly reports as ~0th / bottom_decile (a genuine negative,
        # distinct from data_unavailable when the aggregate itself is missing).
        rec_pct, rec_class = _driver_recurrence_percentile(aggregate_path, indication, 0.0)
        return {
            "overall_mutation_frequency": 0.0,
            "n_samples_in_indication": None,
            "n_samples_mutated": 0,
            "driver_recurrence_percentile": rec_pct,
            "driver_recurrence_class": rec_class,
            "driver_recurrence_context": (
                f"among genes with >=1 non-synonymous mutation in {indication} "
                f"(TCGA-MC3 aggregate); target itself has zero mutations"
            ),
            # GENIE independent of MC3: a target with zero MC3 mutations may still be mutated in
            # GENIE's panel cohort — the informative cross-source disagreement.
            **_genie_recurrence_fields(target, indication),
            "hotspot_frequencies": [],
            "top_cooccurring_genes": [],
            "top_mutually_exclusive_genes": [],
            "_data_source": str(aggregate_path),
            "_data_note": f"target {target!r} has no rows in {indication} MC3 aggregate (no non-synonymous mutations)",
        }

    # Convert to pandas for easier processing
    df = table.to_pandas()
    # Gene-summary row is the one with hotspot_protein_change == null
    summary_row = df[df["hotspot_protein_change"].isnull()].iloc[0]
    hotspot_rows = df[df["hotspot_protein_change"].notnull()].sort_values(
        "hotspot_n_samples", ascending=False
    ).head(top_n_hotspots)

    overall_freq = float(summary_row["overall_mutation_frequency"])
    # Driver-recurrence percentile (Axis-1 analog) — where does this gene's recurrence
    # fall among ALL mutated genes in this indication? DISPLAY facet, verdict-inert.
    rec_pct, rec_class = _driver_recurrence_percentile(aggregate_path, indication, overall_freq)

    return {
        "overall_mutation_frequency": overall_freq,
        "n_samples_in_indication": int(summary_row["n_samples_in_indication"]),
        "n_samples_mutated": int(summary_row["n_samples_mutated"]),
        "driver_recurrence_percentile": rec_pct,
        "driver_recurrence_class": rec_class,
        "driver_recurrence_context": (
            f"among genes with >=1 non-synonymous mutation in {indication} "
            f"(TCGA-MC3 aggregate, n_genes={len(_allgene_mutation_frequency_null(str(aggregate_path), indication))})"
        ),
        # GENIE (higher-N, panel-coverage-correct) recurrence — the DISTINCT sibling comparator to the
        # MC3 driver_recurrence_* above (whole-exome breadth vs 40k-patient panel). Graceful-degrade:
        # data_unavailable when GENIE has no cohort/coverage for this (target, indication).
        **_genie_recurrence_fields(target, indication),
        "hotspot_frequencies": [
            {
                "protein_change": r["hotspot_protein_change"],
                "n_samples": int(r["hotspot_n_samples"]),
                "frequency": float(r["hotspot_frequency"]),
            }
            for _, r in hotspot_rows.iterrows()
        ],
        # Iter-1b: co-occurrence requires cross-sample co-mutation analysis;
        # the aggregate Parquet doesn't carry that information yet
        "top_cooccurring_genes": [],
        "top_mutually_exclusive_genes": [],
        "_data_source": str(aggregate_path),
        "_aggregate_path": str(aggregate_path),
        "_co_occurrence_note": "co-occurrence + mutual-exclusivity analysis is iter-2 work",
    }


def _mc3_maf_path(indication: str, maf_cache: Path = DEFAULT_MC3_MAF_CACHE) -> Path:
    """Locate the per-sample MC3 MAF parquet for an indication."""
    return maf_cache / f"{indication.lower()}-mc3.parquet"


def _mutation_class(freq: float | None) -> str:
    """Coarse frequency class for a subgroup (descriptive, not a verdict).

    Bins mirror the biology-agnostic language the mutation-hotspot-frequency
    card already uses; they feed the render + interpretation_hints only.
    """
    if freq is None:
        return "insufficient"
    if freq >= 0.20:
        return "recurrently_mutated"
    if freq >= 0.05:
        return "occasionally_mutated"
    return "rarely_mutated"


def _hotspot_freq_for_samples(maf, target, member_ids, hotspot_change):
    """Frequency of a specific hotspot protein_change within a member sample-set."""
    n = len(member_ids)
    if n == 0:
        return None, 0
    hit = maf[
        (maf["gene_symbol"] == target)
        & (maf["protein_change"] == hotspot_change)
        & (maf["sample_id"].isin(member_ids))
    ]["sample_id"].nunique()
    return (hit / n), hit


def _resolve_maf_source(maf_source: str, indication: str, maf_cache: Path | None):
    """Return (parquet_path, cohort_label) for a registered MAF source.

    `maf_cache` (when given) overrides the directory of the tcga_mc3 source —
    preserves the existing test/override contract. Other sources resolve from
    MAF_SOURCES templates.
    """
    if maf_source == "tcga_mc3" and maf_cache is not None:
        return maf_cache / f"{indication.lower()}-mc3.parquet", MAF_SOURCES["tcga_mc3"]["cohort"]
    src = MAF_SOURCES.get(maf_source)
    if src is None:
        raise ValueError(f"Unknown maf_source {maf_source!r}; known: {sorted(MAF_SOURCES)}")
    return Path(str(src["path"]).format(ind=indication.lower())), src["cohort"]


@subgroup_iterable
def read_stratified_mutation_frequency(
    target: str,
    indication: str,
    hotspot_changes: tuple[str, ...] = (),
    maf_source: str = "tcga_mc3",
    maf_cache: Path | None = None,
    _sample_id_filter: set[str] | None = None,
) -> dict:
    """Per-subgroup mutation frequency of `target` from a per-sample MAF.

    DESCRIPTIVE (panorama) reader. Unlike read_hotspot_summary — which reads a
    pre-aggregated parquet with frequencies baked in at emit time — this reads
    the RAW per-sample MAF so a subgroup member-set can be filtered at read time
    (the "compute rerun, not read-side filter" point: frequency must be
    recomputed within each stratum's denominator).

    `maf_source` selects the substrate (MAF_SOURCES): `tcga_mc3` for the TCGA
    molecular strata (MSI/MSS/sidedness/KRAS), `genie_registry` for the GENIE-BPC
    LOT strata (the GENIE-registry MAF carries KRAS calls for the BPC sample_ids).
    Both flow through this ONE groupby-within-member-set path.

    Called two ways:
      * Scalar (no @subgroup_iterable fan-out): returns the whole-cohort record.
      * Via @subgroup_iterable with subgroups=[...] + subgroup_assignments_manifest:
        the decorator injects `_sample_id_filter` (the member sample_id set) per
        subgroup and returns {stratum_id: record}. The card composes those into
        per_subgroup_metrics.

    Each record carries `evidence_state` ∈ {measured, underpowered, absent} so a
    real negative (freq~0 on a floor-clearing cohort) is distinguishable from an
    unknown (too few samples) — the positive/negative/unknown trichotomy.
    """
    import pandas as pd

    maf_path, cohort = _resolve_maf_source(maf_source, indication, maf_cache)
    # LOCAL-CACHE-FIRST then the registered S3 product. The tcga_mc3 per-sample MAF is now
    # registered (tcga-mc3-per-sample-maf-v1, single pan-indication payload with an `indication`
    # column) — so when the local per-indication file is absent, resolve S3 filtered on indication.
    # The genie_registry source keeps its own path (not this manifest); an explicit maf_cache
    # override (tests) also stays local-only. Legacy local file → read whole (one indication).
    maf = None
    if maf_path.exists():
        maf = pd.read_parquet(maf_path)
    elif maf_source == "tcga_mc3" and maf_cache is None:
        table = _read_product_table(
            maf_path, _PER_SAMPLE_MAF_MANIFEST,
            filters=[("indication", "=", indication)])
        if table is not None:
            maf = table.to_pandas()
    if maf is None:
        return {
            "target": target, "indication": indication,
            "subgroup_n": 0, "overall_mutation_frequency": None,
            "n_samples_mutated": None, "subgroup_n_floor_met": False,
            "evidence_state": "absent", "mutation_class": "insufficient",
            "hotspot_frequencies": [], "source_cohort": cohort,
            "_data_note": (f"No per-sample MAF for {indication} (neither local {maf_path} nor the "
                           f"{_PER_SAMPLE_MAF_MANIFEST} manifest/S3)."),
        }

    cohort_ids = set(maf["sample_id"].dropna())

    # Restrict to the subgroup member-set if the decorator injected one.
    member_ids = (cohort_ids & _sample_id_filter) if _sample_id_filter is not None else cohort_ids

    n = len(member_ids)
    mutated = maf[
        (maf["gene_symbol"] == target) & (maf["sample_id"].isin(member_ids))
    ]["sample_id"].nunique()
    freq = (mutated / n) if n else None

    hotspots = []
    for change in hotspot_changes:
        hf, hn = _hotspot_freq_for_samples(maf, target, member_ids, change)
        hotspots.append({
            "protein_change": change,
            "frequency": (round(hf, 4) if hf is not None else None),
            "n_samples": hn,
        })

    floor_met = n >= SUBGROUP_N_FLOOR
    return {
        "target": target,
        "indication": indication,
        "subgroup_n": n,
        "overall_mutation_frequency": (round(freq, 4) if freq is not None else None),
        "n_samples_mutated": int(mutated),
        "subgroup_n_floor_met": floor_met,
        "evidence_state": evidence_state(n, floor_met),
        "mutation_class": _mutation_class(freq),
        "hotspot_frequencies": hotspots,
        "source_cohort": cohort,
    }


def _mutation_freq_projection(stratum_id: str, rec: dict) -> dict:
    """Project a per-stratum mutation-frequency record → the card's flat record.

    The ONLY substrate-specific step in the mutation-frequency panorama; the
    fan-out + cross-stratum reduction are handled generically by build_panorama.
    """
    return {
        "stratum": stratum_id,
        "class": rec["mutation_class"],
        "evidence_state": rec["evidence_state"],
        "overall_mutation_frequency": rec["overall_mutation_frequency"],
        "n_samples_mutated": rec["n_samples_mutated"],
        "subgroup_n": rec["subgroup_n"],
        "subgroup_n_floor_met": rec["subgroup_n_floor_met"],
        "subtype_defining_data": "genomic",
        "source_cohort": rec["source_cohort"],
        "hotspot_frequencies": rec["hotspot_frequencies"],
    }


def build_mutation_frequency_panorama(
    target: str,
    indication: str,
    subgroups: list[str],
    subgroup_assignments_manifest: str,
    hotspot_changes: tuple[str, ...] = (),
    subgroup_catalog_repo: Path | str | None = None,
    maf_source: str = "tcga_mc3",
    maf_cache: Path | None = None,
) -> dict:
    """Assemble the mutation-frequency card's per_subgroup_metrics panorama.

    Thin call into the substrate-agnostic subgroup_common.panorama.build_panorama:
    supplies the mutation-frequency reader, a projection, and the frequency
    delta-reducer. The fan-out + cross-stratum summary are generic. Purely
    descriptive — emits no signals.

    `maf_source` picks the substrate: `tcga_mc3` for TCGA molecular strata,
    `genie_registry` for the GENIE-BPC LOT strata (the RWD line-of-therapy axis).
    """
    panorama = build_panorama(
        read_stratified_mutation_frequency,
        target=target,
        indication=indication,
        subgroups=subgroups,
        subgroup_assignments_manifest=subgroup_assignments_manifest,
        record_projection=_mutation_freq_projection,
        reducer=partial(delta_reducer, metric_key="overall_mutation_frequency", label="frequency"),
        subgroup_catalog_repo=subgroup_catalog_repo,
        reader_kwargs={"hotspot_changes": hotspot_changes, "maf_source": maf_source,
                       "maf_cache": maf_cache},
    )
    panorama["_data_source"] = f"{maf_source} per-sample MAF (subgroup-stratified)"
    return panorama
