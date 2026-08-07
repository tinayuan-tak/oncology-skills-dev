"""hpa_subcellular_location — per-target HPA immunofluorescence surface-residency confirmation.

Orthogonal (IF microscopy) cell-surface confirmation leg for surface-modality-fit, complementing
the CSPA mass-spec leg (cspa_surface_confirmation). Reads hpa-subcellular-location-per-gene-v1 and
emits surface_if_location_class {plasma_membrane_main / plasma_membrane_additional /
intracellular_only / location_unavailable}. intracellular_only = MEASURED non-surface;
location_unavailable = coverage gap (never opposing).

METHOD_VERSION 0.1.0.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_surface_if_location  # noqa: E402,F401
