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

REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, str(REPO))
# load the WORKTREE copy explicitly (test runs against the patched classifier)
WT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WT))
from methods.dge_deseq2 import read as dge  # noqa: E402


def _row(**kw):
    r = {"cells_ran": 3, "cells_supporting": None, "dominant_direction": None,
         "discordant": False, "log2fc_cell_a": None, "q_value_cell_a": None,
         "log2fc_cell_b": None, "q_value_cell_b": None,
         "log2fc_cell_c": None, "q_value_cell_c": None, "max_abs_log2fc": None}
    r.update(kw)
    return r


# --- FIX 1: ComBat cell B cannot alone confer magnitude ---

def test_combat_B_alone_does_not_confer_strong():
    # raw cells A + C are BELOW 1.5; only the ComBat cell B is inflated → must NOT be strong.
    r = _row(cells_supporting=3, dominant_direction="up",
             log2fc_cell_a=0.9, q_value_cell_a=0.01,
             log2fc_cell_b=4.8, q_value_cell_b=0.01,   # ComBat inflated
             log2fc_cell_c=0.8, q_value_cell_c=0.01,
             max_abs_log2fc=4.8)                        # legacy max (across all) would say strong
    out = dge._classify_selectivity_from_sensitivity(r)
    assert out != "strong_tumor_selective"
    # raw_max = max(0.9, 0.8) = 0.9 → modest (>=0.5), not strong
    assert out == "modest_tumor_selective"


def test_raw_cell_A_high_still_strong():
    # a genuine signal: raw cell A itself clears 1.5 → strong (Fix 1 doesn't punish real raw signal)
    r = _row(cells_supporting=3, dominant_direction="up",
             log2fc_cell_a=4.7, q_value_cell_a=1e-9,
             log2fc_cell_b=4.9, q_value_cell_b=1e-9,
             log2fc_cell_c=1.2, q_value_cell_c=1e-9, max_abs_log2fc=4.9)
    assert dge._classify_selectivity_from_sensitivity(r) == "strong_tumor_selective"


def test_raw_cell_C_high_still_strong():
    # GTEx-only single-cell strong (FOLR1/MSLN pattern): C high, A/B absent → strong
    r = _row(cells_ran=1, cells_supporting=1, dominant_direction="up",
             log2fc_cell_c=9.9, q_value_cell_c=1e-50, max_abs_log2fc=9.9)
    assert dge._classify_selectivity_from_sensitivity(r) == "strong_tumor_selective"


# --- FIX 2: field-effect-aware discordant ---

def test_field_effect_signature_recovers_selective():
    # CEACAM5/COADREAD pattern: adjacent A/B flat-or-DOWN + GTEx C strongly UP → field_effect subclass
    r = _row(discordant=True, dominant_direction="up",
             log2fc_cell_a=-0.30, q_value_cell_a=0.05,
             log2fc_cell_b=-0.49, q_value_cell_b=0.002,
             log2fc_cell_c=2.94, q_value_cell_c=1e-110, max_abs_log2fc=2.94)
    assert dge._classify_selectivity_from_sensitivity(r) == "field_effect_tumor_selective"


def test_genuine_discordant_stays_discordant():
    # adjacent UP but GTEx DOWN (a true comparator conflict, NOT the field-effect signature) → discordant
    r = _row(discordant=True, dominant_direction="up",
             log2fc_cell_a=2.0, q_value_cell_a=0.001,
             log2fc_cell_b=1.8, q_value_cell_b=0.001,
             log2fc_cell_c=-1.6, q_value_cell_c=0.001, max_abs_log2fc=2.0)
    assert dge._classify_selectivity_from_sensitivity(r) == "discordant_across_comparators"


def test_discordant_but_gtex_only_weakly_up_stays_discordant():
    # GTEx up but < 1.5 (not "strongly up") → not the field-effect rescue; stays discordant
    r = _row(discordant=True, dominant_direction="up",
             log2fc_cell_a=-0.3, q_value_cell_a=0.05,
             log2fc_cell_b=-0.4, q_value_cell_b=0.05,
             log2fc_cell_c=1.1, q_value_cell_c=0.001, max_abs_log2fc=1.1)
    assert dge._classify_selectivity_from_sensitivity(r) == "discordant_across_comparators"


# --- regression: unchanged bands ---

def test_down_all_cells_not_selective():
    r = _row(cells_supporting=3, dominant_direction="down",
             log2fc_cell_a=-2.0, log2fc_cell_c=-1.8, max_abs_log2fc=2.0)
    assert dge._classify_selectivity_from_sensitivity(r) == "not_selective"


def test_low_support_not_informative():
    r = _row(cells_supporting=1, dominant_direction="up",
             log2fc_cell_a=0.8, log2fc_cell_c=0.5, max_abs_log2fc=0.8)
    assert dge._classify_selectivity_from_sensitivity(r) == "not_informative"


def test_empty_and_missing():
    assert dge._classify_selectivity_from_sensitivity({}) == "data_unavailable"
    assert dge._classify_selectivity_from_sensitivity(
        _row(cells_supporting=None)) == "data_unavailable"
