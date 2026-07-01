"""dge_deseq2.read — read functions for existing DGE Parquet outputs.

This module is the *consumption* side of dge_deseq2; the existing `cli.py` is the
*production* side (runs the R pipeline). Both live in the methods repo because both
are deterministic data operations — neither makes orchestration decisions.

Per the framework's layer-distinction discipline (plan § Dashboard, Interpretation,
Inference Layers), reading a Parquet from S3 + filtering to a gene + normalizing
columns is *compute*, not *orchestration*. It belongs here, not in skills/.

Consumers:
  - compose-dashboard skill (via subprocess CLI or library import)
  - Jupyter notebooks doing ad-hoc DGE analysis
  - Future non-Claude consumers (AgenticBoost, Tina's dashboards, batch jobs)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

DATA_CATALOG = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
DEFAULT_AWS_PROFILE = "cbg"


def _ensure_aws_profile():
    """The onc-compbio bucket requires the cbg profile; the default SSO role lacks access."""
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _load_manifest(manifest_id: str) -> dict:
    """Load a derived manifest YAML from the data-catalog."""
    candidates = list((DATA_CATALOG / "manifests" / "derived").glob(f"{manifest_id}.yaml"))
    if not candidates:
        raise FileNotFoundError(
            f"Derived manifest not found in data-catalog/manifests/derived/: {manifest_id!r}"
        )
    with candidates[0].open() as f:
        return yaml.safe_load(f)


def _s3_uri_to_path(s3_uri: str) -> str:
    return s3_uri[5:] if s3_uri.startswith("s3://") else s3_uri


def read_dge_gene_row(
    target: str,
    manifest_id: str,
    return_field_map: bool = True,
) -> Optional[dict]:
    """Read a single gene's row from a DGE Parquet output, with predicate pushdown.

    Args:
      target: HGNC symbol (e.g., 'KRAS')
      manifest_id: Derived manifest ID (e.g., 'coadread-dge-df06320')
      return_field_map: If True, normalize column names to card-spec convention
        (log2_fc, q_value, n_tumor, n_adjacent). If False, return raw Parquet columns.

    Returns:
      Dict with gene's DGE summary, OR None if target not in Parquet.
      Includes _data_source + _data_s3_uri provenance keys.
    """
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    _ensure_aws_profile()

    manifest = _load_manifest(manifest_id)
    s3_uri = manifest.get("s3_uri")
    if not s3_uri:
        raise ValueError(f"Manifest {manifest_id!r} has no s3_uri field")
    path = _s3_uri_to_path(s3_uri)

    s3 = fs.S3FileSystem()
    table = pq.read_table(path, filesystem=s3, filters=[("gene_symbol", "=", target)])

    if table.num_rows == 0:
        return None

    raw = {col: table[col][0].as_py() for col in table.column_names}

    if not return_field_map:
        raw["_data_source"] = manifest_id
        raw["_data_s3_uri"] = s3_uri
        return raw

    log2_fc = raw.get("log2FoldChange")
    q_value = raw.get("padj")

    # Normalize to card-spec convention (v2)
    return {
        "log2_fc": log2_fc,
        "q_value": q_value,
        "tumor_mean_tpm": None,  # not in this product
        "adjacent_mean_tpm": None,
        "n_tumor": raw.get("n_tumor"),
        "n_adjacent": raw.get("n_normal"),
        "base_mean": raw.get("baseMean"),
        "is_significant_provider_call": raw.get("is_significant"),
        "is_actionable_provider_call": raw.get("is_actionable"),
        "is_upregulated_provider_call": raw.get("is_upregulated"),
        # Card v2 descriptive categorical — drives Tier-2 rules directly
        "expression_call_class": _classify_expression_call(log2_fc, q_value),
        "_data_source": manifest_id,
        "_data_s3_uri": s3_uri,
    }


def _classify_expression_call(log2_fc, q_value) -> str:
    """Map (log2_fc, q_value) → expression_call_class categorical.

    Vocabulary matches target-contracts/cards/expression-tumor-vs-adjacent.card.yaml
    summary_fields_vocabulary.expression_call_class. Tier-2 rules in
    interpretation-rules/intracellular-intrinsic.rules.yaml consume these labels.

    Thresholds identical to the pre-v2 interpretation_hints block:
      strong_upregulation:  q < 0.05 AND log2_fc >= 1.5
      modest_upregulation:  q < 0.05 AND 0.5 <= log2_fc < 1.5
      not_informative:      q >= 0.05 OR log2_fc < 0.5
      data_unavailable:     log2_fc or q_value is None/NaN
    """
    if log2_fc is None or q_value is None:
        return "data_unavailable"
    try:
        lfc = float(log2_fc)
        q = float(q_value)
    except (TypeError, ValueError):
        return "data_unavailable"
    # NaN check
    if lfc != lfc or q != q:
        return "data_unavailable"
    if q < 0.05 and lfc >= 1.5:
        return "strong_upregulation"
    if q < 0.05 and 0.5 <= lfc < 1.5:
        return "modest_upregulation"
    return "not_informative"
