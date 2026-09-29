# Oncology Skills — Development Guidelines

## Overview

This repository is the active development home for the oncology **target-evaluation
and profiling** Claude Code skills. The trunk is `main`; all feature work branches off
it and merges back via PR. (Until 2026-09-16 the trunk was `v2-architecture` and `main`
held the v1 plugin — see [README](README.md#v1-is-archived).)

**Writing your first skill?** Start with
[docs/AUTHORING_A_SKILL.md](docs/AUTHORING_A_SKILL.md), which walks the end-to-end path
from evidence card to landed PR. This document is the reference behind it: the current
(v2) layout, skill anatomy, and the branch / test / data-access conventions. It supersedes
the earlier v1 guidelines, which described an `ai-sci-claude-skills` sync flow and a
per-skill `pixi.toml` layout that no longer exist.

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
├── methods/                     # the merged former analysis-methods repo (method CLIs)
├── contracts/                   # the merged former target-contracts repo (cards, rules,
│                                 #   resolvers, schemas, vocabularies)
├── core-artifacts-schema/       # shared JSON schemas for emitted artifacts
├── docs/                        # design notes, scope reviews
├── batch/, configs/, notebooks/, libs/, eval/
├── pixi.toml / pixi.lock        # ONE environment for the whole repo (editable path deps
│                                 #   on ./methods and ./contracts)
└── .github/workflows/           # CI (skills-validate.yml — required `pytest` check)
```

There is a **single repo-level `pixi` environment** (`pixi.toml` at the root); skills
do not carry their own `pixi.toml`. `methods/` and `contracts/` (the former
`analysis-methods` and `target-contracts` repos, merged in-tree — SK#2063) are
declared as editable path dependencies pointing at `./methods` / `./contracts`. The
one remaining sibling is `data-catalog`'s `target_id_resolver` lib, an editable path
dependency resolved from `../rnd-computational-biology-oncology-data-catalog`.

## Skill anatomy

Most skills are a single `skills/<name>/scripts/run.py` that routes through the shared
harness `_skills_common.dispatcher.run_wired_skill(...)` — argument parsing, card
resolution, rule firing, packaging, provenance, and synthesis dispatch are all
single-sourced there. Verdict logic is expressed as a **declarative resolver spec**
(`contracts/resolvers/<gate>.resolver.yaml`) evaluated by one interpreter
(`_skills_common.resolver`); a skill's `_verdict` delegates via
`resolve_or_raise(fired, "<gate>")` rather than hand-rolling an if-chain.

- **Biology-first output.** The primary output (verdict + driving `rule_id`) is
  modality-independent; modality is a post-hoc lens (optional `--modality`).
- **Honest absence.** A card read but with no usable value emits `DATA_UNAVAILABLE`
  (a decision-useful measured-null), distinct from a card never wired.
- **`SKILL.md` frontmatter** — `name`, `description` (with trigger phrases),
  `metadata` (version, owner). Skills registered in the plugin are listed in
  `.claude-plugin/marketplace.json`; keep that list in sync with the skills present.

## Branch, PR, and testing discipline

**Process (worktrees, branch prefixes, PR/landing, required checks, the
`scripts/preland.sh` gate dispatcher) lives entirely in root
[CLAUDE.md](CLAUDE.md)** — that document is the sole process entry point for this
repo; nothing below duplicates it. This section is only the skills-specific testing
shape:

```bash
pixi run pytest skills/<skill-name>/tests/ -q --import-mode=importlib
pixi run pytest skills/_skills_common/tests/ -q     # shared harness
pixi run pytest skills/tests/ -q --import-mode=importlib   # cross-skill guards
```

Before opening a PR: run the touched skill's suite, the `_skills_common` suite, and —
for changes to shared verdict / resolver / synthesis code — `target-profile/tests/`
and the cross-skill guards. For anything beyond a single skill (methods/contracts
also touched, or a `cards/`/`interpretation-rules/`/`resolvers/`/`vocabularies/`
change), run `scripts/preland.sh all` per CLAUDE.md's Testing section.

## Data access

Skills read **derived products** (gene-sorted parquet) with **predicate pushdown** via
the `methods/<name>/read.py` readers, resolving dataset locations through the
data-catalog manifests and the **target-id resolver** sidecar. Do not add ad-hoc
`boto3` / `s3fs` download code or `verify=False` clients in skills — data access is
single-sourced through the readers and the catalog.

## Contact

- Owner: ming-ju.tsai@takeda.com
- Repository: https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills
