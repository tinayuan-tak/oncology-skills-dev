"""tcga_aneuploidy_burden — per-indication genome-instability / aneuploidy-burden summary.

The genome-state summary (aneuploidy / CIN burden), from PanCanAtlas seg-based scores. This is an
INDICATION-level property (how chromosomally unstable is this cancer's cohort?), NOT a per-gene call —
aneuploidy is a genome-wide phenotype. A target maps in only as context: "is this target in a
highly-aneuploid indication?" (high CIN correlates with WGD, poorer prognosis, and modality caveats).

Source: gdc-pancanatlas-cnv-2018 seg_based_scores.tsv (Sample / n_segs / frac_altered / n_extrema) —
per-sample fraction-of-genome-altered (the aneuploidy burden). Barcode→indication via the SAME
merged_sample_quality_annotations join functional_gene_state uses.

NOTE (scope): this file is per-SAMPLE genome-wide instability, NOT a per-arm gain/loss table. A
per-arm arm-loss + per-lineage-selectivity-percentile card (feedback_aneuploidy_baseline_control) needs
the Taylor-2018 arm-level calls, which are NOT yet ingested — a separate follow-up. This ships
the data-in-hand burden metric.

WGD/ploidy (0.2.0): a second genome-state axis — whole-genome-doubling prevalence + median ploidy
from the ABSOLUTE abs_tables (sibling of seg_based_scores in the same source), via
wgd_summary_for_indication(). Same cohort grain, same barcode→cancer-type join.

HRD: the genomic-scar homologous-recombination-deficiency score — HRD-LOH + LST + ntAI
(Abkevich/Popova/Birkbak; Myriad myChoice sums the same three), computed per sample from the
ABSOLUTE allele-specific segtabs (sibling of abs_tables), rolled up to per-indication HRD-high
prevalence via hrd_score_for_indication(). NOTE: this ABSOLUTE-segtabs scar score is IMPLEMENTED
BUT NOT WIRED into any card (no card reads hrd_score_for_indication) — it is deferred. The card
currently surfaces only the SBS3 signature proxy. See hrd.py for the scar-scoring algorithm.
Same cohort grain, same barcode join.

METHOD_VERSION 0.3.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.3.0"

from .read import (  # noqa: E402,F401
    aneuploidy_burden_for_indication,
    wgd_summary_for_indication,
    msi_summary_for_indication,
    model_msi_summary_for_indication,
    model_signature_summary_for_indication,
    hrd_score_for_indication,
    prewarm,
)
