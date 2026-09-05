"""E-PRISM re-home (2026-07-20): PRISM chemical-genetic concordance as a gate-C
dependency CONFIRMATION arm — and its veto-safety.

prism-crispr-concordance's `triangulated_target_engaged` (CRISPR AND RNAi dependency
BOTH correlate with PRISM compound kill) fires `e7-triangulated-target-engaged-supportive`,
which the dependency resolver now reads as `chemical_genetic_confirmed_dependent` — a
POSITIVE-ONLY confirmation the target is required. The same rule also drives
tractability_sm's `well_covered` (E1: a compound was found); one measurement routes
many-to-many to gates.

These tests pin the veto-safety invariant the design turns on: a PRISM signal can
CONFIRM a dependency but can NEVER create or flip a veto (PRISM absence is neutral, not a
killer — not-yet-drugged ≠ undruggable). Sibling of
test_verdict_paralog_buffered_not_veto.py.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

TRIANGULATED = "e7-triangulated-target-engaged-supportive"

fr = load_run_py(Path(__file__).resolve().parent.parent, "fr_run")


def test_triangulated_alone_confirms_dependency():
    """Chemical+genetic target-engagement, nothing else fired → the new positive-only
    confirmation verdict (NOT a bare insufficient)."""
    v, drv = fr._verdict([{"rule_id": TRIANGULATED}])
    assert v == "chemical_genetic_confirmed_dependent"
    assert drv == TRIANGULATED


def test_pan_essential_killer_wins_over_confirmation():
    """VETO-SAFETY: a pan-essential target is never rescued/confirmed by compound
    correlation — pan_essential_killer must win over the confirmation arm."""
    v, _ = fr._verdict([
        {"rule_id": TRIANGULATED},
        {"rule_id": "pan-essential-killer"},
    ])
    assert v == "pan_essential_killer"


def test_confirmation_cannot_create_a_veto():
    """VETO-SAFETY: the confirmation verdict is not in the nomination gate's kill tuples
    (it's a positive_signal). Assert it is neither of the two dependency veto verdicts —
    a PRISM signal can never manufacture a veto."""
    v, _ = fr._verdict([{"rule_id": TRIANGULATED}])
    assert v not in ("non_dependent", "pan_essential_killer")


def test_genetic_concordant_outranks_confirmation():
    """A direct genetic dependency (concordant CRISPR+RNAi) is the stronger call and
    ranks above the chemical-genetic CONFIRMATION — the confirmation corroborates, it is
    not a stronger signal than a direct dependency."""
    v, _ = fr._verdict([
        {"rule_id": TRIANGULATED},
        {"rule_id": "concordant-dependent-supportive-dominant"},
    ])
    assert v == "concordant_dependent"


def test_confirmation_outranks_pooled_non_dependence():
    """Like the existing genetic positives, a measured chemical-genetic confirmation
    outranks a POOLED non-dependence (the false-negative-prone call): if per-line CRISPR
    AND RNAi both track compound kill while the pooled median reads non_dependent, that is
    the biomarker-dilution pattern the framework resolves in favor of the measured
    positive. (Mirrors how concordant/lineage/selective already shadow non_dependent.)"""
    v, drv = fr._verdict([
        {"rule_id": TRIANGULATED},
        {"rule_id": "non-dependent-killer"},
    ])
    assert v == "chemical_genetic_confirmed_dependent"
    assert drv == TRIANGULATED
