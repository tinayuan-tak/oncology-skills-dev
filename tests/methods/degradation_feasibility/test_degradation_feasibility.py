"""degradation_feasibility — per-target degradability feasibility (degrader-lens E3 slice).

Tests the precedence (unfavorable_location > precedented_degradable > ubiquitination_substrate >
plausible_untested > data_unavailable) with injected e3_row/precedent/surface_family_class
(hermetic; no S3), and the asymmetric-absence semantics (no natural substrate is NOT disqualifying).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.degradation_feasibility import read as r  # noqa: E402

_PRECEDENT = {"BRD4": {"examples": ["dBET1", "ARV-771"], "e3": "CRBN/VHL"},
              "AR": {"examples": ["ARV-110 (bavdegalutamide)"], "e3": "CRBN"}}
_LIT_ROW = {"e3_substrate_evidence": "literature", "n_e3_ligases_literature": 54,
            "e3_ligases_literature": ["MDM2", "COP1", "BTRC"], "e3_types_literature": ["RING", "HECT"],
            "n_e3_predicted_confident": 470}
_PRED_ROW = {"e3_substrate_evidence": "predicted_only", "n_e3_ligases_literature": 0,
             "e3_ligases_literature": [], "e3_types_literature": [], "n_e3_predicted_confident": 12}


def test_location_gate_wins_over_everything():
    # a surface protein that ALSO has precedent + literature substrate → still unfavorable_location
    out = r.degradation_feasibility_for_gene("BRD4", surface_family_class="surface",
                                             e3_row=_LIT_ROW, precedent=_PRECEDENT)
    assert out["degradability_feasibility_class"] == "unfavorable_location"
    assert out["surface_location_excluded"] is True
    assert "cannot engage" in out["degradability_context"]


def test_secreted_also_excluded():
    out = r.degradation_feasibility_for_gene("X", surface_family_class="secreted",
                                             e3_row=_LIT_ROW, precedent={})
    assert out["degradability_feasibility_class"] == "unfavorable_location"


def test_curated_precedent_beats_substrate():
    # intracellular (no surface class) + precedent → precedented_degradable (even with lit substrate)
    out = r.degradation_feasibility_for_gene("BRD4", surface_family_class="intracellular",
                                             e3_row=_LIT_ROW, precedent=_PRECEDENT)
    assert out["degradability_feasibility_class"] == "precedented_degradable"
    assert out["degrader_precedent"] is True
    assert "dBET1" in out["degradability_context"]


def test_literature_substrate_when_no_precedent():
    out = r.degradation_feasibility_for_gene("TP53", surface_family_class=None,
                                             e3_row=_LIT_ROW, precedent={})
    assert out["degradability_feasibility_class"] == "ubiquitination_substrate"
    assert out["n_e3_ligases_literature"] == 54
    assert "positive degradability prior" in out["degradability_context"]


def test_plausible_untested_when_intracellular_no_evidence():
    # predicted-only substrate, no precedent, not surface → plausible_untested (absence NOT a veto)
    out = r.degradation_feasibility_for_gene("NEWGENE", surface_family_class="intracellular",
                                             e3_row=_PRED_ROW, precedent={})
    assert out["degradability_feasibility_class"] == "plausible_untested"
    assert out["surface_location_excluded"] is False
    assert "NOT" in out["degradability_context"]


def test_data_unavailable_when_no_signal_at_all():
    # no row AND no surface class → genuinely nothing to reason from
    out = r.degradation_feasibility_for_gene("NOPE", surface_family_class=None,
                                             e3_row=None, precedent={})
    assert out["degradability_feasibility_class"] == "data_unavailable"
    assert out["degradability_context"] is None


def test_absence_of_natural_substrate_is_not_disqualifying():
    # a real PROTAC target (BRD4) with only predicted substrate but curated precedent → still degradable
    out = r.degradation_feasibility_for_gene("BRD4", surface_family_class="intracellular",
                                             e3_row=_PRED_ROW, precedent=_PRECEDENT)
    assert out["degradability_feasibility_class"] == "precedented_degradable"
