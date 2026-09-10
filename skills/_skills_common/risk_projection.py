#!/usr/bin/env python3
"""risk_projection — the DETERMINISTIC 6-dim risk projection (the spine cut by governance category).

This is the pure, reproducible core of the 6-dim risk roll-up: a modality-CONDITIONED worst-case
CONJUNCTION over the relevant sub-verdicts, mapped into the six AstraZeneca-5R governance categories
(biological / druggability / safety / translational / clinical / commercial). It is one of three
orthogonal PROJECTIONS of the same per-skill signal set (target_call = necessity, modality_fit = route,
risk_6dim = governance category) — NOT a new opinion. The LLM/literature NEVER sets a bin.

RE-HOMED here 2026-09-03 from `literature-risk-assessment/scripts/risk_rollup.py`: the deterministic
bins were never a literature product — they merely lived inside a skill named "literature-risk". Moving
the pure core to `_skills_common` lets `target-profile` compute `target_report.risk_6dim` directly from
the in-memory `sub_results` (no disk round-trip, no network) while the standalone lit-risk CLI keeps
working (it re-exports these symbols). The literature-GROUNDING overlay (escalate-only findings +
discordance + the engine-blind pseudo-card literature bin) stays in the lit-risk skill's `risk_rollup.py`
(`project()`), which imports this core.

THRESHOLDS ARE ILLUSTRATIVE (v0). The CONTRACT is the contribution: modality-conditioned conjunction +
declared blind-spots + reproducible bin. Thresholds are to be calibrated; the tests pin the STRUCTURE
(conjunction, reproducibility), not the exact thresholds.
"""

from __future__ import annotations

RANK = {"LOW": 0, "MED": 1, "HIGH": 2}
INV = {0: "LOW", 1: "MED", 2: "HIGH"}
SURFACE = {"adc", "bite_tce", "tce", "antibody"}

# grounded axis -> the risk dim it augments. The 12 subskills map many-to-few onto the 6 risk dims
# (5R-style decomposition): the target-biology axes (dependency + mechanism/genomic/SL/combinatorial/
# expression) all escalate the BIOLOGICAL (Right Target) dim; safety/selectivity escalate SAFETY; the
# two tractability axes escalate DRUGGABILITY; `differentiation` (patient-selection) escalates the
# TRANSLATIONAL dim; clinical/commercial are the engine-blind pseudo-card dims. This completes the
# 6-dim map (biological/druggability/safety/translational/clinical/commercial) — every grounded axis
# now reaches a risk dim in [3A] (parity with [3B], which is axis-agnostic).
AXIS_TO_DIM = {
    "safety": "safety",
    "dependency": "biological",
    "selectivity": "safety",
    "surface_modality": "druggability",
    "tractability_sm": "druggability",
    "mechanism": "biological",
    "genomic_alteration": "biological",
    # synthetic_lethal_partners / combinatorial_dependency REMOVED 2026-08-21 (consolidated
    # into the gateless combination_vulnerability short; their ground_axis axes were dropped).
    "expression": "biological",
    "differentiation": "translational",
    "clinical": "clinical",
    "commercial": "commercial",
}  # translational + clinical/commercial = engine-blind


def _mod(m: str) -> str:
    m = (m or "").lower()
    if "adc" in m:
        return "adc"
    if "tce" in m or "bispecific" in m:
        return "tce"
    if "antibod" in m or "mab" in m:
        return "antibody"
    if "degrad" in m or "glue" in m:
        return "degrader"
    return "small_molecule"


def _sv(pkg):
    return {k: (v.get("verdict") if isinstance(v, dict) else v) for k, v in pkg["synthesis"]["sub_verdicts"].items()}


def _calls(pkg):
    return {c["card_id"]: c.get("interpretation_call") for c in pkg.get("cards", []) if c.get("card_id")}


def _card(pkg, cid):
    for c in pkg.get("cards", []):
        if c.get("card_id") == cid:
            return c.get("summary") or {}
    return {}


def _q(pkg, cid, field):
    """Raw anchoring quantity from a card summary, surfaced in the chain for traceability."""
    v = _card(pkg, cid).get(field)
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return v


def assemble_risk_package(sub_results: dict) -> dict:
    """Build the MINIMAL in-memory evidence-package view the deterministic projection reads, straight
    from target-profile's in-memory `sub_results` — no disk round-trip.

    Byte-parity contract: this mirrors `tp_evidence_package._write_evidence_package`'s card union
    (union-by-card_id, first-wins, present-only) and sub_verdict extraction, and normalizes each present
    card through the SAME `_envelope_card_present` used for the on-disk `evidence_package.json`. So the
    bins computed in-memory are identical to the bins computed from the serialized package. Only the two
    fields the projection reads are needed: `synthesis.sub_verdicts[short].verdict` and the flat `cards`
    list (`card_id` / `summary` / `interpretation_call`)."""
    from .dispatcher import _envelope_card_present  # lazy: avoid an import cycle / import-time cost

    sub_verdicts: dict = {}
    for short, r in sub_results.items():
        v = r.get("verdict")
        sub_verdicts[short] = {"verdict": v[0] if v else None}

    cards: list = []
    seen: set = set()
    for r in sub_results.values():
        for c in r.get("cards") or []:
            cid = c.get("card_id")
            if not cid or cid in seen or c.get("_missing"):
                continue
            seen.add(cid)
            cards.append(_envelope_card_present(c))
    return {"synthesis": {"sub_verdicts": sub_verdicts}, "cards": cards}


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
    ots = {
        "highly_constrained_safety_concern": 2,
        "human_genetics_safety_concern": 1,
        "moderately_constrained_safety": 1,
        "moderately_constrained_safety_concern": 1,
        "wt_constraint_mechanism_mismatch": 0,
        "wt_human_genetics_mechanism_mismatch": 0,
        "tolerant_reduced_safety_risk": 0,
    }.get(sv.get("safety"), 0)
    _loeuf = _q(pkg, "gnomad-lof-constraint", "loeuf_score")
    sig = max(sig, ots)
    chain.append(("on-target-safety", f"{sv.get('safety')} [LOEUF={_loeuf}; <0.35 LoF-intolerant]", INV[ots]))
    esc = 2 if surf else 1
    if calls.get("normal-tissue-liability-gtex") == "critical_organ_liability":
        sig = max(sig, esc)
        chain.append(("normal-tissue-gtex", "critical_organ_liability", INV[esc]))
    if calls.get("normal-tissue-liability-gtex") in ("broad_normal_expression", "broadly_expressed_normal") or sv.get(
        "selectivity"
    ) in ("selective_but_broadly_normal", "not_selective"):
        sig = max(sig, esc)
        chain.append(("tumor-selectivity normal-breadth", "broad", INV[esc]))
    if calls.get("sc-normal-celltype-expression") == "HIGH_LIABILITY":
        sig = max(sig, esc)
        chain.append(("sc-normal", "HIGH_LIABILITY", INV[esc]))
    if calls.get("modality-therapeutic-window") in ("essential_tissue_liability", "no_window"):
        sig = max(sig, esc)
        chain.append(("therapeutic-window", calls.get("modality-therapeutic-window"), INV[esc]))
    if surf and calls.get("shed-ectodomain-liability") == "clinically_shed":
        sig = max(sig, 1)
        chain.append(("shed-ectodomain", "clinically_shed", "MED"))
    mit = (
        "mitigated IF mutant-selective chemistry"
        if (
            not surf
            and sv.get("safety") in ("wt_constraint_mechanism_mismatch", "wt_human_genetics_mechanism_mismatch")
        )
        else None
    )
    dims["safety"] = {
        "pillar": "Right Safety",
        "bin": INV[sig],
        "chain": chain,
        "mitigation": mit,
        "blind_spots": ["off-target/secondary-pharmacology", "immunogenicity", "ADC payload tox", "PK/exposure"],
    }

    # BIOLOGICAL — dependency (oos for surface) ∧ mechanism ∧ driver-role
    sig, chain = 0, []
    if not surf:
        # pan_essential_killer = a dependency but NOT tumor-selective -> its tox routes to SAFETY (not a
        # target-validity failure) -> MED, not HIGH. Only non_dependent is HIGH biological risk.
        dep = {
            "non_dependent": 2,
            "pan_essential_killer": 1,
            "discordant": 1,
            "insufficient": 1,
            "concordant_dependent": 0,
            "lineage_selective": 0,
            "selective_dependent": 0,
            "biomarker_stratified_dependency": 0,
            "partner_conditional_dependent": 0,
            "chemical_genetic_confirmed_dependent": 0,
            "non_dependent_paralog_buffered": 1,
        }.get(sv.get("dependency"), 1)
        _chr = _q(pkg, "dependency-lineage-selectivity", "median_chronos_panel")
        sig = max(sig, dep)
        chain.append(
            (
                "dependency",
                f"{sv.get('dependency')} [lineage-scoped; Chronos<=-0.5 in-lineage; panel median {_chr}]",
                INV[dep],
            )
        )
    else:
        chain.append(("dependency", "out-of-scope (surface)", "N/A"))
    mech = 0 if sv.get("mechanism") == "well_characterized" else 1
    sig = max(sig, mech)
    chain.append(("mechanism", sv.get("mechanism"), INV[mech]))
    dims["biological"] = {
        "pillar": "Right Target",
        "bin": INV[sig],
        "chain": chain,
        "mitigation": None,
        "blind_spots": ["contradictory literature", "resistance biology"],
    }

    # DRUGGABILITY — SM tractability (SM/degrader) or surface fit (biologics)
    sig, chain = 0, []
    if surf:
        r = {
            "both_viable": 0,
            "adc_preferred_tce_unsafe": 1,
            "surface_viable_density_caveated": 1,
            "neither_viable": 2,
        }.get(sv.get("surface_modality"), 1)
        chain.append(("surface-modality-fit", sv.get("surface_modality"), INV[r]))
        blind = ["ADC linker/payload", "internalization"]
    else:
        # LOW-risk = a viable chemical start point. The lookup previously omitted the STRONG-positive
        # tractability verdicts (measured_potent_ligand, chemically_confirmed_genetic) — so the strongest
        # druggability calls silently defaulted to MED (the USP8/NSCLC symptom: measured_potent_ligand →
        # MED). Aligned with tractability-small-molecule's polarity: _TRACT_STRONG → LOW(0); the caveated
        # moderate rungs (structurally_ligandable / clinical_precedent_only / tool_compound_only /
        # weakly_active) stay MED(1) via the default; negatives → HIGH(2).
        r = {
            "well_covered": 0,
            "chemically_confirmed_genetic": 0,
            "chemically_active": 0,
            "measured_potent_ligand": 0,
            "discordant": 1,
            "chemically_unhit": 2,
            "structurally_intractable": 2,
        }.get(sv.get("tractability_sm"), 1)
        _tdl = _q(pkg, "target-development-level", "tdl_class")  # raw Pharos tier (Tclin>Tchem>Tbio>Tdark)
        chain.append(("tractability-SM", f"{sv.get('tractability_sm')} [Pharos TDL={_tdl}]", INV[r]))
        blind = ["PK/exposure", "CNS penetration", "synthesis"]
    dims["druggability"] = {
        "pillar": "Right Molecule",
        "bin": INV[r],
        "chain": chain,
        "mitigation": None,
        "blind_spots": blind,
    }

    # CLINICAL — precedent from the LIVE public AACT/ClinicalTrials `clinical-precedent` card (wired
    # 2026-09; the card is composed into the evidence-package by differentiation-landscape). Risk =
    # clinical-translation uncertainty / failure precedent: an approved-or-late-stage engaging agent =
    # validated (LOW); an asserted notable failure = a real de-risking-required signal (HIGH); anything
    # in-between / no precedent = MED. Only the trial-precedent leg is engine-fed; deeper clinical risk
    # (trial design / endpoint) stays literature-only. Absent card → falls through to ENGINE-BLIND below.
    cp = _card(pkg, "clinical-precedent")
    _stage = cp.get("highest_clinical_stage")
    if cp and (_stage is not None or cp.get("notable_failures")):
        c = 2 if cp.get("notable_failures") else (0 if _stage in ("approved", "phase_3", "pivotal") else 1)
        dims["clinical"] = {
            "pillar": "Right Patient (clinical precedent)",
            "bin": INV[c],
            "chain": [
                (
                    "clinical-precedent",
                    f"highest_clinical_stage={_stage}; notable_failures={bool(cp.get('notable_failures'))}",
                    INV[c],
                )
            ],
            "mitigation": None,
            "blind_spots": ["trial design / endpoint risk (literature-only)"],
        }

    # COMMERCIAL — the COMPETITION leg from the LIVE Open Targets `competitor-landscape` card (CC0). Only
    # competitive intensity is engine-fed; market size / revenue / IP freedom-to-operate remain a genuine
    # DATA gap (Cortellis/IQVIA unlicensed). Direction per the card's own framing: an approved competitor
    # = crowded = high differentiation risk (HIGH); no known competitor = whitespace / first-mover (LOW).
    cl = _card(pkg, "competitor-landscape")
    _klass = cl.get("competitor_class") if cl else None
    _cbin = {
        "approved_competitor": 2,
        "active_clinical_competitor": 1,
        "early_or_preclinical_competitor": 1,
        "no_known_competitor": 0,
    }.get(_klass)
    if _cbin is not None:
        dims["commercial"] = {
            "pillar": "Right Commercial",
            "bin": INV[_cbin],
            "chain": [
                (
                    "competitor-landscape",
                    f"competitor_class={_klass}; n_programs={cl.get('n_competitor_programs')}",
                    INV[_cbin],
                )
            ],
            "mitigation": None,
            "blind_spots": ["market size / revenue / IP freedom-to-operate (unlicensed data)"],
        }

    # TRANSLATIONAL — preclinical-validation readiness from the LIVE translational-readiness cards (HCMI
    # model availability + genotype-matched models + PDXE in-vivo response). Risk = how hard it is to
    # preclinically validate a nomination: no patient-derived models / no genotype-matched model = HIGH;
    # deep coverage + a genotype-matched model = LOW. The model-coverage + genotype-match legs (the skill's
    # critical axes) set the ordinal (worst-of); a PDXE objective responder is in-vivo validation precedent
    # that CAPS the risk at MED. `differentiation` is NOT read here (its verdict is a co-mutation LANDSCAPE,
    # not a readiness ordinal). All legs data_unavailable / absent → falls through to ENGINE-BLIND below.
    tr_sig, tr_chain = None, []
    for cid, field, mapping in [
        (
            "target-model-availability",
            "model_availability_class",
            {"deep_model_coverage": 0, "moderate_model_coverage": 1, "sparse_model_coverage": 2},
        ),
        (
            "target-genotype-matched-model",
            "genotype_matched_class",
            {"matched_deep": 0, "matched_sparse": 1, "none": 2},
        ),
    ]:
        _cls = _card(pkg, cid).get(field)
        b = mapping.get(_cls)
        if b is not None:
            tr_sig = b if tr_sig is None else max(tr_sig, b)
            tr_chain.append((cid, _cls, INV[b]))
    tr_mit = None
    if tr_sig is not None and _card(pkg, "target-pdx-drug-response").get("pdx_drug_response_class") == (
        "pdx_objective_responders"
    ):
        tr_chain.append(("target-pdx-drug-response", "pdx_objective_responders (in-vivo validation precedent)", "LOW"))
        if tr_sig > 1:
            tr_sig = 1
            tr_mit = "capped at MED by a PDXE in-vivo objective response"
    if tr_sig is not None:
        dims["translational"] = {
            "pillar": "Right Patient (translational readiness / patient-selection)",
            "bin": INV[tr_sig],
            "chain": tr_chain,
            "mitigation": tr_mit,
            "blind_spots": [
                "PD-assay / imaging-tracer / internal Takeda models (un-wired)",
                "co-mutation patient-selection (literature-only)",
            ],
        }

    # engine-BLIND dims (literature-only via grounded/Tier-2) — set ONLY if not already engine-fed above.
    # translational is engine-fed above WHEN the translational-readiness model/genotype cards are present;
    # it falls here (literature-only) only when those cards are absent/data_unavailable. `differentiation`
    # carries a co-mutation/patient-selection LANDSCAPE sub-verdict, not a translational risk ordinal, so it
    # is deliberately NOT routed into a computed translational bin — the dim is honestly literature-only
    # until a translational engine bin exists. clinical/commercial fall here only when their card is
    # absent/insufficient. Grounded findings set the coarse literature bin in project() (lit-risk skill).
    for d, pil in [
        ("clinical", "Right Patient (clinical precedent)"),
        ("commercial", "Right Commercial"),
        ("translational", "Right Patient (translational readiness / patient-selection)"),
    ]:
        if d in dims:
            continue
        dims[d] = {
            "pillar": pil,
            "bin": "ENGINE-BLIND",
            "chain": [],
            "mitigation": None,
            "blind_spots": ["entire dim — literature-only"],
        }
    return dims


# ── (category, level, driver) row adaptation ─────────────────────────────────────────────────────
# Re-homed here 2026-09-03 (Wave-3 legacy-renderer retirement) from tp_render_md so the standalone
# render_review reviewer + the (retiring) md report share ONE risk-row source without importing the
# renderer. Presentation-neutral: adapts the canonical deterministic risk_rollup `dims` into
# (category, level, driver) rows. Both the md table + render_review render the SAME 6-dim risk this way.
_ROLLUP_BIN_TO_MD_LEVEL = {"LOW": "LOW", "MED": "MEDIUM", "HIGH": "HIGH", "ENGINE-BLIND": "insufficient_evidence"}
# fixed 6-dim order (matches the historical _risk_by_category ordering).
_RISK_DIM_ORDER = ("biological", "druggability", "translational", "clinical", "safety", "commercial")


def _risk_rows_from_rollup(risk_rollup):
    """Adapt the CANONICAL deterministic risk_rollup (dims) into (category, level, driver) rows, so a
    consumer renders the SAME 6-dim risk the HTML report + risk_rollup.json show — instead of a parallel
    per-consumer mapping that could diverge. Returns None when the rollup is absent/misshaped → the caller
    falls back to its local mapping (e.g. a --no-substrate run where risk_rollup was never produced)."""
    dims = risk_rollup.get("dims") if isinstance(risk_rollup, dict) and "dims" in risk_rollup else risk_rollup
    if not isinstance(dims, dict):
        return None
    rows = []
    for dim in _RISK_DIM_ORDER:
        d = dims.get(dim)
        if not isinstance(d, dict) or "bin" not in d:
            continue
        level = _ROLLUP_BIN_TO_MD_LEVEL.get(d.get("bin"), d.get("bin") or "insufficient_evidence")
        chain = d.get("chain") or []
        driver = f"{chain[0][0]}: {chain[0][1]}" if chain and len(chain[0]) >= 2 else (d.get("pillar") or "")
        rows.append((dim, level, driver))
    return rows or None


__all__ = [
    "RANK",
    "INV",
    "SURFACE",
    "AXIS_TO_DIM",
    "_mod",
    "_sv",
    "_calls",
    "_card",
    "_q",
    "assemble_risk_package",
    "deterministic_bins",
    "_risk_rows_from_rollup",
    "_RISK_DIM_ORDER",
    "_ROLLUP_BIN_TO_MD_LEVEL",
]
