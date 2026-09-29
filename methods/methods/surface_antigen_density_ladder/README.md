# surface_antigen_density_ladder

The **absolute surface-density calibration corpus** — the only evidence-grade **A/B** anchor in the
tiered surface-density model (`.claude/plans/surface-density-multi-anchor.md`;
`feedback_surface_density_evidence_model`). Only directly-calibrated flow / single-molecule counting
sets the absolute copies-per-cell scale; CSPA, CCLE/CPTAC whole-cell proteomics, and HPA IHC are
surface-confirmation / relative-ranking / abundance **priors** (grades C/D), never absolute anchors.

## Status: POPULATED (schema v3, 2026-07-23). Governed dataset, 181 records.

**Source of truth is on S3** (data-catalog manifest `surface-antigen-absolute-density-curated-v1`,
`s3://onc-compbio/data-catalog/sources/surface-antigen-absolute-density-curated-v1/absolute_density_corpus.tsv`,
md5 `12ef885f1d24068c2e41eda2b11de901`). The reader pulls + caches it (definitive-vs-transient latch,
like the other derived readers) — **no in-repo copy**, single source, no dual-home drift. Tests use a
committed fixture slice (`tests/.../fixture_corpus_slice.tsv`) via `corpus_path` for determinism.

Every value is quoted from a primary table/supplement with a **resolvable DOI** (no bar-graph
digitization). Domain-expert curated. 171 admissible numeric anchors + 8 explicit-negative status
records + 2 fixed-cell method controls.

Sources (per-row DOI in the corpus): Tembhare 2013 CLL QuantiBRITE (CD20/CD22/CD25/CD52, 28 patients),
Nerreter 2019 dSTORM CD19 (primary myeloma), Jarantow 2015 monovalent-QuantiBRITE EGFR/MET (11 lines),
Sapski 2020 QIFIKIT EGFR/EPCAM, Geiger 2020 QIFIKIT FOLR1/MSLN (+ normal-cell bounds), Mentink 2023
CTC EpCAM (13 patients) + LNCaP fixation pair, Majzner engineered CD19 ladder.

## Schema v3 (superset) — see `read.py` `SCHEMA_V3_COLUMNS` (32 cols)

Design invariants the reader/validator enforce:
- **Partitions** (`record_partition`) gate use: `native_patient` / `native_cell_line` feed a tumor
  density anchor (the reader default); `normal_reference` / `calibration_reference` (engineered) /
  `method_control` (fixed) / `explicit_negative` do NOT.
- **Dual admissibility booleans** (`admissible_for_absolute_scale`, `admissible_for_native_biology`)
  travel per row and are enforced alongside the partition filter (belt & suspenders).
- **Qualifiers survive** (`value_qualifier`): bounds/approximations/patient-medians are never coerced
  to exact counts; a `patient_median` is ranked on its median, never its (heavy-tailed) SD.
- **Semantics distinguished** (`measurement_semantics` + `reported_unit`): ABC ≠ molecule count;
  monovalent-epitope ≈ epitopes; dSTORM = direct molecule count; PE-equivalent is a proxy. Never
  silently averaged.
- **Grade sub-tiers** (`evidence_grade`): A / A- (patient) · B / B- (cell-line) · A-N (normal ref) ·
  CAL (engineered) · QC (method control). Only A/A-/B/B- feed a native anchor.

## API
- `read_absolute_density(target, indication=None, partitions=("native_patient","native_cell_line"))`
  → grade-resolved summary (best = patient-direct > patient-proxy > cell-line-direct > cell-line-
  rounded; empty/held → grade E). Pass `partitions` for the normal-reference or calibration read.
- `read_explicit_negatives(target)` → the antigen-negative status records (never numeric zeros).
- `validate_row(row)` → admissibility gate (positive value/bound, admissible vocab, DOI-shaped source,
  abs-scale boolean); rejects malformed rows AND (correctly) explicit_negative/method_control as
  non-anchors.
- CLI: `read --target ERBB2` · `audit` (distinguishes expected-held negatives/controls from genuine
  malformations; nonzero exit only on a real malformation).

## What the corpus shows (why a single "high" is wrong)
EGFR spans ~5,000 → 823,000 across native lines; CD19 on myeloma runs 64 → 1,600 molecules/cell yet is
CAR-T-active. Absolute density is target-, model-, and format-dependent — the corpus preserves that
spread instead of collapsing it.

## Governance
No value is authored in code; the S3 object (data-catalog `surface-antigen-absolute-density-curated-v1`)
is the governed artifact. To extend: add rows that pass `validate_row` (run `cli.py audit`), each a real
measured datum with a DOI — or omit it; re-upload to S3 + bump the manifest md5.
