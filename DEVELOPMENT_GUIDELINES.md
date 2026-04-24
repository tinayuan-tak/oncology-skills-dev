# Oncology Skills Development & Integration Guidelines

## Overview

This document defines the workflow for developing oncology Claude Code skills in the `rnd-computational-biology-oncology-claude-oncology-skills` repository and integrating them into the `ai-sci-claude-skills` production repository.

## Repository Roles

| Repository | Purpose | Branch Strategy |
|------------|---------|-----------------|
| `rnd-computational-biology-oncology-claude-oncology-skills` | Development, testing, iteration | `main` → `dev` → `feature/*` |
| `ai-sci-claude-skills` | Production skills, shared across teams | `main` → `feature/*` (PR-based) |

## Directory Structure

Both repos use the same structure for easy integration:

```
repo-root/
├── skills/
│   ├── analysis-bulk-rna-crc/
│   │   ├── SKILL.md
│   │   ├── README.md
│   │   ├── crc_comprehensive_analysis.py
│   │   └── pixi.toml
│   ├── analysis-bulk-rna-nsclc/
│   │   ├── SKILL.md
│   │   ├── README.md
│   │   ├── nsclc_comprehensive_analysis.py
│   │   └── pixi.toml
│   ├── analysis-protein-crc/
│   ├── analysis-protein-nsclc/
│   └── workflow-target-evaluation-onc/
├── docs/
└── README.md
```

## Naming Conventions

Follow `ai-sci-claude-skills` naming taxonomy:

| Pattern | Example | Description |
|---------|---------|-------------|
| `analysis-{method}-{disease}` | `analysis-bulk-rna-crc` | Data analysis skills |
| `workflow-{name}-{domain}` | `workflow-target-evaluation-onc` | Multi-step workflows |

**Skill file naming:**
- `SKILL.md` - Skill definition (required, follows ai-sci template)
- `README.md` - Human documentation
- `{descriptive_name}.py` - Main script
- `pixi.toml` - Dependencies

## Development Workflow

### Phase 1: Feature Development (oncology repo)

```bash
# 1. Start from dev branch
cd /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills
git checkout dev
git pull origin dev

# 2. Create feature branch
git checkout -b feature/{feature-name}

# 3. Develop and test
# ... make changes ...
pixi install
pixi run python {script}.py --genes TNFRSF12A

# 4. Commit changes
git add .
git commit -m "Add {feature description}"

# 5. Push feature branch
git push -u origin feature/{feature-name}

# 6. Merge to dev (after testing)
git checkout dev
git merge feature/{feature-name}
git push origin dev

# 7. Delete feature branch (optional)
git branch -d feature/{feature-name}
```

### Phase 2: Integration to ai-sci

```bash
# 1. Create feature branch in ai-sci
cd /Users/eta3879/tools/ai-sci-claude-skills
git checkout main
git pull origin main
git checkout -b feature/oncology-{skill-name}

# 2. Copy validated skill from oncology repo
cp -r /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills/skills/analysis-bulk-rna-crc \
      skills/

# 3. Validate against ai-sci standards
# - Check SKILL.md frontmatter
# - Check pixi.toml format
# - Run any ai-sci validation scripts

# 4. Commit and push
git add skills/analysis-bulk-rna-crc/
git commit -m "Add analysis-bulk-rna-crc skill from oncology repo"
git push -u origin feature/oncology-{skill-name}

# 5. Create PR for review
gh pr create --title "Add oncology bulk RNA CRC analysis skill" \
  --body "Integrates validated skill from oncology-skills repo"
```

## SKILL.md Template

All skills must use this frontmatter format (from ai-sci standards):

```yaml
---
name: analysis-bulk-rna-crc
description: |
  Comprehensive CRC bulk RNA-seq analysis with TCGA, GTEx, CCLE, and Tempus data.
  Trigger phrases: "analyze CRC expression", "CRC bulk RNA", "colorectal cancer gene"
metadata:
  version: "1.0.0"
  owner: ming-ju.tsai@takeda.com
  requires_preflight: false
  environment:
    - AWS_PROFILE=cbg (for S3 access)
---
```

## Sync Procedures

### Bug Fix in Oncology Repo

```bash
# 1. Fix in oncology repo (feature branch → dev)
cd /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills
git checkout -b fix/{bug-description}
# ... fix bug ...
git commit -m "Fix {bug description}"
git checkout dev && git merge fix/{bug-description}

# 2. Copy fix to ai-sci (if already integrated)
cd /Users/eta3879/tools/ai-sci-claude-skills
git checkout -b fix/oncology-{bug-description}
cp /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills/skills/{skill}/{file} \
   skills/{skill}/{file}
git commit -m "Fix {bug description} in oncology skill"
# Create PR
```

### New Feature Addition

```bash
# 1. Develop fully in oncology repo first
# 2. Test thoroughly
# 3. Only then copy to ai-sci via PR
```

### ai-sci Standard Update

When ai-sci updates its standards (SKILL.md template, pixi.toml format, etc.):

```bash
# 1. Update oncology repo to match
cd /Users/eta3879/tools/rnd-computational-biology-oncology-claude-oncology-skills
git checkout -b chore/update-ai-sci-standards
# ... update SKILL.md files, pixi.toml, etc. ...
git commit -m "Update to ai-sci standards v{X.X}"
```

## Checklist: Before Integration to ai-sci

- [ ] Skill tested with real data in oncology repo
- [ ] SKILL.md follows ai-sci template
- [ ] pixi.toml includes all dependencies
- [ ] No hardcoded local paths (use S3 or configurable paths)
- [ ] README.md documents usage
- [ ] Python syntax validated (`python -m py_compile {script}.py`)
- [ ] Naming follows ai-sci taxonomy

## Version Tracking

Track which version of oncology skills are in ai-sci:

| Skill | Oncology Repo Version | ai-sci Version | Last Sync Date |
|-------|----------------------|----------------|----------------|
| analysis-bulk-rna-crc | dev@{commit} | - | Not integrated |
| analysis-bulk-rna-nsclc | dev@{commit} | - | Not integrated |
| analysis-protein-crc | - | - | Planned |
| analysis-protein-nsclc | - | - | Planned |
| workflow-target-evaluation-onc | dev@{commit} | - | Not integrated |

## S3 Data Access Pattern

All skills use boto3/s3fs for S3 access (not AWS CLI subprocess):

```python
import boto3
import s3fs
from botocore.exceptions import ClientError

AWS_PROFILE = 'cbg'

def get_s3_client():
    """Get boto3 S3 client with profile credentials."""
    session = boto3.Session(profile_name=AWS_PROFILE)
    return session.client('s3', verify=False)

def download_s3_file(s3_path, local_path):
    """Download file from S3 if not already cached."""
    if os.path.exists(local_path):
        return local_path
    bucket, key = parse_s3_uri(s3_path)
    get_s3_client().download_file(bucket, key, local_path)
    return local_path
```

## Contact

- Owner: ming-ju.tsai@takeda.com
- Repository: https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills
