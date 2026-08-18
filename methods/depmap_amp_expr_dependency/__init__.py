"""depmap_amp_expr_dependency — amplification→overexpression→dependency three-way (A1 oncogene-addiction).

The CONJOINT analog of the mutation/CN/fusion stratified-dependency primitive: is target T's DepMap
CRISPR dependency (Chronos) stronger in cell lines that are BOTH amplified (relative CN > 2.0) AND
high-expression (top-tertile log2TPM) for T? This is the amplification-DRIVEN oncogene-addiction
signature (ERBB2/MYC/MET-amp archetype) — the amp→overexpression→dependency chain the CN-only
stratified path (amplified-vs-neutral, expression-blind) cannot resolve, and the expression-dependency
FACET (expression-blind to CN) cannot establish either.

The stratifying boolean is a CONJUNCTION ("conditioned arm vs rest"):
  positive arm = amplified (CN > FOCAL_AMP_HIGH 2.0) AND high-expression (TPM in the top within-panel tertile)
  comparator   = every OTHER evaluated line (not-both) — the broad mirror of the CN/fusion comparators.
Because the stratifier collapses to a single {ModelID -> bool}, the SAME proven one-sided Mann-Whitney
(_mannwhitney_stratification, imported verbatim from depmap_mutation_dependency) applies — statistics
identical to the mutation/CN/fusion paths. It is NOT a mediation test (that was the richer-but-riskier
alternative); it is the conjoint-arm stratification, faithful to the CN/fusion idiom.

Emits amp_expr_stratification_class ∈ {amplified_overexpressed_strongly_dependent,
amplified_overexpressed_moderately_dependent, amp_expr_negative_more_dependent, not_amp_expr_stratified,
insufficient_amp_expr_rate, data_unavailable}. Verdict path (target-contracts): the
amplified_overexpressed_*_dependent classes fire amp-expr-*-dependent rules → genomic_alteration.resolver
REUSES the EXISTING biomarker_stratified_dependency verdict (no gate change; golden byte-identical, like
CN section-2b + fusion section-2c). Precedence: mut > cn > fusion > amp-expr (a Chronos-proven conjoint
signal is the most specific, placed last so any single-alteration driver names the verdict first).

Composes three live {ModelID -> value} loaders (Chronos + relative CN + log2TPM), all ModelID-joinable,
all already proven in depmap_cn_dependency / depmap_expression_distribution.
"""
from .read import read_amp_expr_dependency, METHOD_VERSION  # noqa: F401
