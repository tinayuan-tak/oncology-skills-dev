# Methods repo — development guidelines

## What belongs here

**Deterministic analytical code.** A method:
- Has a single CLI entrypoint (`method-name --arg value ...`).
- Takes catalog manifest IDs and parameters as inputs.
- Emits a structured output bundle (`summary.json`, `figure.svg`, `plot_data.parquet`, `manifest.yaml`) that validates against the method's per-method output schema in `target-contracts/schemas/methods/`.
- Has unit tests in `methods/<method>/tests/`.
- Is **idempotent** — same inputs + same release_pin → byte-identical deterministic-field output.

## What does NOT belong here

- **Skill orchestration** — that's `claude-oncology-skills/`. Methods don't know about cards, dashboards, or evidence packages.
- **Data** — Parquet/CSV/raw data lives in S3, registered via `data-catalog/manifests/`. Methods read from catalog refs, never local data files.
- **Schemas** — JSON Schemas + controlled vocabularies live in `target-contracts/`. Methods consume schemas; they don't author them.
- **Narrative or interpretation** — methods emit numbers, not calls. Interpretation (`"strong upregulation"` etc.) is the card layer's responsibility.

## CLI authoring contract

Every method CLI must:
1. Accept `--release-pin <manifest_id>` (gates resolution against the catalog).
2. Accept `--out <dir>` (where outputs land in staging).
3. Emit outputs validating against the method's schema in `target-contracts/schemas/methods/`.
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

## Per-method output schema discipline

The schema in `target-contracts/schemas/methods/<method>.output.schema.json` is the contract between the method-author and the skill-author (compose-dashboard). A change to a method's output shape requires a coordinated schema bump + a compose-dashboard PR. **Drift fails compose-time validation; it doesn't silently produce a bad evidence package.**

## Carve-out provenance

Methods carved from `claude-oncology-skills/`:
- `dge_deseq2/` ← `batch/expression_rna_COADREAD/` (parameterized indication)
- `target_id_resolver/` ← `libs/target_id_resolver/` (mechanical)
- `io/loaders/` ← `batch/loaders/` (mechanical)

The byte-identity gate for the dge_deseq2 carve-out (R4 in A1's refactor sequencing) is `tests/integration/test_dge_deseq2_byte_identity_with_legacy_coadread.py` (TBD; requires actual env to execute).
