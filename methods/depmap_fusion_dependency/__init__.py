"""depmap_fusion_dependency — fusion-stratified dependency (A1-fusion).

The FUSION analog of depmap_mutation_dependency + depmap_cn_dependency: does a target's DepMap
CRISPR dependency (Chronos) STRATIFY by fusion-involvement — are cell lines carrying a fusion
INVOLVING the target more dependent than fusion-negative lines? A clean fusion-positive-vs-negative
split is a dependency-ESTABLISHING signal for fusion-driven oncogenes (ABL1/BCR-ABL, ALK/EML4-ALK,
FLI1/EWSR1-FLI1) — the class the mutation + CN stratified paths miss.

Composes existing Chronos loading + the PROVEN Mann-Whitney contrast (imported verbatim from
depmap_mutation_dependency), so the statistics are identical to the mutation/CN paths:
  - Chronos via depmap_chronos_distribution.load_depmap_files ({ModelID -> chronos})
  - fusion-involvement bool from DepMap 26Q1 OmicsFusionFiltered.csv (ModelID-native; the target
    symbol appearing as EITHER the 5' (LeftGene) OR 3' (RightGene) partner in any high/medium-
    confidence call — the gene-collapsed symbol-union boolean).
  - fusion-negative (comparator) = every other screened line.

Emits fusion_stratification_class ∈ {fusion_positive_strongly_dependent,
fusion_positive_moderately_dependent, fusion_negative_strongly_dependent, not_fusion_stratified,
insufficient_fusion_rate, data_unavailable}. Verdict path (target-contracts): the
fusion_positive_*_dependent classes fire fusion-positive-*-dependent rules → genomic_alteration.resolver
REUSES the EXISTING biomarker_stratified_dependency verdict (no gate change).

v1 SCOPE (honest): "any fusion involving the target, either partner". Does NOT require the target be
the kinase-retaining / in-frame / dependency-conferring partner — 5'/3' orientation + reading-frame
resolution (OmicsFusionFilteredSupplementary.csv) is a v2 upgrade. Failure mode is CONSERVATIVE: a
bystander-partner fusion only dilutes toward the null (never a false positive) under the one-sided test.
"""

from .read import METHOD_VERSION, read_fusion_stratified_dependency  # noqa: F401
