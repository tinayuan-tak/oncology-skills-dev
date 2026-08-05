"""topology_predictions_tmbed.read — v2 library entry for live-mode reads.

The compose-dashboard dispatcher (`_dispatch_surface_topology_and_ptm`) calls
`read_target_summary(target=..., indication=...)`. The PRECOMPUTE pipeline in this
module (launch.sh / prepare_fasta.py / reduce_predictions.py) built the shipped derived
product `topology-predictions-tmbed-v1` (per-protein 1D topology). This read-side entry
was MISSING — the dispatcher imported a `read_target_summary` that didn't exist, so the
surface-topology card resolved unavailable. This writes it.

Delivers the DECISIVE surface-druggability no-go signal: `topology_class` (derived here
from the parquet's raw TM/SP/ECD fields) + ECD accessibility. A GPCR/multi-pass/ion-channel
target has no viable extracellular epitope → the GRIN2D/HTR1D no-go kill.

HONESTLY PARTIAL: the derived product carries topology only, NOT the UniProt PTM /
glycosylation / endocytosis-motif fields the card also lists. Those are emitted as
`data_unavailable` (a coverage gap, honestly surfaced) — they are ADC-internalization
refinements, not the decisive topology/epitope-viability axis. Same graceful-degradation
contract as the other readers (`_live_read_error` + topology_class=data_unavailable on
load failure).
"""

from __future__ import annotations

import os
from typing import Optional

from . import classify as _classify
from methods.catalog_query.read import bucket_key_for, sidecar_bucket_key_for

DERIVED_MANIFEST_ID = "topology-predictions-tmbed-v1"
# payload + resolver-sidecar keys resolved from the data-catalog manifest (single
# source of truth): s3_uri is the payload; target_resolution.sidecar_s3_uri the sidecar.
S3_BUCKET, PARQUET_KEY = bucket_key_for(DERIVED_MANIFEST_ID)
_, SIDECAR_KEY = sidecar_bucket_key_for(DERIVED_MANIFEST_ID)
DEFAULT_AWS_PROFILE = "cbg"
METHOD_VERSION = "read-0.1.0"

# PTM / motif fields the card lists but the derived product does NOT carry — emitted
# data_unavailable (honest coverage gap; ADC-internalization refinement, not the
# decisive topology axis). Kept explicit so the contract is legible.
_UNAVAILABLE_PTM_FIELDS = {
    "n_glycosylation_sites": None,
    "n_ubiquitination_sites": None,
    "endocytosis_motif_count": None,
    "endocytosis_motif_count_high_confidence": None,
    "endocytosis_motif_types": [],
    "_ptm_coverage": "data_unavailable",  # topology-only derived product; PTM axis not built
}


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _err(reason: str, remediation: str) -> dict:
    return {
        "_live_read_error": reason,
        "_remediation": remediation,
        "topology_class": "data_unavailable",
        "tmbed_model_version": None,
        "method_version": METHOD_VERSION,
    }


def read_target_summary(target: str, indication: Optional[str] = None,
                        parquet_path: Optional[str] = None,
                        sidecar_path: Optional[str] = None) -> dict:
    """Surface topology + epitope-viability for a target. Protein-intrinsic —
    `indication` accepted for the dispatcher contract but NOT consumed (topology is
    a property of the protein). parquet_path/sidecar_path override S3 for tests.

    Resolves target→UniProt accession via the target-resolution sidecar (the payload's
    `gene_symbol` column is 100% empty — documented gotcha — so we MUST join via the
    sidecar's uniprot_canonical, never the native column), then looks up the topology row.
    """
    _ensure_aws_profile()
    try:
        accession = _classify.resolve_uniprot(target, sidecar_path=sidecar_path,
                                              bucket=S3_BUCKET, sidecar_key=SIDECAR_KEY)
    except Exception as e:  # noqa: BLE001
        return _err("topology_sidecar_read_failed",
                    f"Could not resolve {target}→UniProt via sidecar: {e}")
    if accession is None:
        # sidecar read OK but target not resolvable → indeterminate-ish; honest data_unavailable
        return {**_err("target_not_in_resolver",
                       f"{target} not resolved to a UniProt accession in the topology sidecar"),
                "topology_class": "data_unavailable"}
    try:
        row = _classify.load_topology_row(accession, parquet_path=parquet_path,
                                          bucket=S3_BUCKET, parquet_key=PARQUET_KEY)
    except Exception as e:  # noqa: BLE001
        return _err("topology_parquet_read_failed",
                    f"Could not read topology parquet for {target}/{accession}: {e}")
    if row is None:
        return {**_err("accession_not_in_topology_table",
                       f"{target}/{accession} absent from TMbed topology product"),
                "topology_class": "data_unavailable"}
    return _classify.compute_summary(row, ptm_fields=_UNAVAILABLE_PTM_FIELDS,
                                     method_version=METHOD_VERSION)
