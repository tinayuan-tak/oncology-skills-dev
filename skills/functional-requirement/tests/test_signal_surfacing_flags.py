"""Unit tests for the VERDICT-INERT signal-surfacing flags added 2026-09-03 (run.py):
measurement_caveat (coverage-asymmetry) + concordance_scope_note (pooled-scope reconciliation).

Pure over the two helper functions — no S3, no card reads. Both are NEW headline fields that are None
except in the specific data shape each names, so every existing fixture/golden (both arms measured,
positive verdict) is byte-stable and the dependency_verdict spine is untouched.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

run = load_run_py(Path(__file__).resolve().parents[1], "fr_run_under_test")


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
    note = run._concordance_scope_note(
        "moderately_concordant_non_dependent", "strongly_selective", "strongly_selective"
    )
    assert note and "POOLED" in note and "not evidence against the dependency" in note


def test_concordance_scope_note_none_when_distributions_not_dependent():
    """WRN shape: strongly_concordant_non_dependent with both distributions non_dependent → genuinely
    non-dependent pooled; no reconciliation note (it is NOT a pooled-scope artifact)."""
    assert run._concordance_scope_note("strongly_concordant_non_dependent", "non_dependent", "non_dependent") is None


def test_concordance_scope_note_none_when_concordance_is_dependent():
    """PLK1 shape: strongly_concordant_dependent → not the non_dependent-label case → no note."""
    assert run._concordance_scope_note("strongly_concordant_dependent", "common_essential", "common_essential") is None


# ── indication_scope_note: positive pooled verdict enriched OUTSIDE the queried indication ────────────
def _by_scope(cls):
    return {"indication": {"class": cls, "depmap_lineage": "Bowel", "indication": "COADREAD", "median_chronos": -0.248}}


def test_indication_scope_note_fires_on_positive_pooled_outside_indication():
    """BRAF/COADREAD shape: lineage_selective pan-cancer but Bowel not_dependent_in_indication (enriched
    in melanoma). Must flag the target-grain vs indication-lineage divergence."""
    note = run._indication_scope_note("lineage_selective", _by_scope("not_dependent_in_indication"))
    assert note and "TARGET-GRAIN" in note and "Bowel" in note and "COADREAD" in note
    assert "dependency_verdict_by_scope" in note


def test_indication_scope_note_none_when_indication_is_enriched():
    """KRAS/COADREAD shape: selective_in_indication (Bowel IS the enriched lineage) → no flag (byte-stable)."""
    assert run._indication_scope_note("lineage_selective", _by_scope("selective_in_indication")) is None
    # dependent-but-not-enriched also means the indication IS dependent → no mismatch flag
    assert run._indication_scope_note("lineage_selective", _by_scope("dependent_not_enriched")) is None


def test_indication_scope_note_none_on_nonpositive_verdict():
    """A non-positive verdict (discordant/non_dependent/insufficient) is not a target-grain positive →
    the flag does not apply (SMARCA4 discordant is handled by the paralog caveat instead)."""
    by = _by_scope("not_dependent_in_indication")
    assert run._indication_scope_note("discordant", by) is None
    assert run._indication_scope_note("non_dependent", by) is None
    assert run._indication_scope_note("insufficient", by) is None


def test_indication_scope_note_fires_on_not_in_panel():
    assert run._indication_scope_note("selective_dependent", _by_scope("not_in_panel")) is not None
