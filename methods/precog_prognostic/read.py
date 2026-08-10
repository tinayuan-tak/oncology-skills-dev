"""precog_prognostic.read — library entry for the per-(gene x indication) PRECOG prognostic facet.

Reads the MATERIALIZED long per-(gene x indication) PRECOG meta-Z table and returns the
precog-prognostic-association card's summary_fields. Read grain pre-aggregated → O(1) per-(gene,
indication) slice. Unlike the cohort-context facets (stemness/DDR), PRECOG is genuinely
TARGET-DEPENDENT — the meta-Z is specific to THIS gene's expression<->survival association — so
`target` IS consumed here.

Verdict-INERT: no resolver rung. A pan-cancer meta-analytic prognostic prior that corroborates the
single-cohort expression-clinical-association card.
"""
from __future__ import annotations

import io
import os
import subprocess
from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"
_DERIVED_S3 = ("s3://onc-compbio/data-catalog/derived/"
               "precog-prognostic-meta-z-per-indication-v1/precog_prognostic_long.parquet")
_XWALK = _cli.INDICATION_TO_PRECOG


def _ensure_aws_profile() -> None:
    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)


def _load_product():
    import pandas as pd
    _ensure_aws_profile()
    try:
        raw = subprocess.run(["aws", "s3", "cp", _DERIVED_S3, "-"], capture_output=True, timeout=120).stdout
        if raw:
            return pd.read_parquet(io.BytesIO(raw))
    except Exception:
        pass
    return _cli.build_long_table()   # dev fallback (re-reads the source matrix)


def read_precog_prognostic(target: Optional[str] = None, indication: Optional[str] = None) -> dict:
    """Return the precog-prognostic-association card summary_fields for (target, indication).

    Falls back to the pan-cancer meta-Z (indication='PANCAN') as a secondary context field, but the
    PRIMARY prognostic_class is the indication-specific call. data_unavailable when the gene or the
    indication (crosswalk) is absent.
    """
    if not target:
        return {"prognostic_class": "data_unavailable",
                "_note": "target required (per-gene prognostic meta-Z)."}
    gene = target.upper()
    ind = (indication or "PANCAN").upper()
    df = _load_product()

    # gene present at all?
    g_all = df[df["gene"] == gene]
    if g_all.empty:
        return {"prognostic_class": "data_unavailable", "target": target, "indication": indication,
                "_note": f"{gene} not in the PRECOG meta-Z matrix.",
                "_source": "PRECOG (Gentles 2015 + 2026 NAR); verdict-inert prognostic facet"}

    # pan-cancer context (always available if the gene is present)
    pan = g_all[g_all["indication"] == "PANCAN"]
    pan_z = float(pan["meta_z"].iloc[0]) if not pan.empty else None
    pan_cls = str(pan["prognostic_class"].iloc[0]) if not pan.empty else "data_unavailable"

    # indication-specific (the PRIMARY call). If the requested indication is not crosswalked,
    # prognostic_class is data_unavailable but pan-cancer context is still returned.
    mapped = ind in _XWALK or ind == "PANCAN"
    sub = g_all[g_all["indication"] == ind]
    if sub.empty:
        return {
            "prognostic_class": "data_unavailable",
            "target": target, "indication": indication,
            "meta_z": None,
            "pan_cancer_meta_z": round(pan_z, 4) if pan_z is not None else None,
            "pan_cancer_prognostic_class": pan_cls,
            "precog_indication_mapped": mapped,
            "_note": (f"{indication} is not in the PRECOG crosswalk (no PRECOG cancer-type match); "
                      f"pan-cancer meta-Z reported as context." if not mapped
                      else f"{gene} has no meta-Z for {indication} in PRECOG."),
            "_source": "PRECOG (Gentles 2015 + 2026 NAR); verdict-inert prognostic facet",
        }

    row = sub.iloc[0]
    meta_z = float(row["meta_z"])
    approx = bool(row["precog_indication_approx"])
    return {
        "prognostic_class": str(row["prognostic_class"]),       # PRIMARY
        "target": target,
        "indication": indication,
        "meta_z": round(meta_z, 4),
        "meta_z_significance_cut": _cli.META_Z_SIGNIF,           # |z|>=1.96 ~ p<0.05
        "pan_cancer_meta_z": round(pan_z, 4) if pan_z is not None else None,
        "pan_cancer_prognostic_class": pan_cls,
        "precog_source_column": str(row["precog_source_column"]),
        "precog_indication_approx": approx,                     # True if a granularity/composite approximation
        "n_precog_datasets": "166 datasets / ~18k patients (pan-cancer meta-analysis)",
        "_method_version": METHOD_VERSION,
        "_source": ("PRECOG pan-cancer prognostic meta-Z (Gentles 2015 Nat Med + 2026 NAR). "
                    "POSITIVE meta-Z = high expression -> WORSE overall survival. Verdict-inert; "
                    "meta-analytic corroboration of the single-cohort expression-clinical-association."),
        "_caveat": ("meta-analytic across 166 heterogeneous datasets (platforms/cohorts vary); "
                    "UNADJUSTED univariate survival association, hypothesis-generating not a clinical claim."
                    + (" INDICATION IS AN APPROXIMATION — see precog_source_column." if approx else "")),
    }
