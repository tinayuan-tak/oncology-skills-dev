"""cspa_surface_confirmation — wet-lab measured cell-surface confirmation from CSPA (Bausch-Fluck 2015).

The live-firing provider of the `surface_confirmation` measurement_type (DATA_TO_SKILL_CONTRACT).
Resolves the CSPA orphan: cspa-bausch-fluck-2015 was cataloged (source manifest) but wired to no
reader; this module is that reader.
"""

from .read import read_surface_confirmation  # noqa: F401
