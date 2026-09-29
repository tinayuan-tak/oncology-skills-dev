"""onsides_adverse_event — per-target OnSIDES adverse-drug-event CONTEXT (verdict-INERT).

Reads the per-gene rollup onsides-adverse-event-per-gene-v1 (gene-symbol keyed) and emits an
onsides_ade summary {onsides_ade_class, n_drugs_mapped, n_meddra_terms, has_boxed_warning,
n_boxed_warning_terms, example_terms, ...}. A pharmacovigilance CONTEXT layer for
on-target-safety-liability — a DISPLAY signal, NOT a verdict input:

  * the gene attribution rests on a FUZZY drug-name->gene join (~63% match-rate) that is drug-level
    and class-wide (recall-union over every gene a drug engages) — cannot separate on- from
    off-target;
  * grain is per-MedDRA-TERM only (per-organ / SOC rollup needs the licensed MedDRA hierarchy).

Absence = coverage gap (no_mapped_drug_ade), never evidence of safety (measured-vs-null discipline).

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
