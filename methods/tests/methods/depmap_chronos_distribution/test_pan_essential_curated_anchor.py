"""T3 (2026-08-31): the pan-essential KILLER is co-anchored to DepMap's curated core-essential control
set (AchillesCommonEssentialControls) instead of firing on the eyeballed fraction_strongly_dependent>=0.85
alone. This is a VERDICT-MOVING change (dependency_class → the dependency resolver's pan_essential_killer),
so it is backtest-gated on a target PANEL: curated core-essentials must RETAIN common_essential; a
broadly-dependent-by-fraction but NON-curated gene must DOWNGRADE to broadly_dependent (never fabricate a
killer — the CD19 over-eager-clamp lesson); selective oncogene-addiction dependencies (KRAS-like) are
untouched. The raw fraction-only call is retained as the audit field pan_essential_fraction_call.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_chronos_distribution" / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("chr_cli_t3", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr_cli_t3"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()
_PAN = dict(distribution_shape="pan_essential", n_cell_lines_evaluated=1500)


# ── the re-anchor co-requirement (pure logic) ────────────────────────────────────────────────────
def test_curated_core_essential_retains_the_killer():
    # curated True + pan-essential fraction → common_essential (RETAINED)
    assert cli._classify_dependency(0.90, -1.9, curated_common_essential=True, **_PAN) == "common_essential"


def test_non_curated_high_fraction_downgrades_to_broadly_dependent():
    # broadly dependent by fraction but NOT a curated core-essential → NOT a killer (downgraded)
    assert cli._classify_dependency(0.90, -1.9, curated_common_essential=False, **_PAN) == "broadly_dependent"


def test_list_unavailable_falls_back_to_fraction_only():
    # None ⇒ list unreachable ⇒ prior fraction-only behavior (graceful degradation, no dropped killer)
    assert cli._classify_dependency(0.90, -1.9, curated_common_essential=None, **_PAN) == "common_essential"
    # default arg omitted = None = fallback (existing callers byte-stable)
    assert cli._classify_dependency(0.90, -1.9, **_PAN) == "common_essential"


def test_underpowered_guard_precedes_the_anchor():
    # a tiny panel is still common_essential_underpowered regardless of curated membership
    assert (
        cli._classify_dependency(
            0.90, -1.9, distribution_shape="pan_essential", n_cell_lines_evaluated=100, curated_common_essential=True
        )
        == "common_essential_underpowered"
    )
    assert (
        cli._classify_dependency(
            0.90, -1.9, distribution_shape="pan_essential", n_cell_lines_evaluated=100, curated_common_essential=False
        )
        == "common_essential_underpowered"
    )


def test_selective_and_nondependent_unaffected_by_anchor():
    # KRAS-like selective (low fraction, bimodal) — the anchor never touches non-pan-essential branches
    for curated in (True, False, None):
        assert (
            cli._classify_dependency(
                0.24,
                -0.40,
                distribution_shape="bimodal_selective",
                n_cell_lines_evaluated=1500,
                curated_common_essential=curated,
            )
            == "strongly_selective"
        )
        assert (
            cli._classify_dependency(
                0.01,
                0.10,
                distribution_shape="non_essential",
                n_cell_lines_evaluated=1500,
                curated_common_essential=curated,
            )
            == "non_dependent"
        )


# ── summary emits the audit fields ───────────────────────────────────────────────────────────────
def test_summary_emits_audit_fields():
    scores = {f"ACH-{i:06d}": (-2.5 if i < 380 else 0.1) for i in range(400)}  # >= panel floor (300)
    meta = {m: {"OncotreeLineage": "Bowel"} for m in scores}
    s = cli.compute_summary_stats(scores, meta, curated_common_essential=False)
    assert s["depmap_curated_common_essential"] is False
    assert s["pan_essential_fraction_call"] == "common_essential"  # raw fraction-only (audit/ladder)
    assert s["dependency_class"] == "broadly_dependent"  # re-anchored (downgraded)


# ── PANEL backtest against the REAL DepMap curated list (skips without S3 creds) ──────────────────
_POSITIVES = {"PLK1", "KIF11", "RAN", "RPL3", "PCNA", "CDK1"}  # curated core-essentials → RETAIN
_NEGATIVES = {"KRAS", "TP53", "WRN", "EGFR", "BRAF", "MYC"}  # selective / non-essential → OUT


@pytest.mark.skipif(
    not os.environ.get("AWS_PROFILE") and not os.environ.get("AWS_ACCESS_KEY_ID"),
    reason="needs S3 creds to fetch AchillesCommonEssentialControls.csv",
)
def test_curated_list_membership_backtest():
    """Pins the anchor against the real DepMap control file so a future release that reshuffles it is
    caught: every panel positive must be IN the curated set; every negative (esp. the oncogene KRAS,
    which IS in the looser CRISPRInferredCommonEssentials) must be OUT."""
    curated = cli._load_curated_common_essentials("26q1")
    if curated is None:
        pytest.skip("curated control list unreachable this run")
    assert _POSITIVES <= curated, f"missing curated positives: {_POSITIVES - curated}"
    assert not (_NEGATIVES & curated), f"negatives leaked into curated set: {_NEGATIVES & curated}"
