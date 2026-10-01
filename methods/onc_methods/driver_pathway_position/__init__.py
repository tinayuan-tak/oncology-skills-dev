"""driver_pathway_position — target-conditioned, indication-conditioned positional read: does the
target sit IN / UPSTREAM of / DOWNSTREAM of the indication's frequently-altered driver pathway?

Cross-read of Sanchez-Vega per-gene oncogenic-pathway membership (F1) x per-indication pathway-
alteration frequency x SIGNOR directed edges. VERDICT-INERT (soft rules only; no resolver) — reports
POSITION, not desirability (the MARK2->YAP/TAZ membership-lens verdict was rejected as overfit). See
read.py for the full cross-read contract.
"""

from .read import METHOD_VERSION, read_driver_pathway_position  # noqa: F401
