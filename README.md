# Oncology Skills for Claude Code

A collection of Claude Code skills for oncology target evaluation and RNA-seq analysis, covering both bulk and single-cell transcriptomics for colorectal cancer (CRC) and non-small cell lung cancer (NSCLC).

## Branching Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable, production-ready code |
| `dev` | Integration testing and evaluation |
| `feature/*` | Individual feature development |

**Workflow:** `feature/*` → `dev` (evaluate) → `main` (release)

## Versioning

Releases are tagged on `main` using [Semantic Versioning](https://semver.org/) — `vMAJOR.MINOR.PATCH`.

| Bump | When to use | Examples in this repo |
|------|-------------|-----------------------|
| **PATCH** (`v1.0.0` → `v1.0.1`) | Bug fixes, doc fixes, parser tweaks. No change to how skills are invoked or what files they produce. | Fixing a regex that mis-extracts a value; correcting a stale filename in a doc; swapping `eval()` for a safe expression evaluator. |
| **MINOR** (`v1.0.0` → `v1.1.0`) | New functionality that is **backwards compatible**. Existing skills, arguments, and outputs continue to work. | Adding a new skill folder; adding an optional CLI flag; adding new pages or content to the PDF report. |
| **MAJOR** (`v1.0.0` → `v2.0.0`) | **Breaking changes.** Renaming or removing a skill, restructuring directory layout, changing required arguments, or changing output filenames in a way that downstream consumers must adapt to. | The ai-sci restructure (`oncology-skills/` → `skills/`, every skill renamed) — would have been a major bump if released as a single version. |

### Tagging a release

When `dev` merges into `main` for a release:

1. Decide which component to bump based on the table above. Only **one** component bumps per release; the rightmost components reset to `0` when a higher one bumps (e.g. `v1.4.7` + MINOR → `v1.5.0`, not `v1.5.7`).
2. Tag the merge commit on `main`:
   ```bash
   git tag -a v1.0.1 <main-commit-sha> -m "Brief description of the release"
   git push origin v1.0.1
   ```
3. Tags are immutable. **Never reuse a tag** — if a release was wrong, ship a follow-up patch and tag a new version.

### Conventions

- **`v` prefix is required** on git tags (`v1.0.0`, not `1.0.0`) to distinguish version tags from other tags.
- **Pre-1.0** versions (`v0.x.y`) signal "API still in flux"; downstream consumers should expect breaking changes between minor bumps. We released `v1.0.0` as the first stable version and follow strict semver from there.
- **Pre-release suffixes** (`v1.1.0-rc.1`) are used for staged rollouts; not required for routine releases.

### Versioning the audit-trail metadata

The ScholarEval engine and validation framework include their own internal version strings inside their source files (e.g. `Version: 1.0.0` at the top of `scoring_engine.py`). Bump those alongside the repo tag whenever the scoring rules or audit-trail format changes — that lets re-runs against an old YAML/JSON output be detected as version-mismatched.

## Available Skills

| Skill | Description | Status |
|-------|-------------|--------|
| [analysis-bulk-rna-crc](skills/analysis-bulk-rna-crc/) | Comprehensive CRC analysis with TCGA + Tempus RWD (>200K patients), iDAS alignment | Implemented |
| [analysis-bulk-rna-nsclc](skills/analysis-bulk-rna-nsclc/) | Comprehensive NSCLC analysis with TCGA + Tempus RWD (~1,800 patients), iDAS alignment | Implemented |
| [analysis-protein-crc](skills/analysis-protein-crc/) | CRC protein expression analysis from Human Protein Atlas (IHC, subcellular localization, modality recommendation) | Implemented |
| [analysis-protein-nsclc](skills/analysis-protein-nsclc/) | NSCLC protein expression analysis from Human Protein Atlas (IHC, subcellular localization, modality recommendation) | Implemented |
| [analysis-sc-rna-crc](skills/analysis-sc-rna-crc/) | Single-cell RNA-seq analysis for colorectal cancer | Placeholder |
| [analysis-sc-rna-nsclc](skills/analysis-sc-rna-nsclc/) | Single-cell RNA-seq analysis for NSCLC | Placeholder |
| [workflow-target-evaluation-onc](skills/workflow-target-evaluation-onc/) | Full 4-step therapeutic target evaluation workflow with PDF report generation | Implemented |

## Target Evaluation Workflow

The `workflow-target-evaluation-onc` skill provides a comprehensive 4-step pipeline:

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
- **iDAS strategic alignment**: Automatic whitespace scoring for CRC and NSCLC
- **Tempus RWD integration**: Line-of-therapy stratification (CRC: >200K patients, NSCLC: ~1,800 patients)
- **Protein analysis**: Human Protein Atlas integration for IHC, RNA-protein concordance, subcellular localization, and modality recommendation (CRC + NSCLC)
- **Output**: Professional PDF report with Go/No-Go recommendation

## Repository Structure

```
.
├── skills/
│   ├── analysis-bulk-rna-crc/
│   │   ├── SKILL.md
│   │   ├── README.md
│   │   ├── pyproject.toml
│   │   ├── pixi.toml
│   │   └── scripts/
│   │       └── crc_comprehensive_analysis.py
│   ├── analysis-bulk-rna-nsclc/
│   │   ├── SKILL.md
│   │   ├── pyproject.toml
│   │   ├── pixi.toml
│   │   └── scripts/
│   │       └── nsclc_comprehensive_analysis.py
│   ├── analysis-protein-crc/
│   │   ├── SKILL.md
│   │   ├── pixi.toml
│   │   └── scripts/
│   │       └── crc_protein_analysis.py
│   ├── analysis-protein-nsclc/
│   │   ├── SKILL.md
│   │   ├── pixi.toml
│   │   └── scripts/
│   │       └── nsclc_protein_analysis.py
│   ├── analysis-sc-rna-crc/
│   │   └── SKILL.md
│   ├── analysis-sc-rna-nsclc/
│   │   └── SKILL.md
│   └── workflow-target-evaluation-onc/
│       ├── SKILL.md
│       ├── README.md
│       ├── pixi.toml
│       ├── configs/
│       │   ├── crc.yaml
│       │   └── nsclc.yaml
│       ├── reference/
│       │   ├── risk_assessment_template_crc.md
│       │   └── risk_assessment_template_nsclc.md
│       └── scripts/
│           ├── generate_target_report_pdf.py
│           ├── scoring_engine.py
│           └── validation_checkpoints.py
├── DEVELOPMENT_GUIDELINES.md
└── README.md
```

## Output File Naming Convention

All output files follow a consistent naming pattern for traceability:

```
{GENE}_{skill-name}_{content-type}.{ext}
```

### Output Directory Structure

```
./results/{GENE}/
├── {GENE}_analysis-bulk-rna-crc_*.{ext}      # CRC bulk RNA outputs
├── {GENE}_analysis-bulk-rna-nsclc_*.{ext}    # NSCLC bulk RNA outputs
└── {GENE}_workflow-target-evaluation-onc_*.{ext}  # Workflow outputs
```

### analysis-bulk-rna-crc Outputs

| Filename | Purpose |
|----------|---------|
| `{GENE}_analysis-bulk-rna-crc_figure.png` | Main 8-panel summary figure |
| `{GENE}_analysis-bulk-rna-crc_report.md` | Full analysis report with all findings |
| `{GENE}_analysis-bulk-rna-crc_idas.yaml` | iDAS whitespace alignment scores (structured) |
| `{GENE}_analysis-bulk-rna-crc_suitability.csv` | Suitability scores by molecular subgroup |
| `{GENE}_analysis-bulk-rna-crc_suitability.png` | Subgroup suitability heatmap figure |
| `{GENE}_analysis-bulk-rna-crc_tcga-stats.csv` | TCGA cohort expression statistics |
| `{GENE}_analysis-bulk-rna-crc_comparisons.csv` | Tumor vs Normal statistical comparisons |
| `{GENE}_analysis-bulk-rna-crc_panel-01.png` | Panel 01: TCGA cohorts expression |
| `{GENE}_analysis-bulk-rna-crc_panel-02.png` | Panel 02: On-target toxicity |
| `{GENE}_analysis-bulk-rna-crc_panel-03.png` | Panel 03: Line of therapy |
| `{GENE}_analysis-bulk-rna-crc_panel-04.png` | Panel 04: iDAS-aligned cohorts |
| `{GENE}_analysis-bulk-rna-crc_panel-05.png` | Panel 05: RAS mutation status |
| `{GENE}_analysis-bulk-rna-crc_panel-06.png` | Panel 06: CMS subtypes |
| `{GENE}_analysis-bulk-rna-crc_panel-07.png` | Panel 07: iDAS summary table |
| `{GENE}_analysis-bulk-rna-crc_panel-08.png` | Panel 08: Recommendation |

### analysis-bulk-rna-nsclc Outputs

| Filename | Purpose |
|----------|---------|
| `{GENE}_analysis-bulk-rna-nsclc_figure.png` | Main 8-panel summary figure |
| `{GENE}_analysis-bulk-rna-nsclc_report.md` | Full analysis report with all findings |
| `{GENE}_analysis-bulk-rna-nsclc_idas.yaml` | iDAS whitespace alignment scores (structured) |
| `{GENE}_analysis-bulk-rna-nsclc_suitability.csv` | Suitability scores by molecular subgroup |
| `{GENE}_analysis-bulk-rna-nsclc_suitability.png` | Subgroup suitability heatmap figure |
| `{GENE}_analysis-bulk-rna-nsclc_tcga-stats.csv` | TCGA cohort expression statistics |
| `{GENE}_analysis-bulk-rna-nsclc_comparisons.csv` | Tumor vs Normal statistical comparisons |
| `{GENE}_analysis-bulk-rna-nsclc_mutation-stats.csv` | TCGA mutation status expression (KRAS/EGFR/STK11/KEAP1) |
| `{GENE}_analysis-bulk-rna-nsclc_panel-01.png` | Panel 01: TCGA cohorts + mutations |
| `{GENE}_analysis-bulk-rna-nsclc_panel-02.png` | Panel 02: On-target toxicity |
| `{GENE}_analysis-bulk-rna-nsclc_panel-03.png` | Panel 03: Line of therapy |
| `{GENE}_analysis-bulk-rna-nsclc_panel-04.png` | Panel 04: iDAS priority cohorts |
| `{GENE}_analysis-bulk-rna-nsclc_panel-05.png` | Panel 05: KRAS mutation status |
| `{GENE}_analysis-bulk-rna-nsclc_panel-06.png` | Panel 06: EGFR mutation status |
| `{GENE}_analysis-bulk-rna-nsclc_panel-07.png` | Panel 07: IO resistance markers (STK11/KEAP1) |
| `{GENE}_analysis-bulk-rna-nsclc_panel-08.png` | Panel 08: Summary |

### workflow-target-evaluation-onc Outputs

| Filename | Purpose |
|----------|---------|
| `{GENE}_workflow-target-evaluation-onc_report.md` | Final integrated report (markdown source) |
| `{GENE}_workflow-target-evaluation-onc_report.pdf` | Professional PDF report for stakeholders |
| `{GENE}_workflow-target-evaluation-onc_risk.png` | 6-category risk assessment visualization |
| `{GENE}_workflow-target-evaluation-onc_scholareval.png` | 8-dimension ScholarEval scoring visualization |
| `{GENE}_workflow-target-evaluation-onc_slide.png` | Landscape summary slide (PNG) |
| `{GENE}_workflow-target-evaluation-onc_slide.pdf` | Landscape summary slide (PDF) |

### Naming Convention Rules

1. **Pattern**: `{GENE}_{skill-name}_{content-type}.{ext}`
2. **GENE**: Official HGNC gene symbol (e.g., `TNFRSF12A`, `EGFR`)
3. **skill-name**: Full skill name for traceability
4. **content-type**: Short, descriptive suffix:
   - `figure` - Main visualization
   - `report` - Full analysis report
   - `idas` - iDAS alignment data
   - `suitability` - Subgroup suitability scores
   - `tcga-stats` - TCGA statistics
   - `comparisons` - Statistical comparisons
   - `mutation-stats` - Mutation status analysis
   - `panel-NN` - Individual figure panels (zero-padded)
   - `risk` - Risk assessment figure
   - `scholareval` - ScholarEval figure
   - `slide` - Summary slide
5. **Panels**: Use zero-padded numbers (`panel-01`, `panel-02`, etc.)

## Data Sources

### CRC Analysis
- **TCGA-COAD/READ**: Tumor and adjacent normal (on-target toxicity assessment)
- **GTEx**: Normal colon tissue baseline
- **CCLE**: CRC cell line expression
- **Tempus RWD**: >200,000 patients with line-of-therapy stratification
- **Human Protein Atlas v25**: IHC expression for GI toxicity assessment, subcellular localization, RNA-protein concordance, COAD/READ prognostic data

### NSCLC Analysis
- **TCGA-LUAD/LUSC**: Tumor and adjacent normal (on-target toxicity assessment)
- **GTEx**: Normal lung tissue baseline
- **CCLE**: NSCLC cell line expression
- **Tempus RWD**: ~1,800 patients with EGFR/KRAS/STK11/KEAP1 stratification
- **Human Protein Atlas v25**: IHC expression for lung toxicity assessment, subcellular localization, RNA-protein concordance, LUAD/LUSC prognostic data

## Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills.git
cd rnd-computational-biology-oncology-claude-oncology-skills
```

### Step 2: Install Dependencies

Each skill uses either `pixi` or `uv` for dependency management:

```bash
# Using pixi
cd skills/analysis-bulk-rna-crc
pixi install

# Using uv
cd skills/analysis-bulk-rna-crc
uv sync
```

### Step 3: Configure AWS Credentials

Ensure your `~/.aws/credentials` has the `cbg` profile:

```ini
[cbg]
aws_access_key_id = YOUR_ACCESS_KEY
aws_secret_access_key = YOUR_SECRET_KEY
```

## Usage

### Natural Language (Recommended)

Simply describe what you want to do:

```
"Evaluate TNFRSF12A as a target in CRC"
"Analyze CDK4 expression in colorectal cancer"
"Evaluate EGFR as a target in NSCLC"
```

Claude will automatically invoke the appropriate skill.

### Direct Script Execution

```bash
# CRC bulk RNA analysis
cd skills/analysis-bulk-rna-crc
uv run python scripts/crc_comprehensive_analysis.py --genes TNFRSF12A

# NSCLC bulk RNA analysis
cd skills/analysis-bulk-rna-nsclc
uv run python scripts/nsclc_comprehensive_analysis.py --genes EGFR

# Target evaluation workflow (PDF generation)
cd skills/workflow-target-evaluation-onc
uv run python scripts/generate_target_report_pdf.py --gene TNFRSF12A --disease crc
```

## Development Guidelines

See [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md) for:
- Cross-repository workflow with ai-sci-claude-skills
- Skill naming conventions
- Integration procedures

## Requirements

- **Python** >= 3.10
- **boto3** and **s3fs** for S3 data access
- **AWS credentials** with `cbg` profile configured

## License

Internal use only - Computational Biology Oncology Team.

## Author

Ming-Ju Tsai (ming-ju.tsai@takeda.com)
