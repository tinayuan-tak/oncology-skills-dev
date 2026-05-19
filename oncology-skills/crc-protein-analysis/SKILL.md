---
name: crc-protein-analysis
description:
  Use when analyzing protein expression data for colorectal cancer targets.
  Triggers include protein expression analysis for CRC, Human Protein Atlas
  analysis, IHC staining analysis, subcellular localization, modality
  recommendation for CRC targets, or on-target toxicity assessment at protein
  level. Generates comprehensive protein analysis report with GI toxicity risk,
  RNA-protein correlation, subcellular location, and modality recommendations.
  Do NOT use for RNA differential expression - use crc-bulk-rna-analysis
  instead. Do NOT use for protein structure prediction or AlphaFold modeling -
  use tool-protein-structure-prediction instead. Do NOT use for protein-protein
  interaction networks - use data-kg-interactome instead. Do NOT use for NSCLC
  or other indications - use nsclc-protein-analysis or the corresponding
  disease-specific skill instead.
metadata:
  version: 0.1.0
  owner: ming-ju.tsai@takeda.com
  environment: shared
  requires_preflight: false
---

# CRC Protein Analysis (Human Protein Atlas)

## Overview

Analyze protein expression data from Human Protein Atlas for colorectal cancer target evaluation. Provides protein-level evidence for on-target toxicity, modality selection, and prognostic association.

## Key Capabilities

- **Normal Tissue IHC**: GI tract on-target toxicity assessment (Colon, Rectum, Small intestine)
- **RNA-Protein Correlation**: Validate RNA findings at protein level
- **Subcellular Localization**: Modality recommendation (ADC, T-cell engager, small molecule)
- **CRC Prognostic Association**: Survival correlation in COAD/READ
- **Tumor IHC + CPTAC**: Tumor protein expression validation

## Data Sources

### Human Protein Atlas v25 (Preprocessed for CRC)

| File | Description | Rows |
|------|-------------|------|
| `crc_normal_ihc.tsv` | Normal tissue IHC (GI + safety organs) | ~488K |
| `crc_rna_tissue.tsv` | RNA expression for correlation | ~202K |
| `crc_prognostic.tsv` | COAD/READ prognostic data | ~80K |
| `crc_cancer_ihc.tsv` | Colorectal cancer IHC | ~15K |
| `crc_cptac.tsv` | CPTAC proteomics (Colon AC) | ~7K |
| `subcellular_location.tsv` | Subcellular localization | ~14K |

## Output Metrics

### 1. GI Tract On-Target Toxicity

| Risk Level | Criteria | Interpretation |
|------------|----------|----------------|
| **LOW** | No High/Medium in Colon/Rectum glandular cells | Favorable safety profile |
| **MEDIUM** | Medium expression in GI tract | Monitor for GI AEs |
| **HIGH** | High expression in Colon/Rectum | GI toxicity concern |

### 2. Subcellular Location → Modality Recommendation

| Location | Recommended Modalities | Suitability |
|----------|----------------------|-------------|
| **Plasma membrane** | ADC, T-cell engager, CAR-T, Naked Ab | HIGH |
| **Cell Junctions** | ADC, T-cell engager | HIGH |
| **Cytosol** | Small molecule, PROTAC | MEDIUM |
| **Vesicles** | ADC (internalization) | MEDIUM |
| **Nucleoplasm** | Small molecule only | LOW |
| **ER/Golgi** | Small molecule only | LOW |

### 3. RNA-Protein Concordance

| Concordance | Interpretation |
|-------------|----------------|
| >70% | High confidence in RNA-based target selection |
| 50-70% | Moderate - verify key tissues |
| <50% | Low - protein validation required |

### 4. CRC Prognostic Association

Based on TCGA survival analysis for Colon Adenocarcinoma.

## Prerequisites

This skill requires preprocessed Human Protein Atlas (HPA) v25 data filtered
for CRC-relevant tissues. Six TSV files are expected in `--data-dir`:

| File | Approx. size |
|------|--------------|
| `crc_normal_ihc.tsv` | ~30 MB |
| `crc_rna_tissue.tsv` | ~12 MB |
| `crc_prognostic.tsv` | ~5 MB |
| `crc_cancer_ihc.tsv` | ~1 MB |
| `crc_cptac.tsv` | ~1 MB |
| `subcellular_location.tsv` | ~2 MB |

Total: ~50 MB on disk. Generate from full HPA v25 via `preprocess_hpa_crc.py`
(see "Data Preprocessing" below). No API keys or external credentials required.

## Implementation

### Step 0: Setup Environment

Run pixi from the skill directory (do not copy lockfiles into your CWD):

```bash
cd "$SKILL_BASE_DIR"
pixi install
```

### Step 1: Run Analysis

```bash
# Full analysis
pixi run python "$SKILL_BASE_DIR/crc_protein_analysis.py" --gene TNFRSF12A \
    --data-dir /path/to/HPA/crc \
    --output-dir ./crc_protein_results

# Example with default paths
pixi run python "$SKILL_BASE_DIR/crc_protein_analysis.py" --gene TNFRSF12A
```

### Script Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--gene` | Yes | Gene symbol (e.g., TNFRSF12A, CDCP1) |
| `--data-dir` | No | Path to CRC-preprocessed HPA data |
| `--output-dir` | No | Output directory (default: ./crc_protein_results) |

## Output Files

| File | Description |
|------|-------------|
| `{GENE}_crc_protein_report.md` | Full markdown report |
| `{GENE}_crc_protein_analysis.png` | 6-panel summary figure |
| `{GENE}_crc_protein_summary.yaml` | Structured data for integration |

## Integration with Target Evaluation

This skill integrates with the target-evaluation workflow as Step 3 (Protein Analysis):

```
Step 1: Risk Assessment (literature)
Step 2: RNA Analysis (crc-bulk-rna-analysis)
Step 3: Protein Analysis (crc-protein-analysis) ← THIS SKILL
Step 4: ScholarEval (integrates RNA + Protein)
Step 5: Report Generation
```

### YAML Output for Integration

The `{GENE}_crc_protein_summary.yaml` provides structured data:

```yaml
gene: TNFRSF12A
disease: CRC
on_target_toxicity:
  gi_toxicity_risk: LOW
  overall_toxicity_risk: LOW
  colon_expression: Not detected
subcellular_location:
  main_locations: [Plasma membrane, Cytosol]
  is_surface_target: true
  recommended_modalities: [ADC, T-cell engager, CAR-T]
  modality_suitability: HIGH
prognostic:
  is_prognostic: false
rna_protein_correlation:
  concordance_rate: 0.75
```

## Example Results

### TNFRSF12A (Fn14)

| Metric | Value | Interpretation |
|--------|-------|----------------|
| GI Toxicity Risk | **LOW** | Not detected in colon glandular cells |
| Surface Target | **Yes** | Plasma membrane localized |
| Recommended Modality | **ADC** | Surface target with internalization |
| CRC Prognostic | No | Not prognostic in COAD |

### EPCAM

| Metric | Value | Interpretation |
|--------|-------|----------------|
| GI Toxicity Risk | **HIGH** | High expression in colon epithelium |
| Surface Target | **Yes** | Plasma membrane |
| Recommended Modality | **ADC** | But HIGH toxicity risk |
| CRC Prognostic | Yes (unfavorable) | Validates disease relevance |

## Data Preprocessing

CRC-specific HPA data is preprocessed from full HPA v25 using:

```bash
cd /path/to/HPA
pixi run python preprocess_hpa_crc.py --input-dir ./v25 --output-dir ./crc
```

This reduces data size by ~75% for faster loading.
