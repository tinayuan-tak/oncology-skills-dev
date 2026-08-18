"""ground_axis: escalate-only grounded-substrate block — pure-core tests (no network / no Bedrock).

Invariants of the substrate layer:
  - CONTAINMENT: a cited PMID not in the retrieved set is dropped (confabulation guard).
  - ESCALATE-ONLY SHAPE: emits escalate-only FINDINGS + escalate_only=True, and NO risk score
    (LOW/MED/HIGH) — the absence of a re-scored bin is what prevents anchor-propagation.
  - WRAPPER-TOLERANCE: unwraps the structured-output {"value":...} field wrapper; tolerates a
    finding emitted as a bare string.
  - AXIS-PARAMETERIZED: the contract is one structure across axes; safety + dependency are configured
    with different finding nouns/kinds but the same block shape.
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
    out = {"findings": [{"finding": "Ocular tox", "kind": "eye", "cited_pmids": ["111", "999"]}],
           "corroborations": [], "contradicts_deterministic": True, "notes": ""}
    g = ga.build_grounded_block(DET, out, {"111"}, corpus_pin={"mindate": "2015"}, n_retrieved=5)
    assert g["findings"][0]["cited_pmids"] == ["111"]
    assert g["confabulated_dropped"] == ["999"]


def test_escalate_only_shape_no_risk_score():
    g = ga.build_grounded_block(DET, {"findings": [], "corroborations": [],
                                       "contradicts_deterministic": False, "notes": ""},
                                set(), corpus_pin={}, n_retrieved=0)
    assert g["escalate_only"] is True
    assert "risk_level" not in g and "bin" not in g
    assert g["anchor_verdict"] == DET["verdict"]


def test_unwraps_structured_output_and_tolerates_string_finding():
    out = {"findings": {"value": ["CRS liability",
                {"finding": "hepatic", "kind": "liver", "cited_pmids": {"value": ["222"]}}], "_source": "llm"},
           "corroborations": {"value": []}, "contradicts_deterministic": {"value": True}}
    g = ga.build_grounded_block(DET, out, {"222"}, corpus_pin={}, n_retrieved=2)
    findings = [f["finding"] for f in g["findings"]]
    assert "CRS liability" in findings and "hepatic" in findings
    assert g["contradicts_deterministic"] is True


def test_axis_config_has_validated_axes_with_distinct_framing():
    assert {"safety", "dependency"} <= set(ga.AXIS_CONFIG)
    assert ga.AXIS_CONFIG["safety"]["finding_noun"] != ga.AXIS_CONFIG["dependency"]["finding_noun"]
    # each axis maps to a verdict_key + a retrieval category
    for ax, cfg in ga.AXIS_CONFIG.items():
        assert cfg["verdict_key"] and cfg["pubmed_category"] and cfg["cards"]


def test_deterministic_block_selects_axis_cards():
    pkg = {"synthesis": {"sub_verdicts": {"dependency": {"verdict": "lineage_selective",
            "driving_rule_id": "d"}}},
           "cards": [{"card_id": "dependency-lineage-selectivity", "interpretation_call": "lineage_selective"},
                     {"card_id": "gnomad-lof-constraint", "interpretation_call": "tolerant"}]}
    d = ga.deterministic_block(pkg, "dependency")
    assert d["verdict"] == "lineage_selective"
    assert "dependency-lineage-selectivity" in d["cards"]      # dependency card included
    assert "gnomad-lof-constraint" not in d["cards"]           # safety card excluded from dependency axis
