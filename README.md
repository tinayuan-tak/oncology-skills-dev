# oncology-skills — Claude Code Plugin

Claude Code plugin bundling skills for oncology target evaluation and RNA-seq analysis, covering bulk transcriptomics, single-cell transcriptomics (placeholder), and protein expression for colorectal cancer (CRC) and non-small cell lung cancer (NSCLC).

This repository publishes the **`oncology-skills` plugin** (declared in `.claude-plugin/plugin.json`). Users install the plugin once via Claude Code's marketplace; individual skills are then invoked as `oncology-skills:<skill-name>` (e.g. `oncology-skills:workflow-target-evaluation-onc`).

## Quick install (Claude Code plugin)

In Claude Code, run these two slash commands:

```
/plugin marketplace add https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills
/plugin install oncology-skills@claude-oncology-skills
```

That's it. The plugin and all seven bundled skills are now available. To pull the latest version later:

```
/plugin marketplace update
```

You can also point `/plugin marketplace add` at a local clone (e.g. for development):

```
/plugin marketplace add /path/to/local/clone
/plugin install oncology-skills@claude-oncology-skills
```

> **AWS credentials are required** for the bulk-RNA and workflow skills (S3 data + Bedrock LLM calls). See [AWS configuration](#aws-configuration) below.

## Available Skills

| Skill | Description | Status |
|-------|-------------|--------|
| [workflow-target-evaluation-onc](skills/workflow-target-evaluation-onc/) | Full 4-step therapeutic target evaluation workflow with PubMed → facts.yaml extractor (v1.4.0+), structured ScholarEval scoring (v1.7.2), and integrated PDF report | Implemented |
| [analysis-bulk-rna-crc](skills/analysis-bulk-rna-crc/) | Comprehensive CRC analysis with TCGA + Tempus RWD (>200K patients), iDAS alignment | Implemented |
| [analysis-bulk-rna-nsclc](skills/analysis-bulk-rna-nsclc/) | Comprehensive NSCLC analysis with TCGA + Tempus RWD (~1,800 patients), iDAS alignment | Implemented |
| [analysis-protein-crc](skills/analysis-protein-crc/) | CRC protein expression from Human Protein Atlas — IHC, subcellular localization, modality recommendation | Implemented |
| [analysis-protein-nsclc](skills/analysis-protein-nsclc/) | NSCLC protein expression from Human Protein Atlas — IHC, subcellular localization, modality recommendation | Implemented |
| [analysis-sc-rna-crc](skills/analysis-sc-rna-crc/) | Single-cell RNA-seq analysis for colorectal cancer | Placeholder |
| [analysis-sc-rna-nsclc](skills/analysis-sc-rna-nsclc/) | Single-cell RNA-seq analysis for NSCLC | Placeholder |

## Target Evaluation Workflow

The `workflow-target-evaluation-onc` skill provides a comprehensive 4-step pipeline. As of v1.7.x, every stage exchanges **structured data** with the next — no regex-on-prose between stages, deterministic scoring end-to-end:

```
┌─────────────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. DRUG TARGET RISK     │ ──▶ │ 2. EXPRESSION   │ ──▶ │ 3. SCHOLAREVAL  │ ──▶ │ 4. REPORT       │
│    ASSESSMENT           │     │    ANALYSIS     │     │    SCORING      │     │    + PDF        │
│                         │     │                 │     │                 │     │                 │
│ PubMed → Sonnet         │     │ TCGA + Tempus   │     │ 8-dimension     │     │ Integrated      │
│ → Opus → facts.yaml     │     │ bulk RNA skill  │     │ structured      │     │ markdown + PDF  │
│ (auto, v1.4.0+)         │     │                 │     │ scoring         │     │                 │
└─────────────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Key Features

- **Automated literature extraction**: PubMed E-utilities → Sonnet (per-category claim extraction) → Opus (synthesis) → strict-validation gate. No analyst hand-writing.
- **6-category risk assessment**: Biological, Druggability, Translational, Clinical, Safety, Commercial
- **8-dimension structured ScholarEval scoring**: All dimensions read structured fields from `facts.yaml`; markdown-regex parsers retained as legacy fallback
- **Primary metric**: Tumor vs Adjacent Normal expression (predicts on-target toxicity)
- **iDAS strategic alignment**: Per-disease canonical whitespaces, validator-enforced
- **Modality registry**: 6-class registry drives Phase 3 toxicity scoring; modality provenance (`user`/`inferred`/`default`) surfaced in the PDF
- **Primary evidence highlights**: Per-category load-bearing PMID rendered as a callout in Step 1 + Step 4
- **Output**: Professional PDF report with Go/No-Go recommendation

## Repository Structure

```
.
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest (version, name, keywords)
│   └── marketplace.json         # Marketplace registration
├── skills/
│   ├── workflow-target-evaluation-onc/
│   │   ├── SKILL.md
│   │   ├── README.md
│   │   ├── pixi.toml
│   │   ├── configs/             # scoring_rules.yaml, modality_classes.yaml, per-disease cfg
│   │   ├── reference/           # risk_assessment_template_{disease}.md
│   │   ├── templates/           # Jinja templates for Step 1 and Step 4 markdown
│   │   ├── scripts/
│   │   │   ├── generate_facts_from_pubmed.py    # Step 0: PubMed → facts.yaml
│   │   │   ├── generate_risk_assessment.py      # Step 1: facts.yaml → markdown
│   │   │   ├── run_scholareval.py               # Step 3: deterministic scoring
│   │   │   ├── generate_integrated_report.py    # Step 4: integrated markdown
│   │   │   ├── generate_target_report_pdf.py    # Step 4: PDF rendering
│   │   │   ├── scoring_engine.py
│   │   │   ├── modality_registry.py
│   │   │   └── integrated_report/               # Stage 1+2 LLM modules, parsers, renderer
│   │   └── tests/
│   ├── analysis-bulk-rna-crc/
│   ├── analysis-bulk-rna-nsclc/
│   ├── analysis-protein-crc/
│   ├── analysis-protein-nsclc/
│   ├── analysis-sc-rna-crc/
│   └── analysis-sc-rna-nsclc/
├── DEVELOPMENT_GUIDELINES.md
├── INTEGRATION_PLAN.md
└── README.md
```

## Output File Naming Convention

All output files follow:

```
{GENE}_{skill-name}_{content-type}.{ext}
```

### workflow-target-evaluation-onc Outputs

| Filename | Purpose |
|----------|---------|
| `{GENE}_risk_assessment_facts.yaml` | Step 1 structured facts (validated against canonical schema) |
| `{GENE}_risk_assessment_{disease}.md` | Step 1 risk-assessment markdown rendered from facts.yaml |
| `{GENE}_extraction_log.json` | Step 0 provenance: PubMed counts, per-stage timings, attempt counts |
| `{GENE}_scholareval.yaml` | Step 3 deterministic scoring result |
| `{GENE}_audit_trail.json` | Step 3 audit trail with input hash for reproducibility |
| `{GENE}_workflow-target-evaluation-onc_report.md` | Step 4 integrated report (markdown source) |
| `{GENE}_workflow-target-evaluation-onc_report.pdf` | Step 4 PDF report for stakeholders |
| `{GENE}_workflow-target-evaluation-onc_risk.png` | 6-category risk assessment bar chart |
| `{GENE}_workflow-target-evaluation-onc_scholareval.png` | 8-dimension ScholarEval scoring figure |
| `{GENE}_workflow-target-evaluation-onc_slide.png/pdf` | Landscape one-page summary |

### analysis-bulk-rna-{disease} Outputs

| Filename | Purpose |
|----------|---------|
| `{GENE}_analysis-bulk-rna-{disease}_figure.png` | 8-panel summary figure (consolidated) |
| `{GENE}_analysis-bulk-rna-{disease}_report.md` | Full analysis report |
| `{GENE}_analysis-bulk-rna-{disease}_idas.yaml` | iDAS whitespace alignment scores |
| `{GENE}_analysis-bulk-rna-{disease}_suitability.csv` | Subgroup suitability scores |
| `{GENE}_analysis-bulk-rna-{disease}_tcga-stats.csv` | TCGA cohort expression statistics |
| `{GENE}_analysis-bulk-rna-{disease}_comparisons.csv` | Tumor vs Normal statistical comparisons |
| `{GENE}_analysis-bulk-rna-nsclc_mutation-stats.csv` | NSCLC-only: KRAS/EGFR/STK11/KEAP1 expression by mutation status |

> Earlier versions emitted per-panel PNGs (`panel-01` through `panel-08`); these were consolidated into a single `figure.png` and removed.

## Data Sources

### CRC Analysis
- **TCGA-COAD/READ**: Tumor and adjacent normal expression
- **GTEx**: Normal colon tissue baseline
- **CCLE**: CRC cell line expression
- **Tempus RWD**: >200,000 patients with line-of-therapy stratification
- **Human Protein Atlas v25**: IHC for GI toxicity, subcellular localization, RNA-protein concordance, COAD/READ prognostic data

### NSCLC Analysis
- **TCGA-LUAD/LUSC**: Tumor and adjacent normal expression
- **GTEx**: Normal lung tissue baseline
- **CCLE**: NSCLC cell line expression
- **Tempus RWD**: ~1,800 patients with EGFR/KRAS/STK11/KEAP1 stratification
- **Human Protein Atlas v25**: IHC for lung toxicity, subcellular localization, RNA-protein concordance, LUAD/LUSC prognostic data

### Workflow Step 0 (Literature)
- **PubMed E-utilities**: Per-category searches across 6 risk dimensions
- **AWS Bedrock**: Sonnet (per-abstract claim extraction) + Opus (synthesis with structured tool use)

## AWS configuration

Two AWS profiles are used by different skills:

| Profile | Used by | Purpose |
|---------|---------|---------|
| `cbg` | `analysis-bulk-rna-crc`, `analysis-bulk-rna-nsclc` | S3 access to TCGA/Tempus/CCLE data |
| `cmp-dev` | `workflow-target-evaluation-onc` (Stage 0 PubMed → facts.yaml) | Bedrock access for Sonnet + Opus LLM calls |

Configure both in `~/.aws/credentials` (for static keys) or via SSO:

```bash
aws sso login --profile cbg
aws sso login --profile cmp-dev
```

The plugin honors `AWS_PROFILE` and `AWS_REGION` environment variables — Claude Code's harness sets these automatically (typically `AWS_REGION=us-east-1`).

## Local development install

For contributors editing the plugin source rather than installing it as a marketplace plugin:

```bash
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills.git
cd rnd-computational-biology-oncology-claude-oncology-skills
```

Each skill manages its own Python environment with `pixi`:

```bash
cd skills/workflow-target-evaluation-onc
pixi install
pixi run pytest -q   # run the skill's tests
```

Always invoke skill scripts via `pixi run python ...` from the skill's directory — never bare `python` or `uv` (each skill carries its own `pixi.toml`).

## Usage

### Natural Language (Recommended)

Once the plugin is installed, simply describe what you want in Claude Code:

```
"Evaluate WEE1 as a target in CRC"
"Analyze CDCP1 expression in NSCLC"
"Run the target evaluation workflow on PCDH7 with T-cell engager modality"
```

Claude routes the request to the appropriate skill automatically.

### Direct script execution

For automation or CI pipelines:

```bash
# Step 0 — PubMed → facts.yaml (workflow only)
cd skills/workflow-target-evaluation-onc
pixi run python scripts/generate_facts_from_pubmed.py \
    --gene PCDH7 --disease nsclc \
    --output-dir /path/to/PCDH7 \
    --modality "T-cell engager"

# Step 2 — bulk RNA analysis
cd skills/analysis-bulk-rna-nsclc
pixi run python scripts/nsclc_comprehensive_analysis.py \
    --genes PCDH7 \
    --output-dir /path/to/PCDH7

# Step 3 — ScholarEval scoring
cd skills/workflow-target-evaluation-onc
pixi run python scripts/run_scholareval.py \
    --gene PCDH7 --disease nsclc \
    --output-dir /path/to/PCDH7

# Step 4 — Integrated report + PDF
pixi run python scripts/generate_integrated_report.py \
    --gene PCDH7 --disease nsclc \
    --output-dir /path/to/PCDH7
pixi run python scripts/generate_target_report_pdf.py \
    --gene PCDH7 --disease nsclc \
    --output-dir /path/to/PCDH7
```

## Branching strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable, production-ready code; tagged releases |
| `dev` | Integration testing and evaluation |
| `feat/*` | Individual feature development |

**Workflow:** `feat/*` → `dev` (evaluate) → `main` (release + tag)

## Versioning

Releases are tagged on `main` using [Semantic Versioning](https://semver.org/) — `vMAJOR.MINOR.PATCH`.

| Bump | When to use | Example |
|------|-------------|---------|
| **PATCH** (`v1.7.2` → `v1.7.3`) | Bug fixes, doc fixes, parser tweaks. No change to how skills are invoked or what files they produce. | v1.7.3 — render placeholder when Step 2 omics figure is missing |
| **MINOR** (`v1.6.0` → `v1.7.0`) | New functionality that is **backwards compatible**. Existing skills, arguments, and outputs continue to work. | v1.7.0 — primary_evidence per-category pointer; v1.4.0 — PubMed → facts.yaml extractor |
| **MAJOR** (`v1.0.0` → `v2.0.0`) | **Breaking changes.** Renaming or removing a skill, restructuring directory layout, changing required arguments, or changing output filenames. | The ai-sci restructure (`oncology-skills/` → `skills/`) — would have been a major bump if released as one version. |

### Release ritual

After each `dev → main` merge:

1. Pull main locally: `git checkout main && git pull --ff-only origin main`
2. Tag the merge commit: `git tag -a vX.Y.Z <main-HEAD> -m "Brief description"`
3. Push the tag: `git push origin vX.Y.Z`
4. Create a GitHub release with notes covering the merged work
5. Bump `version` in both `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` to match
6. Delete merged feature branches (local + remote)

#### Multi-PR consolidation

When two or more `feat/*` branches reach `main` in the same merge, the convention has been to tag with the **latest** scope's version and use a combined release-notes block covering all PRs. The skipped intermediate version exists in PR titles and commit messages but not as a tag — anyone reading `git tag` sees a coherent semver progression; anyone reading the release notes sees the full work decomposition. (See v1.4.0→v1.5.0, v1.6.0→v1.7.0, v1.7.1→v1.7.2 historically.)

### Conventions

- **`v` prefix is required** on git tags (`v1.0.0`, not `1.0.0`) to distinguish version tags from other tags.
- Tags are immutable. **Never reuse a tag** — if a release was wrong, ship a follow-up patch.
- Pre-release suffixes (`v1.1.0-rc.1`) are available for staged rollouts; not required for routine releases.

### Versioning the audit-trail metadata

The ScholarEval engine and validation framework include their own internal version strings inside their source files (e.g. `Version: 1.0.0` at the top of `scoring_engine.py`). Bump those alongside the repo tag whenever the scoring rules or audit-trail format changes — that lets re-runs against an old YAML/JSON output be detected as version-mismatched.

## Development guidelines

See [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md) for:
- Cross-repository workflow with ai-sci-claude-skills
- Skill naming conventions
- Integration procedures

## Requirements

- **Python** ≥ 3.10 (3.14 supported in newer skills; v1.4.0+ corporate-CA SSL workaround included)
- **pixi** for per-skill environment management
- **AWS credentials** — `cbg` profile for S3, `cmp-dev` profile for Bedrock (see [AWS configuration](#aws-configuration))

## License

Internal use only — Computational Biology Oncology Team.

## Author

Ming-Ju Tsai (ming-ju.tsai@takeda.com)
