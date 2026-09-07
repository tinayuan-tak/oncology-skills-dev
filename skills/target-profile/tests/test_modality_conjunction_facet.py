"""Test the cross-lens modality-conjunction facet:
1. None when the presence claim vector is absent (graceful);
2. a neither_viable / broadly-normal / heterogeneous profile FAILs both modalities,
   with the weakest gate attributed correctly (surface for ADC, homogeneity for TCE);
3. a clean profile (both_viable surface + strong-selective window + abundant/malignant/homogeneous)
   PASSes both;
4. the facet is VERDICT-INERT — it exposes ADC/TCE calls + a safety SIGNAL, never a recommendation.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent  # skills/ — for _skills_common imports pulled in by tp_facets
for _p in (str(SCRIPTS), str(SKILLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_facets import _modality_conjunction_facet  # noqa: E402


def _sr(A, C, hom, sel, surf, safe="tolerant"):
    return {
        "expression": {
            "synthesis_facet": {"claim_vector": {"A": {"signal": A}, "C": {"signal": C}, "homogeneity": hom}}
        },
        "selectivity": {"verdict": (sel, "r")},
        "surface_modality": {"verdict": (surf, "r")},
        "safety": {"verdict": (safe, "r")},
    }


def test_none_without_claim_vector():
    assert _modality_conjunction_facet({"expression": {}}) is None
    assert _modality_conjunction_facet({"expression": {"synthesis_facet": {}}}) is None


def test_neither_viable_fails_both_with_correct_weakest_gate():
    f = _modality_conjunction_facet(
        _sr("weak", "weak", "heterogeneous", "selective_but_broadly_normal", "neither_viable")
    )
    assert f["ADC"]["call"] == "FAIL"
    assert f["ADC"]["weakest_gate"] == "surface"  # neither_viable surface kills ADC
    assert f["TCE"]["call"] == "FAIL"
    assert f["TCE"]["weakest_gate"] == "homogeneity"  # heterogeneous is the TCE killer
    assert f["safety_signal"] == "tolerant"


def test_clean_profile_passes_both():
    f = _modality_conjunction_facet(_sr("moderate", "strong", "homogeneous", "strong_tumor_selective", "both_viable"))
    assert f["ADC"]["call"] == "PASS"
    assert f["TCE"]["call"] == "PASS"


def test_verdict_inert_shape():
    f = _modality_conjunction_facet(_sr("moderate", "strong", "homogeneous", "strong_tumor_selective", "both_viable"))
    # no recommendation/verdict key — it only carries per-modality calls + inputs + a safety signal
    assert set(f) >= {"ADC", "TCE", "inputs", "safety_signal", "_disclaimer"}
    assert "recommendation" not in f and "verdict" not in f
    assert "VERDICT-INERT" in f["_disclaimer"]


def _sr_spine(A, C, hom, sel, surf, safe="tolerant"):
    """Presence A/C/homogeneity carried on the skill_report[] SPINE (chips + claim_scalars), not the raw
    claim_vector — the contract §100-128 read path."""
    return {
        "expression": {
            "synthesis_facet": {
                "skill_report": {
                    "claim_chips": [{"key": "A", "signal": A}, {"key": "C", "signal": C}],
                    "claim_scalars": {"homogeneity": hom},
                }
            }
        },
        "selectivity": {"verdict": (sel, "r")},
        "surface_modality": {"verdict": (surf, "r")},
        "safety": {"verdict": (safe, "r")},
    }


def test_presence_inputs_read_from_spine():
    # No raw claim_vector anywhere — the facet must reconstruct A/C/homogeneity from the skill_report spine.
    f = _modality_conjunction_facet(
        _sr_spine("moderate", "strong", "homogeneous", "strong_tumor_selective", "both_viable")
    )
    assert f is not None
    assert f["ADC"]["call"] == "PASS" and f["TCE"]["call"] == "PASS"
    # heterogeneous on the spine still drives the TCE homogeneity killer
    g = _modality_conjunction_facet(
        _sr_spine("weak", "weak", "heterogeneous", "selective_but_broadly_normal", "neither_viable")
    )
    assert g["TCE"]["call"] == "FAIL" and g["TCE"]["weakest_gate"] == "homogeneity"
