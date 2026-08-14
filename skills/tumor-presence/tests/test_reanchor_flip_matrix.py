"""F re-anchor regression matrix (2026-08-14, VERDICT-MOVING guard).

SKILL_VERSION 1.7.0 re-anchored _EXPRESSION_RANK so the TUMOR-tissue lens outranks the pan-cancer
CELL-LINE proxy for the collapsed headline. That change was justified by an offline A/B backtest over
43 target-indication pairs (10 indications): 23 flips, EVERY ONE -> tumor_broadly_expressed, zero
dangerous flips. The backtest harness was run out-of-tree (ephemeral); this test COMMITS its conclusion
as a permanent, credential-less regression matrix so a future ladder edit that reverts the re-anchor
(or reintroduces the cell-line-over-tumor precedence) fails here.

The collapsed presence_verdict is a pure function of the fired-rule list via run.py::_verdict, so each
row is a synthetic fired-set standing in for a real backtest exemplar (the rule_id that each card emits
is what actually drives the ladder — see CARD_CONTEXT / _EXPRESSION_RANK)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_matrix", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


# The three cell-line vs tumor fired-set shapes that FLIPPED in the backtest — all must resolve to the
# tumor-tissue verdict now that the tumor lens outranks the cell-line proxy.
_CL_MODERATE = _fr("expression-broadly-moderate-neutral", "cellline-rna-distribution")
_CL_RESTRICTED = _fr("expression-lineage-restricted-supportive", "cellline-rna-distribution")
_CL_HIGH = _fr("expression-broadly-high-supportive", "cellline-rna-distribution")
_TVA_MODEST_UP = _fr("expression-modest-upregulation-neutral", "tumor-rna-vs-adjacent")
_TVA_STRONG_UP = _fr("expression-strong-upregulation-supportive", "tumor-rna-vs-adjacent")
_TUMOR_BROAD = _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution")
_TUMOR_SPARSE = _fr("tumor-expression-broadly-low-neutral", "tumor-rna-distribution")


@pytest.mark.parametrize("exemplar,fired,expected", [
    # FLIP class 1 — cell-line broadly_moderate + tumor broadly-expressed (EPCAM/FOLR1/KRAS/APC/BRAF/NAPSA)
    ("cellline_moderate_x_tumor_broad", [_CL_MODERATE, _TUMOR_BROAD], "tumor_broadly_expressed"),
    # FLIP class 2 — cell-line lineage_restricted + tumor broadly-expressed (CDH17/CEACAM5/TACSTD2/DLL3/NECTIN4/MUC13)
    ("cellline_restricted_x_tumor_broad", [_CL_RESTRICTED, _TUMOR_BROAD], "tumor_broadly_expressed"),
    # FLIP class 3 — tumor-vs-adjacent modest_up + tumor broadly-expressed (EGFR-LUAD/KRAS-LUAD/NOX1/STEAP1)
    ("tva_modest_up_x_tumor_broad", [_TVA_MODEST_UP, _TUMOR_BROAD], "tumor_broadly_expressed"),
])
def test_reanchor_flips_to_tumor_broadly_expressed(exemplar, fired, expected):
    """Backtest flip classes: whenever the tumor tissue reads broadly-expressed, the headline is the
    tumor verdict — the cell-line proxy no longer understates it."""
    v, _ = tp._verdict(fired)
    assert v == expected, f"{exemplar}: expected {expected}, got {v}"


@pytest.mark.parametrize("exemplar,fired,expected", [
    # cell-line broadly_high + tumor broadly-expressed → BOTH high, headline unchanged (MET/ERBB2/MYC/TP53/PARP1)
    ("both_high_unchanged", [_CL_HIGH, _TUMOR_BROAD], "broadly_high_expression"),
    # tumor-vs-adjacent strong upregulation dominates (CEACAM5-LUAD/MSLN/HTR1D/TACSTD2-COADREAD)
    ("strong_up_unchanged", [_CL_RESTRICTED, _TVA_STRONG_UP], "strongly_upregulated_in_tumor"),
])
def test_reanchor_leaves_agreeing_and_strong_cases_unchanged(exemplar, fired, expected):
    """No gratuitous churn: cell-line broadly_high stays at rung 1 (both-high agreement) and a
    tumor-vs-adjacent strong-upregulation still wins outright."""
    v, _ = tp._verdict(fired)
    assert v == expected, f"{exemplar}: expected {expected}, got {v}"


def test_tumor_sparse_stays_below_cellline_positive():
    """Guard the deliberate NON-promotion: a per-indication NEUTRAL tumor_sparsely_expressed must NOT
    outrank a supportive cell-line-present signal (broadly_high) — only tumor broadly/moderately were
    promoted, not the sparse read."""
    v, _ = tp._verdict([_CL_HIGH, _TUMOR_SPARSE])
    assert v == "broadly_high_expression"


def test_reanchor_invariant_no_cellline_over_tumor_for_broad():
    """The core invariant, stated directly: given cell-line moderate/restricted AND tumor broadly-
    expressed both fired, the tumor rung must win (a regression that reverts the ladder would return a
    cell-line verdict here)."""
    for cl in (_CL_MODERATE, _CL_RESTRICTED):
        v, drv = tp._verdict([cl, _TUMOR_BROAD])
        assert v == "tumor_broadly_expressed"
        assert drv == "tumor-expression-broadly-high-supportive"
