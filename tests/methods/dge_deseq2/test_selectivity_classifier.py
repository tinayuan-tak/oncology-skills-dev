"""Coverage for _classify_selectivity_from_sensitivity — the v3 tumor-vs-normal selectivity
classifier and the home of the backtest-driven FIX-2 field-effect rescue.

The 2026-08-08 selectivity review found this classifier — which encodes the calibration that stopped
CEACAM5/EPCAM being swallowed as discordant — had NO test. These pure-function tests pin those
invariants so a future edit to the magnitude gate or the field-effect rescue can't silently regress
them.

Row shape mirrors the reader's internal sensitivity row-dict: log2fc_cell_{a,c},
q_value_cell_{a,c}, cells_supporting, cells_ran, dominant_direction, discordant. Cell B (the ComBat
re-run of cell A on the SAME samples) was removed in analysis-methods#727 — the FIX-1 "ComBat
de-weight" tests that lived here are gone with it, since the magnitude gate now has only the two raw
comparators A and C to key on. A stray log2fc_cell_b from a not-yet-rebuilt product is never read.

2026-09-12 (FIX 4, comparator independence): the fixtures below now carry q_value_cell_* wherever
they claim support. They previously asserted support through `cells_supporting=3` while leaving every
q-value None — a shape the producer NEVER emits (a significant cell always has a padj), so the
assertions rode on a field the real product always populates and the classifier no longer reads.
The classifier now derives support from the two comparator FAMILIES via their q-values, which made
the omission load-bearing and surfaced it. Take fixture values from shapes the producer can emit.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dge_deseq2.read import _classify_selectivity_from_sensitivity as classify  # noqa: E402


def _row(**kw):
    base = dict(
        cells_ran=2,
        cells_supporting=2,
        dominant_direction="up",
        discordant=False,
        log2fc_cell_a=None,
        q_value_cell_a=None,
        log2fc_cell_c=None,
        q_value_cell_c=None,
    )
    base.update(kw)
    return base


# ── core ladder ─────────────────────────────────────────────────────────────
def test_strong_requires_full_support_and_raw_magnitude():
    # both comparator families sig-up, raw cell A & C both >= 1.5 → strong
    r = _row(log2fc_cell_a=1.8, q_value_cell_a=1e-6, log2fc_cell_c=2.0, q_value_cell_c=1e-6)
    assert classify(r) == "strong_tumor_selective"


def test_modest_at_full_family_support_and_half_magnitude():
    # Both families agree, but the raw magnitude sits in [0.5, 1.5) → modest, not strong.
    # (Was `test_modest_at_two_thirds_and_half_magnitude`: with a two-FAMILY denominator the
    # fraction can only be 0, 1/2 or 1, so there is no 2/3 tier to land on — the modest band is now
    # unanimity at sub-strong magnitude. The old 2/3 was cells A+B, one comparator counted twice.)
    r = _row(log2fc_cell_a=0.8, q_value_cell_a=1e-6, log2fc_cell_c=0.6, q_value_cell_c=1e-6)
    assert classify(r) == "modest_tumor_selective"


def test_down_direction_full_support_is_not_selective():
    r = _row(
        dominant_direction="down", log2fc_cell_a=-2.0, q_value_cell_a=1e-6, log2fc_cell_c=-1.9, q_value_cell_c=1e-6
    )
    assert classify(r) == "not_selective"


def test_one_of_two_families_is_not_support():
    # The adjacent family (cell A) is sig-up but the GTEx family RAN and did not concur → 1/2, not
    # support. This is the 12,492 shipped rows that used to reach `modest` on cells A+B (one
    # comparator counted twice) clearing a 2/3 bar with cell C measured and dissenting.
    r = _row(
        log2fc_cell_a=2.0,
        q_value_cell_a=1e-6,
        log2fc_cell_c=0.1,
        q_value_cell_c=0.80,  # GTEx measured this gene and saw nothing
    )
    assert classify(r) == "not_informative"


def test_empty_or_missing_is_data_unavailable():
    assert classify({}) == "data_unavailable"
    # data_unavailable now means NO comparator family produced an estimate — not "cells_ran is 0".
    # cells_ran / cells_supporting are provenance only; they no longer drive the class, so a row
    # with real per-cell estimates must NOT read data_unavailable however they are set.
    assert classify(_row(log2fc_cell_a=None, log2fc_cell_c=None)) == "data_unavailable"
    assert classify(_row(cells_ran=0, cells_supporting=None, log2fc_cell_c=2.0, q_value_cell_c=1e-6)) != (
        "data_unavailable"
    )


# ── FIX 2 (field-effect rescue): CEACAM5/EPCAM pattern ───────────────────────
def test_field_effect_rescue_when_adjacent_flat_gtex_strong_up():
    # discordant; adjacent (cell A) sig-DOWN (field cancerization), GTEx cell C strongly up & sig.
    r = _row(
        discordant=True,
        log2fc_cell_a=-0.3,
        q_value_cell_a=0.02,  # adjacent down (field effect)
        log2fc_cell_c=2.4,
        q_value_cell_c=0.001,
    )  # GTEx strongly up
    assert classify(r) == "field_effect_tumor_selective"


def test_field_effect_NOT_rescued_when_gtex_only_weakly_up():
    # discordant; GTEx up but < 1.5 → does NOT clear the rescue bar → stays a genuine conflict
    r = _row(discordant=True, log2fc_cell_a=-0.3, q_value_cell_a=0.02, log2fc_cell_c=1.1, q_value_cell_c=0.01)
    assert classify(r) == "discordant_across_comparators"


def test_field_effect_NOT_rescued_when_adjacent_is_significantly_up():
    # discordant; adjacent A significantly UP → not the field-effect signature → genuine conflict
    r = _row(
        discordant=True,
        log2fc_cell_a=1.2,
        q_value_cell_a=0.01,  # adjacent UP (not flat/down)
        log2fc_cell_c=2.4,
        q_value_cell_c=0.001,
    )
    assert classify(r) == "discordant_across_comparators"
