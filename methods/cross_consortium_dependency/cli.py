#!/usr/bin/env python3
"""cross_consortium_dependency — Broad vs Sanger CRISPR-dependency concordance (Project Score corroboration).

A verdict-INERT CORROBORATION facet for gate C: does an INDEPENDENT CRISPR consortium (Sanger Project
Score, via DepMap's ScreenGeneEffect combined Broad+Sanger Chronos) AGREE with the Broad Achilles
dependency call (CRISPRGeneEffect)? Two independent libraries + pipelines agreeing is stronger
corroboration than the framework's existing CRISPR×RNAi (both Broad-ecosystem).

Both matrices are ALREADY in the DepMap 26q1 mirror (no new source): CRISPRGeneEffect.csv (Broad Achilles
Chronos) + ScreenGeneEffect.csv (the Sanger-inclusive combined Chronos). Per target, compare the
pan-cell dependency fraction in each; classify agreement.

tier: target (pan-cancer, indication-independent). VERDICT-INERT: raises C-confidence, never a killer.
"""

from __future__ import annotations

import io
import os
import subprocess
from typing import Optional

METHOD_VERSION = "0.1.0"
_PREFIX = "s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1"
_BROAD = f"{_PREFIX}/CRISPRGeneEffect.csv"  # Broad Achilles Chronos (CSV fallback)
_SANGER = f"{_PREFIX}/ScreenGeneEffect.csv"  # Sanger-inclusive combined Chronos (Project Score; CSV fallback)
# Gene-column parquet products in depmap-26q1-parquet-v1 (column projection: ~1-2 MB over the wire vs the
# 560/685 MB CSVs). Preferred read path; the CSVs above are the graceful fallback if a product is absent.
_BROAD_PARQUET = "CRISPRGeneEffect.parquet"
_SANGER_PARQUET = "ScreenGeneEffect.parquet"

DEPENDENCY_CUT = -0.5  # Chronos <= -0.5 = dependent (the standard strong-dependency cut)
STRONG_FRAC = 0.10  # >= 10% of lines dependent = a real dependency in that consortium


def _col_for(cols, gene: str):
    for c in cols:
        if c.split(" (")[0] == gene:
            return c
    return None


def _summarize_vals(vals):
    """(frac_dependent, n_lines, median) from a gene-effect value Series. None if all-NaN/empty."""
    vals = vals.dropna()
    if vals.empty:
        return None
    import numpy as np

    return {
        "frac_dependent": round(float(np.mean(vals <= DEPENDENCY_CUT)), 4),
        "n_lines": int(len(vals)),
        "median": round(float(vals.median()), 4),
    }


def _consortium_frac(parquet_name: str, uri: str, gene: str):
    """Return (frac_dependent, n_lines, median) for the gene in one consortium's gene-effect matrix.

    Prefers the gene-COLUMN projection from the parquet product (depmap-26q1-parquet-v1; only the one
    gene's column transits the wire, ~1-2 MB, vs downloading the 560/685 MB CSV). Falls back to the
    full-object CSV read only when the parquet PRODUCT is genuinely unreachable. Output-equivalent: the
    parquet stores float32, but frac_dependent/median rounded to 4 dp match the float64 CSV (verified
    ERBB2/KRAS/TP53/BRAF/MYC on both matrices)."""
    import pandas as pd

    # fast path: gene-column projection from the parquet product
    try:
        from methods.depmap_common import parquet as _dp

        pq_df = _dp.get_matrix_column_by_model_id(parquet_name, gene)
        # None here = the gene is absent from the matrix (a real "no data" for this consortium), which is
        # the SAME answer the CSV path gives when _col_for finds no column — so return it directly.
        if pq_df is None:
            return None
        gene_col = next((c for c in pq_df.columns if c != "ModelID"), None)
        if gene_col is None:
            return None
        return _summarize_vals(pq_df[gene_col])
    except Exception as e:  # noqa: BLE001
        # Product GENUINELY absent (unregistered / NoSuchKey → FileNotFoundError or 404) → CSV fallback
        # (the intended redundancy). A transient/creds/broken-env error must NOT masquerade as
        # product-absence — re-raise it (the CSV fallback reads the same backend).
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
    # fallback: full-object CSV read (parquet product unreachable)
    os.environ.setdefault("AWS_PROFILE", "cbg")
    raw = subprocess.run(["aws", "s3", "cp", uri, "-"], capture_output=True).stdout
    if not raw:
        return None
    head = pd.read_csv(io.BytesIO(raw), nrows=0)
    col = _col_for(head.columns, gene)
    if col is None:
        return None
    df = pd.read_csv(io.BytesIO(raw), usecols=[head.columns[0], col])
    return _summarize_vals(df[col])


def read_cross_consortium_dependency(target: str, indication: Optional[str] = None) -> dict:
    """Compare Broad (Achilles) vs Sanger (Project Score) CRISPR dependency for the target.

    `indication` accepted for the dispatcher signature; NOT consumed (pan-cancer concordance).
    Returns cross_consortium_class + both consortia's dependency fractions.
    """
    if not target:
        return {"cross_consortium_class": "data_unavailable", "_note": "target required."}
    # Broad (Achilles) and Sanger (Project Score) gene-effect reads are independent; fetch them
    # CONCURRENTLY so they overlap (I/O-bound → real wall-clock win despite the GIL). Each side now
    # reads one gene's COLUMN from the parquet product (falling back to its CSV if the product is
    # absent). Output-equivalent: each returns its own (frac_dependent, n_lines, median) or None.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_broad = ex.submit(_consortium_frac, _BROAD_PARQUET, _BROAD, target)
        f_sanger = ex.submit(_consortium_frac, _SANGER_PARQUET, _SANGER, target)
        broad = f_broad.result()
        sanger = f_sanger.result()
    if broad is None and sanger is None:
        return {
            "cross_consortium_class": "data_unavailable",
            "target": target,
            "_note": f"{target} in neither Broad nor Sanger gene-effect matrix.",
        }
    if broad is None or sanger is None:
        present = "sanger_only" if broad is None else "broad_only"
        return {
            "cross_consortium_class": "single_consortium_only",
            "target": target,
            "present_in": present,
            "broad_frac_dependent": (broad or {}).get("frac_dependent"),
            "sanger_frac_dependent": (sanger or {}).get("frac_dependent"),
            "_note": "only one consortium screened this gene; no cross-consortium corroboration possible.",
        }
    b, s = broad["frac_dependent"], sanger["frac_dependent"]
    b_dep, s_dep = b >= STRONG_FRAC, s >= STRONG_FRAC
    if b_dep and s_dep:
        cls = "concordant_dependent"  # BOTH consortia agree it's a dependency → strong corroboration
    elif not b_dep and not s_dep:
        cls = "concordant_non_dependent"  # both agree not a dependency
    else:
        cls = "discordant"  # consortia disagree → interpret with caution
    return {
        "cross_consortium_class": cls,  # PRIMARY
        "target": target,
        "broad_frac_dependent": b,
        "sanger_frac_dependent": s,
        "broad_median_chronos": broad["median"],
        "sanger_median_chronos": sanger["median"],
        "broad_n_lines": broad["n_lines"],
        "sanger_n_lines": sanger["n_lines"],
        "dependency_cut": DEPENDENCY_CUT,
        "_method_version": METHOD_VERSION,
        "_source": "Broad Achilles (CRISPRGeneEffect) vs Sanger Project Score (ScreenGeneEffect), DepMap 26q1; verdict-inert cross-consortium corroboration",
    }


try:
    import click

    @click.command()
    @click.option("--target", required=True)
    @click.option("--indication", default=None)
    def main(target, indication):
        import json

        click.echo(json.dumps(read_cross_consortium_dependency(target, indication), indent=2, default=str))

    if __name__ == "__main__":
        main()
except ImportError:
    pass
