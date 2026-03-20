---
name: nsclc-bulk-rna-analysis
description: Use when analyzing bulk gene expression in non-small cell lung cancer. Triggers include gene expression analysis for NSCLC, TCGA LUAD/LUSC analysis, lung cancer cell lines, histology subtype comparison, tumor vs normal lung comparison, target evaluation report, Tempus RWD analysis, iDAS alignment, EGFR/KRAS/ALK stratification, or any gene-level analysis in NSCLC context. Generates comprehensive expression analysis with TCGA + Tempus data, iDAS strategic alignment, and publication-ready figures.
---

# NSCLC Comprehensive Gene Expression Analysis

## Overview

Analyze gene expression across non-small cell lung cancer (NSCLC) using integrated TCGA and Tempus real-world data. Generates comprehensive target evaluation reports with iDAS strategic alignment assessment, on-target toxicity analysis, and publication-ready figures.

## Key Capabilities

- **TCGA Raw Expression**: Tumor vs Adjacent Normal (primary on-target toxicity metric)
- **Tempus RWD**: >1,800 patients with line-of-therapy and biomarker stratification
- **iDAS Alignment**: Automatic whitespace scoring for strategic prioritization
- **Histology Analysis**: LUAD vs LUSC comparison
- **Biomarker Stratification**: EGFR, KRAS, STK11, KEAP1, ALK status
- **Normal Tissue Comparisons**: TCGA Adjacent Normal, GTEx Normal Lung
- **Cell Line Analysis**: CCLE NSCLC cell line expression

## Data Sources

### TCGA/GTEx/CCLE (Raw Expression)
- **Source**: `s3://onc-compbio/omicsoft_oncoland_data`
- **Use**: Tumor vs Adjacent Normal comparison (primary safety metric)
- **Format**: TPM values, log2-transformed during analysis

### Tempus RWD (Pre-computed Summaries)
- **Source**: Local path `/Users/eta3879/Documents/Projects/ODDU/Tempus/TAK_LACE_Q12026_NSCLC_cohort_1/summary/`
- **Use**: Line-of-therapy stratified expression, biomarker-defined populations
- **Sample Size**: ~1,867 patients, ~3,500 samples

### Required Annotation Files (Auto-downloaded from S3)
| File | S3 Path | Description |
|------|---------|-------------|
| `gene_annotation.tsv.gz` | `s3://onc-compbio/omicsoft_oncoland_data/` | Gene symbol to index mapping |
| `tcga_metadata.tsv.gz` | `s3://onc-compbio/omicsoft_oncoland_data/` | TCGA sample metadata |
| `gtex_metadata.tsv.gz` | `s3://onc-compbio/omicsoft_oncoland_data/` | GTEx sample metadata |
| `ccle_metadata.tsv.gz` | `s3://onc-compbio/omicsoft_oncoland_data/` | CCLE sample metadata |

## Cohort Definitions

### TCGA Cohorts
| Cohort | Definition | Use Case |
|--------|------------|----------|
| **TCGA_LUAD** | Lung adenocarcinoma tumors | Primary histology |
| **TCGA_LUSC** | Lung squamous cell carcinoma | Primary histology |
| **TCGA_NSCLC_All** | All NSCLC tumors (LUAD + LUSC) | Pan-NSCLC |
| **TCGA_Adjacent** | Adjacent normal lung | On-target toxicity |
| **GTEx_Lung** | Normal lung tissue | Baseline expression |
| **CCLE_NSCLC** | NSCLC cell lines | In vitro validation |

### Tempus Cohorts (iDAS-aligned)
| Cohort | N Samples | iDAS Alignment |
|--------|-----------|----------------|
| **Tempus_2L_NonAGA** | 518 | **2L Non-AGA (IO-experienced)** |
| **Tempus_2L_EGFR** | 38 | **2L EGFR Mutant (post-TKI)** |
| **Tempus_1L2L_KRAS** | 1,021 | **1L/2L KRAS Mutant** |
| Tempus_Overall | 2,100 | All samples |
| Tempus_1L | 2,611 | First-line |
| Tempus_2L | 628 | Second-line |
| Tempus_3L+ | 328 | Third-line+ |

### Biomarker Stratifications
| Status | Mutant | Wild-Type |
|--------|--------|-----------|
| **KRAS** | 1,133 samples | 2,434 samples |
| **EGFR** | 121 samples | 3,446 samples |
| **STK11** | 551 samples | 3,016 samples |
| **KEAP1** | 346 samples | 3,221 samples |
| **AGA** | 452 samples (Non-AGA: 3,115) | - |

### AGA (Actionable Genomic Alterations)
Includes: EGFR mutations, ALK/ROS1/RET fusions, BRAF V600E, MET exon 14, NTRK fusions, KRAS G12C (treated), HER2 mutations

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

**IMPORTANT**: Use `nsclc_comprehensive_analysis.py` - the unified analysis pipeline.

```bash
# Copy the analysis script from skill directory
cp "$SKILL_BASE_DIR/nsclc_comprehensive_analysis.py" ./

# Full analysis (TCGA + Tempus) - RECOMMENDED
pixi run python nsclc_comprehensive_analysis.py --genes EGFR

# Multiple genes
pixi run python nsclc_comprehensive_analysis.py --genes EGFR KRAS STK11

# Custom output directory
pixi run python nsclc_comprehensive_analysis.py --genes EGFR --output-dir ./my_results

# TCGA only (skip Tempus)
pixi run python nsclc_comprehensive_analysis.py --genes EGFR --skip-tempus

# Tempus only (skip TCGA raw processing)
pixi run python nsclc_comprehensive_analysis.py --genes EGFR --skip-tcga
```

### Script Usage

```
Usage:
    python nsclc_comprehensive_analysis.py --genes EGFR
    python nsclc_comprehensive_analysis.py --genes EGFR KRAS --output-dir ./results
    python nsclc_comprehensive_analysis.py --genes EGFR --skip-tempus

Arguments:
    --genes          Gene symbol(s) to analyze (space-separated)
    --output-dir     Output directory (default: ./nsclc_comprehensive_results)
    --skip-tcga      Skip TCGA raw expression processing
    --skip-tempus    Skip Tempus RWD analysis
```

## Output Files

For each gene, the analysis generates:

| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel figure: LUAD/LUSC, toxicity, LOT, iDAS, KRAS, EGFR, STK11/KEAP1, recommendation |
| `{GENE}_comprehensive_report.md` | Full report with TCGA + Tempus evidence, iDAS alignment |
| `{GENE}_idas_assessment.yaml` | Structured iDAS whitespace alignment assessment |
| `{GENE}_tcga_statistics.csv` | TCGA cohort expression statistics |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistical comparisons |

## iDAS NSCLC Strategic Alignment

The script automatically assesses alignment with iDAS priority whitespaces:

| Priority Whitespace | Cohort | Strong | Moderate | Weak |
|---------------------|--------|--------|----------|------|
| **2L Non-AGA** | Tempus 2L Non-AGA (n=518) | >4 log2TPM | 2-4 log2TPM | <2 log2TPM |
| **2L EGFR Mutant** | Tempus 2L EGFR (n=38) | >4 log2TPM | 2-4 log2TPM | <2 log2TPM |
| **1L/2L KRAS Mutant** | Tempus 1L2L KRAS (n=1,021) | >4 log2TPM | 2-4 log2TPM | <2 log2TPM |

### iDAS Context
- **2L Non-AGA**: Patients without actionable genomic alterations who progressed on IO ± chemo
- **2L EGFR Mutant**: EGFR+ patients post-TKI failure
- **1L/2L KRAS Mutant**: KRAS-mutant population (G12C and non-G12C)

## On-Target Toxicity Assessment

**Primary metric**: Tumor vs Adjacent Normal expression

| Risk Level | Log2FC vs Adjacent | Interpretation |
|------------|-------------------|----------------|
| **LOW** | >1.5 (tumor >> normal) | Tumor-specific, favorable safety |
| **MEDIUM** | 0.5-1.5 | Moderate tumor enrichment |
| **HIGH** | <0.5 or negative | Normal tissue expression, toxicity risk |

## Quick Start Example

User: "Analyze EGFR expression in NSCLC"

Response:
1. Setup pixi environment and copy script
2. Run: `pixi run python nsclc_comprehensive_analysis.py --genes EGFR`
3. Present key findings:
   - LUAD vs LUSC comparison
   - Tumor vs Normal fold change
   - iDAS whitespace alignment
   - Biomarker stratification (KRAS, STK11, KEAP1 co-mutations)
4. Point user to output files

## Biomarker Considerations

### EGFR Status
- **EGFR Mutant**: Small subset (n=121), TKI-responsive
- **EGFR WT**: Majority, includes KRAS-mutant and other drivers

### KRAS Mutations
- **KRAS G12C**: Targetable with sotorasib/adagrasib (n=367)
- **Non-G12C KRAS**: Unmet need population (n=766)

### Resistance Markers
- **STK11 Mutant**: Associated with IO resistance, poor prognosis
- **KEAP1 Mutant**: Often co-occurs with STK11, metabolic alterations

## Common Issues

| Issue | Solution |
|-------|----------|
| AWS credentials error | Ensure `~/.aws/credentials` has `[cbg]` profile |
| Gene not found | Check gene symbol spelling; use official HGNC symbols |
| Memory error | Process genes in batches |
| Slow first run | Annotation files are cached in `./data_cache/` after first download |
| Tempus data not found | Check local path exists: `/Users/eta3879/Documents/Projects/ODDU/Tempus/TAK_LACE_Q12026_NSCLC_cohort_1/summary/` |
