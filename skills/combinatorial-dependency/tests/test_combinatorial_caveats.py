"""Hermetic tests for the v1.1.0 combinatorial_dependency confidence surface (literature-and-claims arc, #4).

Covers the VERDICT-INERT enrichment over the measured DepMap ParalogV2 combinatorial-dependency skill:
  - combinatorial_dependency_confidence_caveat (3 tiers + DATA-BLIND-TOLERANT paralog guard + precedence + None)
  - combinatorial_druggability_caveat          (scaffold partner → degrader; None otherwise)
  - combinatorial_dependency_provenance        (quorum fields; None on the thin path)
  - the COMBINATORIAL_DEPENDENCY lens (registry, verdict mode, verdict_key, single axis)

Pure caveat tests use synthetic headline dicts (no card / no LLM). SET literals, not 2-string tuples."""

from __future__ import annotations

from pathlib import Path

import pytest
from _skills_common.narrator_lenses import COMBINATORIAL_DEPENDENCY, LENSES
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def M():
    return load_run_py(SKILL_DIR, "cmb_run_caveats")


def _hl(
    verdict="constitutive_combinatorial_dependency",
    n_screened=6,
    n_interacting=1,
    strongest="XYZ1",
    top=None,
    ctx=None,
    cls=None,
):
    return {
        "combinatorial_dependency_verdict": verdict,
        "n_paralog_partners_screened": n_screened,
        "n_interacting_partners": n_interacting,
        "strongest_partner": strongest,
        "top_partners": top if top is not None else ([{"partner_gene": strongest}] if strongest else []),
        "combinatorial_context": ctx,
        "combinatorial_dependency_class": cls,
    }


# ── MILDER — validated_paralog_synthetic_lethal guard (DATA-BLIND-TOLERANT) ─────────────────────────
def test_paralog_guard_partner_present(M):
    c = M._combinatorial_dependency_confidence_caveat(
        _hl(verdict="constitutive_combinatorial_dependency", strongest="SMARCA2", top=[{"partner_gene": "SMARCA2"}]),
        target="SMARCA4",
        indication="LUAD",
    )
    assert c["reason"] == "validated_paralog_synthetic_lethal" and c["false_demote_guarded"] is True
    assert c["partner_screened_present"] is True


def test_paralog_guard_data_blind_no_interaction(M):
    # ParalogV2 UNDER-calls: verdict no_interaction but the pair was screened → guard still fires.
    c = M._combinatorial_dependency_confidence_caveat(
        _hl(verdict="no_combinatorial_dependency", n_interacting=0, strongest="ARID2", top=[{"partner_gene": "ARID2"}]),
        target="SMARCA4",
        indication="LUAD",
    )
    assert c["reason"] == "validated_paralog_synthetic_lethal"
    assert c["partner_screened_present"] is False  # canonical SMARCA2 not among screened → data-blind note


def test_paralog_guard_wins_over_pan_essential(M):
    c = M._combinatorial_dependency_confidence_caveat(
        _hl(strongest="RPL5", top=[{"partner_gene": "RPL5"}]), target="STAG2", indication="BLCA"
    )
    assert c["reason"] == "validated_paralog_synthetic_lethal"  # guard precedence over pan-essential


# ── SHARP — pan_essential_or_context_restricted ─────────────────────────────────────────────────────
def test_pan_essential_fires_sharp(M):
    c = M._combinatorial_dependency_confidence_caveat(
        _hl(strongest="RPL5", top=[{"partner_gene": "RPL5"}]), target="FOO", indication="BAR"
    )
    assert c["reason"] == "pan_essential_or_context_restricted" and c["tier"] == "sharp"


def test_context_restricted_fires_sharp(M):
    c = M._combinatorial_dependency_confidence_caveat(
        _hl(verdict="context_combinatorial_dependency", strongest="XYZ1"), target="FOO", indication="BAR"
    )
    assert c["reason"] == "pan_essential_or_context_restricted"


# ── SHARP — measured_gi_functionally_unconfirmed default ────────────────────────────────────────────
def test_measured_gi_default(M):
    c = M._combinatorial_dependency_confidence_caveat(
        _hl(verdict="constitutive_combinatorial_dependency", strongest="XYZ1"), target="FOO", indication="BAR"
    )
    assert c["reason"] == "measured_gi_functionally_unconfirmed" and c["tier"] == "sharp"


# ── None path ───────────────────────────────────────────────────────────────────────────────────────
def test_no_interaction_non_canonical_none(M):
    assert (
        M._combinatorial_dependency_confidence_caveat(
            _hl(verdict="no_combinatorial_dependency", n_interacting=0, strongest=None, top=[]),
            target="FOO",
            indication="BAR",
        )
        is None
    )


def test_insufficient_none(M):
    assert (
        M._combinatorial_dependency_confidence_caveat(
            _hl(verdict="combinatorial_dependency_insufficient", n_screened=0, n_interacting=0, strongest=None, top=[]),
            target="FOO",
            indication="BAR",
        )
        is None
    )


# ── druggability (scaffold) ─────────────────────────────────────────────────────────────────────────
def test_scaffold_druggability_fires(M):
    d = M._combinatorial_druggability_caveat(
        _hl(strongest="STAG1", top=[{"partner_gene": "STAG1"}]), target="STAG2", indication="BLCA"
    )
    assert d and d["reason"] == "genetic_ko_undruggable_scaffold_partner" and "STAG1" in d["scaffold_partners"]


def test_druggability_none_when_no_scaffold(M):
    assert M._combinatorial_druggability_caveat(_hl(strongest="XYZ1"), target="FOO", indication="BAR") is None


# ── provenance ──────────────────────────────────────────────────────────────────────────────────────
def test_provenance_fields(M):
    p = M._combinatorial_dependency_provenance(
        _hl(strongest="RPL5", top=[{"partner_gene": "RPL5"}]), target="SMARCA4", indication="LUAD"
    )
    assert p["validated_paralog_sl_flag"] is True
    assert p["pan_essential_partners_present"] == ["RPL5"]


def test_provenance_none_on_thin(M):
    assert (
        M._combinatorial_dependency_provenance(
            _hl(n_screened=0, strongest=None, top=[]), target="FOO", indication="BAR"
        )
        is None
    )


# ── lens contract ───────────────────────────────────────────────────────────────────────────────────
def test_lens_registered_verdict_mode():
    assert LENSES.get("combinatorial-dependency") is COMBINATORIAL_DEPENDENCY
    assert COMBINATORIAL_DEPENDENCY.mode == "verdict"
    assert COMBINATORIAL_DEPENDENCY.verdict_key == "combinatorial_dependency_verdict"
    assert set(COMBINATORIAL_DEPENDENCY.axis_labels) == {"CODEP"}


def test_literature_and_synthesize_wired(M):
    src = (SKILL_DIR / "scripts" / "run.py").read_text()
    assert "synthesize_fn=make_synthesize_fn" in src
    assert "literature_fn=make_literature_fn" in src
