"""oncogenic_pathway_alteration — per-indication oncogenic-pathway ALTERATION context (Sanchez-Vega 2018).

Verdict-INERT cohort mechanism-context facet: how frequently is each of the 10 canonical oncogenic
signaling pathways ALTERED in an indication's TCGA cohort, and which pathway(s) does a target belong to?
A pre-integrated multi-omics RESULT (curated driver mut + GISTIC CN + fusion vs expert templates,
per-sample binary). Complements PROGENy pathway-ACTIVITY (transcriptional footprint) — this is pathway
ALTERATION (genomic); the same pathways, orthogonal axis.

Per-(pathway x indication) alteration-frequency rollup at build time (read grain pre-aggregated).
Per-pathway prevalences match textbook expectations (e.g. TP53/OV, WNT/COAD, PI3K/UCEC, RTK-RAS/PAAD).
gene->pathway map: KRAS/EGFR->RTK-RAS, CTNNB1->WNT, TP53->TP53.

Emits oncogenic_pathway_class + frequently_altered_pathways + target_pathway_membership +
target_pathway_alteration. VERDICT-INERT — routes into Mechanism (D) + Altered (E) as advisory context.
"""

from .read import METHOD_VERSION, read_oncogenic_pathway_alteration  # noqa: F401
