"""depmap_cis_protein_dosage — cis-feature → own-PROTEIN dosage coupling.

The PROTEIN analog of methods/depmap_cis_dosage (CN → own-mRNA coupling): does a target's own
relative copy-number predict its own Gygi-MS protein abundance across the DepMap panel? Comparing the
protein slope against the mRNA slope (the sibling card's cn_expr_slope_log2tpm_per_cn) separates truly
dosage-SENSITIVE cis-drivers (ERBB2/MYC/MDM2 — CN raises both mRNA and protein) from dosage-BUFFERED
passengers (mRNA rises with CN but protein is post-transcriptionally buffered). Verdict-inert coherence
dimension for the cis-feature-coherence skill.
"""

from .read import read_cis_protein_dosage, METHOD_VERSION  # noqa: F401 — re-export for the card's
# generic dispatch (module: depmap_cis_protein_dosage, entrypoint: read_cis_protein_dosage), mirroring
# the depmap_cis_dosage sibling.
