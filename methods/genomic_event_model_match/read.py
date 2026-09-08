"""read_genomic_event_model_match — the patient↔model join on functional genomic event.

Joins FOUR reused sources (no new substrate, no new ingestion):
  1. alteration_role (OncoKB × IntOGen) → the driver DIRECTION, which selects the MATCH MODE.
  2. functional_gene_state PATIENT arm → the indication's tumor cohort characterizing event.
  3. functional_gene_state MODEL per-model accessor → each DepMap cell line's functional state
     (+ has_mutation).
  4. depmap_expression_dependency Chronos + lineage metadata → screen role + lineage match.

DIRECTION-AWARE matching (two modes, so both driver classes are served):
  - LoF / ambiguous / unknown → ALLELE-COUNT mode: match models on functional-state identity
    (biallelic-genetic two-hit TSG, or monoallelic). The tumor-suppressor path (TP53 works cleanly).
  - ACTIVATING driver → MUTATION-PRESENCE mode: the characterizing event is "activating mutation
    present" (the functional-state allele-count vocabulary scatters an activating hotspot across monoallelic +
    uncertain, so no allele-count state is recurrent); match models on has_mutation, recurrence from
    the patient arm's fraction_mutated. Resolves the KRAS-class gap (KRAS/COADREAD ~40% mutated).

Emits a ranked table of GENOTYPE-MATCHED models (event_match + screen_role + lineage_match) + an
event_correspondence_class rollup. Mirrors patient_model_expression_correspondence (the expression join)
one-for-one, swapping the match axis from expression-similarity to functional-genotype-identity.
data_unavailable-safe throughout.
"""

from __future__ import annotations

from typing import Optional

# indication → DepMap OncotreeLineage. SINGLE SOURCE: import the canonical map from
# depmap_chronos.read rather than forking it here. The prior local fork mapped GC/STAD →
# "Stomach", a lineage that does NOT exist in DepMap 26Q1 Model.csv (the real value is
# "Esophagus/Stomach"), so gastric within-lineage scoping silently matched zero models.
from methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE  # noqa: E402

# Chronos dependency cutoffs (DepMap convention — identical to the expression join).
DEPENDENT_CHRONOS = -0.5
NOT_DEPENDENT_CHRONOS = -0.2

# fraction of altered tumors of a given state needed for it to be the cohort's characterizing event.
_DOMINANT_EVENT_MIN_FRACTION = 0.10


def _patient_dominant_event(
    patient_arm: dict, functional_direction: Optional[str] = None
) -> tuple[Optional[str], Optional[float], str]:
    """The tumor cohort's characterizing genomic event to match + its fraction + the MATCH MODE.

    Returns (event_key, fraction, match_mode) where match_mode is:
      - "allele_count" : event_key is a functional-gene-state (biallelic-genetic / monoallelic); match models on
                         state identity. The BIALLELIC-LOSS / tumor-suppressor path (TP53 works cleanly).
      - "mutation_presence" : event_key == "activating_mutation"; match models on has_mutation. The
                         ACTIVATING-ONCOGENE path — resolves the scope gap where a recurrent activating
                         hotspot (e.g. KRAS ~40% mutated) scatters across monoallelic + uncertain and
                         clears no single allele-count floor. Selected when alteration_role's
                         functional_direction == "activating".
      - "none" : no recurrent event to match.

    DIRECTION-AWARE: functional_gene_state is intentionally an ALLELE-COUNT primitive (biallelic loss), so for
    an ACTIVATING driver we match on the biologically-correct event (mutation present) using its
    additive fraction_mutated, rather than forcing the activation into an allele-count state. LoF /
    ambiguous / unknown-direction targets keep the allele-count matching (unchanged → TP53 byte-stable)."""
    counts = (patient_arm or {}).get("state_counts")
    n = (patient_arm or {}).get("n_samples")
    if not counts or not n:
        return None, None, "none"

    # ACTIVATING driver → match on mutation presence (the oncogene event), not allele count.
    if functional_direction == "activating":
        frac_mut = (patient_arm or {}).get("fraction_mutated")
        if frac_mut is not None and frac_mut >= _DOMINANT_EVENT_MIN_FRACTION:
            return "activating_mutation", round(frac_mut, 4), "mutation_presence"
        # activating driver but not recurrently mutated here → fall through to allele-count (rarely fires)

    # DEFAULT (LoF / ambiguous / unknown) → allele-count matching. biallelic takes precedence (a
    # completed two-hit is the stronger, more specific event); then monoallelic. Fraction over ALL samples.
    for state in ("biallelic-genetic", "monoallelic"):
        frac = counts.get(state, 0) / n
        if frac >= _DOMINANT_EVENT_MIN_FRACTION:
            return state, round(frac, 4), "allele_count"
    return None, None, "none"


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


def read_genomic_event_model_match(target: str, indication: str, release_pin: str = "26q1", top_n: int = 15) -> dict:
    """Genotype-match assembler — genotype-matched DepMap models for a (target, indication). Returns the
    ranked matched-models table + rollup. data_unavailable-safe.

    Ranking: genotype-matched models first, then lineage-matched, then dependency strength (more
    dependent first). Each row carries event_match + screen_role + lineage_match."""
    from methods.depmap_expression_dependency import cli as _dep
    from methods.functional_gene_state import read_functional_gene_state, read_model_states_per_model

    sym = target.upper().strip()
    target_lineage = INDICATION_TO_DEPMAP_LINEAGE.get(indication.upper().strip())
    base = {"target": target, "indication": indication, "depmap_lineage": target_lineage, "release_pin": release_pin}

    # 0) driver DIRECTION (cheap OncoKB × IntOGen join — no big files) selects the match MODE:
    #    activating driver → match on mutation presence; else → allele-count matching. data-safe.
    functional_direction = None
    try:
        from methods.driver_role_overlay.read import read_alteration_role

        functional_direction = (read_alteration_role(sym, indication) or {}).get("functional_direction")
    except Exception as e:  # noqa: BLE001
        # Genuine absence of the driver-role product → no direction hint (default match mode). A
        # transient/creds/broken-env error must NOT be masked into a silent mode-flip — re-raise.
        from methods.target_id_sidecar import is_definitively_absent

        if not is_definitively_absent(e):
            raise
        functional_direction = None

    # 1) patient event to match (functional_gene_state patient arm), direction-aware
    fgs = read_functional_gene_state(sym, indication)
    patient_arm = fgs.get("patient") or {}
    event, event_frac, match_mode = _patient_dominant_event(patient_arm, functional_direction)
    base.update(
        {
            "patient_event_state": event,
            "patient_event_fraction": event_frac,
            "match_mode": match_mode,  # allele_count | mutation_presence | none
            "functional_direction": functional_direction,
            "patient_functional_state_class": fgs.get("functional_state_class"),
            "n_patient_samples": patient_arm.get("n_samples"),
        }
    )
    if event is None:
        base.update(
            {
                "event_correspondence_class": (
                    "no_target_event" if patient_arm.get("state_counts") else "data_unavailable"
                ),
                "matched_models": [],
                "n_models_considered": 0,
                "n_event_matched": 0,
                "n_matched_dependent": 0,
                "_data_note": (
                    "tumors rarely altered — no recurrent genotype to match"
                    if patient_arm.get("state_counts")
                    else "no patient functional-state distribution"
                ),
            }
        )
        return base

    # 2) per-model genotypes (functional_gene_state model accessor)
    per_model = read_model_states_per_model(sym)
    if not per_model:
        base.update(
            {
                "event_correspondence_class": "data_unavailable",
                "matched_models": [],
                "n_models_considered": 0,
                "n_event_matched": 0,
                "n_matched_dependent": 0,
                "_data_note": "target absent from DepMap model substrate",
            }
        )
        return base

    # 3) Chronos + lineage metadata (reuse the expression-join loader)
    try:
        chronos_by_model, _tpm, meta, errs = _dep.load_depmap_files_for_card4(
            release_pin=release_pin, target_symbol=sym
        )
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
        # event_match depends on the match MODE: mutation_presence (activating oncogene) matches any
        # mutated model; allele_count (LoF/default) matches strict state identity on the dominant event.
        if match_mode == "mutation_presence":
            event_match = bool(mstate.get("has_mutation"))
        else:
            event_match = state == event
        rows.append(
            {
                "model_id": model_id,
                "cell_line": mm.get("StrippedCellLineName") or mm.get("CellLineName") or model_id,
                "lineage": lineage,
                "lineage_match": bool(target_lineage) and (lineage == target_lineage),
                "model_state": state,
                "event_match": event_match,
                "cn_class": mstate.get("cn_class"),
                "chronos": (round(float(chronos), 4) if chronos is not None else None),
                "screen_role": _screen_role(chronos),
            }
        )

    # rank: event-matched first, then lineage-matched, then dependency strength (more negative first)
    rows.sort(
        key=lambda r: (not r["event_match"], not r["lineage_match"], r["chronos"] if r["chronos"] is not None else 0.0)
    )

    matched = [r for r in rows if r["event_match"]]
    matched_dependent = [r for r in matched if r["screen_role"] == "positive_model"]
    matched_dep_lineage = [r for r in matched_dependent if r["lineage_match"]]
    base.update(
        {
            "matched_models": [r for r in rows if r["event_match"]][:top_n],
            "n_models_considered": len(rows),
            "n_event_matched": len(matched),
            "n_event_matched_in_lineage": sum(1 for r in matched if r["lineage_match"]),
            "n_matched_dependent": len(matched_dependent),
            "n_matched_dependent_in_lineage": len(matched_dep_lineage),
            "event_correspondence_class": _classify_event_correspondence(
                len(matched), len(matched_dependent), len(matched_dep_lineage), bool(target_lineage)
            ),
            "dependency_available": not bool(errs),
        }
    )
    return base


def _classify_event_correspondence(n_matched, n_matched_dependent, n_matched_dep_lineage, has_lineage) -> str:
    """Categorical for the card/rules (mirrors the expression join's _classify_correspondence, on
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
