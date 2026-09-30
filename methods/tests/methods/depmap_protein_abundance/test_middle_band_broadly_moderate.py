"""Regression: middle-band (30–70% detected) classification must consult per_lineage.

Bug: classify_protein_abundance ignored its per_lineage arg — the guard `LINEAGE_RESTRICTED_MIN <= f
<= LINEAGE_RESTRICTED_MAX` (0.10..0.70) is ALWAYS true for any f in the middle band, so it returned
`lineage_restricted` unconditionally and the final `broadly_moderate` was unreachable. A protein
detected in ~50% of the panel but SPREAD across many lineages was mislabeled lineage_restricted.

Fix (#365): in the middle band, lineage_restricted requires the detected footprint to be CONCENTRATED
in a minority of lineages (few lineages, or one dominating); a moderate pan-lineage detection rate is
broadly_moderate.

COMPLETED 2026-09-15 — #365 was a PARTIAL fix shaped like a total one. It closed the SPREAD case but
deliberately carved out "no per-lineage data → historical lineage_restricted", and the last test below
pinned that carve-out as intended behaviour. For any caller WITHOUT a lineage map the carve-out is the
ONLY reachable branch, which is the entire ProCan reader (Sanger SIDM ids have no OncotreeLineage
crosswalk, so per_lineage is always empty). So the concentration predicate stayed unfalsifiable there
and 85 of 343 ProCan corpus cards asserted lineage restriction on zero lineage evidence — exactly the
set whose fraction_detected fell in this band. An absent breakdown now yields sub_broad_detection: the
detection band only, with no lineage claim in either direction."""

from __future__ import annotations

import importlib

cli = importlib.import_module("onc_methods.depmap_protein_abundance.cli")


def test_middle_band_spread_across_lineages_is_broadly_moderate():
    # ~50% detected, spread across 10 lineages with no dominant one → broadly_moderate (the case
    # that was unreachable before the fix).
    per_lineage = [{"lineage": f"L{i}", "n": 6} for i in range(10)]  # 10 lineages, top share 0.10
    assert (
        cli.classify_protein_abundance(
            fraction_detected=0.50, median_abundance=0.5, per_lineage=per_lineage, high_cutoff=1.0
        )
        == "broadly_moderate"
    )


def test_middle_band_concentrated_is_lineage_restricted():
    # ~50% detected but concentrated: 2 lineages carry it → lineage_restricted.
    per_lineage = [{"lineage": "L0", "n": 30}, {"lineage": "L1", "n": 20}]
    assert (
        cli.classify_protein_abundance(
            fraction_detected=0.50, median_abundance=0.5, per_lineage=per_lineage, high_cutoff=1.0
        )
        == "lineage_restricted"
    )


def test_middle_band_one_lineage_dominates_is_lineage_restricted():
    # spread nominally across many lineages, but one holds >= 50% of detected lines → concentrated.
    per_lineage = [{"lineage": "L0", "n": 60}] + [{"lineage": f"L{i}", "n": 6} for i in range(1, 6)]
    assert (
        cli.classify_protein_abundance(
            fraction_detected=0.50, median_abundance=0.5, per_lineage=per_lineage, high_cutoff=1.0
        )
        == "lineage_restricted"
    )


def test_middle_band_no_lineage_data_makes_no_lineage_claim():
    # empty per_lineage (ProCan, or a unit test with no model table) → sub_broad_detection: state the
    # detection band, claim nothing about lineage. This asserted `lineage_restricted` — the #365
    # carve-out — until 2026-09-15; see the module docstring for why that was unfalsifiable rather
    # than merely optimistic.
    assert (
        cli.classify_protein_abundance(fraction_detected=0.35, median_abundance=0.1, per_lineage=[], high_cutoff=0.2)
        == "sub_broad_detection"
    )
