---
name: nsclc-protein-analysis
description: Use when analyzing protein expression data for NSCLC targets. Triggers include protein expression analysis for NSCLC/lung cancer, Human Protein Atlas analysis, IHC staining analysis, subcellular localization, modality recommendation for NSCLC targets, or on-target toxicity assessment at protein level. Generates comprehensive protein analysis report with lung toxicity risk, RNA-protein correlation, subcellular location, and modality recommendations.
---

# NSCLC Protein Analysis (Human Protein Atlas)

## Overview

Analyze protein expression data from Human Protein Atlas for non-small cell lung cancer target evaluation. Provides protein-level evidence for on-target toxicity, modality selection, and prognostic association.

## Key Capabilities

- **Normal Tissue IHC**: Respiratory tract on-target toxicity assessment (Lung, Bronchus)
- **RNA-Protein Correlation**: Validate RNA findings at protein level
- **Subcellular Localization**: Modality recommendation (ADC, T-cell engager, small molecule)
- **NSCLC Prognostic Association**: Survival correlation in LUAD/LUSC
- **Tumor IHC + CPTAC**: Tumor protein expression validation

## Data Sources

### Human Protein Atlas v25 (Preprocessed for NSCLC)

| File | Description | Rows |
|------|-------------|------|
| `nsclc_normal_ihc.tsv` | Normal tissue IHC (respiratory + safety organs) | ~636K |
| `nsclc_rna_tissue.tsv` | RNA expression for correlation | ~222K |
| `nsclc_prognostic.tsv` | LUAD/LUSC prognostic data | ~80K |
| `nsclc_cancer_ihc.tsv` | Lung cancer IHC | ~15K |
| `nsclc_cptac.tsv` | CPTAC proteomics (Lung AC/SQCC) | ~22K |
| `subcellular_location.tsv` | Subcellular localization | ~14K |

## Output Metrics

### 1. Respiratory Tract On-Target Toxicity

| Risk Level | Criteria | Interpretation |
|------------|----------|----------------|
| **LOW** | No High/Medium in Lung/Bronchus epithelial cells | Favorable safety profile |
| **MEDIUM** | Medium expression in respiratory tract | Monitor for pulmonary AEs |
| **HIGH** | High expression in Lung/Bronchus | Pulmonary toxicity concern |

### 2. Subcellular Location → Modality Recommendation

| Location | Recommended Modalities | Suitability |
|----------|----------------------|-------------|
| **Plasma membrane** | ADC, T-cell engager, CAR-T, Naked Ab | HIGH |
| **Cell Junctions** | ADC, T-cell engager | HIGH |
| **Cytosol** | Small molecule, PROTAC | MEDIUM |
| **Vesicles** | ADC (internalization) | MEDIUM |
| **Nucleoplasm** | Small molecule only | LOW |
| **ER/Golgi** | Small molecule only | LOW |

### 3. NSCLC Prognostic Association

Based on TCGA survival analysis for:
- Lung Adenocarcinoma (LUAD)
- Lung Squamous Cell Carcinoma (LUSC)

## Implementation

### Step 0: Setup Environment

```bash
if [ ! -f "pixi.toml" ]; then
    cp "$SKILL_BASE_DIR/pixi.toml" ./
    cp "$SKILL_BASE_DIR/pixi.lock" ./
fi
pixi install
```

### Step 1: Run Analysis

```bash
# Full analysis
pixi run python "$SKILL_BASE_DIR/nsclc_protein_analysis.py" --gene CDCP1 \
    --data-dir /path/to/HPA/nsclc \
    --output-dir ./nsclc_protein_results

# Example with default paths
pixi run python "$SKILL_BASE_DIR/nsclc_protein_analysis.py" --gene CDCP1
```

### Script Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--gene` | Yes | Gene symbol (e.g., CDCP1, EGFR) |
| `--data-dir` | No | Path to NSCLC-preprocessed HPA data |
| `--output-dir` | No | Output directory (default: ./nsclc_protein_results) |

## Output Files

| File | Description |
|------|-------------|
| `{GENE}_nsclc_protein_report.md` | Full markdown report |
| `{GENE}_nsclc_protein_analysis.png` | 6-panel summary figure |
| `{GENE}_nsclc_protein_summary.yaml` | Structured data for integration |

## Integration with Target Evaluation

This skill integrates with the target-evaluation workflow as Step 3 (Protein Analysis):

```
Step 1: Risk Assessment (literature)
Step 2: RNA Analysis (nsclc-bulk-rna-analysis)
Step 3: Protein Analysis (nsclc-protein-analysis) ← THIS SKILL
Step 4: ScholarEval (integrates RNA + Protein)
Step 5: Report Generation
```

### YAML Output for Integration

The `{GENE}_nsclc_protein_summary.yaml` provides structured data:

```yaml
gene: CDCP1
disease: NSCLC
on_target_toxicity:
  lung_toxicity_risk: MEDIUM
  overall_toxicity_risk: MEDIUM
  lung_expression: Medium
subcellular_location:
  main_locations: [Nucleoplasm, Vesicles]
  is_surface_target: false
  recommended_modalities: [ADC, Small molecule]
  modality_suitability: MEDIUM
prognostic:
  is_prognostic: true
  direction: unfavorable
  luad: {cancer: 'Lung Adenocarcinoma (TCGA)', direction: unfavorable}
  lusc: {cancer: 'Lung Squamous Cell Carcinoma (TCGA)', direction: unfavorable}
```

## Example Results

### CDCP1

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Lung Toxicity Risk | **MEDIUM** | Medium expression in lung epithelium |
| Surface Target | **No** | Vesicles/Nucleoplasm (verify trafficking) |
| Recommended Modality | **ADC** | May internalize via vesicles |
| NSCLC Prognostic | Yes (unfavorable) | Validates disease relevance |

### EGFR

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Lung Toxicity Risk | **HIGH** | High expression in lung epithelium |
| Surface Target | **Yes** | Plasma membrane |
| Recommended Modality | **ADC, TKI** | Surface target, but toxicity concern |
| NSCLC Prognostic | Yes | Well-established NSCLC driver |

## Data Preprocessing

NSCLC-specific HPA data is preprocessed from full HPA v25 using:

```bash
cd /path/to/HPA
pixi run python preprocess_hpa_nsclc.py --input-dir ./v25 --output-dir ./nsclc
```

This reduces data size by ~70% for faster loading.
