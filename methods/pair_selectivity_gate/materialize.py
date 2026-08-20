"""pair_selectivity_gate.materialize — batch materialization CLI for the bulk pair-selectivity product.

Amortizes the expensive read: ONE DuckDB scan per source pulls ALL clinical-seed antigens' per-sample
TPM (vs the interactive read.scan_pair's one scan per pair), assembles the in-memory cube, and computes
every (indication × target × partner × gate) row via derive_batch. Deterministic given the upstream
product md5s.

Product: `bispecific-bulk-pair-selectivity-per-indication-v1` — grain (indication × target × partner ×
gate), directed. Partner universe = the fixed clinical-seed antigens (bounded batch; arbitrary partner
sets stay served by the interactive bispecific-pair-scan skill).

Usage (AWS_PROFILE=cbg):
    python -m methods.pair_selectivity_gate.materialize --indication all --out /tmp/bulk_pair_selectivity.parquet
"""
from __future__ import annotations

from pathlib import Path

from .derive_batch import derive_bulk_pair_selectivity
from .read import TUMOR_MANIFEST_ID, GTEX_MANIFEST_ID, INDICATION_TO_TCGA_STUDIES, _con
from . import gates as _gates

METHOD_VERSION = "0.1.0"

# The fixed clinical-seed surface-antigen universe (mirrors bispecific-pair-scan skill's list). Both the
# target side and partner side draw from this set for v1 → a bounded batch. Widening the target side to
# the full surfaceome is a v2 option (the amortized read cost is unchanged — still one scan per source).
CLINICAL_SEED_ANTIGENS = [
    "EPCAM", "CEACAM5", "ERBB2", "MET", "MSLN", "FOLR1", "TACSTD2", "MUC1", "MUC16", "CD19",
    "MS4A1", "CD22", "TNFRSF17", "GPRC5D", "DLL3", "CLDN18", "CLDN6", "NECTIN4", "PSMA", "FOLH1",
]


def _build_cube(genes: list, source: str) -> dict:
    """ONE amortized DuckDB scan of a long product pulling ALL `genes` → {gene: {group: {sample_id: tpm}}}.

    source='tumor' → grouped by `study`; 'normal' → `tissue`. Linear TPM = pow(2, log2_tpm) - 1.
    This is the whole point of the batch path: the 790M-row GTEx read cost is row-group-bound (not
    predicate-bound), so pulling 20 genes costs ~the same as pulling 2 — but we reuse it for every pair."""
    from methods.catalog_query.read import s3_uri_for
    manifest = TUMOR_MANIFEST_ID if source == "tumor" else GTEX_MANIFEST_ID
    group_col = "study" if source == "tumor" else "tissue"
    uri = s3_uri_for(manifest)
    gene_list = ", ".join(f"'{g.upper().strip()}'" for g in genes)
    sql = f"""
      SELECT gene_symbol, sample_id, {group_col} AS grp, pow(2, log2_tpm) - 1 AS tpm
      FROM read_parquet('{uri}') WHERE gene_symbol IN ({gene_list})
    """
    df = _con().execute(sql).df()
    return cube_from_frame(df)


def cube_from_frame(df) -> dict:
    """Pure assembly of a scan DataFrame (columns gene_symbol, sample_id, grp, tpm) into
    {gene: {group: {sample_id: tpm}}}. Split out from _build_cube so it is unit-testable without S3."""
    cube: dict = {}
    for r in df.itertuples(index=False):
        cube.setdefault(r.gene_symbol, {}).setdefault(r.grp, {})[r.sample_id] = float(r.tpm)
    return cube


def materialize_all(indications: list | None = None) -> "pandas.DataFrame":  # noqa: F821
    """Build both cubes ONCE, then compute all rows for each indication. Returns the long DataFrame."""
    import pandas as pd
    inds = indications or sorted(INDICATION_TO_TCGA_STUDIES.keys())
    tumor_cube = _build_cube(CLINICAL_SEED_ANTIGENS, "tumor")
    normal_cube = _build_cube(CLINICAL_SEED_ANTIGENS, "normal")
    rows: list = []
    for ind in inds:
        rows.extend(derive_bulk_pair_selectivity(
            tumor_cube, normal_cube, ind, INDICATION_TO_TCGA_STUDIES,
            CLINICAL_SEED_ANTIGENS, CLINICAL_SEED_ANTIGENS, gates=_gates._GATES))
    df = pd.DataFrame(rows)
    if len(df):
        df["method_version"] = METHOD_VERSION
        df = df.sort_values(["indication", "target", "partner", "gate"]).reset_index(drop=True)
    return df


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Materialize the bulk pair-selectivity product.")
    ap.add_argument("--indication", default="all", help="OncoTree code, or 'all'")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    inds = None if args.indication == "all" else [args.indication.upper().strip()]
    df = materialize_all(inds)
    df.to_parquet(args.out, index=False)
    print(f"wrote {len(df)} rows ({df['indication'].nunique() if len(df) else 0} indications, "
          f"{len(CLINICAL_SEED_ANTIGENS)} seed antigens) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["CLINICAL_SEED_ANTIGENS", "cube_from_frame", "materialize_all", "_build_cube", "METHOD_VERSION"]
