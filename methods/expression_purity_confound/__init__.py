"""expression_purity_confound — is the target's tumor expression signal purity-confounded? (expr Q9)

For a (target, indication): correlate the target's per-sample tumor expression against per-sample
TUMOR PURITY (ABSOLUTE). Answers the yardstick's Q9 "purity/processing confound flag":

  - POSITIVE purity↔expression correlation → expression RISES with tumor-cell content → the signal
    is TUMOR-CELL-INTRINSIC (reassuring: the cancer cells express the target).
  - NEGATIVE correlation → expression is HIGHER in LOW-purity tumors → the signal is likely
    STROMAL / IMMUNE-derived (a CONFOUND: the "tumor expression" is really microenvironment).
  - ~zero → purity-independent (no confound signal either way).

Why it matters: bulk tumor RNA can't tell tumor-cell from microenvironment expression; a target that
looks "tumor-expressed" but is really stroma/immune-derived is a false presence signal — and for
ADC/TCE it gates antigen REALITY (is the antigen on the cancer cell or the microenvironment?).

ZERO new ingestion — reuses:
  - tcga_gtex_expression_distribution.read_tumor_samples_with_case → per-sample [case, log2_tpm].
  - PanCanAtlas ABSOLUTE abs_tables (M6 substrate) → per-sample tumor purity, joined on case barcode.

ROUTES (master-sequencing Part 3): Presence (A) — a purity-confound caveat on the tumor presence
call; ALSO (P4, deferred) the ADC/TCE surface-modality gate — "is the antigen tumor-intrinsic?".
This slice wires the biology-axis PRESENCE facet only; the modality-gate facet is deferred to P4.

Modules:
    read — read_expression_purity_confound(target, indication): the purity↔expression correlation + class.
"""
from __future__ import annotations

from .read import read_expression_purity_confound, classify_purity_confound

METHOD_VERSION = "0.1.0"

__all__ = ["read_expression_purity_confound", "classify_purity_confound", "METHOD_VERSION"]
