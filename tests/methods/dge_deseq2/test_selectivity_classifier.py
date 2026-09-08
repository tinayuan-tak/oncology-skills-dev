"""Coverage for _classify_selectivity_from_sensitivity — the v3 tumor-vs-normal selectivity
classifier and the home of the two backtest-driven calibration fixes (FIX-1 ComBat de-weight,
FIX-2 field-effect rescue).

The 2026-08-08 selectivity review found this classifier — which encodes the exact calibration
that stopped GAPDH reading false-strong (via an inflated ComBat cell B) and stopped CEACAM5/EPCAM
being swallowed as discordant — had NO test. These pure-function tests pin those invariants so a
future edit to the magnitude gate or the field-effect rescue can't silently regress them.

Row shape mirrors the reader's internal sensitivity row-dict: log2fc_cell_{a,b,c},
q_value_cell_{a,b,c}, cells_supporting, cells_ran, dominant_direction, discordant.
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
        cells_ran=3,
        cells_supporting=3,
        dominant_direction="up",
        discordant=False,
        log2fc_cell_a=None,
        q_value_cell_a=None,
        log2fc_cell_b=None,
        q_value_cell_b=None,
        log2fc_cell_c=None,
        q_value_cell_c=None,
    )
    base.update(kw)
    return base


# ── core ladder ─────────────────────────────────────────────────────────────
def test_strong_requires_full_support_and_raw_magnitude():
    # 3/3 up, raw cell A & C both >= 1.5 → strong
    r = _row(log2fc_cell_a=1.8, log2fc_cell_c=2.0)
    assert classify(r) == "strong_tumor_selective"


def test_modest_at_two_thirds_and_half_magnitude():
    r = _row(cells_supporting=2, log2fc_cell_a=0.8, log2fc_cell_c=0.6)
    assert classify(r) == "modest_tumor_selective"


def test_down_direction_full_support_is_not_selective():
    r = _row(dominant_direction="down", log2fc_cell_a=-2.0, log2fc_cell_c=-1.9)
    assert classify(r) == "not_selective"


def test_low_support_is_not_informative():
    r = _row(cells_supporting=1, log2fc_cell_a=2.0, log2fc_cell_c=2.0)
    assert classify(r) == "not_informative"


def test_empty_or_missing_is_data_unavailable():
    assert classify({}) == "data_unavailable"
    assert classify(_row(cells_ran=0)) == "data_unavailable"
    assert classify(_row(cells_supporting=None)) == "data_unavailable"


# ── FIX 1 (ComBat de-weight): cell B alone cannot confer strong/modest ───────
def test_combat_cellB_alone_does_NOT_confer_strong():
    # GAPDH/COADREAD archetype: raw A & C modest (<1.5), ComBat cell B artifactually inflated to 4.8.
    # The magnitude gate keys on raw A/C only → B's 4.8 is excluded → NOT strong.
    r = _row(log2fc_cell_a=1.0, log2fc_cell_c=1.2, log2fc_cell_b=4.8)
    assert classify(r) != "strong_tumor_selective"  # the housekeeping false-strong is blocked
    # A=1.0/C=1.2 still clear the modest gate (>=0.5, 3/3 up) — that's the raw-comparator call
    assert classify(r) == "modest_tumor_selective"


def test_combat_cellB_cannot_manufacture_magnitude_from_flat_raw():
    # raw A & C both flat (<0.5); only ComBat B is large → below the modest raw floor → not strong/modest
    r = _row(log2fc_cell_a=0.2, log2fc_cell_c=0.3, log2fc_cell_b=4.8)
    assert classify(r) not in ("strong_tumor_selective", "modest_tumor_selective")


# ── FIX 2 (field-effect rescue): CEACAM5/EPCAM pattern ───────────────────────
def test_field_effect_rescue_when_adjacent_flat_gtex_strong_up():
    # discordant; adjacent (A+B) NOT sig-up (field cancerization), GTEx cell C strongly up & sig.
    r = _row(
        discordant=True,
        log2fc_cell_a=-0.3,
        q_value_cell_a=0.02,  # adjacent down (field effect)
        log2fc_cell_b=0.1,
        q_value_cell_b=0.9,  # adjacent flat
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
