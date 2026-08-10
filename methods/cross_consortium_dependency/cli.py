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
_BROAD = f"{_PREFIX}/CRISPRGeneEffect.csv"          # Broad Achilles Chronos
_SANGER = f"{_PREFIX}/ScreenGeneEffect.csv"         # Sanger-inclusive combined Chronos (Project Score)

DEPENDENCY_CUT = -0.5      # Chronos <= -0.5 = dependent (the standard strong-dependency cut)
STRONG_FRAC = 0.10        # >= 10% of lines dependent = a real dependency in that consortium


def _col_for(cols, gene: str):
    for c in cols:
        if c.split(" (")[0] == gene:
            return c
    return None


def _consortium_frac(uri: str, gene: str):
    """Return (frac_dependent, n_lines, median) for the gene in one consortium's gene-effect matrix."""
    import pandas as pd
    os.environ.setdefault("AWS_PROFILE", "cbg")
    raw = subprocess.run(["aws", "s3", "cp", uri, "-"], capture_output=True).stdout
    if not raw:
        return None
    head = pd.read_csv(io.BytesIO(raw), nrows=0)
    col = _col_for(head.columns, gene)
    if col is None:
        return None
    df = pd.read_csv(io.BytesIO(raw), usecols=[head.columns[0], col])
    vals = df[col].dropna()
    if vals.empty:
        return None
    import numpy as np
    return {"frac_dependent": round(float(np.mean(vals <= DEPENDENCY_CUT)), 4),
            "n_lines": int(len(vals)), "median": round(float(vals.median()), 4)}


def read_cross_consortium_dependency(target: str, indication: Optional[str] = None) -> dict:
    """Compare Broad (Achilles) vs Sanger (Project Score) CRISPR dependency for the target.

    `indication` accepted for the dispatcher signature; NOT consumed (pan-cancer concordance).
    Returns cross_consortium_class + both consortia's dependency fractions.
    """
    if not target:
        return {"cross_consortium_class": "data_unavailable", "_note": "target required."}
    broad = _consortium_frac(_BROAD, target)
    sanger = _consortium_frac(_SANGER, target)
    if broad is None and sanger is None:
        return {"cross_consortium_class": "data_unavailable", "target": target,
                "_note": f"{target} in neither Broad nor Sanger gene-effect matrix."}
    if broad is None or sanger is None:
        present = "sanger_only" if broad is None else "broad_only"
        return {"cross_consortium_class": "single_consortium_only", "target": target,
                "present_in": present,
                "broad_frac_dependent": (broad or {}).get("frac_dependent"),
                "sanger_frac_dependent": (sanger or {}).get("frac_dependent"),
                "_note": "only one consortium screened this gene; no cross-consortium corroboration possible."}
    b, s = broad["frac_dependent"], sanger["frac_dependent"]
    b_dep, s_dep = b >= STRONG_FRAC, s >= STRONG_FRAC
    if b_dep and s_dep:
        cls = "concordant_dependent"          # BOTH consortia agree it's a dependency → strong corroboration
    elif not b_dep and not s_dep:
        cls = "concordant_non_dependent"      # both agree not a dependency
    else:
        cls = "discordant"                    # consortia disagree → interpret with caution
    return {
        "cross_consortium_class": cls,        # PRIMARY
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
