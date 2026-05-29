"""Layer 2 — Context builder.

Takes the dataclasses produced by Layer 1 parsers and assembles a flat
dict that the Jinja template can consume. Computes derived fields
(badge colors, modality routing, summary strings) so the template stays
declarative.

Single public entry point: `build_context()`.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .parsers import (
    IDASAssessment, PairwiseComparison, RiskAssessment,
    ScholarEvalResult, SubgroupRow,
)


# Disease-specific config (could move to configs/{disease}.yaml later;
# inlined here for now to keep the generator self-contained).
DISEASE_CONFIG = {
    'crc': {
        'full_name': 'Colorectal Cancer (CRC)',
        'abbreviation': 'CRC',
        'tcga_projects': 'TCGA-COAD/READ',
        'normal_tissue': 'TCGA Adjacent + GTEx Colon',
        'idas_priorities': [
            'Chemorefractory 3L+',
            'RAS Mutant Frontline',
            'RAS Mutant Refractory',
            'Resectable',
        ],
    },
    'nsclc': {
        'full_name': 'Non-Small Cell Lung Cancer (NSCLC)',
        'abbreviation': 'NSCLC',
        'tcga_projects': 'TCGA-LUAD/LUSC',
        'normal_tissue': 'TCGA Adjacent + GTEx Lung',
        'idas_priorities': [
            '2L Non-AGA',
            '2L EGFR Mutant (post-TKI)',
            '1L/2L KRAS Mutant',
        ],
    },
}


def build_context(
    *,
    gene: str,
    disease: str,
    risk: RiskAssessment,
    idas: IDASAssessment,
    suitability: list[SubgroupRow],
    comparisons: list[PairwiseComparison],
    scholar: ScholarEvalResult,
    modality: str | None = None,
    workflow_version: str = '1.2.0',
) -> dict[str, Any]:
    """Assemble the Jinja render context from parsed inputs.

    All inputs are dataclasses from Layer 1 parsers. Output is a flat dict
    keyed for direct template consumption — `{{ scholar.total_score }}`,
    `{{ idas.tox_summary }}`, `{{ recommendation.full_string }}`, etc.
    """
    disease_lower = disease.lower()
    if disease_lower not in DISEASE_CONFIG:
        raise ValueError(f"Unknown disease: {disease!r}. Expected one of {list(DISEASE_CONFIG)}")
    disease_cfg = DISEASE_CONFIG[disease_lower]

    return {
        'gene': gene,
        'today': date.today().isoformat(),
        'workflow_version': workflow_version,
        'disease': disease_cfg,
        'modality': _build_modality_context(modality, idas, risk),
        'recommendation': _build_recommendation_context(risk, scholar),
        'risk': _build_risk_context(risk),
        'idas': _build_idas_context(idas),
        'comparisons': _build_comparisons_context(comparisons, disease_lower),
        'scholar': _build_scholar_context(scholar),
        'suitability': _build_suitability_context(suitability),
        'key_findings': _build_key_findings(risk, idas, scholar, modality, suitability),
    }


# ----------------------------------------------------------------------------
# Sub-builders (one per template namespace)
# ----------------------------------------------------------------------------

def _build_modality_context(
    cli_modality: str | None,
    idas: IDASAssessment,
    risk: RiskAssessment,
) -> dict[str, Any]:
    """Resolve the modality display string + the registry-aware class.

    Precedence (most authoritative first):
      1. --modality CLI arg
      2. modality recorded in idas.yaml subgroup_analysis (Step 2 captured it)
      3. modality_candidates from the risk-assessment markdown
      4. fallback: 'Antibody / ADC' (the v1.1.0 default)
    """
    raw = (
        cli_modality
        or idas.modality
        or (', '.join(risk.modality_candidates) if risk.modality_candidates else None)
        or 'Antibody / ADC'
    )
    modality_class = idas.modality_class or 'antibody_naked'
    return {
        'raw': raw,
        'display_string': raw,
        'short': raw.split(',')[0].strip().split('(')[0].strip()[:30],
        'class_id': modality_class,
        'is_degrader': modality_class == 'degrader',
        'is_surface': modality_class in ('antibody_naked', 'adc', 'tce'),
    }


def _build_recommendation_context(
    risk: RiskAssessment,
    scholar: ScholarEvalResult,
) -> dict[str, Any]:
    """Compose the recommendation string + badge color.

    Source precedence:
      1. Hand-written recommendation phrase from risk-assessment markdown
         (analyst's editorial call — wins over deterministic ScholarEval
         when present, because it captures modality / safety judgement
         the ScholarEval engine doesn't yet model).
      2. Scholar engine's deterministic recommendation.
    """
    full = risk.recommendation or scholar.recommendation or 'TBD'
    rec_upper = full.upper()
    is_go = 'GO' in rec_upper and 'NO-GO' not in rec_upper
    is_conditional = 'CONDITIONAL' in rec_upper and not is_go
    is_no_go = 'NO-GO' in rec_upper

    if is_no_go:
        badge_color = 'RED'
    elif is_conditional:
        badge_color = 'AMBER'
    elif is_go:
        badge_color = 'GREEN'
    else:
        badge_color = 'GRAY'

    return {
        'full_string': full,
        'badge_color': badge_color,
        'is_go': is_go,
        'is_conditional': is_conditional,
        'is_no_go': is_no_go,
    }


def _build_risk_context(risk: RiskAssessment) -> dict[str, Any]:
    """Per-category risk rows, overall profile, strengths/risks/mitigations."""
    categories = []
    for cat_name in ['Biological', 'Druggability', 'Translational',
                      'Clinical', 'Safety', 'Commercial']:
        if cat_name not in risk.categories:
            categories.append({
                'name': cat_name, 'level': 'TBD', 'driver': 'Not assessed',
                'evidence': '—',
            })
            continue
        cat = risk.categories[cat_name]
        evidence = ', '.join(f'PMID: {p}' for p in cat.evidence_pmids[:2]) or '—'
        categories.append({
            'name': cat.name,
            'level': cat.level,
            'driver': cat.key_driver,
            'evidence': evidence,
        })

    return {
        'categories': categories,
        'overall_profile': risk.overall_risk_profile or 'TBD',
        'strengths': risk.strengths,
        'risks': risk.risks,
        'mitigations': [
            {'risk': r, 'level': l, 'strategy': s}
            for r, l, s in risk.mitigations
        ],
    }


def _build_idas_context(idas: IDASAssessment) -> dict[str, Any]:
    """iDAS whitespace alignment table + tox summary string."""
    rows = []
    for key, ws in idas.whitespaces.items():
        rows.append({
            'label': ws.label,
            'expression': f'{ws.expression_log2tpm:.2f}',
            'alignment': ws.alignment,
            'n_samples': ws.n_samples,
            'source': ws.source,
            # v1.2.0 dispatcher fields — None for legacy yaml.
            'tox_penalty': ws.tox_penalty,
            'adjusted_score': ws.adjusted_score,
            'recommendation': ws.recommendation or '—',
            'rule_applied': ws.rule_applied or '—',
            'toxicity_risk': ws.toxicity_risk or '—',
        })

    # Summary strings used in Exec Summary "Key Findings".
    n_strong = sum(1 for ws in idas.whitespaces.values() if ws.alignment == 'Strong')
    n_total = len(idas.whitespaces)
    if n_strong == n_total:
        alignment_summary = f'Strong across all {n_total} priority whitespaces'
    elif n_strong > 0:
        alignment_summary = f'Strong in {n_strong}/{n_total} priority whitespaces'
    else:
        alignment_summary = f'Limited alignment in {n_total} priority whitespaces'

    linear_fc = 2 ** abs(idas.on_target_tox_log2fc)
    direction = '↑' if idas.on_target_tox_log2fc > 0 else '↓' if idas.on_target_tox_log2fc < 0 else '='
    tox_summary = (
        f'{idas.on_target_tox_risk} risk '
        f'({linear_fc:.1f}× {direction} tumor vs adjacent)'
    )

    return {
        'rows': rows,
        'overall_alignment': idas.overall_alignment,
        'recommendation': idas.recommendation,
        'tox_risk': idas.on_target_tox_risk,
        'tox_log2fc': idas.on_target_tox_log2fc,
        'tox_summary': tox_summary,
        'alignment_summary': alignment_summary,
        'luad_log2fc': idas.luad_log2fc,
        'lusc_log2fc': idas.lusc_log2fc,
    }


def _build_comparisons_context(
    comparisons: list[PairwiseComparison], disease: str,
) -> dict[str, Any]:
    """Tumor vs Adjacent / GTEx pairwise rows for §3.2."""
    rows = []
    for c in comparisons:
        linear_fc = 2 ** abs(c.log2fc)
        direction = '↑' if c.log2fc > 0 else '↓' if c.log2fc < 0 else '='
        # Risk-level convention from §3.2 narrative:
        # LOW: >2× vs adjacent, MEDIUM: 1.5-2×, HIGH: <1.5×.
        if 'Adjacent' in c.normal_group:
            if linear_fc >= 2.0 and c.log2fc > 0:
                risk_level = 'LOW'
            elif linear_fc >= 1.5 and c.log2fc > 0:
                risk_level = 'MEDIUM'
            else:
                risk_level = 'HIGH'
        else:
            risk_level = '—'  # GTEx comparisons don't drive the risk level
        rows.append({
            'tumor_cohort': c.tumor_cohort,
            'normal_group': c.normal_group,
            'tumor_n': c.tumor_n,
            'normal_n': c.normal_n,
            'tumor_median': f'{c.tumor_median:.2f}',
            'normal_median': f'{c.normal_median:.2f}',
            'fold_change': f'{linear_fc:.1f}× {direction}',
            'risk_level': risk_level,
            'p_value': f'{c.p_adjusted:.2e}',
        })
    return {'rows': rows}


def _build_scholar_context(scholar: ScholarEvalResult) -> dict[str, Any]:
    """8-dimension table + total + audit metadata."""
    weights = {
        'differential_expression': 0.15, 'pathway_relevance': 0.15,
        'druggability': 0.15, 'genetic_validation': 0.10,
        'disease_association': 0.10, 'safety_profile': 0.15,
        'clinical_validation': 0.10, 'biomarker_potential': 0.10,
    }
    display_names = {
        'differential_expression': 'Differential Expression',
        'pathway_relevance': 'Pathway Relevance',
        'druggability': 'Druggability',
        'genetic_validation': 'Genetic Validation',
        'disease_association': 'Disease Association',
        'safety_profile': 'Safety Profile',
        'clinical_validation': 'Clinical Validation',
        'biomarker_potential': 'Biomarker Potential',
    }
    rows = []
    for key in weights:
        if key not in scholar.dimensions:
            continue
        dim = scholar.dimensions[key]
        rows.append({
            'name': display_names[key],
            'weight': f'{weights[key]:.2f}',
            'score': f'{dim.score}/5',
            'risk_level': dim.risk_level,
            'rationale': dim.rationale,
        })
    return {
        'rows': rows,
        'total_score': f'{scholar.total_score:.2f}',
        'assessment': scholar.assessment,
        'recommendation': scholar.recommendation,
        'high_risk_count': scholar.high_risk_count,
        'input_hash': scholar.input_hash,
    }


def _build_suitability_context(suitability: list[SubgroupRow]) -> dict[str, Any]:
    """Phase 1 / Phase 2 / Phase 3 row groups for §3.4."""
    by_cat: dict[str, list[dict[str, Any]]] = {
        'tcga_analysis': [],
        'molecular_subgroup': [],   # CRC alias
        'tempus_mutation': [],
        'ras_status': [],           # CRC alias
        'idas_whitespace': [],
    }
    for row in suitability:
        cell = {
            'subgroup': row.subgroup,
            'key_metric': row.key_metric,
            'score': f'{row.score}/5',
            'recommendation': row.recommendation,
            # Risk level derived from score (5-4 LOW, 3 MEDIUM, 2-1 HIGH).
            'risk_level': (
                'LOW' if row.score >= 4 else
                'MEDIUM' if row.score == 3 else 'HIGH'
            ),
        }
        if row.category in by_cat:
            by_cat[row.category].append(cell)

    return {
        'phase1': by_cat['tcga_analysis'] + by_cat['molecular_subgroup'],
        'phase2': by_cat['tempus_mutation'] + by_cat['ras_status'],
        'phase3': by_cat['idas_whitespace'],
    }


def _build_key_findings(
    risk: RiskAssessment,
    idas: IDASAssessment,
    scholar: ScholarEvalResult,
    modality: str | None,
    suitability: list[SubgroupRow],
) -> list[str]:
    """Bullet-list summary for "Key Findings at a Glance" in Exec Summary."""
    findings = []

    # Best populations (top 3 PRIORITY/GO subgroups).
    priority_or_go = [r for r in suitability
                       if r.recommendation in ('PRIORITY', 'GO')]
    priority_or_go.sort(key=lambda r: -r.score)
    if priority_or_go:
        labels = [r.subgroup for r in priority_or_go[:3]]
        findings.append(f'**Best populations**: {"; ".join(labels)}')

    # Caution / exclude.
    caution = [r for r in suitability
               if r.recommendation in ('CAUTION', 'EXCLUDE')]
    if caution:
        labels = [r.subgroup for r in caution[:3]]
        findings.append(f'**Caution populations**: {"; ".join(labels)}')

    return findings
