"""opentargets_competitor_landscape.read — competitor drugs/programs for a (target, indication).

Answers the competitor-landscape card's question: "for {target} in {indication}, who else is
developing a drug against this target, at what MODALITY, and how far did they get?" — the competitive
field a Target Product Profile (TPP) needs to frame positioning (crowded-vs-whitespace,
validated-vs-contrarian modality, differentiation hooks). Orthogonal to the biology axes.

## Composition (one pinned catalogued product + the indication crosswalk)

  1. opentargets-target-competitor-drugs-per-gene-v1 : per-(ensembl_gene_id, drug, disease) rollup
     of drug name, drugType, on-target mechanism-of-action, all_moa_target_genes, per-indication
     max clinical stage, approval + withdrawal (derived over the pinned opentargets-26-06 mirror).
  2. indication_crosswalk.yaml (target-contracts) EFO lane : canonical OncoTree indication ->
     Open-Targets-native EFO/MONDO/Orphanet disease ids (to filter/annotate rows to the indication).

  target -> symbol_to_ensembl -> pushdown-read (1) for that gene;
  indication -> (2) -> efo_ids;  annotate each row indication_match (disease_id in efo_ids or a
  descendant-agnostic membership) -> classify modality -> aggregate.

## Modality classification (the value the raw drugType alone can't give)

  drugType is coarse ('Antibody', 'Small molecule', ...). The finer therapeutic MODALITY is inferred
  from drugType + all_moa_target_genes + action_type:
    - 'Antibody drug conjugate'                                  -> ADC
    - Antibody/Protein engaging a CD3/effector gene (bispecific) -> TCE (T-cell engager)
    - Antibody/Protein, multispecific, no effector arm           -> bispecific_antibody
    - Antibody/Protein, single target                            -> monoclonal_antibody
    - action_type contains DEGRADER                              -> degrader
    - 'Small molecule'                                           -> small_molecule
    - 'Oligonucleotide'                                          -> oligonucleotide
    - 'Cell' / 'Gene'                                            -> cell_or_gene_therapy
    - Enzyme / Oligosaccharide / Vaccine component               -> other_biologic
    - Unknown / else                                             -> other

## Honest coverage (measured-vs-null discipline)

- A target with NO rows in the OT rollup -> no_known_competitor (coverage gap OR genuinely virgin
  target; OT aggregates ChEMBL clinical candidates + approved drugs, not undisclosed/preclinical).
- An indication with no EFO lane -> indication_match cannot be computed; falls back to the
  TARGET-LEVEL competitor field with indication_scope: 'target_level' (still useful; the prototype
  was target-level) and a _note.
- 'notable failures' are NOT directly flagged by OT: a withdrawn marketed drug is captured
  (drug_warning), but a late-stage program that was discontinued pre-approval is reported as
  late_stage_non_approved (a candidate failure), NOT asserted as failed.

data_unavailable-safe. Absence = coverage gap, never a silent fake-negative.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from methods.roots import contracts_root

COMPETITOR_MANIFEST = "opentargets-target-competitor-drugs-per-gene-v1"
METHOD_VERSION = "0.1.0"

# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
TARGET_CONTRACTS = Path(contracts_root())

# CD3 / immune-effector Ensembl gene ids — a competitor antibody engaging one of these has the
# T-cell-engager (bispecific TCE) signature. CD3D / CD3E / CD3G / CD247(CD3zeta) + FCGR3A (NK engager).
_EFFECTOR_ENGAGER_ENSG = frozenset(
    {
        "ENSG00000167286",  # CD3D
        "ENSG00000198851",  # CD3E
        "ENSG00000160654",  # CD3G
        "ENSG00000198821",  # CD247 (CD3 zeta)
        "ENSG00000203747",  # FCGR3A (CD16a — NK-cell engager)
    }
)

# Open Targets maxClinicalStage -> ordinal (highest-wins) + coarse stage class.
_STAGE_ORD = {
    "PRECLINICAL": 1,
    "IND": 2,
    "EARLY_PHASE_1": 3,
    "PHASE_1": 4,
    "PHASE_1_2": 5,
    "PHASE_2": 6,
    "PHASE_2_3": 7,
    "PHASE_3": 8,
    "PREAPPROVAL": 9,
    "APPROVAL": 10,
}
_APPROVED_STAGES = frozenset({"APPROVAL", "PREAPPROVAL"})


def _stage_ord(stage) -> int:
    return _STAGE_ORD.get(stage or "", 0)


def _indication_efo_ids(indication: str) -> list[str]:
    """canonical OncoTree indication code -> EFO/MONDO/Orphanet ids via indication_crosswalk.yaml
    `efo_ids` lane (case-insensitive). Empty list when no lane exists for the indication."""
    path = TARGET_CONTRACTS / "vocabularies" / "indication_crosswalk.yaml"
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    ind = (indication or "").strip().upper()
    for e in doc.get("indications", []):
        if str(e.get("canonical_code", "")).upper() == ind:
            return [str(t).strip() for t in (e.get("efo_ids") or [])]
    return []


def _read_target_rows(ensembl_gene_id: str) -> list:
    """Pushdown-read the competitor rollup for one ENSG. Empty on genuine absence; re-raise env faults."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(COMPETITOR_MANIFEST)
        return pq.read_table(
            f"{bucket}/{key}", filesystem=fs.S3FileSystem(), filters=[("ensembl_gene_id", "=", ensembl_gene_id)]
        ).to_pylist()
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return []
        raise


def classify_modality(
    drug_type: Optional[str],
    all_moa_target_genes: Optional[str],
    n_moa_target_genes: Optional[int],
    action_type: Optional[str],
) -> str:
    """Infer the therapeutic MODALITY from the raw OT fields (see module docstring)."""
    dt = (drug_type or "").strip().lower()
    at = (action_type or "").upper()
    engages_effector = any(g in (all_moa_target_genes or "") for g in _EFFECTOR_ENGAGER_ENSG)
    n = int(n_moa_target_genes or 0)
    if dt == "antibody drug conjugate":
        return "ADC"
    if dt in ("antibody", "protein") and engages_effector:
        return "TCE"
    if "DEGRADER" in at:
        return "degrader"
    if dt in ("antibody", "protein"):
        return "bispecific_antibody" if n > 1 else "monoclonal_antibody"
    if dt == "small molecule":
        return "small_molecule"
    if dt == "oligonucleotide":
        return "oligonucleotide"
    if dt in ("cell", "gene"):
        return "cell_or_gene_therapy"
    if dt in ("enzyme", "oligosaccharide", "vaccine component"):
        return "other_biologic"
    return "other"


def _competitor_class(programs: list) -> str:
    if not programs:
        return "no_known_competitor"
    if any(p["is_approved"] for p in programs):
        return "approved_competitor"
    top = max(_stage_ord(p["max_clinical_stage"]) for p in programs)
    if top >= _STAGE_ORD["PHASE_1"]:  # any clinical-stage (PHASE_1..PHASE_3)
        return "active_clinical_competitor"
    return "early_or_preclinical_competitor"  # PRECLINICAL / IND / EARLY_PHASE_1 / UNKNOWN only


def aggregate_landscape(rows: list, efo_ids: list) -> dict:
    """PURE aggregator (offline-testable): OT rollup rows for ONE target -> the competitor field.

    When `efo_ids` is non-empty, rows are scoped to the indication (disease_id in efo_ids); when
    empty (no crosswalk lane), the TARGET-LEVEL field is returned (indication_scope target_level)."""
    efo_set = {str(x) for x in (efo_ids or [])}
    scope = "indication" if efo_set else "target_level"
    scoped = [r for r in rows if (not efo_set or r.get("disease_id") in efo_set)]

    # Collapse the (drug x disease) rows to one program per drug (max stage within scope).
    by_drug: dict = {}
    for r in scoped:
        did = r.get("drug_chembl_id")
        if did is None:
            continue
        modality = classify_modality(
            r.get("drug_type"), r.get("all_moa_target_genes"), r.get("n_moa_target_genes"), r.get("action_type")
        )
        p = by_drug.get(did)
        cur_ord = _stage_ord(r.get("max_clinical_stage"))
        if p is None or cur_ord > p["_ord"]:
            by_drug[did] = {
                "drug_name": r.get("drug_name"),
                "drug_chembl_id": did,
                "modality": modality,
                "drug_type": r.get("drug_type"),
                "max_clinical_stage": r.get("max_clinical_stage"),
                "is_approved": bool(r.get("is_approved")),
                "withdrawn": bool(r.get("withdrawn")),
                "mechanism_of_action": r.get("mechanism_of_action"),
                "_ord": cur_ord,
            }
        elif cur_ord == p["_ord"]:
            p["is_approved"] = p["is_approved"] or bool(r.get("is_approved"))

    programs = sorted(by_drug.values(), key=lambda p: (-p["_ord"], p["drug_name"] or ""))
    for p in programs:
        p.pop("_ord", None)

    # Per-modality landscape — the field the cross-ref keys on (modality validated vs contrarian).
    modality_landscape: dict = {}
    for p in programs:
        m = p["modality"]
        slot = modality_landscape.setdefault(
            m, {"n_programs": 0, "max_clinical_stage": None, "approved": False, "example_agents": []}
        )
        slot["n_programs"] += 1
        if _stage_ord(p["max_clinical_stage"]) > _stage_ord(slot["max_clinical_stage"]):
            slot["max_clinical_stage"] = p["max_clinical_stage"]
        slot["approved"] = slot["approved"] or p["is_approved"]
        if len(slot["example_agents"]) < 3 and p["drug_name"]:
            slot["example_agents"].append(p["drug_name"])

    approved_agents = sorted({p["drug_name"] for p in programs if p["is_approved"] and p["drug_name"]})
    withdrawn_agents = sorted({p["drug_name"] for p in programs if p["withdrawn"] and p["drug_name"]})
    # candidate failures: reached >= PHASE_2 but never approved, not currently the approved agent.
    late_non_approved = sorted(
        {
            p["drug_name"]
            for p in programs
            if not p["is_approved"] and _stage_ord(p["max_clinical_stage"]) >= _STAGE_ORD["PHASE_2"] and p["drug_name"]
        }
    )
    top_ord = max((_stage_ord(p["max_clinical_stage"]) for p in programs), default=0)
    highest_stage = next((s for s, o in sorted(_STAGE_ORD.items(), key=lambda kv: -kv[1]) if o == top_ord), None)

    return {
        "competitor_class": _competitor_class(programs),
        "indication_scope": scope,
        "n_competitor_programs": len(programs),
        "n_approved": len(approved_agents),
        "highest_clinical_stage": highest_stage,
        "approved_agents": approved_agents,
        "withdrawn_agents": withdrawn_agents,
        "late_stage_non_approved_agents": late_non_approved,
        "modality_landscape": modality_landscape,
        "modalities_in_development": sorted(modality_landscape.keys()),
        "example_programs": [
            {k: p[k] for k in ("drug_name", "modality", "max_clinical_stage", "is_approved", "mechanism_of_action")}
            for p in programs[:15]
        ],
    }


def read_competitor_landscape(
    target: str, indication: str, modality: Optional[str] = None, release_pin: Optional[str] = None
) -> dict:
    """Competitor field for a (target, indication). `modality`/`release_pin` accepted for
    dispatch-signature parity; the product is pinned to its OT release (parameters.opentargets_release)."""
    from methods.opentargets_common import symbol_to_ensembl

    base = {
        "target": target,
        "indication": indication,
        "method_version": METHOD_VERSION,
        "source": COMPETITOR_MANIFEST,
        "as_of_opentargets_release": "26.06",
    }

    ensg = symbol_to_ensembl(target)
    if not ensg:
        return {
            **base,
            "competitor_class": "insufficient",
            "highest_clinical_stage": None,
            "_note": f"{target}: could not resolve to an Ensembl gene id (OT resolver)",
        }

    rows = _read_target_rows(ensg)
    if not rows:
        return {
            **base,
            "ensembl_gene_id": ensg,
            "competitor_class": "no_known_competitor",
            "indication_scope": "target_level",
            "n_competitor_programs": 0,
            "n_approved": 0,
            "highest_clinical_stage": None,
            "approved_agents": [],
            "modality_landscape": {},
            "_note": f"{target} ({ensg}): no drug in the OT clinical-candidates rollup (virgin target or coverage gap)",
        }

    efo_ids = _indication_efo_ids(indication)
    agg = aggregate_landscape(rows, efo_ids)
    out = {**base, "ensembl_gene_id": ensg, "efo_ids": efo_ids, **agg}
    if not efo_ids:
        out["_note"] = (
            f"no efo_ids lane for indication {indication!r} in indication_crosswalk.yaml — "
            f"reporting the TARGET-LEVEL competitor field (all indications)"
        )
    return out


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Competitor drugs/programs for a (target, indication) from Open Targets.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--modality", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(read_competitor_landscape(args.target, args.indication, args.modality), indent=2, default=str))


if __name__ == "__main__":
    _main()
