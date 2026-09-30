"""spatial_colocalization — the build_summary entry point the compose-dashboard live-reader calls.

`build_summary(target, indication) -> dict` is the single entry the skills dispatcher
(_live_readers.py::CARD_DISPATCHERS["spatial-tumor-normal-colocalization"]) invokes. Mirrors the
sc_tumor_expression_celltype contract: a deterministic (target, indication) -> summary dict with a
primary `spatial_coloc_class` categorical and a data_unavailable-safe branch.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import read as _read

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str) -> dict:
    """Spatial tumour-neighbourhood co-localization for a (target, indication): the
    `spatial_coloc_class` + per-compartment neighbourhood enrichment/adjacency of target-positive
    malignant cells, from the imaging spatial co-localization product. data_unavailable-safe."""
    summary = _read.read_spatial_colocalization(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="spatial tumour-normal co-localization for a target.")
    ap.add_argument("--target", required=True, help="HGNC gene symbol")
    ap.add_argument("--indication", required=True, help="OncoTree indication code (e.g. COADREAD)")
    args = ap.parse_args(argv)
    print(json.dumps(build_summary(args.target, args.indication), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
