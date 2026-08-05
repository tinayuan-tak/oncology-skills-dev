"""tumor_presence_controls — control-benchmark axis for the tumor-presence subskill.

Phase 2 of the contextualized-interpretation enhancement. Expresses a target's
Phase-1 all-gene percentile RELATIVE to where KNOWN positive/negative control genes
sit on the SAME percentile scale, in the SAME indication cohort — so a reader can say
"the target sits above 3/4 positive controls and above every negative" rather than
staring at a bare "99th percentile".

The curated controls live in target-contracts/vocabularies/tumor_presence_controls.yaml
(positives = tumor-abundant approved antigens; negatives = housekeeping ceilings +
lineage/silent floors). Indication-matching (a lineage-marker negative is only negative
AWAY from its own lineage) is resolved through indication_crosswalk.yaml.

control_position is a one-directional CONFIDENCE facet — like the rest of this subskill
it never flips presence_verdict.
"""
from __future__ import annotations

from .read import control_position_tumor, control_position_cellline  # noqa: F401
