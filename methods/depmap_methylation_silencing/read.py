"""depmap_methylation_silencing.read — promoter-methylation → own-expression silencing (cell-line).

Composes the CCLE RRBS TSS-1kb methylation matrix (depmap-consortium-ccle-2019 source) with DepMap
log2TPM expression, both cell-line-joinable via DepMap ModelID (CCLE `NAME_TISSUE` → StrippedCellLineName).
NO TCGA crosswalk needed — the cell-line silencing arm; the patient promoter-methylation arm (tcga-sesame-
promoter-methylation-v1 joined via the sample-id crosswalk) is a separate, later leg.

Returns the cellline-methylation-expression-coherence card's summary_fields, or a dict with
_live_read_error + methylation_silencing_class=data_unavailable when data is unreachable.
"""
from __future__ import annotations

import gzip
import io
import sys
from pathlib import Path
from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"

CCLE_SOURCE_MANIFEST_ID = "depmap-consortium-ccle-2019"
CCLE_RRBS_TSS1KB_FILE = "CCLE_RRBS_TSS1kb_20181022.txt.gz"

# Precomputed per-(gene, CCLE-column) MEAN fractional-methylation product (methods/…/build_product.py).
# The reader pushdown-reads ONE gene's rows (~kB) instead of streaming the whole 40 MB gzip each call.
_DERIVED_PRODUCT_ID = "ccle-rrbs-promoter-methylation-mean-per-gene-v1"

from methods.target_id_sidecar import ensure_aws_profile


def _stripped_name_to_model(model_df) -> dict:
    """{StrippedCellLineName (UPPER) -> ModelID} from Model.csv — the CCLE→DepMap bridge."""
    out = {}
    id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
    name_col = "StrippedCellLineName" if "StrippedCellLineName" in model_df.columns else None
    if name_col is None:
        return out
    for _, row in model_df[[id_col, name_col]].iterrows():
        nm = row[name_col]
        if isinstance(nm, str) and nm:
            out[nm.strip().upper()] = row[id_col]
    return out


def _ccle_col_to_stripped(col: str) -> str:
    """CCLE column 'DMS53_LUNG' / 'SW1116_LARGE_INTESTINE' -> stripped name 'DMS53' / 'SW1116'.
    CCLE names are {STRIPPED}_{TISSUE}; the stripped name is the token before the first underscore
    (tissue suffixes may themselves contain underscores, so split on the FIRST only)."""
    return col.split("_", 1)[0].strip().upper()


def _load_ccle_methylation_for_gene(target: str, stripped_to_model: dict) -> tuple[dict, Optional[str]]:
    """Stream CCLE_RRBS_TSS1kb, average the target gene's TSS-1kb rows per cell line, map to ModelID.

    Returns ({ModelID -> mean fractional methylation}, error_or_None). Streams line-by-line so the
    ~400 MB uncompressed matrix is never fully materialized.
    """
    from methods.catalog_query.read import bucket_prefix_for
    try:
        import boto3
    except ImportError as e:
        return {}, f"boto3_not_available: {e}"

    bucket, prefix = bucket_prefix_for(CCLE_SOURCE_MANIFEST_ID)
    key = f"{prefix.rstrip('/')}/{CCLE_RRBS_TSS1KB_FILE}"
    # onc-compbio requires the `cbg` role; the ambient/default SSO role lacks s3:GetObject and env-var
    # creds override AWS_PROFILE, so assume the profile EXPLICITLY via a Session (frozen-creds trap).
    # Fall back to the default client (e.g. CI with instance creds / no cbg profile configured).
    try:
        import botocore  # noqa: F401
        try:
            s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
        except Exception:
            s3 = boto3.client("s3")
        body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as e:
        return {}, f"s3_read_failed: {e}"

    gz = gzip.GzipFile(fileobj=body)
    text = io.TextIOWrapper(gz, encoding="utf-8")

    header = text.readline().rstrip("\n").split("\t")
    # columns 0..2 = locus_id, CpG_sites_hg19, avg_coverage; 3+ = cell-line CCLE names.
    cell_cols = header[3:]
    # Per-cell-line accumulator for the target gene's TSS rows (mean over rows, skipping NaN).
    sums = [0.0] * len(cell_cols)
    counts = [0] * len(cell_cols)
    gene_prefix = f"{target}_"
    n_rows = 0
    for line in text:
        # cheap gene filter before splitting the whole (wide) row
        if not line.startswith(gene_prefix):
            continue
        parts = line.rstrip("\n").split("\t")
        locus_id = parts[0]
        # locus_id = GENE_chr_start_end → gene is everything before the trailing chr_start_end.
        if locus_id.rsplit("_", 3)[0] != target:
            continue
        n_rows += 1
        for i, v in enumerate(parts[3:3 + len(cell_cols)]):
            # CCLE RRBS pads values fixed-width, so missing cells are "    NaN" (leading spaces) and
            # float() would silently parse them to nan — poisoning the correlation. Parse then reject
            # non-finite explicitly (NaN != NaN).
            s = v.strip()
            if not s or s in ("NaN", "NA", "nan"):
                continue
            try:
                fv = float(s)
            except ValueError:
                continue
            if fv != fv:            # NaN guard (handles any residual non-finite parse)
                continue
            sums[i] += fv
            counts[i] += 1

    if n_rows == 0:
        return {}, "gene_not_in_ccle_rrbs"

    methyl_by_model = {}
    n_unmapped = 0
    for i, col in enumerate(cell_cols):
        if counts[i] == 0:
            continue
        model_id = stripped_to_model.get(_ccle_col_to_stripped(col))
        if model_id is None:
            n_unmapped += 1
            continue
        methyl_by_model[model_id] = sums[i] / counts[i]
    return methyl_by_model, None


def _load_methylation_from_product(target: str, stripped_to_model: dict, product_path=None):
    """Per-gene MEAN methylation via predicate-pushdown on the precomputed product.

    Returns, mirroring `_load_ccle_methylation_for_gene`'s contract EXACTLY:
      * ({ModelID -> mean_beta}, None) when the gene has rows (dict may be empty if nothing mapped);
      * ({}, "gene_not_in_ccle_rrbs") when the product is reachable but the gene is absent;
      * None when the product is UNREACHABLE (manifest not registered / object absent) → caller falls
        back to the live whole-gzip read (the intended redundancy).

    Reconstructs the live loop byte-for-byte: iterate the gene's rows in original CCLE-column order
    and map StrippedCellLineName -> ModelID with the CALLER's Model.csv (so the product stays
    release-independent), the last column winning on a ModelID collision. `product_path` (a local
    parquet) overrides S3 for tests.
    """
    cols = ["gene_symbol", "ccle_column", "col_index", "mean_beta"]
    if product_path is not None:
        import pandas as pd
        try:
            df = pd.read_parquet(product_path, columns=cols,
                                 filters=[("gene_symbol", "=", target.upper())])
        except (FileNotFoundError, OSError):
            return None
        rows = df.to_dict("records")
    else:
        try:
            from methods.catalog_query.read import s3_uri_for
            uri = s3_uri_for(_DERIVED_PRODUCT_ID)
        except Exception:  # absence-discipline: exempt -- resolves a LOCAL data-catalog manifest (not an S3 read); an unregistered/unreadable manifest => product not available => live whole-gzip fallback, which enforces its own read discipline.
            return None
        try:
            import pyarrow.fs as fs
            import pyarrow.parquet as pq
            path = uri.replace("s3://", "", 1)
            tbl = pq.read_table(path, filesystem=fs.S3FileSystem(),
                                columns=["ccle_column", "col_index", "mean_beta"],
                                filters=[("gene_symbol", "=", target.upper())])
        except Exception as e:  # noqa: BLE001
            # Product object genuinely absent → None (live fallback). A transient/creds/broken-env
            # error must NOT masquerade as "product absent" (the live read would hit the same infra)
            # — re-raise so the caller records an honest _live_read_error.
            from methods.target_id_sidecar import is_definitively_absent
            if isinstance(e, FileNotFoundError) or is_definitively_absent(e):
                return None
            raise
        rows = tbl.to_pylist()
    if not rows:
        return {}, "gene_not_in_ccle_rrbs"           # reachable, gene absent (live n_rows == 0)
    rows.sort(key=lambda r: r["col_index"])          # original CCLE-column order → last-wins on map
    methyl_by_model: dict = {}
    for r in rows:
        model_id = stripped_to_model.get(_ccle_col_to_stripped(r["ccle_column"]))
        if model_id is not None:
            methyl_by_model[model_id] = r["mean_beta"]
    return methyl_by_model, None


def _methylation_for_gene(target: str, stripped_to_model: dict):
    """Prefer the precomputed per-gene MEAN product (pushdown, ~kB); fall back to streaming the whole
    ~40 MB CCLE gzip when the product is unreachable. Byte-identical {ModelID: mean} either way."""
    res = _load_methylation_from_product(target, stripped_to_model)
    if res is not None:
        return res
    return _load_ccle_methylation_for_gene(target, stripped_to_model)


def read_methylation_silencing(target: str, indication: Optional[str] = None,
                               release_pin: str = "26q1") -> dict:
    """Compute promoter-methylation → own-expression silencing for target across the DepMap panel.

    `indication` accepted for dispatcher-signature back-compat but NOT consumed (pan-panel, target-only;
    evidence_scope=pan_no_indication). Returns the card's summary_fields, or a data_unavailable dict.
    """
    ensure_aws_profile()
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))

    def _unavailable(err: str) -> dict:
        return {"_live_read_error": err, "methylation_silencing_class": "data_unavailable",
                "evidence_scope": "pan_no_indication"}

    # 1. Model.csv → CCLE→ModelID bridge
    try:
        from methods.depmap_common.loaders import load_model_csv
        model_df = load_model_csv(release_pin)
    except Exception as e:
        return _unavailable(f"model_csv_read_failed: {e}")
    stripped_to_model = _stripped_name_to_model(model_df)
    if not stripped_to_model:
        return _unavailable("no_stripped_cell_line_name_column")

    # 2. CCLE RRBS methylation for the target gene → {ModelID -> mean fractional methylation}
    #    (per-gene product pushdown; live whole-gzip stream as fallback)
    methyl_by_model, meth_err = _methylation_for_gene(target, stripped_to_model)
    if meth_err or not methyl_by_model:
        return _unavailable(meth_err or "no_methylation_for_target")

    # 3. log2TPM expression (reuse the shared loader; ModelID-keyed)
    from methods.depmap_expression_distribution import cli as excli
    tpm_by_model, _tpm_meta, tpm_errs = excli.load_expression_files(
        release_pin=release_pin, target_symbol=target
    )
    if tpm_errs or not tpm_by_model:
        return _unavailable(tpm_errs[0].get("_live_read_error", "expression_read_failed")
                            if tpm_errs else "no_expression_for_target")

    summary = _cli.compute_methylation_silencing(methyl_by_model, tpm_by_model)
    summary["evidence_scope"] = "pan_no_indication"   # pan-panel; within-lineage deferred
    return summary
