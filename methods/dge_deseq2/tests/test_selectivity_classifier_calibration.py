"""_classify_selectivity_from_sensitivity — calibration fixes (backtest-driven, 2026-08-07).

Pins the two calibration fixes found by the ground-truth backtest
(feedback_selectivity_calibration_backtest):
  FIX 1 — the magnitude gate keys on RAW comparators (cell A + cell C), NOT the ComBat cell B, so an
          inflated/sign-flipped ComBat B can't by itself confer strong/modest.
  FIX 2 — a discordant row with the FIELD-EFFECT signature (adjacent A/B flat-or-down + GTEx C
          strongly up >=1.5) resolves to `field_effect_tumor_selective` (GTEx-anchored tumour-
          selective) instead of terminal `discordant_across_comparators`.
Plus regression pins on the unchanged bands + the down/not_selective + true-negative paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Portable repo root: was hardcoded to the author's /home/sagemaker-user checkout, so every
# path guard below read as "data missing" on a CI runner or in a worktree.
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
# load the WORKTREE copy explicitly (test runs against the patched classifier)
WT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WT))
from methods.dge_deseq2 import read as dge  # noqa: E402


def _row(**kw):
    r = {
        "cells_ran": 3,
        "cells_supporting": None,
        "dominant_direction": None,
        "discordant": False,
        "log2fc_cell_a": None,
        "q_value_cell_a": None,
        "log2fc_cell_b": None,
        "q_value_cell_b": None,
        "log2fc_cell_c": None,
        "q_value_cell_c": None,
        "max_abs_log2fc": None,
    }
    r.update(kw)
    return r


# --- FIX 1: ComBat cell B cannot alone confer magnitude ---


def test_combat_B_alone_does_not_confer_strong():
    # raw cells A + C are BELOW 1.5; only the ComBat cell B is inflated → must NOT be strong.
    r = _row(
        cells_supporting=3,
        dominant_direction="up",
        log2fc_cell_a=0.9,
        q_value_cell_a=0.01,
        log2fc_cell_b=4.8,
        q_value_cell_b=0.01,  # ComBat inflated
        log2fc_cell_c=0.8,
        q_value_cell_c=0.01,
        max_abs_log2fc=4.8,
    )  # legacy max (across all) would say strong
    out = dge._classify_selectivity_from_sensitivity(r)
    assert out != "strong_tumor_selective"
    # raw_max = max(0.9, 0.8) = 0.9 → modest (>=0.5), not strong
    assert out == "modest_tumor_selective"


def test_raw_cell_A_high_still_strong():
    # a genuine signal: raw cell A itself clears 1.5 → strong (Fix 1 doesn't punish real raw signal)
    r = _row(
        cells_supporting=3,
        dominant_direction="up",
        log2fc_cell_a=4.7,
        q_value_cell_a=1e-9,
        log2fc_cell_b=4.9,
        q_value_cell_b=1e-9,
        log2fc_cell_c=1.2,
        q_value_cell_c=1e-9,
        max_abs_log2fc=4.9,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "strong_tumor_selective"


def test_raw_cell_C_high_confers_magnitude_when_the_adjacent_arm_ALSO_ran():
    # Fix 1's raw-magnitude gate accepts cell C as a RAW comparator — a high C is real magnitude, not
    # a ComBat artefact. Pin that with the adjacent family also measured and agreeing, so this test
    # isolates MAGNITUDE (Fix 1) from EVIDENCE BASE (Fix 4b, below).
    r = _row(
        cells_ran=3,
        cells_supporting=3,
        dominant_direction="up",
        log2fc_cell_a=1.1,
        q_value_cell_a=1e-8,
        log2fc_cell_b=1.2,
        q_value_cell_b=1e-8,
        log2fc_cell_c=9.9,
        q_value_cell_c=1e-50,
        max_abs_log2fc=9.9,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "strong_tumor_selective"


def test_gtex_only_no_adjacent_arm_is_modest_NOT_strong_fix4b():
    """REVERSES a 2026-08-07 pin (#221, e36fef6), deliberately.

    That commit asserted `GTEx-only single-cell strong (FOLR1/MSLN pattern): C high, A/B absent →
    strong`. Measured 2026-09-12 across all 29 shipped sensitivity products: that path mints 32,784
    `strong` calls in 7 indications (ACC, LGG, OV, SCLC, SKCM, TGCT, UCS) that have NO adjacent-normal
    arm at all — every row scores cells_ran=1 / cells_supporting=1 → frac 1.0 → strong on the
    TCGA-vs-GTEx contrast ALONE, which is the platform/batch confound cell D was RETIRED for. The
    nomination gate weights `strong` DOMINANT, so an unreplicated single-arm result was driving
    verdicts.

    The demotion is to `modest`, not to nothing: the biology is frequently real (FOLR1/OV C=+9.95,
    CLDN6/OV C=+12.18, DLL3/SCLC C=+5.02 all remain axis-A selective). What changes is the CLAIM —
    single-armed evidence may not read as the framework's strongest band. Note FOLR1 is one of the
    2026-08-07 backtest's own ground-truth antigens, and the same FIX 4 PROMOTES MSLN/PAAD, the
    other one, from modest to strong (a non-significant ComBat cell B had been diluting a genuine
    cell-A + cell-C agreement); the backtest anchors do not all move the same way.
    """
    r = _row(
        cells_ran=1,
        cells_supporting=1,
        dominant_direction="up",
        log2fc_cell_c=9.9,
        q_value_cell_c=1e-50,
        max_abs_log2fc=9.9,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "modest_tumor_selective"


# --- FIX 2: field-effect-aware discordant ---


def test_field_effect_signature_recovers_selective():
    # CEACAM5/COADREAD pattern: adjacent A/B flat-or-DOWN + GTEx C strongly UP → field_effect subclass
    r = _row(
        discordant=True,
        dominant_direction="up",
        log2fc_cell_a=-0.30,
        q_value_cell_a=0.05,
        log2fc_cell_b=-0.49,
        q_value_cell_b=0.002,
        log2fc_cell_c=2.94,
        q_value_cell_c=1e-110,
        max_abs_log2fc=2.94,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "field_effect_tumor_selective"


def test_genuine_discordant_stays_discordant():
    # adjacent UP but GTEx DOWN (a true comparator conflict, NOT the field-effect signature) → discordant
    r = _row(
        discordant=True,
        dominant_direction="up",
        log2fc_cell_a=2.0,
        q_value_cell_a=0.001,
        log2fc_cell_b=1.8,
        q_value_cell_b=0.001,
        log2fc_cell_c=-1.6,
        q_value_cell_c=0.001,
        max_abs_log2fc=2.0,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "discordant_across_comparators"


# --- FIX 2b (#1013): "mixed" adjacent family (raw down, ComBat up-flipped) is field-affected ---


def test_mixed_adjacent_family_raw_down_combat_up_is_field_effect_1013():
    # EPCAM/COADREAD live shape: raw cell A sig-DOWN (-0.33) + ComBat cell B sig-UP (+1.68) → "mixed"
    # adjacent family; GTEx C strongly UP (+2.09). Deweight the untrustworthy ComBat B for DIRECTION →
    # field-effect (was mis-read as discordant_across_comparators).
    r = _row(
        discordant=True,
        dominant_direction="up",
        log2fc_cell_a=-0.33,
        q_value_cell_a=2.5e-4,
        log2fc_cell_b=1.68,
        q_value_cell_b=1.2e-3,
        log2fc_cell_c=2.09,
        q_value_cell_c=1.6e-72,
        max_abs_log2fc=2.09,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "field_effect_tumor_selective"


def test_mixed_adjacent_family_raw_UP_combat_down_stays_discordant_1013():
    # reverse-mixed guard: raw cell A sig-UP + ComBat cell B sig-DOWN is a GENUINE adjacent-up conflict,
    # NOT the raw-down/ComBat-up field-effect shape — must stay discordant even with GTEx strongly up.
    r = _row(
        discordant=True,
        dominant_direction="up",
        log2fc_cell_a=1.70,
        q_value_cell_a=1.2e-3,
        log2fc_cell_b=-0.33,
        q_value_cell_b=2.5e-4,
        log2fc_cell_c=2.09,
        q_value_cell_c=1.6e-72,
        max_abs_log2fc=2.09,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "discordant_across_comparators"


def test_discordant_but_gtex_only_weakly_up_stays_discordant():
    # GTEx up but < 1.5 (not "strongly up") → not the field-effect rescue; stays discordant
    r = _row(
        discordant=True,
        dominant_direction="up",
        log2fc_cell_a=-0.3,
        q_value_cell_a=0.05,
        log2fc_cell_b=-0.4,
        q_value_cell_b=0.05,
        log2fc_cell_c=1.1,
        q_value_cell_c=0.001,
        max_abs_log2fc=1.1,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "discordant_across_comparators"


# --- FIX 3: field-effect, adjacent-FLAT (non-discordant) variant (FAP/PDAC-driven, 2026-09-03) ---


def test_field_effect_adjacent_flat_recovers_selective():
    # FAP/PDAC pattern: NON-discordant, adjacent A/B ran but flat/non-significant + GTEx C significantly,
    # strongly up. Was collapsing to not_informative (single_comparator); now field_effect_tumor_selective.
    r = _row(
        cells_supporting=1,
        dominant_direction="up",
        log2fc_cell_a=-0.02,
        q_value_cell_a=0.62,  # adjacent ran but flat / non-sig
        log2fc_cell_b=-0.03,
        q_value_cell_b=0.71,
        log2fc_cell_c=3.10,
        q_value_cell_c=1e-30,
        max_abs_log2fc=3.10,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "field_effect_tumor_selective"


def test_field_effect_adjacent_flat_requires_significant_strong_gtex():
    # BATCH-ARTIFACT GUARD: adjacent flat + GTEx up but < 1.5 → NOT rescued; stays not_informative.
    r = _row(
        cells_supporting=1,
        dominant_direction="up",
        log2fc_cell_a=-0.02,
        q_value_cell_a=0.62,
        log2fc_cell_c=1.1,
        q_value_cell_c=0.001,
        max_abs_log2fc=1.1,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "not_informative"


def test_field_effect_adjacent_flat_requires_gtex_significance():
    # a large cell C log2FC that is NOT significant (q high) is a batch-artifact risk → not rescued.
    r = _row(
        cells_supporting=1,
        dominant_direction="up",
        log2fc_cell_a=-0.02,
        q_value_cell_a=0.62,
        log2fc_cell_c=3.0,
        q_value_cell_c=0.40,
        max_abs_log2fc=3.0,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "not_informative"


# --- regression: unchanged bands ---


def test_down_all_cells_not_selective():
    # q-values added 2026-09-12: the fixture claimed 3/3 support with every padj None, a shape the
    # producer never emits. The classifier now reads the families' q-values (FIX 4a), not the count.
    r = _row(
        cells_supporting=3,
        dominant_direction="down",
        log2fc_cell_a=-2.0,
        q_value_cell_a=1e-8,
        log2fc_cell_c=-1.8,
        q_value_cell_c=1e-8,
        max_abs_log2fc=2.0,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "not_selective"


def test_low_support_not_informative():
    # adjacent sig-up, GTEx measured and NOT concurring → 1/2 families → not_informative
    r = _row(
        cells_supporting=1,
        dominant_direction="up",
        log2fc_cell_a=0.8,
        q_value_cell_a=1e-8,
        log2fc_cell_c=0.5,
        q_value_cell_c=0.77,
        max_abs_log2fc=0.8,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "not_informative"


def test_empty_and_missing():
    assert dge._classify_selectivity_from_sensitivity({}) == "data_unavailable"
    # No family produced an estimate (all per-cell log2fc None) → data_unavailable.
    assert dge._classify_selectivity_from_sensitivity(_row(cells_supporting=None)) == "data_unavailable"
