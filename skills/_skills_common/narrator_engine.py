"""narrator_engine — ONE generic, capsule-driven single-lens narrator for the whole fleet.

Replaces the per-skill bespoke synthesis_*.py builders with one engine parameterized by a LensConfig
(data, not code). A narrator no longer plucks skill-specific fields: it reads the SIGNAL layer (the
narrator-input contract — subgroup_signals / question_table / claim_vector off the headline) plus the
bounded DATA layer (evidence_capsule.emit_capsules — the complete-but-limited per-card package), and the
LensConfig supplies only what genuinely differs per lens: the thesis, axis labels, scope guardrails,
signal polarity, and the output tool (a relevance read, or a descriptive context read for gateless skills).

Two-slot / VERDICT-INERT: the result is attached as decision['llm_synthesis'] AFTER the deterministic
spine is composed; it never mints or moves a verdict. Every field is provenance-stamped by
synthesize_structured. All narrators are now LensConfig entries in narrator_lenses.LENSES.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from _skills_common.evidence_capsule import emit_capsules
from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE
from _skills_common.signals_first import render_narrator_signals


@dataclass
class LensConfig:
    name: str  # skill kebab id, e.g. "on-target-safety-liability"
    thesis: str  # what a strong signal MEANS for this lens
    relevance_prompt: str  # 1-2 lines: what the headline judgment should assess
    axis_labels: dict = field(default_factory=dict)
    scope_exclusions: tuple = ()  # guardrails each bespoke narrator hard-codes today
    polarity_note: str = ""  # e.g. safety inversion: "signal = strength of the LIABILITY"
    mode: str = "verdict"  # "verdict" | "descriptive" (gateless skills)
    relevance_enum: tuple = ("strongly_supports", "supports_with_caveats", "neutral_uninformative", "argues_against")
    verdict_card_ids: Optional[set] = None  # full capsules for these; others thin (None = all full)
    capsule_config: dict = field(default_factory=dict)
    verdict_key: Optional[str] = None  # headline key holding the collapsed verdict token (e.g.
    # "presence_verdict"); None → the legacy <name>_verdict guess
    claim_spec_ref: Optional[str] = None  # "<module>:<VARNAME>" under _skills_common naming the ClaimSpec
    # roster this lens narrates, e.g. "genomic_claims:GENOMIC_CLAIM_SPEC". Declared as a STRING and
    # resolved LAZILY (tests/tooling only) so no runtime import edge is added from every skill to every
    # claims module. `axis_labels` MUST cover every axis_key in the referenced roster: literature_synthesis
    # .axis_measured_state iterates axis_labels, so an off-roster claim axis is never asked about — it
    # contributes 0 reads and therefore 0 contradicts, which every concordance instrument downstream reads
    # as AGREEMENT. Unaskable is not agreed. None = the lens hand-builds its vector (tumor-presence,
    # target-archetype); the coverage guard asserts those are the only two.


_CONF_ENUM = ("well_supported", "supported_with_caveats", "weakly_supported", "insufficient_evidence")

# Stage-2 PRIMARY output: a short list of crisp, grounded, anchored executive bullets. Shared by the
# verdict + descriptive tool schemas. Each bullet reasons ACROSS signals and carries the salient omics +
# literature datum (from key_evidence + the literature lane), anchored to real package ids.
_EXEC_BULLETS_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": 6,
    "description": (
        "PRIMARY: <=6 crisp executive bullets, each reasoning ACROSS the signals and carrying "
        "the SALIENT data point(s) — the indication/strongest stratum effect WITH its q/p, the "
        "omnibus, the driving categorical, and a corroborating/contrasting citation where the "
        "literature lane has one. Ground every number in key_evidence; cite the exact "
        "card_id/question_id/citation_id it comes from; <=~40 words each; scientific voice."
    ),
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "polarity", "cites"],
        "properties": {
            "text": {"type": "string", "description": "the bullet, carrying its grounded number(s); <=~40 words."},
            "polarity": {
                "type": "string",
                "enum": ["supportive", "opposing", "neutral", "killer", "not_applicable"],
                "description": "the bullet's direction for THIS lens (respect the polarity note; a liability is opposing/killer, never supportive).",
            },
            "cites": {
                "type": "object",
                "additionalProperties": False,
                "description": "real ids from the package this bullet is grounded in (>=1 total).",
                "properties": {
                    "card_ids": {"type": "array", "items": {"type": "string"}},
                    "question_ids": {"type": "array", "items": {"type": "string"}},
                    "citation_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def _tool(lens: LensConfig) -> tuple:
    if lens.mode == "descriptive":
        name = f"emit_{lens.name.replace('-', '_')}_context"
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["exec_bullets", "context_read", "key_signals_summary", "confidence_qualifier", "key_caveat"],
            "description": f"Descriptive {lens.name} context read (this lens is gateless — no relevance verdict). LEAD with exec_bullets; context_read is the demoted verbose prose.",
            "properties": {
                "exec_bullets": _EXEC_BULLETS_SCHEMA,
                "context_read": {
                    "type": "string",
                    "description": "SECONDARY verbose prose: 2-4 sentences integrating the signals + capsule data into the lens's context contribution; no nomination call.",
                },
                "key_signals_summary": {
                    "type": "string",
                    "description": "the 1-2 strongest, best-corroborated signals, cited to card_id/field.",
                },
                "confidence_qualifier": {"type": "string", "enum": list(_CONF_ENUM)},
                "key_caveat": {"type": "string"},
            },
        }
        return name, schema
    name = f"emit_{lens.name.replace('-', '_')}_synthesis"
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["exec_bullets", "relevance", "rationale", "confidence_qualifier", "key_caveat"],
        "description": f"Single-lens {lens.name} read. {lens.relevance_prompt} SINGLE-LENS — informs confidence, never mints/flips a nomination. LEAD with exec_bullets; rationale is the demoted verbose prose.",
        "properties": {
            "exec_bullets": _EXEC_BULLETS_SCHEMA,
            "relevance": {"type": "string", "enum": list(lens.relevance_enum), "description": lens.relevance_prompt},
            "rationale": {
                "type": "string",
                "description": "SECONDARY verbose prose: 2-4 sentences reasoning ACROSS the signals + capsule data; cite card_id/field/value; state DATA_UNAVAILABLE gaps.",
            },
            "confidence_qualifier": {"type": "string", "enum": list(_CONF_ENUM)},
            "key_caveat": {"type": "string", "description": "the single most important caveat, or 'none'."},
        },
    }
    return name, schema


def _system(lens: LensConfig) -> str:
    s = [
        f"You are a computational-oncology target-evaluation assistant. PURPOSE (single lens): reason "
        f"ACROSS the {lens.name} evidence for a (target, indication) and judge {lens.thesis}",
        "You NARRATE and INTEGRATE; you never invent facts and never change the deterministic, rule-computed "
        "verdict (FIXED upstream). Ground every claim in the provided fields/values.",
        "LEAD with the SIGNAL VECTOR; the collapsed verdict is a compressed label — state it last, never let it "
        "mask a disagreeing signal. Use the RAW CAPSULE DATA to sharpen the read (cite specific strata, "
        "magnitudes, conflicts) but the class labels remain authoritative; obey each capsule row's SCOPE note "
        "and treat data_quality_flags as bugs to flag, not facts to narrate.",
        "A card's RELIABILITY line (when present) is a TYPED, pipeline-computed quality/power read — "
        "n_effective, powered, confound_flags, artifact_flags, detection_strength — NOT a bug like "
        "data_quality_flags: narrate it as a caveat/qualifier on that card's class (e.g. a weak "
        "detection_strength or a confound_flag earns 'weakly supported' / a named caveat, not silence).",
    ]
    if lens.polarity_note:
        s.append(f"POLARITY: {lens.polarity_note}")
    if lens.scope_exclusions:
        s.append("SCOPE — do NOT discuss: " + "; ".join(lens.scope_exclusions) + ".")
    s.append(
        "REGISTER: scientific-publication voice; declarative, precise; report numbers with scale + direction; "
        "no promotional language."
    )
    s.append(
        "If a LITERATURE LANE is provided below, use it to CORROBORATE or CHALLENGE the omics signals and "
        "to surface omics-blind signals; attribute literature-derived claims explicitly (they are external, "
        "not from this package), treat any [unverified] citation with caution, and NEVER let the literature "
        "move the fixed verdict."
    )
    return " ".join(s) + _EVIDENCE_ONLY_DIRECTIVE


def _render_capsules(pkg: dict) -> str:
    caps = pkg.get("capsules", {})
    manifest = pkg.get("manifest", [])
    lines = [
        "EVIDENCE CAPSULES (complete-but-limited per-card data — the bounded raw behind the classes; "
        "cite these to sharpen the read):"
    ]
    n_full = sum(1 for m in manifest if m["status"] == "full")
    n_abs = sum(1 for m in manifest if m["status"] == "absent")
    lines.append(
        f"  [card floor: {len(manifest)} cards — {n_full} full, {n_abs} absent; every scored card is represented]"
    )
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
            parts.append(
                "strata{"
                + "; ".join(f"{r['role']}:{r['stratum']}={r['value']}(n={r['n']})" for r in c["top_k_strata"])
                + "}"
            )
        if c.get("sibling_caveats"):
            parts.append("caveats{" + ", ".join(f"{k}={v}" for k, v in c["sibling_caveats"].items()) + "}")
        if c.get("conflict_pairs"):
            cp = c["conflict_pairs"][0]
            parts.append(f"CONFLICT(mt={cp['measurement_type']} vs {[o['card'] for o in cp['other_sources']]})")
        if c.get("provenance_keys"):
            parts.append("prov[" + ", ".join(f"{p['key']}={p['value']}" for p in c["provenance_keys"][:3]) + "]")
        lines.append(f"  · {cid}: " + "  ".join(parts))
        for dq in c.get("data_quality_flags") or []:
            lines.append(f"      ⚠ DATA-QUALITY: {dq['flag']} [{dq.get('field')}={dq.get('value')}]")
        # Typed `reliability` facet (#2306/#2331) — READ off claim_vector.source_properties, never
        # re-derived from the summary; see evidence_capsule._reliability_for_card. Rendered only when
        # informative (the helper itself omits the honest skeleton), so a signal-poor domain emits no
        # new line here and the prompt degrades exactly as before #2331.
        for rel in c.get("reliability") or []:
            bits = [f"{k}={v}" for k, v in rel.items() if k != "property"]
            lines.append(f"      ◆ RELIABILITY[{rel.get('property')}]: " + ", ".join(bits))
        # RAW cited statements (citation cards only — the pmid/year/sentence SUBSTANCE): the narrator LEADS
        # with + attributes to these, rather than reporting the statements DATA_UNAVAILABLE.
        for st in c.get("cited_statements") or []:
            _cite = "PMID:" + st["pmid"] if st.get("pmid") else "(no pmid)"
            _yr = f" {st['year']}" if st.get("year") is not None else ""
            _sec = f" [{st['section']}]" if st.get("section") else ""
            lines.append(f"      ▸ CITED {_cite}{_yr}{_sec}: {st.get('sentence', '')}")
    return "\n".join(lines)


def _fmt_ke_num(v):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v != 0 and abs(v) < 1e-3:
        return f"{v:.2e}"
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def _ke_line(ke: dict) -> str:
    """A compact one-line grounding string for a card's key_evidence — what a bullet should LEAD with.
    When the card carries a typed reference-frame ruler (interpretation[]), LEAD with the PRE-GAUGED
    reading ('moderately dependent — median CHRONOS -1.73 vs wild-type -0.59 (Δ-1.14, past the -0.5 cut)')
    so the bullet copies the framing; else fall back to the indication stratum effect + q."""
    from _skills_common import display_gloss  # single-source gauge/gloss vocabulary

    parts = []
    interp = ke.get("interpretation") or []
    strata = ke.get("top_strata") or []
    lead = next((s for s in strata if s.get("role") == "indication"), None) or next(
        (s for s in strata if s.get("role") == "strongest"), None
    )
    eff = ke.get("effect") or {}
    if interp:
        gs = display_gloss.gauge_string(interp[0])
        if gs:
            parts.append(gs)
    elif lead:
        seg = f"{lead.get('label')} {eff.get('metric') or 'effect'}={_fmt_ke_num(lead.get('value'))}"
        if lead.get("q") is not None:
            seg += f" (q={_fmt_ke_num(lead.get('q'))})"
        if lead.get("n") is not None:
            seg += f", n={lead.get('n')}"
        parts.append(seg)
    elif eff.get("value") is not None:
        seg = f"{eff.get('metric')}={_fmt_ke_num(eff.get('value'))}"
        sig = ke.get("significance") or {}
        if sig.get("value") is not None:
            seg += f" ({sig.get('stat')}={_fmt_ke_num(sig.get('value'))})"
        parts.append(seg)
    om = ke.get("omnibus") or {}
    if om.get("value") is not None:
        parts.append(f"omnibus {om.get('stat')}={_fmt_ke_num(om.get('value'))}")
    for cat in (ke.get("categorical") or [])[:2]:
        if cat.get("value") is not None:
            parts.append(str(cat.get("value")))
    sub = ke.get("subtype_axis") or {}
    if sub.get("restriction_class"):
        parts.append(
            f"subtype:{sub.get('restriction_class')}"
            + (f"({sub.get('driving_axis')})" if sub.get("driving_axis") else "")
        )
    return " · ".join(str(p) for p in parts if p)


def _render_key_evidence(decision: dict, pkg: dict) -> str:
    """Render the per-card KEY EVIDENCE (Stage-1 promotion) — the decisive, indication-resolved data points
    the narrator must LEAD its bullets with. Built from the same _build_key_evidence the graph emits, over
    the capsule + the card summary (for the pinned omnibus/significance scalars). Empty when none."""
    try:
        from _skills_common.evidence_graph import _build_key_evidence
    except Exception:  # noqa: BLE001
        return ""
    caps = pkg.get("capsules", {}) or {}
    summ = {c.get("card_id"): (c.get("summary") or {}) for c in (decision.get("cards") or []) if isinstance(c, dict)}
    lines = []
    for cid in sorted(caps):
        cap = caps[cid]
        if cap.get("evidence_state") == "data_unavailable":
            continue
        ke = _build_key_evidence(cap, summ.get(cid, {}))
        s = _ke_line(ke) if ke else ""
        if s:
            lines.append(f"  · {cid}: {s}")
    if not lines:
        return ""
    return (
        "KEY EVIDENCE (the decisive, indication-resolved data points behind the classes — LEAD each "
        "bullet with these, carrying the effect WITH its q/p + the omnibus, cited to the card_id):\n" + "\n".join(lines)
    )


def _render_literature(decision: dict) -> str:
    """Compact render of the OPTIONAL verdict-inert literature lane (decision['literature_synthesis'],
    attached upstream by the --literature dispatcher seam). Empty string when absent or errored, so the
    narrator prompt is byte-identical to a no-literature run in that case."""
    lit = decision.get("literature_synthesis") or {}
    if not isinstance(lit, dict) or any(k in lit for k in ("_literature_error", "_literature_skipped")):
        return ""
    # Defensive unwrap: a --literature-only decision.json can reach here with `axes` still (or again)
    # provenance-wrapped as {value:[...], _source:'llm_synthesized', ...}. Without this, lit.get("axes")
    # is a truthy dict, the early-return below is skipped, and `for ax in axes` iterates the wrapper's
    # KEYS (strings) → every isinstance(ax, dict) is False → zero axis lines rendered.
    from _skills_common.literature_synthesis import _unwrap_stamped

    axes = _unwrap_stamped(lit.get("axes")) or []
    blind_spots = _unwrap_stamped(lit.get("blind_spots")) or []
    if not axes and not blind_spots:
        return ""
    lines = [
        "LITERATURE LANE (EXTERNAL published-literature reads — verdict-INERT corroboration/contradiction; "
        "attribute as literature-derived, NOT omics; the class labels + numbers above remain authoritative):"
    ]
    for ax in axes:
        if not isinstance(ax, dict):
            continue
        cites = "; ".join(
            (
                c.get("label", "")
                + (f" PMID:{c['pmid']}" if c.get("pmid") else "")
                + ("" if c.get("verified") else " [unverified]")
            )
            for c in (ax.get("citations") or [])[:2]
            if isinstance(c, dict)
        )
        lines.append(
            f"  · axis {ax.get('axis_key')}: lit={ax.get('literature_read')} vs omics="
            f"{ax.get('agreement_vs_omics')} (conf {ax.get('confidence')}) — {ax.get('assertion', '')}"
            + (f"  [{cites}]" if cites else "")
        )
    for bs in (blind_spots or [])[:3]:
        if isinstance(bs, dict):
            lines.append(f"  ⚠ OMICS-BLIND: {bs.get('signal')} — {bs.get('why_omics_blind')}")
    if lit.get("key_divergence"):
        lines.append(
            f"  KEY DIVERGENCE: {lit['key_divergence']} (overall consistency: {lit.get('overall_consistency')})"
        )
    return "\n".join(lines)


def build_capsule_prompt(decision: dict, lens: LensConfig) -> str:
    h = decision.get("headline", {}) or {}
    target, indication = decision.get("target"), decision.get("indication")
    _cv = h.get("claim_vector")
    pkg = (
        h.get("evidence_capsules")
        or decision.get("evidence_capsules")
        or emit_capsules(
            decision.get("cards", []),
            indication,
            verdict_card_ids=lens.verdict_card_ids,
            config=lens.capsule_config,
            # #2331: same source_properties threading as the dispatcher's central wiring (this branch
            # fires only when a caller built `decision` without going through the dispatcher, e.g. tests).
            source_properties=(_cv.get("source_properties") if isinstance(_cv, dict) else None),
        )
    )
    # collapsed verdict token: the lens's declared verdict_key wins (fixes presence, whose key is
    # `presence_verdict`, not the legacy `<name>_verdict` guess), then the generic fallbacks.
    _collapsed = (
        (h.get(lens.verdict_key) if lens.verdict_key else None)
        or h.get("verdict")
        or h.get(lens.name.replace("-", "_") + "_verdict")
        or h.get("driving_rule_id")
    )
    _ke_block = _render_key_evidence(decision, pkg)
    _lit_block = _render_literature(decision)
    lines = [
        f"TARGET: {target}    INDICATION: {indication}    LENS: {lens.name}",
        "",
        render_narrator_signals(h, axis_labels=lens.axis_labels),
        *(["", _ke_block] if _ke_block else []),
        "",
        _render_capsules(pkg),
        *(["", _lit_block] if _lit_block else []),
        "",
        f"COLLAPSED VERDICT (compressed label, fixed upstream — narrate, do not change): {_collapsed}",
        "",
        f"TASK: using the tool, {lens.relevance_prompt} FIRST write `exec_bullets`: <=6 crisp bullets, each "
        f"reasoning ACROSS the signals and LEADING with a KEY EVIDENCE datum (the indication/strongest stratum "
        f"effect WITH its q/p, the omnibus, the driving categorical), and — where the published-literature "
        f"lane has one — weaving a corroborating/contrasting citation (use agreement_vs_omics). Anchor every bullet: put the "
        f"exact card_id/question_id/citation_id it is grounded in into `cites` (>=1). Set each bullet's polarity "
        f"(a liability is opposing/killer, never supportive). THEN the secondary verbose prose. Cite "
        f"card_id/field/value; state DATA_UNAVAILABLE gaps; flag data_quality_flags rather than narrating them "
        f"as biology. Obey the SCOPE guardrails.",
    ]
    return "\n".join(lines)


def narrate(decision: dict, lens: LensConfig, model_id: Optional[str] = None) -> dict:
    """Run the generic single-lens narration. Returns the provenance-stamped llm_synthesis block. The
    CALLER attaches it as decision['llm_synthesis'] and handles failures (degrade, never break the spine)."""
    from _skills_common.llm import synthesize_structured

    tool_name, tool_schema = _tool(lens)
    return synthesize_structured(
        system_prompt=_system(lens),
        user_prompt=build_capsule_prompt(decision, lens),
        tool_name=tool_name,
        tool_schema=tool_schema,
        model_id=model_id,
    )


def make_synthesize_fn(lens: LensConfig):
    """Adapt a LensConfig to the dispatcher's synthesize_fn signature (decision, model_id, subtype_query).
    Each skill's run.py passes `synthesize_fn=make_synthesize_fn(<LENS>)` — one line, no bespoke module."""

    def _synthesize(decision, model_id=None, subtype_query=None):
        return narrate(decision, lens, model_id)

    return _synthesize
