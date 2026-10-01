#!/usr/bin/env python3
"""cross-evidence-hypothesis — the framework's decision-facing cross-evidence INTEGRATOR.

A composed skill sitting ABOVE target-profile. It consumes ORTHOGONAL grounded evidence —
target-profile's `evidence_package` (indication-conditioned sub-verdicts + cards), the
target-intrinsic DOSSIER (indication-independent target biology), and the optional 6-dim
literature-RISK read — and reasons ACROSS them into a DEFENSIBLE, CITED, gate-CLAMPED drug-target
hypothesis (causal_rationale, therapeutic_hypothesis, population, therapeutic_window, evidence_grade,
go_forth) plus typed cross-line EDGES and EVIDENCE PATHS.

The load-bearing invariant: the integrator ENRICHES; it never OVERRIDES. The model
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
one shared substrate (grounded-substrate two-projection design). The substrate is escalate-only: it
enriches the panel + adds citable PMIDs + surfaces engine↔literature discordance as tensions, but never
lowers the deterministic gate ceiling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hypothesis_core as hc  # noqa: E402

# Shared anti-lore grounding fence. This skill puts the target gene name in-prompt and GENERATES
# biology, which is exactly the prior-knowledge-leak (KRAS blinding) case the directive was written
# for; append it to both generation prompts. Offline-safe (llm.py imports only stdlib at module level).
from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE  # noqa: E402
from _skills_common.skill_report import ROLE_DESCRIPTIVE, build_skill_report  # noqa: E402

SKILL_NAME = "cross-evidence-hypothesis"
SKILL_VERSION = "0.6.0"
# axis ROLES consumed from synthesis.skill_reports (a gateless descriptive lens is no longer a data gap
# and can no longer be named the limiting axis); certainty DISTRIBUTION alongside the weakest-link
# scalar; independence discount made reachable (tagged substrates only + graded caps + tagging_sparse);
# retrieve-don't-recall no longer reads n=/coordinates/TPM as PMIDs; modality scope resolves a card by
# its OWNING dimensions (multi-lens cards); immune_context in scope for adc + antibody; the scalar
# safety cap yields to a spine-DISPOSED hard-gate row.
# 0.4.0→0.5.0: P4 reconciliation — the spine's cross-gate correlation
# (independent decision-gate groups) tightens the certainty discount as the
# MORE conservative unit count (min with card-substrate); never more permissive.
# 0.3.0→0.4.0: consume the remaining decision_facets — cross_gate_shared_evidence
# (surfaced in evidence_independence, additive) + fragility/competitor into the
# LLM panel (P4/P5).
# 0.2.0→0.3.0: consume the spine's decision_facets layer — modality×safety
# seam (per-modality safety cap refinement + composed-modality mismatch) +
# per-axis CERTAINTY_MODEL certainty + confidence_tier cross-check.
# 0.1.0→0.2.0: DRIFT-GUARD (pinned prompt_template_hash + model_id
# + offline golden-set drift-CI) and the intra-package COHERENCE step
# (adversarial-survival root-cause fix). Deferred: content-addressed
# provenance manifest; curated truth-set eval.


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
    "note its absence as a tension). Cite-or-abstain; never cite from memory." + EVIDENCE_ONLY_DIRECTIVE
)

EDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["conditions", "tensions_with", "corroborates", "contradicts"]},
                    "from_dimension": {"type": "string"},
                    "to_dimension": {"type": "string"},
                    "rationale": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["type", "from_dimension", "to_dimension", "rationale", "citations"],
            },
        },
        "principal_tensions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["statement", "citations"],
            },
        },
        "evidence_paths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"signal": {"type": "string"}, "citation": {"type": "string"}},
                            "required": ["signal", "citation"],
                        },
                    },
                    "leads_to": {
                        "type": "string",
                        "enum": ["causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window"],
                    },
                },
                "required": ["claim", "steps"],
            },
        },
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
    "principal tension)." + EVIDENCE_ONLY_DIRECTIVE
)

HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        # contradicting_citations is declared on EVERY assertive clause (not just therapeutic_window):
        # HYP_SYSTEM instructs the model to surface an acknowledged tension IN THE SAME CLAUSE by
        # placing the contradicting token here, and both _all_clause_citations and the coherence teeth
        # READ it from all four clauses. Declaring it on only one clause meant the escape hatch depended
        # on an undeclared field for three clauses — so a legitimately acknowledged-tension clause could
        # fail the coherence guard. (contracts-first: schema now matches prompt + reader.)
        "causal_rationale": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
                "contradicting_citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["statement", "citations"],
        },
        "therapeutic_hypothesis": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                # controlled modality channel (matches hypothesis_core.MODALITY_SCOPE / the resolved
                # --modality vocabulary) so the proposed channel is cross-checkable, not free text.
                "modality": {"type": "string", "enum": sorted(hc.MODALITY_SCOPE)},
                "citations": {"type": "array", "items": {"type": "string"}},
                "contradicting_citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["statement", "modality", "citations"],
        },
        "population": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "indication": {"type": "string"},
                "subtype_or_biomarker": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
                "contradicting_citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["statement", "citations"],
        },
        "therapeutic_window": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
                "contradicting_citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["statement", "citations"],
        },
        "evidence_grade": {
            "type": "object",
            "properties": {
                "overall": {"type": "string", "enum": ["strong", "moderate", "weak", "insufficient"]},
                "per_line": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dimension": {"type": "string"},
                            "strength": {"type": "string", "enum": ["strong", "moderate", "weak", "absent"]},
                        },
                        "required": ["dimension", "strength"],
                    },
                },
            },
            "required": ["overall", "per_line"],
        },
        "proposed_verdict": {"type": "string", "enum": list(hc.VERDICT_RANK.keys())},
        "proposed_verdict_reason": {"type": "string"},
        "go_forth": {
            "type": "object",
            "properties": {"next_evidence": {"type": "string"}, "value_of_information": {"type": "string"}},
            "required": ["next_evidence"],
        },
    },
    "required": [
        "causal_rationale",
        "therapeutic_hypothesis",
        "population",
        "therapeutic_window",
        "evidence_grade",
        "proposed_verdict",
        "proposed_verdict_reason",
        "go_forth",
    ],
}


# --- structured-output normalizers (ported) ---------------------------------------------------------
def _objs(lst) -> list:
    lst = hc._uv(lst)
    if isinstance(lst, dict):
        lst = lst.get("value") or lst.get("items") or []
    out = []
    for x in lst or []:
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


def _edge_endpoint_warnings(edges: list, panel: dict) -> list:
    """Flag edges whose from/to_dimension is NOT a recognized dimension/card token. The coherence teeth
    (hypothesis_core.coherence_violations) match edge endpoints against the conviction/card vocabulary
    (normalized); an endpoint that is a HALLUCINATED or misspelled dimension silently fails to match, so
    a real contradiction the edge names can slip past the coherence guard. FLAG-only + verdict-INERT: a
    static enum would over-constrain (a package's conviction can carry dimensions absent from
    DIMENSION_CARDS, e.g. legacy combinatorial_dependency / synthetic_lethal_partners), so this records
    the unrecognized endpoints for a reviewer instead of forcing a fixed vocabulary."""
    recognized = {hc._norm(k) for k in (panel.get("conviction") or {})}
    recognized |= {hc._norm(k) for k in hc.DIMENSION_CARDS}
    recognized |= {hc._norm(c) for c in ((panel.get("citation_surface") or {}).get("card_ids") or set())}
    warnings = []
    for i, e in enumerate(edges or []):
        if not isinstance(e, dict):
            continue
        for role in ("from_dimension", "to_dimension"):
            tok = e.get(role)
            if tok and hc._norm(tok) not in recognized:
                warnings.append({"edge_index": i, "type": e.get("type"), "field": role, "value": tok})
    return warnings


def _default_synthesize():
    """Lazy default LLM fn — import only when a real run needs Bedrock (keeps tests offline)."""
    from _skills_common.llm import synthesize_structured

    return synthesize_structured


# --- drift-guard provenance: pin prompt_template_hash + model_id ------------------
def prompt_template_hash() -> str:
    """A stable sha256 over the DETERMINISTIC prompt SURFACE (both system prompts + both tool
    schemas) — INDEPENDENT of any single target's user prompt. A change to a prompt or a schema flips
    this hash, so the golden-set drift-CI (test_drift_guard) fails and forces a review + golden
    regeneration on any prompt/model change."""
    h = hashlib.sha256()
    for part in (
        EDGE_SYSTEM,
        HYP_SYSTEM,
        json.dumps(EDGE_SCHEMA, sort_keys=True),
        json.dumps(HYPOTHESIS_SCHEMA, sort_keys=True),
    ):
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
            raise KeyError(f"--llm-replay file has no canned response for call {name!r} (have: {sorted(replay)})")
        return replay[name]

    return _synth


# ── claim-vector SALIENCE GATE (scale-safe atom rendering) ──────────────────────────────────────────
# As more sub-skills emit atoms (fan-in → up to 13 axes), dumping every full atom drowns the
# decision-relevant one (salience dilution). The gate partitions claims into PRIMARY (render full
# citable values) vs SECONDARY (one-line tier only), so the panel stays legible as it scales.
_CV_INFORMATIVE = {"strong", "moderate", "weak", "negative"}  # measured + directional tiers
# Atom value-key fragments that signal decision-relevant distribution STRUCTURE even when the tier is
# flat — the BRAF/SKCM case: tier `unmeasured` (non_dependent_underpowered) but bimodality + a nonzero
# responder fraction reveal a hidden subpopulation. Salience must NOT gate on the tier alone.
_CV_NOTABLE_KEYS = ("fraction", "bimodal", "variance", "effect", "selectivity", "kruskal", "responder")
# Absolute PRIMARY cap (Group D, 2026-08-21): the tier partition bounds WHAT FRACTION renders full, but
# not the absolute count — a strongly-positive 13-axis target where most axes are informative could dump
# ~50-65 full-JSON atoms into the prompt. Cap the PRIMARY block at a deterministic top-N (assembly order:
# sub_results axis order, then per-short headline lines) and record the elided count, so the panel stays
# bounded at scale. SECONDARY is already one-line-per-claim (cheap) and stays uncapped. (The notable-key
# match is intentionally a SUBSTRING test — `bimodal` must match `bimodality_coefficient`, the BRAF case.)
_CV_PRIMARY_CAP = 30


def _atom_is_notable(atom: dict) -> bool:
    for k, v in ((atom or {}).get("values") or {}).items():
        if (
            any(p in k.lower() for p in _CV_NOTABLE_KEYS)
            and isinstance(v, (int, float))
            and not isinstance(v, bool)
            and v
        ):
            return True
    return False


def _render_capsule_data(caps_by_short: dict) -> str:
    """Render the per-sub-skill evidence-capsule DATA layer (synthesis.evidence_capsules) — the bounded
    RAW behind the classes, card-floor complete. COMPLEMENTS the claim-vector atoms: it surfaces only what
    the atoms do NOT carry — the on-INDICATION stratum, cross-source CONFLICTS, and DATA-QUALITY flags —
    so the retrieve-don't-recall agent can cite these card_ids/fields without prompt bloat or duplication.
    Salience-gated (indication row / conflict / DQ only); '' when no capsules (byte-stable for older packages)."""
    if not isinstance(caps_by_short, dict) or not caps_by_short:
        return ""
    lines = [
        "PANEL — evidence-capsule DATA (bounded raw behind the classes; card-floor complete; cite these "
        "card_ids). Complements the claim-vector atoms with the on-indication stratum, salient "
        "categoricals (clinical stage / competitor drugs), cross-source CONFLICTS, and DATA-QUALITY "
        "flags (treat flags as bugs to note, NOT as biology):"
    ]
    for short in sorted(caps_by_short):
        caps = (caps_by_short.get(short) or {}).get("capsules") or {}
        rows = []
        for cid in sorted(caps):
            c = caps[cid]
            if not isinstance(c, dict) or c.get("evidence_state") == "data_unavailable":
                continue
            frag = []
            ind = [r for r in (c.get("top_k_strata") or []) if r.get("role") == "INDICATION"]
            if ind:
                frag.append(f"indication_stratum {ind[0].get('stratum')}={ind[0].get('value')}(n={ind[0].get('n')})")
            if c.get("categorical_anchors"):
                frag.append("; ".join(f"{a.get('field')}={a.get('value')}" for a in c["categorical_anchors"]))
            if c.get("conflict_pairs"):
                cp = c["conflict_pairs"][0]
                frag.append(
                    f"CONFLICT(mt={cp.get('measurement_type')} vs {[o.get('card') for o in cp.get('other_sources', [])]})"
                )
            for dq in (c.get("data_quality_flags") or [])[:1]:
                frag.append(f"DATA_QUALITY: {str(dq.get('flag'))[:70]}")
            if frag:
                rows.append(f"    {cid}: " + " | ".join(frag))
        if rows:
            lines.append(f"  [{short}]")
            lines.extend(rows)
    return "\n".join(lines) + "\n\n" if len(lines) > 1 else ""


def _render_claim_vectors(cvs: dict) -> str:
    """Salience-gated rendering: PRIMARY claims (informative tier OR a conflict OR a notable atom)
    carry their full citable VALUES; SECONDARY claims collapse to a one-line tier (present, not
    competing for attention). The atom's card_id stays citable either way. Compact by design (drops the
    repeated _disclaimer / informs / entity / verbose cite.fields) so 13-axis fan-in stays legible."""
    if not cvs:
        return ""
    # PRIMARY entries are collected with a SALIENCE priority (lower = more decision-relevant) so the
    # top-N cut keeps the most important atoms rather than whatever fell in the first N by assembly
    # order (a conflict/strong atom on a late axis used to be silently dropped for an early neutral one).
    # priority: conflict=0, informative-signal / deterministic-headline=1, notable-only atom=2.
    prim_entries, sec = [], []  # prim_entries: (priority, order_index, text)
    for short, facet in cvs.items():
        if not isinstance(facet, dict):
            continue
        for ax, claim in (facet.get("claim_vector") or {}).items():
            if ax == "_disclaimer" or not isinstance(claim, dict):
                continue
            atom = claim.get("evidence_atom") or {}
            sig, corr, conflict = claim.get("signal"), claim.get("corroboration"), claim.get("conflict")
            cite = (atom.get("cite") or {}).get("card_id")
            informative, notable = sig in _CV_INFORMATIVE, _atom_is_notable(atom)
            if informative or bool(conflict) or notable:
                entry = {
                    "signal": sig,
                    "corroboration": corr,
                    "read": atom.get("read"),
                    "values": atom.get("values"),
                    "cite_card_id": cite,
                }
                if conflict:
                    entry["conflict"] = conflict
                priority = 0 if conflict else (1 if informative else 2)
                prim_entries.append((priority, len(prim_entries), f"  [{short}.{ax}] {json.dumps(entry, default=str)}"))
            else:
                sec.append(f"  [{short}.{ax}] {sig}/{corr}" + (f" [{cite}]" if cite else ""))
        ks = (facet.get("key_signals") or {}).get("headline")
        if ks:
            prim_entries.append((1, len(prim_entries), f"  [{short}] deterministic read: {ks}"))
    # rank by salience (stable within a priority via the recorded assembly index), THEN cap.
    prim_entries.sort(key=lambda e: (e[0], e[1]))
    prim = [t for _, _, t in prim_entries]
    elided = 0
    if len(prim) > _CV_PRIMARY_CAP:
        elided = len(prim) - _CV_PRIMARY_CAP
        prim = prim[:_CV_PRIMARY_CAP]  # top-N by SALIENCE (conflict > informative > notable), bound the prompt
    out = (
        "PANEL — claim-vector signal decomposition (SALIENCE-GATED for scale). PRIMARY claims carry "
        "their full citable atom VALUES — reason over them and cite the cite_card_id. SECONDARY "
        "claims are one-line tiers (uninformative/unremarkable for this target):\n"
    )
    out += "PRIMARY:\n" + ("\n".join(prim) if prim else "  (none)") + "\n"
    if elided:
        out += (
            f"  … (+{elided} more PRIMARY claim(s) elided for length; the {_CV_PRIMARY_CAP} shown are "
            "the highest-SALIENCE (conflict > informative > notable) — see the full "
            "nomination.json claim_vectors)\n"
        )
    if sec:
        out += "SECONDARY (tier-only):\n" + "\n".join(sec) + "\n"
    return out + "\n"


def _panel_block(panel: dict, objective: str) -> str:
    ctx = panel["context"]
    tgt = (ctx.get("target") or {}).get("symbol") if isinstance(ctx.get("target"), dict) else ctx.get("target")
    _ind = ctx.get("indication")
    ind = (_ind.get("name") or _ind.get("oncotree_code")) if isinstance(_ind, dict) else _ind
    subtype = panel["subtype"]
    scoped_subtype = ctx.get("subgroup_spec") or (
        ", ".join(subtype["requested_strata"]) if subtype["requested_strata"] else None
    )
    dossier_block = ""
    if panel["dossier"]:
        dossier_block = (
            "TARGET BIOLOGY — indication-INDEPENDENT dossier (mechanism + pathway role, interactome, "
            "paralogy, domain/structure, on-target-safety genetics). Cite these field names:\n"
            f"{json.dumps(panel['dossier'], indent=1, default=str)}\n\n"
        )
    subtype_block = ""
    if subtype["present"] and subtype["per_stratum"]:
        subtype_block = (
            "SUBTYPE-RESOLVED per-stratum records (cite the stratum name; a stratum axis with "
            "n_floor_met_by_axis=false is UNDERPOWERED — do not credit it):\n"
            f"{json.dumps(subtype['per_stratum'], indent=1, default=str)}\n\n"
        )
    # per-subskill GROUNDED SUBSTRATE — the design-correct literature path: escalate-only
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
            f"{json.dumps(gs['per_axis'], indent=1, default=str)}\n\n"
        )
    # Stage 2a — claim-vector SIGNAL decomposition + CITABLE evidence atoms per sub-skill. Each axis
    # carries a signal×corroboration tier PLUS an evidence_atom binding the load-bearing NUMERIC values
    # (bimodality, responder fraction, control-position, …) to {card_id, fields} + entity keys. Reason
    # over the atom VALUES, not just the verdict label; the atom's card_id is already a citable token.
    cv_block = _render_claim_vectors(panel.get("claim_vectors") or {})
    caps_block = _render_capsule_data((panel["pkg"].get("synthesis") or {}).get("evidence_capsules") or {})
    facets_block = _render_decision_facets(panel)
    return (
        (
            f"OBJECTIVE (modality): {objective}\nMODALITY (controlled): {panel['modality']}\n"
            f"TARGET: {tgt}\nINDICATION: {ind}\nSCOPED SUBTYPE: {scoped_subtype}\n\n"
            f"{dossier_block}{subtype_block}"
            f"PANEL — deterministic verdict per INDICATION-CONDITIONED line:\n"
            f"{json.dumps(panel['conviction'], indent=1, default=str)}\n\n"
            f"PANEL — per-card interpretation (card_id -> call; cite these card_ids):\n"
            f"{json.dumps(panel['cards_brief'], indent=1, default=str)}\n\n"
            f"{cv_block}"
            f"{caps_block}"
            f"{facets_block}"
            f"{grounded_block}"
            f"GROUNDED literature risk reads:\n{json.dumps(panel['risk'], indent=1, default=str)}\n\n"
        ),
        tgt,
        ind,
        scoped_subtype,
    )


def _render_decision_facets(panel: dict) -> str:
    """P5 — surface the spine's verdict-INERT decision facets the panel should reason over:
      - fragility.contested + acquisition_backlog: how solid the call is + which BLIND axes are worth
        acquiring (feeds go_forth — the acquisition backlog IS the ranked next-experiment queue);
      - competitor_crossref: competition density + modality validated/contrarian (feeds
        therapeutic_hypothesis differentiation);
      - cross_gate_shared_evidence: which gate verdicts share an input card = CORRELATED, not
        independent corroboration (the panel must not treat two gates resting on one card as two
        independent votes).
    All verdict-inert: they inform the narrative, never the deterministic ceiling. Compact; emitted only
    when present (byte-stable for older packages)."""
    frag = panel.get("fragility_facet") or {}
    comp = panel.get("competitor_crossref") or {}
    cgse = panel.get("cross_gate_shared_evidence") or {}
    mfc = panel.get("modality_fit_by_channel") or {}
    mbl = panel.get("magnitude_borderline") or []
    lines = []
    if frag:
        contested = frag.get("contested")
        backlog = [b.get("axis") for b in (frag.get("acquisition_backlog") or []) if isinstance(b, dict)]
        # M4 factored-record split: BLIND axes → ACQUIRE (never-looked); measured-thin → STRENGTHEN
        # (add power). Distinct next-actions the scalar 'insufficient' conflated.
        strengthen = [u.get("axis") for u in (frag.get("underpowered_axes") or []) if isinstance(u, dict)]
        lines.append(
            f"  fragility: contested={contested}"
            + (f"; acquisition_backlog (BLIND axes to ACQUIRE, feed go_forth): {backlog}" if backlog else "")
            + (
                f"; underpowered_axes (measured-thin → STRENGTHEN, add cohort/power): {strengthen}"
                if strengthen
                else ""
            )
        )
    if mfc:
        # per-MODALITY favorability (worst-case conjunction across axes): a target can be nominable via
        # one modality and held via another. Reason per channel, not on a flattened scalar.
        calls = {ch: v.get("fit") for ch, v in mfc.items() if isinstance(v, dict) and v.get("fit") != "na"}
        if calls:
            lines.append(f"  modality_fit_by_channel (per-modality call; NOT a single verdict): {calls}")
    if mbl:
        # knife-edge calls: a categorical verdict that hard-cut a near-threshold continuous value —
        # treat these verdicts as magnitude-FRAGILE, not crisp.
        bl = [
            {"axis": b.get("axis"), "scale": b.get("scale"), "distance_to_cut": b.get("distance_to_cut")}
            for b in mbl
            if isinstance(b, dict)
        ]
        lines.append(f"  magnitude_borderline (knife-edge on the cutpoint → treat as fragile): {bl}")
    if comp:
        lines.append(f"  competitor: {json.dumps(comp, default=str)}")
    if cgse.get("correlated_gate_pairs"):
        lines.append(
            "  cross-gate shared evidence (these gate PAIRS share an input card → correlated, "
            f"NOT independent corroboration): {cgse['correlated_gate_pairs']}"
        )
    if not lines:
        return ""
    return (
        "PANEL — decision facets (verdict-INERT context; reason over these but they do NOT change "
        "any deterministic verdict):\n" + "\n".join(lines) + "\n\n"
    )


# --- UNIFIED_OUTPUT_CONTRACT skill_report ---------------------------------------------------------
# The integrator's four OWN measured signals. These are not biology cards — they are the deterministic
# spine's readings of the hypothesis itself (is it clamped, is every clause traceable, is it internally
# coherent, is its corroboration independent), which is exactly what a reviewer needs as chips.
_SR_AXIS_LABELS = {
    "gate_agreement": "hypothesis vs deterministic gate ceiling",
    "clause_traceability": "every clause resolves to the package",
    "intra_package_coherence": "no positive clause on a contradicted signal",
    "evidence_independence": "corroboration is not one measurement re-displayed",
}


def _build_skill_report(
    *,
    computed,
    gate,
    cert,
    cert_dist,
    traceability,
    n_clauses,
    n_clean,
    coherence_v,
    substrate,
    gate_ind,
    promotable,
    promotion_blockers,
    tensions,
    gaps,
    not_scored,
    limiting,
    modality_resolved,
    gate_clamped,
    promotion_capped,
    verdict_after_gate,
    proposed,
) -> dict:
    """The integrator's UNIFIED_OUTPUT_CONTRACT `skill_report`, emitted TOP-LEVEL.

    WHY it exists: without it the integrator's output is unreadable by the shared report/rollup layer —
    `_skill_reports_by_short` / `build_skill_report_rollup` / the dashboard convergence reader all key off
    `skill_report`, so the framework's terminal synthesis was the one artifact that could not be consumed
    the way every sub-skill is. Emitting it makes the integrator a first-class citizen of the same
    contract it reads off the spine.

    WHY `role = descriptive`, given the verdict is a real call: `gating` means the verdict CAN MOVE THE
    NOMINATION RECOMMENDATION (the short is in the composer's gate map). This integrator sits ABOVE the
    nomination — it is downstream of the gate, and feeding it back would violate the load-bearing
    invariant that it ENRICHES and never OVERRIDES the spine. `descriptive` is the contract's word for a
    REAL read that is deliberately excluded from gate math, so `polarity` correctly resolves to
    `not_scored` while `call` still carries the clamped verdict for rendering.

    WHY it is TOP-LEVEL, not under `headline`: `data_product_contract.is_full_decision` keys off
    `headline.skill_report`, and this skill is BESPOKE (a single `hypothesis.json`, no `write_package`
    tree, no `run_health`). Putting the report at the top level gives the unified reader its object
    without silently reclassifying the artifact as a full fan-out decision."""
    tension_stmts = [t.get("statement") for t in (tensions or []) if isinstance(t, dict) and t.get("statement")]
    n_coh = sum(len(v) for v in (coherence_v or {}).values())
    eff_units = cert["effective_independent_units"]

    def _atom(signal, corrob, evidence, informs):
        return {"signal": signal, "corroboration": corrob, "evidence": evidence, "informs": informs}

    claim_vector = {
        # keyed off the GATE clamp alone. This atom answers one question — did the model's proposal
        # exceed what the spine permits — so a promotion cap (the hypothesis's own citation hygiene)
        # must not move it: that defect is already the `clause_traceability` atom's to report, and
        # letting it fire here too double-counted it in a four-atom vector.
        "gate_agreement": _atom(
            "opposing" if gate_clamped else "supportive",
            "high" if gate["hard_gates_present"] else "low",
            (
                (
                    f"proposed '{proposed}' → gate-clamped to '{verdict_after_gate}' "
                    f"(ceiling '{gate['ceiling']}': {gate['reason']})"
                    if gate_clamped
                    else f"proposed '{proposed}' sits at or below the gate ceiling '{gate['ceiling']}'"
                )
                + (f"; then promotion-capped to '{computed}' (not the gate)" if promotion_capped else "")
            ),
            _SR_AXIS_LABELS["gate_agreement"],
        ),
        "clause_traceability": _atom(
            "supportive" if traceability == 1.0 else ("insufficient" if traceability is None else "opposing"),
            "high" if n_clauses else "low",
            f"{n_clean}/{n_clauses} clauses fully traceable to the package",
            _SR_AXIS_LABELS["clause_traceability"],
        ),
        "intra_package_coherence": _atom(
            "supportive" if not n_coh else "opposing",
            "moderate",
            f"{n_coh} intra-package coherence violation(s)",
            _SR_AXIS_LABELS["intra_package_coherence"],
        ),
        "evidence_independence": _atom(
            # `insufficient` — not `supportive` — when no unit view was authoritative: an unmeasured
            # independence read must not read as a passing one.
            (
                "insufficient"
                if not cert["independence_view_authoritative"]
                else ("supportive" if eff_units >= 3 else ("neutral" if eff_units == 2 else "opposing"))
            ),
            "low" if substrate.get("tagging_sparse") else "moderate",
            (
                f"{eff_units} independent {cert['independence_unit_kind']}(s)"
                + (
                    f"; evidence_substrate tagging covers {substrate.get('substrate_tagged_fraction')} of cards"
                    if substrate.get("tagging_sparse")
                    else ""
                )
            ),
            _SR_AXIS_LABELS["evidence_independence"],
        ),
        # NON-atom scalars — carried losslessly for a rollup that reads a coordinate off the report.
        "certainty": cert["final"],
        "n_axes_by_level": cert_dist["n_axes_by_level"],
        "n_gating_axes_by_level": cert_dist["n_gating_axes_by_level"],
        "n_data_gaps": len(gaps),
        "n_not_scored_axes": len(not_scored),
        "limiting_gating_axis": limiting,
        "promotable": promotable,
        "modality": modality_resolved,
        "_disclaimer": (
            "these are the INTEGRATOR's readings of its own hypothesis (gate agreement, traceability, "
            "coherence, independence) — not biology-card signals; role=descriptive, excluded from gate math"
        ),
    }
    headline_block = {
        "verdict": {"phrase": f"{computed} (gate ceiling {gate['ceiling']})", "polarity": None},
        "confidence": cert["final"],
        "top_tension": tension_stmts[0] if tension_stmts else None,
    }
    return build_skill_report(
        role=ROLE_DESCRIPTIVE,
        verdict=computed,
        driving_rule_id=None,  # composes no cards, fires no rules (data_mode: catalog_read)
        headline_block=headline_block,
        claim_vector=claim_vector,
        axis_labels=_SR_AXIS_LABELS,
        question_table=[
            {"question": "Does the hypothesis exceed what the spine permits?", "answer": gate["reason"]},
            {
                "question": "Is it promotable?",
                "answer": ("yes" if promotable else f"no — {', '.join(promotion_blockers)}"),
            },
            {
                "question": "What limits certainty?",
                "answer": "; ".join(cert["cap_reasons"]) or "nothing beyond the weakest in-scope axis",
            },
        ],
        fired_rule_ids=[],
        cards_used=[],
        cards_missing=[],
    )


def run(
    pkg_path: str,
    risk_path=None,
    objective: str = "small-molecule drug target",
    modality=None,
    dossier_path=None,
    synthesize_fn=None,
    llm_mode=None,
    substrate=None,
    adversarial=False,
    n_skeptics=None,
) -> dict:
    """Assemble the panel, run the two-call pipeline, clamp, and enforce the defensibility contract.
    `synthesize_fn(system, user, name, schema, max_tokens=...)` is injectable for offline testing.
    `llm_mode` labels provenance: 'bedrock' (default live), 'offline_replay', or 'injected' (a test
    stub); it never changes the deterministic spine, only what model_id is pinned.
    `substrate` is the per-subskill GROUNDED SUBSTRATE (dict axis→ground_axis block): the design-correct
    literature path — its findings enrich the panel + its PMIDs become citable, and any axis that
    contradicts its deterministic verdict is surfaced as a tension. Escalate-only: it never lowers the
    deterministic ceiling.
    `adversarial` (opt-in): after assembly, run the SKEPTIC refutation post-check and populate
    quality.adversarial_survival + quality.adversarial_gate. Off by default — it costs N_SKEPTICS extra
    Bedrock calls and is INTRINSIC-quality only (never changes the deterministic spine/ceiling; not in
    the drift-golden subset). Reuses this run's injected synth, so it stays offline-testable."""
    if llm_mode is None:
        llm_mode = "bedrock" if synthesize_fn is None else "injected"
    modality_resolved, modality_inferred = hc.resolve_modality(modality, objective)
    panel = hc.assemble(pkg_path, risk_path, dossier_path, modality_resolved, substrate=substrate)
    synth = synthesize_fn or _default_synthesize()
    panel_block, tgt, ind, scoped_subtype = _panel_block(panel, objective)

    # CALL 1 — typed cited edges + tensions + evidence paths
    edge_out = synth(
        EDGE_SYSTEM,
        panel_block + "Emit typed cross-line edges, principal tensions, "
        "and evidence_paths. Cite only card_ids / sub-verdict names / rule_ids / panel "
        "PMIDs / dossier fields / stratum names.",
        "cross_edges",
        EDGE_SCHEMA,
        max_tokens=8000,
    )
    edges = _objs(edge_out.get("edges"))
    tensions = _objs(edge_out.get("principal_tensions"))
    paths = _objs(edge_out.get("evidence_paths"))
    edge_endpoint_warnings = _edge_endpoint_warnings(edges, panel)

    # CALL 2 — assemble the six-part hypothesis ON the edges/paths/tensions
    hyp_user = (
        panel_block + f"CROSS-LINE EDGES (build on these):\n{json.dumps(edges, indent=1, default=str)}\n\n"
        f"EVIDENCE PATHS (signal chains to a claim):\n{json.dumps(paths, indent=1, default=str)}\n\n"
        f"PRINCIPAL TENSIONS:\n{json.dumps(tensions, indent=1, default=str)}\n\n"
        "Assemble the drug-target hypothesis. Cite on EVERY clause. Reflect tensions honestly. Fill "
        "go_forth with the single most decision-changing next experiment. Propose a verdict; a gate "
        "will clamp it."
    )
    hyp_out = synth(HYP_SYSTEM, hyp_user, "hypothesis", HYPOTHESIS_SCHEMA, max_tokens=6000)
    out = {**hyp_out, "edges": edges, "tensions": tensions, "evidence_paths": paths}

    # --- composed-modality seam: the package's hard_gates (esp. the exists_safe_modality safety
    # suppression) were FROZEN under the modality the target-profile run was composed with. If the
    # integrator resolves a DIFFERENT modality, the ceiling it clamps against reflects the wrong channel.
    # Detect + surface the mismatch (never silently trusts a cross-channel ceiling). None on either side
    # (a modality-agnostic compose or run) is NOT a mismatch. ---
    composed_modality = ((panel["pkg"].get("synthesis") or {}).get("decision_facets") or {}).get("composed_modality")
    modality_mismatch = bool(composed_modality and modality_resolved and composed_modality != modality_resolved)

    # --- deterministic FAIL-CLOSED GATE-COMPLETE clamp (the ceiling; the model never overrides) ---
    gate = hc.gate_ceiling(panel["pkg"], modality=modality_resolved)
    proposed = hc._scalar(out.get("proposed_verdict"))
    computed, gate_clamped = hc.clamp(proposed, gate["ceiling"])
    verdict_after_gate = computed
    gate_tension = None
    if gate_clamped:
        gate_tension = (
            f"HYPOTHESIS proposed '{proposed}' but the deterministic gate caps at "
            f"'{gate['ceiling']}' ({gate['reason']}). The evidence read is not permitted "
            f"to override the gate — surfaced, not resolved in the hypothesis's favour."
        )

    # --- clause traceability WITH TEETH ---
    surface = panel["citation_surface"]
    clause_cites = _all_clause_citations(out)
    # ONE check_traceability pass per clause — the previous form called it twice for every clause (once
    # for the untraceable map, once for the clean count) on a check that walks the whole citation surface.
    trace_by_clause = {k: hc.check_traceability(v, surface) for k, v in clause_cites.items()}
    untraceable = {k: bad for k, bad in trace_by_clause.items() if bad}
    n_clauses = len(clause_cites)
    n_clean = sum(1 for bad in trace_by_clause.values() if not bad)
    traceability = round(n_clean / n_clauses, 3) if n_clauses else None

    # --- AXIS ROLES (UNIFIED_OUTPUT_CONTRACT skill_report): which in-scope axes actually GATE the
    # decision, and which are GATELESS BY DESIGN (role ∈ {descriptive, inert}, `polarity: not_scored`).
    # A gateless lens has verdict None, so without this it lands in data_gaps and can be named the
    # limiting axis — the gateless-tier conflation. `present=False` for a pre-#1310 package → every
    # consumer below falls back to its previous behaviour. ---
    reports = hc.parse_skill_reports(panel["pkg"])

    # --- uncertainty / gaps (orthogonal clamp: bounds CONFIDENCE) + substrate + degradation discount
    conviction = panel["conviction"]
    oos = hc.out_of_scope_dims(modality_resolved)
    in_scope = [d for d in conviction if d not in oos]
    not_scored = [d for d in reports["not_scored_axes"] if d in set(in_scope)]
    # SCORED in-scope axes = the axes that can carry a verdict at all. Gaps, the weakest-link certainty
    # base and the minimum-inputs count are all computed over THESE, not over every in-scope lens.
    scored_in_scope = [d for d in in_scope if d not in set(not_scored)]
    gaps = hc.data_gaps({d: conviction[d] for d in in_scope}, not_scored=not_scored)
    # Per-axis certainty: consume the spine's CERTAINTY_MODEL sidecar (synthesis.decision_facets.
    # certainty_by_axis) as the weakest-link base for axes that opted in, so the integrator AGREES with
    # the spine rather than re-deriving; axes without a sidecar fall back to the binary proxy.
    certainty_by_axis = hc.parse_certainty_by_axis(panel["pkg"])
    # None (not []) when the package carries no roles: "roles unknown" must not be reported as "nothing
    # gates". Downstream, None selects the fallback pool (every scored in-scope axis) for the limiting-axis
    # attribution and suppresses the gating histogram entirely.
    gating_axes = [d for d in reports["gating_axes"] if d in set(scored_in_scope)] if reports["present"] else None
    base_certainty, limiting = hc.weakest_link_certainty(
        conviction, scored_in_scope, certainty_by_axis, gating_axes=gating_axes
    )
    # the DISTRIBUTION behind the weakest-link scalar. The scalar is a conjunctive minimum and reads
    # `low` on essentially every real package, so it cannot separate targets; the histogram (and its
    # gating-only slice) is what a portfolio reviewer can actually rank on.
    cert_dist = hc.certainty_distribution(conviction, scored_in_scope, certainty_by_axis, gating_axes=gating_axes)
    # F18: `base_certainty` minimises over EVERY scored in-scope axis while `limiting` is restricted to
    # gating axes, so the two can name different levels — ERBB2/BRCA shipped `low` beside
    # `limiting_dimension: mechanism` when mechanism was moderate and the binding axis was the non-gating
    # `subtype_fit`. Both halves are deliberate; the disagreement was just undisclosed. Attribution only.
    binding = hc.binding_axis_attribution(
        conviction, scored_in_scope, certainty_by_axis, gating_axes=gating_axes, roles=reports.get("roles")
    )

    degraded_inputs = []
    if not panel["dossier_present"]:
        degraded_inputs.append("dossier")
    if not panel["risk_present"]:
        degraded_inputs.append("risk")
    substrate = panel["substrate"]
    # P4 gate-independence: the spine's AUTHORITATIVE cross-gate correlation collapsed over the SUPPORTING
    # (non-gap) in-scope decision gates → independent-gate-group count. Feeds the discount as the MORE
    # CONSERVATIVE unit count (min with the card-substrate view); None when the facet is absent → the
    # substrate discount stands alone (byte-stable for older packages).
    supporting_gates = [d for d in scored_in_scope if conviction.get(d) not in hc.GAP_VERDICTS]
    gate_ind = hc.gate_independence(panel.get("cross_gate_shared_evidence"), supporting_gates)
    cert = hc.discounted_certainty(
        base_certainty,
        substrate["n_independent_units"],
        degraded_inputs,
        n_independent_gate_groups=gate_ind["n_independent_gate_groups"],
        tagging_sparse=substrate.get("tagging_sparse", False),
    )
    # confidence_tier CROSS-CHECK (quick win; no emit-side dependency): the spine emits its OWN
    # composed confidence tier. When the integrator's discounted certainty DIVERGES from it, record the
    # divergence (informational — the integrator's certainty is weakest-link + independence-discounted, a
    # deliberately more conservative read; never silently overrides the spine's tier).
    #
    # It gets its OWN field, not a `cap_reasons` entry. The divergence lowers nothing — it is an
    # observation about two reads disagreeing — so listing it among the caps asserted a causal role it
    # does not have, and (now that `cap_ceiling` is emitted) would leave a reason list of three beside a
    # ceiling explained by two of them.
    spine_tier = ((panel["pkg"].get("synthesis") or {}).get("confidence_tier") or {}).get("tier")
    tier_divergence = None
    if spine_tier and str(spine_tier).lower() != cert["final"]:
        tier_divergence = (
            f"diverges from spine confidence_tier '{spine_tier}' (integrator certainty is weakest-link + "
            "independence-discounted)"
        )

    # absence-discipline WITH TEETH: a SUPPORTING clause may not cite a gap-line sub-verdict.
    #
    # Matching is NORMALIZED + phrase-aware, mirroring how check_traceability resolves a non-PMID token.
    # The exact `tok in gapset` this replaces was asymmetric teeth: traceability CREDITED
    # "expression sub-verdict (expression)" for embedding a known token, while absence-discipline only
    # caught a citation that was the bare string "expression" — so the same phrasing that made a citation
    # traceable let it cite a GAP line for free. A gap axis named inside the citation phrase is a
    # violation regardless of the surrounding prose.
    # Boundary chars EXCLUDE `_` so the axis name must stand as its own token in the normalized citation:
    # "expression sub-verdict (expression)" is a violation, while the CARD "expression-and-specificity"
    # (normalized `expression_and_specificity`) is not the AXIS `expression` and does not match.
    gap_res = {g: re.compile(rf"(?<![a-z0-9_]){re.escape(hc._norm(g))}(?![a-z0-9_])") for g in gaps}
    support_clauses = ("causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window")

    def _cited_gap_axes(tok) -> list:
        tn = hc._norm(tok)
        return sorted(g for g, rx in gap_res.items() if rx.search(tn))

    absence_violations = {}
    for key in support_clauses:
        c = hc._uv(out.get(key)) or {}
        c = c if isinstance(c, dict) else {}
        cited_gaps = sorted({f"{tok}→{g}" for tok in (c.get("citations") or []) for g in _cited_gap_axes(tok)})
        if cited_gaps:
            absence_violations[key] = cited_gaps

    # --- INTRA-PACKAGE COHERENCE WITH TEETH: a positive-thesis clause may not assert on
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
    present_norm = {hc._norm(t) for t in (surface["card_ids"] | surface["sub_verdicts"] | surface["rule_ids"])}
    card_calls = {cid: call for cid, call in (panel.get("cards_brief") or {}).items() if isinstance(call, str)}
    coherence_v = hc.coherence_violations(
        coherence_clauses,
        conviction,
        edges,
        tensions,
        present_norm,
        out_of_scope=oos,
        card_calls=card_calls,
        sv=(panel["pkg"].get("synthesis") or {}).get("sub_verdicts"),
        modality=modality_resolved,
    )
    # SURFACE each detected tension into the structured `tensions` slot (fold-into-tensions), so the
    # contradiction is carried explicitly, never buried — without mutating any LLM clause prose.
    # coherence_v (as DETECTED) still blocks promotion below (the teeth).
    coherence_surfaced_tensions = hc.surface_coherence_tensions(coherence_v)
    if coherence_surfaced_tensions:
        tensions = tensions + coherence_surfaced_tensions
        out["tensions"] = tensions

    # --- GROUNDED-SUBSTRATE discordance surfacing (escalate-only): for each axis whose grounded
    # literature CONTRADICTS its deterministic verdict, surface a DETERMINISTIC tension (tagged
    # grounded_substrate_discordance) citing the axis + its grounded PMIDs — so the engine↔literature
    # disagreement is carried explicitly for a reviewer/skeptic. This RAISES a concern; it never lowers
    # the ceiling (the clamp above already ran off the package hard_gates alone). ---
    grounded = panel.get("grounded_substrate") or {}
    grounded_discordance_tensions = []
    for ax in grounded.get("discordant_axes", []):
        rec = next((r for r in grounded.get("per_axis", []) if r.get("axis") == ax), {})
        pmids = sorted({p for f in rec.get("findings", []) for p in (f.get("cited_pmids") or [])})
        grounded_discordance_tensions.append(
            {
                "statement": (
                    f"grounded literature on the '{ax}' axis contradicts its deterministic "
                    f"verdict '{rec.get('anchor_verdict')}' — an escalate-only concern the "
                    "engine's narrow verdict may have missed"
                ),
                "citations": [ax] + pmids,
                "axis": ax,
                "source": "grounded_substrate_discordance",
            }
        )
    if grounded_discordance_tensions:
        tensions = tensions + grounded_discordance_tensions
        out["tensions"] = tensions

    # --- COMPOSED-MODALITY MISMATCH surfacing: the package's ceiling was frozen under a DIFFERENT
    # modality than this run resolved, so hard_gates (esp. the exists_safe_modality safety suppression)
    # may not apply to this channel. Surface a deterministic tension so the mismatch is explicit for a
    # reviewer; the safe move is to recompose the package under this modality. ---
    if modality_mismatch:
        tensions = tensions + [
            {
                "statement": (
                    f"the evidence package was COMPOSED under modality "
                    f"'{composed_modality}' but this hypothesis resolves modality "
                    f"'{modality_resolved}'. The deterministic ceiling (hard_gates, incl. the "
                    "per-modality safety suppression) was frozen for the composed modality and "
                    "may not hold for this channel — recompose the target-profile package under "
                    f"'{modality_resolved}' to trust the ceiling."
                ),
                "citations": [
                    "synthesis.recommendation_gate.hard_gates",
                    "synthesis.decision_facets.composed_modality",
                ],
                "source": "integrator_modality_mismatch",
            }
        ]
        out["tensions"] = tensions

    # --- minimum-inputs gate: enough non-gap, SCORED, in-scope decision lines to reason over? A gateless
    # descriptive lens is real context but it is not a decision line, so it neither counts toward the
    # minimum nor (via data_gaps above) against it. Counted over scored_in_scope. ---
    n_supporting = sum(1 for d in scored_in_scope if conviction.get(d) not in hc.GAP_VERDICTS)
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
    # a non-promotable hypothesis can never present a permissive verdict — cap at advanceable_flagged.
    #
    # This is a DIFFERENT mechanism from the gate clamp and must be reported as one. It fires on the
    # hypothesis's OWN hygiene (untraceable citations, absence-discipline, coherence, too few supporting
    # axes), not on disagreement with the spine. Folding it into `was_clamped` — as this did — made the
    # live KRAS-COADREAD run emit `was_clamped: true` beside `gate_ceiling == proposed_by_agent` and
    # `gate_clamp_tension: null`: three fields in one object contradicting each other, reading as "the
    # deterministic gate overruled the model" when the model had agreed with the gate exactly and was
    # demoted for citation hygiene. It also made ONE defect (22/25 traceable clauses) fire TWO of the
    # four skill_report claim atoms, double-counting it for any rollup that averages the vector.
    promotion_capped = False
    if not promotable and hc.VERDICT_RANK[computed] > hc.VERDICT_RANK["advanceable_flagged"]:
        computed = "advanceable_flagged"
        promotion_capped = True

    # --- UNIFIED_OUTPUT_CONTRACT skill_report (top-level). Built AFTER the promotion cap so `call` is
    # the FINAL computed verdict. See _build_skill_report for why role == descriptive. ---
    skill_report = _build_skill_report(
        computed=computed,
        gate=gate,
        cert=cert,
        cert_dist=cert_dist,
        traceability=traceability,
        n_clauses=n_clauses,
        n_clean=n_clean,
        coherence_v=coherence_v,
        substrate=substrate,
        gate_ind=gate_ind,
        promotable=promotable,
        promotion_blockers=promotion_blockers,
        tensions=tensions,
        gaps=gaps,
        not_scored=not_scored,
        limiting=limiting,
        modality_resolved=modality_resolved,
        gate_clamped=gate_clamped,
        promotion_capped=promotion_capped,
        verdict_after_gate=verdict_after_gate,
        proposed=proposed,
    )

    result = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": tgt,
        "indication": ind,
        "objective": objective,
        "modality": {
            "resolved": modality_resolved,
            "inferred_from_objective": modality_inferred,
            "out_of_scope_dimensions": sorted(oos),
        },
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
            "proposed_by_agent": proposed,
            "computed": computed,
            # TWO independent demotion mechanisms, reported apart (see the promotion cap above).
            # `was_clamped` is the GATE clamp only — did the spine's ceiling lower the model's proposal.
            # `promotion_capped` is the hypothesis's own hygiene cap. `verdict_after_gate` is the value
            # between them, so a reader can attribute the drop from `proposed_by_agent` to `computed`.
            "was_clamped": gate_clamped,
            "promotion_capped": promotion_capped,
            "verdict_after_gate": verdict_after_gate,
            "gate_ceiling": gate["ceiling"],
            "gate_reason": gate["reason"],
            "gate_fail_closed": gate["fail_closed"],
            "hard_gates_present": gate["hard_gates_present"],
            "active_vetoes": gate["active_vetoes"],
            "blind_gates": gate["blind_gates"],
            "opposing_gates": gate["opposing"],
            "modality_excluded_gates": gate["excluded"],
            "gate_clamp_tension": gate_tension,
            "reason": hc._uv(out.get("proposed_verdict_reason")),
            # MODALITY×SAFETY: the per-modality safety action for this channel + whether it cleared the
            # blanket hold-grade cap (== the spine's exists_safe_modality suppression, mirrored).
            "safety_modality_action": gate.get("safety_modality_action"),
            "safety_modality_cleared": gate.get("safety_modality_cleared", False),
            # the spine's OWN per-run disposition of its safety hard-gate row(s). When it reads
            # `suppressed`/`excluded` the integrator does NOT re-derive a hold from the scalar safety
            # token — re-imposing an adjudicated gate would OVERRIDE the spine.
            "safety_gate_status": gate.get("safety_gate_status"),
            "safety_gate_disposed_by_spine": gate.get("safety_gate_disposed_by_spine", False),
        },
        "defensibility": {
            "clause_traceability": traceability,
            "untraceable_citations": untraceable,
            "n_clauses": n_clauses,
            "n_fully_traceable": n_clean,
            "coherence_violations": coherence_v,
            "n_coherence_violations": sum(len(v) for v in coherence_v.values()),
            "n_coherence_tensions_surfaced": len(coherence_surfaced_tensions),
            "promotable": promotable,
            "promotion_blockers": promotion_blockers,
            # verdict-INERT audit: edges whose from/to_dimension isn't a recognized dimension/card
            # token, so the coherence teeth couldn't match them (a hallucinated/misspelled endpoint
            # could hide a real contradiction). Flagged for a reviewer; never blocks promotion.
            "edge_endpoint_warnings": edge_endpoint_warnings,
        },
        "uncertainty": {
            "overall_certainty": cert["final"],
            "base_certainty": cert["base"],
            "certainty_capped": cert["capped"],
            # every cap CONSIDERED, plus the level they jointly permit. Read as one statement:
            # base / cap_ceiling / overall_certainty / certainty_capped. When the base is already the
            # weakest rung the listed caps bind nothing, and `cap_ceiling` makes that legible instead of
            # leaving a reader to suspect a listed cap silently lowered the answer.
            "cap_reasons": cert["cap_reasons"],
            "cap_ceiling": cert["cap_ceiling"],
            # NOT a cap — the spine's own composed tier disagreeing with this integrator's read.
            "spine_tier_divergence": tier_divergence,
            # the LIMITING axis is restricted to role=gating axes when the spine carries roles, so the
            # decision is never reported as limited by a lens that gates nothing.
            "limiting_dimension": limiting,
            "limiting_dimension_scope": "gating_axes" if gating_axes else "all_scored_in_scope_axes",
            # F18 attribution: `limiting_dimension` is the gating-restricted NAME, `binding_axis` is what
            # actually set the level. `limiting_dimension_is_binding: false` means read `binding_axis`
            # instead — the named axis sits ABOVE the reported certainty and acting on it will not move it.
            # `binding_axis_role: null` means that axis is absent from synthesis.skill_reports entirely
            # (a #1310 producer gap, distinct from a declared descriptive/inert role). Disclosure only.
            **binding,
            # the DISTRIBUTION the weakest-link scalar hides — this is the discriminating read.
            "certainty_by_axis": cert_dist["by_axis"],
            "n_axes_by_level": cert_dist["n_axes_by_level"],
            "gating_certainty_by_axis": cert_dist["gating_by_axis"],
            "n_gating_axes_by_level": cert_dist["n_gating_axes_by_level"],
            "certainty_axes_from_spine_sidecar": cert_dist["axes_from_spine_sidecar"],
            "certainty_axes_from_proxy": cert_dist["axes_from_proxy"],
            "data_gaps": gaps,
            # GATELESS BY DESIGN (skill_report role ∈ {descriptive, inert}) — declared absence of
            # scoring, NOT missing data. Excluded from data_gaps / the certainty base / the minimum-input
            # count, and reported here so the exclusion is auditable rather than invisible.
            "not_scored_axes": sorted(not_scored),
            "axis_roles": reports["roles"],
            "axis_roles_present": reports["present"],
            "absence_discipline_violations": absence_violations,
        },
        "evidence_independence": {
            "correlated_evidence_discounted": substrate["correlated_evidence_discounted"],
            "correlated_groups": substrate["correlated_groups"],
            # NAMED BY VIEW. The old `n_independent_units` was the CARD-SUBSTRATE count sitting beside
            # `effective_independent_units` (the binding view) under a name that claimed to be the
            # authoritative one; on live KRAS-COADREAD they read 2 and 3 and a reader had no way to tell
            # they measure different things. Every unit count below now says which view it is.
            "n_independent_substrate_units": substrate["n_independent_units"],
            "n_distinct_substrates": substrate["n_distinct_substrates"],
            "n_untagged_cards": substrate["n_untagged_cards"],
            # TAGGING COVERAGE the independence read rests on. Independent units are the DISTINCT TAGGED
            # substrates only (an untagged card is missing provenance, not proven independence); when
            # tagging covers a minority of the package the discount says so (`tagging_sparse`) and caps
            # certainty at `moderate` rather than passing silently.
            "n_tagged_cards": substrate["n_tagged_cards"],
            "substrate_tagged_fraction": substrate["substrate_tagged_fraction"],
            "tagging_sparse": substrate["tagging_sparse"],
            # F17 — WHY tagging is sparse, because on the 2026-09-12 panel it was sparse on 15/15 targets
            # and a flag that cannot be False cannot inform anyone. `substrate_vocabulary_limited: true`
            # means the emitter stamped every card it could and the `evidence_substrates` vocab simply
            # names no substrate for this evidence (a target-contracts measurement_types.yaml gap) — NOT
            # that this run lost provenance. `n_untagged_no_measurement_type` is the separate, per-card
            # registry back-ref debt. Disclosure only: no cap or unit count reads these.
            "n_untagged_vocabulary_gap": substrate["n_untagged_vocabulary_gap"],
            "n_untagged_no_measurement_type": substrate["n_untagged_no_measurement_type"],
            "substrate_vocabulary_limited": substrate["substrate_vocabulary_limited"],
            # P4 — the spine's AUTHORITATIVE cross-gate correlation, now RECONCILED into the certainty
            # discount: independent decision-gate groups over the supporting gates (spine
            # cross_gate_shared_evidence) + the effective unit count actually used (the more conservative
            # of the substrate and gate-group views). cross_gate_shared_evidence is the raw spine view;
            # n_independent_gate_groups is None for an older package (facet absent) → discount unchanged.
            "cross_gate_shared_evidence": panel.get("cross_gate_shared_evidence") or {},
            "n_independent_gate_groups": gate_ind["n_independent_gate_groups"],
            "gate_independence_present": gate_ind["present"],
            "effective_independent_units": cert["effective_independent_units"],
            "independence_unit_kind": cert["independence_unit_kind"],
            # TWO questions, two flags. `_view_authoritative` is False when NO unit view could speak
            # (substrate tagging sparse AND no spine gate facet) — the check ABSTAINED rather than
            # capping on a metadata gap. `_cap_binding` is whether the unit count actually lowered the
            # certainty ceiling; an authoritative view finding >= 3 units caps nothing, which the single
            # old `independence_cap_applied: true` misreported as a cap that had been applied.
            "independence_view_authoritative": cert["independence_view_authoritative"],
            "independence_cap_binding": cert["independence_cap_binding"],
        },
        "subtype_resolved": {
            "present": panel["subtype"]["present"],
            "scoped_subtype": scoped_subtype,
            "requested_strata": panel["subtype"]["requested_strata"],
            "available_strata": panel["subtype"]["available_strata"],
            "convergence_facet": panel["subtype"]["convergence_facet"],
            # per-stratum n-floor status — the auditable surface for the citable-token gate. Without it
            # a reviewer cannot reconstruct which stratum-axis citations were below-floor (hence not
            # credited by check_traceability). Each entry carries {stratum, n_floor_met_by_axis}; an
            # axis with n_floor_met_by_axis=false is UNDERPOWERED and is NOT in the citable set.
            "per_stratum_n_floor": [
                {"stratum": rec.get("stratum"), "n_floor_met_by_axis": rec.get("n_floor_met_by_axis", {})}
                for rec in panel["subtype"]["per_stratum"]
            ],
        },
        "degraded_mode": {
            "dossier_present": panel["dossier_present"],
            "risk_present": panel["risk_present"],
            "grounded_substrate_present": panel.get("grounded_substrate_present", False),
            "degraded_inputs": degraded_inputs,
            "minimum_inputs_met": minimum_inputs_met,
            # counted over the SCORED in-scope axes only — a gateless descriptive lens is context, not a
            # decision line, so it neither supports nor blocks the minimum.
            "n_supporting_in_scope_lines": n_supporting,
            "n_scored_in_scope_lines": len(scored_in_scope),
            "n_in_scope_lines": len(in_scope),
            "n_not_scored_in_scope_lines": len(not_scored),
            # composed-modality seam: the modality the package was composed under + whether it mismatches
            # this run's resolved modality (the ceiling was frozen for the composed channel).
            "composed_modality": composed_modality,
            "modality_mismatch": modality_mismatch,
        },
        # --- GROUNDED SUBSTRATE: the per-axis literature findings the hypothesis reasoned over,
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
        # --- optional intrinsic-quality slot. adversarial_survival is null until the optional
        # post-check (scripts/adversarial_survival.py, needs Bedrock) is run; the deterministic
        # coherence guard above is the always-on, offline sibling of that skeptic pass. ---
        "quality": {"adversarial_survival": None},
        # --- UNIFIED_OUTPUT_CONTRACT: the ONE shape every skill shares, so the integrator's terminal
        # synthesis is readable by the shared report/rollup layer (`_skill_reports_by_short`,
        # `build_skill_report_rollup`, the dashboard convergence reader) exactly like a sub-skill's.
        # TOP-LEVEL (not under `headline`) — this skill's emit is bespoke; see _build_skill_report. ---
        "skill_report": skill_report,
        # --- drift-guard provenance: the two PINS the golden-set drift-CI freezes ---
        "provenance": {
            "skill": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "prompt_template_hash": prompt_template_hash(),
            "model_id": _resolve_model_id(llm_mode),
            "llm_mode": llm_mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            # Surface any malformed-tool-use SALVAGE / RECOVERY that synthesize_structured applied to
            # either LLM call (fields lost to the XML-<parameter> dialect leak, or recovered from it),
            # so a partially-lost response is AUDITABLE rather than proceeding silently.
            "llm_field_recovery": {
                "edges": {k: edge_out.get(k) for k in ("_malformed_fields", "_recovered_fields") if edge_out.get(k)},
                "hypothesis": {k: hyp_out.get(k) for k in ("_malformed_fields", "_recovered_fields") if hyp_out.get(k)},
            },
        },
        "panel_conviction": conviction,
    }

    # --- intrinsic-quality post-check (opt-in): the SKEPTIC refutation pass. Populates the quality
    # slot that is otherwise null. Never touches the spine/ceiling (INTRINSIC-quality) — a low survival
    # score is a defensibility SIGNAL for the human, not a gate. ---
    if adversarial:
        import adversarial_survival as AS  # local import: only loaded on the opt-in path

        surv = AS.adversarial_survival(
            result, pkg_path, risk_path, dossier_path, n_skeptics=(n_skeptics or AS.N_SKEPTICS), synthesize_fn=synth
        )
        result["quality"]["adversarial_survival"] = surv
        result["quality"]["adversarial_gate"] = AS.adversarial_survival_gate(surv)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="cross-evidence hypothesis integrator (WS4)")
    ap.add_argument(
        "--evidence-package",
        required=True,
        help="target-profile evidence_package.json (the indication-conditioned panel)",
    )
    ap.add_argument(
        "--target-dossier", default=None, help="target-intrinsic decision.json (indication-independent target biology)"
    )
    ap.add_argument("--risk", default=None, help="6-dim literature-risk decision.json (optional)")
    ap.add_argument(
        "--substrate",
        nargs="*",
        default=[],
        metavar="AXIS=PATH",
        help="per-subskill GROUNDED SUBSTRATE blocks (ground_axis output), as axis=path "
        "(e.g. safety=safety.json selectivity=sel.json). The DESIGN-CORRECT literature "
        "path (§13): findings enrich the panel + PMIDs become citable; discordant axes "
        "surface as tensions. Escalate-only — never lowers the deterministic ceiling.",
    )
    ap.add_argument("--objective", default="small-molecule drug target", help="free-text objective (narration only)")
    ap.add_argument(
        "--modality",
        default=None,
        choices=sorted(hc.MODALITY_SCOPE),
        help="controlled modality enum (overrides objective inference)",
    )
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help="OFFLINE deterministic run: use --llm-replay canned responses instead of "
        "Bedrock (powers the golden-set drift-CI; the deterministic spine is identical)",
    )
    ap.add_argument(
        "--llm-replay",
        default=None,
        help='canned two-call response JSON ({"cross_edges":{...},"hypothesis":{...}}) for --no-llm',
    )
    ap.add_argument(
        "--adversarial",
        action="store_true",
        help="OPT-IN (WS5): after assembling the hypothesis, run the SKEPTIC refutation "
        "post-check and populate quality.adversarial_survival + quality.adversarial_gate. "
        "Costs N extra Bedrock calls; INTRINSIC-quality only — never changes the "
        "verdict/ceiling. Incompatible with --no-llm (the skeptic pass has no replay).",
    )
    ap.add_argument(
        "--n-skeptics",
        type=int,
        default=None,
        help="number of skeptic refutation passes for --adversarial (default: 3)",
    )
    args = ap.parse_args(argv)

    synthesize_fn, llm_mode = None, None
    if args.no_llm:
        if not args.llm_replay:
            print("--no-llm requires --llm-replay <canned response json>", file=sys.stderr)
            return 2
        if args.adversarial:
            print(
                "--adversarial needs live Bedrock (the skeptic pass is not part of the two-call "
                "replay); drop --no-llm to run it",
                file=sys.stderr,
            )
            return 2
        synthesize_fn = replay_synthesize(json.loads(Path(args.llm_replay).read_text()))
        llm_mode = "offline_replay"

    # load the per-subskill grounded substrate blocks (axis=path), if any
    substrate = {}
    for spec in args.substrate or []:
        if "=" not in spec:
            print(f"--substrate expects axis=path, got {spec!r}", file=sys.stderr)
            return 2
        ax, p = spec.split("=", 1)
        substrate[ax] = json.loads(Path(p).read_text())

    outd = Path(args.out)
    outd.mkdir(parents=True, exist_ok=True)
    print("→ assembling cross-evidence hypothesis ...", file=sys.stderr)
    r = run(
        args.evidence_package,
        args.risk,
        args.objective,
        args.modality,
        args.target_dossier,
        synthesize_fn=synthesize_fn,
        llm_mode=llm_mode,
        substrate=substrate or None,
        adversarial=args.adversarial,
        n_skeptics=args.n_skeptics,
    )
    (outd / "hypothesis.json").write_text(json.dumps(r, indent=2, default=str))

    v = r["verdict"]
    print(f"\n=== {r['target']} / {r['indication']}  ({r['modality']['resolved']}) ===")
    print(
        f"VERDICT: {v['computed']}  (proposed {v['proposed_by_agent']}; ceiling {v['gate_ceiling']}"
        f" — {v['gate_reason']})"
    )
    if v["gate_clamp_tension"]:
        print(f"  CLAMPED: {v['gate_clamp_tension']}")
    u = r["uncertainty"]
    print(
        f"CERTAINTY: {u['overall_certainty']} (base {u['base_certainty']}; "
        f"limited by {u['limiting_dimension']}; caps {u['cap_reasons']})"
    )
    ei = r["evidence_independence"]
    if ei["correlated_evidence_discounted"]:
        print(f"  correlated evidence discounted: {ei['correlated_groups']}")
    d = r["defensibility"]
    print(
        f"DEFENSIBILITY: traceability={d['clause_traceability']} promotable={d['promotable']} "
        f"blockers={d['promotion_blockers']}"
    )
    if d["coherence_violations"]:
        print(
            f"  COHERENCE: {d['n_coherence_violations']} intra-package contradiction(s): "
            f"{ {k: [x['type'] for x in v] for k, v in d['coherence_violations'].items()} }"
        )
    gsub = r["grounded_substrate"]
    if gsub["present"]:
        print(
            f"GROUNDED SUBSTRATE: {gsub['n_findings']} finding(s) / {gsub['n_grounded_pmids']} "
            f"citable PMID(s) across {len(gsub['per_axis'])} axes"
            + (f"; discordant: {gsub['discordant_axes']}" if gsub["discordant_axes"] else "")
        )
    surv = (r.get("quality") or {}).get("adversarial_survival")
    if surv and surv.get("score") is not None:
        gate = (r.get("quality") or {}).get("adversarial_gate") or {}
        print(
            f"ADVERSARIAL SURVIVAL: {surv['n_surviving']}/{surv['n_clauses']} clauses survive "
            f"(score {surv['score']}; gate {'PASS' if gate.get('passed') else 'FLAG'})"
        )
    print(
        f"PROVENANCE: model={r['provenance']['model_id']} "
        f"prompt_template_hash={r['provenance']['prompt_template_hash'][:12]}… "
        f"mode={r['provenance']['llm_mode']}"
    )
    print(f"wrote {outd}/hypothesis.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
