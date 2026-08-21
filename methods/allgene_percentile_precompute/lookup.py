"""lookup — read-side accessors for the two all-gene-rank precompute products.

The producer CLIs (build_tumor_rank / build_depmap_rank) emit tiny gene-sorted
parquets so a card reader can answer "where does this target's tumor / panel median
sit among ALL genes in the same context" WITHOUT scanning the multi-GB source
matrices at render time. These accessors do exactly one thing: a single-gene
predicate-PUSHDOWN read of the precomputed `allgene_percentile` (the sort/filter
key == the read key — the products are physically sorted on it), then bin it with
the shared percentile_null.classify_percentile helper.

Access discipline (the "optimize access to derived products" invariant):
  - filter= on the product's primary_filter_column (ensembl_gene_id for tumor,
    gene_symbol for depmap) so pyarrow prunes to a few row-groups — never a full read.
  - project only the columns needed.
  - data_unavailable-safe: any S3/parse/absent-gene failure returns a None-percentile
    dict, never raises into the render path.
  - results cached per (product, key) in-process (lru_cache) — a dashboard scoring
    many genes in one indication re-reads the same few row-groups otherwise.

Context strings are emitted so a consumer can AUDIT which cohort the null was drawn
from (the anti-pooling guard): a percentile is meaningless without naming its null.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional, Sequence

# Import the shared classifier + cutoffs (Phase 1A helper, on main). Fall back to a
# local copy of the cutoffs if the package layout differs, so this module never hard-
# fails an import at render time.
try:
    from methods.percentile_null import classify_percentile, DEFAULT_CUTOFFS
except Exception:  # noqa: BLE001 — keep the accessor importable even if the helper moves
    DEFAULT_CUTOFFS = {"top_1pct": 99.0, "top_decile": 90.0, "bottom_decile": 10.0}

    def classify_percentile(pct, cutoffs=None):  # type: ignore[no-redef]
        if pct is None:
            return "data_unavailable"
        c = {**DEFAULT_CUTOFFS, **(cutoffs or {})}
        if pct >= c["top_1pct"]:
            return "top_1pct"
        if pct >= c["top_decile"]:
            return "top_decile"
        if pct <= c["bottom_decile"]:
            return "bottom_decile"
        return "mid"

DEFAULT_AWS_PROFILE = "cbg"
from methods.catalog_query.read import bucket_key_for

TUMOR_RANK_MANIFEST_ID = "allgene-tumor-rank-v1"
DEPMAP_RANK_MANIFEST_ID = "allgene-depmap-rank-26q1-v1"
# bucket + keys resolved from the data-catalog manifests (single source of truth).
S3_BUCKET, TUMOR_RANK_KEY = bucket_key_for(TUMOR_RANK_MANIFEST_ID)
_, DEPMAP_RANK_KEY = bucket_key_for(DEPMAP_RANK_MANIFEST_ID)


import threading as _threading

_S3FS = None
_S3FS_LOCK = _threading.Lock()


class _RankReadError(Exception):
    """The rank precompute product could not be READ (S3/auth/parse). Distinct from a gene being
    genuinely ABSENT from the product — so a transient infra failure is never silently reported as
    'target absent' (which reads downstream as 'not measured'). See the CEACAM5/COADREAD stale-run
    diagnosis: a failed rank read had masqueraded as absence."""


def _build_s3fs():
    """Build a pyarrow S3FileSystem bound to the cbg profile (the bucket denies the default
    role — see feedback_compose_dashboard_aws_profile). Import-local so a non-S3 unit
    test never needs boto3/pyarrow at module import."""
    import pyarrow.fs as fs
    import boto3
    creds = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).get_credentials()
    if creds is not None:
        frozen = creds.get_frozen_credentials()
        return fs.S3FileSystem(access_key=frozen.access_key, secret_key=frozen.secret_key,
                               session_token=frozen.token, region="us-east-1")
    return fs.S3FileSystem(region="us-east-1")


def _s3fs():
    """Process-wide S3FileSystem singleton. Building one is ~0.4s — dominated by the boto3
    credential fetch (get_frozen_credentials) — and this accessor is hit once per gene lookup:
    control_position_cellline alone resolves the target + ~18 curated control genes, so a
    per-call rebuild spent ~4s of a cold run re-freezing the SAME credentials. The frozen
    credentials are a process-lifetime snapshot (framework runs are short CLI invocations), and
    pyarrow's S3FileSystem is thread-safe for reads (the parallel card-read path since skills
    PR #515). Double-checked locking so concurrent first-callers build one."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                _S3FS = _build_s3fs()
    return _S3FS


_DATASETS: dict = {}
_DATASET_LOCK = _threading.Lock()


def _rank_dataset(key: str):
    """Process-wide pyarrow Dataset singleton per rank-parquet key. `pq.read_table(path, filters=)`
    builds a fresh Dataset — re-reading the parquet FOOTER from S3 — on EVERY call, and the rank
    parquets are read once per gene (control_position resolves the target + ~18 curated control
    genes → ~19 reads/card, ×2 heavy cards). Reusing one Dataset object reads the footer once, then
    each pushdown query is a `.to_table(filter=)` against it: measured 18 reads 4.4s → 0.9s. The
    parquet is immutable within the process; Datasets are thread-safe for reads (parallel card path).
    Double-checked locking."""
    ds = _DATASETS.get(key)
    if ds is None:
        with _DATASET_LOCK:
            ds = _DATASETS.get(key)
            if ds is None:
                import pyarrow.dataset as pads
                ds = pads.dataset(f"{S3_BUCKET}/{key}", filesystem=_s3fs(), format="parquet")
                _DATASETS[key] = ds
    return ds


@lru_cache(maxsize=4096)
def _tumor_rows(ensembl_ids: tuple, source: str) -> tuple:
    """Pushdown-read every (source, group) row for the given ensembl id(s). Cached per
    (ids, source). Returns a tuple of (group, allgene_percentile, allgene_rank,
    n_genes_in_group, median) — hashable so it can live in the lru_cache."""
    if not ensembl_ids:
        return ()
    try:
        import pyarrow.compute as pc
        # Same predicate as the former read_table DNF filters, against a reused Dataset (footer read
        # once) — see _rank_dataset. Byte-identical rows/columns to the prior pq.read_table path.
        expr = pc.field("ensembl_gene_id").isin(list(ensembl_ids)) & (pc.field("source") == source)
        tbl = _rank_dataset(TUMOR_RANK_KEY).to_table(
            filter=expr,
            columns=["group", "allgene_percentile", "allgene_rank", "n_genes_in_group", "median"])
        df = tbl.to_pandas()
    except Exception as e:  # noqa: BLE001 — a READ failure is a typed error, NOT silent absence
        raise _RankReadError(str(e)) from e
    # An empty frame here means the gene(s) are genuinely absent from the product (→ () is correct);
    # a read/auth/parse failure raised above instead, so the caller can tell the two apart.
    return tuple((str(r.group), float(r.allgene_percentile), int(r.allgene_rank),
                  int(r.n_genes_in_group), float(r.median))
                 for r in df.itertuples(index=False))


def tumor_allgene_percentile(ensembl_ids: Sequence[str], studies: Sequence[str],
                             cutoffs: Optional[dict] = None,
                             source: str = "tcga_tumor") -> dict:
    """All-gene percentile of the target's tumor MEDIAN, averaged over the indication's
    TCGA studies (biologically-matched — COADREAD → COAD+READ), from allgene-tumor-rank-v1.

    Returns a data_unavailable-safe dict:
      allgene_percentile        float|None  — mean per-study percentile of the median
      allgene_percentile_class  str         — top_1pct / top_decile / mid / bottom_decile / data_unavailable
      allgene_percentile_context str        — the exact source + studies the null was drawn from (audit)
      allgene_percentile_by_study {study: pct}  — per-study breakdown (multi-study transparency)
    """
    out = {"allgene_percentile": None, "allgene_percentile_class": "data_unavailable",
           "allgene_percentile_context": None, "allgene_percentile_by_study": {}}
    ids = tuple(sorted({str(e) for e in (ensembl_ids or []) if e}))
    want = {str(s).upper().strip() for s in (studies or [])}
    if not ids or not want:
        return out
    try:
        rows = _tumor_rows(ids, source)
    except _RankReadError as e:
        out["allgene_percentile_context"] = (
            f"{source}:{','.join(sorted(want))} (allgene-tumor-rank-v1) — rank read failed: {e}")
        return out
    by_study = {g: pct for (g, pct, _rank, _n, _med) in rows if g.upper() in want}
    if not by_study:
        out["allgene_percentile_context"] = (
            f"{source}:{','.join(sorted(want))} (allgene-tumor-rank-v1) — target absent")
        return out
    mean_pct = sum(by_study.values()) / len(by_study)
    out["allgene_percentile"] = mean_pct
    out["allgene_percentile_class"] = classify_percentile(mean_pct, cutoffs)
    out["allgene_percentile_by_study"] = {k: round(v, 2) for k, v in sorted(by_study.items())}
    out["allgene_percentile_context"] = (
        f"{source}:{','.join(sorted(by_study))} all-gene median rank "
        f"(allgene-tumor-rank-v1; mean of {len(by_study)} study null(s))")
    return out


@lru_cache(maxsize=8192)
def _depmap_row(gene_symbol: str) -> Optional[tuple]:
    """Pushdown-read the single panel-median rank row for a gene_symbol (the product's
    sort/filter key). Cached per symbol. Returns (allgene_percentile, allgene_rank,
    n_genes, panel_median_log2tpm) or None."""
    if not gene_symbol:
        return None
    try:
        import pyarrow.compute as pc
        # Reused Dataset (footer read once) + pushdown — byte-identical to the prior read_table filter.
        tbl = _rank_dataset(DEPMAP_RANK_KEY).to_table(
            filter=pc.field("gene_symbol") == gene_symbol,
            columns=["allgene_percentile", "allgene_rank", "n_genes", "panel_median_log2tpm"])
        df = tbl.to_pandas()
    except Exception as e:  # noqa: BLE001 — a READ failure is a typed error, NOT silent absence
        raise _RankReadError(str(e)) from e
    if df.empty:            # genuinely absent from the product (→ None is correct)
        return None
    r = df.iloc[0]
    return (float(r["allgene_percentile"]), int(r["allgene_rank"]),
            int(r["n_genes"]), float(r["panel_median_log2tpm"]))


def depmap_allgene_percentile(gene_symbol: str, cutoffs: Optional[dict] = None) -> dict:
    """All-gene percentile of the target's DepMap panel MEDIAN log2(TPM+1) among all
    ~19k protein-coding genes in the panel, from allgene-depmap-rank-26q1-v1.

    Returns a data_unavailable-safe dict (same shape as the tumor accessor, no per-study
    breakdown — the DepMap null is a single pan-cancer panel)."""
    out = {"allgene_percentile": None, "allgene_percentile_class": "data_unavailable",
           "allgene_percentile_context": None}
    sym = (gene_symbol or "").strip()
    try:
        row = _depmap_row(sym)
    except _RankReadError as e:
        out["allgene_percentile_context"] = (
            f"DepMap 26q1 panel (allgene-depmap-rank-26q1-v1) — rank read failed: {e}")
        return out
    if row is None:
        out["allgene_percentile_context"] = (
            "DepMap 26q1 panel (allgene-depmap-rank-26q1-v1) — target absent")
        return out
    pct, rank, n_genes, _median = row
    out["allgene_percentile"] = pct
    out["allgene_percentile_class"] = classify_percentile(pct, cutoffs)
    out["allgene_percentile_context"] = (
        f"DepMap 26q1 pan-cancer panel all-gene median rank "
        f"(allgene-depmap-rank-26q1-v1; rank {rank}/{n_genes})")
    return out
