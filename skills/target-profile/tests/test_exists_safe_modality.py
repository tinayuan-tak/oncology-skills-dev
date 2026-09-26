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
    """An explicit --modality adc clears the WT-loss hold even without a surface sub-verdict (the user is
    asking about the ADC channel, to which WT-loss does not apply)."""
    survivors, supp = tp_gates._suppressed_gate_hits(
        list(_HIT), {"safety": {"fired": _AMP, "verdict": ("highly_constrained_safety_concern", "x")}}, "adc"
    )
    assert not any(h["short"] == "safety" for h in survivors)


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
