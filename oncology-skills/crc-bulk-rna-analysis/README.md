# CRC Bulk RNA Analysis

Comprehensive gene expression analysis for colorectal cancer combining TCGA raw expression with Tempus real-world data (>200,000 patients).

## Key Features

- **On-Target Toxicity Assessment**: Tumor vs Adjacent Normal (primary safety metric)
- **iDAS Strategic Alignment**: Automatic whitespace scoring
- **Tempus RWD Integration**: Line-of-therapy stratified expression
- **8-Panel Visualization**: Publication-ready comprehensive figures

## Usage

```bash
# Full analysis (TCGA + Tempus)
pixi run python crc_comprehensive_analysis.py --genes TNFRSF12A

# TCGA only
pixi run python crc_comprehensive_analysis.py --genes TNFRSF12A --skip-tempus
```

## TCGA Cohorts

| Cohort | Definition | iDAS Priority |
|--------|------------|---------------|
| TCGA_RASMut_MSS | RAS-mutant, MSS | Yes |
| TCGA_RASWT_MSS | RAS wild-type, MSS | No |
| TCGA_Resectable | Stage I/II | Yes |
| TCGA_MSIH | MSI-H | No |

## Tempus Cohorts (iDAS-aligned)

| Cohort | N Samples | iDAS Alignment |
|--------|-----------|----------------|
| Tempus_RASMut_MSS_3Lplus | ~26,000 | **RAS mutant refractory** |
| Tempus_MSS_3Lplus | ~40,000 | **Chemorefractory 3L+** |
| Tempus_RASMut_MSS_1L2L | ~85,000 | RAS mutant frontline |

## CMS Subtypes

| Subtype | Name | Characteristics |
|---------|------|-----------------|
| CMS1 | MSI Immune | Hypermutated, immune infiltration |
| CMS2 | Canonical | WNT/MYC activation |
| CMS3 | Metabolic | KRAS mutations |
| CMS4 | Mesenchymal | EMT, poor prognosis |

## Output Files

| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel expression figure |
| `{GENE}_comprehensive_report.md` | Full analysis report |
| `{GENE}_idas_assessment.yaml` | iDAS alignment data |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistics |

## Data Sources

- **TCGA COAD/READ**: Tumor and adjacent normal (Omicsoft reprocessed)
- **GTEx**: Normal colon tissue
- **CCLE**: CRC cell lines
- **Tempus**: Real-world expression data with treatment history
