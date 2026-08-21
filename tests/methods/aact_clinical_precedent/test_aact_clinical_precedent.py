"""aact_clinical_precedent — clinical-trial precedent composition (pure, offline-tested).

Properties: the aggregator's drug-set intersection + highest-stage/approved/failure derivation, and
the coverage-gap paths (no mesh_terms lane -> insufficient; no engaging drug -> no_known_agent)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.aact_clinical_precedent.read")


def _row(cond, drug, phase="PHASE2", n_trials=3, n_active=1, n_terminated=0, itype="DRUG", ncts="NCT1"):
    return {"condition_mesh_term": cond, "intervention_name_norm": drug, "highest_phase": phase,
            "n_trials": n_trials, "n_active": n_active, "n_terminated": n_terminated,
            "intervention_type": itype, "example_nct_ids": ncts}


def test_approved_agent_gives_approved_stage():
    rows = [_row("breast neoplasms", "trastuzumab", phase="PHASE4", n_active=5),
            _row("breast neoplasms", "some-experimental", phase="PHASE1")]
    out = r.aggregate_precedent(rows, drug_set={"trastuzumab", "some-experimental"},
                                approved_drugs={"trastuzumab"})
    assert out["highest_clinical_stage"] == "approved"
    assert out["approved_agents"] == ["trastuzumab"]
    assert out["n_active_trials"] == 6   # 5 (trastuzumab) + 1 (some-experimental default)
    assert out["clinical_precedent_class"] == "trial_precedent_present"


def test_phase_mapping_without_approval():
    rows = [_row("colorectal neoplasms", "drugx", phase="PHASE2")]
    out = r.aggregate_precedent(rows, {"drugx"}, approved_drugs=set())
    assert out["highest_clinical_stage"] == "phase_2"
    rows2 = [_row("colorectal neoplasms", "drugy", phase="PHASE3")]
    assert r.aggregate_precedent(rows2, {"drugy"}, set())["highest_clinical_stage"] == "phase_3"


def test_notable_failures_from_terminated():
    rows = [_row("melanoma", "failed-drug", phase="PHASE2", n_terminated=4),
            _row("melanoma", "ok-drug", phase="PHASE3", n_terminated=0)]
    out = r.aggregate_precedent(rows, {"failed-drug", "ok-drug"}, set())
    assert out["notable_failures"] == ["failed-drug"]


def test_drug_set_intersection_excludes_nonengaging_drugs():
    """A trial-precedent row for a drug that does NOT engage the target is excluded."""
    rows = [_row("melanoma", "pembrolizumab", phase="PHASE4"),   # engages PDCD1, not our target
            _row("melanoma", "vemurafenib", phase="PHASE3")]      # engages BRAF (our target)
    out = r.aggregate_precedent(rows, drug_set={"vemurafenib"}, approved_drugs=set())
    assert out["n_agents_engaging_target"] == 1
    assert out["highest_clinical_stage"] == "phase_3"


def test_no_matching_drug_is_no_precedent():
    rows = [_row("melanoma", "pembrolizumab", phase="PHASE4")]
    out = r.aggregate_precedent(rows, drug_set={"vemurafenib"}, approved_drugs=set())
    assert out["clinical_precedent_class"] == "no_trial_precedent"
    assert out["highest_clinical_stage"] == "none"


def test_insufficient_when_no_mesh_lane(monkeypatch):
    monkeypatch.setattr(r, "_indication_mesh_terms", lambda ind: [])
    out = r.read_clinical_precedent("ERBB2", "MADE_UP")
    assert out["clinical_precedent_class"] == "insufficient"


def test_no_known_agent_when_target_has_no_directional_drug(monkeypatch):
    monkeypatch.setattr(r, "_indication_mesh_terms", lambda ind: ["breast neoplasms"])
    monkeypatch.setattr(r, "_target_drug_set", lambda t: (set(), set()))
    out = r.read_clinical_precedent("SOMEGENE", "BRCA")
    assert out["clinical_precedent_class"] == "no_known_agent"


def test_crosswalk_loader_reads_mesh_terms(monkeypatch, tmp_path):
    vocab = tmp_path / "vocabularies"
    vocab.mkdir()
    (vocab / "indication_crosswalk.yaml").write_text(
        "indications:\n  - canonical_code: COADREAD\n    mesh_terms: [\"colorectal neoplasms\"]\n")
    monkeypatch.setattr(r, "TARGET_CONTRACTS", tmp_path)
    assert r._indication_mesh_terms("coadread") == ["colorectal neoplasms"]
