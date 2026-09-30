"""aact_clinical_precedent.read — clinical-trial precedent for a (target, indication) from AACT.

Answers the clinical-precedent card's question: "for {target} in {indication}, what is the highest
clinical stage reached by a drug that ENGAGES the target, how many active trials, which approved
agents, and what notable failures (terminated trials)?" — the framework's translational-maturity
lens, orthogonal to the biology axes.

## Composition (three catalogued products, joined here)

  1. indication_crosswalk.yaml (target-contracts) : canonical indication -> mesh_terms
     (ClinicalTrials.gov browse_conditions.downcase_mesh_term).
  2. dgidb-drug-target-directional-v1 : target gene -> set of drug names with a DIRECTIONAL
     interaction on it (drops biomarker/pathway noise; VALIDATED 2026-08-21). This is the
     "does a drug ENGAGE the target" filter — precedent semantics, NOT sole-target.
  3. aact-oncology-trial-precedent-per-condition-intervention-v1 : per (mesh condition x drug)
     trial rollup (highest_phase, n_active, n_terminated, ...).

  target -> (2) -> drug set;  indication -> (1) -> mesh_terms;
  filter (3) to (condition in mesh_terms) AND (drug in drug_set) -> aggregate.

## Honest coverage

- A target with no DIRECTIONAL DGIdb drug -> no_known_agent (coverage gap, not "never trialed").
- An indication without a mesh_terms lane -> insufficient (crosswalk gap).
- resistance_mechanisms_reported is NOT derivable from AACT structured fields -> always None here
  (documented gap; would need trial-results / literature mining).
- highest_clinical_stage reflects trials of ANY target-engaging drug in the indication — a
  multi-target drug (imatinib) legitimately contributes precedent for each target it engages.

data_unavailable-safe. Absence = coverage gap (measured-vs-null discipline).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from onc_methods.roots import contracts_root

DRUG_TARGET_MANIFEST = "dgidb-drug-target-directional-v1"
AACT_MANIFEST = "aact-oncology-trial-precedent-per-condition-intervention-v1"
METHOD_VERSION = "0.1.0"

# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
TARGET_CONTRACTS = Path(contracts_root())

# AACT phase string -> ordinal (for highest-stage), and ordinal -> clinical-stage class.
_PHASE_ORD = {
    "EARLY_PHASE1": 1,
    "PHASE1": 2,
    "PHASE1/PHASE2": 3,
    "PHASE2": 4,
    "PHASE2/PHASE3": 5,
    "PHASE3": 6,
    "PHASE4": 7,
}


def _indication_mesh_terms(indication: str) -> list[str]:
    """canonical indication code -> mesh_terms via indication_crosswalk.yaml (case-insensitive)."""
    path = TARGET_CONTRACTS / "vocabularies" / "indication_crosswalk.yaml"
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    ind = (indication or "").strip().upper()
    for e in doc.get("indications", []):
        if str(e.get("canonical_code", "")).upper() == ind:
            return [str(t).strip().lower() for t in (e.get("mesh_terms") or [])]
    return []


def _read_rows(manifest_id: str, filters):
    """Pushdown-read a catalogued parquet. None on genuine absence; re-raise transient/env faults."""
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from onc_methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(manifest_id)
        return pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(), filters=filters).to_pylist()
    except Exception as e:  # noqa: BLE001
        from onc_methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return []
        raise


def _target_drug_set(target: str) -> tuple[set, set]:
    """(all directional drug names, approved subset) engaging `target` — from the DGIdb directional map."""
    rows = _read_rows(DRUG_TARGET_MANIFEST, [("gene_symbol", "=", (target or "").strip().upper())])
    drugs = {r["drug_name_norm"] for r in rows if r.get("drug_name_norm")}
    approved = {r["drug_name_norm"] for r in rows if r.get("is_approved")}
    return drugs, approved


def _highest_stage(max_ord: int, approved_hit: bool) -> str:
    if approved_hit:
        return "approved"
    if max_ord >= 6:  # PHASE3 / PHASE4
        return "phase_3"
    if max_ord >= 4:  # PHASE2 / PHASE2/PHASE3
        return "phase_2"
    if max_ord >= 1:  # EARLY_PHASE1 .. PHASE1/PHASE2
        return "phase_1"
    return "none"


def aggregate_precedent(aact_rows: list, drug_set: set, approved_drugs: set) -> dict:
    """PURE aggregator (offline-testable): AACT (condition x drug) rows already filtered to the
    indication's mesh_terms, intersected here with the target's engaging-drug set, -> precedent."""
    matched = [r for r in aact_rows if r.get("intervention_name_norm") in drug_set]
    if not matched:
        return {
            "clinical_precedent_class": "no_trial_precedent",
            "highest_clinical_stage": "none",
            "n_trials": 0,
            "n_active_trials": 0,
            "approved_agents": [],
            "notable_failures": [],
            "n_agents_engaging_target": 0,
            "modality_precedent": None,
            "resistance_mechanisms_reported": None,
            "example_nct_ids": [],
        }
    max_ord = max(_PHASE_ORD.get(r.get("highest_phase"), 0) for r in matched)
    approved_hit = any(r["intervention_name_norm"] in approved_drugs for r in matched)
    n_active = sum(int(r.get("n_active") or 0) for r in matched)
    agents = sorted({r["intervention_name_norm"] for r in matched})
    approved_agents = sorted(
        {r["intervention_name_norm"] for r in matched if r["intervention_name_norm"] in approved_drugs}
    )
    failures = sorted({r["intervention_name_norm"] for r in matched if int(r.get("n_terminated") or 0) > 0})
    types = {}
    for r in matched:
        t = r.get("intervention_type")
        if t:
            types[t] = types.get(t, 0) + 1
    ncts = []
    for r in sorted(matched, key=lambda r: -int(r.get("n_trials") or 0)):
        for x in (r.get("example_nct_ids") or "").split("|"):
            if x and x not in ncts:
                ncts.append(x)
        if len(ncts) >= 8:
            break
    stage = _highest_stage(max_ord, approved_hit)
    return {
        "clinical_precedent_class": "trial_precedent_present",
        "highest_clinical_stage": stage,
        "n_trials": sum(int(r.get("n_trials") or 0) for r in matched),
        "n_active_trials": n_active,
        "approved_agents": approved_agents,
        "notable_failures": failures[:15],
        "n_agents_engaging_target": len(agents),
        "modality_precedent": "|".join(f"{k}:{v}" for k, v in sorted(types.items())) or None,
        "resistance_mechanisms_reported": None,  # not derivable from AACT structured fields
        "example_nct_ids": ncts,
    }


def read_clinical_precedent(
    target: str, indication: str, modality: Optional[str] = None, release_pin: Optional[str] = None
) -> dict:
    base = {
        "target": target,
        "indication": indication,
        "method_version": METHOD_VERSION,
        "source": "aact-oncology-trial-precedent-per-condition-intervention-v1 x dgidb-drug-target-directional-v1",
    }
    mesh_terms = _indication_mesh_terms(indication)
    if not mesh_terms:
        return {
            **base,
            "clinical_precedent_class": "insufficient",
            "highest_clinical_stage": "none",
            "_note": f"no mesh_terms lane for indication {indication!r} in indication_crosswalk.yaml",
        }
    drug_set, approved = _target_drug_set(target)
    if not drug_set:
        return {
            **base,
            "clinical_precedent_class": "no_known_agent",
            "highest_clinical_stage": "none",
            "n_trials": 0,
            "approved_agents": [],
            "notable_failures": [],
            "_note": f"{target}: no drug with a DIRECTIONAL DGIdb interaction (coverage gap, not 'undruggable')",
        }
    aact_rows = _read_rows(AACT_MANIFEST, [("condition_mesh_term", "in", mesh_terms)])
    return {**base, "mesh_terms": mesh_terms, **aggregate_precedent(aact_rows, drug_set, approved)}


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Clinical-trial precedent for a (target, indication) from AACT.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--modality", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(read_clinical_precedent(args.target, args.indication, args.modality), indent=2, default=str))


if __name__ == "__main__":
    _main()
