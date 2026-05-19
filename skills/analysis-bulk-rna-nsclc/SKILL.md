---
name: analysis-bulk-rna-nsclc
description: |
  Use this skill when the user asks to analyze gene expression in non-small cell lung cancer,
  NSCLC bulk RNA-seq analysis, TCGA LUAD/LUSC expression, tumor vs normal lung comparison,
  NSCLC cell line expression, histology subtype analysis, EGFR/KRAS/STK11/KEAP1 stratification,
  or Tempus RWD NSCLC analysis. Provides comprehensive expression analysis with TCGA + Tempus
  data (~1,800 patients), iDAS strategic alignment, on-target toxicity assessment, and
  publication-ready figures. Do NOT use for single-cell analysis - use analysis-sc-rna-nsclc instead.
  Example queries: "analyze EGFR in NSCLC", "NSCLC expression for MET", "KRAS mutant vs WT expression".
metadata:
  version: 1.0.0
  owner: ming-ju.tsai@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg (for S3 data access)
---

# NSCLC Comprehensive Gene Expression Analysis

## Overview

Analyze gene expression across non-small cell lung cancer (NSCLC) using integrated TCGA and Tempus real-world data. Generates comprehensive target evaluation reports with iDAS strategic alignment assessment, biomarker stratification, on-target toxicity analysis, and publication-ready figures.

## Prerequisites

### Required: AWS Credentials

Ensure AWS credentials are configured for S3 data access:

```bash
# Check if cbg profile exists
cat ~/.aws/credentials | grep -A3 '\[cbg\]'
```

If not configured, add to `~/.aws/credentials`:
```ini
[cbg]
aws_access_key_id = YOUR_ACCESS_KEY
aws_secret_access_key = YOUR_SECRET_KEY
```

### Verify Setup

```bash
cd "<skill_directory>" && uv run python -c "import boto3; boto3.Session(profile_name='cbg').client('s3').head_bucket(Bucket='onc-compbio')"
```

## Quick Start

```bash
# Analyze a single gene
uv run python scripts/nsclc_comprehensive_analysis.py --genes EGFR

# Multiple genes
uv run python scripts/nsclc_comprehensive_analysis.py --genes EGFR KRAS MET

# Custom output directory
uv run python scripts/nsclc_comprehensive_analysis.py --genes EGFR --output-dir ./my_results
```

## Core Capabilities

### Tumor vs Normal Expression Analysis
Primary safety metric for on-target toxicity assessment using TCGA adjacent normal samples.

### Tempus RWD Integration
Expression analysis across ~1,800 NSCLC patients with line-of-therapy and biomarker stratification.

### iDAS Strategic Alignment
Automatic whitespace scoring for Takeda's iDAS priority populations:
- 2L Non-AGA (IO-experienced)
- 2L EGFR Mutant (post-TKI)
- 1L/2L KRAS Mutant

### Biomarker Stratification
Expression by EGFR, KRAS, STK11, KEAP1 mutation status.

## Data Sources

| Source | Description | Access |
|--------|-------------|--------|
| TCGA LUAD/LUSC | Tumor + adjacent normal | `s3://onc-compbio/omicsoft_oncoland_data` |
| GTEx | Normal lung baseline | `s3://onc-compbio/omicsoft_oncoland_data` |
| CCLE | NSCLC cell lines | `s3://onc-compbio/omicsoft_oncoland_data` |
| Tempus RWD | ~1,800 patients, LOT/biomarker stratified | Local path |

## Output Files

For each gene analyzed:

| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel summary figure |
| `{GENE}_comprehensive_report.md` | Full analysis report |
| `{GENE}_idas_assessment.yaml` | iDAS alignment scores |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistics |
| `{GENE}_tcga_mutation_statistics.csv` | Mutation status expression |
| `{GENE}_subgroup_suitability.csv` | Subgroup suitability scores |

## Advanced Features

For detailed documentation, see:
- **Cohort Definitions**: See [references/cohorts.md](references/cohorts.md)
- **iDAS Alignment**: See [references/idas.md](references/idas.md)
- **Biomarker Analysis**: See [references/biomarkers.md](references/biomarkers.md)

## Best Practices

1. **Start with tumor vs normal**: Primary metric for safety assessment
2. **Check iDAS alignment**: Ensures strategic fit with Takeda priorities
3. **Review biomarker stratification**: KRAS/EGFR/STK11/KEAP1 status affects target utility

## Limitations

- Requires AWS credentials with S3 access
- Gene symbols must be official HGNC names
- Large expression files cached locally (~500MB first run)
- Tempus data requires local path access

## Related Skills

- `analysis-bulk-rna-crc`: For CRC expression analysis
- `analysis-sc-rna-nsclc`: For single-cell NSCLC analysis
- `workflow-target-evaluation-onc`: For full target evaluation workflow
