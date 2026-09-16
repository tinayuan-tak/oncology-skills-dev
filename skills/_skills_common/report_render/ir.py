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

from .. import display_gloss as _dg  # plain-language readings (metric gloss + direction + card description)
from .. import field_descriptor as _fd  # per-field descriptor join (role/units/direction) for the evidence view
from ..risk_projection import AXIS_TO_DIM  # verdict-bearing subskill → risk dim crosswalk (the 6-dim spine)
from . import vocab
from .spec import SCOPE_ALL, SCOPE_GATING, ReportSpec, resolve_spec


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
    lens: Optional[str] = None  # faceted-view grouping; composed sections → vocab.LENS_SIGNALS


@dataclass
class ReportIR:
    target: Optional[str]
    indication: Optional[str]
    spec: ReportSpec
    header: Block  # REPORT_HEADER
    sections: list  # list[Section]
    about: Optional[Block]  # ABOUT | None
    deciding_short: Optional[str]
    overview: list = field(default_factory=list)  # report-level blocks (signals_overview, risk_6dim)
    banner: Optional[Block] = None  # SYNTHESIS_BANNER | None — persistent chrome above tabs

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
        for lens_id, items in buckets.items():  # any future lens not in LENS_ORDER, stably last
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
def _chip_with_rarity(chip: dict, short: Optional[str], indication: Optional[str]) -> dict:
    """A COPY of one claim chip carrying `signal_rarity` / `corroboration_rarity` where the frozen
    known-target cohort can discriminate, else the chip unchanged.

    ORDINAL COUNTERPART OF THE NUMERIC COHORT RULER: a gauged value gets "stronger than 82% of 210 known
    targets" from `cohort_percentile`; a ladder tier gets "61% of 293 known targets sit at this tier" from
    `archetype_core.claim_tier_rarity`. Enriching HERE, in the IR, is what keeps the backends dumb — the
    module contract above ("Backends walk this tree and emit syntax; they make no decisions") — and this is
    also the only layer that holds BOTH halves of the atlas key: `_build_section` knows the owning `short`,
    the chip knows its CLAIM. The spine's chips are NOT mutated (a copy per chip): the same skill_report is
    read by the scorecard, the LLM replay and the drift golden, and a display annotation must not appear in
    their inputs.

    VERDICT-INERT and SELF-GATING — `claim_tier_rarity` returns None for an absent/unmeasured tier, an
    unknown column, an under-powered cohort (n<20) or a column showing fewer tiers than
    USABLE_TIER_RARITY_DISTINCT. Measured reach on the shipped 297-target atlas: 80 of the 112 ladder
    columns can say something (::signal 53 of 56; ::corrob 27 of 56, since 26 corroboration columns are
    CONSTANT across the whole panel and would otherwise emit the identical sentence to every target).
    No exception handling: a missing/corrupt atlas is already swallowed by `_shipped_atlas_or_none`, and a
    try/except here would hide a broken environment behind a silently un-annotated chip."""
    if not isinstance(chip, dict) or not short or not chip.get("key"):
        return chip
    from ..archetype_core import claim_tier_rarity

    out = dict(chip)
    for field_name, ladder in (("signal", "signal"), ("corroboration", "corrob")):
        rarity = claim_tier_rarity(short, chip["key"], ladder, chip.get(field_name), indication=indication)
        if rarity:
            out[f"{field_name}_rarity"] = rarity
    return out


def _chips_block(
    report: dict, eff_level: int, short: Optional[str] = None, indication: Optional[str] = None
) -> Optional[Block]:
    chips = report.get("claim_chips") or []
    limit = vocab.CHIP_LIMIT_BY_LEVEL.get(eff_level, None)
    if limit == 0 or not chips:
        return None
    shown = chips if limit is None else chips[:limit]
    shown = [_chip_with_rarity(c, short, indication) for c in shown]
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
        out.append(
            Block(
                vocab.FIGURE,
                {
                    # NB: 'fig_kind' NOT 'kind' — 'kind' is reserved for the block kind and would shadow it
                    # when a backend serializes {kind, **payload} (enforced by test_no_payload_shadows_kind).
                    "slot": f.get("slot"),
                    "fig_kind": f.get("kind"),
                    "ref": f.get("path"),
                    "caption": cap,
                    "fallback_text": cap,
                    "show_image": show_image,
                },
            )
        )
    return out


def _unmeasured(slot: str) -> Block:
    return Block(vocab.UNMEASURED, {"slot": slot, "note": f"{slot.replace('_', ' ')}: not measured / not surfaced"})


# run-dir figure channel: card_figures descriptor `path` is relative to the run's figures/ dir, and the
# default target_profile.html/.md sit at the run root beside it — so a stable `figures/` prefix resolves
# for a browser/markdown viewer with NO file reads (backends stay dumb; ref is the final relative URL).
_FIGURE_BASE = "figures/"


def _card_figure_blocks(
    card_figs: list, eff_level: int, medium: str, polarity: Optional[str], role: Optional[str]
) -> list:
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
        svgs = [
            d
            for d in (descs or [])
            if isinstance(d, dict) and not d.get("dynamic") and str(d.get("path") or "").endswith(".svg")
        ]
        dyn = [d for d in (descs or []) if isinstance(d, dict) and d.get("dynamic")]
        if not svgs:
            continue
        svgs.sort(key=lambda d: 0 if d.get("primary") else 1)  # primary first, else stable
        selected = svgs if eff_level >= 3 else svgs[:1]
        for d in selected:
            cap = vocab.humanize_figure_type(d.get("type"), d.get("id"))
            ref = _FIGURE_BASE + str(d["path"]) if d.get("path") else None
            dref = next(
                (x.get("path") for x in dyn if x.get("id") == d.get("id")), (dyn[0].get("path") if dyn else None)
            )
            out.append(
                Block(
                    vocab.FIGURE,
                    {
                        # 'fig_kind' NOT 'kind' (reserved — see _figure_blocks / test_no_payload_shadows_kind).
                        "slot": None,
                        "fig_kind": d.get("type"),
                        "ref": ref,
                        "caption": cap,
                        "fallback_text": cap,
                        "show_image": show_image,
                        "card_id": card_id,
                        "primary": bool(d.get("primary")),
                        "status": status,
                        "dynamic_ref": (_FIGURE_BASE + str(dref)) if dref else None,
                    },
                )
            )
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
        for cid in sv.get("cards_used") or []:
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


def _build_section(
    short: str,
    report: dict,
    spec: ReportSpec,
    is_deciding: bool,
    card_figs: list = (),
    reconciled_shorts=frozenset(),
    target: Optional[str] = None,
    indication: Optional[str] = None,
    axis_not_applicable=frozenset(),
) -> Section:
    role = report.get("role") or ("gating" if short in vocab.GATING_SHORTS else "descriptive")
    eff = spec.level_int_for(short, is_deciding)

    # COMPOSED cross-axis reconciliation: a measured-negative CONTRADICTION the gate retired renders as
    # NEUTRAL (glyph •) with the raw polarity + note retained — reframed, never hidden — so the per-axis
    # header glyph + figure badge agree with the gate/scorecard/LLM. Empty set on the standalone path.
    # The #1203 biology-axis category-error mask (axis_not_applicable) de-escalates the same way.
    _recon_note = _reconciled_note(short, report.get("polarity"), reconciled_shorts) or _axis_not_applicable_note(
        short, report.get("polarity"), axis_not_applicable
    )
    _eff_polarity = "neutral" if _recon_note else report.get("polarity")

    # carried claim-graph (P3): rich embedded/standalone view + the standalone-dashboard header summary
    # (headline sentence + kv grid — the sandbox `.hdr`, bound to eg.verdict, verdict-inert display).
    eg = report.get("evidence_graph")
    eg_rich = isinstance(eg, dict) and bool(eg.get("questions"))

    header = Block(
        vocab.SKILL_HEADER,
        {
            "short": short,
            "title": vocab.skill_title(short),
            # target/indication for the sandbox `.hdr` h1 (`{TARGET} · {INDICATION}`); fall back to the
            # carried graph's own target/indication so the composed embedded sections also fill the h1.
            "target": target or (eg.get("target") if isinstance(eg, dict) else None),
            "indication": indication or (eg.get("indication") if isinstance(eg, dict) else None),
            "role": role,
            "call": report.get("call"),  # None for gateless — backend falls back to phrase
            "polarity": _eff_polarity,
            "raw_polarity": report.get("polarity") if _recon_note else None,
            "reconciled_note": _recon_note,
            "honest_phrase": report.get("honest_phrase"),
            "is_deciding": is_deciding,
            # the standalone-dashboard headline + kv (from the carried graph's collapsed verdict); None
            # when the skill carries no rich graph, so the backend degrades to the lean stitle/phrase.
            "graph": _skill_graph_header(eg, report.get("confidence")) if eg_rich else None,
        },
    )
    blocks = [header]

    # a question_table will render at L2+ when present; it restates the claim-chips, so suppress the
    # redundant chips block when the Q&A table shows (dedupe — one decision-useful view per card).
    has_qt = eff >= vocab.TIER[vocab.QUESTION_TABLE] and bool(report.get("question_table"))

    # L1: confidence, tension, claim chips. When the rich sandbox header renders (eg_rich), it already
    # carries the confidence (level + basis + coverage) and the tension in its kv grid — so the separate
    # CONFIDENCE / TENSION blocks are suppressed to avoid the duplicate loose lines under the header.
    if eff >= vocab.TIER[vocab.CONFIDENCE] and report.get("confidence") and not eg_rich:
        blocks.append(Block(vocab.CONFIDENCE, {"confidence": report["confidence"]}))
    if eff >= vocab.TIER[vocab.TENSION] and report.get("top_tension") and not eg_rich:
        blocks.append(Block(vocab.TENSION, {"tension": report["top_tension"]}))
    if eff >= vocab.TIER[vocab.CLAIM_CHIPS] and not has_qt:
        cb = _chips_block(report, eff, short, indication)
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
    # (eg / eg_rich computed above, before the header, for the header's graph summary.)
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
        blocks.extend(_card_figure_blocks(card_figs, eff, spec.medium, _eff_polarity, role))

    # L3: RICH embedded view (cont.) — per-card dataset→data→rule→verdict chains, then provenance
    if eg_rich and eff >= vocab.TIER[vocab.CARD_CHAIN]:
        cc = _card_chain_block(eg)
        if cc is not None:
            blocks.append(cc)
    # Stage-2 narrative: the single-lens grounded exec_bullets (from the graph's projected narrative —
    # an opt-in --synthesize trailer; absent → no block). Leads with the crisp bullets; rationale prose
    # is the demoted verbose read. Advisory / verdict-inert.
    if isinstance(eg, dict) and eff >= vocab.TIER[vocab.SYNTHESIS]:
        nb = _skill_synthesis_block(eg.get("narrative") or {}, eg.get("citations") or [])
        if nb is not None:
            blocks.append(nb)
    if eff >= vocab.TIER[vocab.PROVENANCE] and report.get("provenance"):
        blocks.append(Block(vocab.PROVENANCE, {"provenance": report["provenance"]}))

    return Section(short=short, title=vocab.skill_title(short), role=role, is_deciding=is_deciding, blocks=blocks)


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
    rank = vocab.polarity_rank(polarity)  # killer −3 … supportive +2; None off-scale
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


def _negative_expected_under_thesis(
    short: str, polarity: Optional[str], thesis_primary: Optional[str]
) -> Optional[str]:
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
    if rank is None or rank >= 0:  # only a measured-negative (opposing / killer) is reconciled
        return None
    if thesis_primary in _SURFACE_ANTIGEN_THESES:
        return "expected for a surface-antigen thesis — orthogonal to the ADC/TCE mechanism, not counted against"
    return None


_RECONCILED_NOTE = (
    "reconciled by a cross-axis signal (a co-present axis proves it is measured on the wrong basis) — "
    "not counted against"
)


def _reconciled_note(short: str, polarity: Optional[str], reconciled_shorts) -> Optional[str]:
    """A note when a gating axis's MEASURED-NEGATIVE was retired by the COMPOSED cross-axis reconciler
    (`target_call.gate.hard_gates` status == 'reconciled' — e.g. the selectivity no-window KILL reconciled
    by an ADC/TCE surface fit or an amp/biomarker-stratified dependency). Sibling to
    `_negative_expected_under_thesis`: it reuses the SAME neutral/raw_polarity de-escalation so the rendered
    ⛔/▽ glyph, the diverging-strip tally, and the scatter agree with the deterministic gate + the LLM.
    De-escalates a negative ONLY, never invents a positive. COMPOSED-ONLY: `reconciled_shorts` is empty on
    the standalone `build_ir_for_skill` path (which carries no gate), so standalone reports keep the honest
    ⛔. Returns None otherwise."""
    if short not in (reconciled_shorts or frozenset()):
        return None
    rank = vocab.polarity_rank(polarity)
    if rank is None or rank >= 0:  # only a measured-negative (opposing / killer) is reconciled
        return None
    return _RECONCILED_NOTE


_AXIS_NOT_APPLICABLE_NOTE = (
    "not applicable to this target's biology axis — its modality family is a category error (e.g. a "
    "surface/biologics axis on an intracellular target); not counted against"
)


def _axis_not_applicable_note(short, polarity, axis_not_applicable) -> Optional[str]:
    """A note when a gating axis is a CATEGORY ERROR for the target's curated biology axis — its whole
    modality-channel family is masked `not_applicable_by_axis` (the #1203 `build_skill_report_rollup`
    mask, e.g. surface_modality on an intracellular target). Sibling to `_reconciled_note`: SAME
    neutral/raw_polarity de-escalation, so the diverging-strip tally, the scatter, and the composed
    fingerprint stop counting a category-error `killer` as "against" — matching the rollup's
    `killer_axes` exclusion + the suppressed INV-6 `recommendation_exceeds_signals` flag. De-escalates a
    measured-negative ONLY (never invents a positive). COMPOSED-ONLY: `axis_not_applicable` is empty on
    the standalone path + on any run where the rollup masked nothing (byte-stable). Returns None otherwise."""
    if short not in (axis_not_applicable or frozenset()):
        return None
    rank = vocab.polarity_rank(polarity)
    if rank is None or rank >= 0:  # only a measured-negative (opposing / killer) is de-escalated
        return None
    return _AXIS_NOT_APPLICABLE_NOTE


def _evidence_signals_block(selected) -> Optional[Block]:
    """The salient MEASURED fields across the scored skills — the evidence itself, not a ranked verdict.

    One row per evidence card that carries a decisive reading. Relevance is the per-field salience role
    (SALIENCE_SPECS, surfaced via the Step-1 descriptor), so EVERY card's salient datum shows — nothing is
    picked, nothing is ranked into a single per-skill signal. Reuses the already-assembled readings on the
    spine's `evidence_graph.cards[]`: `_format_key_evidence` (the decisive datum: indication-stratum effect
    + q + omnibus + driving categorical) and the reference-frame ruler in words (`_dg.gauge_string`). The
    machine view additionally carries the structured descriptor for the measurement_type's effect field, so
    a programmatic reader gets (label, units, direction, role, significance_field) without prose-parsing.
    Verdict-inert + additive (○): this block adds the evidence view; it does not touch the verdict strip."""
    rows: list = []
    # roll-up over EVIDENCE, not verdicts (2c): how many cards carried a salient measured datum vs how many
    # were looked at but surfaced none — the count-based summary that replaces a polarity ranking. Per skill
    # and total, computed while iterating so it can never disagree with the rows.
    by_skill: dict = {}
    for short, report, _role in selected:
        eg = report.get("evidence_graph")
        if not isinstance(eg, dict):
            continue
        title = vocab.skill_title(short)
        for c in eg.get("cards") or []:
            ke = c.get("key_evidence")
            reading = _format_key_evidence(ke)
            interp = (ke or {}).get("interpretation") if isinstance(ke, dict) else None
            gauge = _dg.gauge_string(interp[0]) if interp else None
            tally = by_skill.setdefault(short, {"title": title, "measured": 0, "unmeasured": 0})
            if not (reading or gauge):
                tally["unmeasured"] += 1  # a card that was consulted but surfaced no decisive datum
                continue
            tally["measured"] += 1
            mt = c.get("measurement_type")
            # the structured descriptor for this measurement_type's EFFECT field (Step-1 join) — machine-side
            effect_desc = None
            if mt:
                effect_desc = next(
                    (d for d in _fd.descriptors_for(mt).values() if d.get("role") == _fd.ROLE_EFFECT), None
                )
            rows.append(
                {
                    "short": short,
                    "title": title,
                    "card_id": c.get("id"),
                    "measurement_type": mt,
                    "role": c.get("role"),
                    "reading": reading,  # the decisive datum in words (effect · q · omnibus · categorical)
                    "gauge": gauge,  # the lead reference-frame ruler in words (gauged value vs cut/cohort)
                    "n": (c.get("confidence") or {}).get("n"),
                    "measured": bool(reading or gauge),
                    "descriptor": effect_desc,  # structured (label/units/direction/role/significance_field) or None
                }
            )
    if not rows:
        return None
    rollup = {
        "n_measured": sum(t["measured"] for t in by_skill.values()),
        "n_unmeasured": sum(t["unmeasured"] for t in by_skill.values()),
        "n_skills": len(by_skill),
        "by_skill": by_skill,
    }
    return Block(vocab.EVIDENCE_SIGNALS, {"rows": rows, "rollup": rollup})


def _signals_overview_block(
    selected, deciding_short, thesis_primary=None, reconciled_shorts=frozenset(), axis_not_applicable=frozenset()
) -> Optional[Block]:
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
            descriptive.append(title)  # context, not a bar
            continue
        # thesis-expected OR composed-reconciled negative → same neutral/raw de-escalation (both reframe,
        # never hide). Composed reconciliation is dormant on standalone runs (reconciled_shorts empty).
        expected_note = (
            _negative_expected_under_thesis(short, polarity, thesis_primary)
            or _reconciled_note(short, polarity, reconciled_shorts)
            or _axis_not_applicable_note(short, polarity, axis_not_applicable)
        )
        prov = report.get("provenance") if isinstance(report.get("provenance"), dict) else {}
        rows.append(
            {
                "short": short,
                "title": title,
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
                "is_deciding": short == deciding_short,
            }
        )
    if not rows:
        return None
    return Block(
        vocab.SIGNALS_OVERVIEW,
        {
            "rows": rows,
            "descriptive": descriptive,
            "counts": {
                "support": sum(1 for r in rows if (r["level"] or 0) > 0),
                "neutral": sum(1 for r in rows if r["level"] == 0),
                "against": sum(1 for r in rows if (r["level"] or 0) < 0),
            },
            "deciding_short": deciding_short,
        },
    )


_RISK6_ORDER = ("biological", "druggability", "safety", "translational", "clinical", "commercial")
# ENGINE-BLIND is deliberately OFF-SCALE (→ None), never rank 0: "not evidenced" is a coverage gap,
# not the lowest risk (same measured-vs-null discipline as ordinal_view's off-scale signals).
_RISK6_RANK = {"HIGH": 3, "MED": 2, "MEDIUM": 2, "LOW": 1}

# The GATELESS "context" subskills (verdict-inert / descriptive) → the dim they annotate. AXIS_TO_DIM
# carries the verdict-BEARING subskills (whose bin the deterministic engine sets); these are the
# additional descriptive companions the assessment spine shows under each dimension, tagged `context`.
# Placement matches the approved redesign-v6 mockup (#v-assess).
_CONTEXT_DIM = {
    "cis_coherence": "biological",
    "combination_vulnerability": "biological",
    "target_intrinsic": "druggability",
    # immune_context is the TCE effector-arm companion to surface-modality-fit → DRUGGABILITY (not
    # clinical): it sits beside the surface/biologics modality call, not the clinical-precedent bin.
    "immune_context": "druggability",
    "translational_readiness": "translational",
    "literature_context": "commercial",
}


def _sentences(text: str, n: int) -> str:
    """First `n` sentences of a prose rationale, split on sentence-final punctuation followed by a
    space + capital (so decimals like `0.23` and `q=1e-10` don't split). Fail-soft: returns the whole
    stripped string when it has < n sentences."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text.strip())
    joined = " ".join(parts[:n]).strip()
    return joined or text.strip()


def _dim_member_reading(report: Any) -> tuple:
    """A rich plain-language reading for a dim member. Prefers the subskill's evidence_graph narrative
    rationale (real prose with the anchoring numbers), then its plain-language `honest_phrase`. Returns
    (reading, is_fallback); reading is None when neither exists → the caller falls back to the class
    label. NEVER fabricates — only real fields off the subskill's own report."""
    if not isinstance(report, dict):
        return None, True
    eg = report.get("evidence_graph")
    nar = eg.get("narrative") if isinstance(eg, dict) else None
    rat = nar.get("rationale") if isinstance(nar, dict) else None
    if isinstance(rat, str) and rat.strip():
        return _sentences(rat, 2), False
    hp = report.get("honest_phrase")
    if isinstance(hp, str) and hp.strip():
        return hp.strip(), False
    return None, True


def _risk_6dim_block(
    risk_6dim, skill_reports: Optional[dict] = None, risk_assessment: Optional[dict] = None
) -> Optional[Block]:
    """The deterministic 6-category risk rollup → {dims:[{dim,bin,rank,members,literature,…}]}.

    Reads target_report.risk_6dim ({dim:{bin,chain,…}} or a list); fail-soft on shape. 'rank' None =
    engine-blind / unrecognized bin. When the composed `skill_reports` are supplied, each dimension
    enumerates its FULL member set — every verdict-bearing subskill whose AXIS_TO_DIM maps to it, PLUS
    the gateless `context` companions (_CONTEXT_DIM) — each with a rich plain-language `read` (off the
    subskill's own evidence_graph, never fabricated) and a `dashboard` same-page anchor (`#skill-<short>`)
    into the inlined subskill dashboard on the composed page. Dims whose bin is card-driven (clinical/commercial) also
    surface their chain driver. `literature` is the verdict-inert per-dim text-mined line (risk_assessment).
    Without skill_reports (a bare unit call) the members fall back to the chain [source, read, level]."""
    if not risk_6dim:
        return None
    skill_reports = skill_reports if isinstance(skill_reports, dict) else {}
    ra_dims = (risk_assessment or {}).get("dimensions") if isinstance(risk_assessment, dict) else None
    ra_dims = ra_dims if isinstance(ra_dims, dict) else {}
    dims = []

    def _member(short: str, context: bool) -> dict:
        rep = skill_reports.get(short)
        read, fell_back = _dim_member_reading(rep)
        if read is None:
            read = str((rep or {}).get("call") or short)  # class-label fallback (no prose available)
            fell_back = True
        return {
            "short": short,
            "skill_dir": vocab.skill_dir_for_short(short),
            "read": read,
            "context": context,
            "spark": None,  # display-only; populated only when a numeric distribution is already in-data
            # EXTERNAL deep-link to the standalone `subskills/{short}/dashboard.html` page the
            # --full-package run emits (tp_manifest writes it under subskills/<short>/). The composed HTML
            # no longer inlines per-subskill dashboards, so the old same-page `#skill-{short}` anchors have
            # no target — the `full ↗` link opens the standalone page instead.
            "dashboard": f"subskills/{short}/dashboard.html",
            "fallback": fell_back,
        }

    def _dim_members(dim: str, v) -> list:
        # verdict-bearing (AXIS_TO_DIM) + gateless context companions, present-only, canonical order.
        out = []
        axis = sorted((s for s, dd in AXIS_TO_DIM.items() if dd == dim), key=vocab.skill_order_index)
        ctx = sorted((s for s, dd in _CONTEXT_DIM.items() if dd == dim), key=vocab.skill_order_index)
        for short in axis:
            if short in skill_reports:
                out.append(_member(short, context=False))
        # card-driven dims (clinical/commercial) have no verdict-bearing subskill report — surface the
        # chain driver (clinical-precedent / competitor-landscape) that actually set the bin as a member.
        if not any(not m["context"] for m in out) and isinstance(v, dict):
            for entry in v.get("chain") or []:
                if isinstance(entry, (list, tuple)) and entry:
                    out.append(
                        {
                            "short": str(entry[0]),
                            "skill_dir": None,
                            "read": str(entry[1]) if len(entry) > 1 else "",
                            "context": False,
                            "spark": None,
                            "dashboard": None,  # not a fan-out subskill → no standalone page
                            "fallback": False,
                        }
                    )
        for short in ctx:
            if short in skill_reports:
                out.append(_member(short, context=True))
        # bare unit call (no skill_reports): fall back to the chain [source, read, level] members.
        if not out and isinstance(v, dict):
            for entry in v.get("chain") or []:
                if isinstance(entry, (list, tuple)) and entry:
                    out.append(
                        {
                            "short": str(entry[0]),
                            "skill_dir": None,
                            "read": str(entry[1]) if len(entry) > 1 else "",
                            "context": False,
                            "spark": None,
                            "dashboard": None,
                            "fallback": False,
                            "level": entry[2] if len(entry) > 2 else None,
                        }
                    )
        return out

    def _literature(dim: str) -> Optional[dict]:
        rad = ra_dims.get(dim)
        if not isinstance(rad, dict):
            return None
        interp = rad.get("interpretation")
        if not (isinstance(interp, str) and interp.strip()):
            return None
        pmids = rad.get("cited_pmids") or rad.get("pmids") or []
        return {"interpretation": interp.strip(), "pmids": [str(p) for p in pmids][:6]}

    def _emit(dim, v):
        b = str(v.get("bin") or "") if isinstance(v, dict) else (v if isinstance(v, str) else "")
        blind_spots, mitigation, grounded = [], None, []
        if isinstance(v, dict):
            blind_spots = v.get("blind_spots") or []
            mitigation = v.get("mitigation")
            # dimension-level literature `grounded_findings` (e.g. the MACRO prognostic study on the
            # engine-blind translational dim) — surfaced honestly even when no deterministic bin exists.
            for f in v.get("grounded_findings") or []:
                if isinstance(f, dict) and (f.get("finding") or "").strip():
                    grounded.append(
                        {
                            "finding": str(f.get("finding")).strip(),
                            "kind": (str(f.get("kind")).strip() if f.get("kind") else None),
                            "severity": (str(f.get("severity")).strip() if f.get("severity") else None),
                            "pmids": [str(p) for p in (f.get("cited_pmids") or f.get("pmids") or [])][:6],
                        }
                    )
        b_up = b.upper()
        dims.append(
            {
                "dim": dim,
                "bin": b or None,
                "rank": _RISK6_RANK.get(b_up),
                # ENGINE-BLIND (empty deterministic chain / unrouted bin): honest gap, not a low score.
                "engine_blind": b_up in ("", "ENGINE-BLIND", "ENGINE_BLIND", "BLIND", "UNROUTED"),
                "members": _dim_members(dim, v),
                "literature": _literature(dim),
                "grounded_findings": grounded,
                # #992: non-mutating literature-discordance flag (a HIGH-severity indication-scoped finding
                # contradicts this deterministic bin). The bin/rank/level are UNCHANGED — this only lets the
                # renderer surface the discordance on the dim header instead of burying it in the detail.
                "engine_literature_discordance": bool(v.get("engine_literature_discordance")),
                "blind_spots": blind_spots,
                "mitigation": mitigation,
            }
        )

    if isinstance(risk_6dim, dict):
        seen = set()
        for d in _RISK6_ORDER:
            if d in risk_6dim:
                _emit(d, risk_6dim[d])
                seen.add(d)
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
    clean = re.sub(r"\s+([.,;:)])", r"\1", clean)  # tidy the space a removed citation left before punctuation
    clean = re.sub(r"\(\s+", "(", clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    seen, ordered = set(), []
    for r in found:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return clean, ordered


def _cross_evidence_summary(nomination: dict) -> Optional[dict]:
    """Compact cross-evidence-hypothesis read for the convergence layer: the causal chain (edges),
    the integrator's independent verdict + certainty, and its defensibility (clause traceability).
    VERDICT-INERT — an independent second read surfaced beside the spine's, never reconciled into it.
    None when --no-hypothesis / offline (nomination['hypothesis'] absent)."""
    hyp = nomination.get("hypothesis")
    if not isinstance(hyp, dict) or not hyp:
        return None
    chain = [
        {"from": e.get("from_dimension"), "to": e.get("to_dimension"), "type": e.get("type")}
        for e in (hyp.get("edges") or [])
        if isinstance(e, dict) and e.get("from_dimension") and e.get("to_dimension")
    ]
    verdict = (hyp.get("verdict") or {}).get("computed") or (hyp.get("verdict") or {}).get("proposed_by_agent")
    unc = hyp.get("uncertainty") or {}
    dfn = hyp.get("defensibility") or {}
    if not (chain or verdict):
        return None
    traceable = f"{dfn.get('n_fully_traceable')}/{dfn.get('n_clauses')}" if dfn.get("n_clauses") is not None else None
    return {
        "chain": chain[:6],
        "verdict": verdict,
        "certainty": unc.get("overall_certainty"),
        "limiting": unc.get("limiting_dimension"),
        "traceable": traceable,
        "coherence_violations": dfn.get("n_coherence_violations"),
    }


def _synthesis_block(nomination: dict, literature: Optional[dict] = None) -> Optional[Block]:
    """The LLM narrative (advisory / verdict-inert): executive summary + tension analysis + top
    arguments. Sourced from `llm_synthesis` (else the legacy `llm_output`). Inline rule-id citations are
    stripped from the prose into `citations` (a provenance affordance the backends render collapsed).
    `literature` = the cited co-mention summary the v6 convergence litctx renders (verdict-inert)."""
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
    cross_evidence = _cross_evidence_summary(nomination)  # convergence layer: cross-evidence causal chain + divergence
    if not (exec_bullets or exec_summary or tension or args or verbose or cross_evidence):
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
    return Block(
        vocab.SYNTHESIS,
        {
            "exec_bullets": exec_bullets,
            "executive_summary": exec_clean,
            "tension_analysis": tens_clean,
            "arguments": args_out,
            "citations": citations,
            "cross_evidence": cross_evidence,
            "literature": literature,
            "mode": "convergence",  # COMPOSED report → v6 convergence layout (see html._synthesis)
        },
    )


def _skill_synthesis_block(narrative: dict, citations: Optional[list] = None) -> Optional[Block]:
    """Build a SYNTHESIS block from a single-skill graph `narrative` (evidence_graph.narrative) — the
    Stage-2 exec_bullets lead + the demoted verbose prose (rationale). None when the narrative is empty
    (no --synthesize). Reuses the SYNTHESIS backends (same as the composed report).

    `citations` = the graph's citation registry (evidence_graph.citations). Each bullet's
    `cites.citation_ids` that resolve to a real citation carrying a PMID are projected onto the bullet
    as `resolved_citations` [{id,label,pmid,verified}] so the backend can render the PMID(s) inline as
    cite-pills — the exec_bullets then WEAVE + CITE the literature lane. Verdict-inert / display-only."""
    if not isinstance(narrative, dict):
        return None
    cites_by_id = {c.get("id"): c for c in (citations or []) if isinstance(c, dict)}
    bullets = []
    for b in narrative.get("exec_bullets") or []:
        if not (isinstance(b, dict) and b.get("text")):
            continue
        cid_list = ((b.get("cites") or {}).get("citation_ids")) or []
        resolved = []
        for cid in cid_list:
            c = cites_by_id.get(cid)
            if isinstance(c, dict) and c.get("pmid"):
                resolved.append(
                    {"id": cid, "label": c.get("label"), "pmid": c.get("pmid"), "verified": bool(c.get("verified"))}
                )
        if resolved:
            b = {**b, "resolved_citations": resolved}
        bullets.append(b)
    verbose = narrative.get("rationale") or narrative.get("relevance")
    if not (bullets or verbose):
        return None
    verbose_clean, cites = _strip_rule_citations(verbose) if verbose else (None, [])
    return Block(
        vocab.SYNTHESIS,
        {
            "exec_bullets": bullets,
            "executive_summary": verbose_clean,
            "tension_analysis": None,
            "arguments": None,
            "citations": cites,
            "mode": "bullets",  # STANDALONE subskill → sandbox two-tone bullets (see html._synthesis)
        },
    )


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
    "small_molecule": "Small molecule",
    "degrader": "Degrader",
    "biologics": "Biologic (generic)",
    "adc": "ADC",
    "bite_tce": "T-cell engager (TCE)",
    "antibody": "Antibody",
}
_CHANNEL_ORDER = ["small_molecule", "degrader", "biologics", "adc", "bite_tce", "antibody"]
# per-channel fit → display rank (viable first) + status token (mapped to the reserved status palette).
_FIT_RANK = {"favorable": 0, "viable": 0, "conditional": 1, "unfavorable": 2}
_FIT_STATUS = {
    "favorable": ("viable", "Viable"),
    "viable": ("viable", "Viable"),
    "conditional": ("conditional", "Conditional"),
    "unfavorable": ("unfavorable", "Unfavorable"),
}


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
        row = {
            "channel": ch,
            "name": _CHANNEL_LABEL.get(ch, ch.replace("_", " ").title()),
            "limiting_axis": d.get("limiting_axis"),
            "by_axis": d.get("by_axis") if isinstance(d.get("by_axis"), dict) else {},
            "masked_by_axis": masked_by,
        }
        if fit in ("not_applicable_by_axis", "not_applicable", None) or masked_by:
            row["status"], row["label"] = "not_applicable", "Not applicable"
            masked.append(row)
        else:
            row["status"], row["label"] = _FIT_STATUS.get(fit, ("unfavorable", _humanize_local(fit)))
            row["_rank"] = _FIT_RANK.get(fit, 3)
            applic.append(row)
    applic.sort(
        key=lambda r: (r.get("_rank", 3), _CHANNEL_ORDER.index(r["channel"]) if r["channel"] in _CHANNEL_ORDER else 99)
    )
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
    return Block(
        vocab.MODALITY_MATRIX,
        {
            "channels": channels,  # the lead: per-modality status readout
            "columns": columns,
            "rows": grid_rows,  # the raw ordinal grid → drill-down
            "legend": (mtx or {}).get("legend") or {},
            "glyph_legend": vocab.ordinal_glyph_legend(),
            "disclaimer": (mtx or {}).get("_disclaimer"),
        },
    )


def _literature_risk_block(nomination: dict, tr: dict) -> Optional[Block]:
    """Literature × omics coherence: the deep-research literature 6-dim risk (risk_assessment) beside
    the deterministic omics 6-dim (risk_6dim), per dimension, with an agreement read. Both are on the
    SAME six dims; coherence is the literature-risk skill's own `contradicts_deterministic` when present,
    else a bin-vs-grade comparison. Literature is CONTEXT, never a gate."""
    ra = nomination.get("risk_assessment") or tr.get("literature_risk") or {}
    dims = ra.get("dimensions") if isinstance(ra, dict) else None
    if not isinstance(dims, dict) or not dims:
        return None
    r6 = tr.get("risk_6dim") if isinstance(tr.get("risk_6dim"), dict) else {}

    def _omics_bin(dim):
        v = r6.get(dim)
        return (v.get("bin") if isinstance(v, dict) else None) or None

    def _coherence(dim, lit_level, contradicts):
        ob = (_omics_bin(dim) or "").upper()
        ll = (lit_level or "").upper()
        if contradicts:
            return "contradicts"
        if not ll or ll == "NOT_ASSESSED":
            return "omics-only" if ob and ob != "ENGINE-BLIND" else "—"
        if not ob or ob == "ENGINE-BLIND":
            return "literature-only"
        return "agree" if ob == ll else "grade-divergence"

    rows = [
        {
            "dim": d,
            "omics_bin": _omics_bin(d),
            "risk_level": v.get("risk_level"),
            "interpretation": v.get("interpretation"),
            "pmids": v.get("cited_pmids") or v.get("pmids") or [],
            "coherence": _coherence(d, v.get("risk_level"), v.get("contradicts_deterministic")),
        }
        for d, v in dims.items()
        if isinstance(v, dict)
    ]
    return Block(vocab.LITERATURE_RISK, {"dims": rows}) if rows else None


def _deciding_axis_block(target_call: dict, nomination: dict, deciding_short) -> Optional[Block]:
    da = (target_call or {}).get("deciding_axis") or nomination.get("deciding_axis")
    if not isinstance(da, dict) or not da:
        return None
    axis_titles = [
        vocab.skill_title(a["short"]) for a in (da.get("deciding_axes") or []) if isinstance(a, dict) and a.get("short")
    ]
    primary = vocab.skill_title(deciding_short) if deciding_short else (axis_titles[0] if axis_titles else None)
    return Block(
        vocab.DECIDING_AXIS,
        {
            "short": deciding_short,
            "title": primary,
            "axes": axis_titles,
            "routing": da.get("routing"),
            "basis": da.get("basis"),
        },
    )


# map the flip_condition `to_role` prefix → a plain-language direction word.
_FLIP_DIRECTION = {
    "kill": "would kill the call",
    "veto": "would kill the call",
    "neutral": "would neutralize the axis",
    "positive": "would strengthen the call",
    "negative": "would weaken the call",
}
# curation priority: what the call RESTS ON, then the ADVERSE flips (kill > neutralize > weaken),
# then the upside (strengthen). The resolver enumerates every reachable verdict, so an axis like
# dependency can emit ~10 recommendation-flips — a full dump is noise, not a decision aid.
_FLIP_DIR_PRIORITY = {
    "would kill the call": 1,
    "would neutralize the axis": 2,
    "would weaken the call": 3,
    "would strengthen the call": 4,
}
_FLIP_MAX_PER_AXIS = 2
_FLIP_MAX_TOTAL = 6


def _flip_conditions_block(nomination: dict) -> Optional[Block]:
    """ "What would change the call" — the recommendation-FLIPPING counterfactuals per axis, read from
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
        for fc in ax.get("flip_conditions") or []:
            if not isinstance(fc, dict) or not fc.get("recommendation_flip"):
                continue
            direction = _FLIP_DIRECTION.get(str(fc.get("to_role") or "").split(":")[0])
            row = {
                "axis": title,
                "to_verdict": fc.get("to_verdict"),
                "present": bool(fc.get("present")),
                "direction": direction,
                "condition": fc.get("rule_id"),
            }
            key = (title, direction)
            cur = reps.get(key)
            if cur is None:
                if title not in axis_order:
                    axis_order.append(title)
                reps[key] = row
            elif row["present"] and not cur["present"]:
                reps[key] = row  # promote the load-bearing representative for this direction
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
    return Block(
        vocab.SUBTYPE,
        {
            "verdict": verdict,
            "n_evaluated": n_eval,
            "axes_available": sc.get("axes_available") or [],
            "convergent_subtypes": sc.get("convergent_subtypes") or [],
            "associated_subtypes": sc.get("associated_subtypes") or [],
            "subtypes": list(per_subtype.keys()),
        },
    )


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
    for h in bm.get("biomarker_hypotheses") or []:
        if isinstance(h, dict) and h.get("intended_use"):
            hyps.append(
                {
                    "intended_use": h.get("intended_use"),
                    "basis": h.get("basis"),
                    "evidence_strength": h.get("evidence_strength"),
                }
            )
    return Block(
        vocab.BIOMARKER,
        {
            "verdict": bm.get("verdict"),
            "preferred_assay": bm.get("preferred_assay"),
            "alteration_role": corr.get("alteration_role"),
            "mutation_stratification": strat.get("mutation_stratification_class"),
            "subtype_stratification": strat.get("subtype_stratification_class"),
            "survival_association": strat.get("survival_association_class"),
            "rna_as_biomarker": strat.get("rna_as_biomarker"),
            "intended_uses": bm.get("intended_uses") or [],
            "hypotheses": hyps,
        },
    )


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
    items = sorted(
        ((k, v) for k, v in mix.items() if isinstance(v, (int, float)) and v >= 0.08), key=lambda kv: -kv[1]
    )[:3]
    if not items:
        return None
    # nearest archetype analogs (the "what is this LIKE" anchor): nearest_analogs is distance-sorted
    # with the target's own (target, indication) as the self-anchor at [0] — skip it, surface the next
    # few real analogs. Verdict-inert context, like the mixture.
    analogs = []
    for a in (arche.get("nearest_analogs") or [])[1:4]:
        if isinstance(a, dict) and a.get("target"):
            dist = a.get("distance")
            analogs.append(
                {
                    "target": a.get("target"),
                    "indication": a.get("indication"),
                    "archetype": a.get("archetype_label"),
                    "distance": round(float(dist), 2)
                    if isinstance(dist, (int, float)) and not isinstance(dist, bool)
                    else None,
                }
            )
    # soft-membership bars (v6 archetype fold): ALL phenotype components (label + weight), sorted, so the
    # fold can draw one bar per class — distinct from `mixture` (which is the ≥8% header lead only).
    membership = [
        {"label": _PHENOTYPE_LABEL.get(k, str(k).replace("_", " ")), "weight": round(float(v), 2)}
        for k, v in sorted(
            ((k, v) for k, v in mix.items() if isinstance(v, (int, float)) and not isinstance(v, bool)),
            key=lambda kv: -kv[1],
        )
    ]
    return {
        "mixture": [
            {"label": _PHENOTYPE_LABEL.get(k, str(k).replace("_", " ")), "weight": round(float(v), 2)} for k, v in items
        ],
        "membership": membership,
        "analogs": analogs,
    }


# =================================================================================================
# faceted-rollup builders (PR2): the signals-first spine one level up + the embedded sub-skill view.
# =================================================================================================
_TIER_ORDINAL = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0}  # subgroup signal tier → y
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
    return Block(
        vocab.SYNTHESIS_BANNER,
        {"executive_summary": exec_clean, "citations": cites, "n_rules": len(cites), "mismatch": mismatch},
    )


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
        for r in list(prov.get("fired_rule_ids") or []) + (
            [prov["driving_rule_id"]] if prov.get("driving_rule_id") else []
        ):
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
    for a in _llm_val(llm, "top_arguments_for") or []:
        if isinstance(a, str):
            sentences.append(("for", a))
    for a in _llm_val(llm, "top_arguments_against") or []:
        if isinstance(a, str):
            sentences.append(("against", a))
    tension = _llm_val(llm, "tension_analysis")
    if isinstance(tension, str) and tension:
        sentences.append(("tension", tension))

    by_lens: dict = {}
    for stance, text in sentences:
        lens = _lens_for(text)
        if lens == vocab.LENS_DECISION:
            continue  # covered by the consolidated SYNTHESIS block already
        clean, _ = _strip_rule_citations(text)
        by_lens.setdefault(lens, []).append({"stance": stance, "text": clean})
    blocks = []
    for lens in vocab.LENS_ORDER:
        notes = by_lens.get(lens)
        if notes:
            b = Block(vocab.SYNTHESIS_NOTE, {"notes": notes})
            b.lens = lens  # pre-lensed; build_ir preserves an already-set lens
            blocks.append(b)
    return blocks


def _signals_scatter_block(
    selected, deciding_short, reconciled_shorts=frozenset(), axis_not_applicable=frozenset()
) -> Optional[Block]:
    """Report-level signal × confidence scatter — one point per SCORED gating skill. Position is honest:
    x = confidence (low/moderate/high), y = signal STRENGTH tier; DIRECTION (supports vs against vs killer)
    is carried by colour + glyph (CVD-safe: position is strength, not direction). Leads the Signals lens,
    complementing the diverging strip (which shows the full signed ordinal)."""
    pts = []
    for short, report, role in selected:
        polarity = report.get("polarity")
        if role != "gating" or polarity in (None, "not_scored"):
            continue
        # composed-reconciled measured-negative → neutral dot (raw retained), consistent with the header
        # glyph + diverging strip. Dormant on standalone (reconciled_shorts empty).
        _recon_note = _reconciled_note(short, polarity, reconciled_shorts) or _axis_not_applicable_note(
            short, polarity, axis_not_applicable
        )
        _raw_polarity = polarity if _recon_note else None
        if _recon_note:
            polarity = "neutral"
        rank = vocab.polarity_rank(polarity)
        strength = "strong" if abs(rank or 0) >= 2 else "weak" if abs(rank or 0) == 1 else "absent"
        pts.append(
            {
                "short": short,
                "title": vocab.skill_title(short),
                "polarity": polarity,
                "raw_polarity": _raw_polarity,
                "reconciled_note": _recon_note,
                "signal_tier": strength,
                "signal_y": _TIER_ORDINAL[strength],
                "confidence_x": _confidence_ordinal(report.get("confidence")),
                "confidence": _confidence_level(report.get("confidence")),
                "honest_phrase": report.get("honest_phrase"),
                "is_deciding": short == deciding_short,
            }
        )
    if not pts:
        return None
    return Block(
        vocab.SIGNALS_SCATTER,
        {
            "scope": "skills",
            "points": pts,
            "deciding_short": deciding_short,
            "y_ticks": ["absent", "weak", "strong"],
            "x_ticks": ["low", "moderate", "high"],
            "y_label": "signal strength",
            "x_label": "confidence",
        },
    )


def _composed_fingerprint_block(
    tr: dict, reconciled_shorts=frozenset(), axis_not_applicable=frozenset()
) -> Optional[Block]:
    """The composed at-a-glance grid — the FIRST renderer of the composed_evidence_graph index
    (target_report.evidence_graph, #1068). A PURE PROJECTION of that index: the whole decision as a
    lens-grouped skill grid (each skill's call/polarity/confidence + a deciding badge + a literature-
    consistency dot), the verdict node, and the honest dissent counterpoint. Leads the Decision lens so
    one glance shows where the call is carried and where the tension lives — the composed analog of the
    per-subskill EVIDENCE_FINGERPRINT.

    Reads ONLY the index (recomputes nothing) so it is display-only/verdict-inert; returns None when the
    index is absent (an old nomination or a run before #1068), keeping standalone + pre-index reports
    byte-stable. The per-lens modality/risk/subtype edges are deliberately NOT re-rendered here — those
    stay in their own lens blocks (MODALITY_MATRIX / RISK_6DIM / SUBTYPE); this block owns the skill×lens
    map + dissent."""
    eg = tr.get("evidence_graph")
    if not isinstance(eg, dict) or eg.get("schema") != "composed_evidence_graph.v1":
        return None
    skills = [s for s in (eg.get("skills") or []) if isinstance(s, dict) and s.get("short")]
    if not skills:
        return None

    # group each skill node under its topical lens, then emit lanes in canonical LENS_ORDER (unknown-lens
    # nodes trail in a stable bucket). Within a lane: deciding axis first, then alpha by short.
    by_lens: dict = {}
    for s in skills:
        # composed-reconciled measured-negative → neutral (raw retained), consistent with the header glyph /
        # strip / scatter. This grid reads the evidence-graph index polarity (a distinct source), so it needs
        # its own de-escalation. Dormant on standalone (reconciled_shorts empty).
        _recon_note = _reconciled_note(
            s.get("short"), s.get("polarity"), reconciled_shorts
        ) or _axis_not_applicable_note(s.get("short"), s.get("polarity"), axis_not_applicable)
        by_lens.setdefault(s.get("lens") or "_other", []).append(
            {
                "short": s.get("short"),
                "title": vocab.skill_title(s.get("short")),
                "call": s.get("call"),
                "polarity": "neutral" if _recon_note else s.get("polarity"),
                "raw_polarity": s.get("polarity") if _recon_note else None,
                "reconciled_note": _recon_note,
                "confidence": s.get("confidence"),
                "deciding": bool(s.get("deciding")),
                "literature_consistency": s.get("literature_consistency"),
            }
        )
    lanes = []
    for lens in list(vocab.LENS_ORDER) + [l for l in sorted(by_lens) if l not in vocab.LENS_ORDER]:
        rows = by_lens.get(lens)
        if not rows:
            continue
        rows.sort(key=lambda r: (not r["deciding"], r["short"] or ""))
        lanes.append(
            {"lens": lens, "title": vocab.LENS_TITLE.get(lens, str(lens).replace("_", " ").title()), "skills": rows}
        )

    verdict = eg.get("verdict") if isinstance(eg.get("verdict"), dict) else {}
    conf = verdict.get("confidence") if isinstance(verdict.get("confidence"), dict) else {}
    dissent = [
        {"source": e.get("from"), "note": e.get("note"), "resolved_to": e.get("resolved_to")}
        for e in (eg.get("edges") or [])
        if isinstance(e, dict) and e.get("type") == "dissent"
    ]
    return Block(
        vocab.COMPOSED_FINGERPRINT,
        {
            "verdict": {
                "recommendation": verdict.get("recommendation"),
                "confidence": conf.get("level"),
                "deciding_shorts": verdict.get("deciding_shorts") or [],
            },
            "lanes": lanes,
            "dissent": dissent,
            "n_skills": len(skills),
        },
    )


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
        pts.append(
            {
                "name": str(sg_id).replace("_", " "),
                "signal_tier": tier,
                "signal_y": _TIER_ORDINAL.get(tier, 0),
                "confidence_x": _CONF_ORDINAL.get(str(d.get("confidence") or "").lower()),
                "confidence": d.get("confidence"),
                "conflict": bool(d.get("conflict")),
                "n_sources": d.get("n_sources"),
            }
        )
    if not pts:
        return None
    return Block(
        vocab.SIGNALS_SCATTER,
        {
            "scope": "subgroups",
            "points": pts,
            "y_ticks": ["absent", "weak", "moderate", "strong"],
            "x_ticks": ["low", "moderate", "high"],
            "y_label": "signal",
            "x_label": "confidence",
        },
    )


def _subgroup_bands_block(subgroup_signals: dict) -> Optional[Block]:
    """Per-skill hierarchy sub-group bands: one row per sub-group with its signal tier, confidence,
    source count + agreement, power and conflict flag (a direct projection of derive_subgroups output)."""
    if not isinstance(subgroup_signals, dict) or not subgroup_signals:
        return None
    rows = []
    for sg_id, d in subgroup_signals.items():
        if not isinstance(d, dict):
            continue
        rows.append(
            {
                "name": str(sg_id).replace("_", " "),
                "signal": d.get("signal"),
                "confidence": d.get("confidence"),
                "n_sources": d.get("n_sources"),
                "n_agree": d.get("n_agree"),
                "power": d.get("power"),
                "conflict": bool(d.get("conflict")),
            }
        )
    return Block(vocab.SUBGROUP_BANDS, {"sub_groups": rows}) if rows else None


# --------------------------------------------------------------------------------------------------
# evidence-graph blocks (P3) — the RICH embedded sub-skill view, projected from the carried
# skill_report.evidence_graph. Pure projections (no re-derivation); opacity/ordinal live in the backend.
# --------------------------------------------------------------------------------------------------
def _skill_graph_header(eg: dict, report_confidence: Optional[dict] = None) -> Optional[dict]:
    """Compact header summary from a skill's `evidence_graph.verdict` — the standalone-dashboard
    headline sentence + kv-grid inputs: the collapsed call/polarity/driving-rule, the confidence level +
    coverage, the top tension, and the question/card counts. A PURE PROJECTION of the carried graph
    (recomputes nothing); every field degrades to None when the verdict omits it. Verdict-inert display."""
    if not isinstance(eg, dict):
        return None
    from .backends.text import _gloss_basis  # local: the confidence-basis gloss lives with the text backend

    v = eg.get("verdict") if isinstance(eg.get("verdict"), dict) else {}
    conf = v.get("confidence") if isinstance(v.get("confidence"), dict) else {}
    cov = conf.get("coverage") if isinstance(conf.get("coverage"), dict) else {}
    tension = v.get("top_tension") if isinstance(v.get("top_tension"), dict) else {}
    return {
        "call": v.get("call") or v.get("id"),
        "polarity": v.get("polarity"),
        "driving_rule_id": v.get("driving_rule_id"),
        "confidence_level": conf.get("level"),
        # basis lives on the skill_report's confidence (not always on the graph verdict's) — fall back to it
        "confidence_basis": _gloss_basis(conf.get("basis") or (report_confidence or {}).get("basis")),
        "coverage": {
            "n_measured": cov.get("n_measured"),
            "n_axes": cov.get("n_axes"),
            "n_critical_measured": cov.get("n_critical_measured"),
        },
        "top_tension": (
            {"text": tension.get("text"), "severity": tension.get("severity")} if tension.get("text") else None
        ),
        "n_questions": len(eg.get("questions") or []),
        "n_cards": len(eg.get("cards") or []),
    }


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
        for cid in q.get("card_ids") or []:
            c = cards_by_id.get(cid) or {}
            sig = c.get("signal") or {}
            cells.append(
                {
                    "card_id": cid,
                    "polarity": sig.get("polarity"),
                    "liability": bool(sig.get("liability")),
                    "dots": (c.get("confidence") or {}).get("dots"),
                    "label": sig.get("label") or (c.get("class") or {}).get("value"),
                }
            )
        lit = None
        for ax_id in q.get("literature_axis_ids") or []:
            a = axes_by_id.get(ax_id)
            if a:
                lit = {
                    "axis_id": ax_id,
                    "read": a.get("read"),
                    "agreement": a.get("agreement_vs_omics"),
                    "confidence": a.get("confidence"),
                    "cited": bool(a.get("citation_ids")),
                }
                break
        sg = q.get("signal") or {}
        rows.append(
            {
                "id": q.get("id"),
                "seq": q.get("seq"),
                "text": q.get("text"),
                "polarity": sg.get("polarity"),
                "tier": sg.get("tier"),
                "dots": (q.get("confidence") or {}).get("dots"),
                "cells": cells,
                "lit": lit,
            }
        )
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
        parts.append(
            f"strongest {strong.get('label')} {_fmt_num(strong.get('value'))}"
            + (f" (q={_fmt_num(strong.get('q'))})" if strong.get("q") is not None else "")
        )
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


def _kegloss(ke: Optional[dict]) -> Optional[dict]:
    """The split metric-gloss for a card's key_evidence.effect — the sandbox `.kegloss` TEXT companion to
    the visual `_gauge` ruler: a metric LABEL = value (+ n + significance stat), and a muted plain-language
    HELP line (units + direction phrase from display_gloss). Reuses `_dg.gloss`/`_dg.direction_phrase`
    (one vocabulary with the gauge words + narrator). None when the card carries no numeric effect."""
    if not isinstance(ke, dict):
        return None
    eff = ke.get("effect") or {}
    if not isinstance(eff, dict) or eff.get("value") is None:
        return None
    label, units = _dg.gloss(eff.get("metric"))
    dp = _dg.direction_phrase(eff.get("direction"))
    help_line = "; ".join(b for b in (units, dp) if b) or None
    sig = ke.get("significance") or {}
    stat = sig.get("stat")
    return {
        "label": label or (eff.get("metric") or "effect"),
        "value": _fmt_num(eff.get("value")),
        "n": ke.get("n"),
        "stat": (_dg.gloss(stat)[0] or stat) if stat else None,
        "stat_value": _fmt_num(sig.get("value")) if sig.get("value") is not None else None,
        "help": help_line,
    }


import re as _re_scope

_PER_INDICATION_RE = _re_scope.compile(r"per[-_]indication", _re_scope.IGNORECASE)


def _card_scope(c: dict, ke: Optional[dict], indication: Optional[str]) -> dict:
    """Classify the SCOPE of ONE card's reading — pan-cancer vs the indication cohort vs a molecular
    subtype — from the card's data grain, so the drill-down can chip each reading with WHERE it applies.
    Signals, most specific first:
      subtype  — key_evidence.subtype_axis (a subtype-restricted axis) OR a subtype/subgroup-stratified
                 card (its id/measurement_type names a subtype/subgroup stratum);
      indication — the reading LEADS with an indication stratum (key_evidence.top_strata role='indication',
                 i.e. a per-indication-cohort restriction such as a TCGA/CPTAC/GENIE cohort or a
                 lineage-restricted DepMap read) OR a `-per-indication` data product;
      pan_cancer — the default: a pan-cell-line DepMap distribution / pan-cohort percentile, unrestricted.
    Returns {'kind','label'} where label is the display token (the indication code, the subtype class, or
    'pan-cancer'). Verdict-inert display classification — never changes a verdict."""
    sub = (ke or {}).get("subtype_axis") or {}
    if isinstance(sub, dict) and sub.get("restriction_class"):
        lbl = _dg.humanize(sub.get("restriction_class")) or "subtype"
        return {"kind": "subtype", "label": lbl}
    cid = str(c.get("id") or "").lower()
    mt = str(c.get("measurement_type") or "").lower()
    if "subtype" in cid or "subtype" in mt or "subgroup" in cid or "subgroup" in mt:
        return {"kind": "subtype", "label": "subtype-stratified"}
    strata = (ke or {}).get("top_strata") or []
    has_ind_stratum = any(isinstance(s, dict) and s.get("role") == "indication" for s in strata)
    dsids = c.get("dataset_ids") or (c.get("chain") or {}).get("dataset_ids") or []
    per_ind = any(_PER_INDICATION_RE.search(str(x)) for x in dsids)
    if has_ind_stratum or per_ind:
        return {"kind": "indication", "label": (indication or "indication")}
    return {"kind": "pan_cancer", "label": "pan-cancer"}


def _subtype_rollup(ke: Optional[dict]) -> Optional[dict]:
    """The card's subtype-stratified breakdown, surfaced as its own drilldown line (3b). Reads
    key_evidence.subtype_axis: the restriction class + the driving axis + a compact per-subtype line when
    the axis carries one. None when the card carries no subtype axis."""
    sub = (ke or {}).get("subtype_axis") if isinstance(ke, dict) else None
    if not isinstance(sub, dict) or not sub.get("restriction_class"):
        return None
    per = []
    for s in sub.get("per_subtype") or sub.get("strata") or []:
        if not isinstance(s, dict):
            continue
        lbl = s.get("label") or s.get("subtype") or s.get("name")
        val = s.get("value")
        if lbl is not None:
            per.append(f"{lbl}={_fmt_num(val)}" if val is not None else str(lbl))
    return {
        "restriction_class": _dg.humanize(sub.get("restriction_class")),
        "driving_axis": sub.get("driving_axis"),
        "per_subtype": per[:6],
    }


def _card_chain_block(eg: dict) -> Optional[Block]:
    """Per-card dataset→data→rule→verdict chains, grouped by the QUESTION each card answers (aligning
    the drill-down with the question-anchored fingerprint above), so a reader drills the question they
    care about instead of scrolling ~20 one-card measurement-type accordions. Falls back to the card's
    measurement_type for skills with no question mapping (gateless / hand-rolled). Projection over
    eg.cards[]; None when the graph carries no cards. Each card carries its promoted `key_evidence` +
    a compact `key_evidence_summary`, its typed reference-frame interpretation ruler(s), and role flags
    (is_driving / contributes) so the drill can badge verdict-drivers apart from context."""
    cards = eg.get("cards") or []
    if not cards:
        return None
    # target/indication for the plain-language card description (question: with {target.symbol}/
    # {indication.label} filled). The join lives HERE (report_render), never the pure graph builder.
    target, indication = eg.get("target"), eg.get("indication")

    def _card(c: dict) -> dict:
        sig = c.get("signal") or {}
        chain = c.get("chain") or {}
        ke = c.get("key_evidence")
        class_value = (c.get("class") or {}).get("value")
        interp = (ke or {}).get("interpretation") or []
        return {
            "id": c.get("id"),
            "polarity": sig.get("polarity"),
            "liability": bool(sig.get("liability")),
            "role": c.get("role"),
            "measurement_type": c.get("measurement_type"),  # the data layer, kept as a per-card tag
            "class_value": class_value,
            "description": _dg.card_description(c.get("id"), target, indication),  # plain "what is this card"
            "reads": _dg.humanize(class_value) or None,  # class-led "Reads: <class>"
            "interpretation": interp,  # typed reference-frame ruler(s)
            "gauge": _dg.gauge_string(interp[0]) if interp else None,  # the LEAD ruler in words
            "gauges": [g for g in (_dg.gauge_string(gv) for gv in interp) if g],  # ALL rulers (multi-frame)
            "n": (c.get("confidence") or {}).get("n"),
            "dots": (c.get("confidence") or {}).get("dots"),
            "dataset_ids": chain.get("dataset_ids") or [],
            "data": chain.get("data") or [],
            "rule_id": chain.get("rule_id"),
            "is_driving": bool(chain.get("is_driving")),
            "contributes": bool(chain.get("contributes_to_verdict")),
            "key_evidence": ke,
            "key_evidence_summary": _format_key_evidence(ke),
            # sandbox split metric-gloss (.kegloss text companion) + the top-strata table (.ketbl)
            "kegloss": _kegloss(ke),
            "top_strata": (ke or {}).get("top_strata") or [],
            # per-reading SCOPE chip (pan-cancer / indication / subtype) + subtype-stratified rollup (3a/3b)
            "scope": _card_scope(c, ke, indication),
            "subtype_rollup": _subtype_rollup(ke),
        }

    # Group by the card's PRIMARY question (its first question_id) when the skill maps cards to
    # questions; else fall back to measurement_type (byte-stable for gateless/unmapped skills).
    by_question = any(c.get("question_ids") for c in cards)
    layers: dict = {}
    order: list = []
    if by_question:
        questions = eg.get("questions") or []
        qtext = {q.get("id"): (q.get("text") or q.get("id")) for q in questions}
        qmeta = {q.get("id"): q for q in questions}
        qorder = [q.get("id") for q in questions]
        # per-question literature axes (mockup `questions()`: inline that question's litaxis in its qbody,
        # matched by the question's literature_axis_ids), so the drill-down carries the literature read
        # WHERE the question lives — not only in a trailing panel. Verdict-inert display context.
        lit_axes_by_id = {a.get("axis_id"): a for a in ((eg.get("literature") or {}).get("axes") or [])}
        lit_cites_by_id = {c.get("id"): c for c in (eg.get("citations") or [])}

        def _q_literature(q: dict) -> list:
            out = []
            for aid in q.get("literature_axis_ids") or []:
                a = lit_axes_by_id.get(aid)
                if not a:
                    continue
                cites = []
                for cid in a.get("citation_ids") or []:
                    c = lit_cites_by_id.get(cid)
                    if c:
                        cites.append(
                            {"label": c.get("label"), "pmid": c.get("pmid"), "verified": bool(c.get("verified"))}
                        )
                out.append(
                    {
                        "axis_id": a.get("axis_id"),
                        "read": a.get("read"),
                        "agreement": a.get("agreement_vs_omics"),
                        "confidence": a.get("confidence"),
                        "assertion": a.get("assertion"),
                        "citations": cites,
                    }
                )
            return out

        for c in cards:
            qids = c.get("question_ids") or []
            key = qids[0] if qids else "__context__"
            layers.setdefault(key, []).append(_card(c))
        order = [q for q in qorder if q in layers] + [k for k in layers if k not in set(qorder)]
        labels = {**qtext, "__context__": "Context / other"}
        # each question group carries the question's own signal tier / polarity / confidence dots + a short
        # evidence-ref key (reused from the fingerprint's question data, not recomputed) so the drill-down
        # <summary> can render the richer sandbox meter + dots + qstrip + qkey. Absent on unmapped keys.
        groups = []
        for k in order:
            q = qmeta.get(k) or {}
            sig = q.get("signal") or {}
            qconf = q.get("confidence") or {}
            refs = q.get("evidence_refs") or []
            key_labels = [r.get("label") for r in refs[:3] if isinstance(r, dict) and r.get("label")]
            groups.append(
                {
                    "layer": labels.get(k, str(k)),
                    "cards": layers[k],
                    "polarity": sig.get("polarity"),
                    "tier": sig.get("tier"),
                    "dots": qconf.get("dots"),
                    "conf_level": qconf.get("level"),
                    "key": " · ".join(key_labels) or ((q.get("prose") or {}).get("primary") or None),
                    "literature": _q_literature(q),  # inline per-question litaxis (mockup fidelity)
                }
            )
    else:
        for c in cards:
            mt = c.get("measurement_type") or "other"
            if mt not in layers:
                layers[mt] = []
                order.append(mt)
            layers[mt].append(_card(c))
        groups = [{"layer": mt.replace("_", " "), "cards": layers[mt]} for mt in order]
    # skill-level SUBTYPE summary (3b): a one-line signal near the top when ANY card carries a subtype
    # axis, so the subtype read is VISIBLE at the skill grain (not buried in one card). None otherwise.
    subtype_summary = None
    sub_cards = [c for grp in groups for c in grp["cards"] if isinstance(c.get("subtype_rollup"), dict)]
    if sub_cards:
        classes = []
        for c in sub_cards:
            rc = (c.get("subtype_rollup") or {}).get("restriction_class")
            if rc and rc not in classes:
                classes.append(rc)
        subtype_summary = " · ".join(classes) if classes else None
    return Block(
        vocab.CARD_CHAIN,
        {
            "layers": groups,
            "grouped_by": "question" if by_question else "measurement_type",
            "indication": indication,
            "subtype_summary": subtype_summary,
        },
    )


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
        for cid in ids or []:
            c = cites_by_id.get(cid)
            if c:
                out.append({"label": c.get("label"), "pmid": c.get("pmid"), "verified": bool(c.get("verified"))})
        return out

    axes_out = [
        {
            "axis_id": a.get("axis_id"),
            "read": a.get("read"),
            "agreement": a.get("agreement_vs_omics"),
            "confidence": a.get("confidence"),
            "assertion": a.get("assertion"),
            "question_ids": a.get("question_ids") or [],
            "citations": _cites(a.get("citation_ids")),
        }
        for a in axes
    ]
    blind = [
        {"text": b.get("text"), "why_omics_blind": b.get("why_omics_blind"), "citations": _cites(b.get("citation_ids"))}
        for b in blind_raw
    ]
    return Block(
        vocab.LITERATURE_AXES,
        {
            "axes": axes_out,
            "blind_spots": blind,
            "overall_consistency": lit.get("overall_consistency"),
            "key_divergence": lit.get("key_divergence"),
        },
    )


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
        for q in rep.get("question_table") or []:
            if not isinstance(q, dict):
                continue
            note = q.get("cross_lens") or q.get("informs_lens")
            if not note:
                continue  # only questions explicitly flagged as cross-lens
            rows.append(
                {
                    "question": q.get("question") or q.get("q") or q.get("label"),
                    "owner": vocab.skill_title(short),
                    "owner_lens": owner_lens,
                    "informs": note,
                }
            )
            if len(rows) >= 6:
                break
        if len(rows) >= 6:
            break
    return Block(vocab.CROSS_CUTTING_QUESTIONS, {"rows": rows}) if rows else None


_KV_TOKEN = re.compile(r"([a-z_]+)=([\d,]+)")


def _literature_comention_summary(skill_reports: dict, nomination: dict) -> Optional[dict]:
    """Cited-literature co-mention VOLUME/RECENCY for the v6 hero + convergence litctx — parsed from the
    literature_context skill_report's machine-formatted `k=v` claim-chip evidence (paper_disease_mentions,
    recent_mentions, n_diseases), plus a handful of cited PMIDs from the deep-research risk_assessment.
    VERDICT-INERT context (literature is never a gate). None when no literature signal is present."""
    lc = (skill_reports or {}).get("literature_context") if isinstance(skill_reports, dict) else None
    vals: dict = {}
    latest_year = None
    if isinstance(lc, dict):
        for c in lc.get("claim_chips") or []:
            ev = str((c or {}).get("evidence") or "")
            for m in _KV_TOKEN.finditer(ev):
                try:
                    vals.setdefault(m.group(1), int(m.group(2).replace(",", "")))
                except ValueError:
                    pass
            ym = re.search(r"latest (\d{4})", ev)
            if ym:
                latest_year = ym.group(1)
    pmids: list = []
    ra = (nomination or {}).get("risk_assessment") or {}
    for _d, v in (ra.get("dimensions") or {}).items() if isinstance(ra, dict) else []:
        if not isinstance(v, dict):
            continue
        for p in (v.get("cited_pmids") or v.get("pmids") or [])[:3]:
            if p not in pmids:
                pmids.append(str(p))
    total = vals.get("paper_disease_mentions")
    recent = vals.get("recent_mentions")
    if not (total or recent or pmids):
        return None
    return {
        "total_comentions": total,
        "recent_comentions": recent,
        "n_diseases": vals.get("n_diseases"),
        "latest_year": latest_year,
        "cited_pmids": pmids[:6],
    }


def _groundedness_summary(nomination: dict) -> Optional[dict]:
    """The synthesis-grounding stamp for the v6 hero (`✓ synthesis grounded · N claims, 0 invented`) —
    read from the LLM synthesis's verdict-INERT anchor-validation audit (n_cited / n_invented). None when
    the run carried no synthesis or no audit."""
    llm = (nomination or {}).get("llm_synthesis") or (nomination or {}).get("llm_output") or {}
    av = llm.get("_anchor_validation") if isinstance(llm, dict) else None
    if not isinstance(av, dict) or av.get("n_cited") is None:
        return None
    return {"n_cited": av.get("n_cited"), "n_invented": av.get("n_invented") or 0}


def _clinical_precedent_card(skill_reports: dict) -> Optional[dict]:
    """The differentiation-landscape `clinical-precedent` evidence-graph card — the source of the concrete
    trial detail (trial count / active / agents-engaging-target / highest phase / drug names) for the v6
    hero pill. None when differentiation carries no such card. Reads real fields only, never fabricates."""
    diff = (skill_reports or {}).get("differentiation")
    eg = diff.get("evidence_graph") if isinstance(diff, dict) else None
    cards = eg.get("cards") if isinstance(eg, dict) else None
    for c in cards or []:
        if isinstance(c, dict) and c.get("id") == "clinical-precedent":
            return c
    return None


def _clinical_precedent_summary(risk_dims: list, skill_reports: Optional[dict] = None) -> Optional[dict]:
    """Clinical-precedent read for the v6 hero green pill — the `highest_clinical_stage` parsed from the
    Clinical risk dimension's clinical-precedent feeding member (display-placed context, verdict-inert),
    ENRICHED with the concrete trial detail (n_trials / n_active_trials / n_agents / highest phase / drug
    names) read off the differentiation `clinical-precedent` card. None when neither source carries data."""
    out: dict = {}
    for d in risk_dims or []:
        if d.get("dim") != "clinical":
            continue
        for m in d.get("members") or []:
            sm = re.search(r"highest_clinical_stage=([A-Za-z0-9_]+)", str(m.get("read") or ""))
            if sm:
                out["highest_stage"] = sm.group(1).replace("_", " ")
    card = _clinical_precedent_card(skill_reports or {})
    if isinstance(card, dict):
        ke = card.get("key_evidence") if isinstance(card.get("key_evidence"), dict) else {}
        nb = ke.get("n_basis") if isinstance(ke.get("n_basis"), dict) else {}
        kf = card.get("key_fields") if isinstance(card.get("key_fields"), dict) else {}
        # trial counts (real fields off the card; any subset may be present)
        for src_key, dst in (
            ("n_trials", "n_trials"),
            ("n_active_trials", "n_active"),
            ("n_agents_engaging_target", "n_agents"),
        ):
            v = nb.get(src_key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[dst] = int(v)
        # highest phase + representative drug names, if the card surfaces them (flexible key probing —
        # these are absent on some runs, so they degrade gracefully to omitted).
        phase = kf.get("highest_phase") or nb.get("highest_phase") or ke.get("highest_phase")
        if phase:
            out["highest_phase"] = str(phase)
        drugs = kf.get("drug_names") or kf.get("drugs") or ke.get("drug_names") or nb.get("drug_names")
        if isinstance(drugs, (list, tuple)) and drugs:
            out["drugs"] = [str(x) for x in drugs][:4]
    return out or None


def build_ir(
    nomination: dict, spec: ReportSpec, target: Optional[str] = None, indication: Optional[str] = None
) -> ReportIR:
    """Project a nomination + spec into the presentation IR. Pure, deterministic, fail-soft."""
    nomination = nomination or {}
    tr = nomination.get("target_report") or {}
    skill_reports: dict = tr.get("skill_reports") or {}
    target_call = tr.get("target_call") or nomination.get("target_call") or {}

    target = target or _first(nomination, ["target"]) or _first(tr, ["target"])
    indication = indication or _first(nomination, ["indication"]) or _first(tr, ["indication"])

    deciding_short = _deciding_short(target_call.get("deciding_axis"), set(skill_reports))

    # COMPOSED cross-axis reconciled axes: shorts whose measured-negative contradiction the gate RETIRED
    # (target_call.gate.hard_gates status == 'reconciled'). De-escalates the rendered glyph/strip/scatter
    # to neutral so they agree with the gate + LLM. Empty for standalone (build_ir_for_skill has no gate),
    # so this is structurally composed-only and byte-stable on any run with no reconciliation.
    reconciled_shorts = frozenset(
        row.get("short")
        for row in ((target_call.get("gate") or {}).get("hard_gates") or [])
        if isinstance(row, dict) and row.get("status") == "reconciled" and row.get("short")
    )

    # #1271: gating axes whose whole modality-channel family is a category error for the target's curated
    # biology axis (surface_modality on an intracellular target) — from the #1203 build_skill_report_rollup
    # mask. De-escalate their measured-negative `killer` to neutral in the strip/scatter/fingerprint tally
    # so the top-line "N against/neutral" count agrees with the rollup (killer_axes excluded) + the gate.
    # Empty on standalone runs + any run the rollup masked nothing → byte-stable.
    axis_not_applicable = frozenset((tr.get("skill_report_rollup") or {}).get("axis_not_applicable") or ())

    # header (the decision) — always present, tier 0.
    # coherence thesis lives at target_report.thesis (full-nest) OR top-level nomination.target_coherence
    # (pre-nest runs) — same fallback _coherence_block uses, so the header + strip reconciliation resolve
    # it in both shapes. Byte-stable on the nested goldens (the fallback never triggers there).
    _tc = (tr.get("thesis") if isinstance(tr.get("thesis"), dict) else None) or (
        nomination.get("target_coherence") if isinstance(nomination.get("target_coherence"), dict) else None
    )
    _thesis_obj = (_tc or {}).get("thesis") if isinstance(_tc, dict) else None
    _thesis_primary = _thesis_obj.get("primary") if isinstance(_thesis_obj, dict) else None
    # v6 hero polish: a STANDOUT one-sentence pull-together (first sentence of the LLM executive
    # summary — a dedicated overall_statement field is preferred when the synthesizer emits one), and
    # the addressable-population framing (target×indication prevalence). Both verdict-inert display.
    _llm = nomination.get("llm_synthesis") or nomination.get("llm_output") or {}
    # a DEDICATED overall_statement / headline field (when the synthesizer emits one) is the crafted
    # standout; else the hero assembles a crafted statement from the deterministic fields (call · biology
    # clause · deciding caveat · cleared modality · addressable prevalence). Both verdict-inert display.
    _overall = (_llm_val(_llm, "overall_statement") or _llm_val(_llm, "headline")) if isinstance(_llm, dict) else None
    _dedicated_headline = bool(_overall)
    _exec_lead = None
    _exec = _llm_val(_llm, "executive_summary") if isinstance(_llm, dict) else None
    if isinstance(_exec, str) and _exec.strip():
        _exec_lead = re.split(r"(?<=[.!?])\s+", _exec.strip(), maxsplit=1)[0]
    if not _overall:
        _overall = _exec_lead
    if _overall:  # strip inline [rule_id] citations from the headline prose (same as the synthesis block)
        _overall = _strip_rule_citations(_overall)[0]
    if _exec_lead:
        _exec_lead = _strip_rule_citations(_exec_lead)[0]
    # the deciding safety→modality reconciliation feeding the crafted headline caveat: a HIGH on-target
    # safety concern SUPPRESSED because a spared (mutant-selective) modality exists. Real gate field only.
    _safety_escape = None
    for _v in (target_call.get("gate") or {}).get("suppressed_vetoes") or []:
        if not isinstance(_v, dict):
            continue
        _by = _v.get("suppressed_by") or {}
        _chans = _by.get("safe_channels") or []
        _safety_escape = {
            "short": _v.get("short") or "safety",
            "verdict": _v.get("verdict"),
            "channels": [str(c) for c in _chans] if _chans else [],
            "kind": _by.get("kind"),
        }
        break
    # v6 single-scroll hero enrichment (verdict-inert display context): the 6-dim GLANCE reads the same
    # deterministic risk_6dim as the assessment spine (built once, shared), the coherence class frames the
    # archetype line, and the literature co-mention volume + clinical-precedent pill anchor the hero. None
    # of these enter the decision — they are the SAME payloads the composed blocks already carry.
    _risk6_block = _risk_6dim_block(tr.get("risk_6dim"), skill_reports, nomination.get("risk_assessment"))
    _risk_dims = _risk6_block.payload["dims"] if _risk6_block else []
    _coh_obj = (_tc or {}).get("coherence") if isinstance(_tc, dict) else None
    _coherence_class = _coh_obj.get("class") if isinstance(_coh_obj, dict) else _coh_obj
    _lit_comention = _literature_comention_summary(skill_reports, nomination)
    header = Block(
        vocab.REPORT_HEADER,
        {
            "target": target,
            "indication": indication,
            "overall_statement": _overall,
            "dedicated_headline": _dedicated_headline,
            "exec_lead": _exec_lead,
            "safety_escape": _safety_escape,
            "addressable_population": tr.get("addressable_population"),
            "thesis": _thesis_primary if _thesis_primary != "insufficient_thesis" else None,
            "coherence_class": _coherence_class,
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
            # v6 hero right-column: the 6-dim glance (same dims as the assessment-view spine).
            "risk_dims": _risk_dims,
            "literature": _lit_comention,
            "clinical_precedent": _clinical_precedent_summary(_risk_dims, skill_reports),
            "groundedness": _groundedness_summary(nomination),
        },
    )

    # select + order sections.
    selected = []
    for short, report in skill_reports.items():
        if not isinstance(report, dict):
            continue
        role = report.get("role") or ("gating" if short in vocab.GATING_SHORTS else "descriptive")
        if not _in_scope(short, role, spec):
            continue
        selected.append((short, report, role))

    selected.sort(key=lambda t: _sort_key(t[0], t[2], t[1].get("polarity"), t[0] == deciding_short, spec))

    # run-dir figure join: map each produced card figure to its owning section (gating-lister first).
    figs_by_owner = _figures_by_owner(nomination, _card_figure_owner_map(nomination, skill_reports))

    sections = [
        _build_section(
            short,
            report,
            spec,
            is_deciding=(short == deciding_short),
            card_figs=figs_by_owner.get(short, []),
            reconciled_shorts=reconciled_shorts,
            target=target,
            indication=indication,
            axis_not_applicable=axis_not_applicable,
        )
        for short, report, role in selected
    ]

    overview = []

    def _add(kind, block):
        if block is not None and spec.level_int >= vocab.TIER[kind]:
            overview.append(block)

    # thesis primary (target_coherence) → reconcile a thesis-EXPECTED negative in the diverging strip
    # (e.g. dependency non-signal under a surface-antigen thesis). Reuses the header's `_thesis_obj`;
    # None on a run without a coherence thesis leaves the strip's raw polarities untouched.
    # composed at-a-glance grid from the target_report.evidence_graph index (#1068) — added first so it
    # leads the Decision lens (lens grouping preserves insertion order within a lens). None → not added
    # (pre-index nominations stay byte-stable).
    _add(vocab.COMPOSED_FINGERPRINT, _composed_fingerprint_block(tr, reconciled_shorts, axis_not_applicable))
    _add(
        vocab.SIGNALS_SCATTER,
        _signals_scatter_block(selected, deciding_short, reconciled_shorts, axis_not_applicable),  # Signals lens
    )
    _add(
        vocab.SIGNALS_OVERVIEW,
        _signals_overview_block(selected, deciding_short, _thesis_primary, reconciled_shorts, axis_not_applicable),
    )
    # the salient measured-fields evidence view (L2+) — the deep dive that carries the evidence itself,
    # additive alongside the verdict strip above (see 2b: relevance is the per-field salience role).
    _add(vocab.EVIDENCE_SIGNALS, _evidence_signals_block(selected))
    _add(vocab.CROSS_CUTTING_QUESTIONS, _cross_cutting_block(nomination, skill_reports))
    _add(vocab.COHERENCE, _coherence_block(tr, nomination))
    _add(vocab.SYNTHESIS, _synthesis_block(nomination, _lit_comention))
    _add(vocab.RISK_6DIM, _risk6_block)
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
    banner = (
        _synthesis_banner_block(nomination, target_call)
        if spec.level_int >= vocab.TIER[vocab.SYNTHESIS_BANNER]
        else None
    )

    return ReportIR(
        target=target,
        indication=indication,
        spec=spec,
        header=header,
        sections=sections,
        about=_about_block(spec),
        deciding_short=deciding_short,
        overview=overview,
        banner=banner,
    )


def _about_block(spec: ReportSpec) -> Optional[Block]:
    """The honesty legend / spec footer — shown from L1 up (kept off the one-page L0 exec brief)."""
    if spec.level_int < vocab.TIER[vocab.ABOUT]:
        return None
    return Block(
        vocab.ABOUT,
        {
            "polarity_legend": vocab.polarity_legend(),
            "spec": {
                "level": spec.level,
                "medium": spec.medium,
                "scope": list(spec.scope) if isinstance(spec.scope, tuple) else spec.scope,
                "lead": spec.lead,
            },
            "note": (
                "Signals lead; the call is a subordinate summary. Ordinal polarity is an "
                "order-preserving display view, NOT calibrated measurement; 'not scored' / "
                "off-scale means context or a coverage gap, not a low score."
            ),
        },
    )


def build_ir_for_skill(
    skill_report: dict,
    spec: ReportSpec,
    *,
    skill_name: Optional[str] = None,
    short: Optional[str] = None,
    target: Optional[str] = None,
    indication: Optional[str] = None,
) -> ReportIR:
    """Project a SINGLE skill's `skill_report` into a one-section report IR (for rendering a standalone
    skill run, e.g. tumor-presence, without a full target_report). No target_call decision header — the
    header is just the target/indication frame; the skill's own call/polarity lead its section. Same
    tiering, medium and fail-soft as the composed path."""
    skill_report = skill_report or {}
    if short is None:
        short = vocab.skill_short_for_name(skill_name) or skill_name or "skill"
    header = Block(
        vocab.REPORT_HEADER,
        {
            "target": target,
            "indication": indication,
            "recommendation": None,
            "confidence": None,
            "deciding_axis": None,
            "deciding_short": None,
            "deciding_title": None,
            "dissent": [],
            "gate": None,
            "lead": spec.lead,
            "single_skill": True,
        },
    )
    section = _build_section(short, skill_report, spec, is_deciding=False, target=target, indication=indication)
    return ReportIR(
        target=target,
        indication=indication,
        spec=spec,
        header=header,
        sections=[section],
        about=_about_block(spec),
        deciding_short=None,
    )


def _skill_reports_of(nomination: dict) -> dict:
    """The {short: skill_report} spine off a nomination/target_report (either nesting), or {}."""
    if not isinstance(nomination, dict):
        return {}
    tr = nomination.get("target_report") if isinstance(nomination.get("target_report"), dict) else nomination
    sr = tr.get("skill_reports")
    return sr if isinstance(sr, dict) else {}


def build_layer_ir(
    nomination: dict,
    *,
    card: Optional[str] = None,
    question: Optional[str] = None,
    datum: Optional[tuple] = None,
    spec: Optional[ReportSpec] = None,
    target: Optional[str] = None,
    indication: Optional[str] = None,
) -> ReportIR:
    """Address a SINGLE layer of a composed target_report and render just it — a card panel (`card=cid`),
    a question panel (`question=qid`), or one gauged datum (`datum=(cid, field)`). Locates the owning
    sub-skill's evidence_graph, PRUNES it to the addressed element, then reuses `build_ir_for_skill` (so
    every existing block builder + backend renders it unchanged). ADDITIVE — a new entry point; the
    all/gating/tuple scopes and the composed/standalone paths are untouched.

    Exactly one address must be given. Raises ValueError if the address is malformed or not found (an
    explicit address should fail loudly, never silently render an empty page)."""
    given = [a for a in (card, question, datum) if a is not None]
    if len(given) != 1:
        raise ValueError("build_layer_ir: pass exactly one of card=, question=, datum=")
    spec = spec or resolve_spec(None, level="L3")
    cid = card or (datum[0] if datum else None)
    field = datum[1] if datum else None
    reports = _skill_reports_of(nomination)
    tgt = target or nomination.get("target")
    ind = indication or nomination.get("indication")

    def _ids(seq, key="id"):
        return [x.get(key) for x in (seq or []) if isinstance(x, dict)]

    for short, sr in reports.items():
        if not isinstance(sr, dict):
            continue
        eg = sr.get("evidence_graph") or {}
        cards = eg.get("cards") or []
        questions = eg.get("questions") or []
        if question is not None:
            q = next((x for x in questions if isinstance(x, dict) and x.get("id") == question), None)
            if q is None:
                continue
            keep_cids = set(q.get("card_ids") or [])
            pruned = {**eg, "questions": [q], "cards": [c for c in cards if c.get("id") in keep_cids]}
        else:
            if cid not in _ids(cards):
                continue
            kept_cards = [c for c in cards if c.get("id") == cid]
            if field is not None:  # datum: narrow the card's rulers to the addressed field
                kc = dict(kept_cards[0])
                ke = dict(kc.get("key_evidence") or {})
                interp = [
                    r
                    for r in (ke.get("interpretation") or [])
                    if isinstance(r, dict) and field in (r.get("value_field"), r.get("field"), r.get("metric"))
                ]
                if interp:
                    ke["interpretation"] = interp
                    kc["key_evidence"] = ke
                kept_cards = [kc]
            pruned = {
                **eg,
                "cards": kept_cards,
                "questions": [q for q in questions if cid in (q.get("card_ids") or [])],
            }
        pruned_report = {**sr, "evidence_graph": pruned}
        return build_ir_for_skill(pruned_report, spec, short=short, target=tgt, indication=ind)

    addr = (
        f"question={question!r}" if question is not None else f"card={cid!r}" + (f" field={field!r}" if field else "")
    )
    raise ValueError(f"build_layer_ir: {addr} not found in any sub-skill evidence_graph")


__all__ = ["Block", "Section", "ReportIR", "build_ir", "build_ir_for_skill", "build_layer_ir"]
