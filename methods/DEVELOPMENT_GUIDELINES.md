# methods/ — development guidelines

> Process (branching, worktrees, landing) lives in root [CLAUDE.md](../CLAUDE.md).
> This document is the domain reference for what belongs in a method module.

## What belongs here

**Deterministic analytical code.** A method:
- Has a single CLI entrypoint (`method-name --arg value ...`).
- Takes catalog manifest IDs and parameters as inputs.
- Emits a structured output bundle (`summary.json`, `figure.svg`, `plot_data.parquet`, `manifest.yaml`) whose `summary` validates against the card's per-card summary schema in `contracts/schemas/methods/<card_id>.summary.schema.json` (when one exists — see the opt-in discipline below).
- Has unit tests in `methods/<method>/tests/`.
- Is **idempotent** — same inputs + same release_pin → byte-identical deterministic-field output.

## What does NOT belong here

- **Skill orchestration** — that's `skills/`. Methods don't know about cards, dashboards, or evidence packages.
- **Data** — Parquet/CSV/raw data lives in S3, registered via `data-catalog/manifests/`. Methods read from catalog refs, never local data files.
- **Schemas** — JSON Schemas + controlled vocabularies live in `contracts/`. Methods consume schemas; they don't author them.
- **Narrative or interpretation** — methods emit numbers, not calls. Interpretation (`"strong upregulation"` etc.) is the card layer's responsibility.

## CLI authoring contract

Every method CLI must:
1. Accept `--release-pin <manifest_id>` (gates resolution against the catalog).
2. Accept `--out <dir>` (where outputs land in staging).
3. Emit outputs whose `summary` validates against the card's schema in `contracts/schemas/methods/<card_id>.summary.schema.json` (opt-in — see the discipline section below).
4. Exit 0 on success, non-zero on failure with structured stderr.
5. Run deterministically — same inputs reproduce byte-identical outputs (caveat: timestamps and machine identity in the `manifest.yaml` are excluded from byte-identity).

## Method skeleton

A new method `methods/foo/` minimally contains:
- `cli.py` (Click-based CLI entrypoint, runnable as `foo`)
- `__init__.py` (importable library surface)
- `tests/test_foo.py` (unit tests; pytest)

When implemented in R (like `dge_deseq2`):
- `cli.py` wraps `Rscript` invocations to numbered step scripts (`steps/00_*.R`, `01_*.R`, …)
- Argument parsing happens in Python; R receives concrete parameter values via command-line args

## Per-card summary-output schema discipline

The schema in `contracts/schemas/methods/<card_id>.summary.schema.json` is the contract between the method-author and the skill-author for the `summary` dict a card emits. (Granularity is **per-card**, not per-method: one method can back several cards with different summary shapes, so the schema is keyed by `card_id`.) A change to a card's summary shape requires a coordinated schema bump + a skill-side PR — this is a single atomic PR across `methods/` + `contracts/` + `skills/` in the consolidated repo (see root CLAUDE.md). **Drift fails validation; it doesn't silently produce a bad evidence package.**

Rollout is **opt-in**: a card's summary is validated only when its `<card_id>.summary.schema.json` exists (generate one with `contracts/validators/gen_summary_schemas.py`), so cards without a schema are unaffected until one is committed.

## Carve-out provenance

Methods carved from `skills/` (pre-consolidation, when this was the separate `claude-oncology-skills` repo):
- `dge_deseq2/` ← `batch/expression_rna_COADREAD/` (parameterized indication)
- `target_id_resolver/` ← `libs/target_id_resolver/` (mechanical)
- `io/loaders/` ← `batch/loaders/` (mechanical)

The byte-identity gate for the dge_deseq2 carve-out (R4 in A1's refactor sequencing) is `tests/integration/test_dge_deseq2_byte_identity_with_legacy_coadread.py` (TBD; requires actual env to execute).
