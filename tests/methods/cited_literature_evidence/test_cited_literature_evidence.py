"""Hermetic tests for cited_literature_evidence — verdict-inert composing reader (no S3).

Two contracts:
  - build_cited_evidence_card: the NESTED card (verbatim contract inherited from the former
    skills-side sibling — VERDICT-INERT, best-effort per-lane, top_cited trim, English preference).
  - read_cited_literature_evidence: the FLATTENED card entrypoint (top-level summary_fields the
    target-contracts card declares + retained nested detail).
"""

from __future__ import annotations

import sys
from pathlib import Path

AM = Path(__file__).resolve().parents[3]
if str(AM) not in sys.path:
    sys.path.insert(0, str(AM))

from methods.cited_literature_evidence.read import (  # noqa: E402
    _flatten_for_card,
    build_cited_evidence_card,
    read_cited_literature_evidence,
)


def _epmc(status="ok", n=3):
    return {
        "status": status,
        "source": "opentargets-europepmc-evidence-per-target-v1",
        "europepmc_scope": "indication",
        "total_papers": 42,
        "n_papers_recent": 9,
        "earliest_year": 2005,
        "latest_year": 2026,
        "n_diseases": 2,
        "top_papers": [
            {"pmid": str(i), "cooccur": 100 - i, "section": "abstract", "sentence": f"s{i}"} for i in range(n)
        ],
    }


def _rel(status="ok"):
    return {
        "status": status,
        "source": "pubtator3-gene-disease-relations-per-gene-v1",
        "relation_scope": "indication",
        "mesh_id_source": "crosswalk_mesh_ids",
        "total_publications": 55,
        "relations": [
            {"relation_type": "associate", "n_publications": 50, "pmids": ["1"]},
            {"relation_type": "stimulate", "n_publications": 5, "pmids": ["2"]},
        ],
    }


# --- NESTED card contract (inherited verbatim) -----------------------------------------------------


def test_both_lanes_present_verdict_inert():
    card = build_cited_evidence_card("KRAS", "COADREAD", _epmc(), _rel())
    assert card["verdict"] is None and card["verdict_inert"] is True
    assert "verdict_key" not in card and "gate" not in card
    assert card["status"] == "ok"
    assert card["literature_evidence"]["paper_disease_mentions"] == 42  # summed mentions, relabeled
    assert card["literature_evidence"]["indication_scope"] == "indication"
    assert card["relation_direction"]["relations"][0]["relation_type"] == "associate"
    assert card["relation_direction"]["mesh_id_source"] == "crosswalk_mesh_ids"
    assert set(card["sources"]) == {"europepmc_evidence", "pubtator_relations"}


def test_top_cited_trim():
    card = build_cited_evidence_card("KRAS", "COADREAD", _epmc(n=20), None, top_cited=5)
    assert len(card["literature_evidence"]["top_cited"]) == 5


def test_pubtator_absent_lane_is_none_with_note():
    card = build_cited_evidence_card("KRAS", "COADREAD", _epmc(), None)
    assert card["relation_direction"] is None
    assert card["literature_evidence"] is not None  # other lane still emitted
    assert any("pubtator" in n for n in card["notes"])
    assert card["status"] == "ok"  # one lane present -> ok


def test_english_preferred_in_top_cited():
    e = _epmc(n=0)
    e["top_papers"] = [
        {"pmid": "1", "cooccur": 99, "sentence": "分子靶向治疗 c-MET NSCLC"},
        {"pmid": "2", "cooccur": 50, "sentence": "MET amplification drives resistance in lung cancer"},
        {"pmid": "3", "cooccur": 10, "sentence": "c-MET exon 14 skipping is oncogenic"},
    ]
    card = build_cited_evidence_card("MET", "LUAD", e, None, top_cited=2)
    tops = card["literature_evidence"]["top_cited"]
    assert [t["pmid"] for t in tops] == ["2", "3"]  # English surfaces first


def test_bad_symbol_is_insufficient_not_no_evidence():
    card = build_cited_evidence_card("ZZZ", "BRCA", {"status": "insufficient"}, {"status": "insufficient"})
    assert card["status"] == "insufficient"
    assert card["literature_evidence"] is None and card["relation_direction"] is None


def test_genuine_absence_is_no_evidence():
    card = build_cited_evidence_card("X", "Y", _epmc(status="no_evidence"), _rel(status="no_relations"))
    assert card["status"] == "no_evidence"
    assert card["verdict"] is None


def test_both_none_never_raises():
    card = build_cited_evidence_card("X", "Y", None, None)
    assert card["status"] == "no_evidence" and card["verdict"] is None
    assert len(card["notes"]) == 2


# --- #783: infra-unavailable must NOT collapse into no_evidence clean-zero -------------------------
# A lane the composing reader could not run surfaces as an explicit data_unavailable sentinel dict
# (see _compose_nested / _unavailable_arm). The builder must promote that to a card-level
# data_unavailable status, DISTINCT from a genuine measured no_evidence, so a consumer keyed on
# cited_evidence_status can tell "a lane never ran" from "we looked, nothing there".
def _unavail(note="reader unavailable: ClientError"):
    return {"status": "data_unavailable", "_note": note}


def test_infra_unavailable_arm_is_data_unavailable_not_no_evidence():
    # one lane unavailable (infra), the other a genuine measured zero -> overall data_unavailable
    card = build_cited_evidence_card("KRAS", "COADREAD", _unavail(), _rel(status="no_relations"))
    assert card["status"] == "data_unavailable"
    assert card["verdict"] is None and card["verdict_inert"] is True
    assert card["literature_evidence"] is None and card["relation_direction"] is None
    assert any("europepmc" in n for n in card["notes"])


def test_both_lanes_unavailable_is_data_unavailable():
    card = build_cited_evidence_card("X", "Y", _unavail(), _unavail())
    assert card["status"] == "data_unavailable"


def test_data_unavailable_outranks_insufficient():
    # infra beats a non-resolving target: the honest overall state is "we could not fully look"
    card = build_cited_evidence_card("X", "Y", _unavail(), {"status": "insufficient"})
    assert card["status"] == "data_unavailable"


def test_measured_zero_still_no_evidence_when_no_lane_unavailable():
    # regression guard: without an unavailable lane, a genuine measured coverage gap stays no_evidence
    card = build_cited_evidence_card("X", "Y", _epmc(status="no_evidence"), _rel(status="no_relations"))
    assert card["status"] == "no_evidence"


def test_data_unavailable_flattens_to_status_field():
    card = build_cited_evidence_card("X", "Y", _unavail(), _unavail())
    flat = _flatten_for_card(card)
    assert flat["cited_evidence_status"] == "data_unavailable"


# --- #783: the composing seam must NOT swallow a child's re-raised infra fault into no_evidence ----
# The two arm readers practice absence discipline (return a status dict on definitive absence, RE-RAISE
# transient/creds/broken-env). The former blanket `except: arm = None` defeated that by collapsing a
# re-raised infra fault to None -> no_evidence. This guard pins the seam directly (no S3): monkeypatch
# the child reader fns on their own modules (the compose imports them by name at call time).
def test_compose_transient_faults_become_data_unavailable_never_raises(monkeypatch):
    from botocore.exceptions import ClientError

    import methods.opentargets_europepmc_evidence.read as EP
    import methods.pubtator3_gene_disease_relations.read as PT
    from methods.cited_literature_evidence.read import _compose_nested

    def _throttle(*a, **k):
        raise ClientError({"Error": {"Code": "SlowDown", "Message": "throttle"}}, "GetObject")

    monkeypatch.setattr(EP, "read_europepmc_evidence", _throttle)
    monkeypatch.setattr(PT, "read_gene_disease_relations", _throttle)
    card = _compose_nested("KRAS", "COADREAD")  # must NOT raise
    assert card["status"] == "data_unavailable"
    assert card["verdict"] is None
    assert any("unavailable" in n for n in card["notes"])


def test_compose_one_infra_one_clean_zero_is_data_unavailable(monkeypatch):
    from botocore.exceptions import ClientError

    import methods.opentargets_europepmc_evidence.read as EP
    import methods.pubtator3_gene_disease_relations.read as PT
    from methods.cited_literature_evidence.read import _compose_nested

    def _expired(*a, **k):
        raise ClientError({"Error": {"Code": "ExpiredToken", "Message": "creds"}}, "GetObject")

    monkeypatch.setattr(EP, "read_europepmc_evidence", _expired)
    monkeypatch.setattr(PT, "read_gene_disease_relations", lambda *a, **k: _rel(status="no_relations"))
    card = _compose_nested("KRAS", "COADREAD")
    assert card["status"] == "data_unavailable"  # one lane never ran -> not a measured no_evidence


def test_compose_both_clean_zero_still_no_evidence(monkeypatch):
    import methods.opentargets_europepmc_evidence.read as EP
    import methods.pubtator3_gene_disease_relations.read as PT
    from methods.cited_literature_evidence.read import _compose_nested

    monkeypatch.setattr(EP, "read_europepmc_evidence", lambda *a, **k: _epmc(status="no_evidence"))
    monkeypatch.setattr(PT, "read_gene_disease_relations", lambda *a, **k: _rel(status="no_relations"))
    card = _compose_nested("X", "Y")
    assert card["status"] == "no_evidence"


# --- FLATTENED card entrypoint --------------------------------------------------------------------

# every declared summary_field on cards/cited-literature-evidence.card.yaml — the emission guard
# requires each to be an emitted top-level key. Keep in sync with the card.
_DECLARED_SUMMARY_FIELDS = [
    "cited_evidence_status",
    "literature_scope",
    "paper_disease_mentions",
    "recent_mentions",
    "n_diseases",
    "earliest_year",
    "latest_year",
    "top_cited",
    "relation_types",
    "total_relation_publications",
]


def test_flatten_projects_declared_summary_fields():
    card = build_cited_evidence_card("KRAS", "COADREAD", _epmc(), _rel())
    flat = _flatten_for_card(card)
    assert flat["cited_evidence_status"] == "ok"
    assert flat["literature_scope"] == "indication"
    assert flat["paper_disease_mentions"] == 42
    assert flat["recent_mentions"] == 9
    assert flat["n_diseases"] == 2
    assert flat["earliest_year"] == 2005 and flat["latest_year"] == 2026
    assert flat["relation_types"] == ["associate", "stimulate"]
    assert flat["total_relation_publications"] == 55


def test_reader_emits_every_declared_summary_field_top_level(monkeypatch):
    """The card entrypoint must emit every declared summary_field as a TOP-LEVEL key (emission guard),
    stay verdict-inert, and never raise when a lane is unavailable — exercised by monkeypatching the
    two underlying readers so the test is hermetic (no S3)."""
    import methods.cited_literature_evidence.read as R

    monkeypatch.setattr(
        R,
        "_compose_nested",
        lambda t, i, top_cited=8: build_cited_evidence_card(t, i, _epmc(), _rel(), top_cited=top_cited),
    )
    out = read_cited_literature_evidence("KRAS", "COADREAD")
    assert out["verdict"] is None and out["verdict_inert"] is True
    for f in _DECLARED_SUMMARY_FIELDS:
        assert f in out, f"declared summary_field {f!r} not emitted top-level"
    assert out["cited_evidence_status"] == "ok"
    # nested detail retained for the display/LLM layer
    assert out["literature_evidence"]["paper_disease_mentions"] == 42
    assert out["relation_direction"]["relations"][0]["relation_type"] == "associate"


def test_reader_absent_lanes_still_shape_stable(monkeypatch):
    import methods.cited_literature_evidence.read as R

    monkeypatch.setattr(R, "_compose_nested", lambda t, i, top_cited=8: build_cited_evidence_card(t, i, None, None))
    out = read_cited_literature_evidence("X", "Y")
    assert out["cited_evidence_status"] == "no_evidence"
    assert out["top_cited"] == [] and out["relation_types"] == []
    for f in _DECLARED_SUMMARY_FIELDS:
        assert f in out
