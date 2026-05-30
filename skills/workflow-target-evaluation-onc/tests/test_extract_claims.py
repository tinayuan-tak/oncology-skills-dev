"""Tests for Stage 1 — per-category claim extraction.

LLM responses are mocked. Real-API verification via the gated e2e
test (commit 7).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.extract_claims import (  # noqa: E402
    EXTRACT_CLAIMS_TOOL, CATEGORY_FOCUS, CategoryExtraction,
    ExtractedClaim, _build_extraction_prompt, _parse_tool_response,
    extract_claims, extract_claims_for_category,
)
from integrated_report.pubmed_search import (  # noqa: E402
    PubMedAbstract, PubMedSearchResult,
)


# ---------------------------------------------------------------------------
# Tool schema sanity
# ---------------------------------------------------------------------------

def test_tool_schema_is_well_formed() -> None:
    """The tool schema needs to be a valid Anthropic tool-use schema."""
    assert EXTRACT_CLAIMS_TOOL['name'] == 'extract_claims'
    schema = EXTRACT_CLAIMS_TOOL['input_schema']
    assert schema['type'] == 'object'
    assert 'claims' in schema['required']
    item_schema = schema['properties']['claims']['items']
    assert set(item_schema['required']) == {'pmid', 'claim', 'study_type'}


def test_category_focus_covers_six_categories() -> None:
    assert set(CATEGORY_FOCUS) == {
        'biological', 'druggability', 'translational',
        'clinical', 'safety', 'commercial',
    }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _make_abstract(pmid: str = '12345678') -> PubMedAbstract:
    return PubMedAbstract(
        pmid=pmid,
        title='Test paper',
        abstract='Body of the abstract.',
        journal='J Test',
        year=2024,
        category='biological',
    )


def test_prompt_includes_gene_disease_category() -> None:
    prompt = _build_extraction_prompt(
        gene='PCDH7', disease='nsclc', category='biological',
        abstracts=[_make_abstract()],
    )
    assert 'PCDH7' in prompt
    assert 'NSCLC' in prompt
    assert 'biological' in prompt.lower()
    # Focus blurb should be present.
    assert 'in vivo' in prompt or 'knockout' in prompt


def test_prompt_includes_each_abstract() -> None:
    abstracts = [
        _make_abstract(pmid='11111111'),
        _make_abstract(pmid='22222222'),
    ]
    prompt = _build_extraction_prompt(
        gene='PCDH7', disease='nsclc', category='biological',
        abstracts=abstracts,
    )
    assert '11111111' in prompt
    assert '22222222' in prompt


# ---------------------------------------------------------------------------
# Tool-response parsing
# ---------------------------------------------------------------------------

def _make_tool_use_response(claims_payload: list[dict]) -> SimpleNamespace:
    """Build a fake Anthropic API response with one tool_use block."""
    block = SimpleNamespace(
        type='tool_use',
        input={'claims': claims_payload},
    )
    return SimpleNamespace(content=[block])


def test_parse_tool_response_happy_path() -> None:
    response = _make_tool_use_response([
        {'pmid': '12345678', 'claim': 'X drives Y', 'study_type': 'in vivo'},
        {'pmid': '87654321', 'claim': 'Z mechanism', 'study_type': 'mechanistic'},
    ])
    result = _parse_tool_response(response, category='biological')
    assert result.category == 'biological'
    assert len(result.claims) == 2
    assert result.claims[0].pmid == '12345678'
    assert result.claims[0].category == 'biological'


def test_parse_tool_response_missing_tool_use_returns_empty() -> None:
    """Defensive: if the model declined to call the tool, return
    empty rather than crashing."""
    response = SimpleNamespace(content=[
        SimpleNamespace(type='text', text='I cannot help'),
    ])
    result = _parse_tool_response(response, category='safety')
    assert result.category == 'safety'
    assert result.claims == []


def test_parse_tool_response_truncates_long_claims() -> None:
    long_claim = 'A' * 300
    response = _make_tool_use_response([
        {'pmid': '12345678', 'claim': long_claim, 'study_type': 'x'},
    ])
    result = _parse_tool_response(response, category='biological')
    assert len(result.claims[0].claim) <= 200
    assert result.claims[0].claim.endswith('...')


def test_parse_tool_response_skips_empty_claims() -> None:
    response = _make_tool_use_response([
        {'pmid': '12345678', 'claim': '', 'study_type': 'x'},   # skipped
        {'pmid': '', 'claim': 'X drives Y', 'study_type': 'x'},  # skipped
        {'pmid': '11111111', 'claim': 'Valid claim', 'study_type': 'x'},
    ])
    result = _parse_tool_response(response, category='biological')
    assert len(result.claims) == 1
    assert result.claims[0].pmid == '11111111'


def test_parse_tool_response_handles_string_input() -> None:
    """SDK sometimes returns tool input as JSON string instead of dict.
    Parser should handle both."""
    import json as _json
    block = SimpleNamespace(
        type='tool_use',
        input=_json.dumps({'claims': [
            {'pmid': '12345678', 'claim': 'X', 'study_type': 'x'},
        ]}),
    )
    response = SimpleNamespace(content=[block])
    result = _parse_tool_response(response, category='biological')
    assert len(result.claims) == 1


# ---------------------------------------------------------------------------
# extract_claims_for_category — empty input is a no-op (no LLM call)
# ---------------------------------------------------------------------------

def test_empty_abstracts_no_llm_call() -> None:
    """If a category has no PubMed hits, skip the LLM call entirely
    (cost + reliability)."""
    fake_client = MagicMock()
    fake_client.messages.create.assert_not_called()  # baseline
    result = extract_claims_for_category(
        gene='PCDH7', disease='nsclc', category='biological',
        abstracts=[],
        client=fake_client,
    )
    assert result.claims == []
    fake_client.messages.create.assert_not_called()


def test_extract_claims_for_category_invokes_client() -> None:
    """When abstracts are present, the client is called once with the
    prompt + tool config."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _make_tool_use_response([
        {'pmid': '12345678', 'claim': 'X', 'study_type': 'in vivo'},
    ])
    result = extract_claims_for_category(
        gene='PCDH7', disease='nsclc', category='biological',
        abstracts=[_make_abstract()],
        client=fake_client,
    )
    fake_client.messages.create.assert_called_once()
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs['tools'][0]['name'] == 'extract_claims'
    assert call_kwargs['tool_choice']['name'] == 'extract_claims'
    assert len(result.claims) == 1


# ---------------------------------------------------------------------------
# extract_claims orchestration
# ---------------------------------------------------------------------------

def test_extract_claims_runs_six_categories() -> None:
    """Orchestrator should hit all 6 categories present in the search result."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _make_tool_use_response([
        {'pmid': '12345678', 'claim': 'X', 'study_type': 'x'},
    ])
    abstracts_by_cat = {
        cat: [_make_abstract()] for cat in [
            'biological', 'druggability', 'translational',
            'clinical', 'safety', 'commercial',
        ]
    }
    result_all = extract_claims(
        PubMedSearchResult(
            gene='PCDH7', disease='nsclc',
            abstracts_by_category=abstracts_by_cat,
        ),
        client=fake_client,
    )
    assert set(result_all) == set(abstracts_by_cat)
    assert fake_client.messages.create.call_count == 6
