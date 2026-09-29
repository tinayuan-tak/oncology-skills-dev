"""progeny_pathway_activity — per-indication PROGENy pathway-activity context (Track PROGENy).

A verdict-INERT mechanism-context facet from the PROGENy model (Schubert 2018, Apache-2.0): which of
the 14 cancer-signaling pathways are relatively ACTIVE in an indication's TCGA cohort? Upgrades the
Mechanism gate from network-topology-only (SIGNOR/OmniPath edges) to QUANTITATIVE per-indication
pathway activity, scored (decoupler MLM) against the recount3/TCGA log2(TPM+1) already in the catalog.

Aggregates to a per-(pathway x indication) rollup at BUILD time (read grain pre-aggregated → O(1)
skill reads). Activity is stored per-indication AND z-scored across indications — the card reads the
RELATIVE (cross-cohort) class (relatively_high / relatively_low / average), never an absolute
per-cohort on/off (PROGENy activity sign depends on the scoring normalization; only cross-cohort
comparison is interpretable — the honest framing).

Micro-benchmark (COADREAD, 2026-08-10): 669 samples x 14 pathways scored in ~28s via DuckDB pushdown
+ decoupler MLM; Hypoxia/TNFa/EGFR high, p53 low (directionally sensible for CRC).

Emits pathway_activity_class + relatively_high/low_pathways + target_pathway_membership. VERDICT-INERT:
no resolver rung — sibling of phospho-pathway-activity / signaling-network-mechanism in the Mechanism space.
"""

from .read import METHOD_VERSION, read_progeny_pathway_activity  # noqa: F401
