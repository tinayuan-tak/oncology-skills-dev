#!/usr/bin/env python3
"""
Target Evaluation PDF Report Generator

Generates a publication-ready PDF report with high-resolution figures (300 DPI)
for oncology target evaluation across multiple indications (CRC, NSCLC).

Usage:
    python generate_target_report_pdf.py --gene TNFRSF12A --disease crc
    python generate_target_report_pdf.py --gene PCDH7 --disease nsclc --output-dir ./nsclc_results/PCDH7
"""

import argparse
import os
import sys
import re
from datetime import date
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.patches as mpatches
import matplotlib.image as mpimg
import numpy as np


# Skill name for output file naming
SKILL_NAME = 'workflow-target-evaluation-onc'


def get_output_filename(gene, content_type, ext):
    """Generate consistent output filename following naming convention.

    Pattern: {GENE}_{skill-name}_{content-type}.{ext}

    Args:
        gene: Gene symbol (e.g., 'TNFRSF12A')
        content_type: Type of content (e.g., 'report', 'risk', 'scholareval')
        ext: File extension without dot (e.g., 'png', 'md', 'pdf')

    Returns:
        Filename string (e.g., 'TNFRSF12A_workflow-target-evaluation-onc_report.pdf')
    """
    return f"{gene}_{SKILL_NAME}_{content_type}.{ext}"


def integrated_report_path(output_dir, gene):
    """Path to the Step 4 integrated target report markdown (ai-sci naming).

    Pattern: {GENE}_workflow-target-evaluation-onc_report.md
    """
    return os.path.join(output_dir, get_output_filename(gene, 'report', 'md'))


def get_bulk_rna_filename(gene, disease, content_type, ext):
    """Generate filename for bulk RNA skill outputs.

    Pattern: {GENE}_analysis-bulk-rna-{disease}_{content-type}.{ext}
    """
    skill = f"analysis-bulk-rna-{disease}"
    return f"{gene}_{skill}_{content_type}.{ext}"


# Disease-specific configurations
DISEASE_CONFIG = {
    'crc': {
        'full_name': 'Colorectal Cancer',
        'abbreviation': 'CRC',
        'tcga_projects': 'TCGA-COAD/READ',
        'normal_tissue': 'colon',
        'gtex_tissue': 'GTEx normal colon',
        'cohort_description': '''Samples were stratified into defined cohorts:
  • 2A: RAS-mutant MSS
  • 2B: RAS-WT MSS
  • 4: Early Stage I/II
  • 5: All MSS
  • 6: MSI-H''',
        'subtype_name': 'CMS',
        'subtype_description': 'Consensus Molecular Subtypes (CMS1-4)',
        'subtype_figure': None,  # CMS included in comprehensive figure panel F
        'default_output_dir': './crc_analysis_results',
        'disease_intro': '''Colorectal cancer remains a leading cause of cancer mortality worldwide, with liver
metastasis representing the primary determinant of patient survival. Despite advances in
chemotherapy, targeted agents, and immunotherapy, five-year survival rates for metastatic
CRC remain below 15%, underscoring the critical need for novel therapeutic targets.''',
    },
    'nsclc': {
        'full_name': 'Non-Small Cell Lung Cancer',
        'abbreviation': 'NSCLC',
        'tcga_projects': 'TCGA-LUAD/LUSC',
        'normal_tissue': 'lung',
        'gtex_tissue': 'GTEx normal lung',
        'cohort_description': '''Samples were stratified into defined cohorts:
  • LUAD: Lung adenocarcinoma
  • LUSC: Lung squamous cell carcinoma
  • Adjacent: Adjacent normal lung
  • GTEx: Normal lung tissue
  • CCLE: NSCLC cell lines''',
        'subtype_name': 'Histology/Biomarker',
        'subtype_description': 'LUAD vs LUSC histology and biomarker stratification (EGFR, KRAS, STK11, KEAP1)',
        'subtype_figure': None,  # NSCLC uses comprehensive figure only
        'default_output_dir': './nsclc_analysis_results',
        'disease_intro': '''Non-small cell lung cancer (NSCLC) accounts for approximately 85% of all lung cancers,
with ~2.2 million new cases annually worldwide. Despite advances in targeted therapy (EGFR,
ALK, KRAS G12C inhibitors) and immunotherapy, five-year survival rates for advanced NSCLC
remain below 25%, underscoring the critical need for novel therapeutic targets.''',
    }
}


def parse_pairwise_comparisons(output_dir, gene, disease='crc'):
    """Parse the pairwise comparisons CSV to get fold change vs adjacent normal."""
    import csv

    csv_path = os.path.join(output_dir, get_bulk_rna_filename(gene, disease, 'comparisons', 'csv'))
    if not os.path.exists(csv_path):
        return None, None

    fc_adj_normal = []
    fc_gtex = []

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            log2fc = float(row.get('Log2FC', 0))
            normal_group = row.get('Normal_Group', '')

            if 'Adjacent' in normal_group:
                fc_adj_normal.append(log2fc)
            elif 'GTEx' in normal_group:
                fc_gtex.append(log2fc)

    # Calculate average fold changes
    avg_adj = sum(fc_adj_normal) / len(fc_adj_normal) if fc_adj_normal else None
    avg_gtex = sum(fc_gtex) / len(fc_gtex) if fc_gtex else None

    return avg_adj, avg_gtex


def parse_integrated_report(report_path, output_dir=None, gene=None, disease='crc'):
    """Parse the integrated target report markdown file to extract key data."""
    data = {
        'date': date.today().isoformat(),
        'score': 'TBD',
        'risk_profile': 'TBD',
        'recommendation': 'GO',
        'assessment': 'TBD',
        'fold_change': 'TBD',
        'fold_change_adj': 'TBD',
        'fold_change_gtex': 'TBD',
        'risk_table': {},
        'strengths': [],
        'risks': [],
        'scholar_scores': {},
    }

    # Try to get fold change from pairwise comparisons CSV (more accurate)
    if output_dir and gene:
        avg_adj, avg_gtex = parse_pairwise_comparisons(output_dir, gene, disease)
        if avg_adj is not None:
            linear_fc_adj = 2 ** abs(avg_adj)
            direction = "↑" if avg_adj > 0 else "↓" if avg_adj < 0 else "="
            if abs(avg_adj) < 0.5:  # Less than 1.4x change
                data['fold_change'] = f"~1x (no change)"
                data['fold_change_adj'] = f"{avg_adj:.2f} ({direction})"
            else:
                data['fold_change'] = f"{linear_fc_adj:.1f}x {direction}"
                data['fold_change_adj'] = f"{avg_adj:.2f} (log2)"
        if avg_gtex is not None:
            linear_fc_gtex = 2 ** avg_gtex
            data['fold_change_gtex'] = f"{linear_fc_gtex:.1f}x vs GTEx"

    if not os.path.exists(report_path):
        return data

    with open(report_path, 'r') as f:
        content = f.read()

    # ==========================================================================
    # STANDARD FORMAT for Executive Summary (table-based):
    # | Metric | Value |
    # |--------|-------|
    # | **ScholarEval Score** | **4.25/5.0 (Strong)** |
    # | **Overall Risk Profile** | **LOW** |
    # | **Recommendation** | **GO** - Description |
    # ==========================================================================

    # Extract ScholarEval Score from table: | **ScholarEval Score** | **4.25/5.0 (Strong)** |
    score_match = re.search(r'\|\s*\*?\*?ScholarEval Score\*?\*?\s*\|\s*\*?\*?(\d+\.?\d*/5\.0)', content, re.IGNORECASE)
    if score_match:
        data['score'] = score_match.group(1)

    # Extract Overall Risk Profile from table: | **Overall Risk Profile** | **LOW** |
    # Allow hyphen and en/em dashes in compound levels like "LOW-MEDIUM" / "LOW–MEDIUM".
    risk_match = re.search(
        r'\|\s*\*?\*?Overall (?:Target )?Risk Profile\*?\*?\s*\|\s*\*?\*?([A-Z][A-Z\-–—]*)',
        content,
        re.IGNORECASE,
    )
    if risk_match:
        # Normalize en/em dash to ASCII hyphen for downstream colour-mapping lookups.
        data['risk_profile'] = (
            risk_match.group(1).replace('–', '-').replace('—', '-')
        )

    # Extract Recommendation from table: | **Recommendation** | **GO** - Description |
    # Capture the full cell verbatim (do NOT stop at the first dash — that
    # would truncate "NO-GO" or "GO — HIGH PRIORITY"). We strip markdown
    # emphasis, then classify below.
    rec_match = re.search(
        r'\|\s*\*?\*?Recommendation\*?\*?\s*\|\s*([^|\n]+)',
        content, re.IGNORECASE,
    )
    rec_full = rec_match.group(1).strip() if rec_match else ''
    rec_full = re.sub(r'\*+', '', rec_full).strip()
    rec_full = rec_full.upper()
    # Normalize: keep priority qualifiers like 'GO — MEDIUM PRIORITY';
    # collapse to canonical short form for display.
    if 'CONDITIONAL NO-GO' in rec_full:
        data['recommendation'] = 'CONDITIONAL NO-GO'
    elif 'CONDITIONAL' in rec_full:
        data['recommendation'] = 'CONDITIONAL'
    elif 'NO-GO' in rec_full:
        data['recommendation'] = 'NO-GO'
    elif 'GO' in rec_full:
        # Preserve priority qualifiers if present.
        priority_match = re.search(
            r'GO[^A-Z]*((?:MEDIUM[- ]?HIGH|HIGH|MEDIUM|LOW)\s*PRIORITY|PRIORITY)',
            rec_full,
        )
        if priority_match:
            qualifier = priority_match.group(1).strip()
            data['recommendation'] = f'GO — {qualifier}'
        else:
            data['recommendation'] = 'GO'
    elif rec_full:
        data['recommendation'] = rec_full[:30]

    # Extract Assessment rating from table: | **ScholarEval Score** | **4.25/5.0 (Strong)** |
    assessment_match = re.search(r'\|\s*\*?\*?ScholarEval Score\*?\*?\s*\|\s*\*?\*?[\d.]+/5\.0\s*\(([^)]+)\)', content, re.IGNORECASE)
    if assessment_match:
        data['assessment'] = assessment_match.group(1).strip()

    # Only use markdown fold change if CSV parsing failed
    if data['fold_change'] == 'TBD':
        fc_match = re.search(r'(\d+\.?\d*[-–]\d+\.?\d*)\s*fold', content, re.IGNORECASE)
        if fc_match:
            data['fold_change'] = fc_match.group(1) + 'x'

    # Extract risk table data
    risk_categories = ['Biological', 'Druggability', 'Translational', 'Clinical', 'Safety', 'Commercial']
    for cat in risk_categories:
        pattern = rf'\|\s*\*?\*?{cat}\*?\*?[^|]*\|\s*\*?\*?([A-Z-]+)\*?\*?\s*\|([^|]+)\|'
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            data['risk_table'][cat] = {
                'level': match.group(1).strip(),
                'considerations': match.group(2).strip()[:50]
            }

    # Extract strengths
    strength_section = re.search(r'(?:Key Strengths|### .*Strengths)[:\s]*\n((?:\d+\..*\n?)+)', content, re.IGNORECASE)
    if strength_section:
        strengths = re.findall(r'\d+\.\s*\*?\*?([^*\n]+)', strength_section.group(1))
        data['strengths'] = [s.strip() for s in strengths if s.strip()][:5]

    # Extract risks
    risk_section = re.search(r'(?:Key Risks|Risks/Challenges)[:\s]*\n((?:\d+\..*\n?)+)', content, re.IGNORECASE)
    if risk_section:
        risks = re.findall(r'\d+\.\s*\*?\*?([^*\n]+)', risk_section.group(1))
        data['risks'] = [r.strip() for r in risks if r.strip()][:5]

    # Extract Risk Mitigation Strategies
    mitigation_section = re.search(r'(?:Risk Mitigation Strategies|## 6\. Risk Mitigation)[^\n]*\n((?:.*\n)*?)(?=\n##|\n---|\Z)', content, re.IGNORECASE)
    if mitigation_section:
        # Parse table format: | Risk | Mitigation Strategy |
        mitigation_rows = re.findall(r'\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|', mitigation_section.group(1))
        mitigations = []
        for risk, strategy in mitigation_rows:
            if risk.strip() and not risk.strip().startswith('-') and risk.strip().lower() != 'risk':
                mitigations.append(f"{risk.strip()}: {strategy.strip()}")
        data['mitigations'] = mitigations[:6]
    else:
        data['mitigations'] = []

    # Extract Recommendations section
    rec_section = re.search(r'(?:Recommended Development Path|### Recommended)[^\n]*\n((?:.*\n)*?)(?=\n###|\n##|\n---|\Z)', content, re.IGNORECASE)
    if rec_section:
        # Parse table format or bullet points
        rec_rows = re.findall(r'\|\s*\*?\*?([^|*]+)\*?\*?\s*\|\s*([^|]+)\s*\|', rec_section.group(1))
        recommendations = []
        for phase, activities in rec_rows:
            if phase.strip() and not phase.strip().startswith('-') and phase.strip().lower() != 'phase':
                recommendations.append(f"{phase.strip()}: {activities.strip()[:60]}")
        data['recommendations_list'] = recommendations[:5]
    else:
        data['recommendations_list'] = []

    # Extract Scholar scores from table
    # Standard format: | Dimension | Weight | Score | Rationale |
    # Example: | Differential Expression | 0.15 | 4/5 | Evidence text |
    scholar_pattern = r'\|\s*(Differential Expression|Pathway Relevance|Druggability|Genetic Validation|Disease Association|Safety Profile|Clinical Validation|Biomarker Potential)\s*\|\s*[\d.]+\s*\|\s*(\d)/5'
    scholar_matches = re.findall(scholar_pattern, content, re.IGNORECASE)
    for dim, score in scholar_matches:
        data['scholar_scores'][dim.strip()] = int(score)

    return data


def create_risk_assessment_figure(gene, output_dir, report_data=None):
    """Create the 6-category risk assessment visualization figure."""
    fig, ax1 = plt.subplots(figsize=(10, 7))

    categories = ['Biological', 'Druggability', 'Translational', 'Clinical', 'Safety', 'Commercial']

    risk_levels = []
    risk_labels = []
    for cat in categories:
        if report_data and cat in report_data.get('risk_table', {}):
            level_str = report_data['risk_table'][cat].get('level', 'MEDIUM').upper()
            risk_labels.append(level_str)
            if 'LOW' in level_str and 'MEDIUM' not in level_str:
                risk_levels.append(1)
            elif 'HIGH' in level_str:
                risk_levels.append(3)
            else:
                risk_levels.append(2)
        else:
            risk_levels.append(2)
            risk_labels.append('MEDIUM')

    colors = ['#2ecc71' if r==1 else '#f39c12' if r==2 else '#e74c3c' for r in risk_levels]

    y_pos = np.arange(len(categories))
    bars = ax1.barh(y_pos, risk_levels, color=colors, edgecolor='black', linewidth=1.5, height=0.6)

    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(categories, fontsize=14, fontweight='bold')
    ax1.set_xlim(0, 3.5)
    ax1.set_xticks([1, 2, 3])
    ax1.set_xticklabels(['LOW', 'MEDIUM', 'HIGH'], fontsize=12)
    ax1.set_xlabel('Risk Level', fontsize=14, fontweight='bold')

    overall_risk = report_data.get('risk_profile', 'TBD') if report_data else 'TBD'
    ax1.set_title(f'6-Category Risk Assessment: {gene}\nOverall Risk Profile: {overall_risk}',
                  fontsize=16, fontweight='bold', pad=15)

    for i, (bar, label) in enumerate(zip(bars, risk_labels)):
        ax1.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                 label, va='center', fontsize=12, fontweight='bold', color=colors[i])

    ax1.axvline(x=1, color='#2ecc71', linestyle='--', alpha=0.3, linewidth=2)
    ax1.axvline(x=2, color='#f39c12', linestyle='--', alpha=0.3, linewidth=2)
    ax1.axvline(x=3, color='#e74c3c', linestyle='--', alpha=0.3, linewidth=2)

    low_patch = mpatches.Patch(color='#2ecc71', label='Low Risk')
    med_patch = mpatches.Patch(color='#f39c12', label='Medium Risk')
    high_patch = mpatches.Patch(color='#e74c3c', label='High Risk')
    ax1.legend(handles=[low_patch, med_patch, high_patch], loc='lower right', fontsize=11)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)

    plt.tight_layout()
    output_path = os.path.join(output_dir, get_output_filename(gene, 'risk', 'png'))
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f"  Created: {gene}_risk_assessment_figure.png")
    return output_path


def create_scholar_eval_figure(gene, output_dir, report_data=None):
    """Create the ScholarEval target scoring visualization figure."""
    fig, ax = plt.subplots(figsize=(12, 7))

    dimensions = ['Differential\nExpression', 'Pathway\nRelevance', 'Druggability',
                  'Genetic\nValidation', 'Disease\nAssociation', 'Safety\nProfile',
                  'Clinical\nValidation', 'Biomarker\nPotential']
    dim_keys = ['Differential Expression', 'Pathway Relevance', 'Druggability',
                'Genetic Validation', 'Disease Association', 'Safety Profile',
                'Clinical Validation', 'Biomarker Potential']

    if report_data and report_data.get('scholar_scores'):
        scores = [report_data['scholar_scores'].get(k, 3) for k in dim_keys]
    else:
        scores = [4, 4, 4, 3, 4, 3, 3, 4]

    score_colors = ['#27ae60' if s >= 4 else '#f39c12' if s >= 3 else '#e74c3c' for s in scores]

    x_pos = np.arange(len(dimensions))
    bars = ax.bar(x_pos, scores, color=score_colors, edgecolor='black', linewidth=1.5, width=0.7)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(dimensions, fontsize=11, rotation=45, ha='right')
    ax.set_ylim(0, 5.5)
    ax.set_ylabel('Score (1-5)', fontsize=14, fontweight='bold')

    overall_score = report_data.get('score', '?/5.0') if report_data else '?/5.0'
    assessment = report_data.get('assessment', '') if report_data else ''
    ax.set_title(f'ScholarEval Target Scoring: {gene}\nOverall Score: {overall_score} ({assessment})',
                 fontsize=16, fontweight='bold', pad=15)

    for bar, score in zip(bars, scores):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f'{score}/5', ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax.axhline(y=4, color='#27ae60', linestyle='--', alpha=0.5, linewidth=1.5, label='Strong (≥4)')
    ax.axhline(y=3, color='#f39c12', linestyle='--', alpha=0.5, linewidth=1.5, label='Moderate (≥3)')
    ax.axhline(y=2, color='#e74c3c', linestyle='--', alpha=0.5, linewidth=1.5, label='Weak (<3)')

    strong_patch = mpatches.Patch(color='#27ae60', label='Strong (≥4)')
    mod_patch = mpatches.Patch(color='#f39c12', label='Moderate (3)')
    weak_patch = mpatches.Patch(color='#e74c3c', label='Weak (≤2)')
    # Place legend below the chart in a horizontal row so it never
    # overlaps the rightmost bar (Biomarker Potential at score 5/5).
    ax.legend(handles=[strong_patch, mod_patch, weak_patch],
              loc='upper center', bbox_to_anchor=(0.5, -0.30),
              ncol=3, fontsize=10, frameon=False)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    output_path = os.path.join(output_dir, get_output_filename(gene, 'scholareval', 'png'))
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f"  Created: {gene}_scholar_eval_figure.png")
    return output_path


def text_page(pdf, title, content, title_size=20):
    """Create a text page."""
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis('off')
    ax.text(0.5, 0.96, title, fontsize=title_size, fontweight='bold', ha='center',
            transform=ax.transAxes, color='#2c3e50')
    ax.text(0.05, 0.90, content, fontsize=9.5, ha='left', va='top', transform=ax.transAxes,
            family='monospace', linespacing=1.4, wrap=True)
    pdf.savefig(fig, dpi=300, bbox_inches='tight')
    plt.close(fig)


def _read_risk_assessment_markdown(output_dir, gene, disease):
    """Read the Step 1 risk assessment markdown if it exists."""
    candidates = [
        os.path.join(output_dir, f"{gene}_risk_assessment_{disease}.md"),
        os.path.join(output_dir, f"{gene}_risk_assessment.md"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, 'r') as fh:
                return fh.read(), path
    return None, None


_RISK_CATEGORIES = ['Biological', 'Druggability', 'Translational',
                    'Clinical', 'Safety', 'Commercial']


def _extract_risk_category_summary(content, category):
    """Pull risk level, justification, and PMIDs for one of the 6 categories.

    Returns dict with keys: level (str), justification (str), pmids (list[str]).
    """
    section_match = re.search(
        rf'##\s*\d+\.\s*{category}.*?(?=^##\s|\Z)',
        content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    if not section_match:
        return {'level': 'TBD', 'justification': 'Section not found', 'pmids': []}
    body = section_match.group(0)

    level_match = re.search(
        r'Risk Level Assigned:\*?\*?\s*\[?x?\]?\s*\*?\*?(LOW|MEDIUM|HIGH)',
        body, re.IGNORECASE,
    )
    level = level_match.group(1).upper() if level_match else 'TBD'

    just_match = re.search(r'Justification:\*?\*?\s*([^\n]+(?:\n[^\n#]+)*)', body)
    justification = just_match.group(1).strip() if just_match else ''
    # Strip remaining bold markers and collapse whitespace.
    justification = re.sub(r'\*\*([^*]+)\*\*', r'\1', justification)
    justification = re.sub(r'\s+', ' ', justification)

    pmids = sorted(set(re.findall(r'PMID:\s*(\d+)', body)))

    return {'level': level, 'justification': justification, 'pmids': pmids}


def append_risk_assessment_pages(pdf, output_dir, gene, disease):
    """Append a structured 6-category risk-assessment summary to the PDF.

    Renders 3 category boxes per page (2 pages total) with color-coded
    risk-level badges, justification text, and supporting PMIDs.
    """
    raw, path = _read_risk_assessment_markdown(output_dir, gene, disease)
    if raw is None:
        print(f"  Risk Assessment: not found, skipping ({gene}_risk_assessment_{disease}.md)")
        return 0

    summaries = [
        (cat, _extract_risk_category_summary(raw, cat))
        for cat in _RISK_CATEGORIES
    ]

    level_colors = {
        'LOW': ('#27ae60', '#e8f5e9'),       # text, fill
        'MEDIUM': ('#f39c12', '#fff8e1'),
        'HIGH': ('#e74c3c', '#ffebee'),
        'TBD': ('#7f8c8d', '#f5f5f5'),
    }

    import textwrap
    pages_added = 0
    for page_idx in range(2):
        page_cats = summaries[page_idx * 3: page_idx * 3 + 3]
        if not page_cats:
            continue
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis('off')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

        title = ('Risk Assessment Summary (Step 1) — Page 1 of 2'
                 if page_idx == 0
                 else 'Risk Assessment Summary (Step 1) — Page 2 of 2')
        ax.text(0.5, 0.965, title, fontsize=15, fontweight='bold',
                ha='center', transform=ax.transAxes, color='#2c3e50')
        if page_idx == 0:
            ax.text(0.5, 0.94,
                    f'{gene} — Six-category literature-derived risk evaluation',
                    fontsize=10, ha='center', transform=ax.transAxes, color='#666')

        # Three boxes per page, vertical layout.
        box_top = 0.91 if page_idx == 0 else 0.94
        box_height = 0.28
        gap = 0.015
        for i, (cat, info) in enumerate(page_cats):
            top = box_top - i * (box_height + gap)
            bottom = top - box_height
            text_color, fill_color = level_colors.get(info['level'], level_colors['TBD'])

            # Background box.
            box = mpatches.FancyBboxPatch(
                (0.04, bottom), 0.92, box_height,
                boxstyle='round,pad=0.005,rounding_size=0.012',
                facecolor=fill_color, edgecolor=text_color, linewidth=1.5,
                transform=ax.transAxes,
            )
            ax.add_patch(box)

            # Category title.
            ax.text(0.06, top - 0.025, f'{cat} Risk',
                    fontsize=13, fontweight='bold',
                    transform=ax.transAxes, color='#2c3e50')

            # Risk-level badge (top-right of box).
            badge_x, badge_y = 0.78, top - 0.04
            badge = mpatches.FancyBboxPatch(
                (badge_x, badge_y), 0.16, 0.035,
                boxstyle='round,pad=0.005,rounding_size=0.012',
                facecolor=text_color, edgecolor='none',
                transform=ax.transAxes,
            )
            ax.add_patch(badge)
            ax.text(badge_x + 0.08, badge_y + 0.018, info['level'],
                    fontsize=11, fontweight='bold', ha='center', va='center',
                    transform=ax.transAxes, color='white')

            # Justification — wrapped to fit the box width. width=88 chars
            # at 9pt fits inside the 0.92-wide box without right-edge clipping.
            just_lines = textwrap.wrap(info['justification'], width=88)[:8]
            y = top - 0.07
            for line in just_lines:
                ax.text(0.06, y, line, fontsize=9,
                        transform=ax.transAxes, color='#2c3e50', va='top')
                y -= 0.022

            # PMIDs footer (truncate to 6 to keep line readable).
            if info['pmids']:
                pmid_str = 'Key PMIDs: ' + ', '.join(info['pmids'][:6])
                if len(info['pmids']) > 6:
                    pmid_str += f' (+{len(info["pmids"]) - 6} more)'
                ax.text(0.06, bottom + 0.012, pmid_str,
                        fontsize=8.5, fontstyle='italic',
                        transform=ax.transAxes, color='#666', va='bottom')

        pdf.savefig(fig, dpi=300, bbox_inches='tight')
        plt.close(fig)
        pages_added += 1

    print(f"  Risk Assessment: {pages_added} structured summary pages "
          f"from {os.path.basename(path)}")
    return pages_added


def add_high_res_figure(pdf, img_path, title, caption):
    """Add a high-resolution figure page."""
    if os.path.exists(img_path):
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(0.5, 0.96, title, fontsize=14, fontweight='bold', ha='center', color='#2c3e50')
        ax = fig.add_axes([0.05, 0.12, 0.9, 0.80])
        img = mpimg.imread(img_path)
        ax.imshow(img, interpolation='lanczos', aspect='equal')
        ax.axis('off')
        fig.text(0.5, 0.05, caption, ha='center', fontsize=9, style='italic', wrap=True)
        pdf.savefig(fig, dpi=300, bbox_inches='tight')
        plt.close(fig)
        return True
    return False


_RISK_LEVEL_FILL = {
    'LOW': '#e8f5e9',
    'MEDIUM': '#fff8e1',
    'HIGH': '#ffebee',
    'STRONG': '#e8f5e9',
    'WEAK': '#ffebee',
    'MODERATE': '#fff8e1',
    'PRIORITY': '#e8f5e9',
    'GO': '#e8f5e9',
    'INCLUDE': '#e8f5e9',
    'CONDITIONAL': '#fff8e1',
    'NEUTRAL': '#fff8e1',
    'CAUTION': '#ffebee',
    'EXCLUDE': '#ffebee',
    'NO-GO': '#ffebee',
}
_RISK_LEVEL_TEXT = {
    'LOW': '#1b5e20',
    'MEDIUM': '#e65100',
    'HIGH': '#b71c1c',
    'STRONG': '#1b5e20',
    'WEAK': '#b71c1c',
    'MODERATE': '#e65100',
    'PRIORITY': '#1b5e20',
    'GO': '#1b5e20',
    'INCLUDE': '#1b5e20',
    'CONDITIONAL': '#e65100',
    'NEUTRAL': '#e65100',
    'CAUTION': '#b71c1c',
    'EXCLUDE': '#b71c1c',
    'NO-GO': '#b71c1c',
}


def _wrap_cell(text, width):
    """Wrap a cell value into multi-line text, returning a single string with \n.

    Character-budget-based wrapping. Used as a quick fallback only; the
    pixel-aware wrapper (_pixel_aware_wrap) is preferred because it
    measures actual rendered widths and avoids overflow even with bold or
    wide-glyph text.
    """
    import textwrap
    if text is None:
        return ''
    raw = str(text).strip()
    if not raw:
        return ''
    lines = []
    for paragraph in raw.split('\n'):
        if not paragraph.strip():
            continue
        max_token_len = max((len(tok) for tok in paragraph.split()), default=0)
        wrapped = textwrap.wrap(
            paragraph, width=width,
            break_long_words=(max_token_len > width),
            break_on_hyphens=True,
        ) or ['']
        lines.extend(wrapped)
    return '\n'.join(lines)


def _measure_text_width_inches(text, fontsize, fontweight, fig):
    """Return the rendered width of `text` in inches.

    Uses matplotlib's get_window_extent against the figure's renderer to
    measure actual glyph widths (not character counts). The figure must
    have an active renderer (call after fig.canvas.draw() or pass a fig
    that's been rendered once).
    """
    if not text:
        return 0.0
    try:
        renderer = fig.canvas.get_renderer()
    except AttributeError:
        # Some backends (e.g. agg in headless mode before draw) need a draw.
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
    # Place text invisibly off-canvas to measure it.
    txt = fig.text(-10, -10, text, fontsize=fontsize, fontweight=fontweight)
    bbox = txt.get_window_extent(renderer=renderer)
    txt.remove()
    # window_extent is in display pixels; convert to inches via fig dpi.
    return bbox.width / fig.dpi


def _pixel_aware_wrap(text, cell_width_inches, fontsize, fontweight, fig):
    """Wrap `text` so each line's rendered width fits within cell_width_inches.

    Greedy word-by-word fitting: build lines by adding words one at a time,
    rolling back to the previous line break when the line's measured width
    exceeds the cell width. Breaks long tokens character-by-character only
    when a single token alone exceeds the cell width (rare; e.g. extremely
    long PMID lists or URLs).

    Returns a single string with embedded \n. Empty input returns ''.
    Multiple paragraphs (separated by \n) are wrapped independently and
    rejoined with single newlines.
    """
    if text is None:
        return ''
    raw = str(text).strip()
    if not raw:
        return ''
    # Reserve ~0.15 inches of horizontal padding (one side of the cell)
    # so wrapped text stays inside the cell after savefig(bbox_inches=
    # 'tight') and downstream rasterization slightly rescale the figure.
    # 0.15 in ≈ 1 char at 9pt — small enough not to over-shrink narrow
    # columns ("MEDIUM"), large enough to absorb the rendering pipeline's
    # geometric drift.
    available = max(0.15, cell_width_inches - 0.15)

    def fits(s):
        return _measure_text_width_inches(s, fontsize, fontweight, fig) <= available

    def break_long_token(token):
        """Split a single oversized token at character boundaries that fit."""
        chunks = []
        current = ''
        for ch in token:
            candidate = current + ch
            if fits(candidate):
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = ch
        if current:
            chunks.append(current)
        return chunks

    output_lines = []
    for paragraph in raw.split('\n'):
        if not paragraph.strip():
            continue
        words = paragraph.split()
        line = ''
        for word in words:
            # If even a single word doesn't fit alone, character-break it.
            if not fits(word):
                if line:
                    output_lines.append(line)
                    line = ''
                output_lines.extend(break_long_token(word))
                continue
            candidate = (line + ' ' + word) if line else word
            if fits(candidate):
                line = candidate
            else:
                if line:
                    output_lines.append(line)
                line = word
        if line:
            output_lines.append(line)
    return '\n'.join(output_lines) if output_lines else ''


def render_table_page(pdf, title, headers, rows, col_widths=None,
                      color_col=None, subtitle=None, footer=None):
    """Render a styled table on one or more PDF pages, paginating as needed.

    Builds the table manually with FancyBboxPatch cells and ax.text per cell
    so each row's height matches its actual wrapped content. Avoids the
    matplotlib ax.table() clipping bug where multi-line cells overflow into
    the next row's visual space.

    Args:
        pdf: matplotlib PdfPages object
        title: page title (string, displayed at top)
        headers: list of column header strings
        rows: list of row tuples (each same length as headers)
        col_widths: optional list of relative widths summing to 1.0;
            defaults to equal widths
        color_col: optional column index whose cell value selects a row
            background color via _RISK_LEVEL_FILL (e.g. LOW/MEDIUM/HIGH).
        subtitle: optional one-line subtitle below the title
        footer: optional one-line footer
    """
    n_cols = len(headers)
    if col_widths is None:
        col_widths = [1.0 / n_cols] * n_cols
    assert len(col_widths) == n_cols, "col_widths must match headers length"

    # Layout constants (in axes fraction). Need these before pixel-aware
    # wrapping so we can compute each column's pixel width.
    table_left = 0.04
    table_right = 0.96
    table_width = table_right - table_left
    body_fontsize = 8
    header_fontsize = 8.5
    line_height = 0.017  # vertical space per text line at 8pt
    cell_v_pad = 0.008
    cell_h_pad = 0.008
    header_color = '#1B365D'
    grid_color = '#cccccc'

    # Pixel-perfect column edges (axes fraction).
    col_edges = [table_left]
    for w in col_widths:
        col_edges.append(col_edges[-1] + w * table_width)

    # Conservative char-based wrapping. Empirically tuned to keep wrapped
    # text inside cell boundaries even with bold glyphs. Char budget is
    # ~13 chars per inch at 8pt body text (matplotlib's default sans-serif
    # measures ~12-14 chars/inch depending on the chars), with one char
    # per side reserved for cell padding.
    page_w_in = 8.5
    chars_per_inch = 13
    col_widths_in = [w * table_width * page_w_in for w in col_widths]
    per_col_body_chars = [
        max(6, int((w_in - 0.15) * chars_per_inch))
        for w_in in col_widths_in
    ]
    # Headers use slightly bigger bold font, so allocate ~10% fewer chars.
    per_col_header_chars = [
        max(5, int((w_in - 0.15) * chars_per_inch * 0.90))
        for w_in in col_widths_in
    ]
    wrapped_rows = [
        [_wrap_cell(cell, per_col_body_chars[i]) for i, cell in enumerate(row)]
        for row in rows
    ]
    wrapped_headers = [
        _wrap_cell(h, per_col_header_chars[i])
        for i, h in enumerate(headers)
    ]

    def row_block_height(row_lines):
        """Required vertical height for a row given each cell's line count."""
        max_lines = max(row_lines) if row_lines else 1
        return max_lines * line_height + 2 * cell_v_pad

    header_lines = [h.count('\n') + 1 for h in wrapped_headers]
    header_h = row_block_height(header_lines)
    row_block_heights = [
        row_block_height([cell.count('\n') + 1 for cell in row])
        for row in wrapped_rows
    ]

    bottom_margin = 0.05
    page_idx = 0
    row_idx = 0

    while row_idx < len(wrapped_rows) or page_idx == 0:
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis('off')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

        page_title = title + (' (cont.)' if page_idx > 0 else '')
        ax.text(0.5, 0.965, page_title, fontsize=15, fontweight='bold',
                ha='center', transform=ax.transAxes, color=header_color)
        y_top = 0.93
        if subtitle and page_idx == 0:
            ax.text(0.5, 0.945, subtitle, fontsize=10, style='italic',
                    ha='center', transform=ax.transAxes, color='#666')
            y_top = 0.92
        if footer:
            ax.text(0.5, 0.02, footer, fontsize=8, style='italic',
                    ha='center', transform=ax.transAxes, color='#888')

        # Header.
        y_cursor = y_top
        ax.add_patch(mpatches.Rectangle(
            (table_left, y_cursor - header_h), table_width, header_h,
            facecolor=header_color, edgecolor=grid_color, linewidth=0.6,
            transform=ax.transAxes,
        ))
        # White vertical separator lines between header columns - makes
        # column boundaries unambiguous even when bold header text extends
        # to the column's right edge.
        for x in col_edges[1:-1]:
            ax.plot([x, x], [y_cursor - header_h, y_cursor],
                    color='white', linewidth=0.8, transform=ax.transAxes)
        for i, htext in enumerate(wrapped_headers):
            ax.text(col_edges[i] + cell_h_pad,
                    y_cursor - cell_v_pad,
                    htext,
                    fontsize=header_fontsize, fontweight='bold',
                    ha='left', va='top', color='white',
                    transform=ax.transAxes)
        y_cursor -= header_h

        # Body rows for this page.
        rows_on_page = 0
        while row_idx < len(wrapped_rows):
            row_h = row_block_heights[row_idx]
            if y_cursor - row_h < bottom_margin:
                break  # paginate
            row = wrapped_rows[row_idx]
            # Background color.
            if color_col is not None and color_col < n_cols:
                level = (row[color_col] or '').strip().upper().strip('* ').split('\n')[0]
                fill = _RISK_LEVEL_FILL.get(
                    level, '#fafafa' if rows_on_page % 2 == 0 else '#f0f0f0')
            else:
                fill = '#fafafa' if rows_on_page % 2 == 0 else '#f0f0f0'
            ax.add_patch(mpatches.Rectangle(
                (table_left, y_cursor - row_h), table_width, row_h,
                facecolor=fill, edgecolor=grid_color, linewidth=0.4,
                transform=ax.transAxes,
            ))
            # Vertical column separators.
            for x in col_edges[1:-1]:
                ax.plot([x, x], [y_cursor - row_h, y_cursor],
                        color=grid_color, linewidth=0.4, transform=ax.transAxes)
            # Cell text.
            for i, cell in enumerate(row):
                txt_color = '#2c3e50'
                weight = 'normal'
                if color_col is not None and i == color_col:
                    level = (cell or '').strip().upper().strip('* ').split('\n')[0]
                    if level in _RISK_LEVEL_TEXT:
                        txt_color = _RISK_LEVEL_TEXT[level]
                        weight = 'bold'
                ax.text(col_edges[i] + cell_h_pad,
                        y_cursor - cell_v_pad,
                        cell,
                        fontsize=body_fontsize,
                        fontweight=weight,
                        ha='left', va='top', color=txt_color,
                        transform=ax.transAxes)
            y_cursor -= row_h
            rows_on_page += 1
            row_idx += 1

        pdf.savefig(fig, dpi=300, bbox_inches='tight')
        plt.close(fig)
        page_idx += 1
        # Defensive: avoid infinite loop if a single row is taller than a page
        # (extremely unlikely with our data; would need ~25 wrapped lines).
        if rows_on_page == 0 and row_idx < len(wrapped_rows):
            row_idx += 1


def _build_narrative_blocks(body_text):
    """Convert markdown narrative into a list of (kind, text) rendering blocks.

    kind in {'subheading', 'paragraph', 'bullet'}. Bullets are emitted one per
    block so the renderer can keep tight inter-bullet spacing without merging
    paragraphs. Markdown emphasis (**bold**, *italic*) markers are stripped.
    """
    blocks = []
    paragraphs = re.split(r'\n\s*\n', body_text)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # Subheading: ### or #### markdown headers.
        m = re.match(r'^(#{2,4})\s+(.+)$', para)
        if m and '\n' not in para:
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', m.group(2))
            blocks.append(('subheading', text))
            continue
        # Bullet block: every non-empty line starts with - / * / N.
        lines = [ln for ln in para.split('\n') if ln.strip()]
        is_bullets = bool(lines) and all(
            ln.lstrip().startswith(('-', '*', '•'))
            or re.match(r'^\s*\d+\.\s', ln)
            for ln in lines
        )
        if is_bullets:
            for ln in lines:
                clean = re.sub(r'^\s*[-*]\s+', '• ', ln)
                clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
                clean = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'\1', clean)
                blocks.append(('bullet', clean))
            continue
        # Paragraph (may contain manual line breaks; treat each line separately).
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', para)
        clean = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'\1', clean)
        blocks.append(('paragraph', clean))
    return blocks


def render_narrative_page(pdf, title, body_text, subtitle=None):
    """Render markdown narrative as one or more proportional-font PDF pages.

    Splits ### / #### subheaders into bold blue subheadings, bullet blocks
    into compact bullet lists, and paragraphs into wrapped text. Paginates
    automatically when content overflows a single page.
    """
    import textwrap

    blocks = _build_narrative_blocks(body_text)

    body_fontsize = 10.5
    line_height = 0.0225
    para_gap = 0.014
    bullet_gap = 0.004
    sub_gap = 0.008
    body_color = '#2c3e50'
    sub_color = '#1B365D'

    def open_page(continuation=False):
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis('off')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        page_title = title + (' (cont.)' if continuation else '')
        ax.text(0.5, 0.965, page_title, fontsize=16, fontweight='bold',
                ha='center', transform=ax.transAxes, color=sub_color)
        if subtitle and not continuation:
            ax.text(0.5, 0.94, subtitle, fontsize=10, style='italic',
                    ha='center', transform=ax.transAxes, color='#666')
            return fig, ax, 0.91
        return fig, ax, 0.93

    def write(ax, y, text, fontsize, fontweight='normal', color='#2c3e50',
              indent=0.06, wrap_width=92):
        wrapped = textwrap.wrap(text, width=wrap_width,
                                 subsequent_indent='  ' if text.startswith('• ') else '') or ['']
        for line in wrapped:
            ax.text(indent, y, line, fontsize=fontsize, fontweight=fontweight,
                    ha='left', va='top', transform=ax.transAxes, color=color)
            y -= line_height
        return y

    fig, ax, y = open_page()
    bottom_margin = 0.06

    for kind, text in blocks:
        # Estimate space needed for this block.
        if kind == 'subheading':
            needed = line_height + sub_gap
        elif kind == 'bullet':
            wrapped = textwrap.wrap(text, width=92) or ['']
            needed = len(wrapped) * line_height + bullet_gap
        else:  # paragraph
            wrapped = textwrap.wrap(text, width=95) or ['']
            needed = len(wrapped) * line_height + para_gap

        if y - needed < bottom_margin:
            pdf.savefig(fig, dpi=300, bbox_inches='tight')
            plt.close(fig)
            fig, ax, y = open_page(continuation=True)

        if kind == 'subheading':
            y -= sub_gap  # extra breathing room before subheading
            y = write(ax, y, text, fontsize=12.5, fontweight='bold',
                      color=sub_color, indent=0.05, wrap_width=85)
            y -= sub_gap
        elif kind == 'bullet':
            y = write(ax, y, text, fontsize=body_fontsize, color=body_color,
                      indent=0.06, wrap_width=92)
            y -= bullet_gap
        else:
            for raw_line in text.split('\n'):
                if not raw_line.strip():
                    continue
                y = write(ax, y, raw_line.strip(), fontsize=body_fontsize,
                          color=body_color, indent=0.06, wrap_width=95)
            y -= para_gap

    pdf.savefig(fig, dpi=300, bbox_inches='tight')
    plt.close(fig)


def _extract_markdown_section_n(content, section_number):
    """Extract the body of a markdown `## N.` (or `## N. Title`) section.

    Returns the text between the `## N.` heading and the next `## ` heading
    (or end-of-document). Empty string if not found.
    """
    pattern = re.compile(
        rf'^##\s+{section_number}\.\s+[^\n]*\n(.*?)(?=^##\s|\Z)',
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(content)
    return match.group(1).strip() if match else ''


def _extract_markdown_table_rows(section_body, header_keywords):
    """Pull rows from the first markdown table whose header matches all keywords.

    header_keywords: list of strings that must each appear in the header row
        (case-insensitive). Lets us pick the right table when a section has
        multiple tables.

    Returns (headers, rows) where each is a list of cell strings.
    """
    lines = section_body.split('\n')
    for i, line in enumerate(lines):
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        lower = [c.lower() for c in cells]
        if all(any(kw.lower() in cell for cell in lower) for kw in header_keywords):
            headers = cells
            # Skip the separator line (---|---).
            j = i + 1
            if j < len(lines) and re.match(r'^\|\s*[-:|\s]+\|', lines[j]):
                j += 1
            rows = []
            while j < len(lines) and lines[j].strip().startswith('|'):
                row_cells = [c.strip() for c in lines[j].strip('|').split('|')]
                if len(row_cells) == len(headers):
                    # Strip markdown bold from cell content.
                    row_cells = [re.sub(r'\*\*([^*]+)\*\*', r'\1', c) for c in row_cells]
                    rows.append(row_cells)
                j += 1
            return headers, rows
    return [], []


def _build_slide_data(output_dir, gene):
    """Build the data dict consumed by both the portrait page-1 and the
    landscape summary slide.

    Returns a dict with keys: toxicity_data, idas_data, subgroup_data,
    takeaways, aliases, modality. All extraction goes through
    _extract_markdown_section_n / _extract_markdown_table_rows so the
    portrait and landscape views stay in sync regardless of markdown
    formatting drift.
    """
    slide_data = {'toxicity_data': [], 'idas_data': [], 'subgroup_data': [],
                  'takeaways': [], 'aliases': '', 'modality': 'Selective'}
    report_path = integrated_report_path(output_dir, gene)
    if not os.path.exists(report_path):
        return slide_data
    with open(report_path, 'r') as f:
        content = f.read()

    # Aliases: parse the Target row of the Executive Summary table.
    aliases_match = re.search(
        r'\*\*Target\*\*\s*\|\s*\w[\w\-]*\s*\(([^)]+)\)', content,
    )
    if aliases_match:
        slide_data['aliases'] = aliases_match.group(1)

    # Modality: take the "Modality:" item from "Key Findings at a Glance".
    modality_match = re.search(r'\*\*Modality\*\*[:\s]*([^\n]+)', content)
    if modality_match:
        mt = modality_match.group(1).strip()
        mt = re.sub(r'^[:\-—\s]+', '', mt)
        mt = re.sub(r'\*\*([^*]+)\*\*', r'\1', mt)
        mt = re.split(r'[,\(\-—–]', mt, maxsplit=1)[0].strip()[:22]
        if mt:
            slide_data['modality'] = mt

    sec3 = _extract_markdown_section_n(content, 3)

    # Toxicity rows from Section 3.2.
    m32 = re.search(
        r'### 3\.2[^\n]*\n(.*?)(?=^### |^## |\Z)',
        sec3, re.DOTALL | re.MULTILINE,
    ) if sec3 else None
    if m32:
        tox_h, tox_r = _extract_markdown_table_rows(
            m32.group(1), header_keywords=['Tumor', 'Normal'])
        if tox_h and tox_r:
            comp_idx = next(
                (i for i, h in enumerate(tox_h)
                 if 'comparison' in h.lower() or 'cohort' in h.lower()), 0,
            )
            fc_idx = next(
                (i for i, h in enumerate(tox_h) if 'fold change' in h.lower()),
                None,
            )
            risk_idx = next(
                (i for i, h in enumerate(tox_h)
                 if 'risk level' in h.lower() or h.lower().strip() == 'risk'),
                None,
            )
            for row in tox_r[:4]:
                if comp_idx >= len(row):
                    continue
                comp = row[comp_idx]
                if 'GTEx' in comp or 'gtex' in comp.lower():
                    continue
                subtype = (
                    'LUSC' if 'LUSC' in comp else
                    'LUAD' if 'LUAD' in comp else
                    'RAS WT MSS' if 'RASWT' in comp else
                    'RAS Mut MSS' if 'RASMut' in comp else
                    'MSI-H' if 'MSIH' in comp else
                    'Resectable' if 'Resectable' in comp else
                    comp[:18]
                )
                fc = (row[fc_idx] if fc_idx is not None and fc_idx < len(row) else '').strip()
                risk = (row[risk_idx] if risk_idx is not None and risk_idx < len(row) else 'MEDIUM').strip().upper()
                slide_data['toxicity_data'].append({
                    'subtype': subtype,
                    'fold_change': fc.replace('×', 'x') or '—',
                    'risk': risk,
                })

    # iDAS whitespace rows from Section 3.2.
    if m32:
        idas_h, idas_r = _extract_markdown_table_rows(
            m32.group(1), header_keywords=['Whitespace', 'Alignment'])
        if idas_h and idas_r:
            ws_idx = next(
                (i for i, h in enumerate(idas_h) if 'whitespace' in h.lower()), 0,
            )
            expr_idx = next(
                (i for i, h in enumerate(idas_h) if 'expression' in h.lower()), None,
            )
            align_idx = next(
                (i for i, h in enumerate(idas_h) if 'alignment' in h.lower()), None,
            )
            for row in idas_r[:4]:
                if ws_idx >= len(row):
                    continue
                slide_data['idas_data'].append({
                    'whitespace': row[ws_idx].strip()[:22],
                    'expression': (row[expr_idx] if expr_idx is not None and expr_idx < len(row) else '').strip(),
                    'alignment': (row[align_idx] if align_idx is not None and align_idx < len(row) else '').strip(),
                })

    # Subgroup recommendations from Section 6.3.
    sec6 = _extract_markdown_section_n(content, 6)
    m63 = re.search(
        r'### 6\.3[^\n]*\n(.*?)(?=^### |^## |\Z)',
        sec6, re.DOTALL | re.MULTILINE,
    ) if sec6 else None
    if m63:
        sg_h, sg_r = _extract_markdown_table_rows(
            m63.group(1), header_keywords=['Population', 'Recommendation'])
        if sg_h and sg_r:
            pop_idx = next(
                (i for i, h in enumerate(sg_h) if 'population' in h.lower()), 0,
            )
            rec_idx = next(
                (i for i, h in enumerate(sg_h) if 'recommendation' in h.lower()), 1,
            )
            rat_idx = next(
                (i for i, h in enumerate(sg_h) if 'rationale' in h.lower()), -1,
            )
            for row in sg_r[:5]:
                if pop_idx >= len(row) or rec_idx >= len(row):
                    continue
                rationale = (row[rat_idx] if 0 <= rat_idx < len(row) else '').strip()[:20]
                slide_data['subgroup_data'].append({
                    'population': row[pop_idx].strip()[:18],
                    'recommendation': row[rec_idx].strip().upper(),
                    'rationale': rationale,
                })

    # Key takeaways: prefer Executive Summary's "Key Findings at a Glance"
    # bullets; fall back to Section 7's numbered list if present.
    kf_match = re.search(
        r'###\s*Key Findings at a Glance\s*\n(.*?)(?=^##|^---|\Z)',
        content, re.DOTALL | re.MULTILINE,
    )
    if kf_match:
        for line in kf_match.group(1).split('\n'):
            ln = line.strip()
            if ln.startswith(('-', '*', '•')):
                cleaned = re.sub(r'^\s*[-*•]\s+', '', ln)
                cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
                slide_data['takeaways'].append(cleaned)
            if len(slide_data['takeaways']) >= 5:
                break
    if not slide_data['takeaways']:
        sec7 = _extract_markdown_section_n(content, 7)
        if sec7:
            for line in sec7.split('\n'):
                if re.match(r'^\s*\d+\.\s', line):
                    cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', line.strip())
                    slide_data['takeaways'].append(cleaned)
                if len(slide_data['takeaways']) >= 5:
                    break

    return slide_data


def generate_landscape_summary_slide(gene, output_dir, disease='crc', report_data=None):
    """Generate landscape (16:9) executive summary slide for presentations."""

    config = DISEASE_CONFIG.get(disease.lower(), DISEASE_CONFIG['crc'])
    disease_abbr = config['abbreviation']

    # Colors
    COLORS = {
        'TAKEDA_RED': '#E4002B',
        'DARK_BLUE': '#1B365D',
        'LIGHT_BLUE': '#0077C8',
        'GREEN': '#00843D',
        'AMBER': '#F2A900',
        'LIGHT_GRAY': '#F5F5F5',
        'WHITE': '#FFFFFF',
    }

    RISK_COLORS = {'LOW': COLORS['GREEN'], 'MEDIUM': COLORS['AMBER'], 'HIGH': COLORS['TAKEDA_RED'], 'LOW-MEDIUM': COLORS['AMBER']}
    REC_COLORS = {'PRIORITY': COLORS['GREEN'], 'GO': COLORS['LIGHT_BLUE'], 'CONDITIONAL': COLORS['AMBER'], 'CAUTION': COLORS['TAKEDA_RED'], 'EXCLUDE': COLORS['TAKEDA_RED']}

    # Parse integrated report for slide data via the shared helper so the
    # landscape slide stays in sync with the portrait page-1 view.
    slide_data = _build_slide_data(output_dir, gene)

    # Set up figure (16:9 landscape)
    fig = plt.figure(figsize=(16, 9), facecolor='white')

    # === TITLE BAR ===
    title_rect = mpatches.FancyBboxPatch((0.02, 0.88), 0.96, 0.10,
                                          boxstyle="round,pad=0.01,rounding_size=0.01",
                                          facecolor=COLORS['DARK_BLUE'], transform=fig.transFigure, zorder=1)
    fig.patches.append(title_rect)
    fig.text(0.5, 0.93, f'{gene} Target Evaluation: {disease_abbr}',
             fontsize=28, fontweight='bold', color=COLORS['WHITE'], ha='center', va='center')
    if slide_data['aliases']:
        fig.text(0.5, 0.895, slide_data['aliases'], fontsize=14, color='#B8D4E8', ha='center', va='center')

    # Recommendation badge (smaller). Use whatever the parser captured —
    # do NOT hallucinate a "PRIORITY" qualifier; the parser preserves any
    # qualifier present in the markdown ("GO — MEDIUM PRIORITY",
    # "GO — HIGH PRIORITY", etc.).
    rec = (report_data.get('recommendation', 'GO') if report_data else 'GO').upper()
    is_go = 'GO' in rec and 'NO-GO' not in rec
    is_conditional = 'CONDITIONAL' in rec and not is_go
    rec_text = rec
    # 3-way color coding: green (GO), amber (CONDITIONAL — caution but not
    # rejection), red (NO-GO / EXCLUDE). Amber matches the engine's
    # "needs more validation" semantics and avoids false-alarm red on
    # programs that may still advance with the right neosubstrate.
    if is_go:
        rec_color = COLORS['GREEN']
    elif is_conditional:
        rec_color = COLORS['AMBER']
    else:
        rec_color = COLORS['TAKEDA_RED']
    badge_rect = mpatches.FancyBboxPatch((0.80, 0.90), 0.17, 0.05,
                                          boxstyle="round,pad=0.01,rounding_size=0.02",
                                          facecolor=rec_color, transform=fig.transFigure, zorder=2)
    fig.patches.append(badge_rect)
    fig.text(0.885, 0.925, rec_text, fontsize=12, fontweight='bold', color=COLORS['WHITE'], ha='center', va='center')

    # === LEFT COLUMN: Key Metrics ===
    # Score box
    score_rect = mpatches.FancyBboxPatch((0.02, 0.70), 0.30, 0.15,
                                          boxstyle="round,pad=0.01,rounding_size=0.02",
                                          facecolor=COLORS['LIGHT_GRAY'], edgecolor=COLORS['DARK_BLUE'], linewidth=2,
                                          transform=fig.transFigure)
    fig.patches.append(score_rect)
    fig.text(0.17, 0.82, 'ScholarEval Score', fontsize=12, fontweight='bold', color=COLORS['DARK_BLUE'], ha='center')
    score = report_data.get('score', '4.0/5.0') if report_data else '4.0/5.0'
    fig.text(0.17, 0.74, score, fontsize=32, fontweight='bold', color=COLORS['DARK_BLUE'], ha='center')
    assessment = report_data.get('assessment', 'Strong') if report_data else 'Strong'
    fig.text(0.17, 0.715, assessment, fontsize=14, color=COLORS['GREEN'], ha='center', fontweight='bold')

    # Risk box
    risk = report_data.get('risk_profile', 'LOW-MEDIUM') if report_data else 'LOW-MEDIUM'
    risk_color = RISK_COLORS.get(risk.upper(), COLORS['AMBER'])
    risk_rect = mpatches.FancyBboxPatch((0.02, 0.52), 0.30, 0.15,
                                         boxstyle="round,pad=0.01,rounding_size=0.02",
                                         facecolor=COLORS['LIGHT_GRAY'], edgecolor=risk_color, linewidth=2,
                                         transform=fig.transFigure)
    fig.patches.append(risk_rect)
    fig.text(0.17, 0.64, 'Overall Risk Profile', fontsize=12, fontweight='bold', color=COLORS['DARK_BLUE'], ha='center')
    fig.text(0.17, 0.56, risk.upper(), fontsize=20 if len(risk) > 6 else 24, fontweight='bold', color=risk_color, ha='center')

    # Modality box
    mod_rect = mpatches.FancyBboxPatch((0.02, 0.34), 0.30, 0.15,
                                        boxstyle="round,pad=0.01,rounding_size=0.02",
                                        facecolor=COLORS['LIGHT_GRAY'], edgecolor=COLORS['LIGHT_BLUE'], linewidth=2,
                                        transform=fig.transFigure)
    fig.patches.append(mod_rect)
    fig.text(0.17, 0.46, 'Recommended Modality', fontsize=12, fontweight='bold', color=COLORS['DARK_BLUE'], ha='center')
    fig.text(0.17, 0.38, slide_data['modality'], fontsize=24, fontweight='bold', color=COLORS['LIGHT_BLUE'], ha='center')

    # === MIDDLE COLUMN: On-Target Toxicity & iDAS ===
    fig.text(0.35, 0.84, 'On-Target Toxicity (Tumor vs Adjacent)', fontsize=14, fontweight='bold', color=COLORS['DARK_BLUE'])
    y = 0.78
    for item in slide_data['toxicity_data'][:4]:
        risk_col = RISK_COLORS.get(item['risk'], COLORS['GREEN'])
        fig.text(0.36, y, item['subtype'], fontsize=11, color=COLORS['DARK_BLUE'])
        fig.text(0.48, y, item['fold_change'], fontsize=11, fontweight='bold', color=COLORS['DARK_BLUE'])
        badge = mpatches.FancyBboxPatch((0.54, y - 0.012), 0.06, 0.03,
                                         boxstyle="round,pad=0.005,rounding_size=0.01",
                                         facecolor=risk_col, transform=fig.transFigure)
        fig.patches.append(badge)
        fig.text(0.57, y, item['risk'], fontsize=9, fontweight='bold', color=COLORS['WHITE'], ha='center')
        y -= 0.042 if len(slide_data['toxicity_data']) > 3 else 0.05

    # iDAS Section
    idas_y = 0.58 if len(slide_data['toxicity_data']) <= 2 else 0.54
    fig.text(0.35, idas_y + 0.06, 'iDAS Priority Whitespace Alignment', fontsize=14, fontweight='bold', color=COLORS['DARK_BLUE'])
    y = idas_y
    for item in slide_data['idas_data'][:4]:
        fig.text(0.36, y, item['whitespace'], fontsize=10, color=COLORS['DARK_BLUE'])
        fig.text(0.54, y, item['expression'], fontsize=9, color='gray')
        badge = mpatches.FancyBboxPatch((0.60, y - 0.012), 0.055, 0.03,
                                         boxstyle="round,pad=0.005,rounding_size=0.01",
                                         facecolor=COLORS['GREEN'], transform=fig.transFigure)
        fig.patches.append(badge)
        fig.text(0.6275, y, item['alignment'], fontsize=8, fontweight='bold', color=COLORS['WHITE'], ha='center')
        y -= 0.042 if len(slide_data['idas_data']) > 3 else 0.05

    # === RIGHT COLUMN: Subgroup Recommendations ===
    fig.text(0.68, 0.84, 'Subgroup Recommendations', fontsize=14, fontweight='bold', color=COLORS['DARK_BLUE'])
    y = 0.78
    has_exclusions = False
    for item in slide_data['subgroup_data'][:5]:
        rec = item['recommendation']
        color = REC_COLORS.get(rec, COLORS['LIGHT_BLUE'])
        if rec in ['CAUTION', 'EXCLUDE']:
            has_exclusions = True
        fig.text(0.69, y, item['population'], fontsize=11, color=COLORS['DARK_BLUE'])
        badge_w = 0.09 if rec == 'CONDITIONAL' else 0.07
        badge = mpatches.FancyBboxPatch((0.87, y - 0.015), badge_w, 0.035,
                                         boxstyle="round,pad=0.005,rounding_size=0.01",
                                         facecolor=color, transform=fig.transFigure)
        fig.patches.append(badge)
        fig.text(0.87 + badge_w/2, y, rec, fontsize=9, fontweight='bold', color=COLORS['WHITE'], ha='center')
        fig.text(0.69, y - 0.025, item['rationale'], fontsize=9, color='gray')
        y -= 0.065
    if not has_exclusions and slide_data['subgroup_data']:
        fig.text(0.69, y + 0.01, 'No exclusion criteria needed', fontsize=10, color=COLORS['GREEN'], fontstyle='italic')

    # === BOTTOM: Key Takeaways ===
    takeaway_rect = mpatches.FancyBboxPatch((0.02, 0.02), 0.96, 0.28,
                                             boxstyle="round,pad=0.01,rounding_size=0.02",
                                             facecolor='#E8F4E8', edgecolor=COLORS['GREEN'], linewidth=2,
                                             transform=fig.transFigure)
    fig.patches.append(takeaway_rect)
    fig.text(0.5, 0.27, 'Key Takeaways', fontsize=16, fontweight='bold', color=COLORS['DARK_BLUE'], ha='center')
    y = 0.22
    import textwrap
    for takeaway in slide_data['takeaways'][:5]:
        # Wrap long text to fit within slide width
        wrapped = textwrap.fill(takeaway, width=130)
        lines = wrapped.split('\n')
        for line in lines[:2]:  # Max 2 lines per takeaway
            fig.text(0.05, y, line, fontsize=11, color=COLORS['DARK_BLUE'])
            y -= 0.035

    # Footer
    date_str = report_data.get('date', date.today().isoformat()) if report_data else date.today().isoformat()
    fig.text(0.02, 0.005, f'Generated: {date_str} | Oncology Target Evaluation Pipeline v2.0', fontsize=9, color='gray')
    fig.text(0.98, 0.005, f'Data Sources: {config["tcga_projects"]}, GTEx, Tempus RWD', fontsize=9, color='gray', ha='right')

    # Save
    png_path = os.path.join(output_dir, get_output_filename(gene, 'slide', 'png'))
    pdf_path = os.path.join(output_dir, get_output_filename(gene, 'slide', 'pdf'))
    plt.savefig(png_path, dpi=300, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.savefig(pdf_path, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"  Landscape summary slide: {gene}_summary_slide.png / .pdf")
    return png_path, pdf_path


def generate_pdf_report(gene, output_dir, disease='crc', report_data=None):
    """Generate the complete PDF report for a target gene."""

    # Get disease-specific configuration
    config = DISEASE_CONFIG.get(disease.lower(), DISEASE_CONFIG['crc'])
    disease_full = config['full_name']
    disease_abbr = config['abbreviation']
    tcga_projects = config['tcga_projects']
    normal_tissue = config['normal_tissue']
    gtex_tissue = config['gtex_tissue']
    cohort_desc = config['cohort_description']
    disease_intro = config['disease_intro']
    subtype_name = config['subtype_name']
    subtype_desc = config['subtype_description']

    # Parse integrated report if exists and no data provided
    if report_data is None:
        report_path = integrated_report_path(output_dir, gene)
        if os.path.exists(report_path):
            report_data = parse_integrated_report(report_path, output_dir, gene, disease)
            print(f"  Parsed: {os.path.basename(report_path)}")
            print(f"  Fold Change (vs Adjacent Normal): {report_data.get('fold_change', 'TBD')}")
        else:
            report_data = {'date': date.today().isoformat(), 'score': 'TBD', 'risk_profile': 'TBD',
                          'recommendation': 'GO', 'assessment': 'TBD', 'fold_change': 'TBD',
                          'risk_table': {}, 'strengths': [], 'risks': [], 'scholar_scores': {}}

    pdf_path = os.path.join(output_dir, get_output_filename(gene, 'report', 'pdf'))
    pdf = PdfPages(pdf_path)

    print(f"Generating PDF report for {gene} ({disease_abbr})...")

    # ===== PAGE 1: EXECUTIVE SUMMARY SLIDE (Portrait) =====
    fig1, ax1 = plt.subplots(figsize=(8.5, 11))
    ax1.axis('off')
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)

    # Colors
    COLORS = {
        'DARK_BLUE': '#1B365D',
        'LIGHT_BLUE': '#0077C8',
        'GREEN': '#00843D',
        'AMBER': '#F2A900',
        'RED': '#E4002B',
        'LIGHT_GRAY': '#F5F5F5',
    }

    # Parse integrated report for slide data via the shared helper so the
    # portrait page-1 stays in sync with the landscape summary slide.
    slide_data = _build_slide_data(output_dir, gene)

    # === TITLE BAR ===
    header = mpatches.FancyBboxPatch((0.03, 0.93), 0.94, 0.055,
                                      boxstyle="round,pad=0.01,rounding_size=0.01",
                                      facecolor=COLORS['DARK_BLUE'], transform=ax1.transAxes)
    ax1.add_patch(header)
    ax1.text(0.35, 0.96, f'{gene} Target Evaluation: {disease_abbr}', fontsize=16, fontweight='bold',
             ha='center', transform=ax1.transAxes, color='white')
    if slide_data['aliases']:
        ax1.text(0.35, 0.938, slide_data['aliases'], fontsize=8, ha='center', transform=ax1.transAxes, color='#B8D4E8')

    # Recommendation badge. Display the parsed recommendation verbatim
    # (with any priority qualifier the parser preserved); do not append
    # "PRIORITY" as a default.
    recommendation = report_data.get('recommendation', 'GO') if report_data else 'GO'
    rec_upper = recommendation.upper().strip()
    is_go = 'GO' in rec_upper and 'NO-GO' not in rec_upper
    is_conditional = 'CONDITIONAL' in rec_upper and not is_go
    if is_go:
        rec_color = COLORS['GREEN']
    elif is_conditional:
        rec_color = COLORS['AMBER']
    else:
        rec_color = COLORS['RED']
    rec_text = rec_upper
    badge = mpatches.FancyBboxPatch((0.72, 0.942), 0.22, 0.035,
                                     boxstyle="round,pad=0.008,rounding_size=0.012",
                                     facecolor=rec_color, transform=ax1.transAxes, zorder=5)
    ax1.add_patch(badge)
    ax1.text(0.83, 0.96, rec_text, fontsize=9, fontweight='bold', ha='center', transform=ax1.transAxes, color='white', zorder=6)

    # === ROW 1: Key Metrics (3 boxes - compact boxes, original font) ===
    score = report_data.get('score', 'TBD') if report_data else 'TBD'
    risk = report_data.get('risk_profile', 'TBD') if report_data else 'TBD'
    risk_color = COLORS['GREEN'] if risk == 'LOW' else COLORS['AMBER'] if 'MEDIUM' in risk else COLORS['RED']

    metrics = [
        ('ScholarEval Score', score, COLORS['DARK_BLUE']),
        ('Risk Profile', risk, risk_color),
        ('Modality', slide_data['modality'], COLORS['LIGHT_BLUE']),
    ]
    for i, (label, value, color) in enumerate(metrics):
        x = 0.03 + i * 0.32
        box = mpatches.FancyBboxPatch((x, 0.855), 0.30, 0.055, boxstyle="round,pad=0.008,rounding_size=0.01",
                                       facecolor=COLORS['LIGHT_GRAY'], edgecolor=color, linewidth=2, transform=ax1.transAxes)
        ax1.add_patch(box)
        ax1.text(x + 0.15, 0.895, label, fontsize=8, fontweight='bold', ha='center', transform=ax1.transAxes, color='#666')
        ax1.text(x + 0.15, 0.865, value, fontsize=14, fontweight='bold', ha='center', transform=ax1.transAxes, color=color)

    # === ROW 2: On-Target Toxicity & iDAS (side by side) ===
    # Left: Toxicity
    ax1.text(0.03, 0.82, 'On-Target Toxicity (Tumor vs Adjacent)', fontsize=10, fontweight='bold', transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
    y = 0.79
    for item in slide_data['toxicity_data'][:4]:
        risk_col = COLORS['GREEN'] if item['risk'] == 'LOW' else COLORS['AMBER'] if item['risk'] == 'MEDIUM' else COLORS['RED']
        ax1.text(0.04, y, item['subtype'], fontsize=9, transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
        ax1.text(0.22, y, item['fold_change'], fontsize=9, fontweight='bold', transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
        badge = mpatches.FancyBboxPatch((0.30, y - 0.008), 0.08, 0.022, boxstyle="round,pad=0.003,rounding_size=0.008",
                                         facecolor=risk_col, transform=ax1.transAxes)
        ax1.add_patch(badge)
        ax1.text(0.34, y, item['risk'], fontsize=7, fontweight='bold', ha='center', transform=ax1.transAxes, color='white')
        y -= 0.03

    # Right: iDAS
    ax1.text(0.52, 0.82, 'iDAS Priority Whitespace Alignment', fontsize=10, fontweight='bold', transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
    y = 0.79
    for item in slide_data['idas_data'][:4]:
        ax1.text(0.53, y, item['whitespace'], fontsize=8, transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
        ax1.text(0.78, y, item['expression'], fontsize=8, transform=ax1.transAxes, color='gray')
        badge = mpatches.FancyBboxPatch((0.86, y - 0.008), 0.10, 0.022, boxstyle="round,pad=0.003,rounding_size=0.008",
                                         facecolor=COLORS['GREEN'], transform=ax1.transAxes)
        ax1.add_patch(badge)
        ax1.text(0.91, y, item['alignment'], fontsize=7, fontweight='bold', ha='center', transform=ax1.transAxes, color='white')
        y -= 0.03

    # === ROW 3: Subgroup Recommendations ===
    ax1.text(0.03, 0.65, 'Subgroup Recommendations', fontsize=10, fontweight='bold', transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
    y = 0.62
    rec_colors = {'PRIORITY': COLORS['GREEN'], 'GO': COLORS['LIGHT_BLUE'], 'CONDITIONAL': COLORS['AMBER'], 'CAUTION': COLORS['RED'], 'EXCLUDE': COLORS['RED']}
    has_exclusions = False
    for item in slide_data['subgroup_data'][:5]:
        rec = item['recommendation']
        color = rec_colors.get(rec, COLORS['LIGHT_BLUE'])
        if rec in ['CAUTION', 'EXCLUDE']:
            has_exclusions = True
        ax1.text(0.04, y, item['population'], fontsize=9, transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
        ax1.text(0.28, y, item['rationale'], fontsize=7, transform=ax1.transAxes, color='gray')
        badge_w = 0.12 if rec == 'CONDITIONAL' else 0.09
        badge = mpatches.FancyBboxPatch((0.85, y - 0.008), badge_w, 0.022, boxstyle="round,pad=0.003,rounding_size=0.008",
                                         facecolor=color, transform=ax1.transAxes)
        ax1.add_patch(badge)
        ax1.text(0.85 + badge_w/2, y, rec, fontsize=7, fontweight='bold', ha='center', transform=ax1.transAxes, color='white')
        y -= 0.032
    if not has_exclusions and slide_data['subgroup_data']:
        ax1.text(0.04, y + 0.008, 'No exclusion criteria needed', fontsize=8, fontstyle='italic', transform=ax1.transAxes, color=COLORS['GREEN'])

    # === ROW 4: Key Takeaways ===
    takeaway_box = mpatches.FancyBboxPatch((0.03, 0.27), 0.94, 0.17, boxstyle="round,pad=0.01,rounding_size=0.01",
                                            facecolor='#E8F4E8', edgecolor=COLORS['GREEN'], linewidth=2, transform=ax1.transAxes)
    ax1.add_patch(takeaway_box)
    ax1.text(0.5, 0.425, 'Key Takeaways', fontsize=12, fontweight='bold', ha='center', transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
    y = 0.395
    import textwrap
    for takeaway in slide_data['takeaways'][:5]:
        wrapped = textwrap.fill(takeaway, width=110)
        lines = wrapped.split('\n')
        for line in lines[:2]:  # Max 2 lines per takeaway
            ax1.text(0.05, y, line, fontsize=8, transform=ax1.transAxes, color=COLORS['DARK_BLUE'])
            y -= 0.022

    # === Pipeline Footer (bottom) ===
    footer_rect = mpatches.FancyBboxPatch((0.03, 0.04), 0.94, 0.085,
                                           boxstyle="round,pad=0.008,rounding_size=0.012",
                                           facecolor='#f8f9f9', edgecolor='#d5d8dc', linewidth=1,
                                           transform=ax1.transAxes)
    ax1.add_patch(footer_rect)
    ax1.text(0.5, 0.105, '4-Step Evaluation Pipeline', fontsize=9, fontweight='bold',
             ha='center', transform=ax1.transAxes, color='#2c3e50')
    steps = ['Risk Assessment', 'Multi-omics', 'ScholarEval', 'Report']
    step_colors = ['#3498db', '#e67e22', '#1abc9c', '#e74c3c']
    for i, (step, scolor) in enumerate(zip(steps, step_colors)):
        x_pos = 0.2 + i * 0.18
        ax1.plot(x_pos, 0.07, 'o', markersize=7, color=scolor, transform=ax1.transAxes)
        ax1.text(x_pos, 0.045, step, fontsize=7, ha='center', va='top', transform=ax1.transAxes, color='#5d6d7e')
        if i < len(steps) - 1:
            ax1.annotate('', xy=(x_pos + 0.12, 0.07), xytext=(x_pos + 0.04, 0.07),
                        arrowprops=dict(arrowstyle='->', color='#bdc3c7', lw=1.5), transform=ax1.transAxes)

    date_str = report_data.get('date', date.today().isoformat()) if report_data else date.today().isoformat()
    ax1.text(0.5, 0.012, f'Generated: {date_str}  |  {disease_abbr} Target Evaluation Pipeline v2.0  |  Data: TCGA, GTEx, CCLE, Tempus',
             fontsize=7, ha='center', transform=ax1.transAxes, color='#aab7b8', style='italic')

    pdf.savefig(fig1, dpi=300, bbox_inches='tight')
    plt.close(fig1)
    print("  Page 1: Executive Summary")

    # Generate landscape summary slide (16:9) for presentations
    generate_landscape_summary_slide(gene, output_dir, disease, report_data)

    # ===== PAGE 2: INTRODUCTION =====
    intro_content = f"""1. INTRODUCTION
─────────────────────────────────────────────────────────────────────────────────────────
{disease_intro}

This report presents an integrated target evaluation for {gene} following a 4-step pipeline:
(1) risk assessment framework with literature review, (2) multi-omics
analysis, (3) ScholarEval target scoring, and (4) integrated scientific
assessment with risk-based recommendation.


2. EVALUATION FRAMEWORK
─────────────────────────────────────────────────────────────────────────────────────────
The evaluation integrates evidence from:

  • Systematic literature review (PubMed)
  • Transcriptomic analysis of {disease_abbr} tumors from {tcga_projects}
  • Normal tissue expression from GTEx {normal_tissue}
  • Real-world patient data from Tempus
  • ScholarEval 8-dimension target scoring
  • 6-category risk assessment framework

KEY EVALUATION CRITERIA:
  • Differential expression: Tumor vs adjacent normal (primary on-target toxicity metric)
  • iDAS alignment: Expression in priority whitespace populations
  • Druggability: Modality options and clinical validation
  • Safety profile: Normal tissue expression and known toxicities
  • Biomarker potential: Patient selection strategies"""
    text_page(pdf, 'Introduction', intro_content)
    print("  Page 2: Introduction")

    # ===== PAGE 3: METHODS =====
    methods = f"""2. METHODS
─────────────────────────────────────────────────────────────────────────────────────────

2.1 Risk Assessment Framework
Six risk categories were defined to guide evidence collection: Biological, Druggability,
Translational, Clinical, Safety, and Commercial/Competitive. Risk levels were assigned as
Low, Medium, or High based on predefined criteria.

2.2 Literature Review
PubMed was searched using target-specific queries combined with disease terms. Results
were organized by risk category to ensure comprehensive evidence collection.

2.3 Multi-omics Analysis
Gene expression and molecular profiling data were obtained from:
  • {tcga_projects} (primary tumors)
  • TCGA adjacent normal {normal_tissue}
  • {gtex_tissue}
  • CCLE {disease_abbr} cell lines
  • Tempus RWD (real-world patient samples)

TPM-normalized expression values were log2-transformed.
{cohort_desc}

Statistical analysis employed Kruskal-Wallis and Mann-Whitney U tests with Benjamini-
Hochberg FDR correction.

2.4 Target Scoring
The ScholarEval framework was applied with 8 weighted dimensions: Differential Expression,
Pathway Relevance, Druggability, Genetic Validation, Disease Association, Safety Profile,
Clinical Validation, and Biomarker Potential."""
    text_page(pdf, 'Methods', methods)
    print("  Page 3: Methods")

    # ===== PAGE 4: RESULTS INTRO =====
    # Signposts the four subsections that follow. The actual content lives in
    # 3.1 (Risk Assessment), 3.2 (Differential Expression), 3.3 (ScholarEval),
    # and 3.4 (Subgroup Suitability) on the pages immediately after this one.
    results_intro = f"""3. RESULTS
─────────────────────────────────────────────────────────────────────────────────────────

This section presents the four-step evaluation findings for {gene} in {disease_abbr},
in the same order as the integrated report markdown:

  3.1 Risk Assessment Summary (Step 1: Literature-Based)
      Six-category target risk evaluation derived from PubMed literature.
      Color-coded summary table, structured per-category cards, and a
      6-category bar chart.

  3.2 Differential Expression Analysis (Step 2: Multi-omics)
      Tumor vs adjacent-normal expression across {disease_abbr} cohorts using
      TCGA, GTEx, and Tempus real-world data. Comprehensive 8-panel figure.

  3.3 Target Validation Scorecard (Step 3: ScholarEval)
      Eight-dimension deterministic target scoring integrating Step 1
      literature evidence and Step 2 omics evidence. Scoring table plus
      bar chart.

  3.4 Subgroup-Stratified Suitability (Steps 2 + 3 integration)
      Three-phase per-subgroup recommendations
      (TCGA molecular -> Tempus mutation -> iDAS whitespace) — see the
      integrated report markdown for the full table."""
    text_page(pdf, '3. Results', results_intro)
    print("  Page 4: Results intro")

    # The page sequence below mirrors the integrated-report markdown order:
    #   3.1 Risk Assessment (Step 1 - literature)
    #   3.2 Differential Expression (Step 2 - multi-omics)
    #   3.3 ScholarEval (Step 3)
    #   3.4 Subgroup-stratified suitability (Steps 2+3 integration)

    # ===== SECTION 3.1: RISK ASSESSMENT TABLE (Step 1 - Literature) =====
    # Load the integrated-report markdown early; sections 3.1, 3.3, 3.4, 4-8
    # all parse from it.
    md_path_31 = integrated_report_path(output_dir, gene)
    md_content_31 = ""
    if os.path.exists(md_path_31):
        with open(md_path_31) as fh:
            md_content_31 = fh.read()
    overall_risk = report_data.get('risk_profile', 'TBD')

    # Try to parse the 4-column markdown table (Risk Category | Risk Level |
    # Key Driver | Key Evidence (PMID)) directly. Fall back to the legacy
    # 3-column hardcoded table if the markdown isn't available.
    sec3_md = _extract_markdown_section_n(md_content_31, 3)
    risk_31_headers, risk_31_rows = ([], [])
    if sec3_md:
        m31 = re.search(r'### 3\.1[^\n]*\n(.*?)(?=^### |^## |\Z)',
                        sec3_md, re.DOTALL | re.MULTILINE)
        if m31:
            risk_31_headers, risk_31_rows = _extract_markdown_table_rows(
                m31.group(1), header_keywords=['Risk', 'Level'])

    if risk_31_headers and risk_31_rows:
        # Find the Risk Level column for color coding.
        color_col = next(
            (i for i, h in enumerate(risk_31_headers) if 'level' in h.lower()),
            None,
        )
        # 4-col layout: Risk Category | Risk Level | Key Driver | Key Evidence (PMID).
        if len(risk_31_headers) == 4:
            # Risk Category needs ~16% to fit "Translational" on one line.
            # Key Driver and Key Evidence share the remainder.
            cw31 = [0.16, 0.11, 0.36, 0.37]
        else:
            cw31 = None
        render_table_page(
            pdf,
            title='3.1 Risk Assessment Summary',
            subtitle=f'Step 1 (Literature-Based) — Overall Risk Profile: {overall_risk}',
            headers=risk_31_headers,
            rows=risk_31_rows,
            col_widths=cw31,
            color_col=color_col,
            footer='LOW: strong evidence • MEDIUM: manageable gaps • HIGH: significant concerns',
        )
    else:
        # Fallback: use parsed risk_table (3 columns, no PMIDs).
        risk_table = report_data.get('risk_table', {})
        risk_rows = []
        for cat in ['Biological', 'Druggability', 'Translational',
                    'Clinical', 'Safety', 'Commercial']:
            info = risk_table.get(cat, {'level': 'TBD',
                                         'considerations': 'See integrated report'})
            risk_rows.append([
                cat,
                info.get('level', 'TBD'),
                info.get('considerations', 'See integrated report'),
            ])
        render_table_page(
            pdf,
            title='3.1 Risk Assessment Summary',
            subtitle=f'Step 1 (Literature-Based) — Overall Risk Profile: {overall_risk}',
            headers=['Risk Factor', 'Level', 'Key Considerations'],
            rows=risk_rows,
            col_widths=[0.20, 0.13, 0.67],
            color_col=1,
            footer='LOW: strong evidence • MEDIUM: manageable gaps • HIGH: significant concerns',
        )
    print("  Section 3.1: Risk Assessment Summary table")

    # ===== SECTION 3.1 (cont.): STRUCTURED 6-CATEGORY DETAIL CARDS =====
    append_risk_assessment_pages(pdf, output_dir, gene, disease)

    # ===== SECTION 3.1 (cont.): 6-CATEGORY RISK BAR CHART =====
    create_risk_assessment_figure(gene, output_dir, report_data)
    risk_fig = os.path.join(output_dir, get_output_filename(gene, 'risk', 'png'))
    add_high_res_figure(pdf, risk_fig, 'Figure: 6-Category Risk Assessment',
                        'Risk levels across Biological, Druggability, Translational, Clinical, Safety, and Commercial dimensions.')
    print("  Section 3.1: Risk Assessment bar chart")

    # ===== SECTION 3.2: DIFFERENTIAL EXPRESSION (Step 2 - Multi-omics) =====
    comp_fig = os.path.join(output_dir, get_bulk_rna_filename(gene, disease, 'figure', 'png'))
    add_high_res_figure(pdf, comp_fig, '3.2 Differential Expression Analysis (Step 2)',
                        f'{gene} expression across {disease_abbr} cohorts showing differential expression vs normal tissue (TCGA + Tempus + GTEx).')
    print("  Section 3.2: Differential Expression figure")

    # ===== SECTION 3.2 (cont.): SUBTYPE FIGURE (CMS for CRC, skip for NSCLC) =====
    subtype_fig_name = config.get('subtype_figure')
    if subtype_fig_name:
        subtype_fig = os.path.join(output_dir, subtype_fig_name.format(gene=gene))
        if os.path.exists(subtype_fig):
            add_high_res_figure(pdf, subtype_fig, f'Figure: Expression by {subtype_name}',
                                f'{subtype_desc}.')
            print(f"  Section 3.2: Subtype figure ({subtype_name})")
        else:
            fig_placeholder, ax_placeholder = plt.subplots(figsize=(8.5, 11))
            ax_placeholder.axis('off')
            ax_placeholder.text(0.5, 0.5, f'Figure: {subtype_name} Expression\n\nNot available for this analysis.',
                               ha='center', va='center', fontsize=14, color='#7f8c8d')
            pdf.savefig(fig_placeholder, dpi=300, bbox_inches='tight')
            plt.close(fig_placeholder)
            print(f"  Section 3.2: Subtype figure ({subtype_name}) - placeholder")
    else:
        print(f"  Section 3.2: Subtype figure skipped (no {subtype_name} for {disease_abbr})")

    # ===== SECTION 3.3: SCHOLAREVAL BAR CHART (Step 3) =====
    # The detail scoring table with per-dimension rationale is rendered later
    # (after the bar chart) directly from the integrated-report markdown via
    # render_table_page(), so we don't emit a redundant compact ASCII table
    # here.

    create_scholar_eval_figure(gene, output_dir, report_data)
    scholar_fig = os.path.join(output_dir, get_output_filename(gene, 'scholareval', 'png'))
    add_high_res_figure(pdf, scholar_fig, 'Figure: ScholarEval 8-Dimension Target Scoring',
                        'Eight-dimension target scoring based on the ScholarEval framework.')
    print("  Section 3.3: ScholarEval bar chart")

    # ===== Load the integrated-report markdown for sections 3.3 detail / 3.4 / 4-8 =====
    md_path = integrated_report_path(output_dir, gene)
    md_content = ""
    if os.path.exists(md_path):
        with open(md_path) as fh:
            md_content = fh.read()

    # ===== SECTION 3.3 (detail): full ScholarEval table with rationale =====
    sec3 = _extract_markdown_section_n(md_content, 3)
    headers, rows = _extract_markdown_table_rows(
        sec3, header_keywords=['Dimension', 'Score'])
    if headers and rows:
        # Markdown columns: Dimension | Weight | Score | Risk Level | Rationale.
        # Some integrated reports lack the Risk Level column - handle both.
        if len(headers) == 5:
            col_widths = [0.22, 0.09, 0.09, 0.13, 0.47]
            color_col = 3  # Risk Level column
        else:
            col_widths = None
            color_col = None
        render_table_page(
            pdf,
            title='3.3 ScholarEval Scoring Detail',
            headers=headers,
            rows=rows,
            col_widths=col_widths,
            color_col=color_col,
            subtitle='8-dimension target validation scorecard with per-dimension rationale',
        )
        print("  Section 3.3: ScholarEval scoring detail table")

    # ===== SECTION 3.4: subgroup-stratified suitability (3 phases) =====
    if sec3 and '3.4' in sec3:
        # Pull the 3.4 subsection body specifically.
        m = re.search(r'### 3\.4[^\n]*\n(.*?)(?=^### |^## |\Z)', sec3,
                       re.DOTALL | re.MULTILINE)
        sec34 = m.group(1) if m else sec3
        for phase_marker, phase_label, header_kw in [
            ('Phase 1', 'Phase 1: TCGA Molecular Subgroups (Treatment-Naive)', 'Score'),
            ('Phase 2', 'Phase 2: Tempus RAS / Mutation Status', 'Score'),
            ('Phase 3', 'Phase 3: iDAS Whitespace Suitability', 'Score'),
        ]:
            block_match = re.search(
                rf'#### {re.escape(phase_marker)}[^\n]*\n(.*?)(?=^#### |\Z)',
                sec34, re.DOTALL | re.MULTILINE,
            )
            if not block_match:
                continue
            # Match by 'Score' keyword which all 3 phase tables share, instead
            # of 'Subgroup' which Phase 3 calls 'Whitespace'.
            phdrs, prows = _extract_markdown_table_rows(
                block_match.group(1), header_keywords=[header_kw])
            if not phdrs or not prows:
                continue
            # Columns: Subgroup | Key Metric | Score | Risk Level | Recommendation
            color_col = None
            for idx, h in enumerate(phdrs):
                if 'recommendation' in h.lower():
                    color_col = idx
                    break
            # Allocate widths to fit long subgroup names and full
            # 'Recommendation' header. 5-col layout: 22/27/8/14/29.
            phase_widths = ([0.22, 0.27, 0.08, 0.14, 0.29]
                            if len(phdrs) == 5 else None)
            render_table_page(
                pdf,
                title='3.4 Subgroup-Stratified Suitability',
                subtitle=phase_label,
                headers=phdrs,
                rows=prows,
                col_widths=phase_widths,
                color_col=color_col,
            )
            print(f"  Section 3.4: {phase_marker}")

    # ===== SECTION 4: DISCUSSION (4.1 Strengths, 4.2 Risks, 4.3 Subgroup considerations) =====
    sec4 = _extract_markdown_section_n(md_content, 4)
    if sec4:
        render_narrative_page(
            pdf,
            title='4. Discussion',
            subtitle='Key strengths, risks, and subgroup-specific considerations',
            body_text=sec4,
        )
        print("  Section 4: Discussion")

    # ===== SECTION 5: RISK MITIGATION STRATEGIES (table) =====
    sec5 = _extract_markdown_section_n(md_content, 5)
    if sec5:
        h5, r5 = _extract_markdown_table_rows(sec5, header_keywords=['Risk', 'Mitigation'])
        if h5 and r5:
            color_col = None
            for idx, h in enumerate(h5):
                if 'level' in h.lower() or 'risk level' in h.lower():
                    color_col = idx
                    break
            render_table_page(
                pdf,
                title='5. Risk Mitigation Strategies',
                headers=h5,
                rows=r5,
                color_col=color_col,
                col_widths=[0.30, 0.13, 0.57] if len(h5) == 3 else None,
            )
            print("  Section 5: Risk Mitigation table")
        else:
            render_narrative_page(pdf, title='5. Risk Mitigation Strategies',
                                  body_text=sec5)
            print("  Section 5: Risk Mitigation (narrative)")

    # ===== SECTION 6: RECOMMENDATIONS =====
    sec6 = _extract_markdown_section_n(md_content, 6)
    if sec6:
        # Split into 6.1 narrative + 6.2 list, then 6.3 subgroup table.
        # 6.1 + 6.2 render as narrative (text + bullets); 6.3 as styled table.
        m61_63 = re.search(
            r'(.*?)(?=^### 6\.3)', sec6,
            re.DOTALL | re.MULTILINE,
        )
        narrative_body = m61_63.group(1) if m61_63 else sec6
        if narrative_body.strip():
            render_narrative_page(
                pdf,
                title='6. Recommendations',
                subtitle='Overall recommendation and development path',
                body_text=narrative_body,
            )
            print("  Section 6: Recommendations narrative")

        m63 = re.search(r'### 6\.3[^\n]*\n(.*?)(?=^### |^## |\Z)', sec6,
                        re.DOTALL | re.MULTILINE)
        if m63:
            h63, r63 = _extract_markdown_table_rows(
                m63.group(1), header_keywords=['Population'])
            if h63 and r63:
                color_col = None
                for idx, h in enumerate(h63):
                    if 'recommend' in h.lower():
                        color_col = idx
                        break
                # 4-col layout (Population/Recommendation/Risk Level/Rationale):
                # Population fits "Chemorefractory 3L+ MSS" type names;
                # Recommendation gets enough width for the bold header word.
                cw63 = [0.20, 0.22, 0.12, 0.46] if len(h63) == 4 else None
                render_table_page(
                    pdf,
                    title='6.3 Subgroup-Specific Recommendations',
                    headers=h63,
                    rows=r63,
                    col_widths=cw63,
                    color_col=color_col,
                )
                print("  Section 6.3: Subgroup recommendations table")

    # ===== SECTION 7: CONCLUSIONS =====
    sec7 = _extract_markdown_section_n(md_content, 7)
    if sec7:
        render_narrative_page(
            pdf,
            title='7. Conclusions',
            body_text=sec7,
        )
        print("  Section 7: Conclusions")

    # ===== Final recommendation badge page (always emit, regardless of markdown) =====
    fig_final, ax_final = plt.subplots(figsize=(8.5, 11))
    ax_final.axis('off')
    ax_final.text(0.5, 0.92, 'Final Recommendation', fontsize=20, fontweight='bold',
                  ha='center', transform=ax_final.transAxes, color='#1B365D')

    final_score = report_data.get('score', 'TBD')
    overall_risk = report_data.get('risk_profile', 'TBD')
    fold_change = report_data.get('fold_change', 'TBD')

    summary_text = f"""{gene} — {disease_full} ({disease_abbr})

    ScholarEval Score:    {final_score}
    Overall Risk Profile: {overall_risk}
    Tumor vs Adjacent:    {fold_change}
    Recommendation:       {recommendation}"""
    ax_final.text(0.5, 0.65, summary_text, fontsize=13, ha='center', va='top',
                  transform=ax_final.transAxes, family='monospace', linespacing=2.0,
                  color='#2c3e50')

    rect = mpatches.FancyBboxPatch((0.1, 0.20), 0.8, 0.10, boxstyle="round,pad=0.02",
                                    facecolor=rec_color, edgecolor='black', linewidth=3,
                                    transform=ax_final.transAxes)
    ax_final.add_patch(rect)
    ax_final.text(0.5, 0.25, f'FINAL: {rec_text}',
                  fontsize=16, fontweight='bold', ha='center', va='center',
                  transform=ax_final.transAxes, color='white')

    pdf.savefig(fig_final, dpi=300, bbox_inches='tight')
    plt.close(fig_final)
    print("  Final: Recommendation badge")

    # ===== SECTION 8: REFERENCES =====
    sec8 = _extract_markdown_section_n(md_content, 8)
    if sec8:
        render_narrative_page(
            pdf,
            title='8. References',
            subtitle='Key publications cited in this report',
            body_text=sec8,
        )
        print("  Section 8: References")

    pdf.close()
    print(f"\nPDF report generated: {pdf_path}")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description='Generate target evaluation PDF report')
    parser.add_argument('--gene', required=True, help='Gene symbol (e.g., TNFRSF12A, PCDH7)')
    parser.add_argument('--disease', required=True, choices=['crc', 'nsclc'],
                        help='Disease indication (crc or nsclc)')
    parser.add_argument('--output-dir', default=None,
                        help='Output directory (default: ./{disease}_analysis_results/{GENE})')
    args = parser.parse_args()

    gene = args.gene.upper()
    disease = args.disease.lower()

    if args.output_dir:
        output_dir = args.output_dir
    else:
        config = DISEASE_CONFIG.get(disease, DISEASE_CONFIG['crc'])
        output_dir = f"{config['default_output_dir']}/{gene}"

    if not os.path.exists(output_dir):
        print(f"Error: Output directory does not exist: {output_dir}")
        print("Please run the expression analysis first.")
        sys.exit(1)

    # Check for required figures
    required_figs = [get_bulk_rna_filename(gene, disease, 'figure', 'png')]

    missing = []
    for fig in required_figs:
        if not os.path.exists(os.path.join(output_dir, fig)):
            missing.append(fig)

    if missing:
        print(f"Warning: Missing figures: {missing}")
        print("Some figure pages may be empty.")

    # Generate PDF
    generate_pdf_report(gene, output_dir, disease)


if __name__ == '__main__':
    main()
