"""entity_search: pure-core tests (no network) for the entity-normalized retrieval lane.

Guards the collision fix: gene-symbol retrieval must resolve to the GENE entity, not a
same-string synonym or a non-PubMed identifier.
"""
from __future__ import annotations
from pathlib import Path

from _test_support import load_module

_MOD = Path(__file__).resolve().parent.parent / "scripts" / "entity_search.py"

es = load_module(_MOD, "entity_search")

# real shape of a PubTator /entity/autocomplete?concept=gene response for the ME3 collision case
_ME3_AUTOCOMPLETE = [
    {"_id": "@GENE_ME3", "name": "ME3", "db_id": "10873", "match": "Matched on name ME3"},
    {"_id": "@GENE_ME31B", "name": "me31B", "db_id": "34364", "match": "Matched on name me31B"},
    {"_id": "@GENE_LOC542233", "name": "LOC542233", "db_id": "542233", "match": "synonyms me3"},
    {"_id": "@GENE_PCDHGA5", "name": "PCDHGA5", "db_id": "56110", "match": "synonyms ME3"},
]


def test_pick_gene_entity_matches_symbol_name_not_synonym():
    # must pick the exact-NAME match (ME3 -> entrez 10873), NOT the synonym false-matches
    # (LOC542233 / PCDHGA5) that are exactly the collision the entity lane exists to avoid
    assert es._pick_gene_entity(_ME3_AUTOCOMPLETE, "ME3") == "@GENE_10873"
    assert es._pick_gene_entity(_ME3_AUTOCOMPLETE, "me3") == "@GENE_10873"  # case-insensitive


def test_pick_gene_entity_none_when_no_exact_name():
    assert es._pick_gene_entity(_ME3_AUTOCOMPLETE, "NOTAGENE") is None
    assert es._pick_gene_entity([], "ME3") is None


def test_numeric_pmids_drops_non_pubmed_ids_and_caps():
    # entity_lut/PubTator can surface Europe-PMC preprint ids (PPR*/IND*) that don't NCBI-efetch
    hits = [{"pmid": "36590518"}, {"pmid": "PPR265863"}, {"_id": "IND608568956"},
            {"pmid": "36813040"}, {"pmid": "37095735"}]
    assert es._numeric_pmids(hits, 10) == ["36590518", "36813040", "37095735"]
    assert es._numeric_pmids(hits, 1) == ["36590518"]              # limit respected


def test_entity_axis_query_scoping_and_broaden():
    ez = "@GENE_10873"
    # disease-scoped, tight: entity + disease + axis terms
    q = es.entity_axis_query(ez, "pancreatic cancer", "toxicity OR normal tissue",
                             disease_scoped=True, broad=False)
    assert q == "@GENE_10873 AND (pancreatic cancer) AND (toxicity OR normal tissue)"
    # broad drops the axis-term conjunction (soft-fallback)
    qb = es.entity_axis_query(ez, "pancreatic cancer", "toxicity OR normal tissue",
                              disease_scoped=True, broad=True)
    assert qb == "@GENE_10873 AND (pancreatic cancer)"
    # target-level axis (not disease-scoped): no disease clause
    qt = es.entity_axis_query(ez, "pancreatic cancer", "toxicity",
                              disease_scoped=False, broad=False)
    assert qt == "@GENE_10873 AND (toxicity)"
    # fallback symbol clause works the same when entity resolution missed
    qs = es.entity_axis_query("(ME3)", "", "toxicity", disease_scoped=False, broad=False)
    assert qs == "(ME3) AND (toxicity)"
