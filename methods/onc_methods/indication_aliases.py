"""Canonical patient-cohort indication aliasing (indication-vocabulary fragmentation guard).

The patient-cohort SNV-frequency products (TCGA-MC3, GENIE, the pooled recurrence table) are
materialised at the framework CANONICAL grain (target-contracts `indication_crosswalk.yaml`
`canonical_code`): lung is pooled as **NSCLC** (TCGA-LUAD + TCGA-LUSC), so the products' `indication`
column value — and their local-cache filename — is `NSCLC`, never `LUAD`/`LUSC`.

But the DepMap-side readers accept the finer OncoTree codes (`LUAD`, `LUSC`) directly (they key on
`depmap_oncotree_codes`), so a skill invoked with `indication="LUAD"` reaches these cohort readers with
a code that has NO product partition → the pushdown filter matches 0 rows and the card emits a spurious
`data_unavailable` (e.g. EGFR/LUAD looked un-mutated, when EGFR is ~8% in NSCLC-MC3 with L858R/ex19del).

Fix: normalise the finer OncoTree sub-code UP to the patient-cohort canonical here, at the cohort-read
entry, BEFORE path resolution and the pushdown filter. Mirrors the PAAD/PDAC dual-key fix. Keyed by the
crosswalk sub-codes that roll up to a coarser `canonical_code`; identity for codes that are already
canonical or have their own partition.
"""

from __future__ import annotations

# OncoTree sub-code -> framework patient-cohort canonical_code (indication_crosswalk.yaml).
# Only sub-codes whose patient-cohort product is materialised at a COARSER canonical grain belong here.
_TO_COHORT_CANONICAL = {
    "LUAD": "NSCLC",  # TCGA-LUAD ∈ NSCLC (pooled with LUSC)
    "LUSC": "NSCLC",  # TCGA-LUSC ∈ NSCLC
}


def to_cohort_canonical(indication: str) -> str:
    """Map a finer OncoTree indication code to the canonical code its patient-cohort SNV product is
    keyed on. Identity for already-canonical codes (and any code with its own partition)."""
    if not indication:
        return indication
    return _TO_COHORT_CANONICAL.get(indication, indication)


# Umbrella canonical code -> its member OncoTree LEAF codes. The DOWN-expansion counterpart to
# to_cohort_canonical's UP-pooling: some products are keyed by the finer LEAF cohort and have NO pooled
# umbrella partition. CPTAC ships lung as two separate cohorts (LUAD + LSCC) with no NSCLC row, so an
# indication="NSCLC" query must expand to BOTH leaves and pool / pick across them, else it spuriously
# reads data_unavailable (the tumor-elevation-breadth card, which enumerates all cohorts target-grain,
# DID see LUAD+LSCC while the per-sample CPTAC readers returned "no cohort"). Keyed by the crosswalk
# umbrella canonical_code; identity for codes that already have their own leaf partition.
_UMBRELLA_TO_LEAVES = {
    "NSCLC": ("LUAD", "LUSC"),  # CPTAC: LUAD + LSCC (LUSC≡LSCC); no pooled NSCLC cohort
}


def indication_leaf_codes(indication: str) -> tuple[str, ...]:
    """Expand an umbrella indication to its member OncoTree LEAF codes for LEAF-keyed products; identity
    (single-element tuple) for a code that is already a leaf / has its own partition. Empty for falsy
    input. Callers pass each returned code through their OWN indication→cohort map (preserving casing)."""
    if not indication:
        return ()
    ind = indication.upper().strip()
    return _UMBRELLA_TO_LEAVES.get(ind, (ind,))
