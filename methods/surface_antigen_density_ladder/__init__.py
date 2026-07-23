"""surface_antigen_density_ladder — the ABSOLUTE surface-density calibration corpus (Phase 2).

The tiered-evidence model (feedback_surface_density_evidence_model; plan
.claude/plans/surface-density-multi-anchor.md) establishes that surface antigen DENSITY is a
tiered problem, and that ONLY directly-calibrated flow cytometry (QIFIKIT / QuantiBRITE / ABC /
MESF / sites-per-cell) can set the absolute copies-per-cell scale — evidence grades A (patient
cells) / B (cell-line/model). Everything else (CSPA, CCLE/CPTAC whole-cell proteomics, HPA IHC) is
a surface-confirmation, relative-ranking, or abundance PRIOR (grades C/D), never an absolute anchor.

This module is that absolute anchor: a MANUALLY GOVERNED corpus of measured copies-per-cell values,
one row per (target, cell_model|specimen, measurement) with full provenance + a per-row DOI.

⚠ SCOPE (2026-07-23): this commit is the VESSEL, not the contents. It ships:
  - the `absolute_density_measurement` row schema + admissibility validator (rejects fabrication-prone
    rows: no value, no unit, no calibration_method, no source DOI, no evidence_grade → REJECTED);
  - the reader (`read_absolute_density`) over a committed reference TSV;
  - a HEADER-ONLY reference table (zero data rows).
Populating the table is a GOVERNANCE step deferred to Phase-2-populate time (the user decides how
values are supplied — team-curated / web-sourced-then-approved / admissibility-spec-only). No value is
authored here — an empty corpus reads as grade-E (no absolute measurement), never a fabricated number.
"""
METHOD_VERSION = "0.1.0"

from .read import read_absolute_density  # noqa: F401,E402
from .read import validate_row  # noqa: F401,E402
