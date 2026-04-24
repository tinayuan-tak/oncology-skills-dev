---
name: analysis-bulk-rna-crc
description: |
  Use this skill when the user asks to analyze gene expression in colorectal cancer,
  CRC bulk RNA-seq analysis, TCGA COAD/READ expression, tumor vs normal colon comparison,
  CRC cell line expression, CMS subtype analysis, or Tempus RWD CRC analysis.
  Provides comprehensive expression analysis with TCGA + Tempus data (>200K patients),
  iDAS strategic alignment, on-target toxicity assessment, and publication-ready figures.
  Do NOT use for single-cell analysis - use analysis-sc-rna-crc instead.
  Example queries: "analyze TNFRSF12A in CRC", "CRC expression for CDK4", "tumor vs normal colon for MET".
metadata:
  version: 1.0.0
  owner: ming-ju.tsai@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg (for S3 data access)
---

# CRC Comprehensive Gene Expression Analysis

## Overview

Analyze gene expression across colorectal cancer (CRC) using integrated TCGA and Tempus real-world data. Generates comprehensive target evaluation reports with iDAS strategic alignment assessment, on-target toxicity analysis, and publication-ready figures.

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
uv run python scripts/crc_comprehensive_analysis.py --genes TNFRSF12A

# Multiple genes
uv run python scripts/crc_comprehensive_analysis.py --genes TNFRSF12A CDCP1 EPCAM

# Custom output directory
uv run python scripts/crc_comprehensive_analysis.py --genes TNFRSF12A --output-dir ./my_results
```

## Core Capabilities

### Tumor vs Normal Expression Analysis
Primary safety metric for on-target toxicity assessment using TCGA adjacent normal samples.

### Tempus RWD Integration
Expression analysis across >200,000 CRC patients with line-of-therapy stratification.

### iDAS Strategic Alignment
Automatic whitespace scoring for Takeda's iDAS priority populations.

### CMS Subtype Analysis
Expression stratified by CMS1-4 molecular subtypes.

## Data Sources

| Source | Description | Access |
|--------|-------------|--------|
| TCGA COAD/READ | Tumor + adjacent normal | `s3://onc-compbio/omicsoft_oncoland_data` |
| GTEx | Normal colon baseline | `s3://onc-compbio/omicsoft_oncoland_data` |
| CCLE | CRC cell lines | `s3://onc-compbio/omicsoft_oncoland_data` |
| Tempus RWD | >200K patients, LOT stratified | `s3://onc-compbio/Tempus/crc` |

## Output Files

For each gene analyzed:

| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel summary figure |
| `{GENE}_comprehensive_report.md` | Full analysis report |
| `{GENE}_idas_assessment.yaml` | iDAS alignment scores |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistics |

## Advanced Features

For detailed documentation, see:
- **Cohort Definitions**: See [references/cohorts.md](references/cohorts.md)
- **iDAS Alignment**: See [references/idas.md](references/idas.md)
- **Toxicity Assessment**: See [references/toxicity.md](references/toxicity.md)

## Best Practices

1. **Start with tumor vs normal**: Primary metric for safety assessment
2. **Check iDAS alignment**: Ensures strategic fit with Takeda priorities
3. **Compare across LOT**: Tempus 3L+ population is key for refractory setting

## Limitations

- Requires AWS credentials with S3 access
- Gene symbols must be official HGNC names
- Large expression files cached locally (~500MB first run)

## Related Skills

- `analysis-bulk-rna-nsclc`: For NSCLC expression analysis
- `analysis-sc-rna-crc`: For single-cell CRC analysis
- `workflow-target-evaluation-onc`: For full target evaluation workflow
