"""CASE-016: the surface/immune-thesis PARTICIPATION dimension.

`_surface_thesis_participation` names -- VERDICT-INERT -- that a surface/immune thesis modulated
the composed gate (downgraded a dependency veto given a favorable surface fit; cleared a WT-loss
safety hold for a biologics channel) but is not the DECIDING axis. It reads already-resolved
suppression state and forces nothing.

The suite pins:
  * FIRES end-to-end when the REAL gate records a `biology_axis_downgrade` (faithfulness, not a
    hand-built tautology -- the rule population is read from the live vocab so the test tracks the
    contract);
  * classifies a biologics-channel `exists_safe_modality` clear as surface participation;
  * does NOT over-read an allele-selective SMALL-MOLECULE clear as surface biology (the guard);
  * references the deciding axis the surface thesis could not overtake, and is None-tolerant when
    the run abstains;
  * SILENT when the surface/immune thesis did not modulate the gate;
  * robust to malformed records and pure (no mutation) -- verdict-inert throughout.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run")
# load_run_py puts the skill's scripts/ on sys.path, so the gate module is importable directly --
# needed for the module-level constant + __all__, which run.py does not re-export.
import tp_gates as tpg  # noqa: E402


def _biology_axis_downgrade_rules():
    """The live biology_axis_scoped_veto_downgrade rules -- the exact population that produces the
    surface-downgrade events this dimension names. Read dynamically so the test tracks the vocab."""
    _ctx, _msvs, bavd, _gdvd, _src = tp._load_veto_suppressors()
    return bavd or []


# --- FIRES: end-to-end through the REAL gate --------------------------------


def test_fires_on_a_real_biology_axis_downgrade():
    """Drive an actual dependency-veto downgrade through `_gate_recommendation` (favorable surface
    fit) and assert the dimension names it -- proving the record shape it reads is what the gate
    emits, not a shape the test invented."""
    rules = _biology_axis_downgrade_rules()
    if not rules:
        return  # vocab carries no downgrade rules in this checkout -> nothing to drive
    rule = rules[0]
    dropped_verdict = rule["downgrades"]["verdict"]
    biology_axis = rule["when_biology_axis_in"][0]
    surface_verdict = rule["when_surface_verdict_in"][0]

    subs = {
        "dependency": {"verdict": (dropped_verdict, "dep-rule")},
        "surface_modality": {"verdict": (surface_verdict, "surf-rule")},
    }
    forced, _hits, sup = tp._gate_recommendation(subs, biology_axis=biology_axis)
    assert forced == "hold"  # the veto was downgraded to a hold, not fully cleared
    assert any(s["suppressed_by"]["kind"] == "biology_axis_downgrade" for s in sup)

    dim = tp._surface_thesis_participation(sup, {"basis": "gate_fired", "deciding_axis": {"short": "safety"}})
    assert dim is not None
    assert dim["kind"] == "surface_immune_thesis_participation"
    assert dim["authoritative"] == "verdict"
    assert dim["modulated_axes"] == ["dependency"]
    assert dim["deciding_axis"] == "safety"
    assert len(dim["events"]) == 1
    ev = dim["events"][0]
    assert ev["axis"] == "dependency"
    assert ev["verdict"] == dropped_verdict
    assert ev["modulation"] == "veto_downgraded_to_hold"
    assert ev["surface_verdict"] == surface_verdict
    assert "MODULATES the conservative gate" in dim["note"]
    assert "authoritative and unchanged" in dim["note"]
    assert "`safety`" in dim["note"]  # names the axis it could not overtake


# --- CLASSIFICATION of the two modulation kinds -----------------------------


def _safe_modality_sup(channels, axis="safety", verdict="normal_tissue_protein_safety_concern"):
    # Matches the documented shape emitted at tp_gates.py `exists_safe_modality`.
    return [
        {
            "short": axis,
            "verdict": verdict,
            "suppressed_by": {"kind": "exists_safe_modality", "safe_channels": channels},
        }
    ]


def test_biologics_safe_modality_is_surface_participation():
    for chan in sorted(tpg._BIOLOGICS_CHANNELS):
        dim = tp._surface_thesis_participation(_safe_modality_sup([chan]), None)
        assert dim is not None, f"{chan}: did not fire"
        assert dim["modulated_axes"] == ["safety"]
        ev = dim["events"][0]
        assert ev["modulation"] == "hold_suppressed"
        assert ev["via"] == "biologics_modality"
        assert ev["safe_channels"] == [chan]


def test_small_molecule_only_clear_is_NOT_surface_participation():
    """The guard: an allele-selective small-molecule escape clears the safety hold but is a
    GoF/SM thesis, not surface biology -- it must NOT be read as surface participation."""
    assert tp._surface_thesis_participation(_safe_modality_sup(["small_molecule"]), None) is None


def test_mixed_channels_keep_only_the_biologics_arm():
    dim = tp._surface_thesis_participation(_safe_modality_sup(["small_molecule", "adc"]), None)
    assert dim is not None
    assert dim["events"][0]["safe_channels"] == ["adc"]  # small_molecule filtered out


def test_both_modulation_kinds_union_their_axes():
    sup = [
        {
            "short": "dependency",
            "verdict": "non_dependent",
            "suppressed_by": {"kind": "biology_axis_downgrade", "surface_verdict": "adc_preferred"},
        },
        {
            "short": "safety",
            "verdict": "normal_tissue_protein_safety_concern",
            "suppressed_by": {"kind": "exists_safe_modality", "safe_channels": ["adc"]},
        },
    ]
    dim = tp._surface_thesis_participation(sup, None)
    assert dim is not None
    assert dim["modulated_axes"] == ["dependency", "safety"]
    assert len(dim["events"]) == 2


# --- deciding-axis reference ------------------------------------------------


def test_deciding_axis_none_when_run_abstains():
    """No fired gate (abstention) -> deciding_axis is None and the note omits the 'not the surface
    thesis' clause, but the participation is still surfaced."""
    dim = tp._surface_thesis_participation(_safe_modality_sup(["adc"]), {"basis": "abstain_routing"})
    assert dim is not None
    assert dim["deciding_axis"] is None
    assert "not the surface/immune thesis" not in dim["note"]


def test_deciding_axis_read_only_from_a_fired_gate():
    dim = tp._surface_thesis_participation(
        _safe_modality_sup(["adc"]), {"basis": "gate_fired", "deciding_axis": {"short": "dependency"}}
    )
    assert dim["deciding_axis"] == "dependency"


# --- SILENT + robustness + purity -------------------------------------------


def test_silent_when_no_surface_modulation():
    assert tp._surface_thesis_participation([], None) is None
    other = [
        {
            "short": "dependency",
            "verdict": "non_dependent",
            "suppressed_by": {"kind": "thesis_irrelevant_axis", "thesis": "antigen_driven"},
        }
    ]
    assert tp._surface_thesis_participation(other, None) is None
    modality_scoped = [
        {
            "short": "dependency",
            "verdict": "non_dependent",
            "suppressed_by": {"kind": "modality_scoped", "modality": "adc"},
        }
    ]
    assert tp._surface_thesis_participation(modality_scoped, None) is None


def test_robust_to_malformed_records():
    for bad in (
        [{"short": "safety"}],
        [{"suppressed_by": "not-a-dict"}],
        [{}],
        ["bare-string"],
        [{"suppressed_by": {"kind": "exists_safe_modality"}}],
    ):
        assert tp._surface_thesis_participation(bad, None) is None


def test_does_not_mutate_input():
    sup = _safe_modality_sup(["adc"])
    before = [dict(s) for s in sup]
    tp._surface_thesis_participation(sup, None)
    assert sup == before


def test_exported_in_all():
    assert "_surface_thesis_participation" in tpg.__all__
