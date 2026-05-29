"""Layer 2+3 — Risk-assessment markdown generator.

Reads {GENE}_risk_assessment_facts.yaml → renders schema-compliant
markdown via Jinja2 template at templates/risk_assessment.md.j2.

Output is guaranteed to pass lint_risk_assessment.py because every
required section is rendered from the structured facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


SKILL_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = SKILL_ROOT / "templates"
DEFAULT_TEMPLATE = "risk_assessment.md.j2"


# Disease full names. Mirrors DISEASE_CONFIG in context.py — kept
# inline here to avoid coupling Step 1 generator to the integrated-report
# context builder.
DISEASE_FULL_NAMES = {
    'crc': 'Colorectal Cancer (CRC)',
    'nsclc': 'Non-Small Cell Lung Cancer (NSCLC)',
}


# Canonical 6 categories — order matches reference/risk_assessment_schema.md
# and what lint_risk_assessment.py expects.
RISK_CATEGORIES_ORDER = [
    ('biological', 'Biological'),
    ('druggability', 'Druggability'),
    ('translational', 'Translational'),
    ('clinical', 'Clinical'),
    ('safety', 'Safety'),
    ('commercial', 'Commercial'),
]


@dataclass(frozen=True)
class RiskAssessmentFacts:
    """Validated facts dict, ready for rendering."""
    gene: str
    disease: str
    date: str
    target_aliases: str
    modality_candidates: list[str]
    background: str
    risk_categories: dict[str, dict[str, Any]]
    idas_alignment: list[dict[str, Any]]
    strengths: list[str]
    risks: list[str]
    mitigations: list[dict[str, Any]]
    recommendation: dict[str, Any]
    overall_risk_profile: str


# ----------------------------------------------------------------------------
# Loader + validator (Layer 1 for the Step 1 generator)
# ----------------------------------------------------------------------------

def load_facts(path: Path) -> RiskAssessmentFacts:
    """Load and validate {GENE}_risk_assessment_facts.yaml.

    Raises ValueError on schema violations — caller produces a
    user-facing error from the message.
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    # Required top-level keys.
    for required in ('gene', 'disease', 'date', 'risk_categories',
                      'recommendation', 'mitigations'):
        if required not in data:
            raise ValueError(f"facts file missing required key: {required!r}")

    # All 6 risk categories required.
    cats = data['risk_categories'] or {}
    missing = [name for name, _ in RISK_CATEGORIES_ORDER if name not in cats]
    if missing:
        raise ValueError(
            f"risk_categories missing entries: {missing}. "
            f"All 6 must be present: {[n for n, _ in RISK_CATEGORIES_ORDER]}"
        )
    for cat_name, _ in RISK_CATEGORIES_ORDER:
        cat = cats[cat_name]
        for required_field in ('level', 'key_driver', 'justification'):
            if required_field not in cat:
                raise ValueError(
                    f"risk_categories.{cat_name} missing required field: {required_field!r}"
                )

    # Recommendation needs at least a level.
    if 'level' not in (data.get('recommendation') or {}):
        raise ValueError("recommendation.level is required")

    # Mitigations: at least one row.
    mitigations = data.get('mitigations') or []
    if not mitigations:
        raise ValueError("mitigations must contain at least one entry")

    return RiskAssessmentFacts(
        gene=data['gene'],
        disease=str(data['disease']).lower(),
        date=str(data['date']),
        target_aliases=data.get('target_aliases', ''),
        modality_candidates=list(data.get('modality_candidates') or []),
        background=str(data.get('background', '') or '').strip(),
        risk_categories=cats,
        idas_alignment=list(data.get('idas_alignment') or []),
        strengths=list(data.get('strengths') or []),
        risks=list(data.get('risks') or []),
        mitigations=mitigations,
        recommendation=data['recommendation'],
        overall_risk_profile=str(
            data.get('overall_risk_profile')
            or _derive_overall_risk(cats)
        ),
    )


def _derive_overall_risk(categories: dict[str, dict[str, Any]]) -> str:
    """Derive overall risk profile from per-category levels.

    Rule (most-severe wins):
      - Any HIGH → HIGH
      - Any MEDIUM-HIGH (no HIGH) → MEDIUM-HIGH
      - Mix of MEDIUM and LOW → LOW-MEDIUM
      - Mostly MEDIUM → MEDIUM
      - All LOW → LOW
    """
    levels = [
        str(cat.get('level', '')).upper().replace('–', '-').replace('—', '-')
        for cat in categories.values()
    ]
    if any(lev == 'HIGH' for lev in levels):
        return 'HIGH'
    if any(lev == 'MEDIUM-HIGH' for lev in levels):
        return 'MEDIUM-HIGH'
    has_med = any('MEDIUM' in lev for lev in levels)
    has_low = any(lev == 'LOW' for lev in levels)
    if has_med and has_low:
        return 'LOW-MEDIUM'
    if has_med:
        return 'MEDIUM'
    return 'LOW'


# ----------------------------------------------------------------------------
# Render context builder (Layer 2)
# ----------------------------------------------------------------------------

def build_render_context(facts: RiskAssessmentFacts) -> dict[str, Any]:
    """Convert validated facts → flat dict the Jinja template consumes."""
    # Per-category context entries in canonical order.
    categories_ordered = []
    for key, display_name in RISK_CATEGORIES_ORDER:
        cat = facts.risk_categories[key]
        evidence = cat.get('evidence') or []
        pmids = [str(ev.get('pmid')) for ev in evidence if ev.get('pmid')]
        pmid_string = '; '.join(f'PMID: {p}' for p in pmids[:3]) if pmids else ''
        categories_ordered.append({
            'display_name': display_name,
            'level': str(cat['level']).upper().replace('–', '-').replace('—', '-'),
            'key_driver': str(cat['key_driver']).strip(),
            'justification': str(cat['justification']).strip(),
            'evidence': evidence,
            'pmid_string': pmid_string,
        })

    # Compose recommendation phrase: "GO — MEDIUM-HIGH PRIORITY"
    rec = facts.recommendation
    rec_level = str(rec['level']).upper()
    rec_priority = (rec.get('priority') or '').strip().upper()
    if rec_priority:
        recommendation_phrase = f"{rec_level} — {rec_priority} PRIORITY"
    else:
        recommendation_phrase = rec_level

    return {
        'gene': facts.gene,
        'disease': facts.disease,
        'disease_full_name': DISEASE_FULL_NAMES.get(
            facts.disease.lower(), facts.disease,
        ),
        'date': facts.date,
        'target_aliases': facts.target_aliases,
        'modality_candidates': facts.modality_candidates,
        'background': facts.background,
        'categories_ordered': categories_ordered,
        'overall_risk_profile': facts.overall_risk_profile,
        'idas_alignment': facts.idas_alignment,
        'strengths': facts.strengths,
        'risks': facts.risks,
        'mitigations': facts.mitigations,
        'recommendation': facts.recommendation,
        'recommendation_phrase': recommendation_phrase,
    }


# ----------------------------------------------------------------------------
# Renderer (Layer 3)
# ----------------------------------------------------------------------------

def render_risk_assessment(
    facts: RiskAssessmentFacts,
    template_name: str = DEFAULT_TEMPLATE,
) -> str:
    """Render risk-assessment markdown from validated facts."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_name)
    return template.render(**build_render_context(facts))
