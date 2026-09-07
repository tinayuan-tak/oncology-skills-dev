"""depmap_cn_dependency — copy-number-stratified dependency (A1a).

The copy-number analog of depmap_mutation_dependency: does a target's DepMap CRISPR
dependency (Chronos) STRATIFY by copy-number amplification status — are AMPLIFIED cell
lines more dependent than non-amplified? A clean amplified-vs-neutral split (amplified
lines dependent, neutral not) is a dependency-ESTABLISHING signal for amplification-driven
oncogenes (ERBB2/MET/MYC) — the class the mutation-only stratified-dependency path misses.

Composes two existing loaders + the PROVEN Mann-Whitney contrast (imported verbatim from
depmap_mutation_dependency), so the statistical treatment is identical to the mutation path:
  - Chronos via depmap_chronos_distribution.load_depmap_files ({ModelID -> chronos})
  - relative CN via depmap_cn_distribution.load_cn_files ({ModelID -> relative_cn})
  - amplified boolean = relative_cn > FOCAL_AMP_HIGH (2.0, the focal high-level amp cut the dependency arm uses)
  - neutral (comparator) = NOT amplified (broad; the faithful mirror of the mutation path's
    "everything not mutant" WT group).

Emits cn_stratification_class ∈ {amplified_strongly_dependent, amplified_moderately_dependent,
neutral_strongly_dependent, not_cn_stratified, insufficient_amplification_rate, data_unavailable}.
Verdict path (target-contracts): the amplified_*_dependent classes fire cn-amplified-*-dependent
rules → genomic_alteration.resolver reuses the EXISTING biomarker_stratified_dependency verdict.
"""

from .read import read_cn_stratified_dependency, METHOD_VERSION  # noqa: F401
