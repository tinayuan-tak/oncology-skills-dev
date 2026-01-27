#!/usr/bin/env python3
"""
CRC Gene Expression Analysis
Analyzes gene expression across CRC cohorts, normal tissues, and cell lines.

Usage:
    python crc_gene_analysis.py --genes CDK4 CDK6 CCND1
    python crc_gene_analysis.py --gene-file genes.txt
    python crc_gene_analysis.py --genes CDK4 --output-dir ./my_results

Data Sources (from S3):
    - TCGA COAD/READ expression and metadata
    - GTEx normal colon expression
    - CCLE CRC cell line expression
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

# Plot settings
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['figure.dpi'] = 150
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
sns.set_style('whitegrid')

# Color schemes
COHORT_COLORS = {
    'Cohort_2A': '#E74C3C',      # Red - RAS mutant MSS
    'Cohort_2B': '#2ECC71',      # Green - RAS WT MSS
    'Cohort_4': '#3498DB',       # Blue - Early stage
    'Cohort_5': '#9B59B6',       # Purple - All MSS
    'Cohort_6': '#F39C12',       # Orange - MSI-H
    'TCGA_Tumor': '#E74C3C',     # Red - All Tumor
    'TCGA_Adjacent': '#7F8C8D',  # Gray - Adjacent Normal
    'GTEx_Normal': '#1ABC9C',    # Teal - GTEx Normal
    'CCLE_CRC': '#8B4513'        # Brown - CRC Cell Lines
}

CMS_COLORS = {
    'CMS1': '#E69F00',   # Orange - MSI Immune
    'CMS2': '#56B4E9',   # Sky Blue - Canonical
    'CMS3': '#009E73',   # Green - Metabolic
    'CMS4': '#CC79A7',   # Pink - Mesenchymal
    'Normal': '#999999'
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
    'CCLE_CRC': 'CRC\nCell Lines'
}

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

    cmd = f"aws s3 cp {s3_path} {local_path} --profile {AWS_PROFILE}"
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
    return df


def load_tcga_metadata(cache_dir):
    """Load TCGA sample metadata."""
    s3_path = f"{S3_BUCKET}/tcga_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/tcga_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)

    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    return df


def load_ccle_metadata(cache_dir):
    """Load CCLE sample metadata."""
    s3_path = f"{S3_BUCKET}/ccle_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/ccle_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)

    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    return df


def load_gtex_metadata(cache_dir):
    """Load GTEx sample metadata."""
    s3_path = f"{S3_BUCKET}/gtex_b38_gc33/raw/sample_metadata.tsv.gz"
    local_path = f"{cache_dir}/gtex_metadata.tsv.gz"
    download_s3_file(s3_path, local_path)

    df = pd.read_csv(local_path, sep='\t', compression='gzip')
    return df


def load_expression_for_gene(cache_dir, dataset, gene_index, sample_indices):
    """
    Load expression data for a specific gene and set of samples.
    Expression data is in long format: sample_index, gene_index, fpkm, count, tpm
    """
    dataset_paths = {
        'tcga': f"{S3_BUCKET}/tcga_b38_gc33/raw/rna_seq_gene_expression.tsv.gz",
        'ccle': f"{S3_BUCKET}/ccle_b38_gc33/raw/rna_seq_gene_expression.tsv.gz",
        'gtex': f"{S3_BUCKET}/gtex_b38_gc33/raw/rna_seq_gene_expression.tsv.gz"
    }

    s3_path = dataset_paths[dataset]
    local_path = f"{cache_dir}/{dataset}_expression.tsv.gz"
    download_s3_file(s3_path, local_path, quiet=True)

    # Read expression data in chunks to handle large files
    # Filter for the specific gene_index and sample_indices
    sample_set = set(sample_indices)
    results = []

    chunksize = 1000000  # 1M rows at a time
    for chunk in pd.read_csv(local_path, sep='\t', compression='gzip', chunksize=chunksize):
        # Filter for our gene and samples
        mask = (chunk['gene_index'] == gene_index) & (chunk['sample_index'].isin(sample_set))
        filtered = chunk[mask]
        if len(filtered) > 0:
            results.append(filtered)

    if len(results) > 0:
        return pd.concat(results, ignore_index=True)
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

def calculate_statistics(groups_dict):
    """Calculate descriptive statistics for each group."""
    records = []

    for group_name, values in groups_dict.items():
        values = np.array([v for v in values if pd.notna(v)])
        if len(values) > 0:
            records.append({
                'group': group_name,
                'n': len(values),
                'mean': np.mean(values),
                'median': np.median(values),
                'std': np.std(values),
                'min': np.min(values),
                'max': np.max(values),
                'Q1': np.percentile(values, 25),
                'Q3': np.percentile(values, 75),
                'IQR': np.percentile(values, 75) - np.percentile(values, 25)
            })

    return pd.DataFrame(records)


def perform_pairwise_comparisons(groups_dict, reference_groups=['TCGA_Adjacent', 'GTEx_Normal']):
    """Perform Mann-Whitney U tests comparing tumor groups to normal."""
    results = []

    for ref_group in reference_groups:
        if ref_group not in groups_dict or len(groups_dict[ref_group]) == 0:
            continue

        ref_values = np.array([v for v in groups_dict[ref_group] if pd.notna(v)])
        if len(ref_values) < 3:
            continue

        for group_name, values in groups_dict.items():
            if group_name in reference_groups:
                continue

            values = np.array([v for v in values if pd.notna(v)])
            if len(values) < 3:
                continue

            try:
                stat, pval = mannwhitneyu(values, ref_values, alternative='two-sided')
                log2fc = np.median(values) - np.median(ref_values)

                n1, n2 = len(values), len(ref_values)
                effect_size = 1 - (2 * stat) / (n1 * n2)

                results.append({
                    'Tumor_Cohort': group_name,
                    'Normal_Group': ref_group,
                    'N_tumor': n1,
                    'N_normal': n2,
                    'Tumor_median': np.median(values),
                    'Normal_median': np.median(ref_values),
                    'Log2FC': log2fc,
                    'U_statistic': stat,
                    'p_value': pval,
                    'effect_size': effect_size
                })
            except Exception as e:
                print(f"  Warning: Could not compare {group_name} vs {ref_group}: {e}")

    df = pd.DataFrame(results)

    if len(df) > 0:
        _, pvals_adj, _, _ = multipletests(df['p_value'], method='fdr_bh')
        df['p_adjusted'] = pvals_adj
        df['significant'] = df['p_adjusted'] < 0.05

    return df


def kruskal_wallis_test(groups_dict):
    """Perform Kruskal-Wallis test across all groups."""
    groups = []
    for name, values in groups_dict.items():
        values = [v for v in values if pd.notna(v)]
        if len(values) > 0:
            groups.append(values)

    if len(groups) < 2:
        return None, None

    try:
        stat, pval = kruskal(*groups)
        return stat, pval
    except:
        return None, None


# =============================================================================
# VISUALIZATION FUNCTIONS
# =============================================================================

def plot_cohort_comparison(groups_dict, gene_symbol, output_dir):
    """Create box plot comparing expression across cohorts."""
    plot_order = ['TCGA_Tumor', 'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']
    plot_order = [g for g in plot_order if g in groups_dict and len(groups_dict[g]) > 0]

    if len(plot_order) == 0:
        print("  No data available for cohort plot")
        return

    fig, ax = plt.subplots(figsize=(12, 8))

    data = [[v for v in groups_dict[g] if pd.notna(v)] for g in plot_order]
    palette = [COHORT_COLORS.get(g, '#666666') for g in plot_order]

    bp = ax.boxplot(data, positions=range(len(plot_order)), widths=0.6,
                    patch_artist=True, showfliers=True,
                    flierprops={'marker': 'o', 'markersize': 3, 'alpha': 0.4, 'markerfacecolor': 'gray'})

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

    labels = [COHORT_LABELS.get(g, g) for g in plot_order]
    ax.set_xticks(range(len(plot_order)))
    ax.set_xticklabels(labels, fontsize=11)

    # Sample sizes
    y_min = ax.get_ylim()[0]
    for i, g in enumerate(plot_order):
        n = len([v for v in groups_dict[g] if pd.notna(v)])
        ax.text(i, y_min - 0.5, f'n={n}', ha='center', va='top', fontsize=10, color='gray')

    ax.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=12)
    ax.set_xlabel('Group', fontsize=12)
    ax.set_title(f'{gene_symbol} Expression Across CRC Cohorts and Normal Tissues',
                 fontsize=14, fontweight='bold')
    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#E74C3C', alpha=0.7, edgecolor='black', label='CRC Tumor (TCGA)'),
        Patch(facecolor='#7F8C8D', alpha=0.7, edgecolor='black', label='Adjacent Normal (TCGA)'),
        Patch(facecolor='#1ABC9C', alpha=0.7, edgecolor='black', label='Normal Colon (GTEx)'),
        Patch(facecolor='#8B4513', alpha=0.7, edgecolor='black', label='CRC Cell Lines (CCLE)')
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=9)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_cohort_boxplot.png', dpi=300, bbox_inches='tight')
    plt.savefig(f'{output_dir}/{gene_symbol}_cohort_boxplot.pdf', bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_cohort_boxplot.png")


def plot_violin(groups_dict, gene_symbol, output_dir):
    """Create violin plot with embedded box plot."""
    plot_order = ['TCGA_Tumor', 'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']
    plot_order = [g for g in plot_order if g in groups_dict and len(groups_dict[g]) > 0]

    if len(plot_order) == 0:
        return

    fig, ax = plt.subplots(figsize=(12, 8))

    data = [[v for v in groups_dict[g] if pd.notna(v)] for g in plot_order]
    palette = [COHORT_COLORS.get(g, '#666666') for g in plot_order]

    # Violin plot
    parts = ax.violinplot(data, positions=range(len(plot_order)),
                          showmeans=False, showmedians=False, showextrema=False)

    for i, pc in enumerate(parts['bodies']):
        pc.set_facecolor(palette[i])
        pc.set_edgecolor('black')
        pc.set_alpha(0.7)
        pc.set_linewidth(1.5)

    # Box plots inside
    bp = ax.boxplot(data, positions=range(len(plot_order)), widths=0.15,
                    patch_artist=True, showfliers=False)

    for patch in bp['boxes']:
        patch.set_facecolor('white')
        patch.set_edgecolor('black')
        patch.set_linewidth(1.5)

    for median in bp['medians']:
        median.set_color('red')
        median.set_linewidth(2)

    labels = [COHORT_LABELS.get(g, g) for g in plot_order]
    ax.set_xticks(range(len(plot_order)))
    ax.set_xticklabels(labels, fontsize=11)

    ax.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=12)
    ax.set_xlabel('Group', fontsize=12)
    ax.set_title(f'{gene_symbol} Expression Across CRC Cohorts', fontsize=14, fontweight='bold')
    ax.yaxis.grid(True, linestyle='--', alpha=0.3)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_cohort_violin.png', dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_cohort_violin.png")


def plot_cell_lines(cell_line_data, gene_symbol, output_dir):
    """Create bar plot of expression across CRC cell lines."""
    if len(cell_line_data) == 0:
        return

    # Sort by expression
    df = pd.DataFrame(cell_line_data).sort_values('expression', ascending=False)

    # Color by MSI status
    color_map = {'MSI': '#F39C12', 'MSS': '#3498DB'}
    colors = df['msi_status'].map(lambda x: color_map.get(x, '#666666') if pd.notna(x) else '#666666')

    fig, ax = plt.subplots(figsize=(16, 8))

    ax.bar(range(len(df)), df['expression'], color=colors, alpha=0.8, edgecolor='black')

    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(df['cell_line'], rotation=90, fontsize=8)
    ax.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=12)
    ax.set_xlabel('Cell Line', fontsize=12)
    ax.set_title(f'{gene_symbol} Expression in CRC Cell Lines', fontsize=14, fontweight='bold')

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#F39C12', alpha=0.8, edgecolor='black', label='MSI'),
        Patch(facecolor='#3498DB', alpha=0.8, edgecolor='black', label='MSS'),
        Patch(facecolor='#666666', alpha=0.8, edgecolor='black', label='Unknown')
    ]
    ax.legend(handles=legend_elements, loc='upper right')

    ax.yaxis.grid(True, linestyle='--', alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(f'{output_dir}/{gene_symbol}_cell_lines.png', dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {gene_symbol}_cell_lines.png")


def plot_comprehensive(groups_dict, gene_symbol, output_dir, stats_df, pairwise_df):
    """Create multi-panel comprehensive figure."""
    fig = plt.figure(figsize=(16, 12))

    # Panel A: Main comparison
    ax1 = fig.add_subplot(2, 2, 1)
    plot_order = ['TCGA_Tumor', 'TCGA_Adjacent', 'GTEx_Normal', 'CCLE_CRC']
    plot_order = [g for g in plot_order if g in groups_dict and len(groups_dict[g]) > 0]

    if len(plot_order) > 0:
        data = [[v for v in groups_dict[g] if pd.notna(v)] for g in plot_order]
        palette = [COHORT_COLORS.get(g, '#666666') for g in plot_order]

        bp1 = ax1.boxplot(data, positions=range(len(plot_order)), widths=0.6,
                          patch_artist=True, showfliers=True,
                          flierprops={'marker': 'o', 'markersize': 2, 'alpha': 0.4})

        for patch, color in zip(bp1['boxes'], palette):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
            patch.set_edgecolor('black')

        for median in bp1['medians']:
            median.set_color('black')
            median.set_linewidth(2)

        short_labels = {'TCGA_Tumor': 'Tumor', 'TCGA_Adjacent': 'Adjacent\nNormal',
                        'GTEx_Normal': 'GTEx\nNormal', 'CCLE_CRC': 'Cell Lines'}
        ax1.set_xticks(range(len(plot_order)))
        ax1.set_xticklabels([short_labels.get(g, g) for g in plot_order], fontsize=10)
        ax1.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=10)
        ax1.yaxis.grid(True, linestyle='--', alpha=0.3)

    ax1.set_title(f'A. {gene_symbol} by Group', fontsize=11, fontweight='bold', loc='left')

    # Panel B: Tumor vs Normal only
    ax2 = fig.add_subplot(2, 2, 2)
    tn_groups = ['TCGA_Tumor', 'TCGA_Adjacent', 'GTEx_Normal']
    tn_groups = [g for g in tn_groups if g in groups_dict and len(groups_dict[g]) > 0]

    if len(tn_groups) > 0:
        data = [[v for v in groups_dict[g] if pd.notna(v)] for g in tn_groups]
        palette = [COHORT_COLORS.get(g, '#666666') for g in tn_groups]

        bp2 = ax2.boxplot(data, positions=range(len(tn_groups)), widths=0.5,
                          patch_artist=True, showfliers=True,
                          flierprops={'marker': 'o', 'markersize': 2, 'alpha': 0.4})

        for patch, color in zip(bp2['boxes'], palette):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
            patch.set_edgecolor('black')

        for median in bp2['medians']:
            median.set_color('black')
            median.set_linewidth(2)

        labels = [f'{short_labels.get(g, g)}\n(n={len([v for v in groups_dict[g] if pd.notna(v)])})' for g in tn_groups]
        ax2.set_xticks(range(len(tn_groups)))
        ax2.set_xticklabels(labels, fontsize=9)

    ax2.set_ylabel(r'$\log_2(TPM + 1)$', fontsize=10)
    ax2.set_title(f'B. {gene_symbol}: Tumor vs Normal', fontsize=11, fontweight='bold', loc='left')
    ax2.yaxis.grid(True, linestyle='--', alpha=0.3)

    # Panel C: Distribution histogram
    ax3 = fig.add_subplot(2, 2, 3)
    if 'TCGA_Tumor' in groups_dict and 'GTEx_Normal' in groups_dict:
        tumor_vals = [v for v in groups_dict['TCGA_Tumor'] if pd.notna(v)]
        normal_vals = [v for v in groups_dict['GTEx_Normal'] if pd.notna(v)]

        ax3.hist(tumor_vals, bins=30, alpha=0.6, color='#E74C3C', label='Tumor', density=True)
        ax3.hist(normal_vals, bins=30, alpha=0.6, color='#1ABC9C', label='Normal', density=True)
        ax3.legend()
        ax3.set_xlabel(r'$\log_2(TPM + 1)$', fontsize=10)
        ax3.set_ylabel('Density', fontsize=10)

    ax3.set_title(f'C. Expression Distribution', fontsize=11, fontweight='bold', loc='left')

    # Panel D: Statistics table
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.axis('off')

    if len(stats_df) > 0:
        table_data = []
        for _, row in stats_df.iterrows():
            table_data.append([
                row['group'].replace('TCGA_', '').replace('GTEx_', '').replace('CCLE_', ''),
                int(row['n']),
                f'{row["median"]:.2f}',
                f'{row["mean"]:.2f}',
                f'{row["std"]:.2f}'
            ])

        table = ax4.table(
            cellText=table_data,
            colLabels=['Group', 'N', 'Median', 'Mean', 'SD'],
            loc='center',
            cellLoc='center',
            colWidths=[0.3, 0.15, 0.18, 0.18, 0.18]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.2, 1.5)

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
# MAIN ANALYSIS FUNCTION
# =============================================================================

def analyze_gene(gene_symbol, gene_annotation, tcga_meta, ccle_meta, gtex_meta, cache_dir, output_dir):
    """Run complete analysis for a single gene."""
    print(f"\n{'='*60}")
    print(f"Analyzing: {gene_symbol}")
    print(f"{'='*60}")

    # Find gene index
    gene_index, gene_id, gene_name = find_gene_index(gene_symbol, gene_annotation)
    if gene_index is None:
        print(f"  ERROR: Gene {gene_symbol} not found in annotation")
        return None

    print(f"  Gene ID: {gene_id}")
    print(f"  Gene Index: {gene_index}")

    # Create gene output directory
    gene_output = f"{output_dir}/{gene_symbol}"
    os.makedirs(gene_output, exist_ok=True)

    # Initialize groups
    groups = {}
    cell_line_data = []

    # === TCGA DATA ===
    print("  Processing TCGA data...")
    tcga_tumor = get_tcga_crc_tumor_samples(tcga_meta)
    tcga_normal = get_tcga_crc_normal_samples(tcga_meta)

    print(f"    TCGA CRC tumor samples: {len(tcga_tumor)}")
    print(f"    TCGA CRC normal samples: {len(tcga_normal)}")

    # Get expression for TCGA tumor samples
    if len(tcga_tumor) > 0:
        tumor_indices = tcga_tumor['sample_index'].tolist()
        tumor_expr = load_expression_for_gene(cache_dir, 'tcga', gene_index, tumor_indices)
        if len(tumor_expr) > 0:
            # Log2 transform TPM
            tumor_expr['log2_tpm'] = np.log2(tumor_expr['tpm'] + 1)
            groups['TCGA_Tumor'] = tumor_expr['log2_tpm'].tolist()
            print(f"    TCGA tumor expression values: {len(tumor_expr)}")

    # Get expression for TCGA normal samples
    if len(tcga_normal) > 0:
        normal_indices = tcga_normal['sample_index'].tolist()
        normal_expr = load_expression_for_gene(cache_dir, 'tcga', gene_index, normal_indices)
        if len(normal_expr) > 0:
            normal_expr['log2_tpm'] = np.log2(normal_expr['tpm'] + 1)
            groups['TCGA_Adjacent'] = normal_expr['log2_tpm'].tolist()
            print(f"    TCGA normal expression values: {len(normal_expr)}")

    # === GTEx DATA ===
    print("  Processing GTEx data...")
    gtex_colon = get_gtex_colon_samples(gtex_meta)
    print(f"    GTEx colon samples: {len(gtex_colon)}")

    if len(gtex_colon) > 0:
        gtex_indices = gtex_colon['sample_index'].tolist()
        gtex_expr = load_expression_for_gene(cache_dir, 'gtex', gene_index, gtex_indices)
        if len(gtex_expr) > 0:
            gtex_expr['log2_tpm'] = np.log2(gtex_expr['tpm'] + 1)
            groups['GTEx_Normal'] = gtex_expr['log2_tpm'].tolist()
            print(f"    GTEx expression values: {len(gtex_expr)}")

    # === CCLE DATA ===
    print("  Processing CCLE data...")
    ccle_crc = get_ccle_crc_samples(ccle_meta)
    print(f"    CCLE CRC cell lines: {len(ccle_crc)}")

    if len(ccle_crc) > 0:
        ccle_indices = ccle_crc['sample_index'].tolist()
        ccle_expr = load_expression_for_gene(cache_dir, 'ccle', gene_index, ccle_indices)
        if len(ccle_expr) > 0:
            ccle_expr['log2_tpm'] = np.log2(ccle_expr['tpm'] + 1)
            groups['CCLE_CRC'] = ccle_expr['log2_tpm'].tolist()
            print(f"    CCLE expression values: {len(ccle_expr)}")

            # Build cell line data for plotting
            ccle_expr_merged = ccle_expr.merge(ccle_crc[['sample_index', 'cell_line_name', 'microsatellite_instability_msi_status_ccle']],
                                                on='sample_index', how='left')
            for _, row in ccle_expr_merged.iterrows():
                cell_line_data.append({
                    'cell_line': row.get('cell_line_name', 'Unknown'),
                    'expression': row['log2_tpm'],
                    'msi_status': row.get('microsatellite_instability_msi_status_ccle', 'Unknown')
                })

    # Calculate statistics
    print("  Calculating statistics...")
    stats_df = calculate_statistics(groups)
    pairwise_df = perform_pairwise_comparisons(groups)
    kw_stat, kw_pval = kruskal_wallis_test(groups)

    # Generate visualizations
    print("  Generating visualizations...")
    plot_cohort_comparison(groups, gene_symbol, gene_output)
    plot_violin(groups, gene_symbol, gene_output)

    if len(cell_line_data) > 0:
        plot_cell_lines(cell_line_data, gene_symbol, gene_output)

    plot_comprehensive(groups, gene_symbol, gene_output, stats_df, pairwise_df)

    # Export results
    print("  Exporting results...")
    stats_df.to_csv(f'{gene_output}/{gene_symbol}_cohort_statistics.csv', index=False)

    if len(pairwise_df) > 0:
        pairwise_df.to_csv(f'{gene_output}/{gene_symbol}_pairwise_comparisons.csv', index=False)

    # Export expression data
    expr_records = []
    for group, values in groups.items():
        for i, val in enumerate(values):
            expr_records.append({'group': group, 'expression': val})
    pd.DataFrame(expr_records).to_csv(f'{gene_output}/{gene_symbol}_expression_data.csv', index=False)

    if len(cell_line_data) > 0:
        pd.DataFrame(cell_line_data).to_csv(f'{gene_output}/{gene_symbol}_cell_line_expression.csv', index=False)

    # Print summary
    print(f"\n  SUMMARY:")
    print(f"  {'Group':<20} {'N':>6} {'Median':>8} {'Mean':>8}")
    print(f"  {'-'*44}")
    for _, row in stats_df.iterrows():
        print(f"  {row['group']:<20} {int(row['n']):>6} {row['median']:>8.2f} {row['mean']:>8.2f}")

    if kw_stat is not None:
        print(f"\n  Kruskal-Wallis test: H={kw_stat:.3f}, p={kw_pval:.2e}")

    if len(pairwise_df) > 0 and 'significant' in pairwise_df.columns:
        sig_results = pairwise_df[pairwise_df['significant']]
        if len(sig_results) > 0:
            print(f"\n  Significant comparisons (FDR < 0.05):")
            for _, row in sig_results.iterrows():
                direction = "higher" if row['Log2FC'] > 0 else "lower"
                print(f"    {row['Tumor_Cohort']} vs {row['Normal_Group']}: {direction} (log2FC={row['Log2FC']:.2f}, p_adj={row['p_adjusted']:.2e})")

    return {
        'gene_symbol': gene_symbol,
        'gene_id': gene_id,
        'output_dir': gene_output,
        'statistics': stats_df,
        'comparisons': pairwise_df
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='CRC Gene Expression Analysis',
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
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR, help='Output directory')
    parser.add_argument('--cache-dir', default=DEFAULT_CACHE_DIR, help='Data cache directory')

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

    print("="*60)
    print("CRC Gene Expression Analysis")
    print("="*60)
    print(f"Genes to analyze: {', '.join(genes)}")
    print(f"Output directory: {args.output_dir}")
    print(f"Cache directory: {args.cache_dir}")

    # Create directories
    os.makedirs(args.cache_dir, exist_ok=True)
    os.makedirs(args.output_dir, exist_ok=True)

    # Load metadata (not expression - that's loaded per gene)
    print("\n1. Loading metadata from S3...")
    gene_annotation = load_gene_annotation(args.cache_dir)
    tcga_meta = load_tcga_metadata(args.cache_dir)
    ccle_meta = load_ccle_metadata(args.cache_dir)
    gtex_meta = load_gtex_metadata(args.cache_dir)

    print(f"\n  Gene annotation: {len(gene_annotation)} genes")
    print(f"  TCGA samples: {len(tcga_meta)}")
    print(f"  CCLE samples: {len(ccle_meta)}")
    print(f"  GTEx samples: {len(gtex_meta)}")

    # Analyze each gene
    print("\n2. Analyzing genes...")
    results = []
    for gene in genes:
        result = analyze_gene(
            gene, gene_annotation,
            tcga_meta, ccle_meta, gtex_meta,
            args.cache_dir, args.output_dir
        )
        if result:
            results.append(result)

    # Final summary
    print("\n" + "="*60)
    print("ANALYSIS COMPLETE")
    print("="*60)
    print(f"\nSuccessfully analyzed: {len(results)}/{len(genes)} genes")
    print(f"Results saved to: {args.output_dir}")

    if len(results) > 0:
        print("\nOutput files for each gene:")
        for r in results:
            print(f"  {r['gene_symbol']}/")
            print(f"    - {r['gene_symbol']}_cohort_boxplot.png")
            print(f"    - {r['gene_symbol']}_cohort_violin.png")
            print(f"    - {r['gene_symbol']}_comprehensive_analysis.png")
            print(f"    - {r['gene_symbol']}_cohort_statistics.csv")
            print(f"    - {r['gene_symbol']}_pairwise_comparisons.csv")

    return results


if __name__ == '__main__':
    main()
