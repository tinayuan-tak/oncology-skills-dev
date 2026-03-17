# Oncology Skills for Claude Code

A collection of Claude Code skills for oncology target evaluation and RNA-seq analysis, covering both bulk and single-cell transcriptomics for colorectal cancer (CRC) and non-small cell lung cancer (NSCLC).

## Available Skills

| Skill | Description | Status |
|-------|-------------|--------|
| [target-evaluation](oncology-skills/target-evaluation/) | Full 5-step therapeutic target evaluation workflow with PDF report generation | Implemented |
| [crc-bulk-rna-analysis](oncology-skills/crc-bulk-rna-analysis/) | Bulk RNA-seq analysis for colorectal cancer (TCGA COAD/READ, CMS subtypes, cohort comparisons) | Implemented |
| [crc-sc-rna-analysis](oncology-skills/crc-sc-rna-analysis/) | Single-cell RNA-seq analysis for colorectal cancer | Placeholder |
| [nsclc-bulk-rna-analysis](oncology-skills/nsclc-bulk-rna-analysis/) | Bulk RNA-seq analysis for NSCLC (TCGA LUAD/LUSC) | Placeholder |
| [nsclc-sc-rna-analysis](oncology-skills/nsclc-sc-rna-analysis/) | Single-cell RNA-seq analysis for NSCLC | Placeholder |

## Target Evaluation Workflow

The `target-evaluation` skill provides a comprehensive 5-step pipeline:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. RISK         │ ──▶ │ 2. PUBMED       │ ──▶ │ 3. EXPRESSION   │ ──▶ │ 4. SCHOLAREVAL  │ ──▶ │ 5. REPORT       │
│    FRAMEWORK    │     │    SEARCH       │     │    ANALYSIS     │     │    SCORING      │     │    + PDF        │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Key Features
- **6-category risk assessment**: Biological, Druggability, Translational, Clinical, Safety, Commercial
- **8-dimension ScholarEval scoring**: Weighted target evaluation framework
- **Primary metric**: Tumor vs Adjacent Normal expression (predicts on-target toxicity)
- **Output**: 13-page professional PDF report with Go/No-Go recommendation

## Repository Structure

```
.
├── .claude-plugin/
│   ├── marketplace.json      # Plugin metadata and skill registration
│   └── plugin.json           # Plugin configuration
├── oncology-skills/
│   ├── target-evaluation/
│   │   ├── SKILL.md
│   │   ├── generate_target_report_pdf.py
│   │   ├── pixi.toml
│   │   └── configs/
│   │       ├── crc.yaml
│   │       └── nsclc.yaml
│   ├── crc-bulk-rna-analysis/
│   │   ├── SKILL.md
│   │   ├── crc_gene_analysis.py
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
"Analyze CDK4 expression in colorectal cancer"
"Evaluate EGFR as a target in NSCLC"
```

Claude will automatically invoke the appropriate skill.

### Direct Skill Invocation

You can also invoke skills directly via the Skill tool:

```
Skill(oncology-skills:target-evaluation) with args "GENE CRC"
Skill(oncology-skills:crc-bulk-rna-analysis) with args "CDK4 CDK6"
```

## Example Output

### Target Evaluation Report

| Target | Score | Assessment | Risk | vs Adj Normal | Recommendation |
|--------|-------|------------|------|---------------|----------------|
| TNFRSF12A | 4.2/5.0 | Strong | LOW-MEDIUM | 7.3x higher | GO |
| EPCAM | 3.55/5.0 | Moderate | HIGH | ~1x (same) | CONDITIONAL NO-GO |
| CDCP1 | 3.25/5.0 | Weak | HIGH | 0.76x (lower) | CONDITIONAL NO-GO |

### Generated Files

```
crc_analysis_results/{GENE}/
├── {GENE}_integrated_target_report.md    # Full markdown report
├── {GENE}_final_risk_report.pdf          # 13-page PDF
├── {GENE}_comprehensive_analysis.png     # Expression figures
├── {GENE}_CMS_boxplot.png                # CMS subtype analysis
├── {GENE}_risk_assessment_figure.png     # Risk profile visualization
├── {GENE}_scholar_eval_figure.png        # Scoring visualization
├── {GENE}_pairwise_comparisons.csv       # Statistical results
└── {GENE}_cohort_statistics.csv          # Descriptive statistics
```

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
   └── SKILL.md
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
