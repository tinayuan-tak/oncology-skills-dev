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

METHOD_VERSION = "1.2.0"  # 1.2.0 (2026-09-12): not_phosphoprotein retired -> phospho_not_detected + protein probe
DEFAULT_AWS_PROFILE = "cbg"
PHOSPHO_PRODUCT_MANIFEST = "cptac-phospho-per-site-per-cohort-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, PHOSPHO_PRODUCT_KEY = bucket_key_for(PHOSPHO_PRODUCT_MANIFEST)

# TOTAL-PROTEIN detection probe (1.2.0). Same CPTAC cohorts, UPPER-CASED cohort keys (BRCA/CCRCC/COAD/
# GBM/HNSCC/LSCC/LUAD/OV/PDAC/UCEC) vs this product's lower-cased ones — `.upper()` maps all 10 exactly.
PROTEIN_PRODUCT_MANIFEST = "cptac-protein-tumor-vs-normal-per-cohort-v1"
PROTEIN_S3_BUCKET, PROTEIN_PRODUCT_KEY = bucket_key_for(PROTEIN_PRODUCT_MANIFEST)

# indication → cptac cohort key (lower-cased; matches the product's `cohort` column). Unchanged map.
INDICATION_TO_CPTAC = {
    "BRCA": "brca",
    "KIRC": "ccrcc",
    "CCRCC": "ccrcc",
    "COADREAD": "coad",
    "COAD": "coad",
    "READ": "coad",
    "GBM": "gbm",
    "HNSC": "hnscc",
    "HNSCC": "hnscc",
    "LUSC": "lscc",
    "LSCC": "lscc",
    "LUAD": "luad",
    "OV": "ov",
    "PAAD": "pdac",
    "PDAC": "pdac",
    "UCEC": "ucec",
}

DETECTED_FRACTION_ACTIVE = 0.50  # phosphosite detected in >= this fraction of tumors → substantial
MIN_TUMORS = 20
# phospho-vs-protein: mean(site phospho log-ratio − gene total-protein log-ratio) across paired
# tumors > this → the site is phosphorylated BEYOND its abundance expectation (real stoichiometry
# signal, from the product's site_phospho_minus_protein column). Needs >= this many paired tumors.
PHOSPHO_OVER_PROTEIN_DELTA = 0.25
MIN_PAIRED_TUMORS = 20


def classify_phospho_activity(
    n_sites: int,
    max_site_detection_fraction: Optional[float],
    phospho_over_protein: Optional[bool],
    n_tumors: int,
    total_protein_detected_in_cohort: Optional[bool] = None,
) -> str:
    """Pure classifier — phospho-activity class. No I/O.

    phospho_active        — a site detected in >= DETECTED_FRACTION_ACTIVE of tumors AND phospho
                            exceeds the total-protein expectation (or protein unavailable but
                            detection is high)
    phospho_present       — sites detected at substantial fraction but not exceeding abundance
    phospho_low           — sites exist in the panel but detected in few tumors
    phospho_not_detected  — NO phosphosites for the gene in this cohort's panel, while the gene's
                            TOTAL PROTEIN *is* detected in the same cohort → a measured no-detection
    data_unavailable      — too few tumors, OR n_sites == 0 with the total protein NOT detected in the
                            cohort either → the axis is UNINFORMATIVE, not negative

    TOKEN RETIREMENT (1.2.0, 2026-09-12). `not_phosphoprotein` used to be returned for every n_sites==0
    gene, asserting a BIOLOGICAL state ("not a phosphoprotein; this axis does not apply") from what is
    really a COVERAGE FLOOR. Measured across the two products: the phospho panel covers ~4.7-6.1k genes
    per cohort vs ~7.4-11.5k for total protein, so ~48-55% of protein-detected genes in EVERY cohort
    have zero phosphosites, and ~1.7-2.3k of those per cohort DO carry sites in another CPTAC cohort
    (i.e. are demonstrated phosphoproteins). Live false calls: ALK (0 sites in all 10 cohorts — an RTK
    defined by autophosphorylation), CDK4 (0 in 9/10 despite the canonical T172 site), MET (0 in
    brca/hnscc, 8 in ccrcc), KRAS (0 in coad but 2 in ccrcc — the example the old caveat cited).

    `total_protein_detected_in_cohort=None` means the probe could not be run; it FAILS SOFT to
    phospho_not_detected rather than silently demoting the axis to data_unavailable.
    """
    if n_tumors < MIN_TUMORS:
        return "data_unavailable"
    if n_sites == 0:
        # protein NOT detected in this cohort → phosphopeptide absence is unreadable (uninformative).
        if total_protein_detected_in_cohort is False:
            return "data_unavailable"
        return "phospho_not_detected"
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
    cols = [
        "phosphosite",
        "detection_fraction",
        "mean_log_ratio",
        "n_tumors_cohort",
        "site_phospho_minus_protein",
        "n_paired_tumors",
    ]
    try:
        if product_path is not None:
            tbl = pq.read_table(product_path, filters=flt, columns=cols)
        else:
            if "AWS_PROFILE" not in os.environ:
                os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
            import pyarrow.fs as fs

            tbl = pq.read_table(
                f"{S3_BUCKET}/{PHOSPHO_PRODUCT_KEY}",
                filesystem=fs.S3FileSystem(region="us-east-1"),
                filters=flt,
                columns=cols,
            )
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
            tbl = pq.read_table(product_path, filters=[("cohort", "==", cohort)], columns=["n_tumors_cohort"])
        else:
            if "AWS_PROFILE" not in os.environ:
                os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
            import pyarrow.fs as fs

            tbl = pq.read_table(
                f"{S3_BUCKET}/{PHOSPHO_PRODUCT_KEY}",
                filesystem=fs.S3FileSystem(region="us-east-1"),
                filters=[("cohort", "==", cohort)],
                columns=["n_tumors_cohort"],
            )
        if tbl.num_rows == 0:
            return None
        return int(tbl.column("n_tumors_cohort")[0].as_py())
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        # Mirror _read_gene_sites (Stage-1): a GENUINELY missing product (NoSuchKey/404, or pyarrow
        # FileNotFoundError on a missing local/S3 object) -> None (caller distinguishes
        # not_phosphoprotein vs data_unavailable, unchanged). A transient/creds/broken-env failure is
        # NOT absence -> re-raise so the live-read seam tags _live_read_error instead of a dead axis.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise


def _protein_detected_in_cohort(gene: str, cohort: str, protein_product_path: Optional[str] = None) -> Optional[bool]:
    """Is `gene`'s TOTAL PROTEIN detected in this CPTAC cohort's MS? (1.2.0)

    True/False = probed answer; None = the probe could not be run (product genuinely absent) → the
    caller FAILS SOFT to phospho_not_detected rather than demoting the axis. Mirrors the absence
    discipline of the other readers: genuine 404/NoSuchKey/FileNotFoundError → None, a transient /
    creds / broken-env failure RE-RAISES so the live-read seam tags _live_read_error.
    """
    import pyarrow.parquet as pq

    flt = [("gene_symbol", "==", gene), ("cohort", "==", cohort.upper())]
    try:
        if protein_product_path is not None:
            tbl = pq.read_table(protein_product_path, filters=flt, columns=["gene_symbol"])
        else:
            if "AWS_PROFILE" not in os.environ:
                os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
            import pyarrow.fs as fs

            tbl = pq.read_table(
                f"{PROTEIN_S3_BUCKET}/{PROTEIN_PRODUCT_KEY}",
                filesystem=fs.S3FileSystem(region="us-east-1"),
                filters=flt,
                columns=["gene_symbol"],
            )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    return tbl.num_rows > 0


def _phosphosite_cohorts(gene: str, product_path: Optional[str] = None) -> Optional[list[str]]:
    """Which CPTAC cohorts carry >= 1 phosphosite for `gene`? (1.2.0)

    The cross-cohort evidence that separates "this cohort did not detect it" from "CPTAC never detects
    it": a gene with sites in ANOTHER cohort is a DEMONSTRATED phosphoprotein, so a zero here is a
    detection gap, not biology. None = probe unavailable (same absence discipline as above).
    """
    import pyarrow.parquet as pq

    flt = [("gene_symbol", "==", gene)]
    try:
        if product_path is not None:
            tbl = pq.read_table(product_path, filters=flt, columns=["cohort"])
        else:
            if "AWS_PROFILE" not in os.environ:
                os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
            import pyarrow.fs as fs

            tbl = pq.read_table(
                f"{S3_BUCKET}/{PHOSPHO_PRODUCT_KEY}",
                filesystem=fs.S3FileSystem(region="us-east-1"),
                filters=flt,
                columns=["cohort"],
            )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    return sorted({str(c) for c in tbl.column("cohort").to_pylist()})


def read_phospho_pathway_activity(
    target: str,
    indication: str,
    product_path: Optional[str] = None,
    protein_product_path: Optional[str] = None,
) -> dict:
    """Q8 — target phosphorylation summary from the CPTAC phospho product for a (target, indication)."""
    sym = target.upper().strip()
    base = {
        "target": target,
        "indication": indication,
        "substrate": "cptac_phosphoproteomics_bcm",
        "method_version": METHOD_VERSION,
    }

    # Resolve indication → cohort(s). An umbrella (NSCLC) expands to its LEAF cohorts (luad + lscc);
    # CPTAC has no pooled NSCLC phospho cohort. A leaf indication resolves to a single cohort.
    from methods.indication_aliases import indication_leaf_codes

    cohorts: list[str] = []
    for leaf in indication_leaf_codes(indication):
        c = INDICATION_TO_CPTAC.get(leaf.upper().strip())
        if c and c not in cohorts:
            cohorts.append(c)
    if not cohorts:
        base.update(
            {
                "phospho_activity_class": "data_unavailable",
                "_data_note": f"no CPTAC phospho cohort for indication {indication}",
            }
        )
        return base

    # _read_gene_sites returns None ONLY on GENUINE absence (NoSuchKey/404) — a transient/broken-env
    # failure re-raises and surfaces as _live_read_error. Read each leaf; report the cohort with the
    # RICHEST phospho evidence for this gene (most phosphosites, tie-break by cohort tumor count). For a
    # single-cohort indication this is the exact prior behavior.
    reads = [(c, _read_gene_sites(sym, c, product_path)) for c in cohorts]
    reads = [(c, d) for c, d in reads if d is not None]
    if not reads:
        base.update(
            {
                "phospho_activity_class": "data_unavailable",
                "_data_note": (f"phospho product genuinely absent (NoSuchKey/404) for cohort(s) {'+'.join(cohorts)}"),
            }
        )
        return base
    cohort, df = max(reads, key=lambda cd: (len(cd[1]), int(cd[1]["n_tumors_cohort"].iloc[0]) if len(cd[1]) else 0))
    base["cptac_cohort"] = cohort
    if len(cohorts) > 1:
        base["_data_note"] = (
            f"{indication.upper().strip()} umbrella → {'+'.join(cohorts)}; "
            f"reporting {cohort} (richest phospho evidence)"
        )

    # cohort tumor count: from the gene's own rows if present, else a cohort probe so a
    # no-phosphosite gene can be classified from the panel rather than as data_unavailable.
    if len(df):
        n_tumors = int(df["n_tumors_cohort"].iloc[0])
    else:
        n_tumors = _cohort_n_tumors(cohort, product_path) or 0
    base["n_tumors"] = n_tumors

    n_sites = int(len(df))
    base["n_phosphosites"] = n_sites

    # 1.2.0 DETECTION-CONTEXT probes, emitted on EVERY path so the axis is never read without them —
    #   (a) is the gene's TOTAL PROTEIN detected in this cohort? A zero-site gene whose protein is also
    #       undetected has an UNINFORMATIVE phospho axis (data_unavailable), not a negative one:
    #       phosphopeptide absence is unreadable without protein detection. This is the ALK/LUAD case
    #       (fusion-activated RTK below bulk-MS detection) that used to read "not a phosphoprotein".
    #   (b) how many CPTAC cohorts carry sites for the gene? Sites in ANOTHER cohort make it a
    #       DEMONSTRATED phosphoprotein, so a zero here is a detection gap (KRAS: 0 in coad, 2 in ccrcc).
    # Both probes FAIL SOFT (None → no demotion, no claim); neither can turn into a biology claim.
    # LOCALITY: the protein probe follows the phospho product's locality. An offline caller (product_path
    # set) that supplies no protein fixture gets None — the probe must NEVER silently reach S3 from an
    # offline read, which would make a "no-network" test do a live credentialed fetch.
    protein_detected = (
        None
        if (product_path is not None and protein_product_path is None)
        else _protein_detected_in_cohort(sym, cohort, protein_product_path)
    )
    site_cohorts = _phosphosite_cohorts(sym, product_path)
    base["total_protein_detected_in_cohort"] = protein_detected
    base["n_cohorts_with_phosphosites"] = None if site_cohorts is None else len(site_cohorts)
    base["phosphoprotein_detected_in_other_cohorts"] = (
        None if site_cohorts is None else bool([c for c in site_cohorts if c != cohort])
    )
    base["phospho_axis_uninformative_reason"] = None

    if n_sites == 0:
        cls = classify_phospho_activity(0, None, None, n_tumors, total_protein_detected_in_cohort=protein_detected)
        base["phospho_activity_class"] = cls
        if cls == "data_unavailable" and n_tumors >= MIN_TUMORS:
            base["phospho_axis_uninformative_reason"] = "total_protein_not_detected_in_cohort"
            base["_data_note"] = (
                f"{sym} has no phosphosites in the CPTAC {cohort} phospho panel AND its total protein is "
                f"not detected in the {cohort.upper()} proteome — the phospho axis is UNINFORMATIVE here "
                f"(absence of phosphopeptides is unreadable without protein detection), NOT negative"
            )
        else:
            elsewhere = base.get("phosphoprotein_detected_in_other_cohorts")
            base["_data_note"] = (
                f"{sym} has no phosphosites in the CPTAC {cohort} phospho panel (total protein "
                f"{'detected' if protein_detected else 'detection unprobed'}); this is a MEASURED "
                f"no-detection, not a claim that {sym} is unphosphorylatable"
                + (
                    f" — {sym} DOES carry phosphosites in "
                    f"{len([c for c in (site_cohorts or []) if c != cohort])} other CPTAC cohort(s), so "
                    f"this cohort's zero is a DETECTION gap"
                    if elsewhere
                    else ""
                )
            )
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
    top_site_n_paired = None  # paired tumors backing the winning site's residual (card field)
    for _, r in df_by_det.iterrows():
        resid = r.get("site_phospho_minus_protein")
        n_paired = int(r.get("n_paired_tumors") or 0)
        if resid is not None and resid == resid and n_paired >= MIN_PAIRED_TUMORS:
            top_site_resid = float(resid)
            top_site_n_paired = n_paired
            phospho_over_protein = bool(top_site_resid > PHOSPHO_OVER_PROTEIN_DELTA)
            break

    cls = classify_phospho_activity(n_sites, max_det, phospho_over_protein, n_tumors)
    top = df_by_det.head(5)
    top_sites = [
        {
            "site": str(s),
            "detection_fraction": round(float(v), 3),
            "phospho_minus_protein": (None if (pr is None or pr != pr) else round(float(pr), 3)),
        }
        for s, v, pr in zip(
            top["phosphosite"].values, top["detection_fraction"].values, top["site_phospho_minus_protein"].values
        )
    ]
    base.update(
        {
            "phospho_activity_class": cls,
            "n_phosphosites_frequent": n_sites_frequent,
            "max_site_detection_fraction": round(max_det, 4),
            "phospho_exceeds_abundance": phospho_over_protein,  # now a REAL call (or None if unpaired)
            "top_site_phospho_minus_protein": (None if top_site_resid is None else round(top_site_resid, 4)),
            "n_phospho_protein_paired": (top_site_n_paired or 0),  # card-declared; paired tumors behind the residual
            "top_phosphosites": top_sites,
            "_data_source": PHOSPHO_PRODUCT_MANIFEST,
        }
    )
    return base
