"""uniprot_gpi_anchor — curated GPI-anchor detection from UniProt SwissProt LIPID features.

P8.1 Slice 2: the surface-accessibility gate keys on TMbed predicted topology, which cannot see a GPI
anchor (no membrane-spanning segment). This module supplies the curated UniProt fact so GPI-anchored
antigens (MSLN/FOLR1/CD59/ALPP) are rescued from the no_transmembrane false-negative.
"""
from .read import read_gpi_anchor

__all__ = ["read_gpi_anchor"]
