"""uniprot_gpi_anchor.derive — reviewed-human UniProt SwissProt DAT → per-UniProt-AC GPI-anchor
parquet + a target-resolution sidecar (via target_id_resolver).

WHY THIS PRODUCT (P8.1 Slice 2): the surface-accessibility gate keys on TMbed PREDICTED topology,
which resolves the bulk transmembrane cases but STRUCTURALLY CANNOT see a GPI anchor — a GPI-anchored
antigen has NO membrane-spanning segment, so TMbed calls it `no_transmembrane` and the gate calls it
`unsupported`. Yet GPI-anchored proteins ARE displayed on the outer leaflet and ARE major biologics
targets (MSLN/mesothelin, FOLR1, CD59, ALPP). Only UniProt's CURATED LIPID feature carries the GPI
fact. This derive extracts it from the SwissProt DAT already mirrored on S3 (no new ingestion) so the
gate can rescue GPI antigens from the no_transmembrane false-negative.

Source: uniprot-sprot-human-2026-02-snapshot-2026-06-18 (the .dat.gz mirror).

DISCRIMINATOR (verified 2026-08-05 against the DAT): GPI-anchored iff a LIPID feature note contains
"GPI-anchor" (equivalently the subcellular line "Lipid-anchor, GPI-anchor"). This is SPECIFIC — it
does NOT fire for inner-leaflet lipid-anchored proteins: NRAS carries `Lipid-anchor` + `Cytoplasmic
side` but NO GPI-anchor, so it stays correctly negative (the false-positive the naive "has lipid
anchor" test would wrongly catch). Verified positives: MSLN/FOLR1/CD59/ALPP; verified negatives:
EGFR (single-pass TM), NRAS (cytoplasmic lipid-anchor).

Emits (one row per GPI-anchored UniProt AC — a POSITIVE-ONLY table; absence = not-GPI, never asserted
here as "not surface"):
  uniprot_ac, is_gpi_anchored (always True in the payload), gpi_lipid_note, gpi_subcellular_evidence
plus a sibling `*.target_resolution.parquet` sidecar (native_key_type='uniprot_accession'). Consumers
join payload + sidecar on the AC — never trust a source symbol column (deprecated-symbol risk).

Deterministic per (DAT snapshot, discriminator, resolver release). Usage:
    python -m methods.uniprot_gpi_anchor.derive --out /tmp/gpi.parquet [--resolver-release resolver_v1.0.0]
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import re
import sys
from pathlib import Path
from typing import Optional

S3_BUCKET = "onc-compbio"
SOURCE_S3_KEY = "data-catalog/sources/uniprot-sprot-human/2026_02-snapshot-2026-06-18/uniprot_sprot_human.dat.gz"
DEFAULT_AWS_PROFILE = "cbg"
DEFAULT_RESOLVER_RELEASE = "resolver_v1.0.0"
DATA_CATALOG = Path(
    os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
)

# A GPI-anchored entry carries a LIPID feature whose /note names a GPI-anchor, e.g.
#   FT   LIPID           ...
#   FT                   /note="GPI-anchor amidated serine"
# and/or the subcellular line "Cell membrane; Lipid-anchor, GPI-anchor". Match the specific
# GPI-anchor phrase — NOT bare "Lipid-anchor" (which also covers cytoplasmic-side prenylation, e.g.
# NRAS S-farnesyl/S-palmitoyl — those must NOT be called surface-accessible).
_GPI_NOTE_RE = re.compile(r'/note="([^"]*GPI-anchor[^"]*)"')
_GPI_SUBCELL_RE = re.compile(r"Lipid-anchor,\s*GPI-anchor", re.IGNORECASE)
_GENE_RE = re.compile(r"^GN\s+Name=([A-Za-z0-9._-]+)", re.M)
_AC_RE = re.compile(r"^AC\s+(\S+?);", re.M)


def _read_dat_bytes(local_path: Optional[str]) -> bytes:
    if local_path:
        return Path(local_path).read_bytes()
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
    import boto3

    return boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=SOURCE_S3_KEY)["Body"].read()


def build_payload(local_dat: Optional[str] = None):
    """Return the per-UniProt-AC GPI-anchor payload DataFrame (positive-only)."""
    import pandas as pd

    raw = _read_dat_bytes(local_dat)
    rows = []
    seen = set()
    cur: list[str] = []
    with gzip.open(io.BytesIO(raw), "rt") as fh:
        for line in fh:
            cur.append(line)
            if not line.startswith("//"):
                continue
            block = "".join(cur)
            cur = []
            note_hit = _GPI_NOTE_RE.search(block)
            subcell_hit = _GPI_SUBCELL_RE.search(block)
            if not (note_hit or subcell_hit):
                continue
            acm = _AC_RE.search(block)
            if not acm:
                continue
            ac = acm.group(1).strip()
            if ac in seen:
                continue
            seen.add(ac)
            rows.append(
                {
                    "uniprot_ac": ac,
                    "is_gpi_anchored": True,
                    "gpi_lipid_note": note_hit.group(1) if note_hit else None,
                    "gpi_subcellular_evidence": bool(subcell_hit),
                }
            )
    df = pd.DataFrame(rows, columns=["uniprot_ac", "is_gpi_anchored", "gpi_lipid_note", "gpi_subcellular_evidence"])
    return df.sort_values("uniprot_ac").reset_index(drop=True)


def _emit_sidecar(payload_path: Path, resolver_release: str):
    """Emit the target-resolution sidecar next to the payload (mirrors cspa_surface_confirmation)."""
    lib = DATA_CATALOG / "libs" / "target_id_resolver"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from target_id_resolver.sidecar import emit_sidecar

    sidecar_path = Path(str(payload_path).replace(".parquet", ".target_resolution.parquet"))
    stats = emit_sidecar(
        payload_parquet_path=payload_path,
        native_key_column="uniprot_ac",
        native_key_type="uniprot_accession",
        gencode_version_source="n/a",  # UniProt curated feature, not gencode-annotated
        out_path=sidecar_path,
        resolver_release=resolver_release,
    )
    return sidecar_path, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path, help="payload parquet output path")
    ap.add_argument("--local-dat", default=None, help="local uniprot_sprot_human.dat.gz (else S3)")
    ap.add_argument("--resolver-release", default=DEFAULT_RESOLVER_RELEASE)
    ap.add_argument("--no-sidecar", action="store_true", help="skip sidecar emission (payload only)")
    args = ap.parse_args(argv)

    df = build_payload(args.local_dat)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, engine="pyarrow", compression="snappy", index=False)
    print(f"[uniprot_gpi] payload: {len(df)} GPI-anchored ACs -> {args.out}", file=sys.stderr)

    if not args.no_sidecar:
        sidecar_path, stats = _emit_sidecar(args.out, args.resolver_release)
        print(f"[uniprot_gpi] sidecar -> {sidecar_path}", file=sys.stderr)
        print(f"  resolver stats: {stats}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
