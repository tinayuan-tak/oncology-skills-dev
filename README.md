# Oncology Skills for Claude Code

A collection of Claude Code skills for oncology target evaluation and RNA-seq analysis, covering both bulk and single-cell transcriptomics for colorectal cancer (CRC) and non-small cell lung cancer (NSCLC).

## Branching Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable, production-ready code |
| `dev` | Integration testing and evaluation |
| `feature/*` | Individual feature development |

**Workflow:** `feature/*` → `dev` (evaluate) → `main` (release)

## Available Skills

| Skill | Description | Status |
|-------|-------------|--------|
| [target-evaluation](oncology-skills/target-evaluation/) | Full 4-step therapeutic target evaluation workflow with validation framework and PDF report generation | Implemented |
| [crc-bulk-rna-analysis](oncology-skills/crc-bulk-rna-analysis/) | Comprehensive CRC analysis with TCGA + Tempus RWD (~2,183 patients), iDAS alignment | Implemented |
| [crc-protein-analysis](oncology-skills/crc-protein-analysis/) | CRC protein expression analysis from Human Protein Atlas (IHC, subcellular localization, modality recommendation) | Implemented |
| [nsclc-bulk-rna-analysis](oncology-skills/nsclc-bulk-rna-analysis/) | Comprehensive NSCLC analysis with TCGA + Tempus RWD (~1,800 patients), iDAS alignment | Implemented |
| [nsclc-protein-analysis](oncology-skills/nsclc-protein-analysis/) | NSCLC protein expression analysis from Human Protein Atlas (IHC, subcellular localization, modality recommendation) | Implemented |
| [crc-sc-rna-analysis](oncology-skills/crc-sc-rna-analysis/) | Single-cell RNA-seq analysis for colorectal cancer | Placeholder |
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
- **Validation framework**: Deterministic scoring engine with 3 checkpoints and audit trail
- **Primary metric**: Tumor vs Adjacent Normal expression (predicts on-target toxicity)
- **iDAS strategic alignment**: Automatic whitespace scoring for CRC and NSCLC
- **Tempus RWD integration**: Line-of-therapy stratification (CRC: ~2,183 patients, NSCLC: ~1,800 patients)
- **Protein analysis**: Human Protein Atlas integration for IHC, RNA-protein concordance, subcellular localization, and modality recommendation (CRC + NSCLC)
- **Output**: 14-page professional PDF report with Go/No-Go recommendation

## Repository Structure

```
.
├── .claude-plugin/
│   ├── marketplace.json          # Plugin metadata and skill registration
│   └── plugin.json               # Plugin configuration
├── oncology-skills/
│   ├── target-evaluation/
│   │   ├── SKILL.md              # 4-step workflow definition
│   │   ├── scripts/
│   │   │   ├── generate_target_report_pdf.py  # PDF report generator
│   │   │   ├── scoring_engine.py              # Deterministic scoring engine
│   │   │   └── validation_checkpoints.py      # Validation framework
│   │   ├── configs/
│   │   │   ├── crc.yaml
│   │   │   ├── nsclc.yaml
│   │   │   └── scoring_rules.yaml             # Scoring thresholds
│   │   ├── reference/
│   │   │   ├── risk_assessment_template_crc.md
│   │   │   ├── risk_assessment_template_nsclc.md
│   │   │   └── evidence_extraction_schema.yaml  # LLM extraction schema
│   │   └── pixi.toml
│   ├── crc-bulk-rna-analysis/
│   │   ├── SKILL.md
│   │   ├── crc_comprehensive_analysis.py   # Unified TCGA + Tempus analysis
│   │   └── pixi.toml
│   ├── crc-protein-analysis/
│   │   ├── SKILL.md
│   │   ├── crc_protein_analysis.py          # HPA IHC + subcellular + modality
│   │   └── pixi.toml
│   ├── nsclc-bulk-rna-analysis/
│   │   ├── SKILL.md
│   │   ├── nsclc_comprehensive_analysis.py  # Unified TCGA + Tempus analysis
│   │   └── pixi.toml
│   ├── nsclc-protein-analysis/
│   │   ├── SKILL.md
│   │   ├── nsclc_protein_analysis.py        # HPA IHC + subcellular + modality
│   │   └── pixi.toml
│   ├── crc-sc-rna-analysis/
│   │   └── SKILL.md                         # Placeholder
│   └── nsclc-sc-rna-analysis/
│       └── SKILL.md                         # Placeholder
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
- `oncology-skills:nsclc-bulk-rna-analysis`
- `oncology-skills:crc-protein-analysis`
- `oncology-skills:nsclc-protein-analysis`
- `oncology-skills:crc-sc-rna-analysis` (placeholder)
- `oncology-skills:nsclc-sc-rna-analysis` (placeholder)

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
{disease}_analysis_results/{GENE}/
├── {GENE}_integrated_target_report.md    # Final integrated report
├── {GENE}_risk_assessment_{disease}.md   # 6-category risk assessment
├── {GENE}_final_risk_report.pdf          # 14-page professional PDF
├── {GENE}_comprehensive_analysis.png     # 8-panel expression figure
├── {GENE}_comprehensive_report.md        # Expression analysis report
├── {GENE}_idas_assessment.yaml           # iDAS alignment data
├── {GENE}_subgroup_suitability.csv       # 3-phase subgroup suitability
├── {GENE}_scholareval.yaml               # Deterministic scoring output
├── {GENE}_audit_trail.json               # Scoring audit trail
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
- **Tempus RWD**: ~2,183 patients with line-of-therapy stratification
- **Human Protein Atlas v25**: IHC expression for GI toxicity assessment, subcellular localization, RNA-protein concordance, COAD/READ prognostic data

### NSCLC Analysis
- **TCGA-LUAD/LUSC**: Tumor and adjacent normal (on-target toxicity assessment)
- **GTEx**: Normal lung tissue baseline
- **CCLE**: NSCLC cell line expression
- **Tempus RWD**: ~1,800 patients with EGFR/KRAS/STK11/KEAP1 stratification
- **Human Protein Atlas v25**: IHC expression for lung toxicity assessment, subcellular localization, RNA-protein concordance, LUAD/LUSC prognostic data

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

## License

Internal use only - Computational Biology Oncology Team.

## Author

Ming-Ju Tsai (ming-ju.tsai@takeda.com)
