---
name: query-target-evidence
description: |
  Use this skill to RETRIEVE pre-computed target evidence for a gene in an indication
  (e.g. "what's the expression evidence for SCD1 in colorectal cancer / COADREAD",
  "get the dependency artifact for KRAS in PAAD / pancreatic", "show stored evidence
  for MET in NSCLC / LUAD"). Indication is a literal AACR OncoTree code (uppercase)
  — COADREAD, LUAD, LUSC, NSCLC, PAAD, STAD, etc.; see https://oncotree.mskcc.org/.
  Returns the stored evidence.json artifact from the core-artifacts store. This skill
  is RETRIEVAL-ONLY — it never recomputes. If an artifact is missing or stale, it
  reports that and points to the batch job that produces it; it does NOT run the
  analysis itself. Do NOT use this to RUN an analysis — that is a batch/ job, not a skill.
metadata:
  version: 2.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg (for S3 read access to core-artifacts)
---

# Query Target Evidence (retrieval-only)

## What this skill is — and the invariant it enforces

This skill **reads** evidence artifacts. It does not compute them. That separation is
the core of the v2 architecture (see the platform runbook):

```
batch/ jobs   →  COMPUTE: run DGE/dependency/etc. across all genes once,
                 write evidence.json artifacts to core-artifacts/.   (NOT invoked by Claude)
skills/ (here) →  RETRIEVE: read the stored evidence.json for one gene. (invoked by Claude)
```

**Why the separation is physical, not just convention:** the v1 suite had a single
script that both computed (streaming a 4 GB expression matrix and chunk-scanning it for
one gene, on every call) and reported. That made "recompute on every Claude call"
the default, which fails at scale. By making this skill *incapable* of computing —
it has no analysis code, only an S3 read — recompute-on-call becomes impossible.

## The contract

Given a `--gene`, `--indication`, and `--dimension`, this skill:

1. Reads `s3://onc-compbio/core-artifacts/{ONCOTREE_CODE}/{subtype}/{gene}/{dimension}/evidence.json`.
2. Validates it against `core-artifacts-schema/evidence.schema.json`.
3. Checks the `staleness` block (release-based, not time-based).
4. Returns the artifact, OR:
   - **Missing** → reports the artifact does not exist and names the batch job that
     produces it (e.g. `batch/expression_rna_COADREAD/run_pipeline.R` for
     `indication=COADREAD, dimension=expression-rna`). It does NOT trigger the
     batch run; a human/scheduler does that.
   - **Stale** → returns the stored artifact WITH the staleness flag set, and lets the
     scientist decide. Per runbook: never auto-rerun at a BLF or stage gate.

## Prerequisites

```bash
# cbg profile for S3 read access (see personal-notes/bin/bootstrap.sh on a fresh instance)
export AWS_PROFILE=cbg
aws sts get-caller-identity --profile cbg   # should return account 557690623046
```

## Usage

```bash
# retrieve one dimension for one gene
pixi run python scripts/query_evidence.py --gene SCD1 --indication COADREAD --dimension expression-rna

# retrieve all available dimensions for a gene
pixi run python scripts/query_evidence.py --gene SCD1 --indication COADREAD --all-dimensions

# machine-readable output (for downstream consumers / AgenticBoost)
pixi run python scripts/query_evidence.py --gene SCD1 --indication COADREAD --dimension expression-rna --json
```

## What it returns

The validated `evidence.json` (see `core-artifacts-schema/evidence.schema.json`), which
always carries: `gene`, `indication`, `dimension`, `computed_date`, `provenance`
(including `catalog_refs` — the data-catalog manifest IDs that trace back to a
re-obtainable source), `result`, `summary`, `confidence`, and `label`
(`pre-specified` | `exploratory`).

## What it explicitly does NOT do

- Does not load expression matrices, run statistics, or generate figures.
- Does not write to S3.
- Does not trigger batch jobs.
- Does not make risk-level judgments or compute scores (directional `confidence` only).

## Related

- `batch/run_global_dge.py` — the compute job that produces `expression`-dimension artifacts.
- `core-artifacts-schema/evidence.schema.json` — the artifact contract this skill enforces.
- The data-catalog repo — where `provenance.catalog_refs` IDs resolve to source datasets.
