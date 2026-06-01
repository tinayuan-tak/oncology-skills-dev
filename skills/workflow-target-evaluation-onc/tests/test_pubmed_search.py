"""Tests for the PubMed E-utilities wrapper.

Mocks HTTP at the urllib level so tests run offline. Real-API
verification is done via a separate gated e2e test.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.pubmed_search import (  # noqa: E402
    DISEASE_TERMS, SEARCH_PATTERNS_BY_CATEGORY,
    PubMedAbstract, _parse_efetch_text, search_pubmed,
)


# ---------------------------------------------------------------------------
# Constants are well-formed
# ---------------------------------------------------------------------------

def test_six_categories_match_workflow() -> None:
    assert set(SEARCH_PATTERNS_BY_CATEGORY) == {
        'biological', 'druggability', 'translational',
        'clinical', 'safety', 'commercial',
    }


def test_disease_terms_cover_canonical_diseases() -> None:
    assert set(DISEASE_TERMS) == {'crc', 'nsclc'}


# ---------------------------------------------------------------------------
# Parser unit tests on captured efetch responses
# ---------------------------------------------------------------------------

PCDH7_NATURE_BRAIN_MET_RECORD = textwrap.dedent("""\
    1. Nature. 2016 May 26;533(7604):493-498. doi: 10.1038/nature18268. Epub 2016 May
     18.

    Carcinoma-astrocyte gap junctions promote brain metastasis by cGAMP transfer.

    Chen Q(#)(1), Boire A(#)(1)(2), Jin X(1).

    Author information:
    (1)Cancer Biology and Genetics Program, Memorial Sloan Kettering Cancer Center,
    New York, NY 10065, USA.
    (2)Department of Neurology, Memorial Sloan Kettering Cancer Center, New York, NY
    10065, USA.

    Brain metastasis represents a substantial source of morbidity and mortality in
    various cancers, and is characterized by high resistance to chemotherapy. Here
    we define the role of the most abundant cell type in the brain, the astrocyte,
    in promoting brain metastasis.

    DOI: 10.1038/nature18268
    PMID: 27225120
""")


def test_parser_extracts_title_journal_year_pmid() -> None:
    abstracts = _parse_efetch_text(
        PCDH7_NATURE_BRAIN_MET_RECORD, category='biological',
    )
    assert len(abstracts) == 1
    a = abstracts[0]
    assert a.pmid == '27225120'
    assert a.journal == 'Nature'
    assert a.year == 2016
    assert 'gap junctions' in a.title
    assert 'brain metastasis' in a.title.lower()


def test_parser_extracts_abstract_body_not_metadata() -> None:
    abstracts = _parse_efetch_text(
        PCDH7_NATURE_BRAIN_MET_RECORD, category='biological',
    )
    a = abstracts[0]
    # Body should be the prose, not author info or DOI line.
    assert 'Brain metastasis represents' in a.abstract
    assert 'Author information' not in a.abstract
    assert 'DOI:' not in a.abstract
    assert 'PMID:' not in a.abstract


def test_parser_carries_category_field() -> None:
    abstracts = _parse_efetch_text(
        PCDH7_NATURE_BRAIN_MET_RECORD, category='safety',
    )
    assert abstracts[0].category == 'safety'


def test_parser_handles_empty_input() -> None:
    assert _parse_efetch_text('', category='biological') == []


def test_parser_skips_records_missing_pmid() -> None:
    """Some efetch responses include header noise without a PMID line.
    Records lacking PMID: should be silently dropped."""
    no_pmid = textwrap.dedent("""\
        1. Some Journal. 2024 Jan 1;1(1):1-10.

        Some title.

        Some body without PMID line.
    """)
    assert _parse_efetch_text(no_pmid, category='biological') == []


def test_parser_handles_multiple_records() -> None:
    two_records = (
        PCDH7_NATURE_BRAIN_MET_RECORD + '\n\n' +
        PCDH7_NATURE_BRAIN_MET_RECORD.replace('27225120', '12345678')
                                       .replace('Nature. 2016', 'Cell. 2018')
    )
    abstracts = _parse_efetch_text(two_records, category='clinical')
    assert len(abstracts) == 2
    assert {a.pmid for a in abstracts} == {'27225120', '12345678'}


# ---------------------------------------------------------------------------
# search_pubmed input validation
# ---------------------------------------------------------------------------

def test_unknown_disease_rejected() -> None:
    with pytest.raises(ValueError, match='disease must be one of'):
        search_pubmed('PCDH7', 'breast', abstracts_per_category=1)


# ---------------------------------------------------------------------------
# search_pubmed orchestration with mocked HTTP
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode('utf-8')

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> '_MockResponse':
        return self

    def __exit__(self, *args) -> None:
        pass


def _mock_urlopen_factory(esearch_pmids: list[str], efetch_text: str):
    """Return a urlopen mock that returns esearch JSON for esearch URLs
    and the captured efetch text for efetch URLs."""
    import json as _json

    def _mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        if 'esearch.fcgi' in url:
            return _MockResponse(_json.dumps({
                'esearchresult': {'idlist': esearch_pmids}
            }))
        if 'efetch.fcgi' in url:
            return _MockResponse(efetch_text)
        raise AssertionError(f'unexpected URL: {url}')

    return _mock_urlopen


def test_search_pubmed_orchestrates_six_categories() -> None:
    """Mocked: every category returns the same fixture; verify all 6
    categories appear in the result."""
    mock_urlopen = _mock_urlopen_factory(
        esearch_pmids=['27225120'],
        efetch_text=PCDH7_NATURE_BRAIN_MET_RECORD,
    )
    with patch('integrated_report.pubmed_search.urllib.request.urlopen',
               side_effect=mock_urlopen):
        with patch('integrated_report.pubmed_search.time.sleep'):  # speed up
            result = search_pubmed(
                'PCDH7', 'nsclc', abstracts_per_category=1,
            )
    assert result.gene == 'PCDH7'
    assert result.disease == 'nsclc'
    assert set(result.abstracts_by_category) == {
        'biological', 'druggability', 'translational',
        'clinical', 'safety', 'commercial',
    }
    # Every category should have 1 abstract (same mock returns 1 PMID).
    for cat, abs_list in result.abstracts_by_category.items():
        assert len(abs_list) == 1, f'{cat}: expected 1 abstract'
        assert abs_list[0].category == cat


def test_search_pubmed_handles_empty_categories() -> None:
    """A category with no PubMed hits returns an empty list, not
    KeyError or crash."""
    import json as _json

    def empty_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        if 'esearch.fcgi' in url:
            return _MockResponse(_json.dumps({
                'esearchresult': {'idlist': []}
            }))
        raise AssertionError('efetch should not be called when esearch is empty')

    with patch('integrated_report.pubmed_search.urllib.request.urlopen',
               side_effect=empty_urlopen):
        with patch('integrated_report.pubmed_search.time.sleep'):
            result = search_pubmed(
                'NONESUCH', 'nsclc', abstracts_per_category=1,
            )
    for abs_list in result.abstracts_by_category.values():
        assert abs_list == []
    assert result.all_pmids == set()


def test_search_pubmed_dedupes_pmids_via_property() -> None:
    """The all_pmids property collapses across categories — same paper
    appearing in multiple search categories should count once."""
    mock_urlopen = _mock_urlopen_factory(
        esearch_pmids=['27225120'],
        efetch_text=PCDH7_NATURE_BRAIN_MET_RECORD,
    )
    with patch('integrated_report.pubmed_search.urllib.request.urlopen',
               side_effect=mock_urlopen):
        with patch('integrated_report.pubmed_search.time.sleep'):
            result = search_pubmed(
                'PCDH7', 'nsclc', abstracts_per_category=1,
            )
    # 6 categories all returned the same single PMID; all_pmids == {1}.
    assert result.all_pmids == {'27225120'}
