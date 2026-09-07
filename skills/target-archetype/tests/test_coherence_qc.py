"""Guards for the role-recovery coherence-QC (offline analysis tool; DESCRIPTIVE, verdict-inert)."""

import csv
import importlib.util
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import Atlas  # noqa: E402

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
CQC = Path(__file__).resolve().parents[1] / "scripts" / "coherence_qc.py"
ROLES = Path(__file__).resolve().parent / "fixtures" / "oncokb_roles.csv"


def _mod():
    spec = importlib.util.spec_from_file_location("coherence_qc", CQC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _roles():
    return {r["target"]: r["role"] for r in csv.DictReader(open(ROLES))}


def test_role_coherence_report_recovers_signal_and_flags_incoherent():
    m = _mod()
    rows, summary = m.coherence_report(Atlas.load(ATLAS), _roles())
    assert summary["n"] > 100
    # de-circularized (genomic axis removed) recovery is a REAL signal (clears chance), honestly modest
    assert summary["auc"] > 0.5
    assert "removed 'genomic_alteration'" in summary["de_circularized"]
    # every row is a coherence judgement with the required fields
    for r in rows[:20]:
        assert set(r) >= {"target", "indication", "oncokb_role", "pred_role", "agree"}
        assert r["oncokb_role"] in ("oncogene", "tsg") and isinstance(r["agree"], bool)
    # the incoherent (review) set is a strict subset, and its size matches the summary
    disagree = [r for r in rows if not r["agree"]]
    assert 0 < len(disagree) < len(rows)
    assert len(disagree) == summary["n_disagree"]


def test_role_head_is_de_circularized_no_genomic_features():
    # the report must not depend on the OncoKB-fed genomic axis (the de-circularization contract)
    m = _mod()
    atlas = Atlas.load(ATLAS)
    dc = [k for k in atlas.feature_order if k.split("::")[0] != m.DECIRC_DROP_AXIS]
    assert len(dc) < len(atlas.feature_order)  # genomic features were dropped
    assert not any(k.split("::")[0] == "genomic_alteration" for k in dc)


def test_empty_roles_degrades_gracefully():
    m = _mod()
    rows, summary = m.coherence_report(Atlas.load(ATLAS), {})
    assert rows == [] and summary["n"] == 0


def _surface():
    import csv

    p = Path(__file__).resolve().parent / "fixtures" / "cspa_surface.csv"
    return {r["target"]: r["surface"] for r in csv.DictReader(open(p))}


def test_surface_head_recovers_cspa_strongly_and_flags_incoherent():
    m = _mod()
    rows, summary = m.coherence_report(Atlas.load(ATLAS), _surface(), head="surface")
    assert summary["head"] == "surface"
    # surfaceome is the most de-circularizable label (lit) — de-circ recovery clears chance by a wide margin
    assert summary["auc"] > 0.75
    assert "removed 'surface_modality'" in summary["de_circularized"]
    for r in rows[:20]:
        assert set(r) >= {"target", "indication", "cspa_surface", "pred_surface", "agree"}
        assert r["cspa_surface"] in ("yes", "no") and isinstance(r["agree"], bool)
    disagree = [r for r in rows if not r["agree"]]
    assert 0 < len(disagree) < len(rows) and len(disagree) == summary["n_disagree"]


def test_heads_registry_is_de_circularized_per_head():
    m = _mod()
    assert set(m.HEADS) >= {"role", "surface"}
    assert m.HEADS["role"]["drop_axis"] == "genomic_alteration"
    assert m.HEADS["surface"]["drop_axis"] == "surface_modality"  # de-circ removes the surface-fed axis


def _pred():
    import csv

    p = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "depmap_predictability.csv"
    return {
        r["target"]: {
            "predictability_class": r["predictability_class"],
            "r2_rf": r["r2_rf"],
            "dominant_feature_class": r["dominant_feature_class"],
        }
        for r in csv.DictReader(open(p))
        if r["predictability_class"] != "not_evaluated"
    }


def test_dependency_predictability_annotation():
    m = _mod()
    rows, summary = m.dependency_predictability_report(Atlas.load(ATLAS), _pred())
    assert summary["n_evaluated"] > 100
    # most dependencies are NOT omics-explainable (the honest minority-predictable finding)
    assert 0.0 < summary["explainable_fraction"] < 0.6
    assert summary["n_explainable"] == sum(1 for r in rows if r["explainable"])
    for r in rows[:20]:
        assert set(r) >= {"target", "indication", "predictability_class", "explainable"}
        assert isinstance(r["explainable"], bool)
    # explainable set is exactly the non-'unpredictable' classes
    for r in rows:
        assert r["explainable"] == (r["predictability_class"] in m._PREDICTABLE_CLASSES)
