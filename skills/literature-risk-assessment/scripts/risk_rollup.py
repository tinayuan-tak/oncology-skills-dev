#!/usr/bin/env python3
"""risk_rollup — PROJECTION [3A]: the 6-dim risk roll-up (grounded-substrate two-projection design).

A sibling projection to the cross-evidence hypothesis. Each risk dimension =
  bin:      DETERMINISTIC, a pure function of the evidence-package sub_verdicts — a modality-CONDITIONED
            worst-case CONJUNCTION over the relevant axes. Reproducible + cross-target comparable; the
            LLM/literature NEVER sets the bin. (Safety is on-target-safety ∧ surface-normal-antigen ∧
            tumor-selectivity-normal-breadth — validated to catch the FOLR1 ADC safety false-LOW that a
            1:1 on-target-only mapping misses.)
  findings: GROUNDED escalate-only findings from ground_axis substrate blocks (PMID-traceable). Findings
            can only RAISE a flag; they NEVER change the deterministic bin (escalate-only).
  discordance: per-dim engine↔literature flag (from the grounded block's contradicts_deterministic).
  blind_spots: what the engine bin does not cover (→ the grounded findings / Tier-2 fill these).

THRESHOLDS ARE ILLUSTRATIVE (v0). The CONTRACT is the contribution: modality-conditioned conjunction +
escalate-only fusion + declared blind-spots + reproducible bin. Thresholds are to be calibrated; the
tests pin the STRUCTURE (conjunction, escalate-only, discordance), not the exact thresholds.
"""
from __future__ import annotations

RANK = {"LOW": 0, "MED": 1, "HIGH": 2}
INV = {0: "LOW", 1: "MED", 2: "HIGH"}
SURFACE = {"adc", "bite_tce", "tce", "antibody"}

# grounded axis -> the risk dim it augments
AXIS_TO_DIM = {"safety": "safety", "dependency": "biological", "selectivity": "safety",
               "surface_modality": "druggability", "tractability_sm": "druggability"}


def _mod(m: str) -> str:
    m = (m or "").lower()
    if "adc" in m: return "adc"
    if "tce" in m or "bispecific" in m: return "tce"
    if "antibod" in m or "mab" in m: return "antibody"
    if "degrad" in m or "glue" in m: return "degrader"
    return "small_molecule"


def _sv(pkg): return {k: (v.get("verdict") if isinstance(v, dict) else v)
                      for k, v in pkg["synthesis"]["sub_verdicts"].items()}
def _calls(pkg): return {c["card_id"]: c.get("interpretation_call")
                         for c in pkg.get("cards", []) if c.get("card_id")}


def deterministic_bins(pkg: dict, modality: str) -> dict:
    """Pure, reproducible per-dim bins (illustrative thresholds; the conjunction structure is the point)."""
    sv, calls = _sv(pkg), _calls(pkg)
    surf = modality in SURFACE
    dims = {}

    # SAFETY — modality-conditioned conjunction (the validated false-LOW fix)
    sig, chain = 0, []
    ots = {"highly_constrained_safety_concern": 2, "human_genetics_safety_concern": 1,
           "moderately_constrained_safety": 1, "moderately_constrained_safety_concern": 1,
           "wt_constraint_mechanism_mismatch": 0, "wt_human_genetics_mechanism_mismatch": 0,
           "tolerant_reduced_safety_risk": 0}.get(sv.get("safety"), 0)
    sig = max(sig, ots); chain.append(("on-target-safety", sv.get("safety"), INV[ots]))
    esc = 2 if surf else 1
    if calls.get("normal-tissue-liability-gtex") == "critical_organ_liability":
        sig = max(sig, esc); chain.append(("normal-tissue-gtex", "critical_organ_liability", INV[esc]))
    if calls.get("normal-tissue-liability-gtex") in ("broad_normal_expression", "broadly_expressed_normal") \
       or sv.get("selectivity") in ("selective_but_broadly_normal", "not_selective"):
        sig = max(sig, esc); chain.append(("tumor-selectivity normal-breadth", "broad", INV[esc]))
    if calls.get("sc-normal-celltype-expression") == "HIGH_LIABILITY":
        sig = max(sig, esc); chain.append(("sc-normal", "HIGH_LIABILITY", INV[esc]))
    if calls.get("modality-therapeutic-window") in ("essential_tissue_liability", "no_window"):
        sig = max(sig, esc); chain.append(("therapeutic-window", calls.get("modality-therapeutic-window"), INV[esc]))
    if surf and calls.get("shed-ectodomain-liability") == "clinically_shed":
        sig = max(sig, 1); chain.append(("shed-ectodomain", "clinically_shed", "MED"))
    mit = ("mitigated IF mutant-selective chemistry" if (not surf and sv.get("safety") in
           ("wt_constraint_mechanism_mismatch", "wt_human_genetics_mechanism_mismatch")) else None)
    dims["safety"] = {"pillar": "Right Safety", "bin": INV[sig], "chain": chain, "mitigation": mit,
                      "blind_spots": ["off-target/secondary-pharmacology", "immunogenicity",
                                      "ADC payload tox", "PK/exposure"]}

    # BIOLOGICAL — dependency (oos for surface) ∧ mechanism ∧ driver-role
    sig, chain = 0, []
    if not surf:
        dep = {"non_dependent": 2, "pan_essential_killer": 2, "discordant": 1, "insufficient": 1,
               "concordant_dependent": 0, "lineage_selective": 0, "selective_dependent": 0,
               "biomarker_stratified_dependency": 0, "partner_conditional_dependent": 0,
               "chemical_genetic_confirmed_dependent": 0, "non_dependent_paralog_buffered": 1}.get(sv.get("dependency"), 1)
        sig = max(sig, dep); chain.append(("dependency", sv.get("dependency"), INV[dep]))
    else:
        chain.append(("dependency", "out-of-scope (surface)", "N/A"))
    mech = 0 if sv.get("mechanism") == "well_characterized" else 1
    sig = max(sig, mech); chain.append(("mechanism", sv.get("mechanism"), INV[mech]))
    dims["biological"] = {"pillar": "Right Target", "bin": INV[sig], "chain": chain, "mitigation": None,
                          "blind_spots": ["contradictory literature", "resistance biology"]}

    # DRUGGABILITY — SM tractability (SM/degrader) or surface fit (biologics)
    sig, chain = 0, []
    if surf:
        r = {"both_viable": 0, "adc_preferred_tce_unsafe": 1, "surface_viable_density_caveated": 1,
             "neither_viable": 2}.get(sv.get("surface_modality"), 1)
        chain.append(("surface-modality-fit", sv.get("surface_modality"), INV[r])); blind = ["ADC linker/payload", "internalization"]
    else:
        r = {"well_covered": 0, "chemically_active": 0, "discordant": 1, "chemically_unhit": 2,
             "structurally_intractable": 2}.get(sv.get("tractability_sm"), 1)
        chain.append(("tractability-SM", sv.get("tractability_sm"), INV[r])); blind = ["PK/exposure", "CNS penetration", "synthesis"]
    dims["druggability"] = {"pillar": "Right Molecule", "bin": INV[r], "chain": chain, "mitigation": None, "blind_spots": blind}

    # engine-BLIND dims (literature-only via grounded/Tier-2)
    for d, pil in [("clinical", "Right Patient (clinical precedent)"), ("commercial", "Right Commercial")]:
        dims[d] = {"pillar": pil, "bin": "ENGINE-BLIND", "chain": [], "mitigation": None,
                   "blind_spots": ["entire dim — literature-only"]}
    return dims


def _findings_of(block: dict) -> list:
    g = block.get("grounded", block) or {}
    return g.get("findings") or g.get("liability_findings") or []   # tolerant of both field names


def project(pkg: dict, modality: str, substrate: dict | None = None) -> dict:
    """Fuse deterministic bins with grounded escalate-only findings + discordance. Findings NEVER
    change a bin (escalate-only)."""
    dims = deterministic_bins(pkg, _mod(modality))
    for axis, block in (substrate or {}).items():
        dim = AXIS_TO_DIM.get(axis)
        if not dim or dim not in dims:
            continue
        dims[dim].setdefault("grounded_findings", [])
        dims[dim]["grounded_findings"] += _findings_of(block)
        g = block.get("grounded", block) or {}
        if g.get("contradicts_deterministic"):
            dims[dim]["engine_literature_discordance"] = True
    return dims


if __name__ == "__main__":
    import argparse, json
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-package", required=True)
    ap.add_argument("--modality", required=True)
    ap.add_argument("--substrate", nargs="*", default=[], help="axis=path grounded substrate blocks")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    sub = {}
    for spec in a.substrate:
        ax, p = spec.split("=", 1); sub[ax] = json.loads(Path(p).read_text())
    dims = project(json.loads(Path(a.evidence_package).read_text()), a.modality, sub)
    if a.out: Path(a.out).write_text(json.dumps(dims, indent=2))
    print(json.dumps(dims, indent=2))
