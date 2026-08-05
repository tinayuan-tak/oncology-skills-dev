"""catalog_query — read-only query engine over the data-catalog manifests.

Loads the source + derived manifest YAMLs (plus subgroup-catalogs and the
target-contracts products registry) into an in-memory CatalogIndex and answers
four kinds of question: search (which manifest covers a need?), describe
(everything about one manifest), lineage (derived_from / cited_by), and audit
(coverage gaps, stale/legacy, orphans).

Per the framework's layer-distinction discipline, reading + filtering catalog
YAML is *compute*, not *orchestration* — it belongs here in analysis-methods,
not in skills/. This method performs NO network/S3 access and NEVER writes.

RESOLVER-READY: load_manifest / s3_uri_for generalize dge_deseq2/read.py's
private _load_manifest/_s3_uri_to_path to a public API over BOTH sources/ and
derived/, so a follow-on can retire the ~57 hard-coded S3 keys across methods/.

Consumer: the catalog-query skill (claude-oncology-skills) via the cli.py
subprocess; also notebooks and other non-Claude consumers by library import.

Companion (read, never written):
    data-catalog:manifests/{sources,derived}/*.yaml
    target-contracts:vocabularies/products.yaml

Modules:
    read — CatalogIndex + load_catalog + manifest primitives
    cli  — argparse front end (search / describe / lineage / audit)
"""
METHOD_VERSION = "0.1.0"

from .read import (  # noqa: F401,E402
    CatalogIndex,
    ManifestRecord,
    bucket_key_for,
    load_catalog,
    load_manifest,
    s3_uri_for,
)
