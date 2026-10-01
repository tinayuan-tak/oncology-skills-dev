"""retrieval_lanes: pure-core + wiring tests (no network) for the shared 3-lane retriever extracted in
PR-2. Guards the vocab consolidation (resolve_disease_terms over the 40-code crosswalk), the three new
6-dim risk-agent axis terms, and the high-level retrieve_axis_abstracts seam.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import retrieval_lanes as rl  # noqa: E402


def test_resolve_disease_terms_crosswalk_and_passthrough():
    # a known OncoTree/TCGA code expands via the shared _INDICATION_PHRASE (Stack A)
    assert rl.resolve_disease_terms("COADREAD") == "colorectal cancer"
    assert rl.resolve_disease_terms("ov") == "ovarian cancer"  # case-insensitive code lookup
    # free-text indication passes through unchanged (not a code)
    assert rl.resolve_disease_terms("ovarian cancer") == "ovarian cancer"
    assert rl.resolve_disease_terms("") == ""


def test_six_risk_dims_have_axis_terms():
    # the 6-dim risk agent retrieves through the shared lanes → every dim needs an AXIS_PUBMED_TERMS entry
    for dim in ("biological", "druggability", "translational", "clinical", "safety", "commercial"):
        assert dim in rl.AXIS_PUBMED_TERMS, dim
    # target-level dims are NOT disease-scoped; indication-conditioned dims are
    assert rl.AXIS_PUBMED_TERMS["druggability"][1] is False
    assert rl.AXIS_PUBMED_TERMS["safety"][1] is False
    assert rl.AXIS_PUBMED_TERMS["biological"][1] is True
    assert rl.AXIS_PUBMED_TERMS["translational"][1] is True


def test_axis_query_new_dims():
    # disease-scoped dim: gene ∧ disease ∧ axis-terms
    q = rl._axis_query("KRAS", "colorectal cancer", "biological")
    assert q.startswith("(KRAS) AND (colorectal cancer) AND (")
    # target-level dim (druggability): no disease clause
    qd = rl._axis_query("KRAS", "colorectal cancer", "druggability")
    assert qd.startswith("(KRAS) AND (") and "colorectal cancer" not in qd


def test_retrieve_axis_abstracts_threads_axis_and_efetches(monkeypatch):
    import pubmed_search as ps

    seen = {}

    def fake_retrieve(target, disease_terms, axis, *, per_cat, mindate, maxdate, indication="", status=None):
        seen.update(dict(target=target, axis=axis, disease_terms=disease_terms, indication=indication))
        return ["111", "222"]

    def fake_efetch(pmids, *, category, timeout_s):
        return [
            ps.PubMedAbstract(pmid=p, title="t", abstract="a", journal="j", year=2021, category=category) for p in pmids
        ]

    monkeypatch.setattr(rl, "_retrieve_pmids", fake_retrieve)
    monkeypatch.setattr(ps, "_efetch_abstracts", fake_efetch)
    out = rl.retrieve_axis_abstracts("KRAS", "COADREAD", "safety", per_cat=5, mindate="2015", maxdate="2026")
    assert [a.pmid for a in out] == ["111", "222"]
    assert all(a.category == "safety" for a in out)
    # disease vocab resolved via the crosswalk before retrieval; axis threaded through
    assert seen == {"target": "KRAS", "axis": "safety", "disease_terms": "colorectal cancer", "indication": "COADREAD"}


def test_retrieve_axis_abstracts_empty_pmids_no_efetch(monkeypatch):
    import pubmed_search as ps

    monkeypatch.setattr(rl, "_retrieve_pmids", lambda *a, **k: [])
    monkeypatch.setattr(ps, "_efetch_abstracts", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no efetch")))
    assert rl.retrieve_axis_abstracts("KRAS", "COADREAD", "safety") == []


# ===================== per-lane outage signal (#2391) =====================
def test_ot_floor_pmids_marks_ok_on_success_even_when_empty(monkeypatch):
    import onc_methods.opentargets_literature_floor.read as reader  # noqa: F401

    monkeypatch.setattr(reader, "read_literature_floor", lambda *a, **k: {"pmids": []})
    status = {}
    out = rl._ot_floor_pmids("KRAS", "COADREAD", 5, status=status)
    assert out == []
    assert status["ot_floor"] == "ok"  # a clean empty result is NOT an error


def test_ot_floor_pmids_marks_error_on_exception(monkeypatch):
    import onc_methods.opentargets_literature_floor.read as reader

    def _boom(*a, **k):
        raise RuntimeError("floor unavailable")

    monkeypatch.setattr(reader, "read_literature_floor", _boom)
    status = {}
    out = rl._ot_floor_pmids("KRAS", "COADREAD", 5, status=status)
    assert out == []
    assert status["ot_floor"] == "error"


def test_europepmc_pmids_marks_ok_and_error(monkeypatch):
    import _skills_common.literature_retrieval as litret

    monkeypatch.setattr(litret, "_search", lambda *a, **k: {"resultList": {"result": []}})
    status = {}
    assert rl._europepmc_pmids("q", retmax=5, status=status) == []
    assert status["europepmc"] == "ok"

    def _boom(*a, **k):
        raise RuntimeError("EPMC outage")

    monkeypatch.setattr(litret, "_search", _boom)
    status2 = {}
    assert rl._europepmc_pmids("q", retmax=5, status=status2) == []
    assert status2["europepmc"] == "error"


def test_mark_lane_does_not_downgrade_ok_to_error():
    # the entity lane calls pubtator_pmids TWICE (tight + broad angle); one success anywhere in the
    # lane must win over a later/earlier failure, not get silently clobbered back to "error".
    status = {}
    rl._mark_lane(status, "pubtator", ok=True)
    rl._mark_lane(status, "pubtator", ok=False)
    assert status["pubtator"] == "ok"
    status2 = {}
    rl._mark_lane(status2, "pubtator", ok=False)
    rl._mark_lane(status2, "pubtator", ok=True)
    assert status2["pubtator"] == "ok"


def test_mark_lane_tolerates_no_status_dict():
    # status=None is the default at every call site that doesn't care — must be a silent no-op
    assert rl._mark_lane(None, "pubtator", ok=True) is None


def test_retrieve_axis_returns_lanes_dict(monkeypatch):
    import pubmed_search as ps

    def fake_retrieve(target, disease_terms, axis, *, per_cat, mindate, maxdate, indication="", status=None):
        if status is not None:
            status["pubtator"] = "ok"
            status["ot_floor"] = "error"
            status["europepmc"] = "ok"
        return ["111"]

    monkeypatch.setattr(rl, "_retrieve_pmids", fake_retrieve)
    monkeypatch.setattr(
        ps,
        "_efetch_abstracts",
        lambda pmids, *, category, timeout_s: [
            ps.PubMedAbstract(pmid=p, title="t", abstract="a", journal="j", year=2021, category=category) for p in pmids
        ],
    )
    out = rl.retrieve_axis("KRAS", "COADREAD", "safety", per_cat=5)
    assert out["lanes"] == {"pubtator": "ok", "ot_floor": "error", "europepmc": "ok"}


def test_ground_axis_reexports_are_identical():
    # back-compat: ground_axis re-exports the moved names as the SAME objects (callers/tests unaffected)
    import ground_axis as ga

    assert ga._axis_query is rl._axis_query
    assert ga._retrieve_pmids is rl._retrieve_pmids
    assert ga.AXIS_PUBMED_TERMS is rl.AXIS_PUBMED_TERMS
    assert ga.MAX_RETRIEVED == rl.MAX_RETRIEVED
