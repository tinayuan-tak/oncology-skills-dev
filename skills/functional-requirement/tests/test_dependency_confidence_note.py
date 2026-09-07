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

from pathlib import Path

from _test_support import load_run_py

fr = load_run_py(Path(__file__).resolve().parent.parent, "fr_run_conf")


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
    assert (
        (v_with, drv_with) == (v_base, drv_base) == ("concordant_dependent", "concordant-dependent-supportive-dominant")
    )


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


# --- cross-consortium corroboration (2026-08-12): independent confidence axis --------------


def test_concordant_consortium_lifts_bare_standard_to_moderate():
    """concordant_dependent (Broad Achilles + Sanger Project Score agree) RAISES a bare
    standard/unknown confidence to moderate — independent-consortium replication is itself a
    confidence handle. The predictability base note is preserved."""
    c = fr._dependency_confidence_note("selective_dependent", "unpredictable", "concordant_dependent")
    assert c["confidence"] == "moderate"
    assert "Independently corroborated across consortia" in c["note"]
    assert "not a verdict downgrade" in c["note"]  # base predictability note preserved


def test_concordant_consortium_lifts_unknown_to_moderate():
    c = fr._dependency_confidence_note("concordant_dependent", "data_unavailable", "concordant_dependent")
    assert c["confidence"] == "moderate"
    assert "Independently corroborated" in c["note"]


def test_concordant_consortium_never_exceeds_high():
    """Already-high (own-omics) stays high + annotates — corroboration never pushes past the top."""
    c = fr._dependency_confidence_note("concordant_dependent", "own_omics_driven", "concordant_dependent")
    assert c["confidence"] == "high"
    assert "Independently corroborated" in c["note"]


def test_discordant_consortium_adds_caveat_no_downgrade():
    """discordant is a confidence CAVEAT, never a downgrade — base level preserved, caution appended."""
    base = fr._dependency_confidence_note("concordant_dependent", "context_or_driver_dependent")
    c = fr._dependency_confidence_note("concordant_dependent", "context_or_driver_dependent", "discordant")
    assert c["confidence"] == base["confidence"] == "moderate"
    assert "CAUTION" in c["note"] and "does NOT corroborate" in c["note"]


def test_no_corroboration_signal_is_backward_compatible():
    """single_consortium_only / data_unavailable / None → identical to the 2-arg call (no change)."""
    for cc in ("single_consortium_only", "data_unavailable", None):
        assert fr._dependency_confidence_note(
            "selective_dependent", "unpredictable", cc
        ) == fr._dependency_confidence_note("selective_dependent", "unpredictable")


def test_corroboration_ignored_on_non_call_verdict():
    """Even concordant corroboration cannot manufacture confidence on a non-call verdict."""
    c = fr._dependency_confidence_note("insufficient", "own_omics_driven", "concordant_dependent")
    assert c["confidence"] == "standard"
    assert "actual dependency call" in c["note"]


# --- co-essential-module confidence fold (2026-08-19, enrichment-review #1) -----------------


def test_coessential_module_card_is_composed():
    assert "coessential-module" in fr.CARDS


def test_coherent_module_raises_confidence_and_annotates():
    # a bare (unknown-predictability) dependency call lifted to moderate by module coherence
    note = fr._dependency_confidence_note(
        "concordant_dependent", None, None, coessential_module_class="in_coherent_module"
    )
    assert note["confidence"] == "moderate"
    assert "Module-anchored" in note["note"]


def test_coherent_module_never_exceeds_high_and_composes_with_predictability():
    # own_omics_driven already high → module coherence keeps it high (never a downgrade)
    note = fr._dependency_confidence_note(
        "concordant_dependent", "own_omics_driven", "concordant_dependent", "in_coherent_module"
    )
    assert note["confidence"] == "high" and "Module-anchored" in note["note"]


def test_isolated_module_is_a_caveat_not_a_downgrade():
    base = fr._dependency_confidence_note("concordant_dependent", "own_omics_driven", None, None)
    iso = fr._dependency_confidence_note("concordant_dependent", "own_omics_driven", None, "isolated_dependency")
    assert iso["confidence"] == base["confidence"] == "high"  # caveat text only, no downgrade
    assert "isolated" in iso["note"]


def test_coessential_module_inert_on_non_call_verdict():
    note = fr._dependency_confidence_note("insufficient", None, None, "in_coherent_module")
    assert note["confidence"] == "standard" and "Module-anchored" not in note["note"]
