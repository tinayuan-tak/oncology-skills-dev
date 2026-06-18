# target-id-resolver

Release-pinned identifier resolver for human gene/protein targets. Backbone of
the v2 oncology target evaluation skill framework.

**One canonical Target object** — HGNC primary symbol + HGNC ID + Ensembl gene
ID (versioned) + UniProt canonical accession + NCBI Entrez ID — produced once
per query at orchestrator entry, propagated unchanged through every downstream
analysis dimension.

**Release-pinned** — every Target object cites the exact data-catalog manifest
IDs of the upstream sources consulted (e.g., `hgnc-2026-q2`, `mygene-info-metadata-20260602`).
Same input + same `resolver_release` → byte-identical Target object (modulo
`resolved_at` timestamp).

**Deterministic, audit-friendly, NOT LLM-mediated.** Identifier resolution is
exactly the kind of audit-critical operation where LLMs degrade trust. This
library is plain Python: pinned snapshots, dictionary lookups, structured
outputs. The trustworthy foundation that lets LLM synthesis happen safely
higher up the stack.

## Status

`v0.1.0a1` — alpha. **Not for production dossier emission.** Outputs from this
release pin omit Ensembl gene_id versioning and UniProt canonical accession
(those will land with full UniProt + Ensembl mirroring in `v1.0.0`). The
walking-skeleton pin (`resolver_v0.1.0-alpha`) uses HGNC + MyGene.info
metadata only, sufficient to prove the round-trip on real targets.

## Quick start

```python
from target_id_resolver import resolve

target = resolve("KRAS", resolver_release="resolver_v0.1.0-alpha")
print(target.hgnc.id)              # HGNC:6407
print(target.hgnc.primary_symbol)  # KRAS
print(target.ensembl.gene_id)      # ENSG00000133703
print(target.input.value)          # KRAS
```

CLI:

```bash
resolve-target-id --input KRAS --release resolver_v0.1.0-alpha
```

## What the resolver guarantees

- **Symbol → primary symbol forward mapping**: input `BAF250A` resolves to
  `ARID1A` with a `deprecation_warning` field set; never silently wrong.
- **Cross-reference completeness**: every Target carries the HGNC, Ensembl,
  UniProt (where available), and NCBI Entrez identifiers, populated from a
  single resolver pass.
- **Aliases captured at resolution time**: downstream literature queries can
  expand to alias sets reproducibly without re-querying HGNC.
- **Fail-closed on ambiguity**: re-purposed symbols (e.g., HGNC's `MARC1`)
  raise a structured error rather than silently picking one resolution.
- **Determinism for a fixed pin**: every field except `resolved_at` is
  byte-identical for the same input + resolver_release across runs.

## Roadmap

- `v0.1.0-alpha` (this slice) — HGNC + MyGene metadata; live-API based.
- `v1.0.0` — pinned local snapshots (HGNC + UniProt + Ensembl + NCBI Gene),
  zero runtime API calls during normal operation.
- `v1.1.x` — sidecar emission for batch artifacts (DGE Parquets, GMT files).
- `v2.0` — isoform-aware resolution (UniProt isoform accessions).

See `~/.claude/plans/you-are-a-skilled-drifting-pixel.md` for the full design.
