"""Regression: a lineage-RESTRICTED surface antigen detected in a MINORITY of the pan-cancer panel
must be classed `lineage_restricted`, not `broadly_low`.

Bug (tumor-presence expert review, G1): `classify_protein_abundance` short-circuited
`if f < LOW_DETECTION_FRACTION (0.30): return "broadly_low"` BEFORE the
`LINEAGE_RESTRICTED_MIN (0.10) <= f <= LINEAGE_RESTRICTED_MAX (0.70)` band, so the entire
[0.10, 0.30) detection range could never be classed `lineage_restricted` — it was pre-empted as
`broadly_low`. Whole-cell shotgun TMT under-samples membrane/low-copy proteins, so a genuinely
lineage-restricted surface antigen (e.g. CLDN18 / the CLDN18.2 zolbetuximab target) detected in only
10-29% of the Gygi panel was mislabeled absent, firing `protein-abundance-broadly-low-degrader-killer`
(a hard degrader-killer) and the tumor-presence `present_rna_only_protein_absent` demotion on exactly
the surface antigens the framework nominates.

Fix: the lineage-concentration check runs BEFORE the low-detection floor. In the low sub-band
[MIN, LOW) it requires REAL per-lineage evidence of concentration (empty per_lineage stays
`broadly_low`, so unit-test / no-model-table behavior is unchanged); below MIN the panel is too sparse
to assert restriction and stays `broadly_low`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

cli = importlib.import_module("methods.depmap_protein_abundance.cli")


def test_low_band_concentrated_is_lineage_restricted_not_broadly_low():
    # ~18% detected (below the 0.30 low-detection floor) but CONCENTRATED in 2 lineages
    # (stomach + lung, the CLDN18 footprint) → lineage_restricted, NOT broadly_low.
    per_lineage = [{"lineage": "Stomach", "n": 12}, {"lineage": "Lung", "n": 8}]
    assert (
        cli.classify_protein_abundance(
            fraction_detected=0.18, median_abundance=0.4, per_lineage=per_lineage, high_cutoff=1.0
        )
        == "lineage_restricted"
    )


def test_low_band_one_lineage_dominates_is_lineage_restricted():
    # nominally several lineages but one holds >= 50% of detected lines → concentrated → restricted.
    per_lineage = [{"lineage": "Stomach", "n": 20}] + [{"lineage": f"L{i}", "n": 3} for i in range(1, 6)]
    assert (
        cli.classify_protein_abundance(
            fraction_detected=0.22, median_abundance=0.3, per_lineage=per_lineage, high_cutoff=1.0
        )
        == "lineage_restricted"
    )


def test_low_band_spread_across_many_lineages_stays_broadly_low():
    # low detection genuinely spread across many lineages with no dominant one → still broadly_low
    # (this is real MS-absence / housekeeping-floor, not lineage restriction).
    per_lineage = [{"lineage": f"L{i}", "n": 2} for i in range(10)]  # 10 lineages, top share 0.10
    assert (
        cli.classify_protein_abundance(
            fraction_detected=0.20, median_abundance=0.1, per_lineage=per_lineage, high_cutoff=1.0
        )
        == "broadly_low"
    )


def test_low_band_no_lineage_evidence_stays_broadly_low():
    # low detection with NO per-lineage breakdown → broadly_low (unchanged; cannot assert restriction
    # without lineage evidence — preserves test_broadly_low_when_detection_sparse).
    assert (
        cli.classify_protein_abundance(fraction_detected=0.20, median_abundance=0.5, per_lineage=[], high_cutoff=0.4)
        == "broadly_low"
    )


def test_very_sparse_below_min_stays_broadly_low_even_if_concentrated():
    # below LINEAGE_RESTRICTED_MIN (0.10): too sparse to call restriction even if concentrated.
    per_lineage = [{"lineage": "Stomach", "n": 4}, {"lineage": "Lung", "n": 3}]
    assert (
        cli.classify_protein_abundance(
            fraction_detected=0.05, median_abundance=0.4, per_lineage=per_lineage, high_cutoff=1.0
        )
        == "broadly_low"
    )
