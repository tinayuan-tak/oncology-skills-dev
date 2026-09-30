"""Hermetic tests for pubtator3_gene_disease_relations — pure aggregator (no S3)."""

from __future__ import annotations

from onc_methods.pubtator3_gene_disease_relations.read import (
    _canonical_indication,
    aggregate_relations,
)


def _row(disease_mesh, relation_type, n_pub, pmids):
    return {
        "ensembl_gene_id": "ENSG_TEST",
        "disease_mesh": disease_mesh,
        "relation_type": relation_type,
        "n_publications": n_pub,
        "pmids": pmids,
    }


# one gene: two in-family diseases (D015179, D003110) + one off-family (D010190)
_ROWS = [
    _row("MESH:D015179", "associate", 40, ["1", "2", "3"]),
    _row("MESH:D015179", "cause", 5, ["2", "9"]),
    _row("MESH:D003110", "associate", 10, ["3", "4"]),
    _row("MESH:D010190", "associate", 99, ["7"]),  # off-family
]


def test_alias_normalization():
    assert _canonical_indication("lusc") == "NSCLC"
    assert _canonical_indication("PAAD") == "PAAD"


def test_target_level_when_no_mesh():
    agg = aggregate_relations(_ROWS, mesh_ids=[], top_n=20)
    assert agg["indication_scope"] == "target_level"
    assert agg["relation_scope"] == "target_level"
    # associate summed across all diseases: 40+10+99 = 149; cause 5
    rel = {r["relation_type"]: r for r in agg["relations"]}
    assert rel["associate"]["n_publications"] == 149
    assert rel["cause"]["n_publications"] == 5
    assert agg["relations"][0]["relation_type"] == "associate"  # ordered by n_pub desc
    assert agg["total_publications"] == 154


def test_scoped_to_family_sums_only_in_family():
    agg = aggregate_relations(_ROWS, mesh_ids=["MESH:D015179", "MESH:D003110"], top_n=20)
    assert agg["indication_scope"] == "indication"
    assert agg["relation_scope"] == "indication"
    rel = {r["relation_type"]: r for r in agg["relations"]}
    assert rel["associate"]["n_publications"] == 50  # 40+10 (D010190 excluded)
    # merged deduped pmids for associate: 1,2,3 (+3,4) -> 1,2,3,4
    assert rel["associate"]["pmids"] == ["1", "2", "3", "4"]
    assert "MESH:D010190" not in agg["disease_mesh_ids"]


def test_over_filter_fallback():
    agg = aggregate_relations(_ROWS, mesh_ids=["MESH:D999999"], top_n=20)
    assert agg["relation_scope"] == "target_level_fallback"
    assert agg["total_publications"] == 154  # all kept


def test_pmid_cap_per_type():
    agg = aggregate_relations(_ROWS, mesh_ids=[], top_n=2)
    rel = {r["relation_type"]: r for r in agg["relations"]}
    assert rel["associate"]["pmids"] == ["1", "2"]  # capped at 2


def test_empty_rows():
    agg = aggregate_relations([], mesh_ids=[], top_n=20)
    assert agg["relations"] == [] and agg["total_publications"] == 0
