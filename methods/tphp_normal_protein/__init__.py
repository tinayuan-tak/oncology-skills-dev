"""tphp_normal_protein — TPHP normal-tissue PROTEIN abundance reader.

Consumer: the verdict-INERT `normal-tissue-protein-abundance-tphp` display card in the
tumor-selectivity skill (a quantitative NORMAL-tissue PROTEIN comparator, complementing the
GTEx-RNA + HPA-IHC normal-tissue signals the skill already carried).

Reads the derived per-gene product `normal-tissue-protein-abundance-per-gene-v1` (data-catalog),
a long/tidy gene_symbol-keyed reshape of the TPHP body+cancer DIA-MS proteome (Xu et al.,
Nature 2026; open PRIDE PXD063370). Per (gene_symbol, tissue, tissue_class) it carries median
log2 MaxLFQ abundance + detection support across the 663 NORMAL samples (70 adult tissues + 4
fetal germ-layer groups). This reader pushes down ONE gene's per-tissue rows and summarizes them
into a normal-tissue-protein comparator shape (breadth class, tissue counts, max/median abundance,
highest-abundance tissue, fetal-vs-adult flag).

Companion: data-catalog:manifests/derived/normal-tissue-protein-abundance-per-gene-v1.yaml
"""
METHOD_VERSION = "0.1.0"

# Re-export the public API so dispatchers using __import__(...) find read_target_summary at
# package level (mirrors collectri_tf_regulon / procan_protein_abundance).
from .read import read_target_summary  # noqa: F401,E402
