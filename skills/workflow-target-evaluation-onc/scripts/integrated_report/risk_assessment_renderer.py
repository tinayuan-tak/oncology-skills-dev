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


# ----------------------------------------------------------------------------
# Canonical value sets — what `load_facts()` accepts after normalization.
# Adding a new accepted value here is the only place to do it; the
# validator and the renderer both consume these constants.
# See reference/risk_assessment_facts_schema.md for rationale.
# ----------------------------------------------------------------------------

CANONICAL_RISK_LEVELS = {
    'LOW', 'MEDIUM', 'HIGH', 'LOW-MEDIUM', 'MEDIUM-HIGH',
}

# Mitigation-level subset: compound levels not allowed for mitigations
# (rationale: a mitigation is for a specific identified risk; compound
# levels imply ambiguity that should be resolved before listing).
CANONICAL_MITIGATION_LEVELS = {'LOW', 'MEDIUM', 'HIGH'}

CANONICAL_RECOMMENDATION_LEVELS = {
    'GO', 'NO-GO', 'CONDITIONAL', 'CONDITIONAL NO-GO',
}

CANONICAL_RECOMMENDATION_PRIORITIES = {
    'HIGH', 'MEDIUM-HIGH', 'MEDIUM', 'LOW',
}

CANONICAL_IDAS_ALIGNMENTS = {'Strong', 'Moderate', 'Weak', 'None'}

CANONICAL_DISEASES = {'crc', 'nsclc'}

# Per-disease canonical iDAS whitespace labels.
CANONICAL_WHITESPACES = {
    'crc': {
        'Chemorefractory 3L+',
        'RAS Mutant Frontline',
        'RAS Mutant Refractory',
        'Resectable',
    },
    'nsclc': {
        '2L Non-AGA (IO-experienced)',
        '2L EGFR Mutant (post-TKI)',
        '1L/2L KRAS Mutant',
    },
}

# Top-level facts.yaml keys we recognize. Anything else is rejected as a
# typo guard. Add new keys here when extending the schema.
RECOGNIZED_TOP_LEVEL_KEYS = {
    'gene', 'disease', 'date',
    'target_aliases', 'modality_candidates', 'background',
    'risk_categories', 'overall_risk_profile',
    'idas_alignment', 'strengths', 'risks', 'mitigations',
    'recommendation',
}

# Recognized per-category keys. Some are category-specific structured
# fields that ScholarEval reads directly to avoid regex-on-prose scoring
# (added in v1.4.0). All structured fields are optional — legacy
# facts.yaml predates them.
RECOGNIZED_CATEGORY_KEYS = {
    # Common
    'level', 'key_driver', 'justification', 'evidence',
    # Clinical-only (optional)
    'highest_phase',
    # Druggability-only (optional)
    'has_approved_drug', 'has_clinical_compound', 'has_tool_compound',
    'has_structure', 'best_ic50_nm',
}

# Recognized per-evidence-entry keys.
RECOGNIZED_EVIDENCE_KEYS = {'claim', 'pmid', 'study_type'}

# Recognized per-mitigation keys.
RECOGNIZED_MITIGATION_KEYS = {'title', 'risk_level', 'strategy'}

# Recognized per-iDAS-alignment keys.
RECOGNIZED_IDAS_KEYS = {'whitespace', 'alignment', 'rationale'}

# Recognized recommendation keys.
RECOGNIZED_RECOMMENDATION_KEYS = {'level', 'priority', 'rationale'}


def _normalize_risk_level(value: Any) -> str:
    """Normalize a risk-level string: uppercase, ASCII hyphen, strip."""
    return str(value).strip().upper().replace('–', '-').replace('—', '-')


def _normalize_alignment(value: Any) -> str:
    """Normalize an iDAS alignment string: title-case, strip."""
    return str(value).strip().title()


def _normalize_pmid(value: Any) -> str:
    """Normalize a PMID: cast to string, strip, validate digits-only."""
    s = str(value).strip()
    if not s.isdigit() or not (6 <= len(s) <= 9):
        raise ValueError(
            f"pmid must be 6-9 digits as string; got {value!r}"
        )
    return s


def _check_unrecognized_keys(
    name: str, data: dict, recognized: set[str],
) -> None:
    """Raise ValueError if `data` has any keys outside `recognized`."""
    extras = set(data.keys()) - recognized
    if extras:
        raise ValueError(
            f"{name}: unrecognized key(s): {sorted(extras)}. "
            f"Recognized keys: {sorted(recognized)}"
        )


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

    Validation is strict (per v1.4.0): structural required-fields check,
    canonical-value enforcement on enums, type coercion for PMIDs,
    rejection of unrecognized keys (typo guard), per-disease validation
    of iDAS whitespace labels.

    Raises ValueError on any violation. Caller produces a user-facing
    error from the message.
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    # ------------------------------------------------------------------
    # Top-level structure
    # ------------------------------------------------------------------
    _check_unrecognized_keys('top-level', data, RECOGNIZED_TOP_LEVEL_KEYS)
    for required in ('gene', 'disease', 'date', 'risk_categories',
                      'recommendation', 'mitigations'):
        if required not in data:
            raise ValueError(f"facts file missing required key: {required!r}")

    # disease must be a known value.
    disease = str(data['disease']).strip().lower()
    if disease not in CANONICAL_DISEASES:
        raise ValueError(
            f"disease must be one of {sorted(CANONICAL_DISEASES)}; "
            f"got {data['disease']!r}"
        )

    # ------------------------------------------------------------------
    # Risk categories: all 6 present, each with canonical level
    # ------------------------------------------------------------------
    cats = data['risk_categories'] or {}
    missing = [name for name, _ in RISK_CATEGORIES_ORDER if name not in cats]
    if missing:
        raise ValueError(
            f"risk_categories missing entries: {missing}. "
            f"All 6 must be present: {[n for n, _ in RISK_CATEGORIES_ORDER]}"
        )
    extra_cats = set(cats.keys()) - {n for n, _ in RISK_CATEGORIES_ORDER}
    if extra_cats:
        raise ValueError(
            f"risk_categories has unrecognized entries: {sorted(extra_cats)}. "
            f"Only the 6 canonical categories are allowed."
        )
    for cat_name, _ in RISK_CATEGORIES_ORDER:
        cat = cats[cat_name]
        if not isinstance(cat, dict):
            raise ValueError(
                f"risk_categories.{cat_name} must be a dict; got {type(cat).__name__}"
            )
        _check_unrecognized_keys(
            f"risk_categories.{cat_name}", cat, RECOGNIZED_CATEGORY_KEYS,
        )
        for required_field in ('level', 'key_driver', 'justification'):
            if required_field not in cat:
                raise ValueError(
                    f"risk_categories.{cat_name} missing required field: {required_field!r}"
                )
        # Normalize + validate level.
        norm_level = _normalize_risk_level(cat['level'])
        if norm_level not in CANONICAL_RISK_LEVELS:
            raise ValueError(
                f"risk_categories.{cat_name}.level must be one of "
                f"{sorted(CANONICAL_RISK_LEVELS)}; got {cat['level']!r}"
            )
        cat['level'] = norm_level
        # Normalize + validate evidence entries.
        evidence = cat.get('evidence') or []
        if not isinstance(evidence, list):
            raise ValueError(
                f"risk_categories.{cat_name}.evidence must be a list"
            )
        for i, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                raise ValueError(
                    f"risk_categories.{cat_name}.evidence[{i}] must be a dict"
                )
            _check_unrecognized_keys(
                f"risk_categories.{cat_name}.evidence[{i}]",
                ev, RECOGNIZED_EVIDENCE_KEYS,
            )
            if 'pmid' in ev:
                ev['pmid'] = _normalize_pmid(ev['pmid'])

        # v1.4.0+ structured scoring fields: type-check when present,
        # but allow absence so legacy facts.yaml still validates.
        if cat_name == 'clinical' and 'highest_phase' in cat:
            phase = cat['highest_phase']
            if not isinstance(phase, int) or not (0 <= phase <= 4):
                raise ValueError(
                    f"risk_categories.clinical.highest_phase must be int "
                    f"in [0, 4]; got {phase!r}"
                )
        if cat_name == 'druggability':
            for bool_field in ('has_approved_drug', 'has_clinical_compound',
                               'has_tool_compound', 'has_structure'):
                if bool_field in cat and not isinstance(cat[bool_field], bool):
                    raise ValueError(
                        f"risk_categories.druggability.{bool_field} must be "
                        f"a bool; got {cat[bool_field]!r}"
                    )
            if 'best_ic50_nm' in cat:
                ic = cat['best_ic50_nm']
                if ic is not None and not isinstance(ic, (int, float)):
                    raise ValueError(
                        f"risk_categories.druggability.best_ic50_nm must "
                        f"be a number or null; got {ic!r}"
                    )

    # ------------------------------------------------------------------
    # Recommendation: canonical level + optional priority
    # ------------------------------------------------------------------
    rec = data['recommendation']
    if not isinstance(rec, dict):
        raise ValueError("recommendation must be a dict")
    _check_unrecognized_keys('recommendation', rec, RECOGNIZED_RECOMMENDATION_KEYS)
    if 'level' not in rec:
        raise ValueError("recommendation.level is required")
    rec_level = str(rec['level']).strip().upper()
    if rec_level not in CANONICAL_RECOMMENDATION_LEVELS:
        raise ValueError(
            f"recommendation.level must be one of "
            f"{sorted(CANONICAL_RECOMMENDATION_LEVELS)}; got {rec['level']!r}"
        )
    rec['level'] = rec_level
    if rec.get('priority'):
        priority = str(rec['priority']).strip().upper().replace('–', '-').replace('—', '-')
        if priority not in CANONICAL_RECOMMENDATION_PRIORITIES:
            raise ValueError(
                f"recommendation.priority must be one of "
                f"{sorted(CANONICAL_RECOMMENDATION_PRIORITIES)} or omitted; "
                f"got {rec['priority']!r}"
            )
        rec['priority'] = priority

    # ------------------------------------------------------------------
    # Mitigations: ≥1 entry, canonical risk_level, recognized keys
    # ------------------------------------------------------------------
    mitigations = data.get('mitigations') or []
    if not mitigations:
        raise ValueError("mitigations must contain at least one entry")
    for i, m in enumerate(mitigations):
        if not isinstance(m, dict):
            raise ValueError(f"mitigations[{i}] must be a dict")
        _check_unrecognized_keys(
            f"mitigations[{i}]", m, RECOGNIZED_MITIGATION_KEYS,
        )
        for required_field in ('title', 'risk_level', 'strategy'):
            if required_field not in m:
                raise ValueError(
                    f"mitigations[{i}] missing required field: {required_field!r}"
                )
        norm = _normalize_risk_level(m['risk_level'])
        if norm not in CANONICAL_MITIGATION_LEVELS:
            raise ValueError(
                f"mitigations[{i}].risk_level must be one of "
                f"{sorted(CANONICAL_MITIGATION_LEVELS)}; got {m['risk_level']!r}"
            )
        m['risk_level'] = norm

    # ------------------------------------------------------------------
    # iDAS alignment: per-disease canonical whitespace labels
    # ------------------------------------------------------------------
    idas_alignment = list(data.get('idas_alignment') or [])
    canonical_ws = CANONICAL_WHITESPACES.get(disease, set())
    for i, ws in enumerate(idas_alignment):
        if not isinstance(ws, dict):
            raise ValueError(f"idas_alignment[{i}] must be a dict")
        _check_unrecognized_keys(
            f"idas_alignment[{i}]", ws, RECOGNIZED_IDAS_KEYS,
        )
        for required_field in ('whitespace', 'alignment'):
            if required_field not in ws:
                raise ValueError(
                    f"idas_alignment[{i}] missing required field: {required_field!r}"
                )
        if canonical_ws and ws['whitespace'] not in canonical_ws:
            raise ValueError(
                f"idas_alignment[{i}].whitespace must be one of "
                f"{sorted(canonical_ws)} for disease={disease!r}; "
                f"got {ws['whitespace']!r}"
            )
        norm_align = _normalize_alignment(ws['alignment'])
        if norm_align not in CANONICAL_IDAS_ALIGNMENTS:
            raise ValueError(
                f"idas_alignment[{i}].alignment must be one of "
                f"{sorted(CANONICAL_IDAS_ALIGNMENTS)}; got {ws['alignment']!r}"
            )
        ws['alignment'] = norm_align

    # ------------------------------------------------------------------
    # Construct typed record
    # ------------------------------------------------------------------
    return RiskAssessmentFacts(
        gene=data['gene'],
        disease=disease,
        date=str(data['date']),
        target_aliases=data.get('target_aliases', ''),
        modality_candidates=list(data.get('modality_candidates') or []),
        background=str(data.get('background', '') or '').strip(),
        risk_categories=cats,
        idas_alignment=idas_alignment,
        strengths=list(data.get('strengths') or []),
        risks=list(data.get('risks') or []),
        mitigations=mitigations,
        recommendation=rec,
        overall_risk_profile=_normalize_risk_level(
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
        # trim_blocks=False so per-iteration newlines in for-loops are
        # preserved (so multi-item lists / multi-row tables don't
        # collapse onto one line). Cost: extra blank lines around tag
        # blocks; we collapse those in post-processing.
        trim_blocks=False,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_name)
    rendered = template.render(**build_render_context(facts))
    # Post-process: clean up cosmetic whitespace from trim_blocks=False.
    #   1. Collapse 3+ consecutive blank lines to 2 (single-line breaks
    #      between paragraphs/sections are preserved).
    #   2. Strip blank lines between adjacent markdown table rows
    #      (lines that both start with '|' should be contiguous).
    #   3. Strip blank lines between adjacent list items (lines that
    #      both start with '- ' or 'N. ' should be contiguous).
    #   4. Remove orphan separators (`---` immediately before another `---`).
    import re
    rendered = re.sub(r'\n{3,}', '\n\n', rendered)
    rendered = re.sub(r'(\|[^\n]*)\n\n(?=\|)', r'\1\n', rendered)
    rendered = re.sub(r'(- \[?[^\n]*)\n\n(?=- )', r'\1\n', rendered)
    rendered = re.sub(r'(\d+\.\s+[^\n]*)\n\n(?=\d+\.\s+)', r'\1\n', rendered)
    rendered = re.sub(r'\n---\s*\n+---', '\n---', rendered)
    # Strip leading blank lines (left over from Jinja {# comment #} block).
    rendered = rendered.lstrip('\n')
    return rendered
