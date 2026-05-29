"""Tests for Layer 1 — input parsers.

Each parser tested against fixtures + the real CRBN/PCDH7 inputs as
golden cases.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.parsers import (  # noqa: E402
    parse_risk_assessment, load_idas, load_suitability,
    load_comparisons, load_scholareval,
)

PCDH7_DIR = Path('/Users/eta3879/target_evaluation_bulk/nsclc_bulk_rna/PCDH7')
CRBN_DIR = Path('/Users/eta3879/target_evaluation_bulk/crc_bulk_rna/CRBN')


# ---------------------------------------------------------------------------
# Risk-assessment parser
# ---------------------------------------------------------------------------

class TestRiskAssessmentParser:
    """Hand-written markdown parser — the riskiest piece of Layer 1."""

    def test_pcdh7_full_extraction(self) -> None:
        ra = parse_risk_assessment(PCDH7_DIR / 'PCDH7_risk_assessment_nsclc.md')
        assert ra.gene == 'PCDH7'
        assert 'Non-Small Cell Lung Cancer' in ra.disease
        assert ra.overall_risk_profile == 'LOW-MEDIUM'
        assert 'GO' in ra.recommendation
        assert 'PRIORITY' in ra.recommendation
        # All 6 categories must be present.
        assert set(ra.categories.keys()) == {
            'Biological', 'Druggability', 'Translational',
            'Clinical', 'Safety', 'Commercial',
        }
        assert ra.categories['Biological'].level == 'LOW'
        assert ra.categories['Druggability'].level == 'MEDIUM'
        # PMIDs extracted across summary + per-category sections.
        assert len(ra.categories['Biological'].evidence_pmids) >= 2
        assert len(ra.mitigations) >= 5
        assert len(ra.idas_alignments) >= 3

    def test_crbn_full_extraction(self) -> None:
        ra = parse_risk_assessment(CRBN_DIR / 'CRBN_risk_assessment_crc.md')
        assert ra.gene == 'CRBN'
        assert 'Colorectal' in ra.disease
        assert ra.overall_risk_profile == 'LOW-MEDIUM'
        assert 'GO' in ra.recommendation
        assert set(ra.categories.keys()) == {
            'Biological', 'Druggability', 'Translational',
            'Clinical', 'Safety', 'Commercial',
        }
        assert ra.categories['Biological'].level == 'LOW'
        assert ra.categories['Druggability'].level == 'LOW'

    def test_strict_no_fallback_on_missing_summary(self, tmp_path: Path) -> None:
        """If Executive Risk Summary table is absent, categories dict is
        empty (no silent fallback). The linter is responsible for
        catching this upstream."""
        broken = tmp_path / 'broken.md'
        broken.write_text(textwrap.dedent('''\
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
        ra = parse_risk_assessment(broken)
        # No Executive Risk Summary → no categories. Strict.
        assert ra.categories == {}

    def test_compound_risk_levels_normalized(self, tmp_path: Path) -> None:
        broken = tmp_path / 'compound.md'
        broken.write_text(textwrap.dedent('''\
            # X Drug Target Risk Assessment — Y

            ## Executive Risk Summary

            | Risk Factor | Risk Level | Key Considerations |
            |---|---|---|
            | Biological | **LOW–MEDIUM** | em-dash test |
            | Druggability | **MEDIUM-HIGH** | hyphen test |
            | Translational | **HIGH** | normal |
            | Clinical | **MEDIUM** | normal |
            | Safety | **LOW** | normal |
            | Commercial | **LOW** | normal |
        '''))
        ra = parse_risk_assessment(broken)
        assert ra.categories['Biological'].level == 'LOW-MEDIUM'
        assert ra.categories['Druggability'].level == 'MEDIUM-HIGH'

    def test_decimal_values_not_truncated_in_key_driver(
        self, tmp_path: Path,
    ) -> None:
        """Regression: 'log2FC = +1.05 (LUAD +0.75...)' was truncated at
        the first period to 'log2FC = +1'."""
        body = textwrap.dedent('''\
            # X Drug Target Risk Assessment — Y

            ## Executive Risk Summary

            | Risk Factor | Risk Level | Key Considerations |
            |---|---|---|
            | Biological | LOW | log2FC = +1.05 (LUAD +0.75, LUSC +1.34); good |
            | Druggability | LOW | x |
            | Translational | LOW | x |
            | Clinical | LOW | x |
            | Safety | LOW | x |
            | Commercial | LOW | x |
        ''')
        f = tmp_path / 'decimal.md'
        f.write_text(body)
        ra = parse_risk_assessment(f)
        assert '1.05' in ra.categories['Biological'].key_driver
        assert '0.75' in ra.categories['Biological'].key_driver


# ---------------------------------------------------------------------------
# iDAS YAML parser
# ---------------------------------------------------------------------------

class TestIDASParser:
    def test_pcdh7_idas(self) -> None:
        idas = load_idas(
            PCDH7_DIR / 'PCDH7_analysis-bulk-rna-nsclc_idas.yaml'
        )
        assert idas.gene == 'PCDH7'
        assert idas.overall_alignment == 'High'
        assert idas.on_target_tox_risk == 'Low'
        assert len(idas.whitespaces) == 3
        # All 3 should be Strong.
        assert all(ws.alignment == 'Strong' for ws in idas.whitespaces.values())

    def test_crbn_idas(self) -> None:
        idas = load_idas(
            CRBN_DIR / 'CRBN_analysis-bulk-rna-crc_idas.yaml'
        )
        assert idas.gene == 'CRBN'
        # CRBN has High tox (uniformly expressed).
        assert idas.on_target_tox_risk == 'High'

    def test_expression_field_fallback(self) -> None:
        """Various field names for expression — parser tries them in order."""
        idas = load_idas(
            PCDH7_DIR / 'PCDH7_analysis-bulk-rna-nsclc_idas.yaml'
        )
        for ws in idas.whitespaces.values():
            assert ws.expression_log2tpm > 0


# ---------------------------------------------------------------------------
# Suitability + Comparisons CSV parsers
# ---------------------------------------------------------------------------

class TestCSVParsers:
    def test_suitability_pcdh7(self) -> None:
        rows = load_suitability(
            PCDH7_DIR / 'PCDH7_analysis-bulk-rna-nsclc_suitability.csv'
        )
        assert len(rows) == 13
        cats = {r.category for r in rows}
        assert {'tcga_analysis', 'tempus_mutation', 'idas_whitespace'} <= cats

    def test_comparisons_pcdh7(self) -> None:
        rows = load_comparisons(
            PCDH7_DIR / 'PCDH7_analysis-bulk-rna-nsclc_comparisons.csv'
        )
        assert len(rows) == 4
        # LUSC vs adjacent should have larger fold change than LUAD vs adjacent.
        lusc = next(r for r in rows if r.tumor_cohort == 'TCGA_LUSC'
                    and r.normal_group == 'TCGA_LUSC_Adjacent')
        luad = next(r for r in rows if r.tumor_cohort == 'TCGA_LUAD'
                    and r.normal_group == 'TCGA_LUAD_Adjacent')
        assert lusc.log2fc > luad.log2fc


# ---------------------------------------------------------------------------
# ScholarEval YAML parser
# ---------------------------------------------------------------------------

class TestScholarEvalParser:
    def test_pcdh7_scholar(self) -> None:
        sc = load_scholareval(PCDH7_DIR / 'PCDH7_scholareval.yaml')
        assert sc.gene == 'PCDH7'
        assert sc.total_score == pytest.approx(4.45, abs=0.01)
        assert sc.assessment == 'Strong'
        assert len(sc.dimensions) == 8
        assert sc.input_hash != ''

    def test_crbn_scholar(self) -> None:
        sc = load_scholareval(CRBN_DIR / 'CRBN_scholareval.yaml')
        assert sc.gene == 'CRBN'
        assert len(sc.dimensions) == 8
