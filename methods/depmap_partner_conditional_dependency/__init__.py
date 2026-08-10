"""depmap_partner_conditional_dependency — partner-conditional stratified dependency (Track PC).

The PARTNER-feature generalization of depmap_cn_dependency (A1a, own-CN) and
depmap_mutation_dependency (own-mutation): does a target's DepMap CRISPR dependency (Chronos)
STRATIFY by a PARTNER gene's DEFICIENCY status? A clean partner-deficient-vs-neutral split
(partner-deficient lines dependent, neutral not) is a dependency-ESTABLISHING signal for the
partner_conditional_sl family — WRN×MSI, PARP1×HRD, SMARCA2×SMARCA4 — that the pooled pan-cancer
dependency scalar structurally misses (definitionally non-monoculture-essential → false non_dependent).

Composes: Chronos loader (depmap_chronos_distribution) + a PARTNER-DEFICIENCY boolean loader
(dispatched on the curated partner_map.yaml deficiency_type: MSI-signature or LoF-mutation) + the
PROVEN _mannwhitney_stratification (imported verbatim from depmap_mutation_dependency). Statistics
identical to the CN/mutation paths.

ANCHOR (validation gate #1, live DepMap 26q1, canonical MSI boolean): WRN×MSI-high →
delta Chronos -0.41, p 8.8e-12, 91 MSI-high lines → partner_conditional_moderately_dependent.

Emits partner_stratification_class ∈ {partner_conditional_strongly_dependent,
partner_conditional_moderately_dependent, partner_neutral_strongly_dependent,
not_partner_stratified, insufficient_partner_deficient_rate, no_partner_mapped, data_unavailable}.

Verdict path (target-contracts): the partner_conditional_*_dependent classes fire
partner-conditional-*-dependent rules → dependency.resolver reuses the biomarker_stratified_dependency
rescue (one-directional; rescues a pooled non_dependent veto, never vetoes). The rescue rung fires at
MODERATE (delta <= -0.2), NOT STRONG — WRN×MSI (a celebrated real SL) is a -0.41 effect; context-
conditional SL effect sizes are structurally smaller than oncogene addiction, so a STRONG-only rung
would rescue nothing real (empirically established 2026-08-09).
"""
from .read import read_partner_conditional_dependency, METHOD_VERSION  # noqa: F401
