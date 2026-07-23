"""read_phospho_pathway_activity — target phosphorylation summary from CPTAC phospho (Q8).

Reads the cptac package's harmonized phosphoproteomics [bcm] for the indication's cohort, extracts
the target's phosphosites, and summarizes detection + (vs total protein) activation. data-safe.
Pure classifier split out for unit-testing without the cptac package / network.
"""
from __future__ import annotations

from typing import Optional

# indication → cptac cohort constructor name (mirrors the Q5 tumor arm's cohort map).
INDICATION_TO_CPTAC = {
    "BRCA": "Brca", "KIRC": "Ccrcc", "CCRCC": "Ccrcc", "COADREAD": "Coad", "COAD": "Coad",
    "READ": "Coad", "GBM": "Gbm", "HNSC": "Hnscc", "HNSCC": "Hnscc", "LUSC": "Lscc", "LSCC": "Lscc",
    "LUAD": "Luad", "OV": "Ov", "PAAD": "Pdac", "PDAC": "Pdac", "UCEC": "Ucec",
}

DETECTED_FRACTION_ACTIVE = 0.50    # phosphosite detected in >= this fraction of tumors → substantial
MIN_TUMORS = 20
# phospho-vs-protein: mean phospho z minus mean protein z; > this → phospho exceeds abundance expectation
PHOSPHO_OVER_PROTEIN_DELTA = 0.25


def classify_phospho_activity(n_sites: int, max_site_detection_fraction: Optional[float],
                              phospho_over_protein: Optional[bool], n_tumors: int) -> str:
    """Pure classifier — phospho-activity class. No I/O.

      not_phosphoprotein   — the gene has NO phosphosites in the panel (n_sites == 0)
      data_unavailable      — too few tumors (handled mostly by caller)
      phospho_active        — a site detected in >= DETECTED_FRACTION_ACTIVE of tumors AND phospho
                              exceeds the total-protein expectation (or protein unavailable but
                              detection is high)
      phospho_present       — sites detected at substantial fraction but not exceeding abundance
      phospho_low           — sites exist in the panel but detected in few tumors
    """
    if n_tumors < MIN_TUMORS:
        return "data_unavailable"
    if n_sites == 0:
        return "not_phosphoprotein"
    if max_site_detection_fraction is None:
        return "data_unavailable"
    if max_site_detection_fraction < 0.10:
        return "phospho_low"
    if max_site_detection_fraction >= DETECTED_FRACTION_ACTIVE:
        # substantial detection; "active" if phospho exceeds abundance expectation (or protein n/a)
        if phospho_over_protein is None or phospho_over_protein:
            return "phospho_active"
        return "phospho_present"
    return "phospho_present"


def _cptac_cohort(indication: str):
    """Instantiate the cptac cohort object for an indication, or None."""
    ctor = INDICATION_TO_CPTAC.get(indication.upper().strip())
    if ctor is None:
        return None, None
    import cptac
    return getattr(cptac, ctor)(), ctor.lower()


def read_phospho_pathway_activity(target: str, indication: str) -> dict:
    """Q8 — target phosphorylation summary from CPTAC phospho for a (target, indication)."""
    sym = target.upper().strip()
    base = {"target": target, "indication": indication, "substrate": "cptac_phosphoproteomics_bcm"}

    try:
        ds, cohort = _cptac_cohort(indication)
    except Exception as e:  # noqa: BLE001
        base.update({"phospho_activity_class": "data_unavailable",
                     "_live_read_error": f"cptac_load_failed:{type(e).__name__}"})
        return base
    if ds is None:
        base.update({"phospho_activity_class": "data_unavailable",
                     "_data_note": f"no CPTAC cohort for indication {indication}"})
        return base
    base["cptac_cohort"] = cohort

    import numpy as np
    import pandas as pd
    try:
        ph = ds.get_dataframe("phosphoproteomics", "bcm")
    except Exception as e:  # noqa: BLE001
        base.update({"phospho_activity_class": "data_unavailable",
                     "_live_read_error": f"phospho_read_failed:{type(e).__name__}"})
        return base

    n_tumors = int(ph.shape[0])
    base["n_tumors"] = n_tumors
    # target's phosphosite columns (gene is level 0 of the multiindex)
    genes = ph.columns.get_level_values(0)
    site_cols = [c for c, g in zip(ph.columns, genes) if g == sym]
    n_sites = len(site_cols)
    base["n_phosphosites"] = n_sites
    if n_sites == 0:
        base["phospho_activity_class"] = classify_phospho_activity(0, None, None, n_tumors)
        base["_data_note"] = f"{sym} has no phosphosites in the CPTAC {cohort} phospho panel"
        return base

    sub = ph[site_cols]
    # per-site detection fraction (non-NaN across tumors); the most-detected site drives the summary
    detection = sub.notna().mean(axis=0)
    max_det = float(detection.max())
    n_sites_frequent = int((detection >= DETECTED_FRACTION_ACTIVE).sum())

    # phospho-vs-total-protein: is the target phosphorylated BEYOND its abundance? Compare the
    # per-tumor mean phospho z-score to the per-tumor total-protein z-score.
    phospho_over_protein = None
    try:
        prot = ds.get_dataframe("proteomics", "bcm")
        pgenes = prot.columns.get_level_values(0) if hasattr(prot.columns, "get_level_values") \
            else prot.columns
        pcol = [c for c, g in zip(prot.columns, pgenes) if g == sym]
        if pcol:
            # mean phospho across the target's sites, per tumor
            ph_mean = sub.mean(axis=1)
            pr = prot[pcol[0]] if len(pcol) == 1 else prot[pcol].mean(axis=1)
            joined = pd.concat([ph_mean.rename("ph"), pr.rename("pr")], axis=1).dropna()
            if len(joined) >= MIN_TUMORS and joined["ph"].std() > 0 and joined["pr"].std() > 0:
                ph_z = (joined["ph"] - joined["ph"].mean()) / joined["ph"].std()
                pr_z = (joined["pr"] - joined["pr"].mean()) / joined["pr"].std()
                phospho_over_protein = bool((ph_z.mean() - pr_z.mean()) > PHOSPHO_OVER_PROTEIN_DELTA)
                base["phospho_minus_protein_z"] = round(float(ph_z.mean() - pr_z.mean()), 4)
                base["n_phospho_protein_paired"] = int(len(joined))
    except Exception:  # noqa: BLE001
        phospho_over_protein = None

    cls = classify_phospho_activity(n_sites, max_det, phospho_over_protein, n_tumors)
    # top sites by detection, for the card
    top = detection.sort_values(ascending=False).head(5)
    top_sites = [{"site": (idx[1] if isinstance(idx, tuple) and len(idx) > 1 else str(idx)),
                  "detection_fraction": round(float(v), 3)} for idx, v in top.items()]
    base.update({
        "phospho_activity_class": cls,
        "n_phosphosites_frequent": n_sites_frequent,
        "max_site_detection_fraction": round(max_det, 4),
        "phospho_exceeds_abundance": phospho_over_protein,
        "top_phosphosites": top_sites,
    })
    return base
