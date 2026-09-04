"""Build the presentation IR from a nomination's spine, applying a ReportSpec.

The IR is a tiered, ordered tree of typed blocks (a closed `vocab.BLOCK_KINDS` vocabulary). This module
is the ONLY place selection logic lives — depth (which slots per level), scope (which skills), lead
(ordering/emphasis), and fail-soft substitution (an empty expected slot → an `unmeasured` block, never
silence or a crash). Backends walk this tree and emit syntax; they make no decisions.

Input is a `nomination` dict (the target-profile `nomination.json`), read defensively: the spine lives
at `nomination.target_report.skill_reports` ({short: skill_report}) with the decision at
`target_report.target_call`. Every read tolerates missing/None (the spine is only partially populated
today — see docs/UNIFIED_OUTPUT_CONTRACT.md adoption status).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from . import vocab
from .spec import ReportSpec, SCOPE_ALL, SCOPE_GATING


@dataclass
class Block:
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass
class Section:
    short: str
    title: str
    role: str
    is_deciding: bool
    blocks: list  # list[Block]; blocks[0] is always the SKILL_HEADER


@dataclass
class ReportIR:
    target: Optional[str]
    indication: Optional[str]
    spec: ReportSpec
    header: Block                 # REPORT_HEADER
    sections: list                # list[Section]
    about: Optional[Block]        # ABOUT | None
    deciding_short: Optional[str]
    overview: list = field(default_factory=list)  # report-level blocks (signals_overview, risk_6dim)

    def present_kinds(self) -> set:
        """Every block kind actually present — the parity/coverage contract surface."""
        kinds = {self.header.kind}
        kinds.update(b.kind for b in self.overview)
        if self.about is not None:
            kinds.add(self.about.kind)
        for sec in self.sections:
            kinds.update(b.kind for b in sec.blocks)
        return kinds


# --------------------------------------------------------------------------------------------------
# defensive readers
# --------------------------------------------------------------------------------------------------
def _first(d: dict, keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _deciding_short(deciding_axis: Any, shorts) -> Optional[str]:
    """Best-effort extract the deciding skill's short from the target_call.deciding_axis object."""
    if not isinstance(deciding_axis, dict):
        return None
    # canonical shape: {basis, deciding_axes: [{short, gate_name, band, ...}, ...]} — take the first.
    axes = deciding_axis.get("deciding_axes")
    if isinstance(axes, list):
        for a in axes:
            if isinstance(a, dict) and a.get("short"):
                return a["short"]
    for k in ("short", "axis", "skill", "deciding_skill"):
        v = deciding_axis.get(k)
        if isinstance(v, str) and v in shorts:
            return v
    # last resort: any string value that IS a known short
    for v in deciding_axis.values():
        if isinstance(v, str) and v in shorts:
            return v
    return None


# --------------------------------------------------------------------------------------------------
# per-skill block assembly
# --------------------------------------------------------------------------------------------------
def _chips_block(report: dict, eff_level: int) -> Optional[Block]:
    chips = report.get("claim_chips") or []
    limit = vocab.CHIP_LIMIT_BY_LEVEL.get(eff_level, None)
    if limit == 0 or not chips:
        return None
    shown = chips if limit is None else chips[:limit]
    return Block(vocab.CLAIM_CHIPS, {"chips": shown, "total": len(chips), "shown": len(shown)})


def _figure_blocks(report: dict, eff_level: int, medium: str) -> list:
    """One FIGURE block per figure entry (each carries a text fallback = caption, so a text-only
    medium degrades gracefully). L2 shows key figures (first), L3 shows all. `medium` is RESOLVED here
    (into `show_image`) — backends read the resolved flag, not the dial, so they stay dumb."""
    figs = report.get("figures") or []
    if not figs:
        return []
    selected = figs if eff_level >= 3 else figs[:1]
    show_image = medium in ("figure", "both")
    out = []
    for f in selected:
        cap = f.get("caption") or f.get("slot") or f.get("kind") or "figure"
        out.append(Block(vocab.FIGURE, {
            # NB: 'fig_kind' NOT 'kind' — 'kind' is reserved for the block kind and would shadow it
            # when a backend serializes {kind, **payload} (enforced by test_no_payload_shadows_kind).
            "slot": f.get("slot"), "fig_kind": f.get("kind"), "ref": f.get("path"),
            "caption": cap, "fallback_text": cap, "show_image": show_image,
        }))
    return out


def _unmeasured(slot: str) -> Block:
    return Block(vocab.UNMEASURED, {"slot": slot,
                                    "note": f"{slot.replace('_', ' ')}: not measured / not surfaced"})


def _build_section(short: str, report: dict, spec: ReportSpec, is_deciding: bool) -> Section:
    role = report.get("role") or ("gating" if short in vocab.GATING_SHORTS else "descriptive")
    eff = spec.level_int_for(short, is_deciding)

    header = Block(vocab.SKILL_HEADER, {
        "short": short,
        "title": vocab.skill_title(short),
        "role": role,
        "call": report.get("call"),                    # None for gateless — backend falls back to phrase
        "polarity": report.get("polarity"),
        "honest_phrase": report.get("honest_phrase"),
        "is_deciding": is_deciding,
    })
    blocks = [header]

    # a question_table will render at L2+ when present; it restates the claim-chips, so suppress the
    # redundant chips block when the Q&A table shows (dedupe — one decision-useful view per card).
    has_qt = eff >= vocab.TIER[vocab.QUESTION_TABLE] and bool(report.get("question_table"))

    # L1: confidence, tension, claim chips
    if eff >= vocab.TIER[vocab.CONFIDENCE] and report.get("confidence"):
        blocks.append(Block(vocab.CONFIDENCE, {"confidence": report["confidence"]}))
    if eff >= vocab.TIER[vocab.TENSION] and report.get("top_tension"):
        blocks.append(Block(vocab.TENSION, {"tension": report["top_tension"]}))
    if eff >= vocab.TIER[vocab.CLAIM_CHIPS] and not has_qt:
        cb = _chips_block(report, eff)
        if cb is not None:
            blocks.append(cb)

    # L2: question table (fail-soft coverage flag for a gating skill that measured none). per-phase
    # metrics + figures render WHEN PRESENT but no longer emit an 'unmeasured' placeholder when absent —
    # those repeated "not measured / not surfaced" lines were pure noise on every card; the question-
    # table coverage flag is the one worth keeping.
    is_gating = role == "gating"
    if eff >= vocab.TIER[vocab.QUESTION_TABLE]:
        qt = report.get("question_table") or []
        if qt:
            blocks.append(Block(vocab.QUESTION_TABLE, {"rows": qt}))
        elif is_gating:
            blocks.append(_unmeasured("question_table"))
    if eff >= vocab.TIER[vocab.PHASE_METRICS] and report.get("per_phase_metrics"):
        blocks.append(Block(vocab.PHASE_METRICS, {"rows": report["per_phase_metrics"]}))
    if eff >= vocab.TIER[vocab.FIGURE]:
        blocks.extend(_figure_blocks(report, eff, spec.medium))

    # L3: provenance
    if eff >= vocab.TIER[vocab.PROVENANCE] and report.get("provenance"):
        blocks.append(Block(vocab.PROVENANCE, {"provenance": report["provenance"]}))

    return Section(short=short, title=vocab.skill_title(short), role=role,
                   is_deciding=is_deciding, blocks=blocks)


# --------------------------------------------------------------------------------------------------
# ordering + scope
# --------------------------------------------------------------------------------------------------
def _in_scope(short: str, role: str, spec: ReportSpec) -> bool:
    if spec.scope == SCOPE_ALL:
        return True
    if spec.scope == SCOPE_GATING:
        return role == "gating"
    return short in spec.scope  # explicit tuple of shorts


def _sort_key(short: str, role: str, polarity: Optional[str], is_deciding: bool, spec: ReportSpec):
    lead_first = 0 if (spec.lead == "deciding_axis" and is_deciding) else 1
    rank = vocab.polarity_rank(polarity)                 # killer −3 … supportive +2; None off-scale
    # killers/opposing lead within a role group; off-scale (not_scored/insufficient) trail (not "worst").
    pol_key = (rank is None, rank if rank is not None else 0)
    return (lead_first, vocab.ROLE_RANK.get(role, 9), pol_key, vocab.skill_order_index(short), short)


# --------------------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------------------
def _signals_overview_block(selected, deciding_short) -> Optional[Block]:
    """The lead diverging-strip: one row per SCORED skill (gating, on-scale polarity), descriptive
    peers as a footnote. Signal polarity is the spine's canonical `skill_report.polarity` (killer-aware)
    — cleaner than parsing driving-rule-id suffixes. Carries the ordinal level for the bar length.
    (Design absorbed from the tp_dashboard v2 signals-first layout, re-sourced from the spine.)"""
    rows, descriptive = [], []
    for short, report, role in selected:
        polarity = report.get("polarity")
        title = vocab.skill_title(short)
        if role != "gating" or polarity in (None, "not_scored"):
            descriptive.append(title)          # context, not a bar
            continue
        rows.append({"short": short, "title": title, "polarity": polarity,
                     "level": vocab.polarity_rank(polarity), "call": report.get("call"),
                     "honest_phrase": report.get("honest_phrase"),  # plain-language, preferred over the snake_case call
                     "is_deciding": short == deciding_short})
    if not rows:
        return None
    return Block(vocab.SIGNALS_OVERVIEW, {
        "rows": rows, "descriptive": descriptive,
        "counts": {"support": sum(1 for r in rows if (r["level"] or 0) > 0),
                   "neutral": sum(1 for r in rows if r["level"] == 0),
                   "against": sum(1 for r in rows if (r["level"] or 0) < 0)},
        "deciding_short": deciding_short,
    })


_RISK6_ORDER = ("biological", "druggability", "safety", "translational", "clinical", "commercial")
# ENGINE-BLIND is deliberately OFF-SCALE (→ None), never rank 0: "not evidenced" is a coverage gap,
# not the lowest risk (same measured-vs-null discipline as ordinal_view's off-scale signals).
_RISK6_RANK = {"HIGH": 3, "MED": 2, "MEDIUM": 2, "LOW": 1}


def _risk_6dim_block(risk_6dim) -> Optional[Block]:
    """The deterministic 6-category risk rollup → {dims:[{dim,bin,rank}]}. Reads target_report.risk_6dim
    ({dim:{bin,…}} or a list); fail-soft on shape. 'rank' None = engine-blind / unrecognized bin."""
    if not risk_6dim:
        return None
    dims = []

    def _emit(dim, v):
        b = str(v.get("bin") or "") if isinstance(v, dict) else (v if isinstance(v, str) else "")
        dims.append({"dim": dim, "bin": b or None, "rank": _RISK6_RANK.get(b.upper())})

    if isinstance(risk_6dim, dict):
        seen = set()
        for d in _RISK6_ORDER:
            if d in risk_6dim:
                _emit(d, risk_6dim[d]); seen.add(d)
        for d, v in risk_6dim.items():
            if d not in seen and not str(d).startswith("_"):
                _emit(d, v)
    elif isinstance(risk_6dim, list):
        for item in risk_6dim:
            if isinstance(item, dict):
                _emit(item.get("dimension") or item.get("dim") or "?", item)
    return Block(vocab.RISK_6DIM, {"dims": dims}) if dims else None


# --- parity blocks (content-parity with the legacy target_profile.html/.md) --------------------
def _llm_val(llm: dict, key):
    raw = llm.get(key)
    return raw.get("value") if isinstance(raw, dict) else raw


def _synthesis_block(nomination: dict) -> Optional[Block]:
    """The LLM narrative (advisory / verdict-inert): executive summary + tension analysis + top
    arguments. Sourced from `llm_synthesis` (else the legacy `llm_output`)."""
    llm = nomination.get("llm_synthesis") or nomination.get("llm_output") or {}
    if not isinstance(llm, dict):
        return None
    exec_summary = _llm_val(llm, "executive_summary")
    tension = _llm_val(llm, "tension_analysis")
    args = _llm_val(llm, "top_arguments") or _llm_val(llm, "arguments")
    if not (exec_summary or tension or args):
        return None
    return Block(vocab.SYNTHESIS, {"executive_summary": exec_summary, "tension_analysis": tension,
                                   "arguments": args if isinstance(args, list) else None})


def _coherence_block(tr: dict, nomination: dict) -> Optional[Block]:
    tc = tr.get("thesis") or nomination.get("target_coherence") or {}
    if not isinstance(tc, dict):
        return None
    th = tc.get("thesis")
    thesis = th.get("primary") if isinstance(th, dict) else tc.get("primary")
    coh = tc.get("coherence")
    # coherence is a dict {class, confirms, caveats, artifact_flags} — surface only the class string
    # (+ non-empty caveats), never the raw dict (str(dict) was leaking into the page).
    coherence = coh.get("class") if isinstance(coh, dict) else coh
    caveats = [c for c in (coh.get("caveats") or [])] if isinstance(coh, dict) else []
    # thesis is rendered in the report header now; the coherence block adds only the coherence class +
    # caveats, so it emits only when there's a coherence class (avoids a duplicate thesis line).
    if not coherence and not caveats:
        return None
    return Block(vocab.COHERENCE, {"thesis": thesis, "coherence": coherence, "caveats": caveats})


def _modality_matrix_block(tr: dict, nomination: dict) -> Optional[Block]:
    mtx = tr.get("evidence_matrix") or nomination.get("ordinal_matrix")
    if not isinstance(mtx, dict) or not mtx.get("rows"):
        return None
    return Block(vocab.MODALITY_MATRIX, {
        "columns": (mtx.get("axes") or {}).get("columns") or [],
        "rows": mtx.get("rows") or [], "legend": mtx.get("legend") or {},
        "disclaimer": mtx.get("_disclaimer"),
    })


def _literature_risk_block(nomination: dict, tr: dict) -> Optional[Block]:
    ra = nomination.get("risk_assessment") or tr.get("literature_risk") or {}
    dims = ra.get("dimensions") if isinstance(ra, dict) else None
    if not isinstance(dims, dict) or not dims:
        return None
    rows = [{"dim": d, "risk_level": v.get("risk_level"), "interpretation": v.get("interpretation"),
             "pmids": v.get("cited_pmids") or v.get("pmids") or []}
            for d, v in dims.items() if isinstance(v, dict)]
    return Block(vocab.LITERATURE_RISK, {"dims": rows}) if rows else None


def _deciding_axis_block(target_call: dict, nomination: dict, deciding_short) -> Optional[Block]:
    da = (target_call or {}).get("deciding_axis") or nomination.get("deciding_axis")
    if not isinstance(da, dict) or not da:
        return None
    axis_titles = [vocab.skill_title(a["short"]) for a in (da.get("deciding_axes") or [])
                   if isinstance(a, dict) and a.get("short")]
    primary = (vocab.skill_title(deciding_short) if deciding_short
               else (axis_titles[0] if axis_titles else None))
    return Block(vocab.DECIDING_AXIS, {
        "short": deciding_short, "title": primary, "axes": axis_titles,
        "routing": da.get("routing"), "basis": da.get("basis"),
    })


def build_ir(nomination: dict, spec: ReportSpec,
             target: Optional[str] = None, indication: Optional[str] = None) -> ReportIR:
    """Project a nomination + spec into the presentation IR. Pure, deterministic, fail-soft."""
    nomination = nomination or {}
    tr = nomination.get("target_report") or {}
    skill_reports: dict = tr.get("skill_reports") or {}
    target_call = tr.get("target_call") or nomination.get("target_call") or {}

    target = target or _first(nomination, ["target"]) or _first(tr, ["target"])
    indication = indication or _first(nomination, ["indication"]) or _first(tr, ["indication"])

    deciding_short = _deciding_short(target_call.get("deciding_axis"), set(skill_reports))

    # header (the decision) — always present, tier 0.
    _thesis_obj = (tr.get("thesis") or {}).get("thesis") if isinstance(tr.get("thesis"), dict) else None
    _thesis_primary = _thesis_obj.get("primary") if isinstance(_thesis_obj, dict) else None
    header = Block(vocab.REPORT_HEADER, {
        "target": target,
        "indication": indication,
        "thesis": _thesis_primary if _thesis_primary != "insufficient_thesis" else None,
        "recommendation": target_call.get("recommendation"),
        "confidence": target_call.get("confidence"),
        "deciding_axis": target_call.get("deciding_axis"),
        "deciding_short": deciding_short,
        "deciding_title": vocab.skill_title(deciding_short) if deciding_short else None,
        "dissent": target_call.get("dissent") or [],
        "gate": target_call.get("gate"),
        "lead": spec.lead,
    })

    # select + order sections.
    selected = []
    for short, report in skill_reports.items():
        if not isinstance(report, dict):
            continue
        role = report.get("role") or ("gating" if short in vocab.GATING_SHORTS else "descriptive")
        if not _in_scope(short, role, spec):
            continue
        selected.append((short, report, role))

    selected.sort(key=lambda t: _sort_key(
        t[0], t[2], t[1].get("polarity"), t[0] == deciding_short, spec))

    sections = [_build_section(short, report, spec, is_deciding=(short == deciding_short))
                for short, report, role in selected]

    overview = []

    def _add(kind, block):
        if block is not None and spec.level_int >= vocab.TIER[kind]:
            overview.append(block)

    _add(vocab.SIGNALS_OVERVIEW, _signals_overview_block(selected, deciding_short))
    _add(vocab.COHERENCE, _coherence_block(tr, nomination))
    _add(vocab.SYNTHESIS, _synthesis_block(nomination))
    _add(vocab.RISK_6DIM, _risk_6dim_block(tr.get("risk_6dim")))
    _add(vocab.MODALITY_MATRIX, _modality_matrix_block(tr, nomination))
    _add(vocab.LITERATURE_RISK, _literature_risk_block(nomination, tr))
    _add(vocab.DECIDING_AXIS, _deciding_axis_block(target_call, nomination, deciding_short))
    return ReportIR(target=target, indication=indication, spec=spec, header=header,
                    sections=sections, about=_about_block(spec), deciding_short=deciding_short,
                    overview=overview)


def _about_block(spec: ReportSpec) -> Optional[Block]:
    """The honesty legend / spec footer — shown from L1 up (kept off the one-page L0 exec brief)."""
    if spec.level_int < vocab.TIER[vocab.ABOUT]:
        return None
    return Block(vocab.ABOUT, {
        "polarity_legend": vocab.polarity_legend(),
        "spec": {"level": spec.level, "medium": spec.medium,
                 "scope": list(spec.scope) if isinstance(spec.scope, tuple) else spec.scope,
                 "lead": spec.lead},
        "note": ("Signals lead; the call is a subordinate summary. Ordinal polarity is an "
                 "order-preserving display view, NOT calibrated measurement; 'not scored' / "
                 "off-scale means context or a coverage gap, not a low score."),
    })


def build_ir_for_skill(skill_report: dict, spec: ReportSpec, *, skill_name: Optional[str] = None,
                       short: Optional[str] = None, target: Optional[str] = None,
                       indication: Optional[str] = None) -> ReportIR:
    """Project a SINGLE skill's `skill_report` into a one-section report IR (for rendering a standalone
    skill run, e.g. tumor-presence, without a full target_report). No target_call decision header — the
    header is just the target/indication frame; the skill's own call/polarity lead its section. Same
    tiering, medium and fail-soft as the composed path."""
    skill_report = skill_report or {}
    if short is None:
        short = vocab.skill_short_for_name(skill_name) or skill_name or "skill"
    header = Block(vocab.REPORT_HEADER, {
        "target": target, "indication": indication,
        "recommendation": None, "confidence": None, "deciding_axis": None,
        "deciding_short": None, "deciding_title": None, "dissent": [], "gate": None,
        "lead": spec.lead, "single_skill": True,
    })
    section = _build_section(short, skill_report, spec, is_deciding=False)
    return ReportIR(target=target, indication=indication, spec=spec, header=header,
                    sections=[section], about=_about_block(spec), deciding_short=None)


__all__ = ["Block", "Section", "ReportIR", "build_ir", "build_ir_for_skill"]
