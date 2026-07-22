"""genomic_event_model_match (M11) pure join logic — no S3 (dict fixtures)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.genomic_event_model_match.read import (  # noqa: E402
    _patient_dominant_event, _screen_role, _classify_event_correspondence,
)


# ── patient dominant event — allele-count mode (LoF / default) ───────────────
def test_recurrent_biallelic_is_the_event():
    arm = {"n_samples": 100, "state_counts": {"biallelic-genetic": 45, "monoallelic": 20,
                                              "wt": 30, "uncertain": 5}}
    ev, frac, mode = _patient_dominant_event(arm, functional_direction="loss_of_function")
    assert ev == "biallelic-genetic"
    assert frac == pytest.approx(0.45)
    assert mode == "allele_count"


def test_biallelic_precedence_over_monoallelic():
    # both clear the 10% floor → biallelic wins (stronger, more specific two-hit event)
    arm = {"n_samples": 100, "state_counts": {"biallelic-genetic": 12, "monoallelic": 50,
                                              "wt": 38, "uncertain": 0}}
    ev, _, mode = _patient_dominant_event(arm)
    assert ev == "biallelic-genetic"
    assert mode == "allele_count"


def test_monoallelic_when_biallelic_below_floor():
    # LoF target, monoallelic recurrent, biallelic negligible → allele-count monoallelic
    arm = {"n_samples": 100, "state_counts": {"biallelic-genetic": 2, "monoallelic": 40,
                                              "wt": 58, "uncertain": 0}}
    ev, frac, mode = _patient_dominant_event(arm, functional_direction="loss_of_function")
    assert ev == "monoallelic"
    assert frac == pytest.approx(0.40)
    assert mode == "allele_count"


def test_no_recurrent_event_when_mostly_wt():
    arm = {"n_samples": 100, "state_counts": {"biallelic-genetic": 3, "monoallelic": 4,
                                              "wt": 90, "uncertain": 3}}
    ev, frac, mode = _patient_dominant_event(arm)
    assert ev is None and frac is None and mode == "none"


def test_empty_patient_arm():
    assert _patient_dominant_event({}) == (None, None, "none")
    assert _patient_dominant_event({"n_samples": 0, "state_counts": {}}) == (None, None, "none")


# ── patient dominant event — mutation-presence mode (activating oncogene) ─────
def test_activating_driver_matches_on_mutation_presence():
    # the KRAS-shape gap: activating hotspot scattered across monoallelic (7%) + uncertain (33%),
    # neither clearing the allele-count floor — but fraction_mutated is high → mutation_presence mode.
    arm = {"n_samples": 631, "fraction_mutated": 0.40,
           "state_counts": {"biallelic-genetic": 23, "monoallelic": 45, "wt": 352, "uncertain": 211}}
    ev, frac, mode = _patient_dominant_event(arm, functional_direction="activating")
    assert ev == "activating_mutation"
    assert frac == pytest.approx(0.40)
    assert mode == "mutation_presence"


def test_activating_driver_falls_back_to_allele_count_when_not_recurrently_mutated():
    # activating direction but low mutation prevalence → fall through to allele-count (rarely fires)
    arm = {"n_samples": 100, "fraction_mutated": 0.03,
           "state_counts": {"biallelic-genetic": 15, "monoallelic": 5, "wt": 80, "uncertain": 0}}
    ev, frac, mode = _patient_dominant_event(arm, functional_direction="activating")
    assert ev == "biallelic-genetic"
    assert mode == "allele_count"


def test_lof_direction_ignores_mutation_presence_shortcut():
    # a LoF target with high mutation prevalence still uses allele-count (does NOT hijack to presence)
    arm = {"n_samples": 100, "fraction_mutated": 0.50,
           "state_counts": {"biallelic-genetic": 40, "monoallelic": 10, "wt": 50, "uncertain": 0}}
    ev, _, mode = _patient_dominant_event(arm, functional_direction="loss_of_function")
    assert ev == "biallelic-genetic" and mode == "allele_count"


# ── screen role from Chronos ─────────────────────────────────────────────────
def test_screen_role_thresholds():
    assert _screen_role(-0.8) == "positive_model"      # dependent
    assert _screen_role(-0.5) == "positive_model"      # boundary
    assert _screen_role(-0.1) == "resistance_model"    # not dependent
    assert _screen_role(-0.3) == "indeterminate"       # intermediate
    assert _screen_role(None) == "indeterminate"       # missing


# ── event correspondence rollup ──────────────────────────────────────────────
def test_correspondence_matched_dependent_in_lineage():
    assert _classify_event_correspondence(
        n_matched=5, n_matched_dependent=3, n_matched_dep_lineage=1, has_lineage=True
    ) == "event_matched_dependent_in_lineage"


def test_correspondence_matched_dependent_off_lineage():
    assert _classify_event_correspondence(
        n_matched=5, n_matched_dependent=3, n_matched_dep_lineage=0, has_lineage=True
    ) == "event_matched_dependent_off_lineage"
    # no lineage defined at all → off-lineage bucket
    assert _classify_event_correspondence(
        n_matched=5, n_matched_dependent=3, n_matched_dep_lineage=0, has_lineage=False
    ) == "event_matched_dependent_off_lineage"


def test_correspondence_matched_not_dependent():
    assert _classify_event_correspondence(
        n_matched=4, n_matched_dependent=0, n_matched_dep_lineage=0, has_lineage=True
    ) == "event_matched_not_dependent"


def test_correspondence_no_event_match():
    assert _classify_event_correspondence(
        n_matched=0, n_matched_dependent=0, n_matched_dep_lineage=0, has_lineage=True
    ) == "no_event_match"
