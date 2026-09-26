"""openFDA pharmacovigilance (PR-7): pure-parser + aggregation + run.py wiring tests (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

from _test_support import load_run_py

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import openfda  # noqa: E402

rc = load_run_py(Path(__file__).resolve().parent.parent, "lra_run_fda")


# ── pure parsers / query construction ────────────────────────────────────────────────────────────
def test_drug_search_clause_event_vs_label():
    ev = openfda._drug_search_clause("mirvetuximab soravtansine")
    assert 'patient.drug.openfda.generic_name:"mirvetuximab soravtansine"' in ev
    assert "patient.drug.openfda.substance_name" in ev and "brand_name" not in ev
    lab = openfda._drug_search_clause("trastuzumab", label=True)
    assert 'openfda.generic_name:"trastuzumab"' in lab and "brand_name" in lab
    assert openfda._drug_search_clause("") == ""


def test_parse_faers_counts_and_limit():
    data = {
        "results": [
            {"term": "VISION BLURRED", "count": 114},
            {"term": "DIARRHOEA", "count": 101},
            {"term": "X", "count": 3},
        ]
    }
    out = openfda._parse_faers_counts(data, limit=2)
    assert out == [{"term": "VISION BLURRED", "count": 114}, {"term": "DIARRHOEA", "count": 101}]
    assert openfda._parse_faers_counts({}, limit=5) == []


def test_parse_label_boxed():
    assert (
        openfda._parse_label_boxed({"results": [{"boxed_warning": ["WARNING: OCULAR TOXICITY ..."]}]})[
            "has_boxed_warning"
        ]
        is True
    )
    assert openfda._parse_label_boxed({"results": [{}]}) is None  # label present, no boxed warning
    assert openfda._parse_label_boxed({"results": []}) is None
    assert openfda._parse_label_boxed(None) is None


def test_get_json_404_is_empty_not_error(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 404, "NOT_FOUND", {}, None)

    monkeypatch.setattr(openfda.urllib.request, "urlopen", boom)
    assert openfda._get_json("http://x", timeout_s=1) is None  # 404 → valid empty, no retry storm


# ── aggregation ──────────────────────────────────────────────────────────────────────────────────
def test_pharmacovigilance_aggregates_and_sorts(monkeypatch):
    monkeypatch.setattr(
        openfda,
        "faers_top_reactions",
        lambda drug, **k: (
            [{"term": "VISION BLURRED", "count": 114}] if drug == "mirvetuximab" else [{"term": "RASH", "count": 5}]
        ),
    )
    monkeypatch.setattr(
        openfda,
        "label_boxed_warning",
        lambda drug, **k: {"boxed_warning": "OCULAR TOX"} if drug == "mirvetuximab" else None,
    )
    out = openfda.pharmacovigilance(
        ["mirvetuximab", "MIRVETUXIMAB", "otherdrug"],  # dedup case-insensitive
        drug_provenance={"mirvetuximab": "clinical-precedent.approved_agents"},
        indication="ovarian cancer",
    )
    assert out["drugs_queried"] == ["mirvetuximab", "otherdrug"]
    assert out["source"] == "openfda" and out["escalate_only"] is True and out["as_of"]
    # #1617 attribution: the resolved drug carries its card_id.field; the un-provenanced one carries None
    assert out["top_reactions"][0] == {
        "term": "VISION BLURRED",
        "count": 114,
        "drug": "mirvetuximab",
        "attributed_via": "clinical-precedent.approved_agents",
    }  # sorted desc
    assert out["boxed_warning_drugs"] == [
        {"drug": "mirvetuximab", "boxed_warning": "OCULAR TOX", "attributed_via": "clinical-precedent.approved_agents"}
    ]
    assert out["drug_attribution"] == {
        "mirvetuximab": "clinical-precedent.approved_agents",
        "otherdrug": None,
    }
    # #1617 indication-scope disclosure: FAERS counts are NOT filtered to the target indication
    assert out["indication_scope"]["requested_indication"] == "ovarian cancer"
    assert out["indication_scope"]["faers_filtered_to_indication"] is False
    # #1617 deterministic query surface (pinnable) — one per queried drug
    assert [q["drug"] for q in out["queries"]] == ["mirvetuximab", "otherdrug"]
    assert out["queries"][0]["event_endpoint"] == openfda._EVENT_URL
    assert 'patient.drug.openfda.generic_name:"mirvetuximab"' in out["queries"][0]["event_search"]


def test_pharmacovigilance_none_when_no_signal(monkeypatch):
    monkeypatch.setattr(openfda, "faers_top_reactions", lambda *a, **k: [])
    monkeypatch.setattr(openfda, "label_boxed_warning", lambda *a, **k: None)
    assert openfda.pharmacovigilance(["drugx"]) is None
    assert openfda.pharmacovigilance([]) is None  # no drugs → nothing to escalate


# ── run.py wiring ────────────────────────────────────────────────────────────────────────────────
def test_drugs_from_package(tmp_path):
    import json

    pkg = tmp_path / "ep.json"
    pkg.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "card_id": "clinical-precedent",
                        "summary": {
                            "approved_agents": ["mirvetuximab soravtansine"],
                            "notable_failures": ["farletuzumab"],
                        },
                    },
                    {"card_id": "competitor-landscape", "summary": {"approved_agents": ["MIRVETUXIMAB SORAVTANSINE"]}},
                ]
            }
        )
    )
    drugs, provenance = rc._drugs_from_package(str(pkg))
    assert drugs == ["mirvetuximab soravtansine", "farletuzumab"]  # deduped case-insensitive, order preserved
    # #1617 attribution honesty: each drug carries the FIRST card_id.field that named it
    assert provenance == {
        "mirvetuximab soravtansine": "clinical-precedent.approved_agents",
        "farletuzumab": "clinical-precedent.notable_failures",
    }
    assert rc._drugs_from_package(None) == ([], {})


def test_run_attaches_pharmacovigilance_to_safety(monkeypatch, tmp_path):
    import json

    pkg = tmp_path / "ep.json"
    pkg.write_text(
        json.dumps(
            {
                "synthesis": {"sub_verdicts": {}},
                "cards": [
                    {"card_id": "clinical-precedent", "summary": {"approved_agents": ["mirvetuximab"]}},
                ],
            }
        )
    )

    class _Ab:
        def __init__(self, pmid):
            self.pmid, self.year, self.title, self.abstract = pmid, 2024, "t", "b"

    monkeypatch.setattr(
        rc.rl,
        "retrieve_axis",
        lambda t, i, axis, **k: {"kept": [_Ab("1")] if axis in ("safety", "biological") else [], "dropped": []},
    )
    monkeypatch.setattr(
        rc,
        "synthesize_structured",
        lambda *a, **k: {
            "risk_level": "MEDIUM",
            "justification": "j",
            "interpretation": "i",
            "cited_pmids": ["1"],
            "contradicts_deterministic": False,
        },
    )
    monkeypatch.setattr(
        rc.openfda,
        "pharmacovigilance",
        lambda drugs, **k: (
            {
                "source": "openfda",
                "top_reactions": [{"term": "VISION BLURRED", "count": 114, "drug": "mirvetuximab"}],
                "drugs_queried": drugs,
            }
            if drugs
            else None
        ),
    )

    res = rc.run("FOLR1", "ovarian cancer", str(pkg), "2015", "2026", per_cat=1)
    pv = res["dimensions"]["safety"].get("pharmacovigilance")
    assert pv and pv["top_reactions"][0]["term"] == "VISION BLURRED"
    assert "pharmacovigilance" not in res["dimensions"]["biological"]  # safety-dim only


def test_corpus_pin_records_openfda_side_channel(monkeypatch, tmp_path):
    """#1617: when a PV signal exists, corpus_pin discloses the openFDA side-channel (as_of, drugs,
    attribution, deterministic queries, indication scope). No package/signal → openfda pin is None."""
    import json

    class _Ab:
        def __init__(self, pmid):
            self.pmid, self.year, self.title, self.abstract = pmid, 2024, "t", "b"

    monkeypatch.setattr(
        rc.rl, "retrieve_axis", lambda t, i, axis, **k: {"kept": [_Ab("1")] if axis == "safety" else [], "dropped": []}
    )
    monkeypatch.setattr(
        rc,
        "synthesize_structured",
        lambda *a, **k: {
            "risk_level": "MEDIUM",
            "justification": "j",
            "interpretation": "i",
            "cited_pmids": ["1"],
            "contradicts_deterministic": False,
        },
    )

    # No evidence-package → no drug hop → no openFDA pin.
    res_none = rc.run("FOLR1", "ovarian cancer", None, "2015", "2026", per_cat=1)
    assert res_none["provenance"]["corpus_pin"]["openfda"] is None

    pkg = tmp_path / "ep.json"
    pkg.write_text(
        json.dumps(
            {
                "synthesis": {"sub_verdicts": {}},
                "cards": [{"card_id": "clinical-precedent", "summary": {"approved_agents": ["mirvetuximab"]}}],
            }
        )
    )
    monkeypatch.setattr(rc.openfda, "faers_top_reactions", lambda drug, **k: [{"term": "RASH", "count": 7}])
    monkeypatch.setattr(rc.openfda, "label_boxed_warning", lambda *a, **k: None)

    res = rc.run("FOLR1", "ovarian cancer", str(pkg), "2015", "2026", per_cat=1)
    pin = res["provenance"]["corpus_pin"]["openfda"]
    assert pin["source"] == "openfda" and pin["escalate_only"] is True and pin["as_of"]
    assert pin["drugs_queried"] == ["mirvetuximab"]
    assert pin["drug_attribution"] == {"mirvetuximab": "clinical-precedent.approved_agents"}
    assert pin["indication_scope"]["faers_filtered_to_indication"] is False
    assert pin["queries"][0]["drug"] == "mirvetuximab"  # deterministic query surface recorded in-pin
