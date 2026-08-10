"""cross_consortium_dependency — Broad vs Sanger CRISPR-dependency concordance (Project Score corroboration).

Verdict-INERT gate-C corroboration: does the INDEPENDENT Sanger Project Score consortium agree with
Broad Achilles that the target is a dependency? Two independent libraries+pipelines agreeing is stronger
than the existing CRISPR×RNAi (both Broad). Both matrices already in the DepMap 26q1 mirror
(CRISPRGeneEffect=Broad, ScreenGeneEffect=Sanger-inclusive). Emits cross_consortium_class ∈
{concordant_dependent, concordant_non_dependent, discordant, single_consortium_only, data_unavailable}.
Raises C-confidence, never a killer.
"""
from .read import read_cross_consortium_dependency, METHOD_VERSION  # noqa: F401
