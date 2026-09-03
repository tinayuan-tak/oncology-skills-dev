"""Unit tests for the VERDICT-INERT signal-surfacing flags added 2026-09-03 (run.py):
measurement_caveat (coverage-asymmetry) + concordance_scope_note (pooled-scope reconciliation).

Pure over the two helper functions — no S3, no card reads. Both are NEW headline fields that are None
except in the specific data shape each names, so every existing fixture/golden (both arms measured,
positive verdict) is byte-stable and the dependency_verdict spine is untouched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

# run.py is a script (not an importable package path) — load it by file location.
_RUN = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
_spec = importlib.util.spec_from_file_location("fr_run_under_test", _RUN)
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


# ── measurement_caveat: decisive single-arm signal held at a coverage-gap verdict ────────────────────
def test_measurement_caveat_rnai_decisive_crispr_unmeasured():
    """POLR2A/COADREAD shape: RNAi common_essential (decisive) + CRISPR data_unavailable → insufficient.
    The caveat must name the decisive-but-unconfirmed RNAi signal and flag it as NOT measured-absent."""
    cav = run._measurement_caveat("insufficient", "data_unavailable", "common_essential")
    assert cav and "RNAi" in cav and "CRISPR" in cav and "UNMEASURED" in cav
    assert "decisive-but-unconfirmed" in cav and "measured-absent" in cav


def test_measurement_caveat_crispr_decisive_rnai_unmeasured():
    cav = run._measurement_caveat("insufficient_underpowered", "strongly_selective", None)
    assert cav and "CRISPR" in cav and "single perturbation channel" in cav


def test_measurement_caveat_none_when_both_arms_measured():
    """KRAS/COADREAD shape (both arms measured, positive verdict) → no caveat (byte-stable)."""
    assert run._measurement_caveat("lineage_selective", "strongly_selective", "strongly_selective") is None
    # even a coverage-gap verdict with BOTH arms measured (a real discordance/underpower) → no caveat
    assert run._measurement_caveat("insufficient", "non_dependent", "non_dependent") is None


def test_measurement_caveat_none_when_verdict_is_a_call():
    """A decisive single arm that STILL produced a positive call (e.g. via lineage rescue) → no caveat:
    the caveat only explains a coverage-GAP verdict, never a real call."""
    assert run._measurement_caveat("lineage_selective", "data_unavailable", "common_essential") is None


# ── concordance_scope_note: pooled non-dependent vs selective distributions ───────────────────────────
def test_concordance_scope_note_fires_on_pooled_nondep_with_selective_distributions():
    """KRAS/COADREAD shape: concordance card *_concordant_non_dependent while BOTH distributions read a
    selective class → a pooled-scope selective signature, NOT a modality contradiction."""
    note = run._concordance_scope_note("moderately_concordant_non_dependent",
                                       "strongly_selective", "strongly_selective")
    assert note and "POOLED" in note and "not evidence against the dependency" in note


def test_concordance_scope_note_none_when_distributions_not_dependent():
    """WRN shape: strongly_concordant_non_dependent with both distributions non_dependent → genuinely
    non-dependent pooled; no reconciliation note (it is NOT a pooled-scope artifact)."""
    assert run._concordance_scope_note("strongly_concordant_non_dependent",
                                       "non_dependent", "non_dependent") is None


def test_concordance_scope_note_none_when_concordance_is_dependent():
    """PLK1 shape: strongly_concordant_dependent → not the non_dependent-label case → no note."""
    assert run._concordance_scope_note("strongly_concordant_dependent",
                                       "common_essential", "common_essential") is None
