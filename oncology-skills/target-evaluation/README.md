# Target Evaluation Skill

Comprehensive 5-step therapeutic target evaluation workflow for oncology indications.

## Overview

This parent skill orchestrates the full target evaluation pipeline:

1. **Risk Assessment Framework** - Define 6 risk categories
2. **PubMed Literature Search** - Guided by risk categories
3. **Expression Analysis** - Disease-specific bulk RNA analysis
4. **ScholarEval Scoring** - 8-dimension target scoring
5. **Report Generation** - Integrated markdown + professional PDF

## Usage

```
Evaluate {GENE} as a target in {disease}
```

**Supported diseases:**
- `crc` - Colorectal Cancer
- `nsclc` - Non-Small Cell Lung Cancer

## Key Features

- **Tumor vs Adjacent Normal** as primary differential expression metric
- **Disease-agnostic orchestration** - add new diseases via config files
- **Professional 13-page PDF reports** with high-resolution figures
- **Standardized markdown format** for reliable parsing

## Files

| File | Description |
|------|-------------|
| `SKILL.md` | Main skill definition with full workflow |
| `generate_target_report_pdf.py` | PDF report generator (300 DPI) |
| `configs/crc.yaml` | CRC-specific configuration |
| `configs/nsclc.yaml` | NSCLC-specific configuration |
| `pixi.toml` | Python dependencies |

## Adding New Diseases

1. Create `oncology-skills:{disease}-bulk-rna-analysis` skill
2. Add `configs/{disease}.yaml` with disease-specific settings
3. Update SKILL.md routing table

## Output

- `{GENE}_integrated_target_report.md` - Source markdown
- `{GENE}_final_risk_report.pdf` - Professional PDF (13 pages)
- Expression figures and statistical results
