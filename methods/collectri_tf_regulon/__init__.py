"""collectri_tf_regulon — CollecTri TF-target regulon reader.

Consumer: signaling-network-mechanism composed card (Phase D), via the
mechanism-and-pharmacology skill.

CollecTri (Müller-Dott et al. 2023 NAR) is a signed TF-target aggregator
merging 12 upstream sources (ExTRI, HTRI, TRRUST, TFactS, DoRothEA tier A,
NTNU.Curated, Pavlidis 2021, ...). ~43k human edges with signed weight
(+1 activator / -1 repressor) + per-row PMID + resource-attribution.

Complements SIGNOR (which has ~2k TF-target edges) with ~20x more TF-target
coverage. For a KRAS target-profile, CollecTri adds "KRAS → NFE2L2 → hundreds
of NFE2L2 target genes" downstream reasoning that SIGNOR alone cannot support.

Companion: data-catalog:manifests/sources/collectri-snapshot-2026-06-30.yaml
"""
METHOD_VERSION = "0.1.0"

# Re-export the public API so dispatchers using __import__(...) find
# read_target_summary at package level.
from .read import read_target_summary  # noqa: F401,E402
