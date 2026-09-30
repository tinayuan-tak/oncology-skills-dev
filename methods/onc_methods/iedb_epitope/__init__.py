"""iedb_epitope — per-protein IEDB epitope / MHC-binding rollup for the biologics peptide-centric
axis. classify = pure epitope-evidence classifier; read = S3 boundary. Consumed by surface-modality-fit
as a VERDICT-INERT display card (pMHC-epitope experimental ground truth, complementing the HLA Ligand
Atlas benign-presentation card). read_target_summary is the generic-dispatch entrypoint.
"""

from .read import read_target_summary  # noqa: E402,F401
