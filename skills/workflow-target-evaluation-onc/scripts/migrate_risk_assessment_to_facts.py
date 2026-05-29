#!/usr/bin/env python3
"""One-time migration: hand-written risk_assessment_{disease}.md → facts.yaml.

For legacy genes whose Step 1 markdown was hand-written before v1.3.0.
Reuses the strict parser from integrated_report.parsers to extract
structured fields, then writes them out as facts.yaml in the schema
shape consumed by generate_risk_assessment.py.

Usage:
    pixi run python scripts/migrate_risk_assessment_to_facts.py \\
        --gene CDCP1 --disease nsclc \\
        --input  /path/to/CDCP1_risk_assessment_nsclc.md \\
        --output /path/to/CDCP1_risk_assessment_facts.yaml

What's migrated automatically:
    - Header metadata (gene, disease, target_aliases, modality_candidates,
      date) — extracted from header lines or inferred from filename
    - 6 risk categories: level + justification + PMIDs from per-category
      sections OR from the Executive Risk Summary table (whichever exists)
    - iDAS alignment table
    - Strengths / Risks lists (if present)
    - Mitigations table or numbered list
    - Recommendation phrase

What requires post-migration review:
    - `key_driver` per category (extracted as first sentence of
      justification; analyst should refine to a single-sentence summary)
    - `evidence[]` per category (one entry per PMID, with placeholder
      `claim` text — analyst should fill in the per-claim text)
    - `recommendation.rationale` (extracted from the Recommendation
      section body, may need trimming)

Run-once-per-legacy-gene: after migration, the facts.yaml is the
canonical input. Subsequent edits go to facts.yaml, not the markdown.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from integrated_report.parsers import parse_risk_assessment  # noqa: E402


CATEGORY_KEYS = [
    ('Biological', 'biological'),
    ('Druggability', 'druggability'),
    ('Translational', 'translational'),
    ('Clinical', 'clinical'),
    ('Safety', 'safety'),
    ('Commercial', 'commercial'),
]


def migrate(input_md: Path, gene: str, disease: str) -> dict[str, Any]:
    """Run the strict parser, then shape the result into facts.yaml form."""
    ra = parse_risk_assessment(input_md)
    raw = input_md.read_text()

    # ------------------------------------------------------------------
    # Header metadata
    # ------------------------------------------------------------------
    date_match = re.search(
        r'\*\*(?:Date|Generated)\*\*[:\s]*([0-9]{4}-[0-9]{2}-[0-9]{2})', raw,
    )
    date = date_match.group(1) if date_match else '2026-01-01'

    target_aliases = ''
    target_match = re.search(r'\*\*Target\*\*[:\s]*[^\(]*\(([^)]+)\)', raw)
    if target_match:
        target_aliases = target_match.group(1).strip()

    modality_candidates = ra.modality_candidates[:] if ra.modality_candidates else []

    # ------------------------------------------------------------------
    # Background — first paragraph of "## Background" (or "## Background Information")
    # ------------------------------------------------------------------
    bg_match = re.search(
        r'^##\s+Background(?:\s+Information)?\s*\n(.*?)(?=^##\s|\Z)',
        raw, re.DOTALL | re.MULTILINE,
    )
    background = ''
    if bg_match:
        background = bg_match.group(1).strip()
        # Trim to first 2 paragraphs to avoid runaway length.
        paragraphs = background.split('\n\n')
        background = '\n\n'.join(paragraphs[:2]).strip()

    # ------------------------------------------------------------------
    # Per-category: level + justification + PMIDs from each
    # "## N. <Category> Risk Assessment" section. Falls back to the
    # parser's Executive Risk Summary extraction if the per-section data
    # isn't there.
    # ------------------------------------------------------------------
    risk_categories: dict[str, dict[str, Any]] = {}
    for display_name, key in CATEGORY_KEYS:
        cat_data: dict[str, Any] = {}

        # Level — prefer Executive Risk Summary if available; else
        # per-section "Risk Level Assigned: [X] LEVEL".
        if display_name in ra.categories:
            cat_data['level'] = ra.categories[display_name].level
        else:
            sec_match = re.search(
                rf'##\s+\d+\.\s+{re.escape(display_name)}'
                rf'(?:\s*/\s*[A-Za-z]+)?\s+Risk Assessment(.*?)(?=^##\s|\Z)',
                raw, re.DOTALL | re.MULTILINE,
            )
            if sec_match:
                level_match = re.search(
                    r'Risk Level Assigned\*?\*?[:\s]*\**\s*\[?[xX]?\]?\s*\**\s*'
                    r'([A-Z][A-Z\-–—]*)',
                    sec_match.group(1),
                )
                cat_data['level'] = (
                    level_match.group(1).replace('–', '-').replace('—', '-')
                    if level_match else 'MEDIUM'
                )

        # Section body for justification + PMIDs.
        section_match = re.search(
            rf'##\s+\d+\.\s+{re.escape(display_name)}'
            rf'(?:\s*/\s*[A-Za-z]+)?\s+Risk Assessment(.*?)(?=^##\s|\Z)',
            raw, re.DOTALL | re.MULTILINE,
        )
        section_body = section_match.group(1) if section_match else ''

        # Justification — text after "**Justification:**".
        just_match = re.search(
            r'\*\*Justification:?\*\*[:\s]*([^\n]+(?:\n(?!\*\*|##|\Z)[^\n]+)*)',
            section_body,
        )
        if just_match:
            cat_data['justification'] = just_match.group(1).strip()
        else:
            # Fall back to Executive Risk Summary key_driver if present.
            cat_data['justification'] = (
                ra.categories[display_name].key_driver
                if display_name in ra.categories
                else 'Migration: justification not found in source markdown.'
            )

        # Key driver — first sentence of justification (capped at ~150 chars).
        first_sentence = re.split(
            r'(?<=[a-z0-9])\.\s', cat_data['justification'], maxsplit=1,
        )[0].rstrip('.').strip()
        if len(first_sentence) > 150:
            first_sentence = first_sentence[:147] + '...'
        cat_data['key_driver'] = first_sentence

        # Evidence — PMIDs from section body. One entry per PMID with
        # placeholder claim. Analyst fills in per-claim text post-migration.
        # Always sweep the per-section body: parser's evidence_pmids is
        # populated only when an Executive Risk Summary table exists,
        # but legacy markdowns (e.g. CDCP1) don't have that.
        pmids: list[str] = []
        if display_name in ra.categories:
            pmids.extend(ra.categories[display_name].evidence_pmids)
        if section_body:
            # "**Key PMIDs:** N, N, N" — common in CDCP1-era markdowns.
            keypmids_match = re.search(
                r'\*\*Key PMIDs?:?\*?\*?[:\s]*([0-9,\s]+)',
                section_body,
            )
            if keypmids_match:
                for p in re.findall(r'\d{6,9}', keypmids_match.group(1)):
                    if p not in pmids:
                        pmids.append(p)
            # Free-text "PMID: N" / "(PMID: N)" anywhere in section body.
            for p in re.findall(r'PMID:?\s*(\d{6,9})', section_body):
                if p not in pmids:
                    pmids.append(p)
            # Bare numeric IDs that look like PMIDs (heuristic — only if
            # explicitly under a "Key PMIDs" heading already covered above).

        if pmids:
            cat_data['evidence'] = [
                {
                    'claim': f'Evidence for {display_name.lower()} category (review post-migration)',
                    'pmid': p,
                    'study_type': '',
                }
                for p in pmids[:5]
            ]

        risk_categories[key] = cat_data

    # ------------------------------------------------------------------
    # iDAS alignment table
    # ------------------------------------------------------------------
    idas_alignment = []
    for ws_name, level in ra.idas_alignments.items():
        # Try to find the rationale from the Whitespace Alignment table.
        rationale = ''
        ws_row = re.search(
            rf'\|\s*{re.escape(ws_name)}\s*\|[^|]+\|\s*([^|\n]+)',
            raw,
        )
        if ws_row:
            rationale = ws_row.group(1).strip().rstrip('|').strip()
        idas_alignment.append({
            'whitespace': ws_name,
            'alignment': level,
            'rationale': rationale,
        })

    # ------------------------------------------------------------------
    # Strengths / Risks / Mitigations (from parser)
    # ------------------------------------------------------------------
    mitigations = []
    for risk, level, strategy in ra.mitigations:
        mitigations.append({
            'title': risk,
            'risk_level': level,
            'strategy': strategy,
        })

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------
    rec_full = ra.recommendation or 'GO'
    rec_level_match = re.match(
        r'(CONDITIONAL\s+NO-GO|NO-GO|CONDITIONAL|GO)', rec_full, re.IGNORECASE,
    )
    rec_level = (
        rec_level_match.group(1).upper().replace('CONDITIONAL', 'CONDITIONAL')
        if rec_level_match else 'GO'
    )
    rec_priority_match = re.search(
        r'((?:MEDIUM[- ]?HIGH|HIGH|MEDIUM|LOW)\s*PRIORITY|CONDITIONAL|PRIORITY)',
        rec_full, re.IGNORECASE,
    )
    rec_priority = ''
    if rec_priority_match:
        rec_priority = (
            rec_priority_match.group(1).upper().replace(' PRIORITY', '')
            .replace('PRIORITY', '').strip() or 'PRIORITY'
        )
    # Recommendation rationale — prose after the bolded phrase.
    rec_section = re.search(
        r'^##\s+Recommendations?\s*$(.*?)(?=^##\s|\Z)',
        raw, re.DOTALL | re.MULTILINE,
    )
    rec_rationale = ''
    if rec_section:
        body = rec_section.group(1)
        body = re.sub(
            r'\*\*((?:CONDITIONAL\s+NO-GO|GO|NO-GO|CONDITIONAL)[^*]*)\*\*', '',
            body, count=1, flags=re.IGNORECASE,
        )
        # First non-empty paragraph after stripping the rec phrase.
        for para in body.split('\n\n'):
            para = para.strip()
            if para and not para.startswith('#'):
                rec_rationale = para[:500].strip()
                break

    # ------------------------------------------------------------------
    # Assemble facts dict
    # ------------------------------------------------------------------
    facts: dict[str, Any] = {
        'gene': gene,
        'disease': disease,
        'date': date,
        'target_aliases': target_aliases,
        'modality_candidates': modality_candidates,
        'background': background,
        'risk_categories': risk_categories,
        'overall_risk_profile': ra.overall_risk_profile or 'MEDIUM',
        'idas_alignment': idas_alignment,
        'strengths': ra.strengths,
        'risks': ra.risks,
        'mitigations': mitigations or [{
            'title': 'Migration: no mitigations extracted',
            'risk_level': 'MEDIUM',
            'strategy': 'Add mitigations post-migration before regenerating markdown.',
        }],
        'recommendation': {
            'level': rec_level,
            'priority': rec_priority,
            'rationale': rec_rationale or rec_full,
        },
    }
    return facts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--gene', required=True)
    parser.add_argument('--disease', required=True, choices=['crc', 'nsclc'])
    parser.add_argument('--input', required=True, type=Path,
                        help='Path to existing hand-written {GENE}_risk_assessment_{disease}.md')
    parser.add_argument('--output', required=True, type=Path,
                        help='Path to write {GENE}_risk_assessment_facts.yaml')
    args = parser.parse_args()

    if not args.input.exists():
        sys.stderr.write(f'ERROR: input not found: {args.input}\n')
        return 1

    # Safety: back up the input markdown before any migration.
    # The migration is read-only on the input, but the downstream
    # generator (generate_risk_assessment.py) writes to the same
    # filename — so guarantee at least one preserved copy of the
    # original hand-written content.
    backup = args.input.with_suffix(args.input.suffix + '.bak')
    if not backup.exists():
        backup.write_text(args.input.read_text())
        print(f'BACKUP: {backup}')

    print(f'Migrating {args.input} → facts.yaml ...')
    facts = migrate(args.input, args.gene, args.disease)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        yaml.safe_dump(
            facts, f, default_flow_style=False, sort_keys=False,
            width=100, allow_unicode=True,
        )
    print(f'Wrote: {args.output}')

    n_evidence = sum(
        len(c.get('evidence') or []) for c in facts['risk_categories'].values()
    )
    print(
        f'Migrated: {len(facts["risk_categories"])} categories, '
        f'{n_evidence} evidence entries, '
        f'{len(facts["idas_alignment"])} iDAS rows, '
        f'{len(facts["mitigations"])} mitigations.'
    )
    print(
        '\nReview placeholder fields before regenerating markdown:\n'
        '  - per-category evidence[].claim (currently placeholder text)\n'
        '  - per-category key_driver (auto-extracted first sentence)\n'
        '  - recommendation.rationale (auto-extracted prose)\n'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
