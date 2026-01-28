#!/usr/bin/env python3
"""
CRC Gene Expression Analysis with Cohort Comparisons and Target Evaluation Report

Analyzes gene expression across CRC cohorts (2A, 2B, 4, 5, 6), CMS subtypes,
and normal tissue comparisons using Omicsoft format data.

Usage:
    python crc_gene_analysis.py --genes CDK4 CDK6 CCND1
    python crc_gene_analysis.py --gene-file genes.txt
    python crc_gene_analysis.py --genes CDK4 --output-dir ./my_results

Data Sources (from S3):
    - TCGA COAD/READ expression and metadata
    - GTEx normal colon expression
    - CCLE CRC cell line expression
    - Cohort assignments CSV
    - CMS predictions CSV
"""

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
from scipy.stats import mannwhitneyu, kruskal
from statsmodels.stats.multitest import multipletests
import subprocess
import os
import sys
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================

S3_BUCKET = 's3://onc-compbio/omicsoft_oncoland_data'
AWS_PROFILE = 'cbg'

# Default directories
DEFAULT_CACHE_DIR = './data_cache'
DEFAULT_OUTPUT_DIR = './crc_analysis_results'

# Cohort and annotation files
DEFAULT_COHORT_PATH = './crc_cohort_assignments.csv'
DEFAULT_CMS_PATH = './TCGA_CMS_prediction.csv'
DEFAULT_ADJ_NORMAL_PATH = './TCGA-COAD-READ-AdjNormal.tsv'

# Plot settings
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['figure.dpi'] = 150
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
sns.set_style('whitegrid')

# Cohorts to analyze
COHORTS_OF_INTEREST = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6']

# Color schemes
COHORT_COLORS = {
    'Cohort_2A': '#E74C3C',       # Red - RAS mutant
    'Cohort_2B': '#2ECC71',       # Green - RAS WT
    'Cohort_4': '#3498DB',        # Blue - Early stage
    'Cohort_5': '#9B59B6',        # Purple - All MSS
    'Cohort_6': '#F39C12',        # Orange - MSI-H
    'TCGA_Tumor': '#E74C3C',      # Red - All Tumor
    'TCGA_Adjacent': '#7F8C8D',   # Gray - TCGA Adjacent Normal
    'GTEx_Normal': '#1ABC9C',     # Teal - GTEx Normal
    'CCLE_CRC': '#8B4513'         # Brown - CRC Cell Lines
}

CMS_COLORS = {
    'CMS1': '#E69F00',   # Orange - MSI Immune
    'CMS2': '#56B4E9',   # Sky Blue - Canonical
    'CMS3': '#009E73',   # Green - Metabolic
    'CMS4': '#CC79A7',   # Pink - Mesenchymal
    'Indeterminate': '#999999'
}

TUMOR_TYPE_COLORS = {
    'COAD': '#3498DB',  # Blue - Colon
    'READ': '#E74C3C',  # Red - Rectal
}

COHORT_LABELS = {
    'Cohort_2A': '2A\nRAS-mut\nMSS',
    'Cohort_2B': '2B\nRAS-WT\nMSS',
    'Cohort_4': '4\nEarly\nStage',
    'Cohort_5': '5\nAll\nMSS',
    'Cohort_6': '6\nMSI-H',
    'TCGA_Tumor': 'CRC\nTumor',
    'TCGA_Adjacent': 'Adjacent\nNormal\n(TCGA)',
    'GTEx_Normal': 'Normal\nColon\n(GTEx)',
    'CCLE_CRC': 'CRC\nCell Lines\n(CCLE)'
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def truncate_tcga_id(sample_id, length=15):
    """Truncate TCGA sample ID to standard length."""
    if isinstance(sample_id, str) and sample_id.startswith('TCGA'):
        return sample_id[:length]
    return sample_id

# =============================================================================
# DATA LOADING FUNCTIONS
# =============================================================================

def download_s3_file(s3_path, local_path, quiet=False):
    """Download file from S3 if not already cached."""
    if os.path.exists(local_path):
        if not quiet:
            print(f"  Using cached: {os.path.basename(local_path)}")
        return local_path

    if not quiet:
        print(f"  Downloading: {os.path.basename(s3_path)}")

    cmd = f"aws s3 cp {s3_path} {local_path} --profile {AWS_PROFILE} --no-verify-ssl"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to download {s3_path}: {result.stderr}")

    return local_path


def load_gene_annotation(cache_dir):
    """Load gene annotation for gene symbol to ID mapping."""
    s3_path = f"{S3_BUCKET}/tcga_b38_gc33/raw/gene_annotation.tsv.gz"
    local_path = f"{cache_dir}/gene_annotation.tsv.gz"
    download_s3_file(s3_path, local_path)

    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    print(f"  {len(df)} genes in annotation")
    return df


def load_tcga_metadata(cache_dir):
    """Load TCGA sample metadata."""
    s3_path = f"{S3_BUCKET}/tcga_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/tcga_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)

    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    print(f"  {len(df)} TCGA samples")
    return df


def load_ccle_metadata(cache_dir):
    """Load CCLE sample metadata."""
    s3_path = f"{S3_BUCKET}/ccle_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/ccle_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)

    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    print(f"  {len(df)} CCLE samples")
    return df


def load_gtex_metadata(cache_dir):
    """Load GTEx sample metadata."""
    s3_path = f"{S3_BUCKET}/gtex_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/gtex_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)

    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    print(f"  {len(df)} GTEx samples")
    return df


def load_cohort_assignments(cohort_path):
    """Load cohort assignments from CSV."""
    print(f"Loading cohort assignments from: {cohort_path}")
    df = pd.read_csv(cohort_path)
    print(f"  {len(df)} samples with cohort assignments")
    return df


def load_cms_predictions(cms_path):
    """Load CMS predictions from CSV."""
    print(f"Loading CMS predictions from: {cms_path}")
    df = pd.read_csv(cms_path)
    print(f"  {len(df)} samples with CMS predictions")
    return df


def load_adjacent_normal_samples(adj_path):
    """Load TCGA adjacent normal sample IDs."""
    print(f"Loading adjacent normal samples from: {adj_path}")
    df = pd.read_csv(adj_path, sep='\t')
    samples = df['Sample_ID'].unique().tolist()
    print(f"  {len(samples)} unique adjacent normal samples")
    return samples


def load_expression_for_gene(cache_dir, dataset, gene_index):
    """Load expression data for a specific gene from long format Omicsoft data."""
    dataset_paths = {
        'tcga': f"{S3_BUCKET}/tcga_b38_gc33/raw/rna_seq_gene_expression.tsv.gz",
        'ccle': f"{S3_BUCKET}/ccle_b38_gc33/raw/rna_seq_gene_expression.tsv.gz",
        'gtex': f"{S3_BUCKET}/gtex_b38_gc33/raw/rna_seq_gene_expression.tsv.gz"
    }

    s3_path = dataset_paths[dataset]
    local_path = f"{cache_dir}/{dataset}_expression.tsv.gz"
    download_s3_file(s3_path, local_path, quiet=True)

    print(f"  Loading {dataset} expression for gene_index={gene_index}...")

    # Read expression data in chunks to handle large files
    results = []
    chunksize = 2000000

    for chunk in pd.read_csv(local_path, sep='\t', compression='gzip', chunksize=chunksize):
        filtered = chunk[chunk['gene_index'] == gene_index]
        if len(filtered) > 0:
            results.append(filtered)

    if len(results) > 0:
        df = pd.concat(results, ignore_index=True)
        print(f"    Found {len(df)} expression values")
        return df

    print(f"    No expression data found")
    return pd.DataFrame()


# =============================================================================
# SAMPLE FILTERING FUNCTIONS
# =============================================================================

def get_tcga_crc_samples(metadata):
    """Get TCGA COAD/READ samples."""
    if 'project_ids' in metadata.columns:
        mask = metadata['project_ids'].str.contains('TCGA_COAD|TCGA_READ', na=False, case=False)
    elif 'project_id' in metadata.columns:
        mask = metadata['project_id'].str.contains('TCGA_COAD|TCGA_READ', na=False, case=False)
    else:
        mask = pd.Series([False] * len(metadata))

    return metadata[mask]


def get_tcga_crc_tumor_samples(metadata):
    """Get TCGA CRC primary tumor samples."""
    crc = get_tcga_crc_samples(metadata)
    if 'tumor_or_normal' in crc.columns:
        tumor_mask = crc['tumor_or_normal'].str.contains('Tumor', case=False, na=False)
        return crc[tumor_mask]
    return crc


def get_tcga_crc_normal_samples(metadata):
    """Get TCGA CRC adjacent normal samples."""
    crc = get_tcga_crc_samples(metadata)
    if 'tumor_or_normal' in crc.columns:
        normal_mask = crc['tumor_or_normal'].str.contains('Normal', case=False, na=False)
        return crc[normal_mask]
    return pd.DataFrame()


def get_gtex_colon_samples(metadata):
    """Get GTEx colon samples."""
    if 'tissue_gtex' in metadata.columns:
        mask = metadata['tissue_gtex'].str.lower().str.contains('colon', na=False)
    elif 'tissue' in metadata.columns:
        mask = metadata['tissue'].str.lower().str.contains('colon', na=False)
    else:
        mask = pd.Series([False] * len(metadata))

    return metadata[mask]


def get_ccle_crc_samples(metadata):
    """Get CCLE CRC cell lines."""
    if 'onco_tree_disease' in metadata.columns:
        mask = metadata['onco_tree_disease'].str.contains('colorectal adenocarcinoma', case=False, na=False)
    else:
        mask = pd.Series([False] * len(metadata))

    return metadata[mask]


# =============================================================================
# MASTER DATAFRAME BUILDING
# =============================================================================

def build_master_dataframe(tcga_expr, gtex_expr, ccle_expr, tcga_meta, gtex_meta, ccle_meta,
                            cohort_df, cms_df, adj_normal_samples):
    """Build master dataframe with all samples and their cohort assignments."""

    records = []

    # Create sample_index to sample_id mapping for TCGA
    tcga_sample_map = dict(zip(tcga_meta['sample_index'], tcga_meta['sample_id']))

    # Create cohort lookup from cohort_df
    cohort_lookup = {}
    if cohort_df is not None:
        for _, row in cohort_df.iterrows():
            sample_id = row['sample_id']
            cohorts = []
            for cohort in COHORTS_OF_INTEREST:
                if cohort in row.index and row[cohort] == True:
                    cohorts.append(cohort)
            cohort_lookup[sample_id] = {
                'cohorts': cohorts,
                'msi_status': row.get('msi_status', 'Unknown'),
                'ras_status': row.get('RAS_status', 'Unknown'),
                'stage_group': row.get('stage_group', 'Unknown'),
                'tumor_type': row.get('tumor_type', 'Unknown')
            }

    # Create CMS lookup
    cms_lookup = {}
    if cms_df is not None:
        for _, row in cms_df.iterrows():
            sample_id = row.get('sample_id', row.iloc[0])
            sample_id_short = truncate_tcga_id(sample_id)
            pred = row.get('prediction', None)
            if pd.notna(pred):
                cms_lookup[sample_id_short] = pred

    # Process TCGA expression
    if len(tcga_expr) > 0:
        # Get CRC samples
        crc_meta = get_tcga_crc_samples(tcga_meta)
        crc_sample_indices = set(crc_meta['sample_index'].tolist())

        # Get adjacent normal sample indices
        adj_normal_indices = set()
        for _, row in crc_meta.iterrows():
            sample_id = row['sample_id']
            if any(adj in sample_id for adj in ['-11', '-11A', '-11B']):
                adj_normal_indices.add(row['sample_index'])

        for _, row in tcga_expr.iterrows():
            sample_idx = row['sample_index']
            if sample_idx not in crc_sample_indices:
                continue

            sample_id = tcga_sample_map.get(sample_idx, '')
            sample_id_short = truncate_tcga_id(sample_id)

            # Log2 transform TPM
            expr_value = np.log2(row['tpm'] + 1)

            # Determine if tumor or normal
            is_normal = sample_idx in adj_normal_indices or '-11' in sample_id

            if is_normal:
                # Determine tumor type from sample ID pattern (COAD or READ project)
                tumor_type_normal = 'COAD' if 'COAD' in sample_id or sample_id.startswith('TCGA-A6') else 'READ'
                records.append({
                    'expr_sample_id': sample_id,
                    'sample_index': sample_idx,
                    'expression': expr_value,
                    'tissue_type': 'TCGA_Adjacent',
                    'cohorts': ['TCGA_Adjacent'],
                    'CMS': 'Normal',
                    'msi_status': 'N/A',
                    'ras_status': 'N/A',
                    'stage_group': 'N/A',
                    'tumor_type': tumor_type_normal
                })
            else:
                # Look up cohort info
                cohort_info = cohort_lookup.get(sample_id_short, None)
                if cohort_info is None:
                    # Try without truncation
                    cohort_info = cohort_lookup.get(sample_id, None)

                if cohort_info is not None and len(cohort_info['cohorts']) > 0:
                    cms = cms_lookup.get(sample_id_short, 'Unknown')
                    records.append({
                        'expr_sample_id': sample_id,
                        'sample_index': sample_idx,
                        'expression': expr_value,
                        'tissue_type': 'Primary_Tumor',
                        'cohorts': cohort_info['cohorts'],
                        'CMS': cms,
                        'msi_status': cohort_info['msi_status'],
                        'ras_status': cohort_info['ras_status'],
                        'stage_group': cohort_info['stage_group'],
                        'tumor_type': cohort_info['tumor_type']
                    })

    # Process GTEx expression
    if len(gtex_expr) > 0:
        gtex_colon = get_gtex_colon_samples(gtex_meta)
        gtex_colon_indices = set(gtex_colon['sample_index'].tolist())
        gtex_sample_map = dict(zip(gtex_meta['sample_index'], gtex_meta['sample_id']))

        for _, row in gtex_expr.iterrows():
            sample_idx = row['sample_index']
            if sample_idx not in gtex_colon_indices:
                continue

            sample_id = gtex_sample_map.get(sample_idx, f'GTEx_{sample_idx}')
            expr_value = np.log2(row['tpm'] + 1)

            records.append({
                'expr_sample_id': sample_id,
                'sample_index': sample_idx,
                'expression': expr_value,
                'tissue_type': 'GTEx_Normal',
                'cohorts': ['GTEx_Normal'],
                'CMS': 'Normal',
                'msi_status': 'N/A',
                'ras_status': 'N/A',
                'stage_group': 'N/A',
                'tumor_type': 'Normal'
            })

    # Process CCLE expression
    if ccle_expr is not None and len(ccle_expr) > 0 and ccle_meta is not None:
        ccle_crc = get_ccle_crc_samples(ccle_meta)
        ccle_crc_indices = set(ccle_crc['sample_index'].tolist())
        ccle_sample_map = dict(zip(ccle_meta['sample_index'], ccle_meta['sample_id']))

        # Get MSI status if available
        ccle_msi_map = {}
        if 'microsatellite_instability_msi_status_ccle' in ccle_meta.columns:
            ccle_msi_map = dict(zip(ccle_meta['sample_index'],
                                    ccle_meta['microsatellite_instability_msi_status_ccle']))

        # Get tumor type (COAD/READ) for CCLE cell lines
        ccle_tumor_type_map = {}
        if 'tumor_type_dep_map' in ccle_meta.columns:
            for _, meta_row in ccle_meta.iterrows():
                tt = meta_row.get('tumor_type_dep_map', '')
                if pd.notna(tt):
                    if tt == 'COAD':
                        ccle_tumor_type_map[meta_row['sample_index']] = 'COAD'
                    elif tt == 'READ':
                        ccle_tumor_type_map[meta_row['sample_index']] = 'READ'
                    else:
                        ccle_tumor_type_map[meta_row['sample_index']] = 'CRC_Other'

        for _, row in ccle_expr.iterrows():
            sample_idx = row['sample_index']
            if sample_idx not in ccle_crc_indices:
                continue

            sample_id = ccle_sample_map.get(sample_idx, f'CCLE_{sample_idx}')
            expr_value = np.log2(row['tpm'] + 1)
            msi_status = ccle_msi_map.get(sample_idx, 'Unknown')
            ccle_tumor_type = ccle_tumor_type_map.get(sample_idx, 'Unknown')

            records.append({
                'expr_sample_id': sample_id,
                'sample_index': sample_idx,
                'expression': expr_value,
                'tissue_type': 'CCLE_CRC',
                'cohorts': ['CCLE_CRC'],
                'CMS': 'Cell_Line',
                'msi_status': msi_status if pd.notna(msi_status) else 'Unknown',
                'ras_status': 'N/A',
                'stage_group': 'N/A',
                'tumor_type': f'CCLE_{ccle_tumor_type}'
            })

    return pd.DataFrame(records)


def expand_for_plotting(master_df):
    """Create expanded dataframe with one row per sample-cohort combination."""
    expanded_records = []

    for _, row in master_df.iterrows():
        for cohort in row['cohorts']:
            expanded_records.append({
                'sample_id': row['expr_sample_id'],
                'expression': row['expression'],
                'cohort': cohort,
                'tissue_type': row['tissue_type'],
                'CMS': row['CMS'],
                'msi_status': row['msi_status'],
                'ras_status': row['ras_status'],
                'stage_group': row['stage_group'],
                'tumor_type': row.get('tumor_type', 'Unknown')
            })

    return pd.DataFrame(expanded_records)


# =============================================================================
# GENE LOOKUP
# =============================================================================

def find_gene_index(gene_symbol, annotation_df):
    """Find gene_index for a gene symbol."""
    # Try gene_name column (omicsoft format)
    if 'gene_name' in annotation_df.columns:
        matches = annotation_df[annotation_df['gene_name'].str.upper() == gene_symbol.upper()]
        if len(matches) > 0:
            return matches['gene_index'].iloc[0], matches['gene_id'].iloc[0], matches['gene_name'].iloc[0]

    return None, None, None


# =============================================================================
# STATISTICAL ANALYSIS
# =============================================================================

def calculate_statistics(plot_df):
    """Calculate descriptive statistics by cohort."""
    stats_summary = plot_df.groupby('cohort')['expression'].agg([
        'count', 'mean', 'median', 'std',
        ('Q1', lambda x: x.quantile(0.25)),
        ('Q3', lambda x: x.quantile(0.75)),
        'min', 'max'
    ]).round(4)

    stats_summary['IQR'] = stats_summary['Q3'] - stats_summary['Q1']
    return stats_summary


def perform_kruskal_wallis(plot_df):
    """Perform Kruskal-Wallis test across all cohorts."""
    cohorts = plot_df['cohort'].unique()
    groups = [plot_df[plot_df['cohort'] == c]['expression'].dropna().values for c in cohorts]
    groups = [g for g in groups if len(g) > 0]

    if len(groups) < 2:
        return None, None

    kw_stat, kw_pval = kruskal(*groups)
    return kw_stat, kw_pval


def perform_pairwise_comparisons(plot_df):
    """Perform Mann-Whitney U tests: tumor cohorts vs normal groups."""
    normal_groups = ['TCGA_Adjacent', 'GTEx_Normal']
    pairwise_results = []

    for normal_group in normal_groups:
        normal_expr = plot_df[plot_df['cohort'] == normal_group]['expression'].dropna().values

        if len(normal_expr) < 3:
            continue

        for tumor_cohort in COHORTS_OF_INTEREST:
            tumor_expr = plot_df[plot_df['cohort'] == tumor_cohort]['expression'].dropna().values

            if len(tumor_expr) < 3:
                continue

            stat, pval = mannwhitneyu(tumor_expr, normal_expr, alternative='two-sided')

            # Effect size (rank-biserial correlation)
            n1, n2 = len(tumor_expr), len(normal_expr)
            effect_size = 1 - (2 * stat) / (n1 * n2)

            pairwise_results.append({
                'Tumor_Cohort': tumor_cohort,
                'Normal_Group': normal_group,
                'N_tumor': n1,
                'N_normal': n2,
                'Tumor_median': np.median(tumor_expr),
                'Normal_median': np.median(normal_expr),
                'Log2FC': np.median(tumor_expr) - np.median(normal_expr),
                'U_statistic': stat,
                'p_value': pval,
                'effect_size': effect_size
            })

    pairwise_df = pd.DataFrame(pairwise_results)

    if len(pairwise_df) > 0:
        _, pvals_corrected, _, _ = multipletests(pairwise_df['p_value'], method='fdr_bh')
        pairwise_df['p_adjusted'] = pvals_corrected
        pairwise_df['significant'] = pairwise_df['p_adjusted'] < 0.05

    return pairwise_df


def perform_cms_statistics(plot_df):
    """Calculate CMS-specific statistics including pairwise comparisons."""
    from itertools import combinations

    tumor_df = plot_df[plot_df['tissue_type'] == 'Primary_Tumor'].copy()
    valid_cms = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
    cms_filtered = tumor_df[tumor_df['CMS'].isin(valid_cms)].drop_duplicates(subset=['sample_id'])

    if len(cms_filtered) == 0:
        return None, None, None, None

    cms_stats = cms_filtered.groupby('CMS')['expression'].agg(['count', 'mean', 'median', 'std']).round(4)

    # Kruskal-Wallis across CMS
    cms_groups = [cms_filtered[cms_filtered['CMS'] == c]['expression'].dropna().values
                  for c in valid_cms if len(cms_filtered[cms_filtered['CMS'] == c]) > 0]

    if len(cms_groups) > 1:
        kw_stat, kw_pval = kruskal(*cms_groups)
    else:
        kw_stat, kw_pval = None, None

    # Pairwise CMS comparisons
    cms_pairwise = []
    available_cms = [c for c in valid_cms if c in cms_filtered['CMS'].values and
                     len(cms_filtered[cms_filtered['CMS'] == c]) > 0]

    for cms1, cms2 in combinations(available_cms, 2):
        g1 = cms_filtered[cms_filtered['CMS'] == cms1]['expression'].dropna()
        g2 = cms_filtered[cms_filtered['CMS'] == cms2]['expression'].dropna()

        if len(g1) > 0 and len(g2) > 0:
            stat, pval = mannwhitneyu(g1, g2, alternative='two-sided')
            median_diff = g2.median() - g1.median()
            cms_pairwise.append({
                'CMS_1': cms1,
                'CMS_2': cms2,
                'N_1': len(g1),
                'N_2': len(g2),
                'Median_1': g1.median(),
                'Median_2': g2.median(),
                'Median_Diff': median_diff,
                'p_value': pval
            })

    cms_pairwise_df = pd.DataFrame(cms_pairwise)

    # Apply Bonferroni correction if we have comparisons
    if len(cms_pairwise_df) > 0:
        n_comparisons = len(cms_pairwise_df)
        cms_pairwise_df['p_adjusted'] = (cms_pairwise_df['p_value'] * n_comparisons).clip(upper=1.0)
        cms_pairwise_df['significant'] = cms_pairwise_df['p_adjusted'] < 0.05

    return cms_stats, kw_stat, kw_pval, cms_pairwise_df


# =============================================================================
# VISUALIZATION FUNCTIONS
# =============================================================================

def plot_cohort_boxplot(plot_df, gene_symbol, output_dir, expr_unit=r'$\log_2(TPM + 1)$'):
    """Create main cohort comparison box plot."""
    plot_order = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6', 'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']
    plot_order = [c for c in plot_order if c in plot_df['cohort'].unique()]

    fig, ax = plt.subplots(figsize=(14, 8))

    palette = [COHORT_COLORS.get(c, '#666666') for c in plot_order]

    bp = ax.boxplot(
        [plot_df[plot_df['cohort'] == c]['expression'].dropna().values for c in plot_order],
        positions=range(len(plot_order)),
        widths=0.6,
        patch_artist=True,
        showfliers=True,
        flierprops={'marker': 'o', 'markersize': 3, 'alpha': 0.4, 'markerfacecolor': 'gray'}
    )

    for patch, color in zip(bp['boxes'], palette):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
        patch.set_edgecolor('black')
        patch.set_linewidth(1.5)

    for median in bp['medians']:
        median.set_color('black')
        median.set_linewidth(2)

    for whisker in bp['whiskers']:
        whisker.set_color('black')
        whisker.set_linewidth(1.5)
    for cap in bp['caps']:
        cap.set_color('black')
        cap.set_linewidth(1.5)

    labels = [COHORT_LABELS.get(c, c) for c in plot_order]
    ax.set_xticks(range(len(plot_order)))
    ax.set_xticklabels(labels, fontsize=10)

    # Sample sizes
    y_min = ax.get_ylim()[0]
    for i, cohort in enumerate(plot_order):
        n = len(plot_df[plot_df['cohort'] == cohort])
        ax.text(i, y_min - 0.8, f'n={n}', ha='center', va='top', fontsize=9, color='gray')

    # Vertical separator between tumor and normal
    tumor_end = len([c for c in plot_order if c.startswith('Cohort_')]) - 0.5
    ax.axvline(x=tumor_end, color='gray', linestyle='--', linewidth=1, alpha=0.5)

    ax.set_ylabel(expr_unit, fontsize=12)
    ax.set_xlabel('Cohort', fontsize=12)
    ax.set_title(f'{gene_symbol} Expression Across CRC Cohorts and Normal Tissues',
                 fontsize=14, fontweight='bold')

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#E74C3C', alpha=0.7, edgecolor='black', label='Tumor Cohorts'),
        Patch(facecolor='#7F8C8D', alpha=0.7, edgecolor='black', label='TCGA Adjacent Normal'),
        Patch(facecolor='#1ABC9C', alpha=0.7, edgecolor='black', label='GTEx Normal Colon'),
        Patch(facecolor='#8B4513', alpha=0.7, edgecolor='black', label='CRC Cell Lines (CCLE)')
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=9)

    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_cohort_boxplot.png', dpi=300, bbox_inches='tight')
    plt.savefig(f'{output_dir}/{gene_symbol}_cohort_boxplot.pdf', bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_cohort_boxplot.png")


def plot_cohort_violin(plot_df, gene_symbol, output_dir, expr_unit=r'$\log_2(TPM + 1)$'):
    """Create violin plot with embedded box plot."""
    plot_order = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6', 'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']
    plot_order = [c for c in plot_order if c in plot_df['cohort'].unique()]

    fig, ax = plt.subplots(figsize=(14, 8))

    palette = [COHORT_COLORS.get(c, '#666666') for c in plot_order]
    data = [plot_df[plot_df['cohort'] == c]['expression'].dropna().values for c in plot_order]

    parts = ax.violinplot(data, positions=range(len(plot_order)),
                          showmeans=False, showmedians=False, showextrema=False)

    for i, pc in enumerate(parts['bodies']):
        pc.set_facecolor(palette[i])
        pc.set_edgecolor('black')
        pc.set_alpha(0.7)
        pc.set_linewidth(1.5)

    bp = ax.boxplot(data, positions=range(len(plot_order)), widths=0.15,
                    patch_artist=True, showfliers=False)

    for patch in bp['boxes']:
        patch.set_facecolor('white')
        patch.set_edgecolor('black')
        patch.set_linewidth(1.5)

    for median in bp['medians']:
        median.set_color('red')
        median.set_linewidth(2)

    labels = [COHORT_LABELS.get(c, c) for c in plot_order]
    ax.set_xticks(range(len(plot_order)))
    ax.set_xticklabels(labels, fontsize=10)

    # Sample sizes
    y_min = ax.get_ylim()[0]
    for i, cohort in enumerate(plot_order):
        n = len(plot_df[plot_df['cohort'] == cohort])
        ax.text(i, y_min - 0.8, f'n={n}', ha='center', va='top', fontsize=9, color='gray')

    tumor_end = len([c for c in plot_order if c.startswith('Cohort_')]) - 0.5
    ax.axvline(x=tumor_end, color='gray', linestyle='--', linewidth=1, alpha=0.5)

    ax.set_ylabel(expr_unit, fontsize=12)
    ax.set_xlabel('Cohort', fontsize=12)
    ax.set_title(f'{gene_symbol} Expression Across CRC Cohorts and Normal Tissues',
                 fontsize=14, fontweight='bold')

    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_cohort_violin.png', dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_cohort_violin.png")


def plot_cms_boxplot(plot_df, gene_symbol, output_dir, expr_unit=r'$\log_2(TPM + 1)$'):
    """Create CMS subtype comparison box plot."""
    tumor_df = plot_df[plot_df['tissue_type'] == 'Primary_Tumor'].copy()
    valid_cms = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
    cms_filtered = tumor_df[tumor_df['CMS'].isin(valid_cms)].drop_duplicates(subset=['sample_id'])

    if len(cms_filtered) == 0:
        print("  No CMS data available for plotting")
        return

    fig, ax = plt.subplots(figsize=(12, 7))

    cms_order = [c for c in valid_cms if c in cms_filtered['CMS'].values]
    cms_palette = [CMS_COLORS[c] for c in cms_order]

    bp = ax.boxplot(
        [cms_filtered[cms_filtered['CMS'] == c]['expression'].dropna().values for c in cms_order],
        positions=range(len(cms_order)),
        widths=0.6,
        patch_artist=True,
        showfliers=True,
        flierprops={'marker': 'o', 'markersize': 4, 'alpha': 0.5}
    )

    for patch, color in zip(bp['boxes'], cms_palette):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
        patch.set_edgecolor('black')
        patch.set_linewidth(1.5)

    for median in bp['medians']:
        median.set_color('black')
        median.set_linewidth(2)

    cms_labels = {'CMS1': 'CMS1\nMSI Immune', 'CMS2': 'CMS2\nCanonical',
                  'CMS3': 'CMS3\nMetabolic', 'CMS4': 'CMS4\nMesenchymal'}
    ax.set_xticks(range(len(cms_order)))
    ax.set_xticklabels([cms_labels[c] for c in cms_order], fontsize=10)

    # Sample sizes
    for i, cms in enumerate(cms_order):
        n = len(cms_filtered[cms_filtered['CMS'] == cms])
        ax.text(i, ax.get_ylim()[0] - 0.5, f'n={n}', ha='center', va='top', fontsize=9)

    # Normal reference lines
    if 'TCGA_Adjacent' in plot_df['cohort'].unique():
        tcga_adj_median = plot_df[plot_df['cohort'] == 'TCGA_Adjacent']['expression'].median()
        ax.axhline(y=tcga_adj_median, color='#7F8C8D', linestyle='--', alpha=0.7, linewidth=1.5,
                   label=f'TCGA Adjacent: {tcga_adj_median:.2f}')

    if 'GTEx_Normal' in plot_df['cohort'].unique():
        gtex_median = plot_df[plot_df['cohort'] == 'GTEx_Normal']['expression'].median()
        ax.axhline(y=gtex_median, color='#1ABC9C', linestyle='-.', alpha=0.7, linewidth=1.5,
                   label=f'GTEx Normal: {gtex_median:.2f}')

    ax.legend(loc='upper right', fontsize=9)

    ax.set_ylabel(expr_unit, fontsize=12)
    ax.set_xlabel('CMS Subtype', fontsize=12)
    ax.set_title(f'{gene_symbol} Expression by CMS Subtype', fontsize=14, fontweight='bold')

    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_CMS_boxplot.png', dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_CMS_boxplot.png")


def plot_tumor_type_boxplot(plot_df, gene_symbol, output_dir, expr_unit=r'$\log_2(TPM + 1)$'):
    """Create COAD vs READ comparison box plot."""
    tumor_df = plot_df[plot_df['tissue_type'] == 'Primary_Tumor'].copy()
    tumor_df = tumor_df[tumor_df['tumor_type'].isin(['COAD', 'READ'])].drop_duplicates(subset=['sample_id'])

    if len(tumor_df) == 0:
        print("  No COAD/READ data available for plotting")
        return None

    fig, ax = plt.subplots(figsize=(10, 7))

    tumor_order = ['COAD', 'READ']
    tumor_palette = [TUMOR_TYPE_COLORS[t] for t in tumor_order]

    bp = ax.boxplot(
        [tumor_df[tumor_df['tumor_type'] == t]['expression'].dropna().values for t in tumor_order],
        positions=range(len(tumor_order)),
        widths=0.5,
        patch_artist=True,
        showfliers=True,
        flierprops={'marker': 'o', 'markersize': 4, 'alpha': 0.5}
    )

    for patch, color in zip(bp['boxes'], tumor_palette):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
        patch.set_edgecolor('black')
        patch.set_linewidth(1.5)

    for median in bp['medians']:
        median.set_color('black')
        median.set_linewidth(2)

    tumor_labels = {'COAD': 'COAD\n(Colon)', 'READ': 'READ\n(Rectal)'}
    ax.set_xticks(range(len(tumor_order)))
    ax.set_xticklabels([tumor_labels[t] for t in tumor_order], fontsize=12)

    # Sample sizes and medians
    for i, ttype in enumerate(tumor_order):
        subset = tumor_df[tumor_df['tumor_type'] == ttype]['expression']
        n = len(subset)
        med = subset.median()
        ax.text(i, ax.get_ylim()[0] - 0.3, f'n={n}\nmed={med:.2f}', ha='center', va='top', fontsize=10)

    # Normal reference lines
    if 'GTEx_Normal' in plot_df['cohort'].unique():
        gtex_median = plot_df[plot_df['cohort'] == 'GTEx_Normal']['expression'].median()
        ax.axhline(y=gtex_median, color='#1ABC9C', linestyle='--', alpha=0.7, linewidth=1.5,
                   label=f'GTEx Normal: {gtex_median:.2f}')
        ax.legend(loc='upper right', fontsize=10)

    ax.set_ylabel(expr_unit, fontsize=12)
    ax.set_xlabel('Tumor Type', fontsize=12)
    ax.set_title(f'{gene_symbol} Expression: COAD vs READ', fontsize=14, fontweight='bold')

    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)

    # Perform Mann-Whitney U test
    coad_expr = tumor_df[tumor_df['tumor_type'] == 'COAD']['expression'].dropna()
    read_expr = tumor_df[tumor_df['tumor_type'] == 'READ']['expression'].dropna()
    if len(coad_expr) > 0 and len(read_expr) > 0:
        stat, pval = mannwhitneyu(coad_expr, read_expr, alternative='two-sided')
        log2fc = coad_expr.median() - read_expr.median()
        sig_text = f"COAD vs READ: log2FC={log2fc:.3f}, p={pval:.2e}"
        ax.text(0.5, 0.02, sig_text, transform=ax.transAxes, ha='center', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_COAD_READ_boxplot.png', dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_COAD_READ_boxplot.png")
    return {'coad_n': len(coad_expr), 'read_n': len(read_expr),
            'coad_median': coad_expr.median(), 'read_median': read_expr.median(),
            'log2fc': log2fc, 'pval': pval}


def plot_tumor_type_by_cohort(plot_df, gene_symbol, output_dir, expr_unit=r'$\log_2(TPM + 1)$'):
    """Create COAD vs READ comparison for each cohort."""
    tumor_df = plot_df[plot_df['tissue_type'] == 'Primary_Tumor'].copy()
    tumor_df = tumor_df[tumor_df['tumor_type'].isin(['COAD', 'READ'])]

    cohorts = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6']
    cohorts = [c for c in cohorts if c in tumor_df['cohort'].unique()]

    if len(cohorts) == 0:
        return None

    fig, axes = plt.subplots(1, len(cohorts), figsize=(4*len(cohorts), 6), sharey=True)
    if len(cohorts) == 1:
        axes = [axes]

    results = []

    for idx, cohort in enumerate(cohorts):
        ax = axes[idx]
        cohort_df = tumor_df[tumor_df['cohort'] == cohort].drop_duplicates(subset=['sample_id'])

        tumor_order = ['COAD', 'READ']
        data = [cohort_df[cohort_df['tumor_type'] == t]['expression'].dropna().values for t in tumor_order]

        if len(data[0]) > 0 or len(data[1]) > 0:
            bp = ax.boxplot(data, positions=[0, 1], widths=0.5, patch_artist=True, showfliers=True,
                           flierprops={'marker': 'o', 'markersize': 3, 'alpha': 0.4})

            for patch, color in zip(bp['boxes'], [TUMOR_TYPE_COLORS['COAD'], TUMOR_TYPE_COLORS['READ']]):
                patch.set_facecolor(color)
                patch.set_alpha(0.7)
                patch.set_edgecolor('black')

            for median in bp['medians']:
                median.set_color('black')
                median.set_linewidth(2)

        ax.set_xticks([0, 1])
        ax.set_xticklabels(['COAD', 'READ'], fontsize=10)
        cohort_label = cohort.replace('Cohort_', '')
        ax.set_title(f'Cohort {cohort_label}', fontsize=12, fontweight='bold')

        # Sample sizes
        for i, ttype in enumerate(tumor_order):
            n = len(cohort_df[cohort_df['tumor_type'] == ttype])
            ax.text(i, ax.get_ylim()[0] - 0.3, f'n={n}', ha='center', va='top', fontsize=9)

        # Statistics
        coad_vals = cohort_df[cohort_df['tumor_type'] == 'COAD']['expression'].dropna()
        read_vals = cohort_df[cohort_df['tumor_type'] == 'READ']['expression'].dropna()
        if len(coad_vals) > 5 and len(read_vals) > 5:
            stat, pval = mannwhitneyu(coad_vals, read_vals, alternative='two-sided')
            results.append({'cohort': cohort, 'coad_n': len(coad_vals), 'read_n': len(read_vals),
                           'coad_median': coad_vals.median(), 'read_median': read_vals.median(),
                           'log2fc': coad_vals.median() - read_vals.median(), 'pval': pval})

        ax.yaxis.grid(True, linestyle='--', alpha=0.3)

    axes[0].set_ylabel(expr_unit, fontsize=12)
    fig.suptitle(f'{gene_symbol} Expression: COAD vs READ by Cohort', fontsize=14, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_COAD_READ_by_cohort.png', dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_COAD_READ_by_cohort.png")
    return pd.DataFrame(results) if results else None


def analyze_by_tumor_type(plot_df, gene_symbol, output_dir):
    """Generate comprehensive analysis for COAD and READ separately."""
    results = {'COAD': {}, 'READ': {}}

    for tumor_type in ['COAD', 'READ']:
        # Filter tumor samples to specific tumor type
        tumor_only = plot_df[
            (plot_df['tissue_type'] == 'Primary_Tumor') &
            (plot_df['tumor_type'] == tumor_type)
        ].drop_duplicates(subset=['sample_id'])

        if len(tumor_only) == 0:
            continue

        # Calculate statistics by cohort for this tumor type
        cohort_stats = {}
        for cohort in ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6']:
            cohort_data = tumor_only[tumor_only['cohort'] == cohort]['expression'].dropna()
            if len(cohort_data) > 0:
                cohort_stats[cohort] = {
                    'n': len(cohort_data),
                    'median': cohort_data.median(),
                    'mean': cohort_data.mean(),
                    'std': cohort_data.std()
                }

        # Add normal tissue stats (shared between COAD/READ)
        for normal_type in ['TCGA_Adjacent', 'GTEx_Normal']:
            normal_data = plot_df[plot_df['cohort'] == normal_type]['expression'].dropna()
            if len(normal_data) > 0:
                cohort_stats[normal_type] = {
                    'n': len(normal_data),
                    'median': normal_data.median(),
                    'mean': normal_data.mean(),
                    'std': normal_data.std()
                }

        # Add CCLE cell line stats for this tumor type
        ccle_tt = f'CCLE_{tumor_type}'
        ccle_data = plot_df[plot_df['tumor_type'] == ccle_tt]['expression'].dropna()
        if len(ccle_data) > 0:
            cohort_stats[ccle_tt] = {
                'n': len(ccle_data),
                'median': ccle_data.median(),
                'mean': ccle_data.mean(),
                'std': ccle_data.std()
            }

        # CMS analysis for this tumor type
        cms_stats = {}
        for cms in ['CMS1', 'CMS2', 'CMS3', 'CMS4']:
            cms_data = tumor_only[tumor_only['CMS'] == cms]['expression'].dropna()
            if len(cms_data) > 0:
                cms_stats[cms] = {
                    'n': len(cms_data),
                    'median': cms_data.median(),
                    'mean': cms_data.mean(),
                    'std': cms_data.std()
                }

        # Statistical comparisons vs normal
        pairwise_results = []
        for cohort in ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6']:
            cohort_data = tumor_only[tumor_only['cohort'] == cohort]['expression'].dropna()
            if len(cohort_data) < 3:
                continue

            for normal_type in ['TCGA_Adjacent', 'GTEx_Normal']:
                normal_data = plot_df[plot_df['cohort'] == normal_type]['expression'].dropna()
                if len(normal_data) < 3:
                    continue

                stat, pval = mannwhitneyu(cohort_data, normal_data, alternative='two-sided')
                log2fc = cohort_data.median() - normal_data.median()
                pairwise_results.append({
                    'Tumor_Cohort': cohort,
                    'Normal_Group': normal_type,
                    'Log2FC': log2fc,
                    'p_value': pval
                })

        # FDR correction
        if pairwise_results:
            pairwise_df = pd.DataFrame(pairwise_results)
            _, pvals_adj, _, _ = multipletests(pairwise_df['p_value'], method='fdr_bh')
            pairwise_df['p_adjusted'] = pvals_adj
            pairwise_df['significant'] = pairwise_df['p_adjusted'] < 0.05
        else:
            pairwise_df = pd.DataFrame()

        results[tumor_type] = {
            'cohort_stats': cohort_stats,
            'cms_stats': cms_stats,
            'pairwise_df': pairwise_df,
            'n_samples': len(tumor_only),
            'tumor_df': tumor_only
        }

        # Save tumor-type specific statistics
        if cohort_stats:
            stats_df = pd.DataFrame(cohort_stats).T
            stats_df.to_csv(f'{output_dir}/{gene_symbol}_{tumor_type}_cohort_statistics.csv')
            print(f"  Saved: {gene_symbol}_{tumor_type}_cohort_statistics.csv")

        if len(pairwise_df) > 0:
            pairwise_df.to_csv(f'{output_dir}/{gene_symbol}_{tumor_type}_pairwise_comparisons.csv', index=False)
            print(f"  Saved: {gene_symbol}_{tumor_type}_pairwise_comparisons.csv")

    return results


def plot_comprehensive(plot_df, master_df, gene_symbol, output_dir, stats_summary,
                       expr_unit=r'$\log_2(TPM + 1)$'):
    """Create multi-panel comprehensive figure."""
    fig = plt.figure(figsize=(16, 12))

    plot_order = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6', 'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']
    plot_order = [c for c in plot_order if c in plot_df['cohort'].unique()]
    palette = [COHORT_COLORS.get(c, '#666666') for c in plot_order]

    # Panel A: Cohort comparison
    ax1 = fig.add_subplot(2, 2, 1)

    bp1 = ax1.boxplot(
        [plot_df[plot_df['cohort'] == c]['expression'].dropna().values for c in plot_order],
        positions=range(len(plot_order)),
        widths=0.6,
        patch_artist=True,
        showfliers=True,
        flierprops={'marker': 'o', 'markersize': 2, 'alpha': 0.4}
    )

    for patch, color in zip(bp1['boxes'], palette):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
        patch.set_edgecolor('black')

    for median in bp1['medians']:
        median.set_color('black')
        median.set_linewidth(2)

    short_labels = ['2A', '2B', '4', '5', '6', 'Adj\nNorm', 'GTEx', 'CCLE'][:len(plot_order)]
    ax1.set_xticks(range(len(plot_order)))
    ax1.set_xticklabels(short_labels, fontsize=9)
    ax1.set_ylabel(expr_unit, fontsize=10)
    ax1.set_title(f'A. {gene_symbol} by Cohort', fontsize=11, fontweight='bold', loc='left')
    ax1.yaxis.grid(True, linestyle='--', alpha=0.3)

    tumor_end = len([c for c in plot_order if c.startswith('Cohort_')]) - 0.5
    ax1.axvline(x=tumor_end, color='gray', linestyle='--', linewidth=1, alpha=0.5)

    # Panel B: CMS comparison
    ax2 = fig.add_subplot(2, 2, 2)

    tumor_df = plot_df[plot_df['tissue_type'] == 'Primary_Tumor'].copy()
    valid_cms = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
    cms_filtered = tumor_df[tumor_df['CMS'].isin(valid_cms)].drop_duplicates(subset=['sample_id'])

    if len(cms_filtered) > 0:
        cms_present = [c for c in valid_cms if c in cms_filtered['CMS'].values]
        cms_palette = [CMS_COLORS[c] for c in cms_present]

        bp2 = ax2.boxplot(
            [cms_filtered[cms_filtered['CMS'] == c]['expression'].dropna().values for c in cms_present],
            positions=range(len(cms_present)),
            widths=0.6,
            patch_artist=True,
            showfliers=True,
            flierprops={'marker': 'o', 'markersize': 2, 'alpha': 0.4}
        )

        for patch, color in zip(bp2['boxes'], cms_palette):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
            patch.set_edgecolor('black')

        for median in bp2['medians']:
            median.set_color('black')
            median.set_linewidth(2)

        ax2.set_xticks(range(len(cms_present)))
        ax2.set_xticklabels(cms_present, fontsize=9)

        if 'GTEx_Normal' in plot_df['cohort'].unique():
            gtex_median = plot_df[plot_df['cohort'] == 'GTEx_Normal']['expression'].median()
            ax2.axhline(y=gtex_median, color='#1ABC9C', linestyle='--', alpha=0.7, linewidth=1.5)

    ax2.set_ylabel(expr_unit, fontsize=10)
    ax2.set_title(f'B. {gene_symbol} by CMS Subtype', fontsize=11, fontweight='bold', loc='left')
    ax2.yaxis.grid(True, linestyle='--', alpha=0.3)

    # Panel C: Tumor vs Normal
    ax3 = fig.add_subplot(2, 2, 3)

    tumor_expr = master_df[master_df['tissue_type'] == 'Primary_Tumor']['expression']
    tcga_adj_expr = master_df[master_df['tissue_type'] == 'TCGA_Adjacent']['expression']
    gtex_expr = master_df[master_df['tissue_type'] == 'GTEx_Normal']['expression']

    tissue_data = []
    tissue_labels = []
    tissue_colors = []

    if len(tumor_expr) > 0:
        tissue_data.append(tumor_expr.dropna().values)
        tissue_labels.append(f'Tumor\n(n={len(tumor_expr)})')
        tissue_colors.append('#E74C3C')

    if len(tcga_adj_expr) > 0:
        tissue_data.append(tcga_adj_expr.dropna().values)
        tissue_labels.append(f'Adjacent\nNormal\n(n={len(tcga_adj_expr)})')
        tissue_colors.append('#7F8C8D')

    if len(gtex_expr) > 0:
        tissue_data.append(gtex_expr.dropna().values)
        tissue_labels.append(f'GTEx\nNormal\n(n={len(gtex_expr)})')
        tissue_colors.append('#1ABC9C')

    if len(tissue_data) > 0:
        bp3 = ax3.boxplot(tissue_data, positions=range(len(tissue_data)), widths=0.5,
                          patch_artist=True, showfliers=True,
                          flierprops={'marker': 'o', 'markersize': 2, 'alpha': 0.4})

        for patch, color in zip(bp3['boxes'], tissue_colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
            patch.set_edgecolor('black')

        for median in bp3['medians']:
            median.set_color('black')
            median.set_linewidth(2)

        ax3.set_xticks(range(len(tissue_data)))
        ax3.set_xticklabels(tissue_labels, fontsize=9)

    ax3.set_ylabel(expr_unit, fontsize=10)
    ax3.set_title(f'C. {gene_symbol}: Tumor vs Normal', fontsize=11, fontweight='bold', loc='left')
    ax3.yaxis.grid(True, linestyle='--', alpha=0.3)

    # Panel D: Summary statistics table
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.axis('off')

    table_data = []
    for cohort in plot_order:
        if cohort in stats_summary.index:
            row = stats_summary.loc[cohort]
            cohort_name = cohort.replace('Cohort_', '').replace('_', ' ')
            table_data.append([
                cohort_name,
                int(row['count']),
                f'{row["median"]:.2f}',
                f'{row["mean"]:.2f}',
                f'{row["std"]:.2f}'
            ])

    if len(table_data) > 0:
        table = ax4.table(
            cellText=table_data,
            colLabels=['Group', 'N', 'Median', 'Mean', 'SD'],
            loc='center',
            cellLoc='center',
            colWidths=[0.3, 0.15, 0.18, 0.18, 0.18]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.2, 1.4)

        for i in range(5):
            table[(0, i)].set_facecolor('#E8E8E8')
            table[(0, i)].set_text_props(fontweight='bold')

    ax4.set_title(f'D. Summary Statistics', fontsize=11, fontweight='bold', loc='left', y=0.95)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_comprehensive_analysis.png', dpi=300, bbox_inches='tight')
    plt.savefig(f'{output_dir}/{gene_symbol}_comprehensive_analysis.pdf', bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_comprehensive_analysis.png")


# =============================================================================
# TARGET EVALUATION REPORT
# =============================================================================

def generate_target_report(gene_symbol, gene_id, master_df, plot_df, stats_summary,
                           pairwise_df, cms_stats, kw_stat, kw_pval, cms_kw_stat,
                           cms_kw_pval, cms_pairwise_df, output_dir):
    """Generate comprehensive target evaluation report in markdown."""

    report_path = f'{output_dir}/{gene_symbol}_target_evaluation_report.md'

    # Pre-calculate key metrics for Target Evaluation Summary
    tumor_median = master_df[master_df['tissue_type'] == 'Primary_Tumor']['expression'].median()
    gtex_median = master_df[master_df['tissue_type'] == 'GTEx_Normal']['expression'].median()
    adj_median = master_df[master_df['tissue_type'] == 'TCGA_Adjacent']['expression'].median()
    ccle_median = master_df[master_df['tissue_type'] == 'CCLE_CRC']['expression'].median()

    log2fc_gtex = tumor_median - gtex_median if not pd.isna(tumor_median) and not pd.isna(gtex_median) else None
    log2fc_adj = tumor_median - adj_median if not pd.isna(tumor_median) and not pd.isna(adj_median) else None

    with open(report_path, 'w') as f:
        # Header
        f.write(f"# {gene_symbol} Target Evaluation Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Gene ID:** {gene_id}\n\n")
        f.write("---\n\n")

        # Executive Summary
        f.write("## Executive Summary\n\n")

        if log2fc_gtex is not None:
            direction = "upregulated" if log2fc_gtex > 0 else "downregulated"
            f.write(f"**{gene_symbol}** is **{direction}** in CRC tumors compared to normal colon tissue ")
            f.write(f"(log2 fold change: **{log2fc_gtex:.2f}**).\n\n")

        if kw_pval is not None:
            sig_text = "significant" if kw_pval < 0.05 else "not significant"
            f.write(f"Overall expression differences across cohorts are **{sig_text}** ")
            f.write(f"(Kruskal-Wallis p = {kw_pval:.2e}).\n\n")

        # Data Overview
        f.write("## Data Overview\n\n")
        f.write("| Sample Group | N |\n")
        f.write("|--------------|---|\n")
        for tissue in ['Primary_Tumor', 'TCGA_Adjacent', 'GTEx_Normal']:
            n = len(master_df[master_df['tissue_type'] == tissue])
            f.write(f"| {tissue.replace('_', ' ')} | {n} |\n")
        f.write("\n")

        # Cohort Statistics
        f.write("## Expression by CRC Cohort\n\n")
        f.write("| Cohort | Definition | N | Median | Mean | SD |\n")
        f.write("|--------|------------|---|--------|------|----|\n")

        cohort_defs = {
            'Cohort_2A': 'RAS-mutant MSS',
            'Cohort_2B': 'RAS-WT MSS',
            'Cohort_4': 'Early Stage (I/II)',
            'Cohort_5': 'All MSS',
            'Cohort_6': 'MSI-H',
            'TCGA_Adjacent': 'Adjacent Normal',
            'GTEx_Normal': 'Normal Colon (GTEx)'
        }

        for cohort in ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6', 'TCGA_Adjacent', 'GTEx_Normal']:
            if cohort in stats_summary.index:
                row = stats_summary.loc[cohort]
                f.write(f"| {cohort.replace('Cohort_', '')} | {cohort_defs.get(cohort, '')} | ")
                f.write(f"{int(row['count'])} | {row['median']:.3f} | {row['mean']:.3f} | {row['std']:.3f} |\n")
        f.write("\n")

        # Pairwise Comparisons
        f.write("## Statistical Comparisons (Tumor vs Normal)\n\n")
        if len(pairwise_df) > 0:
            f.write("| Tumor Cohort | vs Normal | Log2FC | p-value | FDR | Significant |\n")
            f.write("|--------------|-----------|--------|---------|-----|-------------|\n")
            for _, row in pairwise_df.iterrows():
                sig = "✓" if row['significant'] else ""
                f.write(f"| {row['Tumor_Cohort'].replace('Cohort_', '')} | {row['Normal_Group'].replace('_', ' ')} | ")
                f.write(f"{row['Log2FC']:.3f} | {row['p_value']:.2e} | {row['p_adjusted']:.2e} | {sig} |\n")
            f.write("\n")

        # CMS Analysis
        f.write("## CMS Subtype Analysis\n\n")
        if cms_stats is not None and len(cms_stats) > 0:
            f.write("| CMS Subtype | Description | N | Median | Mean | SD |\n")
            f.write("|-------------|-------------|---|--------|------|----|\n")
            cms_desc = {'CMS1': 'MSI Immune', 'CMS2': 'Canonical', 'CMS3': 'Metabolic', 'CMS4': 'Mesenchymal'}
            for cms in ['CMS1', 'CMS2', 'CMS3', 'CMS4']:
                if cms in cms_stats.index:
                    row = cms_stats.loc[cms]
                    f.write(f"| {cms} | {cms_desc[cms]} | {int(row['count'])} | ")
                    f.write(f"{row['median']:.3f} | {row['mean']:.3f} | {row['std']:.3f} |\n")
            f.write("\n")

            if cms_kw_pval is not None:
                f.write(f"**Kruskal-Wallis test across CMS subtypes:** H = {cms_kw_stat:.3f}, p = {cms_kw_pval:.2e}\n\n")

            # CMS Pairwise Comparisons
            if cms_pairwise_df is not None and len(cms_pairwise_df) > 0:
                f.write("### CMS Pairwise Comparisons (Bonferroni-corrected)\n\n")
                f.write("| Comparison | Δ Median | p-value | p-adjusted | Significant |\n")
                f.write("|------------|----------|---------|------------|-------------|\n")
                for _, row in cms_pairwise_df.iterrows():
                    sig = "Yes" if row['significant'] else "No"
                    f.write(f"| {row['CMS_1']} vs {row['CMS_2']} | {row['Median_Diff']:+.3f} | ")
                    f.write(f"{row['p_value']:.2e} | {row['p_adjusted']:.2e} | {sig} |\n")
                f.write("\n")
        else:
            f.write("*CMS data not available*\n\n")

        # Figures
        f.write("## Figures\n\n")
        f.write(f"1. **Cohort Comparison:** `{gene_symbol}_cohort_boxplot.png`\n")
        f.write(f"2. **Violin Plot:** `{gene_symbol}_cohort_violin.png`\n")
        f.write(f"3. **CMS Analysis:** `{gene_symbol}_CMS_boxplot.png`\n")
        f.write(f"4. **Comprehensive:** `{gene_symbol}_comprehensive_analysis.png`\n\n")

        # Key Findings
        f.write("## Key Findings\n\n")

        if len(pairwise_df) > 0:
            sig_results = pairwise_df[pairwise_df['significant']]
            if len(sig_results) > 0:
                f.write("### Significant Differential Expression\n\n")
                for _, row in sig_results.iterrows():
                    direction = "↑ higher" if row['Log2FC'] > 0 else "↓ lower"
                    f.write(f"- **{row['Tumor_Cohort'].replace('Cohort_', 'Cohort ')}** vs {row['Normal_Group'].replace('_', ' ')}: ")
                    f.write(f"{direction} (log2FC = {row['Log2FC']:.2f}, FDR = {row['p_adjusted']:.2e})\n")
                f.write("\n")

        # Target Evaluation Summary
        f.write("## Target Evaluation Summary\n\n")

        # Tumor-specificity assessment
        if log2fc_gtex is not None and log2fc_adj is not None:
            fc_linear_gtex = 2 ** abs(log2fc_gtex)
            fc_linear_adj = 2 ** abs(log2fc_adj)
            if abs(log2fc_gtex) >= 2:  # >= 4-fold
                specificity = "Strong"
            elif abs(log2fc_gtex) >= 1:  # >= 2-fold
                specificity = "Moderate"
            else:
                specificity = "Weak"
            direction = "upregulated" if log2fc_gtex > 0 else "downregulated"
            f.write(f"- **Tumor-specificity**: {specificity} - consistently {direction} ")
            f.write(f"~{fc_linear_gtex:.0f}x vs GTEx normal, ~{fc_linear_adj:.0f}x vs adjacent normal\n")

        # Therapeutic window
        if tumor_median is not None and gtex_median is not None:
            separation = abs(tumor_median - gtex_median)
            if separation >= 2:
                window = "Good"
            elif separation >= 1:
                window = "Moderate"
            else:
                window = "Limited"
            f.write(f"- **Therapeutic window**: {window} - tumor median ({tumor_median:.2f}) ")
            f.write(f"vs normal median ({gtex_median:.2f})\n")

        # CMS pattern assessment
        if cms_stats is not None and len(cms_stats) > 0 and cms_pairwise_df is not None and len(cms_pairwise_df) > 0:
            # Find which CMS has highest median
            cms_medians = cms_stats['median'].to_dict()
            highest_cms = max(cms_medians, key=cms_medians.get)
            lowest_cms = min(cms_medians, key=cms_medians.get)
            cms_desc_map = {'CMS1': 'MSI Immune', 'CMS2': 'Canonical', 'CMS3': 'Metabolic', 'CMS4': 'Mesenchymal'}

            # Check if highest is significantly different from others
            sig_cms_pairs = cms_pairwise_df[cms_pairwise_df['significant']]
            if len(sig_cms_pairs) > 0:
                # Find significant patterns
                sig_pairs_str = [f"{r['CMS_1']} vs {r['CMS_2']}" for _, r in sig_cms_pairs.iterrows()]
                f.write(f"- **CMS subtype pattern**: {highest_cms} ({cms_desc_map[highest_cms]}) shows highest expression; ")
                f.write(f"{lowest_cms} ({cms_desc_map[lowest_cms]}) shows lowest. ")
                f.write(f"Significant differences: {', '.join(sig_pairs_str)}\n")
            else:
                f.write(f"- **CMS subtype pattern**: Expression similar across CMS1/2/4 (no significant pairwise differences after correction); ")
                f.write(f"{lowest_cms} ({cms_desc_map[lowest_cms]}) shows lowest expression\n")

        # Cell line expression
        if not pd.isna(ccle_median) and ccle_median > 0:
            n_ccle = len(master_df[master_df['tissue_type'] == 'CCLE_CRC'])
            f.write(f"- **Cell line expression**: Median {ccle_median:.2f} in {n_ccle} CRC cell lines, ")
            f.write("supporting druggability studies\n")

        # RAS status independence
        if 'Cohort_2A' in stats_summary.index and 'Cohort_2B' in stats_summary.index:
            ras_mut_median = stats_summary.loc['Cohort_2A', 'median']
            ras_wt_median = stats_summary.loc['Cohort_2B', 'median']
            diff = abs(ras_mut_median - ras_wt_median)
            if diff < 0.5:
                f.write(f"- **RAS status**: Similar expression in RAS-mutant ({ras_mut_median:.2f}) and RAS-WT ({ras_wt_median:.2f}) tumors\n")
            else:
                higher = "RAS-mutant" if ras_mut_median > ras_wt_median else "RAS-WT"
                f.write(f"- **RAS status**: Higher in {higher} tumors (mut: {ras_mut_median:.2f}, WT: {ras_wt_median:.2f})\n")

        # MSI status
        if 'Cohort_5' in stats_summary.index and 'Cohort_6' in stats_summary.index:
            mss_median = stats_summary.loc['Cohort_5', 'median']
            msi_median = stats_summary.loc['Cohort_6', 'median']
            diff = abs(mss_median - msi_median)
            if diff < 0.5:
                f.write(f"- **MSI status**: Similar expression in MSS ({mss_median:.2f}) and MSI-H ({msi_median:.2f}) tumors\n")
            else:
                higher = "MSS" if mss_median > msi_median else "MSI-H"
                f.write(f"- **MSI status**: Higher in {higher} tumors (MSS: {mss_median:.2f}, MSI-H: {msi_median:.2f})\n")

        f.write("\n")

        # Output Files
        f.write("## Output Files\n\n")
        f.write(f"- `{gene_symbol}_cohort_statistics.csv`\n")
        f.write(f"- `{gene_symbol}_pairwise_comparisons.csv`\n")
        f.write(f"- `{gene_symbol}_cms_pairwise_comparisons.csv`\n")
        f.write(f"- `{gene_symbol}_expression_data.csv`\n")
        f.write(f"- `{gene_symbol}_cohort_boxplot.png/pdf`\n")
        f.write(f"- `{gene_symbol}_cohort_violin.png`\n")
        f.write(f"- `{gene_symbol}_CMS_boxplot.png`\n")
        f.write(f"- `{gene_symbol}_comprehensive_analysis.png/pdf`\n")

    print(f"  Saved: {gene_symbol}_target_evaluation_report.md")
    return report_path


def generate_pdf_report(gene_symbol, gene_id, master_df, plot_df, stats_summary,
                        pairwise_df, cms_stats, kw_stat, kw_pval, cms_kw_stat,
                        cms_kw_pval, cms_pairwise_df, tumor_type_stats, tumor_type_by_cohort,
                        tumor_type_analysis, output_dir):
    """Generate comprehensive target evaluation report as PDF."""
    from matplotlib.backends.backend_pdf import PdfPages

    pdf_path = f'{output_dir}/{gene_symbol}_target_evaluation_report.pdf'

    # Pre-calculate key metrics for Target Evaluation Summary
    tumor_median = master_df[master_df['tissue_type'] == 'Primary_Tumor']['expression'].median()
    gtex_median = master_df[master_df['tissue_type'] == 'GTEx_Normal']['expression'].median()
    adj_median = master_df[master_df['tissue_type'] == 'TCGA_Adjacent']['expression'].median()
    ccle_median = master_df[master_df['tissue_type'] == 'CCLE_CRC']['expression'].median()

    log2fc_gtex = tumor_median - gtex_median if not pd.isna(tumor_median) and not pd.isna(gtex_median) else None
    log2fc_adj = tumor_median - adj_median if not pd.isna(tumor_median) and not pd.isna(adj_median) else None

    with PdfPages(pdf_path) as pdf:
        # Page 1: Title, Executive Summary, Target Evaluation Summary
        fig = plt.figure(figsize=(11, 8.5))
        ax = fig.add_subplot(111)
        ax.axis('off')

        # Title
        ax.text(0.5, 0.97, f'{gene_symbol} Target Evaluation Report',
                fontsize=24, fontweight='bold', ha='center', va='top', transform=ax.transAxes)
        ax.text(0.5, 0.91, f'Gene ID: {gene_id}',
                fontsize=11, ha='center', va='top', transform=ax.transAxes)
        ax.text(0.5, 0.88, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                fontsize=9, ha='center', va='top', transform=ax.transAxes, color='gray')

        # Executive Summary (compact)
        ax.text(0.05, 0.82, 'Executive Summary', fontsize=14, fontweight='bold',
                va='top', transform=ax.transAxes)

        summary_text = ""
        if log2fc_gtex is not None:
            direction = "upregulated" if log2fc_gtex > 0 else "downregulated"
            fc_linear = 2 ** abs(log2fc_gtex)
            summary_text += f"• {gene_symbol} is {direction} in CRC tumors vs normal (log2FC: {log2fc_gtex:.2f}, ~{fc_linear:.0f}x)\n"

        if kw_pval is not None:
            sig_text = "significant" if kw_pval < 0.05 else "not significant"
            summary_text += f"• Expression differences across cohorts are {sig_text} (p = {kw_pval:.2e})\n"

        n_tumor = len(master_df[master_df['tissue_type'] == 'Primary_Tumor'])
        n_adj = len(master_df[master_df['tissue_type'] == 'TCGA_Adjacent'])
        n_gtex = len(master_df[master_df['tissue_type'] == 'GTEx_Normal'])
        n_ccle = len(master_df[master_df['tissue_type'] == 'CCLE_CRC'])
        summary_text += f"• Samples: {n_tumor} tumor, {n_adj} TCGA adjacent, {n_gtex} GTEx normal"
        if n_ccle > 0:
            summary_text += f", {n_ccle} cell lines"

        ax.text(0.05, 0.77, summary_text, fontsize=10, va='top', transform=ax.transAxes,
                family='monospace')

        # Target Evaluation Summary (NEW)
        ax.text(0.05, 0.60, 'Target Evaluation Summary', fontsize=14, fontweight='bold',
                va='top', transform=ax.transAxes)

        eval_text = ""

        # Tumor-specificity
        if log2fc_gtex is not None and log2fc_adj is not None:
            fc_linear_gtex = 2 ** abs(log2fc_gtex)
            fc_linear_adj = 2 ** abs(log2fc_adj)
            if abs(log2fc_gtex) >= 2:
                specificity = "Strong"
            elif abs(log2fc_gtex) >= 1:
                specificity = "Moderate"
            else:
                specificity = "Weak"
            direction = "upregulated" if log2fc_gtex > 0 else "downregulated"
            eval_text += f"• Tumor-specificity: {specificity} (~{fc_linear_gtex:.0f}x vs GTEx, ~{fc_linear_adj:.0f}x vs adjacent)\n"

        # Therapeutic window
        if tumor_median is not None and gtex_median is not None:
            separation = abs(tumor_median - gtex_median)
            if separation >= 2:
                window = "Good"
            elif separation >= 1:
                window = "Moderate"
            else:
                window = "Limited"
            eval_text += f"• Therapeutic window: {window} (tumor: {tumor_median:.2f}, normal: {gtex_median:.2f})\n"

        # CMS pattern
        if cms_stats is not None and len(cms_stats) > 0:
            cms_medians = cms_stats['median'].to_dict()
            highest_cms = max(cms_medians, key=cms_medians.get)
            lowest_cms = min(cms_medians, key=cms_medians.get)
            cms_desc_map = {'CMS1': 'MSI Immune', 'CMS2': 'Canonical', 'CMS3': 'Metabolic', 'CMS4': 'Mesenchymal'}

            if cms_pairwise_df is not None and len(cms_pairwise_df) > 0:
                sig_cms = cms_pairwise_df[cms_pairwise_df['significant']]
                if len(sig_cms) > 0:
                    sig_pairs = [f"{r['CMS_1']}/{r['CMS_2']}" for _, r in sig_cms.iterrows()]
                    eval_text += f"• CMS pattern: Significant diffs in {', '.join(sig_pairs[:3])}\n"
                else:
                    eval_text += f"• CMS pattern: CMS1/2/4 similar; {lowest_cms} lowest (no sig. pairwise diffs)\n"

        # Cell line expression
        if not pd.isna(ccle_median) and ccle_median > 0:
            eval_text += f"• Cell lines: Median {ccle_median:.2f} in {n_ccle} CRC lines\n"

        # RAS status
        if 'Cohort_2A' in stats_summary.index and 'Cohort_2B' in stats_summary.index:
            ras_mut = stats_summary.loc['Cohort_2A', 'median']
            ras_wt = stats_summary.loc['Cohort_2B', 'median']
            if abs(ras_mut - ras_wt) < 0.5:
                eval_text += f"• RAS status: Similar (mut: {ras_mut:.2f}, WT: {ras_wt:.2f})\n"
            else:
                higher = "RAS-mut" if ras_mut > ras_wt else "RAS-WT"
                eval_text += f"• RAS status: Higher in {higher} (mut: {ras_mut:.2f}, WT: {ras_wt:.2f})\n"

        # MSI status
        if 'Cohort_5' in stats_summary.index and 'Cohort_6' in stats_summary.index:
            mss = stats_summary.loc['Cohort_5', 'median']
            msi = stats_summary.loc['Cohort_6', 'median']
            if abs(mss - msi) < 0.5:
                eval_text += f"• MSI status: Similar (MSS: {mss:.2f}, MSI-H: {msi:.2f})\n"
            else:
                higher = "MSS" if mss > msi else "MSI-H"
                eval_text += f"• MSI status: Higher in {higher} (MSS: {mss:.2f}, MSI-H: {msi:.2f})\n"

        ax.text(0.05, 0.55, eval_text, fontsize=10, va='top', transform=ax.transAxes,
                family='monospace')

        # Cohort Definitions (compact)
        ax.text(0.05, 0.26, 'CRC Cohort Definitions', fontsize=12, fontweight='bold',
                va='top', transform=ax.transAxes)

        cohort_defs = [
            ['2A', 'RAS-mutant MSS'],
            ['2B', 'RAS wild-type MSS'],
            ['4', 'Early Stage (I/II)'],
            ['5', 'All MSS'],
            ['6', 'MSI-H'],
            ['Adj Normal', 'TCGA Adjacent'],
            ['GTEx', 'Normal Colon'],
            ['CCLE', 'CRC Cell Lines']
        ]

        def_table = ax.table(cellText=cohort_defs,
                            colLabels=['Cohort', 'Definition'],
                            loc='center', cellLoc='left',
                            bbox=[0.05, 0.02, 0.9, 0.22])
        def_table.auto_set_font_size(False)
        def_table.set_fontsize(9)
        for i in range(2):
            def_table[(0, i)].set_facecolor('#E8E8E8')
            def_table[(0, i)].set_text_props(fontweight='bold')

        plt.tight_layout()
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

        # Page 2: Cohort Statistics Table
        fig = plt.figure(figsize=(11, 8.5))
        ax = fig.add_subplot(111)
        ax.axis('off')

        ax.text(0.5, 0.95, 'Expression Statistics by Cohort',
                fontsize=18, fontweight='bold', ha='center', va='top', transform=ax.transAxes)

        cohort_order = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6',
                        'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']
        table_data = []
        for cohort in cohort_order:
            if cohort in stats_summary.index:
                row = stats_summary.loc[cohort]
                cohort_name = cohort.replace('Cohort_', '').replace('_', ' ')
                table_data.append([cohort_name, int(row['count']),
                                   f'{row["median"]:.2f}', f'{row["mean"]:.2f}', f'{row["std"]:.2f}'])

        if table_data:
            table = ax.table(cellText=table_data,
                            colLabels=['Cohort', 'N', 'Median', 'Mean', 'SD'],
                            loc='center', cellLoc='center',
                            bbox=[0.1, 0.3, 0.8, 0.5])
            table.auto_set_font_size(False)
            table.set_fontsize(11)
            table.scale(1.2, 1.8)
            for i in range(5):
                table[(0, i)].set_facecolor('#E8E8E8')
                table[(0, i)].set_text_props(fontweight='bold')

        plt.tight_layout()
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

        # Page 3: Cohort Boxplot
        plot_order = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6',
                      'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']
        plot_order = [c for c in plot_order if c in plot_df['cohort'].unique()]

        if len(plot_order) > 0:
            fig, ax = plt.subplots(figsize=(11, 8.5))
            palette = [COHORT_COLORS.get(c, '#666666') for c in plot_order]

            bp = ax.boxplot(
                [plot_df[plot_df['cohort'] == c]['expression'].dropna().values for c in plot_order],
                positions=range(len(plot_order)), widths=0.6, patch_artist=True, showfliers=True,
                flierprops={'marker': 'o', 'markersize': 3, 'alpha': 0.4})

            for patch, color in zip(bp['boxes'], palette):
                patch.set_facecolor(color)
                patch.set_alpha(0.7)
                patch.set_edgecolor('black')

            for median in bp['medians']:
                median.set_color('black')
                median.set_linewidth(2)

            labels = [COHORT_LABELS.get(c, c) for c in plot_order]
            ax.set_xticks(range(len(plot_order)))
            ax.set_xticklabels(labels, fontsize=9)
            ax.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=12)
            ax.set_title(f'{gene_symbol} Expression Across CRC Cohorts and Normal Tissues',
                         fontsize=14, fontweight='bold')
            ax.yaxis.grid(True, linestyle='--', alpha=0.3)

            tumor_end = len([c for c in plot_order if c.startswith('Cohort_')]) - 0.5
            ax.axvline(x=tumor_end, color='gray', linestyle='--', linewidth=1, alpha=0.5)

            plt.tight_layout()
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()

        # Page 4: CMS Boxplot
        tumor_df = plot_df[plot_df['tissue_type'] == 'Primary_Tumor'].copy()
        valid_cms = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
        cms_filtered = tumor_df[tumor_df['CMS'].isin(valid_cms)].drop_duplicates(subset=['sample_id'])

        if len(cms_filtered) > 0:
            fig, ax = plt.subplots(figsize=(11, 8.5))
            cms_order = [c for c in valid_cms if c in cms_filtered['CMS'].values]
            cms_palette = [CMS_COLORS[c] for c in cms_order]

            bp = ax.boxplot(
                [cms_filtered[cms_filtered['CMS'] == c]['expression'].dropna().values for c in cms_order],
                positions=range(len(cms_order)), widths=0.6, patch_artist=True, showfliers=True)

            for patch, color in zip(bp['boxes'], cms_palette):
                patch.set_facecolor(color)
                patch.set_alpha(0.7)
                patch.set_edgecolor('black')

            cms_labels = {'CMS1': 'CMS1\nMSI Immune', 'CMS2': 'CMS2\nCanonical',
                          'CMS3': 'CMS3\nMetabolic', 'CMS4': 'CMS4\nMesenchymal'}
            ax.set_xticks(range(len(cms_order)))
            ax.set_xticklabels([cms_labels[c] for c in cms_order], fontsize=10)
            ax.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=12)
            ax.set_title(f'{gene_symbol} Expression by CMS Subtype', fontsize=14, fontweight='bold')
            ax.yaxis.grid(True, linestyle='--', alpha=0.3)

            if 'GTEx_Normal' in plot_df['cohort'].unique():
                gtex_median = plot_df[plot_df['cohort'] == 'GTEx_Normal']['expression'].median()
                ax.axhline(y=gtex_median, color='#1ABC9C', linestyle='--', alpha=0.7,
                           label=f'GTEx Normal: {gtex_median:.2f}')
                ax.legend(loc='upper right')

            plt.tight_layout()
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()

        # Page 5: CMS Pairwise Comparisons (NEW)
        if cms_pairwise_df is not None and len(cms_pairwise_df) > 0:
            fig = plt.figure(figsize=(11, 8.5))
            ax = fig.add_subplot(111)
            ax.axis('off')

            ax.text(0.5, 0.95, 'CMS Subtype Pairwise Comparisons',
                    fontsize=18, fontweight='bold', ha='center', va='top', transform=ax.transAxes)
            ax.text(0.5, 0.89, '(Bonferroni-corrected for multiple testing)',
                    fontsize=12, ha='center', va='top', transform=ax.transAxes, color='gray')

            table_data = []
            for _, row in cms_pairwise_df.iterrows():
                sig = "Yes" if row['significant'] else "No"
                table_data.append([
                    f"{row['CMS_1']} vs {row['CMS_2']}",
                    int(row['N_1']),
                    int(row['N_2']),
                    f"{row['Median_1']:.2f}",
                    f"{row['Median_2']:.2f}",
                    f"{row['Median_Diff']:+.3f}",
                    f"{row['p_value']:.2e}",
                    f"{row['p_adjusted']:.2e}",
                    sig
                ])

            table = ax.table(cellText=table_data,
                            colLabels=['Comparison', 'N1', 'N2', 'Med1', 'Med2', 'Δ Med', 'p-value', 'p-adj', 'Sig'],
                            loc='center', cellLoc='center',
                            bbox=[0.02, 0.35, 0.96, 0.45])
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            for i in range(9):
                table[(0, i)].set_facecolor('#E8E8E8')
                table[(0, i)].set_text_props(fontweight='bold')

            # Add interpretation text
            sig_pairs = cms_pairwise_df[cms_pairwise_df['significant']]
            nonsig_pairs = cms_pairwise_df[~cms_pairwise_df['significant']]

            interp_text = "Interpretation:\n"
            if len(sig_pairs) > 0:
                sig_list = [f"{r['CMS_1']} vs {r['CMS_2']}" for _, r in sig_pairs.iterrows()]
                interp_text += f"• Significant differences: {', '.join(sig_list)}\n"
            if len(nonsig_pairs) > 0:
                nonsig_list = [f"{r['CMS_1']}/{r['CMS_2']}" for _, r in nonsig_pairs.iterrows()]
                interp_text += f"• Not significantly different: {', '.join(nonsig_list)}\n"

            ax.text(0.05, 0.28, interp_text, fontsize=11, va='top', transform=ax.transAxes)

            plt.tight_layout()
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()

        # Page 6: Statistical Comparisons
        if len(pairwise_df) > 0:
            fig = plt.figure(figsize=(11, 8.5))
            ax = fig.add_subplot(111)
            ax.axis('off')

            ax.text(0.5, 0.95, 'Statistical Comparisons (Tumor vs Normal)',
                    fontsize=16, fontweight='bold', ha='center', va='top', transform=ax.transAxes)

            table_data = []
            for _, row in pairwise_df.iterrows():
                sig = "Yes" if row['significant'] else "No"
                table_data.append([
                    row['Tumor_Cohort'].replace('Cohort_', ''),
                    row['Normal_Group'].replace('_', ' '),
                    f"{row['Log2FC']:.2f}",
                    f"{row['p_value']:.2e}",
                    f"{row['p_adjusted']:.2e}",
                    sig
                ])

            table = ax.table(cellText=table_data,
                            colLabels=['Tumor', 'vs Normal', 'Log2FC', 'p-value', 'FDR', 'Sig'],
                            loc='center', cellLoc='center',
                            bbox=[0.05, 0.2, 0.9, 0.65])
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            for i in range(6):
                table[(0, i)].set_facecolor('#E8E8E8')
                table[(0, i)].set_text_props(fontweight='bold')

            plt.tight_layout()
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()

        # Page 6: COAD vs READ Comparison
        tumor_df = plot_df[plot_df['tissue_type'] == 'Primary_Tumor'].copy()
        if 'tumor_type' in tumor_df.columns:
            tumor_df = tumor_df[tumor_df['tumor_type'].isin(['COAD', 'READ'])].drop_duplicates(subset=['sample_id'])

            if len(tumor_df) > 0:
                fig, ax = plt.subplots(figsize=(11, 8.5))

                tumor_order = ['COAD', 'READ']
                data = [tumor_df[tumor_df['tumor_type'] == t]['expression'].dropna().values for t in tumor_order]

                bp = ax.boxplot(data, positions=[0, 1], widths=0.5, patch_artist=True, showfliers=True,
                               flierprops={'marker': 'o', 'markersize': 4, 'alpha': 0.5})

                for patch, color in zip(bp['boxes'], ['#3498DB', '#E74C3C']):
                    patch.set_facecolor(color)
                    patch.set_alpha(0.7)
                    patch.set_edgecolor('black')

                for median in bp['medians']:
                    median.set_color('black')
                    median.set_linewidth(2)

                ax.set_xticks([0, 1])
                ax.set_xticklabels(['COAD\n(Colon)', 'READ\n(Rectal)'], fontsize=12)
                ax.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=12)
                ax.set_title(f'{gene_symbol} Expression: COAD vs READ', fontsize=14, fontweight='bold')
                ax.yaxis.grid(True, linestyle='--', alpha=0.3)

                # Add statistics text
                if tumor_type_stats is not None:
                    stats_text = f"COAD: n={tumor_type_stats['coad_n']}, median={tumor_type_stats['coad_median']:.2f}\n"
                    stats_text += f"READ: n={tumor_type_stats['read_n']}, median={tumor_type_stats['read_median']:.2f}\n"
                    stats_text += f"Log2FC (COAD-READ): {tumor_type_stats['log2fc']:.3f}\n"
                    stats_text += f"p-value: {tumor_type_stats['pval']:.2e}"
                    ax.text(0.95, 0.95, stats_text, transform=ax.transAxes, ha='right', va='top',
                            fontsize=10, bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

                plt.tight_layout()
                pdf.savefig(fig, bbox_inches='tight')
                plt.close()

        # Page 7: COAD vs READ by Cohort
        if tumor_type_by_cohort is not None and len(tumor_type_by_cohort) > 0:
            fig = plt.figure(figsize=(11, 8.5))
            ax = fig.add_subplot(111)
            ax.axis('off')

            ax.text(0.5, 0.95, f'{gene_symbol}: COAD vs READ by Cohort',
                    fontsize=16, fontweight='bold', ha='center', va='top', transform=ax.transAxes)

            table_data = []
            for _, row in tumor_type_by_cohort.iterrows():
                sig = "Yes" if row['pval'] < 0.05 else "No"
                table_data.append([
                    row['cohort'].replace('Cohort_', ''),
                    int(row['coad_n']),
                    int(row['read_n']),
                    f"{row['coad_median']:.2f}",
                    f"{row['read_median']:.2f}",
                    f"{row['log2fc']:.3f}",
                    f"{row['pval']:.2e}",
                    sig
                ])

            table = ax.table(cellText=table_data,
                            colLabels=['Cohort', 'COAD N', 'READ N', 'COAD Med', 'READ Med', 'Log2FC', 'p-value', 'Sig'],
                            loc='center', cellLoc='center',
                            bbox=[0.05, 0.3, 0.9, 0.55])
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            for i in range(8):
                table[(0, i)].set_facecolor('#E8E8E8')
                table[(0, i)].set_text_props(fontweight='bold')

            # Add legend
            ax.text(0.5, 0.15, 'Log2FC = COAD median - READ median\nPositive values indicate higher expression in COAD (Colon)',
                    transform=ax.transAxes, ha='center', va='top', fontsize=10, style='italic')

            plt.tight_layout()
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()

        # =====================================================================
        # COAD and READ Separate Analyses
        # =====================================================================
        for tumor_type in ['COAD', 'READ']:
            if tumor_type_analysis is None or tumor_type not in tumor_type_analysis:
                continue
            tt_data = tumor_type_analysis[tumor_type]
            if not tt_data or tt_data.get('n_samples', 0) == 0:
                continue

            tumor_label = 'Colon (COAD)' if tumor_type == 'COAD' else 'Rectal (READ)'
            tumor_color = '#3498DB' if tumor_type == 'COAD' else '#E74C3C'

            # Page: Tumor Type Section Header + Statistics
            fig = plt.figure(figsize=(11, 8.5))
            ax = fig.add_subplot(111)
            ax.axis('off')

            ax.text(0.5, 0.95, f'{gene_symbol} Analysis: {tumor_label} Only',
                    fontsize=20, fontweight='bold', ha='center', va='top', transform=ax.transAxes,
                    color=tumor_color)
            ax.text(0.5, 0.88, f'Total {tumor_type} Samples: {tt_data["n_samples"]}',
                    fontsize=12, ha='center', va='top', transform=ax.transAxes)

            # Cohort Statistics Table
            ax.text(0.5, 0.78, 'Expression Statistics by Cohort',
                    fontsize=14, fontweight='bold', ha='center', va='top', transform=ax.transAxes)

            cohort_order = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6',
                           'TCGA_Adjacent', 'GTEx_Normal', f'CCLE_{tumor_type}']
            table_data = []
            for cohort in cohort_order:
                if cohort in tt_data['cohort_stats']:
                    cs = tt_data['cohort_stats'][cohort]
                    cohort_name = cohort.replace('Cohort_', '').replace('_', ' ')
                    table_data.append([cohort_name, int(cs['n']), f"{cs['median']:.2f}",
                                      f"{cs['mean']:.2f}", f"{cs['std']:.2f}"])

            if table_data:
                table = ax.table(cellText=table_data,
                                colLabels=['Cohort', 'N', 'Median', 'Mean', 'SD'],
                                loc='center', cellLoc='center',
                                bbox=[0.15, 0.35, 0.7, 0.38])
                table.auto_set_font_size(False)
                table.set_fontsize(10)
                for i in range(5):
                    table[(0, i)].set_facecolor(tumor_color)
                    table[(0, i)].set_text_props(fontweight='bold', color='white')

            plt.tight_layout()
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()

            # Page: Tumor Type Cohort Boxplot
            tumor_df = tt_data.get('tumor_df', pd.DataFrame())
            if len(tumor_df) > 0:
                fig, ax = plt.subplots(figsize=(11, 8.5))

                # Build plot data for this tumor type + normal tissues + CCLE
                cohort_order_plot = ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6',
                                    'TCGA_Adjacent', 'GTEx_Normal', f'CCLE_{tumor_type}']
                plot_data = []
                plot_labels = []
                plot_colors = []

                for cohort in cohort_order_plot:
                    if cohort.startswith('Cohort_'):
                        data = tumor_df[tumor_df['cohort'] == cohort]['expression'].dropna().values
                    elif cohort.startswith('CCLE_'):
                        # Get CCLE cell lines for this tumor type
                        ccle_tt = f'CCLE_{tumor_type}'
                        data = plot_df[plot_df['tumor_type'] == ccle_tt]['expression'].dropna().values
                    else:
                        data = plot_df[plot_df['cohort'] == cohort]['expression'].dropna().values
                    if len(data) > 0:
                        plot_data.append(data)
                        if cohort.startswith('CCLE_'):
                            plot_labels.append(f'CCLE\n{tumor_type}')
                            plot_colors.append('#8B4513')  # Brown for CCLE
                        else:
                            plot_labels.append(COHORT_LABELS.get(cohort, cohort))
                            plot_colors.append(COHORT_COLORS.get(cohort, '#666666'))

                if plot_data:
                    bp = ax.boxplot(plot_data, positions=range(len(plot_data)), widths=0.6,
                                   patch_artist=True, showfliers=True,
                                   flierprops={'marker': 'o', 'markersize': 3, 'alpha': 0.4})

                    for patch, color in zip(bp['boxes'], plot_colors):
                        patch.set_facecolor(color)
                        patch.set_alpha(0.7)
                        patch.set_edgecolor('black')

                    for median in bp['medians']:
                        median.set_color('black')
                        median.set_linewidth(2)

                    ax.set_xticks(range(len(plot_data)))
                    ax.set_xticklabels(plot_labels, fontsize=9)
                    ax.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=12)
                    ax.set_title(f'{gene_symbol} Expression: {tumor_label} Cohorts vs Normal + Cell Lines',
                                fontsize=14, fontweight='bold', color=tumor_color)
                    ax.yaxis.grid(True, linestyle='--', alpha=0.3)

                    # Divider line between tumor cohorts and normal/CCLE
                    tumor_end = len([c for c in cohort_order_plot[:5] if c in tt_data['cohort_stats']]) - 0.5
                    if tumor_end > 0:
                        ax.axvline(x=tumor_end, color='gray', linestyle='--', linewidth=1, alpha=0.5)

                plt.tight_layout()
                pdf.savefig(fig, bbox_inches='tight')
                plt.close()

            # Page: Tumor Type CMS Analysis
            if tt_data['cms_stats']:
                fig, ax = plt.subplots(figsize=(11, 8.5))

                cms_order = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
                cms_order = [c for c in cms_order if c in tt_data['cms_stats']]

                if cms_order:
                    cms_data = [tumor_df[tumor_df['CMS'] == c]['expression'].dropna().values for c in cms_order]
                    cms_palette = [CMS_COLORS[c] for c in cms_order]

                    bp = ax.boxplot(cms_data, positions=range(len(cms_order)), widths=0.6,
                                   patch_artist=True, showfliers=True,
                                   flierprops={'marker': 'o', 'markersize': 4, 'alpha': 0.5})

                    for patch, color in zip(bp['boxes'], cms_palette):
                        patch.set_facecolor(color)
                        patch.set_alpha(0.7)
                        patch.set_edgecolor('black')

                    for median in bp['medians']:
                        median.set_color('black')
                        median.set_linewidth(2)

                    cms_labels = {'CMS1': 'CMS1\nMSI Immune', 'CMS2': 'CMS2\nCanonical',
                                  'CMS3': 'CMS3\nMetabolic', 'CMS4': 'CMS4\nMesenchymal'}
                    ax.set_xticks(range(len(cms_order)))
                    ax.set_xticklabels([cms_labels[c] for c in cms_order], fontsize=10)
                    ax.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=12)
                    ax.set_title(f'{gene_symbol} Expression by CMS Subtype: {tumor_label}',
                                fontsize=14, fontweight='bold', color=tumor_color)
                    ax.yaxis.grid(True, linestyle='--', alpha=0.3)

                    # Add GTEx reference line
                    if 'GTEx_Normal' in plot_df['cohort'].unique():
                        gtex_median = plot_df[plot_df['cohort'] == 'GTEx_Normal']['expression'].median()
                        ax.axhline(y=gtex_median, color='#1ABC9C', linestyle='--', alpha=0.7,
                                   label=f'GTEx Normal: {gtex_median:.2f}')
                        ax.legend(loc='upper right')

                    # Add sample counts
                    for i, cms in enumerate(cms_order):
                        n = tt_data['cms_stats'][cms]['n']
                        ax.text(i, ax.get_ylim()[0] - 0.3, f'n={n}', ha='center', va='top', fontsize=9)

                plt.tight_layout()
                pdf.savefig(fig, bbox_inches='tight')
                plt.close()

            # Page: Tumor Type Statistical Comparisons
            if len(tt_data['pairwise_df']) > 0:
                fig = plt.figure(figsize=(11, 8.5))
                ax = fig.add_subplot(111)
                ax.axis('off')

                ax.text(0.5, 0.95, f'Statistical Comparisons: {tumor_label} vs Normal',
                        fontsize=16, fontweight='bold', ha='center', va='top', transform=ax.transAxes,
                        color=tumor_color)

                table_data = []
                for _, row in tt_data['pairwise_df'].iterrows():
                    sig = "Yes" if row['significant'] else "No"
                    table_data.append([
                        row['Tumor_Cohort'].replace('Cohort_', ''),
                        row['Normal_Group'].replace('_', ' '),
                        f"{row['Log2FC']:.2f}",
                        f"{row['p_value']:.2e}",
                        f"{row['p_adjusted']:.2e}",
                        sig
                    ])

                table = ax.table(cellText=table_data,
                                colLabels=['Tumor', 'vs Normal', 'Log2FC', 'p-value', 'FDR', 'Sig'],
                                loc='center', cellLoc='center',
                                bbox=[0.05, 0.25, 0.9, 0.6])
                table.auto_set_font_size(False)
                table.set_fontsize(10)
                for i in range(6):
                    table[(0, i)].set_facecolor(tumor_color)
                    table[(0, i)].set_text_props(fontweight='bold', color='white')

                plt.tight_layout()
                pdf.savefig(fig, bbox_inches='tight')
                plt.close()

    print(f"  Saved: {gene_symbol}_target_evaluation_report.pdf")
    return pdf_path


# =============================================================================
# MAIN ANALYSIS
# =============================================================================

def analyze_gene(gene_symbol, cache_dir, cohort_path, cms_path, adj_normal_path, output_dir,
                 gene_annotation, tcga_meta, gtex_meta, ccle_meta, cohort_df, cms_df):
    """Run complete analysis for a gene."""

    print("=" * 70)
    print(f"CRC Gene Expression Analysis: {gene_symbol}")
    print("=" * 70)

    # Create gene-specific output directory
    gene_output_dir = os.path.join(output_dir, gene_symbol)
    os.makedirs(gene_output_dir, exist_ok=True)

    # Find gene
    print(f"\n1. Finding gene: {gene_symbol}")
    gene_index, gene_id, gene_name = find_gene_index(gene_symbol, gene_annotation)
    if gene_index is None:
        print(f"  ERROR: Gene {gene_symbol} not found in annotation")
        return None
    print(f"  Found: {gene_name} ({gene_id}), gene_index={gene_index}")

    # Load expression data for this gene
    print("\n2. Loading expression data...")
    tcga_expr = load_expression_for_gene(cache_dir, 'tcga', gene_index)
    gtex_expr = load_expression_for_gene(cache_dir, 'gtex', gene_index)
    ccle_expr = load_expression_for_gene(cache_dir, 'ccle', gene_index)

    # Load adjacent normal samples if file exists
    adj_normal_samples = []
    if adj_normal_path and os.path.exists(adj_normal_path):
        adj_normal_samples = load_adjacent_normal_samples(adj_normal_path)

    # Build master dataframe
    print("\n3. Building master dataframe...")
    master_df = build_master_dataframe(
        tcga_expr, gtex_expr, ccle_expr, tcga_meta, gtex_meta, ccle_meta,
        cohort_df, cms_df, adj_normal_samples
    )

    print(f"  Primary Tumor samples: {len(master_df[master_df['tissue_type'] == 'Primary_Tumor'])}")
    print(f"  TCGA Adjacent Normal: {len(master_df[master_df['tissue_type'] == 'TCGA_Adjacent'])}")
    print(f"  GTEx Normal Colon: {len(master_df[master_df['tissue_type'] == 'GTEx_Normal'])}")
    print(f"  CRC Cell Lines (CCLE): {len(master_df[master_df['tissue_type'] == 'CCLE_CRC'])}")

    # Expand for plotting
    plot_df = expand_for_plotting(master_df)
    print(f"  Total plot rows: {len(plot_df)}")

    # Statistics
    print("\n4. Calculating statistics...")
    stats_summary = calculate_statistics(plot_df)
    kw_stat, kw_pval = perform_kruskal_wallis(plot_df)
    pairwise_df = perform_pairwise_comparisons(plot_df)
    cms_stats, cms_kw_stat, cms_kw_pval, cms_pairwise_df = perform_cms_statistics(plot_df)

    if kw_pval is not None:
        print(f"  Kruskal-Wallis: H = {kw_stat:.3f}, p = {kw_pval:.2e}")

    # Visualizations
    print("\n5. Generating visualizations...")
    plot_cohort_boxplot(plot_df, gene_symbol, gene_output_dir)
    plot_cohort_violin(plot_df, gene_symbol, gene_output_dir)
    plot_cms_boxplot(plot_df, gene_symbol, gene_output_dir)
    tumor_type_stats = plot_tumor_type_boxplot(plot_df, gene_symbol, gene_output_dir)
    tumor_type_by_cohort = plot_tumor_type_by_cohort(plot_df, gene_symbol, gene_output_dir)
    plot_comprehensive(plot_df, master_df, gene_symbol, gene_output_dir, stats_summary)

    # Analyze by tumor type (COAD and READ separately)
    print("\n5b. Analyzing COAD and READ separately...")
    tumor_type_analysis = analyze_by_tumor_type(plot_df, gene_symbol, gene_output_dir)

    # Export data
    print("\n6. Exporting results...")
    stats_summary.to_csv(f'{gene_output_dir}/{gene_symbol}_cohort_statistics.csv')
    print(f"  Saved: {gene_symbol}_cohort_statistics.csv")

    if len(pairwise_df) > 0:
        pairwise_df.to_csv(f'{gene_output_dir}/{gene_symbol}_pairwise_comparisons.csv', index=False)
        print(f"  Saved: {gene_symbol}_pairwise_comparisons.csv")

    # Save CMS pairwise comparisons
    if cms_pairwise_df is not None and len(cms_pairwise_df) > 0:
        cms_pairwise_df.to_csv(f'{gene_output_dir}/{gene_symbol}_cms_pairwise_comparisons.csv', index=False)
        print(f"  Saved: {gene_symbol}_cms_pairwise_comparisons.csv")

    # Save COAD vs READ statistics
    if tumor_type_by_cohort is not None and len(tumor_type_by_cohort) > 0:
        tumor_type_by_cohort.to_csv(f'{gene_output_dir}/{gene_symbol}_COAD_READ_statistics.csv', index=False)
        print(f"  Saved: {gene_symbol}_COAD_READ_statistics.csv")

    export_df = master_df[['expr_sample_id', 'expression', 'tissue_type', 'CMS',
                           'msi_status', 'ras_status', 'stage_group', 'tumor_type']].copy()
    export_df.to_csv(f'{gene_output_dir}/{gene_symbol}_expression_data.csv', index=False)
    print(f"  Saved: {gene_symbol}_expression_data.csv")

    # Generate reports
    print("\n7. Generating target evaluation reports...")
    report_path = generate_target_report(
        gene_symbol, gene_id, master_df, plot_df, stats_summary,
        pairwise_df, cms_stats, kw_stat, kw_pval, cms_kw_stat, cms_kw_pval,
        cms_pairwise_df, gene_output_dir
    )
    pdf_report_path = generate_pdf_report(
        gene_symbol, gene_id, master_df, plot_df, stats_summary,
        pairwise_df, cms_stats, kw_stat, kw_pval, cms_kw_stat, cms_kw_pval,
        cms_pairwise_df, tumor_type_stats, tumor_type_by_cohort, tumor_type_analysis, gene_output_dir
    )

    # Final summary
    print("\n" + "=" * 70)
    print(f"{gene_symbol} ANALYSIS COMPLETE")
    print("=" * 70)

    print(f"\nKey Statistics:")
    print(f"  {'Cohort':<20} {'N':>6} {'Median':>8} {'Mean':>8}")
    print(f"  {'-'*44}")
    for cohort in ['Cohort_2A', 'Cohort_2B', 'Cohort_4', 'Cohort_5', 'Cohort_6', 'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']:
        if cohort in stats_summary.index:
            row = stats_summary.loc[cohort]
            print(f"  {cohort:<20} {int(row['count']):>6} {row['median']:>8.3f} {row['mean']:>8.3f}")

    if len(pairwise_df) > 0 and 'significant' in pairwise_df.columns:
        sig_results = pairwise_df[pairwise_df['significant']]
        if len(sig_results) > 0:
            print(f"\nSignificant comparisons (FDR < 0.05):")
            for _, row in sig_results.iterrows():
                direction = "↑" if row['Log2FC'] > 0 else "↓"
                print(f"  {row['Tumor_Cohort']} vs {row['Normal_Group']}: {direction} (log2FC={row['Log2FC']:.2f})")

    print(f"\nOutput directory: {gene_output_dir}")
    print(f"Report (MD): {report_path}")
    print(f"Report (PDF): {pdf_report_path}")

    return {
        'gene_symbol': gene_symbol,
        'gene_id': gene_id,
        'master_df': master_df,
        'stats_summary': stats_summary,
        'pairwise_df': pairwise_df,
        'report_path': report_path,
        'pdf_report_path': pdf_report_path
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='CRC Gene Expression Analysis with Cohort Comparisons',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    python crc_gene_analysis.py --genes CDK4
    python crc_gene_analysis.py --genes CDK4 CDK6 CCND1
    python crc_gene_analysis.py --gene-file genes.txt
    python crc_gene_analysis.py --genes CDK4 --output-dir ./my_results
        '''
    )

    parser.add_argument('--genes', nargs='+', help='Gene symbol(s) to analyze')
    parser.add_argument('--gene-file', help='File with gene symbols (one per line)')
    parser.add_argument('--output-dir', '-o', default=DEFAULT_OUTPUT_DIR, help='Output directory')
    parser.add_argument('--cache-dir', default=DEFAULT_CACHE_DIR, help='Data cache directory')
    parser.add_argument('--cohort-path', default=DEFAULT_COHORT_PATH, help='Path to cohort assignments CSV')
    parser.add_argument('--cms-path', default=DEFAULT_CMS_PATH, help='Path to CMS predictions CSV')
    parser.add_argument('--adj-normal-path', default=DEFAULT_ADJ_NORMAL_PATH, help='Path to adjacent normal samples TSV')

    args = parser.parse_args()

    # Parse genes
    genes = []
    if args.genes:
        genes.extend(args.genes)
    if args.gene_file:
        with open(args.gene_file, 'r') as f:
            genes.extend([line.strip() for line in f if line.strip()])

    if not genes:
        parser.error('No genes specified. Use --genes or --gene-file')

    # Remove duplicates while preserving order
    genes = list(dict.fromkeys(genes))

    print("=" * 70)
    print("CRC Gene Expression Analysis with Cohort Comparisons")
    print("=" * 70)
    print(f"Genes to analyze: {', '.join(genes)}")
    print(f"Output directory: {args.output_dir}")
    print(f"Cache directory: {args.cache_dir}")
    print(f"Cohort file: {args.cohort_path}")
    print(f"CMS file: {args.cms_path}")

    # Create directories
    os.makedirs(args.cache_dir, exist_ok=True)
    os.makedirs(args.output_dir, exist_ok=True)

    # Load annotation and metadata
    print("\n1. Loading annotation and metadata from S3...")
    gene_annotation = load_gene_annotation(args.cache_dir)
    tcga_meta = load_tcga_metadata(args.cache_dir)
    gtex_meta = load_gtex_metadata(args.cache_dir)
    ccle_meta = load_ccle_metadata(args.cache_dir)

    # Load cohort and CMS data
    cohort_df = None
    if os.path.exists(args.cohort_path):
        cohort_df = load_cohort_assignments(args.cohort_path)
    else:
        print(f"  Warning: Cohort file not found: {args.cohort_path}")

    cms_df = None
    if os.path.exists(args.cms_path):
        cms_df = load_cms_predictions(args.cms_path)
    else:
        print(f"  Warning: CMS file not found: {args.cms_path}")

    # Analyze each gene
    print("\n2. Analyzing genes...")
    results = []
    for gene in genes:
        result = analyze_gene(
            gene,
            args.cache_dir,
            args.cohort_path,
            args.cms_path,
            args.adj_normal_path,
            args.output_dir,
            gene_annotation,
            tcga_meta,
            gtex_meta,
            ccle_meta,
            cohort_df,
            cms_df
        )
        if result:
            results.append(result)

    # Final summary
    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)
    print(f"\nSuccessfully analyzed: {len(results)}/{len(genes)} genes")
    print(f"Results saved to: {args.output_dir}")

    if len(results) > 0:
        print("\nOutput files for each gene:")
        for r in results:
            print(f"  {r['gene_symbol']}/")
            print(f"    - {r['gene_symbol']}_cohort_boxplot.png/pdf")
            print(f"    - {r['gene_symbol']}_cohort_violin.png")
            print(f"    - {r['gene_symbol']}_CMS_boxplot.png")
            print(f"    - {r['gene_symbol']}_COAD_READ_boxplot.png")
            print(f"    - {r['gene_symbol']}_comprehensive_analysis.png/pdf")
            print(f"    - {r['gene_symbol']}_cohort_statistics.csv")
            print(f"    - {r['gene_symbol']}_pairwise_comparisons.csv")
            print(f"    - {r['gene_symbol']}_target_evaluation_report.md")
            print(f"    - {r['gene_symbol']}_target_evaluation_report.pdf")

    return results


if __name__ == '__main__':
    main()
