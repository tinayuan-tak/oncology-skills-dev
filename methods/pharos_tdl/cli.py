#!/usr/bin/env python3
"""pharos_tdl — per-gene Target Development Level (TDL) druggability/novelty tier (Pharos/IDG).

A verdict-INERT target-intrinsic facet: what is the target's DRUGGABILITY/NOVELTY tier — is it
clinically drugged (Tclin), chemically probed (Tchem), biologically studied (Tbio), or dark (Tdark)?
A PRE-INTEGRATED classification (NCATS TCRD) over ChEMBL activity + drug approvals + ligand/antibody
availability + bibliometrics. Fills the framework's novelty/druggability-tier gap.

tier: target (indication-independent). Reads the frozen per-gene TDL snapshot; O(1) lookup by HGNC symbol.

FACET-ONLY discipline: the novelty score is literature/grant-driven → verdict-INERT, never a killer
(same guardrail the framework applies to the OpenTargets association score).
"""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Optional

METHOD_VERSION = "0.1.1"   # 0.1.1: resolve source via the data-catalog manifest (catalog_query) instead of a hardcoded s3:// URI — same parquet, byte-identical output.

# Source resolved through the data-catalog single-source-of-truth (catalog_query.bucket_prefix_for),
# NOT a hand-typed s3:// constant — so a snapshot relocation follows the manifest, mirroring the
# depmap_paralog_aggregator / gnomad_constraint sibling convention. The manifest s3_uri is a directory
# (trailing slash), so bucket_prefix_for + the file path reconstruct the object key.
_TDL_SOURCE_MANIFEST_ID = "pharos-idg-tcrd-snapshot-2026-08-10"
_TDL_PARQUET_FILENAME = "pharos_tdl_per_gene.parquet"

# TDL → a compact druggability-tier interpretation
_TDL_MEANING = {
    "Tclin": "clinically drugged (approved drug acts via this target's mode)",
    "Tchem": "chemically probed (potent small-molecule ligands; no approved drug)",
    "Tbio":  "biologically studied (no chemical probe / approved drug)",
    "Tdark": "understudied / dark (minimal biology, no probe)",
}
@lru_cache(maxsize=1)
def _load_table():
    """Frozen per-gene TDL snapshot, indexed by gene_symbol. Uses boto3 via the shared client
    (AWS_PROFILE=cbg + adaptive-retry Config) — the sibling-reader convention. Replaces a
    `subprocess aws s3 cp` shell-out that had NO returncode check (a missing aws CLI or bad creds
    produced empty stdout → an opaque parquet-parse error). RAISES on read failure: the table either
    loads or the card honestly errors via the live-read seam (never a silent empty)."""
    import pandas as pd
    from methods.target_id_sidecar import s3_client
    from methods.catalog_query.read import bucket_prefix_for
    bucket, prefix = bucket_prefix_for(_TDL_SOURCE_MANIFEST_ID)   # manifest s3_uri (dir) → (bucket, key_prefix)
    key = f"{prefix}{_TDL_PARQUET_FILENAME}"
    body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body)).set_index("gene_symbol")


def read_pharos_tdl(target: str, indication: Optional[str] = None) -> dict:
    """Return the target-development-level card summary_fields for the target.

    `indication` accepted for dispatcher-signature uniformity but NOT consumed (TDL is
    indication-independent / target-intrinsic). data_unavailable when the target is not in TCRD.
    """
    if not target:
        return {"tdl_class": "data_unavailable", "_note": "target required."}
    try:
        tbl = _load_table()
    except ImportError:
        raise  # broken env (pandas/boto3) — never mask as a data gap
    except Exception as e:
        return {"tdl_class": "data_unavailable", "_live_read_error": f"{type(e).__name__}: {e}"}
    if target not in tbl.index:
        return {"tdl_class": "data_unavailable", "target": target,
                "_note": f"{target} not in the Pharos/IDG TCRD table."}
    row = tbl.loc[target]
    if hasattr(row, "iloc") and getattr(row, "ndim", 1) > 1:   # duplicate symbol safety
        row = row.iloc[0]
    tdl = str(row["tdl"])
    return {
        "tdl_class": tdl,                            # PRIMARY (Tclin | Tchem | Tbio | Tdark)
        "tdl_meaning": _TDL_MEANING.get(tdl, ""),
        "target_family": str(row.get("fam", "")),    # Kinase / Enzyme / GPCR / TF / ...
        "novelty_score": float(row["novelty"]) if row.get("novelty") == row.get("novelty") else None,
        "target": target,
        "_method_version": METHOD_VERSION,
        "_source": "Pharos/IDG TCRD (Target Development Level); verdict-inert target-intrinsic druggability/novelty tier",
    }


try:
    import click

    @click.command()
    @click.option("--target", required=True)
    @click.option("--indication", default=None)
    def main(target, indication):
        import json
        click.echo(json.dumps(read_pharos_tdl(target, indication), indent=2, default=str))

    if __name__ == "__main__":
        main()
except ImportError:
    pass
