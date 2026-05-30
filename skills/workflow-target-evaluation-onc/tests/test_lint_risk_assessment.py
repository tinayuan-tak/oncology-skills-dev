"""Tests for the risk-assessment linter."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from lint_risk_assessment import lint  # noqa: E402

PCDH7_MD = Path('/Users/eta3879/target_evaluation_bulk/nsclc_bulk_rna/PCDH7/PCDH7_risk_assessment_nsclc.md')
CRBN_MD = Path('/Users/eta3879/target_evaluation_bulk/crc_bulk_rna/CRBN/CRBN_risk_assessment_crc.md')


# ---------------------------------------------------------------------------
# Real markdowns must pass
# ---------------------------------------------------------------------------

def test_pcdh7_passes() -> None:
    result = lint(PCDH7_MD)
    assert result.passed, f'PCDH7 lint errors: {result.errors}'


def test_crbn_passes() -> None:
    result = lint(CRBN_MD)
    assert result.passed, f'CRBN lint errors: {result.errors}'


# ---------------------------------------------------------------------------
# Schema violations are caught
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_schema_compliant(tmp_path: Path) -> Path:
    """Smallest possible schema-compliant markdown — used as a baseline
    that subsequent tests perturb."""
    md = tmp_path / 'min.md'
    md.write_text(textwrap.dedent('''\
        # X Drug Target Risk Assessment — Y

        **Date:** 2026-01-01
        **Disease:** Test Disease
        **Target:** X (HGNC:0)
        **Modality candidates:** Antibody

        ## Strategic Alignment Assessment
        **Whitespace Alignment:** [x] foo

        ## Executive Risk Summary

        | Risk Factor | Risk Level | Key Considerations |
        |---|---|---|
        | Biological | LOW | x |
        | Druggability | LOW | x |
        | Translational | LOW | x |
        | Clinical | LOW | x |
        | Safety | LOW | x |
        | Commercial | LOW | x |

        **Overall Target Risk Profile: LOW**

        ## 1. Biological Risk Assessment
        **Risk Level Assigned:** LOW

        ## 2. Druggability Risk Assessment
        **Risk Level Assigned:** LOW

        ## 3. Translational Risk Assessment
        **Risk Level Assigned:** LOW

        ## 4. Clinical Risk Assessment
        **Risk Level Assigned:** LOW

        ## 5. Safety Risk Assessment
        **Risk Level Assigned:** LOW

        ## 6. Commercial Risk Assessment
        **Risk Level Assigned:** LOW

        ## iDAS Strategic Alignment Assessment

        | Priority Whitespace | Alignment | Rationale |
        |---|---|---|
        | Foo | Strong | x |

        ## Risk Mitigation Strategies

        | Risk | Risk Level | Mitigation Strategy |
        |---|---|---|
        | A | LOW | x |

        ## Recommendation
        **GO** - looks fine
    '''))
    return md


def test_minimal_schema_compliant_passes(minimal_schema_compliant: Path) -> None:
    result = lint(minimal_schema_compliant)
    assert result.passed, f'minimal lint errors: {result.errors}'


def test_missing_executive_risk_summary_fails(tmp_path: Path) -> None:
    bad = tmp_path / 'bad.md'
    bad.write_text(textwrap.dedent('''\
        # X Drug Target Risk Assessment — Y

        **Date:** 2026-01-01
        **Disease:** Test
        **Target:** X
        **Modality candidates:** Antibody

        ## Strategic Alignment Assessment
        **Whitespace Alignment:** [x] foo

        ## 1. Biological Risk Assessment
        **Risk Level Assigned:** LOW
    '''))
    result = lint(bad)
    assert not result.passed
    assert any('Executive Risk Summary' in m for _, m in result.errors)


def test_missing_per_category_section_fails(
    minimal_schema_compliant: Path, tmp_path: Path,
) -> None:
    """Drop the Druggability section → linter complains."""
    text = minimal_schema_compliant.read_text()
    text = text.replace('## 2. Druggability Risk Assessment', '## NOT a section')
    bad = tmp_path / 'no_drug.md'
    bad.write_text(text)
    result = lint(bad)
    assert not result.passed
    assert any('Druggability' in m for _, m in result.errors)


def test_summary_missing_one_category_fails(tmp_path: Path) -> None:
    bad = tmp_path / 'missing_cat.md'
    bad.write_text(textwrap.dedent('''\
        # X Drug Target Risk Assessment — Y

        **Date:** 2026-01-01
        **Disease:** Test
        **Target:** X
        **Modality candidates:** Antibody

        ## Strategic Alignment Assessment
        **Whitespace Alignment:** [x] foo

        ## Executive Risk Summary

        | Risk Factor | Risk Level | Key Considerations |
        |---|---|---|
        | Biological | LOW | x |
        | Druggability | LOW | x |
        | Translational | LOW | x |
        | Clinical | LOW | x |
        | Safety | LOW | x |

        **Overall Target Risk Profile: LOW**
    '''))
    result = lint(bad)
    assert not result.passed
    assert any('Commercial' in str(m) for _, m in result.errors)


def test_no_recommendation_phrase_fails(
    minimal_schema_compliant: Path, tmp_path: Path,
) -> None:
    text = minimal_schema_compliant.read_text()
    text = text.replace('**GO** - looks fine', 'just text, no bold recommendation')
    bad = tmp_path / 'no_rec.md'
    bad.write_text(text)
    result = lint(bad)
    assert not result.passed
    assert any('Recommendation' in m and 'not found' in m for _, m in result.errors)


def test_file_not_found(tmp_path: Path) -> None:
    result = lint(tmp_path / 'does_not_exist.md')
    assert not result.passed
    assert any('not found' in m.lower() for _, m in result.errors)
