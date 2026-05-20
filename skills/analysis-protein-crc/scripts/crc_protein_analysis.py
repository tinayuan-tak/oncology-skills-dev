#!/usr/bin/env python3
"""
CRC Protein Analysis using Human Protein Atlas data.

Analyzes protein expression data for colorectal cancer target evaluation:
1. Normal tissue IHC (on-target toxicity in GI tract)
2. RNA-Protein correlation
3. Subcellular localization (modality recommendation)
4. CRC prognostic association
5. Tumor protein expression (IHC + CPTAC)

Usage:
    python crc_protein_analysis.py --gene TNFRSF12A --output-dir ./results
    python crc_protein_analysis.py --gene TNFRSF12A --data-dir /path/to/hpa/crc
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import argparse
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ============================================================================
# Configuration
# ============================================================================

# CRC-relevant tissues for on-target toxicity assessment
CRC_TOXICITY_TISSUES = {
    'primary_gi': ['Colon', 'Rectum'],
    'secondary_gi': ['Appendix', 'Small intestine', 'Stomach', 'Duodenum', 'Esophagus'],
    'safety_organs': ['Liver', 'Kidney', 'Heart muscle', 'Lung', 'Bone marrow', 'Pancreas', 'Skin']
}

# Modality recommendation based on subcellular location
MODALITY_MAPPING = {
    'Plasma membrane': {
        'modalities': ['ADC', 'T-cell engager', 'CAR-T', 'Naked antibody'],
        'suitability': 'HIGH',
        'rationale': 'Cell surface accessible for antibody-based therapies'
    },
    'Cell Junctions': {
        'modalities': ['ADC', 'T-cell engager', 'Naked antibody'],
        'suitability': 'HIGH',
        'rationale': 'Accessible at cell-cell junctions'
    },
    'Cytosol': {
        'modalities': ['Small molecule', 'PROTAC/degrader'],
        'suitability': 'MEDIUM',
        'rationale': 'Intracellular - requires cell-penetrating approach'
    },
    'Nucleoplasm': {
        'modalities': ['Small molecule'],
        'suitability': 'LOW',
        'rationale': 'Nuclear localization - limited to small molecules'
    },
    'Mitochondria': {
        'modalities': ['Small molecule'],
        'suitability': 'LOW',
        'rationale': 'Mitochondrial - challenging for biologics'
    },
    'Vesicles': {
        'modalities': ['ADC'],
        'suitability': 'MEDIUM',
        'rationale': 'Vesicular trafficking may support ADC internalization'
    },
    'Endoplasmic reticulum': {
        'modalities': ['Small molecule'],
        'suitability': 'LOW',
        'rationale': 'ER-localized - limited accessibility'
    },
    'Golgi apparatus': {
        'modalities': ['Small molecule'],
        'suitability': 'LOW',
        'rationale': 'Golgi-localized - limited accessibility'
    }
}

# Colors
COLORS = {
    'LOW': '#00843D',      # Green
    'MEDIUM': '#F2A900',   # Amber
    'HIGH': '#E4002B',     # Red
    'DARK_BLUE': '#1B365D',
    'LIGHT_BLUE': '#0077C8',
    'LIGHT_GRAY': '#F5F5F5'
}

# ============================================================================
# Data Loading Functions
# ============================================================================

def load_hpa_data(data_dir: Path) -> Dict[str, pd.DataFrame]:
    """Load all HPA CRC-specific data files."""
    data = {}

    files = {
        'normal_ihc': 'crc_normal_ihc.tsv',
        'rna_tissue': 'crc_rna_tissue.tsv',
        'prognostic': 'crc_prognostic.tsv',
        'cancer_ihc': 'crc_cancer_ihc.tsv',
        'cptac': 'crc_cptac.tsv',
        'subcellular': 'subcellular_location.tsv'
    }

    for key, filename in files.items():
        filepath = data_dir / filename
        if filepath.exists():
            data[key] = pd.read_csv(filepath, sep='\t')
            print(f"  Loaded {filename}: {len(data[key]):,} rows")
        else:
            print(f"  WARNING: {filename} not found")
            data[key] = None

    return data


def get_gene_data(data: Dict[str, pd.DataFrame], gene: str) -> Dict:
    """Extract all data for a specific gene."""
    gene_data = {}

    for key, df in data.items():
        if df is not None:
            # Try matching by Gene name or Gene column
            if 'Gene name' in df.columns:
                gene_df = df[df['Gene name'] == gene]
            elif 'Gene' in df.columns:
                gene_df = df[(df['Gene'] == gene) | (df['Gene'].str.contains(gene, na=False))]
            else:
                gene_df = pd.DataFrame()

            gene_data[key] = gene_df

    return gene_data


# ============================================================================
# Analysis Functions
# ============================================================================

def analyze_normal_tissue_toxicity(gene_data: Dict, gene: str) -> Dict:
    """Analyze normal tissue IHC for on-target toxicity assessment."""
    result = {
        'gene': gene,
        'primary_gi': [],
        'secondary_gi': [],
        'safety_organs': [],
        'gi_toxicity_risk': 'UNKNOWN',
        'overall_toxicity_risk': 'UNKNOWN'
    }

    df = gene_data.get('normal_ihc')
    if df is None or len(df) == 0:
        return result

    # Analyze each tissue category
    for category, tissues in CRC_TOXICITY_TISSUES.items():
        tissue_results = []
        for tissue in tissues:
            tissue_df = df[df['Tissue'] == tissue]
            for _, row in tissue_df.iterrows():
                tissue_results.append({
                    'tissue': tissue,
                    'cell_type': row.get('Cell type', 'Unknown'),
                    'level': row.get('Level', 'Unknown'),
                    'reliability': row.get('Reliability', 'Unknown')
                })
        result[category] = tissue_results

    # Determine GI toxicity risk (based on colon/rectum)
    gi_levels = []
    for item in result['primary_gi']:
        if item['level'] in ['High', 'Medium', 'Low', 'Not detected']:
            gi_levels.append(item['level'])

    if 'High' in gi_levels:
        result['gi_toxicity_risk'] = 'HIGH'
    elif 'Medium' in gi_levels:
        result['gi_toxicity_risk'] = 'MEDIUM'
    elif gi_levels:
        result['gi_toxicity_risk'] = 'LOW'

    # Determine overall toxicity risk
    all_levels = gi_levels.copy()
    for item in result['safety_organs']:
        if item['level'] in ['High', 'Medium', 'Low', 'Not detected']:
            all_levels.append(item['level'])

    high_count = all_levels.count('High')
    medium_count = all_levels.count('Medium')

    if high_count >= 3:
        result['overall_toxicity_risk'] = 'HIGH'
    elif high_count >= 1 or medium_count >= 5:
        result['overall_toxicity_risk'] = 'MEDIUM'
    else:
        result['overall_toxicity_risk'] = 'LOW'

    return result


def analyze_rna_protein_correlation(gene_data: Dict, gene: str) -> Dict:
    """Analyze RNA-protein correlation for GI tissues."""
    result = {
        'gene': gene,
        'correlations': [],
        'concordance_rate': None,
        'discordant_tissues': []
    }

    rna_df = gene_data.get('rna_tissue')
    ihc_df = gene_data.get('normal_ihc')

    if rna_df is None or ihc_df is None:
        return result

    if len(rna_df) == 0 or len(ihc_df) == 0:
        return result

    # Map IHC levels to numeric for comparison
    level_map = {'High': 3, 'Medium': 2, 'Low': 1, 'Not detected': 0}

    # Get unique tissues from RNA data
    concordant = 0
    total = 0

    for _, rna_row in rna_df.iterrows():
        tissue = rna_row['Tissue']
        ntpm = rna_row['nTPM']

        # Find matching IHC data (case-insensitive tissue match)
        ihc_tissue = ihc_df[ihc_df['Tissue'].str.lower() == tissue.lower()]

        if len(ihc_tissue) > 0:
            # Get max IHC level for this tissue
            max_level = 'Not detected'
            for _, ihc_row in ihc_tissue.iterrows():
                level = ihc_row.get('Level', 'Not detected')
                if level_map.get(level, 0) > level_map.get(max_level, 0):
                    max_level = level

            # Determine concordance
            # High RNA (>50 nTPM) should have Medium/High IHC
            # Low RNA (<10 nTPM) should have Low/Not detected IHC
            if ntpm > 50:
                expected_ihc = ['Medium', 'High']
            elif ntpm < 10:
                expected_ihc = ['Not detected', 'Low']
            else:
                expected_ihc = ['Low', 'Medium']

            is_concordant = max_level in expected_ihc

            result['correlations'].append({
                'tissue': tissue,
                'rna_ntpm': ntpm,
                'ihc_level': max_level,
                'concordant': is_concordant
            })

            if is_concordant:
                concordant += 1
            else:
                result['discordant_tissues'].append(tissue)
            total += 1

    if total > 0:
        result['concordance_rate'] = concordant / total

    return result


def analyze_subcellular_location(gene_data: Dict, gene: str) -> Dict:
    """Analyze subcellular location for modality recommendation."""
    result = {
        'gene': gene,
        'main_locations': [],
        'additional_locations': [],
        'reliability': 'Unknown',
        'recommended_modalities': [],
        'modality_suitability': 'UNKNOWN',
        'is_surface_target': False,
        'rationale': ''
    }

    df = gene_data.get('subcellular')
    if df is None or len(df) == 0:
        return result

    row = df.iloc[0]

    # Parse locations
    main_loc = row.get('Main location', '')
    if pd.notna(main_loc) and main_loc:
        result['main_locations'] = [loc.strip() for loc in str(main_loc).split(';')]

    add_loc = row.get('Additional location', '')
    if pd.notna(add_loc) and add_loc:
        result['additional_locations'] = [loc.strip() for loc in str(add_loc).split(';')]

    result['reliability'] = row.get('Reliability', 'Unknown')

    # Check if surface target
    surface_locations = ['Plasma membrane', 'Cell Junctions']
    all_locations = result['main_locations'] + result['additional_locations']

    result['is_surface_target'] = any(loc in surface_locations for loc in all_locations)

    # Determine recommended modalities based on primary location
    modalities = set()
    best_suitability = 'LOW'
    rationales = []

    for loc in result['main_locations']:
        if loc in MODALITY_MAPPING:
            mapping = MODALITY_MAPPING[loc]
            modalities.update(mapping['modalities'])
            rationales.append(f"{loc}: {mapping['rationale']}")

            # Update suitability (HIGH > MEDIUM > LOW)
            if mapping['suitability'] == 'HIGH':
                best_suitability = 'HIGH'
            elif mapping['suitability'] == 'MEDIUM' and best_suitability != 'HIGH':
                best_suitability = 'MEDIUM'

    result['recommended_modalities'] = list(modalities)
    result['modality_suitability'] = best_suitability
    result['rationale'] = '; '.join(rationales)

    return result


def analyze_prognostic(gene_data: Dict, gene: str) -> Dict:
    """Analyze CRC prognostic association."""
    result = {
        'gene': gene,
        'prognostic_cancers': [],
        'is_prognostic': False,
        'direction': None
    }

    df = gene_data.get('prognostic')
    if df is None or len(df) == 0:
        return result

    # Define prognostic columns
    prog_cols = {
        'favorable': ['potential prognostic - favorable', 'validated prognostic - favorable'],
        'unfavorable': ['potential prognostic - unfavorable', 'validated prognostic - unfavorable']
    }

    for _, row in df.iterrows():
        cancer = row.get('Cancer', 'Unknown')
        prog_info = {'cancer': cancer, 'prognostic': False, 'direction': None, 'p_value': None, 'validated': False}

        # Check favorable
        for col in prog_cols['favorable']:
            if col in row and pd.notna(row[col]):
                prog_info['prognostic'] = True
                prog_info['direction'] = 'favorable'
                prog_info['p_value'] = row[col]
                prog_info['validated'] = 'validated' in col
                break

        # Check unfavorable (overrides favorable if present)
        for col in prog_cols['unfavorable']:
            if col in row and pd.notna(row[col]):
                prog_info['prognostic'] = True
                prog_info['direction'] = 'unfavorable'
                prog_info['p_value'] = row[col]
                prog_info['validated'] = 'validated' in col
                break

        if prog_info['prognostic']:
            result['prognostic_cancers'].append(prog_info)
            result['is_prognostic'] = True
            result['direction'] = prog_info['direction']

    return result


def analyze_tumor_expression(gene_data: Dict, gene: str) -> Dict:
    """Analyze tumor protein expression from IHC and CPTAC."""
    result = {
        'gene': gene,
        'ihc': None,
        'cptac': None
    }

    # IHC tumor data
    ihc_df = gene_data.get('cancer_ihc')
    if ihc_df is not None and len(ihc_df) > 0:
        row = ihc_df.iloc[0]
        result['ihc'] = {
            'cancer': row.get('Cancer', 'colorectal cancer'),
            'high': row.get('High', 0),
            'medium': row.get('Medium', 0),
            'low': row.get('Low', 0),
            'not_detected': row.get('Not detected', 0)
        }

    # CPTAC proteomics
    cptac_df = gene_data.get('cptac')
    if cptac_df is not None and len(cptac_df) > 0:
        cptac_results = []
        for _, row in cptac_df.iterrows():
            cptac_results.append({
                'cancer': row.get('Cancer', 'Colon AC'),
                'logFC': row.get('logFC', 0),
                'p_adj': row.get('p-value adjusted', 1)
            })
        result['cptac'] = cptac_results

    return result


def analyze_tumor_vs_normal_protein(gene_data: Dict, gene: str) -> Dict:
    """
    Compare tumor vs normal protein expression (IHC-based).

    This is the protein-level equivalent of tumor vs adjacent normal RNA comparison.
    """
    result = {
        'gene': gene,
        'normal_colon_ihc': {'high': 0, 'medium': 0, 'low': 0, 'not_detected': 0, 'total': 0},
        'tumor_ihc': {'high': 0, 'medium': 0, 'low': 0, 'not_detected': 0, 'total': 0},
        'cptac_logfc': None,
        'cptac_pvalue': None,
        'protein_enrichment': 'UNKNOWN',
        'enrichment_score': None,
        'interpretation': ''
    }

    # Get normal colon IHC (glandular cells as primary)
    normal_df = gene_data.get('normal_ihc')
    if normal_df is not None and len(normal_df) > 0:
        colon_df = normal_df[normal_df['Tissue'] == 'Colon']

        # Count IHC levels across all colon cell types
        level_counts = {'High': 0, 'Medium': 0, 'Low': 0, 'Not detected': 0}
        for _, row in colon_df.iterrows():
            level = row.get('Level', 'Unknown')
            if level in level_counts:
                level_counts[level] += 1

        result['normal_colon_ihc'] = {
            'high': level_counts['High'],
            'medium': level_counts['Medium'],
            'low': level_counts['Low'],
            'not_detected': level_counts['Not detected'],
            'total': sum(level_counts.values())
        }

        # Get the predominant level for glandular cells (most relevant for CRC)
        glandular = colon_df[colon_df['Cell type'].str.contains('glandular', case=False, na=False)]
        if len(glandular) > 0:
            result['normal_glandular_level'] = glandular.iloc[0].get('Level', 'Unknown')
        else:
            result['normal_glandular_level'] = 'Unknown'

    # Get tumor IHC
    tumor_df = gene_data.get('cancer_ihc')
    if tumor_df is not None and len(tumor_df) > 0:
        row = tumor_df.iloc[0]
        result['tumor_ihc'] = {
            'high': int(row.get('High', 0)),
            'medium': int(row.get('Medium', 0)),
            'low': int(row.get('Low', 0)),
            'not_detected': int(row.get('Not detected', 0)),
            'total': int(row.get('High', 0)) + int(row.get('Medium', 0)) + int(row.get('Low', 0)) + int(row.get('Not detected', 0))
        }

    # Get CPTAC (quantitative tumor vs normal)
    cptac_df = gene_data.get('cptac')
    if cptac_df is not None and len(cptac_df) > 0:
        row = cptac_df.iloc[0]
        result['cptac_logfc'] = row.get('logFC', None)
        result['cptac_pvalue'] = row.get('p-value adjusted', None)

    # Calculate protein enrichment score
    # Convert IHC levels to numeric: High=3, Medium=2, Low=1, Not detected=0
    level_scores = {'high': 3, 'medium': 2, 'low': 1, 'not_detected': 0}

    # Normal score (weighted average)
    normal = result['normal_colon_ihc']
    if normal['total'] > 0:
        normal_score = (normal['high']*3 + normal['medium']*2 + normal['low']*1 + normal['not_detected']*0) / normal['total']
    else:
        normal_score = None

    # Tumor score (weighted average)
    tumor = result['tumor_ihc']
    if tumor['total'] > 0:
        tumor_score = (tumor['high']*3 + tumor['medium']*2 + tumor['low']*1 + tumor['not_detected']*0) / tumor['total']
    else:
        tumor_score = None

    # Calculate enrichment
    if normal_score is not None and tumor_score is not None:
        result['normal_score'] = normal_score
        result['tumor_score'] = tumor_score
        result['enrichment_score'] = tumor_score - normal_score

        # Add distribution data for figure (counts)
        result['normal_ihc_distribution'] = {
            'High': normal['high'],
            'Medium': normal['medium'],
            'Low': normal['low'],
            'Not detected': normal['not_detected']
        }
        result['tumor_ihc_distribution'] = {
            'High': tumor['high'],
            'Medium': tumor['medium'],
            'Low': tumor['low'],
            'Not detected': tumor['not_detected']
        }

        # Determine enrichment level
        if result['enrichment_score'] >= 1.5:
            result['protein_enrichment'] = 'HIGH'
            result['interpretation'] = 'Strong tumor enrichment at protein level - favorable therapeutic window'
        elif result['enrichment_score'] >= 0.5:
            result['protein_enrichment'] = 'MEDIUM'
            result['interpretation'] = 'Moderate tumor enrichment at protein level'
        elif result['enrichment_score'] >= 0:
            result['protein_enrichment'] = 'LOW'
            result['interpretation'] = 'Minimal tumor enrichment at protein level - toxicity concern'
        else:
            result['protein_enrichment'] = 'NEGATIVE'
            result['interpretation'] = 'Lower in tumor than normal - not suitable for this indication'

    # Use CPTAC if available (more quantitative)
    if result['cptac_logfc'] is not None:
        if result['cptac_logfc'] >= 1.0:
            result['protein_enrichment'] = 'HIGH'
            result['interpretation'] = f"CPTAC: {result['cptac_logfc']:.2f} log2FC tumor vs normal - strong enrichment"
        elif result['cptac_logfc'] >= 0.5:
            result['protein_enrichment'] = 'MEDIUM'
            result['interpretation'] = f"CPTAC: {result['cptac_logfc']:.2f} log2FC tumor vs normal - moderate enrichment"
        elif result['cptac_logfc'] >= 0:
            result['protein_enrichment'] = 'LOW'
            result['interpretation'] = f"CPTAC: {result['cptac_logfc']:.2f} log2FC - minimal enrichment"
        else:
            result['protein_enrichment'] = 'NEGATIVE'
            result['interpretation'] = f"CPTAC: {result['cptac_logfc']:.2f} log2FC - lower in tumor"

    return result


# ============================================================================
# Report Generation
# ============================================================================

def generate_protein_report(gene: str, analyses: Dict, output_dir: Path) -> str:
    """Generate markdown report for protein analysis."""

    tox = analyses['toxicity']
    corr = analyses['correlation']
    sub = analyses['subcellular']
    prog = analyses['prognostic']
    tumor = analyses['tumor']
    tvn = analyses['tumor_vs_normal']

    # Determine protein enrichment icon
    enrich = tvn['protein_enrichment']
    enrich_icon = '✅ Favorable' if enrich == 'HIGH' else '⚠️ Moderate' if enrich == 'MEDIUM' else '❌ Concern' if enrich in ['LOW', 'NEGATIVE'] else 'Unknown'

    report = f"""# {gene} Protein Analysis: CRC

**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}
**Data Source:** Human Protein Atlas v25

---

## Executive Summary

| Metric | Value | Risk/Suitability |
|--------|-------|------------------|
| **Protein Tumor Enrichment** | {tvn['protein_enrichment']} (Score: {tvn.get('enrichment_score', 'N/A') if tvn.get('enrichment_score') is None else f"{tvn['enrichment_score']:.2f}"}) | {enrich_icon} |
| **GI Toxicity Risk** | {tox['gi_toxicity_risk']} | {'✅ Favorable' if tox['gi_toxicity_risk'] == 'LOW' else '⚠️ Monitor' if tox['gi_toxicity_risk'] == 'MEDIUM' else '❌ Concern'} |
| **Overall Toxicity Risk** | {tox['overall_toxicity_risk']} | {'✅ Favorable' if tox['overall_toxicity_risk'] == 'LOW' else '⚠️ Monitor' if tox['overall_toxicity_risk'] == 'MEDIUM' else '❌ Concern'} |
| **Surface Target** | {'Yes' if sub['is_surface_target'] else 'No'} | {'✅ ADC/Engager suitable' if sub['is_surface_target'] else '⚠️ Consider small molecule'} |
| **RNA-Protein Concordance** | {f"{corr['concordance_rate']*100:.0f}%" if corr['concordance_rate'] else 'N/A'} | {'✅ High' if corr['concordance_rate'] and corr['concordance_rate'] > 0.7 else '⚠️ Check discordant tissues'} |
| **CRC Prognostic** | {'Yes' if prog['is_prognostic'] else 'No'} | {f"High expr = {prog['direction']}" if prog['is_prognostic'] else 'Not prognostic'} |

---

## 1. Protein-Level Tumor vs Normal (Therapeutic Window)

### IHC Comparison: Normal Colon vs CRC Tumor

| IHC Level | Normal Colon | Tumor (CRC) | Interpretation |
|-----------|--------------|-------------|----------------|
| **High** | {tvn['normal_colon_ihc']['high']} ({100*tvn['normal_colon_ihc']['high']/tvn['normal_colon_ihc']['total']:.0f}% of {tvn['normal_colon_ihc']['total']} cell types) | {tvn['tumor_ihc']['high']} ({100*tvn['tumor_ihc']['high']/tvn['tumor_ihc']['total']:.0f}% of {tvn['tumor_ihc']['total']} patients) | {'↑ Tumor' if tvn['tumor_ihc']['high'] > tvn['normal_colon_ihc']['high'] else '↓ Tumor' if tvn['tumor_ihc']['high'] < tvn['normal_colon_ihc']['high'] else '='} |
| **Medium** | {tvn['normal_colon_ihc']['medium']} ({100*tvn['normal_colon_ihc']['medium']/tvn['normal_colon_ihc']['total']:.0f}%) | {tvn['tumor_ihc']['medium']} ({100*tvn['tumor_ihc']['medium']/tvn['tumor_ihc']['total']:.0f}%) | {'↑ Tumor' if tvn['tumor_ihc']['medium'] > tvn['normal_colon_ihc']['medium'] else '↓ Tumor' if tvn['tumor_ihc']['medium'] < tvn['normal_colon_ihc']['medium'] else '='} |
| **Low** | {tvn['normal_colon_ihc']['low']} ({100*tvn['normal_colon_ihc']['low']/tvn['normal_colon_ihc']['total']:.0f}%) | {tvn['tumor_ihc']['low']} ({100*tvn['tumor_ihc']['low']/tvn['tumor_ihc']['total']:.0f}%) | - |
| **Not detected** | {tvn['normal_colon_ihc']['not_detected']} ({100*tvn['normal_colon_ihc']['not_detected']/tvn['normal_colon_ihc']['total']:.0f}%) | {tvn['tumor_ihc']['not_detected']} ({100*tvn['tumor_ihc']['not_detected']/tvn['tumor_ihc']['total']:.0f}%) | - |

**Normal Colon Glandular Cells:** {tvn.get('normal_glandular_level', 'Unknown')}

### IHC Score (Quantitative)

| Metric | Normal Colon | Tumor | Difference |
|--------|--------------|-------|------------|
| **IHC Score** | {tvn.get('normal_score', 0):.2f} | {tvn.get('tumor_score', 0):.2f} | **{'+' if tvn.get('enrichment_score', 0) >= 0 else ''}{tvn.get('enrichment_score', 0):.2f}** |

*IHC Score: High=3, Medium=2, Low=1, Not detected=0 (weighted average)*

### Enrichment Criteria

| Enrichment Level | IHC Score Difference | CPTAC logFC | Interpretation |
|------------------|---------------------|-------------|----------------|
| **HIGH** | ≥ 1.5 | ≥ 1.0 | Strong tumor enrichment - favorable therapeutic window |
| **MEDIUM** | 0.5 - 1.5 | 0.5 - 1.0 | Moderate enrichment - acceptable window |
| **LOW** | 0 - 0.5 | 0 - 0.5 | Minimal enrichment - toxicity concern |
| **NEGATIVE** | < 0 | < 0 | Lower in tumor - not suitable |

**Result: {tvn['protein_enrichment']}** - {tvn['interpretation']}
"""

    # Add CPTAC if available
    if tvn['cptac_logfc'] is not None:
        report += f"""
### CPTAC Mass Spectrometry (Tumor vs Matched Normal)

| Cancer | logFC | p-adj | Direction |
|--------|-------|-------|-----------|
| Colon AC | {tvn['cptac_logfc']:.2f} | {tvn['cptac_pvalue']:.2e} | {'↑ Tumor enriched' if tvn['cptac_logfc'] > 0 else '↓ Lower in tumor'} |

*CPTAC provides quantitative proteomics comparison between tumor and matched adjacent normal tissue.*
"""
    else:
        report += """
### CPTAC Mass Spectrometry

*No CPTAC data available for this gene in CRC.*
"""

    report += """
---

## 2. Normal Tissue Protein Expression (On-Target Toxicity)

### Primary GI Tract (Colon/Rectum)

| Tissue | Cell Type | IHC Level | Reliability |
|--------|-----------|-----------|-------------|
"""

    for item in tox['primary_gi']:
        level_icon = '✅' if item['level'] in ['Not detected', 'Low'] else '⚠️' if item['level'] == 'Medium' else '❌'
        report += f"| {item['tissue']} | {item['cell_type']} | {item['level']} {level_icon} | {item['reliability']} |\n"

    if not tox['primary_gi']:
        report += "| No data available | - | - | - |\n"

    report += f"""
**GI Toxicity Risk: {tox['gi_toxicity_risk']}**

### Secondary GI Tract

| Tissue | Cell Type | IHC Level | Reliability |
|--------|-----------|-----------|-------------|
"""

    for item in tox['secondary_gi'][:10]:  # Limit to 10 rows
        report += f"| {item['tissue']} | {item['cell_type']} | {item['level']} | {item['reliability']} |\n"

    report += f"""
### Major Safety Organs

| Tissue | Cell Type | IHC Level | Reliability |
|--------|-----------|-----------|-------------|
"""

    for item in tox['safety_organs'][:15]:  # Limit to 15 rows
        level_icon = '✅' if item['level'] in ['Not detected', 'Low'] else '⚠️' if item['level'] == 'Medium' else '❌'
        report += f"| {item['tissue']} | {item['cell_type']} | {item['level']} {level_icon} | {item['reliability']} |\n"

    report += f"""
**Overall Toxicity Risk: {tox['overall_toxicity_risk']}**

---

## 2. RNA-Protein Concordance

"""

    if corr['concordance_rate'] is not None:
        report += f"**Concordance Rate: {corr['concordance_rate']*100:.0f}%**\n\n"

        if corr['discordant_tissues']:
            report += f"**Discordant Tissues:** {', '.join(corr['discordant_tissues'])}\n\n"

        report += """| Tissue | RNA (nTPM) | IHC Level | Concordant |
|--------|------------|-----------|------------|
"""
        for item in corr['correlations'][:15]:
            conc_icon = '✅' if item['concordant'] else '⚠️'
            report += f"| {item['tissue']} | {item['rna_ntpm']:.1f} | {item['ihc_level']} | {conc_icon} |\n"
    else:
        report += "No RNA-protein correlation data available.\n"

    report += f"""
---

## 3. Subcellular Localization & Modality Recommendation

### Location

| Category | Locations |
|----------|-----------|
| **Main Location** | {', '.join(sub['main_locations']) if sub['main_locations'] else 'Unknown'} |
| **Additional Location** | {', '.join(sub['additional_locations']) if sub['additional_locations'] else 'None'} |
| **Reliability** | {sub['reliability']} |

### Modality Recommendation

| Metric | Value |
|--------|-------|
| **Surface Target** | {'✅ Yes' if sub['is_surface_target'] else '❌ No'} |
| **Modality Suitability** | {sub['modality_suitability']} |
| **Recommended Modalities** | {', '.join(sub['recommended_modalities']) if sub['recommended_modalities'] else 'Undetermined'} |

**Rationale:** {sub['rationale'] if sub['rationale'] else 'N/A'}

"""

    # Modality decision tree
    if sub['is_surface_target']:
        report += """### Modality Decision

```
Surface Target: YES
├── ADC: ✅ RECOMMENDED (internalization expected)
├── T-cell engager: ✅ SUITABLE
├── CAR-T: ✅ SUITABLE
└── Naked antibody: ✅ SUITABLE
```
"""
    else:
        report += """### Modality Decision

```
Surface Target: NO
├── ADC: ⚠️ VERIFY membrane trafficking
├── T-cell engager: ❌ NOT RECOMMENDED
├── Small molecule: ✅ CONSIDER
└── PROTAC/Degrader: ✅ CONSIDER
```
"""

    report += f"""
---

## 4. CRC Prognostic Association

"""

    if prog['is_prognostic']:
        report += """| Cancer | Direction | p-value | Validated |
|--------|-----------|---------|-----------|
"""
        for item in prog['prognostic_cancers']:
            val_icon = '✅' if item['validated'] else ''
            report += f"| {item['cancer']} | {item['direction']} | {item['p_value']} | {val_icon} |\n"

        report += f"\n**Interpretation:** High {gene} expression is associated with **{prog['direction']}** prognosis in CRC.\n"
    else:
        report += "No significant prognostic association found in CRC.\n"

    report += f"""
---

## 5. Tumor Protein Expression

### IHC (Tissue Microarray)

"""

    if tumor['ihc']:
        ihc = tumor['ihc']
        total = ihc['high'] + ihc['medium'] + ihc['low'] + ihc['not_detected']
        report += f"""| Cancer | High | Medium | Low | Not Detected | Total |
|--------|------|--------|-----|--------------|-------|
| {ihc['cancer']} | {ihc['high']} ({100*ihc['high']/total:.0f}%) | {ihc['medium']} ({100*ihc['medium']/total:.0f}%) | {ihc['low']} ({100*ihc['low']/total:.0f}%) | {ihc['not_detected']} ({100*ihc['not_detected']/total:.0f}%) | {total} |

**IHC Positive Rate:** {100*(ihc['high']+ihc['medium']+ihc['low'])/total:.0f}%
"""
    else:
        report += "No tumor IHC data available.\n"

    report += """
### CPTAC Mass Spectrometry (Tumor vs Normal)

"""

    if tumor['cptac']:
        report += """| Cancer | logFC | p-adj | Direction |
|--------|-------|-------|-----------|
"""
        for item in tumor['cptac']:
            direction = '↑ Tumor' if item['logFC'] > 0 else '↓ Tumor'
            sig = '***' if item['p_adj'] < 0.001 else '**' if item['p_adj'] < 0.01 else '*' if item['p_adj'] < 0.05 else ''
            report += f"| {item['cancer']} | {item['logFC']:.2f} | {item['p_adj']:.2e}{sig} | {direction} |\n"
    else:
        report += "No CPTAC data available for CRC.\n"

    report += """
---

## 6. Summary & Recommendations

"""

    # Generate recommendations based on all analyses
    recommendations = []

    if tox['gi_toxicity_risk'] == 'LOW':
        recommendations.append(f"✅ **LOW GI toxicity risk** - {gene} shows minimal expression in colon/rectum normal tissue")
    elif tox['gi_toxicity_risk'] == 'MEDIUM':
        recommendations.append(f"⚠️ **MEDIUM GI toxicity risk** - Monitor for GI adverse events in clinical development")
    else:
        recommendations.append(f"❌ **HIGH GI toxicity risk** - Consider patient selection or dose optimization strategies")

    if sub['is_surface_target']:
        recommendations.append(f"✅ **Surface target confirmed** - ADC and T-cell engager modalities are suitable")
    else:
        recommendations.append(f"⚠️ **Not a canonical surface target** - Verify membrane localization; consider small molecule approaches")

    if prog['is_prognostic'] and prog['direction'] == 'unfavorable':
        recommendations.append(f"✅ **Prognostic validation** - High {gene} correlates with worse CRC outcome, supporting therapeutic relevance")

    if corr['concordance_rate'] and corr['concordance_rate'] < 0.7:
        recommendations.append(f"⚠️ **RNA-Protein discordance** - Validate protein expression in target tissues; RNA may not predict protein levels")

    for rec in recommendations:
        report += f"- {rec}\n"

    report += "\n---\n\n*Report generated by CRC Protein Analysis Skill using Human Protein Atlas v25 data.*\n"

    return report


def generate_protein_figure(gene: str, analyses: Dict, output_dir: Path):
    """Generate summary figure for protein analysis."""

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle(f'{gene} Protein Analysis: CRC', fontsize=16, fontweight='bold')

    tox = analyses['toxicity']
    corr = analyses['correlation']
    sub = analyses['subcellular']
    prog = analyses['prognostic']
    tumor = analyses['tumor']
    tvn = analyses.get('tumor_vs_normal', {})

    # Panel A: Tumor vs Normal IHC Level Distribution (categorical - as provided by HPA)
    ax = axes[0, 0]
    if tvn and tvn.get('normal_ihc_distribution') and tvn.get('tumor_ihc_distribution'):
        # Show IHC level counts as grouped bar chart
        categories = ['High', 'Medium', 'Low', 'Not det.']
        x = np.arange(len(categories))
        width = 0.35

        normal_dist = tvn['normal_ihc_distribution']
        tumor_dist = tvn['tumor_ihc_distribution']
        normal_vals = [normal_dist.get('High', 0), normal_dist.get('Medium', 0),
                       normal_dist.get('Low', 0), normal_dist.get('Not detected', 0)]
        tumor_vals = [tumor_dist.get('High', 0), tumor_dist.get('Medium', 0),
                      tumor_dist.get('Low', 0), tumor_dist.get('Not detected', 0)]

        bars1 = ax.bar(x - width/2, normal_vals, width, label='Normal (cell types)', color='#0077C8', edgecolor='black')
        bars2 = ax.bar(x + width/2, tumor_vals, width, label='Tumor (patients)', color='#E4002B', edgecolor='black')

        ax.set_ylabel('Count')
        ax.set_xticks(x)
        ax.set_xticklabels(categories, fontsize=9)
        ax.legend(fontsize=8, loc='upper right')

        # Add IHC-based enrichment annotation
        score_diff = tvn.get('enrichment_score', 0) or 0
        normal_score = tvn.get('normal_score', 0) or 0
        tumor_score = tvn.get('tumor_score', 0) or 0
        # Determine IHC-based enrichment level
        if score_diff >= 1.5:
            ihc_enrichment = 'HIGH'
        elif score_diff >= 0.5:
            ihc_enrichment = 'MEDIUM'
        elif score_diff >= 0:
            ihc_enrichment = 'LOW'
        else:
            ihc_enrichment = 'NEGATIVE'
        ax.text(0.02, 0.98, f'IHC Δ: {score_diff:+.2f} ({ihc_enrichment})',
                transform=ax.transAxes, ha='left', va='top', fontsize=9,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))
        # Add IHC score formula
        ax.text(0.5, -0.18, f'Score = (H×3 + M×2 + L×1 + ND×0) / Total\nNormal={normal_score:.2f}, Tumor={tumor_score:.2f}',
                transform=ax.transAxes, ha='center', va='top', fontsize=7,
                style='italic', color='gray')
        ax.set_title('IHC Level: Tumor vs Normal', fontweight='bold')
    else:
        # Fallback: GI Tissue IHC
        levels = {'High': 0, 'Medium': 0, 'Low': 0, 'Not detected': 0}
        for item in tox['primary_gi'] + tox['secondary_gi']:
            if item['level'] in levels:
                levels[item['level']] += 1
        colors = ['#E4002B', '#F2A900', '#0077C8', '#00843D']
        ax.bar(levels.keys(), levels.values(), color=colors)
        ax.set_ylabel('Number of cell types')
        ax.set_xlabel('IHC Level')
        ax.set_title('GI Tissue IHC', fontweight='bold')

    # Panel B: Toxicity Risk
    ax = axes[0, 1]
    ax.axis('off')

    gi_color = COLORS.get(tox['gi_toxicity_risk'], '#888888')
    overall_color = COLORS.get(tox['overall_toxicity_risk'], '#888888')

    ax.text(0.5, 0.7, 'GI Toxicity Risk', ha='center', fontsize=12, fontweight='bold')
    ax.text(0.5, 0.55, tox['gi_toxicity_risk'], ha='center', fontsize=24, fontweight='bold', color=gi_color)
    ax.text(0.5, 0.3, 'Overall Toxicity Risk', ha='center', fontsize=12, fontweight='bold')
    ax.text(0.5, 0.15, tox['overall_toxicity_risk'], ha='center', fontsize=24, fontweight='bold', color=overall_color)
    ax.set_title('Toxicity Assessment', fontweight='bold')

    # Panel C: Subcellular Location
    ax = axes[0, 2]
    ax.axis('off')

    locations = sub['main_locations'][:3] if sub['main_locations'] else ['Unknown']
    y_pos = 0.8
    ax.text(0.5, 0.95, 'Subcellular Location', ha='center', fontsize=12, fontweight='bold')
    for loc in locations:
        ax.text(0.5, y_pos, f"• {loc}", ha='center', fontsize=11)
        y_pos -= 0.15

    ax.text(0.5, 0.35, 'Surface Target:', ha='center', fontsize=11, fontweight='bold')
    surface_text = 'YES ✓' if sub['is_surface_target'] else 'NO ✗'
    surface_color = '#00843D' if sub['is_surface_target'] else '#E4002B'
    ax.text(0.5, 0.2, surface_text, ha='center', fontsize=16, fontweight='bold', color=surface_color)
    ax.set_title('Modality Suitability', fontweight='bold')

    # Panel D: RNA-Protein Correlation
    ax = axes[1, 0]
    if corr['correlations']:
        rna_vals = [c['rna_ntpm'] for c in corr['correlations']]
        ihc_numeric = {'High': 3, 'Medium': 2, 'Low': 1, 'Not detected': 0}
        ihc_vals = [ihc_numeric.get(c['ihc_level'], 0) for c in corr['correlations']]
        colors = ['#00843D' if c['concordant'] else '#E4002B' for c in corr['correlations']]
        ax.scatter(rna_vals, ihc_vals, c=colors, alpha=0.7, s=50)
        ax.set_xlabel('RNA (nTPM)')
        ax.set_ylabel('IHC Level')
        ax.set_yticks([0, 1, 2, 3])
        ax.set_yticklabels(['Not det.', 'Low', 'Medium', 'High'])
        if corr['concordance_rate']:
            ax.text(0.95, 0.05, f"Concordance: {corr['concordance_rate']*100:.0f}%",
                   transform=ax.transAxes, ha='right', fontsize=10)
        # Add legend
        concordant_patch = mpatches.Patch(color='#00843D', label='Concordant')
        discordant_patch = mpatches.Patch(color='#E4002B', label='Discordant')
        ax.legend(handles=[concordant_patch, discordant_patch], loc='upper left', fontsize=8)
    else:
        ax.text(0.5, 0.5, 'No correlation data', ha='center', va='center')
    ax.set_title('RNA-Protein Correlation', fontweight='bold')

    # Panel E: Prognostic
    ax = axes[1, 1]
    ax.axis('off')

    if prog['is_prognostic']:
        ax.text(0.5, 0.7, 'CRC Prognostic', ha='center', fontsize=12, fontweight='bold')
        ax.text(0.5, 0.5, f"High expr = {prog['direction']}", ha='center', fontsize=14,
               color='#E4002B' if prog['direction'] == 'unfavorable' else '#00843D')
        for i, p in enumerate(prog['prognostic_cancers'][:2]):
            ax.text(0.5, 0.3 - i*0.12, f"{p['cancer']}: p={p['p_value']}", ha='center', fontsize=9)
    else:
        ax.text(0.5, 0.5, 'Not Prognostic', ha='center', fontsize=14)
    ax.set_title('Prognostic Association', fontweight='bold')

    # Panel F: CPTAC (if available) or GI Tissue IHC Distribution
    ax = axes[1, 2]
    cptac_data = tumor.get('cptac')

    if cptac_data and len(cptac_data) > 0:
        # Show CPTAC bar plot (quantitative proteomics)
        # Handle both list and dict formats
        if isinstance(cptac_data, list):
            cancers = ['CRC' for c in cptac_data]  # CRC for all entries
            logfc_vals = [c.get('logFC', 0) for c in cptac_data]
            p_vals = [c.get('p_adj', 1) for c in cptac_data]
        else:
            cancers = ['CRC']
            logfc_vals = [cptac_data.get('logFC', 0)]
            p_vals = [cptac_data.get('p_adj', 1)]

        colors = ['#E4002B' if v > 0 else '#0077C8' for v in logfc_vals]

        bars = ax.bar(cancers, logfc_vals, color=colors, edgecolor='black', width=0.5)
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.set_ylabel('log2 FC (Tumor vs Normal)')

        # Add p-value annotations with scientific notation for very small values
        for i, (logfc_val, p) in enumerate(zip(logfc_vals, p_vals)):
            if p < 1e-10:
                p_text = f'p={p:.1e}'
            elif p < 0.001:
                p_text = f'p={p:.2e}'
            elif p < 0.01:
                p_text = f'p={p:.3f}'
            else:
                p_text = f'p={p:.2f}'
            y_pos = logfc_val + 0.08 if logfc_val > 0 else logfc_val - 0.15
            ax.text(i, y_pos, p_text, ha='center', fontsize=9, style='italic')

        # Add CPTAC enrichment annotation
        max_logfc = max(logfc_vals)
        if max_logfc >= 1.0:
            cptac_enrich = 'HIGH'
        elif max_logfc >= 0.5:
            cptac_enrich = 'MEDIUM'
        elif max_logfc >= 0:
            cptac_enrich = 'LOW'
        else:
            cptac_enrich = 'NEGATIVE'
        ax.text(0.98, 0.98, f'CPTAC: {cptac_enrich}',
                transform=ax.transAxes, ha='right', va='top', fontsize=9,
                bbox=dict(boxstyle='round', facecolor='lightgreen' if cptac_enrich in ['HIGH', 'MEDIUM'] else 'lightyellow', alpha=0.7))
        ax.set_title('CPTAC: Tumor vs Normal', fontweight='bold')
    else:
        # Fallback: GI Tissue IHC Distribution
        levels = {'High': 0, 'Medium': 0, 'Low': 0, 'Not detected': 0}
        for item in tox['primary_gi'] + tox['secondary_gi']:
            if item['level'] in levels:
                levels[item['level']] += 1
        # Filter out zero values for pie chart
        non_zero = [(v, k) for k, v in levels.items() if v > 0]
        if non_zero:
            sizes, labels = zip(*non_zero)
            color_map = {'High': '#E4002B', 'Medium': '#F2A900', 'Low': '#0077C8', 'Not detected': '#00843D'}
            colors = [color_map[l] for l in labels]
            ax.pie(sizes, labels=labels, colors=colors, autopct='%1.0f%%', startangle=90)
        else:
            ax.text(0.5, 0.5, 'No GI IHC data', ha='center', va='center')
            ax.axis('off')
        ax.set_title('GI Tissue IHC Distribution', fontweight='bold')

    plt.tight_layout()

    # Save figure
    fig_path = output_dir / f'{gene}_crc_protein_analysis.png'
    plt.savefig(fig_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

    return fig_path


def save_yaml_summary(gene: str, analyses: Dict, output_dir: Path):
    """Save structured YAML summary for integration with target evaluation."""

    tox = analyses['toxicity']
    sub = analyses['subcellular']
    prog = analyses['prognostic']
    corr = analyses['correlation']
    tvn = analyses.get('tumor_vs_normal', {})

    summary = {
        'gene': gene,
        'disease': 'CRC',
        'data_source': 'Human Protein Atlas v25',

        'tumor_vs_normal': {
            'protein_enrichment': tvn.get('protein_enrichment', 'N/A'),
            'normal_ihc_score': float(tvn.get('normal_score')) if tvn.get('normal_score') is not None else None,
            'tumor_ihc_score': float(tvn.get('tumor_score')) if tvn.get('tumor_score') is not None else None,
            'ihc_score_difference': float(tvn.get('enrichment_score')) if tvn.get('enrichment_score') is not None else None,
            'cptac_logfc': float(tvn.get('cptac_logfc')) if tvn.get('cptac_logfc') is not None else None,
            'interpretation': tvn.get('interpretation', 'N/A')
        },

        'on_target_toxicity': {
            'gi_toxicity_risk': tox['gi_toxicity_risk'],
            'overall_toxicity_risk': tox['overall_toxicity_risk'],
            'colon_expression': next((item['level'] for item in tox['primary_gi']
                                      if item['tissue'] == 'Colon' and item['cell_type'] == 'glandular cells'), 'Unknown'),
            'rectum_expression': next((item['level'] for item in tox['primary_gi']
                                       if item['tissue'] == 'Rectum'), 'Unknown')
        },

        'subcellular_location': {
            'main_locations': sub['main_locations'],
            'is_surface_target': sub['is_surface_target'],
            'reliability': sub['reliability'],
            'recommended_modalities': sub['recommended_modalities'],
            'modality_suitability': sub['modality_suitability']
        },

        'prognostic': {
            'is_prognostic': prog['is_prognostic'],
            'direction': prog['direction'],
            'cancers': [{'cancer': p['cancer'], 'p_value': str(p['p_value']), 'validated': p['validated']}
                       for p in prog['prognostic_cancers']]
        },

        'rna_protein_correlation': {
            'concordance_rate': corr['concordance_rate'],
            'discordant_tissues': corr['discordant_tissues']
        }
    }

    yaml_path = output_dir / f'{gene}_crc_protein_summary.yaml'
    with open(yaml_path, 'w') as f:
        yaml.dump(summary, f, default_flow_style=False, sort_keys=False)

    return yaml_path


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='CRC Protein Analysis using HPA data')
    parser.add_argument('--gene', type=str, required=True, help='Gene symbol to analyze')
    parser.add_argument('--data-dir', type=str, default=None,
                       help='Directory with CRC-preprocessed HPA data (default: skill data_cache)')
    parser.add_argument('--output-dir', type=str, default='./crc_protein_results',
                       help='Output directory')
    args = parser.parse_args()

    gene = args.gene.upper()
    output_dir = Path(args.output_dir) / gene
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine data directory
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        # Default to skill's data_cache
        skill_dir = Path(__file__).parent
        data_dir = skill_dir / 'data_cache'

    print(f"\n{'='*60}")
    print(f"CRC Protein Analysis: {gene}")
    print(f"Data directory: {data_dir}")
    print(f"Output directory: {output_dir}")
    print(f"{'='*60}\n")

    # Load data
    print("Loading HPA data...")
    data = load_hpa_data(data_dir)

    # Get gene-specific data
    print(f"\nExtracting {gene} data...")
    gene_data = get_gene_data(data, gene)

    # Run analyses
    print("\nRunning analyses...")
    analyses = {
        'toxicity': analyze_normal_tissue_toxicity(gene_data, gene),
        'correlation': analyze_rna_protein_correlation(gene_data, gene),
        'subcellular': analyze_subcellular_location(gene_data, gene),
        'prognostic': analyze_prognostic(gene_data, gene),
        'tumor': analyze_tumor_expression(gene_data, gene),
        'tumor_vs_normal': analyze_tumor_vs_normal_protein(gene_data, gene)
    }

    # Generate outputs
    print("\nGenerating outputs...")

    # Markdown report
    report = generate_protein_report(gene, analyses, output_dir)
    report_path = output_dir / f'{gene}_crc_protein_report.md'
    with open(report_path, 'w') as f:
        f.write(report)
    print(f"  Report: {report_path}")

    # Figure
    fig_path = generate_protein_figure(gene, analyses, output_dir)
    print(f"  Figure: {fig_path}")

    # YAML summary
    yaml_path = save_yaml_summary(gene, analyses, output_dir)
    print(f"  YAML: {yaml_path}")

    # Print summary
    print(f"\n{'='*60}")
    print(f"Analysis Complete: {gene}")
    print(f"{'='*60}")
    print(f"GI Toxicity Risk: {analyses['toxicity']['gi_toxicity_risk']}")
    print(f"Surface Target: {'Yes' if analyses['subcellular']['is_surface_target'] else 'No'}")
    print(f"Recommended Modalities: {', '.join(analyses['subcellular']['recommended_modalities'])}")
    print(f"CRC Prognostic: {'Yes - ' + analyses['prognostic']['direction'] if analyses['prognostic']['is_prognostic'] else 'No'}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
