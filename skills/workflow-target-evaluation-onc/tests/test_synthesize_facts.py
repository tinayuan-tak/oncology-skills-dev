"""Tests for Stage 2 — facts synthesis from extracted claims."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.extract_claims import CategoryExtraction, ExtractedClaim  # noqa: E402
from integrated_report.synthesize_facts import (  # noqa: E402
    _build_synthesis_prompt, _build_synthesize_tool,
    _parse_synthesis_response, synthesize_facts,
)
from integrated_report.risk_assessment_renderer import load_facts  # noqa: E402


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

def test_tool_schema_includes_canonical_disease_whitespaces() -> None:
    crc_schema = _build_synthesize_tool('crc')
    nsclc_schema = _build_synthesize_tool('nsclc')
    crc_ws = crc_schema['input_schema']['properties']['idas_alignment'] \
        ['items']['properties']['whitespace']['enum']
    nsclc_ws = nsclc_schema['input_schema']['properties']['idas_alignment'] \
        ['items']['properties']['whitespace']['enum']
    assert 'Chemorefractory 3L+' in crc_ws
    assert '2L Non-AGA (IO-experienced)' in nsclc_ws
    # Disease isolation: NSCLC schema doesn't accept CRC labels.
    assert 'Chemorefractory 3L+' not in nsclc_ws


def test_tool_schema_enums_match_canonical_sets() -> None:
    """Risk levels, alignment values, recommendation level, priority
    should all be enum-restricted to canonical sets."""
    schema = _build_synthesize_tool('nsclc')
    biological_level = schema['input_schema']['properties']['risk_categories'] \
        ['properties']['biological']['properties']['level']
    assert set(biological_level['enum']) == {
        'LOW', 'MEDIUM', 'HIGH', 'LOW-MEDIUM', 'MEDIUM-HIGH',
    }
    rec_level = schema['input_schema']['properties']['recommendation'] \
        ['properties']['level']
    assert set(rec_level['enum']) == {
        'GO', 'NO-GO', 'CONDITIONAL', 'CONDITIONAL NO-GO',
    }


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _make_extractions() -> dict[str, CategoryExtraction]:
    """Build a dict of CategoryExtraction objects with placeholder claims.

    PMIDs are realistic-shaped 8-digit strings to satisfy the strict
    load_facts() PMID validator (6-9 digits required).
    """
    cats = ['biological', 'druggability', 'translational',
            'clinical', 'safety', 'commercial']
    return {
        cat: CategoryExtraction(
            category=cat,
            claims=[
                ExtractedClaim(
                    pmid=f'1000{cat_idx:01d}{i:03d}',  # e.g. 10000000, 10000001
                    claim=f'Claim {i} for {cat}',
                    study_type='in vivo',
                    category=cat,
                )
                for i in range(2)
            ],
        )
        for cat_idx, cat in enumerate(cats)
    }


def test_prompt_includes_gene_disease_and_all_categories() -> None:
    prompt = _build_synthesis_prompt(
        gene='PCDH7', disease='nsclc', modality='Antibody',
        extractions=_make_extractions(),
    )
    assert 'PCDH7' in prompt
    assert 'NSCLC' in prompt
    for cat in ['Biological', 'Druggability', 'Translational',
                 'Clinical', 'Safety', 'Commercial']:
        assert cat in prompt


def test_prompt_includes_extracted_pmids() -> None:
    prompt = _build_synthesis_prompt(
        gene='PCDH7', disease='nsclc', modality=None,
        extractions=_make_extractions(),
    )
    assert 'Claim 0 for biological' in prompt


def test_prompt_handles_empty_categories_gracefully() -> None:
    extractions = {
        cat: CategoryExtraction(category=cat, claims=[])
        for cat in ['biological', 'druggability', 'translational',
                    'clinical', 'safety', 'commercial']
    }
    prompt = _build_synthesis_prompt(
        gene='X', disease='nsclc', modality=None, extractions=extractions,
    )
    assert 'No claims extracted' in prompt


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _make_synthesis_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=[
        SimpleNamespace(type='tool_use', input=payload),
    ])


def test_parse_synthesis_response_returns_dict() -> None:
    response = _make_synthesis_response({'recommendation': {'level': 'GO'}})
    parsed = _parse_synthesis_response(response)
    assert parsed == {'recommendation': {'level': 'GO'}}


def test_parse_synthesis_response_missing_tool_returns_empty() -> None:
    response = SimpleNamespace(content=[
        SimpleNamespace(type='text', text='no tool call'),
    ])
    assert _parse_synthesis_response(response) == {}


# ---------------------------------------------------------------------------
# synthesize_facts orchestration: produces a load_facts-compatible dict
# ---------------------------------------------------------------------------

def _full_synthesis_payload() -> dict:
    """A fully populated synthesis output that satisfies load_facts."""
    return {
        'background': 'PCDH7 is a cell-surface protocadherin.',
        'risk_categories': {
            'biological': {'level': 'LOW', 'key_driver': 'd', 'justification': 'j'},
            'druggability': {'level': 'MEDIUM', 'key_driver': 'd', 'justification': 'j'},
            'translational': {'level': 'MEDIUM', 'key_driver': 'd', 'justification': 'j'},
            'clinical': {'level': 'MEDIUM', 'key_driver': 'd', 'justification': 'j'},
            'safety': {'level': 'MEDIUM', 'key_driver': 'd', 'justification': 'j'},
            'commercial': {'level': 'LOW', 'key_driver': 'd', 'justification': 'j'},
        },
        'idas_alignment': [
            {'whitespace': '2L Non-AGA (IO-experienced)',
             'alignment': 'Strong',
             'rationale': 'r'},
        ],
        'strengths': ['s1', 's2'],
        'risks': ['r1', 'r2'],
        'mitigations': [{'title': 't', 'risk_level': 'MEDIUM', 'strategy': 's'}],
        'recommendation': {'level': 'GO', 'priority': 'MEDIUM-HIGH', 'rationale': 'r'},
    }


def test_synthesize_facts_returns_load_facts_compatible_dict(tmp_path: Path) -> None:
    """End-to-end on the synthesizer: mocked LLM returns valid payload,
    output dict round-trips through load_facts() cleanly."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _make_synthesis_response(
        _full_synthesis_payload(),
    )
    facts = synthesize_facts(
        gene='PCDH7', disease='nsclc',
        extractions=_make_extractions(),
        modality='Antibody',
        client=fake_client,
    )
    # Persist + re-load via load_facts for the strict-validation check.
    import yaml
    facts_path = tmp_path / 'PCDH7_risk_assessment_facts.yaml'
    facts_path.write_text(yaml.safe_dump(facts, sort_keys=False))
    parsed = load_facts(facts_path)
    assert parsed.gene == 'PCDH7'
    assert parsed.disease == 'nsclc'
    assert len(parsed.risk_categories) == 6
    assert parsed.recommendation['level'] == 'GO'


def test_synthesize_facts_attaches_evidence_from_stage1() -> None:
    """The synthesizer's output should carry evidence[] entries derived
    from Stage 1's extracted claims (Stage 2 doesn't see PMIDs)."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _make_synthesis_response(
        _full_synthesis_payload(),
    )
    extractions = _make_extractions()
    facts = synthesize_facts(
        gene='PCDH7', disease='nsclc',
        extractions=extractions,
        client=fake_client,
    )
    bio = facts['risk_categories']['biological']
    assert 'evidence' in bio
    assert len(bio['evidence']) == 2  # 2 claims per category in fixture
    assert len(bio['evidence'][0]['pmid']) == 8
    assert 'Claim 0' in bio['evidence'][0]['claim']


def test_synthesize_facts_unknown_disease_raises() -> None:
    with pytest.raises(ValueError, match='unknown disease'):
        synthesize_facts(
            gene='X', disease='breast',
            extractions={},
            client=MagicMock(),
        )
