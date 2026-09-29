"""cspa_surface_confirmation.derive — CSPA S2 master xlsx → per-UniProt-AC surface-confirmation
parquet + a target-resolution sidecar (via target_id_resolver).

Source: cspa-bausch-fluck-2015 (source manifest). Reads the S2 master workbook:
  - Table_B — 1,492 high-confidence human surface proteins: UniProt AC (`ID_link`), `CSPA category`
    (1-high / 2-putative / 3-unspecific), `Protein count` (detection breadth across the 41 cell lines).
  - Table_A — the UniProt↔gene-symbol map (used only to sanity-check; the CANONICAL symbol mapping
    is the resolver sidecar, NOT CSPA's own ENTREZ symbol column — the whole point of the sidecar).

Emits (one row per UniProt AC):
  uniprot_ac, surface_confirmation_class, cspa_category, n_celllines_detected
plus a sibling `*.target_resolution.parquet` sidecar mapping each uniprot_ac → canonical HGNC/
Ensembl/Entrez via target_id_resolver (native_key_type='uniprot_accession'). Consumers join the
payload + sidecar on the AC — never trust CSPA's own symbol column (deprecated-symbol risk).

Deterministic per (CSPA S2 xlsx, category→class map, resolver release). Usage:
    python -m methods.cspa_surface_confirmation.derive --out /tmp/cspa.parquet [--resolver-release resolver_v1.0.0]
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path
from typing import Optional

from methods.roots import data_catalog_root

S3_BUCKET = "onc-compbio"
SOURCE_S3_KEY = "data-catalog/sources/cspa-bausch-fluck-2015/pone.0121314.s002.xlsx"
DEFAULT_AWS_PROFILE = "cbg"
DEFAULT_RESOLVER_RELEASE = "resolver_v1.0.0"
# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DATA_CATALOG = data_catalog_root()

# CSPA confidence category (verbatim in Table_B) → surface_confirmation card vocab.
_CATEGORY_TO_CLASS = {
    "1 - high confidence": "confirmed_high",
    "2 - putative": "confirmed",
    "3 - unspecific": "not_surface",  # detected but non-specific → not a trusted confirmation
}


def _read_source_xlsx(local_path: Optional[str]) -> "pd.ExcelFile":  # noqa: F821
    import pandas as pd

    if local_path:
        return pd.ExcelFile(local_path)
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
    import boto3

    body = boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=SOURCE_S3_KEY)["Body"].read()
    return pd.ExcelFile(io.BytesIO(body))


def build_payload(local_xlsx: Optional[str] = None):
    """Return the per-UniProt-AC payload DataFrame (uniprot_ac + class + category + n_celllines)."""
    import pandas as pd

    xl = _read_source_xlsx(local_xlsx)
    B = xl.parse("Table_B")
    B = B.rename(columns={c: str(c).strip() for c in B.columns})
    if "ID_link" not in B.columns:
        raise ValueError("CSPA Table_B missing expected 'ID_link' (UniProt AC) column")
    rows = []
    seen = set()
    cat_col = "CSPA category"
    cnt_col = "Protein count"
    for ac, cat, cnt in zip(
        B["ID_link"].values,
        B.get(cat_col, pd.Series([None] * len(B))).values,
        B.get(cnt_col, pd.Series([None] * len(B))).values,
    ):
        if not isinstance(ac, str) or not ac.strip():
            continue
        ac = ac.strip()
        if ac in seen:
            continue
        seen.add(ac)
        cat_s = str(cat).strip() if cat is not None and cat == cat else None
        try:
            n = int(cnt) if cnt is not None and cnt == cnt else None
        except (TypeError, ValueError):
            n = None
        rows.append(
            {
                "uniprot_ac": ac,
                "surface_confirmation_class": _CATEGORY_TO_CLASS.get(cat_s or "", "not_surface"),
                "cspa_category": cat_s,
                "n_celllines_detected": n,
            }
        )
    df = pd.DataFrame(rows).sort_values("uniprot_ac").reset_index(drop=True)
    return df


def _emit_sidecar(payload_path: Path, resolver_release: str):
    """Emit the target-resolution sidecar next to the payload via target_id_resolver.emit_sidecar."""
    lib = DATA_CATALOG / "libs" / "target_id_resolver"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from target_id_resolver.sidecar import emit_sidecar

    sidecar_path = Path(str(payload_path).replace(".parquet", ".target_resolution.parquet"))
    stats = emit_sidecar(
        payload_parquet_path=payload_path,
        native_key_column="uniprot_ac",
        native_key_type="uniprot_accession",
        gencode_version_source="n/a",  # CSPA is protein-level MS, not gencode-annotated
        out_path=sidecar_path,
        resolver_release=resolver_release,
    )
    return sidecar_path, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path, help="payload parquet output path")
    ap.add_argument("--local-xlsx", default=None, help="local CSPA S2 xlsx (else stream from S3)")
    ap.add_argument("--resolver-release", default=DEFAULT_RESOLVER_RELEASE)
    ap.add_argument("--no-sidecar", action="store_true", help="skip sidecar emission (payload only)")
    args = ap.parse_args(argv)

    df = build_payload(args.local_xlsx)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, engine="pyarrow", compression="snappy", index=False)
    print(f"[cspa] payload: {len(df)} rows -> {args.out}", file=sys.stderr)
    print("  class distribution:", df["surface_confirmation_class"].value_counts().to_dict(), file=sys.stderr)

    if not args.no_sidecar:
        sidecar_path, stats = _emit_sidecar(args.out, args.resolver_release)
        print(f"[cspa] sidecar -> {sidecar_path}", file=sys.stderr)
        print(f"  resolver stats: {stats}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
