"""tphp_tumor_vs_normal_protein.read — TPHP tumor-vs-BODY-ATLAS-normal PROTEIN DEG reader.

Consumer: the `tumor-vs-normal-protein-abundance-tphp` evidence card (tumor-selectivity), a
VERDICT-INERT RNA->PROTEIN corroboration facet PARALLEL to `tumor-protein-abundance-cptac`. Emits
per-(target, cohort) protein-level tumor-vs-normal differential statistics from the TPHP body+cancer
DIA-MS proteome (Xu et al., Nature 2026; open PRIDE PXD063370), across 22 carcinoma cohorts — several
outside CPTAC coverage (gallbladder, laryngeal, GIST, testis, fallopian-tube, thymoma, ...).

★ WHAT THE NORMAL ARM ACTUALLY IS (v1 mislabelled it, and so did this module). There is no per-patient
pairing and no separate adjacent-normal collection. The comparator is the BODY-ATLAS normal samples of
the tumour's organism part — the SAME samples methods/tphp_normal_protein reads. Proof, from the
producer: for all 22 retained cohorts max(n_normal) equals that organism part's n_samples in the normal-
tissue product EXACTLY (brain 74=74, lung 14=14, large intestine 13=13, mammary gland 4=4). So this
facet and the TPHP normal-tissue atlas are ONE measurement read twice, NOT two independent platforms —
`normal_arm_source` carries that per row so a consumer keys on the VALUE, not on a hardcoded product id.
(The `stat_test_used` constant still spells "adjacent_normal": that literal is pinned in the contracts
card vocabulary and in two skills fixtures, so renaming it belongs to the contracts-side truth-in-
labelling change, not here. It is a KNOWN-WRONG NAME, superseded by normal_arm_source.)

★ DETECTION CENSORING IS THE DOMINANT ARTIFACT, and it is DECLARED here, not corrected. The product's
n_tumor / n_normal are DETECTED counts; v2 adds the arm TOTALS so completeness is reconstructable.
Measured on the shipped v2 product: among the 28,618 effect-classed rows, tumour-down:up is 3.60:1
ungated and 1.50:1 on detection-complete rows, and median log2_fc runs -0.055 (tumour arm fully
detected) to -0.860 (below 50% detected). The producer deliberately does NOT re-centre log2_fc (a
per-cohort constant has the wrong functional form and inflates strong_up 2.09x — see the derived
manifest), so a DIRECTIONAL read of this facet must gate on protein_detection_complete. This reader
emits the completeness fields and never silently drops a row: 58.1% of genes have NO detection-complete
row in ANY cohort, so filtering here would blank most of the product instead of qualifying it.

DISTINCT-IN-ROLE from methods/tphp_normal_protein (NOT distinct in substrate — see the normal-arm note
above): that reader is the NORMAL-tissue protein-abundance liability (a verdict-BEARING normal-breadth
veto arm) over the atlas product (normal-tissue-protein-abundance-per-gene-v2, sample_context=normal).
THIS reader is the TUMOR-context differential facet, verdict-INERT (fires no rule / no clamp). The two
read the SAME normal samples, so they are NOT mutually corroborating evidence about the normal arm.

Field-name contract — CPTAC-ALIGNED. The emitted keys (protein_expression_class / protein_effect_size
/ protein_bh_q_value / protein_median_log2_{tumor,normal} / n_{tumor,normal}_samples) mirror
methods/cptac_protein_deg/read.py so the tumor-selectivity run.py `_rna_protein_tvn_concordance`
projection consumes this card UNCHANGED — the same derived read it already runs over the CPTAC card
summary (protein_effect_size + protein_bh_q_value → rna_protein_concordant / _discordant /
protein_not_significant / protein_unmeasured).

Substrate: the derived per-cohort product `tphp-tumor-vs-normal-protein-per-cohort-v2` — gene_symbol-
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

from methods.catalog_query.read import bucket_key_for

DERIVED_MANIFEST_ID = "tphp-tumor-vs-normal-protein-per-cohort-v2"
METHOD_VERSION = "0.2.0"

# The product's tumor-vs-normal comparison is an UNPAIRED Welch two-sample t-test on the detected log2
# MaxLFQ values, BH-adjusted within cohort (see the derived manifest transformation). A single constant
# (the product has no per-row test flag) — surfaced so a consumer can distinguish it from CPTAC's
# MSstatsTMT limma-moderated t (the two facets use different estimators by design).
#
# ★ The "adjacent_normal" in this literal is WRONG (the arm is the body atlas — see the module docstring)
# and is KEPT ANYWAY: the exact string is pinned in the contracts card's `stat_test_used` vocabulary and
# in two skills fixtures, so a rename here reds those without fixing anything. `normal_arm_source`
# (emitted per row, straight from the product) is the field that carries the truth; a consumer keys on
# THAT. Renaming this constant is the contracts-side change, tracked in the W5 registry entry.
STAT_TEST = "welch_unpaired_tumor_vs_adjacent_normal"

# Fallback pick bases (emitted as `cohort_pick_basis`) — say WHICH rule chose the returned cohort, so a
# consumer can tell an indication-matched contrast from a pan-cancer extremum, and a detection-complete
# extremum from a censored one. See the fallback in read_target_summary.
PICK_INDICATION = "indication_mapped"
PICK_PAN_COMPLETE = "pan_cancer_max_abs_log2fc_detection_complete"
PICK_PAN_ANY = "pan_cancer_max_abs_log2fc_no_detection_complete_row"

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


def _abs_effect(row: dict) -> float:
    """|log2_fc| as an ARGMAX/SORT key, with non-finite values ranked LAST (-1.0), not first.

    ±Inf and NaN are numbers: `abs(inf)` wins every max() and NaN makes max() order-dependent, so a
    single degenerate row would capture the pan-cancer pick or the top of the cross-cohort panel. The
    product should not contain either (both arms have >= min_{tumor,normal} detected finite log2 values),
    so this guard is expected to be inert — it exists because the failure mode is silent if it isn't."""
    v = row.get("log2_fc")
    try:
        f = abs(float(v))
    except (TypeError, ValueError):
        return -1.0
    return f if math.isfinite(f) else -1.0


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


def _row_to_summary(row: dict, matched_cohort: str, pick_basis: str = PICK_INDICATION) -> dict:
    """Map ONE product row → the CPTAC-ALIGNED card summary contract (verdict-inert)."""
    return {
        "cohort": matched_cohort,
        # The tumour-site organism part — and ALSO the normal arm's tissue (one part, both arms). NOT a
        # separately collected adjacent normal; see the module docstring's normal-arm note.
        "tissue": row.get("tissue"),
        # PRIMARY categorical — the product's `effect` (strong_up/modest_up/unchanged/modest_down/strong_down).
        "protein_expression_class": row.get("effect", "unchanged"),
        # RAW log2 tumor-vs-normal effect (median_log2_tumor - median_log2_normal). CPTAC-aligned name.
        "protein_effect_size": row.get("log2_fc"),
        "protein_median_log2_tumor": row.get("median_log2_tumor"),
        "protein_median_log2_normal": row.get("median_log2_normal"),
        "protein_p_value": row.get("p_value"),
        "protein_bh_q_value": row.get("q_value"),  # BH within-cohort. CPTAC-aligned name.
        # DETECTED counts (unchanged names/values), now with their DENOMINATORS so a consumer can
        # reconstruct completeness instead of mistaking a censored arm for a small one.
        "n_tumor_samples": row.get("n_tumor"),
        "n_normal_samples": row.get("n_normal"),
        "n_tumor_samples_total": row.get("n_tumor_total"),
        "n_normal_samples_total": row.get("n_normal_total"),
        "protein_detection_rate_tumor": row.get("detection_rate_tumor"),
        "protein_detection_rate_normal": row.get("detection_rate_normal"),
        # ★ GATE DIRECTIONAL READS ON THIS. False does not mean "no effect" — it means the effect size is
        # confounded by missingness (tumour-down:up 3.60:1 ungated vs 1.50:1 here). Rows are NEVER dropped
        # for it: 58.1% of genes have no complete row in ANY cohort, so filtering here would blank the facet.
        "protein_detection_complete": row.get("detection_complete"),
        # What the normal arm IS, from the product. Consumers testing platform independence against
        # normal-tissue-protein-abundance-per-gene must key on this VALUE, not on a product-id allowlist.
        "normal_arm_source": row.get("normal_arm_source"),
        "uniprot_ac": row.get("uniprot_ac"),
        "cohort_pick_basis": pick_basis,
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
        "n_tumor_samples_total": None,
        "n_normal_samples_total": None,
        "protein_detection_rate_tumor": None,
        "protein_detection_rate_normal": None,
        # None, NOT False: an unread row is not a censored row. False would let a consumer's
        # `if not complete` branch treat a coverage gap as a measured-but-censored contrast.
        "protein_detection_complete": None,
        "normal_arm_source": None,
        "uniprot_ac": None,
        "cohort_pick_basis": None,
        "stat_test_used": STAT_TEST,
        "method_version": METHOD_VERSION,
        "_data_note": note,
    }


def read_target_summary(target: str, indication: str = None, product_path=None) -> dict:
    """Per-target TPHP tumor-vs-atlas-normal PROTEIN differential summary (verdict-inert facet).

    Args:
        target: HGNC gene symbol (the product's `gene_symbol` pushdown key).
        indication: If given, restrict to the TPHP cohort mapped from this OncoTree/TCGA code via
            INDICATION_TO_TPHP_COHORT. A supplied-but-unmapped indication returns data_unavailable
            (never leaks another cohort's contrast — mirrors cptac_protein_deg). Otherwise (no
            indication) return the largest-|effect_size| row among the target's DETECTION-COMPLETE
            cohort rows, falling back to all rows only when it has none (see cohort_pick_basis).
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
            f"Could not read the TPHP tumor-vs-normal protein product ({DERIVED_MANIFEST_ID}) for {target}: {e}"
        )
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

    # Fallback (NO indication — target-only / pan-cancer query): the largest-|effect_size| cohort row,
    # ★ PREFERRING detection-complete rows. A bare max-|log2_fc| over all rows systematically picks the
    # MOST CENSORED cohort, because incompleteness INFLATES |log2_fc| (median log2_fc -0.055 where the
    # tumour arm is fully detected vs -0.860 below 50% detected) — so the old max() selected an
    # artifact-maximising row by construction. Restricting the argmax to complete rows keeps the same
    # "most extreme cohort" semantics on the population where the extremum means what it says. We fall
    # back to the full set (rather than return data_unavailable) because 58.1% of genes have NO complete
    # row anywhere; cohort_pick_basis says which population the winner came from.
    #
    # MEASURED over all 10,573 genes in the product (2026-09-13). 4,431 genes (41.9%) have >=1 complete
    # row, and for 2,201 of those (49.7%) this changes which cohort is returned; 470 change SIGN. Net
    # effect on the returned class: strong_down 3,599 -> 3,152 (-447), strong_up 823 -> 668 (-155),
    # unchanged 4,573 -> 5,107 (+534). So it de-calls spuriously extreme contrasts in BOTH directions,
    # which is the intended correction, and it is NOT a fail-open change dressed as rigour: the
    # transition census includes 79 unchanged -> strong_down promotions alongside 358 strong_down ->
    # unchanged demotions.
    #
    # ★ WHAT THIS DOES *NOT* FIX, stated because the number goes the other way: the down:up ratio of the
    # returned class gets slightly WORSE, 3.87:1 -> 4.25:1 (up-classes shrink 15.6%, down-classes 7.2%).
    # Detection censoring is therefore NOT the source of the pan-cancer path's directional skew — the
    # ARGMAX-OVER-|EFFECT| RULE ITSELF is. Row-level down:up among effect-classed complete rows is 1.50:1;
    # taking the per-gene extremum of those same rows yields 4.25:1, because the tumour-down tail is the
    # longer one and a max-|effect| pick samples exactly the tail. Any consumer reading this facet
    # directionally on the no-indication path is reading a worst-case selection, not a typical contrast.
    # Fixing that means changing the pan-cancer SEMANTIC (e.g. median-across-cohorts, or returning the
    # panel), which moves a shipped field's meaning and is out of scope here — declared, not silently
    # patched. read_all_cohorts() already exposes the full panel for a consumer that wants it.
    complete = [r for r in rows if r.get("detection_complete") is True]
    pool, basis = (complete, PICK_PAN_COMPLETE) if complete else (rows, PICK_PAN_ANY)
    best = max(pool, key=_abs_effect)
    return _row_to_summary(best, matched_cohort=str(best.get("cohort", "")).strip(), pick_basis=basis)


def read_all_cohorts(target: str, product_path=None) -> list[dict]:
    """Every TPHP cohort row for a target — the cross-cohort tumor-vs-normal panel (|effect|-desc).

    Empty list when the target is absent / product unavailable (a genuine 404-class fault is re-raised
    by _read_rows_from_derived, surfacing at the live-read seam — never masked as an empty panel)."""
    rows = _read_rows_from_derived(target.upper().strip(), product_path=product_path)
    if not rows:
        return []
    out = [
        _row_to_summary(
            r,
            matched_cohort=str(r.get("cohort", "")).strip(),
            # None: a panel row was never "picked" — every cohort is returned, so there is no selection
            # basis to report. Per-row completeness rides on protein_detection_complete, which is what a
            # caller ranking this panel must gate direction on.
            pick_basis=None,
        )
        for r in rows
    ]
    out.sort(key=lambda r: _abs_effect({"log2_fc": r.get("protein_effect_size")}), reverse=True)
    return out


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="TPHP tumor-vs-atlas-normal protein differential for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    ap.add_argument("--product-path", default=None, help="offline: local parquet path (bypasses S3)")
    args = ap.parse_args(argv)
    print(
        json.dumps(
            read_target_summary(args.target, indication=args.indication, product_path=args.product_path),
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    _main()
