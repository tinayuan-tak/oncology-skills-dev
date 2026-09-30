"""depmap_cis_dosage — cis-feature → own-expression coupling (cis-coherence Stage 0).

The MISSING leg of the locus → expression → dependency coherence chain. Does target T's own relative
copy-number PREDICT its own expression across the DepMap panel (cis-dosage coupling)? A strong POSITIVE
CN↔log2TPM correlation is the amplification-DRIVEN overexpression signature (ERBB2/MYC/KRAS-amp); a
CN-varies-but-expression-flat panel is the informative NEGATIVE (expression is copy-number-INDEPENDENT,
i.e. trans/lineage-regulated).

DISTINCT from the two adjacent cards it must NOT duplicate:
  - amp-expr-stratified-dependency conjoins amplified∩overexpressed and tests the DEPENDENCY of that
    subset — it PRESUMES the CN→expression step, never measures it.
  - expression-dependency-correlation tests expression→dependency, and is CN-BLIND.
This module measures the CN→expression step directly, so the cis_coherence resolver can distinguish an
amplification-driven cis-driver from a co-occurring passenger amplicon.

Composes two live {ModelID -> value} loaders (relative CN + log2TPM), both ModelID-joinable, both proven
in depmap_cn_distribution / depmap_expression_distribution. Chronos is NOT read here — dependency is
leg-2, owned by the reused expression-dependency-correlation + amp-expr cards.

Emits cis_dosage_class ∈ {cn_dosage_coupled_strong, cn_dosage_coupled_moderate, cn_dosage_uncoupled,
cn_invariant_panel, data_unavailable}. Verdict path (target-contracts): the coupled/uncoupled classes
fire cis-dosage-* rules → cis_coherence.resolver (a VERDICT-INERT, dedicated self-contained axis).
"""

from .read import METHOD_VERSION, read_cis_dosage  # noqa: F401
