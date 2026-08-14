"""spatial_surface_protein — build_summary entry for the spatial-surface-protein-abundance card.

`build_summary(target, indication) -> dict` is the entry the skills dispatcher
(_live_readers.py::CARD_DISPATCHERS["spatial-surface-protein-abundance"]) invokes. Deterministic
(target, indication) -> summary with a primary `spatial_protein_class` + data_unavailable-safe branch.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import read as _read

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str) -> dict:
    """Spatial region-PROTEIN tumour-compartment abundance for a (target, indication): the
    `spatial_protein_class` (tumour_enriched / tme_enriched / no-preference) + TUMOUR vs TME abundance,
    from the GeoMx DSP region-protein product. data_unavailable-safe."""
    summary = _read.read_spatial_surface_protein(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="spatial region-protein tumour-compartment abundance.")
    ap.add_argument("--target", required=True, help="HGNC gene symbol")
    ap.add_argument("--indication", required=True, help="OncoTree indication code (e.g. HNSC)")
    args = ap.parse_args(argv)
    print(json.dumps(build_summary(args.target, args.indication), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
