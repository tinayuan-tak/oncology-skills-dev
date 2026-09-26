"""literature-risk-assessment: guard + shape tests (no network / no Bedrock).

The load-bearing invariant is the CONTAINMENT GUARD: an LLM must never emit a PMID from memory;
only PMIDs present in the retrieved corpus may be cited. These tests pin that guard + the
6-dimension shape + the overlap-anchor mapping, all without a live call.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

rc = load_run_py(Path(__file__).resolve().parent.parent, "lra_run")


def test_containment_drops_pmids_not_in_corpus():
    retrieved = {"111", "222"}
    good, bad = rc._contain(["111", "999"], retrieved)  # 999 never retrieved → confabulated
    assert good == ["111"]
    assert bad == ["999"]


def test_containment_all_grounded_is_clean():
    good, bad = rc._contain(["111", "222"], {"111", "222", "333"})
    assert bad == []  # retrieval-grounded → zero confabulation
    assert set(good) == {"111", "222"}


def test_containment_handles_none_and_ints():
    good, bad = rc._contain(None, {"1"})
    assert good == [] and bad == []
    good, bad = rc._contain([111, "222"], {"111"})  # int coerced to str
    assert good == ["111"] and bad == ["222"]


def test_containment_normalizes_misformatted_pmid():
    # a real-but-misformatted citation ('PMID 111', 'PMID: 222') must NOT be dropped as confabulated
    good, bad = rc._contain(["PMID 111", "PMID: 222", "PMID 999"], {"111", "222"})
    assert set(good) == {"111", "222"}
    assert bad == ["999"]


def test_norm_pmid_versioned_suffix_stripped():
    # a versioned PubMed id ('12345678.1') normalizes to its bare PMID
    assert rc._norm_pmid("12345678.1") == "12345678"


def test_norm_pmid_pmc_accession_not_collapsed_to_bogus_pmid():
    # a PMC accession's digit-run is the PMC accession number, NOT the article's PMID; it must
    # not be collapsed to bogus digits (which would wrong-drop the real citation or wrong-admit a
    # coincidental PMID collision). Case-insensitive; the stripped token is returned unchanged.
    assert rc._norm_pmid("PMC3539614") == "PMC3539614"
    assert rc._norm_pmid("pmc3539614") == "pmc3539614"
    # containment: a cited PMC accession never falsely matches a retrieved PMID that shares digits
    good, bad = rc._contain(["PMC3539614"], {"3539614"})
    assert good == [] and bad == ["PMC3539614"]


def test_fit_abstract_keeps_tail_and_stays_in_budget():
    # #1635a: a structured abstract whose escalating CONCLUSIONS sentence lives past ABSTRACT_CHARS must
    # remain in-window — the truncation×containment seam (a real, retrieved PMID whose SHOWN text no
    # longer supports the grade). Head+tail fitting keeps both the framing and the tail.
    body = (
        "BACKGROUND: "
        + ("filler background text. " * 90)
        + "RESULTS: "
        + ("filler results text. " * 40)
        + "CONCLUSIONS: unexpected on-target hepatotoxicity was reported in the phase II cohort."
    )
    assert len(body) > rc.ABSTRACT_CHARS
    fitted = rc._fit_abstract(body, rc.ABSTRACT_CHARS)
    assert len(fitted) <= rc.ABSTRACT_CHARS
    assert "unexpected on-target hepatotoxicity" in fitted  # tail conclusion survives
    assert fitted.startswith("BACKGROUND:") and rc._ABSTRACT_TRUNC_MARKER in fitted
    assert rc._fit_abstract("short", rc.ABSTRACT_CHARS) == "short"  # within budget → verbatim
    assert rc._fit_abstract(None, rc.ABSTRACT_CHARS) == ""  # tolerates a missing abstract


def test_build_prompt_fences_abstracts_with_random_sentinel():
    # #1635b: each interpolated (external) abstract is wrapped in a per-run random delimiter the SYSTEM
    # prompt (rule 7) names as the untrusted-data boundary.
    from types import SimpleNamespace

    abs_ = [SimpleNamespace(pmid="111", year=2020, title="T", abstract="body")]
    p = rc._build_prompt("safety", "q", abs_, None, sentinel="cafef00d")
    assert "BEGIN-UNTRUSTED-cafef00d" in p and "END-UNTRUSTED-cafef00d" in p
    assert "PMID 111" in p
    # SYSTEM rule 7 names the fence convention; the fence is randomized when not supplied
    assert "BEGIN-UNTRUSTED-" in rc.SYSTEM
    p1 = rc._build_prompt("safety", "q", abs_, None)
    p2 = rc._build_prompt("safety", "q", abs_, None)
    assert "cafef00d" not in p1 and p1 != p2  # fresh random token per run


class _Ab:
    def __init__(self, pmid):
        self.pmid, self.year, self.title, self.abstract = pmid, 2020, "t", "body"


def _only_safety(target, indication, axis, **k):
    """Frozen retrieval seam (rc.rl.retrieve_axis): one kept abstract for the safety dim, none dropped."""
    return {"kept": [_Ab("111")] if axis == "safety" else [], "dropped": []}


def test_run_downgrades_grade_with_only_confabulated_citations(monkeypatch):
    # A HIGH grade whose only cited PMID was confabulated (not retrieved) must be downgraded to
    # not_assessed rather than shipping an ungrounded risk level (P0.2 grounding-integrity).
    monkeypatch.setattr(rc.rl, "retrieve_axis", _only_safety)
    monkeypatch.setattr(
        rc,
        "synthesize_structured",
        lambda *a, **k: {
            "risk_level": "HIGH",
            "justification": "j",
            "interpretation": "i",
            "cited_pmids": ["999"],
            "contradicts_deterministic": False,
        },
    )
    res = rc.run("GENE", "safety-indication", None, "2015", "2026", per_cat=1)
    d = res["dimensions"]["safety"]
    assert d["risk_level"] == "not_assessed"
    assert d["risk_level_pre_containment"] == "HIGH"
    assert d["confabulated_dropped"] == ["999"] and d["cited_pmids"] == []


def test_run_keeps_grade_with_surviving_citation(monkeypatch):
    monkeypatch.setattr(rc.rl, "retrieve_axis", _only_safety)
    monkeypatch.setattr(
        rc,
        "synthesize_structured",
        lambda *a, **k: {
            "risk_level": "HIGH",
            "justification": "j",
            "interpretation": "i",
            "cited_pmids": ["111"],
            "contradicts_deterministic": False,
        },
    )
    d = rc.run("GENE", "safety-indication", None, "2015", "2026", per_cat=1)["dimensions"]["safety"]
    assert d["risk_level"] == "HIGH" and "risk_level_pre_containment" not in d


def test_run_resets_discordance_when_no_surviving_citation(monkeypatch):
    # (#1614 facet c) contradicts_deterministic may only stand on ≥1 SURVIVING cited PMID. When the only
    # cite was confabulated (grade downgraded to not_assessed), the discordance flag rested on
    # confabulated support and must be reset. BEFORE the fix it was copied from the LLM (True).
    monkeypatch.setattr(rc.rl, "retrieve_axis", _only_safety)
    monkeypatch.setattr(
        rc,
        "synthesize_structured",
        lambda *a, **k: {
            "risk_level": "HIGH",
            "justification": "j",
            "interpretation": "i",
            "cited_pmids": ["999"],
            "contradicts_deterministic": True,
        },
    )
    d = rc.run("GENE", "safety-indication", None, "2015", "2026", per_cat=1)["dimensions"]["safety"]
    assert d["risk_level"] == "not_assessed"
    assert d["contradicts_deterministic"] is False  # discordance reset — no surviving citation


def test_run_flags_partial_confabulation_and_residual_prose(monkeypatch):
    # (#1614 facets a/b) a grade backed by one real + one confabulated cite is KEPT (a surviving cite
    # still grounds it — this is NOT a downgrade), but the entry is annotated `partial_confabulation`,
    # and when the justification still literally names the dropped PMID's digits,
    # `prose_references_dropped_pmid`. The surviving-cite discordance flag still stands.
    monkeypatch.setattr(rc.rl, "retrieve_axis", _only_safety)
    monkeypatch.setattr(
        rc,
        "synthesize_structured",
        lambda *a, **k: {
            "risk_level": "HIGH",
            "justification": "A phase III trial (PMID 99999999) showed 40% hepatotox",
            "interpretation": "i",
            "cited_pmids": ["111", "99999999"],
            "contradicts_deterministic": True,
        },
    )
    d = rc.run("GENE", "safety-indication", None, "2015", "2026", per_cat=1)["dimensions"]["safety"]
    assert d["risk_level"] == "HIGH"  # a surviving cite grounds the grade — NOT downgraded
    assert d["cited_pmids"] == ["111"] and d["confabulated_dropped"] == ["99999999"]
    assert d["partial_confabulation"] is True
    assert d["prose_references_dropped_pmid"] is True  # prose still names the dropped id
    assert d["contradicts_deterministic"] is True  # ≥1 surviving cite → discordance stands


def test_six_dimensions_and_overlap_anchors():
    assert set(rc.DIMENSIONS) == {"biological", "druggability", "translational", "clinical", "safety", "commercial"}
    # overlap dimensions anchor to a deterministic sub_verdict; orthogonal ones do not
    anchor = {d: rc.DIMENSIONS[d][2] for d in rc.DIMENSIONS}
    assert anchor["biological"] == "dependency"
    assert anchor["safety"] == "safety"
    assert anchor["clinical"] is None and anchor["commercial"] is None


def test_tool_schema_null_state_and_required():
    props = rc.TOOL_SCHEMA["properties"]
    assert "not_assessed" in props["risk_level"]["enum"]  # null != MEDIUM
    # two reads per axis: a risk grade AND an interpretation (context) — the general primitive
    assert set(rc.TOOL_SCHEMA["required"]) >= {
        "risk_level",
        "interpretation",
        "cited_pmids",
        "contradicts_deterministic",
    }


# (test_gene_search_term_disambiguates + test_search_pubmed_queries_are_gene_qualified removed 2026-09-10:
#  the retired ps.search_pubmed/gene_search_term single-lane keyword path was superseded by
#  retrieval_lanes' entity-normalized retrieval — gene-symbol disambiguation is now covered by
#  entity_search's @GENE_<entrez> resolution + its tests, not this free-text-qualification path.)
