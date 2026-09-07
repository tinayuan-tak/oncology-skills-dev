"""spatial_region_rna — build_summary entry for the spatial-region-rna-expression card.

`build_summary(target, indication) -> dict` is the entry the skills dispatcher
(_live_readers.py::CARD_DISPATCHERS["spatial-region-rna-expression"]) invokes. Deterministic
(target, indication) -> summary with a primary `spatial_rna_class` + data_unavailable-safe branch.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import read as _read

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str) -> dict:
    """Spatial region-RNA tumour-compartment expression for a (target, indication): the
    `spatial_rna_class` (tumour_enriched / tme_enriched / no-preference) + TUMOUR vs TME abundance,
    from the GeoMx DSP WTA region-RNA product. data_unavailable-safe."""
    summary = _read.read_spatial_region_rna(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="spatial region-RNA tumour-compartment expression.")
    ap.add_argument("--target", required=True, help="HGNC gene symbol")
    ap.add_argument("--indication", required=True, help="OncoTree indication code (e.g. HNSC)")
    args = ap.parse_args(argv)
    print(json.dumps(build_summary(args.target, args.indication), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
