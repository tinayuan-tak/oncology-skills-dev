"""tphp_tumor_vs_normal_protein.read — TPHP tumor-vs-adjacent-normal PROTEIN DEG reader.

Consumer: the `tumor-vs-normal-protein-abundance-tphp` evidence card (tumor-selectivity), a
VERDICT-INERT RNA->PROTEIN corroboration facet PARALLEL to `tumor-protein-abundance-cptac`. Emits
per-(target, cohort) protein-level tumor-vs-normal differential statistics from the TPHP body+cancer
DIA-MS proteome (Xu et al., Nature 2026; open PRIDE PXD063370), across 22 carcinoma cohorts — several
outside CPTAC coverage (gallbladder, laryngeal, GIST, testis, fallopian-tube, thymoma, ...).

DISTINCT from methods/tphp_normal_protein: that reader is the NORMAL-tissue protein-abundance
liability (a verdict-BEARING normal-breadth veto arm) over a DIFFERENT product
(normal-tissue-protein-abundance-per-gene-v1, sample_context=normal). THIS reader is the TUMOR-context
tumor-vs-adjacent-normal protein corroboration facet, verdict-INERT (fires no rule / no clamp).

Field-name contract — CPTAC-ALIGNED. The emitted keys (protein_expression_class / protein_effect_size
/ protein_bh_q_value / protein_median_log2_{tumor,normal} / n_{tumor,normal}_samples) mirror
methods/cptac_protein_deg/read.py so the tumor-selectivity run.py `_rna_protein_tvn_concordance`
projection consumes this card UNCHANGED — the same derived read it already runs over the CPTAC card
summary (protein_effect_size + protein_bh_q_value → rna_protein_concordant / _discordant /
protein_not_significant / protein_unmeasured).

Substrate: the derived per-cohort product `tphp-tumor-vs-normal-protein-per-cohort-v1` — gene_symbol-
sorted (row_group_size 20000) so a per-gene predicate-pushdown read STREAMS the gene's few row-groups
off S3 (pyarrow S3FileSystem, filters=[("gene_symbol","=",symbol)]) instead of downloading the whole
product. Cohort is a FREE-TEXT carcinoma name (e.g. "Colon carcinoma"), NOT an OncoTree code — the
INDICATION_TO_TPHP_COHORT map resolves an OncoTree/TCGA indication code to the matching TPHP cohort.

Absence discipline (mirrors cptac_protein_deg + tphp_normal_protein): a GENUINE product-object absence
(NoSuchKey/404 / FileNotFoundError) or a gene simply absent from the product → honest
`data_unavailable`. A transient / credential / broken-env error is RE-RAISED (never masked as an empty
protein footprint) so the live-read seam surfaces `_live_read_error` instead of a silent dead facet.
"""
from __future__ import annotations

import math
import threading
from typing import Optional

from methods.catalog_query.read import bucket_key_for

DERIVED_MANIFEST_ID = "tphp-tumor-vs-normal-protein-per-cohort-v1"
METHOD_VERSION = "0.1.0"

# The product's tumor-vs-normal comparison is an UNPAIRED Welch two-sample t-test on the detected log2
# MaxLFQ values, BH-adjusted within cohort (see the derived manifest transformation). A single constant
# (the product has no per-row test flag) — surfaced so a consumer can distinguish it from CPTAC's
# MSstatsTMT limma-moderated t (the two facets use different estimators by design).
STAT_TEST = "welch_unpaired_tumor_vs_adjacent_normal"

# ── Indication (OncoTree / TCGA code) → TPHP cohort (FREE-TEXT carcinoma name) ─────────────────────
# TPHP cohorts are free-text SDRF carcinoma types, NOT OncoTree codes. This map resolves the OncoTree/
# TCGA indication code the pipeline passes as context.indication to the matching cohort STRING (values
# are EXACT-verbatim from the product's `cohort` column — enumerated from S3 2026-08-25). Only
# UNAMBIGUOUS 1:1 codes are mapped; an ambiguous or absent code returns data_unavailable rather than
# leak a different cohort's contrast (see read_target_summary).
#
# DELIBERATELY UNMAPPED (honest data_unavailable, no cross-indication leak):
#   * the 3 breast SUBTYPE cohorts (Luminal A / Luminal B HER2- / TNBC): the product has no whole-cohort
#     "Breast carcinoma", so a whole-cohort BRCA query has no unambiguous single cohort (mapping BRCA to
#     one subtype would misrepresent the aggregate). CPTAC (tumor-protein-abundance-cptac) covers BRCA.
#   * Tongue carcinoma + Laryngocarcinoma: the pipeline passes HNSC for head&neck, which maps to TWO
#     TPHP cohorts (ambiguous) → unmapped.
#   * Fallopian tube carcinoma: ambiguous vs ovarian (the product dropped ovarian for low normal-n) → unmapped.
# The unmapped cohorts stay reachable via the no-indication (target-only / pan-cancer) best-effect path.
INDICATION_TO_TPHP_COHORT = {
    # colorectal — mirrors the CPTAC reader's COADREAD→COAD (colon is the dominant COADREAD site)
    "COAD": "Colon carcinoma",
    "COADREAD": "Colon carcinoma",
    "READ": "Rectum carcinoma",
    # upper GI
    "STAD": "Gastric carcinoma",
    "ESCA": "Esophageal carcinoma",
    # pancreas
    "PAAD": "Pancreas carcinoma",
    "PDAC": "Pancreas carcinoma",
    # hepatobiliary
    "LIHC": "Hepatocellular carcinoma",
    "HCC": "Hepatocellular carcinoma",
    "GBC": "Gallbladder carcinoma",
    "GBAD": "Gallbladder carcinoma",
    # GI stromal
    "GIST": "Gastrointestinal stromal tumors",
    # thoracic — TPHP does NOT split lung histology (one "Lung carcinoma" cohort)
    "LUAD": "Lung carcinoma",
    "LUSC": "Lung carcinoma",
    "LSCC": "Lung carcinoma",
    "NSCLC": "Lung carcinoma",
    # renal — TPHP generic "Renal carcinoma" (no ccRCC/pRCC histology split)
    "KIRC": "Renal carcinoma",
    "CCRCC": "Renal carcinoma",
    "KIRP": "Renal carcinoma",
    "KICH": "Renal carcinoma",
    "RCC": "Renal carcinoma",
    # CNS
    "GBM": "Glioblastoma",
    # gynecologic
    "CESC": "Cervical carcinoma",
    "UCEC": "Endometrial carcinoma",
    # thymic
    "THYM": "Thymoma and thymic carcinoma",
    # germ-cell / testis
    "TGCT": "Testis carcinoma",
    # lymphoma
    "DLBC": "Diffused large B-cell carcinoma",
    "DLBCL": "Diffused large B-cell carcinoma",
}


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


# ── streamed pushdown read (pyarrow S3FileSystem; no whole-file download) ──────────────────────────
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1, the onc-compbio bucket).
    Built once and shared (safe for concurrent reads — the parallel card-read pool relies on that).
    Mirrors methods/tphp_normal_protein/read.py::_get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs
                _S3FS = pafs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_rows_from_derived(gene: str, product_path=None) -> list[dict]:
    """Streamed per-gene pushdown read of ALL cohort rows for one gene from the derived product.

    Returns the list of per-cohort row dicts (may be empty when the gene is absent). `product_path`
    (offline test seam): a local parquet bypasses S3. Raises on transient/creds/broken-env failure
    (NOT swallowed — the caller's boundary classifies a genuine 404/absence into data_unavailable)."""
    import pyarrow.parquet as pq
    filters = [("gene_symbol", "=", gene)]
    if product_path is not None:
        tbl = pq.read_table(str(product_path), filters=filters)
    else:
        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=filters)
    return tbl.to_pylist()


def _row_to_summary(row: dict, matched_cohort: str) -> dict:
    """Map ONE product row → the CPTAC-ALIGNED card summary contract (verdict-inert)."""
    return {
        "cohort": matched_cohort,
        "tissue": row.get("tissue"),                        # matched adjacent-normal comparator tissue (TPHP-specific)
        # PRIMARY categorical — the product's `effect` (strong_up/modest_up/unchanged/modest_down/strong_down).
        "protein_expression_class": row.get("effect", "unchanged"),
        # RAW log2 tumor-vs-normal effect (median_log2_tumor - median_log2_normal). CPTAC-aligned name.
        "protein_effect_size": row.get("log2_fc"),
        "protein_median_log2_tumor": row.get("median_log2_tumor"),
        "protein_median_log2_normal": row.get("median_log2_normal"),
        "protein_p_value": row.get("p_value"),
        "protein_bh_q_value": row.get("q_value"),           # BH within-cohort. CPTAC-aligned name.
        "n_tumor_samples": row.get("n_tumor"),
        "n_normal_samples": row.get("n_normal"),
        "uniprot_ac": row.get("uniprot_ac"),
        "stat_test_used": STAT_TEST,
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    """Honest data_unavailable summary. Every card-declared field is present (a reader RENAME is caught
    by the tumor-selectivity replay drift guard); numerics are None and the primary categorical is
    data_unavailable (NEVER read as a favorable / flat protein window — a genuine coverage gap)."""
    return {
        "cohort": None,
        "tissue": None,
        "protein_expression_class": "data_unavailable",
        "protein_effect_size": None,
        "protein_median_log2_tumor": None,
        "protein_median_log2_normal": None,
        "protein_p_value": None,
        "protein_bh_q_value": None,
        "n_tumor_samples": None,
        "n_normal_samples": None,
        "uniprot_ac": None,
        "stat_test_used": STAT_TEST,
        "method_version": METHOD_VERSION,
        "_data_note": note,
    }


def read_target_summary(target: str, indication: str = None, product_path=None) -> dict:
    """Per-target TPHP tumor-vs-adjacent-normal PROTEIN differential summary (verdict-inert facet).

    Args:
        target: HGNC gene symbol (the product's `gene_symbol` pushdown key).
        indication: If given, restrict to the TPHP cohort mapped from this OncoTree/TCGA code via
            INDICATION_TO_TPHP_COHORT. A supplied-but-unmapped indication returns data_unavailable
            (never leaks another cohort's contrast — mirrors cptac_protein_deg). Otherwise (no
            indication) return the largest-|effect_size| row across cohorts (pan-cancer / target-only).
        product_path: offline test seam — a local parquet path bypasses S3.

    Returns:
        The CPTAC-aligned per-cohort summary. Never raises on target-not-found — returns
        protein_expression_class='data_unavailable'. A transient/creds/broken-env fault surfaces
        _live_read_error (so the compose path degrades honestly instead of crashing).
    """
    try:
        rows = _read_rows_from_derived(target.upper().strip(), product_path=product_path)
    except Exception as e:  # noqa: BLE001
        # GENUINE 404-class absence (NoSuchKey/404 / FileNotFoundError) → honest data_unavailable. A
        # transient/creds/broken-env fault must NOT be masked as an empty protein footprint — re-raise
        # so the live-read seam surfaces _live_read_error (absence discipline; mirrors tphp_normal_protein).
        from methods.target_id_sidecar import is_definitively_absent
        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        out = _empty("tphp_tvn_read_failed")
        out["_live_read_error"] = "tphp_tumor_vs_normal_protein_read_failed"
        out["_remediation"] = (
            f"Could not read the TPHP tumor-vs-normal protein product ({DERIVED_MANIFEST_ID}) "
            f"for {target}: {e}")
        return out

    if not rows:
        return _empty("target_not_in_tphp_tvn_product")

    # Index this gene's rows by (upper-cased) cohort string.
    by_cohort = {str(r.get("cohort", "")).strip(): r for r in rows}

    # Primary path: indication-specific lookup via the OncoTree→cohort map.
    if indication:
        cohort = INDICATION_TO_TPHP_COHORT.get(indication.upper().strip())
        # A SUPPLIED but unmapped indication must NOT leak a different cohort's contrast (TPHP is a
        # PER-COHORT tumor-vs-normal differential). Honest posture: data_unavailable. Mirrors
        # cptac_protein_deg's indication-leak guard.
        if cohort is None:
            return _empty(f"indication_not_in_tphp_tvn_{indication.upper().strip()}")
        row = by_cohort.get(cohort)
        if row is None:
            return _empty(f"target_not_in_tphp_tvn_cohort_{cohort.replace(' ', '_')}")
        return _row_to_summary(row, matched_cohort=cohort)

    # Fallback (NO indication — target-only / pan-cancer query): the largest-|effect_size| cohort row.
    best = max(rows, key=lambda r: abs(float(r.get("log2_fc", 0) or 0)))
    return _row_to_summary(best, matched_cohort=str(best.get("cohort", "")).strip())


def read_all_cohorts(target: str, product_path=None) -> list[dict]:
    """Every TPHP cohort row for a target — the cross-cohort tumor-vs-normal panel (|effect|-desc).

    Empty list when the target is absent / product unavailable (a genuine 404-class fault is re-raised
    by _read_rows_from_derived, surfacing at the live-read seam — never masked as an empty panel)."""
    rows = _read_rows_from_derived(target.upper().strip(), product_path=product_path)
    if not rows:
        return []
    out = [_row_to_summary(r, matched_cohort=str(r.get("cohort", "")).strip()) for r in rows]
    out.sort(key=lambda r: abs(float(r.get("protein_effect_size") or 0)), reverse=True)
    return out


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(
        description="TPHP tumor-vs-adjacent-normal protein differential for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    ap.add_argument("--product-path", default=None, help="offline: local parquet path (bypasses S3)")
    args = ap.parse_args(argv)
    print(json.dumps(read_target_summary(args.target, indication=args.indication,
                                         product_path=args.product_path), indent=2, default=str))


if __name__ == "__main__":
    _main()
