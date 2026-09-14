# Oncology Skills — Development Guidelines

## Overview

This repository is the active development home for the oncology **target-evaluation
and profiling** Claude Code skills. The long-lived integration branch is
`v2-architecture` (not `main`); all feature work branches off it and merges back via
PR. This document describes the current (v2) layout, skill anatomy, and the
branch / test / data-access conventions. It supersedes the earlier v1 guidelines,
which described an `ai-sci-claude-skills` sync flow and a per-skill `pixi.toml`
layout that no longer exist.

## Repository layout

```
repo-root/
├── skills/
│   ├── _skills_common/          # shared harness: dispatcher, resolver, synthesis,
│   │                            #   write_package, provenance, card accessors, …
│   ├── <skill-name>/
│   │   ├── SKILL.md             # skill definition + frontmatter (required)
│   │   ├── scripts/run.py       # entrypoint (most skills delegate to run_wired_skill)
│   │   └── tests/               # per-skill pytest suite
│   └── tests/                   # cross-skill invariant guards
├── core-artifacts-schema/       # shared JSON schemas for emitted artifacts
├── docs/                        # design notes, scope reviews
├── batch/, configs/, notebooks/, libs/
├── pixi.toml / pixi.lock        # ONE environment for the whole repo
└── .github/workflows/           # CI (skills-validate.yml — required check)
```

There is a **single repo-level `pixi` environment** (`pixi.toml` at the root); skills
do not carry their own `pixi.toml`. The three sibling framework repos
(`analysis-methods`, `target-contracts`, and the `target_id_resolver` lib in
`data-catalog`) are declared as editable path dependencies.

## Skill anatomy

Most skills are a single `skills/<name>/scripts/run.py` that routes through the shared
harness `_skills_common.dispatcher.run_wired_skill(...)` — argument parsing, card
resolution, rule firing, packaging, provenance, and synthesis dispatch are all
single-sourced there. Verdict logic is expressed as a **declarative resolver spec**
(`target-contracts/resolvers/<gate>.resolver.yaml`) evaluated by one interpreter
(`_skills_common.resolver`); a skill's `_verdict` delegates via
`resolve_or_raise(fired, "<gate>")` rather than hand-rolling an if-chain.

- **Biology-first output.** The primary output (verdict + driving `rule_id`) is
  modality-independent; modality is a post-hoc lens (optional `--modality`).
- **Honest absence.** A card read but with no usable value emits `DATA_UNAVAILABLE`
  (a decision-useful measured-null), distinct from a card never wired.
- **`SKILL.md` frontmatter** — `name`, `description` (with trigger phrases),
  `metadata` (version, owner). Skills registered in the plugin are listed in
  `.claude-plugin/marketplace.json`; keep that list in sync with the skills present.

## Branch & PR discipline

Work in a **per-workstream git worktree** cut off `v2-architecture`. Do not develop
directly in the primary checkout (parallel sessions share one index — worktrees give
structural isolation).

```bash
# create an isolated worktree + branch (writes .claude/branch-scope, prints a registry stub)
~/.claude/git-hooks/new-worktree claude-oncology-skills <prefix>/<name> --scope skills/

# ... edit in the printed /tmp/wt/... directory, then:
git add -A && git commit -m "..."
git push -u origin <prefix>/<name>          # pre-push nudges you to open a PR
gh pr create --base v2-architecture --fill  # draft is fine

# land when CI is green (enables auto-merge; prunes worktree + branch after merge):
~/.claude/git-hooks/land-pr <pr#> --repo claude-oncology-skills
```

- **Approved branch prefixes:** `feat/`, `fix/`, `chore/`, `feature/` (enforced by
  `.claude/hooks/pre-commit`).
- **Base branch:** `v2-architecture` (this repo's `default_base`).
- **One workstream per branch;** draft PR on first push.
- **Required status checks** on `v2-architecture` are exactly two contexts — `pytest` (from
  `skills-validate.yml`) and `ruff` (from `ruff.yml`) — with `strict: false`, so a PR merges
  once both are green. CodeQL / `Analyze (python)` also run on every PR (org-level default
  setup) but are **not** required contexts and do not gate the merge. Four checks run; two
  gate. Re-measure rather than trusting this line:
  `gh api 'repos/{owner}/{repo}/branches/v2-architecture/protection' --jq .required_status_checks`

## Testing

Run under `pixi` (the repo environment), per-skill with importlib isolation — this is
how CI runs it, and it avoids `import run` collisions across skills that each ship a
`scripts/run.py`:

```bash
pixi run pytest skills/<skill-name>/tests/ -q --import-mode=importlib
pixi run pytest skills/_skills_common/tests/ -q     # shared harness
pixi run pytest skills/tests/ -q --import-mode=importlib   # cross-skill guards
```

Before opening a PR: run the touched skill's suite, the `_skills_common` suite, and —
for changes to shared verdict / resolver / synthesis code — `target-profile/tests/`
and the cross-skill guards.

## Data access

Skills read **derived products** (gene-sorted parquet) with **predicate pushdown** via
the `methods/<name>/read.py` readers in the `analysis-methods` repo, resolving dataset
locations through the data-catalog manifests and the **target-id resolver** sidecar.
Do not add ad-hoc `boto3` / `s3fs` download code or `verify=False` clients in skills —
data access is single-sourced through the readers and the catalog.

## Contact

- Owner: ming-ju.tsai@takeda.com
- Repository: https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills
