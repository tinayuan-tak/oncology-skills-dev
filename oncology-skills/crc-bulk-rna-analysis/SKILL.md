---
name: crc-bulk-rna-analysis
description: Use when analyzing gene expression in colorectal cancer. Triggers include gene expression analysis for CRC, TCGA COAD/READ analysis, CRC cell lines, CMS subtype comparison, tumor vs normal colon comparison, target evaluation report, Tempus RWD analysis, iDAS alignment, or any gene-level analysis in colorectal cancer context. Generates comprehensive expression analysis with TCGA + Tempus data, iDAS strategic alignment, and publication-ready figures.
---

# CRC Comprehensive Gene Expression Analysis

## Overview

Analyze gene expression across colorectal cancer (CRC) using integrated TCGA and Tempus real-world data. Generates comprehensive target evaluation reports with iDAS strategic alignment assessment, on-target toxicity analysis, and publication-ready figures.

## Key Capabilities

- **TCGA Raw Expression**: Tumor vs Adjacent Normal (primary on-target toxicity metric)
- **Tempus RWD**: >200,000 patients with line-of-therapy stratification
- **iDAS Alignment**: Automatic whitespace scoring for strategic prioritization
- **CMS Subtype Analysis**: CMS1-4 stratification
- **Normal Tissue Comparisons**: TCGA Adjacent Normal, GTEx Normal Colon
- **Cell Line Analysis**: CCLE CRC cell line expression

## Data Sources

### TCGA/GTEx/CCLE (Raw Expression)
- **Source**: `s3://onc-compbio/omicsoft_oncoland_data`
- **Use**: Tumor vs Adjacent Normal comparison (primary safety metric)
- **Format**: TPM values, log2-transformed during analysis

### Tempus RWD (Pre-computed Summaries)
- **Source**: `s3://onc-compbio/Tempus/crc`
- **Use**: Line-of-therapy stratified expression, chemorefractory population
- **Sample Size**: >200,000 CRC patients

### Required Annotation Files (Auto-downloaded from S3)
| File | S3 Path | Description |
|------|---------|-------------|
| `gene_annotation.tsv.gz` | `s3://onc-compbio/omicsoft_oncoland_data/` | Gene symbol to index mapping |
| `tcga_metadata.tsv.gz` | `s3://onc-compbio/omicsoft_oncoland_data/` | TCGA sample metadata |
| `gtex_metadata.tsv.gz` | `s3://onc-compbio/omicsoft_oncoland_data/` | GTEx sample metadata |
| `ccle_metadata.tsv.gz` | `s3://onc-compbio/omicsoft_oncoland_data/` | CCLE sample metadata |

## Cohort Definitions

### TCGA Cohorts (Unified Naming)
| Cohort | Legacy | Definition | iDAS Priority |
|--------|--------|------------|---------------|
| **TCGA_RASMut_MSS** | 2A | RAS-mutant, MSS | Yes |
| **TCGA_RASWT_MSS** | 2B | RAS wild-type, MSS | No |
| **TCGA_Resectable** | 4 | Early Stage I/II | Yes |
| **TCGA_MSS_All** | 5 | All MSS samples | No |
| **TCGA_MSIH** | 6 | MSI-H | No |

### Tempus Cohorts (iDAS-aligned)
| Cohort | N Samples | iDAS Alignment |
|--------|-----------|----------------|
| Tempus_RASMut_MSS_1L2L | ~85,000 | RAS mutant frontline |
| **Tempus_RASMut_MSS_3Lplus** | ~26,000 | **RAS mutant refractory** |
| **Tempus_MSS_3Lplus** | ~40,000 | **Chemorefractory 3L+** |
| Tempus_RASWT_MSS_1L2L | ~59,000 | Contrast group |

### CMS Subtypes
- **CMS1**: MSI Immune (hypermutated)
- **CMS2**: Canonical (WNT/MYC)
- **CMS3**: Metabolic (KRAS)
- **CMS4**: Mesenchymal (EMT)

## Implementation

### Step 0: Setup Pixi Environment

```bash
# Get the skill base directory from the loaded skill context
# SKILL_BASE_DIR is provided when the skill is invoked

# Check if pixi is installed
if ! command -v pixi &> /dev/null; then
    echo "ERROR: pixi is not installed. Install it first:"
    echo "  curl -fsSL https://pixi.sh/install.sh | bash"
    exit 1
fi

# Copy pixi files to user's workspace (if not already present)
if [ ! -f "pixi.toml" ]; then
    cp "$SKILL_BASE_DIR/pixi.toml" ./
    cp "$SKILL_BASE_DIR/pixi.lock" ./
fi

# Install pixi environment
pixi install
```

### Step 1: Run the Analysis Script

**IMPORTANT**: Use `crc_comprehensive_analysis.py` - the unified analysis pipeline.

```bash
# Copy the analysis script from skill directory
cp "$SKILL_BASE_DIR/crc_comprehensive_analysis.py" ./

# Full analysis (TCGA + Tempus) - RECOMMENDED
pixi run python crc_comprehensive_analysis.py --genes TNFRSF12A

# Multiple genes
pixi run python crc_comprehensive_analysis.py --genes TNFRSF12A CDCP1 EPCAM

# Custom output directory
pixi run python crc_comprehensive_analysis.py --genes TNFRSF12A --output-dir ./my_results

# TCGA only (skip Tempus)
pixi run python crc_comprehensive_analysis.py --genes TNFRSF12A --skip-tempus

# Tempus only (skip TCGA raw processing)
pixi run python crc_comprehensive_analysis.py --genes TNFRSF12A --skip-tcga
```

### Script Usage

```
Usage:
    python crc_comprehensive_analysis.py --genes TNFRSF12A
    python crc_comprehensive_analysis.py --genes TNFRSF12A CDCP1 --output-dir ./results
    python crc_comprehensive_analysis.py --genes TNFRSF12A --skip-tempus

Arguments:
    --genes          Gene symbol(s) to analyze (space-separated)
    --output-dir     Output directory (default: ./crc_comprehensive_results)
    --skip-tcga      Skip TCGA raw expression processing
    --skip-tempus    Skip Tempus RWD analysis
```

## Output Files

For each gene, the analysis generates:

| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel figure: TCGA cohorts, toxicity, Tempus LOT, iDAS, RAS status, CMS, alignment, recommendation |
| `{GENE}_comprehensive_report.md` | Full report with TCGA + Tempus evidence, iDAS alignment |
| `{GENE}_idas_assessment.yaml` | Structured iDAS whitespace alignment assessment |
| `{GENE}_tcga_statistics.csv` | TCGA cohort expression statistics |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistical comparisons |

### Individual High-Resolution Figures

Each panel is also saved as a separate 300 DPI PNG file in the `figures/` subfolder:

| File | Description |
|------|-------------|
| `figures/{GENE}_panel_A_tcga_cohorts.png` | TCGA expression by cohort |
| `figures/{GENE}_panel_B_toxicity.png` | On-target toxicity assessment |
| `figures/{GENE}_panel_C_lot.png` | Tempus line of therapy |
| `figures/{GENE}_panel_D_idas_cohorts.png` | Tempus iDAS-aligned cohorts |
| `figures/{GENE}_panel_E_ras_status.png` | RAS mutation status |
| `figures/{GENE}_panel_F_cms.png` | CMS subtype expression |
| `figures/{GENE}_panel_G_idas_summary.png` | iDAS alignment summary table |
| `figures/{GENE}_panel_H_recommendation.png` | Recommendation summary |

## iDAS Strategic Alignment

The script automatically assesses alignment with iDAS priority whitespaces:

| Priority Whitespace | Metric | Strong | Moderate | Weak |
|---------------------|--------|--------|----------|------|
| Chemorefractory 3L+ | Tempus 3L+ expression | >4 log2TPM | 2-4 log2TPM | <2 log2TPM |
| RAS Mutant Frontline | Tempus RAS-mut 1L-2L | >4 log2TPM | 2-4 log2TPM | <2 log2TPM |
| RAS Mutant Refractory | Tempus RAS-mut 3L+ | >4 log2TPM | 2-4 log2TPM | <2 log2TPM |
| Resectable | TCGA Stage I/II | >4 log2TPM | 2-4 log2TPM | <2 log2TPM |

## On-Target Toxicity Assessment

**Primary metric**: Tumor vs Adjacent Normal expression

| Risk Level | Log2FC vs Adjacent | Interpretation |
|------------|-------------------|----------------|
| **LOW** | >1.5 (tumor >> normal) | Tumor-specific, favorable safety |
| **MEDIUM** | 0.5-1.5 | Moderate tumor enrichment |
| **HIGH** | <0.5 or negative | Normal tissue expression, toxicity risk |

## Quick Start Example

User: "Analyze TNFRSF12A expression in CRC"

Response:
1. Setup pixi environment and copy script
2. Run: `pixi run python crc_comprehensive_analysis.py --genes TNFRSF12A`
3. Present key findings:
   - Tumor vs Normal: +2.96 log2FC (7.8x higher in tumor) → **LOW toxicity risk**
   - iDAS Alignment: **High** (strong in all priority populations)
   - Recommendation: **PRIORITY**
4. Point user to output files

## Example Results

| Gene | Tumor vs Normal | Toxicity Risk | iDAS Alignment | Recommendation |
|------|-----------------|---------------|----------------|----------------|
| TNFRSF12A | +2.96 (7.8x ↑) | **LOW** | High | **PRIORITY** |
| CDCP1 | -0.41 (tumor < normal) | **HIGH** | High | **CONDITIONAL NO-GO** |

## Common Issues

| Issue | Solution |
|-------|----------|
| AWS credentials error | Ensure `~/.aws/credentials` has `[cbg]` profile |
| Gene not found | Check gene symbol spelling; use official HGNC symbols |
| Memory error | Process genes in batches |
| Slow first run | Annotation files are cached in `./data_cache/` after first download |
