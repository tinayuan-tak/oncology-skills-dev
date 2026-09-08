"""depmap_methylation_silencing — promoter-methylation → own-expression silencing (cell-line arm).

The LoF/epigenetic-silencing analog of depmap_cis_dosage (amplification → over-expression). Does target
T's own promoter methylation PREDICT LOW expression of T across the DepMap panel? A strong NEGATIVE
methylation↔log2TPM correlation is the silencing signature (MLH1/CDKN2A/MGMT archetype) — the LoF cis
leg the amplification-driven cis-dosage card cannot see.

Composes the CCLE RRBS TSS-1kb methylation matrix (depmap-consortium-ccle-2019) with DepMap log2TPM
expression, both cell-line-joinable via DepMap ModelID (CCLE NAME_TISSUE → StrippedCellLineName). NO
TCGA crosswalk needed (that is the separate patient promoter-methylation arm).

Emits methylation_silencing_class ∈ {silencing_coupled_strong, silencing_coupled_moderate,
methylation_uncoupled, methylation_invariant_panel, data_unavailable}. Feeds the cis_coherence resolver's
LoF/silencing arm (coherent_lof_silencing) alongside the amplification-driven cis_dosage leg.
"""

from .read import METHOD_VERSION, read_methylation_silencing  # noqa: F401
