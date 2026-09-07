"""shet_selection — GeneBayes s_het (dominant-LoF selection coefficient) per-gene reader.

Reads shet-selection-per-gene-v1 (continuous s_het + 95% CI + shet_class) via gene_symbol pushdown.
The continuous LoF-intolerance signal for on-target-safety-liability, complementing the binary gnomAD
pLI/LOEUF constraint leg. Higher s_het = more intolerant of heterozygous LoF (dominant-LoF constraint).
"""

from .read import read_target_summary, METHOD_VERSION  # noqa: F401
