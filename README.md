# Oncology Skills for Claude Code

A collection of Claude Code skills for oncology RNA-seq analysis, covering both bulk and single-cell transcriptomics for colorectal cancer (CRC) and non-small cell lung cancer (NSCLC).

## Available Skills

| Skill | Description | Status |
|-------|-------------|--------|
| [crc-bulk-rna-analysis](skills/crc-bulk-rna-analysis/) | Bulk RNA-seq analysis for colorectal cancer (TCGA COAD/READ, CMS subtypes, cohort comparisons) | Implemented |
| [crc-sc-rna-analysis](skills/crc-sc-rna-analysis/) | Single-cell RNA-seq analysis for colorectal cancer | Placeholder |
| [nsclc-bulk-rna-analysis](skills/nsclc-bulk-rna-analysis/) | Bulk RNA-seq analysis for NSCLC (TCGA LUAD/LUSC) | Placeholder |
| [nsclc-sc-rna-analysis](skills/nsclc-sc-rna-analysis/) | Single-cell RNA-seq analysis for NSCLC | Placeholder |

## Repository Structure

```
.
├── .claude-plugin/
│   └── marketplace.json      # Plugin metadata and skill registration
├── skills/
│   ├── crc-bulk-rna-analysis/
│   │   ├── README.md
│   │   ├── SKILL.md
│   │   └── crc_gene_analysis.py
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
git clone <repository-url> ~/oncology-skills
cd ~/oncology-skills
```

### Step 2: Register the Marketplace

In Claude Code, run the following command:
```bash
/plugin marketplace add ~/oncology-skills
```

### Step 3: Install the Plugin

```bash
/plugin install rna-analysis@oncology-skills
```


## Usage

Once installed, skills are automatically triggered based on context:

```
"Analyze CDK4 expression in colorectal cancer"
"Compare EGFR expression across CRC CMS subtypes"
```

Or invoke explicitly with slash commands:

```
/crc-bulk-rna-analysis CDK4, CDK6, CCND1
```

## Requirements

- AWS CLI with `cbg` profile configured with the `tec-rnd-cbg-dev` account
- Python 3.8+ with: `pandas`, `numpy`, `matplotlib`, `seaborn`, `scipy`, `statsmodels`

## License

Internal use only.
