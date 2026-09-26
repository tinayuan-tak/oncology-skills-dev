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
# TRANSLATIONAL dim; clinical/commercial are the engine-blind pseudo-card dims.
#
# CORRECTED 2026-09-16: this comment used to end "every grounded axis now reaches a risk dim". That was
# FALSE BY MEASUREMENT — 7 of the 16 rostered subskill axes reach no dim (504-target corpus). The claim
# is not repaired by widening the map; it is repaired by DECLARING each absence, because the absences
# are not all the same kind. See AXIS_DIM_EXCLUSIONS below: an axis is now required to be in exactly
# one of {AXIS_TO_DIM, AXIS_DIM_EXCLUSIONS}, so a NEW axis can no longer reach no dim SILENTLY — which
# is exactly how this drifted (the 2026-08-21 consolidation dropped two mapped axes and the comment
# asserting completeness outlived them).
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

# ── declared absences from AXIS_TO_DIM (substrate Step 2d follow-on) ─────────────────────────────
# Why this map exists: an axis missing from AXIS_TO_DIM is INVISIBLE. Nothing distinguished "this axis
# must never reach a risk dim" from "nobody wired it yet", so both read as an absence — and an absence
# cannot be reviewed. The two are opposite actions, which is the same argument the per-dim evidence
# coverage below makes about bins.
#
# The three states are three DIFFERENT reasons for the same absence, and only one of them is a TODO:
#   DECLARED_DESCRIPTIVE   settled — verdict=None, so there is nothing to project (4 axes).
#   DECLARED_CONTEXT_TIER  settled 2026-09-16 — verdict-BEARING but gate-less BY DESIGN, so Decision 3
#                          (below) forbids the bin; already displayed AND counted on its dim (2 axes).
#   OPEN_PENDING_REVIEW    NOT a decision — a verdict-bearing, live axis absent from the risk VIEW with
#                          nothing in writing justifying it (now 1 axis: subtype_fit).
#
# WHY OPEN_PENDING_REVIEW EXISTED AT ALL, and why two of its three tenants have now left it: the written
# rationales for those axes all concern `_SHORT_TO_GATE` (tp_fanout), the kill/hold NOMINATION gate, while
# risk_6dim is a PROJECTION — a different consumer. "Must never drive the nomination spine" justifies
# exclusion from the gate and, ON ITS OWN, says nothing about this map. What closed the question was not
# that argument but Decision 3, which makes the gate roster the ORACLE for bin membership: under it,
# gate-less is not merely uninformative about the dim, it is DISQUALIFYING. Note the asymmetry that makes
# the oracle safe to lean on — being a gate is NECESSARY, not SUFFICIENT (2 of the 8 gates are unread by
# `deterministic_bins`), so no test here may infer the converse.
#
# ★ RETRACTED 2026-09-16, THE SAME DAY IT WAS WRITTEN. This comment used to end: "Resolving an OPEN
# entry MOVES BINS (it adds a conjunction member), so it is not additive: it needs a per-verdict-value
# direction judgement, golden snapshots, and a corpus re-measure." THAT IS FALSE, and it was refuted by
# the obvious measurement nobody had run: `deterministic_bins` NEVER READS THIS MAP. It reads the
# sub-verdicts it wants directly (`sv.get("dependency")`, `sv.get("safety")`, …) and hardcodes each
# dim's contribution table inline. Adding all three OPEN axes to AXIS_TO_DIM and re-projecting the
# 504-target corpus x 5 modalities moved 0 of 2520 bins, while 2520 of 2520 `evidence_coverage`
# payloads changed — a PAIRED control, so the null result is not a silent no-op.
#
# AXIS_TO_DIM has exactly three readers and NOT ONE of them sets a bin:
#   1. `evidence_coverage_by_dim` below — which axes COUNT as evidence for a dim (Step 2d);
#   2. `report_render.ir._dim_members` — which subskills are DISPLAYED under a dim;
#   3. `risk_rollup.project` — routes grounded literature onto a dim as an ESCALATE-ONLY annotation,
#      and its own docstring locks that "Grounding NEVER moves a bin" (2026-09-03).
# So mapping an axis is a VISIBILITY change, not a governance change. To make an axis actually
# contribute to a bin you must edit `deterministic_bins`' inline tables — a separate, larger decision.
#
# ★ AND THERE IS A SECOND MAP, which this file failed to mention: `report_render.ir._CONTEXT_DIM`
# already routes 6 of the 7 axes declared below onto a dim, displayed as `context` companions —
# cis_coherence + combination_vulnerability -> biological, target_intrinsic + immune_context ->
# druggability, translational_readiness -> translational, literature_context -> commercial. The two
# maps are DISJOINT and that is deliberate (verdict-bearing members vs descriptive companions), but it
# means "absent from AXIS_TO_DIM" != "reaches no dim": only `subtype_fit` is in NEITHER map. Keep them
# disjoint — `_dim_members` appends from both WITHOUT DEDUPE, so an axis in both is displayed TWICE.
# `test_axis_dim_mapping_completeness.py` now pins both facts.
DECLARED_DESCRIPTIVE = "declared_descriptive"  # verdict=None BY DESIGN — mapping it would be inert
# ★ NEW 2026-09-16: verdict-BEARING, but deliberately NOT a scorecard gate, so it must never feed a bin.
# This state exists because `declared_descriptive` could not hold these two: that state asserts "no verdict
# to project" and is CHECKED against narrator_lenses, so parking a live verdict-bearing axis there would
# (correctly) red `test_declared_descriptive_axes_are_genuinely_verdictless`. The absence needed its own
# reason, not the nearest available one. See THE GOVERNING PRINCIPLE below.
DECLARED_CONTEXT_TIER = "declared_context_tier"
OPEN_PENDING_REVIEW = "open_pending_review"  # verdict-bearing + live, absence UNJUSTIFIED in writing
AXIS_DIM_EXCLUSION_STATES: frozenset = frozenset({DECLARED_DESCRIPTIVE, DECLARED_CONTEXT_TIER, OPEN_PENDING_REVIEW})

# ── THE GOVERNING PRINCIPLE: a dim's bin rolls up its GATES, so a gateless axis cannot be a member ──
#
# target-contracts `docs/design/RISK_CATEGORY_DASHBOARD_SPINE.md` Decision 3 (approved): "a category's
# risk level is a ROLL-UP of its gates' statuses, computed not authored … derives from the member GATES'
# scorecard statuses … so the category rollup can NEVER DISAGREE with the per-gate verdicts."
#
# MEASURED 2026-09-16 (AST scan of every `sv.get("…")` inside `deterministic_bins`, not by eye) —
# it implements Decision 3 with ZERO exceptions. Every sub_verdict axis it reads is a scorecard gate in
# tp_fanout._SHORT_TO_GATE, and no gateless axis is read:
#
#   reads + gated   dependency · mechanism · safety · selectivity · surface_modality · tractability_sm  6/6
#   gated, unread   genomic_alteration · differentiation      (gate ⇒ NECESSARY, not SUFFICIENT — 2 of 8)
#   gateless, read  — none —
#
# (Count corrected in the writing: `selectivity` IS read, by the safety dim's normal-breadth conjunction.
# The conclusion does not depend on the tally, but a wrong tally in a rationale invites a wrong edit.)
# Note the bins ALSO read card `interpretation_call`s directly (normal-tissue-liability-gtex, sc-normal,
# modality-therapeutic-window, shed-ectodomain). Decision 3 constrains AXIS membership, so those are out
# of its scope and out of the guard's — do not read the guard as "bins read nothing but gates".
#
# ⇒ THE DECISION ON `cis_coherence` / `immune_context` IS THEREFORE **NO**: they must not become verdict
# members of their dim. Both are DELIBERATELY absent from `_SHORT_TO_GATE`, so under Decision 3 they have
# no gate status for a bin to roll up. This is now pinned by
# `test_deterministic_bins_reads_only_scorecard_gate_axes` — the machine-checkable form of Decision 3,
# which had been approved but never enforced.
#
# ★ AND NOTE WHAT "PROMOTE" WOULD ACTUALLY DO, because it is NOT what the map name suggests: AXIS_TO_DIM
# does not make an axis verdict-bearing — `deterministic_bins`'s hardcoded contribution tables do (that is
# the same fact the retraction above establishes). Editing AXIS_TO_DIM alone would make the HTML DROP the
# `context` tag it renders per member (`backends/html.py` `_mem_row`) while the engine still ignored the
# axis entirely: a member DISPLAYED as verdict-bearing whose verdict reaches no bin. That is the exact
# MIRROR of the coverage undercount fixed in #1419 — there the report displayed more than it counted, here
# it would claim more than it computes. Both are the same defect class: a display claim the computation
# does not honour. The `context` tag is currently TRUE, and keeping it true is the point.

AXIS_DIM_EXCLUSIONS = {
    # --- settled: run.py passes verdict_fn=None, so there is no verdict to project (measured null on
    # 504/504 corpus targets). These satisfy must-not-gate STRUCTURALLY (verdict=None + gate=None).
    "target_intrinsic": {
        "state": DECLARED_DESCRIPTIVE,
        "reason": "GATELESS DESCRIPTIVE peer (2026-08-17): target-intrinsic/run.py has synthesis:none "
        "=> verdict_fn is None => verdict=None. The indication-INDEPENDENT biology dossier informs the "
        "LLM synthesis, never a bin. 504/504 corpus verdicts null, so a mapping would be inert.",
    },
    "combination_vulnerability": {
        "state": DECLARED_DESCRIPTIVE,
        "reason": "CONSOLIDATED relational (gene x gene) annex, verdict=None: its payload is a RANKED "
        "PARTNER TABLE + relational claim_vector, NOT a scalar verdict, so there is nothing to bin. "
        "NOTE its two predecessors (synthetic_lethal_partners / combinatorial_dependency) DID map to "
        "`biological` before the 2026-08-21 consolidation; dropping them was CORRECT, not a regression, "
        "because the replacement is deliberately verdict=None. 504/504 corpus verdicts null.",
    },
    "translational_readiness": {
        "state": DECLARED_DESCRIPTIVE,
        "reason": "GATELESS DESCRIPTIVE peer (2026-08-31), exact target-intrinsic precedent: "
        "verdict_fn=None => verdict=None. Model availability / PDX / organoid context informs "
        "CONFIDENCE, not a nomination gate. 504/504 corpus verdicts null.",
    },
    "literature_context": {
        "state": DECLARED_DESCRIPTIVE,
        "reason": "GATELESS DESCRIPTIVE peer (2026-09-02) AND the module contract: verdict_fn=None per "
        "RISK_ASSESSMENT_INTEGRATION.md S4 (cited-literature co-occurrence is CONTEXT/CONFIDENCE), plus "
        "this module's own rule that THE LLM/LITERATURE NEVER SETS A BIN. Doubly justified. Its "
        "cited-literature-evidence card reaches NO governance bin by ANY path: it is not in this map, "
        "not in AXIS_TO_DIM, and is never read by risk_rollup.project() (which routes only "
        "ground_axis per-engine-axis substrate, not this skill's card). Even the engine-axis grounding "
        "overlay is confidence-annotation-only and CANNOT move a bin (risk_rollup grounding NEVER moves "
        "a bin, locked 2026-09-03). Measured: 1489 pmid-bearing cited_statements live under "
        "synthesis.evidence_capsules.literature_context and reach no dim BY CONTRACT, not by omission.",
    },
    # --- SETTLED 2026-09-16: verdict-bearing, but gate-less BY DESIGN, so Decision 3 excludes them from
    # a bin. Both are already DISPLAYED on their dim as `context` companions and (since #1419) COUNTED in
    # its evidence coverage. Context-tier is their terminal state, not a waypoint — the remaining
    # difference from a verdict member is exactly the difference Decision 3 requires.
    "cis_coherence": {
        "state": DECLARED_CONTEXT_TIER,
        "reason": "NOT A VERDICT MEMBER, DECIDED (was OPEN_PENDING_REVIEW; the open question is now "
        "answered NO). It has a DECIDED role one tier down: it GRADUATED at nomination-gate v1.6.0 "
        "(2026-08-20) to a CONFIDENCE-tier axis in nomination_verdict_gate.yaml — positive_signal "
        "`coherent_cis_driver`, positive_contradiction `expressed_cis_coupled_inert` blocking `strong`, "
        "correlated_dimension group [genomic_alteration, cis_coherence] — with NO `gates` action, so it "
        "can never cross the kill boundary: it moves CONFIDENCE, not Go/No-Go. Promoting it to a "
        "risk_6dim bin member would UPGRADE that tier, because risk_6dim IS `citable_in_nominations` "
        "(UNIFIED_OUTPUT_CONTRACT Decision 2, 2026-09-03: 'may be governance-load-bearing'), so a bin is "
        "a citable governance claim while `target_call` stays the sole go/hold/kill gate. Under Decision "
        "3 it has no gate status for `biological` to roll up. Verdict-BEARING and LIVE: 504/504 corpus "
        "targets, 7 distinct verdicts "
        "(coherent_cis_driver 76, coherent_cis_loss_of_function 116, expressed_cis_coupled_inert 111, "
        "cis_uncoupled_no_dependency 105, dependency_without_cis_dosage 60, "
        "coherent_epigenetic_silencing 32, insufficient_cis_coherence 4) — so its absence here is a "
        "CHOICE, not an oversight, which is why it needed a state of its own rather than "
        "declared_descriptive. BOTH REACHABLE CONSUMERS ALREADY SEE IT: ir._CONTEXT_DIM DISPLAYS it "
        "under `biological`, and COVERAGE_ONLY_AXES (#1419) COUNTS its 3733 resolved cards toward that "
        "dim's evidence line (measured state=measured on 504/504). The only remaining difference from a "
        "verdict member is the bin itself — exactly the difference Decision 3 requires. It does "
        "discriminate (coherent_cis_driver 53 LOW / 3 MED / 20 HIGH against the biological bin vs "
        "coherent_epigenetic_silencing 32/32 HIGH), and that is NOT an argument for promotion: a "
        "confidence-tier axis is supposed to be informative. Note also that `biological` is "
        "max(dependency, mechanism), so any added leg could only ESCALATE.",
    },
    "immune_context": {
        "state": DECLARED_CONTEXT_TIER,
        "reason": "NOT A VERDICT MEMBER, DECIDED (was OPEN_PENDING_REVIEW; answered NO on TWO "
        "independent grounds). (1) DECISION 3: it is deliberately out of _SHORT_TO_GATE, documented as "
        "GATELESS/ADDITIVE and 'kept off the gate pending calibration', so `druggability` has no gate "
        "status of its own to roll up. (2) IT WOULD NOT EARN THE BIN EVEN IF THE RULE ALLOWED IT: 88.7% of "
        "targets are non-directional (immune_intermediate 314 + insufficient 86 + "
        "lymphoid_denominator_unreliable 47 of 504), only 57/504 are hot/cold, and hot vs cold show "
        "near-identical safety-bin splits => it does not discriminate risk. AND the change would be "
        "STRUCTURAL, not additive: `druggability` is the one SINGLE-LEG dim (deterministic_bins sets "
        "dims['druggability']['bin'] = INV[r] with its `sig` left dead), so adding a leg means "
        "converting a citable bin to a max-conjunction — a weak, undescribed-on-86/504 axis is the worst "
        "possible reason to do that. ★ EARLIER FRAMING CORRECTED: this entry used to call the dim "
        "UNDECIDED and blame a flat axis->dim dict for not expressing modality-conditioning. The dim was "
        "ALREADY DECIDED — ir._CONTEXT_DIM routes it to `druggability` with a written rationale (the TCE "
        "effector-arm companion to surface-modality-fit, NOT the clinical-precedent bin) matching an "
        "approved mockup — and modality-conditioning was never needed for a map that cannot move a bin. "
        "As COVERAGE it is real (1773 resolved cards) and is COUNTED via COVERAGE_ONLY_AXES since #1419.",
    },
    # --- STILL OPEN, and the ONE entry Decision 3 does NOT settle. Kept OPEN deliberately: the blocker
    # is upstream of this file, in `skills/target-profile/`, so this branch cannot close it.
    "subtype_fit": {
        "state": OPEN_PENDING_REVIEW,
        "reason": "THE GENUINELY OPEN ONE, and the ONLY rostered axis in NEITHER map (every other axis "
        "declared here reaches a dim via ir._CONTEXT_DIM), so it is invisible in the report AND "
        "uncountable in the coverage join. ★ TWO EARLIER CLAIMS IN THIS ENTRY CORRECTED 2026-09-16, "
        "because they pointed at the wrong fix. (1) IT IS NOT GATELESS — it is one of only THREE "
        "recommendation-forcing axes (tp_gates._GATING_AXES = {dependency, safety, subtype_fit}), and "
        "('subtype_fit','subtype_specific_non_dependence') FORCES overall_recommendation to `hold`. So "
        "the Decision-3 argument that settles cis_coherence / immune_context above does NOT apply here: "
        "of the three axes once parked in this state, this is the one WITH a governance claim, not the "
        "weakest. (2) THE SPARSITY IS NOT A COVERAGE GAP — 433/504 nulls are SCOPE FORECLOSURE BY "
        "DESIGN. It is in _SCOPE_OPTIN_GATING_AXES, whose own comment states its SILENCE IS THE "
        "DORMANT/OK STATE, because treating it as a gap 'would wrongly DECLINE every target on the "
        "(default) no-subtypes path'. Reading 348/504-emitting + 71 non-null as thin evidence inverts "
        "that. ★ AND THE ROOT CAUSE IS NOT AN EMISSION BUG (the prior 'fix the emission first' was "
        "wrong): it is the FACET-LESS INLINE TIER. tp_fanout builds results[SUBTYPE_SHORT] with "
        "skill_dir=None ('not a directory sub-skill; composed inline') and no `synthesis_facet`, so "
        "tp_facets._skill_reports_by_short — which requires r['synthesis_facet']['skill_report'] — skips "
        "it, hence 0/504 synthesis.skill_reports entries, hence no `provenance`, hence invisible to "
        "_axis_card_provenance, evidence_coverage_by_axis, and _dim_members (which appends only `if "
        "short in skill_reports`). NOTE 0/504 is the count for `synthesis.skill_reports`; a probe of a "
        "TOP-LEVEL `skill_reports` key returns None for all 504 and measures nothing. So NO MAPPING IN "
        "THIS FILE CAN FIX IT — correct conclusion, different reason: not because emission is broken, "
        "but because this axis is not a directory sub-skill and the report spine is keyed on facets. "
        "The residual is real and BOUNDED: even on the 71 ACTIVE targets a `hold`-forcing axis carries "
        "no provenance the report can show. Closing it means wiring a build_skill_report call in "
        "tp_fanout (feasible — build_skill_report requires only role+verdict, cards_used/cards_missing "
        "optional), which is OUT OF SCOPE for this branch and carries a REGRESSION RISK worth stating: "
        "_modality_scope_by_axis currently falls back to _claim_record_shadow_by_axis BECAUSE the report "
        "is absent, so emitting a report without `modality_scope` could regress modality_fit.",
    },
}


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
#
# ── which axes COUNT as evidence for a dim (vs which are merely DISPLAYED under it) ───────────────
# MEASURED DEFECT this closes (2026-09-16): the report DISPLAYS 6 axes under `biological` while this
# coverage line COUNTED 4, because `_dim_members` unions AXIS_TO_DIM with `ir._CONTEXT_DIM` and the
# roll-up below read AXIS_TO_DIM alone. Corpus-wide that hid 14291 resolved cards under a dim whose own
# coverage line did not count them — e.g. `biological` reading "4/4 axes measured · 43 cards resolved"
# on a target where 6 axes reported and 56 cards resolved. A dim understating its OWN evidence is the
# same lossiness this whole block exists to remove.
#
# WHY A THIRD MAP INSTEAD OF WIDENING AXIS_TO_DIM. The two questions are genuinely different:
#   AXIS_TO_DIM       = is this axis a VERDICT-bearing member of the dim?   (nothing here sets a bin,
#                       but it is also read by `_dim_members` and `risk_rollup`)
#   COVERAGE_ONLY_AXES = does this axis's EVIDENCE count toward the dim's coverage line?
# Coverage counts CARDS, not verdicts, so `verdict_fn=None` is simply the wrong gate on it:
# `combination_vulnerability` has no verdict and 3024 resolved cards corpus-wide. Widening AXIS_TO_DIM
# instead would (a) make it non-disjoint from `_CONTEXT_DIM` and so render each axis TWICE under its dim
# (`_dim_members` does not dedupe — see `test_axis_to_dim_and_context_dim_are_disjoint`), and (b) hand
# `risk_rollup` new literature-annotation targets as a side effect of a display decision.
#
# THE INCLUSION RULE, and it is the one `evidence_coverage_by_axis` below already states: do not surface
# a CONSTANT dressed as a per-run signal. An axis that is `undescribed` on every run contributes only a
# caveat that always fires ("not descriptor-covered: X" on 504/504) — noise, and properly the descriptor
# work queue. So the discriminator is whether the axis's state VARIES / is descriptor-covered at all:
#   COUNTED   cis_coherence             measured 504/504, 3733 cards   -> biological 4/4 -> 6/6
#             combination_vulnerability  measured 504/504, 3024 cards
#             target_intrinsic           measured 428 / UNMEASURED 76   -> a real evidence gap, the exact
#                                                                          thing this block exists to say
#             immune_context             measured 418 / undescribed 86  -> caveat fires on 86, not 504
#   NOT       translational_readiness    undescribed 504/504            -> permanent caveat, no signal
#             literature_context         undescribed 504/504            -> and it is the ONLY axis in
#                                        `commercial`, so counting it would replace that dim's honest
#                                        "card-fed dim — no subskill axis reports into it" with
#                                        "0/1 axes measured", which reads as a MEASURED CLAIM OF
#                                        BLINDNESS. Measured on 504/504 targets; that guard is why the
#                                        naive "just union the two maps" fix is wrong.
# The earlier version of this module applied that rule to ALL SIX context axes when it only justified the
# bottom two. VERDICT-INERT: no bin reads this map (see the retraction above AXIS_DIM_EXCLUSIONS).
COVERAGE_ONLY_AXES = {
    "cis_coherence": "biological",
    "combination_vulnerability": "biological",
    "target_intrinsic": "druggability",
    "immune_context": "druggability",
}

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
    context companions can be read too. `evidence_coverage_by_dim` surfaces the AXIS_TO_DIM axes PLUS the
    `COVERAGE_ONLY_AXES` context companions, and deliberately still omits `translational_readiness` /
    `literature_context`: their measurement_types carry no SALIENCE_SPEC, so they are `undescribed` on 504
    of 504 runs and surfacing them per-run would ship a CONSTANT dressed as a per-run signal. They belong
    in the descriptor work queue until the specs land — see the inclusion rule above COVERAGE_ONLY_AXES."""
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

    `axes_declared` is every axis that COUNTS as evidence for the dim — AXIS_TO_DIM's verdict-bearing
    members plus the `COVERAGE_ONLY_AXES` context companions, so the count matches what the report
    DISPLAYS under the dim (`ir._dim_members` unions the same two kinds). `axes_reported` are those that
    actually emitted a report. Both are surfaced because they DIFFER meaningfully: clinical / commercial
    declare an axis that is never a fan-out subskill (their bin comes from the clinical-precedent /
    competitor-landscape CARDS), so `axes_declared` non-empty with `axes_reported` empty is the honest
    reading "this dim is card-fed, not axis-fed" — not "this dim is blind".

    The dim SET stays AXIS_TO_DIM's, not the union's: COVERAGE_ONLY_AXES may only annotate a dim that
    already exists here (pinned by `test_coverage_only_axes_add_no_new_dim`), so this cannot invent a dim.

    The three named lists are kept SEPARATE rather than summed into one blind-spot count: an evidence gap
    (`unmeasured`), a never-resolved axis (`unresolved`) and a descriptor gap (`undescribed`) call for
    three different actions, and collapsing them is exactly the lossiness the substrate pivot removes."""
    per_axis = evidence_coverage_by_axis(pkg)
    # verdict-bearing members first, then the coverage-only companions — canonical, stable order.
    counted = {**AXIS_TO_DIM, **COVERAGE_ONLY_AXES}
    out: dict = {}
    for dim in dict.fromkeys(AXIS_TO_DIM.values()):
        declared = [a for a, d in counted.items() if d == dim]
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
    # Re-synced to the resolver's live 8-token safety verdict set (_SAFETY_VERDICT_PHRASE,
    # on-target-safety-liability run.py). The p1 pan_essential_broad_tox_concern (dominant) and p2
    # normal_tissue_protein_safety_concern are measured HOLD concerns and score HIGH (2) per their
    # precedence — they were silently absent, so both fell through the `.get(...,0)` default to LOW
    # (fail-toward-safe on a governance-citable axis; #1573). The retired v2.0.0 downgrade tokens
    # (wt_*_mechanism_mismatch) and the phantom moderately_constrained_safety_concern are dropped;
    # data_unavailable / insufficient are gaps, not concerns, and stay at the 0 default.
    ots = {
        "highly_constrained_safety_concern": 2,
        "pan_essential_broad_tox_concern": 2,
        "normal_tissue_protein_safety_concern": 2,
        "human_genetics_safety_concern": 1,
        "moderately_constrained_safety": 1,
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
    # sc-normal veto: read the GRADED instrument the verdict-active consumers honor DIRECTLY off the
    # summary field, NOT the blunt interpretation_call. The blunt `sc_normal_expression_class` ==
    # HIGH_LIABILITY fires on ANY high normal cell (incl. tissue-of-origin epithelium / non-essential
    # cells) and is 94% saturated — the exact bluntness the graded veto (AM#647/TC#786) was built to
    # replace. The card DECLARES primary_class: sc_normal_essential_veto_grade, and post-#1541
    # `_primary_class_value(summary, card_id)` is contracts-first so it now honors that declaration —
    # but this rung reads the graded field by name off the summary regardless, so it is robust whether
    # or not the caller threaded the card_id. The surface killer
    # (sc-normal-high-liability-bite-killer) and the selectivity clamp (tvn-sc-normal-critical-organ-veto)
    # both fire ONLY on grade ∈ {accessible_high_severity, accessible_ungraded}; accessible_moderate_severity
    # / accessible_low_confidence / bbb_protected are relieved (opposing, no veto). Mirror that here so the
    # risk rung inherits the same grading — a validated ADC/TCE antigen at HIGH normal expression that the
    # grade relieves must NOT raise this rung.
    _scn_grade = _card(pkg, "sc-normal-celltype-expression").get("sc_normal_essential_veto_grade")
    if _scn_grade in ("accessible_high_severity", "accessible_ungraded"):
        sig = max(sig, esc)
        chain.append(("sc-normal", _scn_grade, INV[esc]))
    if calls.get("modality-therapeutic-window") in ("essential_tissue_liability", "no_window"):
        sig = max(sig, esc)
        chain.append(("therapeutic-window", calls.get("modality-therapeutic-window"), INV[esc]))
    if surf and calls.get("shed-ectodomain-liability") == "clinically_shed":
        sig = max(sig, 1)
        chain.append(("shed-ectodomain", "clinically_shed", "MED"))
    # The mutant-selective "mitigated IF mutant-selective chemistry" downgrade was RETIRED at resolver
    # v2.0.0 (2026-08-24): the resolver now emits the raw per-modality concern with no wt_*_mechanism_mismatch
    # token, so this branch was gated on two dead tokens and could never fire (#1573). Removed — no safety
    # mitigation string is currently produced.
    dims["safety"] = {
        "pillar": "Right Safety",
        "bin": INV[sig],
        "chain": chain,
        "mitigation": None,
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
        # #1568: annotation_only_indirect is a NEGATIVE-polarity token (_TRACTABILITY_NEGATIVE in the
        # resolver, added v1.5.0→1.7.0 AFTER this map was frozen — the CASE-008 modality gate mints it
        # to mark a biologics-only approved antigen / undruggable TF with NO direct SM binder). It is a
        # sibling of chemically_unhit / structurally_intractable and must read HIGH(2), not silently
        # default to MED. `insufficient` is a resolver COVERAGE GAP ("never a verdict"), not a negative
        # finding: it is keyed EXPLICITLY at MED(1) — the same value as the default, but pinned so a
        # coverage gap is a governance-citable choice and is NOT escalated to HIGH. INV has no
        # data-unavailable bin, so a full abstention treatment is out of scope for this single-leg map.
        r = {
            "well_covered": 0,
            "chemically_confirmed_genetic": 0,
            "chemically_active": 0,
            "measured_potent_ligand": 0,
            "discordant": 1,
            "insufficient": 1,
            "chemically_unhit": 2,
            "structurally_intractable": 2,
            "annotation_only_indirect": 2,
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
    "AXIS_DIM_EXCLUSIONS",
    "AXIS_DIM_EXCLUSION_STATES",
    "COVERAGE_ONLY_AXES",
    "DECLARED_DESCRIPTIVE",
    "OPEN_PENDING_REVIEW",
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
