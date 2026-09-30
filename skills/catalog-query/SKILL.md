---
name: catalog-query
description: |
  Use this skill to QUERY and EXPLORE the oncology data-catalog — find which
  dataset/manifest covers a need, inspect one manifest (S3 URI, parquet schema,
  sort key, license, lineage), trace derived_from/cited_by lineage, or audit
  coverage gaps & stale references.
  (e.g. "which manifest has CPTAC phospho for tumor?", "what's the S3 path +
  schema for biogrid-physical-interactions-per-gene-v1?", "what depends on
  tcga-gdc-dr45-0?", "which indications lack a tumor-vs-normal DGE product?",
  "is there a DepMap proteomics dataset in the catalog?").
  READ-ONLY over the data-catalog YAML manifests — it never adds, edits,
  validates-and-rewrites, or pushes manifests. Do NOT use this to INGEST or
  scaffold a NEW dataset — that is the data-catalog repo's
  pull_*/scaffold_*/validate_catalog workflow, not a skill.
metadata:
  version: 1.0.0
  owner: takoncoder
  requires_preflight: false
  environment: []
status: operational    # top-level (matches compose-dashboard/render-evidence-package): read-only catalog query/explore tool, not a wired evaluation skill. Clears framework_health missing_status_field; kept OUT of composition so the composition-schema status enum (wired/not_wired/partial) doesn't reject it.
composition:
  data_mode: catalog_read
  synthesis: [none]
  output_shape: [text_report]
  delegates_to:
    - onc_methods/catalog_query/cli.py
---

# Catalog Query (read-only)

## What this skill is — and the invariant it enforces

This skill **reads** the data-catalog to help you find and understand datasets.
It does not compute evidence, and it does not touch the catalog. The reusable
query engine lives in `analysis-methods` as `onc_methods/catalog_query/` (per the
framework rule: *skills call methods; methods don't know about skills*); this
skill is a thin front end that subprocess-invokes that method's CLI.

```
data-catalog repo  →  AUTHOR: pull_*/scaffold_*/validate_catalog add & verify
                      manifests.                          (NOT this skill)
onc_methods/catalog_query → READ: parse manifest YAML, answer queries.  (compute)
skills/ (here)       → INVOKE: run the method CLI for a question.   (this skill)
```

**Why the read-only separation is physical, not just convention:** the method
imports no boto3/s3fs/requests and opens no file in write mode (guarded by a
test). It is a pure function of the on-disk catalog. It cannot ingest, mutate,
or publish — so "accidentally edit a manifest from a query" is impossible.

## The contract

Four questions, one subcommand each. Point at non-default checkouts with
`--catalog-root` / `--contracts-root` (or `ANALYSIS_METHODS_ROOT` /
`DATA_CATALOG_ROOT` env vars).

| subcommand | answers |
|---|---|
| `search`   | which manifests match a keyword + facets (provider, data_subject, type, file category, license, system_of_record)? |
| `describe` | authoritative single view of one manifest: s3_uri, parquet_schema, sort key, license, size, derived_from, cited_by, consuming products |
| `lineage`  | walk `derived_from` (upstream) / `cited_by` (downstream, incl. subgroup-catalog citations) |
| `audit`    | DGE coverage gaps · superseded-but-still-present manifests · uncited source-releases |

## Prerequisites

None beyond a local checkout of `analysis-methods` (for the method) and
`data-catalog` (the data). **No AWS profile is needed** — this is a filesystem
read of manifest YAML, not an S3 read of the datasets themselves. (Contrast the
sibling `query-target-evidence`, which DOES read S3 and needs `AWS_PROFILE=cbg`.)

## Usage

```bash
# find datasets
python skills/catalog-query/scripts/run.py search "CPTAC phospho" --data-subject tumor

# everything about one manifest (add --json for machine-readable)
python skills/catalog-query/scripts/run.py describe biogrid-physical-interactions-per-gene-v1

# lineage in either direction
python skills/catalog-query/scripts/run.py lineage tcga-gdc-dr45-0 --direction downstream

# catalog health
python skills/catalog-query/scripts/run.py audit --coverage-gaps
```

`run.py` forwards all arguments verbatim to `onc_methods/catalog_query/cli.py`.

## What it returns

Human-readable text by default; `--json` for downstream consumers. `describe`
returns the s3_uri + parquet_schema + query_optimization sort key (the fields a
reader needs to actually consume the dataset), plus the lineage + which
products/subgroup-catalogs consume it. `lineage` renders an ASCII tree.

## What it explicitly does NOT do

- Does not read the datasets themselves from S3 (only the manifest YAML on disk).
- Does not write, edit, validate-and-rewrite, or push any manifest.
- Does not scaffold or ingest a new dataset, and does not run `validate_catalog.py`.
- Does not make scientific judgments — it reports catalog facts, not evidence.

## Related

- `onc_methods/catalog_query/` (analysis-methods) — the query engine this wraps;
  also importable as a library (`from onc_methods.catalog_query import load_catalog,
  s3_uri_for`) and **resolver-ready** (the seam for a shared manifest_id → s3_uri
  resolver that could retire the ~57 hard-coded S3 keys across methods/).
- The data-catalog repo's `scripts/{pull_*,scaffold_*,validate_catalog}.py` —
  the *write* path (add/verify a manifest), which this skill deliberately is not.
- `query-target-evidence` — the sibling retrieval skill; that one reads the
  pre-computed evidence.json artifacts from S3 (needs AWS_PROFILE=cbg).
