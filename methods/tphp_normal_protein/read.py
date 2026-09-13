"""tphp_normal_protein.read — TPHP normal-tissue PROTEIN abundance per target.

Streamed pushdown read of the derived per-gene product `normal-tissue-protein-abundance-per-gene-v2`
via a pyarrow S3FileSystem, pushing down the `gene_symbol` filter so only ONE gene's per-tissue rows
transit the wire (mirrors methods/collectri_tf_regulon/read.py — the gene_symbol-keyed pushdown
precedent). The product stores DETECTED-only rows (a (gene, tissue) with n_detected==0 is not stored),
so every row is a tissue where the protein was quantified in >=1 normal sample.

This reader emits a normal-tissue-protein comparator summary. Most fields are DISPLAYED by the
tumor-selectivity skill; ONE field — tphp_normal_protein_liability_class — is VERDICT-BEARING: it is
the abundance-gated (Floor-C) NORMAL-BREADTH liability instrument the tumor-selectivity skill uses to
downgrade an axis-A-selective call to selective_with_normal_liability (via the skills-side
selectivity_veto clamp; NO resolver rung). It is the quantitative NORMAL-tissue PROTEIN baseline the
skill lacked — GTEx gives normal RNA, HPA gives categorical IHC breadth; this gives DIA-MS protein
abundance across 70 adult tissues + 4 fetal germ-layer groups.

Absence discipline (mirrors the collectri reader): a GENUINE product-object absence (NoSuchKey/404
or FileNotFoundError) or a gene simply absent from the product → honest `data_unavailable`. A
transient / credential / broken-env error is RE-RAISED (never masked as an empty normal footprint)
so the live-read seam surfaces `_live_read_error` instead of a silent dead comparator.
"""

from __future__ import annotations

import statistics
import threading
from typing import Optional

from methods.catalog_query.read import bucket_key_for
from methods.normal_tissue_safety_common.essential_organs import TPHP_CROSSWALK

DERIVED_MANIFEST_ID = "normal-tissue-protein-abundance-per-gene-v2"
METHOD_VERSION = "0.3.0"  # 0.3.0: v2 substrate — tissue_category + solid-tissue counts + vital-organ MEASURABILITY
# 0.2.0: + vital-organ safety read (tphp_vital_organ_* via TPHP_CROSSWALK), for T0-3 (on-target-safety wiring)

# Denominators sourced from the derived manifest `parameters` block (n_adult_tissues / n_fetal_groups)
# — the population of normal-tissue groups the DIA-MS panel spans. Surfaced so a consumer can read
# "detected in K of N adult tissues" without a full-product scan (the per-gene pushdown only sees the
# gene's own rows). Breadth thresholds below are ABSOLUTE counts, so the denominator is informational.
N_ADULT_TISSUES_TOTAL = 70
N_FETAL_GROUPS_TOTAL = 4

# ── WHAT KIND OF ENTRY each "adult tissue" is (v2 `tissue_category`) ───────────────────────────────
# 10 of the 70 adult organism-parts are NOT solid tissues: 4 body fluids (blood plasma / urine /
# saliva / tear), 4 blood_compartment entries (blood / erythrocyte / leukocyte / blood platelet — ONE
# haematopoietic compartment counted FOUR times), 1 non_tissue (hair) and 1 unassignable (plant
# vessel; 11 human runs whose median proteome's best adult match sits in a flat rho=0.86-0.88 band
# across eight unrelated tissues, so it is not reassignable). Producer-verified counts, v2 parameters:
# 60 solid + 4 blood_compartment + 4 body_fluid + 1 non_tissue + 1 unassignable = 70.
SOLID_TISSUE_CATEGORY = "solid_tissue"
N_SOLID_ADULT_TISSUES_TOTAL = 60

# ── SUPPORT (measurability) bar ────────────────────────────────────────────────────────────────────
# 21 of the 70 adult parts have n_samples <= 2 (measured off v2, 2026-09-13) — 30% of the breadth
# denominator is decided by one or two donors. This bar does NOT gate any class; it labels rows so a
# consumer can tell "measured, absent" from "too few samples to say". See _vital_organ_summary for why
# a DROPPING gate here would be a safety inversion rather than a tightening.
MIN_SAMPLES_MEASURABLE = 3

# normal_protein_breadth_class thresholds on the count of ADULT tissues the protein is detected in
# (the safety-relevant breadth — fetal groups are developmental context, not an adult on-target-off-
# tumor footprint). ABSOLUTE counts against the ~70-adult-tissue panel.
BROAD_ADULT_TISSUE_COUNT = 35  # >=50% of adult tissues → broad normal-protein footprint
MODERATE_ADULT_TISSUE_COUNT = 10  # >=~15% → moderate

_FETAL_CLASS = "fetal"
_ADULT_CLASS = "adult_normal"

# ── ABUNDANCE-FLOOR (Floor-C) parameters for tphp_normal_protein_liability_class ─────────────────
# The tumor-selectivity NORMAL-BREADTH liability instrument keys on tphp_normal_protein_liability_class,
# a promotion of this (formerly verdict-inert) card to a verdict-bearing normal-protein liability read.
# It is gated on ABUNDANCE, not DIA DETECTION. DIA-MS detects a protein broadly at TRACE levels, so
# "detected in >=35 adult tissues" alone (normal_protein_breadth_class == broad_normal_protein) is NOT a
# therapeutic-index liability — a broadly-DETECTED-but-low-abundance protein is not broadly present at a
# level that costs a therapeutic window. Floor-C corrects this: broad_and_abundant requires a BROAD
# COUNT of adult tissues that are EACH at/above a global per-tissue abundance floor.
#
# WHY A COUNT, NOT max_median_log2_abundance: a single origin/outlier tissue spiking high does NOT make
# a protein broadly abundant. CEACAM5's per-tissue max is 20.8 (eye tissue — iris/sclera) but only ~30
# of its 63 detected adult tissues clear the floor, so it reads detected_not_abundant (NOT a broad
# liability) — the intended correction. True housekeeping / pan-tissue-abundant proteins (GAPDH/ACTB/
# KRAS) clear the floor in ~all 70 tissues → broad_and_abundant. max_median_log2_abundance is retained
# as a DISPLAY field only; it does NOT gate the class.
#
# ABUNDANCE_FLOOR_LOG2 DERIVATION (cached; tunable/recalibratable): the ABUNDANCE_FLOOR_PERCENTILE (p75)
# of the per-(gene, adult-tissue) median_log2_abundance across the WHOLE product
# (482,704 adult rows over 13,009 genes; v2 leaves every v1 column byte-identical) == 15.0759. This
# is a global, product-derived floor (a defensible "typical-or-better" abundance level), cached here as
# a frozen constant so the per-gene pushdown reader never scans the whole product on the critical path.
# Recompute with compute_abundance_floor(product_path=, percentile=) on a product refresh / to
# recalibrate the percentile.
#
# ★ THE FLOOR IS A DEPTH READOUT AS MUCH AS AN ABUNDANCE ONE — declared, not corrected. Over the 70
# adult tissues, Spearman(n_proteins_quantified, fraction of proteome >= floor) = -0.886: a SHALLOW
# run's few detected proteins are its most abundant ones, so it clears the floor at a HIGHER rate. The
# non-solid entries are the extreme case (median fraction above floor 0.389 vs 0.238 for solid tissues;
# blood plasma 0.566 on just 1,766 proteins). Two consequences, both handled by DECLARING rather than
# transforming: (1) `tissue_category` is emitted per tissue and the solid-only counts are emitted
# alongside the all-adult ones, so a consumer can pick its denominator; (2) the counts below are NOT
# re-derived against the 60 solid parts — see BROAD_ABUNDANT_TISSUE_COUNT.
ABUNDANCE_FLOOR_PERCENTILE = 75  # tunable: global per-tissue percentile that defines "abundant"
ABUNDANCE_FLOOR_LOG2 = 15.076  # cached p75 of per-(gene,adult-tissue) median_log2_abundance
BROAD_ABUNDANT_TISSUE_COUNT = 35  # tunable: # adult tissues at/above the floor → broad_and_abundant
# (shares the ~50%-of-panel breadth bar with BROAD_ADULT_TISSUE_COUNT)
#
# ★ WHY THIS COUNT IS NOT RE-DERIVED AGAINST THE 60 SOLID PARTS (a deliberate NON-change, twice over).
#
# (a) Switching the numerator to solid-only WITHOUT moving the cut would be a pure safety RELAXATION.
#     Excluding the 10 non-solid parts removes ~10 from the count of a broadly-abundant target, and
#     because those parts are ENRICHED above the floor it removes MORE than their share — while 35 is an
#     ABSOLUTE cut. Fewer targets clear it, so the veto fires LESS often. Nothing about the biology got
#     safer; the instrument just got quieter. (Pairing the exclusion with a proportional cut of 30 is the
#     arithmetically consistent version — and (b) says we cannot justify even that here.)
#
# (b) The panel CANNOT DISCRIMINATE any cut between 30 and 35, so retuning it would be unfalsifiable.
#     Every target measured on the review panel sits at <=30 or >=58 adult tissues above the floor; the
#     30-35 interval is EMPTY. A "recalibration" that no observation can distinguish from the status quo
#     is not a calibration, it is a number swap that spends the reviewability of a SAFETY threshold for
#     nothing. Moving this cut needs a population that populates the interval — a full-product sweep of
#     the per-gene above-floor distribution, not the review panel. Recorded as the open item.
#
# So the verdict-bearing arithmetic is UNCHANGED by this version: same floor, same cut, same all-adult
# numerator. The v2 columns arrive as DECLARATION (n_solid_adult_tissues_*, tissue_category per row),
# which is what a future calibration needs and what a consumer choosing its own denominator needs.


# ── streamed pushdown read (pyarrow S3FileSystem; no whole-file download) ─────────────────────
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1, the onc-compbio bucket).
    Built once and shared (safe for concurrent reads — the parallel card-read pool relies on that).
    Mirrors methods/collectri_tf_regulon/read.py::_get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs

                _S3FS = pafs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_rows_from_derived(gene: str, product_path=None) -> list[dict]:
    """Streamed pushdown read of ONE gene's per-tissue rows from the derived product.

    Returns the list of row dicts (may be empty if the gene has no detected tissue). `product_path`
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


def _is_num(x) -> bool:
    import math

    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def _breadth_class(n_adult: int) -> str:
    if n_adult >= BROAD_ADULT_TISSUE_COUNT:
        return "broad_normal_protein"
    if n_adult >= MODERATE_ADULT_TISSUE_COUNT:
        return "moderate_normal_protein"
    if n_adult >= 1:
        return "restricted_normal_protein"
    return "not_detected_in_normal_protein"  # rows exist but none adult (fetal-only detection)


def _liability_class(n_adult_detected: int, n_adult_above_floor: int) -> str:
    """tphp_normal_protein_liability_class (Floor-C, abundance-gated NORMAL-breadth liability).

    Args:
        n_adult_detected: # distinct ADULT tissues the protein is DETECTED in (any quantified value).
        n_adult_above_floor: # distinct ADULT tissues whose median_log2_abundance >= ABUNDANCE_FLOOR_LOG2.

    Classes:
      * broad_and_abundant     — abundant across a BROAD count of tissues (n_adult_above_floor >=
                                 BROAD_ABUNDANT_TISSUE_COUNT). The therapeutic-index liability: a genuine
                                 broad normal-protein presence (GAPDH/ACTB/KRAS pan-tissue archetype).
      * detected_not_abundant  — broadly DETECTED (n_adult_detected >= BROAD_ADULT_TISSUE_COUNT) but NOT
                                 broadly abundant. The DIA-detects-broadly-at-trace correction: a protein
                                 seen in many tissues at low/trace levels, or abundant in only a few
                                 origin/outlier tissues (CEACAM5), is NOT a broad liability.
      * restricted             — narrow footprint (detected in < BROAD_ADULT_TISSUE_COUNT adult tissues).
      * data_unavailable       — handled by the caller (gene absent / read fault).
    """
    if n_adult_above_floor >= BROAD_ABUNDANT_TISSUE_COUNT:
        return "broad_and_abundant"
    if n_adult_detected >= BROAD_ADULT_TISSUE_COUNT:
        return "detected_not_abundant"
    return "restricted"


def compute_abundance_floor(product_path=None, percentile: int = ABUNDANCE_FLOOR_PERCENTILE) -> float:
    """Recompute the global per-tissue abundance floor from the product's OWN distribution — the
    `percentile` of the per-(gene, ADULT-tissue) median_log2_abundance across ALL proteins.

    This is the DERIVATION behind the cached ABUNDANCE_FLOOR_LOG2 constant, exposed so the floor can be
    recalibrated on a product refresh or a different percentile without a code archaeology dig. It reads
    the WHOLE product (two columns), so it is NOT called on the per-gene read path — the reader uses the
    frozen constant. `product_path` (offline seam): a local parquet bypasses S3.

    Reachable via `python -m methods.tphp_normal_protein.read --recompute-floor`, which prints the
    re-derived floor beside the cached constant and their drift. That CLI flag exists because this
    function had no caller at all: an unreachable derivation for the cut of a verdict-bearing safety
    class is indistinguishable from a hardcoded magic number, and "recompute it" was not a runnable
    instruction. It stays read-only — bumping the constant is a reviewed edit, not a side effect.
    """
    import statistics

    import pyarrow.parquet as pq

    cols = ["tissue_class", "median_log2_abundance"]
    if product_path is not None:
        tbl = pq.read_table(str(product_path), columns=cols)
    else:
        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), columns=cols)
    d = tbl.to_pydict()
    vals = [v for tc, v in zip(d["tissue_class"], d["median_log2_abundance"]) if tc != _FETAL_CLASS and _is_num(v)]
    if not vals:
        raise ValueError("no adult-tissue abundance values in the product — cannot compute floor")
    # statistics.quantiles(n=100) → 99 cut points; the p-th percentile is index p-1 (inclusive method).
    if percentile <= 0:
        return float(min(vals))
    if percentile >= 100:
        return float(max(vals))
    return float(statistics.quantiles(vals, n=100, method="inclusive")[percentile - 1])


def _fetal_vs_adult_flag(n_adult: int, n_fetal: int) -> str:
    if n_adult and n_fetal:
        return "adult_and_fetal"
    if n_adult:
        return "adult_only"
    if n_fetal:
        return "fetal_only"
    return "none"


def _empty_summary() -> dict:
    """The data_unavailable summary — gene absent from the product, or a genuine read fault. Every
    field the card declares is present (so a reader RENAME is caught by the card-field drift guard);
    the numerics are None/0 and the primary categorical is data_unavailable (honest coverage gap,
    NEVER read as a favorable / narrow normal footprint)."""
    return {
        "normal_protein_breadth_class": "data_unavailable",
        "tphp_normal_protein_liability_class": "data_unavailable",
        "tphp_vital_organ_liability_class": "data_unavailable",
        "n_vital_organs_above_abundance_floor": 0,
        # 0 measurable / 0 unmeasurable: the gene was never read, so NO organ was assessed. Reporting
        # 2 unmeasurable here would claim a panel property from a row that does not exist.
        "n_vital_organs_measurable": 0,
        "n_vital_organs_unmeasurable": 0,
        "vital_organ_min_samples": MIN_SAMPLES_MEASURABLE,
        "tphp_vital_organ_abundance": [],
        "n_adult_tissues_above_abundance_floor": 0,
        "abundance_floor_log2": ABUNDANCE_FLOOR_LOG2,
        "n_tissues_detected": 0,
        "n_adult_tissues_detected": 0,
        "n_adult_tissues_detected_low_support": 0,
        "n_solid_adult_tissues_detected": 0,
        "n_solid_adult_tissues_above_abundance_floor": 0,
        "n_fetal_groups_detected": 0,
        "n_adult_tissues_total": N_ADULT_TISSUES_TOTAL,
        "n_solid_adult_tissues_total": N_SOLID_ADULT_TISSUES_TOTAL,
        "n_fetal_groups_total": N_FETAL_GROUPS_TOTAL,
        "max_median_log2_abundance": None,
        "median_across_tissues_log2_abundance": None,
        "highest_abundance_tissue": None,
        "highest_abundance_tissue_class": None,
        "fetal_vs_adult_flag": "data_unavailable",
        "max_detection_rate": None,
        "uniprot_ac": None,
        "per_tissue_abundance": [],
        "method_version": METHOD_VERSION,
    }


# Canonical vital organs TPHP can represent (crosswalk non-None), each with its representative TPHP
# organism-part. This is the SAFETY-facing view (dose-limiting-organ protein presence), distinct from
# the pan-tissue BREADTH view (tphp_normal_protein_liability_class): a target can be narrow-breadth yet
# abundant in a vital organ (a therapeutic-window flag the breadth class misses). TPHP fills nerve /
# muscle / blood / adrenal / thyroid — organs HPA-IHC is blind to.
_VITAL_ORGAN_TISSUE = {organ: tissue for organ, tissue in TPHP_CROSSWALK.items() if tissue}

# Panel ARM SIZE (n_samples) per vital-organ representative part. The product stores DETECTED-only
# rows, so a per-gene pushdown sees NO row for an organ where the target was not quantified — and then
# the row's own n_samples is unavailable, which is exactly the case where knowing the arm size matters
# (is this organ clean, or unmeasurable?). Cached here, measured off
# normal-tissue-protein-abundance-per-gene-v2 on 2026-09-13; n_samples is constant per (tissue,
# tissue_class), so one number per organ is well defined.
#
# This cache is SELF-FALSIFYING, not a trusted constant: whenever a row IS present, the ROW's n_samples
# wins and the record reports n_samples_source='product_row'. A refreshed product with different arm
# sizes therefore shows up in the emitted values rather than being silently overridden by this dict.
VITAL_ORGAN_N_SAMPLES = {
    "blood": 1,
    "thyroid gland": 2,
    "bone marrow": 3,
    "pancreas": 7,
    "adrenal gland": 8,
    "kidney": 10,
    "skeletal muscle": 10,
    "liver": 12,
    "lung": 14,
    "heart": 18,
    "artery": 18,
    "nerve": 51,
    "brain": 74,
}


def _vital_organ_summary(per_tissue: list[dict]) -> tuple[list[dict], str, int, int, int]:
    """Per-vital-organ protein abundance + a verdict-INERT liability class + MEASURABILITY counts.

    For each canonical vital organ TPHP can represent, look up the target's median_log2_abundance in
    that organ's representative TPHP organism-part and flag `above_floor` against the SAME calibrated
    ABUNDANCE_FLOOR_LOG2 the breadth class uses (no new threshold). The class keys on whether the target
    is abundantly present in ANY dose-limiting organ — a therapeutic-window flag — reusing the existing
    floor rather than an invented multi-cut:
      * vital_organ_abundant   — >=1 vital organ at/above the abundance floor (window liability)
      * vital_organ_low        — detected in >=1 vital organ but NONE at/above the floor (trace only)
      * no_vital_organ_signal  — not detected in any vital organ (in the TPHP panel)

    ★ MEASURABILITY IS LABELLED, NEVER GATED — and that is the load-bearing decision here. Two of the 13
    crosswalked organs are below MIN_SAMPLES_MEASURABLE: `blood` (n_samples=1) and `thyroid gland`
    (n_samples=2). `thyroid` is an S1_3_REQUIRED_ORGANS member, i.e. one of the five organs whose
    ABSENCE from an essential set WAS the original safety false-negative. So a `n_samples >= 3` filter on
    this loop — the obvious-looking support gate — would DROP thyroid and blood from the panel, and
    dropping an organ makes it contribute nothing to n_above, which reads as "not a liability here". The
    gate would silently restore two thirteenths of the exact hole `essential_organs.py` exists to close,
    and it would do it while looking like added rigour. (`bone marrow`, n_samples=3, sits EXACTLY on that
    bar — a third organ one donor away from disappearing.)

    Instead every organ stays in the list with `measurable` stating whether the arm can support a call,
    and the counts are returned so a consumer can say "clean across 11 well-powered organs, 2
    unmeasurable" rather than "clean". `measurable=False` is NOT evidence of absence in either direction.

    Returns (rows, class, n_above_floor, n_measurable, n_unmeasurable).
    """
    by_tissue = {t["tissue"]: t for t in per_tissue if t.get("tissue_class") != _FETAL_CLASS}
    rows: list[dict] = []
    n_above = 0
    n_detected = 0
    n_measurable = 0
    n_unmeasurable = 0
    for organ, tissue in _VITAL_ORGAN_TISSUE.items():
        rec = by_tissue.get(tissue)
        med = rec.get("median_log2_abundance") if rec else None
        detected = med is not None
        above = detected and med >= ABUNDANCE_FLOOR_LOG2
        # Arm size: the ROW's own n_samples when this gene was quantified in the organ (authoritative,
        # and it falsifies the cache); otherwise the cached panel arm size, because a detected-only
        # product has no row to read it from precisely when the organ looks clean.
        row_n = rec.get("n_samples") if rec else None
        if _is_num(row_n):
            n_samples, n_src = int(row_n), "product_row"
        elif tissue in VITAL_ORGAN_N_SAMPLES:
            n_samples, n_src = VITAL_ORGAN_N_SAMPLES[tissue], "cached_panel_arm_size"
        else:
            # An organ absent from BOTH the gene's rows and the cached table: a new crosswalk entry or a
            # renamed part. Unknown arm size => NOT measurable (fail-closed on the measurability claim,
            # which keeps it out of the "well-powered and clean" count instead of quietly joining it).
            n_samples, n_src = None, "unknown"
        measurable = bool(n_samples is not None and n_samples >= MIN_SAMPLES_MEASURABLE)
        if detected:
            n_detected += 1
        if above:
            n_above += 1
        if measurable:
            n_measurable += 1
        else:
            n_unmeasurable += 1
        rows.append(
            {
                "organ": organ,
                "tissue": tissue,
                "median_log2_abundance": med,
                "detected": detected,
                "above_abundance_floor": above,
                "n_samples": n_samples,
                "n_samples_source": n_src,
                "n_detected": rec.get("n_detected") if rec else None,
                "detection_rate": rec.get("detection_rate") if rec else None,
                # False => this organ cannot support a presence/absence call (arm below
                # MIN_SAMPLES_MEASURABLE). Do NOT read it as "not expressed".
                "measurable": measurable,
            }
        )
    # abundance-sorted (highest vital-organ presence first; undetected organs last)
    rows.sort(key=lambda r: (r["median_log2_abundance"] is not None, r["median_log2_abundance"] or 0.0), reverse=True)
    if n_above >= 1:
        cls = "vital_organ_abundant"
    elif n_detected >= 1:
        cls = "vital_organ_low"
    else:
        # NOTE: still `no_vital_organ_signal`, not a new "partial coverage" token — the class vocabulary
        # is pinned in the contracts card. n_vital_organs_unmeasurable is what qualifies this value, and
        # a consumer reading the class WITHOUT that count is over-reading it by 2 organs of 13.
        cls = "no_vital_organ_signal"
    return rows, cls, n_above, n_measurable, n_unmeasurable


def compute_summary(gene: str, rows: list[dict]) -> dict:
    """Build the normal-tissue-protein comparator summary from the gene's per-tissue rows."""
    if not rows:
        return _empty_summary()

    # Per-tissue records (the DISPLAY list) + the abundance / breadth aggregates. The product stores
    # detected-only rows, so each row is a (tissue, tissue_class) where the protein was quantified.
    per_tissue: list[dict] = []
    adult_tissues: set[str] = set()
    fetal_tissues: set[str] = set()
    for r in rows:
        tissue = r.get("tissue")
        tclass = r.get("tissue_class")
        med = r.get("median_log2_abundance")
        det = r.get("detection_rate")
        # tissue_category (v2). Default SOLID_TISSUE_CATEGORY when the column is missing (a v1 product
        # read through this reader) — matching the producer's own fail-OPEN direction: an unrecognised
        # part counts toward breadth rather than vanishing from the denominator. Fail-open is right here
        # because dropping a part makes the liability veto fire LESS (see BROAD_ABUNDANT_TISSUE_COUNT).
        tcat = r.get("tissue_category") or SOLID_TISSUE_CATEGORY
        per_tissue.append(
            {
                "tissue": tissue,
                "tissue_class": tclass,
                "tissue_category": tcat,
                "median_log2_abundance": med if _is_num(med) else None,
                "median_intensity": r.get("median_intensity") if _is_num(r.get("median_intensity")) else None,
                "n_samples": r.get("n_samples"),
                "n_detected": r.get("n_detected"),
                "detection_rate": det if _is_num(det) else None,
            }
        )
        if tclass == _FETAL_CLASS:
            fetal_tissues.add(tissue)
        else:
            adult_tissues.add(tissue)

    # Sort the display list by abundance descending (highest normal-tissue expression first).
    per_tissue.sort(
        key=lambda t: (t["median_log2_abundance"] is not None, t["median_log2_abundance"] or 0.0), reverse=True
    )

    abundances = [t["median_log2_abundance"] for t in per_tissue if t["median_log2_abundance"] is not None]
    det_rates = [t["detection_rate"] for t in per_tissue if t["detection_rate"] is not None]

    # Highest-abundance tissue (across adult + fetal): the top of the sorted display list with a value.
    top = next((t for t in per_tissue if t["median_log2_abundance"] is not None), None)

    n_adult = len(adult_tissues)
    n_fetal = len(fetal_tissues)

    # ABUNDANCE FLOOR (Floor-C): # ADULT tissues whose median_log2_abundance is at/above the global
    # per-tissue floor. Counts distinct adult tissues (a tissue is "abundant" if its median clears the
    # floor), so it is robust to a single origin/outlier tissue spiking high (unlike a max).
    adult_above_floor: set[str] = set()
    for t in per_tissue:
        if (
            t["tissue_class"] != _FETAL_CLASS
            and t["median_log2_abundance"] is not None
            and t["median_log2_abundance"] >= ABUNDANCE_FLOOR_LOG2
        ):
            adult_above_floor.add(t["tissue"])
    n_adult_above_floor = len(adult_above_floor)

    # SOLID-ONLY companions to the two all-adult counts above. These are DECLARATION, not the class
    # inputs: _liability_class still keys on the all-adult numerator (see BROAD_ABUNDANT_TISSUE_COUNT for
    # why swapping the numerator under an absolute cut would fire the veto LESS, not more). Emitted so a
    # consumer can choose the 60-solid-part denominator, and so a future recalibration has both series.
    solid_adult = {
        t["tissue"]
        for t in per_tissue
        if t["tissue_class"] != _FETAL_CLASS and t["tissue_category"] == SOLID_TISSUE_CATEGORY
    }
    n_solid_above_floor = len(adult_above_floor & solid_adult)

    # Detected adult tissues whose arm is too small to support the call (n_samples < MIN_SAMPLES_MEASURABLE).
    # 21 of the 70 adult parts are in that state panel-wide, so a breadth count of K adult tissues can be
    # up to ~30% one-or-two-donor observations; this says how much of THIS target's K is low-support.
    n_adult_low_support = sum(
        1
        for t in per_tissue
        if t["tissue_class"] != _FETAL_CLASS and _is_num(t.get("n_samples")) and t["n_samples"] < MIN_SAMPLES_MEASURABLE
    )

    # uniprot_ac: 1:1 with the gene in this product (no ;-joined groups); take the first row's value.
    uniprot_ac = rows[0].get("uniprot_ac")

    # T0-3: dose-limiting-organ protein view (safety-facing), reusing the calibrated abundance floor.
    (
        vital_organ_abundance,
        vital_organ_liability_class,
        n_vital_above,
        n_vital_measurable,
        n_vital_unmeasurable,
    ) = _vital_organ_summary(per_tissue)

    return {
        "normal_protein_breadth_class": _breadth_class(n_adult),
        "tphp_normal_protein_liability_class": _liability_class(n_adult, n_adult_above_floor),
        "tphp_vital_organ_liability_class": vital_organ_liability_class,
        "n_vital_organs_above_abundance_floor": n_vital_above,
        # Qualifies the class above: how many dose-limiting organs the panel can actually SUPPORT a call
        # in. A no_vital_organ_signal over 11 measurable + 2 unmeasurable organs is not a clean sweep.
        "n_vital_organs_measurable": n_vital_measurable,
        "n_vital_organs_unmeasurable": n_vital_unmeasurable,
        "vital_organ_min_samples": MIN_SAMPLES_MEASURABLE,
        "tphp_vital_organ_abundance": vital_organ_abundance,
        "n_adult_tissues_above_abundance_floor": n_adult_above_floor,
        "abundance_floor_log2": ABUNDANCE_FLOOR_LOG2,
        "n_tissues_detected": len(adult_tissues | fetal_tissues),
        "n_adult_tissues_detected": n_adult,
        "n_adult_tissues_detected_low_support": n_adult_low_support,
        "n_solid_adult_tissues_detected": len(solid_adult),
        "n_solid_adult_tissues_above_abundance_floor": n_solid_above_floor,
        "n_fetal_groups_detected": n_fetal,
        "n_adult_tissues_total": N_ADULT_TISSUES_TOTAL,
        "n_solid_adult_tissues_total": N_SOLID_ADULT_TISSUES_TOTAL,
        "n_fetal_groups_total": N_FETAL_GROUPS_TOTAL,
        "max_median_log2_abundance": max(abundances) if abundances else None,
        "median_across_tissues_log2_abundance": (round(statistics.median(abundances), 6) if abundances else None),
        "highest_abundance_tissue": top["tissue"] if top else None,
        "highest_abundance_tissue_class": top["tissue_class"] if top else None,
        "fetal_vs_adult_flag": _fetal_vs_adult_flag(n_adult, n_fetal),
        "max_detection_rate": max(det_rates) if det_rates else None,
        "uniprot_ac": uniprot_ac,
        "per_tissue_abundance": per_tissue,
        "method_version": METHOD_VERSION,
    }


def load_and_classify(gene: str, product_path=None) -> dict:
    """Full pipeline: pushdown-read the gene's per-tissue normal-protein rows → comparator summary."""
    rows = _read_rows_from_derived(gene, product_path=product_path)
    return compute_summary(gene, rows)


def read_target_summary(target: str, indication: Optional[str] = None, product_path=None) -> dict:
    """Per-target TPHP normal-tissue-protein comparator via streamed pushdown.

    Args:
        target: HGNC gene symbol (the product's `gene_symbol` pushdown key).
        indication: unused (a normal-tissue footprint is a gene-level property); accepted for the
            generic-dispatch contract signature but NOT consumed.
        product_path: offline test seam — a local parquet path bypasses S3.

    Returns:
        The normal-tissue-protein comparator summary. Never raises on target-not-found — returns
        normal_protein_breadth_class='data_unavailable'. A transient/creds/broken-env fault surfaces
        _live_read_error (so the compose path degrades honestly instead of crashing).
    """
    try:
        return load_and_classify(target, product_path=product_path)
    except Exception as e:  # noqa: BLE001
        # A GENUINE product-object absence (NoSuchKey/404 or FileNotFoundError) → honest
        # data_unavailable. A transient/creds/broken-env error must NOT be masked as an empty normal
        # footprint — re-raise so the live-read seam surfaces _live_read_error instead of a silent
        # dead comparator (mirrors collectri_tf_regulon.read).
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        out = _empty_summary()
        out["_live_read_error"] = "tphp_normal_protein_read_failed"
        out["_remediation"] = (
            f"Could not read the TPHP normal-tissue protein product ({DERIVED_MANIFEST_ID}) for {target}: {e}"
        )
        return out


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="TPHP normal-tissue protein abundance for a target.")
    ap.add_argument("--target", default=None)
    ap.add_argument("--product-path", default=None, help="offline: local parquet path (bypasses S3)")
    # The recalibration entrypoint for ABUNDANCE_FLOOR_LOG2. compute_abundance_floor previously had NO
    # caller anywhere in the tree: the constant it derives is the cut of a VERDICT-BEARING safety class,
    # and the only way to check it against the live product was to reimplement the derivation by hand.
    # Reports the re-derived floor next to the cached constant and their drift, so a product refresh is
    # a command rather than an archaeology dig. Read-only — never rewrites the constant.
    ap.add_argument(
        "--recompute-floor",
        action="store_true",
        help="re-derive ABUNDANCE_FLOOR_LOG2 from the product's own distribution and report drift vs the cached constant",
    )
    ap.add_argument("--percentile", type=int, default=ABUNDANCE_FLOOR_PERCENTILE)
    args = ap.parse_args(argv)

    if args.recompute_floor:
        derived = compute_abundance_floor(product_path=args.product_path, percentile=args.percentile)
        print(
            json.dumps(
                {
                    "percentile": args.percentile,
                    "recomputed_abundance_floor_log2": round(derived, 6),
                    "cached_abundance_floor_log2": ABUNDANCE_FLOOR_LOG2,
                    "drift": round(derived - ABUNDANCE_FLOOR_LOG2, 6),
                    "product": args.product_path or DERIVED_MANIFEST_ID,
                    "note": "read-only; update ABUNDANCE_FLOOR_LOG2 by hand if the drift is material",
                },
                indent=2,
            )
        )
        return 0

    if not args.target:
        ap.error("--target is required unless --recompute-floor is given")
    print(json.dumps(read_target_summary(args.target, product_path=args.product_path), indent=2, default=str))
    return 0


if __name__ == "__main__":
    _main()
