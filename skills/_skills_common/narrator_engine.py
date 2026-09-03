"""narrator_engine — ONE generic, capsule-driven single-lens narrator for the whole fleet.

Replaces the per-skill bespoke synthesis_*.py builders with one engine parameterized by a LensConfig
(data, not code). A narrator no longer plucks skill-specific fields: it reads the SIGNAL layer (the
narrator-input contract — subgroup_signals / question_table / claim_vector off the headline) plus the
bounded DATA layer (evidence_capsule.emit_capsules — the complete-but-limited per-card package), and the
LensConfig supplies only what genuinely differs per lens: the thesis, axis labels, scope guardrails,
signal polarity, and the output tool (a relevance read, or a descriptive context read for gateless skills).

Two-slot / VERDICT-INERT: the result is attached as decision['llm_synthesis'] AFTER the deterministic
spine is composed; it never mints or moves a verdict. Every field is provenance-stamped by
synthesize_structured. Migrating the 6 bespoke narrators onto this engine is a follow-on; new lenses
adopt it directly.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE
from _skills_common.signals_first import render_narrator_signals
from _skills_common.evidence_capsule import emit_capsules


@dataclass
class LensConfig:
    name: str                                    # skill kebab id, e.g. "on-target-safety-liability"
    thesis: str                                  # what a strong signal MEANS for this lens
    relevance_prompt: str                        # 1-2 lines: what the headline judgment should assess
    axis_labels: dict = field(default_factory=dict)
    scope_exclusions: tuple = ()                 # guardrails each bespoke narrator hard-codes today
    polarity_note: str = ""                      # e.g. safety inversion: "signal = strength of the LIABILITY"
    mode: str = "verdict"                        # "verdict" | "descriptive" (gateless skills)
    relevance_enum: tuple = ("strongly_supports", "supports_with_caveats",
                             "neutral_uninformative", "argues_against")
    verdict_card_ids: Optional[set] = None       # full capsules for these; others thin (None = all full)
    capsule_config: dict = field(default_factory=dict)
    verdict_key: Optional[str] = None            # headline key holding the collapsed verdict token (e.g.
                                                 # "presence_verdict"); None → the legacy <name>_verdict guess


_CONF_ENUM = ("well_supported", "supported_with_caveats", "weakly_supported", "insufficient_evidence")


def _tool(lens: LensConfig) -> tuple:
    if lens.mode == "descriptive":
        name = f"emit_{lens.name.replace('-', '_')}_context"
        schema = {"type": "object", "additionalProperties": False,
                  "required": ["context_read", "key_signals_summary", "confidence_qualifier", "key_caveat"],
                  "description": f"Descriptive {lens.name} context read (this lens is gateless — no relevance verdict).",
                  "properties": {
                      "context_read": {"type": "string", "description": "2-4 sentences integrating the signals + capsule data into the lens's context contribution; no nomination call."},
                      "key_signals_summary": {"type": "string", "description": "the 1-2 strongest, best-corroborated signals, cited to card_id/field."},
                      "confidence_qualifier": {"type": "string", "enum": list(_CONF_ENUM)},
                      "key_caveat": {"type": "string"}}}
        return name, schema
    name = f"emit_{lens.name.replace('-', '_')}_synthesis"
    schema = {"type": "object", "additionalProperties": False,
              "required": ["relevance", "rationale", "confidence_qualifier", "key_caveat"],
              "description": f"Single-lens {lens.name} read. {lens.relevance_prompt} SINGLE-LENS — informs confidence, never mints/flips a nomination.",
              "properties": {
                  "relevance": {"type": "string", "enum": list(lens.relevance_enum),
                                "description": lens.relevance_prompt},
                  "rationale": {"type": "string", "description": "2-4 sentences reasoning ACROSS the signals + capsule data; cite card_id/field/value; state DATA_UNAVAILABLE gaps."},
                  "confidence_qualifier": {"type": "string", "enum": list(_CONF_ENUM)},
                  "key_caveat": {"type": "string", "description": "the single most important caveat, or 'none'."}}}
    return name, schema


def _system(lens: LensConfig) -> str:
    s = [f"You are a computational-oncology target-evaluation assistant. PURPOSE (single lens): reason "
         f"ACROSS the {lens.name} evidence for a (target, indication) and judge {lens.thesis}",
         "You NARRATE and INTEGRATE; you never invent facts and never change the deterministic, rule-computed "
         "verdict (FIXED upstream). Ground every claim in the provided fields/values.",
         "LEAD with the SIGNAL VECTOR; the collapsed verdict is a compressed label — state it last, never let it "
         "mask a disagreeing signal. Use the RAW CAPSULE DATA to sharpen the read (cite specific strata, "
         "magnitudes, conflicts) but the class labels remain authoritative; obey each capsule row's SCOPE note "
         "and treat data_quality_flags as bugs to flag, not facts to narrate."]
    if lens.polarity_note:
        s.append(f"POLARITY: {lens.polarity_note}")
    if lens.scope_exclusions:
        s.append("SCOPE — do NOT discuss: " + "; ".join(lens.scope_exclusions) + ".")
    s.append("REGISTER: scientific-publication voice; declarative, precise; report numbers with scale + direction; "
             "no promotional language.")
    s.append("If a LITERATURE LANE is provided below, use it to CORROBORATE or CHALLENGE the omics signals and "
             "to surface omics-blind signals; attribute literature-derived claims explicitly (they are external, "
             "not from this package), treat any [unverified] citation with caution, and NEVER let the literature "
             "move the fixed verdict.")
    return " ".join(s) + _EVIDENCE_ONLY_DIRECTIVE


def _render_capsules(pkg: dict) -> str:
    caps = pkg.get("capsules", {})
    manifest = pkg.get("manifest", [])
    lines = ["EVIDENCE CAPSULES (complete-but-limited per-card data — the bounded raw behind the classes; "
             "cite these to sharpen the read):"]
    n_full = sum(1 for m in manifest if m["status"] == "full")
    n_abs = sum(1 for m in manifest if m["status"] == "absent")
    lines.append(f"  [card floor: {len(manifest)} cards — {n_full} full, {n_abs} absent; every scored card is represented]")
    for cid in sorted(caps):
        c = caps[cid]
        if c.get("evidence_state") == "data_unavailable":
            lines.append(f"  · {cid}: DATA_UNAVAILABLE (measured gap, decision-useful)")
            continue
        parts = [f"class={c.get('class')}"]
        if c.get("numeric_anchors"):
            parts.append("anchors[" + ", ".join(f"{a['metric']}={a['value']}" for a in c["numeric_anchors"]) + "]")
        if c.get("n_basis"):
            parts.append("n[" + ", ".join(f"{k}={v}" for k, v in c["n_basis"].items()) + "]")
        if c.get("top_k_strata"):
            parts.append("strata{" + "; ".join(f"{r['role']}:{r['stratum']}={r['value']}(n={r['n']})" for r in c["top_k_strata"]) + "}")
        if c.get("sibling_caveats"):
            parts.append("caveats{" + ", ".join(f"{k}={v}" for k, v in c["sibling_caveats"].items()) + "}")
        if c.get("conflict_pairs"):
            cp = c["conflict_pairs"][0]
            parts.append(f"CONFLICT(mt={cp['measurement_type']} vs {[o['card'] for o in cp['other_sources']]})")
        if c.get("provenance_keys"):
            parts.append("prov[" + ", ".join(f"{p['key']}={p['value']}" for p in c["provenance_keys"][:3]) + "]")
        lines.append(f"  · {cid}: " + "  ".join(parts))
        for dq in (c.get("data_quality_flags") or []):
            lines.append(f"      ⚠ DATA-QUALITY: {dq['flag']} [{dq.get('field')}={dq.get('value')}]")
    return "\n".join(lines)


def _render_literature(decision: dict) -> str:
    """Compact render of the OPTIONAL verdict-inert literature lane (decision['literature_synthesis'],
    attached upstream by the --literature dispatcher seam). Empty string when absent or errored, so the
    narrator prompt is byte-identical to a no-literature run in that case."""
    lit = decision.get("literature_synthesis") or {}
    if not isinstance(lit, dict) or any(k in lit for k in ("_literature_error", "_literature_skipped")):
        return ""
    axes = lit.get("axes") or []
    if not axes and not lit.get("blind_spots"):
        return ""
    lines = ["LITERATURE LANE (EXTERNAL published-literature reads — verdict-INERT corroboration/contradiction; "
             "attribute as literature-derived, NOT omics; the class labels + numbers above remain authoritative):"]
    for ax in axes:
        if not isinstance(ax, dict):
            continue
        cites = "; ".join(
            (c.get("label", "") + (f" PMID:{c['pmid']}" if c.get("pmid") else "")
             + ("" if c.get("verified") else " [unverified]"))
            for c in (ax.get("citations") or [])[:2] if isinstance(c, dict))
        lines.append(f"  · axis {ax.get('axis_key')}: lit={ax.get('literature_read')} vs omics="
                     f"{ax.get('agreement_vs_omics')} (conf {ax.get('confidence')}) — {ax.get('assertion', '')}"
                     + (f"  [{cites}]" if cites else ""))
    for bs in (lit.get("blind_spots") or [])[:3]:
        if isinstance(bs, dict):
            lines.append(f"  ⚠ OMICS-BLIND: {bs.get('signal')} — {bs.get('why_omics_blind')}")
    if lit.get("key_divergence"):
        lines.append(f"  KEY DIVERGENCE: {lit['key_divergence']} (overall consistency: {lit.get('overall_consistency')})")
    return "\n".join(lines)


def build_capsule_prompt(decision: dict, lens: LensConfig) -> str:
    h = decision.get("headline", {}) or {}
    target, indication = decision.get("target"), decision.get("indication")
    pkg = (h.get("evidence_capsules") or decision.get("evidence_capsules")
           or emit_capsules(decision.get("cards", []), indication,
                            verdict_card_ids=lens.verdict_card_ids, config=lens.capsule_config))
    # collapsed verdict token: the lens's declared verdict_key wins (fixes presence, whose key is
    # `presence_verdict`, not the legacy `<name>_verdict` guess), then the generic fallbacks.
    _collapsed = ((h.get(lens.verdict_key) if lens.verdict_key else None)
                  or h.get("verdict") or h.get(lens.name.replace("-", "_") + "_verdict")
                  or h.get("driving_rule_id"))
    lines = [
        f"TARGET: {target}    INDICATION: {indication}    LENS: {lens.name}",
        "",
        render_narrator_signals(h, axis_labels=lens.axis_labels),
        "",
        _render_capsules(pkg),
        *(["", _render_literature(decision)] if _render_literature(decision) else []),
        "",
        f"COLLAPSED VERDICT (compressed label, fixed upstream — narrate, do not change): {_collapsed}",
        "",
        f"TASK: using the tool, {lens.relevance_prompt} Reason ACROSS the signals + capsule data; cite "
        f"card_id/field/value; state DATA_UNAVAILABLE gaps plainly; flag any data_quality_flags rather than "
        f"narrating them as biology. Obey the SCOPE guardrails.",
    ]
    return "\n".join(lines)


def narrate(decision: dict, lens: LensConfig, model_id: Optional[str] = None) -> dict:
    """Run the generic single-lens narration. Returns the provenance-stamped llm_synthesis block. The
    CALLER attaches it as decision['llm_synthesis'] and handles failures (degrade, never break the spine)."""
    from _skills_common.llm import synthesize_structured
    tool_name, tool_schema = _tool(lens)
    return synthesize_structured(system_prompt=_system(lens), user_prompt=build_capsule_prompt(decision, lens),
                                 tool_name=tool_name, tool_schema=tool_schema, model_id=model_id)


def make_synthesize_fn(lens: LensConfig):
    """Adapt a LensConfig to the dispatcher's synthesize_fn signature (decision, model_id, subtype_query).
    Each skill's run.py passes `synthesize_fn=make_synthesize_fn(<LENS>)` — one line, no bespoke module."""
    def _synthesize(decision, model_id=None, subtype_query=None):
        return narrate(decision, lens, model_id)
    return _synthesize
