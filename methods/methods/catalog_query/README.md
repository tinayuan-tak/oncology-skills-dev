# catalog_query

Read-only query engine over the [data-catalog](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog)
manifests. Answers "which dataset do I need?", "what's the S3 path + schema for
manifest M?", "what's downstream of GDC?", and "which indications lack a DGE
product?" — without grepping 219 manifest YAMLs by hand.

**Read-only, filesystem-only, zero-write.** No S3, no AWS profile, no network.
It is a pure function of the on-disk catalog. Producing/mutating manifests is the
data-catalog repo's `pull_*` / `scaffold_*` / `validate_catalog.py` workflow — not
this method.

## Why it lives here (not in skills/)

Per the framework's layer discipline (see `dge_deseq2/read.py`), reading + filtering
catalog YAML is *compute*, not *orchestration*. Skills call methods; methods don't
know about skills. The `catalog-query` skill in `claude-oncology-skills` is a thin
wrapper that subprocess-invokes this CLI.

## Capabilities

| subcommand | question |
|---|---|
| `search`   | which manifests match a keyword + facets (provider, data_subject, type, file category, license, system_of_record)? |
| `describe` | authoritative single view of one manifest: s3_uri, parquet_schema, sort key, license, derived_from, cited_by, consuming products |
| `lineage`  | walk `derived_from` (upstream) / `cited_by` (downstream, incl. subgroup-catalog citations) |
| `audit`    | coverage gaps, superseded/version-shadowed, orphan source-releases |

## Usage

```bash
python -m methods.catalog_query.cli search "CPTAC phospho" --data-subject tumor
python -m methods.catalog_query.cli describe biogrid-physical-interactions-per-gene-v1
python -m methods.catalog_query.cli lineage tcga-gdc-dr45-0 --direction downstream
python -m methods.catalog_query.cli audit --coverage-gaps
# machine-readable:
python -m methods.catalog_query.cli describe <id> --json
```

Point at a non-default checkout with `--catalog-root` / `--contracts-root`
(also how the tests stay hermetic).

## Library API (resolver-ready)

```python
from methods.catalog_query import load_catalog, s3_uri_for

idx = load_catalog()                 # cached CatalogIndex
idx.search(data_subject="tumor")     # list[ManifestRecord]
idx.describe("tcga-gdc-dr45-0")      # dict
idx.lineage("tcga-gdc-dr45-0", direction="downstream")

s3_uri_for("biogrid-physical-interactions-per-gene-v1")   # the resolver seam
```

`load_manifest` / `s3_uri_for` generalize `dge_deseq2/read.py`'s private
`_load_manifest`/`_s3_uri_to_path` to a public API over **both** `sources/` and
`derived/`. A follow-on can back a shared `manifest_id → s3_uri` resolver here,
retiring the ~57 hard-coded S3 keys currently scattered across `methods/`.

## Lineage source of truth

The reverse `cited_by` graph is computed the same way as the data-catalog's
`scripts/validate_catalog.py` (`compute_cited_by` + `compute_subgroup_catalog_citations`):
manifest→manifest `derived_from` edges folded together with
`subgroup-catalogs/**/*.yaml` `atomic_strata[].data_source.manifest_id` citations.
It does not trust the (auto-populated, potentially stale) `cited_by:` field on the
manifest itself.
