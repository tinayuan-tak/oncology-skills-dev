"""Hermetic tests for opentargets_europepmc_evidence — pure aggregator (no S3)."""
from __future__ import annotations
import sys
from pathlib import Path

AM = Path(__file__).resolve().parents[3]
if str(AM) not in sys.path:
    sys.path.insert(0, str(AM))

from methods.opentargets_europepmc_evidence.read import (  # noqa: E402
    aggregate_evidence, _canonical_indication,
)


def _paper(pmid, cooccur, year=2023, section="abstract", sentence="s", pmc=None):
    return {"pmid": pmid, "pmc": pmc, "year": year, "cooccur": cooccur,
            "section": section, "sentence": sentence}


def _row(disease, n_papers, papers, *, cooccur_sum=None, first=2000, latest=2024, recent=0):
    return {"ensembl_gene_id": "ENSG_TEST", "disease_id": disease, "n_papers": n_papers,
            "cooccur_sum": cooccur_sum if cooccur_sum is not None else float(n_papers),
            "first_year": first, "latest_year": latest, "n_papers_recent": recent,
            "top_papers": papers}


# one gene with three disease rows
_ROWS = [
    _row("EFO_HIT", 10, [_paper("111", 50.0), _paper("222", 30.0)], first=2005, latest=2024, recent=6),
    _row("EFO_HIT_2", 4, [_paper("333", 40.0), _paper("111", 20.0)], first=2010, latest=2023, recent=3),
    _row("EFO_OTHER", 7, [_paper("999", 99.0)], first=2001, latest=2022, recent=1),
]


def test_alias_normalization():
    assert _canonical_indication("luad") == "NSCLC"
    assert _canonical_indication("MESO") == "MESO"   # unaliased passes through


def test_target_level_when_no_efo_lane():
    agg = aggregate_evidence(_ROWS, efo_ids=[], top_n=10)
    assert agg["indication_scope"] == "target_level"
    assert agg["europepmc_scope"] == "target_level"
    assert agg["n_diseases"] == 3
    assert agg["total_papers"] == 21          # 10+4+7 (per-disease distinct counts summed)
    assert agg["earliest_year"] == 2001 and agg["latest_year"] == 2024
    # pmid 111 appears in two diseases -> deduped, keeping the higher-cooccur (50.0) mention
    p111 = [p for p in agg["top_papers"] if p["pmid"] == "111"]
    assert len(p111) == 1 and p111[0]["cooccur"] == 50.0
    # ordered by cooccur desc: 999(99) > 111(50) > 333(40) > 222(30)
    assert [p["pmid"] for p in agg["top_papers"]] == ["999", "111", "333", "222"]


def test_scoped_to_indication_drops_off_family_diseases():
    agg = aggregate_evidence(_ROWS, efo_ids=["EFO_HIT", "EFO_HIT_2"], top_n=10)
    assert agg["indication_scope"] == "indication"
    assert agg["europepmc_scope"] == "indication"
    assert set(agg["disease_ids"]) == {"EFO_HIT", "EFO_HIT_2"}
    assert agg["total_papers"] == 14          # EFO_OTHER (7) excluded
    assert "999" not in [p["pmid"] for p in agg["top_papers"]]   # off-family paper gone
    assert agg["n_papers_recent"] == 9        # 6+3


def test_over_filter_fallback_when_no_disease_matches():
    # indication has an efo lane but none of the gene's disease rows match -> target-level fallback
    agg = aggregate_evidence(_ROWS, efo_ids=["EFO_NONE"], top_n=10)
    assert agg["indication_scope"] == "indication"
    assert agg["europepmc_scope"] == "target_level_fallback"
    assert agg["total_papers"] == 21          # all rows kept rather than emptying the lane


def test_top_n_caps_merged_papers_by_cooccur():
    agg = aggregate_evidence(_ROWS, efo_ids=[], top_n=2)
    assert [p["pmid"] for p in agg["top_papers"]] == ["999", "111"]   # top-2 by cooccur


def test_empty_rows_yields_empty_evidence():
    agg = aggregate_evidence([], efo_ids=[], top_n=10)
    assert agg["total_papers"] == 0 and agg["top_papers"] == [] and agg["n_diseases"] == 0
