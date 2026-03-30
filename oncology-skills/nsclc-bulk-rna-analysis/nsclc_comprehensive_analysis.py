#!/usr/bin/env python3
"""
NSCLC Comprehensive Gene Expression Analysis - TCGA + Tempus Unified

Complete target evaluation pipeline combining:
- TCGA raw expression: Tumor vs Normal comparisons (on-target toxicity)
- GTEx: Healthy tissue baseline
- CCLE: Cell line expression for in vitro validation
- Tempus RWD: Line-of-therapy and mutation stratification (iDAS alignment)

This is the recommended script for comprehensive NSCLC target evaluation.

Cohort Naming (unified with iDAS alignment):
    TCGA Cohorts:
        TCGA_LUAD         - Lung Adenocarcinoma
        TCGA_LUSC         - Lung Squamous Cell Carcinoma
        TCGA_Adjacent     - Adjacent normal (on-target toxicity reference)
        GTEx_Lung         - Normal lung (healthy baseline)
        CCLE_NSCLC        - NSCLC cell lines

    Tempus Cohorts (iDAS-aligned):
        Tempus_2L_NonAGA      - 2L Non-AGA (n=518) - iDAS Priority
        Tempus_2L_EGFR        - 2L EGFR Mutant (n=38) - iDAS Priority
        Tempus_1L2L_KRAS      - 1L-2L KRAS Mutant (n=1,021) - iDAS Priority
        Tempus_KRAS_Mut       - All KRAS Mutant (n=1,133)
        Tempus_EGFR_Mut       - All EGFR Mutant (n=121)
        Tempus_STK11_Mut      - STK11 Mutant (n=551) - IO resistance marker
        Tempus_KEAP1_Mut      - KEAP1 Mutant (n=346) - IO resistance marker

Usage:
    python nsclc_comprehensive_analysis.py --genes TNFRSF12A EGFR MET
    python nsclc_comprehensive_analysis.py --genes MET --output-dir ./results
    python nsclc_comprehensive_analysis.py --genes MET --skip-tcga  # Tempus only
    python nsclc_comprehensive_analysis.py --genes MET --skip-tempus  # TCGA only

Data Sources:
    TCGA/GTEx/CCLE: s3://onc-compbio/omicsoft_oncoland_data
    Tempus: Local files from /Users/eta3879/Documents/Projects/ODDU/Tempus/TAK_LACE_Q12026_NSCLC_cohort_1/summary/
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
import yaml

warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================

AWS_PROFILE = 'cbg'

# S3 Buckets
TCGA_S3_BUCKET = 's3://onc-compbio/omicsoft_oncoland_data'

# Local Tempus data path
TEMPUS_LOCAL_PATH = '/Users/eta3879/Documents/Projects/ODDU/Tempus/TAK_LACE_Q12026_NSCLC_cohort_1/summary'

# Default directories
DEFAULT_CACHE_DIR = './data_cache'
DEFAULT_OUTPUT_DIR = './nsclc_comprehensive_results'

# Tempus summary files
TEMPUS_FILES = {
    'overall': 'gene_summary_overall.csv',
    'aga_status': 'gene_summary_by_AGA_status.csv',
    'egfr_status': 'gene_summary_by_EGFR_status.csv',
    'kras_status': 'gene_summary_by_KRAS_status.csv',
    'stk11_status': 'gene_summary_by_STK11_status.csv',
    'keap1_status': 'gene_summary_by_KEAP1_status.csv',
    'lot': 'gene_summary_by_LOT.csv',
    'cpi_status': 'gene_summary_by_CPI_status.csv',
    'metastatic': 'gene_summary_by_metastatic_status.csv',
    'idas_2l_nonaga': 'gene_summary_iDAS_2L_NonAGA.csv',
    'idas_2l_egfr': 'gene_summary_iDAS_2L_EGFR.csv',
    'idas_1l2l_kras': 'gene_summary_iDAS_1L2L_KRAS.csv',
    'cpi_nonaga': 'gene_summary_CPI_treated_NonAGA.csv',
    'key_targets_long': 'NSCLC_key_targets_summary_long.csv',
    'key_targets_wide': 'NSCLC_key_targets_summary_wide.csv',
    'sample_sizes': 'SAMPLE_SIZE_SUMMARY.csv',
}

# =============================================================================
# COHORT DEFINITIONS
# =============================================================================

# TCGA cohorts to analyze
TCGA_COHORTS = ['TCGA_LUAD', 'TCGA_LUSC']

# iDAS Priority cohorts for NSCLC
IDAS_PRIORITY_COHORTS = {
    'Tempus_2L_NonAGA': '2L Non-AGA',
    'Tempus_2L_EGFR': '2L EGFR Mutant (post-TKI)',
    'Tempus_1L2L_KRAS': '1L/2L KRAS Mutant',
}

# TCGA mutation columns (from TCGA metadata)
TCGA_MUTATION_COLUMNS = {
    'KRAS': 'dna_seq_somatic_mutation_status_kras',
    'EGFR': 'dna_seq_somatic_mutation_status_egfr',
    'STK11': 'dna_seq_somatic_mutation_status_stk11',
    'KEAP1': 'dna_seq_somatic_mutation_status_keap1',
}

# Color schemes
COHORT_COLORS = {
    # TCGA tumor cohorts
    'TCGA_LUAD': '#E74C3C',
    'TCGA_LUSC': '#3498DB',
    'TCGA_NSCLC': '#9B59B6',
    'TCGA_Adjacent': '#7F8C8D',
    'GTEx_Lung': '#1ABC9C',
    'CCLE_NSCLC': '#8B4513',
    # TCGA mutation status
    'TCGA_KRAS_Mut': '#E67E22',
    'TCGA_KRAS_WT': '#F5B041',
    'TCGA_EGFR_Mut': '#16A085',
    'TCGA_EGFR_WT': '#48C9B0',
    'TCGA_STK11_Mut': '#8E44AD',
    'TCGA_STK11_WT': '#BB8FCE',
    'TCGA_KEAP1_Mut': '#D35400',
    'TCGA_KEAP1_WT': '#EB984E',
    # Tempus cohorts
    'Tempus_2L_NonAGA': '#C0392B',
    'Tempus_2L_EGFR': '#27AE60',
    'Tempus_1L2L_KRAS': '#2874A6',
    'Tempus_KRAS_Mut': '#E67E22',
    'Tempus_EGFR_Mut': '#16A085',
    'Tempus_STK11_Mut': '#8E44AD',
    'Tempus_KEAP1_Mut': '#D35400',
    'Tempus_1L': '#5DADE2',
    'Tempus_2L': '#2980B9',
    'Tempus_3Lplus': '#1B4F72',
}

COHORT_LABELS = {
    # TCGA
    'TCGA_LUAD': 'LUAD\n(TCGA)',
    'TCGA_LUSC': 'LUSC\n(TCGA)',
    'TCGA_NSCLC': 'NSCLC\n(TCGA)',
    'TCGA_Adjacent': 'Adjacent\nNormal',
    'GTEx_Lung': 'Normal\nLung\n(GTEx)',
    'CCLE_NSCLC': 'Cell Lines\n(CCLE)',
    # Tempus
    'Tempus_2L_NonAGA': '2L Non-AGA\n(Tempus)',
    'Tempus_2L_EGFR': '2L EGFR-mut\n(post-TKI)',
    'Tempus_1L2L_KRAS': '1L-2L KRAS\n(Tempus)',
    'Tempus_KRAS_Mut': 'KRAS-mut\n(Tempus)',
    'Tempus_EGFR_Mut': 'EGFR-mut\n(Tempus)',
    'Tempus_1L': '1L\n(Tempus)',
    'Tempus_2L': '2L\n(Tempus)',
    'Tempus_3Lplus': '3L+\n(Tempus)',
}

# Plot settings
plt.rcParams['figure.figsize'] = (16, 10)
plt.rcParams['figure.dpi'] = 150
plt.rcParams['font.size'] = 10
sns.set_style('whitegrid')


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def truncate_tcga_id(sample_id, length=15):
    """Truncate TCGA sample ID to standard length."""
    if isinstance(sample_id, str) and sample_id.startswith('TCGA'):
        return sample_id[:length]
    return sample_id


# =============================================================================
# S3 DATA LOADING
# =============================================================================

def download_s3_file(s3_path, local_path, quiet=False):
    """Download file from S3 if not already cached."""
    if os.path.exists(local_path):
        if not quiet:
            print(f"  Using cached: {os.path.basename(local_path)}")
        return local_path

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    if not quiet:
        print(f"  Downloading: {os.path.basename(s3_path)}")

    aws_cmd = "/usr/local/bin/aws" if os.path.exists("/usr/local/bin/aws") else "aws"
    cmd = f"{aws_cmd} s3 cp {s3_path} {local_path} --profile {AWS_PROFILE} --no-verify-ssl"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to download {s3_path}: {result.stderr}")

    return local_path


# =============================================================================
# TCGA DATA LOADING
# =============================================================================

def load_gene_annotation(cache_dir):
    """Load gene annotation for gene symbol to ID mapping."""
    s3_path = f"{TCGA_S3_BUCKET}/tcga_b38_gc33/raw/gene_annotation.tsv.gz"
    local_path = f"{cache_dir}/gene_annotation.tsv.gz"
    download_s3_file(s3_path, local_path)
    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    return df


def load_tcga_metadata(cache_dir):
    """Load TCGA sample metadata."""
    s3_path = f"{TCGA_S3_BUCKET}/tcga_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/tcga_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)
    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    return df


def load_gtex_metadata(cache_dir):
    """Load GTEx sample metadata."""
    s3_path = f"{TCGA_S3_BUCKET}/gtex_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/gtex_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)
    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    return df


def load_ccle_metadata(cache_dir):
    """Load CCLE sample metadata."""
    s3_path = f"{TCGA_S3_BUCKET}/ccle_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/ccle_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)
    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    return df


def load_expression_for_gene(cache_dir, dataset, gene_index):
    """Load expression data for a specific gene from Omicsoft format."""
    dataset_paths = {
        'tcga': f"{TCGA_S3_BUCKET}/tcga_b38_gc33/raw/rna_seq_gene_expression.tsv.gz",
        'ccle': f"{TCGA_S3_BUCKET}/ccle_b38_gc33/raw/rna_seq_gene_expression.tsv.gz",
        'gtex': f"{TCGA_S3_BUCKET}/gtex_b38_gc33/raw/rna_seq_gene_expression.tsv.gz"
    }

    s3_path = dataset_paths[dataset]
    local_path = f"{cache_dir}/{dataset}_expression.tsv.gz"
    download_s3_file(s3_path, local_path, quiet=True)

    results = []
    chunksize = 2000000

    for chunk in pd.read_csv(local_path, sep='\t', compression='gzip', chunksize=chunksize):
        filtered = chunk[chunk['gene_index'] == gene_index]
        if len(filtered) > 0:
            results.append(filtered)

    if results:
        return pd.concat(results, ignore_index=True)
    return pd.DataFrame()


# =============================================================================
# TEMPUS DATA LOADING
# =============================================================================

def load_tempus_file(file_key):
    """Load a Tempus summary file from local path."""
    filename = TEMPUS_FILES.get(file_key)
    if not filename:
        return None

    local_path = os.path.join(TEMPUS_LOCAL_PATH, filename)

    if not os.path.exists(local_path):
        print(f"  Warning: Tempus file not found: {local_path}")
        return None

    try:
        return pd.read_csv(local_path)
    except Exception as e:
        print(f"  Warning: Could not load Tempus {file_key}: {e}")
        return None


def load_all_tempus_data():
    """Load all Tempus summary files."""
    print("\nLoading Tempus data...")
    tempus_data = {}
    for key in TEMPUS_FILES:
        df = load_tempus_file(key)
        if df is not None:
            tempus_data[key] = df
            print(f"  Loaded {key}: {len(df)} rows")
    return tempus_data


def get_tempus_gene_data(gene_symbol, tempus_data):
    """Extract Tempus data for a specific gene."""
    results = {}

    for key, df in tempus_data.items():
        if 'gene_symbol' in df.columns:
            gene_df = df[df['gene_symbol'] == gene_symbol]
            if not gene_df.empty:
                results[key] = gene_df

    return results


# =============================================================================
# NSCLC SAMPLE FILTERING
# =============================================================================

def get_tcga_nsclc_samples(metadata):
    """Get TCGA LUAD/LUSC samples."""
    if 'project_ids' in metadata.columns:
        mask = metadata['project_ids'].str.contains('TCGA_LUAD|TCGA_LUSC', na=False, case=False)
    elif 'project_id' in metadata.columns:
        mask = metadata['project_id'].str.contains('TCGA_LUAD|TCGA_LUSC', na=False, case=False)
    else:
        return pd.DataFrame()
    return metadata[mask]


def get_tcga_luad_samples(metadata):
    """Get TCGA LUAD samples."""
    if 'project_ids' in metadata.columns:
        mask = metadata['project_ids'].str.contains('TCGA_LUAD', na=False, case=False)
    elif 'project_id' in metadata.columns:
        mask = metadata['project_id'].str.contains('TCGA_LUAD', na=False, case=False)
    else:
        return pd.DataFrame()
    return metadata[mask]


def get_tcga_lusc_samples(metadata):
    """Get TCGA LUSC samples."""
    if 'project_ids' in metadata.columns:
        mask = metadata['project_ids'].str.contains('TCGA_LUSC', na=False, case=False)
    elif 'project_id' in metadata.columns:
        mask = metadata['project_id'].str.contains('TCGA_LUSC', na=False, case=False)
    else:
        return pd.DataFrame()
    return metadata[mask]


def get_tcga_nsclc_tumor_samples(metadata):
    """Get TCGA NSCLC primary tumor samples."""
    nsclc = get_tcga_nsclc_samples(metadata)
    if 'tumor_or_normal' in nsclc.columns:
        return nsclc[nsclc['tumor_or_normal'].str.contains('Tumor', case=False, na=False)]
    return nsclc


def get_gtex_lung_samples(metadata):
    """Get GTEx lung samples."""
    if 'tissue_gtex' in metadata.columns:
        return metadata[metadata['tissue_gtex'].str.lower().str.contains('lung', na=False)]
    elif 'tissue' in metadata.columns:
        return metadata[metadata['tissue'].str.lower().str.contains('lung', na=False)]
    return pd.DataFrame()


def get_ccle_nsclc_samples(metadata):
    """Get CCLE NSCLC cell lines."""
    if 'onco_tree_disease' in metadata.columns:
        mask = metadata['onco_tree_disease'].str.contains('lung|nsclc|luad|lusc', case=False, na=False)
        return metadata[mask]
    return pd.DataFrame()


# =============================================================================
# MASTER DATAFRAME BUILDING (TCGA)
# =============================================================================

def build_tcga_master_dataframe(tcga_expr, gtex_expr, ccle_expr, tcga_meta, gtex_meta, ccle_meta):
    """Build master dataframe with all TCGA/GTEx/CCLE samples for NSCLC."""
    all_data = []

    # Create sample_index to sample_id mappings
    tcga_sample_map = dict(zip(tcga_meta['sample_index'], tcga_meta['sample_id']))
    gtex_sample_map = dict(zip(gtex_meta['sample_index'], gtex_meta['sample_id']))
    ccle_sample_map = dict(zip(ccle_meta['sample_index'], ccle_meta['sample_id']))

    # Create sample_index to mutation status mappings from TCGA metadata
    tcga_mutation_maps = {}
    for gene, col in TCGA_MUTATION_COLUMNS.items():
        if col in tcga_meta.columns:
            mutation_map = {}
            for _, row in tcga_meta.iterrows():
                status = row.get(col, '')
                if status == 'MUT':
                    mutation_map[row['sample_index']] = 'Mutant'
                elif status == 'WT':
                    mutation_map[row['sample_index']] = 'WT'
                else:
                    mutation_map[row['sample_index']] = 'Unknown'
            tcga_mutation_maps[gene] = mutation_map

    # Get NSCLC sample sets from metadata
    nsclc_meta = get_tcga_nsclc_samples(tcga_meta)
    luad_meta = get_tcga_luad_samples(tcga_meta)
    lusc_meta = get_tcga_lusc_samples(tcga_meta)

    luad_indices = set(luad_meta['sample_index'].tolist())
    lusc_indices = set(lusc_meta['sample_index'].tolist())
    nsclc_indices = luad_indices | lusc_indices

    # Identify tumor vs adjacent normal in TCGA
    tumor_meta = get_tcga_nsclc_tumor_samples(tcga_meta)
    tumor_indices = set(tumor_meta['sample_index'].tolist())

    # Adjacent normal sample indices (samples ending in -11)
    adj_normal_indices = set()
    for _, row in nsclc_meta.iterrows():
        sample_id = row['sample_id']
        if any(adj in sample_id for adj in ['-11', '-11A', '-11B']):
            adj_normal_indices.add(row['sample_index'])

    # Process TCGA expression
    for _, row in tcga_expr.iterrows():
        sample_idx = row['sample_index']
        if sample_idx not in nsclc_indices and sample_idx not in adj_normal_indices:
            continue

        sample_id = tcga_sample_map.get(sample_idx, f"TCGA_{sample_idx}")
        tpm = row['tpm']
        log2_tpm = np.log2(tpm + 1)

        # Determine cohort
        if sample_idx in adj_normal_indices:
            cohort = 'TCGA_Adjacent'
        elif sample_idx in luad_indices:
            cohort = 'TCGA_LUAD'
        elif sample_idx in lusc_indices:
            cohort = 'TCGA_LUSC'
        else:
            cohort = 'TCGA_NSCLC'

        sample_record = {
            'sample_id': sample_id,
            'cohort': cohort,
            'expression': log2_tpm,
            'source': 'TCGA',
            'is_tumor': sample_idx in tumor_indices,
            'is_adjacent_normal': sample_idx in adj_normal_indices,
        }
        # Add mutation status columns
        for gene in TCGA_MUTATION_COLUMNS.keys():
            if gene in tcga_mutation_maps:
                sample_record[f'{gene}_status'] = tcga_mutation_maps[gene].get(sample_idx, 'Unknown')
        all_data.append(sample_record)

    # Process GTEx lung expression
    gtex_lung_meta = get_gtex_lung_samples(gtex_meta)
    gtex_lung_indices = set(gtex_lung_meta['sample_index'].tolist())

    for _, row in gtex_expr.iterrows():
        sample_idx = row['sample_index']
        if sample_idx not in gtex_lung_indices:
            continue

        sample_id = gtex_sample_map.get(sample_idx, f"GTEx_{sample_idx}")
        tpm = row['tpm']
        log2_tpm = np.log2(tpm + 1)

        all_data.append({
            'sample_id': sample_id,
            'cohort': 'GTEx_Lung',
            'expression': log2_tpm,
            'source': 'GTEx',
            'is_tumor': False,
            'is_adjacent_normal': False,
        })

    # Process CCLE NSCLC expression
    ccle_nsclc_meta = get_ccle_nsclc_samples(ccle_meta)
    ccle_nsclc_indices = set(ccle_nsclc_meta['sample_index'].tolist())

    for _, row in ccle_expr.iterrows():
        sample_idx = row['sample_index']
        if sample_idx not in ccle_nsclc_indices:
            continue

        sample_id = ccle_sample_map.get(sample_idx, f"CCLE_{sample_idx}")
        tpm = row['tpm']
        log2_tpm = np.log2(tpm + 1)

        all_data.append({
            'sample_id': sample_id,
            'cohort': 'CCLE_NSCLC',
            'expression': log2_tpm,
            'source': 'CCLE',
            'is_tumor': True,
            'is_adjacent_normal': False,
        })

    return pd.DataFrame(all_data)


# =============================================================================
# STATISTICAL ANALYSIS
# =============================================================================

def perform_pairwise_comparisons(df, tumor_cohorts, normal_cohorts):
    """Perform statistical comparisons between tumor and normal cohorts."""
    results = []

    for tumor in tumor_cohorts:
        tumor_data = df[df['cohort'] == tumor]['expression']
        if len(tumor_data) == 0:
            continue

        for normal in normal_cohorts:
            normal_data = df[df['cohort'] == normal]['expression']
            if len(normal_data) == 0:
                continue

            # Mann-Whitney U test
            stat, pval = mannwhitneyu(tumor_data, normal_data, alternative='two-sided')

            # Calculate fold change
            log2fc = tumor_data.median() - normal_data.median()

            results.append({
                'Tumor_Cohort': tumor,
                'Normal_Group': normal,
                'Tumor_N': len(tumor_data),
                'Normal_N': len(normal_data),
                'Tumor_Median': tumor_data.median(),
                'Normal_Median': normal_data.median(),
                'Log2FC': log2fc,
                'p_value': pval,
            })

    if not results:
        return pd.DataFrame()

    results_df = pd.DataFrame(results)

    # FDR correction
    if len(results_df) > 0:
        _, pvals_adj, _, _ = multipletests(results_df['p_value'], method='fdr_bh')
        results_df['p_adjusted'] = pvals_adj
        results_df['significant'] = results_df['p_adjusted'] < 0.05

    return results_df


def compute_tcga_mutation_statistics(df):
    """
    Compute TCGA mutation expression statistics by mutation status.

    Returns a dictionary with statistics for each mutation gene (KRAS, EGFR, STK11, KEAP1).
    Only uses TCGA tumor samples (treatment-naive) for valid within-dataset comparison.
    """
    mutation_stats = {}

    # Filter to TCGA tumor samples only
    tcga_tumor = df[(df['source'] == 'TCGA') & (df['is_tumor'] == True)]

    for gene in TCGA_MUTATION_COLUMNS.keys():
        status_col = f'{gene}_status'
        if status_col not in tcga_tumor.columns:
            continue

        gene_stats = []
        for status in ['Mutant', 'WT']:
            subset = tcga_tumor[tcga_tumor[status_col] == status]
            if len(subset) > 0:
                gene_stats.append({
                    'Gene': gene,
                    'Status': status,
                    'N': len(subset),
                    'Mean': subset['expression'].mean(),
                    'Median': subset['expression'].median(),
                    'SD': subset['expression'].std(),
                })

        if gene_stats:
            gene_df = pd.DataFrame(gene_stats)
            # Calculate log2FC (Mutant vs WT)
            mut_mean = gene_df[gene_df['Status'] == 'Mutant']['Mean'].values
            wt_mean = gene_df[gene_df['Status'] == 'WT']['Mean'].values
            if len(mut_mean) > 0 and len(wt_mean) > 0:
                gene_df['log2FC_vs_WT'] = gene_df['Mean'] - wt_mean[0]
            mutation_stats[gene] = gene_df

    return mutation_stats


def calculate_cohort_statistics(df):
    """Calculate descriptive statistics by cohort."""
    stats_list = []

    for cohort in df['cohort'].unique():
        cohort_data = df[df['cohort'] == cohort]['expression']

        stats_list.append({
            'cohort': cohort,
            'count': len(cohort_data),
            'mean': cohort_data.mean(),
            'median': cohort_data.median(),
            'std': cohort_data.std(),
            'min': cohort_data.min(),
            'max': cohort_data.max(),
            'q25': cohort_data.quantile(0.25),
            'q75': cohort_data.quantile(0.75),
        })

    return pd.DataFrame(stats_list)


# =============================================================================
# iDAS ALIGNMENT ASSESSMENT
# =============================================================================

def assess_idas_alignment(tcga_stats, tempus_gene_data, pairwise_df):
    """Assess alignment with iDAS NSCLC priority whitespaces."""
    assessment = {
        'whitespace_alignment': {},
        'on_target_toxicity': {},
        'overall_alignment': None,
        'recommendation': None,
    }

    # 1. On-target toxicity (tumor vs adjacent normal)
    if pairwise_df is not None and len(pairwise_df) > 0:
        adj_comparisons = pairwise_df[pairwise_df['Normal_Group'] == 'TCGA_Adjacent']
        if len(adj_comparisons) > 0:
            avg_fc = adj_comparisons['Log2FC'].mean()
            assessment['on_target_toxicity'] = {
                'tumor_vs_adjacent_log2FC': avg_fc,
                'risk_level': 'Low' if avg_fc > 1.5 else 'Medium' if avg_fc > 0.5 else 'High'
            }

    # 2. iDAS Priority Whitespace Alignment
    # Check Tempus iDAS cohorts
    idas_cohorts = {
        '2L_NonAGA': ('idas_2l_nonaga', '2L Non-AGA'),
        '2L_EGFR': ('idas_2l_egfr', '2L EGFR Mutant (post-TKI)'),
        '1L2L_KRAS': ('idas_1l2l_kras', '1L/2L KRAS Mutant'),
    }

    for key, (file_key, label) in idas_cohorts.items():
        if file_key in tempus_gene_data:
            data = tempus_gene_data[file_key]
            if len(data) > 0:
                mean_expr = data['mean'].values[0] if 'mean' in data.columns else None
                n_samples = data['n_samples'].values[0] if 'n_samples' in data.columns else None

                if mean_expr is not None:
                    alignment = 'Strong' if mean_expr > 4 else 'Moderate' if mean_expr > 2 else 'Weak'
                    assessment['whitespace_alignment'][key] = {
                        'expression': mean_expr,
                        'n_samples': n_samples,
                        'alignment': alignment,
                        'label': label,
                    }

    # 3. Overall assessment
    alignments = [v.get('alignment', 'Weak') for v in assessment['whitespace_alignment'].values()]
    toxicity_risk = assessment['on_target_toxicity'].get('risk_level', 'Unknown')

    strong_count = sum(1 for a in alignments if a == 'Strong')
    moderate_count = sum(1 for a in alignments if a == 'Moderate')

    if toxicity_risk == 'High':
        assessment['overall_alignment'] = 'Low'
        assessment['recommendation'] = 'CONDITIONAL - High on-target toxicity risk'
    elif strong_count >= 2 and toxicity_risk in ['Low', 'Medium']:
        assessment['overall_alignment'] = 'High'
        assessment['recommendation'] = 'PRIORITY - Strong iDAS alignment'
    elif strong_count >= 1 or moderate_count >= 2:
        assessment['overall_alignment'] = 'Moderate'
        assessment['recommendation'] = 'CONSIDER - Moderate iDAS alignment'
    else:
        assessment['overall_alignment'] = 'Low'
        assessment['recommendation'] = 'LOW PRIORITY - Limited iDAS alignment'

    return assessment


def compute_subgroup_suitability(gene, tcga_stats, pairwise_df, tcga_mutation_stats, idas_assessment, tempus_gene_data):
    """
    Compute subgroup-specific suitability scores for target evaluation.

    3-Phase Analysis (consistent with CRC):
    - Phase 1: TCGA Analysis (treatment-naive) - Histology + Mutation status
    - Phase 2: Tempus Mutation Status (IO-experienced) - KRAS, EGFR, STK11, KEAP1
    - Phase 3: iDAS Whitespace Alignment (uses Tempus mutation data)

    Returns:
        dict: Subgroup suitability analysis with scores and recommendations
    """
    suitability = {
        'gene': gene,
        'tcga_analysis': {},      # Phase 1: All TCGA data
        'tempus_mutation': {},    # Phase 2: Tempus mutation status
        'idas_whitespace': {},    # Phase 3: iDAS whitespaces
        'summary': []
    }

    # ==========================================================================
    # PHASE 1: TCGA ANALYSIS (Treatment-Naive)
    # ==========================================================================
    # Includes both histology tumor enrichment AND mutation status from TCGA

    # 1a. Histology suitability (LUAD vs LUSC tumor enrichment)
    if pairwise_df is not None and len(pairwise_df) > 0:
        for histology in ['TCGA_LUAD', 'TCGA_LUSC']:
            hist_comparison = pairwise_df[
                (pairwise_df['Tumor_Cohort'] == histology) &
                (pairwise_df['Normal_Group'] == 'TCGA_Adjacent')
            ]
            if len(hist_comparison) > 0:
                log2fc = hist_comparison['Log2FC'].values[0]
                linear_fc = 2 ** log2fc

                # Suitability scoring based on tumor enrichment
                if log2fc > 1.0:  # >2x vs adjacent
                    score = 5
                    recommendation = 'GO'
                    rationale = f'Strong tumor enrichment ({linear_fc:.1f}x vs adjacent)'
                elif log2fc > 0.58:  # >1.5x vs adjacent
                    score = 4
                    recommendation = 'GO'
                    rationale = f'Good tumor enrichment ({linear_fc:.1f}x vs adjacent)'
                elif log2fc > 0:  # >1x vs adjacent
                    score = 3
                    recommendation = 'CONDITIONAL'
                    rationale = f'Moderate tumor enrichment ({linear_fc:.1f}x vs adjacent)'
                else:
                    score = 2
                    recommendation = 'CAUTION'
                    rationale = f'No tumor enrichment ({linear_fc:.1f}x vs adjacent)'

                hist_label = 'LUAD' if 'LUAD' in histology else 'LUSC'
                suitability['tcga_analysis'][f'Histology_{hist_label}'] = {
                    'log2fc_vs_adjacent': round(log2fc, 3),
                    'linear_fc': round(linear_fc, 2),
                    'data_source': 'TCGA',
                    'suitability_score': score,
                    'recommendation': recommendation,
                    'rationale': rationale
                }

                suitability['summary'].append({
                    'subgroup': f'TCGA Histology: {hist_label}',
                    'category': 'tcga_analysis',
                    'key_metric': f'{linear_fc:.1f}x vs adjacent (TCGA)',
                    'score': score,
                    'recommendation': recommendation
                })

    # 1b. TCGA Mutation status (treatment-naive)
    if tcga_mutation_stats:
        for mutation_gene, mut_df in tcga_mutation_stats.items():
            mutant_row = mut_df[mut_df['Status'] == 'Mutant']
            wt_row = mut_df[mut_df['Status'] == 'WT']

            if len(mutant_row) > 0 and len(wt_row) > 0:
                log2fc_vs_wt = mutant_row['log2FC_vs_WT'].values[0]
                fold_change = 2 ** log2fc_vs_wt  # Convert to fold change
                mutant_mean = mutant_row['Mean'].values[0]
                mutant_n = int(mutant_row['N'].values[0])
                wt_mean = wt_row['Mean'].values[0]
                wt_n = int(wt_row['N'].values[0])

                # Interpret mutation status effect
                if log2fc_vs_wt > 0.5:
                    score = 5
                    recommendation = 'PRIORITY'
                    rationale = f'Upregulated in {mutation_gene}-mutant ({fold_change:.1f}x vs WT)'
                elif log2fc_vs_wt > 0:
                    score = 4
                    recommendation = 'GO'
                    rationale = f'Slightly higher in {mutation_gene}-mutant ({fold_change:.1f}x vs WT)'
                elif log2fc_vs_wt > -0.5:
                    score = 3
                    recommendation = 'NEUTRAL'
                    rationale = f'Similar expression regardless of {mutation_gene} status ({fold_change:.1f}x vs WT)'
                elif log2fc_vs_wt > -1.0:
                    score = 2
                    recommendation = 'CAUTION'
                    rationale = f'Lower in {mutation_gene}-mutant ({fold_change:.1f}x vs WT)'
                else:
                    score = 1
                    recommendation = 'EXCLUDE'
                    rationale = f'Significantly lower in {mutation_gene}-mutant ({fold_change:.1f}x vs WT)'

                suitability['tcga_analysis'][f'Mutation_{mutation_gene}'] = {
                    'log2fc_vs_wt': round(log2fc_vs_wt, 3),
                    'fold_change': round(fold_change, 2),
                    'mutant_mean': round(mutant_mean, 3),
                    'mutant_n': mutant_n,
                    'wt_mean': round(wt_mean, 3),
                    'wt_n': wt_n,
                    'data_source': 'TCGA',
                    'suitability_score': score,
                    'recommendation': recommendation,
                    'rationale': rationale
                }

                suitability['summary'].append({
                    'subgroup': f'TCGA Mutation: {mutation_gene}+',
                    'category': 'tcga_analysis',
                    'key_metric': f'{fold_change:.1f}x vs WT (TCGA)',
                    'score': score,
                    'recommendation': recommendation
                })

    # ==========================================================================
    # PHASE 2: TEMPUS MUTATION STATUS (IO-Experienced)
    # ==========================================================================
    # Compare mutation status in Tempus (post-treatment) population
    tempus_mutation_files = {
        'KRAS': ('kras_status', 'KRAS Mutant', 'KRAS WT'),
        'EGFR': ('egfr_status', 'EGFR Mutant', 'EGFR WT'),
        'STK11': ('stk11_status', 'STK11 Mutant', 'STK11 WT'),
        'KEAP1': ('keap1_status', 'KEAP1 Mutant', 'KEAP1 WT'),
    }

    tempus_mutation_log2fc = {}  # Store for Phase 3 iDAS whitespace scoring

    for mutation_gene, (tempus_key, mut_group, wt_group) in tempus_mutation_files.items():
        if tempus_key in tempus_gene_data:
            mut_data = tempus_gene_data[tempus_key]
            if 'group_name' in mut_data.columns and 'mean' in mut_data.columns:
                mut_row = mut_data[mut_data['group_name'] == mut_group]
                wt_row = mut_data[mut_data['group_name'] == wt_group]

                if len(mut_row) > 0 and len(wt_row) > 0:
                    mut_mean = mut_row['mean'].values[0]
                    wt_mean = wt_row['mean'].values[0]
                    mut_n = int(mut_row['n_samples'].values[0]) if 'n_samples' in mut_row.columns else 0
                    wt_n = int(wt_row['n_samples'].values[0]) if 'n_samples' in wt_row.columns else 0
                    log2fc_vs_wt = mut_mean - wt_mean  # Already log2-transformed
                    fold_change = 2 ** log2fc_vs_wt  # Convert to fold change

                    # Store for Phase 3
                    tempus_mutation_log2fc[mutation_gene] = log2fc_vs_wt

                    # Interpret mutation status effect
                    if log2fc_vs_wt > 0.5:
                        score = 5
                        recommendation = 'PRIORITY'
                        rationale = f'Upregulated in {mutation_gene}-mutant ({fold_change:.1f}x vs WT, Tempus)'
                    elif log2fc_vs_wt > 0:
                        score = 4
                        recommendation = 'GO'
                        rationale = f'Slightly higher in {mutation_gene}-mutant ({fold_change:.1f}x vs WT, Tempus)'
                    elif log2fc_vs_wt > -0.5:
                        score = 3
                        recommendation = 'NEUTRAL'
                        rationale = f'Similar expression regardless of {mutation_gene} status ({fold_change:.1f}x vs WT, Tempus)'
                    elif log2fc_vs_wt > -1.0:
                        score = 2
                        recommendation = 'CAUTION'
                        rationale = f'Lower in {mutation_gene}-mutant ({fold_change:.1f}x vs WT, Tempus)'
                    else:
                        score = 1
                        recommendation = 'EXCLUDE'
                        rationale = f'Significantly lower in {mutation_gene}-mutant ({fold_change:.1f}x vs WT, Tempus)'

                    suitability['tempus_mutation'][f'{mutation_gene}_mut'] = {
                        'log2fc_vs_wt': round(log2fc_vs_wt, 3),
                        'fold_change': round(fold_change, 2),
                        'mutant_mean': round(mut_mean, 3),
                        'mutant_n': mut_n,
                        'wt_mean': round(wt_mean, 3),
                        'wt_n': wt_n,
                        'data_source': 'Tempus',
                        'suitability_score': score,
                        'recommendation': recommendation,
                        'rationale': rationale
                    }

                    suitability['summary'].append({
                        'subgroup': f'Tempus Mutation: {mutation_gene}+',
                        'category': 'tempus_mutation',
                        'key_metric': f'{fold_change:.1f}x vs WT (Tempus)',
                        'score': score,
                        'recommendation': recommendation
                    })

    # ==========================================================================
    # PHASE 3: iDAS WHITESPACE SUITABILITY
    # ==========================================================================
    # Based on expression level + mutation status (from Phase 2 Tempus data) + toxicity risk
    whitespace_info = idas_assessment.get('whitespace_alignment', {})
    toxicity = idas_assessment.get('on_target_toxicity', {})
    tox_risk = toxicity.get('risk_level', 'Unknown')
    tox_log2fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)

    # Map iDAS whitespaces to their corresponding mutation genes (uses Phase 2 tempus_mutation_log2fc)
    whitespace_mutation_map = {
        '2L_EGFR': 'EGFR',       # Uses EGFR mutation log2FC from Phase 2
        '1L2L_KRAS': 'KRAS',     # Uses KRAS mutation log2FC from Phase 2
        '2L_NonAGA': None,       # Non-AGA has no specific mutation association
    }

    for ws_key, ws_data in whitespace_info.items():
        expression = ws_data.get('expression', 0)
        alignment = ws_data.get('alignment', 'Unknown')
        n_samples = ws_data.get('n_samples', 0)
        label = ws_data.get('label', ws_key)

        # Base score on expression level
        if expression > 5:
            base_score = 5
        elif expression > 4:
            base_score = 4
        elif expression > 3:
            base_score = 3
        elif expression > 2:
            base_score = 2
        else:
            base_score = 1

        # Get corresponding mutation status log2FC from Phase 2 Tempus data (if applicable)
        mutation_gene = whitespace_mutation_map.get(ws_key)
        mutation_log2fc = tempus_mutation_log2fc.get(mutation_gene) if mutation_gene else None
        mutation_penalty = 0
        mutation_context = ''

        mutation_fc = None
        if mutation_log2fc is not None:
            mutation_fc = 2 ** mutation_log2fc  # Convert to fold change
            # Apply penalty if target is lower in the mutant population (Tempus data)
            if mutation_log2fc < -0.5:
                mutation_penalty = 2  # Significant penalty for substantially lower expression
                mutation_context = f', MUT_LOWER ({mutation_fc:.1f}x vs WT, Tempus)'
            elif mutation_log2fc < 0:
                mutation_penalty = 1  # Moderate penalty for slightly lower expression
                mutation_context = f', mut_lower ({mutation_fc:.1f}x vs WT, Tempus)'
            elif mutation_log2fc > 0.5:
                mutation_penalty = -1  # Bonus for higher expression in mutant
                mutation_context = f', mut_higher ({mutation_fc:.1f}x vs WT, Tempus)'

        # Adjust for toxicity risk
        if tox_risk == 'High':
            tox_penalty = 2
        elif tox_risk == 'Medium':
            tox_penalty = 1
        else:
            tox_penalty = 0

        # Calculate final adjusted score
        adjusted_score = max(1, base_score - tox_penalty - mutation_penalty)

        # Determine recommendation based on adjusted score and context
        if mutation_penalty >= 2:
            recommendation = 'CAUTION'
            rationale = f'Expression={expression:.2f}, but target LOWER in mutant population{mutation_context}'
        elif adjusted_score >= 4 and tox_risk != 'High':
            if mutation_penalty == 0 and tox_penalty == 0:
                recommendation = 'PRIORITY'
            else:
                recommendation = 'GO'
            rationale = f'Expression={expression:.2f}, {tox_risk} toxicity{mutation_context}'
        elif adjusted_score >= 3:
            recommendation = 'CONDITIONAL'
            rationale = f'Expression={expression:.2f}, {tox_risk} toxicity{mutation_context}'
        else:
            recommendation = 'CAUTION'
            rationale = f'Expression={expression:.2f}, concerns: tox={tox_risk}{mutation_context}'

        suitability['idas_whitespace'][ws_key] = {
            'expression': round(expression, 3),
            'n_samples': int(n_samples) if n_samples else 0,
            'alignment': alignment,
            'toxicity_risk': tox_risk,
            'mutation_log2fc': round(mutation_log2fc, 3) if mutation_log2fc is not None else None,
            'mutation_fold_change': round(mutation_fc, 2) if mutation_fc is not None else None,
            'mutation_data_source': 'Tempus' if mutation_log2fc is not None else None,
            'base_score': base_score,
            'tox_penalty': tox_penalty,
            'mutation_penalty': mutation_penalty,
            'adjusted_score': adjusted_score,
            'recommendation': recommendation,
            'rationale': rationale
        }

        # Build key metric string
        key_metric = f'expr={expression:.2f}'
        if mutation_fc is not None:
            key_metric += f', {mutation_fc:.1f}x vs WT (Tempus)'
        key_metric += f', tox={tox_risk}'

        suitability['summary'].append({
            'subgroup': f'iDAS: {label}',
            'category': 'idas_whitespace',
            'key_metric': key_metric,
            'score': adjusted_score,
            'recommendation': recommendation
        })

    # ==========================================================================
    # 4. OVERALL BEST SUBGROUPS
    # ==========================================================================
    # Sort summary by score to identify best subgroups
    suitability['summary'] = sorted(suitability['summary'], key=lambda x: -x['score'])

    # Identify top recommendations
    priority_subgroups = [s for s in suitability['summary'] if s['recommendation'] == 'PRIORITY']
    go_subgroups = [s for s in suitability['summary'] if s['recommendation'] == 'GO']
    exclude_subgroups = [s for s in suitability['summary'] if s['recommendation'] in ['EXCLUDE', 'CAUTION']]

    suitability['top_recommendations'] = {
        'priority': [s['subgroup'] for s in priority_subgroups],
        'go': [s['subgroup'] for s in go_subgroups],
        'exclude': [s['subgroup'] for s in exclude_subgroups]
    }

    return suitability


# =============================================================================
# VISUALIZATION
# =============================================================================

def create_comprehensive_figure(gene, tcga_df, tempus_gene_data, idas_assessment, output_dir):
    """Create comprehensive 8-panel visualization figure."""
    fig = plt.figure(figsize=(20, 16))

    # Panel 1: TCGA Cohort Expression + Mutation Status
    ax1 = fig.add_subplot(2, 4, 1)

    # Build combined data: histology cohorts + mutation status
    plot_data_list = []
    plot_order = []
    plot_colors = []

    # Histology cohorts
    histology_order = ['TCGA_LUAD', 'TCGA_LUSC', 'TCGA_Adjacent', 'GTEx_Lung']
    histology_data = tcga_df[tcga_df['cohort'].isin(histology_order)].copy()
    if len(histology_data) > 0:
        for cohort in histology_order:
            n = len(histology_data[histology_data['cohort'] == cohort])
            if n > 0:
                histology_data.loc[histology_data['cohort'] == cohort, 'plot_group'] = cohort
                plot_order.append(cohort)
                plot_colors.append(COHORT_COLORS.get(cohort, '#333333'))
        plot_data_list.append(histology_data[['expression', 'plot_group']])

    # TCGA Mutation Status (tumor samples only)
    tcga_tumor = tcga_df[(tcga_df['source'] == 'TCGA') & (tcga_df['is_tumor'] == True)].copy()
    for mutation_gene in ['KRAS', 'EGFR', 'STK11', 'KEAP1']:
        status_col = f'{mutation_gene}_status'
        if status_col in tcga_tumor.columns:
            for status in ['Mutant', 'WT']:
                subset = tcga_tumor[tcga_tumor[status_col] == status].copy()
                if len(subset) > 0:
                    label = f'{mutation_gene}_{status[:3]}'
                    subset['plot_group'] = label
                    plot_data_list.append(subset[['expression', 'plot_group']])
                    plot_order.append(label)
                    color_key = f'TCGA_{mutation_gene}_{"Mut" if status == "Mutant" else "WT"}'
                    plot_colors.append(COHORT_COLORS.get(color_key, '#333333'))

    if plot_data_list:
        combined_df = pd.concat(plot_data_list, ignore_index=True)
        sns.boxplot(data=combined_df, x='plot_group', y='expression',
                    order=plot_order, palette=plot_colors, ax=ax1, linewidth=0.5)
        ax1.set_xticklabels(plot_order, rotation=90, ha='center', fontsize=6)
        ax1.axvline(x=len(histology_order) - 0.5, color='gray', linestyle='--', alpha=0.5, linewidth=0.5)

    ax1.set_ylabel('Expression (log2 TPM+1)')
    ax1.set_xlabel('')
    ax1.set_title(f'{gene} - TCGA Cohorts & Mutations', fontweight='bold', fontsize=10)

    # Panel 2: On-Target Toxicity (Tumor vs Adjacent Normal)
    ax2 = fig.add_subplot(2, 4, 2)
    tox_data = tcga_df[tcga_df['cohort'].isin(['TCGA_LUAD', 'TCGA_LUSC', 'TCGA_Adjacent'])]
    if len(tox_data) > 0:
        tox_data = tox_data.copy()
        tox_data['tissue_type'] = tox_data['cohort'].apply(
            lambda x: 'Tumor' if x in ['TCGA_LUAD', 'TCGA_LUSC'] else 'Adjacent Normal'
        )
        sns.boxplot(data=tox_data, x='tissue_type', y='expression',
                    palette={'Tumor': '#E74C3C', 'Adjacent Normal': '#7F8C8D'}, ax=ax2)

        # Add fold change annotation
        toxicity = idas_assessment.get('on_target_toxicity', {})
        fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)
        risk = toxicity.get('risk_level', 'Unknown')
        ax2.text(0.5, 0.95, f'log2FC: {fc:.2f}\nRisk: {risk}',
                transform=ax2.transAxes, ha='center', va='top', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    ax2.set_ylabel('Expression (log2 TPM+1)')
    ax2.set_xlabel('')
    ax2.set_title('On-Target Toxicity Assessment', fontweight='bold')

    # Panel 3: Tempus Line of Therapy
    ax3 = fig.add_subplot(2, 4, 3)
    if 'lot' in tempus_gene_data:
        lot_data = tempus_gene_data['lot']
        if 'group_name' in lot_data.columns:
            lot_order = ['1L', '2L', '3L+']
            lot_plot = lot_data[lot_data['group_name'].isin(lot_order)].copy()
            if len(lot_plot) > 0:
                lot_plot['group_name'] = pd.Categorical(lot_plot['group_name'], categories=lot_order, ordered=True)
                lot_plot = lot_plot.sort_values('group_name')
                colors = [COHORT_COLORS.get(f'Tempus_{g.replace("+", "plus")}', '#333333') for g in lot_plot['group_name']]
                ax3.bar(lot_plot['group_name'], lot_plot['mean'], color=colors, edgecolor='black')
                ax3.errorbar(lot_plot['group_name'], lot_plot['mean'], yerr=lot_plot['sd']/2, fmt='none', color='black', capsize=3)
    ax3.set_ylabel('Expression (log2 TPM+1)')
    ax3.set_xlabel('Line of Therapy')
    ax3.set_title('Tempus: Line of Therapy', fontweight='bold')

    # Panel 4: iDAS Priority Cohorts
    ax4 = fig.add_subplot(2, 4, 4)
    idas_data = []
    for key, info in idas_assessment.get('whitespace_alignment', {}).items():
        idas_data.append({
            'cohort': info.get('label', key),
            'expression': info.get('expression', 0),
            'alignment': info.get('alignment', 'Unknown')
        })
    if idas_data:
        idas_df = pd.DataFrame(idas_data)
        colors = ['#27AE60' if a == 'Strong' else '#F39C12' if a == 'Moderate' else '#E74C3C'
                  for a in idas_df['alignment']]
        ax4.barh(idas_df['cohort'], idas_df['expression'], color=colors, edgecolor='black')
        ax4.axvline(x=4, color='green', linestyle='--', alpha=0.5, label='Strong threshold')
        ax4.axvline(x=2, color='orange', linestyle='--', alpha=0.5, label='Moderate threshold')
    ax4.set_xlabel('Expression (log2 TPM+1)')
    ax4.set_title('iDAS Priority Whitespaces', fontweight='bold')

    # Panel 5: KRAS Status
    ax5 = fig.add_subplot(2, 4, 5)
    if 'kras_status' in tempus_gene_data:
        kras_data = tempus_gene_data['kras_status']
        if 'group_name' in kras_data.columns:
            kras_plot = kras_data[kras_data['group_name'].isin(['KRAS Mutant', 'KRAS WT'])]
            if len(kras_plot) > 0:
                colors = ['#E67E22', '#3498DB']
                ax5.bar(kras_plot['group_name'], kras_plot['mean'], color=colors, edgecolor='black')
                ax5.errorbar(kras_plot['group_name'], kras_plot['mean'], yerr=kras_plot['sd']/2, fmt='none', color='black', capsize=3)
    ax5.set_ylabel('Expression (log2 TPM+1)')
    ax5.set_title('KRAS Mutation Status', fontweight='bold')

    # Panel 6: EGFR Status
    ax6 = fig.add_subplot(2, 4, 6)
    if 'egfr_status' in tempus_gene_data:
        egfr_data = tempus_gene_data['egfr_status']
        if 'group_name' in egfr_data.columns:
            egfr_plot = egfr_data[egfr_data['group_name'].isin(['EGFR Mutant', 'EGFR WT'])]
            if len(egfr_plot) > 0:
                colors = ['#16A085', '#9B59B6']
                ax6.bar(egfr_plot['group_name'], egfr_plot['mean'], color=colors, edgecolor='black')
                ax6.errorbar(egfr_plot['group_name'], egfr_plot['mean'], yerr=egfr_plot['sd']/2, fmt='none', color='black', capsize=3)
    ax6.set_ylabel('Expression (log2 TPM+1)')
    ax6.set_title('EGFR Mutation Status', fontweight='bold')

    # Panel 7: STK11/KEAP1 Status (IO resistance markers)
    ax7 = fig.add_subplot(2, 4, 7)
    io_data = []
    if 'stk11_status' in tempus_gene_data:
        stk11 = tempus_gene_data['stk11_status']
        for _, row in stk11.iterrows():
            if 'group_name' in row:
                io_data.append({'marker': row['group_name'], 'mean': row['mean'], 'sd': row.get('sd', 0)})
    if 'keap1_status' in tempus_gene_data:
        keap1 = tempus_gene_data['keap1_status']
        for _, row in keap1.iterrows():
            if 'group_name' in row:
                io_data.append({'marker': row['group_name'], 'mean': row['mean'], 'sd': row.get('sd', 0)})
    if io_data:
        io_df = pd.DataFrame(io_data)
        colors = ['#8E44AD' if 'STK11' in m else '#D35400' for m in io_df['marker']]
        ax7.bar(range(len(io_df)), io_df['mean'], color=colors, edgecolor='black')
        ax7.set_xticks(range(len(io_df)))
        ax7.set_xticklabels(io_df['marker'], rotation=45, ha='right', fontsize=8)
    ax7.set_ylabel('Expression (log2 TPM+1)')
    ax7.set_title('IO Resistance Markers (STK11/KEAP1)', fontweight='bold')

    # Panel 8: Overall Assessment Summary
    ax8 = fig.add_subplot(2, 4, 8)
    ax8.axis('off')

    # Create summary text
    overall = idas_assessment.get('overall_alignment', 'Unknown')
    rec = idas_assessment.get('recommendation', 'Unknown')
    toxicity = idas_assessment.get('on_target_toxicity', {})
    tox_risk = toxicity.get('risk_level', 'Unknown')
    tox_fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)

    # Color based on recommendation
    if 'PRIORITY' in rec:
        bg_color = '#D5F5E3'
        text_color = '#1E8449'
    elif 'CONDITIONAL' in rec:
        bg_color = '#FADBD8'
        text_color = '#922B21'
    else:
        bg_color = '#FEF9E7'
        text_color = '#9A7D0A'

    summary_text = f"""
    {gene} Target Assessment Summary
    ════════════════════════════════════

    Overall iDAS Alignment: {overall}

    On-Target Toxicity Risk: {tox_risk}
    (Tumor vs Normal log2FC: {tox_fc:.2f})

    Recommendation:
    {rec}
    """

    ax8.text(0.5, 0.5, summary_text, transform=ax8.transAxes, ha='center', va='center',
             fontsize=12, family='monospace',
             bbox=dict(boxstyle='round,pad=0.5', facecolor=bg_color, edgecolor=text_color, linewidth=2))

    plt.suptitle(f'{gene} Comprehensive NSCLC Target Analysis', fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()

    # Save figure
    output_path = os.path.join(output_dir, f'{gene}_comprehensive_analysis.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

    print(f"  Saved: {output_path}")

    # Save individual high-resolution figures
    save_individual_figures_nsclc(gene, tcga_df, tempus_gene_data, idas_assessment, output_dir)

    return output_path


def save_individual_figures_nsclc(gene, tcga_df, tempus_gene_data, idas_assessment, output_dir):
    """Save each panel as a separate high-resolution PNG file."""
    figures_dir = os.path.join(output_dir, 'figures')
    os.makedirs(figures_dir, exist_ok=True)

    DPI = 300  # High resolution

    # Panel 1: TCGA Cohort Expression + Mutation Status (all in 1 row)
    fig, ax = plt.subplots(figsize=(16, 6))

    # Build combined data: histology cohorts + mutation status
    plot_data_list = []
    plot_order = []
    plot_colors = []

    # First: Histology cohorts
    histology_order = ['TCGA_LUAD', 'TCGA_LUSC', 'TCGA_Adjacent', 'GTEx_Lung', 'CCLE_NSCLC']
    histology_data = tcga_df[tcga_df['cohort'].isin(histology_order)].copy()
    if len(histology_data) > 0:
        # Add sample counts to labels
        for cohort in histology_order:
            n = len(histology_data[histology_data['cohort'] == cohort])
            if n > 0:
                label = f'{COHORT_LABELS.get(cohort, cohort)}\n(n={n})'
                histology_data.loc[histology_data['cohort'] == cohort, 'plot_group'] = label
                plot_order.append(label)
                plot_colors.append(COHORT_COLORS.get(cohort, '#333333'))
        plot_data_list.append(histology_data[['expression', 'plot_group']])

    # Second: TCGA Mutation Status (tumor samples only)
    tcga_tumor = tcga_df[(tcga_df['source'] == 'TCGA') & (tcga_df['is_tumor'] == True)].copy()
    for mutation_gene in ['KRAS', 'EGFR', 'STK11', 'KEAP1']:
        status_col = f'{mutation_gene}_status'
        if status_col in tcga_tumor.columns:
            for status in ['Mutant', 'WT']:
                subset = tcga_tumor[tcga_tumor[status_col] == status].copy()
                if len(subset) > 0:
                    label = f'{mutation_gene}\n{status}\n(n={len(subset)})'
                    subset['plot_group'] = label
                    plot_data_list.append(subset[['expression', 'plot_group']])
                    plot_order.append(label)
                    color_key = f'TCGA_{mutation_gene}_{"Mut" if status == "Mutant" else "WT"}'
                    plot_colors.append(COHORT_COLORS.get(color_key, '#333333'))

    if plot_data_list:
        combined_df = pd.concat(plot_data_list, ignore_index=True)
        sns.boxplot(data=combined_df, x='plot_group', y='expression',
                    order=plot_order, palette=plot_colors, ax=ax)
        ax.set_xticklabels(plot_order, rotation=45, ha='right', fontsize=9)

        # Add vertical line to separate histology from mutations
        ax.axvline(x=len(histology_order) - 0.5, color='gray', linestyle='--', alpha=0.5)

    ax.set_ylabel('Expression (log2 TPM+1)', fontsize=12)
    ax.set_xlabel('')
    ax.set_title(f'{gene} - TCGA Expression: Histology & Mutation Status (Treatment-Naive)', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, f'{gene}_panel_1_tcga_cohorts.png'), dpi=DPI, facecolor='white')
    plt.close()

    # Panel 2: On-Target Toxicity (Tumor vs Adjacent Normal)
    fig, ax = plt.subplots(figsize=(6, 5))
    tox_data = tcga_df[tcga_df['cohort'].isin(['TCGA_LUAD', 'TCGA_LUSC', 'TCGA_Adjacent'])]
    if len(tox_data) > 0:
        tox_data = tox_data.copy()
        tox_data['tissue_type'] = tox_data['cohort'].apply(
            lambda x: 'Tumor' if x in ['TCGA_LUAD', 'TCGA_LUSC'] else 'Adjacent Normal'
        )
        sns.boxplot(data=tox_data, x='tissue_type', y='expression',
                    palette={'Tumor': '#E74C3C', 'Adjacent Normal': '#7F8C8D'}, ax=ax)
        toxicity = idas_assessment.get('on_target_toxicity', {})
        fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)
        risk = toxicity.get('risk_level', 'Unknown')
        ax.text(0.5, 0.95, f'log2FC: {fc:.2f}\nRisk: {risk}',
                transform=ax.transAxes, ha='center', va='top', fontsize=11,
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    ax.set_ylabel('Expression (log2 TPM+1)', fontsize=12)
    ax.set_xlabel('')
    ax.set_title(f'{gene} - On-Target Toxicity Assessment', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, f'{gene}_panel_2_toxicity.png'), dpi=DPI, facecolor='white')
    plt.close()

    # Panel 3: Tempus Line of Therapy
    fig, ax = plt.subplots(figsize=(6, 5))
    if 'lot' in tempus_gene_data:
        lot_data = tempus_gene_data['lot']
        if 'group_name' in lot_data.columns:
            lot_order = ['1L', '2L', '3L+']
            lot_plot = lot_data[lot_data['group_name'].isin(lot_order)].copy()
            if len(lot_plot) > 0:
                lot_plot['group_name'] = pd.Categorical(lot_plot['group_name'], categories=lot_order, ordered=True)
                lot_plot = lot_plot.sort_values('group_name')
                colors = [COHORT_COLORS.get(f'Tempus_{g.replace("+", "plus")}', '#333333') for g in lot_plot['group_name']]
                ax.bar(lot_plot['group_name'], lot_plot['mean'], color=colors, edgecolor='black')
                ax.errorbar(lot_plot['group_name'], lot_plot['mean'], yerr=lot_plot['sd']/2, fmt='none', color='black', capsize=3)
    ax.set_ylabel('Expression (log2 TPM+1)', fontsize=12)
    ax.set_xlabel('Line of Therapy', fontsize=12)
    ax.set_title(f'{gene} - Line of Therapy (Tempus)', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, f'{gene}_panel_3_lot.png'), dpi=DPI, facecolor='white')
    plt.close()

    # Panel 4: iDAS Priority Cohorts
    fig, ax = plt.subplots(figsize=(8, 6))
    idas_data = []
    for key, info in idas_assessment.get('whitespace_alignment', {}).items():
        idas_data.append({
            'cohort': info.get('label', key),
            'expression': info.get('expression', 0),
            'alignment': info.get('alignment', 'Unknown')
        })
    if idas_data:
        idas_df = pd.DataFrame(idas_data)
        colors = ['#27AE60' if a == 'Strong' else '#F39C12' if a == 'Moderate' else '#E74C3C'
                  for a in idas_df['alignment']]
        ax.barh(idas_df['cohort'], idas_df['expression'], color=colors, edgecolor='black')
        ax.axvline(x=4, color='green', linestyle='--', alpha=0.5, label='Strong threshold')
        ax.axvline(x=2, color='orange', linestyle='--', alpha=0.5, label='Moderate threshold')
        ax.legend(loc='lower right', fontsize=9)
    ax.set_xlabel('Expression (log2 TPM+1)', fontsize=12)
    ax.set_title(f'{gene} - iDAS Priority Whitespaces', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, f'{gene}_panel_4_idas_priority.png'), dpi=DPI, facecolor='white')
    plt.close()

    # Panel 5: KRAS Status
    fig, ax = plt.subplots(figsize=(6, 5))
    if 'kras_status' in tempus_gene_data:
        kras_data = tempus_gene_data['kras_status']
        if 'group_name' in kras_data.columns:
            kras_plot = kras_data[kras_data['group_name'].isin(['KRAS Mutant', 'KRAS WT'])]
            if len(kras_plot) > 0:
                colors = ['#E67E22', '#3498DB']
                ax.bar(kras_plot['group_name'], kras_plot['mean'], color=colors, edgecolor='black')
                ax.errorbar(kras_plot['group_name'], kras_plot['mean'], yerr=kras_plot['sd']/2, fmt='none', color='black', capsize=3)
    ax.set_ylabel('Expression (log2 TPM+1)', fontsize=12)
    ax.set_title(f'{gene} - KRAS Mutation Status (Tempus)', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, f'{gene}_panel_5_kras_status.png'), dpi=DPI, facecolor='white')
    plt.close()

    # Panel 6: EGFR Status
    fig, ax = plt.subplots(figsize=(6, 5))
    if 'egfr_status' in tempus_gene_data:
        egfr_data = tempus_gene_data['egfr_status']
        if 'group_name' in egfr_data.columns:
            egfr_plot = egfr_data[egfr_data['group_name'].isin(['EGFR Mutant', 'EGFR WT'])]
            if len(egfr_plot) > 0:
                colors = ['#16A085', '#9B59B6']
                ax.bar(egfr_plot['group_name'], egfr_plot['mean'], color=colors, edgecolor='black')
                ax.errorbar(egfr_plot['group_name'], egfr_plot['mean'], yerr=egfr_plot['sd']/2, fmt='none', color='black', capsize=3)
    ax.set_ylabel('Expression (log2 TPM+1)', fontsize=12)
    ax.set_title(f'{gene} - EGFR Mutation Status (Tempus)', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, f'{gene}_panel_6_egfr_status.png'), dpi=DPI, facecolor='white')
    plt.close()

    # Panel 7: STK11/KEAP1 Status (IO resistance markers)
    fig, ax = plt.subplots(figsize=(8, 6))
    io_data = []
    if 'stk11_status' in tempus_gene_data:
        stk11 = tempus_gene_data['stk11_status']
        for _, row in stk11.iterrows():
            if 'group_name' in row:
                io_data.append({'marker': row['group_name'], 'mean': row['mean'], 'sd': row.get('sd', 0)})
    if 'keap1_status' in tempus_gene_data:
        keap1 = tempus_gene_data['keap1_status']
        for _, row in keap1.iterrows():
            if 'group_name' in row:
                io_data.append({'marker': row['group_name'], 'mean': row['mean'], 'sd': row.get('sd', 0)})
    if io_data:
        io_df = pd.DataFrame(io_data)
        colors = ['#8E44AD' if 'STK11' in m else '#D35400' for m in io_df['marker']]
        ax.bar(range(len(io_df)), io_df['mean'], color=colors, edgecolor='black')
        ax.set_xticks(range(len(io_df)))
        ax.set_xticklabels(io_df['marker'], rotation=45, ha='right', fontsize=10)
    ax.set_ylabel('Expression (log2 TPM+1)', fontsize=12)
    ax.set_title(f'{gene} - IO Resistance Markers (STK11/KEAP1)', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, f'{gene}_panel_7_io_resistance.png'), dpi=DPI, facecolor='white')
    plt.close()

    # Panel 8: Overall Assessment Summary
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.axis('off')
    overall = idas_assessment.get('overall_alignment', 'Unknown')
    rec = idas_assessment.get('recommendation', 'Unknown')
    toxicity = idas_assessment.get('on_target_toxicity', {})
    tox_risk = toxicity.get('risk_level', 'Unknown')
    tox_fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)
    if 'PRIORITY' in rec:
        bg_color = '#D5F5E3'
        text_color = '#1E8449'
    elif 'CONDITIONAL' in rec:
        bg_color = '#FADBD8'
        text_color = '#922B21'
    else:
        bg_color = '#FEF9E7'
        text_color = '#9A7D0A'
    summary_text = f"""
    {gene} Target Assessment Summary
    ════════════════════════════════════

    Overall iDAS Alignment: {overall}

    On-Target Toxicity Risk: {tox_risk}
    (Tumor vs Normal log2FC: {tox_fc:.2f})

    Recommendation:
    {rec}
    """
    ax.text(0.5, 0.5, summary_text, transform=ax.transAxes, ha='center', va='center',
             fontsize=13, family='monospace',
             bbox=dict(boxstyle='round,pad=0.5', facecolor=bg_color, edgecolor=text_color, linewidth=2))
    ax.set_title(f'{gene} - Assessment Summary', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, f'{gene}_panel_8_summary.png'), dpi=DPI, facecolor='white')
    plt.close()

    print(f"  Saved individual figures to: {figures_dir}/")


def save_subgroup_suitability_figure(gene, subgroup_suitability, output_dir):
    """Create and save subgroup suitability heatmap visualization."""
    figures_dir = os.path.join(output_dir, 'figures')
    os.makedirs(figures_dir, exist_ok=True)

    summary = subgroup_suitability.get('summary', [])
    if not summary:
        return

    # Create figure
    fig, ax = plt.subplots(figsize=(12, max(6, len(summary) * 0.5)))

    # Prepare data for visualization
    subgroups = [s['subgroup'] for s in summary]
    scores = [s['score'] for s in summary]
    recommendations = [s['recommendation'] for s in summary]
    metrics = [s['key_metric'] for s in summary]

    # Color mapping by recommendation
    color_map = {
        'PRIORITY': '#27AE60',  # Green
        'GO': '#58D68D',        # Light green
        'CONDITIONAL': '#F39C12',  # Orange
        'NEUTRAL': '#BDC3C7',   # Gray
        'CAUTION': '#E67E22',   # Dark orange
        'EXCLUDE': '#E74C3C'    # Red
    }
    colors = [color_map.get(r, '#BDC3C7') for r in recommendations]

    # Create horizontal bar chart
    y_pos = range(len(subgroups))
    bars = ax.barh(y_pos, scores, color=colors, edgecolor='black', height=0.7)

    # Add labels
    ax.set_yticks(y_pos)
    ax.set_yticklabels(subgroups, fontsize=10)
    ax.set_xlabel('Suitability Score', fontsize=12)
    ax.set_xlim(0, 5.5)

    # Add score values and recommendations on bars
    for i, (bar, score, rec, metric) in enumerate(zip(bars, scores, recommendations, metrics)):
        width = bar.get_width()
        ax.text(width + 0.1, bar.get_y() + bar.get_height()/2,
                f'{score}/5 - {rec}', va='center', ha='left', fontsize=9, fontweight='bold')
        ax.text(0.1, bar.get_y() + bar.get_height()/2,
                metric, va='center', ha='left', fontsize=8, color='white' if score >= 3 else 'black')

    # Add threshold lines
    ax.axvline(x=4, color='green', linestyle='--', alpha=0.5, linewidth=1)
    ax.axvline(x=3, color='orange', linestyle='--', alpha=0.5, linewidth=1)
    ax.axvline(x=2, color='red', linestyle='--', alpha=0.5, linewidth=1)

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#27AE60', label='PRIORITY'),
        Patch(facecolor='#58D68D', label='GO'),
        Patch(facecolor='#F39C12', label='CONDITIONAL'),
        Patch(facecolor='#E67E22', label='CAUTION'),
        Patch(facecolor='#E74C3C', label='EXCLUDE'),
    ]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=8)

    ax.set_title(f'{gene} - Subgroup Suitability Analysis\n(Phase 1: TCGA | Phase 2: Tempus Mutation | Phase 3: iDAS Whitespace)', fontweight='bold', fontsize=12)
    ax.invert_yaxis()  # Highest score at top
    plt.tight_layout()

    # Save figure
    output_path = os.path.join(figures_dir, f'{gene}_subgroup_suitability.png')
    plt.savefig(output_path, dpi=300, facecolor='white', bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path}")

    return output_path


# =============================================================================
# REPORT GENERATION
# =============================================================================

def generate_report(gene, tcga_stats, tempus_gene_data, idas_assessment, pairwise_df, output_dir, tcga_mutation_stats=None, subgroup_suitability=None):
    """Generate comprehensive markdown report."""
    report = []
    report.append(f"# {gene} Comprehensive NSCLC Target Evaluation Report\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    report.append(f"**Data Sources:** TCGA/GTEx (tumor vs normal) + Tempus RWD\n")
    report.append("\n---\n")

    # Executive Summary
    report.append("## Executive Summary\n")
    report.append("| Metric | Value |")
    report.append("|--------|-------|")
    report.append(f"| **iDAS Alignment** | {idas_assessment.get('overall_alignment', 'Unknown')} |")
    report.append(f"| **Recommendation** | {idas_assessment.get('recommendation', 'Unknown')} |")

    toxicity = idas_assessment.get('on_target_toxicity', {})
    fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)
    risk = toxicity.get('risk_level', 'Unknown')
    report.append(f"| **On-Target Toxicity Risk** | {risk} (log2FC: {fc:.2f}) |")
    report.append("\n---\n")

    # iDAS Whitespace Alignment
    report.append("## iDAS Whitespace Alignment (Tempus RWD)\n")
    report.append("> **Data Source:** Tempus NSCLC cohort (100% CPI-treated/IO-experienced)\n\n")
    report.append("| Priority Whitespace | Expression (log2TPM) | Alignment | N Samples |")
    report.append("|---------------------|----------------------|-----------|-----------|")
    total_idas_n = 0
    for key, info in idas_assessment.get('whitespace_alignment', {}).items():
        label = info.get('label', key)
        expr = info.get('expression', 0)
        align = info.get('alignment', 'Unknown')
        n = info.get('n_samples', 'N/A')
        if isinstance(n, (int, float)):
            total_idas_n += int(n)
        report.append(f"| {label} | {expr:.2f} | **{align}** | {n} |")
    report.append(f"\n*Total iDAS priority samples: N={total_idas_n}*\n")
    report.append("\n---\n")

    # On-Target Toxicity Assessment
    report.append("## On-Target Toxicity Assessment (TCGA/GTEx)\n")
    report.append("> **Data Source:** TCGA-LUAD/LUSC (treatment-naive) vs TCGA Adjacent Normal & GTEx Lung\n\n")
    report.append("**Primary Metric:** Tumor vs Adjacent Normal Expression\n")
    if pairwise_df is not None and len(pairwise_df) > 0:
        report.append("| Comparison | Tumor N | Normal N | Tumor Median | Normal Median | log2FC | p-value |")
        report.append("|------------|---------|----------|--------------|---------------|--------|---------|")
        for _, row in pairwise_df.iterrows():
            report.append(f"| {row['Tumor_Cohort']} vs {row['Normal_Group']} | {int(row['Tumor_N'])} | {int(row['Normal_N'])} | {row['Tumor_Median']:.2f} | {row['Normal_Median']:.2f} | {row['Log2FC']:.2f} | {row['p_value']:.2e} |")
    report.append("\n")

    # Interpretation
    if fc > 1.5:
        linear_fc = 2 ** fc
        report.append(f"**Interpretation:**\n- Tumor expression is {linear_fc:.1f}x higher than adjacent normal\n- **Low on-target toxicity risk** - target appears tumor-specific\n")
    elif fc > 0.5:
        linear_fc = 2 ** fc
        report.append(f"**Interpretation:**\n- Tumor expression is {linear_fc:.1f}x higher than adjacent normal\n- **Medium on-target toxicity risk** - moderate tumor enrichment\n")
    else:
        report.append(f"**Interpretation:**\n- Tumor expression similar to adjacent normal\n- **High on-target toxicity risk** - consider alternative targets\n")
    report.append("\n---\n")

    # Tempus RWD Summary
    report.append("## Tempus Real-World Evidence\n")
    report.append("> **Data Source:** Tempus NSCLC cohort (~2,100 patients, 100% CPI-treated/IO-experienced)\n")
    report.append("> **Note:** Direct comparison with treatment-naive TCGA is confounded by batch + treatment effects.\n\n")

    # Line of Therapy
    if 'lot' in tempus_gene_data:
        lot_data = tempus_gene_data['lot']
        total_lot_n = int(lot_data['n_samples'].sum()) if 'n_samples' in lot_data.columns else 0
        report.append(f"### Line of Therapy Expression (Tempus, N={total_lot_n})\n")
        report.append("| Line of Therapy | N Samples | Mean (log2TPM) | Median |")
        report.append("|-----------------|-----------|----------------|--------|")
        for _, row in lot_data.iterrows():
            if 'group_name' in row:
                n_samples = int(row.get('n_samples', 0))
                median_val = row.get('median', row['mean'])
                median_str = f"{float(median_val):.2f}" if pd.notna(median_val) else "N/A"
                report.append(f"| {row['group_name']} | {n_samples} | {row['mean']:.2f} | {median_str} |")
        report.append("\n")

    # KRAS Status
    if 'kras_status' in tempus_gene_data:
        kras_data = tempus_gene_data['kras_status']
        total_kras_n = int(kras_data['n_samples'].sum()) if 'n_samples' in kras_data.columns else 0
        report.append(f"### KRAS Mutation Status (Tempus, N={total_kras_n})\n")
        report.append("| KRAS Status | N Samples | Mean (log2TPM) | log2FC vs WT |")
        report.append("|-------------|-----------|----------------|--------------|")
        wt_mean = None
        for _, row in kras_data.iterrows():
            if 'KRAS WT' in str(row.get('group_name', '')):
                wt_mean = row['mean']
                break
        for _, row in kras_data.iterrows():
            if 'group_name' in row:
                n_samples = int(row.get('n_samples', 0))
                fc_vs_wt = row['mean'] - wt_mean if wt_mean else 0
                report.append(f"| {row['group_name']} | {n_samples} | {row['mean']:.2f} | {fc_vs_wt:.2f} |")
        report.append("\n")

    # EGFR Status
    if 'egfr_status' in tempus_gene_data:
        egfr_data = tempus_gene_data['egfr_status']
        total_egfr_n = int(egfr_data['n_samples'].sum()) if 'n_samples' in egfr_data.columns else 0
        report.append(f"### EGFR Mutation Status (Tempus, N={total_egfr_n})\n")
        report.append("| EGFR Status | N Samples | Mean (log2TPM) |")
        report.append("|-------------|-----------|----------------|")
        for _, row in egfr_data.iterrows():
            if 'group_name' in row:
                n_samples = int(row.get('n_samples', 0))
                report.append(f"| {row['group_name']} | {n_samples} | {row['mean']:.2f} |")
        report.append("\n")

    report.append("---\n")

    # TCGA Mutation Statistics Section
    if tcga_mutation_stats:
        total_tcga_mut_samples = 0
        for gene_name, mut_df in tcga_mutation_stats.items():
            total_tcga_mut_samples = max(total_tcga_mut_samples, int(mut_df['N'].sum()) if 'N' in mut_df.columns else 0)

        report.append(f"## TCGA Mutation Status Expression (N={total_tcga_mut_samples})\n")
        report.append("> **Data Source:** TCGA-LUAD/LUSC (treatment-naive) - valid within-dataset comparison\n\n")

        for mutation_gene, mut_df in tcga_mutation_stats.items():
            total_n = int(mut_df['N'].sum()) if 'N' in mut_df.columns else 0
            report.append(f"### {mutation_gene} Mutation Status (TCGA, N={total_n})\n")
            report.append("| Status | N | Mean (log2TPM) | Median | SD | log2FC vs WT |")
            report.append("|--------|---|----------------|--------|----|--------------| ")
            for _, row in mut_df.iterrows():
                fc = row.get('log2FC_vs_WT', 0)
                fc_str = f"{fc:.2f}" if pd.notna(fc) else "0.00"
                report.append(f"| {row['Status']} | {int(row['N'])} | {row['Mean']:.2f} | {row['Median']:.2f} | {row['SD']:.2f} | {fc_str} |")
            report.append("\n")

        report.append("---\n")

    # TCGA Cohort Statistics
    total_tcga_n = int(tcga_stats['count'].sum()) if tcga_stats is not None and 'count' in tcga_stats.columns else 0
    report.append(f"## TCGA/GTEx Cohort Expression Statistics (N={total_tcga_n})\n")
    report.append("> **Data Source:** TCGA-LUAD, TCGA-LUSC (treatment-naive), TCGA Adjacent Normal, GTEx Lung, CCLE\n\n")
    if tcga_stats is not None and len(tcga_stats) > 0:
        report.append("| Cohort | N | Median (log2TPM) | Mean | SD |")
        report.append("|--------|---|------------------|------|----| ")
        for _, row in tcga_stats.iterrows():
            report.append(f"| {row['cohort']} | {int(row['count'])} | {row['median']:.2f} | {row['mean']:.2f} | {row['std']:.2f} |")
    report.append("\n---\n")

    # Subgroup Suitability Analysis (3-Phase)
    if subgroup_suitability and subgroup_suitability.get('summary'):
        report.append("## Subgroup Suitability Analysis\n")
        report.append("> **3-Phase Analysis:** Phase 1 (TCGA, treatment-naive) → Phase 2 (Tempus mutation, IO-experienced) → Phase 3 (iDAS whitespace)\n\n")

        # Phase 1: TCGA Analysis (Histology + Mutation)
        report.append("### Phase 1: TCGA Analysis (Treatment-Naive)\n")
        report.append("| Subgroup | Key Metric | Score | Recommendation |")
        report.append("|----------|------------|-------|----------------|")
        for row in subgroup_suitability['summary']:
            if row.get('category') == 'tcga_analysis':
                report.append(f"| {row['subgroup']} | {row['key_metric']} | {row['score']}/5 | **{row['recommendation']}** |")
        report.append("\n")

        # Phase 2: Tempus Mutation Status (IO-experienced)
        report.append("### Phase 2: Tempus Mutation Status (IO-Experienced)\n")
        report.append("| Subgroup | Key Metric | Score | Recommendation |")
        report.append("|----------|------------|-------|----------------|")
        for row in subgroup_suitability['summary']:
            if row.get('category') == 'tempus_mutation':
                report.append(f"| {row['subgroup']} | {row['key_metric']} | {row['score']}/5 | **{row['recommendation']}** |")
        report.append("\n")

        # Phase 3: iDAS Whitespace Suitability
        report.append("### Phase 3: iDAS Whitespace Suitability\n")
        report.append("| Whitespace | Key Metric | Score | Recommendation |")
        report.append("|------------|------------|-------|----------------|")
        for row in subgroup_suitability['summary']:
            if row.get('category') == 'idas_whitespace':
                report.append(f"| {row['subgroup']} | {row['key_metric']} | {row['score']}/5 | **{row['recommendation']}** |")
        report.append("\n")

        # Top Recommendations Summary
        top_recs = subgroup_suitability.get('top_recommendations', {})
        if top_recs.get('priority') or top_recs.get('go') or top_recs.get('exclude'):
            report.append("### Subgroup Recommendations\n")
            if top_recs.get('priority'):
                report.append(f"**PRIORITY Subgroups:** {', '.join(top_recs['priority'])}\n")
            if top_recs.get('go'):
                report.append(f"**GO Subgroups:** {', '.join(top_recs['go'])}\n")
            if top_recs.get('exclude'):
                report.append(f"**CAUTION/EXCLUDE Subgroups:** {', '.join(top_recs['exclude'])}\n")
        report.append("\n---\n")

    # Conclusions
    report.append("## Conclusions and Recommendations\n")
    report.append(f"### Overall Assessment: **{idas_assessment.get('overall_alignment', 'Unknown')}**\n")
    report.append(f"**Recommendation:** {idas_assessment.get('recommendation', 'Unknown')}\n\n")

    report.append("### Key Findings:\n")
    report.append(f"1. **On-target toxicity risk**: {risk} - Tumor vs adjacent normal log2FC = {fc:.2f}\n")

    strong_ws = [k for k, v in idas_assessment.get('whitespace_alignment', {}).items() if v.get('alignment') == 'Strong']
    if strong_ws:
        report.append(f"2. **Strong alignment** with iDAS whitespaces: {', '.join(strong_ws)}\n")

    report.append("\n### Next Steps:\n")
    if 'PRIORITY' in idas_assessment.get('recommendation', ''):
        report.append("- Proceed with target validation studies\n")
        report.append("- Evaluate druggability and modality options\n")
        report.append("- Consider combination strategies for iDAS priority populations\n")
    elif 'CONDITIONAL' in idas_assessment.get('recommendation', ''):
        report.append("- Investigate tumor-selective delivery approaches\n")
        report.append("- Evaluate patient selection strategies\n")
        report.append("- Consider alternative indications with better tumor specificity\n")
    else:
        report.append("- Further evaluation needed\n")
        report.append("- Consider alternative targets with better iDAS alignment\n")

    # Write report
    report_text = "\n".join(report)
    report_path = os.path.join(output_dir, f'{gene}_comprehensive_report.md')
    with open(report_path, 'w') as f:
        f.write(report_text)
    print(f"  Saved: {report_path}")

    return report_path


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def analyze_gene(gene, tcga_meta, gtex_meta, ccle_meta, gene_annotation, tempus_data,
                 cache_dir, output_dir, skip_tcga=False, skip_tempus=False):
    """Run comprehensive analysis for a single gene."""
    print(f"\n{'='*70}")
    print(f"Analyzing: {gene}")
    print('='*70)

    # Create gene output directory
    gene_output_dir = os.path.join(output_dir, gene)
    os.makedirs(gene_output_dir, exist_ok=True)

    tcga_df = None
    tcga_stats = None
    pairwise_df = None
    tcga_mutation_stats = None

    # TCGA Analysis
    if not skip_tcga:
        print(f"\n  Processing TCGA data...")

        # Get gene index
        gene_info = gene_annotation[gene_annotation['gene_name'] == gene]
        if len(gene_info) == 0:
            print(f"  Warning: Gene {gene} not found in annotation")
            return None

        gene_index = gene_info['gene_index'].iloc[0]
        print(f"  Gene index: {gene_index}")

        # Load expression data
        print("  Loading TCGA expression...")
        tcga_expr = load_expression_for_gene(cache_dir, 'tcga', gene_index)
        print(f"    TCGA: {len(tcga_expr)} samples")

        print("  Loading GTEx expression...")
        gtex_expr = load_expression_for_gene(cache_dir, 'gtex', gene_index)
        print(f"    GTEx: {len(gtex_expr)} samples")

        print("  Loading CCLE expression...")
        ccle_expr = load_expression_for_gene(cache_dir, 'ccle', gene_index)
        print(f"    CCLE: {len(ccle_expr)} samples")

        # Build master dataframe
        tcga_df = build_tcga_master_dataframe(tcga_expr, gtex_expr, ccle_expr,
                                               tcga_meta, gtex_meta, ccle_meta)
        print(f"  Built master dataframe: {len(tcga_df)} samples")

        # Calculate statistics
        tcga_stats = calculate_cohort_statistics(tcga_df)

        # Pairwise comparisons
        tumor_cohorts = ['TCGA_LUAD', 'TCGA_LUSC']
        normal_cohorts = ['TCGA_Adjacent', 'GTEx_Lung']
        pairwise_df = perform_pairwise_comparisons(tcga_df, tumor_cohorts, normal_cohorts)
        print(f"  Performed {len(pairwise_df)} pairwise comparisons")

        # TCGA Mutation Statistics
        tcga_mutation_stats = compute_tcga_mutation_statistics(tcga_df)
        if tcga_mutation_stats:
            print(f"  Computed mutation statistics for {len(tcga_mutation_stats)} genes")

    # Tempus Analysis
    tempus_gene_data = {}
    if not skip_tempus and tempus_data:
        print(f"\n  Processing Tempus data...")
        tempus_gene_data = get_tempus_gene_data(gene, tempus_data)
        print(f"  Found Tempus data for {len(tempus_gene_data)} categories")

    # iDAS Alignment Assessment
    print(f"\n  Assessing iDAS alignment...")
    idas_assessment = assess_idas_alignment(tcga_stats, tempus_gene_data, pairwise_df)
    print(f"  Overall alignment: {idas_assessment.get('overall_alignment', 'Unknown')}")
    print(f"  Recommendation: {idas_assessment.get('recommendation', 'Unknown')}")

    # Subgroup Suitability Analysis
    print(f"\n  Computing subgroup suitability...")
    subgroup_suitability = compute_subgroup_suitability(
        gene, tcga_stats, pairwise_df, tcga_mutation_stats, idas_assessment, tempus_gene_data
    )

    # Report top recommendations
    top_recs = subgroup_suitability.get('top_recommendations', {})
    if top_recs.get('priority'):
        print(f"  PRIORITY subgroups: {', '.join(top_recs['priority'])}")
    if top_recs.get('exclude'):
        print(f"  EXCLUDE/CAUTION subgroups: {', '.join(top_recs['exclude'])}")

    # Save subgroup suitability as CSV
    if subgroup_suitability.get('summary'):
        suitability_df = pd.DataFrame(subgroup_suitability['summary'])
        suitability_path = os.path.join(gene_output_dir, f'{gene}_subgroup_suitability.csv')
        suitability_df.to_csv(suitability_path, index=False)
        print(f"  Saved: {suitability_path}")

    # Save iDAS assessment (with subgroup analysis included)
    idas_path = os.path.join(gene_output_dir, f'{gene}_idas_assessment.yaml')
    idas_assessment['gene'] = gene
    idas_assessment['timestamp'] = datetime.now().isoformat()
    idas_assessment['subgroup_analysis'] = {
        'histology': subgroup_suitability.get('histology', {}),
        'mutation_status': subgroup_suitability.get('mutation_status', {}),
        'idas_whitespace': subgroup_suitability.get('idas_whitespace', {}),
        'top_recommendations': subgroup_suitability.get('top_recommendations', {})
    }
    with open(idas_path, 'w') as f:
        yaml.dump(idas_assessment, f, default_flow_style=False)
    print(f"  Saved: {idas_path}")

    # Generate visualization
    if tcga_df is not None or tempus_gene_data:
        print(f"\n  Generating visualizations...")
        create_comprehensive_figure(gene, tcga_df if tcga_df is not None else pd.DataFrame(),
                                   tempus_gene_data, idas_assessment, gene_output_dir)

    # Generate subgroup suitability visualization
    if subgroup_suitability.get('summary'):
        save_subgroup_suitability_figure(gene, subgroup_suitability, gene_output_dir)

    # Generate report
    print(f"\n  Generating report...")
    generate_report(gene, tcga_stats, tempus_gene_data, idas_assessment, pairwise_df, gene_output_dir, tcga_mutation_stats, subgroup_suitability)

    # Save statistics
    if tcga_stats is not None:
        stats_path = os.path.join(gene_output_dir, f'{gene}_tcga_statistics.csv')
        tcga_stats.to_csv(stats_path, index=False)
        print(f"  Saved: {stats_path}")

    if pairwise_df is not None and len(pairwise_df) > 0:
        pairwise_path = os.path.join(gene_output_dir, f'{gene}_pairwise_comparisons.csv')
        pairwise_df.to_csv(pairwise_path, index=False)
        print(f"  Saved: {pairwise_path}")

    # Save TCGA mutation statistics
    if tcga_mutation_stats:
        mut_stats_list = []
        for mutation_gene, mut_df in tcga_mutation_stats.items():
            mut_df_copy = mut_df.copy()
            mut_df_copy['Target_Gene'] = gene
            mut_stats_list.append(mut_df_copy)
        if mut_stats_list:
            all_mut_stats = pd.concat(mut_stats_list, ignore_index=True)
            mut_stats_path = os.path.join(gene_output_dir, f'{gene}_tcga_mutation_statistics.csv')
            all_mut_stats.to_csv(mut_stats_path, index=False)
            print(f"  Saved: {mut_stats_path}")

    return idas_assessment


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='NSCLC Comprehensive Gene Expression Analysis')
    parser.add_argument('--genes', nargs='+', help='Gene symbol(s) to analyze')
    parser.add_argument('--gene-file', help='File with gene symbols (one per line)')
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR, help='Output directory')
    parser.add_argument('--cache-dir', default=DEFAULT_CACHE_DIR, help='Cache directory for data')
    parser.add_argument('--skip-tcga', action='store_true', help='Skip TCGA analysis')
    parser.add_argument('--skip-tempus', action='store_true', help='Skip Tempus analysis')
    args = parser.parse_args()

    # Get genes to analyze
    genes = []
    if args.genes:
        genes = [g.upper() for g in args.genes]
    elif args.gene_file:
        with open(args.gene_file) as f:
            genes = [line.strip().upper() for line in f if line.strip()]

    if not genes:
        print("Error: No genes specified. Use --genes or --gene-file")
        sys.exit(1)

    # Create directories
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.cache_dir, exist_ok=True)

    print("="*70)
    print("NSCLC COMPREHENSIVE TARGET ANALYSIS")
    print("="*70)
    print(f"Analyzing {len(genes)} gene(s): {', '.join(genes)}")
    print(f"TCGA analysis: {'Disabled' if args.skip_tcga else 'Enabled'}")
    print(f"Tempus analysis: {'Disabled' if args.skip_tempus else 'Enabled'}")

    # Load metadata
    tcga_meta = None
    gtex_meta = None
    ccle_meta = None
    gene_annotation = None

    if not args.skip_tcga:
        print("\nLoading TCGA/GTEx/CCLE metadata...")
        gene_annotation = load_gene_annotation(args.cache_dir)
        tcga_meta = load_tcga_metadata(args.cache_dir)
        gtex_meta = load_gtex_metadata(args.cache_dir)
        ccle_meta = load_ccle_metadata(args.cache_dir)
        print("  TCGA data loaded successfully")

    # Load Tempus data
    tempus_data = {}
    if not args.skip_tempus:
        tempus_data = load_all_tempus_data()

    # Analyze each gene
    results = {}
    for gene in genes:
        result = analyze_gene(gene, tcga_meta, gtex_meta, ccle_meta, gene_annotation,
                             tempus_data, args.cache_dir, args.output_dir,
                             args.skip_tcga, args.skip_tempus)
        if result:
            results[gene] = result

    # Summary
    print("\n" + "="*70)
    print("ANALYSIS COMPLETE")
    print("="*70)
    print(f"\nProcessed {len(results)}/{len(genes)} genes successfully")
    print(f"Output directory: {args.output_dir}")

    # Print summary table
    print("\n" + "-"*70)
    print("iDAS ALIGNMENT SUMMARY")
    print("-"*70)
    print(f"{'Gene':<15} {'Alignment':<12} {'Toxicity Risk':<15} {'Recommendation'}")
    print("-"*70)
    for gene, assessment in results.items():
        align = assessment.get('overall_alignment', 'Unknown')
        tox = assessment.get('on_target_toxicity', {}).get('risk_level', 'Unknown')
        rec = 'PRIORITY' if 'PRIORITY' in assessment.get('recommendation', '') else \
              'CONDITIONAL' if 'CONDITIONAL' in assessment.get('recommendation', '') else 'CONSIDER'
        print(f"{gene:<15} {align:<12} {tox:<15} {rec}")


if __name__ == '__main__':
    main()
