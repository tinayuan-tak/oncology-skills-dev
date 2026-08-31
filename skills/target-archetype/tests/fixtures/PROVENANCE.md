# Coherence-QC label fixtures — provenance & refresh

These CSVs are **frozen snapshots** of external biological labels for the atlas targets, used by
`scripts/coherence_qc.py` as the **test fixtures AND the default `--labels`**. They are point-in-time
snapshots — for a production/coherence run against current data, pass a freshly-derived `--labels` CSV
(same columns) rather than relying on these. Regenerate when the atlas corpus or the source product changes.

| fixture | columns | source product / snapshot | positive class | built |
|---|---|---|---|---|
| `oncokb_roles.csv` | target, role | OncoKB gene-roles public snapshot `oncokb-gene-roles-public-snapshot-2026-07-01` (`geneType`) | role=oncogene vs tsg | 2026-08-31 |
| `cspa_surface.csv` | target, surface | `cspa-surface-confirmation-per-uniprot-v1` (S3, cbg) — `surface_confirmation_class` ∈ {confirmed_high, confirmed}; uniprot_ac→HGNC via its target_resolution sidecar | surface=yes | 2026-08-31 |
| `depmap_predictability.csv` | target, predictability_class, r2_rf, dominant_feature_class | `depmap-predictability-26q1-v3` (S3, cbg) — per-gene `predictability_class` | explainable = non-`unpredictable` | 2026-08-31 |

## Regenerate (needs `AWS_PROFILE=cbg` for the S3 products)
- **oncokb_roles**: map each atlas target → OncoKB `geneType` (ONCOGENE→oncogene, TSG→tsg) from the snapshot.
- **cspa_surface**: read the CSPA parquet + resolution sidecar, join `uniprot_ac`→`hgnc_primary_symbol_at_resolution`, mark confirmed_high/confirmed as `yes`.
- **depmap_predictability**: read `predictability_per_gene.parquet`, key by `gene_symbol`.
Restrict rows to the current `atlas/atlas.json` targets. (Build scripts were run ad-hoc; the joins are documented above and in each fixture's header comment is intentionally omitted to keep them CSV-clean.)
