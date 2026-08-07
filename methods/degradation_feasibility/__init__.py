"""degradation_feasibility — per-target degradability feasibility (degrader-lens E3 slice).

Answers the degrader lens's "is this target a tractable degradation substrate?" (the slot it reports
as degradability_machinery: not_yet_assessed). Fuses curated PROTAC/molecular-glue precedent
(degrader_precedent_targets.yaml) + natural E3-substrate evidence (ubibrowser-e3-substrate-per-gene-v1)
+ a surfaceome location gate (surface/secreted → cytoplasmic-E3-unreachable). Emits
degradability_feasibility_class {unfavorable_location / precedented_degradable /
ubiquitination_substrate / plausible_untested / data_unavailable}. Feeds the degrader lens via
degrader-channel-only rules; the small-molecule verdict is untouched.

METHOD_VERSION 0.1.0.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import degradation_feasibility_for_gene  # noqa: E402,F401
