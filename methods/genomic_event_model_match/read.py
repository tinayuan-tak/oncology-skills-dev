"""read_genomic_event_model_match — the canonical P3 patient↔model join on functional genomic event.

Joins THREE reused sources (no new substrate):
  1. functional_gene_state PATIENT arm → the indication's tumor cohort dominant functional event
     (the genotype to match: biallelic-genetic for a two-hit TSG, monoallelic for a single-hit
     activating oncogene, wt when tumors are rarely altered).
  2. functional_gene_state MODEL per-model accessor → each DepMap cell line's functional state.
  3. depmap_expression_dependency Chronos + lineage metadata → screen role + lineage match.

Emits a ranked table of GENOTYPE-MATCHED models (event_match + screen_role + lineage_match) + an
event_correspondence_class rollup. Mirrors patient_model_expression_correspondence (expression-Q4)
one-for-one, swapping the match axis from expression-similarity to functional-genotype-identity.
data_unavailable-safe throughout.
"""
from __future__ import annotations

from typing import Optional

# indication → DepMap OncotreeLineage (SAME map as expression-Q4 / depmap_expression_dependency).
INDICATION_TO_DEPMAP_LINEAGE = {
    "COADREAD": "Bowel", "COAD": "Bowel", "READ": "Bowel",
    "PDAC": "Pancreas", "PAAD": "Pancreas", "NSCLC": "Lung", "LUAD": "Lung", "LUSC": "Lung",
    "SCLC": "Lung", "GC": "Stomach", "STAD": "Stomach", "BRCA": "Breast", "SKCM": "Skin",
    "PRAD": "Prostate", "OV": "Ovary/Fallopian Tube", "KIRC": "Kidney", "HNSC": "Head and Neck",
    "BLCA": "Bladder/Urinary Tract", "LIHC": "Liver", "ESCA": "Esophagus/Stomach",
}

# Chronos dependency cutoffs (DepMap convention — identical to expression-Q4).
DEPENDENT_CHRONOS = -0.5
NOT_DEPENDENT_CHRONOS = -0.2

# fraction of altered tumors of a given state needed for it to be the cohort's characterizing event.
_DOMINANT_EVENT_MIN_FRACTION = 0.10


def _patient_dominant_event(patient_arm: dict) -> tuple[Optional[str], Optional[float]]:
    """The tumor cohort's characterizing functional event + its fraction, from the M6 patient arm.

    The event to match is the dominant ALTERED state: biallelic-genetic if it is recurrent (≥ the
    min fraction), else monoallelic if recurrent, else None (tumors rarely altered → no genotype to
    match, an honest 'no target event' rather than forcing a match to wild-type). Returns
    (event_state, fraction) or (None, None).

    SCOPE BOUNDARY (documented, Phase-1): M11 matches on M6's ALLELE-COUNT states, so it is tuned to
    the BIALLELIC-LOSS / tumor-suppressor case (TP53/COADREAD works cleanly). It UNDER-CALLS
    activating-HOTSPOT oncogenes: e.g. KRAS/COADREAD is ~40% mutated (all G12/G13 activating), but M6
    scatters that across monoallelic (~7%) + uncertain (~33%, copy-neutral-no-confirmable-LOH), so
    neither allele-count state clears the recurrence floor → no_target_event. That is HONEST ('no
    recurrent allele-count event'), NOT a claim the target is unaltered — the activating-oncogene
    story is told by the sibling genomic cards (mutation-hotspot-frequency + alteration-role, which
    calls KRAS direct_driver_gof), not by this allele-count join. A future refinement could let a
    recurrent activating hotspot define a monoallelic-activating event even when LOH is uncertain."""
    counts = (patient_arm or {}).get("state_counts")
    n = (patient_arm or {}).get("n_samples")
    if not counts or not n:
        return None, None
    # biallelic takes precedence (a completed two-hit is the stronger, more specific event); then
    # monoallelic (single-hit activating). fraction over ALL samples (matches the headline framing).
    for state in ("biallelic-genetic", "monoallelic"):
        frac = counts.get(state, 0) / n
        if frac >= _DOMINANT_EVENT_MIN_FRACTION:
            return state, round(frac, 4)
    return None, None


def _screen_role(chronos: Optional[float]) -> str:
    """Screen role from Chronos dependency (genotype-match framing):
      positive_model   — DEPENDENT (Chronos <= -0.5): the on-target, genotype-matched screen line
      resistance_model — NOT dependent (Chronos >= -0.2): matched genotype yet resistant
      indeterminate    — intermediate dependency, or Chronos missing"""
    if chronos is None:
        return "indeterminate"
    if chronos <= DEPENDENT_CHRONOS:
        return "positive_model"
    if chronos >= NOT_DEPENDENT_CHRONOS:
        return "resistance_model"
    return "indeterminate"


def read_genomic_event_model_match(target: str, indication: str, release_pin: str = "26q1",
                                   top_n: int = 15) -> dict:
    """M11 assembler — genotype-matched DepMap models for a (target, indication). Returns the
    ranked matched-models table + rollup. data_unavailable-safe.

    Ranking: genotype-matched models first, then lineage-matched, then dependency strength (more
    dependent first). Each row carries event_match + screen_role + lineage_match."""
    from methods.functional_gene_state import read_functional_gene_state, read_model_states_per_model
    from methods.depmap_expression_dependency import cli as _dep

    sym = target.upper().strip()
    target_lineage = INDICATION_TO_DEPMAP_LINEAGE.get(indication.upper().strip())
    base = {"target": target, "indication": indication, "depmap_lineage": target_lineage,
            "release_pin": release_pin}

    # 1) patient event to match (M6 patient arm)
    fgs = read_functional_gene_state(sym, indication)
    patient_arm = fgs.get("patient") or {}
    event, event_frac = _patient_dominant_event(patient_arm)
    base.update({
        "patient_event_state": event,
        "patient_event_fraction": event_frac,
        "patient_functional_state_class": fgs.get("functional_state_class"),
        "n_patient_samples": patient_arm.get("n_samples"),
    })
    if event is None:
        base.update({"event_correspondence_class": ("no_target_event"
                     if patient_arm.get("state_counts") else "data_unavailable"),
                     "matched_models": [], "n_models_considered": 0,
                     "n_event_matched": 0, "n_matched_dependent": 0,
                     "_data_note": ("tumors rarely altered — no recurrent genotype to match"
                                    if patient_arm.get("state_counts")
                                    else "no patient functional-state distribution")})
        return base

    # 2) per-model genotypes (M6 model accessor)
    per_model = read_model_states_per_model(sym)
    if not per_model:
        base.update({"event_correspondence_class": "data_unavailable", "matched_models": [],
                     "n_models_considered": 0, "n_event_matched": 0, "n_matched_dependent": 0,
                     "_data_note": "target absent from DepMap model substrate"})
        return base

    # 3) Chronos + lineage metadata (reuse the expression-Q4 loader)
    try:
        chronos_by_model, _tpm, meta, errs = _dep.load_depmap_files_for_card4(
            release_pin=release_pin, target_symbol=sym)
    except Exception as e:  # noqa: BLE001
        chronos_by_model, meta, errs = {}, {}, [{"_live_read_error": type(e).__name__}]
    if errs:
        # dependency unavailable → still report genotype match, but screen roles are indeterminate.
        chronos_by_model = chronos_by_model or {}

    rows = []
    for model_id, mstate in per_model.items():
        mm = meta.get(model_id, {})
        lineage = str(mm.get("OncotreeLineage") or mm.get("lineage") or "unknown")
        chronos = chronos_by_model.get(model_id)
        state = mstate["state"]
        rows.append({
            "model_id": model_id,
            "cell_line": mm.get("StrippedCellLineName") or mm.get("CellLineName") or model_id,
            "lineage": lineage,
            "lineage_match": bool(target_lineage) and (lineage == target_lineage),
            "model_state": state,
            "event_match": state == event,             # strict genotype identity on the dominant event
            "cn_class": mstate.get("cn_class"),
            "chronos": (round(float(chronos), 4) if chronos is not None else None),
            "screen_role": _screen_role(chronos),
        })

    # rank: event-matched first, then lineage-matched, then dependency strength (more negative first)
    rows.sort(key=lambda r: (not r["event_match"], not r["lineage_match"],
                             r["chronos"] if r["chronos"] is not None else 0.0))

    matched = [r for r in rows if r["event_match"]]
    matched_dependent = [r for r in matched if r["screen_role"] == "positive_model"]
    matched_dep_lineage = [r for r in matched_dependent if r["lineage_match"]]
    base.update({
        "matched_models": [r for r in rows if r["event_match"]][:top_n],
        "n_models_considered": len(rows),
        "n_event_matched": len(matched),
        "n_event_matched_in_lineage": sum(1 for r in matched if r["lineage_match"]),
        "n_matched_dependent": len(matched_dependent),
        "n_matched_dependent_in_lineage": len(matched_dep_lineage),
        "event_correspondence_class": _classify_event_correspondence(
            len(matched), len(matched_dependent), len(matched_dep_lineage), bool(target_lineage)),
        "dependency_available": not bool(errs),
    })
    return base


def _classify_event_correspondence(n_matched, n_matched_dependent, n_matched_dep_lineage,
                                   has_lineage) -> str:
    """Categorical for the card/rules (mirrors expression-Q4's _classify_correspondence, on
    genotype-match + dependency):
      event_matched_dependent_in_lineage  — ≥1 genotype-matched + DEPENDENT model IN the lineage
      event_matched_dependent_off_lineage — matched+dependent models exist, none in the lineage
      event_matched_not_dependent         — genotype-matched models exist but none are dependent
      no_event_match                       — no model carries the tumor's functional event
      data_unavailable                     — handled by the caller."""
    if n_matched == 0:
        return "no_event_match"
    if n_matched_dependent == 0:
        return "event_matched_not_dependent"
    if has_lineage and n_matched_dep_lineage >= 1:
        return "event_matched_dependent_in_lineage"
    return "event_matched_dependent_off_lineage"
