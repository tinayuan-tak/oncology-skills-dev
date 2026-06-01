"""v1.7.2: tests for modality provenance + page-1 fixes."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.context import _build_modality_context  # noqa: E402
from integrated_report.parsers import IDASAssessment, RiskAssessment  # noqa: E402


def _bare_idas(modality: str = '', modality_class: str = '') -> IDASAssessment:
    """Minimal IDASAssessment with empty whitespaces; suitable for
    modality-context tests that don't exercise iDAS scoring."""
    return IDASAssessment(
        gene='G', overall_alignment='Unknown',
        recommendation='', on_target_tox_risk='Unknown',
        on_target_tox_log2fc=0.0,
        luad_log2fc=None, lusc_log2fc=None,
        whitespaces={},
        modality=modality, modality_class=modality_class,
    )


def _bare_risk(modality_candidates: list[str] | None = None) -> RiskAssessment:
    return RiskAssessment(
        gene='G', disease='nsclc',
        overall_risk_profile='LOW',
        categories={},
        modality_candidates=modality_candidates or [],
    )


def _write_facts(tmp_path: Path, modality_source: str | None) -> Path:
    p = tmp_path / 'facts.yaml'
    data = {'modality_source': modality_source} if modality_source else {}
    p.write_text(yaml.safe_dump(data))
    return p


# ---------------------------------------------------------------------------
# Provenance: source label resolution waterfall
# ---------------------------------------------------------------------------

def test_cli_modality_marks_user_provided(tmp_path):
    """--modality at Step 4 → source='user'."""
    ctx = _build_modality_context(
        cli_modality='Small molecule inhibitor',
        idas=_bare_idas(),
        risk=_bare_risk(),
        facts_yaml=None,
    )
    assert ctx['source'] == 'user'
    assert ctx['source_label'] == 'user-provided'
    assert ctx['is_default'] is False
    assert ctx['class_id'] == 'small_molecule'  # B2: resolver IS called


def test_facts_modality_source_user_marks_user(tmp_path):
    """facts.yaml: modality_source='user' → source='user' even without CLI flag."""
    facts = _write_facts(tmp_path, 'user')
    ctx = _build_modality_context(
        cli_modality=None,
        idas=_bare_idas(),
        risk=_bare_risk(modality_candidates=['T-cell engager']),
        facts_yaml=facts,
    )
    assert ctx['source'] == 'user'
    assert ctx['class_id'] == 'tce'


def test_facts_modality_source_inferred(tmp_path):
    """facts.yaml: modality_source='inferred' → source='inferred'."""
    facts = _write_facts(tmp_path, 'inferred')
    ctx = _build_modality_context(
        cli_modality=None,
        idas=_bare_idas(),
        risk=_bare_risk(modality_candidates=['ADC']),
        facts_yaml=facts,
    )
    assert ctx['source'] == 'inferred'
    assert ctx['source_label'] == 'inferred from literature'
    assert ctx['is_default'] is False


def test_no_modality_anywhere_falls_to_default(tmp_path):
    """No CLI flag, no idas modality, no facts modality_candidates,
    no facts modality_source → source='default', class_id=antibody_naked."""
    facts = _write_facts(tmp_path, None)
    ctx = _build_modality_context(
        cli_modality=None,
        idas=_bare_idas(),
        risk=_bare_risk(),
        facts_yaml=facts,
    )
    assert ctx['source'] == 'default'
    assert 'default' in ctx['source_label']
    assert ctx['is_default'] is True
    assert ctx['class_id'] == 'antibody_naked'


def test_no_facts_yaml_at_all_falls_to_default():
    """When facts.yaml doesn't exist (legacy gene), and nothing upstream
    supplies modality, fall through to default."""
    ctx = _build_modality_context(
        cli_modality=None,
        idas=_bare_idas(),
        risk=_bare_risk(),
        facts_yaml=None,
    )
    assert ctx['source'] == 'default'
    assert ctx['is_default'] is True


# ---------------------------------------------------------------------------
# B2: resolver is called when idas.modality_class is empty
# ---------------------------------------------------------------------------

def test_idas_empty_class_triggers_registry_lookup():
    """v1.7.2 B2 fix: when idas.modality_class is '' (the new parser
    default), context should call ModalityRegistry.resolve_class(raw)
    instead of silently anchoring to antibody_naked."""
    ctx = _build_modality_context(
        cli_modality='T-cell engager',
        idas=_bare_idas(modality_class=''),  # the new default
        risk=_bare_risk(),
    )
    assert ctx['class_id'] == 'tce'  # registry resolved correctly


def test_idas_explicit_class_takes_priority():
    """When Step 2 already resolved the class, that wins over CLI string."""
    ctx = _build_modality_context(
        cli_modality='T-cell engager',
        idas=_bare_idas(modality_class='degrader'),  # Step 2 says degrader
        risk=_bare_risk(),
    )
    assert ctx['class_id'] == 'degrader'
