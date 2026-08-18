"""lookup — read-side accessor for the organoid CRISPR dependency substrate.

`build_summary(target, indication)` is the card entrypoint (generic dispatch, T11): a single-gene
predicate-PUSHDOWN read of the precomputed organoid dependency summary (sort/filter key ==
gene_symbol — the product is physically sorted on it), classified into a descriptive
`organoid_dependency_class`. The normative supportive/opposing interpretation lives in the
target-contracts interpretation-rules keyed on that class (not here).

Access discipline (the "optimize access to derived products" invariant):
  - the manifest S3 key is resolved LAZILY (not at import): a NEW product's manifest may not be
    merged when this module first imports in CI. Resolution + read failures are swallowed →
    data_unavailable, never raised into the render path.
  - filter= on gene_symbol so pyarrow prunes to a few row-groups — never a full read.
  - results cached per gene_symbol in-process (lru_cache).

Context strings name the null (organoid cohort, n≈114, GI-dominated) so a consumer can AUDIT
which cohort the dependency was measured in — the anti-pooling guard.
"""
from __future__ import annotations

import threading as _threading
from functools import lru_cache
from typing import Optional

METHOD_VERSION = "0.1.0"
MANIFEST_ID = "organoid-crispr-dependency-26q1-v1"
DEFAULT_AWS_PROFILE = "cbg"  # the onc-compbio bucket denies the default role

# Dependency-fraction bands → descriptive class. Keyed by the card's interpretation-rules.
# pan_organoid_essential mirrors DepMap's common-essential idea (low target value: essential
# everywhere, not tumour-selective); the mid bands are the interesting "is this a real, and how
# broad, an organoid dependency" signal.
PAN_ESSENTIAL_FRAC = 0.90
BROAD_FRAC = 0.50
SELECTIVE_FRAC = 0.20
RARE_FRAC = 0.05


def classify_dependency(frac_dependent: Optional[float]) -> str:
    """Descriptive organoid dependency class from the fraction of screened organoids in which the
    gene is a Chronos dependency (< -0.5). frac_dependent is the ROBUST signal (the median-effect
    percentile can sit mid-pack for a non-dependency because most genes have slightly-negative
    medians), so the class keys on it."""
    if frac_dependent is None:
        return "data_unavailable"
    if frac_dependent >= PAN_ESSENTIAL_FRAC:
        return "pan_organoid_essential"
    if frac_dependent >= BROAD_FRAC:
        return "broad_organoid_dependency"
    if frac_dependent >= SELECTIVE_FRAC:
        return "selective_organoid_dependency"
    if frac_dependent >= RARE_FRAC:
        return "rare_organoid_dependency"
    return "not_organoid_dependent"


_S3FS = None
_S3FS_LOCK = _threading.Lock()


def _build_s3fs():
    import boto3
    import pyarrow.fs as fs
    creds = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).get_credentials()
    if creds is not None:
        frozen = creds.get_frozen_credentials()
        return fs.S3FileSystem(access_key=frozen.access_key, secret_key=frozen.secret_key,
                               session_token=frozen.token, region="us-east-1")
    return fs.S3FileSystem(region="us-east-1")


def _s3fs():
    """Process-wide S3FileSystem singleton (double-checked locking) — building one re-freezes the
    cbg credentials (~0.4s), and this accessor is hit once per gene lookup."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                _S3FS = _build_s3fs()
    return _S3FS


@lru_cache(maxsize=1)
def _bucket_key() -> Optional[tuple]:
    """Lazily resolve (bucket, key) from the data-catalog manifest (single source of truth).
    Returns None if the manifest is not present yet (pre-merge) — the read then reports
    data_unavailable rather than raising at import."""
    try:
        from methods.catalog_query.read import bucket_key_for
        return bucket_key_for(MANIFEST_ID)
    except FileNotFoundError:
        # absence-discipline: exempt -- a FileNotFoundError from bucket_key_for is DEFINITIVE
        # manifest absence (the derived manifest is not merged yet, or not in this checkout) →
        # the reader honestly reports data_unavailable. Any OTHER error (yaml parse, layout
        # change) re-raises below so it is not silently masked as absence.
        return None


@lru_cache(maxsize=8192)
def _organoid_row(gene_symbol: str) -> Optional[tuple]:
    """Pushdown-read the single organoid dependency row for gene_symbol (the product's sort/filter
    key). Cached per symbol. Returns a tuple of the summary fields or None (absent / read failure)."""
    if not gene_symbol:
        return None
    bk = _bucket_key()
    if bk is None:
        return None
    bucket, key = bk
    try:
        import pyarrow.parquet as pq
        tbl = pq.read_table(
            f"{bucket}/{key}", filesystem=_s3fs(),
            filters=[("gene_symbol", "==", gene_symbol)],
            columns=["entrez_gene_id", "n_models_screened", "n_dependent", "n_strongly_dependent",
                     "frac_dependent", "frac_strongly_dependent", "mean_gene_effect",
                     "median_gene_effect", "min_gene_effect", "organoid_dependency_percentile",
                     "n_models_total", "n_genes"])
        df = tbl.to_pandas()
        if df.empty:
            return None
        r = df.iloc[0]
        return (str(r["entrez_gene_id"]), int(r["n_models_screened"]), int(r["n_dependent"]),
                int(r["n_strongly_dependent"]), float(r["frac_dependent"]),
                float(r["frac_strongly_dependent"]), float(r["mean_gene_effect"]),
                float(r["median_gene_effect"]), float(r["min_gene_effect"]),
                float(r["organoid_dependency_percentile"]), int(r["n_models_total"]),
                int(r["n_genes"]))
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # Only a GENUINELY missing object (NoSuchKey/404, or pyarrow FileNotFoundError) is data
        # absence → None (data_unavailable). A transient/creds/broken-env failure is NOT absence →
        # re-raise so it surfaces as an honest _live_read_error, never masked as "gene absent".
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise


def build_summary(target: str, indication: str = None) -> dict:
    """organoid-crispr-dependency card entrypoint. Is {target} a dependency in the DepMap organoid
    panel, and how broad? Target-grain: the organoid cohort (n≈114, GI-dominated) is small and not
    reliably splittable per-indication, so `indication` is accepted for the dispatch contract but
    NOT consumed (per-lineage organoid selectivity is a documented v2 follow-up).

    data_unavailable-safe: absent gene / unmerged manifest / S3 failure → a None-valued dict."""
    sym = (target or "").strip()
    out = {
        "target": sym,
        "method_version": METHOD_VERSION,
        "organoid_dependency_class": "data_unavailable",
        "frac_dependent": None,
        "frac_strongly_dependent": None,
        "median_gene_effect": None,
        "min_gene_effect": None,
        "n_models_screened": None,
        "organoid_dependency_percentile": None,
        "organoid_dependency_context": None,
    }
    row = _organoid_row(sym)
    if row is None:
        out["organoid_dependency_context"] = (
            f"DepMap 26Q1 organoid CRISPR panel ({MANIFEST_ID}) — target absent or product unavailable")
        out["_data_note"] = "gene absent from organoid gene-effect matrix or product not yet available"
        return out
    (entrez, n_screened, n_dep, n_strong, frac_dep, frac_strong, mean_eff,
     median_eff, min_eff, pct, n_total, _n_genes) = row
    out.update({
        "entrez_gene_id": entrez,
        "organoid_dependency_class": classify_dependency(frac_dep),
        "n_models_screened": n_screened,
        "n_models_total": n_total,
        "n_dependent": n_dep,
        "n_strongly_dependent": n_strong,
        "frac_dependent": round(frac_dep, 4),
        "frac_strongly_dependent": round(frac_strong, 4),
        "mean_gene_effect": round(mean_eff, 4),
        "median_gene_effect": round(median_eff, 4),
        "min_gene_effect": round(min_eff, 4),
        "organoid_dependency_percentile": round(pct, 2),
        "organoid_dependency_context": (
            f"DepMap 26Q1 organoid CRISPR panel ({MANIFEST_ID}; n={n_screened}/{n_total} organoid "
            f"models screened; GI-dominated cohort). Chronos gene-effect < -0.5 = dependent."),
    })
    return out
