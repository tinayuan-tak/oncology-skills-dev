"""dependency_controls — anchor a target's dependency (Chronos) against curated controls.

Axis-2 of the functional-requirement (Gate-C) contextualized-interpretation hardening.
The dependency analog of methods/tumor_presence_controls, but with two structural
differences that follow from the biology:

  1. NO PERCENTILE PRODUCT. Chronos is already a control-normalized scale (0 ~
     non-essential, -1 ~ common-essential median), so we do NOT need an all-gene rank
     product to make the number interpretable — we read the target's and each control
     gene's pan-panel MEDIAN Chronos DIRECTLY from the DepMap matrix (cheap
     column-projection reads via depmap_common.parquet.get_chronos_column) and compare
     on the raw scale.

  2. INVERTED semantics. positive_controls are pan-essential genes (an essentiality
     CEILING); reading AS essential as them is a broad-tox LIABILITY, not a win.
     negative_controls are non-essential genes (a dependency FLOOR). The therapeutic
     sweet spot is BETWEEN the bands.

Public entry point:
  control_position_dependency(target, release_pin="26q3") -> dict of dep_control_* fields.

data_unavailable-safe: vocab-load failure or absent Chronos → a
dep_control_position_class of data_unavailable, never a raise into the render path
(so the method can land before the vocab is merged, mirroring tumor_presence_controls).
"""

from .read import METHOD_VERSION, control_position_dependency  # noqa: F401
