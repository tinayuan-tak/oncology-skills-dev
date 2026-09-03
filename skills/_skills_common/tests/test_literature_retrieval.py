"""Tests for the Europe PMC grounding + PMID verification helpers (network monkeypatched — no live calls).

Pins:
  * the retrieval corpus is well-formed (PMID + citation + truncated abstract) and degrades to None;
  * verify_citations reconciles citation.verified against GROUND TRUTH (a hallucinated PMID flips to
    false; a real one to true) and records a _verification summary — and stays honest ('unavailable')
    when the check itself cannot run;
  * synthesize_literature runs the verify_fn over the synthesized result.
"""
from __future__ import annotations

from _skills_common import literature_retrieval as lr
from _skills_common import literature_synthesis as lit
from _skills_common.narrator_lenses import TUMOR_PRESENCE as LENS


def test_indication_phrase_maps_and_falls_back():
    assert lr._indication_phrase("COADREAD") == "colorectal cancer"
    assert lr._indication_phrase("ZZZ") == "ZZZ cancer"
    assert lr._indication_phrase(None) == "cancer"


def test_retrieve_formats_corpus(monkeypatch):
    canned = {"resultList": {"result": [
        {"pmid": "16404366", "authorString": "Went P, Vasei M", "pubYear": "2006",
         "journalTitle": "Br J Cancer", "title": "Frequent high EpCAM expression",
         "abstractText": "EpCAM is expressed in 97.7% of colon cancers. " * 30},
        {"id": "PPR123", "title": "no pmid, skipped"},
    ]}}
    monkeypatch.setattr(lr, "_search", lambda *a, **k: canned)
    corpus = lr.europe_pmc_retrieve("EPCAM", "COADREAD", LENS)
    assert "colorectal cancer" in corpus
    assert "[PMID:16404366] Went P 2006, Br J Cancer" in corpus
    assert corpus.rstrip().endswith("…")             # long abstract truncated
    assert "no pmid, skipped" not in corpus          # a hit without a pmid is dropped


def test_retrieve_degrades_to_none(monkeypatch):
    monkeypatch.setattr(lr, "_search", lambda *a, **k: None)     # network/API failure
    assert lr.europe_pmc_retrieve("EPCAM", "COADREAD", LENS) is None
    monkeypatch.setattr(lr, "_search", lambda *a, **k: {"resultList": {"result": []}})
    assert lr.europe_pmc_retrieve("EPCAM", "COADREAD", LENS) is None
    assert lr.europe_pmc_retrieve(None, "COADREAD", LENS) is None


def _result_with_cites():
    return {"axes": [{"axis_key": "A", "literature_read": "supports", "assertion": "x",
                      "agreement_vs_omics": "agree", "confidence": "high",
                      "citations": [{"label": "real", "pmid": "16404366", "verified": False},
                                    {"label": "hallucinated", "pmid": "99999999", "verified": True},
                                    {"label": "no id", "verified": True}]}],
            "blind_spots": [{"signal": "s", "why_omics_blind": "w",
                             "citations": [{"label": "real2", "pmid": "17548814", "verified": False}]}],
            "overall_consistency": "concordant", "key_divergence": "none"}


def test_verify_flips_against_ground_truth(monkeypatch):
    exists = {"16404366": True, "99999999": False, "17548814": True}
    monkeypatch.setattr(lr, "_pmid_exists", lambda pmid, timeout: exists[pmid])
    out = lr.verify_citations(_result_with_cites())
    cites = out["axes"][0]["citations"]
    assert cites[0]["verified"] is True          # real PMID confirmed
    assert cites[1]["verified"] is False         # hallucinated PMID flipped to false
    assert cites[2]["verified"] is False         # no identifier → not verifiable
    assert out["blind_spots"][0]["citations"][0]["verified"] is True
    v = out["_verification"]
    assert v["status"] == "checked" and v["source"] == "europe_pmc"
    # 3 PMIDs checked; 2 exist (verified); 3 flipped (real F→T, hallucinated T→F, blind-spot real F→T).
    assert v["n_pmid_checked"] == 3 and v["n_verified"] == 2 and v["n_flipped"] == 3


def test_verify_unavailable_when_check_cannot_run(monkeypatch):
    monkeypatch.setattr(lr, "_pmid_exists", lambda pmid, timeout: None)   # e.g. no network
    out = lr.verify_citations(_result_with_cites())
    assert out["_verification"]["status"] == "unavailable"
    # the model's flag is LEFT for pmid citations when the check couldn't run, but a no-id citation is false
    assert out["axes"][0]["citations"][1]["verified"] is True            # left as-reported
    assert out["axes"][0]["citations"][2]["verified"] is False           # no id → false regardless


def test_synthesize_runs_verify_fn(monkeypatch):
    monkeypatch.setattr("_skills_common.llm.synthesize_structured", lambda **k: _result_with_cites())
    monkeypatch.setattr(lr, "_pmid_exists", lambda pmid, timeout: pmid != "99999999")
    fn = lit.make_literature_fn(LENS, retrieve_fn=None, verify_fn=lr.verify_citations)
    out = fn({"target": "EPCAM", "indication": "COADREAD", "headline": {"claim_vector": {}}})
    assert out["_verification"]["status"] == "checked"
    assert out["axes"][0]["citations"][1]["verified"] is False           # hallucinated flipped by verify_fn
