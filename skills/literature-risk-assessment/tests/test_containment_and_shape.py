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
