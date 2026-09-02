"""literature-risk-assessment: guard + shape tests (no network / no Bedrock).

The load-bearing invariant is the CONTAINMENT GUARD: an LLM must never emit a PMID from memory;
only PMIDs present in the retrieved corpus may be cited. These tests pin that guard + the
6-dimension shape + the overlap-anchor mapping, all without a live call.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("lra_run", _RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rc = _load()


def test_containment_drops_pmids_not_in_corpus():
    retrieved = {"111", "222"}
    good, bad = rc._contain(["111", "999"], retrieved)   # 999 never retrieved → confabulated
    assert good == ["111"]
    assert bad == ["999"]


def test_containment_all_grounded_is_clean():
    good, bad = rc._contain(["111", "222"], {"111", "222", "333"})
    assert bad == []                       # retrieval-grounded → zero confabulation
    assert set(good) == {"111", "222"}


def test_containment_handles_none_and_ints():
    good, bad = rc._contain(None, {"1"})
    assert good == [] and bad == []
    good, bad = rc._contain([111, "222"], {"111"})   # int coerced to str
    assert good == ["111"] and bad == ["222"]


def test_containment_normalizes_misformatted_pmid():
    # a real-but-misformatted citation ('PMID 111', 'PMID: 222') must NOT be dropped as confabulated
    good, bad = rc._contain(["PMID 111", "PMID: 222", "PMID 999"], {"111", "222"})
    assert set(good) == {"111", "222"}
    assert bad == ["999"]


class _Ab:
    def __init__(self, pmid):
        self.pmid, self.year, self.title, self.abstract = pmid, 2020, "t", "body"


class _Res:
    def __init__(self, by_cat):
        self.abstracts_by_category = by_cat


def test_run_downgrades_grade_with_only_confabulated_citations(monkeypatch):
    # A HIGH grade whose only cited PMID was confabulated (not retrieved) must be downgraded to
    # not_assessed rather than shipping an ungrounded risk level (P0.2 grounding-integrity).
    monkeypatch.setattr(rc.ps, "search_pubmed",
                        lambda *a, **k: _Res({"safety": [_Ab("111")]}))
    monkeypatch.setattr(rc.ps, "SEARCH_PATTERNS_BY_CATEGORY",
                        {d: "{gene} {disease}" for d in rc.DIMENSIONS}, raising=False)
    monkeypatch.setattr(rc, "synthesize_structured",
                        lambda *a, **k: {"risk_level": "HIGH", "justification": "j",
                                         "interpretation": "i", "cited_pmids": ["999"],
                                         "contradicts_deterministic": False})
    res = rc.run("GENE", "safety-indication", None, "2015", "2026", per_cat=1)
    d = res["dimensions"]["safety"]
    assert d["risk_level"] == "not_assessed"
    assert d["risk_level_pre_containment"] == "HIGH"
    assert d["confabulated_dropped"] == ["999"] and d["cited_pmids"] == []


def test_run_keeps_grade_with_surviving_citation(monkeypatch):
    monkeypatch.setattr(rc.ps, "search_pubmed",
                        lambda *a, **k: _Res({"safety": [_Ab("111")]}))
    monkeypatch.setattr(rc.ps, "SEARCH_PATTERNS_BY_CATEGORY",
                        {d: "{gene} {disease}" for d in rc.DIMENSIONS}, raising=False)
    monkeypatch.setattr(rc, "synthesize_structured",
                        lambda *a, **k: {"risk_level": "HIGH", "justification": "j",
                                         "interpretation": "i", "cited_pmids": ["111"],
                                         "contradicts_deterministic": False})
    d = rc.run("GENE", "safety-indication", None, "2015", "2026", per_cat=1)["dimensions"]["safety"]
    assert d["risk_level"] == "HIGH" and "risk_level_pre_containment" not in d


def test_six_dimensions_and_overlap_anchors():
    assert set(rc.DIMENSIONS) == {"biological", "druggability", "translational",
                                  "clinical", "safety", "commercial"}
    # overlap dimensions anchor to a deterministic sub_verdict; orthogonal ones do not
    anchor = {d: rc.DIMENSIONS[d][2] for d in rc.DIMENSIONS}
    assert anchor["biological"] == "dependency"
    assert anchor["safety"] == "safety"
    assert anchor["clinical"] is None and anchor["commercial"] is None


def test_tool_schema_null_state_and_required():
    props = rc.TOOL_SCHEMA["properties"]
    assert "not_assessed" in props["risk_level"]["enum"]   # null != MEDIUM
    # two reads per axis: a risk grade AND an interpretation (context) — the general primitive
    assert set(rc.TOOL_SCHEMA["required"]) >= {"risk_level", "interpretation", "cited_pmids", "contradicts_deterministic"}
