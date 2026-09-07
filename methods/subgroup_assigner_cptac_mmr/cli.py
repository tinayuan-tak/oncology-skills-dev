"""CPTAC MMR-IHC -> MSI_H/MSS subgroup-assignment shard builder.

Output (tall, canonical subgroup-assignment row schema; matches subgroup_assigner_directly_tagged):
    sample_id, patient_id, source_native_id, stratum_id, is_member, derivation_source, derivation_value

  sample_id        = aliquot_submitter_id (joins the CPTAC protein per-sample product)
  patient_id       = source_native_id = case_submitter_id (== CPTAC Participant/Patient_ID)
  stratum_id       in {MSI_H, MSS}
  is_member        True / False / None  (None = MMR status could not be determined — tri-value)
  derivation_source= "cptac_clinical_mmr_ihc"
  derivation_value = e.g. "dMMR:MLH1,PMS2" (member) / "pMMR" / "" (non-member / unknown)

Usage:
    python -m methods.subgroup_assigner_cptac_mmr.cli --indication COADREAD --out <dir>
(main() does the live I/O — XLSX + PDC bridge + per-sample aliquots; not exercised by unit tests.)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

DERIVATION_SOURCE = "cptac_clinical_mmr_ihc"
ASSIGNER_METHOD = "subgroup_assigner_cptac_mmr"
ASSIGNER_METHOD_VERSION = "0.1.0"

# The four MMR proteins whose IHC loss defines dMMR (MSI-H). Column names as they appear on the
# CPTAC Colon clinical CRF Baseline row.
MMR_PROTEINS = ("MLH1", "MSH2", "PMS2", "MSH6")
_STRATA = ("MSI_H", "MSS")


# ── PURE: classification ──────────────────────────────────────────────────────────────────────


def _norm(v) -> str:
    return str(v).strip().lower() if v is not None else ""


def classify_msi_from_mmr(mmr_calls: dict) -> tuple[Optional[str], list[str]]:
    """Classify a patient's MSI status from their four MMR-IHC calls. PURE.

    Args:
      mmr_calls: {protein: raw_value} for MLH1/MSH2/PMS2/MSH6, values like
                 "MLH1-expressed" / "MLH1-not expressed" / "MLH1-not tested" / "" / None.

    Returns (status, lost_proteins):
      status = "MSI_H"  — >=1 MMR protein is NOT EXPRESSED (dMMR)
             = "MSS"    — >=1 protein tested AND all tested proteins EXPRESSED (pMMR)
             = None     — no protein has an informative (expressed/not-expressed) call
                          (all not-tested / missing) -> MSI status undetermined
      lost_proteins = the proteins called not-expressed (for the derivation_value trail).

    A single unambiguous loss dominates (dMMR), matching clinical MMR-IHC interpretation. "not
    tested"/blank contribute no information; if NONE are informative the patient is undetermined
    (-> is_member null downstream), never silently MSS."""
    lost, informative = [], 0
    for p in MMR_PROTEINS:
        val = _norm(mmr_calls.get(p))
        if not val or "not tested" in val or "unknown" in val:
            continue
        if "not expressed" in val or "loss" in val:
            informative += 1
            lost.append(p)
        elif "expressed" in val or "intact" in val or "retained" in val:
            informative += 1
    if lost:
        return "MSI_H", lost
    if informative:
        return "MSS", []
    return None, []


def _member_rows(sample_id: str, patient_id: str, status: Optional[str], lost: list[str]) -> list[dict]:
    """Emit one tall row per stratum for a single aliquot, tri-value is_member.

    status None -> is_member None for BOTH strata (undetermined, carries no weight downstream).
    status set -> True for the matching stratum, False for the other (a real evaluated negative)."""
    dval = ("dMMR:" + ",".join(lost)) if status == "MSI_H" else ("pMMR" if status == "MSS" else "")
    rows = []
    for stratum in _STRATA:
        if status is None:
            is_member = None
        else:
            is_member = stratum == status
        rows.append(
            {
                "sample_id": sample_id,
                "patient_id": patient_id,
                "source_native_id": patient_id,
                "stratum_id": stratum,
                "is_member": is_member,
                "derivation_source": DERIVATION_SOURCE,
                "derivation_value": dval if is_member is True else "",
            }
        )
    return rows


# ── PURE: assignment assembly ─────────────────────────────────────────────────────────────────


def build_assignments(aliquots: pd.DataFrame, bridge: pd.DataFrame, clinical: pd.DataFrame) -> pd.DataFrame:
    """Assemble the tall MSI assignment shard. PURE (no I/O).

    Args:
      aliquots: DataFrame with column `aliquot_submitter_id` (the CPTAC protein per-sample product's
                distinct tumor aliquots for the indication). Optional `condition`/`sample_type`.
      bridge:   DataFrame mapping `aliquot_submitter_id` -> `case_submitter_id`.
      clinical: DataFrame with `case_submitter_id` (== Participant ID) + the four MMR_PROTEINS
                columns (one informative row per patient; caller de-dups CRF rows).

    Returns the tall assignment DataFrame (canonical row schema). An aliquot that does not join a
    case, or a case absent from `clinical`, yields status None (is_member null) — never dropped, so
    coverage is honest and total aliquot count is preserved."""
    a2c = dict(zip(bridge["aliquot_submitter_id"], bridge["case_submitter_id"]))
    clin = clinical.drop_duplicates(subset=["case_submitter_id"], keep="last").set_index("case_submitter_id")
    rows: list[dict] = []
    for aliquot in aliquots["aliquot_submitter_id"].dropna().unique().tolist():
        case = a2c.get(aliquot)
        status, lost = None, []
        if case is not None and case in clin.index:
            crec = clin.loc[case]
            status, lost = classify_msi_from_mmr({p: crec.get(p) for p in MMR_PROTEINS})
        rows.extend(_member_rows(aliquot, case if case is not None else "", status, lost))
    cols = [
        "sample_id",
        "patient_id",
        "source_native_id",
        "stratum_id",
        "is_member",
        "derivation_source",
        "derivation_value",
    ]
    return pd.DataFrame(rows, columns=cols)


def strata_summary(assignments: pd.DataFrame) -> dict:
    """Per-stratum member/non-member/undetermined counts — for the manifest + a build-time sanity log."""
    out: dict = {}
    for stratum in _STRATA:
        sub = assignments[assignments["stratum_id"] == stratum]
        out[stratum] = {
            "n_member": int((sub["is_member"] == True).sum()),  # noqa: E712
            "n_non_member": int((sub["is_member"] == False).sum()),  # noqa: E712
            "n_undetermined": int(sub["is_member"].isna().sum()),
        }
    return out


# ── I/O + main (live; not unit-tested) ─────────────────────────────────────────────────────────


def _load_clinical_xlsx(path: str) -> pd.DataFrame:  # pragma: no cover - thin I/O
    """Parse the CPTAC Colon clinical CRF: keep the informative (Baseline) row per Participant ID,
    project case_submitter_id + the four MMR columns. Heterogeneous per-study schema — kept thin +
    isolated so the pure logic above is fully testable without the real XLSX."""
    raw = pd.read_excel(path)
    ren = {"Participant ID": "case_submitter_id"}
    df = raw.rename(columns={k: v for k, v in ren.items() if k in raw.columns})
    keep = ["case_submitter_id"] + [p for p in MMR_PROTEINS if p in df.columns]
    df = df[[c for c in keep if c in df.columns]].dropna(subset=["case_submitter_id"])
    return df


def main(argv=None) -> int:  # pragma: no cover - live I/O orchestration
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--indication", required=True, help="AACR OncoTree code (COADREAD today)")
    ap.add_argument("--clinical-xlsx", required=True, help="Path/URI to the CPTAC clinical CRF XLSX")
    ap.add_argument(
        "--aliquots-parquet", required=True, help="cptac-protein-tumor-vs-normal-per-sample product (tumor aliquots)"
    )
    ap.add_argument(
        "--bridge-parquet",
        required=True,
        help="aliquot_submitter_id -> case_submitter_id (stage-00 annotations / PDC re-pull)",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    aliquots = pd.read_parquet(args.aliquots_parquet)
    aliquots = (
        aliquots[aliquots.get("condition", "Tumor").astype(str).str.contains("Tumor|Primary", case=False, na=False)]
        if "condition" in aliquots.columns
        else aliquots
    )
    bridge = pd.read_parquet(args.bridge_parquet)
    clinical = _load_clinical_xlsx(args.clinical_xlsx)

    assignments = build_assignments(aliquots[["aliquot_submitter_id"]], bridge, clinical)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    assignments.to_parquet(out / "assignments.parquet", index=False)
    summary = strata_summary(assignments)
    print(f"[{ASSIGNER_METHOD} v{ASSIGNER_METHOD_VERSION}] {args.indication}: {summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
