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
    bins computed in-memory are identical to the bins computed from the serialized package. Three fields
    the projection reads are needed: `synthesis.sub_verdicts[short].verdict`, the flat `cards` list
    (`card_id` / `summary` / `interpretation_call` / `measurement_type`), and each axis's card provenance
    at `synthesis.skill_reports[short].provenance` (`cards_used` / `cards_missing`) — the join key for the
    computed evidence coverage below. That provenance is COPIED off the very same `skill_report` object
    that `tp_evidence_package` writes to disk as `synthesis.skill_reports[short]`, so the in-memory and
    on-disk coverage are one derivation, not two."""
    from .dispatcher import _envelope_card_present  # lazy: avoid an import cycle / import-time cost

    sub_verdicts: dict = {}
    skill_reports: dict = {}
    for short, r in sub_results.items():
        v = r.get("verdict")
        sub_verdicts[short] = {"verdict": v[0] if v else None}
        # the axis's own card provenance, off the emitted skill_report spine (never re-derived here: a
        # second `_missing` scan would be a copy that can disagree with the written package).
        rep = ((r or {}).get("synthesis_facet") or {}).get("skill_report")
        prov = rep.get("provenance") if isinstance(rep, dict) else None
        if isinstance(prov, dict):
            skill_reports[short] = {
                "provenance": {
                    "cards_used": list(prov.get("cards_used") or []),
                    "cards_missing": list(prov.get("cards_missing") or []),
                }
            }

    cards: list = []
    seen: set = set()
    for r in sub_results.values():
        for c in r.get("cards") or []:
            cid = c.get("card_id")
            if not cid or cid in seen or c.get("_missing"):
                continue
            seen.add(cid)
            cards.append(_envelope_card_present(c))
    return {"synthesis": {"sub_verdicts": sub_verdicts, "skill_reports": skill_reports}, "cards": cards}


# ── computed evidence coverage per dim (substrate Step 2d) ───────────────────────────────────────
# A bin says HOW BAD it looks. It cannot say WHETHER WE LOOKED. "SAFETY: HIGH because 2 axes measured
# badly" and "SAFETY: HIGH because 4 axes were never looked at" are OPPOSITE actions — de-risk the
# liability vs acquire the data — and the ordinal is IDENTICAL in both. This block computes the second
# half from the Step-1 per-field descriptor: for each axis AXIS_TO_DIM routes into a dim, how many of
# that axis's own declared cards resolved, and how many descriptor-covered fields THIS RUN measured.
#
# ADDITIVE + VERDICT-INERT: it lands on a new `evidence_coverage` key and touches no bin, chain,
# mitigation or hand-authored `blind_spots` literal (verified as a null diff: a 2520-row digest over the
# 504-target corpus x 5 modalities is byte-identical before/after). It does not REPLACE the literals
# either — those say what the omics CANNOT SEE AT ALL (a property of the framework); this says what THIS
# RUN saw (a property of the data). Both belong on the dim.
#
# FOUR states, not two, and the third one is the whole point. Measured over the 504-package corpus
# (4536 axis-runs): 4505 measured / 11 unmeasured / 20 undescribed / 0 absent. A binary measured-vs-not
# flag would therefore have reported 31 "blind spots" of which 20 (65%) are SALIENCE_SPECS coverage gaps
# — an INSTRUMENT gap shipped as an EVIDENCE gap, i.e. "nobody looked" asserted about an axis that looked
# and reported. `undescribed` keeps those in their own bucket, where they read as the descriptor work
# queue (`field_descriptor.coverage_report`) rather than as a data gap.
STATE_MEASURED = "measured"  # >=1 descriptor-covered field carried a measured value
STATE_UNMEASURED = "unmeasured"  # descriptor-covered fields exist; NONE measured -> a real evidence gap
STATE_UNDESCRIBED = "undescribed"  # cards resolved but no descriptor-covered field -> an INSTRUMENT gap
STATE_ABSENT = "absent"  # not one of the axis's declared cards resolved -> genuinely never looked at
COVERAGE_STATES: frozenset = frozenset({STATE_MEASURED, STATE_UNMEASURED, STATE_UNDESCRIBED, STATE_ABSENT})

# The descriptor roles that carry a MEASUREMENT. Held as literals (not imported) so this module stays
# stdlib-pure at import time — `deterministic_bins` is offline-safe and the descriptor join pulls in the
# gloss + salience registries. `test_measurement_roles_partition_descriptor_roles` asserts this set plus
# the four non-measurement roles EXACTLY partitions `field_descriptor.ROLES`, so a new role reds until
# it is classified here rather than being silently swallowed.
MEASUREMENT_ROLES: frozenset = frozenset(
    {"effect", "significance", "omnibus", "n", "categorical", "extra_scalar", "frame_value"}
)
# label = a stratum's name, strata = the array container, envelope = framework plumbing, unclassified =
# the descriptor could not read the field. None of the four is evidence that an axis measured anything.
NON_MEASUREMENT_ROLES: frozenset = frozenset({"label", "strata", "envelope", "unclassified"})


def _axis_card_provenance(pkg: dict) -> dict:
    """`{axis: (cards_used, cards_missing)}` off the emitted skill_report spine — the axis→cards join key.

    `synthesis.skill_reports[short].provenance` is written by `skill_report.build_skill_report` and is the
    SAME object on both routes (the on-disk evidence_package, and the in-memory view
    `assemble_risk_package` copies out of `sub_results[short].synthesis_facet.skill_report`). Axes with no
    report (clinical / commercial are card-fed pseudo-dims, never fan-out subskills) are simply absent."""
    reports = ((pkg.get("synthesis") or {}).get("skill_reports")) or {}
    out: dict = {}
    for short, rep in reports.items():
        if not isinstance(rep, dict):
            continue
        prov = rep.get("provenance")
        if not isinstance(prov, dict):
            continue
        out[short] = (list(prov.get("cards_used") or []), list(prov.get("cards_missing") or []))
    return out


def evidence_coverage_by_axis(pkg: dict) -> dict:
    """`{axis: {state, n_cards_resolved, n_cards_missing, n_fields_described, n_fields_measured}}`.

    One entry per axis that emitted a skill_report this run. `n_fields_described` counts the fields the
    Step-1 descriptor classified into a MEASUREMENT role across the axis's RESOLVED cards;
    `n_fields_measured` is how many of those carried a measured value under the shared
    `field_disposition.is_measured` rule (0/0.0/False are measured; None/sentinel/non-finite/empty are
    not) — this module invents no second measuredness rule.

    A card whose measurement_type resolves to no salience spec contributes 0 described fields, which is
    why the `undescribed` state exists: it is a statement about the DESCRIPTOR, not about the data.

    Covers EVERY axis that reported, not only the verdict-bearing AXIS_TO_DIM ones, so the gateless
    context companions can be read too — but `evidence_coverage_by_dim` deliberately surfaces only the
    AXIS_TO_DIM axes. Measured reason (504-package corpus): `translational_readiness` and
    `literature_context` are `undescribed` on 504 of 504 runs and `immune_context` on 86 — none of those
    measurement_types carries a SALIENCE_SPEC yet, so displaying their state per-run would ship a CONSTANT
    dressed as a per-run signal. They belong in the descriptor work queue until the specs land."""
    from .field_descriptor import descriptors_for  # lazy: keep this module stdlib-pure at import time
    from .field_disposition import is_measured
    from .measurement_types import card_measurement_type

    cards: dict = {}
    for c in pkg.get("cards") or []:
        cid = c.get("card_id")
        if cid and cid not in cards:
            cards[cid] = c

    out: dict = {}
    for axis, (used, missing) in _axis_card_provenance(pkg).items():
        resolved = [cards[cid] for cid in used if cid in cards]
        n_described = n_measured = 0
        for card in resolved:
            # the stamped measurement_type when the writer stamped it, else the SAME registry back-ref
            # the stamp itself is resolved from (envelope._stamp_evidence_substrate) — one derivation.
            mt = card.get("measurement_type") or card_measurement_type(card.get("card_id") or "")
            if not mt:
                continue
            descriptors = descriptors_for(mt)
            for field, value in (card.get("summary") or {}).items():
                d = descriptors.get(field)
                if not d or d.get("role") not in MEASUREMENT_ROLES:
                    continue
                n_described += 1
                if is_measured(value):
                    n_measured += 1
        if not resolved:
            state = STATE_ABSENT
        elif n_described == 0:
            state = STATE_UNDESCRIBED
        elif n_measured == 0:
            state = STATE_UNMEASURED
        else:
            state = STATE_MEASURED
        out[axis] = {
            "state": state,
            "n_cards_resolved": len(resolved),
            # declared by the axis and NOT resolved this run. 15.6% of all declared cards corpus-wide
            # (selectivity 38%, differentiation 27%) — the coverage number a bin cannot show even when
            # the axis is `measured`: 1-of-11 cards resolving still reads `measured`.
            "n_cards_missing": len(missing),
            "n_fields_described": n_described,
            "n_fields_measured": n_measured,
        }
    return out


def evidence_coverage_by_dim(pkg: dict) -> dict:
    """`{dim: {axes_declared, axes_reported, axes, unmeasured_axes, unresolved_axes, undescribed_axes,
    n_cards_resolved, n_cards_missing}}` — the per-dim roll-up of `evidence_coverage_by_axis`.

    `axes_declared` is every axis AXIS_TO_DIM routes into the dim; `axes_reported` those that actually
    emitted a report. Both are surfaced because they DIFFER meaningfully: clinical / commercial declare an
    axis that is never a fan-out subskill (their bin comes from the clinical-precedent /
    competitor-landscape CARDS), so `axes_declared` non-empty with `axes_reported` empty is the honest
    reading "this dim is card-fed, not axis-fed" — not "this dim is blind".

    The three named lists are kept SEPARATE rather than summed into one blind-spot count: an evidence gap
    (`unmeasured`), a never-resolved axis (`unresolved`) and a descriptor gap (`undescribed`) call for
    three different actions, and collapsing them is exactly the lossiness the substrate pivot removes."""
    per_axis = evidence_coverage_by_axis(pkg)
    out: dict = {}
    for dim in dict.fromkeys(AXIS_TO_DIM.values()):
        declared = [a for a, d in AXIS_TO_DIM.items() if d == dim]
        reported = [a for a in declared if a in per_axis]
        axes = {a: per_axis[a] for a in reported}
        out[dim] = {
            "axes_declared": declared,
            "axes_reported": reported,
            "axes": axes,
            "unmeasured_axes": [a for a in reported if axes[a]["state"] == STATE_UNMEASURED],
            "unresolved_axes": [a for a in reported if axes[a]["state"] == STATE_ABSENT],
            "undescribed_axes": [a for a in reported if axes[a]["state"] == STATE_UNDESCRIBED],
            "n_cards_resolved": sum(axes[a]["n_cards_resolved"] for a in reported),
            "n_cards_missing": sum(axes[a]["n_cards_missing"] for a in reported),
        }
    return out


def _attach_evidence_coverage(dims: dict, pkg: dict) -> None:
    """Attach the computed per-dim coverage to `dims` IN PLACE, additively.

    FAIL-SOFT but never SILENT: the descriptor join reads the gloss + salience + measurement-type
    registries, and a skills-only checkout cannot reach the last of those. On any failure every dim gets
    `evidence_coverage = {"error": ...}` — the bins stay untouched (this is display-only), and the reason
    is on the artifact rather than swallowed. Deliberately NOT raised: `build_risk_6dim` wraps the whole
    projection in one try/except, so letting this propagate would drop the entire 6-dim roll-up over an
    additive display key."""
    try:
        coverage = evidence_coverage_by_dim(pkg)
    except Exception as e:  # noqa: BLE001 — display-only enrichment; must never cost a bin
        coverage = None
        err = {"error": f"{type(e).__name__}: {e}"}
    for dim, d in dims.items():
        if not isinstance(d, dict):
            continue
        d["evidence_coverage"] = coverage.get(dim, {}) if coverage is not None else dict(err)


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
    # Step 2d: the COMPUTED coverage beside the hand-authored literals — additive, last, bins untouched.
    _attach_evidence_coverage(dims, pkg)
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
    "COVERAGE_STATES",
    "MEASUREMENT_ROLES",
    "NON_MEASUREMENT_ROLES",
    "STATE_ABSENT",
    "STATE_MEASURED",
    "STATE_UNDESCRIBED",
    "STATE_UNMEASURED",
    "evidence_coverage_by_axis",
    "evidence_coverage_by_dim",
    "_risk_rows_from_rollup",
    "_RISK_DIM_ORDER",
    "_ROLLUP_BIN_TO_MD_LEVEL",
]
