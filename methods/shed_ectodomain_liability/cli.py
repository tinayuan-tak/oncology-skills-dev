"""shed_ectodomain_liability.cli — shed-antigen classifier + loaders + CLI.

Answers the gate-F surface-window question the topology/family cards do NOT:
for a surface-present, correctly-targetable antigen, is its ectodomain
proteolytically SHED into circulation as a soluble decoy ("antigen sink") that
neutralizes an antibody / ADC / T-cell-engager before tumor delivery?

TWO EVIDENCE TIERS (deep-research verdict 2026-07-19 — no clean redistributable
structured shedding system-of-record exists):

  1. RELIABLE `clinical` tier — the curated serum-marker crosswalk
     `target-contracts/vocabularies/shed_antigen_targets.yaml`. A serum tumor
     marker IS a shed ectodomain by clinical-chemistry definition (CA125=MUC16,
     CA15-3=MUC1, SMRP=MSLN, shed-HER2-ECD=ERBB2, CEA=CEACAM5). This tier is the
     ONLY one that reliably covers shed receptors — verified live: ERBB2 + CEACAM5
     have NO HPA secretome annotation and MSLN reads "Intracellular and membrane",
     yet all three are clinically shed.

  2. PROXY `secretome_proxy` tier — HPA v25-1 "Secretome location" column
     ("Secreted to blood" / "Secreted in/to ...") corroborates a soluble form for
     genes absent from the curated tier. Broader but noisier (biased toward
     signal-peptide-route secretion), so it maps to the weaker class.

Emits the `shed-ectodomain-liability` card contract fields. A gene with NO
evidence at any tier returns `indeterminate` (NOT `not_shed`) — structured
shedding sources have systematic false negatives, so absence is not a trusted
negative. The card thresholds nothing; this reader produces the primary
categorical directly (continuous-in / threshold-out is not applicable — the
signal is inherently categorical clinical evidence).
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import Optional

import yaml

from methods.catalog_query.read import bucket_prefix_for

METHOD_VERSION = "0.2.0"  # 0.2.0 (E3): + MEASURED Olink conditioned-media shed facet (media.py)

# --- reliable tier: curated vocab in target-contracts ---
DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
SHED_VOCAB_RELPATH = "vocabularies/shed_antigen_targets.yaml"

# --- proxy tier: HPA v25-1 secretome (landed source hpa-v25-1) ---
HPA_SOURCE_MANIFEST_ID = "hpa-v25-1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, _HPA_PREFIX = bucket_prefix_for(HPA_SOURCE_MANIFEST_ID)
HPA_KEY = f"{_HPA_PREFIX}proteinatlas.tsv.zip"
DEFAULT_AWS_PROFILE = "cbg"

HPA_GENE_COL = "Gene"
HPA_UNIPROT_COL = "Uniprot"
HPA_SECRETOME_COL = "Secretome location"

# HPA "Secretome location" values that indicate a soluble/circulating form. The
# blood/ECM/systemic values are the shed-relevant ones; a purely local secretion
# (e.g. "Secreted in male reproductive system") is a much weaker circulating-sink
# signal, so we tier it. Verified against live value_counts (2026-07-19).
HPA_BLOOD_LOCATIONS = {
    "secreted to blood",
    "secreted to extracellular matrix",
    "secreted - unknown location",
}
HPA_SYSTEMIC_LOCATIONS = {  # secreted, but into a specific compartment (weaker circulating sink)
    "secreted in other tissues",
    "secreted to digestive system",
    "secreted in brain",
    "secreted in female reproductive system",
    "secreted in male reproductive system",
}


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


# ---------------------------------------------------------------------------
# Reliable tier — curated serum-marker crosswalk
# ---------------------------------------------------------------------------

def load_shed_vocab(target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS) -> dict:
    """Load the curated shed-antigen vocabulary (entries keyed by HGNC symbol)."""
    path = Path(target_contracts_dir) / SHED_VOCAB_RELPATH
    with open(path) as f:
        return yaml.safe_load(f)


def lookup_clinical_shed(gene_symbol: str,
                         target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS,
                         vocab: Optional[dict] = None) -> Optional[dict]:
    """Return the curated entry for a gene, or None. Vocab may be pre-loaded for tests."""
    v = vocab if vocab is not None else load_shed_vocab(target_contracts_dir)
    entries = (v or {}).get("entries", {}) or {}
    sym = gene_symbol.strip().upper()
    for k, entry in entries.items():
        if str(k).strip().upper() == sym:
            out = dict(entry or {})
            out["_vocab_version"] = (v or {}).get("version")
            return out
    return None


# ---------------------------------------------------------------------------
# Proxy tier — HPA secretome
# ---------------------------------------------------------------------------

def _read_hpa_secretome_df(hpa_path=None):
    """Load the HPA master TSV (Gene, Uniprot, Secretome location) — local path or S3."""
    import pandas as pd
    if hpa_path is not None:
        # local override: a .tsv, .tsv.zip, or parquet fixture for tests
        p = str(hpa_path)
        if p.endswith(".zip"):
            z = zipfile.ZipFile(p)
            with z.open(z.namelist()[0]) as f:
                return pd.read_csv(f, sep="\t",
                                   usecols=[HPA_GENE_COL, HPA_UNIPROT_COL, HPA_SECRETOME_COL],
                                   dtype=str)
        if p.endswith(".parquet"):
            return pd.read_parquet(p)
        return pd.read_csv(p, sep="\t",
                           usecols=[HPA_GENE_COL, HPA_UNIPROT_COL, HPA_SECRETOME_COL],
                           dtype=str)
    _ensure_aws_profile()
    import boto3
    body = boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=HPA_KEY)["Body"].read()
    z = zipfile.ZipFile(io.BytesIO(body))
    with z.open(z.namelist()[0]) as f:
        return pd.read_csv(f, sep="\t",
                           usecols=[HPA_GENE_COL, HPA_UNIPROT_COL, HPA_SECRETOME_COL],
                           dtype=str)


def lookup_hpa_secretome(gene_symbol: str, hpa_path=None) -> dict:
    """Return {found, secretome_location, uniprot, secreted_systemic} for a gene."""
    import pandas as pd
    df = _read_hpa_secretome_df(hpa_path)
    hit = df[df[HPA_GENE_COL].astype(str).str.upper() == gene_symbol.strip().upper()]
    if not len(hit):
        return {"found": False, "secretome_location": None, "uniprot": None,
                "secreted_systemic": False}
    row = hit.iloc[0]
    loc = row.get(HPA_SECRETOME_COL)
    loc = None if (loc is None or (isinstance(loc, float) and pd.isna(loc)) or str(loc) == "nan") else str(loc)
    loc_l = (loc or "").strip().lower()
    return {
        "found": True,
        "secretome_location": loc,
        "uniprot": (None if row.get(HPA_UNIPROT_COL) in (None, "nan") else str(row.get(HPA_UNIPROT_COL))),
        # blood/ECM/unknown = strong circulating-sink proxy; local compartments = weaker
        "secreted_systemic": loc_l in HPA_BLOOD_LOCATIONS,
        "secreted_local": loc_l in HPA_SYSTEMIC_LOCATIONS,
    }


# ---------------------------------------------------------------------------
# Classifier + summary
# ---------------------------------------------------------------------------

def classify_shed(clinical_entry: Optional[dict], hpa: dict) -> str:
    """Map the two-tier evidence → shed_liability_class per the card vocabulary.

    Precedence: clinical (curated) > secretome proxy (blood/ECM) > membrane-retained
    (found in HPA, no secretion) > indeterminate (no evidence either way).

    Vocabulary: clinically_shed | secretome_proxy_shed | not_shed_membrane_retained
                | indeterminate.
    """
    if clinical_entry is not None:
        return "clinically_shed"
    if hpa.get("secreted_systemic") or hpa.get("secreted_local"):
        return "secretome_proxy_shed"
    if hpa.get("found") and not hpa.get("secretome_location"):
        # HPA has the gene and assigns NO secretome location → membrane-retained /
        # intracellular per HPA. The shed axis is clear FROM THIS PROXY (still not a
        # guarantee — a shed RTK like ERBB2 that HPA misses is rescued by the curated
        # tier above; here we reached this branch only because the curated tier missed too).
        return "not_shed_membrane_retained"
    # gene not found in HPA at all, or found with an unhandled value → cannot tell
    return "indeterminate"


def compute_summary(gene_symbol: str,
                    clinical_entry: Optional[dict],
                    hpa: dict) -> dict:
    """Build the shed-ectodomain-liability card summary from the two tiers."""
    shed_class = classify_shed(clinical_entry, hpa)
    if clinical_entry is not None:
        tier = "clinical"
    elif shed_class == "secretome_proxy_shed":
        tier = "secretome_proxy"
    else:
        tier = "none"
    return {
        "shed_liability_class": shed_class,
        "shed_evidence_tier": tier,
        "serum_marker": (clinical_entry or {}).get("serum_marker"),
        "shed_product": (clinical_entry or {}).get("shed_product"),
        "shedding_protease": (clinical_entry or {}).get("shedding_protease"),
        "hpa_secretome_location": hpa.get("secretome_location"),
        "source_citation": (clinical_entry or {}).get("primary_source_citation"),
        "method_version": METHOD_VERSION,
    }


def load_and_classify(gene_symbol: str,
                      target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS,
                      hpa_path=None, vocab: Optional[dict] = None,
                      with_measured: bool = True,
                      media_path=None, idmap_path=None) -> dict:
    """Full pipeline for one gene: curated lookup + HPA proxy → card summary, PLUS the
    MEASURED Olink conditioned-media facet (E3, 2026-08-07).

    The measured facet is a PARALLEL categorical (`measured_shed_class` + media_* fields);
    it is ADDITIVE and NEVER alters the primary `shed_liability_class`/`shed_evidence_tier`
    that the two annotation tiers produce — so every gene's primary class is byte-stable.
    `with_measured=False` reproduces the pre-E3 summary exactly (used by the byte-stability
    test). `media_path`/`idmap_path` override S3 for offline tests.
    """
    clinical = lookup_clinical_shed(gene_symbol, target_contracts_dir, vocab=vocab)
    hpa = lookup_hpa_secretome(gene_symbol, hpa_path=hpa_path)
    summary = compute_summary(gene_symbol, clinical, hpa)
    if with_measured:
        from . import media as _media
        summary.update(_media.classify_measured_shed(
            gene_symbol, media_path=media_path, idmap_path=idmap_path))
    return summary


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Shed-ectodomain-liability lookup for a gene.")
    ap.add_argument("--gene", required=True)
    ap.add_argument("--target-contracts-dir", default=str(DEFAULT_TARGET_CONTRACTS))
    ap.add_argument("--hpa-path", default=None, help="local HPA TSV/zip/parquet override (else S3)")
    args = ap.parse_args(argv)
    out = load_and_classify(args.gene, Path(args.target_contracts_dir), hpa_path=args.hpa_path)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    _main()
