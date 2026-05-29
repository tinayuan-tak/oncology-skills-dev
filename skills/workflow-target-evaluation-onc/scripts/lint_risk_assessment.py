#!/usr/bin/env python3
"""Lint risk-assessment markdown against the schema.

Hard gate before the integrated-report generator runs. Catches the
"hand-written drift" failure mode (v1.0.0 / v1.1.0 / v1.2.0 retros).

Usage:
    pixi run python scripts/lint_risk_assessment.py PATH/TO/risk_assessment.md

Exit codes:
    0 — schema-compliant, downstream tools may consume the file
    1 — schema violations, fix before running the generator
    2 — file not found

See `reference/risk_assessment_schema.md` for the authoritative schema.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


REQUIRED_CATEGORIES = [
    'Biological', 'Druggability', 'Translational',
    'Clinical', 'Safety', 'Commercial',
]

# Recommendation tokens (any of these in a bolded phrase satisfies §6).
RECOMMENDATION_TOKENS = re.compile(
    r'\*\*((?:CONDITIONAL\s+NO-GO|GO|NO-GO|CONDITIONAL)[^*]*)\*\*',
    re.IGNORECASE,
)


@dataclass
class LintResult:
    path: Path
    errors: list[tuple[int, str]] = field(default_factory=list)   # (line_no, msg)
    warnings: list[tuple[int, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def add_error(self, line_no: int, msg: str) -> None:
        self.errors.append((line_no, msg))

    def add_warning(self, line_no: int, msg: str) -> None:
        self.warnings.append((line_no, msg))


def lint(path: Path) -> LintResult:
    if not path.exists():
        result = LintResult(path=path)
        result.add_error(0, f'File not found: {path}')
        return result

    content = path.read_text()
    lines = content.split('\n')
    result = LintResult(path=path)

    _check_header(lines, result)
    _check_strategic_alignment(lines, result)
    _check_executive_risk_summary(content, lines, result)
    _check_per_category_sections(content, result)
    _check_overall_risk_profile(content, result)
    _check_idas_alignment_table(content, lines, result)
    _check_risk_mitigation(content, result)
    _check_recommendation(content, result)

    return result


# ----------------------------------------------------------------------------
# Individual checks
# ----------------------------------------------------------------------------

def _check_header(lines: list[str], result: LintResult) -> None:
    if not lines or not lines[0].startswith('# '):
        result.add_error(1, 'Header: file must start with "# {GENE} Drug Target Risk Assessment — {Disease}"')
        return
    title = lines[0]
    if 'Risk Assessment' not in title:
        result.add_error(1, f'Header: title missing "Risk Assessment" — got {title!r}')

    required_meta = ['Date', 'Disease', 'Target', 'Modality candidates']
    found = {m: False for m in required_meta}
    for i, line in enumerate(lines[:30], start=1):
        for meta in required_meta:
            if line.startswith(f'**{meta}:**'):
                found[meta] = True
    for meta, ok in found.items():
        if not ok:
            result.add_error(2, f'Header: required metadata field "**{meta}:**" not found in first 30 lines')


def _check_strategic_alignment(lines: list[str], result: LintResult) -> None:
    found_section = False
    found_whitespace_line = False
    for i, line in enumerate(lines, start=1):
        if line.strip() == '## Strategic Alignment Assessment':
            found_section = True
        if '**Whitespace Alignment:**' in line:
            found_whitespace_line = True
    if not found_section:
        result.add_error(0, 'Required section "## Strategic Alignment Assessment" not found')
    if found_section and not found_whitespace_line:
        result.add_warning(0, 'Strategic Alignment Assessment: "**Whitespace Alignment:**" line recommended')


def _check_executive_risk_summary(content: str, lines: list[str], result: LintResult) -> None:
    section_match = re.search(
        r'^##\s+Executive Risk Summary[^\n]*\n(.*?)(?=^##\s|\Z)',
        content, re.DOTALL | re.MULTILINE,
    )
    if not section_match:
        result.add_error(
            0, 'Required section "## Executive Risk Summary" not found. '
               'See reference/risk_assessment_schema.md for the required table format.'
        )
        return

    body = section_match.group(1)
    section_line_no = _line_number_of(content, section_match.start())

    found_categories: set[str] = set()
    has_table_header = False
    for line in body.split('\n'):
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip().strip('*') for c in line.strip('|').split('|')]
        if len(cells) < 3:
            continue
        first = cells[0]
        if 'Risk Factor' in first or first.lower() in ('risk factor', 'risk category'):
            has_table_header = True
            continue
        # Skip separator lines.
        if all(set(c) <= {'-', ':', ' '} for c in cells if c):
            continue
        for cat in REQUIRED_CATEGORIES:
            if cat.lower() in first.lower():
                found_categories.add(cat)

    if not has_table_header:
        result.add_error(
            section_line_no,
            'Executive Risk Summary table header not found. '
            'Required columns: "| Risk Factor | Risk Level | Key Considerations |"'
        )

    missing = [c for c in REQUIRED_CATEGORIES if c not in found_categories]
    if missing:
        result.add_error(
            section_line_no,
            f'Executive Risk Summary missing required categories: {missing}. '
            f'All 6 categories must appear: {REQUIRED_CATEGORIES}'
        )


def _check_per_category_sections(content: str, result: LintResult) -> None:
    """Each of the 6 numbered category sections must exist."""
    for n, cat in enumerate(REQUIRED_CATEGORIES, start=1):
        # Allow "Commercial" or "Commercial / Competitive" naming variants.
        pattern = rf'^##\s+{n}\.\s+{re.escape(cat)}(?:\s*/\s*[A-Za-z]+)?\s+Risk Assessment'
        if not re.search(pattern, content, re.MULTILINE):
            result.add_error(
                0,
                f'Required per-category section "## {n}. {cat} Risk Assessment" not found'
            )


def _check_overall_risk_profile(content: str, result: LintResult) -> None:
    # Two acceptable phrasings.
    if not re.search(
        r'\*\*Overall(?: Target)? Risk Profile:?\s*\*?\*?\s*[A-Z][A-Z\-–—]*',
        content, re.IGNORECASE,
    ):
        result.add_error(
            0,
            'Required "**Overall Target Risk Profile: {LEVEL}**" statement not found '
            '(typically appears immediately after the Executive Risk Summary table)'
        )


def _check_idas_alignment_table(content: str, lines: list[str], result: LintResult) -> None:
    section_match = re.search(
        r'^##\s+iDAS(?:\s+Strategic)?(?:\s+Alignment)?(?:\s+Assessment)?[^\n]*\n(.*?)(?=^##\s|\Z)',
        content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    if not section_match:
        result.add_error(0, 'Required section "## iDAS Strategic Alignment Assessment" not found')
        return

    body = section_match.group(1)
    section_line_no = _line_number_of(content, section_match.start())

    has_table = False
    for line in body.split('\n'):
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) >= 2 and ('whitespace' in cells[0].lower() or 'priority' in cells[0].lower()):
            has_table = True
            break

    if not has_table:
        result.add_error(
            section_line_no,
            'iDAS Strategic Alignment: required Whitespace Alignment table not found. '
            'Expected columns: "| Priority Whitespace | Alignment | Rationale |"'
        )


def _check_risk_mitigation(content: str, result: LintResult) -> None:
    section_match = re.search(
        r'^##\s+Risk Mitigation(?:\s+Strategies)?[^\n]*\n(.*?)(?=^##\s|\Z)',
        content, re.DOTALL | re.MULTILINE,
    )
    if not section_match:
        result.add_error(
            0,
            'Required section "## Risk Mitigation Strategies" not found'
        )
        return

    body = section_match.group(1)
    section_line_no = _line_number_of(content, section_match.start())

    # Accept either table OR numbered list with **bold** items.
    has_table = any(
        line.strip().startswith('|') and len(line.split('|')) >= 4
        for line in body.split('\n')
    )
    has_numbered_list = bool(re.search(r'^\s*\d+\.\s+\*\*[^*]+\*\*', body, re.MULTILINE))
    if not (has_table or has_numbered_list):
        result.add_error(
            section_line_no,
            'Risk Mitigation Strategies section must contain either a markdown table '
            '("| Risk | Risk Level | Mitigation Strategy |") OR a numbered list '
            '("1. **Risk title** — strategy text").'
        )


def _check_recommendation(content: str, result: LintResult) -> None:
    section_match = re.search(
        r'^##\s+Recommendations?\s*$(.*?)(?=^##\s|\Z)',
        content, re.DOTALL | re.MULTILINE,
    )
    if not section_match:
        result.add_error(
            0,
            'Required section "## Recommendation" or "## Recommendations" not found'
        )
        return

    body = section_match.group(1)
    section_line_no = _line_number_of(content, section_match.start())

    if not RECOMMENDATION_TOKENS.search(body):
        result.add_error(
            section_line_no,
            'Recommendation section: bolded phrase containing GO/NO-GO/CONDITIONAL '
            'not found. Example: "### Overall: **GO — MEDIUM-HIGH PRIORITY**"'
        )


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _line_number_of(content: str, char_offset: int) -> int:
    return content.count('\n', 0, char_offset) + 1


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _format_results(result: LintResult) -> str:
    lines = []
    rel = result.path
    if result.passed and not result.warnings:
        lines.append(f'✓ {rel} — schema-compliant')
        return '\n'.join(lines)

    if result.errors:
        lines.append(f'✗ {rel}')
        for line_no, msg in result.errors:
            prefix = f'  Line {line_no}: ' if line_no else '  '
            lines.append(f'{prefix}{msg}')

    if result.warnings:
        if not result.errors:
            lines.append(f'✓ {rel} — schema-compliant (with warnings)')
        for line_no, msg in result.warnings:
            prefix = f'  Line {line_no} (warn): ' if line_no else '  (warn) '
            lines.append(f'{prefix}{msg}')

    if result.errors:
        lines.append('')
        lines.append(
            'Linting failed. Fix the input markdown before running the '
            'integrated-report generator.'
        )
        lines.append('See reference/risk_assessment_schema.md for the schema.')
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('path', type=Path, help='Path to risk-assessment markdown file')
    parser.add_argument('--quiet', action='store_true', help='Only print errors')
    args = parser.parse_args()

    result = lint(args.path)
    if not result.passed and any('not found' in msg for _, msg in result.errors if 'File not found' in msg):
        # File-not-found uses exit 2 per CLI convention.
        sys.stderr.write(_format_results(result) + '\n')
        return 2

    if not args.quiet or not result.passed:
        sys.stdout.write(_format_results(result) + '\n')
    return 0 if result.passed else 1


if __name__ == '__main__':
    sys.exit(main())
