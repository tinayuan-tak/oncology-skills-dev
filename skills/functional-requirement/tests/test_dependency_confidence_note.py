"""Gate-C gap 1 (Option A, 2026-07-21): dependency-predictability CONFIDENCE annotation.

dependency-predictability is composed into the dependency skill as META-evidence: it drives
a `dependency_confidence_note` over the verdict, and NEVER the verdict itself (predictability
answers "how omics-learnable is this dependency, and by what feature?" — confidence, not a call).

These tests pin:
  1. the verdict path is UNTOUCHED (delegates to the resolver; predictability rule_ids never
     appear in a rung — so no verdict changes regardless of predictability_class);
  2. the confidence note maps each predictability_class correctly, ONLY on a real dependency call;
  3. on a non-call verdict (insufficient/discordant) the note is neutral (nothing to be confident in);
  4. the card is composed (in CARDS) so it actually runs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("fr_run_conf", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fr = _load()


# --- composition ---------------------------------------------------------------------------

def test_predictability_card_is_composed():
    assert "dependency-predictability" in fr.CARDS


# --- verdict path is untouched by predictability -------------------------------------------

def test_verdict_ignores_predictability_rules():
    """A predictability rule firing must NOT change the verdict — it is not in any resolver rung.
    A concordant-dependent call stays concordant_dependent whatever predictability says."""
    base = [{"rule_id": "concordant-dependent-supportive-dominant"}]
    v_base, drv_base = fr._verdict(base)
    v_with, drv_with = fr._verdict(base + [{"rule_id": "predictability-biomarker-hypothesis-supportive"}])
    assert (v_with, drv_with) == (v_base, drv_base) == ("concordant_dependent",
                                                        "concordant-dependent-supportive-dominant")


# --- confidence-note mapping ---------------------------------------------------------------

def test_own_omics_driven_is_high_confidence_on_a_call():
    c = fr._dependency_confidence_note("concordant_dependent", "own_omics_driven")
    assert c["confidence"] == "high" and "own omics" in c["note"]


def test_context_driven_is_moderate():
    c = fr._dependency_confidence_note("lineage_selective", "context_or_driver_dependent")
    assert c["confidence"] == "moderate"


def test_unpredictable_is_standard_not_a_downgrade():
    for pc in ("weakly_predictable", "unpredictable"):
        c = fr._dependency_confidence_note("selective_dependent", pc)
        assert c["confidence"] == "standard"
        assert "not a verdict downgrade" in c["note"]


def test_data_unavailable_is_unknown():
    c = fr._dependency_confidence_note("concordant_dependent", "data_unavailable")
    assert c["confidence"] == "unknown"
    c2 = fr._dependency_confidence_note("concordant_dependent", None)
    assert c2["confidence"] == "unknown"


def test_note_neutral_on_a_non_call_verdict():
    """On insufficient/discordant there is no dependency call to be confident in — the note is
    standard with no meta-claim, even if predictability is own_omics_driven."""
    for verdict in ("insufficient", "discordant"):
        c = fr._dependency_confidence_note(verdict, "own_omics_driven")
        assert c["confidence"] == "standard"
        assert "actual dependency call" in c["note"]


def test_confidence_applies_to_veto_verdict_too():
    """A non_dependent veto is a real call — an omics-predictable non-dependence is a
    higher-confidence negative, so the annotation still applies (not just to positives)."""
    c = fr._dependency_confidence_note("non_dependent", "own_omics_driven")
    assert c["confidence"] == "high"
