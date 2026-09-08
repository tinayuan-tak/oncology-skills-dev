"""Hermetic tests for opentargets_literature_floor — pure aggregator (no S3)."""

from __future__ import annotations

import sys
from pathlib import Path

AM = Path(__file__).resolve().parents[3]
if str(AM) not in sys.path:
    sys.path.insert(0, str(AM))

from methods.opentargets_literature_floor.read import (  # noqa: E402
    _axis_match,
    _axis_tokens,
    _canonical_indication,
    aggregate_literature,
)


def _row(source, pmid, rank, score, disease=None, sentence=None, year=2020):
    return {
        "source": source,
        "pmid": pmid,
        "rank_in_source": rank,
        "score": score,
        "disease_id": disease,
        "sentence": sentence,
        "year": year,
    }


# gene with europepmc (disease-scoped) + entity_lut (target-level) rows
_ROWS = [
    _row("europepmc", "111", 1, 4.0, disease="EFO_HIT", sentence="tumor-specific expression"),
    _row("europepmc", "222", 2, 3.0, disease="EFO_OTHER", sentence="off-indication"),
    _row("europepmc", "333", 3, 2.0, disease="EFO_HIT", sentence="normal-tissue liability"),
    _row("entity_lut", "444", 1, 1.5),
    _row("entity_lut", "111", 2, 1.4),  # overlaps europepmc 111 -> dedup in union
]


def test_target_level_when_no_efo_lane():
    # no efo_ids -> europepmc NOT disease-scoped; both lanes present, union deduped
    agg = aggregate_literature(_ROWS, efo_ids=[], top_n=10)
    assert agg["indication_scope"] == "target_level"
    assert set(agg["sources_present"]) == {"europepmc", "entity_lut"}
    assert agg["pmids"] == ["111", "222", "333", "444"]  # 111 deduped, per-source rank order
    assert agg["n_pmids"] == 4
    # europepmc records carry the text-mined sentence hint
    epmc = {r["pmid"]: r for r in agg["by_source"]["europepmc"]}
    assert epmc["111"]["sentence"] == "tumor-specific expression"


def test_europepmc_scoped_to_indication_when_efo_present():
    # efo_ids scopes ONLY the europepmc lane (entity_lut is target-level by construction)
    agg = aggregate_literature(_ROWS, efo_ids=["EFO_HIT"], top_n=10)
    assert agg["indication_scope"] == "indication"
    epmc_pmids = [r["pmid"] for r in agg["by_source"]["europepmc"]]
    assert epmc_pmids == ["111", "333"]  # 222 (EFO_OTHER) dropped
    assert "444" in agg["pmids"]  # entity_lut unaffected by scoping


def test_top_n_caps_per_source_by_rank():
    agg = aggregate_literature(_ROWS, efo_ids=[], top_n=1)
    assert [r["pmid"] for r in agg["by_source"]["europepmc"]] == ["111"]  # rank 1 only
    assert [r["pmid"] for r in agg["by_source"]["entity_lut"]] == ["444"]  # rank 1 only


def test_empty_rows_yields_empty_floor():
    agg = aggregate_literature([], efo_ids=[], top_n=10)
    assert agg["n_pmids"] == 0 and agg["pmids"] == [] and agg["by_source"] == {}


def test_europepmc_scope_field_reports_indication_when_scoped():
    agg = aggregate_literature(_ROWS, efo_ids=["EFO_HIT"], top_n=10)
    assert agg["europepmc_scope"] == "indication"


def test_over_filter_fallback_keeps_target_level_europepmc():
    # gene HAS europepmc rows, but NONE match the indication efo_ids -> scoping would empty the lane;
    # fallback keeps target-level europepmc (flagged) instead of losing the reproducible signal.
    rows = [
        _row("europepmc", "111", 1, 4.0, disease="EFO_A", sentence="s1"),
        _row("europepmc", "222", 2, 3.0, disease="EFO_B", sentence="s2"),
        _row("entity_lut", "444", 1, 1.5),
    ]
    agg = aggregate_literature(rows, efo_ids=["EFO_NOMATCH"], top_n=10)
    assert agg["indication_scope"] == "indication"  # efo_ids WERE supplied
    assert agg["europepmc_scope"] == "target_level_fallback"  # but none matched -> fallback
    assert [r["pmid"] for r in agg["by_source"]["europepmc"]] == ["111", "222"]
    assert "444" in agg["pmids"]  # entity_lut unaffected


def test_over_filter_no_fallback_when_gene_has_no_europepmc():
    # no europepmc rows at all -> not a fallback case; just entity_lut, scope stays 'indication'
    rows = [_row("entity_lut", "444", 1, 1.5)]
    agg = aggregate_literature(rows, efo_ids=["EFO_X"], top_n=10)
    assert agg["europepmc_scope"] == "indication"
    assert "europepmc" not in agg["by_source"]


def test_axis_tokens_and_match():
    toks = _axis_tokens("toxicity OR adverse event OR normal tissue")
    assert toks == ["toxicity", "adverse event", "normal tissue"]
    assert _axis_tokens(None) == [] and _axis_tokens("") == []
    assert _axis_match("reported normal tissue toxicity in liver", toks) == 2  # 'toxicity' + 'normal tissue'
    assert _axis_match("unrelated proliferation finding", toks) == 0
    assert _axis_match(None, toks) == 0  # entity_lut row w/o sentence


def test_axis_rerank_floats_axis_relevant_papers_before_topn():
    # association order would keep rank-1 first; axis re-rank floats the sentence-matching paper up
    rows = [
        _row("europepmc", "111", 1, 9.0, disease="D", sentence="high expression, no safety signal"),
        _row("europepmc", "222", 2, 8.0, disease="D", sentence="on-target normal tissue toxicity in kidney"),
        _row("europepmc", "333", 3, 7.0, disease="D", sentence="unrelated"),
    ]
    # no axis_terms -> association order (rank_in_source): 111,222,333
    plain = aggregate_literature(rows, efo_ids=[], top_n=2)
    assert [r["pmid"] for r in plain["by_source"]["europepmc"]] == ["111", "222"]
    assert plain["axis_reranked"] is False
    # safety axis_terms -> 222 (matches 'normal tissue'+'toxicity') floats to #1, survives top_n=2
    axed = aggregate_literature(rows, efo_ids=[], top_n=2, axis_terms="toxicity OR normal tissue OR adverse event")
    assert axed["axis_reranked"] is True
    assert axed["by_source"]["europepmc"][0]["pmid"] == "222"
    assert axed["by_source"]["europepmc"][0]["axis_match"] >= 2


def test_axis_rerank_noop_when_no_sentences():
    # entity_lut rows have no sentence -> axis_match 0 -> association order preserved
    rows = [_row("entity_lut", "444", 1, 1.5), _row("entity_lut", "555", 2, 1.4)]
    axed = aggregate_literature(rows, efo_ids=[], top_n=10, axis_terms="toxicity OR normal tissue")
    assert [r["pmid"] for r in axed["by_source"]["entity_lut"]] == ["444", "555"]


def test_indication_alias_normalizes_subtype_codes():
    # finer OncoTree/panel codes normalize to the crosswalk canonical_code
    assert _canonical_indication("LUAD") == "NSCLC"
    assert _canonical_indication("luad") == "NSCLC"  # case-insensitive
    assert _canonical_indication("DLBCL") == "DLBC"
    assert _canonical_indication("LAML") == "AML"
    # codes with no alias pass through unchanged (target-level if no crosswalk entry)
    assert _canonical_indication("PAAD") == "PAAD"
    assert _canonical_indication("MESO") == "MESO"
