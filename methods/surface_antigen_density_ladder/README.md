# surface_antigen_density_ladder

The **absolute surface-density calibration corpus** — the only evidence-grade **A/B** anchor in the
tiered surface-density model (`.claude/plans/surface-density-multi-anchor.md`;
`feedback_surface_density_evidence_model`). Only directly-calibrated flow cytometry
(QIFIKIT / QuantiBRITE / calibrated-bead / MESF / quantitative-IHC) can set the absolute
copies-per-cell scale; everything else (CSPA, CCLE/CPTAC whole-cell proteomics, HPA IHC) is a
surface-confirmation / relative-ranking / abundance **prior** (grades C/D), never an absolute anchor.

## Status: VESSEL (2026-07-23). Corpus is HEADER-ONLY by design.

This module ships the machinery but **no data values** — no copies-per-cell number is authored in
code. The committed `absolute_density_corpus.tsv` is header-only, so every target reads as grade
**E** (no absolute measurement) rather than a fabricated number. Populating the corpus is a
**governance step** (deferred): the user decides how values are supplied (team-curated /
web-sourced-then-approved). This separation is deliberate — the vessel is value-neutral and forces
the admissibility rules concrete before any value enters.

## What's here
- `absolute_density_corpus.tsv` — the committed reference table (header-only until populated).
- `read.py`
  - `read_absolute_density(target, indication=None)` — grade-resolved summary of the admissible
    measurements for a target (grade A patient-cell preferred over B model; empty/all-rejected → E).
  - `validate_row(row)` — the **admissibility gate**. A row is admissible ONLY with a positive numeric
    `value`, an admissible absolute `unit` (ABC / sites_per_cell / molecules_per_cell / MESF), an
    admissible `calibration_method`, an `evidence_grade` in {A, B}, and a DOI-shaped `source_doi`; if
    both bounds are present they must bracket the value. A relative unit (log2/ppm/NPX), an
    "estimated"/"inferred" method, or a grade C/D/E row is **rejected** — those belong to the prior
    tiers, not the anchor.
- `cli.py`
  - `read  --target ERBB2 [--indication BRCA]` — the summary as JSON.
  - `audit [--corpus PATH]` — validate every row; **nonzero exit if any row is rejected**. The
    populate-time governance check: a candidate table must audit clean before it's committed.

## Populate-time contract (for whoever governs the corpus later)
Each row is one measured `absolute_density_measurement`:
`target · uniprot_ac · cell_model · disease · specimen_type · value · lower_bound · upper_bound ·
unit · calibration_method · antibody_clone · valency · fluorophore · saturation_confirmed ·
viable_cell_gating · replicate_count · source_doi · evidence_grade · notes`.
Curate **several model systems per antigen** (not one canonical number). Every row MUST pass
`validate_row` (run `cli.py audit`). No fabricated values — a row is a real measured datum with a
DOI, or it is omitted.
