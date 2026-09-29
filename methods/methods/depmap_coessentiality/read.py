"""read.py — runtime reader for the co-essentiality substrate.

Single entry point: read_coessential_partners(target, top_n, ...).
Reads the gene-sorted parquet with predicate pushdown — only the row-groups
for the queried gene are loaded (< 1 s per call on a cold parquet, < 200 ms warm).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq

from . import METHOD_VERSION

DEFAULT_AWS_PROFILE = "cbg"
MANIFEST_ID = "depmap-coessentiality-26q3-v1"
_CACHE_DIR = Path.home() / ".cache" / "framework-depmap-26q3-parquet"
_CACHED_PATH = _CACHE_DIR / "coessentiality_edges.parquet"


def _resolve_s3_uri() -> str:
    """Resolve the manifest-authoritative S3 URI at call time (not at import)."""
    from methods.catalog_query.read import s3_uri_for

    return s3_uri_for(MANIFEST_ID)


from methods.target_id_sidecar import ensure_aws_profile


def _local_path() -> Optional[Path]:
    """Return a local-cache hit, or None."""
    return _CACHED_PATH if _CACHED_PATH.exists() else None


def read_coessential_partners(
    target: str,
    top_n: int = 25,
    min_abs_r: float = 0.0,
    parquet_path: Optional[str] = None,
    aws_profile: str = DEFAULT_AWS_PROFILE,
) -> dict:
    """Return top-N co-essential partners for a gene from the pre-built substrate.

    Args:
        target:       HGNC gene symbol (e.g. "KRAS").
        top_n:        Number of partners to return (ranked by |r|, default 25).
                      Capped at what is available (the substrate stores top-100).
        min_abs_r:    Optional additional |r| floor applied at read-time.
        parquet_path: Override the default S3/cache path (local path or s3:// URI).
        aws_profile:  AWS profile for S3 reads (default: cbg).

    Returns a dict with:
        gene_symbol:      queried symbol
        partners:         list of dicts [{symbol, pearson_r, abs_rank, direction}]
        n_partners:       number of partners returned
        n_cell_lines:     DepMap 26Q3 cell lines used in the pre-build
        method_version:   MODULE_VERSION from __init__
        substrate_uri:    resolved path used
        _data_unavailable: present (True) if the substrate could not be read
    """
    ensure_aws_profile()
    local = _local_path() if not parquet_path else None
    if parquet_path:
        path = parquet_path
    elif local:
        path = str(local)
    else:
        path = _resolve_s3_uri()

    try:
        # Predicate pushdown: only row-groups covering this gene are read.
        table = pq.read_table(
            path,
            filters=[("gene_symbol", "==", target)],
            columns=["gene_symbol", "partner_symbol", "pearson_r", "abs_rank", "n_cell_lines"],
        )
    except Exception as exc:
        # honest-loud absence discipline (#822): only a GENUINE product absence (NoSuchKey/404/NoSuchBucket
        # or a missing local file) is an honest data_unavailable; a transient S3/creds/parse fault must
        # RE-RAISE so mechanism_composed's honest-loud guard surfaces it (fail-loud) rather than silently
        # masking it as a substrate gap. (A gene simply absent from the substrate is handled by the
        # len(table)==0 branch below, not this catch.) Mirrors collectri_tf_regulon/read.py:177-198.
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(exc, FileNotFoundError) or is_definitively_absent(exc)):
            raise
        return {
            "gene_symbol": target,
            "partners": [],
            "n_partners": 0,
            "_data_unavailable": True,
            "_error": str(exc),
            "method_version": METHOD_VERSION,
            "substrate_uri": path,
        }

    if len(table) == 0:
        return {
            "gene_symbol": target,
            "partners": [],
            "n_partners": 0,
            "_data_unavailable": True,
            "_reason": f"gene '{target}' not found in coessentiality substrate",
            "method_version": METHOD_VERSION,
            "substrate_uri": path,
        }

    df = table.to_pandas()

    # Optional extra |r| filter (substrate already stores >=0.2 by default)
    if min_abs_r > 0:
        df = df[df["pearson_r"].abs() >= min_abs_r]

    # Sort by abs_rank (already sorted, but honour override filter re-rank)
    df = df.sort_values("abs_rank").head(top_n)

    n_cell_lines = int(df["n_cell_lines"].iloc[0]) if len(df) else 0

    partners = [
        {
            "symbol": row.partner_symbol,
            "pearson_r": round(float(row.pearson_r), 4),
            "abs_rank": int(row.abs_rank),
            "direction": "co-essential" if row.pearson_r >= 0 else "anti-correlated",
        }
        for row in df.itertuples(index=False)
    ]

    return {
        "gene_symbol": target,
        "partners": partners,
        "n_partners": len(partners),
        "n_cell_lines": n_cell_lines,
        "method_version": METHOD_VERSION,
        "substrate_uri": path,
    }


# |r| at/above which a co-essential partner is a STRONG module member (shared complex/pathway).
# The substrate already floors at |r|>=0.2. CALIBRATED to 0.3 against real DepMap 26Q1 modules: at 0.3
# the canonical module genes resolve as coherent (KRAS 4 partners incl. TCF7L2; UBA3 12 incl. NAE1/NEDD8;
# BRAF 5; CTNNB1 9; EGFR 13), whereas 0.4 is too stringent — DepMap co-essential r peaks ~0.3-0.7 and 0.4
# spuriously reads KRAS/UBA3 as isolated. See PR-description live smoke.
_STRONG_MODULE_R = 0.3


def read_coessential_module_summary(
    target: str,
    indication: Optional[str] = None,
    parquet_path: Optional[str] = None,
    aws_profile: str = DEFAULT_AWS_PROFILE,
    strong_r: float = _STRONG_MODULE_R,
) -> dict:
    """CARD-READY co-essential-MODULE summary: is the target's dependency embedded in a COHERENT
    co-essential module (complex/pathway partners co-essential in the same cell lines), or is it an
    ISOLATED hit? A dependency sitting in a coherent module is a more credible, mechanism-anchored call
    — a verdict-INERT CONFIDENCE signal (the sibling of cross-consortium replication + omics-
    predictability), NOT a dependency call in itself.

    `indication` is accepted for the generic-dispatch reader contract (fn(target=, indication=)) but
    NOT consumed — co-essentiality is a pan-cancer target-grain property (tier: target).

    Returns a summary keyed by `coessential_module_class`:
      in_coherent_module   — >=3 strong (|r|>=strong_r) partners → embedded in a coherent module
      sparse_module        — 1-2 strong partners, or >=5 partners overall → some module context
      isolated_dependency  — no strong partner and few/no edges → not module-anchored
      data_unavailable     — substrate could not be read / gene absent
    plus n_partners / n_strong_partners / n_coessential / n_anti_correlated, the strongest partner,
    a top-5 partner vector, and n_cell_lines. Reuses read_coessential_partners (single data path)."""
    raw = read_coessential_partners(target, top_n=25, parquet_path=parquet_path, aws_profile=aws_profile)
    base = {
        "coessential_module_class": "data_unavailable",
        "n_partners": 0,
        "n_strong_partners": 0,
        "n_coessential": 0,
        "n_anti_correlated": 0,
        "strongest_partner_symbol": None,
        "strongest_partner_r": None,
        "strong_r_threshold": strong_r,
        "top_partners": [],
        "n_cell_lines": raw.get("n_cell_lines"),
        "method_version": METHOD_VERSION,
        "_data_source": MANIFEST_ID,
        "_scope_note": "pan-cancer target-grain (indication accepted-not-consumed)",
    }
    if raw.get("_data_unavailable"):
        base["_data_unavailable"] = True
        base["_reason"] = raw.get("_reason") or raw.get("_error")
        return base

    partners = raw.get("partners") or []
    strong = [p for p in partners if abs(p.get("pearson_r", 0.0)) >= strong_r]
    n_partners, n_strong = len(partners), len(strong)
    if n_strong >= 3:
        cls = "in_coherent_module"
    elif n_strong >= 1 or n_partners >= 5:
        cls = "sparse_module"
    else:
        cls = "isolated_dependency"
    strongest = partners[0] if partners else None  # partners are abs_rank-sorted (strongest first)
    base.update(
        coessential_module_class=cls,
        n_partners=n_partners,
        n_strong_partners=n_strong,
        n_coessential=sum(1 for p in partners if p.get("pearson_r", 0.0) >= 0),
        n_anti_correlated=sum(1 for p in partners if p.get("pearson_r", 0.0) < 0),
        strongest_partner_symbol=(strongest or {}).get("symbol"),
        strongest_partner_r=(strongest or {}).get("pearson_r"),
        top_partners=[
            {"symbol": p.get("symbol"), "pearson_r": p.get("pearson_r"), "direction": p.get("direction")}
            for p in partners[:5]
        ],
    )
    return base
