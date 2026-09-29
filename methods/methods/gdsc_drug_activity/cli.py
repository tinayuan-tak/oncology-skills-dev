"""gdsc_drug_activity.cli — per-gene GDSC (Sanger GDSC1+GDSC2, release 8.5) drug-activity loaders.

Orthogonal-platform sibling of depmap_prism_activity (Broad PRISM). Reads the derived per-gene
rollup `gdsc-drug-activity-per-gene-v1` (one row per GDSC putative-TARGET token) via pyarrow
predicate-pushdown on the `gene_symbol` column (filters=[("gene_symbol","=",token)] reads ~1 row
group of the gene-sorted parquet), and emits a compact activity summary for the
gdsc-drug-activity display card.

## gene_symbol is a FREE-TEXT putative-target token, NOT a clean HGNC key
GDSC's TARGET is a curated free-text putative-target annotation. Tokens include clean HGNC symbols
(EGFR, MET, ALK, BRAF), protein FAMILY tokens (PDGFR, VEGFR), complex/pathway tokens (MTORC1,
Proteasome), and placeholders. Only ~65.9% resolve to a single HGNC gene (per the product's
`.target_resolution.parquet` sidecar: resolved 178 + deprecated_remapped 73 = 251 of 381). The
reader therefore resolves a framework HGNC symbol to a native GDSC token two ways:
  1. DIRECT — the framework symbol IS a native token (the common case: EGFR/MET/ALK/BRAF).
  2. HGNC-ALIAS fallback — the sidecar's `hgnc_primary_symbol_at_resolution` == the framework
     symbol for a deprecated/alias native token (e.g. framework RPS6KA1 -> GDSC token RSK1).
A symbol that matches no native token is `no_compounds_found` — a REAL weak-negative (no GDSC
compound annotates against it), NOT a data-availability gap.

## Cell-line axis — SANGER SIDM, no crosswalk
Cell lines are Sanger SIDM ids with no DepMap-ModelID/OncotreeLineage crosswalk yet, so there is NO
per-lineage stratification here (unlike PRISM) and NO indication axis; `indication` is accepted for
the generic-dispatch contract but NOT consumed. n_cell_lines_tested counts distinct SIDM ids.

## Absence discipline (mirror of the ProCan/PRISM readers)
A symbol that resolves to no GDSC token is `no_compounds_found` (a measured weak-negative). A
transient S3/read failure PROPAGATES (never memoized) so read.py surfaces an honest
_live_read_error + gdsc_activity_class=data_unavailable — `no_compounds_found` and `data_unavailable`
are DISTINCT (measured negative vs infra gap), the key disambiguates for provenance.

## LICENSE (research-only — Sanger DepMap data-usage policy)
Internal Takeda target/biomarker/drug-discovery research permitted; NO external redistribution.
Cite Yang et al. 2013 NAR (GDSC) + Iorio et al. 2016 Cell.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for, sidecar_bucket_key_for
from methods.target_id_sidecar import ensure_aws_profile

METHOD_VERSION = "0.1.0"
DERIVED_PRODUCT_MANIFEST_ID = "gdsc-drug-activity-per-gene-v1"

# Activity-class vocabulary — mirrors the gdsc-drug-activity.card.yaml summary_fields_vocabulary.
CLASS_POTENT = "potent_activity"
CLASS_MODERATE = "moderate_activity"
CLASS_WEAK = "weak_activity"
CLASS_NO_COMPOUNDS_FOUND = "no_compounds_found"
CLASS_DATA_UNAVAILABLE = "data_unavailable"

# Potency bands keyed on min_median_ln_ic50 = the MOST-SENSITIVE drug's typical potency (natural-log
# IC50 in micromolar; lower = more potent). ln(IC50)=0 <=> IC50=1 uM; ln(IC50)=3 <=> IC50~=20 uM.
# DISPLAY-ONLY thresholds (this card is verdict-inert — they colour a class label, drive no verdict).
POTENT_MAX_LN_IC50 = 0.0  # best agent typical IC50 <= ~1 uM  -> potent_activity
MODERATE_MAX_LN_IC50 = 3.0  # best agent typical IC50 <= ~20 uM -> moderate_activity; above -> weak


@lru_cache(maxsize=1)
def _derived_bucket_key() -> tuple:
    """(bucket, key) of the derived per-gene parquet payload, resolved from the manifest."""
    return bucket_key_for(DERIVED_PRODUCT_MANIFEST_ID)


@lru_cache(maxsize=1)
def _sidecar_bucket_key() -> tuple:
    """(bucket, key) of the target-resolution sidecar, resolved from the manifest."""
    return sidecar_bucket_key_for(DERIVED_PRODUCT_MANIFEST_ID)


def _classify(min_median_ln_ic50: Optional[float]) -> str:
    """Map the most-sensitive-drug potency to the activity class. None -> weak (a token with a row but
    no numeric potency is a weak signal, not a coverage gap)."""
    if min_median_ln_ic50 is None:
        return CLASS_WEAK
    if min_median_ln_ic50 <= POTENT_MAX_LN_IC50:
        return CLASS_POTENT
    if min_median_ln_ic50 <= MODERATE_MAX_LN_IC50:
        return CLASS_MODERATE
    return CLASS_WEAK


def _nan_to_none(v):
    """NaN floats -> None (parquet writes NaN for a genuinely-absent numeric)."""
    if isinstance(v, float) and v != v:
        return None
    return v


def _absent_summary(target: str) -> dict:
    """no_compounds_found — the target resolves to no GDSC putative-target token. A measured
    weak-negative (no GDSC compound annotates against it), NOT a data-availability gap."""
    return {
        "gdsc_activity_class": CLASS_NO_COMPOUNDS_FOUND,
        "_data_note": (
            f"Target {target!r} matches no GDSC putative-target token (direct or via the "
            "HGNC-alias sidecar). No GDSC1/2 compound annotates against it — a first-in-"
            "class opportunity, NOT a data-availability gap."
        ),
        "n_drugs": 0,
        "n_cell_lines_tested": 0,
        "median_ln_ic50": None,
        "median_auc": None,
        "min_median_ln_ic50": None,
        "most_sensitive_drug_name": None,
        "datasets": None,
        "looks_like_gene_symbol": None,
        "gdsc_target_token": None,
        "resolved_via": None,
        "method_version": METHOD_VERSION,
    }


def compute_summary(
    row: Optional[dict], target: str, gdsc_target_token: Optional[str], resolved_via: Optional[str]
) -> dict:
    """Map a product row (or None) to the gdsc-drug-activity card summary shape."""
    if row is None:
        return _absent_summary(target)
    min_ln = _nan_to_none(row.get("min_median_ln_ic50"))
    return {
        "gdsc_activity_class": _classify(min_ln),
        "n_drugs": int(row.get("n_drugs") or 0),
        "n_cell_lines_tested": int(row.get("n_cell_lines_tested") or 0),
        "median_ln_ic50": _nan_to_none(row.get("median_ln_ic50")),
        "median_auc": _nan_to_none(row.get("median_auc")),
        "min_median_ln_ic50": min_ln,
        "most_sensitive_drug_name": row.get("most_sensitive_drug_name"),
        "datasets": row.get("datasets"),
        "looks_like_gene_symbol": row.get("looks_like_gene_symbol"),
        "gdsc_target_token": gdsc_target_token,
        "resolved_via": resolved_via,
        "method_version": METHOD_VERSION,
    }


def _fetch_row_from_table(tbl, token: str) -> Optional[dict]:
    """One gene_symbol row from a pushdown-filtered pyarrow Table, or None if absent."""
    if tbl.num_rows == 0:
        return None
    if tbl.num_rows > 1:
        raise RuntimeError(f"Multiple GDSC rows for {token!r}; product violated gene_symbol uniqueness")
    return {col: tbl[col][0].as_py() for col in tbl.column_names}


def _read_product_row(token: str, product_path=None) -> Optional[dict]:
    """Pushdown-read one gene_symbol token from the derived per-gene parquet. `product_path` (offline
    test seam) reads a local parquet with the same filter; None => the live S3 product (cached)."""
    import pyarrow.parquet as pq

    if product_path is not None:
        tbl = pq.read_table(str(product_path), filters=[("gene_symbol", "=", token)])
        return _fetch_row_from_table(tbl, token)
    return _read_product_row_live(token)


@lru_cache(maxsize=256)
def _read_product_row_live(token: str) -> Optional[dict]:
    """LIVE S3 pushdown, cached per token. A transient failure RAISES and is NOT cached (lru_cache
    never memoizes exceptions), so read.py surfaces an honest _live_read_error and a later call retries."""
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    ensure_aws_profile()
    bucket, key = _derived_bucket_key()
    tbl = pq.read_table(f"{bucket}/{key}", filesystem=pafs.S3FileSystem(), filters=[("gene_symbol", "=", token)])
    return _fetch_row_from_table(tbl, token)


def _resolve_alias_token(target: str, sidecar_path=None) -> Optional[str]:
    """HGNC-alias fallback: find a native GDSC token whose sidecar `hgnc_primary_symbol_at_resolution`
    equals the framework symbol (e.g. framework RPS6KA1 -> GDSC token RSK1). Returns the native token
    (deterministic min on native_row_key when several alias to the same HGNC symbol), or None."""
    import pyarrow.parquet as pq

    cols = ["native_row_key", "hgnc_primary_symbol_at_resolution"]
    if sidecar_path is not None:
        tbl = pq.read_table(
            str(sidecar_path), columns=cols, filters=[("hgnc_primary_symbol_at_resolution", "=", target)]
        )
    else:
        tbl = _read_sidecar_alias_live(target)
    if tbl.num_rows == 0:
        return None
    return min(str(v) for v in tbl.column("native_row_key").to_pylist())


@lru_cache(maxsize=256)
def _read_sidecar_alias_live(target: str):
    """LIVE sidecar pushdown on hgnc_primary_symbol_at_resolution, cached per target. RAISES (not
    cached) on a transient failure — the caller propagates it as an honest read error."""
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    ensure_aws_profile()
    bucket, key = _sidecar_bucket_key()
    return pq.read_table(
        f"{bucket}/{key}",
        filesystem=pafs.S3FileSystem(),
        columns=["native_row_key", "hgnc_primary_symbol_at_resolution"],
        filters=[("hgnc_primary_symbol_at_resolution", "=", target)],
    )


def load_and_classify(target: str, product_path=None, sidecar_path=None) -> dict:
    """Full pipeline for one target: resolve the framework HGNC symbol to a native GDSC token (DIRECT
    then HGNC-alias sidecar fallback) -> pushdown-read the token's per-gene rollup -> classify.

    product_path / sidecar_path: offline test seams (local parquet). Default None => the live S3 product.
    A symbol matching no token -> no_compounds_found (measured weak-negative). A transient read failure
    PROPAGATES (read.py -> _live_read_error + data_unavailable)."""
    sym = (target or "").strip()
    token = sym.upper()
    # 1. DIRECT — the framework symbol is itself a native GDSC token.
    row = _read_product_row(token, product_path=product_path)
    if row is not None:
        return compute_summary(row, target, gdsc_target_token=token, resolved_via="direct")
    # 2. HGNC-ALIAS fallback — a deprecated/alias native token resolves to this framework symbol.
    alias_token = _resolve_alias_token(sym, sidecar_path=sidecar_path)
    if alias_token:
        row = _read_product_row(alias_token, product_path=product_path)
        if row is not None:
            return compute_summary(row, target, gdsc_target_token=alias_token, resolved_via="hgnc_alias")
    # 3. Unmatched -> measured weak-negative.
    return _absent_summary(target)


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="GDSC per-gene drug-activity summary for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--product-path", default=None)
    ap.add_argument("--sidecar-path", default=None)
    args = ap.parse_args(argv)
    out = load_and_classify(args.target, product_path=args.product_path, sidecar_path=args.sidecar_path)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    _main()
