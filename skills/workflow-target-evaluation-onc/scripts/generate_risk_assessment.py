#!/usr/bin/env python3
"""Generate {GENE}_risk_assessment_{disease}.md from facts.yaml.

Replaces the hand-written Step 1 markdown stage. Reads structured
facts → renders schema-compliant markdown via Jinja2 → optionally
runs the schema linter on the output as a self-check.

Usage:
    pixi run python scripts/generate_risk_assessment.py \\
        --gene PCDH7 --disease nsclc \\
        --output-dir /path/to/PCDH7

Expected input file (in the output dir):
    {GENE}_risk_assessment_facts.yaml

Produces:
    {GENE}_risk_assessment_{disease}.md

Exit codes:
    0 — markdown generated and lints cleanly
    1 — facts.yaml validation failure (missing required fields, etc.)
    2 — output failed the schema linter (template bug; should not happen)
    3 — file system error (output dir missing, write failure)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from integrated_report.risk_assessment_renderer import (  # noqa: E402
    load_facts, render_risk_assessment,
)
from lint_risk_assessment import lint as lint_risk_md  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Generate Step 1 risk-assessment markdown from facts.yaml.'
    )
    parser.add_argument('--gene', required=True, help='Gene symbol (e.g. PCDH7)')
    parser.add_argument('--disease', required=True, choices=['crc', 'nsclc'])
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='Directory containing {GENE}_risk_assessment_facts.yaml; '
                             'output {GENE}_risk_assessment_{disease}.md is written here.')
    parser.add_argument('--skip-lint-check', action='store_true',
                        help='Skip the post-render lint self-check (NOT recommended).')
    args = parser.parse_args()

    out_dir: Path = args.output_dir
    if not out_dir.is_dir():
        sys.stderr.write(f'ERROR: output dir not found: {out_dir}\n')
        return 3

    facts_path = out_dir / f'{args.gene}_risk_assessment_facts.yaml'
    if not facts_path.exists():
        sys.stderr.write(
            f'ERROR: facts file not found: {facts_path}\n'
            f'See reference/risk_assessment_facts_schema.md for the required shape.\n'
        )
        return 1

    print(f'Loading facts: {facts_path}')
    try:
        facts = load_facts(facts_path)
    except ValueError as e:
        sys.stderr.write(f'ERROR: facts.yaml schema violation: {e}\n')
        return 1

    print(f'Rendering risk-assessment markdown for {args.gene} ({args.disease}) ...')
    markdown = render_risk_assessment(facts)

    output_path = out_dir / f'{args.gene}_risk_assessment_{args.disease}.md'

    # Safety: if the target file exists and was NOT produced by this
    # generator (no "Workflow:" stamp from our template), back it up
    # before overwriting. Prevents the v1.3.0 CDCP1 incident where a
    # hand-written markdown was silently overwritten.
    if output_path.exists():
        existing = output_path.read_text()
        is_generator_produced = (
            'risk_assessment_facts.yaml' in existing or
            'risk_assessment_schema.md' in existing
            # Future: stamp generator-produced files with a sentinel comment.
        )
        # Heuristic: if the existing file lacks the Executive Risk Summary
        # table OR has unique content (like "Key PMIDs:" — legacy format),
        # treat as hand-written and back up.
        looks_legacy = (
            'Key PMIDs' in existing or
            '## Executive Risk Summary' not in existing
        )
        if looks_legacy and not is_generator_produced:
            backup = output_path.with_suffix(output_path.suffix + '.bak')
            backup.write_text(existing)
            print(f'BACKED UP existing hand-written markdown to: {backup}')

    output_path.write_text(markdown)
    print(f'Wrote: {output_path}')
    print(f'Size: {len(markdown):,} chars / {markdown.count(chr(10))} lines')

    # Self-check: verify the rendered output passes the schema linter.
    if not args.skip_lint_check:
        print('Running self-check via lint_risk_assessment.py ...')
        result = lint_risk_md(output_path)
        if not result.passed:
            sys.stderr.write(
                'ERROR: rendered markdown failed schema lint. '
                'This is a template/renderer bug; please report.\n'
            )
            for line_no, msg in result.errors:
                prefix = f'  Line {line_no}: ' if line_no else '  '
                sys.stderr.write(f'{prefix}{msg}\n')
            return 2
        print('Self-check passed.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
