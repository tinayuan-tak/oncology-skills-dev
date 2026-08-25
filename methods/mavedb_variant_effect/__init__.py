"""mavedb_variant_effect — MEASURED multiplexed variant-effect (MAVE/DMS/SGE) reader.

Consumer: the verdict-INERT `variant-effect-mave-mavedb` display card in the
genomic-alteration-profile skill. It adds the per-variant *functional* axis alongside CIViC's
per-variant *clinical* call (variant-level-interpretation) and the gene-level alteration-role:
"how many of this gene's variants have been functionally ASSAYED, across how many MAVE score
sets, and what is the pooled functional-score distribution?"

Reads the derived per-gene product `mavedb-variant-effect-per-gene-v1` (data-catalog), a
gene_symbol-keyed rollup of the MAVEdb snapshot (mavedb.org; Rubin, Esposito, Fowler et al.):
per gene_symbol it carries has_hgnc_mapping, n_score_sets, n_variants_assayed / n_variants_scored,
the pooled functional-score distribution (score_min/median/max — a PER-ASSAY scale, NOT a
thresholded LoF call), target_categories, and the score-set URNs. The reader pushes down ONE
gene's row (filters=[("gene_symbol","=",symbol)]) and summarizes it into a measured-variant-effect
comparator shape (mave_evidence_class + counts + score distribution).

ORTHOGONAL to CIViC: CIViC is curated CLINICAL interpretation (oncogenic/resistance); MAVEdb is
MEASURED multiplexed functional-effect scores. Different claim → distinct measurement_type
(variant_functional_effect_mave), not a corroborating provider of variant_level_interpretation.

Companion: data-catalog:manifests/derived/mavedb-variant-effect-per-gene-v1.yaml
"""
METHOD_VERSION = "0.1.0"

# Re-export the public API so dispatchers using __import__(...) find read_target_summary at
# package level (mirrors tphp_normal_protein / collectri_tf_regulon / procan_protein_abundance).
from .read import read_target_summary  # noqa: F401,E402
