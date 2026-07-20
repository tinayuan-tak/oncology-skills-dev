# Ordinal evidence matrix — KRAS × COADREAD

> **ORDINAL VIEW — an order-preserving projection of categorical signals for display and ranking ONLY. NOT calibrated measurement (gaps between ranks are not metric); NOT a verdict input; insufficient/not_applicable are off-scale (coverage gaps, not low scores). The categorical signal is the source of truth.**

| gate (sub-skill) | small_molecule | degrader | adc | bite_tce | antibody | resolved verdict |
|---|---|---|---|---|---|---|
| expression | +0 | -3 | · | · | · | broadly_moderate_expression |
| selectivity | +0 | +0 | · | · | · | discordant_across_comparators |
| dependency | -1 | +0 | · | · | · | lineage_selective |
| synthetic_lethal_partners | +2 | +2 | · | · | · | has_experimental_sl_partner |
| mechanism | +2 | +2 | · | · | · | well_characterized |
| genomic_alteration | +0 | +0 | · | · | · | biomarker_stratified_dependency |
| differentiation | +2 | +2 | · | · | · | both_patterns_present |
| tractability_sm | +0 | +0 | · | · | · | well_covered |
| surface_modality | +0 | · | -3 | -3 | -3 | neither_viable |
| safety | -1 | -1 | · | · | · | highly_constrained_safety_concern |

**Scale (order-preserving, NOT metric):** supportive=+2, neutral=+0, opposing=-1, killer=-3. Off-scale (coverage, not a low score): insufficient, not_applicable (shown `insf`/`n/a`); `·` = the gate emits no signal on that modality.

**Why a cell can differ from the verdict:** a cell shows the *strongest raw signal* the gate's rules emit for that modality (a co-fired killer dominates a co-fired supportive). The *resolved verdict* is the gate's ordered-precedence outcome over all its fired rules. They legitimately differ — e.g. a paralog-buffering rule emits `small_molecule: opposing, degrader: supportive` (degrader-preferred), visible as a modality split in the row even when the verdict is a single positive. The verdict, not the cell, is the decision.
