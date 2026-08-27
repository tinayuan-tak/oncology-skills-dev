"""topology_predictions_tmbed.classify — derive topology_class + load helpers.

The shipped derived product carries RAW TMbed fields (n_tm_alpha_helices, n_tm_beta_strands,
signal_peptide, ecd_orientation, ecd_length, ...). The card contract wants the DERIVED
categorical `topology_class`. This module owns that derivation + the parquet/sidecar loaders,
so read.py stays a thin orchestrator (mirrors the cli/read split in the other methods).

topology_class vocabulary (target-contracts/cards/surface-topology-and-ptm.card.yaml):
  single_pass_type_1 | single_pass_type_2 | single_pass_type_other | multi_pass |
  gpi_anchored | beta_barrel | no_transmembrane | data_unavailable
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional


def classify_topology(n_tm_alpha: Optional[int], n_tm_beta: Optional[int],
                      signal_peptide: Optional[bool], ecd_orientation: Optional[str]) -> str:
    """Derive topology_class from raw TMbed fields.

    Rules (from the card's vocabulary comments):
      - beta_barrel: any TM-beta strands (rare in human).
      - no_transmembrane: 0 TM alpha + 0 TM beta (secreted or intracellular).
      - multi_pass: >=2 TM alpha helices.
      - single_pass (1 TM alpha): type_1 = signal-peptide + ECD-outside (N-term extracellular);
        type_2 = no signal-peptide + ECD-outside (C-term extracellular); else type_other.
    GPI-anchored is NOT derivable from TMbed 1D topology alone (needs a GPI-attachment-site
    predictor); left to the family/structure cards — never emitted here (honest under-call).
    """
    n_alpha = n_tm_alpha or 0
    n_beta = n_tm_beta or 0
    if n_beta > 0:
        return "beta_barrel"
    if n_alpha == 0:
        return "no_transmembrane"
    if n_alpha >= 2:
        return "multi_pass"
    # exactly one TM alpha helix — single-pass sub-typing
    outside = (ecd_orientation or "").lower() == "outside"
    if not outside:
        return "single_pass_type_other"
    return "single_pass_type_1" if signal_peptide else "single_pass_type_2"


# --- ECD-engineerability thresholds (residues of longest extracellular run) ---
# ADC epitope-accessibility floor mirrors the card threshold (min_ecd_length_adc_favorable: 200).
# The engineerability floor (30 AA) is the biologics-target-discovery TopologyECDProvider bar:
# a membrane-anchored protein needs an extracellular run long enough to raise a binder against;
# below it there is effectively no bindable ectodomain regardless of surface residency.
ECD_ENGINEERABLE_FLOOR = 30      # AA — below this the ECD is too small to engineer a binder against
ECD_AMPLE_EPITOPE_AREA = 200     # AA — ample epitope area (matches card min_ecd_length_adc_favorable)


def classify_ecd_engineerability(topology_class: str, extracellular_residue_count: Optional[int],
                                 ecd_orientation: Optional[str]) -> str:
    """Derive the ECD-engineerability categorical from fields already computed by TMbed.

    This makes the extracellular-domain SIZE a first-class biologics-substrate signal — not
    only an ADC epitope-accessibility gate (the card's prior framing) but ALSO a TCE-favorable
    positive: a large exposed ECD is a strong bispecific-binder substrate. Mirrors the
    biologics-target-discovery TopologyECDProvider ("is the exposed surface large enough to
    engineer a binder against?"), derived here from `extracellular_residue_count` + topology
    already flowing through the topology product — NO new data.

    Vocabulary (target-contracts/cards/surface-topology-and-ptm.card.yaml):
      no_extracellular_domain | minimal_ecd | moderate_ecd | large_ecd | data_unavailable

    Discipline: an ABSENT ECD length (None) is `data_unavailable` (coverage gap — abstain),
    NEVER coerced to 0 → `no_extracellular_domain` (which would be a measured-negative). This
    mirrors the measured-vs-data_unavailable doctrine (cf. the endocytosis-abstains fix).
    """
    if topology_class == "data_unavailable":
        return "data_unavailable"
    # A membrane-anchored surface protein is the substrate; 0-TM (secreted/intracellular) or an
    # inside-facing ECD offers no accessible extracellular target for a biologic.
    if topology_class == "no_transmembrane":
        return "no_extracellular_domain"
    if extracellular_residue_count is None:
        return "data_unavailable"          # ECD length not measured — abstain, do not call zero
    if (ecd_orientation or "").lower() != "outside":
        return "no_extracellular_domain"   # ECD faces the cytoplasm / orientation not extracellular
    if extracellular_residue_count < ECD_ENGINEERABLE_FLOOR:
        return "minimal_ecd"               # too small to raise a binder against
    if extracellular_residue_count < ECD_AMPLE_EPITOPE_AREA:
        return "moderate_ecd"              # engineerable; epitope area constrained for ADC
    return "large_ecd"                     # ample epitope area — strong ADC + TCE substrate


def _to_bool(v) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "t")


def _to_int(v) -> Optional[int]:
    try:
        if v is None or v == "":
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def compute_summary(row: dict, ptm_fields: dict, method_version: str) -> dict:
    """Build the card summary from a topology parquet row + the (data_unavailable) PTM block."""
    n_alpha = _to_int(row.get("n_tm_alpha_helices"))
    n_beta = _to_int(row.get("n_tm_beta_strands"))
    sp = _to_bool(row.get("signal_peptide"))
    ecd_orient = row.get("ecd_orientation") or "unknown"
    topology_class = classify_topology(n_alpha, n_beta, sp, ecd_orient)
    ecd_len = _to_int(row.get("ecd_length"))
    ecd_engineerability_class = classify_ecd_engineerability(topology_class, ecd_len, ecd_orient)
    summary = {
        "topology_class": topology_class,
        "tm_pass_count": n_alpha,
        "has_tm_beta": (n_beta or 0) > 0,
        "extracellular_residue_count": ecd_len,
        "ecd_engineerability_class": ecd_engineerability_class,
        "ecd_orientation": ecd_orient,
        "signal_peptide_present": sp,
        "signal_peptide_length": _to_int(row.get("signal_peptide_end")),
        "topology_summary": row.get("topology_summary"),
        "tmbed_model_version": row.get("tmbed_model_version"),
        "method_version": method_version,
        # isoform-selective warning is a separate vocabulary concern (not in this product) —
        # left False here; the composed card / skill applies the isoform vocab overlay.
        "isoform_selective_warning": False,
        "isoform_selective_dominant_isoform": None,
    }
    summary.update(ptm_fields)  # the data_unavailable PTM/motif block
    return summary


# --- loaders (S3 read-through; parquet_path/sidecar_path override for tests) ---

def _read_parquet(path_or_none, bucket, key):
    """Read a parquet from a local path if given, else stream from S3 (cached per (bucket, key))."""
    import pandas as pd
    if path_or_none is not None:
        return pd.read_parquet(path_or_none)   # test override — never cached
    return _read_parquet_s3(bucket, key)


@lru_cache(maxsize=8)
def _read_parquet_s3(bucket, key):
    """Whole-object S3 parquet read, cached per (bucket, key).

    The payload and the resolver sidecar are each a small per-protein reference table (~20k rows);
    they are read ONCE per process and reused across every target (mirrors the sibling surface
    readers, e.g. surfaceome_family_fusion's lru-cached whole-index). Previously this re-downloaded
    the ENTIRE payload AND sidecar on every read_target_summary call — the one in-family reader
    paying the whole-object cost repeatedly."""
    import io
    import boto3
    import pandas as pd
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def resolve_uniprot(target: str, sidecar_path=None, bucket=None, sidecar_key=None) -> Optional[str]:
    """target (HGNC symbol) → UniProt canonical accession via the resolution sidecar.

    MUST use the sidecar: the payload parquet's gene_symbol column is 100% empty
    (documented gotcha) — joining on it returns None for every row.
    """
    df = _read_parquet(sidecar_path, bucket, sidecar_key)
    # match on the resolver's primary symbol (native_row_key is the accession for this product's
    # sidecar; the human-facing join key is hgnc_primary_symbol_at_resolution).
    sym = target.strip().upper()
    for col in ("hgnc_primary_symbol_at_resolution",):
        if col in df.columns:
            hit = df[df[col].astype(str).str.upper() == sym]
            if len(hit) and "uniprot_canonical" in hit.columns:
                val = hit.iloc[0]["uniprot_canonical"]
                return str(val) if val is not None and str(val) != "nan" else None
    return None


def load_topology_row(accession: str, parquet_path=None, bucket=None, parquet_key=None) -> Optional[dict]:
    """Look up the per-protein topology row by UniProt accession."""
    df = _read_parquet(parquet_path, bucket, parquet_key)
    if "accession" not in df.columns:
        return None
    hit = df[df["accession"].astype(str).str.upper() == accession.strip().upper()]
    if not len(hit):
        return None
    return hit.iloc[0].to_dict()
