"""pancanatlas_ddr_context — per-indication DDR/HRD-deficiency cohort context.

A verdict-INERT, pre-integrated companion facet from the PanCanAtlas DDR footprint resource
(Knijnenburg 2018 Cell Rep), which already did the per-sample multi-omics HRD integration
(HRD_Score = HRD-TAI + HRD-LST + HRD-LOH; mutSig3; PARPi7). We aggregate to a per-INDICATION rollup
at build time (read grain pre-aggregated → O(1) skill reads). The resource's "disease" column IS the
TCGA tumor-type code, so per-indication aggregation needs no barcode join.

Emits ddr_context_class ∈ {hrd_enriched, hrd_intermediate, hrd_low, data_unavailable} from the
fraction of cohort samples that are HRD-high (HRD_Score >= 42, the Myriad-style clinical cut).
Per-indication prevalences match the published TCGA HRD landscape (e.g. OV enriched, genomically
stable types near zero).

VERDICT-INERT context facet: no resolver rung. Surfaces the cohort HRD prior alongside the separate,
verdict-moving partner-conditional dependency analysis; it does NOT itself move a verdict.
"""

from .read import read_ddr_deficiency_context, METHOD_VERSION  # noqa: F401
