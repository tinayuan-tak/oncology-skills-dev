# Oncology Skills Integration Plan

**Version**: 2.1.0
**Date**: 2026-04-23
**Source Repository**: `/Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills`
**Target Repository**: `/Users/eta3879/tools/ai-sci-claude-skills`

---

## Executive Summary

Integrate oncology target evaluation skills into `ai-sci-claude-skills` using a phased approach:

| Phase | Skills | Status |
|-------|--------|--------|
| **Phase 1** | `analysis-bulk-rna-crc`, `analysis-bulk-rna-nsclc` | **READY TO START** |
| **Phase 2** | `analysis-protein-crc`, `analysis-protein-nsclc` | Planned |
| **Phase 3** | `workflow-target-evaluation-onc` | After analysis skills tested |

**Rationale**: Build and test analysis skills first (foundation), then add the orchestrating workflow.

---

## Phase 1: Bulk RNA-seq Analysis Skills (START HERE)

### 1.1 Setup Feature Branch

```bash
cd /Users/eta3879/tools/ai-sci-claude-skills
git fetch origin
git checkout main
git pull origin main
git checkout -b feature/add-oncology-bulk-rna-skills
```

### 1.2 Create Directory Structure

```bash
mkdir -p skills/analysis-bulk-rna-crc/{scripts,references}
mkdir -p skills/analysis-bulk-rna-nsclc/{scripts,references}
```

---

## Phase 1A: analysis-bulk-rna-crc

### Source Location
```
/Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills/oncology-skills/crc-bulk-rna-analysis/
```

### Target Structure
```
skills/analysis-bulk-rna-crc/
├── SKILL.md
├── pyproject.toml
├── .env.example
└── scripts/
    ├── crc_comprehensive_analysis.py
    └── check_setup.py
```

### Step 1: Create SKILL.md

```bash
cat > skills/analysis-bulk-rna-crc/SKILL.md << 'EOF'
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

# Bulk RNA Expression Analysis for CRC

## Overview

Comprehensive bulk RNA-seq analysis for colorectal cancer target evaluation. Integrates TCGA, GTEx, and Tempus real-world data to assess target expression, on-target toxicity risk, and iDAS strategic alignment.

## Prerequisites

### Required Environment Variables

```bash
export AWS_PROFILE=cbg
```

Or create `.env` file:
```bash
cp .env.example .env
```

### Verify Setup

```bash
cd "<skill_directory>" && python scripts/check_setup.py
```

## Core Capabilities

### 1. On-Target Toxicity Assessment
Primary metric: Tumor vs Adjacent Normal expression (predicts GI toxicity)
- **LOW risk**: >2x tumor enrichment
- **MEDIUM risk**: 1.5-2x tumor enrichment  
- **HIGH risk**: <1.5x tumor enrichment

### 2. TCGA/GTEx Expression Analysis
- TCGA-COAD/READ tumor samples
- TCGA adjacent normal tissue
- GTEx healthy colon baseline
- CCLE CRC cell lines

### 3. Tempus Real-World Data
- >200,000 CRC patients
- Line-of-therapy stratification (1L/2L vs 3L+)
- RAS mutation status
- CMS subtype expression

### 4. iDAS Strategic Alignment
Priority whitespaces:
- Chemorefractory 3L+ MSS
- RAS mutant frontline
- RAS mutant refractory

## Usage

```bash
python scripts/crc_comprehensive_analysis.py --genes TNFRSF12A --output-dir ./results

# Multiple genes
python scripts/crc_comprehensive_analysis.py --genes "TNFRSF12A CDCP1 EPCAM" --output-dir ./results

# Skip Tempus (faster, TCGA only)
python scripts/crc_comprehensive_analysis.py --genes TNFRSF12A --skip-tempus
```

## Output Files

| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel figure |
| `{GENE}_comprehensive_report.md` | Full analysis report |
| `{GENE}_idas_assessment.yaml` | iDAS alignment data |
| `{GENE}_subgroup_suitability.csv` | 3-phase subgroup scores |
| `{GENE}_pairwise_comparisons.csv` | Statistical comparisons |

## Data Sources

| Source | Location | Description |
|--------|----------|-------------|
| TCGA | `s3://onc-compbio/omicsoft_oncoland_data` | Tumor + adjacent normal |
| GTEx | `s3://onc-compbio/omicsoft_oncoland_data` | Normal colon |
| Tempus | `s3://onc-compbio/Tempus/crc` | Real-world evidence |
| CCLE | `s3://onc-compbio/omicsoft_oncoland_data` | Cell lines |

## Related Skills

- `analysis-bulk-rna-nsclc`: For NSCLC expression analysis
- `analysis-protein-crc`: For protein-level validation (planned)
- `workflow-target-evaluation-onc`: Full target evaluation workflow
EOF
```

### Step 2: Create pyproject.toml

```bash
cat > skills/analysis-bulk-rna-crc/pyproject.toml << 'EOF'
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
EOF
```

### Step 3: Create .env.example

```bash
cat > skills/analysis-bulk-rna-crc/.env.example << 'EOF'
# AWS credentials for S3 access (TCGA/GTEx/Tempus data)
AWS_PROFILE=cbg

# S3 bucket locations (usually not changed)
# TCGA_S3_BUCKET=s3://onc-compbio/omicsoft_oncoland_data
# TEMPUS_S3_BUCKET=s3://onc-compbio/Tempus/crc
EOF
```

### Step 4: Create check_setup.py

```bash
cat > skills/analysis-bulk-rna-crc/scripts/check_setup.py << 'EOF'
#!/usr/bin/env python3
"""Pre-flight check for analysis-bulk-rna-crc."""
import os
import sys

def check_dependencies():
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

def check_aws_credentials():
    profile = os.environ.get('AWS_PROFILE', 'cbg')
    try:
        import boto3
        session = boto3.Session(profile_name=profile)
        s3 = session.client('s3')
        s3.head_bucket(Bucket='onc-compbio')
        print(f"✓ AWS credentials valid, S3 bucket accessible")
        return True
    except Exception as e:
        print(f"✗ AWS/S3 error: {e}")
        return False

def main():
    print("=" * 50)
    print("analysis-bulk-rna-crc Pre-flight Check")
    print("=" * 50)
    all_passed = check_dependencies() and check_aws_credentials()
    print("\n" + "=" * 50)
    if all_passed:
        print("✓ All checks passed. Ready to use skill.")
        sys.exit(0)
    else:
        print("✗ Some checks failed. Please fix issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
EOF
```

### Step 5: Copy Analysis Script

```bash
cp /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills/oncology-skills/crc-bulk-rna-analysis/crc_comprehensive_analysis.py \
   skills/analysis-bulk-rna-crc/scripts/
```

### Phase 1A Checklist

- [ ] Create SKILL.md
- [ ] Create pyproject.toml
- [ ] Create .env.example
- [ ] Create scripts/check_setup.py
- [ ] Copy crc_comprehensive_analysis.py to scripts/
- [ ] Verify SKILL.md body < 500 lines
- [ ] Test: `python scripts/check_setup.py`
- [ ] Test: `python scripts/crc_comprehensive_analysis.py --genes TNFRSF12A --output-dir ./test_output`

---

## Phase 1B: analysis-bulk-rna-nsclc

### Source Location
```
/Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills/oncology-skills/nsclc-bulk-rna-analysis/
```

### Target Structure
```
skills/analysis-bulk-rna-nsclc/
├── SKILL.md
├── pyproject.toml
├── .env.example
└── scripts/
    ├── nsclc_comprehensive_analysis.py
    └── check_setup.py
```

### Step 1: Create SKILL.md

```bash
cat > skills/analysis-bulk-rna-nsclc/SKILL.md << 'EOF'
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

# Bulk RNA Expression Analysis for NSCLC

## Overview

Comprehensive bulk RNA-seq analysis for non-small cell lung cancer target evaluation. Integrates TCGA LUAD/LUSC, GTEx, and Tempus real-world data to assess target expression, on-target toxicity risk, and iDAS strategic alignment.

## Prerequisites

### Required Environment Variables

```bash
export AWS_PROFILE=cbg
```

### Verify Setup

```bash
cd "<skill_directory>" && python scripts/check_setup.py
```

## Core Capabilities

### 1. On-Target Toxicity Assessment
Primary metric: Tumor vs Adjacent Normal expression (predicts pulmonary toxicity)
- **LOW risk**: >2x tumor enrichment
- **MEDIUM risk**: 1.5-2x tumor enrichment  
- **HIGH risk**: <1.5x tumor enrichment

### 2. TCGA/GTEx Expression Analysis
- TCGA-LUAD (adenocarcinoma)
- TCGA-LUSC (squamous cell carcinoma)
- TCGA adjacent normal lung
- GTEx healthy lung baseline
- CCLE NSCLC cell lines

### 3. Tempus Real-World Data
- ~1,867 patients, ~3,500 samples
- Biomarker stratification (EGFR, KRAS, STK11, KEAP1)
- Line-of-therapy data
- AGA (actionable genomic alterations) status

### 4. iDAS Strategic Alignment
Priority whitespaces:
- 2L Non-AGA (IO-experienced)
- 2L EGFR Mutant (post-TKI)
- 1L/2L KRAS Mutant

## Usage

```bash
python scripts/nsclc_comprehensive_analysis.py --genes CDCP1 --output-dir ./results

# Multiple genes
python scripts/nsclc_comprehensive_analysis.py --genes "CDCP1 EGFR MET" --output-dir ./results

# Skip Tempus (faster, TCGA only)
python scripts/nsclc_comprehensive_analysis.py --genes CDCP1 --skip-tempus
```

## Output Files

| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel figure |
| `{GENE}_comprehensive_report.md` | Full analysis report |
| `{GENE}_idas_assessment.yaml` | iDAS alignment data |
| `{GENE}_subgroup_suitability.csv` | 3-phase subgroup scores |
| `{GENE}_tcga_mutation_statistics.csv` | Mutation status expression |

## Data Sources

| Source | Location | Description |
|--------|----------|-------------|
| TCGA | `s3://onc-compbio/omicsoft_oncoland_data` | LUAD/LUSC + adjacent normal |
| GTEx | `s3://onc-compbio/omicsoft_oncoland_data` | Normal lung |
| Tempus | Local | Real-world evidence |
| CCLE | `s3://onc-compbio/omicsoft_oncoland_data` | Cell lines |

## Related Skills

- `analysis-bulk-rna-crc`: For CRC expression analysis
- `analysis-protein-nsclc`: For protein-level validation (planned)
- `workflow-target-evaluation-onc`: Full target evaluation workflow
EOF
```

### Step 2: Create pyproject.toml

```bash
cat > skills/analysis-bulk-rna-nsclc/pyproject.toml << 'EOF'
[project]
name = "analysis-bulk-rna-nsclc"
version = "1.0.0"
description = "Bulk RNA expression analysis for NSCLC targets"
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
EOF
```

### Step 3: Create .env.example and check_setup.py

```bash
# .env.example (same as CRC)
cat > skills/analysis-bulk-rna-nsclc/.env.example << 'EOF'
AWS_PROFILE=cbg
EOF

# check_setup.py (same structure, different name in output)
cat > skills/analysis-bulk-rna-nsclc/scripts/check_setup.py << 'EOF'
#!/usr/bin/env python3
"""Pre-flight check for analysis-bulk-rna-nsclc."""
import os
import sys

def check_dependencies():
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

def check_aws_credentials():
    profile = os.environ.get('AWS_PROFILE', 'cbg')
    try:
        import boto3
        session = boto3.Session(profile_name=profile)
        s3 = session.client('s3')
        s3.head_bucket(Bucket='onc-compbio')
        print(f"✓ AWS credentials valid, S3 bucket accessible")
        return True
    except Exception as e:
        print(f"✗ AWS/S3 error: {e}")
        return False

def main():
    print("=" * 50)
    print("analysis-bulk-rna-nsclc Pre-flight Check")
    print("=" * 50)
    all_passed = check_dependencies() and check_aws_credentials()
    print("\n" + "=" * 50)
    if all_passed:
        print("✓ All checks passed. Ready to use skill.")
        sys.exit(0)
    else:
        print("✗ Some checks failed. Please fix issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
EOF
```

### Step 4: Copy Analysis Script

```bash
cp /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills/oncology-skills/nsclc-bulk-rna-analysis/nsclc_comprehensive_analysis.py \
   skills/analysis-bulk-rna-nsclc/scripts/
```

### Phase 1B Checklist

- [ ] Create SKILL.md
- [ ] Create pyproject.toml
- [ ] Create .env.example
- [ ] Create scripts/check_setup.py
- [ ] Copy nsclc_comprehensive_analysis.py to scripts/
- [ ] Verify SKILL.md body < 500 lines
- [ ] Test: `python scripts/check_setup.py`
- [ ] Test: `python scripts/nsclc_comprehensive_analysis.py --genes CDCP1 --output-dir ./test_output`

---

## Phase 1 Commit & Test

### Commit Phase 1

```bash
cd /Users/eta3879/tools/ai-sci-claude-skills

git add skills/analysis-bulk-rna-crc/ skills/analysis-bulk-rna-nsclc/
git commit -m "Add bulk RNA analysis skills for CRC and NSCLC

- analysis-bulk-rna-crc: TCGA/GTEx/Tempus integration for CRC targets
- analysis-bulk-rna-nsclc: TCGA/GTEx/Tempus integration for NSCLC targets
- Includes on-target toxicity assessment, iDAS alignment, subgroup suitability
- Per SKILLS_MANAGEMENT_FRAMEWORK.md and CONTRIBUTION_GUIDE.md"
```

### Run Tests

```bash
# Structure tests
cd tests/skills
pytest -v test_skill_structure.py -k "analysis_bulk_rna"

# Content tests
pytest -v test_skill_content.py -k "analysis_bulk_rna"

# Manual test - CRC
cd ../../skills/analysis-bulk-rna-crc
python scripts/crc_comprehensive_analysis.py --genes TNFRSF12A --output-dir ./test_output

# Manual test - NSCLC
cd ../analysis-bulk-rna-nsclc
python scripts/nsclc_comprehensive_analysis.py --genes CDCP1 --output-dir ./test_output
```

---

## Phase 2: Protein Analysis Skills (After Phase 1 Tested)

### 2.1 analysis-protein-crc

| Item | Value |
|------|-------|
| Source | Human Protein Atlas API |
| Purpose | IHC expression, subcellular localization, GI toxicity assessment |
| Status | **Planned** |

### 2.2 analysis-protein-nsclc

| Item | Value |
|------|-------|
| Source | Human Protein Atlas API |
| Purpose | IHC expression, subcellular localization, pulmonary toxicity assessment |
| Status | **Planned** |

### Phase 2 Checklist

- [ ] Implement HPA data fetching for CRC
- [ ] Implement HPA data fetching for NSCLC
- [ ] Create SKILL.md files
- [ ] Test protein analysis skills
- [ ] Commit and validate

---

## Phase 3: Target Evaluation Workflow (After Phase 2 Tested)

### 3.1 workflow-target-evaluation-onc

| Item | Value |
|------|-------|
| Dependencies | analysis-bulk-rna-crc, analysis-bulk-rna-nsclc, analysis-protein-crc, analysis-protein-nsclc |
| Purpose | 4-step target evaluation: Risk Assessment → Expression Analysis → ScholarEval → PDF Report |
| Status | **After Phase 2** |

### Phase 3 Checklist

- [ ] Create workflow-target-evaluation-onc directory structure
- [ ] Copy scripts (scoring_engine.py, validation_checkpoints.py, etc.)
- [ ] Copy references (risk templates, criteria TSV)
- [ ] Copy configs (scoring_rules.yaml)
- [ ] Update SKILL.md with dependency declarations
- [ ] Test full workflow with TNFRSF12A in CRC
- [ ] Test full workflow with CDCP1 in NSCLC
- [ ] Commit and validate

---

## Compliance Checklist (from docs/)

### Per Skill Requirements

| Requirement | CRC | NSCLC | Source |
|-------------|-----|-------|--------|
| Valid category prefix (`analysis-`) | ✅ | ✅ | NAMING_TAXONOMY.md |
| Valid domain suffix (`-bulk-rna`) | ✅ | ✅ | SKILLS_MANAGEMENT_FRAMEWORK.md |
| Disease qualifier (`-crc`, `-nsclc`) | ✅ | ✅ | SKILLS_MANAGEMENT_FRAMEWORK.md |
| SKILL.md with frontmatter | ✅ | ✅ | SKILL_TEMPLATE.md |
| `name` matches folder | ✅ | ✅ | CONTRIBUTION_GUIDE.md |
| Trigger phrases in description | ✅ | ✅ | CONTRIBUTION_GUIDE.md |
| 3+ example queries | ✅ | ✅ | CONTRIBUTION_GUIDE.md |
| "Do NOT use" alternatives | ✅ | ✅ | CONTRIBUTION_GUIDE.md |
| SKILL.md < 500 lines | ✅ | ✅ | CONTRIBUTION_GUIDE.md |
| Scripts in `scripts/` folder | ✅ | ✅ | SKILLS_MANAGEMENT_FRAMEWORK.md |
| pyproject.toml (shared env) | ✅ | ✅ | SKILLS_MANAGEMENT_FRAMEWORK.md |
| .env.example | ✅ | ✅ | CONTRIBUTION_GUIDE.md |
| check_setup.py | ✅ | ✅ | CONTRIBUTION_GUIDE.md |
| No README.md | ✅ | ✅ | SKILLS_MANAGEMENT_FRAMEWORK.md |
| No .pixi/ committed | ✅ | ✅ | CONTRIBUTION_GUIDE.md |

---

## PR Template (Phase 1)

```markdown
## Skills: Oncology Bulk RNA Analysis

### Description
Adds 2 bulk RNA expression analysis skills for oncology target evaluation:
- `analysis-bulk-rna-crc`: CRC expression analysis (TCGA/GTEx/Tempus)
- `analysis-bulk-rna-nsclc`: NSCLC expression analysis (TCGA/GTEx/Tempus)

### Category
- [x] Analysis

### Checklist (per CONTRIBUTION_GUIDE.md)
- [x] SKILL.md has valid frontmatter
- [x] Names follow NAMING_TAXONOMY.md
- [x] Description includes trigger phrases and "do NOT use" alternatives
- [x] At least 3 example queries per skill
- [x] No credentials committed
- [x] .env.example provided
- [x] scripts/check_setup.py for preflight validation
- [x] SKILL.md body under 500 lines
- [x] Scripts in scripts/ folder
- [x] No README.md files
- [x] Tests pass locally

### Testing
- CRC: Tested with TNFRSF12A, CDCP1, EPCAM
- NSCLC: Tested with CDCP1, EGFR, MET

### Related
- Part of oncology target evaluation suite
- Future: analysis-protein-crc, analysis-protein-nsclc, workflow-target-evaluation-onc
```
