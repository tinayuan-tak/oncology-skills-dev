"""Tests for v1.4.0 canonical-value enforcement in load_facts().

Closes the schema-drift gap exposed in v1.3.0: structural validation
existed but enums/types were not enforced, so two analysts could write
facts.yaml files that lint-pass but render slightly differently.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.risk_assessment_renderer import (  # noqa: E402
    CANONICAL_DISEASES, CANONICAL_IDAS_ALIGNMENTS,
    CANONICAL_MITIGATION_LEVELS, CANONICAL_RECOMMENDATION_LEVELS,
    CANONICAL_RECOMMENDATION_PRIORITIES, CANONICAL_RISK_LEVELS,
    CANONICAL_WHITESPACES, load_facts,
)


def _write_facts(tmp_path: Path, facts_yaml: str) -> Path:
    """Write a facts.yaml fixture file and return its path."""
    p = tmp_path / 'facts.yaml'
    p.write_text(facts_yaml)
    return p


# Minimal valid facts.yaml — used as a baseline that tests perturb.
MINIMAL_VALID = textwrap.dedent("""\
    gene: TESTGENE
    disease: nsclc
    date: 2026-05-30
    risk_categories:
      biological: {level: LOW, key_driver: x, justification: y}
      druggability: {level: LOW, key_driver: x, justification: y}
      translational: {level: LOW, key_driver: x, justification: y}
      clinical: {level: LOW, key_driver: x, justification: y}
      safety: {level: LOW, key_driver: x, justification: y}
      commercial: {level: LOW, key_driver: x, justification: y}
    mitigations:
      - {title: A, risk_level: LOW, strategy: x}
    recommendation:
      level: GO
""")


# ---------------------------------------------------------------------------
# Baseline parses cleanly
# ---------------------------------------------------------------------------

def test_minimal_valid_parses(tmp_path: Path) -> None:
    p = _write_facts(tmp_path, MINIMAL_VALID)
    facts = load_facts(p)
    assert facts.gene == 'TESTGENE'
    assert facts.disease == 'nsclc'


# ---------------------------------------------------------------------------
# Risk-category levels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level_in, expected", [
    ('LOW', 'LOW'),
    ('low', 'LOW'),         # case normalization
    ('Low', 'LOW'),
    ('  LOW  ', 'LOW'),     # whitespace strip
    ('LOW–MEDIUM', 'LOW-MEDIUM'),  # en-dash → ASCII
    ('LOW—MEDIUM', 'LOW-MEDIUM'),  # em-dash → ASCII
    ('MEDIUM-HIGH', 'MEDIUM-HIGH'),
])
def test_risk_level_normalization(tmp_path: Path, level_in: str, expected: str) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'biological: {level: LOW,',
        f'biological: {{level: "{level_in}",',
    )
    p = _write_facts(tmp_path, yaml_text)
    facts = load_facts(p)
    assert facts.risk_categories['biological']['level'] == expected


@pytest.mark.parametrize("bad_level", [
    'EXTREME', 'medium-low', 'low-low', 'TBD', 'unknown', '',
])
def test_invalid_risk_level_rejected(tmp_path: Path, bad_level: str) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'biological: {level: LOW,',
        f'biological: {{level: "{bad_level}",',
    )
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='level must be one of'):
        load_facts(p)


def test_canonical_risk_levels_exact_set() -> None:
    """Lock down the exact accepted set so adding values is intentional."""
    assert CANONICAL_RISK_LEVELS == {
        'LOW', 'MEDIUM', 'HIGH', 'LOW-MEDIUM', 'MEDIUM-HIGH',
    }


# ---------------------------------------------------------------------------
# Recommendation level + priority
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rec_level", ['GO', 'NO-GO', 'CONDITIONAL', 'CONDITIONAL NO-GO'])
def test_canonical_recommendation_levels_accepted(
    tmp_path: Path, rec_level: str,
) -> None:
    yaml_text = MINIMAL_VALID.replace('level: GO', f'level: "{rec_level}"')
    p = _write_facts(tmp_path, yaml_text)
    facts = load_facts(p)
    assert facts.recommendation['level'] == rec_level


@pytest.mark.parametrize("bad", ['MAYBE', 'YES', 'TBD', ''])
def test_invalid_recommendation_level_rejected(tmp_path: Path, bad: str) -> None:
    yaml_text = MINIMAL_VALID.replace('level: GO', f'level: "{bad}"')
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='recommendation.level must be'):
        load_facts(p)


@pytest.mark.parametrize("priority_in, expected", [
    ('HIGH', 'HIGH'),
    ('high', 'HIGH'),
    ('MEDIUM-HIGH', 'MEDIUM-HIGH'),
    ('medium-high', 'MEDIUM-HIGH'),
    ('MEDIUM–HIGH', 'MEDIUM-HIGH'),  # en-dash
])
def test_recommendation_priority_normalization(
    tmp_path: Path, priority_in: str, expected: str,
) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'level: GO',
        f'level: GO\n  priority: "{priority_in}"',
    )
    p = _write_facts(tmp_path, yaml_text)
    facts = load_facts(p)
    assert facts.recommendation['priority'] == expected


def test_invalid_recommendation_priority_rejected(tmp_path: Path) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'level: GO',
        'level: GO\n  priority: "URGENT"',
    )
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='recommendation.priority'):
        load_facts(p)


# ---------------------------------------------------------------------------
# PMID type coercion
# ---------------------------------------------------------------------------

def test_pmid_int_coerced_to_string(tmp_path: Path) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'biological: {level: LOW, key_driver: x, justification: y}',
        textwrap.dedent("""\
            biological:
                level: LOW
                key_driver: x
                justification: y
                evidence:
                  - claim: "test"
                    pmid: 12345678"""),
    )
    p = _write_facts(tmp_path, yaml_text)
    facts = load_facts(p)
    pmid = facts.risk_categories['biological']['evidence'][0]['pmid']
    assert isinstance(pmid, str)
    assert pmid == '12345678'


@pytest.mark.parametrize("bad_pmid", ['abc', '12345', '1234567890', ''])
def test_invalid_pmid_rejected(tmp_path: Path, bad_pmid: str) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'biological: {level: LOW, key_driver: x, justification: y}',
        textwrap.dedent(f"""\
            biological:
                level: LOW
                key_driver: x
                justification: y
                evidence:
                  - claim: "test"
                    pmid: "{bad_pmid}\""""),
    )
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='pmid'):
        load_facts(p)


# ---------------------------------------------------------------------------
# iDAS alignment: per-disease canonical whitespace + alignment values
# ---------------------------------------------------------------------------

def test_canonical_whitespace_accepted_nsclc(tmp_path: Path) -> None:
    yaml_text = MINIMAL_VALID + textwrap.dedent("""\
        idas_alignment:
          - whitespace: "2L Non-AGA (IO-experienced)"
            alignment: Strong
            rationale: x
    """)
    p = _write_facts(tmp_path, yaml_text)
    facts = load_facts(p)
    assert facts.idas_alignment[0]['whitespace'] == '2L Non-AGA (IO-experienced)'
    assert facts.idas_alignment[0]['alignment'] == 'Strong'


def test_non_canonical_whitespace_rejected(tmp_path: Path) -> None:
    yaml_text = MINIMAL_VALID + textwrap.dedent("""\
        idas_alignment:
          - whitespace: "Some Made-Up Whitespace"
            alignment: Strong
    """)
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='whitespace must be one of'):
        load_facts(p)


def test_crc_whitespace_rejected_for_nsclc(tmp_path: Path) -> None:
    """NSCLC facts can't reference CRC-disease whitespaces."""
    yaml_text = MINIMAL_VALID + textwrap.dedent("""\
        idas_alignment:
          - whitespace: "Chemorefractory 3L+"
            alignment: Strong
    """)
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='whitespace must be one of'):
        load_facts(p)


@pytest.mark.parametrize("alignment_in, expected", [
    ('Strong', 'Strong'),
    ('strong', 'Strong'),    # title-case
    ('STRONG', 'Strong'),
    ('  Moderate  ', 'Moderate'),
])
def test_alignment_normalization(
    tmp_path: Path, alignment_in: str, expected: str,
) -> None:
    yaml_text = MINIMAL_VALID + textwrap.dedent(f"""\
        idas_alignment:
          - whitespace: "2L Non-AGA (IO-experienced)"
            alignment: "{alignment_in}"
    """)
    p = _write_facts(tmp_path, yaml_text)
    facts = load_facts(p)
    assert facts.idas_alignment[0]['alignment'] == expected


def test_invalid_alignment_rejected(tmp_path: Path) -> None:
    yaml_text = MINIMAL_VALID + textwrap.dedent("""\
        idas_alignment:
          - whitespace: "2L Non-AGA (IO-experienced)"
            alignment: "Excellent"
    """)
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='alignment must be one of'):
        load_facts(p)


# ---------------------------------------------------------------------------
# Mitigations: subset of risk levels (compound levels rejected)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_level", ['LOW-MEDIUM', 'MEDIUM-HIGH', 'EXTREME'])
def test_compound_mitigation_level_rejected(tmp_path: Path, bad_level: str) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'risk_level: LOW', f'risk_level: "{bad_level}"',
    )
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='risk_level must be'):
        load_facts(p)


# ---------------------------------------------------------------------------
# Disease canonical
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_disease", ['breast', 'BRCA', 'pdac', 'unknown'])
def test_invalid_disease_rejected(tmp_path: Path, bad_disease: str) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'disease: nsclc', f'disease: "{bad_disease}"',
    )
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='disease must be one of'):
        load_facts(p)


# ---------------------------------------------------------------------------
# Unrecognized keys (typo guard)
# ---------------------------------------------------------------------------

def test_unrecognized_top_level_key_rejected(tmp_path: Path) -> None:
    yaml_text = MINIMAL_VALID + 'random_typo_field: x\n'
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='unrecognized key'):
        load_facts(p)


def test_unrecognized_category_key_rejected(tmp_path: Path) -> None:
    yaml_text = MINIMAL_VALID.replace(
        'biological: {level: LOW, key_driver: x, justification: y}',
        textwrap.dedent("""\
            biological:
                level: LOW
                key_driver: x
                justification: y
                random_typo: "oops\""""),
    )
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='unrecognized key'):
        load_facts(p)


def test_extra_risk_category_rejected(tmp_path: Path) -> None:
    """Adding a 7th category should be rejected."""
    yaml_text = MINIMAL_VALID.replace(
        'commercial: {level: LOW, key_driver: x, justification: y}',
        'commercial: {level: LOW, key_driver: x, justification: y}\n  '
        'imaginary: {level: LOW, key_driver: x, justification: y}',
    )
    p = _write_facts(tmp_path, yaml_text)
    with pytest.raises(ValueError, match='unrecognized entries'):
        load_facts(p)


# ---------------------------------------------------------------------------
# Constants are well-defined (regression guards)
# ---------------------------------------------------------------------------

def test_canonical_recommendation_levels_locked_set() -> None:
    assert CANONICAL_RECOMMENDATION_LEVELS == {
        'GO', 'NO-GO', 'CONDITIONAL', 'CONDITIONAL NO-GO',
    }


def test_canonical_diseases_locked_set() -> None:
    assert CANONICAL_DISEASES == {'crc', 'nsclc'}


def test_canonical_idas_alignments_locked_set() -> None:
    assert CANONICAL_IDAS_ALIGNMENTS == {'Strong', 'Moderate', 'Weak', 'None'}


def test_canonical_whitespaces_per_disease() -> None:
    assert CANONICAL_WHITESPACES['crc'] == {
        'Chemorefractory 3L+', 'RAS Mutant Frontline',
        'RAS Mutant Refractory', 'Resectable',
    }
    assert CANONICAL_WHITESPACES['nsclc'] == {
        '2L Non-AGA (IO-experienced)',
        '2L EGFR Mutant (post-TKI)',
        '1L/2L KRAS Mutant',
    }


# ---------------------------------------------------------------------------
# v1.6.0: per-category placement of structured fields
# ---------------------------------------------------------------------------

def _cat_facts_with_extra(category: str, extra: dict) -> str:
    """Build a facts.yaml string where `category` carries an extra field
    that may or may not belong there, and return as YAML text."""
    base = {
        "gene": "G", "disease": "nsclc", "date": "2026-01-01",
        "risk_categories": {
            cat: {"level": "MEDIUM", "key_driver": "x", "justification": "x"}
            for cat in ("biological", "druggability", "translational",
                        "clinical", "safety", "commercial")
        },
        "recommendation": {"level": "CONDITIONAL", "rationale": "x"},
        "mitigations": [{"title": "t", "risk_level": "MEDIUM", "strategy": "s"}],
    }
    base["risk_categories"][category].update(extra)
    return yaml.safe_dump(base)


def test_highest_phase_rejected_outside_clinical(tmp_path):
    """Opus has been observed spraying clinical-only fields onto other
    categories. The strict validator must reject misplacement."""
    p = _write_facts(tmp_path, _cat_facts_with_extra("safety", {"highest_phase": 0}))
    with pytest.raises(ValueError, match="risk_categories.safety.*highest_phase"):
        load_facts(p)


def test_pathway_score_rejected_outside_biological(tmp_path):
    p = _write_facts(tmp_path, _cat_facts_with_extra("translational",
                                                    {"pathway_score": 4}))
    with pytest.raises(ValueError,
                       match="risk_categories.translational.*pathway_score"):
        load_facts(p)


def test_has_clinical_compound_rejected_outside_druggability(tmp_path):
    p = _write_facts(tmp_path, _cat_facts_with_extra("commercial",
                                                    {"has_clinical_compound": True}))
    with pytest.raises(ValueError,
                       match="risk_categories.commercial.*has_clinical_compound"):
        load_facts(p)


# ---------------------------------------------------------------------------
# Real-target round-trip: existing facts.yaml files still parse cleanly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path_str", [
    '/Users/eta3879/target_evaluation_bulk/crc_bulk_rna/CRBN/CRBN_risk_assessment_facts.yaml',
    '/Users/eta3879/target_evaluation_bulk/nsclc_bulk_rna/PCDH7/PCDH7_risk_assessment_facts.yaml',
    '/Users/eta3879/target_evaluation_bulk/nsclc_bulk_rna/CDCP1/CDCP1/CDCP1_risk_assessment_facts.yaml',
])
def test_real_facts_files_parse_after_strict_validation(path_str: str) -> None:
    """All 3 real-target facts.yaml files (post-canonical-cleanup) must
    parse with the v1.4.0 strict validator."""
    p = Path(path_str)
    if not p.exists():
        pytest.skip(f'fixture path not present on this machine: {p}')
    facts = load_facts(p)
    assert facts.gene
    assert facts.disease in CANONICAL_DISEASES
    assert len(facts.risk_categories) == 6
