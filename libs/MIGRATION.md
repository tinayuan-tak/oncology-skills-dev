# Migration notice

The following directories were removed from this repo on 2026-06-29 (PR following the v2-architecture
target_id_resolver migration):

- `libs/target_id_resolver/` — moved to the data-catalog repo at `libs/target_id_resolver/`
- `resolver-releases/` — moved to the data-catalog repo at `resolver-releases/`

Canonical location:

  https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog
    → `libs/target_id_resolver/`
    → `resolver-releases/`

Rationale: the resolver library and its release pins are part of the data-catalog's identifier-
resolution backbone — they emit `*.target_resolution.parquet` sidecars alongside source manifests
(see `manifests/sources/{msigdb-human-v2026-1-hs,reactome-v96,gene-ontology-release-2026-05-19,
gdc-pancanatlas-cnv-2018}.yaml`). Keeping them next to the manifests they describe avoids
cross-repo coupling and lets a single PR ship both the data and its resolver pin.

`core-artifacts-schema/` remains in this repo: it is consumed at runtime by
`skills/query-target-evidence/scripts/query_evidence.py` and
`batch/expression_rna_COADREAD/scripts/write_evidence.py` and is therefore not a migration
candidate.

The `target.schema.json` reference to "`libs/target_id_resolver`" (line 81) now points at the
data-catalog copy. No code change required since that field is documentation, not an import.
