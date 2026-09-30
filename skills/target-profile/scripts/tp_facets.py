"""target-profile — deterministic derived facets (verdict-inert render inputs + the deciding-axis
router): ordinal matrix, biomarker, subtype, fragility, heterogeneity, addressable-population,
competitor cross-ref, per-axis certainty, modality-fit-by-channel, actionability-mode, magnitude,
and cross-gate shared-evidence, plus the composed target_report builder family (build_target_report /
build_target_rollup / build_target_call / build_target_coherence / build_composed_evidence_graph)."""

from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Optional

import yaml

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _skills_common import ordinal_view
from _skills_common.flip_analysis import flip_analysis
from _skills_common.narrative import build_narrative
from tp_common import _CONTRACTS_REPO
from tp_facets_biomarker import (  # re-export the split-out biomarker cluster
    _BIOMARKER_INPUTS,
    _BIOMARKER_QUANT,
    _biomarker_facet,
    _biomarker_quantitative,
    _classify_biomarker_best_roles,
)
from tp_facets_subtype import (  # re-export the split-out subtype/subgroup cluster
    _SUBTYPE_INPUTS,
    _backfill_subtype_spine,
    _first_card_per_subgroup,
    _load_subtype_crosswalk,
    _rollup_subtype_block,
    _subgroup_flip_view,
    _subtype_facet,
    _subtype_stratum_key,
)
from tp_fanout import _CONFIDENCE_AXIS_TO_GATE, _SHORT_TO_GATE, SUBTYPE_SHORT
from tp_gates import (
    _COVERAGE_RANK,
    _load_gate_coverage,
    _load_gate_verdicts,
    _load_positive_signals,
    _reconciled_contradiction_keys,
    _run_coverage_for_short,
    _sub_result_has_signal,
)


def _admissible_but_silent(sub_results: dict, baseline: dict, exclude: set[str]) -> list[dict]:
    """The axes the framework COULD evidence this run (per-run framework_can_evidence in
    captured/partial) that produced a signal but did NOT carry the call — the honesty companion to
    the deciding axis. This is what makes a HOLD auditable: "held on safety; surface was ADMISSIBLE
    and read `adc_preferred`" instead of a bare "held". `exclude` = the deciding short(s), so the
    winner is not also listed as silent. A purely descriptive/gateless axis (no gate + no band) is
    not admissible-to-DECIDE, so it is omitted (it is context, not a silent decider). Deterministic:
    necessity-band first, then strongest coverage, then short — no run-to-run reordering."""
    rows = []
    for short, r in sub_results.items():
        if short in exclude or short not in baseline:
            continue
        if not _sub_result_has_signal(r):
            continue
        cov = _run_coverage_for_short(short, r, baseline)
        if cov not in ("captured", "partial"):
            continue
        b = baseline.get(short, {})
        if not (b.get("gate") or b.get("gate_name") or b.get("band")):
            continue  # descriptive/gateless axis — not an admissible decider
        v = r.get("verdict")
        rows.append(
            {
                "short": short,
                "gate": b.get("gate"),
                "band": b.get("band"),
                "framework_can_evidence": cov,
                "verdict": v[0] if v else None,
            }
        )
    rows.sort(
        key=lambda x: (
            x.get("band") != "necessity",
            -_COVERAGE_RANK.get(x.get("framework_can_evidence"), 0),
            x.get("short") or "",
        )
    )
    return rows


def _attribution_mismatch(deciding_rows: list[dict], silent_rows: list[dict]) -> dict:
    """Ontology-derived honesty flag (Step 1b): was the call carried by an axis OUTSIDE the necessity
    ANY-OF set ("is this real biology?") while a necessity axis was ADMISSIBLE but mute? That is the
    attribution the architecture assessment found pervasive — surface antigens HELD on safety /
    dependency, never adjudicated on surface biology (0/14 on the reference panel).

    `band` is the ontology's necessity/sufficiency partition (target_profiling_axes.yaml, mirrored
    into gate_coverage), so this needs NO per-target thesis typing and is independent of Step 2's
    routing. Flags iff EVERY deciding axis is non-necessity AND >=1 admissible-but-silent axis is
    necessity.

    SCOPE BOUND (deliberate, ontology-only): it CANNOT flag a necessity-axis decision that is wrong
    for the target's thesis — e.g. a dependency veto of an antigen-driven target that carries no
    recurrent dependency (an ANY-OF violation). Distinguishing that needs per-target thesis typing,
    which is Step 2. This is the subset detectable from the ontology alone; verdict-INERT either way."""
    deciding_bands = {r.get("band") for r in deciding_rows}
    silent_necessity = [r["short"] for r in silent_rows if r.get("band") == "necessity"]
    flagged = bool(silent_necessity) and all(b != "necessity" for b in deciding_bands)
    out: dict = {"flagged": flagged, "silent_necessity_axes": silent_necessity}
    if flagged:
        dec = sorted({r.get("short") for r in deciding_rows if r.get("short")})
        out["reason"] = (
            f"deciding axis {dec} is non-necessity (sufficiency/gating) while necessity axes "
            f"{silent_necessity} were admissible but silent — the call may not rest on the target's "
            f"thesis biology (ontology-only signal; per-target thesis is Step 2)."
        )
    return out


def _deciding_axis(
    sub_results: dict,
    gate_action: Optional[str],
    gate_hits: list[dict],
    positive_hits: list[dict],
    contracts_repo: Path | None = None,
    thesis_record: Optional[dict] = None,
) -> dict:
    """Build the deciding_axis block (see module comment above). Deterministic; never predicts.

    Every decided basis (gate_fired / thesis_decider / positive_signal) also reports
    `admissible_but_silent` (the other axes the framework could evidence this run but that did not
    carry the call) and `attribution_mismatch` (did a non-necessity axis carry the call while a
    necessity axis was admissible-but-mute?) — so the attribution is auditable, not just "which axis
    won" but "which axes were in play and mute, and does the winner rest on the target's thesis
    biology".

    `thesis_record` is the Step-3 `thesis_nomination` provenance record. When it APPLIED, the
    thesis's deciding axis IS the decision's attribution — which is the whole point of Step 3: the
    7 surface reference targets previously attributed to `abstention_coverage_gaps` (DLL3 carries
    ZERO positive hits in default biology-first mode, since surface positives are
    excluded_positive_modality_scoped unless --modality is declared), so surface-antigen attribution
    measured 0.0 even for the approved drugs. A declined-but-registered record does NOT change the
    basis — the framework did not decide, and saying otherwise would overstate the attribution."""
    baseline, source = _load_gate_coverage(contracts_repo)

    def _row(short: str) -> dict:
        b = baseline.get(short, {})
        return {
            "short": short,
            "gate": b.get("gate"),
            "gate_name": b.get("gate_name"),
            "band": b.get("band"),
            "framework_can_evidence": _run_coverage_for_short(short, sub_results.get(short, {}), baseline),
        }

    # (1) A gate FIRED → the deciding axis is KNOWN (the firing gate). captured by definition.
    if gate_action and gate_hits:
        # Name the gate whose action actually WON (forced == max over action ranks), not merely
        # the first-iterated hit — otherwise the routing text could name a 'hold' gate while
        # reporting the 'veto' a different gate forced.
        _winning = next((h for h in gate_hits if h.get("action") == gate_action), gate_hits[0])
        top = _winning["short"]
        row = _row(top)
        row["framework_can_evidence"] = "captured"  # it fired → we evidenced it
        # A veto axis (e.g. safety) has a gate NAME but no lettered gate id → never render "gate None".
        _gid, _gname = row.get("gate"), row.get("gate_name")
        _gate_label = (
            f"gate {_gid} ({_gname})"
            if _gid and _gname
            else f"gate {_gid}"
            if _gid
            else f"the {_gname} gate"
            if _gname
            else f"the {top} gate"
        )
        silent = _admissible_but_silent(sub_results, baseline, {top})
        return {
            "basis": "gate_fired",
            "coverage_source": source,
            "deciding_axis": row,
            "admissible_but_silent": silent,
            "attribution_mismatch": _attribution_mismatch([row], silent),
            "routing": f"decided by {_gate_label}: {top} forced '{gate_action}'.",
        }

    # (1b) The THESIS DECIDER minted a `nominate` (Step 3) → the deciding axis is the thesis's
    # declared deciding axis, and the framework evidenced it by construction (the stage requires a
    # MEASURED favorable verdict there). Ranked above the positive tier because this basis carries the
    # RECOMMENDATION, whereas a positive tier only floors confidence.
    if thesis_record and thesis_record.get("applied"):
        top = (thesis_record.get("deciding") or {}).get("short")
        row = _row(top)
        row["framework_can_evidence"] = "captured"  # the conjunction required a measured verdict here
        corr = [h["short"] for h in thesis_record.get("corroborating") or []]
        rows = [row] + [_row(s) for s in corr]
        silent = _admissible_but_silent(sub_results, baseline, {top, *corr})
        return {
            "basis": "thesis_decider",
            "coverage_source": source,
            "deciding_axis": row,
            "deciding_axes": rows,
            "thesis": thesis_record.get("thesis"),
            "admissible_but_silent": silent,
            "attribution_mismatch": _attribution_mismatch(rows, silent),
            "routing": (
                f"decided by the '{thesis_record.get('thesis')}' thesis deciding axis: "
                f"{top}={(thesis_record.get('deciding') or {}).get('verdict')} forced 'nominate' "
                f"(corroborated by {', '.join(corr) or 'none'}; measured "
                f"{', '.join(m['field'] for m in thesis_record.get('measured_conjuncts') or []) or 'none'})."
            ),
        }

    # (2) A positive tier exists → the load-bearing axis is the strongest positive dimension.
    if positive_hits:
        shorts = sorted({h["short"] for h in positive_hits})
        rows = [_row(s) for s in shorts]
        # describe the routing from the actual BAND of the supporting axes, not a blanket "necessity
        # biology" — some positive axes are sufficiency-band (tractability_sm, surface_modality), so
        # labelling them "necessity" mis-states what was evidenced.
        _nec = any(r.get("band") == "necessity" for r in rows)
        _suf = any(r.get("band") and r.get("band") != "necessity" for r in rows)
        _kind = (
            "necessity + sufficiency evidenced"
            if _nec and _suf
            else "necessity biology evidenced"
            if _nec
            else "sufficiency / supporting evidence"
        )
        silent = _admissible_but_silent(sub_results, baseline, set(shorts))
        return {
            "basis": "positive_signal",
            "coverage_source": source,
            "deciding_axes": rows,
            "admissible_but_silent": silent,
            "attribution_mismatch": _attribution_mismatch(rows, silent),
            "routing": f"supported by {', '.join(shorts)} ({_kind}).",
        }

    # (3) Abstaining → report the NECESSITY gates we could NOT evidence this run + their standing.
    # This is the routing instruction: "the decision lives in a gate we're blind on."
    unevidenced = []
    for short, r in sub_results.items():
        if short not in baseline:
            continue
        if not _sub_result_has_signal(r):
            unevidenced.append(_row(short))
    # necessity first, then by weakest coverage (blind before partial) — the gates most likely
    # to be the reason we can't decide.
    unevidenced.sort(
        key=lambda x: (x.get("band") != "necessity", _COVERAGE_RANK.get(x.get("framework_can_evidence"), 0))
    )
    return {
        "basis": "abstention_coverage_gaps",
        "coverage_source": source,
        "unevidenced_gates": unevidenced,
        "routing": (
            "cannot decide from framework evidence; unevidenced gates (necessity "
            "first): "
            + ", ".join(f"{g['short']}[{g.get('gate')}/{g.get('framework_can_evidence')}]" for g in unevidenced)
            if unevidenced
            else "cannot decide; no gate produced a signal and no coverage map available."
        ),
    }


# --- Ordinal matrix VIEW ------------------------
#
# A gate × modality signal matrix, projected onto the ordinal scale for DISPLAY + RANKING.
# This is the "evidence matrix" made concrete for a single (target, indication) run: rows = the
# gates (sub-skills), columns = the 5 delivery modalities, cells = the strongest signal that
# gate's fired rules emit for that modality, shown as its ordinal.
#
# HONESTY (ordinal_view module contract): this is a labeled VIEW, NOT measurement and NOT a
# verdict input. It reads already-resolved fired-rule signals and never feeds back into any
# rule/resolver/gate. insufficient/not_applicable cells are off-scale (coverage), not low scores.
_MATRIX_MODALITIES = ("small_molecule", "degrader", "adc", "bite_tce", "antibody")


def _strongest_signal_for_modality(fired: list[dict], modality: str) -> Optional[str]:
    """The most-decisive signal a gate's fired rules emit for one modality channel. 'Most
    decisive' = lowest ordinal (killer < opposing < neutral < supportive); off-scale
    (insufficient/not_applicable) only when NO on-scale signal was emitted. Mirrors the
    display convention that a killer dominates a co-fired supportive in the same cell.

    DOMINANT PRECEDENCE: a `dominant: true` rule is the resolver's declared per-rule precedence,
    so its on-scale signal for the modality WINS the cell over co-fired NON-dominant signals —
    otherwise a non-dominant killer masks the dominant rule and the cell contradicts the resolved
    verdict. The canonical case: `strong-paralog-buffering-degrader-preferred` (dominant;
    small_molecule=opposing, degrader=supportive — the SM-vs-degrader split that DRIVES the
    `non_dependent_paralog_buffered` verdict) co-fires with `non-dependent-killer` (non-dominant;
    both=killer). Without this the degrader cell reads killer, inverting the degrader-preferred
    verdict + the authoritative modality_fit_by_channel. Among dominant rules (if >1) the
    most-decisive still wins, so a dominant killer is never softened. Falls back to the min over
    ALL fired only when NO dominant rule emits an on-scale signal for the modality (unchanged)."""
    on_scale: list[tuple[int, str]] = []
    dominant_on_scale: list[tuple[int, str]] = []
    off_scale: Optional[str] = None
    for r in fired:
        sig = (r.get("signals") or {}).get(modality)
        if sig is None:
            continue
        o = ordinal_view.ordinal_of(sig)
        if o is None:
            off_scale = off_scale or sig  # remember an off-scale signal as a fallback
        else:
            on_scale.append((o, sig))
            if r.get("dominant"):
                dominant_on_scale.append((o, sig))
    # a dominant rule's signal wins the cell (most-decisive among dominants); else the min over all.
    if dominant_on_scale:
        return min(dominant_on_scale, key=lambda t: t[0])[1]
    if on_scale:
        return min(on_scale, key=lambda t: t[0])[1]  # most-negative wins the cell
    return off_scale  # else an off-scale coverage marker (or None)


def _ordinal_matrix(sub_results: dict) -> dict:
    """Build the gate × modality ordinal-view matrix for this run (see section comment).
    Returns {rows: [{short, gate signals+ordinals per modality}], legend, _disclaimer}."""
    rows = []
    for short, r in sub_results.items():
        fired = r.get("fired") or []
        by_mod = {m: _strongest_signal_for_modality(fired, m) for m in _MATRIX_MODALITIES}
        view = ordinal_view.project_signals(by_mod)
        rows.append(
            {
                "short": short,
                "verdict": (r.get("verdict") or [None])[0],
                "cells": view["cells"],  # {modality: {signal, ordinal, on_scale}}
            }
        )
    return {
        "axes": {
            "rows": "gate (sub-skill)",
            "columns": list(_MATRIX_MODALITIES),
            "cell": "strongest signal for (gate, modality), ordinal-projected",
        },
        "rows": rows,
        "legend": ordinal_view.scale_legend(),
        # SPINE-SAFETY GUARD: this matrix is a per-CELL display view; it must NOT be aggregated down a
        # modality COLUMN into a per-modality call — multiple axes emit a negative surface signal for the
        # SAME normal-breadth liability, so a column rollup double-counts it (regresses an ADC-favorable
        # target to unfavorable). The authoritative per-modality spine is modality_fit_by_channel.
        "spine_safe": False,
        "spine_source": "modality_fit_by_channel",
        "_disclaimer": ordinal_view.scale_legend()["_disclaimer"]
        + (
            " NOT SPINE-SAFE: do not aggregate a modality COLUMN into a per-modality call — that "
            "double-counts a normal-breadth liability shared across axes. Use modality_fit_by_channel."
        ),
    }


# --- PRESENCE cross-modal reconciliation facet -------------------------------------------------
# tumor-presence emits a per-(measurement, sample_context) sub-verdict MATRIX + proxy-quality +
# normal-tissue comparators via its `_synthesis_facet` (carried by the fan-out as
# sub_results['expression']['synthesis_facet']). This thin reader surfaces it as a first-class
# facet for the synthesis prompt + evidence package — parallel to _biomarker_facet / _subtype_facet.
# VERDICT-INERT: presence is deliberately absent from _SHORT_TO_GATE, so this never moves the
# nomination. Its value: the LLM reasons over the deterministic cross-modal reconciliation (where
# RNA / protein / single-cell / normal-comparator AGREE or CONFLICT) instead of re-deriving it from
# raw card numbers. Returns None when tumor-presence is absent / supplied no facet.
def _presence_facet(sub_results: dict) -> Optional[dict]:
    expr = (sub_results or {}).get("expression") or {}
    return expr.get("synthesis_facet")


# (_selectivity_facet RETIRED 2026-09-03, Wave-3: a thin passthrough of
# sub_results['selectivity']['synthesis_facet'] whose only consumers — the legacy md/html renderers — are
# gone; render_review reads the selectivity question_table off the skill_report[] spine. The synthesis_facet
# itself is still carried by the fan-out + on target_report.skill_reports.selectivity.)


# Dependency claim-vector facet: functional-requirement's `_synthesis_facet`,
# carried by the fan-out as sub_results['dependency']['synthesis_facet']. Parallel to _presence_facet —
# a thin reader surfacing the dependency SIGNAL decomposition (claim_vector DEP/SEL/COND/CHEM +
# key_signals + confidence annotations) for the synthesis prompt + evidence package. The per-axis
# certainty roll-up is the SEPARATE certainty_by_axis sidecar; this is the SIGNAL half.
# VERDICT-INERT — dependency's verdict is owned by its resolver; this projection never moves it.
# Returns None when functional-requirement is absent / supplied no facet.
# ── Competitor cross-reference facet (2026-08-24) ─────────────────────────────────────────────
# The competitor-landscape VALUE-ADD: cross-reference the Open Targets competitor field (carried on
# the differentiation facet as competitor_modality_landscape) against the framework's OWN
# surface-modality-fit verdict — is the framework's preferred modality VALIDATED by clinical
# precedent, or CONTRARIAN to it (an approved competitor validates a DIFFERENT modality)? And is the
# indication CROWDED (an approved competitor) or WHITE SPACE (none)? DETERMINISTIC + VERDICT-INERT:
# reads two already-computed sub-results, emits positioning hooks, and NEVER touches the gate /
# recommendation / confidence. The framework surfaces the hooks; the TPP author writes the claim.
# (This is the DLL3 archetype: framework says adc_preferred_tce_unsafe, but the APPROVED competitor is
# a TCE and the ADC failed at PHASE_3 → modality_contrarian=True — an independent check on the surface
# call, exactly the round-1 ADC/TCE arbitration-inversion this layer was built to surface.)
_COMPETITOR_STAGE_ORD = {
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
_COMPETITION_DENSITY = {
    "approved_competitor": "crowded",
    "active_clinical_competitor": "contested",
    "early_or_preclinical_competitor": "emerging",
    "no_known_competitor": "white_space",
}


def _framework_preferred_modalities(surface_verdict) -> set:
    """Map a surface-modality-fit verdict token -> the biologics modality/ies the framework prefers.
    Empty set = no clear surface preference (neither_viable / unsafe / isoform_undefined / ambiguous)."""
    v = surface_verdict or ""
    if v == "both_viable":
        return {"ADC", "TCE"}
    if v.startswith("adc_preferred"):  # adc_preferred / adc_preferred_tce_unsafe / adc_preferred_tce_escape_risk
        return {"ADC"}
    if v in ("tce_preferred", "tce_escape_risk"):
        return {"TCE"}
    if v.startswith("pmhc_tce_supported"):  # peptide-MHC / TCR-mimic route (surface-dead intracellular
        # target); incl. #2113 pmhc_tce_supported_presentation_unconfirmed (caveated — normal-presentation
        # unmeasured — but still a pMHC-TCE-preferring route for this display-only cross-ref).
        return {"TCE"}
    return set()


def _competitor_crossref_facet(sub_results: dict) -> Optional[dict]:
    """DETERMINISTIC, VERDICT-INERT cross-ref of the OT competitor field vs the framework's own
    surface-modality-fit verdict. Returns None when there is no competitor signal to cross-reference."""
    facet = ((sub_results or {}).get("differentiation") or {}).get("synthesis_facet") or {}
    comp_class = facet.get("competitor_class")
    if not comp_class or comp_class == "insufficient":
        return None
    ml = facet.get("competitor_modality_landscape") or {}
    density = _COMPETITION_DENSITY.get(comp_class, "unknown")
    approved_modalities = sorted({m for m, s in ml.items() if (s or {}).get("approved")})

    surface_verdict = ((sub_results.get("surface_modality") or {}).get("verdict") or [None])[0]
    pref = _framework_preferred_modalities(surface_verdict)

    positioning = {}
    for mod in sorted(pref):
        slot = ml.get(mod) or {}
        if slot.get("approved"):
            positioning[mod] = "validated_approved"
        elif _COMPETITOR_STAGE_ORD.get(slot.get("max_clinical_stage") or "", 0) >= _COMPETITOR_STAGE_ORD["PHASE_2"]:
            positioning[mod] = "attempted_not_approved"  # candidate failed / failing precedent
        elif slot:
            positioning[mod] = "in_development"
        else:
            positioning[mod] = "no_precedent"

    hooks: list = []
    contrarian = bool(pref) and bool(approved_modalities) and not (pref & set(approved_modalities))
    if contrarian:
        hooks.append(
            f"The framework's preferred surface modality {sorted(pref)} is NOT the approved clinical "
            f"modality here — the approved competitor(s) validate {approved_modalities}. The modality "
            f"preference is CONTRARIAN to clinical precedent; re-examine the surface-modality-fit call."
        )
    for mod in sorted(pref):
        if positioning.get(mod) == "attempted_not_approved":
            st = (ml.get(mod) or {}).get("max_clinical_stage")
            hooks.append(
                f"{mod}: a competitor reached {st} but was not approved (candidate failed precedent) — "
                f"de-risk before committing to {mod}."
            )
    if density == "white_space":
        hooks.append(
            "No competitor in the Open Targets clinical field — potential white space (verify "
            "undisclosed / preclinical / patent-stage assets before claiming first-mover)."
        )
    if density == "crowded" and (pref & set(approved_modalities)):
        hooks.append(
            f"Crowded at the framework's preferred modality {sorted(pref & set(approved_modalities))} "
            f"(an approved competitor exists) — differentiation must come from biomarker/subtype "
            f"selection, a next-gen format, or a distinct indication."
        )

    return {
        "competition_density": density,
        "competitor_class": comp_class,
        "competitor_indication_scope": facet.get("competitor_indication_scope"),
        "n_competitor_programs": facet.get("n_competitor_programs"),
        "competitor_approved_agents": facet.get("competitor_approved_agents"),
        "competitor_late_stage_non_approved": facet.get("competitor_late_stage_non_approved"),
        "competitor_modalities_approved": approved_modalities,
        "surface_modality_verdict": surface_verdict,
        "framework_preferred_modality": sorted(pref),
        "modality_positioning": positioning,
        "modality_contrarian": contrarian,
        "differentiation_hooks": hooks,
        "_facet_note": (
            "DETERMINISTIC competitor cross-ref (verdict-inert): the Open Targets competitor "
            "field vs the framework's own surface-modality-fit verdict. Surfaces positioning hooks "
            "(crowded/white-space, modality validated/contrarian); the TPP author writes the claim."
        ),
    }


# --- PER-AXIS (strength, certainty) sidecar assembly (CERTAINTY_MODEL) ------------------------
# Each verdict-bearing sub-skill MAY expose `_strength_certainty`; the fan-out captures it as
# sub_results[short]['strength_certainty'] (None for skills without the hook). This thin reader
# assembles the present ones into a {short: {strength, certainty{level, coverage, corroboration,
# unknown_mass}, provenance, _model_ref}} block for nomination.json + the panel. VERDICT-INERT — a
# reliability projection beside the verdict, NEVER in `sub_verdicts` / the recommendation spine.
# Returns {} until an axis opts in (functional-requirement `dependency` is the reference axis).
def _certainty_by_axis(sub_results: dict) -> dict:
    out = {}
    for short, r in (sub_results or {}).items():
        sc = (r or {}).get("strength_certainty")
        if isinstance(sc, dict) and sc:
            out[short] = sc
    return out


# --- FACTORED CLAIM-RECORD SHADOW assembly (M1; VERDICT_REPRESENTATION_MIGRATION.md) ------------
# Each verdict-bearing sub-skill MAY expose `_claim_record`; the fan-out captures it as
# sub_results[short]['claim_record_shadow'] (None for skills without the hook). This thin reader
# assembles the present ones into a {short: <factored record>} block surfaced beside the verdict
# spine. CONSUMED BY NOTHING — the shadow exists so the M2 render-equivalence proof
# (rho(record) == legacy token) has records to compare; it NEVER enters `sub_verdicts` / the
# recommendation spine. Returns {} until an axis opts in (genomic + selectivity are the first).
def _claim_record_shadow_by_axis(sub_results: dict) -> dict:
    out = {}
    for short, r in (sub_results or {}).items():
        rec = (r or {}).get("claim_record_shadow")
        if isinstance(rec, dict) and rec:
            out[short] = rec
    return out


# --- skill_report[] SPINE + roll-up (docs/UNIFIED_OUTPUT_CONTRACT.md, target_report section) ----------
# Every wired skill emits a per-skill `skill_report` (via _skills_common.skill_report.build_skill_report),
# carried at sub_results[short]['synthesis_facet']['skill_report']. These two readers are the FIRST
# consumers of that spine inside target_report: `_skill_reports_by_short` assembles the {short: report}
# spine, and `build_skill_report_rollup` PROJECTS it — grouping by role and cross-checking target-level
# INV-6 (the recommendation must not read more favorable than the gating signals support). VERDICT-INERT:
# they read only the emitted reports + the already-built target_call, and NEVER mutate the recommendation
# spine (target_call stays the sole owner). This closes the "emitted-but-not-consumed" gap: the rollups
# begin reading the skill_report[] spine rather than only the legacy sub_results reach-ins.
def _skill_reports_by_short(sub_results: dict) -> dict:
    """The per-skill skill_report[] spine as an ordered {short: report} dict (SUB_SKILLS order), from each
    sub-result's synthesis_facet. Tolerant of None / missing / non-dict / the facet-less subtype tier."""
    out = {}
    for short, r in (sub_results or {}).items():
        sr = ((r or {}).get("synthesis_facet") or {}).get("skill_report")
        if isinstance(sr, dict) and sr:
            out[short] = sr
    return out


def _modality_scope_by_axis(sub_results: dict) -> dict:
    """{short: modality_scope} — the per-axis FOR-WHAT projection, read FROM THE skill_report[] SPINE
    (`synthesis_facet.skill_report.modality_scope`) rather than the legacy `claim_record_shadow`
    reach-in. The spine value is emitted by the SAME per-skill helper the shadow uses, so this is
    byte-identical to `_claim_record_shadow_by_axis(...)[short]['modality_scope']`; the shadow is a
    FALLBACK only for an axis whose report is absent (e.g. the facet-less subtype tier) or predates the
    modality_scope slot. Spine-first is the migration (contract §100-128): the modality_fit rollup now
    reads the wired spine, not a raw sub_results reach-in."""
    reports = _skill_reports_by_short(sub_results)
    shadow = _claim_record_shadow_by_axis(sub_results)
    out: dict = {}
    for short in {*reports, *shadow}:
        ms = (reports.get(short) or {}).get("modality_scope")
        if not isinstance(ms, dict):
            ms = (shadow.get(short) or {}).get("modality_scope")  # spine absent → legacy fallback
        if isinstance(ms, dict) and ms:
            out[short] = ms
    return out


# canonical polarity → ordinal rank (mirrors _skills_common.ordinal_view; off-scale states unranked)
_SKILL_REPORT_POLARITY_RANK = {"killer": -3, "opposing": -1, "neutral": 0, "supportive": 2}
# recommendation tokens that read as a POSITIVE (go) call, across the gate + LLM vocabularies
_POSITIVE_RECOMMENDATIONS = frozenset({"nominate", "go", "advance"})


# A gating axis's modality-channel family — the channels whose axis-applicability governs whether the
# axis's polarity is a real call or a category error. surface_modality is the biologics (ADC/TCE/antibody)
# call; tractability_sm is the intracellular (small-molecule/degrader) call. When ALL of an axis's family
# channels are masked `not_applicable_by_axis` in modality_fit_by_channel (a curated single-axis target —
# e.g. biologics for an INTRACELLULAR target, or SM/degrader for a pure SURFACE antigen), the axis is a
# category error for this target and its `killer` polarity must NOT count as an against-signal.
_GATING_AXIS_CHANNEL_FAMILY = {
    "surface_modality": ("adc", "bite_tce", "antibody"),
    "tractability_sm": ("small_molecule", "degrader"),
}


def _axis_masked_not_applicable(short: str, modality_fit_by_channel: dict) -> bool:
    """True when `short`'s whole modality-channel family is masked `not_applicable_by_axis` — i.e. the
    axis is a category error for this target's curated biology axis (the same mask that turns biologics
    into `not_applicable_by_axis` for an intracellular target in `_modality_fit_by_channel`)."""
    channels = _GATING_AXIS_CHANNEL_FAMILY.get(short)
    if not channels or not modality_fit_by_channel:
        return False
    fits = [(modality_fit_by_channel.get(c) or {}).get("fit") for c in channels]
    present = [f for f in fits if f is not None]
    return bool(present) and all(f == _NOT_APPLICABLE_BY_AXIS for f in present)


def build_skill_report_rollup(
    skill_reports_by_short: dict,
    target_call: "Optional[dict]" = None,
    modality_fit_by_channel: "Optional[dict]" = None,
) -> dict:
    """VERDICT-INERT projection over the skill_report[] spine. Groups the per-skill reports by role
    (gating / descriptive / inert), records the GATING skills' canonical polarities + the peak
    (most-favorable) gating signal, and cross-checks target-level INV-6: the recommendation must not read
    MORE favorable than the gating signals support — a gating `killer` polarity alongside a POSITIVE
    recommendation is surfaced as `recommendation_exceeds_signals`. This is a coherence FLAG for the
    reader; it NEVER mutates target_call (the sole recommendation owner).

    biology-axis applicability mask (#1203): a gating axis whose whole modality-channel family is masked
    `not_applicable_by_axis` (from `modality_fit_by_channel`) is a CATEGORY ERROR for the target — e.g.
    surface_modality=`killer`/`neither_viable` on an INTRACELLULAR target, whose biologics channels are
    correctly `not_applicable_by_axis`. Its `killer` polarity is relabeled `not_applicable` so it does not
    count in `killer_axes` and cannot spuriously fire `recommendation_exceeds_signals` on a correct
    `nominate`. Mirrors `_channel_applicable_for_axis`; no-op when `modality_fit_by_channel` is absent."""
    mfc = modality_fit_by_channel or {}
    by_role: dict = {"gating": [], "descriptive": [], "inert": []}
    gating_polarities: dict = {}
    axis_not_applicable: list = []
    for short, sr in (skill_reports_by_short or {}).items():
        role = sr.get("role")
        polarity = sr.get("polarity")
        if polarity == "killer" and _axis_masked_not_applicable(short, mfc):
            polarity = "not_applicable"  # category error for this target's biology axis — not an against-signal
            axis_not_applicable.append(short)
        by_role.setdefault(role, []).append({"short": short, "call": sr.get("call"), "polarity": polarity})
        if role == "gating":
            gating_polarities[short] = polarity
    ranks = [_SKILL_REPORT_POLARITY_RANK[p] for p in gating_polarities.values() if p in _SKILL_REPORT_POLARITY_RANK]
    peak = max(ranks) if ranks else None  # most-favorable gating signal on the ordinal scale
    killer_axes = [s for s, p in gating_polarities.items() if p == "killer"]
    rec = target_call.get("recommendation") if isinstance(target_call, dict) else None
    positive_rec = str(rec).lower() in _POSITIVE_RECOMMENDATIONS
    return {
        "by_role": by_role,
        "gating_polarities": gating_polarities,
        "peak_gating_rank": peak,
        "killer_axes": killer_axes,
        # axes whose `killer` was relabeled `not_applicable` because their modality family is a category
        # error for this target's curated biology axis (biology-axis applicability mask, #1203).
        "axis_not_applicable": axis_not_applicable,
        "recommendation": rec,
        # INV-6 at the target level (verdict-inert coherence flag): a killer gating signal should have
        # forced a non-positive recommendation; surface — never silently allow — the mismatch.
        "recommendation_exceeds_signals": bool(killer_axes) and positive_rec,
        "_note": (
            "VERDICT-INERT projection over the skill_report[] spine; groups by role + flags any "
            "target-level INV-6 breach. target_call remains the sole recommendation owner."
        ),
    }


# --- MODALITY-FIT-BY-CHANNEL rollup (M4 move #4; VERDICT_REPRESENTATION §8 / migration §3) ----------
# The SECOND factored-record consumer, and the answer to the KRAS motivating case: a target is not
# "safe/unsafe" or "druggable/undruggable" as a SCALAR — it is favorable for SOME modalities and not
# others. This rolls up each axis's record `modality_scope` into a PER-CHANNEL favorability, so the
# nomination can say "nominable as an allele-selective small molecule, hold as a degrader" instead of
# collapsing to one call. Deterministic worst-case CONJUNCTION across axes (the selectivity
# best-practice: a target is only as deliverable via a channel as its WEAKEST modality-relevant axis
# on that channel). VERDICT-INERT — a projection over the shadow, never the recommendation spine.
_MODALITY_FIT_ORDER = {"unfavorable": 0, "conditional": 1, "favorable": 2}  # worst -> best
# a specific channel inherits from the record's `_refinements[channel]` if present, else its BASE
# channel: small_molecule for degrader (a PROTAC is a small molecule), biologics for adc/bite_tce/antibody.
_CHANNEL_BASE = {
    "small_molecule": "small_molecule",
    "biologics": "biologics",
    "degrader": "small_molecule",
    "adc": "biologics",
    "bite_tce": "biologics",
    "antibody": "biologics",
}


def _channel_value(modality_scope: dict, channel: str):
    """The axis's favorability for `channel`: an explicit _refinements override wins, else the base
    channel value. Returns None when the axis says nothing (base 'na'/absent) about that channel."""
    ref = modality_scope.get("_refinements") or {}
    if channel in ref:
        v = ref[channel]
    else:
        v = modality_scope.get(_CHANNEL_BASE.get(channel, channel))
    return v if v in _MODALITY_FIT_ORDER else None  # 'na' / None → axis is silent on this channel


# --- MAGNITUDE-BORDERLINE consumer (M4 coarsen-magnitude; VERDICT_REPRESENTATION move #5 / R5) -------
# Over-precision audit made actionable: a categorical verdict HARD-CUTS a continuous measure at a
# boundary, so a call whose value barely cleared its cutpoint is knife-edge — the token asserts a
# crispness the data doesn't support. The factored record retains the raw value + distance_to_cut, so
# this reads them back and flags axes whose call sits within a NEAR-THRESHOLD band of its cutpoint.
# Scale-aware (the band is in the measure's own units). VERDICT-INERT — a fragility signal for the
# reader, never the spine. Empty until an axis populates magnitude.value + distance_to_cut (selectivity
# is the first: max|log2FC| vs the strong>=1.5 / modest>=0.5 cutpoints).
_BORDERLINE_BAND = {"log2fc": 0.25}  # within this many units of the cutpoint = borderline; keyed LOWERCASE


def _borderline_band(scale):
    """The borderline band for a scale, CASE-INSENSITIVELY. The band was keyed 'log2fc' but a
    spec-derived magnitude carries the SALIENCE_SPECS scale 'log2FC' (capital) — so the day
    tumor-selectivity's hand-written magnitude becomes spec-derived, a case-sensitive lookup would
    silently return None and empty the borderline list. Presence stays 0 either way: its magnitude is
    level-only (scale=None), so it can never match any band."""
    return _BORDERLINE_BAND.get(scale.lower()) if isinstance(scale, str) else None


def _magnitude_borderline(sub_results: dict) -> list[dict]:
    shadow = _claim_record_shadow_by_axis(sub_results)
    out: list[dict] = []
    for short in sorted(shadow):
        mag = ((shadow[short] or {}).get("finding") or {}).get("magnitude") or {}
        value, scale, dist = mag.get("value"), mag.get("scale"), mag.get("distance_to_cut")
        band = _borderline_band(scale)
        if value is None or dist is None or band is None:
            continue  # axis has no continuous value / cutpoint to be borderline on
        if abs(dist) <= band:
            out.append(
                {
                    "axis": short,
                    "level": mag.get("level"),
                    "value": value,
                    "scale": scale,
                    "distance_to_cut": dist,
                    "band": band,
                }
            )
    return out


# biology-axis APPLICABILITY MASK (coherence fix): a channel that is a CATEGORY ERROR for the target's
# curated biology axis (a small molecule / degrader for a pure SURFACE antigen; an ADC / TCE / antibody
# for a pure INTRACELLULAR target) is marked `not_applicable_by_axis` — distinct from the silent `na`
# ("no axis spoke to it") — so the per-modality view offers only BIOLOGICALLY POSSIBLE channels, not
# just individually-favorable ones. Driven directly by the curated `plausible_modalities` (self-
# maintaining). GATED to fire ONLY for a curated, SINGLE-axis target: a `multi_axis` dual (EGFR = kinase
# AND antigen; ERBB2, MET) keeps ALL channels live — the mask must never foreclose a legitimate dual
# arm (biology_axis.py is a de-emphasis STEER, not an eraser). Uncurated/unknown → no mask.
_NOT_APPLICABLE_BY_AXIS = "not_applicable_by_axis"
_BIOLOGIC_CHANNELS = ("adc", "bite_tce", "antibody")


def _channel_applicable_for_axis(channel: str, plausible: set) -> bool:
    """Is `channel` biologically possible for a target whose axis admits `plausible` modalities?
    biologics(base) is applicable iff any specific biologic channel is plausible."""
    if channel == "biologics":
        return any(c in plausible for c in _BIOLOGIC_CHANNELS)
    return channel in plausible


def _modality_fit_by_channel(sub_results: dict, axis_info: Optional[dict] = None) -> dict:
    """{channel: {fit, limiting_axis, by_axis}} — worst-case conjunction of every axis's record
    modality_scope. `fit` is the min (worst) favorability across the axes that speak to the channel;
    'na' when no axis constrains it; limiting_axis names the axis that set the worst.

    biology-axis mask: when `axis_info` is a curated, single-axis target, a channel outside the axis's
    `plausible_modalities` is overridden to 'not_applicable_by_axis' (a category error, not a call).

    Reads each axis's modality_scope from the skill_report[] SPINE (`_modality_scope_by_axis`,
    contract §100-128) — byte-identical to the former `claim_record_shadow` reach-in (same source), now
    sourced from the wired spine so the rollup provenance links back to the per-skill report."""
    scope_by_axis = _modality_scope_by_axis(sub_results)
    ax = axis_info or {}
    plausible = set(ax.get("plausible_modalities") or [])
    mask_active = bool(ax.get("curated")) and not ax.get("multi_axis") and bool(plausible)

    out: dict = {}
    for channel in ("small_molecule", "biologics", "degrader", "adc", "bite_tce", "antibody"):
        # coherence mask FIRST — a category-error channel is not_applicable regardless of any axis's fit.
        if mask_active and not _channel_applicable_for_axis(channel, plausible):
            out[channel] = {
                "fit": _NOT_APPLICABLE_BY_AXIS,
                "limiting_axis": None,
                "by_axis": {},
                "masked_by_axis": ax.get("biology_axis"),
            }
            continue
        by_axis: dict = {}
        for short, ms in scope_by_axis.items():
            v = _channel_value(ms, channel)
            if v is not None:
                by_axis[short] = v
        if not by_axis:
            out[channel] = {"fit": "na", "limiting_axis": None, "by_axis": {}}
            continue
        limiting_axis = min(by_axis, key=lambda s: _MODALITY_FIT_ORDER[by_axis[s]])
        out[channel] = {"fit": by_axis[limiting_axis], "limiting_axis": limiting_axis, "by_axis": by_axis}
    return out


# --- MODALITY-CONJUNCTION facet (cross-lens; the composed layer's job) --------------------------
# The modality nomination presence deliberately CANNOT mint (it is modality-blind). This is where
# it is completed: the presence CLAIM VECTOR (A abundance / C malignant-intrinsic / homogeneity)
# is conjoined with the CROSS-lens gates only target-profile holds — surface accessibility
# (surface-modality-fit fit_class), the tumor-vs-normal WINDOW (tumor-selectivity), and safety.
# A conjunction gated by the WEAKEST required gate (never an average); confidence-relevant, but
# VERDICT-INERT — additive to nomination.json, never touches the recommendation spine (like the
# biomarker / subtype / presence facets). Returns None if the presence claim vector is absent.
def _modality_gate(sig):
    return {
        "strong": "pass",
        "moderate": "pass",
        "weak": "conditional",
        "absent": "fail",
        "negative": "fail",
        "unmeasured": "unknown",
    }.get(sig, "unknown")


# selectivity verdict -> (TCE window, ADC window). TCE has no therapeutic-index buffer, so a broad
# normal footprint is a killer; ADC tolerates more via TI.
_WINDOW = {
    "strong_tumor_selective": ("pass", "pass"),
    "modest_tumor_selective": ("conditional", "pass"),
    "field_effect_tumor_selective": ("conditional", "conditional"),
    "selective_but_broadly_normal": ("fail", "conditional"),
    "discordant_across_comparators": ("unknown", "unknown"),
}
# surface-modality-fit fit_class -> (TCE surface, ADC surface).
_SURFACE = {
    "both_viable": ("pass", "pass"),
    "TCE_preferred": ("pass", "conditional"),
    "ADC_preferred": ("conditional", "pass"),
    "neither_viable": ("fail", "fail"),
}
_RANK = {"fail": 0, "unknown": 1, "stub": 1, "conditional": 2, "pass": 3}


def _sub_verdict(sub_results, key):
    v = ((sub_results or {}).get(key) or {}).get("verdict")
    return v[0] if isinstance(v, (list, tuple)) and v else (v if isinstance(v, str) else None)


def _presence_signal_from_spine(sub_results: dict, key: str) -> Optional[str]:
    """The presence claim-`key` (A/C) signal read from the tumor-presence skill_report[] SPINE
    (`skill_report.claim_chips[key].signal`), or None if the report/chip is absent. The chip signal is
    the SAME value the presence claim_vector atom carries (chips are a projection of it), so this is a
    byte-identical spine read of what `_modality_conjunction_facet` used to reach into the raw
    claim_vector for (contract §100-128)."""
    sr = ((sub_results or {}).get("expression", {}).get("synthesis_facet") or {}).get("skill_report")
    for chip in (sr or {}).get("claim_chips") or []:
        if isinstance(chip, dict) and chip.get("key") == key:
            return chip.get("signal")
    return None


def _modality_conjunction_facet(sub_results: dict) -> Optional[dict]:
    facet = (sub_results or {}).get("expression", {}).get("synthesis_facet") or {}
    cv = facet.get("claim_vector") if isinstance(facet.get("claim_vector"), dict) else {}
    # Read the presence inputs FROM THE SPINE (skill_report claim_chips for A/C signals, claim_scalars for
    # the homogeneity coordinate), falling back to the raw claim_vector for a report that predates those
    # slots. Byte-identical (the spine is a lossless projection of the claim_vector). The three GATING
    # verdicts below stay on `_sub_verdict` — they read the raw resolved `verdict_pair`, which is NOT the
    # (sometimes reconciled) skill_report.call, so re-pointing them would change the mapped window/surface.
    sr = facet.get("skill_report") or {}
    if not cv and not sr.get("claim_chips"):
        return None  # no presence claim vector on EITHER path → graceful
    scalars = sr.get("claim_scalars") if isinstance(sr.get("claim_scalars"), dict) else {}
    _a_sig = _presence_signal_from_spine(sub_results, "A")
    _c_sig = _presence_signal_from_spine(sub_results, "C")
    a_raw = _a_sig if _a_sig is not None else (cv.get("A") or {}).get("signal")
    c_raw = _c_sig if _c_sig is not None else (cv.get("C") or {}).get("signal")
    A = _modality_gate(a_raw)
    C = _modality_gate(c_raw)
    hom = scalars.get("homogeneity", cv.get("homogeneity"))
    hom_gate = {"homogeneous": "pass", "moderately_homogeneous": "conditional", "heterogeneous": "fail"}.get(
        hom, "unknown"
    )
    sel_v = _sub_verdict(sub_results, "selectivity")
    surf_v = _sub_verdict(sub_results, "surface_modality")
    safe_v = _sub_verdict(sub_results, "safety")
    tce_w, adc_w = _WINDOW.get(sel_v, ("unknown", "unknown"))
    tce_s, adc_s = _SURFACE.get(surf_v, ("unknown", "unknown"))

    def rollup(gates):
        stat = [s for _, s in gates]
        head = (
            "FAIL"
            if any(s == "fail" for s in stat)
            else "CONDITIONAL"
            if any(s in ("conditional", "unknown", "stub") for s in stat)
            else "PASS"
        )
        weakest = min(gates, key=lambda g: _RANK.get(g[1], 1))[0]
        return {"call": head, "weakest_gate": weakest, "gates": dict(gates)}

    adc = rollup(
        [
            ("presence_abundance", A),
            ("presence_malignant(tolerant)", "conditional" if C == "conditional" else C),
            ("surface", adc_s),
            ("window", adc_w),
        ]
    )
    tce = rollup(
        [
            ("presence_abundance", A),
            ("presence_malignant", C),
            ("homogeneity", hom_gate),
            ("surface", tce_s),
            ("window", tce_w),
        ]
    )
    return {
        "ADC": adc,
        "TCE": tce,
        "inputs": {
            "presence_A": a_raw,
            "presence_C": c_raw,
            "homogeneity": hom,
            "selectivity_verdict": sel_v,
            "surface_fit_class": surf_v,
        },
        "safety_signal": safe_v,
        "_disclaimer": (
            "Cross-lens modality nomination — VERDICT-INERT (never touches overall_recommendation). "
            "Conjoins the presence claim vector (modality-blind) with the surface-accessibility "
            "(surface-modality-fit), tumor-vs-normal WINDOW (tumor-selectivity), and safety gates that "
            "only the composed layer holds. Gated by the WEAKEST required gate, not an average. Safety "
            "is surfaced as a signal (it has its own resolver); weigh it, do not read this as a safety call."
        ),
    }


_FRAGILITY_LEGEND = (
    "Verdict FRAGILITY (flip-stability): re-runs the deterministic resolver over single-rule-perturbed "
    "fired sets. target_index = worst-case fraction of a gate's verdict-movable rules whose toggle "
    "changes its DECISION ROLE (how solid each axis's CALL is). recommendation_fragility_index = worst "
    "case whose toggle crosses the KILL boundary (how solid the GO/NO-GO is) — this drives `contested`. "
    "0 = robust; higher = a call one plausible rule-change could flip. A structural sensitivity "
    "measure — NOT a probability the target succeeds, and never summed or averaged."
)


def _load_contested_threshold(contracts_repo: Path | None = None) -> Optional[dict]:
    """Load the optional `contested_threshold` stanza from the nomination-gate vocab, or None if
    absent/malformed. NEVER-FABRICATE contract: absence → None → the facet emits contested=None (no
    flag). A missing threshold can only make the facet emit LESS (no contested), never fabricate one;
    and the flag is verdict-inert either way, so this is safe."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        ct = data.get("contested_threshold")
        if isinstance(ct, dict) and isinstance(ct.get("fragility_index_min"), (int, float)):
            return ct
        return None
    except Exception:  # noqa: BLE001 — absence/parse failure → no contested flag (verdict-inert)
        return None


def _decision_role(short: str, verdict: str, gate_map: dict, pos_map: dict, contra_set: set) -> str:
    """The axis's role in the nomination decision for a given verdict: 'kill:<action>' /
    'positive:<weight>' / 'contradiction' / 'neutral'. Pure lookup over the loaded vocab maps."""
    if (short, verdict) in gate_map:
        return f"kill:{gate_map[(short, verdict)]}"
    if (short, verdict) in pos_map:
        return f"positive:{pos_map[(short, verdict)]}"
    if (short, verdict) in contra_set:
        return "contradiction"
    return "neutral"


def _cross_gate_shared_evidence(sub_results: dict) -> dict:
    """VERDICT-INERT transparency facet (VERDICT_REPRESENTATION.md — de-dup cross-gate cards). An input
    card that fires signal into >1 gate's verdict makes those gate calls CORRELATED, not independent
    corroboration — a consumer/synthesis that counts N agreeing gates as N independent votes overstates
    confidence (the measured cross-gate redundancy: the ~11 verdict gates carry only ~4 independent axes;
    e.g. normal-tissue-liability drives safety+surface, crispr-dependency drives dependency+safety). This
    surfaces the shared inputs so the roll-up can discount them. Never touches the verdict/gate/recommendation.
    Computed from each sub-result's OWN fired rules (their card_id) — no re-read of the rules files."""
    card_to_gates: dict = {}
    for short, r in sub_results.items():
        if not isinstance(r, dict):
            continue
        for f in r.get("fired") or []:
            cid = f.get("card_id") if isinstance(f, dict) else None
            if cid:
                card_to_gates.setdefault(cid, set()).add(short)
    shared = {cid: sorted(gates) for cid, gates in card_to_gates.items() if len(gates) > 1}
    # correlated gate pairs (the actionable read for the synthesis: don't double-count these)
    correlated_gates = sorted(
        {tuple(sorted((a, b))) for gates in shared.values() for a in gates for b in gates if a < b}
    )
    return {
        "shared_input_cards": {c: shared[c] for c in sorted(shared)},
        "correlated_gate_pairs": [list(p) for p in correlated_gates],
        "_note": "Cards driving >1 gate's fired signal → those gate verdicts are CORRELATED (share "
        "evidence), NOT independent corroboration. Roll-ups / synthesis must not treat "
        "co-firing correlated gates as independent agreement.",
    }


def _fragility_facet(
    sub_results: dict,
    subtypes: Optional[list[str]] = None,
    contracts_repo: Path | None = None,
    modality: str | None = None,
) -> dict:
    """Verdict-inert flip-stability facet (see section header). Emitted in nomination.json; never
    touches the verdict / gate / recommendation. `modality` is threaded so the decision-relevant
    axis set includes modality-scoped surface positives under an explicit biologics modality —
    keeping the fragility scan consistent with what the gate/positive tier actually reads."""
    gate_map, _gsrc = _load_gate_verdicts(contracts_repo)
    pos_map, contra_set, _cfg, _psrc = _load_positive_signals(contracts_repo, modality=modality)
    contra_set = contra_set - _reconciled_contradiction_keys(sub_results, contracts_repo)  # cross-axis reconcile
    baseline, _covsrc = _load_gate_coverage(contracts_repo)

    # Decision-relevant axes = every sub_skill short the gate / positive / contradiction vocab reads.
    decision_shorts = {s for (s, _v) in gate_map} | {s for (s, _v) in pos_map} | {s for (s, _v) in contra_set}

    per_axis: dict = {}
    fragilities: list[float] = []  # worst-case CALL fragility (any decision-role change)
    rec_fragilities: list[float] = []  # worst-case RECOMMENDATION fragility (kill-boundary crossing)
    blind_decision_axes: list[str] = []
    # ACQUISITION BACKLOG (VERDICT_REPRESENTATION.md — ignorance≠negation). A decision-relevant axis
    # that is BLIND this run is held by IGNORANCE (a coverage gap), NOT by a measured negative — the two
    # license opposite next actions: ACQUIRE the data vs KILL the target. Measured-negative KILLs are the
    # gate's veto/hold hits (surfaced there); this list is the "go measure X" backlog the composed layer
    # otherwise drops. Verdict-INERT (fragility facet); names the missing cards + their availability_state.
    acquisition_backlog: list[dict] = []
    # M4 insufficient-split (first factored-record CONSUMER): the record's finding.availability is the
    # authoritative per-axis absence TYPE. It resolves a THIRD state the has_signal/blind logic could not
    # express — a MEASURED-but-UNDERPOWERED verdict (availability=='insufficient'): the axis HAS signal
    # (so it is not blind/acquire) yet the call is thin. That licenses a distinct action — STRENGTHEN
    # (add cohort/power), not ACQUIRE (wire/get data) and not KILL (measured negative). Sourced from
    # claim_record_shadow[short].finding.availability (the M1 shadow), verdict-INERT.
    underpowered_axes: list[dict] = []

    def _record_availability(res: dict):
        return (((res or {}).get("claim_record_shadow") or {}).get("finding") or {}).get("availability")

    for short in sorted(decision_shorts):
        r = sub_results.get(short)
        if r is None:
            continue  # a decision-relevant axis not present this run (e.g. subtype_fit w/o --subtypes)
        has_signal = _sub_result_has_signal(r)
        coverage = _run_coverage_for_short(short, r, baseline)
        # Gating axes resolve via _SHORT_TO_GATE; a resolver-backed CONFIDENCE axis (cis_coherence) is
        # flip-scanned via _CONFIDENCE_AXIS_TO_GATE so its call-fragility folds into target_index. It has
        # no `gates` action, so _decision_role never returns "kill:" for it → it can never contribute a
        # recommendation flip (contested stays untouched); this only widens call-fragility coverage.
        gate = _SHORT_TO_GATE.get(short) or _CONFIDENCE_AXIS_TO_GATE.get(short)

        if not has_signal:
            # An un-evidenced axis is an EVIDENCE GAP, not a fragile verdict (measured-vs-null
            # discipline): it has no verdict to flip. Tracked separately, NOT folded into the flip
            # index — coverage/blindness is the deciding-axis router's responsibility, not fragility's.
            per_axis[short] = {
                "gate": gate,
                "flip_applicable": bool(gate),
                "has_signal": False,
                "coverage": coverage,
                "fragility": None,
                "reason": "blind",
            }
            blind_decision_axes.append(short)
            # ACQUIRE task: name the missing cards + WHY (availability_state, if the composer set it —
            # not_wired / data_blocked / read_error / insufficient). is_coverage_gap distinguishes a
            # never-looked gap (acquire wiring/data) from a measured 'we looked, absent' insufficient.
            missing = [
                {"card_id": c.get("card_id"), "availability_state": c.get("availability_state") or "unknown"}
                for c in (r.get("cards") or [])
                if c.get("_missing")
            ]
            acquisition_backlog.append(
                {
                    "axis": short,
                    "gate": gate,
                    "coverage": coverage,
                    "action": "acquire",  # held by IGNORANCE → go measure; never a KILL
                    # M4: the record's axis-level absence TYPE (not_wired / data_blocked / read_error),
                    # authoritative over the per-missing-card availability_state above. None if no shadow.
                    "availability": _record_availability(r),
                    "missing_cards": missing,
                }
            )
            continue

        if gate is None:
            # decision-relevant but no resolver to flip (e.g. `expression` presence positive): it has
            # signal but no flip scan, so it informs coverage, not the index.
            per_axis[short] = {
                "gate": None,
                "flip_applicable": False,
                "has_signal": True,
                "coverage": coverage,
                "fragility": None,
                "reason": "no_resolver_gate",
            }
            continue

        fa = flip_analysis(r.get("fired") or [], gate, contracts_repo)
        if fa is None:
            per_axis[short] = {
                "gate": gate,
                "flip_applicable": False,
                "has_signal": True,
                "coverage": coverage,
                "fragility": None,
                "reason": "resolver_absent",
            }
            continue

        base_role = _decision_role(short, fa["base_verdict"], gate_map, pos_map, contra_set)
        base_kill = base_role.startswith("kill:")  # base verdict maps to a gate action (veto/hold)
        decision_flips = []
        n_rec_flips = 0
        for f in fa["flips"]:
            to_role = _decision_role(short, f["to_verdict"], gate_map, pos_map, contra_set)
            if to_role == base_role:
                continue  # raw flip but same decision role (e.g. lineage↔selective)
            # A RECOMMENDATION flip crosses the KILL boundary (enters/leaves a gate action) — the only
            # flips that can move overall_recommendation. Role changes AMONG positive/contradiction/
            # neutral change CONFIDENCE, not the Go/No-Go — so they are call-fragile, not recommendation-
            # fragile (this is why KRAS, fragile only on the selectivity CONTRADICTION, is not contested).
            rec = base_kill != to_role.startswith("kill:")
            if rec:
                n_rec_flips += 1
            decision_flips.append(
                {
                    "rule_id": f["rule_id"],
                    "present": f["present"],
                    "to_verdict": f["to_verdict"],
                    "to_role": to_role,
                    "recommendation_flip": rec,
                }
            )
        n_rel = fa["n_relevant"]
        decision_fragility = (len(decision_flips) / n_rel) if n_rel else 0.0
        rec_fragility = (n_rec_flips / n_rel) if n_rel else 0.0
        per_axis[short] = {
            "gate": gate,
            "flip_applicable": True,
            "has_signal": True,
            "coverage": coverage,
            "base_verdict": fa["base_verdict"],
            "base_driver": fa["base_driver"],
            "base_role": base_role,
            "n_relevant": n_rel,
            "raw_flip_fragility": round(fa["flip_fragility"], 4),
            "decision_flip_fragility": round(decision_fragility, 4),
            "recommendation_flip_fragility": round(rec_fragility, 4),
            "decision_flips": decision_flips,
            "fragility": round(decision_fragility, 4),
        }
        fragilities.append(decision_fragility)
        rec_fragilities.append(rec_fragility)

    # target_index = worst-case CALL fragility (how solid is each axis's own call — informative).
    # recommendation_fragility_index = worst-case fragility of the GO/NO-GO ACTION itself, and it is what
    # DRIVES `contested` — a call can be fragile (selectivity discordant) while the recommendation is rock
    # solid, and only the latter should raise a contested banner.
    target_index = round(max(fragilities), 4) if fragilities else None
    recommendation_fragility_index = round(max(rec_fragilities), 4) if rec_fragilities else None

    # M4 insufficient-split pass: an axis whose factored record reports a MEASURED-but-underpowered
    # verdict (finding.availability == 'insufficient') is neither blind (acquire) nor a measured
    # negative (kill) — it is a thin call that licenses STRENGTHEN (add power). Sourced authoritatively
    # from the record, independent of the flip/coverage machinery above. Verdict-INERT.
    for short in sorted(decision_shorts):
        if _record_availability(sub_results.get(short)) == "insufficient":
            underpowered_axes.append(
                {
                    "axis": short,
                    "gate": _SHORT_TO_GATE.get(short),
                    "action": "strengthen",
                    "availability": "insufficient",
                }
            )

    ct = _load_contested_threshold(contracts_repo)
    contested = None
    if ct is not None and recommendation_fragility_index is not None:
        contested = recommendation_fragility_index >= ct["fragility_index_min"]

    facet = {
        "target_index": target_index,
        "recommendation_fragility_index": recommendation_fragility_index,
        "contested": contested,
        "decision_relevant_axes": sorted(decision_shorts),
        "blind_decision_axes": blind_decision_axes,
        "acquisition_backlog": acquisition_backlog,
        "underpowered_axes": underpowered_axes,
        "per_axis": per_axis,
        "_basis": "target_index = worst-case DECISION-flip (any role change: how solid is each axis's "
        "call). recommendation_fragility_index = worst-case KILL-boundary-crossing flip (how "
        "solid the Go/No-Go ACTION is) and DRIVES `contested`. single-rule scan; blind axes "
        "tracked separately (coverage != fragility), never folded into either index.",
        "_legend": _FRAGILITY_LEGEND,
        "_contested_threshold": ct,
    }
    if subtypes:
        facet["subgroup_flips"] = _subgroup_flip_view(sub_results)
    return facet


def _narrative_by_axis(
    sub_results: dict, fragility_facet: dict, contracts_repo: Path | None = None, modality: str | None = None
) -> dict:
    """Verdict-INERT per-axis NARRATIVE for every decision-relevant sub-verdict — the composed
    fan-out of the shared build_narrative (Stage C deterministic half). For each resolver-backed
    axis it re-materialises the traversal the resolver distils away: movers (winning driver +
    same-direction referenced fired rules), dissenters (fired rules whose per-channel signal OPPOSES
    the resolved call), flip_conditions, and rule_sentences (human text for every cited rule_id,
    fired or not). Gaps (acquire / strengthen) are threaded from the fragility facet.

    Assembled ENTIRELY from each sub_result's fired-set + the ALREADY-COMPUTED `fragility_facet`
    (its per_axis[short].decision_flips / acquisition_backlog / underpowered_axes) — no second flip
    scan, so it is a cheap projection. Emitted in nomination.json.narrative_by_axis and consumed by
    the dashboard 'why this verdict' panel + the Tier-3 synthesis prompt. Never touches the verdict
    spine. Mirrors _claim_record_shadow_by_axis (passthrough) + _fragility_facet (flip consumer)."""
    per_axis = (fragility_facet or {}).get("per_axis") or {}
    # gap tasks keyed by axis (acquire = held by ignorance; strengthen = measured-but-underpowered)
    gaps_by_axis: dict[str, list] = {}
    for g in (fragility_facet or {}).get("acquisition_backlog") or []:
        gaps_by_axis.setdefault(g.get("axis"), []).append(
            {"kind": "acquire", "availability": g.get("availability"), "missing_cards": g.get("missing_cards") or []}
        )
    for g in (fragility_facet or {}).get("underpowered_axes") or []:
        gaps_by_axis.setdefault(g.get("axis"), []).append(
            {"kind": "strengthen", "availability": g.get("availability"), "missing_cards": []}
        )

    # Cross-axis reconciled contradictions (same set the gate drops): stamp the per-axis trace so the
    # 'why this verdict' panel + Tier-3 narrative block read a reconciled contradiction as retired, not
    # opposing — consistent with _hard_gates_status/_gate_scorecard. Fail-closed empty.
    reconciled = _reconciled_contradiction_keys(sub_results, contracts_repo)
    out: dict = {}
    for short, ax in per_axis.items():
        gaps = gaps_by_axis.get(short)
        if ax.get("flip_applicable"):
            r = sub_results.get(short) or {}
            try:
                out[short] = build_narrative(
                    axis=short,
                    gate=ax.get("gate"),
                    fired=r.get("fired") or [],
                    verdict=ax.get("base_verdict"),
                    driving_rule_id=ax.get("base_driver"),
                    modality=modality,
                    contracts_repo=contracts_repo,
                    flip_facet=ax,  # reuse the fragility facet's decision_flips (no re-scan)
                    gaps=gaps,
                )
            except Exception:  # noqa: BLE001 — verdict-inert projection; a build fault must not abort
                continue
            if (short, ax.get("base_verdict")) in reconciled:
                out[short]["reconciled_contradiction"] = True
        elif gaps:
            # blind / no-resolver axis with an outstanding acquire/strengthen task: gap-only narrative
            # so the dashboard still surfaces "go measure X" (ignorance != a measured negative).
            out[short] = {
                "axis": short,
                "gate": ax.get("gate"),
                "verdict": None,
                "driving_rule_id": None,
                "scan_depth": "single_rule",
                "movers": [],
                "dissenters": [],
                "flip_conditions": [],
                "gaps": gaps,
                "rule_sentences": {},
                "_basis": "blind/underpowered axis — acquire/strengthen gap only; verdict-INERT",
            }

    # GATELESS DESCRIPTIVE axes (2026-09-12). The loop above iterates the FRAGILITY facet's per_axis,
    # whose membership is `decision_shorts` = the shorts the gate / positive / contradiction vocabularies
    # name. A gateless skill (verdict_fn=None — target-intrinsic) appears in NONE of them by design, so it
    # got NO narrative entry at all: the dashboard "why this verdict" panel and the Tier-3 narrative block
    # simply had no row for it, and a reader saw the axis only as an absence — indistinguishable from an
    # axis that failed or was never run. That is the wrong read for ROUTING: these skills computed a real
    # interpreted answer (honest_phrase, confidence, claim chips, per-question table), they just do not
    # gate on it. Emit that answer in the SAME narrative shape, with the verdict slots explicitly null and
    # a `_basis` naming gatelessness as the reason.
    #
    # Sourced from the skill_report[] SPINE (role == descriptive), NOT from the fragility facet — which is
    # deliberately left untouched, since it feeds target_index / recommendation_fragility_index and a new
    # member there would move a published number. movers / dissenters / flip_conditions stay EMPTY: there
    # is no call to move or flip. VERDICT-INERT; skips any short the loop above already narrated.
    for short, sr in _skill_reports_by_short(sub_results).items():
        if short in out or sr.get("role") != "descriptive":
            continue
        out[short] = {
            "axis": short,
            "gate": None,  # structurally gateless — absent from _SHORT_TO_GATE, not merely unresolved
            "verdict": None,
            "driving_rule_id": None,
            "scan_depth": "not_applicable",
            "movers": [],
            "dissenters": [],
            "flip_conditions": [],
            "gaps": gaps_by_axis.get(short) or [],
            "rule_sentences": {},
            # what the axis DID compute — its own interpreted read, for routing/calibration only
            "role": "descriptive",
            "polarity": sr.get("polarity"),
            "honest_phrase": sr.get("honest_phrase"),
            "confidence": sr.get("confidence"),
            "top_tension": sr.get("top_tension"),
            "claim_chips": sr.get("claim_chips") or [],
            "question_table": sr.get("question_table") or [],
            "cards_used": ((sr.get("provenance") or {}).get("cards_used")) or [],
            "_basis": (
                "gateless DESCRIPTIVE axis — emits no verdict BY DESIGN (verdict_fn=None), so there is no "
                "call to move or flip; the interpreted read is CONTEXT for routing, never a gate. "
                "verdict-INERT"
            ),
        }
    return out


def _find_card_summary(sub_results: dict, card_id: str) -> dict:
    """First matching card's summary dict across all sub-results (source-short-agnostic), or {}."""
    for r in sub_results.values():
        for c in r.get("cards") or []:
            if c.get("card_id") == card_id:
                return c.get("summary") or {}
    return {}


def _cv(vals: list) -> "Optional[float]":
    """Coefficient of variation (population stdev / |mean|) over >=2 numerics; None otherwise.

    Values are coerced to Python float: numpy.float64 passes isinstance(v, float) (it
    subclasses float) but breaks statistics.mean/pstdev in py3.12 with
    "'float' object has no attribute 'numerator'". bool and NaN are excluded.
    """
    import math

    xs = []
    for v in vals:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fv = float(v)
        if math.isnan(fv):
            continue
        xs.append(fv)
    if len(xs) < 2:
        return None
    import statistics

    m = statistics.mean(xs)
    return (statistics.pstdev(xs) / abs(m)) if m != 0 else None


def _norm_entropy(labels: list) -> "Optional[float]":
    """Shannon entropy of a label multiset, normalized to 0..1 by log(#distinct); None if <2 labels."""
    xs = [x for x in labels if x]
    if len(xs) < 2:
        return None
    import math
    from collections import Counter

    counts = Counter(xs)
    if len(counts) < 2:
        return 0.0
    n = len(xs)
    h = -sum((c / n) * math.log(c / n) for c in counts.values())
    return h / math.log(len(counts))


# --- Heterogeneity facet (verdict-inert; cross-stratum / -comparator / -modality DISPERSION) --------
#
# Companion to fragility: fragility asks "how easily does the CALL move?"; heterogeneity asks "does a
# single pooled verdict HIDE a split?" — a target strong in some strata/comparators/assays and absent
# in others. NARROW by design: dispersion is only computable where the underlying
# MULTI-VALUE data survives — the tumor-vs-normal four-cell (always), CRISPR-vs-RNAi fraction_agree
# (always), and the per-molecular-subtype dependency panorama (ONLY under --subtypes; not pulled
# otherwise). Most pooled cards carry no per-value array, so a GENERAL cross-cohort dispersion is
# deliberately NOT attempted (needs method-layer plumbing). heterogeneity_index = worst-case over the
# available NORMALIZED (0..1) signals. STRICTLY VERDICT-INERT: emitted in nomination.json; never
# touches overall_recommendation / confidence.
_HETEROGENEITY_LEGEND = (
    "Cross-context HETEROGENEITY (dispersion): does a pooled verdict hide a split? Worst-case over the "
    "available normalized signals — tumor-vs-normal comparator disagreement (four-cell), CRISPR-vs-RNAi "
    "modality disagreement (1-fraction_agree), and (only under --subtypes) per-subtype dependency "
    "spread (class entropy / metric CV over floor-cleared strata). 0 = uniform; higher = a stratified "
    "opportunity the pooled call hides. NOT a probability; never summed or averaged."
)


def _heterogeneity_facet(sub_results: dict, subtypes: "Optional[list[str]]" = None) -> dict:
    """Verdict-inert cross-context dispersion facet (see section header). Emitted in nomination.json;
    never touches the verdict / gate / recommendation."""
    sources: dict = {}
    signals: list = []

    # (1) tumor-vs-normal four-cell comparator dispersion
    sel = _find_card_summary(sub_results, "tumor-vs-normal-selectivity")
    ran, sup = sel.get("cells_ran"), sel.get("cells_supporting")
    if isinstance(ran, (int, float)) and ran and isinstance(sup, (int, float)):
        unsupported = 1.0 - (sup / ran)
        disc = bool(sel.get("discordant"))
        logs_cv = _cv([sel.get("log2fc_cell_a"), sel.get("log2fc_cell_b"), sel.get("log2fc_cell_c")])
        disp = 1.0 if disc else round(unsupported, 4)  # an explicit discordant read is maximal dispersion
        sources["selectivity_comparators"] = {
            "cells_ran": ran,
            "cells_supporting": sup,
            "unsupported_fraction": round(unsupported, 4),
            "discordant": disc,
            "log2fc_cv": round(logs_cv, 4) if logs_cv is not None else None,
            "dispersion": disp,
        }
        signals.append(disp)

    # (2) CRISPR-vs-RNAi modality dispersion
    conc = _find_card_summary(sub_results, "crispr-rnai-dependency-concordance")
    fa = conc.get("fraction_agree")
    if isinstance(fa, (int, float)):
        disp = round(1.0 - fa, 4)
        sources["modality_crispr_rnai"] = {"fraction_agree": round(fa, 4), "dispersion": disp}
        signals.append(disp)

    # (3) per-molecular-subtype dependency spread — only when --subtypes scoped (panorama present)
    if subtypes:
        rows = _first_card_per_subgroup(sub_results.get(SUBTYPE_SHORT) or {}, "subgroup-stratified-dependency")
        measured = [r for r in rows if r.get("evidence_state") == "measured" and r.get("subgroup_n_floor_met")]
        if len(measured) >= 2:
            metric_cv = _cv([r.get("median_chronos") for r in measured])
            ent = _norm_entropy([r.get("dependency_class") or r.get("_dependency_class") for r in measured])
            disp = ent if ent is not None else (min(metric_cv, 1.0) if metric_cv is not None else None)
            sources["subtype_strata"] = {
                "n_measured_strata": len(measured),
                "class_entropy": round(ent, 4) if ent is not None else None,
                "metric_cv": round(metric_cv, 4) if metric_cv is not None else None,
                "dispersion": round(disp, 4) if disp is not None else None,
            }
            if disp is not None:
                signals.append(disp)

    return {
        "heterogeneity_index": round(max(signals), 4) if signals else None,
        "sources": sources,
        "_basis": "worst_case over available normalized cross-context dispersion signals "
        "(selectivity four-cell / crispr-rnai concordance / subtype strata [--subtypes only])",
        "_legend": _HETEROGENEITY_LEGEND,
    }


# --- Addressable-population facet (patient-population layer, reconstructed as composition) ----------
_ADDRESSABLE_POPULATION_LEGEND = (
    "Estimated fraction of the indication addressable by the target's SELECTION BASIS. For an "
    "alteration-stratified / mutation-driver target the addressable population is the in-indication "
    "PREVALENCE of the defining SNV/indel (coverage-correct GENIE preferred — ~35x the MC3 sample "
    "count; MC3 fallback); for a broad (unstratified) dependency it is biomarker_unrestricted (the "
    "indication itself); a CN/fusion-defined subgroup is not_estimated_this_axis (SNV frequency is the "
    "wrong denominator — CN/fusion prevalence is a v2 extension). VERDICT-INERT: population-sizing "
    "context beside the nomination, never a gate input."
)


# clinical addressable-population tiers by alteration prevalence
def _addressable_population_class(freq: "float | None") -> "str | None":
    if not isinstance(freq, (int, float)):
        return None
    if freq >= 0.20:
        return "broad"  # e.g. KRAS/TP53 in COADREAD (~40%)
    if freq >= 0.05:
        return "common"
    if freq >= 0.01:
        return "uncommon"
    if freq >= 0.001:
        return "rare"
    return "ultra_rare"


# genomic verdicts whose actionability is TIED TO AN SNV/indel ALTERATION → population = its prevalence
_SNV_SELECTION_VERDICTS = frozenset(
    {
        "biomarker_stratified_dependency",
        "moderate_biomarker_dependency",
        "confirmed_driver",
        "multi_class_driver",
        "confirmed_lof_driver",
        "multi_class_lof_driver",
        "missense_dominant_pattern",
        "lof_dominant_pattern",
        "drug_response_biomarker",
    }
)
_CN_FUSION_SELECTION_VERDICTS = frozenset(
    {
        "recurrent_amplification_driver",
        "recurrent_deletion_driver",
        "recurrent_fusion_driver",
    }
)
_NON_DEPENDENT = frozenset({"non_dependent", "insufficient", "data_unavailable", ""})


def _addressable_population_facet(sub_results: dict) -> dict:
    """VERDICT-INERT addressable-population facet — joins the target's SELECTION BASIS (what defines the
    treatable subgroup, from the genomic + dependency verdicts) to the in-indication PREVALENCE of that
    basis (from mutation-hotspot-frequency: genie_mutation_frequency preferred, overall_mutation_frequency
    fallback). Reconstructs the deleted patient-population-and-access layer as a composition over signals
    already on the fan-out. Emitted in nomination.json + the synthesis prompt; never touches the gate."""
    gen = (sub_results.get("genomic_alteration") or {}).get("verdict")
    gen_verdict = gen[0] if gen else None
    dep = (sub_results.get("dependency") or {}).get("verdict")
    dep_verdict = dep[0] if dep else None

    hf = _find_card_summary(sub_results, "mutation-hotspot-frequency")
    genie_freq = hf.get("genie_mutation_frequency")
    mc3_freq = hf.get("overall_mutation_frequency")
    n_samples = hf.get("n_samples_in_indication")
    freq, source = (
        (genie_freq, "genie")
        if isinstance(genie_freq, (int, float))
        else (mc3_freq, "tcga_mc3")
        if isinstance(mc3_freq, (int, float))
        else (None, None)
    )

    if gen_verdict in _SNV_SELECTION_VERDICTS:
        basis = "snv_indel_stratified"
        pop_class = _addressable_population_class(freq)
        note = None
    elif gen_verdict in _CN_FUSION_SELECTION_VERDICTS:
        basis = "copy_number_or_fusion_stratified"
        pop_class, freq, source = "not_estimated_this_axis", None, None
        note = (
            "addressable population is defined by a CN/fusion event; SNV frequency is inapplicable "
            "— CN/fusion prevalence (copy-number-distribution / fusion cards) is a v2 extension"
        )
    elif dep_verdict and dep_verdict not in _NON_DEPENDENT:
        basis = "biomarker_unrestricted"
        pop_class = "biomarker_unrestricted"
        note = (
            "a broad dependency with no alteration-defined selection biomarker; the addressable "
            "population is the indication itself"
        )
    else:
        basis = "undetermined"
        pop_class = None
        note = "no alteration-selection verdict and no positive dependency to anchor an addressable-population estimate"

    return {
        "addressable_population_class": pop_class,
        "selection_basis": basis,
        "biomarker_prevalence": round(freq, 4) if isinstance(freq, (int, float)) else None,
        "prevalence_source": source,
        "n_samples_in_indication": n_samples,
        "_note": note,
        "_legend": _ADDRESSABLE_POPULATION_LEGEND,
    }


# ── actionability_mode facet (2026-08-19) ─────────────────────────────────────────────────────────
# VERDICT-INERT descriptive conditioner: HOW is the target actioned — what IS the patient-selection
# handle — orthogonal to biology_axis (WHERE the drug acts) and the necessity/sufficiency questions.
# A PROFILE, never a partition: cis_feature / abundance / mixed / dependency_relational / insufficient,
# with per-arm tiers (dominant|supporting|none|unknown) + a dominant call. Pure post-hoc function over
# already-fired sub_results (like _biomarker_facet); absent from _SHORT_TO_GATE → structurally cannot
# move the verdict spine. Now GRADUATED past the annotation-only phase: it emits a synthesis EMPHASIS governance block
# (tp_synthesis_prompt.format_mode_governance_block) AND routes render emphasis (tp_render_md) — so the
# LLM prompt (and thus prompt_hash) DO change when a mode is present. What stays byte-identical is the
# DETERMINISTIC verdict spine (recommendation / confidence / gate), NOT the prompt: this facet reorders
# narrative emphasis only, never a verdict. (Do not re-add a "no prompt change / prompt_hash byte-stable"
# claim here — later phases falsified it; see the actionability-mode design doc.)
# `unknown` (read-failure/uncurated) is strictly distinct from `none` (measured-absent): a blind arm
# lowers confidence and never cedes to another mode. Thresholds are calibratable; unrecognized
# card values degrade to none/unknown (honest), never crash. See the actionability-mode design doc.
_ABUNDANCE_FIT = frozenset({"both_viable", "adc_preferred", "tce_preferred", "ADC_preferred", "TCE_preferred"})
_ABUNDANCE_DENSITY = frozenset({"high", "moderate"})
_SELECTIVE_VERDICTS = frozenset({"strong_tumor_selective", "modest_tumor_selective", "selective_with_normal_liability"})


@functools.lru_cache(maxsize=1)
def _actionability_mode_overrides() -> dict:
    """Curated actionability_mode overrides — symbol/alias (UPPER) -> {mode, rationale}. From
    target-contracts vocabularies/actionability_mode_lookup.yaml; graceful-skip → {} if absent. Pins the
    documented multi-axis duals (ERBB2/HER2, EGFR, MET) as `mixed` so a thin run can't collapse them."""
    path = _CONTRACTS_REPO / "vocabularies" / "actionability_mode_lookup.yaml"
    if not path.exists():
        return {}
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return {}
    out: dict = {}
    for o in doc.get("overrides") or []:
        if not isinstance(o, dict) or not o.get("hgnc_symbol") or not o.get("mode"):
            continue
        entry = {"mode": o["mode"], "rationale": o.get("rationale")}
        out[o["hgnc_symbol"].upper()] = entry
        for a in o.get("aliases") or []:
            out[str(a).upper()] = entry
    return out


def _actionability_mode_facet(sub_results: dict, target: str | None = None) -> dict:
    """VERDICT-INERT selection-basis profile: cis_feature vs abundance vs dependency_relational (+ mixed
    / insufficient). Post-hoc over fired sub_results; never touches the gate. A curated override
    (actionability_mode_lookup.yaml) pins `dominant` for listed high-value duals; the derived
    value is retained as `derived_dominant` for audit."""

    def _cs(card_id, field):
        return (_find_card_summary(sub_results, card_id) or {}).get(field)

    def _v(short):
        vv = (sub_results.get(short) or {}).get("verdict")
        return vv[0] if vv else None

    deriv: list[str] = []

    # ---- CIS-FEATURE arm: a specific lesion/feature IS the handle (patient-selection = the biomarker) ----
    role, hotspot = (
        _cs("alteration-role", "alteration_role"),
        _cs("mutation-hotspot-frequency", "pooled_driver_recurrence_class"),
    )
    fusion, cn, gen_v = (
        _cs("fusion-rearrangement-landscape", "fusion_class"),
        _cs("copy-number-distribution", "patient_focal_cn_class"),
        _v("genomic_alteration"),
    )
    # a LoF/TSG driver is NOT a positive cis handle (you cannot target an absence) → route it to the
    # dependency_relational arm (MDM2/SL/context), never cis. Suppress the cis arm when role is LoF.
    _lof = role == "direct_driver_lof"
    cis_dom = (not _lof) and (
        role == "direct_driver_gof"
        or hotspot == "top_1pct"
        or fusion == "recurrent_fusion_driver"
        or gen_v in _SNV_SELECTION_VERDICTS
        or gen_v in _CN_FUSION_SELECTION_VERDICTS
    )
    cis_sup = (not _lof) and (role == "predictive_biomarker" or hotspot == "top_decile" or fusion == "sporadic_fusion")
    cis_seen = any(x not in (None, "data_unavailable") for x in (role, hotspot, fusion, cn, gen_v))
    cis_tier = "dominant" if cis_dom else "supporting" if cis_sup else "none" if cis_seen else "unknown"
    if cis_dom:
        deriv += [
            f"{k}={x} -> cis:dominant"
            for k, x in (("role", role), ("hotspot", hotspot), ("fusion", fusion), ("genomic_verdict", gen_v))
            if x
        ]

    # ---- ABUNDANCE arm: selectively over-present (patient-selection = an expression/density cutoff) ----
    dens_abs, dens_cls = (
        _cs("surface-abundance-density", "absolute_density_class"),
        _cs("surface-abundance-density", "surface_density_class"),
    )
    fit, sel_v = _cs("adc-tce-modality-fit", "fit_class"), _v("selectivity")
    ab_dom = dens_abs in _ABUNDANCE_DENSITY or dens_cls in _ABUNDANCE_DENSITY or fit in _ABUNDANCE_FIT
    ab_sup = dens_cls == "low" or sel_v in _SELECTIVE_VERDICTS
    ab_seen = any(x not in (None, "data_unavailable", "unmeasured") for x in (dens_abs, dens_cls, fit, sel_v))
    ab_tier = "dominant" if ab_dom else "supporting" if ab_sup else "none" if ab_seen else "unknown"
    if ab_dom:
        deriv += [
            f"{k}={x} -> abundance:dominant"
            for k, x in (("surface_density", dens_abs or dens_cls), ("adc_tce_fit", fit))
            if x
        ]

    # ---- DEPENDENCY_RELATIONAL arm: no positive cis handle / not over-abundant — actioned via a
    #      partner/context (LoF-driver → MDM2/SL; partner-conditional SL [WRN×MSI]; combinatorial) ----
    # relational SL/combinatorial signal now flows through combination-and-vulnerability (trio consolidated
    # 2026-08-20); read SOURCE cards directly via _cs (still composed under combination_vulnerability) so
    # this arm is behavior-preserving without the retired shorts.
    dep_v = _v("dependency")
    sl_cls = _cs("synthetic-lethal-partners", "sl_partner_class")
    # In the fan-out, combinatorial-dependency is composed as a CARD (under combination-and-vulnerability),
    # so it emits combinatorial_dependency_CLASS — NOT the standalone skill's combinatorial_dependency_VERDICT.
    # Reading the verdict field left combo signal permanently None → the relational arm never saw a
    # combinatorial SL. Read the class + check the two SL class tokens (strong_/context_synthetic_lethal),
    # which are the card-vocab equivalents of the constitutive/context verdicts (suppressive_interaction is
    # NOT a co-targeting rationale, so it is excluded).
    combo_cls = _cs("combinatorial-dependency", "combinatorial_dependency_class")
    rel_dom = (
        role == "direct_driver_lof"
        or dep_v == "partner_conditional_dependent"
        or sl_cls == "has_experimental_sl_partner"
    )
    rel_sup = sl_cls == "has_computational_sl_partner" or combo_cls in (
        "strong_synthetic_lethal",
        "context_synthetic_lethal",
    )
    rel_seen = any(x not in (None, "data_unavailable", "") for x in (role, dep_v, sl_cls, combo_cls))
    rel_tier = "dominant" if rel_dom else "supporting" if rel_sup else "none" if rel_seen else "unknown"
    if rel_dom:
        deriv += [
            f"{k}={x} -> dependency_relational:dominant"
            for k, x in (
                ("role", role if role == "direct_driver_lof" else None),
                ("dependency", dep_v if dep_v == "partner_conditional_dependent" else None),
                ("sl_partner", sl_cls if sl_cls == "has_experimental_sl_partner" else None),
            )
            if x
        ]

    arms = {"cis_feature": cis_tier, "abundance": ab_tier, "dependency_relational": rel_tier}
    dom_arms = [a for a, t in arms.items() if t == "dominant"]
    secondary = None
    if len(dom_arms) >= 2:
        dominant = "mixed"  # both leading arms ARE the story (HER2/EGFR/MET guarantee)
    elif len(dom_arms) == 1:
        dominant = dom_arms[0]
    else:
        sup_arms = [a for a, t in arms.items() if t == "supporting"]
        dominant = sup_arms[0] if len(sup_arms) == 1 else "insufficient"
    _rank = {"dominant": 3, "supporting": 2, "none": 1, "unknown": 0}
    if dominant not in ("mixed", "insufficient"):
        others = sorted((a for a in arms if a != dominant), key=lambda a: _rank[arms[a]], reverse=True)
        secondary = others[0] if others and _rank[arms[others[0]]] >= 2 else None

    if dominant == "insufficient":
        confidence = "low"
    elif dominant == "mixed" or arms.get(dominant) == "dominant":
        confidence = "moderate" if any(t == "unknown" for t in arms.values()) else "high"
    else:
        confidence = "low"

    # Curated OVERRIDE: a listed high-value dual (ERBB2/EGFR/MET) is pinned so a thin/one-sided
    # run can't collapse it; the derived call is retained as derived_dominant for audit.
    source = "derived"
    derived_dominant = dominant
    override = _actionability_mode_overrides().get((target or "").upper())
    if override:
        dominant = override["mode"]
        source = "curated_override"
        if dominant == "mixed":
            secondary = None
        # a curated override pins the DOMINANT mode, but confidence must reflect THIS run's arms —
        # else a thin/one-sided run (every arm unknown/none) falsely reads `high`. High only when at least
        # one arm was actually measured this run; otherwise curation-anchored `moderate`.
        confidence = "high" if any(t not in ("unknown", "none") for t in arms.values()) else "moderate"
        deriv.append(f"curated_override(target={target}) -> {dominant} [{(override.get('rationale') or '')[:80]}]")

    return {
        "dominant": dominant,
        "derived_dominant": derived_dominant,
        "source": source,
        "secondary": secondary,
        "arms": arms,
        "confidence": confidence,
        "derivation": deriv,
        "note": (
            "VERDICT-INERT selection-basis profile: it ROUTES narrative emphasis (render lead-order "
            "+ a synthesis emphasis-governance block) but never changes the verdict / recommendation / "
            "gate (all clamped deterministically). Orthogonal to biology_axis; `unknown` != `none`. cis_feature=biomarker handle, "
            "abundance=expression/density cutoff, dependency_relational=partner/context handle, "
            "mixed=both (e.g. HER2 amplification is BOTH the cis handle AND the abundance readout)."
        ),
    }


# =====================================================================================================
# target_rollup.v1 + target_coherence.v1 — the VERDICT-INERT distillation layer (PR-4).
# A multi-axis roll-up (7 decision axes + a NEGATIVE cross-axis block; NO positive scalar) and a
# thesis/coherence lens ON TOP of it. Both recomputed from the SAME sub_results + facets already in a
# composed run — additive keys in nomination.json; they NEVER touch the verdict spine (sub_verdicts /
# recommendation_gate / confidence_tier / deciding_axis). Ported from the validated prototype +
# TARGET_ROLLUP_DESIGN_2026-08-25.md (route-quality band map keyed on driving_rule_id class; biology
# axis derived EVIDENCE-FIRST from surface_modality; block drawn from axis evidence, IGNORING
# recommendation_gate.fired; thesis classified from UN-CONTAMINATED signals only).
# =====================================================================================================
_SURFACE_FITS = {"adc_preferred_tce_unsafe", "both_viable", "adc_preferred", "tce_preferred"}
# pmhc_tce_supported_presentation_unconfirmed (#2113): the caveated pMHC-TCE promotion — still a folded-
# surface-dead intracellular target reached via the peptide-MHC route, so it reads intracellular_intrinsic
# like its clean sibling pmhc_tce_supported (VERDICT-INERT biology-axis label).
_INTRACELL_FITS = {"pmhc_tce_supported", "pmhc_tce_supported_presentation_unconfirmed", "neither_viable"}
_ROLLUP_FIT_ORDER = {"favorable": 3, "conditional": 2, "unfavorable": 0}


def _rollup_sv(sub_results: dict, short: str) -> "tuple":
    v = (sub_results.get(short) or {}).get("verdict")
    if isinstance(v, (list, tuple)) and v:
        return v[0], (v[1] if len(v) > 1 else None)
    return None, None


def _biology_axis_from_surface(surf_v: "Optional[str]") -> str:
    if surf_v in _SURFACE_FITS:
        return "surface_intrinsic"
    if surf_v in _INTRACELL_FITS:
        return "intracellular_intrinsic"
    return "unknown"


def build_target_rollup(
    sub_results: dict, modality_fit_by_channel: "Optional[dict]" = None, subtype_facet: "Optional[dict]" = None
) -> dict:
    """target_rollup.v1 — 7-axis distillation + a NEGATIVE cross-axis block + a PROMINENT subtype block.
    Verdict-inert; the block is recomputed from axis evidence and deliberately IGNORES
    recommendation_gate.fired (which mis-fires the dependency hard-gate on antigen-only targets)."""
    mfc = modality_fit_by_channel or {}
    dep_v, dep_r = _rollup_sv(sub_results, "dependency")
    _gen_v, gen_r = _rollup_sv(sub_results, "genomic_alteration")
    sel_v, _sel_r = _rollup_sv(sub_results, "selectivity")
    surf_v, _surf_r = _rollup_sv(sub_results, "surface_modality")
    safe_v, _safe_r = _rollup_sv(sub_results, "safety")
    bio = _biology_axis_from_surface(surf_v)

    # A biological_necessity — route-QUALITY ladder keyed on the driving_rule_id class (not the verdict
    # string): CRISPR-confirmed lineage/stratified → favorable; amplification-inferred → capped
    # conditional; mutation-spectrum-only driver is NOT a route; surface antigen non_dependent →
    # insufficient (expected, non-blocking); intracellular w/ no route → unfavorable (block-eligible).
    if dep_v in ("lineage_selective", "broadly_dependent") or (dep_r or "").startswith("mutant-strongly-dependent"):
        A = ("lineage_dependency", "favorable")
    elif (gen_r or "").startswith("cn-amplified"):
        A = ("amplification_driven", "conditional")
    elif bio == "surface_intrinsic" and dep_v in ("non_dependent", "non_dependent_paralog_buffered"):
        A = ("antigen_no_survival_necessity", "insufficient")
    elif bio == "intracellular_intrinsic":
        A = ("no_necessity", "unfavorable")
    else:
        A = ("unresolved_necessity", "insufficient")

    B = {
        "discordant_across_comparators": ("present_not_selective", "conditional"),
        "selective_but_broadly_normal": ("present_broad_normal", "conditional"),
        "selective_with_normal_liability": ("selective_normal_liability", "conditional"),
        "strong_tumor_selective": ("tumor_selective_present", "favorable"),
    }.get(sel_v, ("present", "insufficient"))

    # D deliverability — per-channel from modality_fit_by_channel; frontier = best viable band.
    ch: dict = {}
    for c in ("small_molecule", "degrader", "adc", "bite_tce", "antibody"):
        fit = (mfc.get(c) or {}).get("fit")
        applicable = fit not in ("not_applicable_by_axis", "na", None)
        ch[c] = {"fit": fit, "applicable": applicable, "viable": applicable and fit in ("favorable", "conditional")}
    viable = [c for c, v in ch.items() if v["viable"]]
    frontier = max((_ROLLUP_FIT_ORDER[ch[c]["fit"]] for c in viable), default=None)
    D_band = {3: "favorable", 2: "conditional"}.get(frontier, "unfavorable")

    # E safety — escapability = the per-channel safety×deliverability join. A WT-loss/human-genetics
    # constraint is escaped by a viable tumor-restricted channel; a non-mutant-selective SM does NOT
    # spare WT (drop it unless the necessity route is a driver/mutant-selective one). Pan-essential
    # broad-tox is escapable_by=null.
    #
    # Fall-through-direction fix (#2041): the old bare `else` swallowed EVERY non-HOLD measured
    # safety state — including the equivocal `moderately_constrained_safety` mid-band AND (once
    # packages regenerate with AM depmap_chronos 0.3.0 emissions) the graded
    # `broad_dependency_partial_tox_concern` token — into ("clean", "favorable"). That is the
    # conjunctive-label / fall-through-direction defect: "clean, favorable" asserts POSITIVE evidence
    # of safety, so it must only be reachable by a state that actually measured low risk
    # (`tolerant_reduced_safety_risk`), never by a measured mid-band concern, and never by an
    # unmeasured/open-world token (`data_unavailable` / `insufficient` / None) — absence must
    # DEGRADE, never reassure. `normal_tissue_protein_safety_concern` is also a concern-HOLD
    # (same severity rung as highly_constrained/human_genetics in risk_projection._SAFETY_BINS) and
    # was previously mis-swallowed into the same reassuring else-branch; it now shares the
    # concern-HOLD escapability logic below.
    _E_CONCERN_HOLD = (
        "highly_constrained_safety_concern",
        "human_genetics_safety_concern",
        "normal_tissue_protein_safety_concern",
    )
    # measured-mid: a real signal was measured, but it is equivocal/partial rather than a HOLD-grade
    # concern or a clean read — it must render as its OWN conditional facet, never as clean/favorable
    # and never silently promoted to a HOLD.
    _E_MEASURED_MID = ("moderately_constrained_safety", "broad_dependency_partial_tox_concern")
    if safe_v == "pan_essential_broad_tox_concern" or dep_v == "pan_essential_killer":
        E, E_escape, E_blocks = ("pan_essential_veto", "unfavorable"), [], True
    elif safe_v in _E_CONCERN_HOLD:
        E_escape = list(viable)
        if "small_molecule" in E_escape and A[0] not in ("lineage_dependency", "amplification_driven"):
            E_escape.remove("small_molecule")
        E = ("constrained_escapable", "conditional") if E_escape else ("constrained_pan_modality", "unfavorable")
        E_blocks = not E_escape
    elif safe_v in _E_MEASURED_MID:
        E, E_escape, E_blocks = ("measured_mid_signal", "conditional"), [], False
    elif safe_v == "tolerant_reduced_safety_risk":
        E, E_escape, E_blocks = ("clean", "favorable"), [], False
    else:
        # data_unavailable / insufficient / None / any unrecognized token: open-world — no
        # measured evidence of a clean safety profile, so this must NOT read favorable.
        E, E_escape, E_blocks = ("unmeasured", "insufficient"), [], False

    blocks: list = []
    if A[1] == "unfavorable" and bio == "intracellular_intrinsic":
        blocks.append({"axis": "biological_necessity", "kind": "no_biological_necessity"})
    if not viable:
        blocks.append({"axis": "deliverability", "kind": "no_viable_modality"})
    if E_blocks:
        blocks.append({"axis": "safety_liability", "kind": "pan_modality_safety_veto"})
    block_status = (
        "hard_block"
        if blocks
        else "provisional_block"
        if (A == ("unresolved_necessity", "insufficient"))
        else "not_blocked"
    )
    return {
        "schema": "target_rollup.v1",
        "biology_axis": bio,
        "axes": {
            "biological_necessity": {"call": A[0], "band": A[1]},
            "presence_window": {"call": B[0], "band": B[1]},
            "deliverability": {"band": D_band, "viable_channels": viable, "channels": ch},
            "safety_liability": {"call": E[0], "band": E[1], "escapable_by": E_escape},
        },
        "block": {
            "blocked": bool(blocks),
            "status": block_status,
            "blocking_axes": blocks,
            "_basis": "union of per-axis unescapable blocks; from axis evidence, IGNORES recommendation_gate.fired",
        },
        "subtype": _rollup_subtype_block(subtype_facet),
        "_note": "VERDICT-INERT distillation. No positive scalar — the only target-level verdict is block.blocked.",
    }


def build_target_call(
    recommendation_gate: dict,
    confidence_tier: dict,
    deciding_axis: dict,
    gate_scorecard: "Optional[dict]" = None,
    overall_recommendation: "Optional[object]" = None,
    target_rollup: "Optional[dict]" = None,
) -> dict:
    """target_call.v1 — the unified DECISION view for `target_report`, and the CANONICAL OWNER of the
    decision-spine objects (docs/UNIFIED_OUTPUT_CONTRACT.md).

    FULL-NEST (2026-09-03): the four decision-spine objects nest UNDER target_call
    (recommendation_gate→`gate`, confidence_tier→`confidence`, deciding_axis→`deciding_axis`,
    gate_scorecard→`gate_scorecard`) and are NO LONGER emitted as top-level nomination keys — this retires
    the #932 dual-exposure scaffold, giving one canonical home. VERDICT-INERT: it recomputes nothing.

    recommendation VALUE clamp is now TWO-SIDED (the one-sided-clamp defect found 2026-09-11 is fixed):
    when a veto/hold rule fires (`gate.fired == true`) the gate FORCES the value; when the gate ABSTAINS,
    an LLM-authored NEGATIVE (veto/hold) is clamped to `insufficient_evidence` by the lower-bound guard
    (run.py else-branch → tp_gates.abstention_lower_bound_clamp; recorded as `gate.lower_bound_clamp`),
    so a negative recommendation always has a rule (or the honest abstention floor) behind it.

    POSITIVE side (A1, 2026-09-11, gate vocab 1.18.0): on abstention the STRONG positive tier now also
    FORCES `nominate` (`gate.forced_recommendation` = "nominate" with `gate.forced_by` = "positive_tier";
    `gate.fired` deliberately stays false — it means "a KILL fired"). So the LLM owns a `nominate`
    outright only BELOW that tier — bounded above by the kill gate and now bounded below by the tier.
    A nomination withheld by the LLM-authored-negative interlock is recorded as `gate.nominate_withheld`.
    Adds two things no single spine object carries: the
    recommendation VALUE, and a `dissent` block naming where independent signals disagree with the
    gate (the honest 'why not higher / why not lower')."""
    rg = recommendation_gate or {}
    rec_val = (
        overall_recommendation.get("value") if isinstance(overall_recommendation, dict) else overall_recommendation
    )
    dissent: list = []
    # (1) the gate overrode the LLM's recommendation (already computed by run.py's gate assembly)
    if rg.get("overridden"):
        dissent.append(
            {
                "source": "llm_synthesis",
                "detail": f"LLM recommended {rg.get('llm_recommendation')!r}; "
                f"gate forced {rg.get('forced_recommendation')!r}",
                "resolved_to": rg.get("forced_recommendation"),
            }
        )
    # (2) the verdict-inert evidence-band block (target_rollup) fired while the recommendation gate did
    #     not — the two intentionally-independent negative reads disagree (see build_target_rollup's
    #     "IGNORES recommendation_gate.fired" note). Surface it rather than silently collapsing.
    blk = (target_rollup or {}).get("block") or {}
    if blk.get("blocked") and not rg.get("fired"):
        dissent.append(
            {
                "source": "target_rollup.block",
                "detail": f"evidence-band block ({blk.get('status')}) fired while the recommendation gate did not",
                "blocking_axes": blk.get("blocking_axes"),
                "resolved_to": rec_val,
            }
        )
    return {
        "schema": "target_call.v1",
        "recommendation": rec_val,  # gate-forced when gate.fired OR gate.forced_by=="positive_tier"; on abstention a negative is clamped to insufficient
        "gate": rg,  # ← recommendation_gate (owns the value when gate.fired or the strong positive tier forced a nominate)
        "confidence": confidence_tier,  # ← confidence_tier
        "deciding_axis": deciding_axis,  # ← deciding_axis
        "gate_scorecard": gate_scorecard,  # ← gate_scorecard
        "dissent": dissent,  # NEW: independent signals that disagree with the gate
        "_note": (
            "Unified DECISION view + CANONICAL OWNER of the decision spine (target_report.target_call). "
            "VERDICT-INERT COMPOSITION; recommendation_gate remains the sole owner of the "
            "recommendation. The four spine objects nest here and are no longer top-level "
            "nomination keys (full-nest 2026-09-03)."
        ),
    }


def build_target_coherence(sub_results: dict, target_rollup: "Optional[dict]" = None) -> dict:
    """target_coherence.v1 — thesis classification + thesis-relative coherence, ON TOP of the rollup.
    Reads only UN-CONTAMINATED signals (cis_coherence, dependency, genomic rule-class, surface_modality);
    NEVER alteration-role or actionability arms (both contaminated). Verdict-inert; never gates; emits a
    PARALLEL note, never overwrites confidence_tier."""
    dep_v, _dr = _rollup_sv(sub_results, "dependency")
    _gv, gen_r = _rollup_sv(sub_results, "genomic_alteration")
    cis_v, _cr = _rollup_sv(sub_results, "cis_coherence")
    surf_v, _sr = _rollup_sv(sub_results, "surface_modality")
    bio = _biology_axis_from_surface(surf_v)
    reclassified = None
    if bio == "surface_intrinsic":
        if (gen_r or "").startswith("cn-amplified"):
            thesis, co, actionable = "amplification_overexpression_antigen", ["surface_antigen_no_dependency"], True
        else:
            thesis, co, actionable = "surface_antigen_no_dependency", [], True
            if (gen_r or "").startswith("mut-") and dep_v in ("non_dependent", "non_dependent_paralog_buffered"):
                reclassified = "genomic 'driver' label is a mutation-spectrum artifact (cis-uncoupled + non_dependent)"
    elif bio == "intracellular_intrinsic":
        if cis_v == "coherent_cis_driver" and dep_v in ("lineage_selective", "broadly_dependent"):
            thesis, co, actionable = "oncogene_addiction_driver", [], True
        else:
            thesis, co, actionable = "lineage_survival_dependency", [], True
    else:
        thesis, co, actionable = "insufficient_thesis", [], None

    confirms, caveats, artifacts = [], [], []
    if thesis in ("surface_antigen_no_dependency", "amplification_overexpression_antigen"):
        if dep_v in ("non_dependent", "non_dependent_paralog_buffered"):
            caveats.append("non_dependent is EXPECTED for a surface antigen — coherent, not a red flag")
        if cis_v == "cis_uncoupled_no_dependency":
            confirms.append("cis-uncoupled: no dosage-driven dependency — coherent (cis-coupling is ANTI here)")
        if (gen_r or "").startswith("mut-"):
            artifacts.append(
                "genomic driver via mutation-spectrum, contradicted by cis-uncoupled + non_dependent → data_artifact"
            )
    elif thesis == "oncogene_addiction_driver":
        confirms.append("cis-coherent driver + lineage-selective dependency — coherent addiction core")
    coherence_class = "coherent" if not artifacts else "coherent_with_caveats"
    return {
        "schema": "target_coherence.v1",
        "thesis": {"primary": thesis, "co_theses": co, "actionable": actionable, "reclassified_note": reclassified},
        "coherence": {"class": coherence_class, "confirms": confirms, "caveats": caveats, "artifact_flags": artifacts},
        "_note": "VERDICT-INERT lens (thesis + thesis-relative coherence). Un-contaminated signals only; never gates.",
    }


def build_composed_evidence_graph(target_report: dict) -> dict:
    """composed_evidence_graph.v1 — a THIN, additive, DISPLAY-ONLY index over `target_report`: the target
    decision as a node/edge graph (the composed analog of the per-subskill
    decision.headline.evidence_graph). PURE PROJECTION — the verdict + skill nodes read target_call +
    skill_reports; edges are typed cross-lens relations that REFERENCE existing target_report rollups by a
    `ref` path and RECOMPUTE NOTHING. It gates nothing and never moves the recommendation (target_call
    owns it). This is the reconstruct-ability / consumer API for the composed decision, mirroring what the
    per-subskill graph gave the sub-skill dashboard (docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §2). Fail-soft:
    absent rollups → empty node/edge lists.
    """
    from _skills_common.report_render.vocab import SKILL_TOPICAL_LENS  # canonical short→lens map (one source)

    tr = target_report or {}
    tc = tr.get("target_call") or {}
    skill_reports = tr.get("skill_reports") or {}

    # deciding short(s) — the deciding_axis block has three basis-shapes (gate_fired / positive_signal /
    # abstention); read defensively.
    da = tc.get("deciding_axis") or {}
    deciding_shorts: list = []
    if isinstance(da.get("deciding_axis"), dict) and da["deciding_axis"].get("short"):
        deciding_shorts = [da["deciding_axis"]["short"]]
    elif isinstance(da.get("deciding_axes"), list):
        deciding_shorts = [r.get("short") for r in da["deciding_axes"] if isinstance(r, dict) and r.get("short")]
    deciding_set = set(deciding_shorts)

    conf = tc.get("confidence") if isinstance(tc.get("confidence"), dict) else {}
    verdict_node = {
        "recommendation": tc.get("recommendation"),
        "confidence": {"level": conf.get("level")},
        "deciding_shorts": deciding_shorts,
    }

    # skill nodes — one per short in skill_reports (verdict-inert projection)
    skills: list = []
    for short in sorted(skill_reports):
        rep = skill_reports.get(short)
        if not isinstance(rep, dict):
            continue
        eg = rep.get("evidence_graph") if isinstance(rep.get("evidence_graph"), dict) else None
        lit = (eg or {}).get("literature") or {}
        c = rep.get("confidence") if isinstance(rep.get("confidence"), dict) else {}
        skills.append(
            {
                "short": short,
                "lens": SKILL_TOPICAL_LENS.get(short),
                "role": rep.get("role"),
                "call": rep.get("call"),
                "polarity": rep.get("polarity"),
                "confidence": c.get("level"),
                "deciding": short in deciding_set,
                "has_evidence_graph": eg is not None,
                "literature_consistency": lit.get("overall_consistency"),
            }
        )

    edges: list = []
    # deciding_axis: verdict → the deciding skill(s)
    for s in deciding_shorts:
        edges.append(
            {"type": "deciding_axis", "from": "verdict", "to": s, "ref": "target_report.target_call.deciding_axis"}
        )
    # dissent: an independent signal disagreed with the gate (the honest 'why not higher/lower')
    for d in tc.get("dissent") or []:
        if isinstance(d, dict):
            edges.append(
                {
                    "type": "dissent",
                    "from": d.get("source"),
                    "to": "verdict",
                    "note": d.get("detail"),
                    "resolved_to": d.get("resolved_to"),
                    "ref": "target_report.target_call.dissent",
                }
            )
    # modality_fit: the limiting skill → each channel (worst-case fit per channel)
    for channel, mf in ((tr.get("modality_fit") or {}).get("by_channel") or {}).items():
        if isinstance(mf, dict):
            edges.append(
                {
                    "type": "modality_fit",
                    "from": mf.get("limiting_axis"),
                    "to": channel,
                    "signal": mf.get("fit"),
                    "ref": "target_report.modality_fit.by_channel",
                }
            )
    # risk: verdict → each governance risk dimension (deterministic 6-dim)
    risk = tr.get("risk_6dim") or {}
    if isinstance(risk, dict):
        for dim, rd in risk.items():
            if isinstance(rd, dict) and rd.get("bin") is not None:
                edges.append(
                    {
                        "type": "risk",
                        "from": "verdict",
                        "to": dim,
                        "bin": rd.get("bin"),
                        "ref": "target_report.risk_6dim",
                    }
                )
    # subtype convergence: the convergent molecular strata
    sc = tr.get("subtype_convergence") if isinstance(tr.get("subtype_convergence"), dict) else {}
    for st in sc.get("convergent_subtypes") or []:
        edges.append({"type": "subtype_convergence", "to": st, "ref": "target_report.subtype_convergence"})

    return {
        "schema": "composed_evidence_graph.v1",
        "verdict": verdict_node,
        "skills": skills,
        "edges": edges,
        "_note": (
            "Thin DISPLAY-ONLY index over target_report — the composed analog of the per-subskill "
            "evidence_graph. Edges reference existing rollups by `ref`; recomputes nothing; gates "
            "nothing; target_call owns the recommendation."
        ),
    }


def build_target_report(
    *,
    target_call: dict,
    target_rollup: "Optional[dict]" = None,
    target_coherence: "Optional[dict]" = None,
    ordinal_matrix: "Optional[dict]" = None,
    modality_fit_by_channel: "Optional[dict]" = None,
    modality_conjunction: "Optional[dict]" = None,
    risk_rollup: "Optional[dict]" = None,
    subtype_facet: "Optional[dict]" = None,
    biomarker_facet: "Optional[dict]" = None,
    fragility: "Optional[dict]" = None,
    heterogeneity: "Optional[dict]" = None,
    cross_gate_shared_evidence: "Optional[dict]" = None,
    magnitude_borderline: "Optional[object]" = None,
    certainty_by_axis: "Optional[dict]" = None,
    addressable_population: "Optional[dict]" = None,
    actionability_mode: "Optional[dict]" = None,
    competitor_crossref: "Optional[dict]" = None,
    archetype_companion: "Optional[dict]" = None,
    nomination_scorecard: "Optional[dict]" = None,
    nomination_predictive_score: "Optional[object]" = None,
    skill_reports: "Optional[dict]" = None,
) -> dict:
    """target_report.v1 — the unified per-target object (docs/UNIFIED_OUTPUT_CONTRACT.md).

    ADDITIVE + VERDICT-INERT: a composed VIEW that REFERENCES the existing target-level facets (which
    stay top-level until consumers migrate to read target_report). Recomputes NOTHING — `target_call`
    owns the recommendation; the rollups are the already-built projections. This is the scaffold the later
    consolidation (full-nest of the spine keys, risk_6dim migration, per-skill facet relocation) collapses
    into — and the object the deterministic-risk / literature migrations require to exist."""
    tr = target_rollup or {}
    report = {
        "schema": "target_report.v1",
        # the per-skill skill_report[] SPINE + its role-grouped roll-up — target_report's FIRST consumer of
        # the unified per-skill signals (docs/UNIFIED_OUTPUT_CONTRACT.md). Verdict-inert; the rollup carries
        # a target-level INV-6 coherence flag but never moves the recommendation (target_call owns it).
        "skill_reports": skill_reports,
        "skill_report_rollup": (
            build_skill_report_rollup(skill_reports, target_call, modality_fit_by_channel) if skill_reports else None
        ),
        "target_call": target_call,  # DECISION (recommendation owner = target_call.gate)
        "risk_6dim": risk_rollup,  # ← risk_rollup (deterministic 6-dim; None w/o substrate)
        "axis_rollup": tr.get("axes"),  # ← target_rollup.axes (A/B/D/E bands)
        "block": tr.get("block"),  # ← target_rollup.block (evidence-band shadow)
        "thesis": target_coherence,  # ← target_coherence
        "evidence_matrix": ordinal_matrix,  # ← ordinal_matrix_view
        "modality_fit": {"by_channel": modality_fit_by_channel, "conjunction": modality_conjunction},
        "subtype_convergence": subtype_facet,  # ← subtype_facet (convergent_subtypes)
        "biomarker": biomarker_facet,
        "robustness": {
            "fragility": fragility,
            "heterogeneity": heterogeneity,
            "correlated_evidence": cross_gate_shared_evidence,
            "borderline": magnitude_borderline,
            "certainty_by_axis": certainty_by_axis,
        },
        "addressable_population": addressable_population,
        "actionability_mode": actionability_mode,
        "competitive_positioning": competitor_crossref,
        "archetype": archetype_companion,
        "nomination_scorecard": nomination_scorecard,
        "predictive_score": nomination_predictive_score,
        "_note": (
            "Unified per-target object (target_report.v1). VERDICT-INERT composition over the "
            "existing target-level facets, which remain top-level until consumers migrate. "
            "target_call owns the recommendation; nothing here is recomputed."
        ),
    }
    # additive DISPLAY-ONLY composed index over this report — the composed analog of the per-subskill
    # decision.headline.evidence_graph (P6). Pure projection; recomputes nothing; verdict spine untouched.
    report["evidence_graph"] = build_composed_evidence_graph(report)
    return report


__all__ = [
    "build_target_rollup",
    "build_target_coherence",
    "build_target_call",
    "build_target_report",
    "build_composed_evidence_graph",
    "_ADDRESSABLE_POPULATION_LEGEND",
    "_BIOMARKER_INPUTS",
    "_BIOMARKER_QUANT",
    "_CN_FUSION_SELECTION_VERDICTS",
    "_FRAGILITY_LEGEND",
    "_HETEROGENEITY_LEGEND",
    "_MATRIX_MODALITIES",
    "_NON_DEPENDENT",
    "_SNV_SELECTION_VERDICTS",
    "_SUBTYPE_INPUTS",
    "_actionability_mode_facet",
    "_addressable_population_class",
    "_addressable_population_facet",
    "_biomarker_facet",
    "_presence_facet",
    "_competitor_crossref_facet",
    "_framework_preferred_modalities",
    "_modality_conjunction_facet",
    "_biomarker_quantitative",
    "_classify_biomarker_best_roles",
    "_cv",
    "_deciding_axis",
    "_decision_role",
    "_find_card_summary",
    "_first_card_per_subgroup",
    "_fragility_facet",
    "_heterogeneity_facet",
    "_load_contested_threshold",
    "_load_subtype_crosswalk",
    "_norm_entropy",
    "_ordinal_matrix",
    "_backfill_subtype_spine",
    "_strongest_signal_for_modality",
    "_subgroup_flip_view",
    "_subtype_facet",
    "_subtype_stratum_key",
]
