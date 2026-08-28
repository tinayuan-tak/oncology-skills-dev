"""cited_evidence: verdict-inert gene×indication cited-literature card — pure-assembler tests.

Invariants:
  - VERDICT-INERT: the card always carries verdict=None / verdict_inert=True and no verdict/gate keys.
  - BEST-EFFORT SHAPE: either lane (europepmc / pubtator) may be None or non-'ok'; the card never
    raises and records the absence in notes, still emitting the other lane.
  - TRIM: europepmc top_cited is capped to top_cited.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "scripts" / "cited_evidence.py"


def _load():
    spec = importlib.util.spec_from_file_location("cited_evidence", _MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _epmc(status="ok", n=3):
    return {"status": status, "source": "opentargets-europepmc-evidence-per-target-v1",
            "europepmc_scope": "indication", "total_papers": 42, "n_papers_recent": 9,
            "earliest_year": 2005, "latest_year": 2026, "n_diseases": 2,
            "top_papers": [{"pmid": str(i), "cooccur": 100 - i, "section": "abstract",
                            "sentence": f"s{i}"} for i in range(n)]}


def _rel(status="ok"):
    return {"status": status, "source": "pubtator3-gene-disease-relations-per-gene-v1",
            "relation_scope": "indication", "mesh_id_source": "crosswalk_mesh_ids",
            "total_publications": 55,
            "relations": [{"relation_type": "associate", "n_publications": 50, "pmids": ["1"]},
                          {"relation_type": "stimulate", "n_publications": 5, "pmids": ["2"]}]}


def test_both_lanes_present_verdict_inert():
    ce = _load()
    card = ce.build_cited_evidence_card("KRAS", "COADREAD", _epmc(), _rel())
    assert card["verdict"] is None and card["verdict_inert"] is True
    assert "verdict_key" not in card and "gate" not in card
    assert card["status"] == "ok"
    assert card["literature_evidence"]["total_papers"] == 42
    assert card["literature_evidence"]["indication_scope"] == "indication"
    assert card["relation_direction"]["relations"][0]["relation_type"] == "associate"
    assert card["relation_direction"]["mesh_id_source"] == "crosswalk_mesh_ids"
    assert set(card["sources"]) == {"europepmc_evidence", "pubtator_relations"}


def test_top_cited_trim():
    ce = _load()
    card = ce.build_cited_evidence_card("KRAS", "COADREAD", _epmc(n=20), None, top_cited=5)
    assert len(card["literature_evidence"]["top_cited"]) == 5


def test_pubtator_absent_lane_is_none_with_note():
    ce = _load()
    card = ce.build_cited_evidence_card("KRAS", "COADREAD", _epmc(), None)
    assert card["relation_direction"] is None
    assert card["literature_evidence"] is not None       # other lane still emitted
    assert any("pubtator" in n for n in card["notes"])
    assert card["status"] == "ok"                          # one lane present -> ok


def test_non_ok_status_treated_as_absent():
    ce = _load()
    card = ce.build_cited_evidence_card("X", "Y", _epmc(status="no_evidence"), _rel(status="insufficient"))
    assert card["literature_evidence"] is None and card["relation_direction"] is None
    assert card["status"] == "no_evidence"
    assert card["verdict"] is None


def test_both_none_never_raises():
    ce = _load()
    card = ce.build_cited_evidence_card("X", "Y", None, None)
    assert card["status"] == "no_evidence" and card["verdict"] is None
    assert len(card["notes"]) == 2
