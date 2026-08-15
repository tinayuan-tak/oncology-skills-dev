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

from methods.catalog_query.read import bucket_key_for

METHOD_VERSION = "1.1.0"   # 1.1.0 (2026-08-05): real phospho-vs-protein cross-layer statistic
DEFAULT_AWS_PROFILE = "cbg"
PHOSPHO_PRODUCT_MANIFEST = "cptac-phospho-per-site-per-cohort-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, PHOSPHO_PRODUCT_KEY = bucket_key_for(PHOSPHO_PRODUCT_MANIFEST)

# indication → cptac cohort key (lower-cased; matches the product's `cohort` column). Unchanged map.
INDICATION_TO_CPTAC = {
    "BRCA": "brca", "KIRC": "ccrcc", "CCRCC": "ccrcc", "COADREAD": "coad", "COAD": "coad",
    "READ": "coad", "GBM": "gbm", "HNSC": "hnscc", "HNSCC": "hnscc", "LUSC": "lscc", "LSCC": "lscc",
    "LUAD": "luad", "OV": "ov", "PAAD": "pdac", "PDAC": "pdac", "UCEC": "ucec",
}

DETECTED_FRACTION_ACTIVE = 0.50    # phosphosite detected in >= this fraction of tumors → substantial
MIN_TUMORS = 20
# phospho-vs-protein: mean(site phospho log-ratio − gene total-protein log-ratio) across paired
# tumors > this → the site is phosphorylated BEYOND its abundance expectation (real stoichiometry
# signal, from the product's site_phospho_minus_protein column). Needs >= this many paired tumors.
PHOSPHO_OVER_PROTEIN_DELTA = 0.25
MIN_PAIRED_TUMORS = 20


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
    cols = ["phosphosite", "detection_fraction", "mean_log_ratio", "n_tumors_cohort",
            "site_phospho_minus_protein", "n_paired_tumors"]
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
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # A GENUINELY missing product (NoSuchKey/404, or pyarrow FileNotFoundError for a missing
        # local/S3 object) -> None -> caller emits data_unavailable (unchanged). A transient/creds/
        # broken-env failure is NOT absence -> re-raise so the live-read seam tags _live_read_error.
        # The caller therefore no longer double-tags _live_read_error on None (that path is now
        # genuine-absence only); the transient error is surfaced solely via this raise.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
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

    # _read_gene_sites now returns None ONLY on GENUINE absence (NoSuchKey/404) — a transient/broken-
    # env failure re-raises and is surfaced as _live_read_error by the live-read seam. So None here is
    # honest data_unavailable (unchanged verdict), NOT a masked read error — no double-handling.
    df = _read_gene_sites(sym, cohort, product_path)
    if df is None:
        base.update({"phospho_activity_class": "data_unavailable",
                     "_data_note": f"phospho product genuinely absent (NoSuchKey/404) for cohort {cohort}"})
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

    # phospho-vs-total-protein (REAL cross-layer statistic, 1.1.0). The product now carries, per site,
    # site_phospho_minus_protein = mean(site phospho log-ratio − gene total-protein log-ratio) across
    # paired tumors (positive => phosphorylated BEYOND abundance). We read the MOST-DETECTED site's
    # residual (that site drives the activity call) when it has enough paired tumors; a residual above
    # PHOSPHO_OVER_PROTEIN_DELTA means phospho exceeds the abundance expectation. None when no site has
    # a paired-tumor residual (protein unavailable for those aliquots) — classifier treats None as
    # "can't tell → active if detection is high" (unchanged behavior).
    df_by_det = df.sort_values("detection_fraction", ascending=False)
    phospho_over_protein = None
    top_site_resid = None
    for _, r in df_by_det.iterrows():
        resid = r.get("site_phospho_minus_protein")
        n_paired = int(r.get("n_paired_tumors") or 0)
        if resid is not None and resid == resid and n_paired >= MIN_PAIRED_TUMORS:
            top_site_resid = float(resid)
            phospho_over_protein = bool(top_site_resid > PHOSPHO_OVER_PROTEIN_DELTA)
            break

    cls = classify_phospho_activity(n_sites, max_det, phospho_over_protein, n_tumors)
    top = df_by_det.head(5)
    top_sites = [{"site": str(s), "detection_fraction": round(float(v), 3),
                  "phospho_minus_protein": (None if (pr is None or pr != pr) else round(float(pr), 3))}
                 for s, v, pr in zip(top["phosphosite"].values, top["detection_fraction"].values,
                                     top["site_phospho_minus_protein"].values)]
    base.update({
        "phospho_activity_class": cls,
        "n_phosphosites_frequent": n_sites_frequent,
        "max_site_detection_fraction": round(max_det, 4),
        "phospho_exceeds_abundance": phospho_over_protein,      # now a REAL call (or None if unpaired)
        "top_site_phospho_minus_protein": (None if top_site_resid is None else round(top_site_resid, 4)),
        "top_phosphosites": top_sites,
        "_data_source": PHOSPHO_PRODUCT_MANIFEST,
    })
    return base
