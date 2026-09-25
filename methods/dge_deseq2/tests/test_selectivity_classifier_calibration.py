"""_classify_selectivity_from_sensitivity — calibration fixes (backtest-driven, 2026-08-07).

Pins the calibration fixes found by the ground-truth backtest
(feedback_selectivity_calibration_backtest):
  FIX 1 — the magnitude gate keys on the RAW comparators (cell A TCGA-adjacent + cell C GTEx). This
          was originally introduced to exclude the ComBat cell B, which INFLATED/sign-flipped log2FC
          and could confer a false strong/modest on its own. Cell B was removed entirely in
          analysis-methods#727, so the gate now simply has A and C to key on; a stray log2fc_cell_b
          on a not-yet-rebuilt product is never read.
  FIX 2 — a discordant row with the FIELD-EFFECT signature (adjacent cell A flat-or-down + GTEx C
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
        "cells_ran": 2,
        "cells_supporting": None,
        "dominant_direction": None,
        "discordant": False,
        "log2fc_cell_a": None,
        "q_value_cell_a": None,
        "log2fc_cell_c": None,
        "q_value_cell_c": None,
        "max_abs_log2fc": None,
    }
    r.update(kw)
    return r


# --- FIX 1: the magnitude gate keys on the RAW comparators A and C ---


def test_raw_ac_below_1_5_is_modest_not_strong():
    # raw cells A + C are BELOW 1.5 → modest, not strong. (Historically cell B could be inflated to
    # 4.8 here and drive a false strong; the A/C-only gate — and #727 removing B — block that.)
    r = _row(
        cells_supporting=2,
        dominant_direction="up",
        log2fc_cell_a=0.9,
        q_value_cell_a=0.01,
        log2fc_cell_c=0.8,
        q_value_cell_c=0.01,
        max_abs_log2fc=0.9,
    )
    out = dge._classify_selectivity_from_sensitivity(r)
    assert out != "strong_tumor_selective"
    # raw_max = max(0.9, 0.8) = 0.9 → modest (>=0.5), not strong
    assert out == "modest_tumor_selective"


def test_raw_cell_A_high_still_strong():
    # a genuine signal: raw cell A itself clears 1.5 → strong
    r = _row(
        cells_supporting=2,
        dominant_direction="up",
        log2fc_cell_a=4.7,
        q_value_cell_a=1e-9,
        log2fc_cell_c=1.2,
        q_value_cell_c=1e-9,
        max_abs_log2fc=4.7,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "strong_tumor_selective"


def test_raw_cell_C_high_confers_magnitude_when_the_adjacent_arm_ALSO_ran():
    # Fix 1's raw-magnitude gate accepts cell C as a RAW comparator — a high C is real magnitude. Pin
    # that with the adjacent family also measured and agreeing, so this test isolates MAGNITUDE
    # (Fix 1) from EVIDENCE BASE (Fix 4b, below).
    r = _row(
        cells_ran=2,
        cells_supporting=2,
        dominant_direction="up",
        log2fc_cell_a=1.1,
        q_value_cell_a=1e-8,
        log2fc_cell_c=9.9,
        q_value_cell_c=1e-50,
        max_abs_log2fc=9.9,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "strong_tumor_selective"


def test_gtex_only_no_adjacent_arm_is_modest_NOT_strong_fix4b():
    """REVERSES a 2026-08-07 pin (#221, e36fef6), deliberately.

    That commit asserted `GTEx-only single-cell strong (FOLR1/MSLN pattern): C high, A absent →
    strong`. Measured 2026-09-12 across all shipped sensitivity products: that path mints 32,784
    `strong` calls in 7 indications (ACC, LGG, OV, SCLC, SKCM, TGCT, UCS) that have NO adjacent-normal
    arm at all — every row scores cells_ran=1 / cells_supporting=1 → frac 1.0 → strong on the
    TCGA-vs-GTEx contrast ALONE, which is the platform/batch confound cell D was RETIRED for. The
    nomination gate weights `strong` DOMINANT, so an unreplicated single-arm result was driving
    verdicts.

    The demotion is to `modest`, not to nothing: the biology is frequently real (FOLR1/OV C=+9.95,
    CLDN6/OV C=+12.18, DLL3/SCLC C=+5.02 all remain axis-A selective). What changes is the CLAIM —
    single-armed evidence may not read as the framework's strongest band.
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
    # CEACAM5/COADREAD pattern: adjacent cell A flat/non-sig + GTEx C strongly UP → field_effect subclass
    r = _row(
        discordant=True,
        dominant_direction="up",
        log2fc_cell_a=-0.30,
        q_value_cell_a=0.05,  # adjacent ran but not significant
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
        log2fc_cell_c=-1.6,
        q_value_cell_c=0.001,
        max_abs_log2fc=2.0,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "discordant_across_comparators"


# --- adjacent-direction gating of the discordant field-effect rescue ---


def test_adjacent_sig_down_gtex_up_is_field_effect():
    # EPCAM/COADREAD live shape: raw cell A sig-DOWN (-0.33) while GTEx C strongly UP (+2.09) is the
    # field-cancerization signature — the adjacent margin already over-expresses → field_effect.
    # (Before #727 this was the FIX-2b "mixed" case, where a ComBat cell B flipped sig-up against a
    # sig-down A; with cell B removed the adjacent family is cell A alone and reads sig-down directly.)
    r = _row(
        discordant=True,
        dominant_direction="up",
        log2fc_cell_a=-0.33,
        q_value_cell_a=2.5e-4,
        log2fc_cell_c=2.09,
        q_value_cell_c=1.6e-72,
        max_abs_log2fc=2.09,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "field_effect_tumor_selective"


def test_adjacent_sig_up_gtex_up_flagged_discordant_stays_discordant():
    # guard: a sig-UP adjacent cell A is a GENUINE adjacent-up signal, NOT the field-effect shape —
    # so a row the product flagged `discordant` must stay discordant even with GTEx strongly up.
    r = _row(
        discordant=True,
        dominant_direction="up",
        log2fc_cell_a=1.70,
        q_value_cell_a=1.2e-3,
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
        log2fc_cell_c=1.1,
        q_value_cell_c=0.001,
        max_abs_log2fc=1.1,
    )
    assert dge._classify_selectivity_from_sensitivity(r) == "discordant_across_comparators"


# --- FIX 3: field-effect, adjacent-FLAT (non-discordant) variant (FAP/PDAC-driven, 2026-09-03) ---


def test_field_effect_adjacent_flat_recovers_selective():
    # FAP/PDAC pattern: NON-discordant, adjacent cell A ran but flat/non-significant + GTEx C
    # significantly, strongly up. Was collapsing to not_informative; now field_effect_tumor_selective.
    r = _row(
        cells_supporting=1,
        dominant_direction="up",
        log2fc_cell_a=-0.02,
        q_value_cell_a=0.62,  # adjacent ran but flat / non-sig
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
        cells_supporting=2,
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
