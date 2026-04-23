# Oncology Skills Integration Plan

**Version**: 2.0.0
**Date**: 2026-04-23
**Source Repository**: `/Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills`
**Target Repository**: `/Users/eta3879/tools/ai-sci-claude-skills`

---

## Executive Summary

Integrate oncology target evaluation skills into the `ai-sci-claude-skills` repository following the Skills Management Framework. This involves:
- Renaming skills per NAMING_TAXONOMY.md conventions
- Restructuring directories per SKILLS_MANAGEMENT_FRAMEWORK.md
- Updating SKILL.md frontmatter per SKILL_TEMPLATE.md
- Converting from pixi.toml to pyproject.toml
- Adding preflight checks per CONTRIBUTION_GUIDE.md

---

## Compliance Checklist (from docs/)

### SKILLS_MANAGEMENT_FRAMEWORK.md Requirements

- [ ] Category prefix from valid list: `data-`, `analysis-`, `tool-`, `workflow-`, `ref-`, `util-`
- [ ] Domain suffix from valid list: `-target`, `-chem`, `-genomics`, `-protein`, `-bulk-rna`, `-sc-rna`
- [ ] Disease suffix where applicable: `-crc`, `-nsclc`
- [ ] Directory structure: `SKILL.md`, `pyproject.toml`, `scripts/`, `references/`, `assets/`
- [ ] No README.md, CHANGELOG.md, INSTALLATION_GUIDE.md files
- [ ] Scripts in `scripts/` folder (not root)
- [ ] `data/` folder gitignored for cached files

### CONTRIBUTION_GUIDE.md Requirements

- [ ] SKILL.md has valid YAML frontmatter (`name`, `description`, `metadata`)
- [ ] `name` field matches folder name (lowercase, hyphens)
- [ ] `description` contains ALL trigger phrases and "when to use" info
- [ ] `description` includes example queries (at least 3)
- [ ] `description` includes "do NOT use when" alternatives
- [ ] SKILL.md body under 500 lines
- [ ] No credentials hardcoded
- [ ] No `.venv/` or `.pixi/` directories committed
- [ ] `scripts/check_setup.py` if `requires_preflight: true`
- [ ] `.env.example` template if credentials needed
- [ ] Prerequisites section in SKILL.md body

### NAMING_TAXONOMY.md Requirements

- [ ] Format: `{category}-{domain}-{function}[-{qualifier}]`
- [ ] All lowercase
- [ ] Use hyphens (not underscores)
- [ ] No redundant suffixes (-skill, -database, -tool)
- [ ] Domain identifier included

### SKILL_TEMPLATE.md Requirements

- [ ] Frontmatter fields: `name`, `description`, `metadata.version`, `metadata.owner`, `metadata.requires_preflight`, `metadata.environment`
- [ ] `environment` field set: `none`, `shared`, or `isolated`
- [ ] `pyproject.toml` present if environment is `shared` or `isolated`

---

## Skill Name Mapping

| Current Name | New Name | Category | Notes |
|--------------|----------|----------|-------|
| `target-evaluation` | `workflow-target-evaluation-onc` | workflow | Therapeutic area suffix |
| `crc-bulk-rna-analysis` | `analysis-bulk-rna-crc` | analysis | Technology + disease |
| `nsclc-bulk-rna-analysis` | `analysis-bulk-rna-nsclc` | analysis | Technology + disease |
| `crc-protein-analysis` | `analysis-protein-crc` | analysis | Planned |
| `nsclc-protein-analysis` | `analysis-protein-nsclc` | analysis | Planned |

---

## Phase 1: Setup Branch & Directory Structure

### 1.1 Create Feature Branch

```bash
# Navigate to ai-sci-claude-skills repo
cd /Users/eta3879/tools/ai-sci-claude-skills

# Ensure main is up to date
git fetch origin
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/add-oncology-skills
```

### 1.2 Create Directory Structure

```bash
# Create all skill directories per SKILLS_MANAGEMENT_FRAMEWORK.md Section 2.1
mkdir -p skills/workflow-target-evaluation-onc/{scripts,references,assets/configs}
mkdir -p skills/analysis-bulk-rna-crc/{scripts,references}
mkdir -p skills/analysis-bulk-rna-nsclc/{scripts,references}
mkdir -p skills/analysis-protein-crc/{scripts,references}
mkdir -p skills/analysis-protein-nsclc/{scripts,references}
```

### 1.3 Update .gitignore

Ensure these patterns exist in `.gitignore`:

```gitignore
# Python environments
.pixi/
.venv/
__pycache__/
*.py[cod]

# Environment files (keep .env.example)
.env
*.env.local

# Data cache (per SKILLS_MANAGEMENT_FRAMEWORK.md Section 2.2)
data/
data_cache/

# Generated outputs
*_analysis_results/

# macOS
.DS_Store
```

### 1.4 Phase 1 Checklist

- [ ] Clone/update ai-sci-claude-skills repo
- [ ] Create `feature/add-oncology-skills` branch
- [ ] Create directory structure for all 5 skills
- [ ] Verify .gitignore entries
- [ ] Commit initial structure

---

## Phase 2: workflow-target-evaluation-onc

### 2.1 Source Files Location

```
SOURCE: /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills/oncology-skills/target-evaluation/
```

### 2.2 Target Directory Structure

```
workflow-target-evaluation-onc/
├── SKILL.md                          # Updated with metadata (per SKILL_TEMPLATE.md)
├── pyproject.toml                    # Converted from pixi.toml
├── .env.example                      # AWS credentials template
├── scripts/
│   ├── generate_target_report_pdf.py # Main PDF generator
│   ├── scoring_engine.py             # Deterministic scoring engine
│   ├── validation_checkpoints.py     # Validation framework
│   ├── run_scholareval.py            # CLI for ScholarEval
│   └── check_setup.py                # Pre-flight AWS check
├── references/
│   ├── risk_assessment_template_crc.md
│   ├── risk_assessment_template_nsclc.md
│   ├── risk_assessment_criteria.tsv  # Official Step 1 criteria
│   └── evidence_extraction_schema.yaml
└── assets/
    └── configs/
        ├── crc.yaml
        ├── nsclc.yaml
        └── scoring_rules.yaml
```

### 2.3 SKILL.md Frontmatter (per SKILL_TEMPLATE.md)

```yaml
---
name: workflow-target-evaluation-onc
description: >
  Use when user asks to "evaluate a target", "target assessment",
  "GO/NO-GO recommendation", "evaluate {gene} in {disease}",
  "target evaluation report", or needs systematic target evaluation
  for oncology drug discovery. Provides 4-step workflow: risk assessment
  (PubMed literature), expression analysis (TCGA/Tempus), ScholarEval
  scoring, and PDF report generation. Includes validation framework with
  deterministic scoring and audit trail. Supports CRC and NSCLC indications.
  Do NOT use for target prioritization across multiple targets -
  use workflow-target-prioritization instead.
  Do NOT use for individual gene expression queries -
  use analysis-bulk-rna-crc or analysis-bulk-rna-nsclc instead.
  Example queries: "evaluate TNFRSF12A in CRC", "assess CDCP1 as target in NSCLC",
  "generate target evaluation report for EPCAM".
metadata:
  version: 2.0.0
  owner: ming-ju.tsai@takeda.com
  requires_preflight: true
  environment: shared
  dependencies:
    - analysis-bulk-rna-crc
    - analysis-bulk-rna-nsclc
    - analysis-protein-crc
    - analysis-protein-nsclc
---
```

### 2.4 pyproject.toml

```toml
[project]
name = "workflow-target-evaluation-onc"
version = "2.0.0"
description = "Oncology target evaluation workflow for CRC and NSCLC"
requires-python = ">=3.10"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.24",
    "matplotlib>=3.8",
    "seaborn>=0.13",
    "pyyaml>=6.0",
    "scipy>=1.11",
    "reportlab>=4.0",
    "pillow>=10.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0"]
```

### 2.5 .env.example

```bash
# AWS credentials for S3 access (TCGA/Tempus data)
# Option 1: Use AWS profile (recommended)
AWS_PROFILE=cbg

# Option 2: Use explicit credentials (not recommended)
# AWS_ACCESS_KEY_ID=your_access_key
# AWS_SECRET_ACCESS_KEY=your_secret_key
# AWS_DEFAULT_REGION=us-east-1
```

### 2.6 scripts/check_setup.py (per CONTRIBUTION_GUIDE.md)

```python
#!/usr/bin/env python3
"""Pre-flight check for workflow-target-evaluation-onc.

Run this before using the skill to verify AWS credentials and dependencies.
"""
import os
import sys

def check_aws_credentials():
    """Check if AWS credentials are configured."""
    profile = os.environ.get('AWS_PROFILE', 'cbg')

    try:
        import boto3
        session = boto3.Session(profile_name=profile)
        sts = session.client('sts')
        identity = sts.get_caller_identity()
        print(f"✓ AWS credentials valid (Account: {identity['Account']})")
        return True
    except Exception as e:
        print(f"✗ AWS credentials error: {e}")
        print(f"  Set AWS_PROFILE or configure ~/.aws/credentials")
        return False

def check_dependencies():
    """Check required Python packages."""
    required = ['pandas', 'matplotlib', 'seaborn', 'yaml', 'scipy', 'reportlab', 'PIL']
    missing = []

    for pkg in required:
        try:
            __import__(pkg if pkg != 'yaml' else 'yaml')
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"✗ Missing packages: {', '.join(missing)}")
        print(f"  Run: pip install {' '.join(missing)}")
        return False

    print("✓ All required packages installed")
    return True

def main():
    print("=" * 50)
    print("workflow-target-evaluation-onc Pre-flight Check")
    print("=" * 50)

    checks = [
        ("Dependencies", check_dependencies),
        ("AWS Credentials", check_aws_credentials),
    ]

    all_passed = True
    for name, check_fn in checks:
        print(f"\nChecking {name}...")
        if not check_fn():
            all_passed = False

    print("\n" + "=" * 50)
    if all_passed:
        print("✓ All checks passed. Ready to use skill.")
        sys.exit(0)
    else:
        print("✗ Some checks failed. Please fix issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

### 2.7 Files to Copy

| Source | Destination | Action |
|--------|-------------|--------|
| `SKILL.md` | `SKILL.md` | Rewrite with new frontmatter |
| `scripts/generate_target_report_pdf.py` | `scripts/generate_target_report_pdf.py` | Copy, update paths |
| `scripts/scoring_engine.py` | `scripts/scoring_engine.py` | Copy |
| `scripts/validation_checkpoints.py` | `scripts/validation_checkpoints.py` | Copy |
| `scripts/run_scholareval.py` | `scripts/run_scholareval.py` | Copy |
| `reference/risk_assessment_template_crc.md` | `references/risk_assessment_template_crc.md` | Copy |
| `reference/risk_assessment_template_nsclc.md` | `references/risk_assessment_template_nsclc.md` | Copy |
| `reference/evidence_extraction_schema.yaml` | `references/evidence_extraction_schema.yaml` | Copy |
| `risk_assessment_criteria.tsv` | `references/risk_assessment_criteria.tsv` | Copy (Step 1 criteria) |
| `configs/crc.yaml` | `assets/configs/crc.yaml` | Copy |
| `configs/nsclc.yaml` | `assets/configs/nsclc.yaml` | Copy |
| `configs/scoring_rules.yaml` | `assets/configs/scoring_rules.yaml` | Copy |

### 2.8 Files to DELETE (Not Needed per SKILLS_MANAGEMENT_FRAMEWORK.md)

| File | Reason |
|------|--------|
| `README.md` | Not allowed per framework |
| `.pixi/` | Environment directory (gitignored) |
| `pixi.lock` | Replaced by pyproject.toml |
| `pixi.toml` | Replaced by pyproject.toml |

### 2.9 Path Updates in SKILL.md

Update all references from:
```markdown
`reference/risk_assessment_template_crc.md`
`configs/crc.yaml`
`generate_target_report_pdf.py`
```

To:
```markdown
`references/risk_assessment_template_crc.md`
`assets/configs/crc.yaml`
`scripts/generate_target_report_pdf.py`
```

### 2.10 Phase 2 Checklist

- [ ] Create new SKILL.md with proper frontmatter (per SKILL_TEMPLATE.md)
- [ ] Create pyproject.toml
- [ ] Create .env.example
- [ ] Create scripts/check_setup.py (per CONTRIBUTION_GUIDE.md)
- [ ] Copy all scripts to scripts/
- [ ] Copy risk templates to references/
- [ ] Copy risk_assessment_criteria.tsv to references/
- [ ] Copy configs to assets/configs/
- [ ] Update all paths in SKILL.md body
- [ ] Delete README.md, pixi.toml, pixi.lock
- [ ] Verify SKILL.md body < 500 lines
- [ ] Commit changes

---

## Phase 3: analysis-bulk-rna-crc

### 3.1 Source Files Location

```
SOURCE: /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills/oncology-skills/crc-bulk-rna-analysis/
```

### 3.2 Target Directory Structure

```
analysis-bulk-rna-crc/
├── SKILL.md                          # Updated with metadata
├── pyproject.toml                    # Converted from pixi.toml
├── .env.example                      # AWS credentials template
├── scripts/
│   ├── crc_comprehensive_analysis.py # Main analysis script
│   └── check_setup.py                # Pre-flight AWS check
└── references/
    └── cohort_definitions.md         # Optional: detailed cohort docs
```

### 3.3 SKILL.md Frontmatter

```yaml
---
name: analysis-bulk-rna-crc
description: >
  Use when user asks to "analyze gene expression in CRC",
  "TCGA colorectal analysis", "CRC tumor vs normal expression",
  "Tempus CRC data", "iDAS alignment for CRC", "CMS subtype expression",
  or needs bulk RNA expression analysis for colorectal cancer targets.
  Provides TCGA/GTEx/Tempus integration, on-target toxicity assessment,
  CMS subtype analysis, RAS mutation stratification, and iDAS strategic
  alignment assessment. Generates comprehensive reports and 8-panel figures.
  Do NOT use for protein expression analysis - use analysis-protein-crc instead.
  Do NOT use for NSCLC - use analysis-bulk-rna-nsclc instead.
  Example queries: "analyze TNFRSF12A expression in CRC",
  "CRC tumor vs normal for CDCP1", "check iDAS alignment for EPCAM in CRC".
metadata:
  version: 1.0.0
  owner: ming-ju.tsai@takeda.com
  requires_preflight: true
  environment: shared
---
```

### 3.4 pyproject.toml

```toml
[project]
name = "analysis-bulk-rna-crc"
version = "1.0.0"
description = "Bulk RNA expression analysis for colorectal cancer targets"
requires-python = ">=3.10"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.24",
    "matplotlib>=3.8",
    "seaborn>=0.13",
    "scipy>=1.11",
    "pyyaml>=6.0",
    "boto3>=1.28",
    "pyarrow>=14.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0"]
```

### 3.5 .env.example

```bash
# AWS credentials for S3 access (TCGA/GTEx/Tempus data)
AWS_PROFILE=cbg

# S3 bucket locations (usually not changed)
# TCGA_S3_BUCKET=s3://onc-compbio/omicsoft_oncoland_data
# TEMPUS_S3_BUCKET=s3://onc-compbio/Tempus/crc
```

### 3.6 scripts/check_setup.py

```python
#!/usr/bin/env python3
"""Pre-flight check for analysis-bulk-rna-crc.

Verifies AWS credentials and S3 bucket access for TCGA/Tempus data.
"""
import os
import sys

def check_aws_credentials():
    """Check AWS credentials and S3 access."""
    profile = os.environ.get('AWS_PROFILE', 'cbg')

    try:
        import boto3
        session = boto3.Session(profile_name=profile)
        s3 = session.client('s3')

        # Test bucket access
        bucket = 'onc-compbio'
        s3.head_bucket(Bucket=bucket)
        print(f"✓ AWS credentials valid, S3 bucket '{bucket}' accessible")
        return True
    except Exception as e:
        print(f"✗ AWS/S3 error: {e}")
        return False

def check_dependencies():
    """Check required Python packages."""
    required = ['pandas', 'numpy', 'matplotlib', 'seaborn', 'scipy', 'yaml', 'boto3', 'pyarrow']
    missing = []

    for pkg in required:
        try:
            __import__(pkg if pkg != 'yaml' else 'yaml')
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"✗ Missing packages: {', '.join(missing)}")
        return False

    print("✓ All required packages installed")
    return True

def main():
    print("=" * 50)
    print("analysis-bulk-rna-crc Pre-flight Check")
    print("=" * 50)

    all_passed = True

    print("\nChecking dependencies...")
    if not check_dependencies():
        all_passed = False

    print("\nChecking AWS/S3 access...")
    if not check_aws_credentials():
        all_passed = False

    print("\n" + "=" * 50)
    if all_passed:
        print("✓ All checks passed. Ready to use skill.")
        sys.exit(0)
    else:
        print("✗ Some checks failed. Please fix issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

### 3.7 Files to Copy

| Source | Destination | Action |
|--------|-------------|--------|
| `SKILL.md` | `SKILL.md` | Rewrite with new frontmatter |
| `crc_comprehensive_analysis.py` | `scripts/crc_comprehensive_analysis.py` | Copy |

### 3.8 Files to DELETE

| File | Reason |
|------|--------|
| `README.md` | Not allowed per framework |
| `.pixi/` | Environment directory |
| `pixi.lock` | Replaced by pyproject.toml |
| `pixi.toml` | Replaced by pyproject.toml |

### 3.9 Phase 3 Checklist

- [ ] Create new SKILL.md with proper frontmatter
- [ ] Create pyproject.toml
- [ ] Create .env.example
- [ ] Create scripts/check_setup.py
- [ ] Copy crc_comprehensive_analysis.py to scripts/
- [ ] Delete README.md, .pixi/, pixi.toml, pixi.lock
- [ ] Verify SKILL.md body < 500 lines
- [ ] Commit changes

---

## Phase 4: analysis-bulk-rna-nsclc

**Follow same steps as Phase 3, with NSCLC-specific changes:**

### 4.1 SKILL.md Frontmatter

```yaml
---
name: analysis-bulk-rna-nsclc
description: >
  Use when user asks to "analyze gene expression in NSCLC",
  "TCGA lung cancer analysis", "NSCLC tumor vs normal expression",
  "Tempus NSCLC data", "iDAS alignment for NSCLC", "LUAD vs LUSC expression",
  "KRAS/EGFR mutation stratification", or needs bulk RNA expression analysis
  for non-small cell lung cancer targets. Provides TCGA LUAD/LUSC analysis,
  GTEx normal lung comparison, Tempus RWD with biomarker stratification,
  and iDAS priority whitespace assessment (2L Non-AGA, 2L EGFR, 1L/2L KRAS).
  Do NOT use for protein expression analysis - use analysis-protein-nsclc instead.
  Do NOT use for CRC - use analysis-bulk-rna-crc instead.
  Example queries: "analyze CDCP1 expression in NSCLC", "LUAD vs LUSC for USP8",
  "KRAS mutant expression in lung cancer".
metadata:
  version: 1.0.0
  owner: ming-ju.tsai@takeda.com
  requires_preflight: true
  environment: shared
---
```

### 4.2 Files to Copy

| Source | Destination |
|--------|-------------|
| `nsclc_comprehensive_analysis.py` | `scripts/nsclc_comprehensive_analysis.py` |

### 4.3 Phase 4 Checklist

- [ ] Create new SKILL.md with NSCLC frontmatter
- [ ] Create pyproject.toml (same structure as CRC)
- [ ] Create .env.example
- [ ] Create scripts/check_setup.py
- [ ] Copy nsclc_comprehensive_analysis.py to scripts/
- [ ] Delete README.md, .pixi/, pixi.toml, pixi.lock
- [ ] Verify SKILL.md body < 500 lines
- [ ] Commit changes

---

## Phase 5: Protein Analysis Skills (Planned)

### 5.1 analysis-protein-crc

```yaml
---
name: analysis-protein-crc
description: >
  Use when user asks to "analyze protein expression in CRC",
  "Human Protein Atlas CRC", "IHC expression colorectal",
  "protein localization CRC", or needs protein-level validation
  for colorectal cancer targets. Provides HPA IHC data, subcellular
  localization, and GI toxicity assessment based on normal colon expression.
  Do NOT use for RNA expression - use analysis-bulk-rna-crc instead.
  Do NOT use for NSCLC - use analysis-protein-nsclc instead.
  Example queries: "check HPA expression for TNFRSF12A in colon",
  "protein localization of CDCP1", "GI toxicity risk from IHC".
metadata:
  version: 0.1.0
  owner: ming-ju.tsai@takeda.com
  requires_preflight: false
  environment: shared
---

# Protein Expression Analysis for CRC

## Status

**PLANNED** - Data integration from Human Protein Atlas in progress.

## Planned Capabilities

- Human Protein Atlas IHC expression for normal colon tissue
- Subcellular localization data (surface vs cytoplasm vs nucleus)
- GI toxicity risk assessment based on normal tissue expression
- Integration with bulk RNA analysis for RNA-protein concordance

## Data Sources

- **Human Protein Atlas**: IHC expression, subcellular localization
- **Protein Atlas API**: Programmatic access to tissue expression

## Related Skills

- `analysis-bulk-rna-crc`: For bulk RNA expression analysis
- `workflow-target-evaluation-onc`: Uses protein data in Step 2
```

### 5.2 analysis-protein-nsclc

Same structure as above, adapted for NSCLC (lung tissue expression, pulmonary toxicity assessment).

### 5.3 Phase 5 Checklist

- [ ] Create SKILL.md for analysis-protein-crc
- [ ] Create SKILL.md for analysis-protein-nsclc
- [ ] Create pyproject.toml with HPA dependencies
- [ ] Implement HPA data fetching scripts
- [ ] Test integration with workflow-target-evaluation-onc
- [ ] Commit changes

---

## Validation Commands

After each phase, run validation:

```bash
# Navigate to repo
cd /Users/eta3879/tools/ai-sci-claude-skills

# Run structure tests
cd tests/skills
pytest -v test_skill_structure.py

# Run content tests
pytest -v test_skill_content.py

# Test specific skill
pytest -v -k "workflow_target_evaluation_onc"
pytest -v -k "analysis_bulk_rna_crc"
```

---

## PR Template (per CONTRIBUTION_GUIDE.md)

When ready to submit PR:

```markdown
## Skills: Oncology Target Evaluation Suite

### Description
Adds 5 oncology-focused skills for systematic target evaluation in CRC and NSCLC:
- `workflow-target-evaluation-onc`: Main 4-step evaluation workflow with validation framework
- `analysis-bulk-rna-crc`: CRC bulk RNA expression analysis
- `analysis-bulk-rna-nsclc`: NSCLC bulk RNA expression analysis
- `analysis-protein-crc`: CRC protein expression analysis (HPA) - planned
- `analysis-protein-nsclc`: NSCLC protein expression analysis (HPA) - planned

### Category
- [x] Workflow
- [x] Analysis

### Naming Convention
Uses naming pattern per NAMING_TAXONOMY.md:
- Analysis: `analysis-{tech}-{disease}` (e.g., `analysis-bulk-rna-crc`)
- Workflow: `workflow-{function}-{therapeutic_area}` (e.g., `workflow-target-evaluation-onc`)

### Checklist (per CONTRIBUTION_GUIDE.md)
- [x] SKILL.md has valid frontmatter for all skills
- [x] Names follow NAMING_TAXONOMY.md
- [x] Description includes trigger phrases and "do NOT use" alternatives
- [x] At least 3 example queries per skill
- [x] No credentials committed
- [x] .env.example provided for skills requiring credentials
- [x] scripts/check_setup.py for preflight validation
- [x] SKILL.md body under 500 lines
- [x] Scripts in scripts/ folder (not root)
- [x] No README.md files (per SKILLS_MANAGEMENT_FRAMEWORK.md)
- [x] Tests pass locally

### Testing
- Validated with pytest test_skill_structure.py and test_skill_content.py
- Manually tested target evaluation for TNFRSF12A, CDCP1 in both CRC and NSCLC

### Related
- Migrated from: rnd-computational-biology-oncology-claude-oncology-skills
- Related to: workflow-target-prioritization (complementary, not duplicate)
```

---

## Summary of Framework Compliance

| Requirement | Source Document | Status |
|-------------|-----------------|--------|
| Valid category prefix | NAMING_TAXONOMY.md | ✅ workflow-, analysis- |
| Valid domain suffix | SKILLS_MANAGEMENT_FRAMEWORK.md | ✅ -bulk-rna, -protein |
| Disease qualifier | SKILLS_MANAGEMENT_FRAMEWORK.md | ✅ -crc, -nsclc, -onc |
| Directory structure | SKILLS_MANAGEMENT_FRAMEWORK.md | ✅ scripts/, references/, assets/ |
| No README.md | SKILLS_MANAGEMENT_FRAMEWORK.md | ✅ Will delete |
| Frontmatter fields | SKILL_TEMPLATE.md | ✅ name, description, metadata |
| Trigger phrases in description | CONTRIBUTION_GUIDE.md | ✅ Included |
| Example queries | CONTRIBUTION_GUIDE.md | ✅ At least 3 per skill |
| "Do NOT use" alternatives | CONTRIBUTION_GUIDE.md | ✅ Included |
| check_setup.py | CONTRIBUTION_GUIDE.md | ✅ For preflight skills |
| .env.example | CONTRIBUTION_GUIDE.md | ✅ For credential skills |
| pyproject.toml | SKILLS_MANAGEMENT_FRAMEWORK.md | ✅ For shared environment |
| SKILL.md < 500 lines | CONTRIBUTION_GUIDE.md | ✅ Will verify |
