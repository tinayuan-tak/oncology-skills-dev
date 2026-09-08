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
    canned = {
        "resultList": {
            "result": [
                {
                    "pmid": "16404366",
                    "authorString": "Went P, Vasei M",
                    "pubYear": "2006",
                    "journalTitle": "Br J Cancer",
                    "title": "Frequent high EpCAM expression",
                    "abstractText": "EpCAM is expressed in 97.7% of colon cancers. " * 30,
                },
                {"id": "PPR123", "title": "no pmid, skipped"},
            ]
        }
    }
    monkeypatch.setattr(lr, "_search", lambda *a, **k: canned)
    corpus = lr.europe_pmc_retrieve("EPCAM", "COADREAD", LENS)
    assert "colorectal cancer" in corpus
    assert "[PMID:16404366] Went P 2006, Br J Cancer" in corpus
    assert corpus.rstrip().endswith("…")  # long abstract truncated
    assert "no pmid, skipped" not in corpus  # a hit without a pmid is dropped


def test_retrieve_degrades_to_none(monkeypatch):
    monkeypatch.setattr(lr, "_search", lambda *a, **k: None)  # network/API failure
    assert lr.europe_pmc_retrieve("EPCAM", "COADREAD", LENS) is None
    monkeypatch.setattr(lr, "_search", lambda *a, **k: {"resultList": {"result": []}})
    assert lr.europe_pmc_retrieve("EPCAM", "COADREAD", LENS) is None
    assert lr.europe_pmc_retrieve(None, "COADREAD", LENS) is None


def _result_with_cites():
    return {
        "axes": [
            {
                "axis_key": "A",
                "literature_read": "supports",
                "assertion": "x",
                "agreement_vs_omics": "agree",
                "confidence": "high",
                "citations": [
                    {"label": "real", "pmid": "16404366", "verified": False},
                    {"label": "hallucinated", "pmid": "99999999", "verified": True},
                    {"label": "no id", "verified": True},
                ],
            }
        ],
        "blind_spots": [
            {
                "signal": "s",
                "why_omics_blind": "w",
                "citations": [{"label": "real2", "pmid": "17548814", "verified": False}],
            }
        ],
        "overall_consistency": "concordant",
        "key_divergence": "none",
    }


def test_verify_flips_against_ground_truth(monkeypatch):
    exists = {"16404366": True, "99999999": False, "17548814": True}
    monkeypatch.setattr(lr, "_pmid_exists", lambda pmid, timeout: exists[pmid])
    out = lr.verify_citations(_result_with_cites())
    cites = out["axes"][0]["citations"]
    assert cites[0]["verified"] is True  # real PMID confirmed
    assert cites[1]["verified"] is False  # hallucinated PMID flipped to false
    assert cites[2]["verified"] is False  # no identifier → not verifiable
    assert out["blind_spots"][0]["citations"][0]["verified"] is True
    v = out["_verification"]
    assert v["status"] == "checked" and v["source"] == "europe_pmc"
    # 3 PMIDs checked; 2 exist (verified); 3 flipped (real F→T, hallucinated T→F, blind-spot real F→T).
    assert v["n_pmid_checked"] == 3 and v["n_verified"] == 2 and v["n_flipped"] == 3


def test_verify_unavailable_when_check_cannot_run(monkeypatch):
    monkeypatch.setattr(lr, "_pmid_exists", lambda pmid, timeout: None)  # e.g. no network
    out = lr.verify_citations(_result_with_cites())
    assert out["_verification"]["status"] == "unavailable"
    # the model's flag is LEFT for pmid citations when the check couldn't run, but a no-id citation is false
    assert out["axes"][0]["citations"][1]["verified"] is True  # left as-reported
    assert out["axes"][0]["citations"][2]["verified"] is False  # no id → false regardless


def test_synthesize_runs_verify_fn(monkeypatch):
    monkeypatch.setattr("_skills_common.llm.synthesize_structured", lambda **k: _result_with_cites())
    monkeypatch.setattr(lr, "_pmid_exists", lambda pmid, timeout: pmid != "99999999")
    fn = lit.make_literature_fn(LENS, retrieve_fn=None, verify_fn=lr.verify_citations)
    out = fn({"target": "EPCAM", "indication": "COADREAD", "headline": {"claim_vector": {}}})
    assert out["_verification"]["status"] == "checked"
    assert out["axes"][0]["citations"][1]["verified"] is False  # hallucinated flipped by verify_fn


# ── per-subskill query SPECIFICITY + VARIATIONS ─────────────────────────────────────────────────────
def test_query_variations_are_lens_specific():
    from _skills_common.narrator_lenses import TUMOR_PRESENCE, TUMOR_SELECTIVITY

    vs_sel = lr._build_query_variations("EPCAM", "COADREAD", TUMOR_SELECTIVITY)
    # a broad recall query + a lens-specific precision query
    assert vs_sel[0] == '("EPCAM") AND ("colorectal cancer")'
    assert len(vs_sel) == 2 and "therapeutic window" in vs_sel[1]
    # a DIFFERENT subskill produces a DIFFERENT specific query (specificity per lens)
    vs_pres = lr._build_query_variations("EPCAM", "COADREAD", TUMOR_PRESENCE)
    assert vs_pres[1] != vs_sel[1]
    # no lens → just the broad query (byte-compatible with the pre-lens behavior)
    assert lr._build_query_variations("EPCAM", "COADREAD", None) == ['("EPCAM") AND ("colorectal cancer")']


# ── PubTator3 retriever ─────────────────────────────────────────────────────────────────────────────
_PUBTATOR_CANNED = {
    "results": [
        {
            "pmid": "41357552",
            "title": "Construction of EpCAM overexpression vectors",
            "journal": "Front Genome Ed",
            "authors": ["Wang B", "Li Q"],
            "date": "2025-11-20T00:00:00Z",
            "doi": "10.x/y",
            "text_hl": "@@@EpCAM@@@ is overexpressed in @DISEASE_Colorectal_Neoplasms @DISEASE_MESH:D015179 @@@colorectal cancer@@@ cells",
        },
        {"title": "no pmid, dropped"},
    ]
}


def test_pubtator3_retrieve_parses_and_cleans_markup(monkeypatch):
    monkeypatch.setattr(lr, "_http_get_json", lambda *a, **k: _PUBTATOR_CANNED)
    corpus = lr.pubtator3_retrieve("EPCAM", "COADREAD", LENS)
    assert "NCBI PubTator3" in corpus
    assert "[PMID:41357552] Wang B 2025, Front Genome Ed" in corpus
    # text_hl bioconcept markup stripped to clean prose (spans unwrapped, @TYPE_ tokens dropped)
    assert "EpCAM is overexpressed in colorectal cancer cells" in corpus
    assert "@@@" not in corpus and "@DISEASE" not in corpus and "no pmid, dropped" not in corpus


def test_default_retrieve_falls_back_to_pubtator(monkeypatch):
    monkeypatch.setattr(lr, "_search", lambda *a, **k: None)  # Europe PMC unavailable
    monkeypatch.setattr(lr, "_http_get_json", lambda *a, **k: _PUBTATOR_CANNED)  # PubTator up
    corpus = lr.default_retrieve("EPCAM", "COADREAD", LENS)
    assert corpus is not None and "NCBI PubTator3" in corpus  # fell back, did not return None


def test_default_retrieve_prefers_europe_pmc(monkeypatch):
    canned = {
        "resultList": {
            "result": [
                {
                    "pmid": "16404366",
                    "authorString": "Went P",
                    "pubYear": "2006",
                    "journalTitle": "Br J Cancer",
                    "title": "t",
                    "abstractText": "a",
                }
            ]
        }
    }
    monkeypatch.setattr(lr, "_search", lambda *a, **k: canned)
    monkeypatch.setattr(lr, "_http_get_json", lambda *a, **k: _PUBTATOR_CANNED)
    corpus = lr.default_retrieve("EPCAM", "COADREAD", LENS)
    assert "Europe PMC" in corpus and "NCBI PubTator3" not in corpus  # primary wins when it returns hits


# ── verification NCBI fallback ──────────────────────────────────────────────────────────────────────
def test_pmid_exists_falls_back_to_ncbi(monkeypatch):
    monkeypatch.setattr(lr, "_pmid_exists_epmc", lambda pmid, timeout: None)  # EPMC check can't run
    monkeypatch.setattr(lr, "_pmid_exists_ncbi", lambda pmid, timeout: True)  # NCBI confirms
    assert lr._pmid_exists("16404366", 8.0) is True
    # a DEFINITIVE Europe PMC answer short-circuits (no NCBI call needed)
    monkeypatch.setattr(lr, "_pmid_exists_epmc", lambda pmid, timeout: False)
    monkeypatch.setattr(
        lr, "_pmid_exists_ncbi", lambda pmid, timeout: (_ for _ in ()).throw(AssertionError("should not call"))
    )
    assert lr._pmid_exists("99999999", 8.0) is False
