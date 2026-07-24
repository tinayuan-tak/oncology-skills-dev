#!/usr/bin/env python3
"""on-target-safety-liability — Phase-G partial skill (graduated 2026-07-08).

Germline LoF-constraint safety signal from gnomAD.

W4c refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common.resolver import resolve_verdict_for_gate


SKILL_NAME = "on-target-safety-liability"
SKILL_VERSION = "1.6.0"   # 1.4.0: + P5 human-genetics leg — target-safety-prioritisation (Slice 1,
                          # OT context) + gene-burden-safety (Slice 2, OT rare-variant burden LoF-
                          # tolerance; verdict-moving rule resolver-wired in Slice 5).
                          # 1.3.0: + alteration-role for mutant-selective mechanism-conditioning of
                          # the WT gnomAD-constraint concern (activating-driver-role-safety-context)

CARDS = [
    "gnomad-lof-constraint",
    "target-safety-prioritisation",   # P5 Slice 1 (2026-07-24) — OT 26.06 engineered target-priority
                                      # scores as safety-orienting CONTEXT (safety-event / genetic-
                                      # constraint / mouse-KO bands). VERDICT-INERT: no warning, no
                                      # resolver reference — it orients the reader alongside the
                                      # authoritative gnomAD constraint call; the verdict-moving human-
                                      # genetics signals arrive in P5 Slices 2-4 (gene_burden/clingen/
                                      # mouse_phenotype). Spine byte-stable.
    "normal-tissue-liability-gtex",   # Q3 — GTEx normal-tissue atlas (critical-organ liability +
                                      # breadth). Its normal-liability-* rules emit SM/degrader
                                      # opposing on critical_organ_liability (on-target-off-tumor for
                                      # full-KO modalities); supportive on restricted_normal. Additive
                                      # signal — the safety RESOLVER stays keyed to gnomAD (byte-stable).
    "alteration-role",                # 2026-07-23 — mechanism CONTEXT for mutant-selective conditioning.
                                      # Its activating-driver-role-safety-context rule (intracellular axis)
                                      # fires on functional_direction==activating; the safety RESOLVER
                                      # combines it with highly-constrained-safety-warning (when_all_fired)
                                      # to DOWNGRADE the WT-constraint concern → wt_constraint_mechanism_
                                      # mismatch (a GoF driver is drugged mutant-selectively; gnomAD
                                      # constraint is about the WILD-TYPE protein the drug spares).
    "mouse-ko-phenotype",             # P5 Slice 4 (2026-07-24) — mouse-KO normal-physiology safety.
                                      # lethal_ko (adult/postnatal) -> mouse-ko-lethal-safety-warning
                                      # (SM/degrader opposing, INFERRED-tier caution); developmental_
                                      # only -> neutral (the guardrail). Resolver-wired in Slice 5.
    "clingen-dosage",                 # P5 Slice 3 (2026-07-24) — ClinGen dosage sensitivity. dosage_
                                      # sensitivity_class=autosomal_dominant_loss -> clingen-dominant-
                                      # loss-safety-warning (SM/degrader opposing, haploinsufficiency
                                      # full-KO concern). Verdict-moving rule resolver-wired in Slice 5.
    "gene-burden-safety",             # P5 Slice 2 (2026-07-24) — population rare-variant BURDEN LoF-
                                      # tolerance (OT 26.06). burden_safety_class=lof_risk_phenotype ->
                                      # gene-burden-lof-safety-warning (SM/degrader opposing, the full-KO
                                      # WT-loss safety signal); protective -> drug-positive. The
                                      # verdict-moving rule is NOT yet resolver-referenced (byte-stable);
                                      # safety.resolver.yaml wires it in P5 Slice 5, composed with the
                                      # same mutant-selective downgrade as the gnomAD path.
]

QUESTION = ("Is {target} highly constrained against loss-of-function "
            "variants in the gnomAD population, and what does this imply "
            "for on-target safety of full-KO modalities (degrader, RNA "
            "therapeutic, full-inhibition SM) in {indication}?")

PARTIAL_STATUS_NOTE = (
    "on-target-safety-liability is status: partial; this skill reflects only the "
    "gnomAD GERMLINE constraint signal (modality-agnostic / SM-relevant). The "
    "normal-tissue-liability HPA-IHC signal (biologics on-target-off-tumor safety) "
    "is now WIRED, but on the surface_intrinsic axis — it is consumed by the "
    "surface-modality-fit skill (adc/bite_tce/antibody channels), not here. "
    "protein-surface-evidence card remains unwired."
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (gap #5, 2026-07-20).
    The former if-chain now lives in resolvers/safety.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    result = resolve_verdict_for_gate(fired, "safety")
    if result is None:
        raise RuntimeError(
            "safety resolver spec missing (target-contracts/resolvers/safety.resolver.yaml) "
            "— the verdict source of truth is absent.")
    return result

def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    # Mechanism-conditioning context: when the verdict is the mutant-selective downgrade, surface WHY
    # (the activating driver role) + the conditionality caveat so a consumer isn't left guessing.
    functional_direction = _get("alteration-role", "functional_direction")
    is_mismatch = (v == "wt_constraint_mechanism_mismatch")
    return {
        "safety_verdict":   v,
        "driving_rule_id":  drv,
        "constraint_class": _get("gnomad-lof-constraint", "constraint_class"),
        "pli_score":        _get("gnomad-lof-constraint", "pli_score"),
        "loeuf_score":      _get("gnomad-lof-constraint", "loeuf_score"),
        "mis_z_score":      _get("gnomad-lof-constraint", "mis_z_score"),
        "syn_z_score":      _get("gnomad-lof-constraint", "syn_z_score"),
        "obs_lof_count":    _get("gnomad-lof-constraint", "obs_lof_count"),
        "exp_lof_count":    _get("gnomad-lof-constraint", "exp_lof_count"),
        # P5 Slice 2 — human-genetics rare-variant burden (verdict-moving in Slice 5)
        "burden_safety_class": _get("gene-burden-safety", "burden_safety_class"),
        "burden_min_pvalue":   _get("gene-burden-safety", "min_pvalue"),
        "burden_top_disease":  _get("gene-burden-safety", "top_disease"),
        # P5 Slice 3 — ClinGen dosage sensitivity (verdict-moving in Slice 5)
        "dosage_sensitivity_class": _get("clingen-dosage", "dosage_sensitivity_class"),
        "dosage_top_disease":       _get("clingen-dosage", "top_disease"),
        # P5 Slice 4 — mouse-KO normal-physiology (verdict-moving in Slice 5)
        "mouse_ko_phenotype_class": _get("mouse-ko-phenotype", "ko_phenotype_class"),
        "mouse_ko_top_lethal":      _get("mouse-ko-phenotype", "top_lethal_label"),
        # mutant-selective conditioning (2026-07-23)
        "alteration_functional_direction": functional_direction,
        "mechanism_conditioning_note": (
            "gnomAD constraint reflects WILD-TYPE LoF-intolerance; this target is an ACTIVATING (GoF) "
            "driver typically drugged MUTANT-SELECTIVELY, so the WT-constraint safety concern is "
            "largely nullified (the therapy spares WT protein in normal tissue). CONDITIONAL on an "
            "allele-selective modality — a pan-target degrader / WT-hitting inhibitor re-exposes it."
        ) if is_mismatch else None,
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        partial_status_note=PARTIAL_STATUS_NOTE,
    ))
