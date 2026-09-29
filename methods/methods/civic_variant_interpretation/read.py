"""civic_variant_interpretation.read — per-gene CIViC per-variant interpretation.

Fuses three CIViC snapshot TSVs (all on a single molecular_profile_id join axis):
  - VariantSummaries       : single_variant_molecular_profile_id → (gene, variant)
  - ClinicalEvidenceSummaries : molecular_profile_id → evidence_type / direction / significance / therapies
  - AssertionSummaries     : molecular_profile_id → AMP/ASCO/CAP graded significance (Oncogenic tier)

Emits per-(gene) the set of interpreted variants with an oncogenicity class + resistance class,
plus gene-level rollups (has_oncogenic_variant, resistance_variant_count, …). DISPLAY facet.
"""

from __future__ import annotations

import io
from functools import lru_cache

S3_BUCKET = "onc-compbio"
CIVIC_PREFIX = "data-catalog/sources/civic/nightly-snapshot-2026-07-02"
_VARIANT_KEY = f"{CIVIC_PREFIX}/nightly-VariantSummaries.tsv"
_EVIDENCE_KEY = f"{CIVIC_PREFIX}/nightly-ClinicalEvidenceSummaries.tsv"
_ASSERTION_KEY = f"{CIVIC_PREFIX}/nightly-AssertionSummaries.tsv"

# AMP/ASCO/CAP significance (AssertionSummaries) → oncogenicity class. Authoritative graded call.
_ASSERTION_ONCOGENICITY = {
    "Oncogenic": "oncogenic",
    "Likely Oncogenic": "likely_oncogenic",
    "Pathogenic": "oncogenic",  # germline-cancer-predisposing curated as pathogenic
    "Likely Pathogenic": "likely_oncogenic",
    "Benign": "benign",
    "Likely Benign": "benign",
    "Uncertain Significance": "vus",
}
# Ordering for choosing the strongest oncogenicity call per variant (higher = more oncogenic).
_ONCOGENICITY_RANK = {"oncogenic": 4, "likely_oncogenic": 3, "vus": 2, "benign": 1, "data_unavailable": 0}
# ClinicalEvidence Functional significance → oncogenicity when no graded Assertion exists.
# GoF / Dominant Negative / LoF (Supports) = a real functional consequence → likely_oncogenic;
# "Unaltered Function" (Supports) = benign-leaning.
_FUNCTIONAL_TO_ONCOGENICITY = {
    ("Supports", "Gain of Function"): "likely_oncogenic",
    ("Supports", "Loss of Function"): "likely_oncogenic",
    ("Supports", "Dominant Negative"): "likely_oncogenic",
    ("Supports", "Neomorphic"): "likely_oncogenic",
    ("Supports", "Unaltered Function"): "benign",
}
_RESISTANCE_SIGNIFICANCE = {"Resistance": "known_resistance", "Reduced Sensitivity": "reduced_sensitivity"}
# A variant with Predictive Sensitivity/Response evidence (a therapy TARGETS it) is strong
# implicit evidence of an actionable oncogenic driver — the canonical actionable variants
# (BRAF V600E, EGFR L858R, KRAS G12C) are catalogued via this evidence, NOT a dedicated
# Oncogenic item. Lift such a variant to likely_oncogenic when no stronger call exists.
_PREDICTIVE_SENSITIVITY = {"Sensitivity/Response"}


from methods.target_id_sidecar import ensure_aws_profile


def _read_tsv(key: str):
    import pandas as pd

    ensure_aws_profile()
    import boto3

    s3 = boto3.client("s3")  # ensure_aws_profile() has set AWS_PROFILE in the environment
    body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    return pd.read_csv(io.BytesIO(body), sep="\t", dtype=str)


@lru_cache(maxsize=1)
def _mp_to_gene_variant() -> dict:
    """{molecular_profile_id: (gene, variant)} for SINGLE-VARIANT molecular profiles only.
    Complex/compound/fusion profiles (no single_variant_molecular_profile_id → gene) are
    excluded — their evidence is combination biology, not a single gene's per-variant call."""
    vs = _read_tsv(_VARIANT_KEY)
    out = {}
    for mpid, gene, variant in zip(
        vs.get("single_variant_molecular_profile_id", []), vs.get("gene", []), vs.get("variant", [])
    ):
        if mpid and isinstance(mpid, str) and gene and isinstance(gene, str):
            out[mpid] = (gene, variant if isinstance(variant, str) else "")
    return out


@lru_cache(maxsize=1)
def _load() -> dict:
    """Build the per-gene interpretation index once. Returns {gene: {variant: {...}}}.

    Per variant we collect: oncogenicity_class (strongest of assertion/functional evidence),
    resistance_class (strongest resistance significance), n_evidence, and resistance therapies.
    """
    mp_gv = _mp_to_gene_variant()
    ev = _read_tsv(_EVIDENCE_KEY)
    asrt = _read_tsv(_ASSERTION_KEY)

    # per-(gene, variant) accumulator
    acc: dict = {}

    def _slot(mpid):
        gv = mp_gv.get(mpid)
        if not gv:
            return None
        gene, variant = gv
        g = acc.setdefault(gene, {})
        return g.setdefault(
            variant,
            {
                "variant": variant,
                "oncogenicity_class": "data_unavailable",
                "resistance_class": "no_resistance_annotation",
                "resistance_therapies": set(),
                "n_evidence": 0,
                "n_oncogenic_evidence": 0,
                "n_functional_evidence": 0,
                "n_resistance_evidence": 0,
                "n_sensitivity_evidence": 0,
            },
        )

    def _bump_oncogenicity(slot, cls):
        if _ONCOGENICITY_RANK.get(cls, 0) > _ONCOGENICITY_RANK.get(slot["oncogenicity_class"], 0):
            slot["oncogenicity_class"] = cls

    # ---- Assertions first (graded, authoritative) ----
    for mpid, atype, sig in zip(
        asrt.get("molecular_profile_id", []), asrt.get("assertion_type", []), asrt.get("significance", [])
    ):
        slot = _slot(mpid)
        if slot is None:
            continue
        if atype == "Oncogenic" and sig in _ASSERTION_ONCOGENICITY:
            _bump_oncogenicity(slot, _ASSERTION_ONCOGENICITY[sig])

    # ---- Clinical evidence ----
    for row in ev.itertuples(index=False):
        r = row._asdict() if hasattr(row, "_asdict") else dict(zip(ev.columns, row))
        mpid = r.get("molecular_profile_id")
        slot = _slot(mpid)
        if slot is None:
            continue
        slot["n_evidence"] += 1
        etype = r.get("evidence_type")
        edir = r.get("evidence_direction")
        sig = r.get("significance")
        if etype == "Oncogenic":
            slot["n_oncogenic_evidence"] += 1
            if edir == "Supports":
                _bump_oncogenicity(slot, "likely_oncogenic")  # supported-oncogenic w/o graded assertion
            elif edir == "Does Not Support":
                _bump_oncogenicity(slot, "vus")
        elif etype == "Functional":
            slot["n_functional_evidence"] += 1
            cls = _FUNCTIONAL_TO_ONCOGENICITY.get((edir, sig))
            if cls:
                _bump_oncogenicity(slot, cls)
        elif etype == "Predictive" and sig in _RESISTANCE_SIGNIFICANCE:
            slot["n_resistance_evidence"] += 1
            rcls = _RESISTANCE_SIGNIFICANCE[sig]
            # known_resistance dominates reduced_sensitivity
            if rcls == "known_resistance" or slot["resistance_class"] == "no_resistance_annotation":
                slot["resistance_class"] = rcls
            ther = r.get("therapies")
            if ther and isinstance(ther, str) and ther.strip():
                slot["resistance_therapies"].add(ther.strip())
        elif etype == "Predictive" and sig in _PREDICTIVE_SENSITIVITY:
            slot["n_sensitivity_evidence"] += 1
            # Implicit oncogenicity: a targeted-by-a-drug variant is an actionable driver. Only lift
            # from unknown/vus — never override an explicit benign/oncogenic graded call.
            if slot["oncogenicity_class"] in ("data_unavailable", "vus"):
                _bump_oncogenicity(slot, "likely_oncogenic")

    # freeze therapy sets → sorted lists
    for gene in acc:
        for v in acc[gene].values():
            v["resistance_therapies"] = sorted(v["resistance_therapies"])
    return acc


def civic_interpretation_for_gene(target: str) -> dict:
    """Per-gene CIViC per-variant interpretation summary for `target`. DISPLAY facet (verdict-inert).

    Returns gene-level rollups + the list of interpreted variants:
      has_oncogenic_variant       — any variant oncogenic/likely_oncogenic
      strongest_oncogenicity_class — the strongest per-variant oncogenicity call in the gene
      n_interpreted_variants      — single-variant profiles with CIViC evidence
      resistance_variant_count    — variants with a resistance annotation
      resistance_variants         — [{variant, resistance_class, therapies}], count-desc
      oncogenic_variants          — [{variant, oncogenicity_class, n_evidence}], strongest-first
      civic_interpretation_context
    data_unavailable when the gene has no single-variant CIViC evidence (NOT a benign call)."""
    idx = _load()
    sym = (target or "").strip()
    gene_variants = idx.get(sym)
    if not gene_variants:
        return {
            "civic_variant_class": "data_unavailable",
            "has_oncogenic_variant": None,
            "strongest_oncogenicity_class": "data_unavailable",
            "n_interpreted_variants": 0,
            "resistance_variant_count": 0,
            "resistance_variants": [],
            "oncogenic_variants": [],
            "civic_interpretation_context": f"no single-variant CIViC evidence for {sym}",
        }
    variants = list(gene_variants.values())
    onc = [v for v in variants if v["oncogenicity_class"] in ("oncogenic", "likely_oncogenic")]
    res = [v for v in variants if v["resistance_class"] != "no_resistance_annotation"]
    strongest = max((v["oncogenicity_class"] for v in variants), key=lambda c: _ONCOGENICITY_RANK.get(c, 0))
    onc_sorted = sorted(
        variants, key=lambda v: (-_ONCOGENICITY_RANK.get(v["oncogenicity_class"], 0), -v["n_evidence"], v["variant"])
    )
    res_sorted = sorted(res, key=lambda v: (-v["n_resistance_evidence"], v["variant"]))
    return {
        # a compact gene-level headline class: the strongest oncogenicity, or resistance-only note.
        "civic_variant_class": strongest,
        "has_oncogenic_variant": bool(onc),
        "strongest_oncogenicity_class": strongest,
        "n_interpreted_variants": len(variants),
        "resistance_variant_count": len(res),
        "resistance_variants": [
            {
                "variant": v["variant"],
                "resistance_class": v["resistance_class"],
                "therapies": v["resistance_therapies"],
                "n_evidence": v["n_resistance_evidence"],
            }
            for v in res_sorted[:10]
        ],
        "oncogenic_variants": [
            {"variant": v["variant"], "oncogenicity_class": v["oncogenicity_class"], "n_evidence": v["n_evidence"]}
            for v in onc_sorted
            if v["oncogenicity_class"] in ("oncogenic", "likely_oncogenic")
        ][:10],
        "civic_interpretation_context": (
            f"{len(variants)} single-variant CIViC profiles for {sym}: "
            f"{len(onc)} oncogenic/likely, {len(res)} with resistance annotation"
        ),
    }


def build_civic_interpretation_table():
    """Materialize the per-gene CIViC interpretation table (one row per gene with evidence).
    Gene-sorted for the gene-keyed product invariant."""
    import pyarrow as pa

    idx = _load()
    rows = []
    for gene in sorted(idx):
        g = civic_interpretation_for_gene(gene)
        rows.append(
            {
                "gene_symbol": gene,
                "civic_variant_class": g["strongest_oncogenicity_class"],
                "has_oncogenic_variant": bool(g["has_oncogenic_variant"]),
                "n_interpreted_variants": g["n_interpreted_variants"],
                "resistance_variant_count": g["resistance_variant_count"],
                # top oncogenic + resistance variants as compact strings (parquet-friendly)
                "oncogenic_variants": "; ".join(
                    f"{v['variant']}:{v['oncogenicity_class']}" for v in g["oncogenic_variants"]
                ),
                "resistance_variants": "; ".join(
                    f"{v['variant']}:{v['resistance_class']}({'/'.join(v['therapies'][:3])})"
                    for v in g["resistance_variants"]
                ),
            }
        )
    return pa.Table.from_pylist(rows, schema=_schema())


def _schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("civic_variant_class", pa.string()),
            pa.field("has_oncogenic_variant", pa.bool_()),
            pa.field("n_interpreted_variants", pa.int64()),
            pa.field("resistance_variant_count", pa.int64()),
            pa.field("oncogenic_variants", pa.string()),
            pa.field("resistance_variants", pa.string()),
        ]
    )
