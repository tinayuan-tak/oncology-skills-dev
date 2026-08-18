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

# grounded axis -> the risk dim it augments. The 12 subskills map many-to-few onto the 6 risk dims
# (5R-style decomposition): the target-biology axes (dependency + mechanism/genomic/SL/combinatorial/
# expression, rolled out 2026-08-18) all escalate the BIOLOGICAL (Right Target) dim; safety/selectivity
# escalate SAFETY; the two tractability axes escalate DRUGGABILITY; clinical/commercial are the
# engine-blind pseudo-card dims. `differentiation` is patient-selection (a TRANSLATIONAL dim not yet
# modelled here) → intentionally unmapped: it feeds the cross-evidence hypothesis [3B] (axis-agnostic)
# but not this [3A] roll-up until a translational dim is added (documented follow-up, not a silent drop).
AXIS_TO_DIM = {"safety": "safety", "dependency": "biological", "selectivity": "safety",
               "surface_modality": "druggability", "tractability_sm": "druggability",
               "mechanism": "biological", "genomic_alteration": "biological",
               "synthetic_lethal_partners": "biological", "combinatorial_dependency": "biological",
               "expression": "biological",
               "clinical": "clinical", "commercial": "commercial"}   # pseudo-card dims
# coarse literature-bin escalators for the engine-blind pseudo-card dims (decision 2)
_PSEUDO_ESCALATORS = ("fail", "discontinu", "terminat", "negative", "toxic", "crowded",
                      "competitor", "freedom", "ip_", "lack_of")


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
def _card(pkg, cid):
    for c in pkg.get("cards", []):
        if c.get("card_id") == cid: return c.get("summary") or {}
    return {}
def _q(pkg, cid, field):
    """Raw anchoring quantity from a card summary, surfaced in the chain for traceability."""
    v = _card(pkg, cid).get(field)
    try: return round(float(v), 3)
    except (TypeError, ValueError): return v


def deterministic_bins(pkg: dict, modality: str) -> dict:
    """Pure, reproducible per-dim bins. CALIBRATION (ryan.abo 2026-08-17): the bin is the spine's
    already-CONDITIONED sub-verdict (safety = gnomAD LOEUF<0.35 THEN GoF/mutant-selective downgrade;
    biological = DepMap Chronos<=-0.5 WITHIN the indication lineage; both applied by the resolvers) —
    re-thresholding the raw PAN-cancer quantity would discard that conditioning and re-introduce
    false-HIGHs. So the bin stays the conditioned verdict; the RAW anchoring quantity + published
    threshold is SURFACED in the chain for defensibility. druggability additionally anchors to raw
    Pharos TDL (its verdict is a lossy roll-up)."""
    sv, calls = _sv(pkg), _calls(pkg)
    surf = modality in SURFACE
    dims = {}

    # SAFETY — modality-conditioned conjunction (the validated false-LOW fix)
    sig, chain = 0, []
    ots = {"highly_constrained_safety_concern": 2, "human_genetics_safety_concern": 1,
           "moderately_constrained_safety": 1, "moderately_constrained_safety_concern": 1,
           "wt_constraint_mechanism_mismatch": 0, "wt_human_genetics_mechanism_mismatch": 0,
           "tolerant_reduced_safety_risk": 0}.get(sv.get("safety"), 0)
    _loeuf = _q(pkg, "gnomad-lof-constraint", "loeuf_score")
    sig = max(sig, ots)
    chain.append(("on-target-safety", f"{sv.get('safety')} [LOEUF={_loeuf}; <0.35 LoF-intolerant]", INV[ots]))
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
        # pan_essential_killer = a dependency but NOT tumor-selective -> its tox routes to SAFETY (not a
        # target-validity failure) -> MED, not HIGH. Only non_dependent is HIGH biological risk.
        dep = {"non_dependent": 2, "pan_essential_killer": 1, "discordant": 1, "insufficient": 1,
               "concordant_dependent": 0, "lineage_selective": 0, "selective_dependent": 0,
               "biomarker_stratified_dependency": 0, "partner_conditional_dependent": 0,
               "chemical_genetic_confirmed_dependent": 0, "non_dependent_paralog_buffered": 1}.get(sv.get("dependency"), 1)
        _chr = _q(pkg, "dependency-lineage-selectivity", "median_chronos_panel")
        sig = max(sig, dep)
        chain.append(("dependency", f"{sv.get('dependency')} [lineage-scoped; Chronos<=-0.5 in-lineage; panel median {_chr}]", INV[dep]))
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
        _tdl = _q(pkg, "target-development-level", "tdl_class")   # raw Pharos tier (Tclin>Tchem>Tbio>Tdark)
        chain.append(("tractability-SM", f"{sv.get('tractability_sm')} [Pharos TDL={_tdl}]", INV[r]))
        blind = ["PK/exposure", "CNS penetration", "synthesis"]
    dims["druggability"] = {"pillar": "Right Molecule", "bin": INV[r], "chain": chain, "mitigation": None, "blind_spots": blind}

    # engine-BLIND dims (literature-only via grounded/Tier-2)
    for d, pil in [("clinical", "Right Patient (clinical precedent)"), ("commercial", "Right Commercial")]:
        dims[d] = {"pillar": pil, "bin": "ENGINE-BLIND", "chain": [], "mitigation": None,
                   "blind_spots": ["entire dim — literature-only"]}
    return dims


def _findings_of(block: dict) -> list:
    g = block.get("grounded", block) or {}
    return g.get("findings") or g.get("liability_findings") or []   # tolerant of both field names


def _pseudo_literature_bin(findings: list) -> str:
    """Coarse literature-only bin for engine-blind pseudo-card dims (decision 2): a finding whose kind
    hits an escalator → HIGH; any finding → MED; none → LOW. Uncalibrated (literature-only)."""
    if not findings:
        return "LOW"
    for f in findings:
        k = str(f.get("kind", "")).lower()
        if any(e in k for e in _PSEUDO_ESCALATORS):
            return "HIGH"
    return "MED"


def project(pkg: dict, modality: str, substrate: dict | None = None) -> dict:
    """Fuse deterministic bins with grounded escalate-only findings + discordance. For ENGINE-anchored
    dims, findings NEVER change the deterministic bin (escalate-only). For engine-BLIND pseudo-card dims
    (clinical/commercial), a COARSE literature-only bin is derived from the findings (tagged uncalibrated)."""
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
        # engine-blind pseudo-card dim → derive the coarse literature bin (never for engine dims)
        if dims[dim].get("bin") == "ENGINE-BLIND":
            dims[dim]["bin"] = _pseudo_literature_bin(dims[dim]["grounded_findings"])
            dims[dim]["bin_basis"] = "literature-only (uncalibrated)"
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
