"""genomic_event_model_match — the canonical P3 patient↔model join on GENOMIC EVENT (M11).

For a (target, indication): which DepMap cell-line models carry the SAME functional genomic event
in the target as the indication's tumors — and of those genotype-matched models, which are the
positive / resistance / negative screen lines by Chronos dependency? The genomic sibling of the
expression-Q4 join (patient_model_expression_correspondence / recommended-models), which matched
models by TARGET EXPRESSION similarity. Same P3 question, orthogonal axis:

    expression-Q4 : match models to tumors by TARGET-EXPRESSION distribution similarity
    M11 (this)    : match models to tumors by FUNCTIONAL GENE STATE (M6 two-hit genotype)

Why the genomic axis matters over expression alone: a cell line can be EXPRESSION-matched yet
GENOTYPE-mismatched — highly expressing the target but WILD-TYPE where the tumor is BIALLELICALLY
INACTIVATED. For a loss-of-function-driven dependency that line is a POOR model, even though the
expression join ranks it well. M11 catches the genotype mismatch the expression join cannot.

Reuses (no new substrate, no new ingestion):
  - functional_gene_state (M6): PATIENT arm → the tumor cohort's dominant functional state
    (the event to match); MODEL arm per-model accessor read_model_states_per_model → each cell
    line's functional state (the candidate genotypes).
  - depmap_expression_dependency.load_depmap_files_for_card4: {ModelID → Chronos} + lineage
    metadata (the screen-role + lineage-match inputs, exactly as expression-Q4 uses them).

Output: a ranked table of genotype-matched models (event_match + screen_role + lineage_match) +
an event_correspondence_class rollup {event_matched_dependent_in_lineage / _off_lineage /
event_matched_not_dependent / no_event_match / data_unavailable}. data_unavailable-safe.

Modules:
    read — read_genomic_event_model_match(target, indication): the P3 join + rollup.
"""
from __future__ import annotations

from .read import read_genomic_event_model_match

METHOD_VERSION = "0.1.0"

__all__ = ["read_genomic_event_model_match", "METHOD_VERSION"]
