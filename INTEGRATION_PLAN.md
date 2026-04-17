# Oncology Skills Integration Plan

**Version**: 1.1.0
**Date**: 2026-04-17
**Target Repository**: `ai-sci-claude-skills`
**Source Repository**: `rnd-computational-biology-oncology-claude-oncology-skills`

---

## Executive Summary

Integrate oncology target evaluation skills into the `ai-sci-claude-skills` repository following the Skills Management Framework. This involves renaming skills with revised naming conventions, restructuring directories, updating SKILL.md frontmatter, and converting from pixi to pyproject.toml.

---

## Naming Convention (Revised)

### Secondary Categories Update

**Proposed addition to SKILLS_MANAGEMENT_FRAMEWORK.md Section 1.2:**

| Domain | Suffix | Description | Examples |
|--------|--------|-------------|----------|
| **Bulk** | `-bulk-` | Bulk sequencing analysis | RNA-seq, ATAC-seq, ChIP-seq |
| **Single-Cell** | `-sc-` | Single-cell analysis | scRNA-seq, scATAC-seq |
| Genomics | `-genomics` | Genetic variants | GWAS, somatic mutations |
| Proteomics | `-protein-` | Protein analysis | HPA, mass spec |

### Naming Patterns

| Category | Pattern | Example |
|----------|---------|---------|
| **Analysis** | `analysis-{tech}-{assay}-{disease?}` | `analysis-bulk-rna-crc` |
| **Workflow** | `workflow-{function}-{therapeutic_area}` | `workflow-target-evaluation-onc` |
| Data | `data-{source}` | `data-tcga`, `data-tempus` |
| Tool | `tool-{name}` | `tool-scanpy`, `tool-deseq2` |

**Key principles:**
- Analysis skills: Technology-driven (bulk, sc) + disease suffix when disease-specific
- Workflow skills: Function-driven + therapeutic area suffix (onc, gi, neuro)
- No redundant `-onc-` prefix for analysis skills

---

## Phase 1: Setup Branch & Directory Structure

### 1.1 Create Feature Branch

```bash
# Navigate to ai-sci-claude-skills repo
cd /Users/eta3879/Documents/claude-code/ai-sci-claude-skills

# Ensure main is up to date
git fetch origin
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/add-oncology-skills
```

### 1.2 Skill Name Mapping

| Current Name | New Name | Category | Notes |
|--------------|----------|----------|-------|
| `target-evaluation` | `workflow-target-evaluation-onc` | workflow | Therapeutic area suffix |
| `crc-bulk-rna-analysis` | `analysis-bulk-rna-crc` | analysis | Technology + disease |
| `nsclc-bulk-rna-analysis` | `analysis-bulk-rna-nsclc` | analysis | Technology + disease |
| `crc-protein-analysis` | `analysis-protein-crc` | analysis | Technology + disease |
| `nsclc-protein-analysis` | `analysis-protein-nsclc` | analysis | Technology + disease |

### 1.3 Create Directory Structure

```bash
# Create all skill directories
mkdir -p skills/workflow-target-evaluation-onc/{scripts,references,assets/configs}
mkdir -p skills/analysis-bulk-rna-crc/{scripts,references}
mkdir -p skills/analysis-bulk-rna-nsclc/{scripts,references}
mkdir -p skills/analysis-protein-crc/{scripts,references}
mkdir -p skills/analysis-protein-nsclc/{scripts,references}
```

### 1.4 Update .gitignore

Ensure these patterns are in `.gitignore`:

```gitignore
# Python environments
.pixi/
.venv/
__pycache__/

# Environment files (keep .env.example)
.env
*.env.local

# Data cache
data/
data_cache/

# Generated outputs
*_analysis_results/
```

### 1.5 Phase 1 Checklist

- [ ] Clone/update ai-sci-claude-skills repo
- [ ] Create `feature/add-oncology-skills` branch
- [ ] Create directory structure for all 5 skills
- [ ] Verify .gitignore entries
- [ ] Commit initial structure

---

## Phase 2: workflow-target-evaluation-onc

### 2.1 Source Files Location

```
SOURCE: /Users/eta3879/Documents/claude-code/rnd-computational-biology-oncology-claude-oncology-skills/oncology-skills/target-evaluation/
```

### 2.2 Target Directory Structure

```
workflow-target-evaluation-onc/
├── SKILL.md                          # Updated with metadata
├── pyproject.toml                    # Converted from pixi.toml
├── .env.example                      # AWS credentials template
├── scripts/
│   ├── generate_target_report_pdf.py # Main PDF generator
│   ├── scoring_engine.py             # Deterministic scoring engine
│   ├── validation_checkpoints.py     # Validation framework
│   └── check_setup.py                # Pre-flight AWS check
├── references/
│   ├── risk_assessment_template_crc.md
│   ├── risk_assessment_template_nsclc.md
│   └── evidence_extraction_schema.yaml
└── assets/
    └── configs/
        ├── crc.yaml
        ├── nsclc.yaml
        └── scoring_rules.yaml
```

### 2.3 SKILL.md Frontmatter

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
  Examples: "evaluate TNFRSF12A in CRC", "assess CDCP1 as target in NSCLC",
  "generate target evaluation report for EPCAM".
metadata:
  version: 2.0.0
  owner: [YOUR_EMAIL]@takeda.com
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
# Option 1: Use AWS profile
AWS_PROFILE=cbg

# Option 2: Use explicit credentials (not recommended)
# AWS_ACCESS_KEY_ID=your_access_key
# AWS_SECRET_ACCESS_KEY=your_secret_key
# AWS_DEFAULT_REGION=us-east-1
```

### 2.6 scripts/check_setup.py

```python
#!/usr/bin/env python3
"""Pre-flight check for workflow-target-evaluation-onc.

Run this before using the skill to verify AWS credentials and dependencies.
"""
import os
import sys

def check_aws_credentials():
    """Check if AWS credentials are configured."""
    # Check for profile
    profile = os.environ.get('AWS_PROFILE', 'cbg')

    # Try to import boto3 and verify credentials
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
| `reference/risk_assessment_template_crc.md` | `references/risk_assessment_template_crc.md` | Copy |
| `reference/risk_assessment_template_nsclc.md` | `references/risk_assessment_template_nsclc.md` | Copy |
| `reference/evidence_extraction_schema.yaml` | `references/evidence_extraction_schema.yaml` | Copy |
| `configs/crc.yaml` | `assets/configs/crc.yaml` | Copy |
| `configs/nsclc.yaml` | `assets/configs/nsclc.yaml` | Copy |
| `configs/scoring_rules.yaml` | `assets/configs/scoring_rules.yaml` | Copy |

### 2.8 Files to DELETE (Not Needed)

| File | Reason |
|------|--------|
| `generate_risk_framework_idas.py` | Static image generator, not used in workflow |
| `risk_assessment_framework.png` | Static reference image |
| `idas_whitespace_crc.png` | Static reference image |
| `idas_whitespace_nsclc.png` | Static reference image |
| `scholareval_8_dimensions.png` | Static reference image |
| `scholareval_step3.png` | Static reference image |
| `target_evaluation_workflow.png` | Static reference image |
| `report_generation_step4.png` | Static reference image |
| `risk_assessment_criteria.tsv` | Not used in workflow |
| `.pixi/` | Environment directory (gitignored) |
| `pixi.lock` | Replaced by pyproject.toml |
| `pixi.toml` | Replaced by pyproject.toml |
| `README.md` | Not allowed per framework |

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

- [ ] Create new SKILL.md with proper frontmatter
- [ ] Create pyproject.toml
- [ ] Create .env.example
- [ ] Create scripts/check_setup.py
- [ ] Copy generate_target_report_pdf.py to scripts/
- [ ] Update paths in generate_target_report_pdf.py
- [ ] Copy risk templates to references/
- [ ] Copy configs to assets/configs/
- [ ] Update all paths in SKILL.md body
- [ ] Delete unused files (static PNGs, etc.)
- [ ] Test skill structure with pytest
- [ ] Commit changes

---

## Phase 3: analysis-bulk-rna-crc

### 3.1 Source Files Location

```
SOURCE: /Users/eta3879/Documents/claude-code/rnd-computational-biology-oncology-claude-oncology-skills/oncology-skills/crc-bulk-rna-analysis/
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
  Do NOT use for single-cell CRC analysis - use analysis-sc-rna-crc instead.
  Do NOT use for NSCLC - use analysis-bulk-rna-nsclc instead.
  Examples: "analyze TNFRSF12A expression in CRC",
  "CRC tumor vs normal for CDCP1", "check iDAS alignment for EPCAM in CRC".
metadata:
  version: 1.0.0
  owner: [YOUR_EMAIL]@takeda.com
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
| `.pixi/` | Environment directory |
| `pixi.lock` | Replaced by pyproject.toml |
| `pixi.toml` | Replaced by pyproject.toml |
| `README.md` | Not allowed per framework |

### 3.9 Phase 3 Checklist

- [ ] Create new SKILL.md with proper frontmatter
- [ ] Create pyproject.toml
- [ ] Create .env.example
- [ ] Create scripts/check_setup.py
- [ ] Copy crc_comprehensive_analysis.py to scripts/
- [ ] Delete .pixi/, pixi.toml, pixi.lock, README.md
- [ ] Test skill structure with pytest
- [ ] Commit changes

---

## Phase 3b: analysis-bulk-rna-nsclc

**Follow same steps as Phase 3, with NSCLC-specific changes:**

### 3b.1 SKILL.md Frontmatter

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
  Do NOT use for single-cell NSCLC analysis - use analysis-sc-rna-nsclc instead.
  Do NOT use for CRC - use analysis-bulk-rna-crc instead.
  Examples: "analyze CDCP1 expression in NSCLC", "LUAD vs LUSC for USP8",
  "KRAS mutant expression in lung cancer".
metadata:
  version: 1.0.0
  owner: [YOUR_EMAIL]@takeda.com
  requires_preflight: true
  environment: shared
---
```

### 3b.2 Files to Copy

| Source | Destination |
|--------|-------------|
| `nsclc_comprehensive_analysis.py` | `scripts/nsclc_comprehensive_analysis.py` |

### 3b.3 Phase 3b Checklist

- [ ] Create new SKILL.md with NSCLC frontmatter
- [ ] Create pyproject.toml (same as CRC)
- [ ] Create .env.example
- [ ] Create scripts/check_setup.py (same as CRC)
- [ ] Copy nsclc_comprehensive_analysis.py to scripts/
- [ ] Delete .pixi/, pixi.toml, pixi.lock
- [ ] Test skill structure with pytest
- [ ] Commit changes

---

## Validation Commands

After each phase, run validation:

```bash
# Navigate to repo
cd /Users/eta3879/Documents/claude-code/ai-sci-claude-skills

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

## PR Template

When ready to submit PR:

```markdown
## Skills: Oncology Target Evaluation Suite

### Description
Adds 5 oncology-focused skills for systematic target evaluation in CRC and NSCLC:
- `workflow-target-evaluation-onc`: Main 4-step evaluation workflow with validation framework
- `analysis-bulk-rna-crc`: CRC bulk RNA expression analysis
- `analysis-bulk-rna-nsclc`: NSCLC bulk RNA expression analysis
- `analysis-protein-crc`: CRC protein analysis (HPA)
- `analysis-protein-nsclc`: NSCLC protein analysis (HPA)

### Category
- [x] Workflow
- [x] Analysis

### Naming Convention
Uses revised naming pattern:
- Analysis: `analysis-{tech}-{assay}-{disease}` (e.g., `analysis-bulk-rna-crc`)
- Workflow: `workflow-{function}-{therapeutic_area}` (e.g., `workflow-target-evaluation-onc`)

### Checklist
- [x] SKILL.md has valid frontmatter for all skills
- [x] Names follow revised taxonomy
- [x] Description includes trigger phrases and "do NOT use" alternatives
- [x] At least 3 example queries per skill
- [x] No credentials committed
- [x] .env.example provided for skills requiring credentials
- [x] scripts/check_setup.py for preflight validation
- [x] Validation framework with deterministic scoring
- [x] Tests pass locally

### Testing
- Validated with pytest test_skill_structure.py and test_skill_content.py
- Manually tested target evaluation for TNFRSF12A, CDCP1 in both CRC and NSCLC

### Related
- Migrated from: rnd-computational-biology-oncology-claude-oncology-skills
- Related to: workflow-target-prioritization (complementary, not duplicate)
- Proposes adding `-bulk-` secondary category to SKILLS_MANAGEMENT_FRAMEWORK.md
```

---

## Next Phases (Future)

### Phase 4: analysis-protein-crc
### Phase 5: analysis-protein-nsclc
### Phase 6: Testing & PR Submission

These phases follow the same pattern as Phase 3, adapted for protein analysis skills.

---

## Proposed Framework Update

**Add to SKILLS_MANAGEMENT_FRAMEWORK.md Section 1.2:**

```markdown
| Domain | Suffix/Tag | Description |
|--------|------------|-------------|
| **Bulk** | `-bulk-` | Bulk sequencing analysis (RNA-seq, ATAC-seq, ChIP-seq) |
```

This enables cleaner naming for bulk vs single-cell analysis skills.

---

## Questions to Resolve

1. **Owner email**: `[YOUR_EMAIL]@takeda.com` - replace with actual owner
2. **Environment**: Using `shared` - confirm this is correct
3. **SC-RNA skills**: Exclude from initial integration (incomplete)
4. **HPA data location**: Document in protein skill prerequisites
5. **Framework update**: Submit PR to add `-bulk-` category to SKILLS_MANAGEMENT_FRAMEWORK.md
