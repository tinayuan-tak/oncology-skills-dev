"""synleth_partner_lookup.read — live-mode dispatcher entry for the synthetic-lethal-
partners card.

ANNOTATION lookup (not a compute / screen): target → curated SL partners from the
published SynLethDB v3 (derived synlethdb-sl-partners-per-gene-v1). Reads the derived
parquet (S3 read-through cache), point-looks-up the gene, returns the
synthetic-lethal-partners card summary.

The card/gate use this as a veto-SUPPRESSOR input, NEVER a nominator: a curated SL
partner means a pooled `non_dependent` CRISPR read is NOT a trusted negative (the target
may be a genuine dependency in the partner-altered context — SMARCA2←SMARCA4-loss). It
does not, on its own, make the target a dependency.

`has_experimental_partner` is the load-bearing gate: an experimentally-supported SL
partner (CRISPR / RNAi / throughput screen) is a trustworthy suppressor; a
computational-only annotation is weaker (surfaced but the gate wiring requires
experimental support to suppress a veto).

Graceful degradation: derived product unreachable → data_unavailable + _live_read_error
(never raises). Gene genuinely absent from the SL table → `no_curated_sl_partner`
(a real read: this gene has no known SL partner) — distinct from data_unavailable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

METHOD_VERSION = "read-0.1.0"

S3_BUCKET = "onc-compbio"
DERIVED_KEY = ("data-catalog/derived/synlethdb-sl-partners-per-gene-v1/"
               "synlethdb_sl_partners_per_gene.parquet")
DEFAULT_AWS_PROFILE = "cbg"
CACHE_DIR = Path.home() / ".cache" / "synlethdb-sl-partners"
CACHE_PARQUET = CACHE_DIR / "synlethdb_sl_partners_per_gene.parquet"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _ensure_cached(parquet_path=None) -> Optional[Path]:
    """Return a local parquet path (test override, warm cache, or S3 download)."""
    if parquet_path is not None:
        return Path(parquet_path)
    if CACHE_PARQUET.exists():
        return CACHE_PARQUET
    _ensure_aws_profile()
    import boto3
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    boto3.client("s3").download_file(S3_BUCKET, DERIVED_KEY, str(CACHE_PARQUET))
    return CACHE_PARQUET


def _summary(row) -> dict:
    """Build the synthetic-lethal-partners card summary from a per-gene parquet row."""
    n = int(row["sl_partner_count"])
    n_exp = int(row["n_experimental_partners"])
    has_exp = bool(row["has_experimental_partner"])
    # PRIMARY categorical: experimentally-supported partner is the trustworthy tier.
    if has_exp:
        klass = "has_experimental_sl_partner"
    elif n > 0:
        klass = "has_computational_sl_partner"
    else:
        klass = "no_curated_sl_partner"
    top = row["top_partners"]
    # parquet may store list-of-dict as numpy array / list
    top_list = list(top) if top is not None else []
    return {
        "sl_partner_class": klass,
        "sl_partner_count": n,
        "n_experimental_partners": n_exp,
        "has_experimental_partner": has_exp,
        "best_evidence_tier": row["best_evidence_tier"],
        "sl_partner_symbols": list(row["sl_partner_symbols"]) if row["sl_partner_symbols"] is not None else [],
        "top_partners": [dict(p) for p in top_list],
        "method_version": METHOD_VERSION,
    }


def read_target_summary(target: str, indication: Optional[str] = None,
                        parquet_path: Optional[str] = None) -> dict:
    """SL-partner annotation for a target. Gene-level (SL pairs are gene-gene) —
    `indication` accepted for the dispatcher contract but NOT consumed."""
    try:
        path = _ensure_cached(parquet_path)
    except Exception as e:  # noqa: BLE001
        return {
            "_live_read_error": "synlethdb_partners_read_failed",
            "_remediation": (f"Could not read SL-partners derived product "
                             f"(s3://{S3_BUCKET}/{DERIVED_KEY}) for {target}: {e}"),
            "sl_partner_class": "data_unavailable",
            "sl_partner_count": 0, "has_experimental_partner": False,
            "method_version": METHOD_VERSION,
        }
    import pandas as pd
    df = pd.read_parquet(path)
    hit = df[df["gene_symbol"].astype(str).str.upper() == target.strip().upper()]
    if not len(hit):
        # a real read: this gene has no curated SL partner (NOT data_unavailable)
        return {
            "sl_partner_class": "no_curated_sl_partner",
            "sl_partner_count": 0, "n_experimental_partners": 0,
            "has_experimental_partner": False, "best_evidence_tier": None,
            "sl_partner_symbols": [], "top_partners": [],
            "method_version": METHOD_VERSION,
        }
    return _summary(hit.iloc[0])
