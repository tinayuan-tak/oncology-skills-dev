---
name: crc-bulk-rna-analysis
description: Use when analyzing gene expression in colorectal cancer. Triggers include gene expression analysis for CRC, TCGA COAD/READ analysis, CRC cell lines, CMS subtype comparison, tumor vs normal colon comparison, target evaluation report, or any gene-level analysis in colorectal cancer context. Generates cohort comparisons (2A, 2B, 4, 5, 6, CMS) with figures and comprehensive target evaluation reports.
---

# CRC Gene Expression Analysis & Target Evaluation

## Overview

Analyze gene expression across colorectal cancer (CRC) cohorts, normal tissue comparisons, CMS subtypes, and CRC cell lines. Generates comprehensive target evaluation reports with publication-ready figures.

## Key Capabilities

- **Cohort Comparisons**: 2A (RAS-mut MSS), 2B (RAS-WT MSS), 4 (Early Stage), 5 (All MSS), 6 (MSI-H)
- **CMS Subtype Analysis**: CMS1-4 stratification with statistical comparisons
- **Normal Tissue Comparisons**: TCGA Adjacent Normal, GTEx Normal Colon
- **COAD vs READ Analysis**: Colon vs rectal adenocarcinoma comparisons
- **Cell Line Analysis**: CCLE CRC cell line expression
- **Target Evaluation Reports**: Comprehensive markdown reports with figures and statistics

## Data Sources

### Expression Data (Omicsoft Reprocessed from S3)
- **TCGA**: COAD/READ tumor and adjacent normal samples
- **GTEx**: Normal colon tissue
- **CCLE**: CRC cell lines
- **Format**: TPM values, log2-transformed during analysis

### Required Input Files (from S3)
| File | S3 Path | Description |
|------|---------|-------------|
| `crc_cohort_assignments.csv` | `s3://onc-compbio/TCGA/crc_cohort_assignments.csv` | Pre-computed cohort memberships (2A, 2B, 4, 5, 6) |
| `TCGA_CMS_prediction.csv` | `s3://onc-compbio/TCGA/TCGA_CMS_prediction.csv` | CMS subtype predictions |
| `TCGA-COAD-READ-AdjNormal.tsv` | `s3://onc-compbio/TCGA/TCGA-COAD-READ-AdjNormal.tsv` | TCGA adjacent normal sample IDs |

## CRC Cohort Definitions

| Cohort | Definition | Description |
|--------|------------|-------------|
| **2A** | RAS-mutant MSS | Frontline RAS-mutant, microsatellite stable |
| **2B** | RAS-WT MSS | Frontline RAS wild-type, microsatellite stable |
| **4** | Early Stage | Stage I/II CRC |
| **5** | All MSS | All microsatellite stable samples |
| **6** | All MSI-H | All microsatellite instability-high samples |

## CMS Subtypes

- **CMS1**: MSI Immune
- **CMS2**: Canonical
- **CMS3**: Metabolic
- **CMS4**: Mesenchymal

## Implementation

### Step 0: Setup Pixi Environment

Before running the analysis, ensure the pixi environment is set up in the user's workspace. The skill includes `pixi.toml` and `pixi.lock` files for reproducible environment management.

**Copy pixi files and required data files to workspace:**

```bash
# Get the skill base directory from the loaded skill context
# SKILL_BASE_DIR is provided when the skill is invoked (see "Base directory for this skill:" in skill output)

# Check if pixi is installed
if ! command -v pixi &> /dev/null; then
    echo "ERROR: pixi is not installed. Install it first:"
    echo "  curl -fsSL https://pixi.sh/install.sh | bash"
    echo "  source ~/.zshrc  # or restart terminal"
    exit 1
fi

# Copy pixi files to user's workspace (if not already present)
if [ ! -f "pixi.toml" ]; then
    echo "Copying pixi.toml and pixi.lock to workspace..."
    cp "$SKILL_BASE_DIR/pixi.toml" ./
    cp "$SKILL_BASE_DIR/pixi.lock" ./
fi

# Download required data files from S3 if not present
if [ ! -f "crc_cohort_assignments.csv" ]; then
    echo "Downloading crc_cohort_assignments.csv from S3..."
    aws s3 cp s3://onc-compbio/TCGA/crc_cohort_assignments.csv ./ --profile cbg --no-verify-ssl
fi

if [ ! -f "TCGA_CMS_prediction.csv" ]; then
    echo "Downloading TCGA_CMS_prediction.csv from S3..."
    aws s3 cp s3://onc-compbio/TCGA/TCGA_CMS_prediction.csv ./ --profile cbg --no-verify-ssl
fi

if [ ! -f "TCGA-COAD-READ-AdjNormal.tsv" ]; then
    echo "Downloading TCGA-COAD-READ-AdjNormal.tsv from S3..."
    aws s3 cp s3://onc-compbio/TCGA/TCGA-COAD-READ-AdjNormal.tsv ./ --profile cbg --no-verify-ssl
fi

# Install pixi environment in workspace
if [ ! -d ".pixi" ]; then
    echo "Installing pixi environment from pixi.lock..."
    pixi install
else
    echo "Pixi environment already exists in workspace"
fi
```

**Environment includes:**
- Python 3.12
- pandas, numpy, matplotlib, seaborn
- scipy, statsmodels
- awscli (for S3 data access)

**Note:** The `.pixi/` directory will be created in your workspace. Add `.pixi/` to your `.gitignore` if using version control.

### Step 1: Parse Gene Input

Accept gene input as:
- Single gene: `TNFRSF12A` (Fn14)
- Multiple genes: `CDK4 CDK6 CCND1`
- Gene list file: `genes.txt` (one per line)

### Step 2: Run the Analysis Script

**IMPORTANT**: Always use the `crc_gene_analysis.py` script from the skill directory. This is the complete, validated analysis pipeline.

**Copy the script to workspace and run:**

```bash
# Copy the analysis script from skill directory
cp "$SKILL_BASE_DIR/crc_gene_analysis.py" ./

# Run analysis with pixi (single gene)
pixi run python crc_gene_analysis.py --genes CDK4

# Run analysis with pixi (multiple genes)
pixi run python crc_gene_analysis.py --genes CDK4 CDK6 CCND1

# Run analysis with gene file
pixi run python crc_gene_analysis.py --gene-file genes.txt

# Custom output directory
pixi run python crc_gene_analysis.py --genes CDK4 --output-dir ./my_results
```

### Script Usage

```
Usage:
    python crc_gene_analysis.py --genes CDK4 CDK6 CCND1
    python crc_gene_analysis.py --gene-file genes.txt
    python crc_gene_analysis.py --genes CDK4 --output-dir ./my_results

Arguments:
    --genes          Gene symbol(s) to analyze (space-separated)
    --gene-file      File with gene symbols (one per line)
    --output-dir     Output directory (default: ./crc_analysis_results)
    --cache-dir      Data cache directory (default: ./data_cache)
    --cohort-path    Path to cohort assignments CSV
    --cms-path       Path to CMS predictions CSV
    --adj-normal-path Path to adjacent normal samples TSV
```

### Step 3: Review Results

Results are saved to `./crc_analysis_results/{GENE}/` for each gene analyzed.

## Output Files

For each gene, the analysis generates:

| File | Description |
|------|-------------|
| `{GENE}_cohort_boxplot.png/pdf` | Expression across CRC cohorts (2A, 2B, 4, 5, 6) vs normal |
| `{GENE}_cohort_violin.png` | Violin plot with distribution |
| `{GENE}_CMS_boxplot.png` | Expression by CMS subtype |
| `{GENE}_COAD_READ_boxplot.png` | COAD vs READ comparison |
| `{GENE}_COAD_READ_by_cohort.png` | COAD vs READ within each cohort |
| `{GENE}_comprehensive_analysis.png/pdf` | Multi-panel summary figure |
| `{GENE}_cohort_statistics.csv` | Descriptive statistics by cohort |
| `{GENE}_pairwise_comparisons.csv` | Statistical comparisons (tumor vs normal) |
| `{GENE}_COAD_READ_statistics.csv` | COAD vs READ statistics |
| `{GENE}_expression_data.csv` | Raw expression values with metadata |
| `{GENE}_target_evaluation_report.md` | Comprehensive markdown report |
| `{GENE}_COAD_cohort_statistics.csv` | COAD-only cohort statistics |
| `{GENE}_READ_cohort_statistics.csv` | READ-only cohort statistics |

## Quick Start Example

User: "Analyze CDK4, CDK6, and CCND1 expression in CRC"

Response:
1. Setup pixi environment and copy required files
2. Run: `pixi run python crc_gene_analysis.py --genes CDK4 CDK6 CCND1`
3. Present key findings from target evaluation reports:
   - Tumor vs Normal fold changes
   - Significant cohort differences (FDR-corrected)
   - CMS subtype patterns
   - COAD vs READ differences
4. Point user to output files in `./crc_analysis_results/`

## Analysis Pipeline Details

The `crc_gene_analysis.py` script performs:

1. **Data Loading**: Downloads and caches expression/metadata from S3
2. **Sample Filtering**: Identifies CRC samples across TCGA, GTEx, CCLE
3. **Cohort Assignment**: Maps samples to cohorts using pre-computed assignments
4. **Expression Extraction**: Loads gene-specific expression (log2 TPM+1)
5. **Statistical Analysis**:
   - Descriptive statistics per cohort
   - Kruskal-Wallis test across groups
   - Mann-Whitney U tests (tumor vs normal)
   - FDR correction (Benjamini-Hochberg)
6. **Visualization**: Generates all figures
7. **Report Generation**: Creates target evaluation report

## Common Issues

| Issue | Solution |
|-------|----------|
| AWS credentials error | Ensure `~/.aws/credentials` has `[cbg]` profile |
| Gene not found | Check gene symbol spelling; use official HGNC symbols |
| Memory error | Process genes in batches; script uses chunked data loading |
| Slow first run | Data files are cached in `./data_cache/` after first download |
| Cohort file not found | Run: `aws s3 cp s3://onc-compbio/TCGA/crc_cohort_assignments.csv ./ --profile cbg --no-verify-ssl` |
| CMS file not found | Run: `aws s3 cp s3://onc-compbio/TCGA/TCGA_CMS_prediction.csv ./ --profile cbg --no-verify-ssl` |
| Adjacent normal file not found | Run: `aws s3 cp s3://onc-compbio/TCGA/TCGA-COAD-READ-AdjNormal.tsv ./ --profile cbg --no-verify-ssl` |
