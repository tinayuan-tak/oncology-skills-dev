"""HRD genomic-scar score — a homologous-recombination-deficiency score based on genomic scars.
NOTE: this score is implemented here but NOT wired into any card (deferred); the card currently
surfaces only the SBS3 signature proxy.

HRD-score = HRD-LOH + LST + ntAI, the three orthogonal genomic-scar counts, each a distinct
footprint of failed homologous-recombination repair (the sum is the "HRD score" / "genomic scar
score" clinically used as a PARP-sensitivity biomarker; Myriad myChoice sums the same three):

  HRD-LOH  (Abkevich 2012)  — number of LOH regions > 15 Mb but NOT covering a whole chromosome.
                              (whole-chromosome LOH reflects mitotic missegregation, not HR repair.)
  LST      (Popova 2012)    — Large-scale State Transitions: breakpoints between two adjacent
                              segments each >= 10 Mb, after smoothing/removing segments < 3 Mb.
                              Counted per chromosome ARM (a transition cannot cross the centromere).
  ntAI     (Birkbak 2012)   — number of sub-chromosomal regions with Allelic Imbalance that extend
                              to a telomere but do NOT cross the centromere (telomeric AI).

Computed per sample from the PanCanAtlas ABSOLUTE allele-specific segtabs
(TCGA_mastercalls.abs_segtabs.fixed.txt): columns Modal_HSCN_1/Modal_HSCN_2 (the two
haplotype-specific copy numbers), Modal_Total_CN, LOH (per-segment flag), Length, Start/End, and
Chromosome (1..23; 23 = X). HRD scar counts are conventionally computed on the AUTOSOMES (1..22);
X is excluded (its allelic state is confounded by sex / X-inactivation).

This is a genuine DERIVATION — the scar counts exist in no landed file; only the raw allele-specific
segments do. Cohort roll-up mirrors the aneuploidy/WGD arms: per-indication fraction of samples that
are HRD-high (score >= 42, the Myriad myChoice clinical cutoff).
"""

from __future__ import annotations

from typing import Optional

# --- Scar-scoring thresholds (from the defining papers; MB in base pairs) ---
_MB = 1_000_000
HRD_LOH_MIN_MB = 15 * _MB  # Abkevich 2012: LOH region must exceed 15 Mb
LST_MIN_SEG_MB = 10 * _MB  # Popova 2012: each flanking segment >= 10 Mb
LST_SMOOTH_MB = 3 * _MB  # Popova 2012: remove/merge segments < 3 Mb before counting
# HRD-high clinical cutoff on the summed score (Myriad myChoice / Telli 2016): >= 42.
HRD_HIGH_SCORE = 42
# Cohort HRD-prevalence class cutoffs on the FRACTION of samples that are HRD-high.
_HRD_COHORT_HIGH = 0.20
_HRD_COHORT_LOW = 0.05

# hg19 centromere positions (Mb midpoint used as the arm boundary) for chromosomes 1..22.
# Source: UCSC hg19 gaps (centromere). ABSOLUTE segtabs are hg19-based (PanCanAtlas 2018).
# We only need the centromere coordinate to split p/q arms and detect whole-chromosome spans.
_HG19_CENTROMERE = {
    1: 125_000_000,
    2: 93_300_000,
    3: 91_000_000,
    4: 50_400_000,
    5: 48_400_000,
    6: 61_000_000,
    7: 59_900_000,
    8: 45_600_000,
    9: 49_000_000,
    10: 40_200_000,
    11: 53_700_000,
    12: 35_800_000,
    13: 17_900_000,
    14: 17_600_000,
    15: 19_000_000,
    16: 36_600_000,
    17: 24_000_000,
    18: 17_200_000,
    19: 26_500_000,
    20: 27_500_000,
    21: 13_200_000,
    22: 14_700_000,
}
# hg19 chromosome lengths (bp) 1..22 — for the whole-chromosome-LOH exclusion + telomere detection.
_HG19_CHROM_LEN = {
    1: 249_250_621,
    2: 243_199_373,
    3: 198_022_430,
    4: 191_154_276,
    5: 180_915_260,
    6: 171_115_067,
    7: 159_138_663,
    8: 146_364_022,
    9: 141_213_431,
    10: 135_534_747,
    11: 135_006_516,
    12: 133_851_895,
    13: 115_169_878,
    14: 107_349_540,
    15: 102_531_392,
    16: 90_354_753,
    17: 81_195_210,
    18: 78_077_248,
    19: 59_128_983,
    20: 63_025_520,
    21: 48_129_895,
    22: 51_304_566,
}
# A segment "reaches" a telomere / centromere if within this slack of the boundary (probe/segment
# resolution — ABSOLUTE segment ends rarely hit the exact base). 3 Mb is the Birkbak 2012 practice.
_BOUNDARY_SLACK = 3 * _MB

_AUTOSOMES = tuple(range(1, 23))


def _is_allelic_imbalance(hscn1, hscn2) -> bool:
    """Allelic imbalance = the two haplotype-specific copy numbers differ (incl. LOH, where one is 0)."""
    if hscn1 is None or hscn2 is None:
        return False
    try:
        return int(round(float(hscn1))) != int(round(float(hscn2)))
    except (TypeError, ValueError):
        return False


def _arm_of(start: int, end: int, chrom: int) -> Optional[str]:
    """'p', 'q', or None if the segment spans the centromere (cross-arm segments are excluded from
    the arm-local scar counts). Uses the segment midpoint only when it clearly sits on one arm."""
    cen = _HG19_CENTROMERE.get(chrom)
    if cen is None:
        return None
    if end <= cen:
        return "p"
    if start >= cen:
        return "q"
    return None  # spans the centromere


def hrd_scars_for_sample(segments: list[dict]) -> dict:
    """Compute (hrd_loh, lst, ntai, hrd_score) for ONE sample's autosomal segments.

    `segments`: list of dicts with keys Chromosome, Start, End, Length, Modal_HSCN_1, Modal_HSCN_2,
    LOH (0/1). Rows for chromosome 23 (X) and rows missing geometry are ignored.
    """
    # bucket segments by chromosome, autosomes only, sorted by Start
    by_chrom: dict[int, list[dict]] = {}
    for s in segments:
        try:
            chrom = int(round(float(s["Chromosome"])))
        except (TypeError, ValueError, KeyError):
            continue
        if chrom not in _AUTOSOMES:
            continue
        try:
            start = float(s["Start"])
            end = float(s["End"])
        except (TypeError, ValueError, KeyError):
            continue
        by_chrom.setdefault(chrom, []).append(
            {
                "start": start,
                "end": end,
                "length": float(s.get("Length") or (end - start)),
                "loh": _truthy(s.get("LOH")),
                "ai": _is_allelic_imbalance(s.get("Modal_HSCN_1"), s.get("Modal_HSCN_2")),
            }
        )

    hrd_loh = 0
    lst = 0
    ntai = 0
    for chrom, segs in by_chrom.items():
        segs.sort(key=lambda x: x["start"])
        chrom_len = _HG19_CHROM_LEN[chrom]
        cen = _HG19_CENTROMERE[chrom]

        # --- HRD-LOH: LOH segments > 15 Mb that do NOT span the whole chromosome ---
        for sg in segs:
            if sg["loh"] and sg["length"] > HRD_LOH_MIN_MB:
                spans_whole = sg["start"] <= _BOUNDARY_SLACK and sg["end"] >= chrom_len - _BOUNDARY_SLACK
                if not spans_whole:
                    hrd_loh += 1

        # --- ntAI: allelic-imbalance segments touching a telomere, not crossing the centromere ---
        for sg in segs:
            if not sg["ai"]:
                continue
            touches_p_tel = sg["start"] <= _BOUNDARY_SLACK
            touches_q_tel = sg["end"] >= chrom_len - _BOUNDARY_SLACK
            crosses_cen = sg["start"] < cen < sg["end"]
            if (touches_p_tel or touches_q_tel) and not crosses_cen:
                # exclude the whole-chromosome case (both telomeres) — that is not telomeric AI
                if not (touches_p_tel and touches_q_tel):
                    ntai += 1

        # --- LST: transitions between adjacent >=10 Mb segments, per arm, after <3 Mb smoothing ---
        for arm in ("p", "q"):
            arm_segs = [sg for sg in segs if _arm_of(sg["start"], sg["end"], chrom) == arm]
            smoothed = _smooth(arm_segs)
            # count adjacent pairs where both flanks are >= 10 Mb (a large-scale state transition)
            for a, b in zip(smoothed, smoothed[1:]):
                if a["length"] >= LST_MIN_SEG_MB and b["length"] >= LST_MIN_SEG_MB:
                    lst += 1

    return {
        "hrd_loh": hrd_loh,
        "lst": lst,
        "ntai": ntai,
        "hrd_score": hrd_loh + lst + ntai,
    }


def _smooth(arm_segs: list[dict]) -> list[dict]:
    """Popova 2012 smoothing: iteratively remove segments < 3 Mb (they are merged into the adjacent
    run). We drop sub-3 Mb segments; the remaining large segments are what LST transitions count
    between. Returns the retained (>=3 Mb) segments in order."""
    return [sg for sg in arm_segs if sg["length"] >= LST_SMOOTH_MB]


def _truthy(v) -> bool:
    if v is None:
        return False
    try:
        return float(v) >= 1.0
    except (TypeError, ValueError):
        return str(v).strip().lower() in ("1", "true", "yes", "loh")


def classify_hrd_cohort(hrd_high_fraction: Optional[float]) -> str:
    if hrd_high_fraction is None:
        return "data_unavailable"
    if hrd_high_fraction >= _HRD_COHORT_HIGH:
        return "hrd_enriched"
    if hrd_high_fraction <= _HRD_COHORT_LOW:
        return "hrd_rare"
    return "hrd_intermediate"
