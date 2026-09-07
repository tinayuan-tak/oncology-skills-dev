"""pmhc_presentation — peptide-centric HLA-presentation (immunopeptidome) for the biologics
peptide-centric TCE axis. classify = pure benign-presentation classifier; read = S3 boundary.
Consumed by surface-modality-fit (peptide-centric presentation facet). read_pmhc_presentation is the
live-dispatcher entry.
"""

from .read import read_pmhc_presentation  # noqa: E402,F401
