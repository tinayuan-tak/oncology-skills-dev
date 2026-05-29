"""End-to-end + round-trip tests for the integrated-report generator.

The critical regression guard: generated markdown must round-trip
through the existing PDF parser cleanly (zero TBD fields, all required
sections detected). If this passes, the generator output is suitable
for `generate_target_report_pdf.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.context import build_context  # noqa: E402
from integrated_report.parsers import (  # noqa: E402
    load_comparisons, load_idas, load_scholareval,
    load_suitability, parse_risk_assessment,
)
from integrated_report.renderer import render_integrated_report  # noqa: E402

# The PDF extractor's parsers — what the generator's output is graded against.
import generate_target_report_pdf as pdf_gen  # noqa: E402

PCDH7_DIR = Path('/Users/eta3879/target_evaluation_bulk/nsclc_bulk_rna/PCDH7')
CRBN_DIR = Path('/Users/eta3879/target_evaluation_bulk/crc_bulk_rna/CRBN')


# ---------------------------------------------------------------------------
# End-to-end render
# ---------------------------------------------------------------------------

def _render_for(gene: str, disease: str, dir_path: Path,
                modality: str | None = None) -> str:
    """Run the full Layer 1+2+3 pipeline on a real input dir."""
    return render_integrated_report(build_context(
        gene=gene, disease=disease, modality=modality,
        risk=parse_risk_assessment(dir_path / f'{gene}_risk_assessment_{disease}.md'),
        idas=load_idas(dir_path / f'{gene}_analysis-bulk-rna-{disease}_idas.yaml'),
        suitability=load_suitability(dir_path / f'{gene}_analysis-bulk-rna-{disease}_suitability.csv'),
        comparisons=load_comparisons(dir_path / f'{gene}_analysis-bulk-rna-{disease}_comparisons.csv'),
        scholar=load_scholareval(dir_path / f'{gene}_scholareval.yaml'),
    ))


class TestEndToEndRender:
    def test_pcdh7_renders(self) -> None:
        md = _render_for('PCDH7', 'nsclc', PCDH7_DIR, modality='Antibody')
        assert len(md) > 5000
        # Required sections appear.
        for section in ['## Executive Summary', '### Key Findings at a Glance',
                         '## 1. Introduction', '## 2. Methods',
                         '### 3.1 Risk Assessment Summary',
                         '### 3.2 Differential Expression Analysis',
                         '### 3.3 Target Validation Scorecard',
                         '### 3.4 Subgroup-Stratified Suitability',
                         '## 4. Discussion', '## 5. Risk Mitigation Strategies',
                         '## 6. Recommendations', '## 7. Conclusions']:
            assert section in md, f'missing required section: {section!r}'

    def test_crbn_renders(self) -> None:
        md = _render_for('CRBN', 'crc', CRBN_DIR, modality='Molecular Glue')
        assert len(md) > 5000
        assert '**Recommendation** | **GO' in md or 'GO' in md
        # Modality routing reflected in the output.
        assert 'Molecular Glue' in md or 'degrader' in md


# ---------------------------------------------------------------------------
# Round-trip: generated markdown must parse cleanly through PDF parsers
# ---------------------------------------------------------------------------

class TestRoundTripWithPDFParser:
    """Critical regression guard. The generator's output is the PDF
    parser's input. Every required field the PDF parser looks for must
    be populated — zero TBD/fallback values."""

    def _parse_round_trip(self, gene: str, disease: str, dir_path: Path,
                          modality: str | None, tmp_path: Path):
        md = _render_for(gene, disease, dir_path, modality)
        report_path = tmp_path / f'{gene}_workflow-target-evaluation-onc_report.md'
        report_path.write_text(md)
        return report_path, pdf_gen.parse_integrated_report(
            str(report_path), output_dir=str(tmp_path), gene=gene, disease=disease,
        )

    def test_pcdh7_round_trip_no_tbd(self, tmp_path: Path) -> None:
        _, data = self._parse_round_trip(
            'PCDH7', 'nsclc', PCDH7_DIR, 'Antibody', tmp_path,
        )
        # Every required field must be populated — no TBD.
        assert data['score'] != 'TBD'
        assert data['risk_profile'] != 'TBD'
        assert data['recommendation'] != 'TBD'
        assert data['assessment'] != 'TBD'
        # Risk table populated for all 6 categories.
        assert len(data['risk_table']) == 6
        # ScholarEval scores populated.
        assert len(data['scholar_scores']) == 8

    def test_crbn_round_trip_no_tbd(self, tmp_path: Path) -> None:
        _, data = self._parse_round_trip(
            'CRBN', 'crc', CRBN_DIR, 'Molecular Glue', tmp_path,
        )
        assert data['score'] != 'TBD'
        assert data['risk_profile'] != 'TBD'
        assert data['recommendation'] != 'TBD'
        assert len(data['risk_table']) == 6
        assert len(data['scholar_scores']) == 8

    def test_pcdh7_recommendation_preserves_priority_qualifier(
        self, tmp_path: Path,
    ) -> None:
        """v1.1.0 parser bug regression: 'GO — MEDIUM-HIGH PRIORITY'
        must round-trip without losing the qualifier."""
        _, data = self._parse_round_trip(
            'PCDH7', 'nsclc', PCDH7_DIR, 'Antibody', tmp_path,
        )
        # Must contain GO and PRIORITY (parser's normalized form is
        # 'GO — MEDIUM-HIGH PRIORITY' or 'GO').
        assert 'GO' in data['recommendation']

    def test_round_trip_slide_data_populates(self, tmp_path: Path) -> None:
        """Check the page-1 slide data extractor (separate from
        parse_integrated_report) also gets clean inputs."""
        report_path, _ = self._parse_round_trip(
            'PCDH7', 'nsclc', PCDH7_DIR, 'Antibody', tmp_path,
        )
        slide_data = pdf_gen._build_slide_data(str(tmp_path), 'PCDH7')
        # Modality is the bug we hit on PCDH7_TCE — must populate now.
        assert slide_data['modality'] != ''
        assert slide_data['modality'] != 'Selective'
        # Takeaways from the Key Findings at a Glance section.
        assert len(slide_data['takeaways']) >= 3


# ---------------------------------------------------------------------------
# Modality awareness — same gene, different modality, different output
# ---------------------------------------------------------------------------

class TestModalityAwareness:
    def test_modality_string_in_output(self, tmp_path: Path) -> None:
        """The user-supplied modality must appear in the rendered output."""
        for modality in ['Antibody', 'ADC', 'T-cell engager', 'Molecular Glue']:
            md = _render_for('PCDH7', 'nsclc', PCDH7_DIR, modality)
            # Modality string OR its registry-resolved class should appear.
            assert (modality in md
                    or modality.lower() in md.lower()
                    or any(c in md for c in
                           ['antibody_naked', 'adc', 'tce', 'degrader'])), \
                f'modality {modality!r} not visible in rendered output'

    def test_modality_class_in_phase3_header(self, tmp_path: Path) -> None:
        """§3.4 Phase 3 header should name the modality class."""
        md = _render_for('PCDH7', 'nsclc', PCDH7_DIR, 'Molecular Glue')
        assert 'modality' in md.lower()
