"""tp_gates exists-safe-modality (VERDICT_REPRESENTATION.md Layer-2b/3): the safety WT-loss concern
(now emitted RAW by the resolver) is cleared at the gate iff the per-modality safety verdict shows an
admissible safe channel. Verifies the swap is behavior-PRESERVING for nomination: GoF point-mutation
drivers are rescued (stay nominable), amplification-driven / non-GoF constrained targets are NOT."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tp_gates

_HIT = [{"short": "safety", "verdict": "highly_constrained_safety_concern", "action": "hold"}]

# GoF point-mutation driver (KRAS-shape): eligible, not disqualified.
_GOF = [
    {"rule_id": "highly-constrained-safety-warning"},
    {"rule_id": "activating-driver-role-safety-context"},
    {"rule_id": "oncogene-role-safety-context"},
]
# Amplification-driven oncogene (ERBB2-shape): eligible role BUT disqualified (no selectable point mut).
_AMP = _GOF + [{"rule_id": "copy-number-amplified-oncogene-safety-context"}]
# Non-GoF constrained (TP53-shape): concern only, no allele-selective eligibility.
_NONGOF = [{"rule_id": "highly-constrained-safety-warning"}]


def _survives(fired, modality=None):
    survivors, supp = tp_gates._suppressed_gate_hits(
        list(_HIT), {"safety": {"fired": fired, "verdict": ("highly_constrained_safety_concern", "x")}}, modality
    )
    return any(h["short"] == "safety" for h in survivors), supp


def test_gof_point_mutation_rescued():
    survives, supp = _survives(_GOF)
    assert not survives, "GoF driver safety hold should be cleared (small_molecule=conditional exists)"
    assert any(s.get("suppressed_by", {}).get("kind") == "exists_safe_modality" for s in supp)


def test_amplification_driven_not_rescued():
    survives, _ = _survives(_AMP)
    assert survives, "amplification-driven oncogene has no allele-selective escape → hold must stand"


def test_nongof_constrained_not_rescued():
    survives, _ = _survives(_NONGOF)
    assert survives, "non-GoF constrained target has no safe modality → hold must stand"


def test_degrader_scoped_run_keeps_hold():
    # --modality degrader: the degrader channel engages WT → hold stands even for a GoF driver.
    survives, _ = _survives(_GOF, modality="degrader")
    assert survives, "degrader-scoped run must keep the WT-loss hold (degrader depletes WT)"


def test_sm_scoped_run_rescued():
    survives, _ = _survives(_GOF, modality="small_molecule")
    assert not survives, "small_molecule-scoped GoF driver is allele-selective-rescuable"


# --- T2c (2026-08-25): biologics not_applicable clears a WT-loss hold iff the arm is VIABLE ---
# ERBB2-shape: amplification-driven, NO allele-selective SM escape (_AMP → small_molecule=hold), so the
# pre-T2c gate kept the WT-loss hold on every channel. But an ADC engages the amplified surface antigen
# without depleting WT protein — WT-loss is not_applicable to it. The hold should clear WHEN the ADC arm
# is viable (favorable surface fit or an explicit biologics --modality), and ONLY then.


def _survives_surface(fired, surface_verdict, modality=None):
    """exists-safe-modality with a surface_modality sub-verdict present (for the biologics-viability
    co-condition)."""
    subs = {
        "safety": {"fired": fired, "verdict": ("highly_constrained_safety_concern", "x")},
        "surface_modality": {"verdict": (surface_verdict, "adc-tce-fit")},
    }
    survivors, supp = tp_gates._suppressed_gate_hits(list(_HIT), subs, modality)
    return any(h["short"] == "safety" for h in survivors), supp


def test_amp_adc_cleared_when_surface_favorable_enumerate_all():
    """ERBB2 amp-selective ADC: no SM escape, but a FAVORABLE surface fit → the WT-loss hold clears via
    the viable ADC arm (not_applicable). This is the T2c fix."""
    survives, supp = _survives_surface(_AMP, "adc_preferred_tce_unsafe")
    assert not survives, "amp-driven target with a viable ADC arm should clear the WT-loss hold"
    rec = next(s for s in supp if s.get("suppressed_by", {}).get("kind") == "exists_safe_modality")
    assert "adc" in rec["suppressed_by"]["safe_channels"]


def test_amp_not_cleared_when_surface_not_viable():
    """Guard: amp-driven target with NO viable surface arm (neither_viable) → the WT-loss hold STANDS
    (not_applicable does not clear an unusable channel)."""
    survives, _ = _survives_surface(_AMP, "neither_viable")
    assert survives, "no allele-selective escape AND no viable biologics arm → hold must stand"


def test_amp_adc_cleared_when_modality_explicitly_adc():
    """An explicit --modality adc clears the WT-loss hold only when the ADC arm is genuinely VIABLE
    (a favorable surface fit). Biologics-arm viability is a property of the surface fit, not of which
    flag the user passed (#1652): a favorable surface + --modality adc clears."""
    survives, supp = _survives_surface(_AMP, "adc_preferred_tce_unsafe", modality="adc")
    assert not survives, "explicit --modality adc on a favorable surface should clear the WT-loss hold"
    assert any(s.get("suppressed_by", {}).get("kind") == "exists_safe_modality" for s in supp)


def test_explicit_modality_does_not_fail_open_without_surface_verdict():
    """#1652 regression: an explicit --modality adc with NO surface sub-verdict (arm viability never
    established) must NOT clear the WT-loss hold. Pre-fix this short-circuited on (modality == ch) and
    never consulted the surface fit — the fail-open on the nomination go/hold spine."""
    survivors, _ = tp_gates._suppressed_gate_hits(
        list(_HIT), {"safety": {"fired": _AMP, "verdict": ("highly_constrained_safety_concern", "x")}}, "adc"
    )
    assert any(h["short"] == "safety" for h in survivors), "no surface fit → biologics arm not viable → hold stands"


@pytest.mark.parametrize("modality", ["adc", "bite_tce", "antibody", None])
@pytest.mark.parametrize("surface_verdict", ["neither_viable", "shed_dominant_opposed"])
def test_no_viable_surface_arm_keeps_hold_all_biologics_modalities(modality, surface_verdict):
    """#1652 core: a surface verdict with NO viable arm (neither_viable / shed_dominant_opposed) must
    keep the WT-loss safety hold for EVERY biologics modality AND the enumerate-all (modality=None)
    path. The corrected asymmetry: an explicit --modality no longer fails open where the surface fit
    forecloses every arm."""
    survives, _ = _survives_surface(_AMP, surface_verdict, modality=modality)
    assert survives, f"{surface_verdict} + modality={modality}: no viable biologics arm → hold must stand"


@pytest.mark.parametrize("modality", ["adc", "bite_tce", "antibody"])
def test_viable_surface_arm_clears_hold_all_biologics_modalities(modality):
    """Non-regression: a genuinely viable surface fit (favorable) still clears the WT-loss hold for the
    explicit biologics modalities (the deliberate ERBB2/TROP2 clearing)."""
    survives, supp = _survives_surface(_AMP, "adc_preferred_tce_unsafe", modality=modality)
    if modality == "bite_tce":
        # adc_preferred_tce_unsafe explicitly forecloses the TCE channel → hold stands even explicitly.
        assert survives, "TCE-unsafe surface forecloses bite_tce → hold must stand"
    else:
        assert not survives, f"favorable surface + --modality {modality} → hold clears (viable arm)"
        assert any(s.get("suppressed_by", {}).get("kind") == "exists_safe_modality" for s in supp)


def test_amp_degrader_keeps_hold_even_with_favorable_surface():
    """A degrader-scoped run keeps the WT-loss hold even when the surface arm is favorable — a degrader
    depletes WT protein (action=hold), and not_applicable-clearance is biologics-only."""
    survives, _ = _survives_surface(_AMP, "adc_preferred_tce_unsafe", modality="degrader")
    assert survives, "degrader depletes WT → WT-loss hold must stand regardless of surface viability"


def test_intracellular_not_cleared_by_biologics_without_viability():
    """The over-clear guard: a non-GoF constrained target with NO surface sub-verdict (biologics arm not
    viable) must NOT have its WT-loss hold cleared just because biologics report not_applicable."""
    survives, _ = _survives(_NONGOF)  # no surface_modality present → biologics arm not viable
    assert survives, "not_applicable must not clear a hold when the biologics arm is not viable"


def test_surface_foreclosed_channel_not_listed_safe():
    """safe_channels honesty: under `adc_preferred_tce_unsafe` the surface verdict EXPLICITLY forecloses
    the TCE channel, so bite_tce must NOT appear in safe_channels (it is not a genuinely viable escape) —
    while the truly-viable adc/antibody arms still clear the hold. Prevents the per-veto escape scope from
    over-reading as global modality viability (the ERBB2 ADC-only case)."""
    survives, supp = _survives_surface(_AMP, "adc_preferred_tce_unsafe")
    assert not survives
    rec = next(s for s in supp if s.get("suppressed_by", {}).get("kind") == "exists_safe_modality")
    chans = rec["suppressed_by"]["safe_channels"]
    assert "adc" in chans and "antibody" in chans
    assert "bite_tce" not in chans, "TCE-unsafe channel must not be listed as a safe modality"


# --- SK #1603: the clearance set is DERIVED from the vocab nominate favorable set (no drift) ---


def _vocab_favorable():
    import yaml

    path = tp_gates._CONTRACTS_REPO / "vocabularies" / "nomination_verdict_gate.yaml"
    blocks = yaml.safe_load(path.read_text())["thesis_deciding_axes"]
    blk = next(b for b in blocks if b.get("thesis") == "antigen_driven")
    return set(blk["deciding"]["favorable_verdicts"])


def test_surface_favorable_tracks_vocab():
    """Anti-drift guard: the surface-favorable clearance set MUST equal the vocab's
    `thesis_deciding_axes[antigen_driven].deciding.favorable_verdicts` — the same set the nominate
    decider and (as a superset) branch-C use. Fails if the two ever diverge (the #1603 fail-closed bug)."""
    loaded = set(tp_gates._load_surface_favorable_verdicts())
    assert loaded == _vocab_favorable(), (
        "surface-favorable clearance set drifted from the vocab nominate favorable set: "
        f"loaded={sorted(loaded)} vocab={sorted(_vocab_favorable())}"
    )
    # The conservative fallback must be a SUBSET of the vocab set (fewer clears = the safe direction).
    assert set(tp_gates._FALLBACK_SURFACE_FAVORABLE_VERDICTS) <= _vocab_favorable()


@pytest.mark.parametrize(
    "token",
    ["adc_preferred_tce_escape_risk", "adc_preferred_tce_patient_variable", "tce_patient_variable"],
)
def test_new_favorable_tokens_clear_wt_loss_hold(token):
    """The 3 tokens that already downgrade the dependency veto + carry an antigen_driven nomination now
    ALSO clear a WT-loss safety hold on a viable biologics arm (the #1603 divergent-encoding fix)."""
    survives, supp = _survives_surface(_AMP, token)
    assert not survives, f"{token} is a viable surface arm → WT-loss hold should clear (not fail-closed)"
    assert any(s.get("suppressed_by", {}).get("kind") == "exists_safe_modality" for s in supp)
