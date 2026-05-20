#!/usr/bin/env python3
"""
CRC Comprehensive Gene Expression Analysis - TCGA + Tempus Unified

Complete target evaluation pipeline combining:
- TCGA raw expression: Tumor vs Normal comparisons (on-target toxicity)
- GTEx: Healthy tissue baseline
- CCLE: Cell line expression for in vitro validation
- Tempus RWD: Line-of-therapy stratification (iDAS alignment)

This is the recommended script for comprehensive CRC target evaluation.

Cohort Naming (unified with iDAS alignment):
    TCGA Cohorts:
        TCGA_RASMut_MSS   - RAS-mutant MSS - iDAS Priority: Frontline
        TCGA_RASWT_MSS    - RAS wild-type MSS
        TCGA_Resectable   - Early stage I/II - iDAS Priority: Neo/Adjuvant
        TCGA_MSS_All      - All MSS samples
        TCGA_MSIH         - MSI-H
        TCGA_Adjacent     - Adjacent normal (on-target toxicity reference)
        GTEx_Colon        - Normal colon (healthy baseline)
        CCLE_CRC          - CRC cell lines

    Tempus Cohorts (iDAS-aligned):
        Tempus_RASMut_MSS_1L2L    - RAS-mut MSS 1L-2L (n=85,560)
        Tempus_RASMut_MSS_3Lplus  - RAS-mut MSS 3L+ (n=26,319) - iDAS Priority
        Tempus_RASWT_MSS_1L2L     - RAS-WT MSS 1L-2L (n=58,683)
        Tempus_RASWT_MSS_3Lplus   - RAS-WT MSS 3L+ (n=13,299)
        Tempus_MSS_3Lplus         - All MSS 3L+ (n=39,618) - iDAS Priority

Usage:
    python crc_comprehensive_analysis.py --genes TNFRSF12A CDK4 EPCAM
    python crc_comprehensive_analysis.py --gene-file genes.txt --output-dir ./results
    python crc_comprehensive_analysis.py --genes MET --skip-tcga  # Tempus only
    python crc_comprehensive_analysis.py --genes MET --skip-tempus  # TCGA only

Data Sources:
    TCGA/GTEx/CCLE: s3://onc-compbio/omicsoft_oncoland_data
    Tempus: s3://onc-compbio/Tempus/crc
"""

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
from scipy.stats import mannwhitneyu, kruskal
from statsmodels.stats.multitest import multipletests
import os
import sys
from datetime import datetime
import warnings
import yaml
import boto3
import s3fs
from botocore.exceptions import ClientError

warnings.filterwarnings('ignore')


def convert_numpy_types(obj):
    """Convert numpy types to Python native types for YAML serialization."""
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    else:
        return obj


# =============================================================================
# CONFIGURATION
# =============================================================================

AWS_PROFILE = 'cbg'

# S3 Configuration
S3_BUCKET = 'onc-compbio'
TCGA_S3_PREFIX = 'omicsoft_oncoland_data'
TEMPUS_S3_PREFIX = 'Tempus/crc'

# Legacy S3 paths (for compatibility)
TCGA_S3_BUCKET = f's3://{S3_BUCKET}/{TCGA_S3_PREFIX}'
TEMPUS_S3_BUCKET = f's3://{S3_BUCKET}/{TEMPUS_S3_PREFIX}'

# Initialize S3 clients (lazy loading)
_s3_client = None
_s3_fs = None


def get_s3_client():
    """Get boto3 S3 client with profile credentials."""
    global _s3_client
    if _s3_client is None:
        session = boto3.Session(profile_name=AWS_PROFILE)
        _s3_client = session.client('s3', verify=False)
    return _s3_client


def get_s3_filesystem():
    """Get s3fs filesystem with profile credentials."""
    global _s3_fs
    if _s3_fs is None:
        session = boto3.Session(profile_name=AWS_PROFILE)
        credentials = session.get_credentials()
        _s3_fs = s3fs.S3FileSystem(
            key=credentials.access_key,
            secret=credentials.secret_key,
            token=credentials.token,
            client_kwargs={'verify': False}
        )
    return _s3_fs


def parse_s3_uri(s3_uri):
    """Parse S3 URI into bucket and key."""
    if s3_uri.startswith('s3://'):
        path = s3_uri[5:]
    else:
        path = s3_uri
    parts = path.split('/', 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ''
    return bucket, key


def validate_s3_access(s3_uri):
    """Validate access to S3 object."""
    bucket, key = parse_s3_uri(s3_uri)
    try:
        get_s3_client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False

# Skill name for output file naming
SKILL_NAME = 'analysis-bulk-rna-crc'

# Default directories
DEFAULT_CACHE_DIR = './data_cache'
DEFAULT_OUTPUT_DIR = './results'


def get_output_filename(gene, content_type, ext):
    """Generate consistent output filename following naming convention.

    Pattern: {GENE}_{skill-name}_{content-type}.{ext}

    Args:
        gene: Gene symbol (e.g., 'TNFRSF12A')
        content_type: Type of content (e.g., 'figure', 'report', 'panel-01')
        ext: File extension without dot (e.g., 'png', 'md', 'csv')

    Returns:
        Filename string (e.g., 'TNFRSF12A_analysis-bulk-rna-crc_figure.png')
    """
    return f"{gene}_{SKILL_NAME}_{content_type}.{ext}"

# Cohort and annotation files (TCGA)
DEFAULT_COHORT_PATH = './crc_cohort_assignments.csv'
DEFAULT_CMS_PATH = './TCGA_CMS_prediction.csv'
DEFAULT_ADJ_NORMAL_PATH = './TCGA-COAD-READ-AdjNormal.tsv'

# S3 paths for annotation files (auto-download if not found locally)
TCGA_ANNOTATION_S3 = 's3://onc-compbio/TCGA'
COHORT_S3_PATH = f'{TCGA_ANNOTATION_S3}/crc_cohort_assignments.csv'
CMS_S3_PATH = f'{TCGA_ANNOTATION_S3}/TCGA_CMS_prediction.csv'
ADJ_NORMAL_S3_PATH = f'{TCGA_ANNOTATION_S3}/TCGA-COAD-READ-AdjNormal.tsv'

# Tempus summary files
TEMPUS_FILES = {
    'idas_groups': 'gene_summary_by_iDAS_group.csv',
    'idas_groups_wide': 'gene_summary_by_iDAS_group_wide.csv',
    'key_target_3lplus': 'gene_summary_key_target_MSS_RASMut_3L+.csv',
    'lot_mss': 'gene_summary_by_LOT_MSS.csv',
    'ras_status_mss': 'gene_summary_by_RAS_status_MSS.csv',
    'msi_status': 'gene_summary_by_MSI_status.csv',
    'cpi_status': 'gene_summary_by_CPI_status.csv',
    'cms': 'gene_summary_by_CMS.csv',
    'overall': 'gene_summary_overall.csv',
}

# =============================================================================
# UNIFIED COHORT NAMING
# =============================================================================

# Legacy to new cohort name mapping
LEGACY_COHORT_MAP = {
    'Cohort_2A': 'TCGA_RASMut_MSS',
    'Cohort_2B': 'TCGA_RASWT_MSS',
    'Cohort_4': 'TCGA_Resectable',
    'Cohort_5': 'TCGA_MSS_All',
    'Cohort_6': 'TCGA_MSIH',
}

# New to legacy mapping (reverse)
NEW_TO_LEGACY_MAP = {v: k for k, v in LEGACY_COHORT_MAP.items()}

# Tempus group mapping
TEMPUS_GROUP_MAP = {
    'MSS_RASMut_1L2L': 'Tempus_RASMut_MSS_1L2L',
    'MSS_RASMut_3L+': 'Tempus_RASMut_MSS_3Lplus',
    'MSS_RASWT_1L2L': 'Tempus_RASWT_MSS_1L2L',
    'MSS_RASWT_3L+': 'Tempus_RASWT_MSS_3Lplus',
    '1L-2L': 'Tempus_MSS_1L2L',
    '3L+ Chemorefractory': 'Tempus_MSS_3Lplus',
    'RAS Mutant': 'Tempus_RASMut_MSS',
    'RAS WT': 'Tempus_RASWT_MSS',
    'MSS': 'Tempus_MSS',
    'MSI-H': 'Tempus_MSIH',
    'CPI Naive': 'Tempus_CPI_Naive',
    'CPI Treated': 'Tempus_CPI_Treated',
}

# TCGA cohorts to analyze
TCGA_COHORTS = ['TCGA_RASMut_MSS', 'TCGA_RASWT_MSS', 'TCGA_Resectable', 'TCGA_MSS_All', 'TCGA_MSIH']

# iDAS Priority cohorts
IDAS_PRIORITY_COHORTS = {
    'TCGA_RASMut_MSS': 'RAS Mutant Frontline',
    'TCGA_Resectable': 'Resectable (Neo/Adjuvant)',
    'Tempus_RASMut_MSS_3Lplus': 'RAS Mutant Refractory',
    'Tempus_MSS_3Lplus': 'Chemorefractory 3L+',
    'Tempus_RASMut_MSS_1L2L': 'RAS Mutant Frontline',
}

# Color schemes
COHORT_COLORS = {
    # TCGA tumor cohorts
    'TCGA_RASMut_MSS': '#E74C3C',
    'TCGA_RASWT_MSS': '#2ECC71',
    'TCGA_Resectable': '#3498DB',
    'TCGA_MSS_All': '#9B59B6',
    'TCGA_MSIH': '#F39C12',
    'TCGA_Tumor': '#E74C3C',
    'TCGA_Adjacent': '#7F8C8D',
    'GTEx_Colon': '#1ABC9C',
    'CCLE_CRC': '#8B4513',
    # Tempus cohorts
    'Tempus_RASMut_MSS_1L2L': '#C0392B',
    'Tempus_RASMut_MSS_3Lplus': '#922B21',
    'Tempus_RASWT_MSS_1L2L': '#27AE60',
    'Tempus_RASWT_MSS_3Lplus': '#1E8449',
    'Tempus_MSS_1L2L': '#5DADE2',
    'Tempus_MSS_3Lplus': '#2874A6',
    'Tempus_CPI_Naive': '#85929E',
    'Tempus_CPI_Treated': '#566573',
}

COHORT_LABELS = {
    # TCGA
    'TCGA_RASMut_MSS': 'RAS-mut MSS\n(TCGA)',
    'TCGA_RASWT_MSS': 'RAS-WT MSS\n(TCGA)',
    'TCGA_Resectable': 'Resectable\n(TCGA)',
    'TCGA_MSS_All': 'All MSS\n(TCGA)',
    'TCGA_MSIH': 'MSI-H\n(TCGA)',
    'TCGA_Tumor': 'CRC Tumor\n(TCGA)',
    'TCGA_Adjacent': 'Adjacent\nNormal',
    'GTEx_Colon': 'Normal\nColon\n(GTEx)',
    'CCLE_CRC': 'Cell Lines\n(CCLE)',
    # Tempus (simplified labels without "Tempus" prefix)
    'Tempus_RASMut_MSS_1L2L': 'RAS-mut\n1L-2L',
    'Tempus_RASMut_MSS_3Lplus': 'RAS-mut\n3L+',
    'Tempus_RASWT_MSS_1L2L': 'RAS-WT\n1L-2L',
    'Tempus_RASWT_MSS_3Lplus': 'RAS-WT\n3L+',
    'Tempus_MSS_1L2L': 'MSS\n1L-2L',
    'Tempus_MSS_3Lplus': 'MSS\n3L+',
}

CMS_COLORS = {
    'CMS1': '#E69F00',
    'CMS2': '#56B4E9',
    'CMS3': '#009E73',
    'CMS4': '#CC79A7',
    'Indeterminate': '#999999'
}

# Plot settings
plt.rcParams['figure.figsize'] = (16, 10)
plt.rcParams['figure.dpi'] = 150
plt.rcParams['font.size'] = 10
sns.set_style('whitegrid')


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def convert_legacy_cohort_name(name):
    """Convert legacy cohort name to unified naming."""
    return LEGACY_COHORT_MAP.get(name, name)


def convert_tempus_group_name(name):
    """Convert Tempus group name to unified naming."""
    return TEMPUS_GROUP_MAP.get(name, name)


def truncate_tcga_id(sample_id, length=15):
    """Truncate TCGA sample ID to standard length."""
    if isinstance(sample_id, str) and sample_id.startswith('TCGA'):
        return sample_id[:length]
    return sample_id


def draw_boxplot_from_summary(ax, data_df, x_col, colors, x_labels=None):
    """
    Draw boxplot-style visualization from summary statistics.

    Args:
        ax: matplotlib axes
        data_df: DataFrame with columns: group_name, mean, median, sd, q25, q75
        x_col: column name for x-axis grouping
        colors: list of colors for each box
        x_labels: optional custom x-axis labels

    The Tempus summary data contains q25, median, q75 which allows us to draw
    proper box plots. Whiskers are estimated using IQR * 1.5.
    """
    box_stats = []
    positions = []

    for i, (_, row) in enumerate(data_df.iterrows()):
        median = row.get('median', row.get('mean', 0))
        q25 = row.get('q25', median - row.get('sd', 0) * 0.675)  # Fallback to ~IQR estimate
        q75 = row.get('q75', median + row.get('sd', 0) * 0.675)
        iqr = q75 - q25

        # Whiskers: typically 1.5 * IQR from quartiles, but cap at reasonable range
        whislo = max(0, q25 - 1.5 * iqr)  # Lower whisker (cap at 0 for expression)
        whishi = q75 + 1.5 * iqr  # Upper whisker

        # If we have SD, use it to estimate whisker range more accurately
        if 'sd' in row and pd.notna(row['sd']):
            mean = row.get('mean', median)
            whislo = max(0, mean - 1.5 * row['sd'])
            whishi = mean + 1.5 * row['sd']

        box_stats.append({
            'med': median,
            'q1': q25,
            'q3': q75,
            'whislo': whislo,
            'whishi': whishi,
            'fliers': []  # No outliers from summary data
        })
        positions.append(i)

    if box_stats:
        # Draw boxplots
        bp = ax.bxp(box_stats, positions=positions, patch_artist=True,
                    widths=0.6, showfliers=False)

        # Apply colors
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
            patch.set_edgecolor('black')

        # Style median lines
        for median_line in bp['medians']:
            median_line.set_color('black')
            median_line.set_linewidth(1.5)

        # Set x-axis labels
        if x_labels:
            ax.set_xticks(positions)
            ax.set_xticklabels(x_labels)
        else:
            ax.set_xticks(positions)
            ax.set_xticklabels(data_df[x_col].tolist())

    return ax


# =============================================================================
# S3 DATA LOADING
# =============================================================================

def download_s3_file(s3_path, local_path, quiet=False):
    """Download file from S3 if not already cached using boto3."""
    if os.path.exists(local_path):
        if not quiet:
            print(f"  Using cached: {os.path.basename(local_path)}")
        return local_path

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    if not quiet:
        print(f"  Downloading: {os.path.basename(s3_path)}")

    bucket, key = parse_s3_uri(s3_path)
    try:
        get_s3_client().download_file(bucket, key, local_path)
    except ClientError as e:
        raise RuntimeError(f"Failed to download {s3_path}: {e}")

    return local_path


def stream_s3_file(s3_path):
    """Stream file directly from S3 without downloading (for read-only operations)."""
    fs = get_s3_filesystem()
    bucket, key = parse_s3_uri(s3_path)
    return fs.open(f"{bucket}/{key}", 'rb')


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


def load_cohort_assignments(cohort_path):
    """Load cohort assignments from CSV with automatic name conversion.

    Auto-downloads from S3 if not found locally.
    """
    if not os.path.exists(cohort_path):
        print(f"  Cohort file not found locally, downloading from S3...")
        try:
            download_s3_file(COHORT_S3_PATH, cohort_path)
        except Exception as e:
            print(f"  Warning: Could not download cohort file: {e}")
            return None

    df = pd.read_csv(cohort_path)
    print(f"  Loaded cohort assignments: {len(df)} samples")
    # Convert legacy names
    for col in df.columns:
        if 'cohort' in col.lower():
            df[col] = df[col].apply(convert_legacy_cohort_name)
    return df


def load_cms_predictions(cms_path):
    """Load CMS predictions from CSV.

    Auto-downloads from S3 if not found locally.
    """
    if not os.path.exists(cms_path):
        print(f"  CMS file not found locally, downloading from S3...")
        try:
            download_s3_file(CMS_S3_PATH, cms_path)
        except Exception as e:
            print(f"  Warning: Could not download CMS file: {e}")
            return None

    df = pd.read_csv(cms_path)
    print(f"  Loaded CMS predictions: {len(df)} samples")
    return df


def load_adjacent_normal_samples(adj_path):
    """Load TCGA adjacent normal sample IDs.

    Auto-downloads from S3 if not found locally.
    """
    if not os.path.exists(adj_path):
        print(f"  Adjacent normal file not found locally, downloading from S3...")
        try:
            download_s3_file(ADJ_NORMAL_S3_PATH, adj_path)
        except Exception as e:
            print(f"  Warning: Could not download adjacent normal file: {e}")
            return []

    df = pd.read_csv(adj_path, sep='\t')
    samples = df['Sample_ID'].unique().tolist()
    print(f"  Loaded adjacent normal samples: {len(samples)} samples")
    return samples


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

def load_tempus_summary(file_key, cache_dir):
    """Load a Tempus summary file from S3."""
    filename = TEMPUS_FILES.get(file_key)
    if not filename:
        return None

    s3_path = f"{TEMPUS_S3_BUCKET}/{filename}"
    local_path = f"{cache_dir}/tempus/{filename}"

    try:
        download_s3_file(s3_path, local_path, quiet=True)
        return pd.read_csv(local_path)
    except Exception as e:
        print(f"  Warning: Could not load Tempus {file_key}: {e}")
        return None


def load_all_tempus_data(cache_dir):
    """Load all Tempus summary files."""
    print("\nLoading Tempus data...")
    tempus_data = {}
    for key in TEMPUS_FILES:
        df = load_tempus_summary(key, cache_dir)
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
# TCGA SAMPLE FILTERING
# =============================================================================

def get_tcga_crc_samples(metadata):
    """Get TCGA COAD/READ samples."""
    if 'project_ids' in metadata.columns:
        mask = metadata['project_ids'].str.contains('TCGA_COAD|TCGA_READ', na=False, case=False)
    elif 'project_id' in metadata.columns:
        mask = metadata['project_id'].str.contains('TCGA_COAD|TCGA_READ', na=False, case=False)
    else:
        return pd.DataFrame()
    return metadata[mask]


def get_tcga_crc_tumor_samples(metadata):
    """Get TCGA CRC primary tumor samples."""
    crc = get_tcga_crc_samples(metadata)
    if 'tumor_or_normal' in crc.columns:
        return crc[crc['tumor_or_normal'].str.contains('Tumor', case=False, na=False)]
    return crc


def get_gtex_colon_samples(metadata):
    """Get GTEx colon samples."""
    if 'tissue_gtex' in metadata.columns:
        return metadata[metadata['tissue_gtex'].str.lower().str.contains('colon', na=False)]
    elif 'tissue' in metadata.columns:
        return metadata[metadata['tissue'].str.lower().str.contains('colon', na=False)]
    return pd.DataFrame()


def get_ccle_crc_samples(metadata):
    """Get CCLE CRC cell lines."""
    if 'onco_tree_disease' in metadata.columns:
        return metadata[metadata['onco_tree_disease'].str.contains('colorectal', case=False, na=False)]
    return pd.DataFrame()


# =============================================================================
# MASTER DATAFRAME BUILDING (TCGA)
# =============================================================================

def build_tcga_master_dataframe(tcga_expr, gtex_expr, ccle_expr, tcga_meta, gtex_meta, ccle_meta,
                                 cohort_df, cms_df, adj_normal_samples):
    """Build master dataframe with all TCGA/GTEx/CCLE samples.

    Expression data comes in Omicsoft format with sample_index, gene_index, tpm columns.
    This function joins with metadata using sample_index to get sample_id and calculates
    log2(tpm + 1) for expression values.
    """
    all_data = []

    # Create sample_index to sample_id mappings
    tcga_sample_map = dict(zip(tcga_meta['sample_index'], tcga_meta['sample_id']))
    gtex_sample_map = dict(zip(gtex_meta['sample_index'], gtex_meta['sample_id']))
    ccle_sample_map = dict(zip(ccle_meta['sample_index'], ccle_meta['sample_id']))

    # Get CRC sample sets from metadata
    crc_meta = get_tcga_crc_samples(tcga_meta)
    crc_sample_indices = set(crc_meta['sample_index'].tolist())

    # Identify tumor vs adjacent normal in TCGA
    tumor_meta = get_tcga_crc_tumor_samples(tcga_meta)
    tumor_sample_indices = set(tumor_meta['sample_index'].tolist())

    # Adjacent normal sample indices (samples ending in -11)
    adj_normal_indices = set()
    for _, row in crc_meta.iterrows():
        sample_id = row['sample_id']
        if any(adj in sample_id for adj in ['-11', '-11A', '-11B']):
            adj_normal_indices.add(row['sample_index'])

    # Create cohort lookup from cohort_df
    cohort_lookup = {}
    if cohort_df is not None:
        for _, row in cohort_df.iterrows():
            sid = row.get('sample_id', '')
            sid_short = truncate_tcga_id(sid)
            cohort_lookup[sid_short] = row.to_dict()

    # Create CMS lookup
    cms_lookup = {}
    if cms_df is not None:
        for _, row in cms_df.iterrows():
            sid = str(row.get('sample', row.get('sample_id', '')))
            sid_short = truncate_tcga_id(sid)
            cms_lookup[sid_short] = row.get('CMS', row.get('prediction', 'Unknown'))

    # Process TCGA expression
    if not tcga_expr.empty:
        for _, row in tcga_expr.iterrows():
            sample_idx = row['sample_index']
            if sample_idx not in crc_sample_indices:
                continue

            sample_id = tcga_sample_map.get(sample_idx, '')
            sample_id_short = truncate_tcga_id(sample_id)

            # Calculate log2(tpm + 1) expression
            expr_value = np.log2(row['tpm'] + 1)

            # Determine if tumor or adjacent normal
            is_normal = sample_idx in adj_normal_indices or '-11' in sample_id

            if is_normal:
                all_data.append({
                    'sample_id': sample_id_short,
                    'expression': expr_value,
                    'data_source': 'TCGA',
                    'tissue_type': 'TCGA_Adjacent',
                    'cohort': 'TCGA_Adjacent',
                })
            elif sample_idx in tumor_sample_indices:
                record = {
                    'sample_id': sample_id_short,
                    'expression': expr_value,
                    'data_source': 'TCGA',
                    'tissue_type': 'TCGA_Tumor',
                    'cohort': 'TCGA_Tumor',
                }

                # Add cohort assignment from lookup
                # Priority order: specific cohorts first, then general ones
                COHORT_PRIORITY = ['TCGA_RASMut_MSS', 'TCGA_RASWT_MSS', 'TCGA_Resectable', 'TCGA_MSIH', 'TCGA_MSS_All']
                cohort_info = cohort_lookup.get(sample_id_short, {})

                # Check for cohorts in priority order
                for cohort_name in COHORT_PRIORITY:
                    # Check direct column name
                    if cohort_info.get(cohort_name) == True:
                        record['cohort'] = cohort_name
                        break
                    # Check legacy column name
                    legacy_name = NEW_TO_LEGACY_MAP.get(cohort_name)
                    if legacy_name and cohort_info.get(legacy_name) == True:
                        record['cohort'] = cohort_name
                        break

                # Add CMS prediction
                record['CMS'] = cms_lookup.get(sample_id_short, 'Unknown')

                all_data.append(record)

    # Process GTEx expression
    if not gtex_expr.empty:
        colon_meta = get_gtex_colon_samples(gtex_meta)
        colon_indices = set(colon_meta['sample_index'].tolist())

        for _, row in gtex_expr.iterrows():
            sample_idx = row['sample_index']
            if sample_idx not in colon_indices:
                continue

            sample_id = gtex_sample_map.get(sample_idx, f'GTEx_{sample_idx}')
            expr_value = np.log2(row['tpm'] + 1)

            all_data.append({
                'sample_id': sample_id,
                'expression': expr_value,
                'data_source': 'GTEx',
                'tissue_type': 'GTEx_Colon',
                'cohort': 'GTEx_Colon',
            })

    # Process CCLE expression
    if not ccle_expr.empty:
        crc_cell_meta = get_ccle_crc_samples(ccle_meta)
        crc_cell_indices = set(crc_cell_meta['sample_index'].tolist())

        for _, row in ccle_expr.iterrows():
            sample_idx = row['sample_index']
            if sample_idx not in crc_cell_indices:
                continue

            sample_id = ccle_sample_map.get(sample_idx, f'CCLE_{sample_idx}')
            expr_value = np.log2(row['tpm'] + 1)

            all_data.append({
                'sample_id': sample_id,
                'expression': expr_value,
                'data_source': 'CCLE',
                'tissue_type': 'CCLE_CRC',
                'cohort': 'CCLE_CRC',
            })

    return pd.DataFrame(all_data)


# =============================================================================
# STATISTICAL ANALYSIS
# =============================================================================

def calculate_cohort_statistics(master_df):
    """Calculate expression statistics by cohort."""
    stats = master_df.groupby('cohort')['expression'].agg([
        'count', 'mean', 'median', 'std', 'min', 'max',
        lambda x: x.quantile(0.25),
        lambda x: x.quantile(0.75)
    ])
    stats.columns = ['count', 'mean', 'median', 'std', 'min', 'max', 'q25', 'q75']
    return stats


def perform_pairwise_comparisons(master_df, tumor_cohorts, normal_groups):
    """Perform statistical comparisons between tumor cohorts and normal tissue."""
    results = []

    for tumor in tumor_cohorts:
        tumor_data = master_df[master_df['cohort'] == tumor]['expression']
        if len(tumor_data) < 3:
            continue

        for normal in normal_groups:
            normal_data = master_df[master_df['cohort'] == normal]['expression']
            if len(normal_data) < 3:
                continue

            # Mann-Whitney U test
            stat, pval = mannwhitneyu(tumor_data, normal_data, alternative='two-sided')

            # Log2 fold change
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
    if len(results_df) > 1:
        _, pvals_adj, _, _ = multipletests(results_df['p_value'], method='fdr_bh')
        results_df['p_adjusted'] = pvals_adj
    else:
        results_df['p_adjusted'] = results_df['p_value']

    results_df['significant'] = results_df['p_adjusted'] < 0.05

    return results_df


# =============================================================================
# iDAS ALIGNMENT ASSESSMENT
# =============================================================================

def assess_idas_alignment(gene_symbol, tcga_stats, tcga_comparisons, tempus_gene_data):
    """Comprehensive iDAS alignment assessment combining TCGA and Tempus."""
    assessment = {
        'gene': gene_symbol,
        'timestamp': datetime.now().isoformat(),
        'whitespace_alignment': {},
        'on_target_toxicity': {},
        'overall_alignment': 'Unknown',
        'recommendation': 'Unknown',
    }

    scores = []

    # 1. On-target toxicity assessment (TCGA)
    if tcga_comparisons is not None and not tcga_comparisons.empty:
        adj_comparison = tcga_comparisons[tcga_comparisons['Normal_Group'] == 'TCGA_Adjacent']
        if not adj_comparison.empty:
            best_fc = adj_comparison['Log2FC'].max()
            assessment['on_target_toxicity'] = {
                'tumor_vs_adjacent_log2FC': best_fc,
                'risk_level': 'Low' if best_fc > 1 else 'Medium' if best_fc > 0.5 else 'High',
            }
            # Score: higher FC = lower toxicity risk = better
            tox_score = min(best_fc / 2, 1.0) if best_fc > 0 else 0
            scores.append(('on_target_toxicity', tox_score))

    # 2. RAS mutant frontline (TCGA + Tempus)
    ras_mut_expr = None
    if tcga_stats is not None and 'TCGA_RASMut_MSS' in tcga_stats.index:
        ras_mut_expr = tcga_stats.loc['TCGA_RASMut_MSS', 'median']

    tempus_ras_1l2l = None
    if 'idas_groups_wide' in tempus_gene_data:
        df = tempus_gene_data['idas_groups_wide']
        if 'mean_MSS_RASMut_1L2L' in df.columns:
            tempus_ras_1l2l = df.iloc[0]['mean_MSS_RASMut_1L2L']

    if ras_mut_expr is not None or tempus_ras_1l2l is not None:
        expr = tempus_ras_1l2l if tempus_ras_1l2l is not None else ras_mut_expr
        alignment = 'Strong' if expr > 4 else 'Moderate' if expr > 2 else 'Weak'
        # Determine source based on available data
        if tempus_ras_1l2l is not None and ras_mut_expr is not None:
            source = 'TCGA+Tempus'
        elif tempus_ras_1l2l is not None:
            source = 'Tempus'
        else:
            source = 'TCGA'
        assessment['whitespace_alignment']['ras_mutant_frontline'] = {
            'tcga_expression': ras_mut_expr,
            'tempus_expression': tempus_ras_1l2l,
            'alignment': alignment,
            'source': source,
        }
        score = 1.0 if alignment == 'Strong' else 0.6 if alignment == 'Moderate' else 0.2
        scores.append(('ras_mutant_frontline', score))

    # 3. RAS mutant refractory / 3L+ (Tempus)
    if 'key_target_3lplus' in tempus_gene_data:
        df = tempus_gene_data['key_target_3lplus']
        if not df.empty:
            row = df.iloc[0]
            expr = row.get('mean', 0)
            fc_vs_all = row.get('log2FC_vs_MSS_all', 0)
            alignment = 'Strong' if expr > 4 and fc_vs_all > 0.3 else 'Moderate' if expr > 2 else 'Weak'
            assessment['whitespace_alignment']['ras_mutant_refractory'] = {
                'expression_3lplus': expr,
                'log2FC_vs_MSS_all': fc_vs_all,
                'n_samples': row.get('n_samples', 0),
                'alignment': alignment,
                'source': 'Tempus',
            }
            score = 1.0 if alignment == 'Strong' else 0.6 if alignment == 'Moderate' else 0.2
            scores.append(('ras_mutant_refractory', score))

    # 4. Chemorefractory 3L+ (Tempus)
    if 'lot_mss' in tempus_gene_data:
        df = tempus_gene_data['lot_mss']
        lot_3lplus = df[df['group_name'] == '3L+ Chemorefractory']
        if not lot_3lplus.empty:
            row = lot_3lplus.iloc[0]
            expr = row.get('mean', 0)
            fc_vs_early = row.get('log2FC_3Lplus_vs_early', 0)
            alignment = 'Strong' if expr > 4 else 'Moderate' if expr > 2 else 'Weak'
            assessment['whitespace_alignment']['chemorefractory_3lplus'] = {
                'expression': expr,
                'log2FC_vs_frontline': fc_vs_early,
                'n_samples': row.get('n_samples', 0),
                'alignment': alignment,
                'source': 'Tempus',
            }
            score = 1.0 if alignment == 'Strong' else 0.6 if alignment == 'Moderate' else 0.2
            scores.append(('chemorefractory_3lplus', score))

    # 5. Resectable (TCGA)
    if tcga_stats is not None and 'TCGA_Resectable' in tcga_stats.index:
        expr = tcga_stats.loc['TCGA_Resectable', 'median']
        alignment = 'Strong' if expr > 4 else 'Moderate' if expr > 2 else 'Weak'
        assessment['whitespace_alignment']['resectable'] = {
            'tcga_expression': expr,
            'alignment': alignment,
            'source': 'TCGA',
        }
        score = 1.0 if alignment == 'Strong' else 0.6 if alignment == 'Moderate' else 0.2
        scores.append(('resectable', score))

    # Calculate overall alignment
    if scores:
        avg_score = np.mean([s[1] for s in scores])
        if avg_score >= 0.7:
            assessment['overall_alignment'] = 'High'
            assessment['recommendation'] = 'PRIORITY - Strong iDAS alignment'
        elif avg_score >= 0.4:
            assessment['overall_alignment'] = 'Medium'
            assessment['recommendation'] = 'CONDITIONAL - Moderate alignment, review specifics'
        else:
            assessment['overall_alignment'] = 'Low'
            assessment['recommendation'] = 'DEPRIORITIZE - Limited iDAS alignment'

    # Check on-target toxicity
    if assessment.get('on_target_toxicity', {}).get('risk_level') == 'High':
        assessment['recommendation'] = 'CAUTION - High on-target toxicity risk'

    return assessment


def compute_subgroup_suitability(gene, tcga_stats, pairwise_df, idas_assessment, tempus_gene_data):
    """
    Compute subgroup-specific suitability scores for CRC target evaluation.

    Integrates:
    - Molecular subgroups (RAS Mutant MSS, RAS WT MSS, MSI-H, Resectable - tumor enrichment)
    - RAS mutation status (RAS Mutant vs RAS WT from Tempus)
    - iDAS whitespace alignment (RAS Mut Refractory, Chemorefractory 3L+, Resectable)

    Returns:
        dict: Subgroup suitability analysis with scores and recommendations
    """
    suitability = {
        'gene': gene,
        'molecular_subgroup': {},
        'ras_status': {},
        'idas_whitespace': {},
        'summary': []
    }

    # ==========================================================================
    # 1. MOLECULAR SUBGROUP SUITABILITY (Tumor vs Adjacent enrichment)
    # ==========================================================================
    if pairwise_df is not None and len(pairwise_df) > 0:
        subgroup_map = {
            'TCGA_RASMut_MSS': 'RAS Mutant MSS',
            'TCGA_RASWT_MSS': 'RAS WT MSS',
            'TCGA_MSIH': 'MSI-H',
            'TCGA_Resectable': 'Resectable',
            'TCGA_MSS_All': 'All MSS',
        }

        for cohort, label in subgroup_map.items():
            comparison = pairwise_df[
                (pairwise_df['Tumor_Cohort'] == cohort) &
                (pairwise_df['Normal_Group'] == 'TCGA_Adjacent')
            ]
            if len(comparison) > 0:
                log2fc = comparison['Log2FC'].values[0]
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

                suitability['molecular_subgroup'][label] = {
                    'log2fc_vs_adjacent': round(log2fc, 3),
                    'linear_fc': round(linear_fc, 2),
                    'suitability_score': score,
                    'recommendation': recommendation,
                    'rationale': rationale
                }

                suitability['summary'].append({
                    'subgroup': f'Molecular: {label}',
                    'category': 'molecular_subgroup',
                    'key_metric': f'{linear_fc:.1f}x vs adjacent',
                    'score': score,
                    'recommendation': recommendation
                })

    # ==========================================================================
    # 2. RAS MUTATION STATUS (Tempus RWD - IO-experienced population)
    # ==========================================================================
    # Use Tempus ras_status_mss for RAS Mutant vs RAS WT comparison
    tempus_ras_log2fc = None
    tempus_ras_fc = None
    if 'ras_status_mss' in tempus_gene_data:
        ras_data = tempus_gene_data['ras_status_mss']
        if 'group_name' in ras_data.columns and 'mean' in ras_data.columns:
            mut_row = ras_data[ras_data['group_name'] == 'RAS Mutant']
            wt_row = ras_data[ras_data['group_name'] == 'RAS WT']
            if len(mut_row) > 0 and len(wt_row) > 0:
                mut_mean = mut_row['mean'].values[0]
                wt_mean = wt_row['mean'].values[0]
                mut_n = int(mut_row['n_samples'].values[0]) if 'n_samples' in mut_row.columns else 0
                wt_n = int(wt_row['n_samples'].values[0]) if 'n_samples' in wt_row.columns else 0
                tempus_ras_log2fc = mut_mean - wt_mean
                tempus_ras_fc = 2 ** tempus_ras_log2fc  # Convert to fold change

                # Interpret RAS mutation status effect
                if tempus_ras_log2fc > 0.5:
                    score = 5
                    recommendation = 'PRIORITY'
                    rationale = f'Upregulated in RAS-mutant ({tempus_ras_fc:.1f}x vs WT, Tempus)'
                elif tempus_ras_log2fc > 0:
                    score = 4
                    recommendation = 'GO'
                    rationale = f'Slightly higher in RAS-mutant ({tempus_ras_fc:.1f}x vs WT, Tempus)'
                elif tempus_ras_log2fc > -0.5:
                    score = 3
                    recommendation = 'NEUTRAL'
                    rationale = f'Similar expression regardless of RAS status ({tempus_ras_fc:.1f}x vs WT, Tempus)'
                elif tempus_ras_log2fc > -1.0:
                    score = 2
                    recommendation = 'CAUTION'
                    rationale = f'Lower in RAS-mutant ({tempus_ras_fc:.1f}x vs WT, Tempus)'
                else:
                    score = 1
                    recommendation = 'EXCLUDE'
                    rationale = f'Significantly lower in RAS-mutant ({tempus_ras_fc:.1f}x vs WT, Tempus)'

                suitability['ras_status']['RAS_mut'] = {
                    'log2fc_vs_wt': round(tempus_ras_log2fc, 3),
                    'fold_change': round(tempus_ras_fc, 2),
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
                    'subgroup': 'RAS Status: RAS+ (Tempus)',
                    'category': 'ras_status',
                    'key_metric': f'{tempus_ras_fc:.1f}x vs WT (Tempus)',
                    'score': score,
                    'recommendation': recommendation
                })

    # ==========================================================================
    # 3. iDAS WHITESPACE SUITABILITY
    # ==========================================================================
    # Based on expression level + RAS status + toxicity risk
    whitespace_info = idas_assessment.get('whitespace_alignment', {})
    toxicity = idas_assessment.get('on_target_toxicity', {})
    tox_risk = toxicity.get('risk_level', 'Unknown')
    tox_log2fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)

    # Map iDAS whitespaces - for CRC, RAS mutant whitespaces use RAS status from Tempus
    whitespace_ras_map = {
        'ras_mutant_refractory': True,    # RAS Mutant 3L+ - apply RAS penalty if lower in mutant
        'ras_mutant_frontline': True,     # RAS Mutant 1L-2L - apply RAS penalty if lower in mutant
        'chemorefractory_3lplus': False,  # All MSS 3L+ - no RAS-specific penalty
        'resectable': False,              # Early stage - no RAS-specific penalty
    }

    for ws_key, ws_data in whitespace_info.items():
        # Get expression from available fields
        expression = ws_data.get('expression_3lplus') or ws_data.get('expression') or \
                     ws_data.get('tempus_expression') or ws_data.get('tcga_expression') or 0
        alignment = ws_data.get('alignment', 'Unknown')
        n_samples = ws_data.get('n_samples', 0)

        # Label mapping
        label_map = {
            'ras_mutant_refractory': 'RAS Mutant Refractory (3L+)',
            'ras_mutant_frontline': 'RAS Mutant Frontline',
            'chemorefractory_3lplus': 'Chemorefractory 3L+',
            'resectable': 'Resectable (Neo/Adjuvant)',
        }
        label = label_map.get(ws_key, ws_key)

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

        # Apply RAS mutation penalty for RAS-specific whitespaces (from Tempus)
        mutation_penalty = 0
        mutation_context = ''
        applies_ras_penalty = whitespace_ras_map.get(ws_key, False)

        if applies_ras_penalty and tempus_ras_fc is not None:
            if tempus_ras_log2fc < -0.5:
                mutation_penalty = 2
                mutation_context = f', RAS_LOWER ({tempus_ras_fc:.1f}x vs WT, Tempus)'
            elif tempus_ras_log2fc < 0:
                mutation_penalty = 1
                mutation_context = f', ras_lower ({tempus_ras_fc:.1f}x vs WT, Tempus)'
            elif tempus_ras_log2fc > 0.5:
                mutation_penalty = -1
                mutation_context = f', ras_higher ({tempus_ras_fc:.1f}x vs WT, Tempus)'

        # Adjust for toxicity risk
        if tox_risk == 'High':
            tox_penalty = 2
        elif tox_risk == 'Medium':
            tox_penalty = 1
        else:
            tox_penalty = 0

        # Calculate final adjusted score
        adjusted_score = max(1, base_score - tox_penalty - mutation_penalty)

        # Determine recommendation
        if mutation_penalty >= 2:
            recommendation = 'CAUTION'
            rationale = f'Expression={expression:.2f}, but target LOWER in RAS-mutant{mutation_context}'
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
            'expression': round(expression, 3) if expression else 0,
            'n_samples': int(n_samples) if n_samples else 0,
            'alignment': alignment,
            'toxicity_risk': tox_risk,
            'ras_log2fc': round(tempus_ras_log2fc, 3) if tempus_ras_log2fc is not None and applies_ras_penalty else None,
            'ras_fold_change': round(tempus_ras_fc, 2) if tempus_ras_fc is not None and applies_ras_penalty else None,
            'ras_data_source': 'Tempus' if tempus_ras_log2fc is not None and applies_ras_penalty else None,
            'base_score': base_score,
            'tox_penalty': tox_penalty,
            'mutation_penalty': mutation_penalty,
            'adjusted_score': adjusted_score,
            'recommendation': recommendation,
            'rationale': rationale
        }

        # Build key metric string
        key_metric = f'expr={expression:.2f}' if expression else 'expr=N/A'
        if applies_ras_penalty and tempus_ras_fc is not None:
            key_metric += f', {tempus_ras_fc:.1f}x vs WT (Tempus)'
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
    suitability['summary'] = sorted(suitability['summary'], key=lambda x: -x['score'])

    priority_subgroups = [s for s in suitability['summary'] if s['recommendation'] == 'PRIORITY']
    go_subgroups = [s for s in suitability['summary'] if s['recommendation'] == 'GO']
    exclude_subgroups = [s for s in suitability['summary'] if s['recommendation'] in ['EXCLUDE', 'CAUTION']]

    suitability['best_subgroups'] = {
        'priority': [s['subgroup'] for s in priority_subgroups],
        'go': [s['subgroup'] for s in go_subgroups],
        'caution_exclude': [s['subgroup'] for s in exclude_subgroups],
    }

    return suitability


def save_subgroup_suitability_figure(gene, suitability, output_dir):
    """Save subgroup suitability summary figure."""
    summary = suitability.get('summary', [])
    if not summary:
        return

    fig, ax = plt.subplots(figsize=(12, max(6, len(summary) * 0.5)))

    # Prepare data
    subgroups = [s['subgroup'] for s in summary]
    scores = [s['score'] for s in summary]
    recommendations = [s['recommendation'] for s in summary]

    # Color mapping
    color_map = {
        'PRIORITY': '#27AE60',
        'GO': '#2ECC71',
        'CONDITIONAL': '#F39C12',
        'NEUTRAL': '#85929E',
        'CAUTION': '#E74C3C',
        'EXCLUDE': '#922B21',
    }
    colors = [color_map.get(r, '#888888') for r in recommendations]

    # Create horizontal bar chart
    y_pos = range(len(subgroups))
    bars = ax.barh(y_pos, scores, color=colors, edgecolor='black', alpha=0.8)

    # Add score labels
    for i, (bar, score, rec) in enumerate(zip(bars, scores, recommendations)):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                f'{score}/5 ({rec})', va='center', fontsize=9)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(subgroups, fontsize=10)
    ax.set_xlabel('Suitability Score (1-5)', fontsize=12)
    ax.set_xlim(0, 6.5)
    ax.set_title(f'{gene} - Subgroup Suitability Analysis\n(Molecular, RAS Status, iDAS Whitespaces)',
                 fontweight='bold', fontsize=14)

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#27AE60', label='PRIORITY'),
        Patch(facecolor='#2ECC71', label='GO'),
        Patch(facecolor='#F39C12', label='CONDITIONAL'),
        Patch(facecolor='#85929E', label='NEUTRAL'),
        Patch(facecolor='#E74C3C', label='CAUTION'),
    ]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=9)

    # Add vertical lines for score thresholds
    ax.axvline(x=4, color='green', linestyle='--', alpha=0.3)
    ax.axvline(x=3, color='orange', linestyle='--', alpha=0.3)

    plt.tight_layout()

    figures_dir = os.path.join(output_dir, 'figures')
    os.makedirs(figures_dir, exist_ok=True)
    fig_path = os.path.join(figures_dir, get_output_filename(gene, 'suitability', 'png'))
    plt.savefig(fig_path, dpi=150, facecolor='white', bbox_inches='tight')
    plt.close()

    return fig_path


# =============================================================================
# VISUALIZATION
# =============================================================================

def create_comprehensive_figure(gene_symbol, master_df, tempus_gene_data, assessment, output_dir):
    """Create comprehensive multi-panel figure."""
    fig = plt.figure(figsize=(20, 16))
    fig.suptitle(f'{gene_symbol} Comprehensive CRC Target Analysis\n'
                 f'iDAS Alignment: {assessment["overall_alignment"]} | '
                 f'{assessment["recommendation"]}',
                 fontsize=16, fontweight='bold', y=0.98)

    # Create grid
    gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.3)

    # Panel A: TCGA Cohort Expression (Tumor vs Normal)
    ax1 = fig.add_subplot(gs[0, 0])
    if not master_df.empty:
        plot_order = ['TCGA_RASMut_MSS', 'TCGA_RASWT_MSS', 'TCGA_Resectable',
                      'TCGA_MSS_All', 'TCGA_MSIH', 'TCGA_Adjacent', 'GTEx_Colon']
        plot_order = [c for c in plot_order if c in master_df['cohort'].unique()]

        if plot_order:
            plot_df = master_df[master_df['cohort'].isin(plot_order)]
            colors = [COHORT_COLORS.get(c, '#888888') for c in plot_order]

            sns.boxplot(data=plot_df, x='cohort', y='expression', order=plot_order,
                       palette=colors, ax=ax1, width=0.6)

            ax1.set_xticklabels([COHORT_LABELS.get(c, c) for c in plot_order],
                               rotation=45, ha='right', fontsize=8)
            ax1.axhline(y=master_df[master_df['cohort'] == 'TCGA_Adjacent']['expression'].median(),
                       color='gray', linestyle='--', alpha=0.5, label='Adjacent Normal')

    ax1.set_xlabel('')
    ax1.set_ylabel('Expression (log2)')
    ax1.set_title('A. TCGA Expression by Cohort\n(On-Target Toxicity Reference)', fontweight='bold')

    # Panel B: Tumor vs Normal Fold Change
    ax2 = fig.add_subplot(gs[0, 1])
    toxicity = assessment.get('on_target_toxicity', {})
    if toxicity:
        fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)
        risk = toxicity.get('risk_level', 'Unknown')
        color = '#2ECC71' if risk == 'Low' else '#F39C12' if risk == 'Medium' else '#E74C3C'

        ax2.barh(['Tumor vs\nAdjacent Normal'], [fc], color=color, height=0.5)
        ax2.axvline(x=0, color='black', linestyle='-', linewidth=0.5)
        ax2.axvline(x=1, color='green', linestyle='--', alpha=0.5, label='Low risk threshold')
        ax2.axvline(x=0.5, color='orange', linestyle='--', alpha=0.5, label='Medium risk threshold')
        ax2.set_xlabel('log2 Fold Change')
        ax2.set_xlim(-2, max(fc + 1, 3))
        ax2.legend(loc='lower right', fontsize=8)

        ax2.text(fc + 0.1, 0, f'{fc:.2f}\n({risk} Risk)', va='center', fontsize=10, fontweight='bold')

    ax2.set_title('B. On-Target Toxicity Assessment\n(Tumor vs Adjacent Normal)', fontweight='bold')

    # Panel C: Tempus Line of Therapy (Boxplot from summary stats)
    ax3 = fig.add_subplot(gs[0, 2])
    if 'lot_mss' in tempus_gene_data:
        df = tempus_gene_data['lot_mss'].copy()
        if 'group_name' in df.columns:
            lot_order = ['1L-2L', '3L+ Chemorefractory']
            lot_plot = df[df['group_name'].isin(lot_order)].copy()
            if len(lot_plot) > 0:
                lot_plot['group_name'] = pd.Categorical(lot_plot['group_name'], categories=lot_order, ordered=True)
                lot_plot = lot_plot.sort_values('group_name')
                colors = ['#5DADE2', '#2874A6']
                draw_boxplot_from_summary(ax3, lot_plot, 'group_name', colors,
                                         x_labels=['Frontline\n(1L-2L)', 'Chemorefractory\n(3L+)'])
                ax3.set_ylabel('Expression (log2 TPM)')

                # Add sample sizes
                for i, (_, row) in enumerate(lot_plot.iterrows()):
                    n = int(row['n_samples']) if 'n_samples' in row else 0
                    ax3.annotate(f"n={n:,}", (i, row['q75'] + 0.3), ha='center', fontsize=8)

    ax3.set_title('C. Expression by Line of Therapy\n(Tempus RWD, MSS)', fontweight='bold')

    # Panel D: Tempus iDAS Cohorts (Boxplot from summary stats)
    ax4 = fig.add_subplot(gs[1, 0])
    if 'idas_groups' in tempus_gene_data:
        df = tempus_gene_data['idas_groups'].copy()
        if 'group_name' in df.columns and len(df) > 0:
            # Sort cohorts logically: group by line of therapy (1L-2L together, 3L+ together)
            idas_order = ['MSS_RASMut_1L2L', 'MSS_RASWT_1L2L', 'MSS_RASMut_3L+', 'MSS_RASWT_3L+']
            df = df[df['group_name'].isin(idas_order)].copy()
            df['group_name'] = pd.Categorical(df['group_name'], categories=idas_order, ordered=True)
            df = df.sort_values('group_name')

            # Colors alternating: RAS-mut (red), RAS-WT (green) for each line of therapy
            colors = ['#C0392B', '#27AE60', '#922B21', '#1E8449']
            x_labels = ['RAS-mut\n1L-2L', 'RAS-WT\n1L-2L', 'RAS-mut\n3L+', 'RAS-WT\n3L+']
            draw_boxplot_from_summary(ax4, df, 'group_name', colors, x_labels=x_labels)
            ax4.tick_params(axis='x', labelrotation=0, labelsize=9)
            ax4.set_ylabel('Expression (log2 TPM)')

            # Add sample sizes
            for i, (_, row) in enumerate(df.iterrows()):
                n = int(row['n_samples']) if 'n_samples' in row else 0
                ax4.annotate(f"n={n:,}", (i, row['q75'] + 0.2), ha='center', fontsize=7)

            # Compute and display p-values for RAS mut vs WT comparisons using Welch's t-test
            df_indexed = df.set_index('group_name')

            # P-value for 1L-2L: RAS-mut vs RAS-WT
            if 'MSS_RASMut_1L2L' in df_indexed.index and 'MSS_RASWT_1L2L' in df_indexed.index:
                mut_1l = df_indexed.loc['MSS_RASMut_1L2L']
                wt_1l = df_indexed.loc['MSS_RASWT_1L2L']
                se_diff = np.sqrt(mut_1l['sd']**2 / mut_1l['n_samples'] + wt_1l['sd']**2 / wt_1l['n_samples'])
                if se_diff > 0:
                    t_stat = (mut_1l['mean'] - wt_1l['mean']) / se_diff
                    # Welch-Satterthwaite df approximation
                    num = (mut_1l['sd']**2 / mut_1l['n_samples'] + wt_1l['sd']**2 / wt_1l['n_samples'])**2
                    denom = (mut_1l['sd']**4 / (mut_1l['n_samples']**2 * (mut_1l['n_samples']-1)) +
                            wt_1l['sd']**4 / (wt_1l['n_samples']**2 * (wt_1l['n_samples']-1)))
                    df_welch = num / denom if denom > 0 else 1
                    p_val_1l = 2 * stats.t.sf(abs(t_stat), df_welch)
                    p_str = f"p={p_val_1l:.2e}" if p_val_1l < 0.01 else f"p={p_val_1l:.3f}"
                    max_y_1l = max(mut_1l['q75'], wt_1l['q75'])
                    ax4.plot([0, 1], [max_y_1l + 0.4] * 2, 'k-', linewidth=0.8)
                    ax4.annotate(p_str, xy=(0.5, max_y_1l + 0.5), ha='center', fontsize=7, style='italic')

            # P-value for 3L+: RAS-mut vs RAS-WT
            if 'MSS_RASMut_3L+' in df_indexed.index and 'MSS_RASWT_3L+' in df_indexed.index:
                mut_3l = df_indexed.loc['MSS_RASMut_3L+']
                wt_3l = df_indexed.loc['MSS_RASWT_3L+']
                se_diff = np.sqrt(mut_3l['sd']**2 / mut_3l['n_samples'] + wt_3l['sd']**2 / wt_3l['n_samples'])
                if se_diff > 0:
                    t_stat = (mut_3l['mean'] - wt_3l['mean']) / se_diff
                    num = (mut_3l['sd']**2 / mut_3l['n_samples'] + wt_3l['sd']**2 / wt_3l['n_samples'])**2
                    denom = (mut_3l['sd']**4 / (mut_3l['n_samples']**2 * (mut_3l['n_samples']-1)) +
                            wt_3l['sd']**4 / (wt_3l['n_samples']**2 * (wt_3l['n_samples']-1)))
                    df_welch = num / denom if denom > 0 else 1
                    p_val_3l = 2 * stats.t.sf(abs(t_stat), df_welch)
                    p_str = f"p={p_val_3l:.2e}" if p_val_3l < 0.01 else f"p={p_val_3l:.3f}"
                    max_y_3l = max(mut_3l['q75'], wt_3l['q75'])
                    ax4.plot([2, 3], [max_y_3l + 0.4] * 2, 'k-', linewidth=0.8)
                    ax4.annotate(p_str, xy=(2.5, max_y_3l + 0.5), ha='center', fontsize=7, style='italic')

    ax4.set_title('D. iDAS-Aligned Cohorts\n(Tempus RWD, MSS)', fontweight='bold')

    # Panel E: RAS Status Comparison (Boxplot from summary stats)
    ax5 = fig.add_subplot(gs[1, 1])
    if 'ras_status_mss' in tempus_gene_data:
        df = tempus_gene_data['ras_status_mss'].copy()
        if 'group_name' in df.columns:
            ras_order = ['RAS Mutant', 'RAS WT']
            ras_plot = df[df['group_name'].isin(ras_order)].copy()
            if len(ras_plot) > 0:
                ras_plot['group_name'] = pd.Categorical(ras_plot['group_name'], categories=ras_order, ordered=True)
                ras_plot = ras_plot.sort_values('group_name')
                colors = ['#C0392B', '#27AE60']
                draw_boxplot_from_summary(ax5, ras_plot, 'group_name', colors,
                                         x_labels=['RAS Mutant', 'RAS Wild-Type'])
                ax5.set_ylabel('Expression (log2 TPM)')

                # Add sample sizes
                for i, (_, row) in enumerate(ras_plot.iterrows()):
                    n = int(row['n_samples']) if 'n_samples' in row else 0
                    ax5.annotate(f"n={n:,}", (i, row['q75'] + 0.3), ha='center', fontsize=9)

    ax5.set_title('E. Expression by RAS Status\n(Tempus RWD, MSS)', fontweight='bold')

    # Panel F: CMS Subtypes (Boxplot for TCGA, summary boxplot for Tempus)
    ax6 = fig.add_subplot(gs[1, 2])
    cms_source = None

    # Try TCGA CMS first (individual samples - use real boxplot)
    if not master_df.empty and 'CMS' in master_df.columns:
        cms_order = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
        cms_df = master_df[master_df['CMS'].isin(cms_order)].copy()
        if len(cms_df) > 0:
            colors = [CMS_COLORS.get(c, '#888888') for c in cms_order]
            sns.boxplot(data=cms_df, x='CMS', y='expression', order=cms_order,
                       palette=colors, ax=ax6, width=0.6)
            ax6.set_ylabel('Expression (log2 TPM)')
            cms_source = 'TCGA'

    # Fallback to Tempus CMS (summary stats - use boxplot from summary)
    if cms_source is None and 'cms' in tempus_gene_data:
        df = tempus_gene_data['cms'].copy()
        group_col = 'group' if 'group' in df.columns else 'group_name'
        cms_order = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
        cms_plot = df[df[group_col].isin(cms_order)].copy()
        if len(cms_plot) > 0:
            cms_plot['group_name'] = cms_plot[group_col]
            cms_plot['group_name'] = pd.Categorical(cms_plot['group_name'], categories=cms_order, ordered=True)
            cms_plot = cms_plot.sort_values('group_name')
            colors = [CMS_COLORS.get(c, '#888888') for c in cms_order if c in cms_plot['group_name'].values]
            draw_boxplot_from_summary(ax6, cms_plot, 'group_name', colors)
            ax6.set_ylabel('Expression (log2 TPM)')
            cms_source = 'Tempus'

    if cms_source:
        ax6.set_title(f'F. CMS Subtype Expression\n({cms_source})', fontweight='bold')
    else:
        ax6.set_title('F. CMS Subtype Expression\n(No data)', fontweight='bold')
        ax6.text(0.5, 0.5, 'No CMS data available', ha='center', va='center', transform=ax6.transAxes)

    # Panel G: iDAS Alignment Summary
    ax7 = fig.add_subplot(gs[2, 0:2])
    ax7.axis('off')

    # Create summary table
    whitespace = assessment.get('whitespace_alignment', {})
    table_data = []
    for ws_name, ws_data in whitespace.items():
        alignment = ws_data.get('alignment', 'Unknown')
        color = '#2ECC71' if alignment == 'Strong' else '#F39C12' if alignment == 'Moderate' else '#E74C3C'

        # Get expression value
        expr = ws_data.get('expression_3lplus') or ws_data.get('tempus_expression') or \
               ws_data.get('tcga_expression') or ws_data.get('expression') or 'N/A'
        if isinstance(expr, float):
            expr = f'{expr:.2f}'

        table_data.append([
            ws_name.replace('_', ' ').title(),
            expr,
            alignment,
            IDAS_PRIORITY_COHORTS.get(f'Tempus_{ws_name}', IDAS_PRIORITY_COHORTS.get(f'TCGA_{ws_name}', ''))
        ])

    if table_data:
        table = ax7.table(cellText=table_data,
                         colLabels=['iDAS Whitespace', 'Expression', 'Alignment', 'Strategic Priority'],
                         loc='center',
                         cellLoc='center',
                         colWidths=[0.3, 0.15, 0.15, 0.4])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.2, 1.8)

        # Color alignment cells
        for i, row in enumerate(table_data):
            alignment = row[2]
            color = '#2ECC71' if alignment == 'Strong' else '#F39C12' if alignment == 'Moderate' else '#E74C3C'
            table[(i + 1, 2)].set_facecolor(color)
            table[(i + 1, 2)].set_text_props(color='white', fontweight='bold')

    ax7.set_title('G. iDAS Whitespace Alignment Summary', fontweight='bold', pad=20)

    # Panel H: Recommendation
    ax8 = fig.add_subplot(gs[2, 2])
    ax8.axis('off')

    overall = assessment.get('overall_alignment', 'Unknown')
    rec = assessment.get('recommendation', 'Unknown')

    bg_color = '#2ECC71' if 'PRIORITY' in rec else '#F39C12' if 'CONDITIONAL' in rec else '#E74C3C'

    ax8.add_patch(plt.Rectangle((0.05, 0.3), 0.9, 0.6, facecolor=bg_color, alpha=0.3,
                                 transform=ax8.transAxes, edgecolor='black', linewidth=2))

    ax8.text(0.5, 0.7, f'Overall Alignment: {overall}', ha='center', va='center',
             transform=ax8.transAxes, fontsize=14, fontweight='bold')
    ax8.text(0.5, 0.5, rec, ha='center', va='center',
             transform=ax8.transAxes, fontsize=11, fontweight='bold', wrap=True)

    # Add toxicity warning if applicable
    tox_risk = assessment.get('on_target_toxicity', {}).get('risk_level', '')
    if tox_risk == 'High':
        ax8.text(0.5, 0.2, 'WARNING: High on-target toxicity risk',
                ha='center', va='center', transform=ax8.transAxes,
                fontsize=10, color='red', fontweight='bold')

    ax8.set_title('H. Recommendation', fontweight='bold')

    # Save figure
    output_path = os.path.join(output_dir, get_output_filename(gene_symbol, 'figure', 'png'))
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"  Saved: {output_path}")

    # Save individual high-resolution figures
    save_individual_figures_crc(gene_symbol, master_df, tempus_gene_data, assessment, output_dir)

    return output_path


def save_individual_figures_crc(gene_symbol, master_df, tempus_gene_data, assessment, output_dir):
    """Save each panel as a separate high-resolution PNG file."""
    figures_dir = os.path.join(output_dir, 'figures')
    os.makedirs(figures_dir, exist_ok=True)

    DPI = 300  # High resolution

    # Panel A: TCGA Cohort Expression
    fig, ax = plt.subplots(figsize=(8, 6))
    if not master_df.empty:
        plot_order = ['TCGA_RASMut_MSS', 'TCGA_RASWT_MSS', 'TCGA_Resectable',
                      'TCGA_MSS_All', 'TCGA_MSIH', 'TCGA_Adjacent', 'GTEx_Colon']
        plot_order = [c for c in plot_order if c in master_df['cohort'].unique()]
        if plot_order:
            plot_df = master_df[master_df['cohort'].isin(plot_order)]
            colors = [COHORT_COLORS.get(c, '#888888') for c in plot_order]
            sns.boxplot(data=plot_df, x='cohort', y='expression', order=plot_order,
                       palette=colors, ax=ax, width=0.6)
            ax.set_xticklabels([COHORT_LABELS.get(c, c) for c in plot_order],
                               rotation=45, ha='right', fontsize=10)
            ax.axhline(y=master_df[master_df['cohort'] == 'TCGA_Adjacent']['expression'].median(),
                       color='gray', linestyle='--', alpha=0.5, label='Adjacent Normal')
    ax.set_xlabel('')
    ax.set_ylabel('Expression (log2)', fontsize=12)
    ax.set_title(f'{gene_symbol} - TCGA Expression by Cohort', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, get_output_filename(gene_symbol, 'panel-01', 'png')), dpi=DPI, facecolor='white')
    plt.close()

    # Panel B: On-Target Toxicity
    fig, ax = plt.subplots(figsize=(6, 5))
    toxicity = assessment.get('on_target_toxicity', {})
    if toxicity:
        fc = toxicity.get('tumor_vs_adjacent_log2FC', 0)
        risk = toxicity.get('risk_level', 'Unknown')
        color = '#2ECC71' if risk == 'Low' else '#F39C12' if risk == 'Medium' else '#E74C3C'
        ax.barh(['Tumor vs\nAdjacent Normal'], [fc], color=color, height=0.5)
        ax.axvline(x=0, color='black', linestyle='-', linewidth=0.5)
        ax.axvline(x=1, color='green', linestyle='--', alpha=0.5, label='Low risk threshold')
        ax.axvline(x=0.5, color='orange', linestyle='--', alpha=0.5, label='Medium risk threshold')
        ax.set_xlabel('log2 Fold Change', fontsize=12)
        ax.set_xlim(-2, max(fc + 1, 3))
        ax.legend(loc='lower right', fontsize=9)
        ax.text(fc + 0.1, 0, f'{fc:.2f}\n({risk} Risk)', va='center', fontsize=11, fontweight='bold')
    ax.set_title(f'{gene_symbol} - On-Target Toxicity Assessment', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, get_output_filename(gene_symbol, 'panel-02', 'png')), dpi=DPI, facecolor='white')
    plt.close()

    # Panel C: Tempus Line of Therapy (Boxplot from summary stats)
    fig, ax = plt.subplots(figsize=(6, 5))
    if 'lot_mss' in tempus_gene_data:
        df = tempus_gene_data['lot_mss'].copy()
        if 'group_name' in df.columns:
            lot_order = ['1L-2L', '3L+ Chemorefractory']
            lot_plot = df[df['group_name'].isin(lot_order)].copy()
            if len(lot_plot) > 0:
                lot_plot['group_name'] = pd.Categorical(lot_plot['group_name'], categories=lot_order, ordered=True)
                lot_plot = lot_plot.sort_values('group_name')
                colors = ['#5DADE2', '#2874A6']
                draw_boxplot_from_summary(ax, lot_plot, 'group_name', colors,
                                         x_labels=['Frontline\n(1L-2L)', 'Chemorefractory\n(3L+)'])
                ax.set_ylabel('Expression (log2 TPM)', fontsize=12)
                for i, (_, row) in enumerate(lot_plot.iterrows()):
                    n = int(row['n_samples']) if 'n_samples' in row else 0
                    ax.annotate(f"n={n:,}", (i, row['q75'] + 0.3), ha='center', fontsize=10)
    ax.set_title(f'{gene_symbol} - Expression by Line of Therapy (Tempus)', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, get_output_filename(gene_symbol, 'panel-03', 'png')), dpi=DPI, facecolor='white')
    plt.close()

    # Panel D: Tempus iDAS Cohorts (Boxplot from summary stats)
    fig, ax = plt.subplots(figsize=(8, 6))
    if 'idas_groups' in tempus_gene_data:
        df = tempus_gene_data['idas_groups'].copy()
        if 'group_name' in df.columns and len(df) > 0:
            # Sort cohorts logically: group by line of therapy (1L-2L together, 3L+ together)
            idas_order = ['MSS_RASMut_1L2L', 'MSS_RASWT_1L2L', 'MSS_RASMut_3L+', 'MSS_RASWT_3L+']
            df = df[df['group_name'].isin(idas_order)].copy()
            df['group_name'] = pd.Categorical(df['group_name'], categories=idas_order, ordered=True)
            df = df.sort_values('group_name')

            colors = ['#C0392B', '#27AE60', '#922B21', '#1E8449']
            x_labels = ['RAS-mut\n1L-2L', 'RAS-WT\n1L-2L', 'RAS-mut\n3L+', 'RAS-WT\n3L+']
            draw_boxplot_from_summary(ax, df, 'group_name', colors, x_labels=x_labels)
            ax.tick_params(axis='x', labelrotation=0, labelsize=10)
            ax.set_ylabel('Expression (log2 TPM)', fontsize=12)

            # Add sample sizes
            for i, (_, row) in enumerate(df.iterrows()):
                n = int(row['n_samples']) if 'n_samples' in row else 0
                ax.annotate(f"n={n:,}", (i, row['q75'] + 0.2), ha='center', fontsize=9)

            # Compute and display p-values for RAS mut vs WT comparisons
            df_indexed = df.set_index('group_name')

            # P-value for 1L-2L
            if 'MSS_RASMut_1L2L' in df_indexed.index and 'MSS_RASWT_1L2L' in df_indexed.index:
                mut_1l = df_indexed.loc['MSS_RASMut_1L2L']
                wt_1l = df_indexed.loc['MSS_RASWT_1L2L']
                se_diff = np.sqrt(mut_1l['sd']**2 / mut_1l['n_samples'] + wt_1l['sd']**2 / wt_1l['n_samples'])
                if se_diff > 0:
                    t_stat = (mut_1l['mean'] - wt_1l['mean']) / se_diff
                    num = (mut_1l['sd']**2 / mut_1l['n_samples'] + wt_1l['sd']**2 / wt_1l['n_samples'])**2
                    denom = (mut_1l['sd']**4 / (mut_1l['n_samples']**2 * (mut_1l['n_samples']-1)) +
                            wt_1l['sd']**4 / (wt_1l['n_samples']**2 * (wt_1l['n_samples']-1)))
                    df_welch = num / denom if denom > 0 else 1
                    p_val_1l = 2 * stats.t.sf(abs(t_stat), df_welch)
                    p_str = f"p={p_val_1l:.2e}" if p_val_1l < 0.01 else f"p={p_val_1l:.3f}"
                    max_y_1l = max(mut_1l['q75'], wt_1l['q75'])
                    ax.plot([0, 1], [max_y_1l + 0.5] * 2, 'k-', linewidth=0.8)
                    ax.annotate(p_str, xy=(0.5, max_y_1l + 0.6), ha='center', fontsize=9, style='italic')

            # P-value for 3L+
            if 'MSS_RASMut_3L+' in df_indexed.index and 'MSS_RASWT_3L+' in df_indexed.index:
                mut_3l = df_indexed.loc['MSS_RASMut_3L+']
                wt_3l = df_indexed.loc['MSS_RASWT_3L+']
                se_diff = np.sqrt(mut_3l['sd']**2 / mut_3l['n_samples'] + wt_3l['sd']**2 / wt_3l['n_samples'])
                if se_diff > 0:
                    t_stat = (mut_3l['mean'] - wt_3l['mean']) / se_diff
                    num = (mut_3l['sd']**2 / mut_3l['n_samples'] + wt_3l['sd']**2 / wt_3l['n_samples'])**2
                    denom = (mut_3l['sd']**4 / (mut_3l['n_samples']**2 * (mut_3l['n_samples']-1)) +
                            wt_3l['sd']**4 / (wt_3l['n_samples']**2 * (wt_3l['n_samples']-1)))
                    df_welch = num / denom if denom > 0 else 1
                    p_val_3l = 2 * stats.t.sf(abs(t_stat), df_welch)
                    p_str = f"p={p_val_3l:.2e}" if p_val_3l < 0.01 else f"p={p_val_3l:.3f}"
                    max_y_3l = max(mut_3l['q75'], wt_3l['q75'])
                    ax.plot([2, 3], [max_y_3l + 0.5] * 2, 'k-', linewidth=0.8)
                    ax.annotate(p_str, xy=(2.5, max_y_3l + 0.6), ha='center', fontsize=9, style='italic')

    ax.set_title(f'{gene_symbol} - iDAS-Aligned Cohorts (Tempus)', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, get_output_filename(gene_symbol, 'panel-04', 'png')), dpi=DPI, facecolor='white')
    plt.close()

    # Panel E: RAS Status (Boxplot from summary stats)
    fig, ax = plt.subplots(figsize=(6, 5))
    if 'ras_status_mss' in tempus_gene_data:
        df = tempus_gene_data['ras_status_mss'].copy()
        if 'group_name' in df.columns:
            ras_order = ['RAS Mutant', 'RAS WT']
            ras_plot = df[df['group_name'].isin(ras_order)].copy()
            if len(ras_plot) > 0:
                ras_plot['group_name'] = pd.Categorical(ras_plot['group_name'], categories=ras_order, ordered=True)
                ras_plot = ras_plot.sort_values('group_name')
                colors = ['#C0392B', '#27AE60']
                draw_boxplot_from_summary(ax, ras_plot, 'group_name', colors,
                                         x_labels=['RAS Mutant', 'RAS Wild-Type'])
                ax.set_ylabel('Expression (log2 TPM)', fontsize=12)
                for i, (_, row) in enumerate(ras_plot.iterrows()):
                    n = int(row['n_samples']) if 'n_samples' in row else 0
                    ax.annotate(f"n={n:,}", (i, row['q75'] + 0.3), ha='center', fontsize=10)
    ax.set_title(f'{gene_symbol} - Expression by RAS Status (Tempus)', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, get_output_filename(gene_symbol, 'panel-05', 'png')), dpi=DPI, facecolor='white')
    plt.close()

    # Panel F: CMS Subtypes (Boxplot for TCGA, summary boxplot for Tempus)
    fig, ax = plt.subplots(figsize=(6, 5))
    cms_source = None
    if not master_df.empty and 'CMS' in master_df.columns:
        cms_order = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
        cms_df = master_df[master_df['CMS'].isin(cms_order)].copy()
        if len(cms_df) > 0:
            colors = [CMS_COLORS.get(c, '#888888') for c in cms_order]
            sns.boxplot(data=cms_df, x='CMS', y='expression', order=cms_order,
                       palette=colors, ax=ax, width=0.6)
            ax.set_ylabel('Expression (log2 TPM)', fontsize=12)
            cms_source = 'TCGA'
    if cms_source is None and 'cms' in tempus_gene_data:
        df = tempus_gene_data['cms'].copy()
        group_col = 'group' if 'group' in df.columns else 'group_name'
        cms_order = ['CMS1', 'CMS2', 'CMS3', 'CMS4']
        cms_plot = df[df[group_col].isin(cms_order)].copy()
        if len(cms_plot) > 0:
            cms_plot['group_name'] = cms_plot[group_col]
            cms_plot['group_name'] = pd.Categorical(cms_plot['group_name'], categories=cms_order, ordered=True)
            cms_plot = cms_plot.sort_values('group_name')
            colors = [CMS_COLORS.get(c, '#888888') for c in cms_order if c in cms_plot['group_name'].values]
            draw_boxplot_from_summary(ax, cms_plot, 'group_name', colors)
            ax.set_ylabel('Expression (log2 TPM)', fontsize=12)
            cms_source = 'Tempus'
    if cms_source:
        ax.set_title(f'{gene_symbol} - CMS Subtype Expression ({cms_source})', fontweight='bold', fontsize=14)
    else:
        ax.set_title(f'{gene_symbol} - CMS Subtype Expression (No data)', fontweight='bold', fontsize=14)
        ax.text(0.5, 0.5, 'No CMS data available', ha='center', va='center', transform=ax.transAxes)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, get_output_filename(gene_symbol, 'panel-06', 'png')), dpi=DPI, facecolor='white')
    plt.close()

    # Panel G: iDAS Alignment Summary Table
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axis('off')
    whitespace = assessment.get('whitespace_alignment', {})
    table_data = []
    for ws_name, ws_data in whitespace.items():
        alignment = ws_data.get('alignment', 'Unknown')
        expr = ws_data.get('expression_3lplus') or ws_data.get('tempus_expression') or \
               ws_data.get('tcga_expression') or ws_data.get('expression') or 'N/A'
        if isinstance(expr, float):
            expr = f'{expr:.2f}'
        table_data.append([
            ws_name.replace('_', ' ').title(), expr, alignment,
            IDAS_PRIORITY_COHORTS.get(f'Tempus_{ws_name}', IDAS_PRIORITY_COHORTS.get(f'TCGA_{ws_name}', ''))
        ])
    if table_data:
        table = ax.table(cellText=table_data,
                         colLabels=['iDAS Whitespace', 'Expression', 'Alignment', 'Strategic Priority'],
                         loc='center', cellLoc='center', colWidths=[0.25, 0.15, 0.15, 0.45])
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1.2, 2.0)
        for i, row in enumerate(table_data):
            alignment = row[2]
            color = '#2ECC71' if alignment == 'Strong' else '#F39C12' if alignment == 'Moderate' else '#E74C3C'
            table[(i + 1, 2)].set_facecolor(color)
            table[(i + 1, 2)].set_text_props(color='white', fontweight='bold')
    ax.set_title(f'{gene_symbol} - iDAS Whitespace Alignment Summary', fontweight='bold', fontsize=14, pad=20)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, get_output_filename(gene_symbol, 'panel-07', 'png')), dpi=DPI, facecolor='white')
    plt.close()

    # Panel H: Recommendation
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.axis('off')
    overall = assessment.get('overall_alignment', 'Unknown')
    rec = assessment.get('recommendation', 'Unknown')
    bg_color = '#2ECC71' if 'PRIORITY' in rec else '#F39C12' if 'CONDITIONAL' in rec else '#E74C3C'
    ax.add_patch(plt.Rectangle((0.05, 0.2), 0.9, 0.6, facecolor=bg_color, alpha=0.3,
                                 transform=ax.transAxes, edgecolor='black', linewidth=2))
    ax.text(0.5, 0.6, f'Overall Alignment: {overall}', ha='center', va='center',
             transform=ax.transAxes, fontsize=16, fontweight='bold')
    ax.text(0.5, 0.4, rec, ha='center', va='center',
             transform=ax.transAxes, fontsize=12, fontweight='bold', wrap=True)
    tox_risk = assessment.get('on_target_toxicity', {}).get('risk_level', '')
    if tox_risk == 'High':
        ax.text(0.5, 0.15, 'WARNING: High on-target toxicity risk',
                ha='center', va='center', transform=ax.transAxes,
                fontsize=11, color='red', fontweight='bold')
    ax.set_title(f'{gene_symbol} - Recommendation', fontweight='bold', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, get_output_filename(gene_symbol, 'panel-08', 'png')), dpi=DPI, facecolor='white')
    plt.close()

    print(f"  Saved individual figures to: {figures_dir}/")


# =============================================================================
# REPORT GENERATION
# =============================================================================

def generate_comprehensive_report(gene_symbol, master_df, tcga_stats, tcga_comparisons,
                                   tempus_gene_data, assessment, output_dir, subgroup_suitability=None):
    """Generate comprehensive markdown report."""
    report = []

    # Header
    report.append(f"# {gene_symbol} Comprehensive CRC Target Evaluation Report")
    report.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Get Tempus sample count dynamically from overall data
    tempus_n = 2183  # Default fallback
    if tempus_gene_data and 'overall' in tempus_gene_data:
        overall_df = tempus_gene_data['overall']
        if not overall_df.empty and 'n_samples' in overall_df.columns:
            tempus_n = int(overall_df['n_samples'].iloc[0])

    report.append(f"\n**Data Sources:** TCGA/GTEx (n={len(master_df) if not master_df.empty else 0}) + "
                 f"Tempus RWD (n={tempus_n:,})")

    # Executive Summary
    report.append("\n---\n## Executive Summary\n")

    overall = assessment.get('overall_alignment', 'Unknown')
    rec = assessment.get('recommendation', 'Unknown')
    tox_risk = assessment.get('on_target_toxicity', {}).get('risk_level', 'Unknown')
    tox_fc = assessment.get('on_target_toxicity', {}).get('tumor_vs_adjacent_log2FC', 0)

    report.append(f"| Metric | Value |")
    report.append(f"|--------|-------|")
    report.append(f"| **iDAS Alignment** | {overall} |")
    report.append(f"| **Recommendation** | {rec} |")
    report.append(f"| **On-Target Toxicity Risk** | {tox_risk} (log2FC: {tox_fc:.2f}) |")

    # iDAS Whitespace Alignment
    report.append("\n---\n## iDAS Whitespace Alignment\n")
    report.append("> **Data Sources:** Tempus CRC RWD (~2,183 patients, ~90% CPI-naive) + TCGA-COAD/READ\n\n")
    report.append("| Priority Whitespace | Expression (log2TPM) | Alignment | N Samples | Source |")
    report.append("|---------------------|----------------------|-----------|-----------|--------|")

    for ws_name, ws_data in assessment.get('whitespace_alignment', {}).items():
        expr = ws_data.get('expression_3lplus') or ws_data.get('tempus_expression') or \
               ws_data.get('tcga_expression') or ws_data.get('expression') or 'N/A'
        if isinstance(expr, float):
            expr = f'{expr:.2f}'
        alignment = ws_data.get('alignment', 'Unknown')
        n_samples = ws_data.get('n_samples', 'N/A')
        source = ws_data.get('source', 'TCGA')
        report.append(f"| {ws_name.replace('_', ' ').title()} | {expr} | **{alignment}** | {n_samples} | {source} |")

    # On-Target Toxicity Assessment
    report.append("\n---\n## On-Target Toxicity Assessment (TCGA/GTEx)\n")
    report.append("> **Data Source:** TCGA-COAD/READ (treatment-naive) vs TCGA Adjacent Normal & GTEx Colon\n\n")
    report.append("**Primary Metric:** Tumor vs Adjacent Normal Expression\n")

    if tcga_comparisons is not None and not tcga_comparisons.empty:
        report.append("| Comparison | Tumor N | Normal N | Tumor Median | Normal Median | log2FC | p-value |")
        report.append("|------------|---------|----------|--------------|---------------|--------|---------|")
        for _, row in tcga_comparisons.iterrows():
            report.append(f"| {row['Tumor_Cohort']} vs {row['Normal_Group']} | "
                         f"{int(row['Tumor_N'])} | {int(row['Normal_N'])} | "
                         f"{row['Tumor_Median']:.2f} | {row['Normal_Median']:.2f} | "
                         f"{row['Log2FC']:.2f} | {row['p_value']:.2e} |")

    report.append(f"\n**Interpretation:**")
    if tox_fc > 1:
        report.append(f"- Tumor expression is {2**tox_fc:.1f}x higher than adjacent normal")
        report.append(f"- **Low on-target toxicity risk** - target appears tumor-specific")
    elif tox_fc > 0.5:
        report.append(f"- Tumor expression is {2**tox_fc:.1f}x higher than adjacent normal")
        report.append(f"- **Moderate on-target toxicity risk** - some normal tissue expression")
    else:
        report.append(f"- Tumor expression similar to adjacent normal (FC: {2**tox_fc:.1f}x)")
        report.append(f"- **High on-target toxicity risk** - significant normal tissue expression")

    # Tempus Real-World Evidence
    report.append("\n---\n## Tempus Real-World Evidence\n")
    report.append("> **Data Source:** Tempus CRC cohort (~2,183 patients, ~90% CPI-naive, ~10% CPI-treated)\n\n")

    # Line of Therapy
    report.append("### Line of Therapy Expression (MSS, Tempus)\n")
    if 'lot_mss' in tempus_gene_data:
        df = tempus_gene_data['lot_mss']
        report.append("| Line of Therapy | N Samples | Mean | Median | log2FC vs Frontline |")
        report.append("|-----------------|-----------|------|--------|---------------------|")
        for _, row in df.iterrows():
            fc = row.get('log2FC_3Lplus_vs_early', 'N/A')
            if isinstance(fc, float):
                fc = f"{fc:.3f}"
            report.append(f"| {row['group_name']} | {int(row['n_samples']):,} | "
                         f"{row['mean']:.2f} | {row['median']:.2f} | {fc} |")

    # Key Target Population
    report.append("\n### Key iDAS Population: MSS RAS-Mutant 3L+ Chemorefractory (Tempus)\n")
    if 'key_target_3lplus' in tempus_gene_data:
        df = tempus_gene_data['key_target_3lplus']
        if not df.empty:
            row = df.iloc[0]
            report.append(f"- **Sample Size:** {int(row.get('n_samples', 0)):,}")
            report.append(f"- **Mean Expression:** {row.get('mean', 0):.2f} log2TPM")
            report.append(f"- **% Detected:** {row.get('pct_detected', 0):.1f}%")
            report.append(f"- **log2FC vs All MSS:** {row.get('log2FC_vs_MSS_all', 0):.3f}")

    # RAS Status
    report.append("\n### RAS Status Expression (MSS, Tempus)\n")
    if 'ras_status_mss' in tempus_gene_data:
        df = tempus_gene_data['ras_status_mss']
        report.append("| RAS Status | N Samples | Mean | log2FC vs WT |")
        report.append("|------------|-----------|------|--------------|")
        for _, row in df.iterrows():
            fc = row.get('log2FC_RASMut_vs_WT', 'N/A')
            if isinstance(fc, float):
                fc = f"{fc:.3f}"
            report.append(f"| {row['group_name']} | {int(row['n_samples']):,} | "
                         f"{row['mean']:.2f} | {fc} |")

    # CPI Treatment Context
    report.append("\n### Checkpoint Inhibitor Context (Tempus)\n")
    if 'cpi_status' in tempus_gene_data:
        df = tempus_gene_data['cpi_status']
        report.append("| CPI Status | N Samples | Mean | log2FC Treated vs Naive |")
        report.append("|------------|-----------|------|-------------------------|")
        for _, row in df.iterrows():
            fc = row.get('log2FC_treated_vs_naive', 'N/A')
            if isinstance(fc, float):
                fc = f"{fc:.3f}"
            report.append(f"| {row['group_name']} | {int(row['n_samples']):,} | "
                         f"{row['mean']:.2f} | {fc} |")

    # TCGA Cohort Statistics
    total_tcga_n = int(tcga_stats['count'].sum()) if tcga_stats is not None and 'count' in tcga_stats.columns else 0
    report.append(f"\n---\n## TCGA/GTEx Cohort Expression Statistics (N={total_tcga_n})\n")
    report.append("> **Data Source:** TCGA-COAD/READ (treatment-naive), TCGA Adjacent Normal, GTEx Colon, CCLE\n\n")
    if tcga_stats is not None and not tcga_stats.empty:
        report.append("| Cohort | N | Median (log2TPM) | Mean | SD | iDAS Priority |")
        report.append("|--------|---|------------------|------|----| --------------|")
        for cohort in tcga_stats.index:
            row = tcga_stats.loc[cohort]
            priority = "Yes" if cohort in IDAS_PRIORITY_COHORTS else "No"
            report.append(f"| {cohort} | {int(row['count'])} | {row['median']:.2f} | "
                         f"{row['mean']:.2f} | {row['std']:.2f} | {priority} |")

    # Subgroup Suitability Analysis (3-Phase)
    if subgroup_suitability and subgroup_suitability.get('summary'):
        report.append("\n---\n## Subgroup Suitability Analysis\n")
        report.append("> **3-Phase Analysis:** Phase 1 (TCGA Molecular, treatment-naive) → Phase 2 (Tempus RAS status, CPI-naive/treated) → Phase 3 (iDAS whitespace)\n\n")

        # Phase 1: Molecular Subgroups
        report.append("### Phase 1: Molecular Subgroup Suitability (TCGA)\n")
        report.append("| Subgroup | Key Metric | Score | Recommendation |")
        report.append("|----------|------------|-------|----------------|")
        for row in subgroup_suitability['summary']:
            if row.get('category') == 'molecular_subgroup':
                report.append(f"| {row['subgroup']} | {row['key_metric']} | {row['score']}/5 | **{row['recommendation']}** |")
        report.append("\n")

        # Phase 2: RAS Mutation Status (Tempus)
        report.append("### Phase 2: RAS Mutation Status (Tempus)\n")
        report.append("| Subgroup | Key Metric | Score | Recommendation |")
        report.append("|----------|------------|-------|----------------|")
        for row in subgroup_suitability['summary']:
            if row.get('category') == 'ras_status':
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

        # Best Subgroups Summary
        best_subs = subgroup_suitability.get('best_subgroups', {})
        if best_subs.get('priority') or best_subs.get('go') or best_subs.get('caution_exclude'):
            report.append("### Subgroup Recommendations\n")
            if best_subs.get('priority'):
                report.append(f"**PRIORITY Subgroups:** {', '.join(best_subs['priority'])}\n")
            if best_subs.get('go'):
                report.append(f"**GO Subgroups:** {', '.join(best_subs['go'])}\n")
            if best_subs.get('caution_exclude'):
                report.append(f"**CAUTION/EXCLUDE Subgroups:** {', '.join(best_subs['caution_exclude'])}\n")

    # Conclusions
    report.append("\n---\n## Conclusions and Recommendations\n")

    report.append(f"### Overall Assessment: **{overall}**\n")
    report.append(f"**Recommendation:** {rec}\n")

    report.append("\n### Key Findings:\n")

    # On-target toxicity
    if tox_risk == 'Low':
        report.append(f"1. **Low on-target toxicity risk** - {2**tox_fc:.1f}x higher in tumor vs adjacent normal")
    elif tox_risk == 'Medium':
        report.append(f"1. **Moderate on-target toxicity risk** - {2**tox_fc:.1f}x higher in tumor vs adjacent normal")
    else:
        report.append(f"1. **High on-target toxicity risk** - similar expression in tumor and normal tissue")

    # iDAS alignment
    strong_ws = [k for k, v in assessment.get('whitespace_alignment', {}).items()
                 if v.get('alignment') == 'Strong']
    if strong_ws:
        report.append(f"2. **Strong alignment** with iDAS whitespaces: {', '.join(strong_ws)}")
    else:
        report.append("2. **Limited alignment** with iDAS priority whitespaces")

    # RAS status
    if 'ras_mutant_frontline' in assessment.get('whitespace_alignment', {}):
        ras_data = assessment['whitespace_alignment']['ras_mutant_frontline']
        report.append(f"3. **RAS mutant population**: Expression = {ras_data.get('tempus_expression', ras_data.get('tcga_expression', 'N/A'))}")

    report.append("\n### Next Steps:\n")
    if overall == 'High' and tox_risk != 'High':
        report.append("- Proceed with target validation studies")
        report.append("- Evaluate druggability and modality options")
        report.append("- Consider combination strategies for iDAS priority populations")
    elif overall == 'Medium':
        report.append("- Conduct additional validation in specific populations")
        report.append("- Evaluate expression in relevant disease models")
        report.append("- Assess competitive landscape")
    else:
        report.append("- Consider alternative targets with better iDAS alignment")
        report.append("- If proceeding, focus on specific biomarker-defined populations")

    # Write report
    report_path = os.path.join(output_dir, get_output_filename(gene_symbol, 'report', 'md'))
    with open(report_path, 'w') as f:
        f.write('\n'.join(report))
    print(f"  Saved: {report_path}")

    return report_path


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def analyze_gene(gene_symbol, cache_dir, output_dir, tcga_data=None, tempus_data=None,
                 skip_tcga=False, skip_tempus=False):
    """Run comprehensive analysis for a single gene."""
    print(f"\n{'='*70}")
    print(f"Analyzing: {gene_symbol}")
    print('='*70)

    # Create gene output directory
    # Avoid double-nesting if output_dir already ends with gene name
    if os.path.basename(output_dir.rstrip('/')) == gene_symbol:
        gene_dir = output_dir
    else:
        gene_dir = os.path.join(output_dir, gene_symbol)
    os.makedirs(gene_dir, exist_ok=True)

    master_df = pd.DataFrame()
    tcga_stats = None
    tcga_comparisons = None
    tempus_gene_data = {}

    # TCGA Analysis
    if not skip_tcga and tcga_data is not None:
        print("\n  Processing TCGA data...")

        gene_annotation = tcga_data.get('gene_annotation')
        if gene_annotation is not None:
            gene_match = gene_annotation[gene_annotation['gene_name'] == gene_symbol]
            if gene_match.empty:
                print(f"  Warning: Gene {gene_symbol} not found in annotation")
            else:
                gene_index = gene_match.iloc[0]['gene_index']
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
                master_df = build_tcga_master_dataframe(
                    tcga_expr, gtex_expr, ccle_expr,
                    tcga_data['tcga_meta'], tcga_data['gtex_meta'], tcga_data['ccle_meta'],
                    tcga_data.get('cohort_df'), tcga_data.get('cms_df'),
                    tcga_data.get('adj_normal_samples', [])
                )
                print(f"  Built master dataframe: {len(master_df)} samples")

                # Calculate statistics
                if not master_df.empty:
                    tcga_stats = calculate_cohort_statistics(master_df)

                    # Pairwise comparisons
                    tumor_cohorts = [c for c in TCGA_COHORTS if c in master_df['cohort'].unique()]
                    normal_groups = ['TCGA_Adjacent', 'GTEx_Colon']
                    normal_groups = [n for n in normal_groups if n in master_df['cohort'].unique()]

                    if tumor_cohorts and normal_groups:
                        tcga_comparisons = perform_pairwise_comparisons(master_df, tumor_cohorts, normal_groups)
                        print(f"  Performed {len(tcga_comparisons)} pairwise comparisons")

    # Tempus Analysis
    if not skip_tempus and tempus_data is not None:
        print("\n  Processing Tempus data...")
        tempus_gene_data = get_tempus_gene_data(gene_symbol, tempus_data)
        print(f"  Found Tempus data for {len(tempus_gene_data)} categories")

    # iDAS Alignment Assessment
    print("\n  Assessing iDAS alignment...")
    assessment = assess_idas_alignment(gene_symbol, tcga_stats, tcga_comparisons, tempus_gene_data)
    print(f"  Overall alignment: {assessment['overall_alignment']}")
    print(f"  Recommendation: {assessment['recommendation']}")

    # Compute subgroup suitability
    print("\n  Computing subgroup suitability...")
    subgroup_suitability = compute_subgroup_suitability(
        gene_symbol, tcga_stats, tcga_comparisons, assessment, tempus_gene_data
    )

    # Print key findings
    priority_subs = subgroup_suitability.get('best_subgroups', {}).get('priority', [])
    go_subs = subgroup_suitability.get('best_subgroups', {}).get('go', [])
    caution_subs = subgroup_suitability.get('best_subgroups', {}).get('caution_exclude', [])

    if priority_subs:
        print(f"  PRIORITY subgroups: {', '.join(priority_subs)}")
    if caution_subs:
        print(f"  EXCLUDE/CAUTION subgroups: {', '.join(caution_subs)}")

    # Save subgroup suitability
    suitability_csv_path = os.path.join(gene_dir, get_output_filename(gene_symbol, 'suitability', 'csv'))
    suitability_df = pd.DataFrame(subgroup_suitability['summary'])
    suitability_df.to_csv(suitability_csv_path, index=False)
    print(f"  Saved: {suitability_csv_path}")

    # Save assessment
    assessment_path = os.path.join(gene_dir, get_output_filename(gene_symbol, 'idas', 'yaml'))
    with open(assessment_path, 'w') as f:
        # Convert numpy types to Python native types for clean YAML serialization
        yaml.dump(convert_numpy_types(assessment), f, default_flow_style=False)
    print(f"  Saved: {assessment_path}")

    # Generate visualizations
    print("\n  Generating visualizations...")
    fig_path = create_comprehensive_figure(gene_symbol, master_df, tempus_gene_data, assessment, gene_dir)

    # Generate subgroup suitability figure
    suitability_fig_path = save_subgroup_suitability_figure(gene_symbol, subgroup_suitability, gene_dir)
    if suitability_fig_path:
        print(f"  Saved: {suitability_fig_path}")

    # Generate report
    print("\n  Generating report...")
    report_path = generate_comprehensive_report(
        gene_symbol, master_df, tcga_stats, tcga_comparisons,
        tempus_gene_data, assessment, gene_dir, subgroup_suitability
    )

    # Save statistics
    if tcga_stats is not None:
        stats_path = os.path.join(gene_dir, get_output_filename(gene_symbol, 'tcga-stats', 'csv'))
        tcga_stats.to_csv(stats_path)
        print(f"  Saved: {stats_path}")

    if tcga_comparisons is not None and not tcga_comparisons.empty:
        comp_path = os.path.join(gene_dir, get_output_filename(gene_symbol, 'comparisons', 'csv'))
        tcga_comparisons.to_csv(comp_path, index=False)
        print(f"  Saved: {comp_path}")

    return {
        'gene': gene_symbol,
        'assessment': assessment,
        'output_dir': gene_dir,
        'tcga_samples': len(master_df) if not master_df.empty else 0,
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='CRC Comprehensive Gene Expression Analysis (TCGA + Tempus)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python crc_comprehensive_analysis.py --genes TNFRSF12A CDK4 EPCAM
    python crc_comprehensive_analysis.py --gene-file genes.txt --output-dir ./results
    python crc_comprehensive_analysis.py --genes MET --skip-tcga  # Tempus only (faster)
    python crc_comprehensive_analysis.py --genes MET --skip-tempus  # TCGA only

This script provides comprehensive CRC target evaluation combining:
  - TCGA: Tumor vs Normal expression (on-target toxicity assessment)
  - GTEx: Healthy tissue baseline
  - CCLE: Cell line expression
  - Tempus: Real-world data with line-of-therapy stratification (iDAS alignment)
        """)

    parser.add_argument('--genes', nargs='+', help='Gene symbols to analyze')
    parser.add_argument('--gene-file', help='File with gene symbols (one per line)')
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR, help='Output directory')
    parser.add_argument('--cache-dir', default=DEFAULT_CACHE_DIR, help='Data cache directory')
    parser.add_argument('--skip-tcga', action='store_true', help='Skip TCGA analysis (Tempus only)')
    parser.add_argument('--skip-tempus', action='store_true', help='Skip Tempus analysis (TCGA only)')
    parser.add_argument('--cohort-file', default=DEFAULT_COHORT_PATH, help='Cohort assignments CSV')
    parser.add_argument('--cms-file', default=DEFAULT_CMS_PATH, help='CMS predictions CSV')
    parser.add_argument('--adj-normal-file', default=DEFAULT_ADJ_NORMAL_PATH, help='Adjacent normal samples')

    args = parser.parse_args()

    # Get gene list
    genes = []
    if args.genes:
        genes.extend(args.genes)
    if args.gene_file:
        with open(args.gene_file) as f:
            genes.extend([line.strip() for line in f if line.strip()])

    if not genes:
        parser.error('No genes specified. Use --genes or --gene-file')

    genes = list(set(genes))
    print(f"\n{'='*70}")
    print(f"CRC COMPREHENSIVE TARGET ANALYSIS")
    print(f"{'='*70}")
    print(f"Analyzing {len(genes)} gene(s): {', '.join(genes[:5])}{'...' if len(genes) > 5 else ''}")
    print(f"TCGA analysis: {'Disabled' if args.skip_tcga else 'Enabled'}")
    print(f"Tempus analysis: {'Disabled' if args.skip_tempus else 'Enabled'}")

    # Setup directories
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.cache_dir, exist_ok=True)

    # Load TCGA data
    tcga_data = None
    if not args.skip_tcga:
        print("\nLoading TCGA/GTEx/CCLE metadata...")
        try:
            tcga_data = {
                'gene_annotation': load_gene_annotation(args.cache_dir),
                'tcga_meta': load_tcga_metadata(args.cache_dir),
                'gtex_meta': load_gtex_metadata(args.cache_dir),
                'ccle_meta': load_ccle_metadata(args.cache_dir),
                'cohort_df': load_cohort_assignments(args.cohort_file),
                'cms_df': load_cms_predictions(args.cms_file),
                'adj_normal_samples': load_adjacent_normal_samples(args.adj_normal_file),
            }
            print("  TCGA data loaded successfully")
        except Exception as e:
            print(f"  Warning: Could not load TCGA data: {e}")
            tcga_data = None

    # Load Tempus data
    tempus_data = None
    if not args.skip_tempus:
        tempus_data = load_all_tempus_data(args.cache_dir)

    # Analyze each gene
    results = []
    for gene in genes:
        try:
            result = analyze_gene(
                gene, args.cache_dir, args.output_dir,
                tcga_data=tcga_data, tempus_data=tempus_data,
                skip_tcga=args.skip_tcga, skip_tempus=args.skip_tempus
            )
            results.append(result)
        except Exception as e:
            print(f"  Error analyzing {gene}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print(f"\n{'='*70}")
    print("ANALYSIS COMPLETE")
    print('='*70)
    print(f"\nProcessed {len(results)}/{len(genes)} genes successfully")
    print(f"Output directory: {args.output_dir}")

    if results:
        print("\n" + "-"*70)
        print("iDAS ALIGNMENT SUMMARY")
        print("-"*70)
        print(f"{'Gene':<15} {'Alignment':<12} {'Toxicity Risk':<15} {'Recommendation'}")
        print("-"*70)
        for r in results:
            gene = r['gene']
            alignment = r['assessment']['overall_alignment']
            tox_risk = r['assessment'].get('on_target_toxicity', {}).get('risk_level', 'N/A')
            rec = r['assessment']['recommendation'].split(' - ')[0]
            print(f"{gene:<15} {alignment:<12} {tox_risk:<15} {rec}")


if __name__ == '__main__':
    main()
