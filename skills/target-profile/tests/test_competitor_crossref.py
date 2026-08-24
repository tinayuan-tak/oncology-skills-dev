"""Competitor cross-reference facet (verdict-inert) — the competitor-landscape VALUE-ADD.

Locks the deterministic cross-ref of the Open Targets competitor field (carried on the
differentiation facet) against the framework's own surface-modality-fit verdict:
  - the DLL3 archetype (framework says adc_preferred_tce_unsafe, but the APPROVED competitor is a
    TCE and the ADC failed at PHASE_3) => modality_contrarian=True + a contrarian hook,
  - white-space (no competitor),
  - validated (framework's preferred modality IS the approved competitor modality),
and that the facet NEVER emits a verdict / recommendation (it is a pure facet).
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent          # skills/ — for _skills_common imports pulled in by tp_facets
for _p in (str(SCRIPTS), str(SKILLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_facets import _competitor_crossref_facet, _framework_preferred_modalities  # noqa: E402


def _sub_results(competitor_facet, surface_verdict):
    return {
        "differentiation": {"synthesis_facet": competitor_facet},
        "surface_modality": {"verdict": [surface_verdict, "some-rule"] if surface_verdict else None},
    }


def test_dll3_archetype_modality_inversion_is_flagged_contrarian():
    """DLL3/SCLC: framework adc_preferred_tce_unsafe, but the APPROVED competitor is a TCE and the
    ADC reached PHASE_3 without approval — the cross-ref must flag modality_contrarian + hooks."""
    diff = {
        "competitor_class": "approved_competitor",
        "competitor_indication_scope": "indication",
        "n_competitor_programs": 2,
        "competitor_approved_agents": ["TARLATAMAB"],
        "competitor_late_stage_non_approved": ["ROVALPITUZUMAB TESIRINE"],
        "competitor_modality_landscape": {
            "TCE": {"n_programs": 1, "max_clinical_stage": "APPROVAL", "approved": True,
                    "example_agents": ["TARLATAMAB"]},
            "ADC": {"n_programs": 1, "max_clinical_stage": "PHASE_3", "approved": False,
                    "example_agents": ["ROVALPITUZUMAB TESIRINE"]},
        },
    }
    cx = _competitor_crossref_facet(_sub_results(diff, "adc_preferred_tce_unsafe"))
    assert cx is not None
    assert cx["competition_density"] == "crowded"
    assert cx["framework_preferred_modality"] == ["ADC"]
    assert cx["competitor_modalities_approved"] == ["TCE"]
    assert cx["modality_contrarian"] is True
    assert cx["modality_positioning"]["ADC"] == "attempted_not_approved"
    hooks = " ".join(cx["differentiation_hooks"]).lower()
    assert "contrarian" in hooks
    assert "not approved" in hooks  # the failed-ADC-precedent de-risk hook
    # strictly verdict-inert: the facet exposes no verdict / recommendation key
    assert "verdict" not in cx and "recommendation" not in cx


def test_white_space_when_no_competitor():
    diff = {"competitor_class": "no_known_competitor", "n_competitor_programs": 0,
            "competitor_modality_landscape": {}}
    cx = _competitor_crossref_facet(_sub_results(diff, "both_viable"))
    assert cx["competition_density"] == "white_space"
    assert cx["modality_contrarian"] is False
    assert any("white space" in h.lower() for h in cx["differentiation_hooks"])


def test_validated_when_preferred_modality_is_the_approved_competitor():
    """Framework prefers ADC and an approved ADC competitor exists — validated, not contrarian."""
    diff = {
        "competitor_class": "approved_competitor", "n_competitor_programs": 1,
        "competitor_approved_agents": ["SOME-ADC"],
        "competitor_modality_landscape": {
            "ADC": {"n_programs": 1, "max_clinical_stage": "APPROVAL", "approved": True,
                    "example_agents": ["SOME-ADC"]},
        },
    }
    cx = _competitor_crossref_facet(_sub_results(diff, "adc_preferred"))
    assert cx["modality_contrarian"] is False
    assert cx["modality_positioning"]["ADC"] == "validated_approved"
    assert any("crowded at the framework's preferred modality" in h.lower()
               for h in cx["differentiation_hooks"])


def test_returns_none_when_no_competitor_signal():
    assert _competitor_crossref_facet(_sub_results({}, "adc_preferred")) is None
    assert _competitor_crossref_facet(_sub_results({"competitor_class": "insufficient"}, "adc_preferred")) is None
    assert _competitor_crossref_facet({}) is None


def test_framework_preferred_modality_token_map():
    assert _framework_preferred_modalities("both_viable") == {"ADC", "TCE"}
    assert _framework_preferred_modalities("adc_preferred") == {"ADC"}
    assert _framework_preferred_modalities("adc_preferred_tce_unsafe") == {"ADC"}
    assert _framework_preferred_modalities("tce_preferred") == {"TCE"}
    # no clear surface preference => empty (never guesses)
    assert _framework_preferred_modalities("neither_viable") == set()
    assert _framework_preferred_modalities("isoform_dependent_undefined") == set()
    assert _framework_preferred_modalities(None) == set()
