"""Step-3 (signals-first): FIRST-CLASS SUBTYPE. The per-stratum reads (multiplicity-aware, #798) are
elevated INTO the sub-group structure as `by_stratum`, surfaced by default — not just the opt-in
panorama. Subtype stays an orthogonal conditioner (refines a sub-group per stratum; not a new
sub-group). Verdict-INERT."""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


tp = _load()


def _cvbs():
    return {"stratification_class": "subtype_enriched", "subtype_variance_explained": 0.21,
            "multiplicity_strata_tested": 14, "which_subtypes_separate": {"highest": "MSI_H", "lowest": "MSS"},
            "strata": {
                "MSI_H": {"A": {"signal": "strong", "corroboration": "moderate", "evidence": "median 6.0"}, "n_tumor_samples": 100},
                "MSS": {"A": {"signal": "weak", "corroboration": "moderate", "evidence": "median 1.5"}, "n_tumor_samples": 100}}}


def test_by_stratum_elevated_into_subgroup():
    sg = {"abundance": {"signal": "strong", "confidence": "moderate", "sources": []}}
    tp._attach_subtype_firstclass(sg, _cvbs())
    bs = sg["abundance"]["by_stratum"]
    assert bs["MSI_H"]["signal"] == "strong" and bs["MSI_H"]["certainty"] == "moderate"
    assert bs["MSS"]["signal"] == "weak"
    ax = sg["abundance"]["subtype_axis"]
    assert ax["epsilon_squared"] == 0.21 and ax["multiplicity_strata_tested"] == 14


def test_noop_when_no_strata():
    sg = {"abundance": {"signal": "strong"}}
    tp._attach_subtype_firstclass(sg, None)
    tp._attach_subtype_firstclass(sg, {"strata": {}})
    assert "by_stratum" not in sg["abundance"]


def test_conditioner_not_a_new_subgroup():
    """by_stratum lives UNDER a sub-group (a conditioner), never as its own top-level sub-group."""
    sg = {"abundance": {"signal": "strong"}, "malignant_intrinsic": {"signal": "strong"}}
    tp._attach_subtype_firstclass(sg, _cvbs())
    assert set(sg) == {"abundance", "malignant_intrinsic"}          # no new sub-group minted
    assert "by_stratum" in sg["abundance"]
