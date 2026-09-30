"""cspa_surface_confirmation.cli — thin CLI over the reader (parity with sibling method modules).

Derive (source xlsx → derived parquet + resolver sidecar) lives in derive.py; this exposes the
read-side lookup for ad-hoc inspection:

    python -m onc_methods.cspa_surface_confirmation.cli --target EGFR
    python -m onc_methods.cspa_surface_confirmation.cli --target EGFR --payload-path /tmp/cspa.parquet \
        --sidecar-path /tmp/cspa.target_resolution.parquet
"""

from __future__ import annotations

import argparse
import json
import sys

from .read import read_surface_confirmation


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", required=True, help="HGNC symbol or UniProt accession")
    ap.add_argument("--indication", default=None)
    ap.add_argument("--payload-path", default=None, help="local payload parquet (else S3)")
    ap.add_argument("--sidecar-path", default=None, help="local sidecar parquet (else S3)")
    args = ap.parse_args(argv)
    summary = read_surface_confirmation(
        args.target, indication=args.indication, payload_path=args.payload_path, sidecar_path=args.sidecar_path
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
