"""kinome_atlas_prediction — Johnson 2023 + Yaron-Barir 2024 kinome atlas reader.

Consumer: mechanism_composed Phase-D card via a SEPARATE prediction lane.
Distinct from SIGNOR/CollecTri/Reactome curated edges — kinome-atlas
"edges" are PWM-derived predictions, not curated assertions.

Kinome coverage:
  - 303 human Ser/Thr kinases (Johnson 2023 Nature)
  - 78 canonical Tyr kinases + 15 non-canonical Tyr (Yaron-Barir 2024 Nature)
  - Total: 381 kinases with PWM specificity + ~89k substrate-site predictions

License: CC-BY 4.0 (Nature open-access; supplementary Excel files).

Companion:
  data-catalog:manifests/sources/kinome-atlas-nature-supplementary-snapshot-2026-07-10.yaml

Downstream consumers should:
  1. Treat kinome_atlas edges as source key `kinome_atlas_prediction` in
     the composed card's `sources` list — separate from curated sources.
  2. Weight/discount kinome-atlas edges vs curated edges in Tier-3 synthesis.
  3. Consult the confidence-rank percentile field for per-edge weighting.
"""
METHOD_VERSION = "0.1.0"

# Re-export the public API so dispatchers using __import__(...) find
# read_target_summary at package level.
from .read import read_target_summary  # noqa: F401,E402
