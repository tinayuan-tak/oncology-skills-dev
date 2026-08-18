"""depmap_fusion_dependency.read — library entry point for fusion-stratified dependency.

Delegates to depmap_chronos_distribution.load_depmap_files (Chronos) + a target-scoped fusion
loader (below, ported from depmap_predictability_precompute.features.load_fusion) +
cli.compute_fusion_stratification. Mirrors depmap_cn_dependency/read.py's shape + error handling.
Target-only (indication accepted for the dispatcher signature, not consumed).

Returns the fusion-stratified-dependency card's summary_fields, or a dict with _live_read_error
when the underlying DepMap data is unreachable.

The fusion-involvement boolean is the gene-collapsed symbol-union: True when the target appears
as EITHER the 5' (LeftGene) or 3' (RightGene) partner in any default high-confidence fusion call
for a line. The comparator (fusion-negative) universe is every OTHER fusion-PROFILED line — lines
absent from OmicsFusionFiltered.csv were never fusion-called and are excluded, not counted negative.
"""
from __future__ import annotations

import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"

# DepMap 26Q1 source location (raw source, mirrors depmap_predictability_precompute.features).
DEPMAP_S3_BUCKET = "onc-compbio"
DEPMAP_SOURCE_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1"
FUSION_S3_KEY = f"{DEPMAP_SOURCE_PREFIX}/OmicsFusionFiltered.csv"

_GENE_PAREN_RE = re.compile(r"^([A-Za-z0-9._\-]+)\s*\(\d+\)$")


from methods.target_id_sidecar import ensure_aws_profile


def _extract_symbol(col) -> Optional[str]:
    """Return HGNC symbol from a fusion gene cell in either form ('KRAS' or 'KRAS (3845)').

    Ported verbatim from depmap_predictability_precompute.features.extract_symbol.
    """
    if not isinstance(col, str):
        return None
    s = col.strip().strip('"')
    if not s:
        return None
    m = _GENE_PAREN_RE.match(s)
    if m:
        return m.group(1)
    return s.split(" ", 1)[0] or None


def _load_fusion_involvement(target: str) -> tuple[dict, list]:
    """Build {ModelID -> bool} over the fusion-profiled universe: True iff `target` is a
    partner (5' OR 3') in any default high-confidence fusion call for that line.

    Returns (fusion_by_model, errors). errors is non-empty (and dict empty) on read failure.
    """
    import pandas as pd

    try:
        import boto3
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=FUSION_S3_KEY)
        df = pd.read_csv(BytesIO(obj["Body"].read()))
    except Exception as exc:  # noqa: BLE001 — surface as data_unavailable, never raise
        return {}, [{"_live_read_error": "fusion_read_failed", "detail": str(exc)}]

    if "ModelID" not in df.columns:
        return {}, [{"_live_read_error": "fusion_schema_no_modelid"}]

    # Default-entry filter (one representative fusion call set per model), mirroring load_fusion.
    if "IsDefaultEntryForModel" in df.columns:
        df = df[df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])]

    # Fusion-profiled universe = every line present in the (default-filtered) table.
    profiled = [m for m in df["ModelID"].dropna().unique()]
    if not profiled:
        return {}, [{"_live_read_error": "no_profiled_fusion_lines"}]

    # Gene-partner columns vary slightly across releases; look for likely candidates.
    left_col = next((c for c in df.columns
                     if c.lower() in ("leftgene", "leftgenesymbol", "gene1", "leftbreakpointgene")), None)
    right_col = next((c for c in df.columns
                      if c.lower() in ("rightgene", "rightgenesymbol", "gene2", "rightbreakpointgene")), None)
    if left_col is None or right_col is None:
        return {}, [{"_live_read_error": "fusion_schema_no_partner_columns"}]

    # Lines carrying a fusion INVOLVING the target (either partner).
    target_u = target.strip().upper()
    left_sym = df[left_col].map(_extract_symbol)
    right_sym = df[right_col].map(_extract_symbol)
    involves = ((left_sym.str.upper() == target_u) | (right_sym.str.upper() == target_u))
    positive = set(df.loc[involves, "ModelID"].dropna().unique())

    fusion_by_model = {m: (m in positive) for m in profiled}
    return fusion_by_model, []


def read_fusion_stratified_dependency(target: str, indication: Optional[str] = None) -> dict:
    """Compute fusion-stratified dependency for target across the DepMap panel.

    `indication` is accepted for dispatcher-signature back-compat but NOT consumed
    (target-only, like the mutation/CN stratified siblings). Returns the card's
    summary_fields, or a dict with _live_read_error when data is unreachable.
    """
    ensure_aws_profile()
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))

    from methods.depmap_chronos_distribution import cli as c1cli

    # 1. Chronos (reuse Card-1's loader)
    chronos_by_model, model_metadata, chronos_errs = c1cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if chronos_errs:
        return {
            "_live_read_error": chronos_errs[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": chronos_errs,
            "_remediation": "Method cannot reach DepMap 26Q1 Chronos; verify local cache or AWS credentials.",
            "fusion_stratification_class": "data_unavailable",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_chronos_for_target",
            "target": target,
            "fusion_stratification_class": "data_unavailable",
        }

    # 2. Fusion-involvement boolean over the fusion-profiled universe.
    fusion_by_model, fusion_errs = _load_fusion_involvement(target)
    if fusion_errs or not fusion_by_model:
        return {
            "_live_read_error": (fusion_errs[0].get("_live_read_error", "fusion_read_failed")
                                 if fusion_errs else "no_fusion_profiled_lines"),
            "errors": fusion_errs,
            "_remediation": "Method cannot reach DepMap 26Q1 fusion calls; verify local cache or AWS credentials.",
            "fusion_stratification_class": "data_unavailable",
        }

    # INDICATION-CONDITIONED ladder (T2.0) — within-lineage when powered, else pan-DepMap
    # (strong→moderate). Compute kernel unchanged. See depmap_common.lineage_ladder.
    from methods.depmap_common.lineage_ladder import apply_lineage_ladder

    def _compute(mut_models, wt_models):
        # fusion-positive = the "mutant" arm → mut_models; fusion-negative = WT arm → wt_models.
        def _keep(m):
            arm = mut_models if fusion_by_model.get(m) else wt_models
            return arm is None or m in arm
        c = {m: v for m, v in chronos_by_model.items() if _keep(m)}
        f = {m: v for m, v in fusion_by_model.items() if m in c}
        return _cli.compute_fusion_stratification(c, f)

    return apply_lineage_ladder(_compute, "fusion_stratification_class", model_metadata, indication)
