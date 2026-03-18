# Oncology Skills for Claude Code

A collection of Claude Code skills for oncology target evaluation and RNA-seq analysis, covering both bulk and single-cell transcriptomics for colorectal cancer (CRC) and non-small cell lung cancer (NSCLC).

## Available Skills

| Skill | Description | Status |
|-------|-------------|--------|
| [target-evaluation](oncology-skills/target-evaluation/) | Full 4-step therapeutic target evaluation workflow with PDF report generation | Implemented |
| [crc-bulk-rna-analysis](oncology-skills/crc-bulk-rna-analysis/) | Comprehensive CRC analysis with TCGA + Tempus RWD (>200K patients), iDAS alignment | Implemented |
| [crc-sc-rna-analysis](oncology-skills/crc-sc-rna-analysis/) | Single-cell RNA-seq analysis for colorectal cancer | Placeholder |
| [nsclc-bulk-rna-analysis](oncology-skills/nsclc-bulk-rna-analysis/) | Bulk RNA-seq analysis for NSCLC (TCGA LUAD/LUSC) | Placeholder |
| [nsclc-sc-rna-analysis](oncology-skills/nsclc-sc-rna-analysis/) | Single-cell RNA-seq analysis for NSCLC | Placeholder |

## Target Evaluation Workflow

The `target-evaluation` skill provides a comprehensive 4-step pipeline:

```
┌─────────────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. DRUG TARGET RISK     │ ──▶ │ 2. EXPRESSION   │ ──▶ │ 3. SCHOLAREVAL  │ ──▶ │ 4. REPORT       │
│    ASSESSMENT           │     │    ANALYSIS     │     │    SCORING      │     │    + PDF        │
│                         │     │                 │     │                 │     │                 │
│ Risk framework +        │     │ TCGA + Tempus   │     │ 8-dimension     │     │ Integrated      │
│ PubMed literature       │     │ bulk RNA skill  │     │ weighted score  │     │ markdown + PDF  │
└─────────────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Key Features

- **6-category risk assessment**: Biological, Druggability, Translational, Clinical, Safety, Commercial
- **8-dimension ScholarEval scoring**: Weighted target evaluation framework
- **Primary metric**: Tumor vs Adjacent Normal expression (predicts on-target toxicity)
- **iDAS strategic alignment**: Automatic whitespace scoring for CRC
- **Tempus RWD integration**: >200,000 patients with line-of-therapy stratification
- **Output**: 13-page professional PDF report with Go/No-Go recommendation

## Example Results

| Target | Disease | Tumor vs Normal | ScholarEval | Risk | Recommendation |
|--------|---------|-----------------|-------------|------|----------------|
| **TNFRSF12A (Fn14)** | CRC | **+2.96 log2FC (7.8x ↑)** | 4.15/5.0 | LOW-MEDIUM | **GO** |
| **CDCP1** | CRC | **-0.41 log2FC (tumor < normal)** | 2.75/5.0 | HIGH | **NO-GO** |

**Key insight:** Tumor vs Adjacent Normal expression is the critical metric for predicting on-target toxicity. TNFRSF12A shows excellent tumor specificity, while CDCP1 fails due to higher expression in normal colon epithelium.

## Repository Structure

```
.
├── .claude-plugin/
│   ├── marketplace.json          # Plugin metadata and skill registration
│   └── plugin.json               # Plugin configuration
├── oncology-skills/
│   ├── target-evaluation/
│   │   ├── SKILL.md              # 4-step workflow definition
│   │   ├── README.md
│   │   ├── generate_target_report_pdf.py
│   │   ├── pixi.toml
│   │   ├── reference/
│   │   │   ├── risk_assessment_template_crc.md
│   │   │   └── risk_assessment_template_nsclc.md
│   │   └── configs/
│   │       ├── crc.yaml
│   │       └── nsclc.yaml
│   ├── crc-bulk-rna-analysis/
│   │   ├── SKILL.md
│   │   ├── README.md
│   │   ├── crc_comprehensive_analysis.py   # Unified TCGA + Tempus analysis
│   │   └── pixi.toml
│   ├── crc-sc-rna-analysis/
│   │   └── SKILL.md
│   ├── nsclc-bulk-rna-analysis/
│   │   └── SKILL.md
│   └── nsclc-sc-rna-analysis/
│       └── SKILL.md
└── README.md
```

## Installation

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd rnd-computational-biology-oncology-claude-oncology-skills
```

### Step 2: Register the Marketplace

In Claude Code, run:
```
/plugin marketplace add /path/to/rnd-computational-biology-oncology-claude-oncology-skills
```

### Step 3: Install the Plugin

```
/plugin install oncology-skills@claude-oncology-skills
```

### Step 4: Reload Plugins

```
/reload-plugins
```

### Verify Installation

The skills should appear in the available skills list:
- `oncology-skills:target-evaluation`
- `oncology-skills:crc-bulk-rna-analysis`
- `oncology-skills:crc-sc-rna-analysis`
- `oncology-skills:nsclc-bulk-rna-analysis`
- `oncology-skills:nsclc-sc-rna-analysis`

## Usage

### Natural Language (Recommended)

Simply describe what you want to do:

```
"Evaluate TNFRSF12A as a target in CRC"
"target evaluation on Fn14 in CRC"
"Analyze CDK4 expression in colorectal cancer"
"Evaluate EGFR as a target in NSCLC"
```

Claude will automatically invoke the appropriate skill.

### Direct Skill Invocation

You can also invoke skills directly via the Skill tool:

```
Skill(oncology-skills:target-evaluation) with args "TNFRSF12A --disease crc"
Skill(oncology-skills:crc-bulk-rna-analysis) with args "CDK4 CDK6"
```

## Output Files

### Target Evaluation Outputs

```
crc_comprehensive_results/{GENE}/
├── {GENE}_integrated_target_report.md    # Final integrated report
├── {GENE}_risk_assessment_crc.md         # 6-category risk assessment
├── {GENE}_final_risk_report.pdf          # 13-page professional PDF
├── {GENE}_comprehensive_analysis.png     # 8-panel expression figure
├── {GENE}_comprehensive_report.md        # Expression analysis report
├── {GENE}_idas_assessment.yaml           # iDAS alignment data
├── {GENE}_risk_assessment_figure.png     # Risk visualization
├── {GENE}_scholar_eval_figure.png        # ScholarEval visualization
├── {GENE}_pairwise_comparisons.csv       # Tumor vs Normal statistics
└── {GENE}_tcga_statistics.csv            # Cohort statistics
```

## Data Sources

### CRC Analysis
- **TCGA-COAD/READ**: Tumor and adjacent normal (on-target toxicity assessment)
- **GTEx**: Normal colon tissue baseline
- **CCLE**: CRC cell line expression
- **Tempus RWD**: >200,000 patients with line-of-therapy stratification

### NSCLC Analysis
- **TCGA-LUAD/LUSC**: Tumor and adjacent normal
- **GTEx**: Normal lung tissue baseline
- **CCLE**: NSCLC cell line expression

## Requirements

- **Claude Code** with plugin support
- **AWS CLI** with `cbg` profile configured (for S3 data access)
- **Pixi** - skills automatically install Python dependencies via pixi

### AWS Configuration

Ensure your `~/.aws/credentials` has the `cbg` profile:
```ini
[cbg]
aws_access_key_id = ...
aws_secret_access_key = ...
```

Or use AWS SSO:
```bash
aws sso login --profile cbg
```

## Plugin Development

### Adding a New Skill

1. Create a new directory under `oncology-skills/`:
   ```
   oncology-skills/new-skill/
   ├── SKILL.md
   └── README.md
   ```

2. Add the skill path to `.claude-plugin/marketplace.json`:
   ```json
   "skills": [
     "./oncology-skills/target-evaluation",
     "./oncology-skills/new-skill"
   ]
   ```

3. Reinstall the plugin:
   ```
   /plugin  → Remove marketplace
   /plugin marketplace add /path/to/plugin
   /plugin install oncology-skills@claude-oncology-skills
   /reload-plugins
   ```

### SKILL.md Format

```markdown
---
name: skill-name
description: Brief description for skill matching
---

# Skill Title

## Overview
...

## Usage
...
```

## Known Limitations

- **No slash command autocomplete**: Local directory plugins don't support `/skill-name` autocomplete. Use natural language or host on GitHub for full autocomplete support.
- **SC-RNA skills**: Single-cell analysis skills are placeholders pending data availability.
- **NSCLC skills**: NSCLC bulk RNA analysis is a placeholder pending implementation.

## License

Internal use only - Computational Biology Oncology Team.

## Author

Ming-Ju Tsai (ming-ju.tsai@takeda.com)
