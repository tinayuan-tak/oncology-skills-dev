#!/usr/bin/env python3
"""Generate {GENE}_workflow-target-evaluation-onc_report.md from structured inputs.

Replaces the hand-written integrated-report stage. Reads 5 structured
inputs (1 hand-written risk-assessment + 4 auto-generated outputs from
Steps 2-3), runs the schema linter on the risk-assessment markdown,
then renders the integrated report via Jinja2.

Usage:
    pixi run python scripts/generate_integrated_report.py \\
        --gene PCDH7 --disease nsclc \\
        --output-dir /path/to/PCDH7 \\
        [--modality "T-cell engager"]

Exit codes:
    0 — markdown generated successfully
    1 — input validation or render failure (linter error, missing file)
    2 — file system error (output dir missing, write failure)

Pre-flight: runs lint_risk_assessment.py on the input markdown. If the
linter fails, the generator refuses to run — schema enforcement, not
parser tolerance.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from integrated_report.context import build_context  # noqa: E402
from integrated_report.parsers import (  # noqa: E402
    load_comparisons, load_idas, load_scholareval,
    load_suitability, parse_risk_assessment,
)
from integrated_report.renderer import render_integrated_report  # noqa: E402
from lint_risk_assessment import lint as lint_risk_md  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Generate integrated target-evaluation report from structured inputs.'
    )
    parser.add_argument('--gene', required=True, help='Gene symbol (e.g. PCDH7)')
    parser.add_argument('--disease', required=True, choices=['crc', 'nsclc'])
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='Directory containing the 5 structured inputs; output written here.')
    parser.add_argument('--modality', default=None,
                        help='Therapeutic modality string (e.g. "Antibody", "Molecular Glue", '
                             '"T-cell engager"). Resolved via the modality registry.')
    parser.add_argument('--workflow-version', default='1.2.0',
                        help='Pipeline version recorded in the report header.')
    parser.add_argument('--skip-lint', action='store_true',
                        help='Skip risk-assessment lint pre-flight (NOT recommended).')
    args = parser.parse_args()

    out_dir: Path = args.output_dir
    if not out_dir.is_dir():
        sys.stderr.write(f'ERROR: output dir not found: {out_dir}\n')
        return 2

    gene = args.gene
    disease = args.disease

    # Resolve all 5 input paths.
    risk_md = out_dir / f'{gene}_risk_assessment_{disease}.md'
    idas_yaml = out_dir / f'{gene}_analysis-bulk-rna-{disease}_idas.yaml'
    suitability_csv = out_dir / f'{gene}_analysis-bulk-rna-{disease}_suitability.csv'
    comparisons_csv = out_dir / f'{gene}_analysis-bulk-rna-{disease}_comparisons.csv'
    scholar_yaml = out_dir / f'{gene}_scholareval.yaml'

    inputs = {
        'risk-assessment': risk_md,
        'idas': idas_yaml,
        'suitability': suitability_csv,
        'comparisons': comparisons_csv,
        'scholareval': scholar_yaml,
    }
    missing = {label: path for label, path in inputs.items() if not path.exists()}
    if missing:
        sys.stderr.write('ERROR: required inputs missing:\n')
        for label, path in missing.items():
            sys.stderr.write(f'  - {label}: {path}\n')
        sys.stderr.write(
            'Run Steps 1-3 first (risk-assessment markdown + bulk-RNA + ScholarEval) '
            'before invoking the integrated-report generator.\n'
        )
        return 1

    # Pre-flight: lint the hand-written risk-assessment markdown.
    if not args.skip_lint:
        lint_result = lint_risk_md(risk_md)
        if not lint_result.passed:
            sys.stderr.write('ERROR: risk-assessment markdown failed schema lint.\n')
            sys.stderr.write(f'File: {risk_md}\n')
            for line_no, msg in lint_result.errors:
                prefix = f'  Line {line_no}: ' if line_no else '  '
                sys.stderr.write(f'{prefix}{msg}\n')
            sys.stderr.write(
                '\nFix the input markdown before running the generator.\n'
                'See reference/risk_assessment_schema.md for the schema.\n'
            )
            return 1

    print(f'Reading inputs from {out_dir} ...')
    risk = parse_risk_assessment(risk_md)
    idas = load_idas(idas_yaml)
    suitability = load_suitability(suitability_csv)
    comparisons = load_comparisons(comparisons_csv)
    scholar = load_scholareval(scholar_yaml)

    print(f'Building render context for {gene} ({disease}) ...')
    ctx = build_context(
        gene=gene, disease=disease,
        risk=risk, idas=idas, suitability=suitability,
        comparisons=comparisons, scholar=scholar,
        modality=args.modality,
        workflow_version=args.workflow_version,
    )

    print('Rendering integrated report ...')
    markdown = render_integrated_report(ctx)

    output_path = out_dir / f'{gene}_workflow-target-evaluation-onc_report.md'
    output_path.write_text(markdown)
    print(f'Wrote: {output_path}')
    print(f'Size: {len(markdown):,} chars / {markdown.count(chr(10))} lines')
    return 0


if __name__ == '__main__':
    sys.exit(main())
