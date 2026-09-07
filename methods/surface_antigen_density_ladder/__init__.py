"""surface_antigen_density_ladder — the ABSOLUTE surface-density calibration corpus (schema v3).

The tiered-evidence model (feedback_surface_density_evidence_model; plan
.claude/plans/surface-density-multi-anchor.md) establishes that ONLY directly-calibrated flow /
single-molecule counting sets the absolute surface copies-per-cell scale (evidence grades A patient /
B cell-line). CSPA, CCLE/CPTAC whole-cell proteomics, and HPA IHC are priors (grades C/D), never
absolute anchors.

This module is that absolute anchor: a MANUALLY GOVERNED corpus of MEASURED density values, one row
per (target, sample, measurement), every value quoted from a primary table/supplement with a
resolvable DOI (no bar-graph digitization). schema v3 is the SUPERSET of the domain-expert's governed
32-column schema + this module's validator guarantees (see read.py). Partitions gate use
(native_patient/native_cell_line = tumor anchor; normal_reference/calibration_reference/method_control/
explicit_negative = NOT); dual admissibility booleans + a quarantine-aware validator keep malformed or
mis-tagged rows out of any calibration.
"""

METHOD_VERSION = "0.3.0"

from .read import read_absolute_density  # noqa: F401,E402
from .read import read_explicit_negatives  # noqa: F401,E402
from .read import validate_row  # noqa: F401,E402
from .read import SCHEMA_V3_COLUMNS  # noqa: F401,E402
