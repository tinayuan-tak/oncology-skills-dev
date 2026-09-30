"""depmap_surfaceome_protein_abundance.cli — DepMap Consortium Surfaceome 26Q3 PAIRED DIA-MS loaders.

Third-platform sibling of depmap_protein_abundance (Gygi TMT MS) and procan_protein_abundance
(ProCan DIA/SWATH). Reads the derived long/tidy product `depmap-surfaceome-paired-per-protein-v1`
(one row per (uniprot_base, model_id), columns surface_log2 / wholecell_log2 / enrichment_log2ratio /
proteomics_predicted_enriched / proteomics_pr_auc + per-layer filter status) via per-protein pyarrow
column-pushdown (filters=[("uniprot_base","=",accession)] reads ~1 row group), and emits the SAME
cellline-protein-abundance card summary shape as the Gygi/ProCan readers — computed here on the
SURFACE-ENRICHED abundance layer (`surface_log2`) — PLUS the genuinely-new surface-vs-wholecell
enrichment / localization rollup that is the unique value of the paired assay.

It REUSES (does not fork) the Gygi sibling's shape + classifier + symbol->UniProt path (identical to
how ProCan reuses them, so field names stay identical across platforms):
  - compute_summary / classify_protein_abundance   (identical summary shape + distribution vocab)
  - _symbol_to_uniprot_map                          (the general uniprot_hugo map — the product's
    uniprot_base is the universal UniProt accession, so it joins directly)
and methods.percentile_null for the all-gene percentile.

Documented platform differences (NOT forks of the Gygi logic):
  * the abundance layer is `surface_log2` (log2 surface-enrichment DIA-MS intensity) — the emitted
    field keeps the sibling's `*_log2_abundance_panel` NAME for cross-platform field parity
    (verdict-inert display); a cell line where the surface layer was NOT detected (surface_log2 null)
    is not counted in the abundance summary (honest detection fraction over the 64-line panel).
  * the cell-line axis is DepMap ModelID (ACH-*) but the release ships NO OncotreeLineage crosswalk in
    this product, so per-lineage stratification is unavailable (per_lineage_stats == []); lineage is a
    v2 join.
  * the product ships NO all-protein median-null sidecar, so the null is computed on-read (parity with
    ProCan): one cached 2-column scan + groupby-median over `surface_log2`. It backs allgene_percentile
    AND the panel-relative broadly_high cutoff (H3 discipline: broadly_high is decided relative to the
    all-protein panel, never the target's own spread).

NEW capability — surface-vs-wholecell enrichment rollup (the paired-assay value): per (gene, cell-line)
read `enrichment_log2ratio` (= surface_log2 - wholecell_log2, null unless BOTH layers detected), gated
by the Hu-2021 Cancer Surfaceome Atlas SVM call `proteomics_predicted_enriched` / its `proteomics_pr_auc`
confidence, then roll up across the 64 gastric/eso lines into: `median_enrichment_log2ratio`,
`fraction_lines_predicted_enriched`, `median_pr_auc`, and a `surface_localization_class`
(surface_confirmed / mixed / intracellular_contaminant / insufficient). Surfaced as summary fields
alongside the abundance set. Verdict-INERT display — the card ships `interpretation: rules_pending`.

Absence discipline (mirror of the Gygi/ProCan readers): a symbol that resolves to no accession, or an
accession absent from the surfaceome panel, is `data_unavailable` (a coverage gap, NOT a measured
negative). A transient S3/read failure PROPAGATES (never memoized) so read.py surfaces an honest
_live_read_error.
"""

from __future__ import annotations

import statistics
import threading
from functools import lru_cache
from typing import Optional

from onc_methods.catalog_query.read import bucket_key_for, load_manifest

# Reuse the Gygi sibling's summary shape + classifier + symbol->UniProt path (single source of truth).
from onc_methods.depmap_protein_abundance.cli import (  # noqa: F401
    _symbol_to_uniprot_map,
    classify_protein_abundance,
    compute_summary,
)
from onc_methods.percentile_null import DEFAULT_CUTOFFS, classify_percentile, percentile_rank
from onc_methods.target_id_sidecar import ensure_aws_profile

METHOD_VERSION = "0.1.0"
DERIVED_PRODUCT_MANIFEST_ID = "depmap-surfaceome-paired-per-protein-v1"
PROTEIN_ABUNDANCE_SOURCE = "depmap_surfaceome_dia_ms"

# The abundance layer this reader summarizes: the surface-enriched DIA-MS intensity (log2). The paired
# product also carries wholecell_log2, but the surface layer is the antigen-abundance signal the
# surface-modality-fit card asks for.
_ABUNDANCE_COL = "surface_log2"

# all-gene percentile-class cutoffs. Derive from onc_methods.percentile_null.DEFAULT_CUTOFFS (the same
# source the Gygi/ProCan siblings use) instead of hard-copying literals, so a future change to
# DEFAULT_CUTOFFS cannot silently drift this platform out of parity.
_PCT_CUTOFFS = dict(DEFAULT_CUTOFFS)

# --- surface-localization rollup thresholds (verdict-INERT display; card interpretation=rules_pending)
# The class is a DESCRIPTIVE summary of the Hu-2021 SVM enrichment call across the panel, not a gate.
_MIN_LINES_FOR_LOCALIZATION = 3  # below this the enrichment lens is too sparse to characterize
_ENRICHED_FRACTION_HI = 0.5  # >= this share of surface-detected lines called predicted-enriched
_ENRICHED_FRACTION_LO = 0.5  # < this share (with non-positive median enrichment) => contaminant-leaning


# --- shared S3FileSystem singleton (parity with the ProCan sibling) --------------------------------
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton. Both cached loaders share ONE instance, and this is
    the single place to add retry/connect-timeout/region hardening later (parity with the ProCan
    sibling). Double-checked locking so concurrent first-callers build exactly one."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs

                _S3FS = pafs.S3FileSystem()
    return _S3FS


@lru_cache(maxsize=1)
def _derived_bucket_key() -> tuple:
    """(bucket, key) of the derived long-parquet payload, resolved from the manifest (never hard-coded)."""
    return bucket_key_for(DERIVED_PRODUCT_MANIFEST_ID)


@lru_cache(maxsize=1)
def _derived_manifest() -> dict:
    return load_manifest(DERIVED_PRODUCT_MANIFEST_ID)


@lru_cache(maxsize=1)
def _panel_size() -> Optional[int]:
    """Total surfaceome cell lines (detection denominator = 64) — a release constant carried in manifest
    params (NOT recoverable from the detected-only long table)."""
    v = (_derived_manifest().get("parameters", {}) or {}).get("panel_size_n_cell_lines")
    return int(v) if v is not None else None


def resolve_accessions(target: str) -> list:
    """HGNC symbol -> [UniProt accession, ...] via the GENERAL uniprot_hugo map (reused from the Gygi
    sibling). The product's uniprot_base is the universal UniProt accession, so these join directly.
    Empty list when the symbol is not in the map (→ data_unavailable, honest)."""
    return list(_symbol_to_uniprot_map().get(target.strip().upper()) or [])


def _select_from_table(tbl, panel_size):
    """Post-read selection shared by the live + offline paths. `tbl` is a pyarrow Table of the rows for
    one uniprot_base. Deterministic isoform tie-break: pick the min uniprot_id (parity with the Gygi /
    ProCan selectors' 'first base-match' semantics). Returns
    (abundance_by_model | None, enrichment_rows, panel_size), where:
      - abundance_by_model maps model_id -> surface_log2 for lines where the surface layer was DETECTED
        (surface_log2 not null); None when no such line exists (→ caller → data_unavailable);
      - enrichment_rows is a list of (enrichment_log2ratio, proteomics_predicted_enriched,
        proteomics_pr_auc) for the chosen isoform, nulls preserved (the rollup filters per-field)."""
    if tbl.num_rows == 0:
        return None, [], panel_size  # accession not in the surfaceome panel → caller → data_unavailable
    d = tbl.to_pydict()
    uids = sorted(set(d["uniprot_id"]))
    chosen = uids[0]
    idx = [i for i, u in enumerate(d["uniprot_id"]) if u == chosen]
    abundance = {}
    enrichment_rows = []
    for i in idx:
        s = d["surface_log2"][i]
        if s is not None:
            abundance[d["model_id"][i]] = float(s)
        enrichment_rows.append(
            (
                d["enrichment_log2ratio"][i],
                d["proteomics_predicted_enriched"][i],
                d["proteomics_pr_auc"][i],
            )
        )
    return (abundance or None), enrichment_rows, panel_size


def _load_pushdown(accession: str, product_path=None):
    """Pushdown-read one protein's rows from the derived long parquet. Returns
    (abundance_by_model | None, enrichment_rows, panel_size). `product_path` (offline test seam) reads a
    local parquet with the same filter; None => the live S3 product (cached per accession)."""
    import pyarrow.parquet as pq

    if product_path is not None:
        tbl = pq.read_table(str(product_path), filters=[("uniprot_base", "=", accession)])
        return _select_from_table(tbl, _panel_size())
    return _load_pushdown_live(accession)


@lru_cache(maxsize=128)
def _load_pushdown_live(accession: str):
    """LIVE S3 pushdown, cached per accession (a single small row-group slice). A transient failure
    RAISES and is NOT cached (lru_cache never memoizes exceptions), so a later call retries."""
    import pyarrow.parquet as pq

    ensure_aws_profile()
    bucket, key = _derived_bucket_key()
    tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=[("uniprot_base", "=", accession)])
    return _select_from_table(tbl, _panel_size())


def _compute_null_from_table(path, filesystem=None) -> tuple:
    """One median per protein (uniprot_base) over the 2-column (uniprot_base, surface_log2) scan of the
    product — the all-protein surface-abundance null the product ships no sidecar for. NaN surface_log2
    (surface layer not detected in a line) is dropped so a protein with no surface detection contributes
    no null entry. Returned as a hashable tuple."""
    import pyarrow.parquet as pq

    tbl = pq.read_table(path, filesystem=filesystem, columns=["uniprot_base", _ABUNDANCE_COL])
    med = tbl.to_pandas().groupby("uniprot_base")[_ABUNDANCE_COL].median().dropna()
    return tuple(float(x) for x in med.tolist())


def _allprotein_median_null(product_path=None) -> tuple:
    """All-protein median surface-abundance null. `product_path` (offline test seam) reads a local
    parquet; None => the live S3 product (cached). Empty tuple on any live read failure → high_cutoff
    stays None (broadly_high honestly cannot fire) + percentile data_unavailable — same graceful
    degrade as the ProCan sibling."""
    if product_path is not None:
        return _compute_null_from_table(str(product_path))
    return _allprotein_median_null_live()


# SUCCESS-ONLY memo (parity with the ProCan sibling's F1 fix). The bare-except degrade below returns
# tuple() on a transient scan failure; an lru_cache would MEMOIZE that empty tuple and poison the whole
# session (allgene_percentile → data_unavailable + broadly_high high_cutoff → None for ALL targets for
# the process lifetime). So we cache ONLY a successful scan and let a failure fall through uncached, so a
# later call retries — parity with the raising primary pushdown (_load_pushdown_live), which lru_cache
# correctly never memoizes. `None` sentinel = not-yet-successfully-computed (a genuine empty product
# legitimately caches an empty tuple, distinct from the None "no success yet" state).
_ALLPROTEIN_NULL_CACHE: Optional[tuple] = None


def _reset_allprotein_null_cache() -> None:
    """Clear the success-only null memo (test seam; parity with the ProCan sibling)."""
    global _ALLPROTEIN_NULL_CACHE
    _ALLPROTEIN_NULL_CACHE = None


def _allprotein_median_null_live() -> tuple:
    global _ALLPROTEIN_NULL_CACHE
    if _ALLPROTEIN_NULL_CACHE is not None:
        return _ALLPROTEIN_NULL_CACHE
    ensure_aws_profile()
    bucket, key = _derived_bucket_key()
    try:
        result = _compute_null_from_table(f"{bucket}/{key}", filesystem=_get_s3fs())
    except Exception:  # noqa: BLE001  # absence-discipline: exempt -- the null is an OPTIONAL enhancement, not an absence signal: the per-protein pushdown (_load_pushdown_live, no broad except) runs FIRST in load_and_classify and propagates any transient/creds/broken-env failure honestly as _live_read_error; a null-read failure at that point only degrades broadly_high (unreachable) + allgene_percentile (data_unavailable), never masks a coverage gap. Mirrors the ProCan sibling. NOT memoized so a transient failure does not stick session-wide.
        return tuple()
    _ALLPROTEIN_NULL_CACHE = result
    return result


def _rollup_enrichment(enrichment_rows: list) -> dict:
    """Roll up the surface-vs-wholecell enrichment lens across the panel for one protein.

    enrichment_rows: list of (enrichment_log2ratio, proteomics_predicted_enriched, proteomics_pr_auc),
    one per surfaceome line for the chosen isoform (nulls preserved). Each field is filtered
    independently to its non-null support (a line may have an enrichment ratio but a null classifier
    call, or vice versa). Emits the paired-assay summary block:
      - n_lines_enrichment_evaluated       lines with a non-null enrichment_log2ratio (BOTH layers)
      - median_enrichment_log2ratio        median surface-vs-wholecell enrichment (log2), or None
      - fraction_lines_predicted_enriched  share of classifier-called lines called predicted-enriched
      - median_pr_auc                      median classifier PR-AUC confidence, or None
      - surface_localization_class         descriptive class (see below) — verdict-INERT

    surface_localization_class (DESCRIPTIVE — card interpretation=rules_pending, gates nothing):
      - insufficient:            fewer than _MIN_LINES_FOR_LOCALIZATION lines with an enrichment ratio
      - surface_confirmed:       median enrichment > 0 AND >= _ENRICHED_FRACTION_HI of classifier-called
                                 lines predicted-enriched (surface-localized, not a contaminant)
      - intracellular_contaminant: < _ENRICHED_FRACTION_LO predicted-enriched AND median enrichment <= 0
                                 (surface-detected but not surface-enriched — likely intracellular)
      - mixed:                   everything in between (heterogeneous surface localization)
    """
    ratios = [float(r) for (r, _e, _a) in enrichment_rows if r is not None]
    flags = [bool(e) for (_r, e, _a) in enrichment_rows if e is not None]
    aucs = [float(a) for (_r, _e, a) in enrichment_rows if a is not None]

    median_enrichment = statistics.median(ratios) if ratios else None
    fraction_enriched = (sum(flags) / len(flags)) if flags else None
    median_pr_auc = statistics.median(aucs) if aucs else None
    n_eval = len(ratios)

    if n_eval < _MIN_LINES_FOR_LOCALIZATION:
        cls = "insufficient"
    elif (
        median_enrichment is not None
        and median_enrichment > 0
        and fraction_enriched is not None
        and fraction_enriched >= _ENRICHED_FRACTION_HI
    ):
        cls = "surface_confirmed"
    elif (
        fraction_enriched is not None
        and fraction_enriched < _ENRICHED_FRACTION_LO
        and median_enrichment is not None
        and median_enrichment <= 0
    ):
        cls = "intracellular_contaminant"
    else:
        cls = "mixed"

    return {
        "n_lines_enrichment_evaluated": n_eval,
        "median_enrichment_log2ratio": median_enrichment,
        "fraction_lines_predicted_enriched": fraction_enriched,
        "median_pr_auc": median_pr_auc,
        "surface_localization_class": cls,
    }


def _empty_enrichment_rollup() -> dict:
    """The enrichment block for the data_unavailable / coverage-gap path (no measured enrichment)."""
    return {
        "n_lines_enrichment_evaluated": 0,
        "median_enrichment_log2ratio": None,
        "fraction_lines_predicted_enriched": None,
        "median_pr_auc": None,
        "surface_localization_class": "insufficient",
    }


def _pct_context() -> str:
    return f"{DERIVED_PRODUCT_MANIFEST_ID} panel-wide metric=median_surface_log2 source={PROTEIN_ABUNDANCE_SOURCE}"


def _data_unavailable_summary(target: str, panel_size, note: Optional[str] = None) -> dict:
    """The card-shaped data_unavailable summary (coverage-gap / missing-input path). Reuses the Gygi
    sibling's compute_summary None-branch (fraction_detected=0.0, never fabricated) + the surfaceome
    source marker, null-percentile placeholders, and an empty enrichment rollup. `note` (optional)
    records WHY it is unavailable."""
    summ = compute_summary(target, None, {}, n_panel=panel_size)
    summ["method_version"] = METHOD_VERSION
    summ["protein_abundance_source"] = "data_unavailable"
    summ["allgene_percentile"] = None
    summ["allgene_percentile_class"] = "data_unavailable"
    summ["allgene_percentile_context"] = _pct_context()
    summ.update(_empty_enrichment_rollup())
    if note is not None:
        summ["_data_note"] = note
    return summ


def load_and_classify(target: str, product_path=None, null_path=None) -> dict:
    """Full pipeline for one target: resolve symbol→UniProt → pushdown-read the protein's rows →
    classify the SURFACE abundance layer (reusing the Gygi sibling's compute_summary) → roll up the
    surface-vs-wholecell enrichment lens. Emits the cellline-protein-abundance card shape + the
    surfaceome platform source marker + the all-gene percentile + the enrichment block.

    product_path / null_path: offline test seams (local parquet). Default None => the live S3 product.
    Lineage is unavailable (no OncotreeLineage crosswalk in this product), so an EMPTY lineage map is
    passed → per_lineage_stats == [] (honest)."""
    panel_size = _panel_size()
    if panel_size is None:
        # panel_size_n_cell_lines (the detection denominator) is a release constant carried in the
        # manifest params — NOT recoverable from the detected-only long table. Absent it,
        # compute_summary falls back to denom=n_eval → a fabricated fraction_detected=1.0. Fail loud
        # with data_unavailable instead of minting a false full-panel detection. Inert today: the
        # manifest carries 64; this fires only if a future manifest genuinely drops the field.
        return _data_unavailable_summary(target, panel_size, note="panel_size_n_cell_lines absent from manifest params")

    abundance = None
    enrichment_rows: list = []
    for acc in resolve_accessions(target):
        abundance, enrichment_rows, panel_size = _load_pushdown(acc, product_path=product_path)
        if abundance:
            break
    if not abundance:
        return _data_unavailable_summary(target, panel_size)

    null_vec = _allprotein_median_null(product_path=(null_path if null_path is not None else product_path))
    summary = compute_summary(target, abundance, {}, n_panel=panel_size, all_protein_medians=(null_vec or None))
    summary["method_version"] = METHOD_VERSION
    summary["protein_abundance_source"] = PROTEIN_ABUNDANCE_SOURCE
    pct = percentile_rank(summary.get("median_log2_abundance_panel"), null_vec or [])
    summary["allgene_percentile"] = pct
    summary["allgene_percentile_class"] = classify_percentile(pct, _PCT_CUTOFFS)
    summary["allgene_percentile_context"] = _pct_context()
    summary.update(_rollup_enrichment(enrichment_rows))
    return summary


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="DepMap Surfaceome 26Q3 surface protein-abundance + enrichment rollup for a target."
    )
    ap.add_argument("--target", required=True)
    ap.add_argument("--product-path", default=None)
    ap.add_argument("--null-path", default=None)
    args = ap.parse_args(argv)
    out = load_and_classify(args.target, product_path=args.product_path, null_path=args.null_path)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    _main()
