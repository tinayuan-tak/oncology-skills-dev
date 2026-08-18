#!/usr/bin/env python3
"""cross-evidence-hypothesis — the framework's decision-facing cross-evidence INTEGRATOR (WS4).

A composed skill sitting ABOVE target-profile. It consumes ORTHOGONAL grounded evidence —
target-profile's `evidence_package` (indication-conditioned sub-verdicts + cards), the
target-intrinsic DOSSIER (indication-independent target biology), and the optional 6-dim
literature-RISK read — and reasons ACROSS them into a DEFENSIBLE, CITED, gate-CLAMPED drug-target
hypothesis (causal_rationale, therapeutic_hypothesis, population, therapeutic_window, evidence_grade,
go_forth) plus typed cross-line EDGES and EVIDENCE PATHS.

The load-bearing invariant (roadmap §1): the integrator ENRICHES; it never OVERRIDES. The model
PROPOSES a verdict but a DETERMINISTIC, FAIL-CLOSED, GATE-COMPLETE ceiling (hypothesis_core.gate_ceiling,
consuming synthesis.recommendation_gate.hard_gates) CLAMPS it — where the proposed verdict exceeds the
spine's hard-gate ceiling, the ceiling wins and the tension is SURFACED. Defensibility is an ENFORCED
contract: retrieve-don't-recall PMIDs, clause-traceability-with-teeth (untraceable → blocks promotion),
absence-discipline (an absent line supports nothing), independence-before-certainty (correlated cards
sharing an evidence_substrate count once).

Two-call pipeline (ported from framework-runs/cross-dim-agent/hypothesis_agent.py):
  CALL 1 — propose typed cited edges + principal tensions + evidence_paths (cross-line reasoning).
  CALL 2 — assemble the six-part hypothesis GIVEN the edges/paths/tensions.
The LLM call is injectable (`synthesize_fn`) so the deterministic spine is unit-testable offline.

Run:  BEDROCK_AWS_PROFILE=cmp-dev python3 run.py \
        --evidence-package <target-profile evidence_package.json> \
        --target-dossier   <target-intrinsic decision.json>      (optional) \
        --substrate safety=safety.json selectivity=sel.json ...  (optional; per-subskill ground_axis) \
        --risk             <6-dim risk decision.json>            (optional) \
        --modality small_molecule                                (controlled enum)

Grounded literature enters the hypothesis NATIVELY via `--substrate` (per-subskill ground_axis blocks),
NOT via the risk projection — the two projections (6-dim risk + this hypothesis) are SIBLINGS off the
one shared substrate (grounded-substrate two-projection design §13). The substrate is escalate-only: it
enriches the panel + adds citable PMIDs + surfaces engine↔literature discordance as tensions, but never
lowers the deterministic gate ceiling.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hypothesis_core as hc  # noqa: E402

SKILL_NAME = "cross-evidence-hypothesis"
SKILL_VERSION = "0.2.0"   # 0.1.0→0.2.0: WS4 DRIFT-GUARD (§9 — pinned prompt_template_hash + model_id
                          # + offline golden-set drift-CI) and the intra-package COHERENCE step
                          # (WS5 adversarial-survival root-cause fix). Deferred: content-addressed
                          # provenance manifest; curated truth-set eval (WS6).


# --- LLM prompts (ported + extended for subtype-resolved reasoning) ---------------------------------
EDGE_SYSTEM = (
    "You are the cross-evidence reasoning step for oncology target assessment. You are given a PANEL "
    "of orthogonal evidence lines (each: a deterministic verdict + a short interpretation) and "
    "grounded literature risk reads. Your ONLY job here is the INTERACTIONS ACROSS lines — do NOT "
    "re-judge any single line and do NOT write a hypothesis yet.\n"
    "You are ALSO given the indication-INDEPENDENT TARGET BIOLOGY dossier (mechanism/pathway role, "
    "interactome, paralogy, domain/structure, safety genetics) — use it to reason about HOW the "
    "indication-conditioned lines fit the target's fundamental biology (pathway role CONDITIONS a "
    "dependency; paralogy TENSIONS_WITH a monotherapy dependency).\n"
    "If SUBTYPE-RESOLVED per-stratum records are given, reason at subtype resolution where the "
    "records support it (e.g. dependency strong in MSS but absent in MSI-H), citing the stratum name.\n"
    "CRITICAL — actively hunt for INTERNAL CONTRADICTIONS where a POSITIVE line's thesis is undercut "
    "by a NEGATIVE or absent SIBLING line measuring the SAME biology, and emit an explicit "
    "`contradicts` edge for each. In particular: a synthetic-lethal / combination signal "
    "(synthetic-lethal-partners, combinatorial-dependency) is CONTRADICTED by "
    "partner-conditional-dependency=no_partner_mapped (a combination has no actionable partner to pair "
    "with); a monotherapy dependency is contradicted by paralog-buffering / dependency=non_dependent; "
    "an amplified/enriched-population claim is contradicted by copy-number-distribution=broadly_neutral. "
    "Emit: (a) typed EDGES — conditions | corroborates | tensions_with | contradicts — each with a "
    "one-line rationale citing ONLY card_ids / sub-verdict names / rule_ids / panel PMIDs / dossier "
    "field names / stratum names; (b) principal_tensions — the few disagreements that most bear on "
    "the decision; (c) evidence_paths — string signals into ordered CHAINS building to a "
    "decision-relevant claim, each step citing what it rests on. A line whose verdict is "
    "insufficient / data_unavailable carries NO weight — do not build an edge or path on it (you may "
    "note its absence as a tension). Cite-or-abstain; never cite from memory."
)

EDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "edges": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"type": "string",
                     "enum": ["conditions", "tensions_with", "corroborates", "contradicts"]},
            "from_dimension": {"type": "string"}, "to_dimension": {"type": "string"},
            "rationale": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}}},
            "required": ["type", "from_dimension", "to_dimension", "rationale", "citations"]}},
        "principal_tensions": {"type": "array", "items": {"type": "object", "properties": {
            "statement": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}}},
            "required": ["statement", "citations"]}},
        "evidence_paths": {"type": "array", "items": {"type": "object", "properties": {
            "claim": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "signal": {"type": "string"}, "citation": {"type": "string"}},
                "required": ["signal", "citation"]}},
            "leads_to": {"type": "string", "enum": [
                "causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window"]}},
            "required": ["claim", "steps"]}},
    },
    "required": ["edges", "principal_tensions", "evidence_paths"],
}

HYP_SYSTEM = (
    "You are the cross-evidence hypothesis agent for oncology target assessment. Reason ACROSS the "
    "orthogonal evidence lines + the indication-INDEPENDENT target-biology dossier + grounded "
    "literature RISK reads and assemble a DEFENSIBLE, DATA-BACKED DRUG-TARGET HYPOTHESIS for this "
    "target in this indication/subtype — with enough substance to go forth to a validation plan.\n\n"
    "Ground causal_rationale in the target's mechanism/pathway role + genetics + dependency + "
    "expression; justify the therapeutic_hypothesis modality from domain/structure biophysics + "
    "tractability + modality-fit; read paralogy + interactome for combination/resistance; read "
    "safety genetics + selectivity into the therapeutic_window. When SUBTYPE-RESOLVED records are "
    "given, express population / causal_rationale / therapeutic_window at subtype resolution and "
    "cite the stratum name (e.g. 'dependency strong in MSS (n=NN) but absent in MSI-H').\n\n"
    "Assemble the six parts: (1) causal_rationale; (2) therapeutic_hypothesis (+ why this modality); "
    "(3) population (indication / subtype / biomarker); (4) therapeutic_window; (5) evidence_grade "
    "(per line); (6) go_forth (the single experiment/datum that would most confirm or kill it).\n\n"
    "HARD RULES: (a) EVERY clause MUST cite the evidence it rests on — card_ids, sub-verdict names, "
    "fired rule_ids, dossier field names, stratum names, or PMIDs present in the input. NEVER cite "
    "from memory. (b) Name where lines CORROBORATE and where they TENSION/CONTRADICT — the honest "
    "map matters more than a clean story. (b2) INTRA-PACKAGE COHERENCE — a positive-thesis clause "
    "(causal_rationale / therapeutic_hypothesis / population) may NOT assert a positive claim on a "
    "signal that ANOTHER line in this SAME package contradicts. If a line you cite is a MEASURED-"
    "NEGATIVE call (e.g. dependency=non_dependent_paralog_buffered, partner-conditional=no_partner_"
    "mapped, selectivity=not_selective), or if you emitted a `contradicts`/`tensions_with` EDGE "
    "touching a signal your clause rests on, you MUST surface that tension IN THE SAME CLAUSE — put "
    "the contradicting token in that clause's `contradicting_citations` AND state the tension in the "
    "clause text (e.g. 'a combination strategy is proposed BECAUSE monotherapy dependency is absent "
    "(dependency non_dependent_paralog_buffered)'). Do NOT list a contradicting line among plain "
    "`citations` as if it supported the claim — that is an internally-contradicted assertion and is "
    "rejected. (b3) SPECIFIC — do NOT propose a COMBINATION or SYNTHETIC-LETHAL strategy as the "
    "actionable vulnerability unless a partner-mapping line actually maps an actionable partner: if "
    "partner-conditional-dependency=no_partner_mapped (or synthetic_lethal_partners maps none), the "
    "combination is UNSUPPORTED — state that in the clause, put partner-conditional-dependency in "
    "contradicting_citations, and grade the line weak/absent; do NOT claim a biomarker-enriched "
    "(e.g. amplified) population when the copy-number line reads broadly_neutral. (c) Propose a "
    "verdict but know a deterministic gate will "
    "CLAMP it — if the evidence is compelling but a hard gate (safety/veto) opposes, SURFACE the "
    "tension. (d) ABSENCE: a line whose verdict is insufficient / data_unavailable / not_assessed "
    "carries NO weight — you may NOT cite an absent line as support; name such gaps in go_forth and "
    "grade those lines 'absent'. An honest low-certainty hypothesis with a clear next experiment is "
    "the goal — do not inflate confidence to fill a gap. go_forth is REQUIRED and must name the "
    "single most decision-changing next experiment (typically resolving the limiting gap or the "
    "principal tension)."
)

HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "causal_rationale": {"type": "object", "properties": {
            "statement": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}}},
            "required": ["statement", "citations"]},
        "therapeutic_hypothesis": {"type": "object", "properties": {
            "statement": {"type": "string"}, "modality": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}}},
            "required": ["statement", "modality", "citations"]},
        "population": {"type": "object", "properties": {
            "statement": {"type": "string"}, "indication": {"type": "string"},
            "subtype_or_biomarker": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}}},
            "required": ["statement", "citations"]},
        "therapeutic_window": {"type": "object", "properties": {
            "statement": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}},
            "contradicting_citations": {"type": "array", "items": {"type": "string"}}},
            "required": ["statement", "citations"]},
        "evidence_grade": {"type": "object", "properties": {
            "overall": {"type": "string", "enum": ["strong", "moderate", "weak", "insufficient"]},
            "per_line": {"type": "array", "items": {"type": "object", "properties": {
                "dimension": {"type": "string"},
                "strength": {"type": "string", "enum": ["strong", "moderate", "weak", "absent"]}},
                "required": ["dimension", "strength"]}}},
            "required": ["overall", "per_line"]},
        "proposed_verdict": {"type": "string", "enum": list(hc.VERDICT_RANK.keys())},
        "proposed_verdict_reason": {"type": "string"},
        "go_forth": {"type": "object", "properties": {
            "next_evidence": {"type": "string"}, "value_of_information": {"type": "string"}},
            "required": ["next_evidence"]},
    },
    "required": ["causal_rationale", "therapeutic_hypothesis", "population",
                 "therapeutic_window", "evidence_grade", "proposed_verdict",
                 "proposed_verdict_reason", "go_forth"],
}


# --- structured-output normalizers (ported) ---------------------------------------------------------
def _objs(lst) -> list:
    lst = hc._uv(lst)
    if isinstance(lst, dict):
        lst = lst.get("value") or lst.get("items") or []
    out = []
    for x in (lst or []):
        x = hc._uv(x)
        if isinstance(x, dict) and set(x.keys()) == {"value"} and isinstance(x["value"], dict):
            x = x["value"]
        if isinstance(x, dict):
            out.append(x)
    return out


def _all_clause_citations(out: dict) -> dict:
    m = {}
    for key in ("causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window"):
        c = hc._uv(out.get(key)) or {}
        c = c if isinstance(c, dict) else {}
        m[key] = list(c.get("citations") or []) + list(c.get("contradicting_citations") or [])
    for i, e in enumerate(_objs(out.get("edges"))):
        m[f"edge[{i}]:{e.get('type')}"] = list(e.get("citations") or [])
    for i, t in enumerate(_objs(out.get("tensions"))):
        m[f"tension[{i}]"] = list(t.get("citations") or [])
    for i, p in enumerate(_objs(out.get("evidence_paths"))):
        m[f"path[{i}]"] = [s.get("citation") for s in _objs(p.get("steps")) if s.get("citation")]
    return m


def _default_synthesize():
    """Lazy default LLM fn — import only when a real run needs Bedrock (keeps tests offline)."""
    from _skills_common.llm import synthesize_structured
    return synthesize_structured


# --- WS4 drift-guard provenance (roadmap §9): pin prompt_template_hash + model_id ------------------
def prompt_template_hash() -> str:
    """A stable sha256 over the DETERMINISTIC prompt SURFACE (both system prompts + both tool
    schemas) — INDEPENDENT of any single target's user prompt. A change to a prompt or a schema flips
    this hash, so the golden-set drift-CI (test_drift_guard) fails and forces a review + golden
    regeneration on any prompt/model change (roadmap invariant 7)."""
    h = hashlib.sha256()
    for part in (EDGE_SYSTEM, HYP_SYSTEM,
                 json.dumps(EDGE_SCHEMA, sort_keys=True),
                 json.dumps(HYPOTHESIS_SCHEMA, sort_keys=True)):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _resolve_model_id(llm_mode: str) -> str:
    """The model_id pinned into provenance. For an offline/injected run there is no Bedrock model, so
    record the mode; for a live run resolve the framework synthesis-model pin without importing boto3
    at test time."""
    if llm_mode != "bedrock":
        return f"offline:{llm_mode}"
    try:
        from _skills_common.bedrock_client import FRAMEWORK_SYNTHESIS_MODEL
        return FRAMEWORK_SYNTHESIS_MODEL
    except Exception:  # noqa: BLE001 — provenance must never crash the run
        return "unknown"


def replay_synthesize(replay: dict):
    """Deterministic offline synthesize_fn backed by a CANNED two-call response dict
    ({"cross_edges": {...}, "hypothesis": {...}}). Powers `--no-llm --llm-replay <file>` and the
    offline golden-set drift-CI: identical inputs → identical deterministic spine outputs, no Bedrock."""
    def _synth(system, user, name, schema, **kw):
        if name not in replay:
            raise KeyError(f"--llm-replay file has no canned response for call {name!r} "
                           f"(have: {sorted(replay)})")
        return replay[name]
    return _synth


def _panel_block(panel: dict, objective: str) -> str:
    ctx = panel["context"]
    tgt = (ctx.get("target") or {}).get("symbol") if isinstance(ctx.get("target"), dict) \
        else ctx.get("target")
    _ind = ctx.get("indication")
    ind = (_ind.get("name") or _ind.get("oncotree_code")) if isinstance(_ind, dict) else _ind
    subtype = panel["subtype"]
    scoped_subtype = ctx.get("subgroup_spec") or (
        ", ".join(subtype["requested_strata"]) if subtype["requested_strata"] else None)
    dossier_block = ""
    if panel["dossier"]:
        dossier_block = (
            "TARGET BIOLOGY — indication-INDEPENDENT dossier (mechanism + pathway role, interactome, "
            "paralogy, domain/structure, on-target-safety genetics). Cite these field names:\n"
            f"{json.dumps(panel['dossier'], indent=1, default=str)}\n\n")
    subtype_block = ""
    if subtype["present"] and subtype["per_stratum"]:
        subtype_block = (
            "SUBTYPE-RESOLVED per-stratum records (cite the stratum name; a stratum axis with "
            "n_floor_met_by_axis=false is UNDERPOWERED — do not credit it):\n"
            f"{json.dumps(subtype['per_stratum'], indent=1, default=str)}\n\n")
    # per-subskill GROUNDED SUBSTRATE — the design-correct literature path (§13): escalate-only
    # per-axis literature findings, each ANCHORED to the axis it augments. The engine may MISS these;
    # they RAISE a concern, never lower one. Their PMIDs are in the citation surface (cite them).
    grounded_block = ""
    gs = panel.get("grounded_substrate") or {}
    if gs.get("present") and gs.get("per_axis"):
        grounded_block = (
            "GROUNDED per-axis SUBSTRATE — escalate-only literature findings, EACH ANCHORED to its "
            "axis (the deterministic engine may MISS these; a finding may RAISE that axis's concern, "
            "never lower it). Cite the PMIDs listed. An axis with contradicts_deterministic=true "
            "DISAGREES with that axis's deterministic verdict — you MUST surface it as a tension:\n"
            f"{json.dumps(gs['per_axis'], indent=1, default=str)}\n\n")
    return (
        f"OBJECTIVE (modality): {objective}\nMODALITY (controlled): {panel['modality']}\n"
        f"TARGET: {tgt}\nINDICATION: {ind}\nSCOPED SUBTYPE: {scoped_subtype}\n\n"
        f"{dossier_block}{subtype_block}"
        f"PANEL — deterministic verdict per INDICATION-CONDITIONED line:\n"
        f"{json.dumps(panel['conviction'], indent=1, default=str)}\n\n"
        f"PANEL — per-card interpretation (card_id -> call; cite these card_ids):\n"
        f"{json.dumps(panel['cards_brief'], indent=1, default=str)}\n\n"
        f"{grounded_block}"
        f"GROUNDED literature risk reads:\n{json.dumps(panel['risk'], indent=1, default=str)}\n\n"), \
        tgt, ind, scoped_subtype


def run(pkg_path: str, risk_path=None, objective: str = "small-molecule drug target",
        modality=None, dossier_path=None, synthesize_fn=None, llm_mode=None,
        substrate=None) -> dict:
    """Assemble the panel, run the two-call pipeline, clamp, and enforce the defensibility contract.
    `synthesize_fn(system, user, name, schema, max_tokens=...)` is injectable for offline testing.
    `llm_mode` labels provenance: 'bedrock' (default live), 'offline_replay', or 'injected' (a test
    stub); it never changes the deterministic spine, only what model_id is pinned.
    `substrate` is the per-subskill GROUNDED SUBSTRATE (dict axis→ground_axis block): the design-correct
    literature path (§13) — its findings enrich the panel + its PMIDs become citable, and any axis that
    contradicts its deterministic verdict is surfaced as a tension. Escalate-only: it never lowers the
    deterministic ceiling."""
    if llm_mode is None:
        llm_mode = "bedrock" if synthesize_fn is None else "injected"
    modality_resolved, modality_inferred = hc.resolve_modality(modality, objective)
    panel = hc.assemble(pkg_path, risk_path, dossier_path, modality_resolved, substrate=substrate)
    synth = synthesize_fn or _default_synthesize()
    panel_block, tgt, ind, scoped_subtype = _panel_block(panel, objective)

    # CALL 1 — typed cited edges + tensions + evidence paths
    edge_out = synth(EDGE_SYSTEM, panel_block + "Emit typed cross-line edges, principal tensions, "
                     "and evidence_paths. Cite only card_ids / sub-verdict names / rule_ids / panel "
                     "PMIDs / dossier fields / stratum names.", "cross_edges", EDGE_SCHEMA,
                     max_tokens=8000)
    edges = _objs(edge_out.get("edges"))
    tensions = _objs(edge_out.get("principal_tensions"))
    paths = _objs(edge_out.get("evidence_paths"))

    # CALL 2 — assemble the six-part hypothesis ON the edges/paths/tensions
    hyp_user = (
        panel_block +
        f"CROSS-LINE EDGES (build on these):\n{json.dumps(edges, indent=1, default=str)}\n\n"
        f"EVIDENCE PATHS (signal chains to a claim):\n{json.dumps(paths, indent=1, default=str)}\n\n"
        f"PRINCIPAL TENSIONS:\n{json.dumps(tensions, indent=1, default=str)}\n\n"
        "Assemble the drug-target hypothesis. Cite on EVERY clause. Reflect tensions honestly. Fill "
        "go_forth with the single most decision-changing next experiment. Propose a verdict; a gate "
        "will clamp it.")
    hyp_out = synth(HYP_SYSTEM, hyp_user, "hypothesis", HYPOTHESIS_SCHEMA, max_tokens=6000)
    out = {**hyp_out, "edges": edges, "tensions": tensions, "evidence_paths": paths}

    # --- deterministic FAIL-CLOSED GATE-COMPLETE clamp (the ceiling; the model never overrides) ---
    gate = hc.gate_ceiling(panel["pkg"], modality=modality_resolved)
    proposed = hc._scalar(out.get("proposed_verdict"))
    computed, was_clamped = hc.clamp(proposed, gate["ceiling"])
    gate_tension = None
    if was_clamped:
        gate_tension = (f"HYPOTHESIS proposed '{proposed}' but the deterministic gate caps at "
                        f"'{gate['ceiling']}' ({gate['reason']}). The evidence read is not permitted "
                        f"to override the gate — surfaced, not resolved in the hypothesis's favour.")

    # --- clause traceability WITH TEETH (§6.3–6.5) ---
    surface = panel["citation_surface"]
    clause_cites = _all_clause_citations(out)
    untraceable = {k: bad for k, bad in
                   ((k, hc.check_traceability(v, surface)) for k, v in clause_cites.items()) if bad}
    n_clauses = len(clause_cites)
    n_clean = sum(1 for k, v in clause_cites.items() if not hc.check_traceability(v, surface))
    traceability = round(n_clean / n_clauses, 3) if n_clauses else None

    # --- uncertainty / gaps (orthogonal clamp: bounds CONFIDENCE) + substrate + degradation discount
    conviction = panel["conviction"]
    oos = hc.out_of_scope_dims(modality_resolved)
    in_scope = [d for d in conviction if d not in oos]
    gaps = hc.data_gaps({d: conviction[d] for d in in_scope})
    base_certainty, limiting = hc.weakest_link_certainty(conviction, in_scope)

    degraded_inputs = []
    if not panel["dossier_present"]:
        degraded_inputs.append("dossier")
    if not panel["risk_present"]:
        degraded_inputs.append("risk")
    substrate = panel["substrate"]
    cert = hc.discounted_certainty(base_certainty, substrate["n_independent_units"], degraded_inputs)

    # absence-discipline WITH TEETH: a SUPPORTING clause may not cite a gap-line sub-verdict.
    gapset = set(gaps)
    support_clauses = ("causal_rationale", "therapeutic_hypothesis", "population",
                       "therapeutic_window")
    absence_violations = {}
    for key in support_clauses:
        c = hc._uv(out.get(key)) or {}
        c = c if isinstance(c, dict) else {}
        cited_gaps = [tok for tok in (c.get("citations") or []) if tok in gapset]
        if cited_gaps:
            absence_violations[key] = cited_gaps

    # --- INTRA-PACKAGE COHERENCE WITH TEETH (§6.5 / WS5): a positive-thesis clause may not assert on
    # a signal another present line contradicts (measured-negative cited as support, or one end of the
    # agent's OWN contradicts/tensions_with edge) unless it surfaces the tension. ---
    coherence_clauses = {}
    for key in support_clauses:
        c = hc._uv(out.get(key)) or {}
        c = c if isinstance(c, dict) else {}
        coherence_clauses[key] = {
            "support": list(c.get("citations") or []),
            "surfaced": list(c.get("contradicting_citations") or []),
        }
    present_norm = {hc._norm(t) for t in (surface["card_ids"] | surface["sub_verdicts"]
                                          | surface["rule_ids"])}
    card_calls = {cid: call for cid, call in (panel.get("cards_brief") or {}).items()
                  if isinstance(call, str)}
    coherence_v = hc.coherence_violations(coherence_clauses, conviction, edges, tensions,
                                          present_norm, out_of_scope=oos, card_calls=card_calls)
    # SURFACE each detected tension into the structured `tensions` slot (fold-into-tensions), so the
    # contradiction is carried explicitly, never buried — without mutating any LLM clause prose
    # (invariant 9). coherence_v (as DETECTED) still blocks promotion below (the teeth).
    coherence_surfaced_tensions = hc.surface_coherence_tensions(coherence_v)
    if coherence_surfaced_tensions:
        tensions = tensions + coherence_surfaced_tensions
        out["tensions"] = tensions

    # --- GROUNDED-SUBSTRATE discordance surfacing (§13, escalate-only): for each axis whose grounded
    # literature CONTRADICTS its deterministic verdict, surface a DETERMINISTIC tension (tagged
    # grounded_substrate_discordance) citing the axis + its grounded PMIDs — so the engine↔literature
    # disagreement is carried explicitly for a reviewer/skeptic. This RAISES a concern; it never lowers
    # the ceiling (the clamp above already ran off the package hard_gates alone). ---
    grounded = panel.get("grounded_substrate") or {}
    grounded_discordance_tensions = []
    for ax in grounded.get("discordant_axes", []):
        rec = next((r for r in grounded.get("per_axis", []) if r.get("axis") == ax), {})
        pmids = sorted({p for f in rec.get("findings", []) for p in (f.get("cited_pmids") or [])})
        grounded_discordance_tensions.append({
            "statement": (f"grounded literature on the '{ax}' axis contradicts its deterministic "
                          f"verdict '{rec.get('anchor_verdict')}' — an escalate-only concern the "
                          "engine's narrow verdict may have missed"),
            "citations": [ax] + pmids, "axis": ax,
            "source": "grounded_substrate_discordance"})
    if grounded_discordance_tensions:
        tensions = tensions + grounded_discordance_tensions
        out["tensions"] = tensions

    # --- minimum-inputs gate (§12): enough non-gap in-scope decision lines to reason over? ---
    n_supporting = sum(1 for d in in_scope if conviction.get(d) not in hc.GAP_VERDICTS)
    minimum_inputs_met = n_supporting >= 2

    # --- promotion gate (teeth): untraceable / absence-violation / coherence / below-minimum BLOCK ---
    promotion_blockers = []
    if untraceable:
        promotion_blockers.append("untraceable_citations")
    if absence_violations:
        promotion_blockers.append("absence_discipline_violations")
    if coherence_v:
        promotion_blockers.append("intra_package_coherence_violations")
    if not minimum_inputs_met:
        promotion_blockers.append("insufficient_inputs")
    promotable = not promotion_blockers
    # a non-promotable hypothesis can never present a permissive verdict — cap at advanceable_flagged
    if not promotable and hc.VERDICT_RANK[computed] > hc.VERDICT_RANK["advanceable_flagged"]:
        computed = "advanceable_flagged"
        was_clamped = True

    return {
        "skill": SKILL_NAME, "skill_version": SKILL_VERSION,
        "target": tgt, "indication": ind, "objective": objective,
        "modality": {"resolved": modality_resolved, "inferred_from_objective": modality_inferred,
                     "out_of_scope_dimensions": sorted(oos)},
        "hypothesis": {
            "causal_rationale": hc._uv(out.get("causal_rationale")),
            "therapeutic_hypothesis": hc._uv(out.get("therapeutic_hypothesis")),
            "population": hc._uv(out.get("population")),
            "therapeutic_window": hc._uv(out.get("therapeutic_window")),
            "evidence_grade": hc._uv(out.get("evidence_grade")),
            "tensions": _objs(out.get("tensions")),
            "go_forth": hc._uv(out.get("go_forth")),
        },
        "edges": _objs(out.get("edges")),
        "evidence_paths": _objs(out.get("evidence_paths")),
        "verdict": {
            "proposed_by_agent": proposed, "computed": computed, "was_clamped": was_clamped,
            "gate_ceiling": gate["ceiling"], "gate_reason": gate["reason"],
            "gate_fail_closed": gate["fail_closed"],
            "hard_gates_present": gate["hard_gates_present"],
            "active_vetoes": gate["active_vetoes"], "blind_gates": gate["blind_gates"],
            "opposing_gates": gate["opposing"], "modality_excluded_gates": gate["excluded"],
            "gate_clamp_tension": gate_tension, "reason": hc._uv(out.get("proposed_verdict_reason")),
        },
        "defensibility": {
            "clause_traceability": traceability, "untraceable_citations": untraceable,
            "n_clauses": n_clauses, "n_fully_traceable": n_clean,
            "coherence_violations": coherence_v,
            "n_coherence_violations": sum(len(v) for v in coherence_v.values()),
            "n_coherence_tensions_surfaced": len(coherence_surfaced_tensions),
            "promotable": promotable, "promotion_blockers": promotion_blockers,
        },
        "uncertainty": {
            "overall_certainty": cert["final"], "base_certainty": cert["base"],
            "certainty_capped": cert["capped"], "cap_reasons": cert["cap_reasons"],
            "limiting_dimension": limiting, "data_gaps": gaps,
            "absence_discipline_violations": absence_violations,
        },
        "evidence_independence": {
            "correlated_evidence_discounted": substrate["correlated_evidence_discounted"],
            "correlated_groups": substrate["correlated_groups"],
            "n_independent_units": substrate["n_independent_units"],
            "n_distinct_substrates": substrate["n_distinct_substrates"],
            "n_untagged_cards": substrate["n_untagged_cards"],
        },
        "subtype_resolved": {
            "present": panel["subtype"]["present"],
            "scoped_subtype": scoped_subtype,
            "requested_strata": panel["subtype"]["requested_strata"],
            "available_strata": panel["subtype"]["available_strata"],
            "convergence_facet": panel["subtype"]["convergence_facet"],
        },
        "degraded_mode": {
            "dossier_present": panel["dossier_present"], "risk_present": panel["risk_present"],
            "grounded_substrate_present": panel.get("grounded_substrate_present", False),
            "degraded_inputs": degraded_inputs, "minimum_inputs_met": minimum_inputs_met,
            "n_supporting_in_scope_lines": n_supporting,
        },
        # --- GROUNDED SUBSTRATE (§13): the per-axis literature findings the hypothesis reasoned over,
        # the count of grounded PMIDs folded into the citation surface, and the engine↔literature
        # discordant axes surfaced as tensions above. Informational (escalate-only; never caps the
        # verdict) — but it is the auditable record that literature reached the hypothesis NATIVELY
        # (per-subskill), not via the risk projection. ---
        "grounded_substrate": {
            "present": grounded.get("present", False),
            "n_findings": grounded.get("n_findings", 0),
            "n_grounded_pmids": len(grounded.get("pmids") or ()),
            "discordant_axes": grounded.get("discordant_axes", []),
            "n_discordance_tensions_surfaced": len(grounded_discordance_tensions),
            "per_axis": grounded.get("per_axis", []),
        },
        # --- optional intrinsic-quality slot (WS5). adversarial_survival is null until the optional
        # post-check (scripts/adversarial_survival.py, needs Bedrock) is run; the deterministic
        # coherence guard above is the always-on, offline sibling of that skeptic pass. ---
        "quality": {"adversarial_survival": None},
        # --- WS4 drift-guard provenance (roadmap §9): the two PINS the golden-set drift-CI freezes ---
        "provenance": {
            "skill": SKILL_NAME, "skill_version": SKILL_VERSION,
            "prompt_template_hash": prompt_template_hash(),
            "model_id": _resolve_model_id(llm_mode), "llm_mode": llm_mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "panel_conviction": conviction,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="cross-evidence hypothesis integrator (WS4)")
    ap.add_argument("--evidence-package", required=True,
                    help="target-profile evidence_package.json (the indication-conditioned panel)")
    ap.add_argument("--target-dossier", default=None,
                    help="target-intrinsic decision.json (indication-independent target biology)")
    ap.add_argument("--risk", default=None, help="6-dim literature-risk decision.json (optional)")
    ap.add_argument("--substrate", nargs="*", default=[], metavar="AXIS=PATH",
                    help="per-subskill GROUNDED SUBSTRATE blocks (ground_axis output), as axis=path "
                         "(e.g. safety=safety.json selectivity=sel.json). The DESIGN-CORRECT literature "
                         "path (§13): findings enrich the panel + PMIDs become citable; discordant axes "
                         "surface as tensions. Escalate-only — never lowers the deterministic ceiling.")
    ap.add_argument("--objective", default="small-molecule drug target",
                    help="free-text objective (narration only)")
    ap.add_argument("--modality", default=None, choices=sorted(hc.MODALITY_SCOPE),
                    help="controlled modality enum (overrides objective inference)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--no-llm", action="store_true",
                    help="OFFLINE deterministic run: use --llm-replay canned responses instead of "
                         "Bedrock (powers the golden-set drift-CI; the deterministic spine is identical)")
    ap.add_argument("--llm-replay", default=None,
                    help="canned two-call response JSON ({\"cross_edges\":{...},\"hypothesis\":{...}}) "
                         "for --no-llm")
    args = ap.parse_args(argv)

    synthesize_fn, llm_mode = None, None
    if args.no_llm:
        if not args.llm_replay:
            print("--no-llm requires --llm-replay <canned response json>", file=sys.stderr)
            return 2
        synthesize_fn = replay_synthesize(json.loads(Path(args.llm_replay).read_text()))
        llm_mode = "offline_replay"

    # load the per-subskill grounded substrate blocks (axis=path), if any
    substrate = {}
    for spec in (args.substrate or []):
        if "=" not in spec:
            print(f"--substrate expects axis=path, got {spec!r}", file=sys.stderr)
            return 2
        ax, p = spec.split("=", 1)
        substrate[ax] = json.loads(Path(p).read_text())

    outd = Path(args.out)
    outd.mkdir(parents=True, exist_ok=True)
    print("→ assembling cross-evidence hypothesis ...", file=sys.stderr)
    r = run(args.evidence_package, args.risk, args.objective, args.modality, args.target_dossier,
            synthesize_fn=synthesize_fn, llm_mode=llm_mode, substrate=substrate or None)
    (outd / "hypothesis.json").write_text(json.dumps(r, indent=2, default=str))

    v = r["verdict"]
    print(f"\n=== {r['target']} / {r['indication']}  ({r['modality']['resolved']}) ===")
    print(f"VERDICT: {v['computed']}  (proposed {v['proposed_by_agent']}; ceiling {v['gate_ceiling']}"
          f" — {v['gate_reason']})")
    if v["gate_clamp_tension"]:
        print(f"  CLAMPED: {v['gate_clamp_tension']}")
    u = r["uncertainty"]
    print(f"CERTAINTY: {u['overall_certainty']} (base {u['base_certainty']}; "
          f"limited by {u['limiting_dimension']}; caps {u['cap_reasons']})")
    ei = r["evidence_independence"]
    if ei["correlated_evidence_discounted"]:
        print(f"  correlated evidence discounted: {ei['correlated_groups']}")
    d = r["defensibility"]
    print(f"DEFENSIBILITY: traceability={d['clause_traceability']} promotable={d['promotable']} "
          f"blockers={d['promotion_blockers']}")
    if d["coherence_violations"]:
        print(f"  COHERENCE: {d['n_coherence_violations']} intra-package contradiction(s): "
              f"{ {k: [x['type'] for x in v] for k, v in d['coherence_violations'].items()} }")
    gsub = r["grounded_substrate"]
    if gsub["present"]:
        print(f"GROUNDED SUBSTRATE: {gsub['n_findings']} finding(s) / {gsub['n_grounded_pmids']} "
              f"citable PMID(s) across {len(gsub['per_axis'])} axes"
              + (f"; discordant: {gsub['discordant_axes']}" if gsub["discordant_axes"] else ""))
    print(f"PROVENANCE: model={r['provenance']['model_id']} "
          f"prompt_template_hash={r['provenance']['prompt_template_hash'][:12]}… "
          f"mode={r['provenance']['llm_mode']}")
    print(f"wrote {outd}/hypothesis.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
