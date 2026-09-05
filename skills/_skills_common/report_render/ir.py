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

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import vocab
from .. import display_gloss as _dg  # plain-language readings (metric gloss + direction + card description)
from .spec import ReportSpec, SCOPE_ALL, SCOPE_GATING


@dataclass
class Block:
    kind: str
    payload: dict = field(default_factory=dict)
    # faceted-view grouping (see vocab.BLOCK_LENS). None = report chrome / un-lensed (standalone path).
    # A dataclass FIELD, not a payload key — so it never shadows `kind` under {kind, **payload}.
    lens: Optional[str] = None


@dataclass
class Section:
    short: str
    title: str
    role: str
    is_deciding: bool
    blocks: list  # list[Block]; blocks[0] is always the SKILL_HEADER
    lens: Optional[str] = None    # faceted-view grouping; composed sections → vocab.LENS_SIGNALS


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
    banner: Optional[Block] = None                 # SYNTHESIS_BANNER | None — persistent chrome above tabs

    def present_kinds(self) -> set:
        """Every block kind actually present — the parity/coverage contract surface."""
        kinds = {self.header.kind}
        kinds.update(b.kind for b in self.overview)
        if self.banner is not None:
            kinds.add(self.banner.kind)
        if self.about is not None:
            kinds.add(self.about.kind)
        for sec in self.sections:
            kinds.update(b.kind for b in sec.blocks)
        return kinds

    def lenses(self) -> list:
        """Group the lens-annotated overview blocks + sections into the faceted view, in LENS_ORDER.

        Returns `[(lens_id, title, items)]` where `items` is a list of `("block", Block)` |
        `("section", Section)` — overview blocks first (their build_ir insertion order), then the
        per-skill sections. Report chrome (header, about) and any block/section with lens=None are NOT
        bucketed, so an all-None IR (the standalone `build_ir_for_skill` path) returns `[]` and the
        backends fall back to the flat header→overview→sections layout (byte-stable for standalone)."""
        buckets: dict = {}
        for b in self.overview:
            lg = getattr(b, "lens", None)
            if lg:
                buckets.setdefault(lg, []).append(("block", b))
        for sec in self.sections:
            lg = getattr(sec, "lens", None)
            if lg:
                buckets.setdefault(lg, []).append(("section", sec))
        ordered = []
        for lens_id in vocab.LENS_ORDER:
            if buckets.get(lens_id):
                ordered.append((lens_id, vocab.LENS_TITLE.get(lens_id, lens_id), buckets[lens_id]))
        for lens_id, items in buckets.items():   # any future lens not in LENS_ORDER, stably last
            if lens_id not in vocab.LENS_ORDER:
                ordered.append((lens_id, vocab.LENS_TITLE.get(lens_id, lens_id), items))
        return ordered


# --------------------------------------------------------------------------------------------------
# defensive readers
# --------------------------------------------------------------------------------------------------
def _first(d: dict, keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _deciding_axis_rank(a: dict) -> int:
    """Headline-worthiness of one entry in `deciding_axes` (lower = better). The list can LEAD with an
    axis the framework cannot evidence (`framework_can_evidence: "blind"`, e.g. the gateless
    cis_coherence lens) — headlining that as THE deciding axis is misleading and hides the marker from
    the signals strip (a blind axis is a descriptive footnote, not a bar). Prefer an evidenced + gated
    axis (the real decision driver), then evidenced, then gated, else anything."""
    blind = a.get("framework_can_evidence") == "blind"
    gated = bool(a.get("gate") or a.get("gate_name"))
    if not blind and gated:
        return 0
    if not blind:
        return 1
    if gated:
        return 2
    return 3


def _deciding_short(deciding_axis: Any, shorts) -> Optional[str]:
    """Best-effort extract the deciding skill's short from the target_call.deciding_axis object."""
    if not isinstance(deciding_axis, dict):
        return None
    # canonical shape: {basis, deciding_axes: [{short, gate_name, band, framework_can_evidence, ...}]}.
    # Pick the most headline-worthy (evidenced + gated), NOT blindly the first — the list may lead with
    # a framework-blind axis. Stable on original order within a rank.
    axes = deciding_axis.get("deciding_axes")
    if isinstance(axes, list):
        cand = [(i, a) for i, a in enumerate(axes) if isinstance(a, dict) and a.get("short")]
        if cand:
            cand.sort(key=lambda t: (_deciding_axis_rank(t[1]), t[0]))
            return cand[0][1]["short"]
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


# run-dir figure channel: card_figures descriptor `path` is relative to the run's figures/ dir, and the
# default target_profile.html/.md sit at the run root beside it — so a stable `figures/` prefix resolves
# for a browser/markdown viewer with NO file reads (backends stay dumb; ref is the final relative URL).
_FIGURE_BASE = "figures/"


def _card_figure_blocks(card_figs: list, eff_level: int, medium: str,
                        polarity: Optional[str], role: Optional[str]) -> list:
    """Join a section's run-dir card figures (nomination.card_figures) into FIGURE blocks. Each figure
    carries a verdict BADGE derived from the section's spine polarity (the figure-emitter redesign moved
    the verdict OFF the figure onto the composing layer — see vocab.figure_status). L2 shows each card's
    PRIMARY figure; L3 shows all its SVGs. Plotly `.plotly.json` siblings are carried as `dynamic_ref`
    (an interactive-embed hook) but never emitted as their own image block. medium is RESOLVED here."""
    if not card_figs:
        return []
    show_image = medium in ("figure", "both")
    status = vocab.figure_status(polarity, role)
    out = []
    for card_id, descs in card_figs:
        svgs = [d for d in (descs or []) if isinstance(d, dict)
                and not d.get("dynamic") and str(d.get("path") or "").endswith(".svg")]
        dyn = [d for d in (descs or []) if isinstance(d, dict) and d.get("dynamic")]
        if not svgs:
            continue
        svgs.sort(key=lambda d: 0 if d.get("primary") else 1)   # primary first, else stable
        selected = svgs if eff_level >= 3 else svgs[:1]
        for d in selected:
            cap = vocab.humanize_figure_type(d.get("type"), d.get("id"))
            ref = _FIGURE_BASE + str(d["path"]) if d.get("path") else None
            dref = next((x.get("path") for x in dyn if x.get("id") == d.get("id")),
                        (dyn[0].get("path") if dyn else None))
            out.append(Block(vocab.FIGURE, {
                # 'fig_kind' NOT 'kind' (reserved — see _figure_blocks / test_no_payload_shadows_kind).
                "slot": None, "fig_kind": d.get("type"), "ref": ref,
                "caption": cap, "fallback_text": cap, "show_image": show_image,
                "card_id": card_id, "primary": bool(d.get("primary")), "status": status,
                "dynamic_ref": (_FIGURE_BASE + str(dref)) if dref else None,
            }))
    return out


def _card_figure_owner_map(nomination: dict, skill_reports: dict) -> dict:
    """Assign each card_id in `card_figures` to ONE owning skill short. A card composes under several
    lenses (its card_id appears in multiple sub_verdicts.cards_used); prefer the GATING lister (spine
    role, else GATING_SHORTS), then canonical SKILL_ORDER — so a card that carries a gating verdict
    (e.g. normal-tissue-liability under safety) lands there, not under a descriptive lister (presence)
    that merely displays it. One owner → a figure is never duplicated across sections."""
    listers: dict = {}
    for short, sv in (nomination.get("sub_verdicts") or {}).items():
        if not isinstance(sv, dict):
            continue
        for cid in (sv.get("cards_used") or []):
            listers.setdefault(cid, []).append(short)

    def _is_gating(short: str) -> bool:
        rep = skill_reports.get(short)
        rrole = rep.get("role") if isinstance(rep, dict) else None
        return rrole == "gating" or (rrole is None and short in vocab.GATING_SHORTS)

    def _pick(shorts: list) -> str:
        pool = [s for s in shorts if _is_gating(s)] or shorts
        return sorted(pool, key=vocab.skill_order_index)[0]

    return {cid: _pick(shorts) for cid, shorts in listers.items() if shorts}


def _figures_by_owner(nomination: dict, owner_map: dict) -> dict:
    """{owner_short: [(card_id, [descriptor,...]), ...]} — the card figures grouped by owning section,
    in nomination.card_figures insertion order (deterministic upstream)."""
    by: dict = {}
    for cid, descs in (nomination.get("card_figures") or {}).items():
        if not isinstance(descs, list):
            continue
        owner = owner_map.get(cid)
        if owner:
            by.setdefault(owner, []).append((cid, descs))
    return by


def _build_section(short: str, report: dict, spec: ReportSpec, is_deciding: bool,
                   card_figs: list = ()) -> Section:
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

    # embedded sub-skill signals-first detail (the composed report's per-skill drill-down == the standalone
    # sub-skill view, one code path): a signal×confidence scatter + hierarchy sub-group bands, both
    # projections of the spine's `subgroup_signals` (populated by PR4). Tier-gated to L2 so L0/L1 stay lean;
    # fail-soft — absent until the spine carries subgroup_signals, so this lands green before PR4.
    # both embedded blocks are evidence-depth (L2) — the report-level SIGNALS_SCATTER is TIER 0 (it leads
    # the Signals lens), but the PER-SKILL embedded scatter is drill-down detail, gated with the bands.
    # When the carried evidence_graph is question-anchored (P2 carry + questions.yaml / hierarchy
    # fallback), render the RICH embedded view (per-question fingerprint here; literature axes + per-card
    # chains below) == the standalone dashboard; the fingerprint SUPERSEDES the lean sub-group
    # scatter/bands. Otherwise fall back to the sub-group scatter/bands. Fail-soft; display-only.
    eg = report.get("evidence_graph")
    eg_rich = isinstance(eg, dict) and bool(eg.get("questions"))
    sg = report.get("subgroup_signals")
    if eg_rich and eff >= vocab.TIER[vocab.EVIDENCE_FINGERPRINT]:
        fp = _evidence_fingerprint_block(eg)
        if fp is not None:
            blocks.append(fp)
    elif isinstance(sg, dict) and sg and eff >= vocab.TIER[vocab.SUBGROUP_BANDS]:
        sc = _subgroup_scatter_block(sg)
        if sc is not None:
            blocks.append(sc)
        bb = _subgroup_bands_block(sg)
        if bb is not None:
            blocks.append(bb)

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
    # RICH embedded view (cont.): the literature-axis panel (per-axis agreement + citations + blind spots)
    if eg_rich and eff >= vocab.TIER[vocab.LITERATURE_AXES]:
        la = _literature_axes_block(eg)
        if la is not None:
            blocks.append(la)
    if eff >= vocab.TIER[vocab.PHASE_METRICS] and report.get("per_phase_metrics"):
        blocks.append(Block(vocab.PHASE_METRICS, {"rows": report["per_phase_metrics"]}))
    if eff >= vocab.TIER[vocab.FIGURE]:
        blocks.extend(_figure_blocks(report, eff, spec.medium))
        blocks.extend(_card_figure_blocks(card_figs, eff, spec.medium,
                                          report.get("polarity"), role))

    # L3: RICH embedded view (cont.) — per-card dataset→data→rule→verdict chains, then provenance
    if eg_rich and eff >= vocab.TIER[vocab.CARD_CHAIN]:
        cc = _card_chain_block(eg)
        if cc is not None:
            blocks.append(cc)
    # Stage-2 narrative: the single-lens grounded exec_bullets (from the graph's projected narrative —
    # an opt-in --synthesize trailer; absent → no block). Leads with the crisp bullets; rationale prose
    # is the demoted verbose read. Advisory / verdict-inert.
    if isinstance(eg, dict) and eff >= vocab.TIER[vocab.SYNTHESIS]:
        nb = _skill_synthesis_block(eg.get("narrative") or {})
        if nb is not None:
            blocks.append(nb)
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
# A surface-antigen coherence thesis (from tp_facets.build_target_coherence): the target's actionable
# modality is a biologics SURFACE agent (ADC / TCE / naked antibody), whose mechanism of action does NOT
# require the target to be a genetic dependency — the payload / T-cell does the killing, not target loss.
# Under such a thesis a MEASURED-NEGATIVE dependency is EXPECTED and orthogonal, NOT evidence against the
# target. Two layers of the composed run already say exactly this — the ordinal matrix emits `·` (no
# signal) for the dependency axis on the adc/bite_tce/antibody columns, and build_target_coherence emits
# the caveat "non_dependent is EXPECTED for a surface antigen — coherent, not a red flag" — but the flat
# diverging strip reads only the scalar `skill_report.polarity` (floored to `opposing`) and would miscount
# the dependency "against". This constant mirrors that SAME, already-validated determination onto the strip.
_SURFACE_ANTIGEN_THESES = frozenset({"surface_antigen_no_dependency", "amplification_overexpression_antigen"})


def _negative_expected_under_thesis(short: str, polarity: Optional[str],
                                    thesis_primary: Optional[str]) -> Optional[str]:
    """A short note when a gating skill's MEASURED-NEGATIVE signal is EXPECTED (orthogonal, not opposing)
    under the target's coherence thesis — so the diverging strip does not miscount it "against". The one
    encoded case (mirrors build_target_coherence's caveat + the ordinal-matrix `·`): the dependency axis
    under a surface-antigen thesis, where an ADC / TCE / antibody MoA never required a genetic dependency.
    Returns None otherwise — every intracellular / oncogene-addiction / driver thesis, and every
    non-negative row, is UNCHANGED (so the reconciliation can only ever de-escalate a negative, never
    invent a positive, and only for a target the coherence engine has already typed as a surface antigen)."""
    if short != "dependency":
        return None
    rank = vocab.polarity_rank(polarity)
    if rank is None or rank >= 0:            # only a measured-negative (opposing / killer) is reconciled
        return None
    if thesis_primary in _SURFACE_ANTIGEN_THESES:
        return ("expected for a surface-antigen thesis — orthogonal to the ADC/TCE mechanism, "
                "not counted against")
    return None


def _signals_overview_block(selected, deciding_short, thesis_primary=None) -> Optional[Block]:
    """The lead diverging-strip: one row per SCORED skill (gating, on-scale polarity), descriptive
    peers as a footnote. Signal polarity is the spine's canonical `skill_report.polarity` (killer-aware)
    — cleaner than parsing driving-rule-id suffixes. Carries the ordinal level for the bar length.
    (Design absorbed from the tp_dashboard v2 signals-first layout, re-sourced from the spine.)

    THESIS RECONCILIATION: a gating skill's measured-negative that is EXPECTED under the target's
    coherence thesis (dependency × surface-antigen — see `_negative_expected_under_thesis`) is reframed to
    NEUTRAL for the bar + the support/neutral/against tally, with the raw polarity + a note retained so it
    is reframed, never hidden. This keeps the flat strip consistent with the ordinal matrix (`·` on the
    biologics columns) and the coherence caveat, which already treat that non-dependence as orthogonal."""
    rows, descriptive = [], []
    for short, report, role in selected:
        polarity = report.get("polarity")
        title = vocab.skill_title(short)
        if role != "gating" or polarity in (None, "not_scored"):
            descriptive.append(title)          # context, not a bar
            continue
        expected_note = _negative_expected_under_thesis(short, polarity, thesis_primary)
        prov = report.get("provenance") if isinstance(report.get("provenance"), dict) else {}
        rows.append({"short": short, "title": title,
                     # a thesis-expected negative renders + tallies as NEUTRAL (orthogonal, not against);
                     # the raw polarity + note are carried so a backend can show it was a measured negative.
                     "polarity": "neutral" if expected_note else polarity,
                     "level": 0 if expected_note else vocab.polarity_rank(polarity),
                     "raw_polarity": polarity if expected_note else None,
                     "expected_note": expected_note,
                     "call": report.get("call"),
                     "honest_phrase": report.get("honest_phrase"),  # plain-language, preferred over the snake_case call
                     # provenance for the "where does this signal come from" context: each bar is one
                     # sub-skill's verdict rolled up from N evidence cards / M fired rules.
                     "n_cards": len(prov.get("cards_used") or []),
                     "n_rules": len(prov.get("fired_rule_ids") or []),
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


# A rule-id token: kebab with ≥2 dashes (alteration-role-gof-driver-supportive) or an UPPER-CASE
# contract id (SAF-LOF-01). The synthesis prompt asks the LLM to cite these inline as [rule-a, rule-b];
# they clutter the executive prose, so the renderer lifts them OUT into a provenance affordance.
_RULE_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+){2,}|[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+")
_CITE_GROUP = re.compile(r"\s*\[([^\[\]]+)\]")


def _strip_rule_citations(text: Any) -> tuple:
    """Lift inline `[rule-id, rule-id]` grounding citations out of LLM prose → (clean_text, [rule_ids]).
    Only a bracket whose content is ENTIRELY rule-id-like tokens is removed, so a prose aside like
    '[see figure]' is preserved. Order-preserving dedup of the collected rule-ids."""
    if not isinstance(text, str) or not text:
        return text, []
    found: list = []

    def _sub(m):
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if parts and all(_RULE_TOKEN.fullmatch(p) for p in parts):
            found.extend(parts)
            return ""
        return m.group(0)

    clean = _CITE_GROUP.sub(_sub, text)
    clean = re.sub(r"\s+([.,;:)])", r"\1", clean)   # tidy the space a removed citation left before punctuation
    clean = re.sub(r"\(\s+", "(", clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    seen, ordered = set(), []
    for r in found:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return clean, ordered


def _synthesis_block(nomination: dict) -> Optional[Block]:
    """The LLM narrative (advisory / verdict-inert): executive summary + tension analysis + top
    arguments. Sourced from `llm_synthesis` (else the legacy `llm_output`). Inline rule-id citations are
    stripped from the prose into `citations` (a provenance affordance the backends render collapsed)."""
    llm = nomination.get("llm_synthesis") or nomination.get("llm_output") or {}
    if not isinstance(llm, dict):
        return None
    exec_summary = _llm_val(llm, "executive_summary")
    tension = _llm_val(llm, "tension_analysis")
    args = _llm_val(llm, "top_arguments") or _llm_val(llm, "arguments")
    # Stage-2 PRIMARY: the crisp grounded executive bullets (single-lens narrator + composed). Lead with
    # them; the verbose prose (executive_summary / rationale / context_read) is demoted to a secondary read.
    raw_bullets = _llm_val(llm, "exec_bullets") or []
    exec_bullets = []
    for b in raw_bullets:
        if isinstance(b, dict) and b.get("text"):
            txt, _ = _strip_rule_citations(b.get("text"))
            exec_bullets.append({"text": txt, "polarity": b.get("polarity"), "cites": b.get("cites") or {}})
    verbose = exec_summary or _llm_val(llm, "rationale") or _llm_val(llm, "context_read")
    if not (exec_bullets or exec_summary or tension or args or verbose):
        return None
    exec_clean, c1 = _strip_rule_citations(exec_summary)
    tens_clean, c2 = _strip_rule_citations(tension)
    args_out, c3 = None, []
    if isinstance(args, list):
        args_out = []
        for a in args:
            if isinstance(a, dict):
                claim = a.get("claim") or a.get("text") or a.get("argument")
                cc, cids = _strip_rule_citations(claim)
                c3.extend(cids)
                args_out.append({**a, "claim": cc} if claim is not None else a)
            else:
                cc, cids = _strip_rule_citations(a)
                c3.extend(cids)
                args_out.append(cc)
    seen, citations = set(), []
    for r in (*c1, *c2, *c3):
        if r not in seen:
            seen.add(r)
            citations.append(r)
    return Block(vocab.SYNTHESIS, {"exec_bullets": exec_bullets, "executive_summary": exec_clean,
                                   "tension_analysis": tens_clean, "arguments": args_out,
                                   "citations": citations})


def _skill_synthesis_block(narrative: dict) -> Optional[Block]:
    """Build a SYNTHESIS block from a single-skill graph `narrative` (evidence_graph.narrative) — the
    Stage-2 exec_bullets lead + the demoted verbose prose (rationale). None when the narrative is empty
    (no --synthesize). Reuses the SYNTHESIS backends (same as the composed report)."""
    if not isinstance(narrative, dict):
        return None
    bullets = [b for b in (narrative.get("exec_bullets") or []) if isinstance(b, dict) and b.get("text")]
    verbose = narrative.get("rationale") or narrative.get("relevance")
    if not (bullets or verbose):
        return None
    verbose_clean, cites = _strip_rule_citations(verbose) if verbose else (None, [])
    return Block(vocab.SYNTHESIS, {"exec_bullets": bullets, "executive_summary": verbose_clean,
                                   "tension_analysis": None, "arguments": None, "citations": cites})


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
    # A bare "Coherence: coherent" line carries no information (it's the expected default) — the block
    # is worth showing ONLY when it adds a caveat or flags a NON-coherent class. Drop the trivial case
    # so the report doesn't accrue context-free one-word sections. (thesis lives in the header.)
    _trivial = (not caveats) and (coherence in (None, "", "coherent", "coherent_with_caveats"))
    if _trivial:
        return None
    return Block(vocab.COHERENCE, {"thesis": thesis, "coherence": coherence, "caveats": caveats})


def _row_has_on_scale(row: dict) -> bool:
    """True if any cell in the row is on-scale (a measured signal). An all-off-scale row is pure `·`
    noise (no measured modality signal for that axis) — dropped from the display matrix."""
    return any((c or {}).get("on_scale") for c in (row.get("cells") or {}).values())


# drug-delivery channel → reader label, in decision display order (intracellular first, then surface).
_CHANNEL_LABEL = {
    "small_molecule": "Small molecule", "degrader": "Degrader", "biologics": "Biologic (generic)",
    "adc": "ADC", "bite_tce": "T-cell engager (TCE)", "antibody": "Antibody",
}
_CHANNEL_ORDER = ["small_molecule", "degrader", "biologics", "adc", "bite_tce", "antibody"]
# per-channel fit → display rank (viable first) + status token (mapped to the reserved status palette).
_FIT_RANK = {"favorable": 0, "viable": 0, "conditional": 1, "unfavorable": 2}
_FIT_STATUS = {"favorable": ("viable", "Viable"), "viable": ("viable", "Viable"),
               "conditional": ("conditional", "Conditional"), "unfavorable": ("unfavorable", "Unfavorable")}


def _modality_fit_channels(nomination: dict, tr: dict) -> list:
    """Per-modality readout from the AUTHORITATIVE `modality_fit_by_channel` (worst-case conjunction of
    each axis's RESOLVED modality_scope — the spine-safe per-channel view, NOT the raw gate×modality
    column-min the matrix disclaimer forbids aggregating). Each channel → {name, status, label,
    limiting_axis, by_axis, masked_by_axis}. Applicable channels first (ranked viable→unfavorable),
    then the not-applicable/masked channels."""
    mf = tr.get("modality_fit") or nomination.get("modality_fit_by_channel") or {}
    by = mf.get("by_channel") if isinstance(mf, dict) else None
    if not isinstance(by, dict) or not by:
        return []
    applic, masked = [], []
    for ch in list(_CHANNEL_ORDER) + [c for c in by if c not in _CHANNEL_ORDER]:
        d = by.get(ch)
        if not isinstance(d, dict):
            continue
        fit = d.get("fit")
        masked_by = d.get("masked_by_axis")
        row = {"channel": ch, "name": _CHANNEL_LABEL.get(ch, ch.replace("_", " ").title()),
               "limiting_axis": d.get("limiting_axis"),
               "by_axis": d.get("by_axis") if isinstance(d.get("by_axis"), dict) else {},
               "masked_by_axis": masked_by}
        if fit in ("not_applicable_by_axis", "not_applicable", None) or masked_by:
            row["status"], row["label"] = "not_applicable", "Not applicable"
            masked.append(row)
        else:
            row["status"], row["label"] = _FIT_STATUS.get(fit, ("unfavorable", _humanize_local(fit)))
            row["_rank"] = _FIT_RANK.get(fit, 3)
            applic.append(row)
    applic.sort(key=lambda r: (r.get("_rank", 3), _CHANNEL_ORDER.index(r["channel"])
                               if r["channel"] in _CHANNEL_ORDER else 99))
    return applic + masked


def _humanize_local(x) -> str:
    return str(x).replace("_", " ") if x is not None else ""


def _modality_matrix_block(tr: dict, nomination: dict) -> Optional[Block]:
    """Modality FIT: a per-channel status readout (from modality_fit_by_channel) + the raw gate×modality
    ordinal grid retained as a drill-down (it preserves the killer-vs-opposing shape + the per-axis
    detail the scalar per-channel view can flatten). Emits if EITHER source is present."""
    channels = _modality_fit_channels(nomination, tr)
    mtx = tr.get("evidence_matrix") or nomination.get("ordinal_matrix")
    grid_rows, columns = [], []
    if isinstance(mtx, dict) and mtx.get("rows"):
        # drop all-`·` rows (no on-scale cell) — an axis with no measured modality signal adds only noise.
        grid_rows = [r for r in (mtx.get("rows") or []) if isinstance(r, dict) and _row_has_on_scale(r)]
        columns = (mtx.get("axes") or {}).get("columns") or []
    if not channels and not grid_rows:
        return None
    return Block(vocab.MODALITY_MATRIX, {
        "channels": channels,                       # the lead: per-modality status readout
        "columns": columns, "rows": grid_rows,      # the raw ordinal grid → drill-down
        "legend": (mtx or {}).get("legend") or {},
        "glyph_legend": vocab.ordinal_glyph_legend(),
        "disclaimer": (mtx or {}).get("_disclaimer"),
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


# map the flip_condition `to_role` prefix → a plain-language direction word.
_FLIP_DIRECTION = {"kill": "would kill the call", "veto": "would kill the call",
                   "neutral": "would neutralize the axis", "positive": "would strengthen the call",
                   "negative": "would weaken the call"}
# curation priority: what the call RESTS ON, then the ADVERSE flips (kill > neutralize > weaken),
# then the upside (strengthen). The resolver enumerates every reachable verdict, so an axis like
# dependency can emit ~10 recommendation-flips — a full dump is noise, not a decision aid.
_FLIP_DIR_PRIORITY = {"would kill the call": 1, "would neutralize the axis": 2,
                      "would weaken the call": 3, "would strengthen the call": 4}
_FLIP_MAX_PER_AXIS = 2
_FLIP_MAX_TOTAL = 6


def _flip_conditions_block(nomination: dict) -> Optional[Block]:
    """"What would change the call" — the recommendation-FLIPPING counterfactuals per axis, read from
    narrative_by_axis[axis].flip_conditions. Rendered from the STRUCTURED fields (to_verdict, present,
    to_role) — the dev-note `sentence` is deliberately NOT surfaced (engineering commentary, not reader
    prose). `present=True` = a load-bearing signal the current call rests on (absent it, the call
    changes); `present=False` = a latent condition that would flip the call if it held.

    The resolver enumerates EVERY reachable verdict, so a single axis can emit ~10 flips (incl.
    near-duplicate `insufficient_*` flavours and vacuous same-direction upside). This is CURATED into a
    decision aid: collapse to one representative per (axis, direction) — preferring the load-bearing
    (present) row — then keep, per axis, the highest-priority directions (rests-on / adverse over
    upside), capped per axis and overall."""
    nba = nomination.get("narrative_by_axis") or {}
    if not isinstance(nba, dict):
        return None
    # one representative per (axis, direction): a present=True row wins (it's a live fact, not a hypo).
    reps: dict = {}
    axis_order: list = []
    for short, ax in nba.items():
        if not isinstance(ax, dict):
            continue
        title = vocab.skill_title(short)
        for fc in (ax.get("flip_conditions") or []):
            if not isinstance(fc, dict) or not fc.get("recommendation_flip"):
                continue
            direction = _FLIP_DIRECTION.get(str(fc.get("to_role") or "").split(":")[0])
            row = {"axis": title, "to_verdict": fc.get("to_verdict"),
                   "present": bool(fc.get("present")), "direction": direction,
                   "condition": fc.get("rule_id")}
            key = (title, direction)
            cur = reps.get(key)
            if cur is None:
                if title not in axis_order:
                    axis_order.append(title)
                reps[key] = row
            elif row["present"] and not cur["present"]:
                reps[key] = row     # promote the load-bearing representative for this direction
    if not reps:
        return None

    def _prio(r):
        return 0 if r["present"] else _FLIP_DIR_PRIORITY.get(r["direction"], 5)

    rows, per_axis = [], {}
    for r in sorted(reps.values(), key=lambda r: (axis_order.index(r["axis"]), _prio(r))):
        if per_axis.get(r["axis"], 0) >= _FLIP_MAX_PER_AXIS:
            continue
        per_axis[r["axis"]] = per_axis.get(r["axis"], 0) + 1
        rows.append(r)
    rows.sort(key=lambda r: (not r["present"], axis_order.index(r["axis"]), _prio(r)))
    return Block(vocab.FLIP_CONDITIONS, {"rows": rows[:_FLIP_MAX_TOTAL]})


def _subtype_block(tr: dict) -> Optional[Block]:
    """Molecular-subtype stratification (MSI/MSS, CMS, CIMP, …) from target_report.subtype_convergence.
    Emits only when a subtype axis was actually evaluated (skips subtype_axis_unavailable / n=0)."""
    sc = tr.get("subtype_convergence")
    if not isinstance(sc, dict):
        return None
    verdict = sc.get("verdict")
    n_eval = sc.get("n_subtypes_evaluated") or 0
    per_subtype = sc.get("per_subtype") or {}
    if verdict in (None, "subtype_axis_unavailable") or (not per_subtype and not n_eval):
        return None
    return Block(vocab.SUBTYPE, {
        "verdict": verdict,
        "n_evaluated": n_eval,
        "axes_available": sc.get("axes_available") or [],
        "convergent_subtypes": sc.get("convergent_subtypes") or [],
        "associated_subtypes": sc.get("associated_subtypes") or [],
        "subtypes": list(per_subtype.keys()),
    })


def _biomarker_block(tr: dict) -> Optional[Block]:
    """Patient-selection biomarker facet (target_report.biomarker): the stratification story +
    preferred assay + intended-use hypotheses. Drops the per-hypothesis `_note` dev text + deep
    dependency_performance numbers (kept in the evidence package), surfacing only the reader fields."""
    bm = tr.get("biomarker")
    if not isinstance(bm, dict) or not bm.get("verdict"):
        return None
    strat = bm.get("stratification_role") if isinstance(bm.get("stratification_role"), dict) else {}
    corr = bm.get("corroboration_role") if isinstance(bm.get("corroboration_role"), dict) else {}
    hyps = []
    for h in (bm.get("biomarker_hypotheses") or []):
        if isinstance(h, dict) and h.get("intended_use"):
            hyps.append({"intended_use": h.get("intended_use"), "basis": h.get("basis"),
                         "evidence_strength": h.get("evidence_strength")})
    return Block(vocab.BIOMARKER, {
        "verdict": bm.get("verdict"),
        "preferred_assay": bm.get("preferred_assay"),
        "alteration_role": corr.get("alteration_role"),
        "mutation_stratification": strat.get("mutation_stratification_class"),
        "subtype_stratification": strat.get("subtype_stratification_class"),
        "survival_association": strat.get("survival_association_class"),
        "rna_as_biomarker": strat.get("rna_as_biomarker"),
        "intended_uses": bm.get("intended_uses") or [],
        "hypotheses": hyps,
    })


# archetype phenotype-mixture key → reader phrase (the "what kind of target IS this" characterization).
_PHENOTYPE_LABEL = {
    "control_housekeeping": "housekeeping / broadly-essential control",
    "amp_driver": "amplification-driven oncogene",
    "dependency_essential": "selective genetic dependency",
    "snv_driver": "SNV / mutation driver",
    "tsg_loss": "tumor-suppressor (loss-of-function)",
    "expression_surface": "surface / expression antigen",
    "immune_checkpoint": "immune-checkpoint",
    "fusion_driver": "fusion driver",
}


def _target_characterization(tr: dict) -> Optional[dict]:
    """A concrete, data-backed 'what kind of target is this' from the archetype phenotype-mixture
    (soft kNN membership against the reference atlas) — the leading CONTEXT that frames the target
    itself BEFORE any verdict. Returns the top phenotype components (weight ≥ 8%), or None."""
    arche = tr.get("archetype") if isinstance(tr.get("archetype"), dict) else {}
    mix = arche.get("phenotype_mixture")
    if not isinstance(mix, dict) or not mix:
        return None
    items = sorted(((k, v) for k, v in mix.items() if isinstance(v, (int, float)) and v >= 0.08),
                   key=lambda kv: -kv[1])[:3]
    if not items:
        return None
    return {"mixture": [{"label": _PHENOTYPE_LABEL.get(k, str(k).replace("_", " ")),
                         "weight": round(float(v), 2)} for k, v in items]}


# =================================================================================================
# faceted-rollup builders (PR2): the signals-first spine one level up + the embedded sub-skill view.
# =================================================================================================
_TIER_ORDINAL = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0}      # subgroup signal tier → y
_CONF_ORDINAL = {"high": 2, "moderate": 1, "medium": 1, "low": 0, "weak": 0}  # confidence level → x


def _confidence_level(conf) -> Optional[str]:
    """The confidence level string from a {level|tier} dict or a bare string."""
    if isinstance(conf, dict):
        return conf.get("level") or conf.get("tier")
    return conf if isinstance(conf, str) else None


def _confidence_ordinal(conf) -> Optional[int]:
    lvl = _confidence_level(conf)
    return _CONF_ORDINAL.get(str(lvl).lower()) if lvl else None


def _unwrap(v):
    """Unwrap a provenance-stamped {value, _source, …} scalar; pass a bare value through."""
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _rec_norm(v) -> str:
    return str(_unwrap(v) or "").strip().lower().split()[0] if _unwrap(v) else ""


def _synthesis_banner_block(nomination: dict, target_call: dict) -> Optional[Block]:
    """The persistent advisory banner (report chrome, above the lens tabs): the LLM executive summary +
    an explicit LLM-vs-deterministic recommendation MISMATCH flag (UNIFIED_OUTPUT_CONTRACT rule 2 — the
    deterministic target_call is authoritative; a divergent LLM lean is surfaced, never allowed to win).
    Advisory / verdict-inert; the executive summary's inline [rule-id] citations are lifted to a footnote."""
    llm = nomination.get("llm_synthesis") or nomination.get("llm_output") or {}
    if not isinstance(llm, dict):
        return None
    exec_summary = _llm_val(llm, "executive_summary")
    if not exec_summary:
        return None
    exec_clean, cites = _strip_rule_citations(exec_summary)
    llm_rec = _llm_val(llm, "overall_recommendation") or _llm_val(llm, "recommendation")
    det_rec = _unwrap((target_call or {}).get("recommendation"))
    mismatch = None
    if _rec_norm(llm_rec) and _rec_norm(det_rec) and _rec_norm(llm_rec) != _rec_norm(det_rec):
        mismatch = {"llm": str(_unwrap(llm_rec)), "deterministic": str(det_rec)}
    return Block(vocab.SYNTHESIS_BANNER, {"executive_summary": exec_clean, "citations": cites,
                                          "n_rules": len(cites), "mismatch": mismatch})


def _route_synthesis_to_lenses(nomination: dict, skill_reports: dict) -> list:
    """Route each LLM argument / tension SENTENCE to its TOPICAL lens (a SYNTHESIS_NOTE block, pre-lensed)
    by resolving its inline citation anchors → owning skill (via each skill_report's provenance) → lens
    (vocab.SKILL_TOPICAL_LENS). Anchors resolve rule-ids first, then cards (a card can be shared; rule-ids
    are skill-specific). Sentences that route to the Decision lens are DROPPED here — the Decision lens
    already carries the full consolidated SYNTHESIS block, so per-lens notes are additive surfacing for the
    NON-decision lenses only. No LLM tool-schema change; reuses the existing anchor tokens."""
    llm = nomination.get("llm_synthesis") or nomination.get("llm_output") or {}
    if not isinstance(llm, dict):
        return []
    rule_idx: dict = {}
    card_idx: dict = {}
    for short in sorted(skill_reports, key=vocab.skill_order_index):
        rep = skill_reports.get(short)
        prov = (rep.get("provenance") if isinstance(rep, dict) else None) or {}
        for r in list(prov.get("fired_rule_ids") or []) + \
                ([prov["driving_rule_id"]] if prov.get("driving_rule_id") else []):
            rule_idx.setdefault(str(r), short)
        for c in list(prov.get("cards_used") or []):
            card_idx.setdefault(str(c), short)

    def _lens_for(text) -> str:
        _clean, toks = _strip_rule_citations(text)
        for t in toks:
            if t in rule_idx:
                return vocab.SKILL_TOPICAL_LENS.get(rule_idx[t], vocab.LENS_DECISION)
        for t in toks:
            if t in card_idx:
                return vocab.SKILL_TOPICAL_LENS.get(card_idx[t], vocab.LENS_DECISION)
        return vocab.LENS_DECISION

    sentences: list = []
    for a in (_llm_val(llm, "top_arguments_for") or []):
        if isinstance(a, str):
            sentences.append(("for", a))
    for a in (_llm_val(llm, "top_arguments_against") or []):
        if isinstance(a, str):
            sentences.append(("against", a))
    tension = _llm_val(llm, "tension_analysis")
    if isinstance(tension, str) and tension:
        sentences.append(("tension", tension))

    by_lens: dict = {}
    for stance, text in sentences:
        lens = _lens_for(text)
        if lens == vocab.LENS_DECISION:
            continue                       # covered by the consolidated SYNTHESIS block already
        clean, _ = _strip_rule_citations(text)
        by_lens.setdefault(lens, []).append({"stance": stance, "text": clean})
    blocks = []
    for lens in vocab.LENS_ORDER:
        notes = by_lens.get(lens)
        if notes:
            b = Block(vocab.SYNTHESIS_NOTE, {"notes": notes})
            b.lens = lens                  # pre-lensed; build_ir preserves an already-set lens
            blocks.append(b)
    return blocks


def _signals_scatter_block(selected, deciding_short) -> Optional[Block]:
    """Report-level signal × confidence scatter — one point per SCORED gating skill. Position is honest:
    x = confidence (low/moderate/high), y = signal STRENGTH tier; DIRECTION (supports vs against vs killer)
    is carried by colour + glyph (CVD-safe: position is strength, not direction). Leads the Signals lens,
    complementing the diverging strip (which shows the full signed ordinal)."""
    pts = []
    for short, report, role in selected:
        polarity = report.get("polarity")
        if role != "gating" or polarity in (None, "not_scored"):
            continue
        rank = vocab.polarity_rank(polarity)
        strength = "strong" if abs(rank or 0) >= 2 else "weak" if abs(rank or 0) == 1 else "absent"
        pts.append({"short": short, "title": vocab.skill_title(short), "polarity": polarity,
                    "signal_tier": strength, "signal_y": _TIER_ORDINAL[strength],
                    "confidence_x": _confidence_ordinal(report.get("confidence")),
                    "confidence": _confidence_level(report.get("confidence")),
                    "honest_phrase": report.get("honest_phrase"),
                    "is_deciding": short == deciding_short})
    if not pts:
        return None
    return Block(vocab.SIGNALS_SCATTER, {
        "scope": "skills", "points": pts, "deciding_short": deciding_short,
        "y_ticks": ["absent", "weak", "strong"], "x_ticks": ["low", "moderate", "high"],
        "y_label": "signal strength", "x_label": "confidence",
    })


def _subgroup_scatter_block(subgroup_signals: dict) -> Optional[Block]:
    """Per-skill signal × confidence scatter over the hierarchy sub-groups (the embedded-view analog of the
    report-level scatter). x = confidence, y = signal tier; a conflicted sub-group is flagged."""
    if not isinstance(subgroup_signals, dict) or not subgroup_signals:
        return None
    pts = []
    for sg_id, d in subgroup_signals.items():
        if not isinstance(d, dict):
            continue
        tier = str(d.get("signal") or "absent")
        pts.append({"name": str(sg_id).replace("_", " "), "signal_tier": tier,
                    "signal_y": _TIER_ORDINAL.get(tier, 0),
                    "confidence_x": _CONF_ORDINAL.get(str(d.get("confidence") or "").lower()),
                    "confidence": d.get("confidence"), "conflict": bool(d.get("conflict")),
                    "n_sources": d.get("n_sources")})
    if not pts:
        return None
    return Block(vocab.SIGNALS_SCATTER, {
        "scope": "subgroups", "points": pts,
        "y_ticks": ["absent", "weak", "moderate", "strong"], "x_ticks": ["low", "moderate", "high"],
        "y_label": "signal", "x_label": "confidence",
    })


def _subgroup_bands_block(subgroup_signals: dict) -> Optional[Block]:
    """Per-skill hierarchy sub-group bands: one row per sub-group with its signal tier, confidence,
    source count + agreement, power and conflict flag (a direct projection of derive_subgroups output)."""
    if not isinstance(subgroup_signals, dict) or not subgroup_signals:
        return None
    rows = []
    for sg_id, d in subgroup_signals.items():
        if not isinstance(d, dict):
            continue
        rows.append({"name": str(sg_id).replace("_", " "), "signal": d.get("signal"),
                     "confidence": d.get("confidence"), "n_sources": d.get("n_sources"),
                     "n_agree": d.get("n_agree"), "power": d.get("power"),
                     "conflict": bool(d.get("conflict"))})
    return Block(vocab.SUBGROUP_BANDS, {"sub_groups": rows}) if rows else None


# --------------------------------------------------------------------------------------------------
# evidence-graph blocks (P3) — the RICH embedded sub-skill view, projected from the carried
# skill_report.evidence_graph. Pure projections (no re-derivation); opacity/ordinal live in the backend.
# --------------------------------------------------------------------------------------------------
def _evidence_fingerprint_block(eg: dict) -> Optional[Block]:
    """Per-question fingerprint == the standalone dashboard's heatmap: one row per question, one cell per
    contributing card (colour = card signal polarity, opacity = confidence — the backend maps dots→opacity),
    plus a literature dot (colour = agreement). Projection over eg.{questions,cards,literature}; None when
    the graph carries no questions."""
    qs = eg.get("questions") or []
    if not qs:
        return None
    cards_by_id = {c.get("id"): c for c in (eg.get("cards") or [])}
    axes_by_id = {a.get("axis_id"): a for a in ((eg.get("literature") or {}).get("axes") or [])}
    rows = []
    for q in qs:
        cells = []
        for cid in (q.get("card_ids") or []):
            c = cards_by_id.get(cid) or {}
            sig = c.get("signal") or {}
            cells.append({"card_id": cid, "polarity": sig.get("polarity"),
                          "liability": bool(sig.get("liability")),
                          "dots": (c.get("confidence") or {}).get("dots"),
                          "label": sig.get("label") or (c.get("class") or {}).get("value")})
        lit = None
        for ax_id in (q.get("literature_axis_ids") or []):
            a = axes_by_id.get(ax_id)
            if a:
                lit = {"axis_id": ax_id, "read": a.get("read"), "agreement": a.get("agreement_vs_omics"),
                       "confidence": a.get("confidence"), "cited": bool(a.get("citation_ids"))}
                break
        sg = q.get("signal") or {}
        rows.append({"id": q.get("id"), "seq": q.get("seq"), "text": q.get("text"),
                     "polarity": sg.get("polarity"), "tier": sg.get("tier"),
                     "dots": (q.get("confidence") or {}).get("dots"), "cells": cells, "lit": lit})
    return Block(vocab.EVIDENCE_FINGERPRINT, {"questions": rows})


def _fmt_num(v):
    """Compact display of a scalar (sig-figs for tiny p/q, else short decimal)."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v != 0 and abs(v) < 1e-3:
        return f"{v:.2e}"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _format_key_evidence(ke: Optional[dict]) -> Optional[str]:
    """A compact one-line grounding string from a card's key_evidence — the decisive datum the narrator
    and the card-chain drill should LEAD with (indication stratum effect + q, omnibus, driving categorical,
    subtype restriction). None when the card carries no key_evidence."""
    if not isinstance(ke, dict) or not ke:
        return None
    parts: list = []
    strata = ke.get("top_strata") or []
    ind = next((s for s in strata if s.get("role") == "indication"), None)
    lead = ind or next((s for s in strata if s.get("role") == "strongest"), None)
    eff = ke.get("effect") or {}
    direction = eff.get("direction")
    if lead:
        # the stratum row carries its own value; gloss the effect metric + direction (plain reading)
        seg = f"{lead.get('label')}: {_dg.metric_reading(eff.get('metric') or 'effect', lead.get('value'), direction)}"
        if lead.get("q") is not None:
            seg += f", q={_fmt_num(lead.get('q'))}"
        if lead.get("n") is not None:
            seg += f", n={lead.get('n')}"
        parts.append(seg)
    elif eff.get("value") is not None:
        seg = _dg.metric_reading(eff.get("metric") or "effect", eff.get("value"), direction)
        sig = ke.get("significance") or {}
        if sig.get("value") is not None:
            seg += f", {_dg.gloss(sig.get('stat'))[0] or sig.get('stat')}={_fmt_num(sig.get('value'))}"
        parts.append(seg)
    strong = next((s for s in strata if s.get("role") == "strongest"), None)
    if ind and strong and strong is not lead:
        parts.append(f"strongest {strong.get('label')} {_fmt_num(strong.get('value'))}"
                     + (f" (q={_fmt_num(strong.get('q'))})" if strong.get("q") is not None else ""))
    omni = ke.get("omnibus") or {}
    if omni.get("value") is not None:
        parts.append(f"{_dg.gloss(omni.get('stat'))[0] or omni.get('stat')}={_fmt_num(omni.get('value'))}")
    for cat in (ke.get("categorical") or [])[:2]:
        if cat.get("value") is not None:
            parts.append(_dg.humanize(cat.get("value")))
    sub = ke.get("subtype_axis") or {}
    if sub.get("restriction_class"):
        seg = f"subtype: {sub.get('restriction_class')}"
        if sub.get("driving_axis"):
            seg += f" ({sub.get('driving_axis')})"
        parts.append(seg)
    return " · ".join(p for p in parts if p) or None


def _card_chain_block(eg: dict) -> Optional[Block]:
    """Per-card dataset→data→rule→verdict chains, grouped by measurement layer (the card's
    measurement_type). Projection over eg.cards[]; None when the graph carries no cards. Each card also
    carries its promoted `key_evidence` + a compact `key_evidence_summary` (the decisive grounded datum)."""
    cards = eg.get("cards") or []
    if not cards:
        return None
    # target/indication for the plain-language card description (question: with {target.symbol}/
    # {indication.label} filled). The join lives HERE (report_render), never the pure graph builder.
    target, indication = eg.get("target"), eg.get("indication")
    layers: dict = {}
    order: list = []
    for c in cards:
        mt = c.get("measurement_type") or "other"
        if mt not in layers:
            layers[mt] = []
            order.append(mt)
        sig = c.get("signal") or {}
        chain = c.get("chain") or {}
        ke = c.get("key_evidence")
        class_value = (c.get("class") or {}).get("value")
        interp = (ke or {}).get("interpretation") or []
        layers[mt].append({
            "id": c.get("id"), "polarity": sig.get("polarity"), "liability": bool(sig.get("liability")),
            "role": c.get("role"), "class_value": class_value,
            "description": _dg.card_description(c.get("id"), target, indication),  # plain "what is this card"
            "reads": _dg.humanize(class_value) or None,                            # class-led "Reads: <class>"
            "interpretation": interp,                                              # typed reference-frame ruler(s)
            "gauge": _dg.gauge_string(interp[0]) if interp else None,              # the ruler in words
            "n": (c.get("confidence") or {}).get("n"), "dots": (c.get("confidence") or {}).get("dots"),
            "dataset_ids": chain.get("dataset_ids") or [], "data": chain.get("data") or [],
            "rule_id": chain.get("rule_id"), "is_driving": bool(chain.get("is_driving")),
            "contributes": bool(chain.get("contributes_to_verdict")),
            "key_evidence": ke, "key_evidence_summary": _format_key_evidence(ke)})
    return Block(vocab.CARD_CHAIN,
                 {"layers": [{"layer": mt.replace("_", " "), "cards": layers[mt]} for mt in order]})


def _literature_axes_block(eg: dict) -> Optional[Block]:
    """Per-axis literature panel (read / agreement / assertion / citations) + blind spots + overall
    consistency, from eg.literature + eg.citations. None when the graph carries no literature."""
    lit = eg.get("literature") or {}
    axes = lit.get("axes") or []
    blind_raw = lit.get("blind_spots") or []
    if not axes and not blind_raw:
        return None
    cites_by_id = {c.get("id"): c for c in (eg.get("citations") or [])}

    def _cites(ids):
        out = []
        for cid in (ids or []):
            c = cites_by_id.get(cid)
            if c:
                out.append({"label": c.get("label"), "pmid": c.get("pmid"),
                            "verified": bool(c.get("verified"))})
        return out

    axes_out = [{"axis_id": a.get("axis_id"), "read": a.get("read"),
                 "agreement": a.get("agreement_vs_omics"), "confidence": a.get("confidence"),
                 "assertion": a.get("assertion"), "question_ids": a.get("question_ids") or [],
                 "citations": _cites(a.get("citation_ids"))} for a in axes]
    blind = [{"text": b.get("text"), "why_omics_blind": b.get("why_omics_blind"),
              "citations": _cites(b.get("citation_ids"))} for b in blind_raw]
    return Block(vocab.LITERATURE_AXES, {
        "axes": axes_out, "blind_spots": blind,
        "overall_consistency": lit.get("overall_consistency"),
        "key_divergence": lit.get("key_divergence")})


def _cross_cutting_block(nomination: dict, skill_reports: dict) -> Optional[Block]:
    """Cross-cutting questions: a skill's question-table rows whose signal is measured but which inform a
    DIFFERENT lens than the skill's own (surfaced so a cross-lens question is not buried inside one skill).
    Derived from spine data already present (question_table + the skill's topical lens); a thin, capped
    list — not a dump. Fail-soft: returns None when nothing qualifies."""
    rows = []
    for short in sorted(skill_reports, key=vocab.skill_order_index):
        rep = skill_reports.get(short)
        if not isinstance(rep, dict):
            continue
        owner_lens = vocab.SKILL_TOPICAL_LENS.get(short)
        for q in (rep.get("question_table") or []):
            if not isinstance(q, dict):
                continue
            note = q.get("cross_lens") or q.get("informs_lens")
            if not note:
                continue                    # only questions explicitly flagged as cross-lens
            rows.append({"question": q.get("question") or q.get("q") or q.get("label"),
                         "owner": vocab.skill_title(short), "owner_lens": owner_lens,
                         "informs": note})
            if len(rows) >= 6:
                break
        if len(rows) >= 6:
            break
    return Block(vocab.CROSS_CUTTING_QUESTIONS, {"rows": rows}) if rows else None


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
    # coherence thesis lives at target_report.thesis (full-nest) OR top-level nomination.target_coherence
    # (pre-nest runs) — same fallback _coherence_block uses, so the header + strip reconciliation resolve
    # it in both shapes. Byte-stable on the nested goldens (the fallback never triggers there).
    _tc = (tr.get("thesis") if isinstance(tr.get("thesis"), dict) else None) \
        or (nomination.get("target_coherence") if isinstance(nomination.get("target_coherence"), dict) else None)
    _thesis_obj = (_tc or {}).get("thesis") if isinstance(_tc, dict) else None
    _thesis_primary = _thesis_obj.get("primary") if isinstance(_thesis_obj, dict) else None
    header = Block(vocab.REPORT_HEADER, {
        "target": target,
        "indication": indication,
        "thesis": _thesis_primary if _thesis_primary != "insufficient_thesis" else None,
        # data-backed "what kind of target is this" (archetype phenotype-mixture) — leads the header so
        # the target is CHARACTERIZED before the one-word recommendation.
        "characterization": _target_characterization(tr),
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

    # run-dir figure join: map each produced card figure to its owning section (gating-lister first).
    figs_by_owner = _figures_by_owner(nomination, _card_figure_owner_map(nomination, skill_reports))

    sections = [_build_section(short, report, spec, is_deciding=(short == deciding_short),
                               card_figs=figs_by_owner.get(short, []))
                for short, report, role in selected]

    overview = []

    def _add(kind, block):
        if block is not None and spec.level_int >= vocab.TIER[kind]:
            overview.append(block)

    # thesis primary (target_coherence) → reconcile a thesis-EXPECTED negative in the diverging strip
    # (e.g. dependency non-signal under a surface-antigen thesis). Reuses the header's `_thesis_obj`;
    # None on a run without a coherence thesis leaves the strip's raw polarities untouched.
    _add(vocab.SIGNALS_SCATTER, _signals_scatter_block(selected, deciding_short))   # leads the Signals lens
    _add(vocab.SIGNALS_OVERVIEW, _signals_overview_block(selected, deciding_short, _thesis_primary))
    _add(vocab.CROSS_CUTTING_QUESTIONS, _cross_cutting_block(nomination, skill_reports))
    _add(vocab.COHERENCE, _coherence_block(tr, nomination))
    _add(vocab.SYNTHESIS, _synthesis_block(nomination))
    _add(vocab.RISK_6DIM, _risk_6dim_block(tr.get("risk_6dim")))
    _add(vocab.BIOMARKER, _biomarker_block(tr))
    _add(vocab.SUBTYPE, _subtype_block(tr))
    _add(vocab.MODALITY_MATRIX, _modality_matrix_block(tr, nomination))
    _add(vocab.LITERATURE_RISK, _literature_risk_block(nomination, tr))
    _add(vocab.DECIDING_AXIS, _deciding_axis_block(target_call, nomination, deciding_short))
    _add(vocab.FLIP_CONDITIONS, _flip_conditions_block(nomination))

    # routed LLM synthesis notes → their topical lens (pre-lensed SYNTHESIS_NOTE blocks); the consolidated
    # SYNTHESIS block stays in the Decision lens (see _route_synthesis_to_lenses).
    if spec.level_int >= vocab.TIER[vocab.SYNTHESIS_NOTE]:
        overview.extend(_route_synthesis_to_lenses(nomination, skill_reports))

    # stamp the faceted-view lens grouping (presentation only — never changes what was selected above).
    # overview blocks → their BLOCK_LENS; the per-skill sections → the Signals lens. A block that already
    # carries a lens (a pre-lensed SYNTHESIS_NOTE) is preserved. The composed report is thus a
    # lens-annotated IR; the standalone build_ir_for_skill leaves everything lens=None.
    for b in overview:
        b.lens = b.lens or vocab.BLOCK_LENS.get(b.kind)
    for sec in sections:
        sec.lens = vocab.LENS_SIGNALS

    # the persistent advisory synthesis banner is report chrome (above the tabs), not a lens block.
    banner = (_synthesis_banner_block(nomination, target_call)
              if spec.level_int >= vocab.TIER[vocab.SYNTHESIS_BANNER] else None)

    return ReportIR(target=target, indication=indication, spec=spec, header=header,
                    sections=sections, about=_about_block(spec), deciding_short=deciding_short,
                    overview=overview, banner=banner)


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
