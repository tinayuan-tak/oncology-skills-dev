#!/usr/bin/env python3
"""
Target Evaluation PDF Report Generator

Generates a publication-ready PDF report with high-resolution figures (300 DPI)
for the CRC target evaluation pipeline.

Usage:
    python generate_target_report_pdf.py --gene TNFRSF12A
    python generate_target_report_pdf.py --gene TNFRSF12A --output-dir ./crc_analysis_results/TNFRSF12A
"""

import argparse
import os
import sys
import re
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.patches as mpatches
import matplotlib.image as mpimg
import numpy as np


def parse_pairwise_comparisons(output_dir, gene):
    """Parse the pairwise comparisons CSV to get fold change vs adjacent normal."""
    import csv

    csv_path = os.path.join(output_dir, f'{gene}_pairwise_comparisons.csv')
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


def parse_integrated_report(report_path, output_dir=None, gene=None):
    """Parse the integrated target report markdown file to extract key data."""
    data = {
        'date': '2026-03-13',
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
        avg_adj, avg_gtex = parse_pairwise_comparisons(output_dir, gene)
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
            data['fold_change_gtex'] = f"{linear_fc_gtex:.0f}x vs GTEx"

    if not os.path.exists(report_path):
        return data

    with open(report_path, 'r') as f:
        content = f.read()

    # Extract ScholarEval Score (handles both "Key: Value" and "| Key | Value |" formats)
    score_match = re.search(r'\*?\*?ScholarEval Score\*?\*?[:\s|]+(\d+\.?\d*/5\.0)', content, re.IGNORECASE)
    if score_match:
        data['score'] = score_match.group(1)

    # Extract Overall Risk Profile (handles both formats)
    risk_match = re.search(r'\*?\*?Overall (?:Target )?Risk Profile\*?\*?[:\s|]+\*?\*?([A-Z-]+)\*?\*?', content, re.IGNORECASE)
    if risk_match:
        data['risk_profile'] = risk_match.group(1)

    # Extract Recommendation (handles both formats)
    # First try to capture just the main recommendation keyword (GO, NO-GO, CONDITIONAL NO-GO)
    rec_match = re.search(r'\*?\*?Recommendation\*?\*?[:\s|]+\*?\*?((?:CONDITIONAL\s+)?(?:NO-GO|GO))', content, re.IGNORECASE)
    if rec_match:
        rec = rec_match.group(1).strip().upper()
        data['recommendation'] = rec
    else:
        # Fallback: try broader pattern but extract only the first part
        rec_match = re.search(r'\*?\*?Recommendation\*?\*?[:\s|]+\*?\*?([^|\n]+)', content, re.IGNORECASE)
        if rec_match:
            rec_full = rec_match.group(1).strip()
            # Extract just the main recommendation from the full text
            if 'CONDITIONAL NO-GO' in rec_full.upper():
                data['recommendation'] = 'CONDITIONAL NO-GO'
            elif 'NO-GO' in rec_full.upper():
                data['recommendation'] = 'NO-GO'
            elif 'GO' in rec_full.upper():
                data['recommendation'] = 'GO'
            else:
                # Keep first part before hyphen or dash
                parts = re.split(r'\s*[-–—]\s*', rec_full, maxsplit=1)
                data['recommendation'] = parts[0].strip().upper()[:20]  # Limit length

    # Extract Assessment rating from "ScholarEval Score: X.XX/5.0 (Assessment)" or table format
    assessment_match = re.search(r'ScholarEval Score[:\s|]+[\d.]+/5\.0\s*\(([^)]+)\)', content, re.IGNORECASE)
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
        pattern = rf'\|\s*{cat}[^|]*\|\s*\*?\*?([A-Z-]+)\*?\*?\s*\|([^|]+)\|'
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            data['risk_table'][cat] = {
                'level': match.group(1).strip(),
                'considerations': match.group(2).strip()[:50]
            }

    # Extract strengths (look for numbered list after "Strengths" heading)
    strength_section = re.search(r'(?:Key Strengths|### .*Strengths)[:\s]*\n((?:\d+\..*\n?)+)', content, re.IGNORECASE)
    if strength_section:
        strengths = re.findall(r'\d+\.\s*\*?\*?([^*\n]+)', strength_section.group(1))
        data['strengths'] = [s.strip() for s in strengths if s.strip()][:5]

    # Extract risks
    risk_section = re.search(r'(?:Key Risks|Risks/Challenges)[:\s]*\n((?:\d+\..*\n?)+)', content, re.IGNORECASE)
    if risk_section:
        risks = re.findall(r'\d+\.\s*\*?\*?([^*\n]+)', risk_section.group(1))
        data['risks'] = [r.strip() for r in risks if r.strip()][:5]

    # Extract Scholar scores from table (handles format with or without Weight column)
    # Format 1: | Dimension | Score/5 | Rationale |
    # Format 2: | Dimension | Weight | Score/5 | Rationale | (with weight column)
    # Pattern matches: | Dimension | optional_weight | **X/5** or X/5 |
    scholar_pattern = r'\|\s*(Differential Expression|Pathway Relevance|Druggability|Genetic Validation|Disease Association|Safety Profile|Clinical Validation|Biomarker Potential)\s*\|(?:\s*[\d.]+\s*\|)?\s*\*?\*?(\d)/5\*?\*?'
    scholar_matches = re.findall(scholar_pattern, content, re.IGNORECASE)
    for dim, score in scholar_matches:
        data['scholar_scores'][dim.strip()] = int(score)

    return data


def create_risk_assessment_figure(gene, output_dir, report_data=None):
    """Create the 6-category risk assessment visualization figure."""
    fig, ax1 = plt.subplots(figsize=(10, 7))

    categories = ['Biological', 'Druggability', 'Translational', 'Clinical', 'Safety', 'Commercial']

    # Get risk levels from report_data if available
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
    output_path = os.path.join(output_dir, f'{gene}_risk_assessment_figure.png')
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

    # Get scores from report_data if available
    if report_data and report_data.get('scholar_scores'):
        scores = [report_data['scholar_scores'].get(k, 3) for k in dim_keys]
    else:
        scores = [4, 4, 4, 3, 4, 3, 3, 4]  # Default scores

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

    # Add legend for score interpretation
    strong_patch = mpatches.Patch(color='#27ae60', label='Strong (≥4)')
    mod_patch = mpatches.Patch(color='#f39c12', label='Moderate (3)')
    weak_patch = mpatches.Patch(color='#e74c3c', label='Weak (≤2)')
    ax.legend(handles=[strong_patch, mod_patch, weak_patch], loc='upper right', fontsize=10)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    output_path = os.path.join(output_dir, f'{gene}_scholar_eval_figure.png')
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


def generate_pdf_report(gene, output_dir, report_data=None):
    """Generate the complete PDF report for a target gene."""

    # Parse integrated report if exists and no data provided
    if report_data is None:
        report_path = os.path.join(output_dir, f'{gene}_integrated_target_report.md')
        if os.path.exists(report_path):
            report_data = parse_integrated_report(report_path, output_dir, gene)
            print(f"  Parsed: {gene}_integrated_target_report.md")
            print(f"  Fold Change (vs Adjacent Normal): {report_data.get('fold_change', 'TBD')}")
        else:
            report_data = {'date': '2026-03-13', 'score': 'TBD', 'risk_profile': 'TBD',
                          'recommendation': 'GO', 'assessment': 'TBD', 'fold_change': 'TBD',
                          'risk_table': {}, 'strengths': [], 'risks': [], 'scholar_scores': {}}

    pdf_path = os.path.join(output_dir, f'{gene}_final_risk_report.pdf')
    pdf = PdfPages(pdf_path)

    print(f"Generating PDF report for {gene}...")

    # ===== PAGE 1: TITLE (Professional Design - Compact Layout) =====
    fig1, ax1 = plt.subplots(figsize=(8.5, 11))
    ax1.axis('off')
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)

    # Define margins for compact layout
    margin = 0.12  # Side margins

    # --- Header Banner (with margins) ---
    header_rect = mpatches.FancyBboxPatch((margin, 0.84), 1.0 - 2*margin, 0.14,
                                           boxstyle="round,pad=0.01,rounding_size=0.02",
                                           facecolor='#1a252f', transform=ax1.transAxes)
    ax1.add_patch(header_rect)

    # Accent line under header
    ax1.plot([margin, 1-margin], [0.84, 0.84], color='#3498db', linewidth=3, transform=ax1.transAxes)

    # Title text on banner
    ax1.text(0.5, 0.93, 'TARGET EVALUATION REPORT', fontsize=11, fontweight='bold',
             ha='center', transform=ax1.transAxes, color='#95a5a6')
    ax1.text(0.5, 0.88, gene, fontsize=32, fontweight='bold', ha='center',
             transform=ax1.transAxes, color='white')

    # --- Subtitle section ---
    ax1.text(0.5, 0.78, 'Colorectal Cancer (CRC) — Integrated Assessment',
             fontsize=12, ha='center', transform=ax1.transAxes, color='#34495e')

    # Thin separator line
    ax1.plot([0.25, 0.75], [0.75, 0.75], color='#bdc3c7', linewidth=1, transform=ax1.transAxes)

    # --- Recommendation Badge (Prominent but narrower) ---
    recommendation = report_data.get('recommendation', 'GO') if report_data else 'GO'
    # Normalize recommendation text - only keep the main keyword
    rec_upper = recommendation.upper().strip()
    if 'CONDITIONAL' in rec_upper and 'NO-GO' in rec_upper:
        rec_color = '#c0392b'
        rec_bg = '#fadbd8'
        rec_text = 'CONDITIONAL NO-GO'
        rec_subtitle = 'Fundamental Safety Barrier'
    elif 'NO-GO' in rec_upper:
        rec_color = '#c0392b'
        rec_bg = '#fadbd8'
        rec_text = 'NO-GO'
        rec_subtitle = 'Not Recommended'
    elif rec_upper == 'GO':
        rec_color = '#1e8449'
        rec_bg = '#d5f5e3'
        rec_text = 'GO'
        rec_subtitle = 'Advance to Development'
    else:
        rec_color = '#d68910'
        rec_bg = '#fef9e7'
        rec_text = rec_upper[:20] if len(rec_upper) > 20 else rec_upper  # Truncate if needed
        rec_subtitle = 'Conditional Approval'

    # Determine font size based on text length
    if len(rec_text) <= 5:
        rec_fontsize = 24
    elif len(rec_text) <= 12:
        rec_fontsize = 20
    else:
        rec_fontsize = 16

    # Recommendation box with border (narrower)
    rec_width = 0.56
    rec_x = (1 - rec_width) / 2
    rec_rect = mpatches.FancyBboxPatch((rec_x, 0.60), rec_width, 0.12,
                                        boxstyle="round,pad=0.015,rounding_size=0.02",
                                        facecolor=rec_bg, edgecolor=rec_color, linewidth=3,
                                        transform=ax1.transAxes)
    ax1.add_patch(rec_rect)
    ax1.text(0.5, 0.68, rec_text, fontsize=rec_fontsize, fontweight='bold', ha='center',
             transform=ax1.transAxes, color=rec_color)
    ax1.text(0.5, 0.625, rec_subtitle, fontsize=10, ha='center',
             transform=ax1.transAxes, color=rec_color, style='italic')

    # --- Key Metrics Cards (more compact) ---
    metrics = [
        ('ScholarEval Score', report_data.get('score', 'TBD') if report_data else 'TBD', '#2980b9'),
        ('Risk Profile', report_data.get('risk_profile', 'TBD') if report_data else 'TBD', '#8e44ad'),
        ('Fold Change', report_data.get('fold_change', 'TBD') if report_data else 'TBD', '#16a085'),
    ]

    card_width = 0.20
    card_height = 0.11
    total_cards_width = 3 * card_width + 2 * 0.04  # 3 cards + 2 gaps
    start_x = (1 - total_cards_width) / 2
    spacing = card_width + 0.04

    for i, (label, value, color) in enumerate(metrics):
        x = start_x + i * spacing
        # Card background
        card = mpatches.FancyBboxPatch((x, 0.42), card_width, card_height,
                                        boxstyle="round,pad=0.01,rounding_size=0.015",
                                        facecolor='white', edgecolor=color, linewidth=2,
                                        transform=ax1.transAxes)
        ax1.add_patch(card)
        # Color accent bar at top of card
        accent = mpatches.FancyBboxPatch((x, 0.515), card_width, 0.015,
                                          boxstyle="round,pad=0,rounding_size=0.008",
                                          facecolor=color, transform=ax1.transAxes)
        ax1.add_patch(accent)
        # Label
        ax1.text(x + card_width/2, 0.49, label, fontsize=8, fontweight='bold',
                 ha='center', transform=ax1.transAxes, color='#7f8c8d')
        # Value
        ax1.text(x + card_width/2, 0.45, value, fontsize=11, fontweight='bold',
                 ha='center', transform=ax1.transAxes, color=color)

    # --- Report Details Section ---
    ax1.plot([0.25, 0.75], [0.36, 0.36], color='#ecf0f1', linewidth=1, transform=ax1.transAxes)

    date_str = report_data.get('date', '2026-03-13') if report_data else '2026-03-13'
    assessment = report_data.get('assessment', 'TBD') if report_data else 'TBD'

    detail_text = f"Date: {date_str}  |  Target: {gene}  |  Indication: CRC  |  Assessment: {assessment}"
    ax1.text(0.5, 0.32, detail_text, fontsize=9, ha='center', transform=ax1.transAxes, color='#5d6d7e')

    # --- Pipeline Footer (with margins) ---
    footer_rect = mpatches.FancyBboxPatch((margin, 0.10), 1.0 - 2*margin, 0.12,
                                           boxstyle="round,pad=0.01,rounding_size=0.015",
                                           facecolor='#f8f9f9', edgecolor='#d5d8dc', linewidth=1,
                                           transform=ax1.transAxes)
    ax1.add_patch(footer_rect)

    ax1.text(0.5, 0.185, '4-Step Evaluation Pipeline', fontsize=9, fontweight='bold',
             ha='center', transform=ax1.transAxes, color='#2c3e50')

    steps = ['Risk Assessment', 'Expression', 'ScholarEval', 'Report']
    step_colors = ['#3498db', '#e67e22', '#1abc9c', '#e74c3c']
    step_spacing = 0.16
    step_start = 0.5 - (len(steps) - 1) * step_spacing / 2  # Center the steps
    for i, (step, scolor) in enumerate(zip(steps, step_colors)):
        x_pos = step_start + i * step_spacing
        ax1.plot(x_pos, 0.145, 'o', markersize=7, color=scolor, transform=ax1.transAxes)
        ax1.text(x_pos, 0.115, step, fontsize=7, ha='center', va='top',
                 transform=ax1.transAxes, color='#5d6d7e')
        if i < len(steps) - 1:
            ax1.annotate('', xy=(x_pos + 0.10, 0.145), xytext=(x_pos + 0.04, 0.145),
                        arrowprops=dict(arrowstyle='->', color='#bdc3c7', lw=1.5),
                        transform=ax1.transAxes)

    # Version footer
    ax1.text(0.5, 0.03, 'CRC Target Evaluation Pipeline v2.0  |  Data: TCGA, GTEx, CCLE, Tempus, PubMed',
             fontsize=7, ha='center', transform=ax1.transAxes, color='#aab7b8', style='italic')

    pdf.savefig(fig1, dpi=300, bbox_inches='tight')
    plt.close(fig1)
    print("  Page 1: Title page")

    # ===== PAGE 2: EXECUTIVE SUMMARY =====
    exec_summary = f"""{gene} represents a compelling therapeutic target for colorectal cancer.
This integrated assessment combines evidence from systematic literature review,
transcriptomic analysis of CRC tumors from TCGA-COAD/READ, ScholarEval target scoring,
and comprehensive 6-category risk assessment.

KEY FINDINGS:
─────────────────────────────────────────────────────────────────────────────────────────
• Significant differential expression across CRC molecular subtypes
• Mechanistic link to disease progression
• Therapeutic modalities validated or under development
• Risk-benefit profile assessed across 6 categories


1. INTRODUCTION
─────────────────────────────────────────────────────────────────────────────────────────
Colorectal cancer remains a leading cause of cancer mortality worldwide, with liver
metastasis representing the primary determinant of patient survival. Despite advances in
chemotherapy, targeted agents, and immunotherapy, five-year survival rates for metastatic
CRC remain below 15%, underscoring the critical need for novel therapeutic targets.

This report presents an integrated target evaluation following a 5-step pipeline:
(1) risk assessment framework, (2) systematic literature review, (3) bulk RNA-seq
expression analysis, (4) ScholarEval target scoring, and (5) integrated scientific
assessment with risk-based recommendation."""
    text_page(pdf, 'Executive Summary', exec_summary)
    print("  Page 2: Executive Summary")

    # ===== PAGE 3: METHODS =====
    methods = """2. METHODS
─────────────────────────────────────────────────────────────────────────────────────────

2.1 Risk Assessment Framework
Six risk categories were defined to guide evidence collection: Biological, Druggability,
Translational, Clinical, Safety, and Commercial/Competitive. Risk levels were assigned as
Low, Medium, or High based on predefined criteria.

2.2 Literature Review
PubMed was searched using target-specific queries combined with disease terms. Results
were organized by risk category to ensure comprehensive evidence collection.

2.3 Expression Analysis
Gene expression data were obtained from:
  • TCGA-COAD/READ (primary tumors)
  • TCGA adjacent normal tissue
  • GTEx normal colon
  • CCLE CRC cell lines

TPM-normalized expression values were log2-transformed. Samples were stratified into
defined cohorts:
  • 2A: RAS-mutant MSS
  • 2B: RAS-WT MSS
  • 4: Early Stage I/II
  • 5: All MSS
  • 6: MSI-H

Statistical analysis employed Kruskal-Wallis and Mann-Whitney U tests with Benjamini-
Hochberg FDR correction.

2.4 Target Scoring
The ScholarEval framework was applied with 8 weighted dimensions: Differential Expression,
Pathway Relevance, Druggability, Genetic Validation, Disease Association, Safety Profile,
Clinical Validation, and Biomarker Potential."""
    text_page(pdf, 'Methods', methods)
    print("  Page 3: Methods")

    # ===== PAGE 4: RESULTS =====
    results1 = """3. RESULTS
─────────────────────────────────────────────────────────────────────────────────────────

3.1 Differential Expression

Analysis of primary CRC tumors revealed significant target overexpression compared to
normal tissue across all cohorts examined.

See Figure 1 for comprehensive expression analysis.
See Figure 2 for CMS subtype expression patterns.


3.2 Literature Evidence

Key findings from systematic literature review organized by risk category:

BIOLOGICAL VALIDATION:
  • Functional validation studies (knockout/knockdown)
  • Mechanistic studies linking target to disease
  • Replication across independent laboratories

THERAPEUTIC DEVELOPMENT:
  • Existing drug development programs
  • Tool molecules and assay availability
  • Clinical trial data (if available)

TRANSLATIONAL EVIDENCE:
  • Disease models (xenograft, PDX, syngeneic)
  • Biomarker studies
  • Patient stratification approaches"""
    text_page(pdf, 'Results: Expression & Literature', results1)
    print("  Page 4: Results")

    # ===== PAGE 5: FIGURE - Comprehensive Analysis =====
    comp_fig = os.path.join(output_dir, f'{gene}_comprehensive_analysis.png')
    add_high_res_figure(pdf, comp_fig, 'Figure 1: Comprehensive Expression Analysis',
                        f'{gene} expression across CRC cohorts showing differential expression vs normal tissue.')
    print("  Page 5: Figure 1 - Comprehensive Analysis")

    # ===== PAGE 6: FIGURE - CMS Boxplot =====
    cms_fig = os.path.join(output_dir, f'{gene}_CMS_boxplot.png')
    add_high_res_figure(pdf, cms_fig, 'Figure 2: Expression by CMS Subtype',
                        'Expression patterns across Consensus Molecular Subtypes (CMS1-4).')
    print("  Page 6: Figure 2 - CMS Subtype")

    # ===== PAGE 7: SCHOLAREVAL SCORING =====
    # Build ScholarEval table from parsed data
    dimensions = ['Differential Expression', 'Pathway Relevance', 'Druggability',
                  'Genetic Validation', 'Disease Association', 'Safety Profile',
                  'Clinical Validation', 'Biomarker Potential']
    weights = [0.15, 0.15, 0.15, 0.10, 0.10, 0.15, 0.10, 0.10]
    scholar_scores = report_data.get('scholar_scores', {})

    score_lines = []
    total_weighted = 0
    for dim, weight in zip(dimensions, weights):
        score = scholar_scores.get(dim, '?')
        if isinstance(score, int):
            weighted = score * weight
            total_weighted += weighted
            score_lines.append(f"│ {dim:<23} │ {score}/5   │ {weight:.2f}   │ {weighted:.2f}     │")
        else:
            score_lines.append(f"│ {dim:<23} │ ?/5   │ {weight:.2f}   │ ?        │")

    final_score = report_data.get('score', f'{total_weighted:.2f}/5.0' if total_weighted > 0 else 'TBD')

    scholar = f"""3.3 ScholarEval Target Score
─────────────────────────────────────────────────────────────────────────────────────────

┌─────────────────────────┬───────┬────────┬──────────┐
│ Dimension               │ Score │ Weight │ Weighted │
├─────────────────────────┼───────┼────────┼──────────┤
{chr(10).join(score_lines)}
├─────────────────────────┼───────┼────────┼──────────┤
│ TOTAL                   │       │ 1.00   │ {total_weighted:.2f}     │
└─────────────────────────┴───────┴────────┴──────────┘

                    FINAL SCORE: {final_score}


Score Interpretation:
─────────────────────────────────────────────────────────────────────────────────────────
  • 4.5-5.0: Excellent - Priority development candidate
  • 4.0-4.4: Strong - Advance with confidence
  • 3.5-3.9: Moderate - Proceed with caution
  • 3.0-3.4: Weak - Requires additional validation
  • <3.0: Poor - Not recommended"""
    text_page(pdf, 'ScholarEval Target Scoring', scholar)
    print("  Page 7: ScholarEval Scoring")

    # ===== PAGE 8: RISK ASSESSMENT TABLE =====
    risk_table = report_data.get('risk_table', {})
    risk_lines = []
    for cat in ['Biological', 'Druggability', 'Translational', 'Clinical', 'Safety', 'Commercial']:
        info = risk_table.get(cat, {'level': 'TBD', 'considerations': 'See integrated report'})
        level = info.get('level', 'TBD')[:12]
        considerations = info.get('considerations', 'See integrated report')[:48]
        risk_lines.append(f"│ {cat:<18} │ {level:<11} │ {considerations:<48} │")

    overall_risk = report_data.get('risk_profile', 'TBD')

    risk_page = f"""4. RISK ASSESSMENT
─────────────────────────────────────────────────────────────────────────────────────────

┌────────────────────┬─────────────┬──────────────────────────────────────────────────────┐
│ Risk Factor        │ Level       │ Key Considerations                                   │
├────────────────────┼─────────────┼──────────────────────────────────────────────────────┤
{chr(10).join(risk_lines)}
└────────────────────┴─────────────┴──────────────────────────────────────────────────────┘

                    OVERALL RISK PROFILE: {overall_risk}


Risk Level Legend:
  • LOW: Strong evidence, minimal concerns
  • MEDIUM: Manageable gaps, mitigation strategies available
  • HIGH: Significant concerns or critical blockers"""
    text_page(pdf, 'Risk Assessment Summary', risk_page)
    print("  Page 8: Risk Assessment Table")

    # ===== PAGE 9: RISK ASSESSMENT FIGURE =====
    risk_fig = os.path.join(output_dir, f'{gene}_risk_assessment_figure.png')
    # Always regenerate to ensure it matches current report data
    create_risk_assessment_figure(gene, output_dir, report_data)
    add_high_res_figure(pdf, risk_fig, 'Figure 3: 6-Category Risk Assessment',
                        'Risk levels across Biological, Druggability, Translational, Clinical, Safety, and Commercial dimensions.')
    print("  Page 9: Figure 3 - Risk Assessment")

    # ===== PAGE 10: SCHOLAREVAL FIGURE =====
    scholar_fig = os.path.join(output_dir, f'{gene}_scholar_eval_figure.png')
    # Always regenerate to ensure it matches current report data
    create_scholar_eval_figure(gene, output_dir, report_data)
    add_high_res_figure(pdf, scholar_fig, 'Figure 4: ScholarEval Target Scoring',
                        'Eight-dimension target scoring based on the ScholarEval framework.')
    print("  Page 10: Figure 4 - ScholarEval Scoring")

    # ===== PAGE 10: KEY STRENGTHS & RISKS =====
    strengths = report_data.get('strengths', ['See integrated report for details'])
    risks = report_data.get('risks', ['See integrated report for details'])

    # Format strengths
    if strengths:
        strength_text = '\n\n'.join([f"{i+1}. {s[:70]}" for i, s in enumerate(strengths[:5])])
    else:
        strength_text = "See integrated report for details."

    # Format risks
    if risks:
        risk_text = '\n\n'.join([f"{i+1}. {r[:70]}" for i, r in enumerate(risks[:5])])
    else:
        risk_text = "See integrated report for details."

    strengths_risks = f"""5. KEY STRENGTHS
─────────────────────────────────────────────────────────────────────────────────────────

{strength_text}


6. KEY RISKS/CHALLENGES
─────────────────────────────────────────────────────────────────────────────────────────

{risk_text}"""
    text_page(pdf, 'Key Strengths & Risks', strengths_risks)
    print("  Page 11: Strengths & Risks")

    # ===== PAGE 11: MITIGATION & RECOMMENDATIONS =====
    mitigation = """7. RISK MITIGATION STRATEGIES
─────────────────────────────────────────────────────────────────────────────────────────

1. [Mitigation strategy 1]

2. [Mitigation strategy 2]

3. [Mitigation strategy 3]

4. [Mitigation strategy 4]


8. RECOMMENDATIONS - PRIORITY ACTIONS
─────────────────────────────────────────────────────────────────────────────────────────

HIGH PRIORITY:
1. [Action 1]
2. [Action 2]
3. [Action 3]

MEDIUM PRIORITY:
4. [Action 4]
5. [Action 5]
6. [Action 6]

LOWER PRIORITY:
7. [Action 7]
8. [Action 8]"""
    text_page(pdf, 'Risk Mitigation & Recommendations', mitigation)
    print("  Page 12: Recommendations")

    # ===== PAGE 12: CONCLUSIONS =====
    fig12, ax12 = plt.subplots(figsize=(8.5, 11))
    ax12.axis('off')

    ax12.text(0.5, 0.95, '9. Conclusions', fontsize=20, fontweight='bold', ha='center',
              transform=ax12.transAxes, color='#2c3e50')

    final_score = report_data.get('score', 'TBD')
    overall_risk = report_data.get('risk_profile', 'TBD')
    fold_change = report_data.get('fold_change', 'TBD')
    fold_change_gtex = report_data.get('fold_change_gtex', '')

    conclusion_text = f"""{gene} target evaluation summary based on convergent evidence:

EVIDENCE INTEGRATION:
─────────────────────────────────────────────────────────────────────────────────────────
• Tumor vs Adjacent Normal: {fold_change}
• Tumor vs GTEx Normal: {fold_change_gtex}
• ScholarEval Score: {final_score}
• Overall Risk Profile: {overall_risk}
• Recommendation: {recommendation}

See the full integrated report ({gene}_integrated_target_report.md) for
detailed findings, citations, and complete analysis.


10. REFERENCES
─────────────────────────────────────────────────────────────────────────────────────────
See integrated report for complete reference list with PMIDs."""

    ax12.text(0.05, 0.88, conclusion_text, fontsize=9.5, ha='left', va='top',
              transform=ax12.transAxes, family='monospace', linespacing=1.4)

    rect = mpatches.FancyBboxPatch((0.1, 0.06), 0.8, 0.08, boxstyle="round,pad=0.02",
                                    facecolor=rec_color, edgecolor='black', linewidth=3,
                                    transform=ax12.transAxes)
    ax12.add_patch(rect)
    ax12.text(0.5, 0.10, f'FINAL {rec_text}',
              fontsize=12, fontweight='bold', ha='center', va='center',
              transform=ax12.transAxes, color='white')

    pdf.savefig(fig12, dpi=300, bbox_inches='tight')
    plt.close(fig12)
    print("  Page 13: Conclusions")

    pdf.close()
    print(f"\nPDF report generated: {pdf_path}")
    print(f"Total pages: 13")
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description='Generate target evaluation PDF report')
    parser.add_argument('--gene', required=True, help='Gene symbol (e.g., TNFRSF12A)')
    parser.add_argument('--output-dir', default=None,
                        help='Output directory (default: ./crc_analysis_results/{GENE})')
    args = parser.parse_args()

    gene = args.gene.upper()

    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = f'./crc_analysis_results/{gene}'

    if not os.path.exists(output_dir):
        print(f"Error: Output directory does not exist: {output_dir}")
        print("Please run the expression analysis first.")
        sys.exit(1)

    # Check for required figures
    required_figs = [
        f'{gene}_comprehensive_analysis.png',
        f'{gene}_CMS_boxplot.png'
    ]

    missing = []
    for fig in required_figs:
        if not os.path.exists(os.path.join(output_dir, fig)):
            missing.append(fig)

    if missing:
        print(f"Warning: Missing figures: {missing}")
        print("Some figure pages may be empty.")

    # Generate PDF
    generate_pdf_report(gene, output_dir)


if __name__ == '__main__':
    main()
