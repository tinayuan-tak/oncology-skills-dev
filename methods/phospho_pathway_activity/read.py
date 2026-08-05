"""read_phospho_pathway_activity — target phosphorylation summary from CPTAC phospho (Q8).

Reads the gene-sorted CPTAC phospho product (cptac-phospho-per-site-per-cohort-v1) for the
indication's cohort, extracts the target's phosphosites, and summarizes detection. data-safe.
Pure classifier split out for unit-testing without S3/network.

SOURCING (2026-08-05): this method previously imported the LIVE `cptac` pip package and called
`getattr(cptac, Cohort)()`, which downloaded CPTAC from a remote index at read time — against the
framework's read-mirrored-S3 convention, and it degraded to data_unavailable whenever the package
was absent. It now reads the catalogued derived product
`cptac-phospho-per-site-per-cohort-v1/cptac_phospho_per_site.parquet` by predicate pushdown on
gene_symbol (deterministic, no runtime download). The product is built by
data-catalog/scripts/derive_cptac_phospho.py from the mirrored cptac-pdc-snapshot-2026-07-01.
The emitted-field contract is UNCHANGED.
"""
from __future__ import annotations

import os
from typing import Optional

METHOD_VERSION = "1.0.0"
DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
PHOSPHO_PRODUCT_MANIFEST = "cptac-phospho-per-site-per-cohort-v1"
PHOSPHO_PRODUCT_KEY = ("data-catalog/derived/cptac-phospho-per-site-per-cohort-v1/"
                       "cptac_phospho_per_site.parquet")

# indication → cptac cohort key (lower-cased; matches the product's `cohort` column). Unchanged map.
INDICATION_TO_CPTAC = {
    "BRCA": "brca", "KIRC": "ccrcc", "CCRCC": "ccrcc", "COADREAD": "coad", "COAD": "coad",
    "READ": "coad", "GBM": "gbm", "HNSC": "hnscc", "HNSCC": "hnscc", "LUSC": "lscc", "LSCC": "lscc",
    "LUAD": "luad", "OV": "ov", "PAAD": "pdac", "PDAC": "pdac", "UCEC": "ucec",
}

DETECTED_FRACTION_ACTIVE = 0.50    # phosphosite detected in >= this fraction of tumors → substantial
MIN_TUMORS = 20


def classify_phospho_activity(n_sites: int, max_site_detection_fraction: Optional[float],
                              phospho_over_protein: Optional[bool], n_tumors: int) -> str:
    """Pure classifier — phospho-activity class. No I/O. (Unchanged contract.)

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
        if phospho_over_protein is None or phospho_over_protein:
            return "phospho_active"
        return "phospho_present"
    return "phospho_present"


def _read_gene_sites(gene: str, cohort: str, product_path: Optional[str] = None):
    """Pushdown-read the product for one (gene, cohort). Returns a DataFrame with columns
    phosphosite, detection_fraction, mean_log_ratio, n_tumors_cohort — or None if unreadable."""
    import pyarrow.parquet as pq
    flt = [("gene_symbol", "==", gene), ("cohort", "==", cohort)]
    cols = ["phosphosite", "detection_fraction", "mean_log_ratio", "n_tumors_cohort"]
    try:
        if product_path is not None:
            tbl = pq.read_table(product_path, filters=flt, columns=cols)
        else:
            if "AWS_PROFILE" not in os.environ:
                os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
            import pyarrow.fs as fs
            tbl = pq.read_table(f"{S3_BUCKET}/{PHOSPHO_PRODUCT_KEY}",
                                filesystem=fs.S3FileSystem(region="us-east-1"),
                                filters=flt, columns=cols)
    except Exception:  # noqa: BLE001 — product unreadable → caller emits data_unavailable
        return None
    return tbl.to_pandas()


def _cohort_n_tumors(cohort: str, product_path: Optional[str] = None) -> Optional[int]:
    """The cohort's tumor count (constant across the cohort's rows). Lets a gene with NO sites be
    distinguished from a cohort that isn't in the product at all (not_phosphoprotein vs unavailable)."""
    import pyarrow.parquet as pq
    try:
        if product_path is not None:
            tbl = pq.read_table(product_path, filters=[("cohort", "==", cohort)],
                                columns=["n_tumors_cohort"])
        else:
            if "AWS_PROFILE" not in os.environ:
                os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
            import pyarrow.fs as fs
            tbl = pq.read_table(f"{S3_BUCKET}/{PHOSPHO_PRODUCT_KEY}",
                                filesystem=fs.S3FileSystem(region="us-east-1"),
                                filters=[("cohort", "==", cohort)], columns=["n_tumors_cohort"])
        if tbl.num_rows == 0:
            return None
        return int(tbl.column("n_tumors_cohort")[0].as_py())
    except Exception:  # noqa: BLE001
        return None


def read_phospho_pathway_activity(target: str, indication: str,
                                  product_path: Optional[str] = None) -> dict:
    """Q8 — target phosphorylation summary from the CPTAC phospho product for a (target, indication)."""
    sym = target.upper().strip()
    base = {"target": target, "indication": indication, "substrate": "cptac_phosphoproteomics_bcm",
            "method_version": METHOD_VERSION}

    cohort = INDICATION_TO_CPTAC.get(indication.upper().strip())
    if cohort is None:
        base.update({"phospho_activity_class": "data_unavailable",
                     "_data_note": f"no CPTAC phospho cohort for indication {indication}"})
        return base
    base["cptac_cohort"] = cohort

    df = _read_gene_sites(sym, cohort, product_path)
    if df is None:
        base.update({"phospho_activity_class": "data_unavailable",
                     "_live_read_error": "phospho_product_read_failed"})
        return base

    # cohort tumor count: from the gene's own rows if present, else a cohort probe so a
    # no-phosphosite gene is classified not_phosphoprotein rather than data_unavailable.
    if len(df):
        n_tumors = int(df["n_tumors_cohort"].iloc[0])
    else:
        n_tumors = _cohort_n_tumors(cohort, product_path) or 0
    base["n_tumors"] = n_tumors

    n_sites = int(len(df))
    base["n_phosphosites"] = n_sites
    if n_sites == 0:
        base["phospho_activity_class"] = classify_phospho_activity(0, None, None, n_tumors)
        base["_data_note"] = f"{sym} has no phosphosites in the CPTAC {cohort} phospho panel"
        return base

    det = df["detection_fraction"].astype(float)
    max_det = float(det.max())
    n_sites_frequent = int((det >= DETECTED_FRACTION_ACTIVE).sum())

    # phospho-vs-total-protein: the prior implementation compared per-tumor z-means, but that
    # statistic was degenerate (the mean of a z-scored vector is 0 by construction, so it never
    # fired — phospho_exceeds_abundance was effectively always False/None). v1 of the product
    # carries per-site detection + mean_log_ratio, not per-tumor vectors, so we report
    # phospho_exceeds_abundance = None pending a corrected cross-layer statistic (a real
    # phospho-vs-protein comparison belongs in a future join with the cptac-protein product).
    phospho_over_protein = None

    cls = classify_phospho_activity(n_sites, max_det, phospho_over_protein, n_tumors)
    top = df.sort_values("detection_fraction", ascending=False).head(5)
    top_sites = [{"site": str(s), "detection_fraction": round(float(v), 3)}
                 for s, v in zip(top["phosphosite"].values, top["detection_fraction"].values)]
    base.update({
        "phospho_activity_class": cls,
        "n_phosphosites_frequent": n_sites_frequent,
        "max_site_detection_fraction": round(max_det, 4),
        "phospho_exceeds_abundance": phospho_over_protein,
        "top_phosphosites": top_sites,
        "_data_source": PHOSPHO_PRODUCT_MANIFEST,
    })
    return base
