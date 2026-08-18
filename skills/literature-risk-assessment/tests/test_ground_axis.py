"""ground_axis: escalate-only grounded-substrate block — pure-core tests (no network / no Bedrock).

Pins the load-bearing invariants of the substrate layer [2]:
  - CONTAINMENT: a cited PMID not in the retrieved set is dropped (confabulation guard).
  - ESCALATE-ONLY SHAPE: the block emits liability FINDINGS + escalate_only=True, and NO risk score
    (LOW/MED/HIGH) — the absence of a re-scored bin is what structurally prevents anchor-propagation.
  - WRAPPER-TOLERANCE: unwraps the structured-output {"value":...,"_source":...} field wrapper and
    tolerates a finding emitted as a bare string.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "scripts" / "ground_axis.py"


def _load():
    spec = importlib.util.spec_from_file_location("ground_axis", _MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ga = _load()
DET = {"verdict": "wt_human_genetics_mechanism_mismatch", "driving_rule_id": "r", "cards": {}}


def test_containment_drops_pmids_not_in_corpus():
    llm_out = {"liability_findings": [
        {"liability": "Ocular tox", "organ_or_class": "eye", "cited_pmids": ["111", "999"]}],
        "corroborations_of_deterministic": [], "contradicts_deterministic": True, "notes": ""}
    g = ga.build_grounded_block(DET, llm_out, {"111"}, corpus_pin={"mindate": "2015"}, n_retrieved=5)
    f = g["liability_findings"][0]
    assert f["cited_pmids"] == ["111"]          # 999 not in corpus -> dropped
    assert g["confabulated_dropped"] == ["999"]


def test_escalate_only_shape_no_risk_score():
    g = ga.build_grounded_block(DET, {"liability_findings": [], "corroborations_of_deterministic": [],
                                       "contradicts_deterministic": False, "notes": ""},
                                set(), corpus_pin={}, n_retrieved=0)
    assert g["escalate_only"] is True
    assert "risk_level" not in g and "bin" not in g   # emits findings, NOT a re-scored LOW/MED/HIGH
    assert g["anchor_verdict"] == DET["verdict"]


def test_unwraps_structured_output_and_tolerates_string_finding():
    # structured-output wraps each field; a finding may arrive as a bare string
    llm_out = {"liability_findings": {"value": ["CRS liability", {"liability": "hepatic",
                "organ_or_class": "liver", "cited_pmids": {"value": ["222"]}}], "_source": "llm"},
        "corroborations_of_deterministic": {"value": []},
        "contradicts_deterministic": {"value": True}}
    g = ga.build_grounded_block(DET, llm_out, {"222"}, corpus_pin={}, n_retrieved=2)
    libs = [f["liability"] for f in g["liability_findings"]]
    assert "CRS liability" in libs and "hepatic" in libs
    assert g["contradicts_deterministic"] is True
