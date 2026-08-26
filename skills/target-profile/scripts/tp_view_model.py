"""target-profile — the composed-dashboard VIEW MODEL (PR-3 of the restructure).

ONE ordered list of optional BLOCKS that BOTH renderers (html + md) and the left-nav iterate — so
section set, order, and mode-selection have a single source and can no longer drift (the nav/body
ordering + the md↔html section-set drift the old code fought by hand). A renderer is then a thin
`{block.kind → emitter}` dispatch over `view_model.blocks`.

A Block is verdict-inert metadata: `id` (anchor/nav id), `kind` (which emitter draws it), `title`,
and the `modes`/predicate that gate whether it appears this run. Block PAYLOADS are not pre-sliced —
emitters read what they need from the shared `RenderContext` (keeps this module free of rendering
concerns and avoids duplicating the renderers' input plumbing).

`build_view_model(ctx)` returns only the blocks PRESENT for this run+mode, in canonical order. The
canonical order is defined ONCE here (fixing the old nav-vs-body order discrepancy):
  synthesis → risk_by_category → literature_risk → evidence_summary → modality_matrix →
  deciding_axis → subskill_sections → tension → provenance_trace → about
`presence_only` (focused view) collapses to synthesis-less: just the single presence subskill section.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# Canonical block order for the FULL report. Each entry: (kind, anchor-id, title, predicate(ctx)->bool).
# Kept declarative so html/md/nav all consume the identical ordered set.


@dataclass
class Block:
    kind: str                    # dispatch key → the renderer's emitter for this section
    id: str                      # anchor / nav id (e.g. "s-evidence")
    title: str                   # nav label
    nav: bool = True             # show in the left nav
    payload: Any = None          # optional pre-computed payload; usually None (emitter reads ctx)


@dataclass
class RenderContext:
    """Everything the block emitters read — the renderers' shared inputs, gathered once."""
    target: str
    indication: str
    sub_results: dict
    llm_output: dict
    invoked_lenses: Any = None
    deciding_axis: Optional[dict] = None
    ordinal_matrix: Optional[dict] = None
    scorecard: Optional[list] = None
    catalogue_rows: Optional[list] = None
    recommendation_gate: Optional[dict] = None
    card_figures: Optional[dict] = None
    figures_dir: Any = None
    presence_facet: Optional[dict] = None
    selectivity_facet: Optional[dict] = None
    risk_assessment: Optional[dict] = None
    grounded_by_axis: Optional[dict] = None
    hypothesis: Optional[dict] = None
    confidence_tier: Optional[dict] = None
    risk_rollup: Optional[dict] = None
    addressable_population: Optional[dict] = None
    target_coherence: Optional[dict] = None      # target_coherence.v1 — the thesis / through-line lens
    full_package: bool = False                   # --full-package → render the data-package explorer block
    presence_only: bool = False
    show_deciding_axis: bool = True
    embed: str = "interactive"        # "interactive" (plotly+CDN) | "self_contained" (inline SVG data-URI)
    extra: dict = field(default_factory=dict)


# (kind, id, title, nav, predicate) — the FULL-report block spec in canonical render order.
# Order matches the current body assembly: risk-by-category LEADS the analytical content (per
# RISK_CATEGORY_DASHBOARD_SPINE.md), then the synthesis, then literature-risk, then the summaries.
_BLOCK_SPEC = [
    ("risk_by_category", "s-risk-rollup", "Risk by category (deterministic)", True,
     lambda c: bool(c.risk_rollup)),
    ("synthesis",        "s-exec",       "Executive summary",              True,
     lambda c: True),                                                      # exec OR hypothesis (emitter picks)
    ("coherence",        "s-coherence",  "Target thesis & coherence",      True,
     # predicate MUST match _coherence_emit's guard (needs thesis.primary) — else a dead nav anchor.
     lambda c: bool(((c.target_coherence or {}).get("thesis") or {}).get("primary"))),
    ("literature_risk",  "s-litrisk",    "Literature risk (context)",      True,
     # predicate MUST match _render_literature_risk_html's guard (needs a dimensions dict).
     lambda c: isinstance((c.risk_assessment or {}).get("dimensions"), dict)),
    ("evidence_summary", "s-evidence",   "Evidence summary",               True,
     # the emitter renders from sub_results verdicts (even gateless shorts w/ no scorecard row), so gate
     # on present sub-skills, not on a truthy scorecard (which suppressed a gateless-only run's summary).
     lambda c: bool(c.sub_results)),
    ("modality_matrix",  "s-matrix",     "Modality-fit matrix",            True,
     lambda c: bool(c.ordinal_matrix) or bool(c.catalogue_rows)),
    ("deciding_axis",    "s-deciding",   "Deciding axis",                  True,
     lambda c: bool(c.deciding_axis) and c.show_deciding_axis),
    ("subskill_sections", "s-subskills", "Subskill evidence",             True,
     lambda c: True),                                                      # always ≥1 subskill
    ("tension",          "s-tension",    "Conflicting signals",            True,
     # suppressed ONLY when a hypothesis BODY replaces the synthesis (it carries its own tensions);
     # a bodyless hypothesis leaves the exec-summary + tension in place (matches the synthesis swap).
     lambda c: not (isinstance(c.hypothesis, dict) and c.hypothesis.get("hypothesis"))),
    ("provenance_trace", "s-provenance", "Provenance trace",               True,
     lambda c: bool(c.sub_results)),
    ("data_package_explorer", "s-data-package", "Data package",            True,
     lambda c: bool(c.full_package)),                                      # --full-package only
    ("about",            "s-about",      "About this analysis",            True,
     lambda c: True),
]

# When `--hypothesis` is supplied the synthesis block leads with the cross-evidence hypothesis and
# its nav label/id change; the emitter handles the content, the nav label is adjusted here.
_HYP_SYNTHESIS = ("synthesis", "s-hypothesis", "Cross-evidence hypothesis", True, lambda c: True)


def build_view_model(ctx: RenderContext) -> list[Block]:
    """Return the ordered list of PRESENT blocks for this run+mode. Single source for html/md/nav."""
    if ctx.presence_only:
        # Focused presence view: only the subskill section(s); no synthesis/summary chrome.
        return [Block("subskill_sections", "s-subskills", "Presence", nav=True)]
    blocks: list[Block] = []
    for kind, bid, title, nav, pred in _BLOCK_SPEC:
        if kind == "synthesis":
            # Swap the nav to the hypothesis anchor ONLY when a hypothesis BODY exists — otherwise the
            # emitter falls back to the exec-summary (id s-exec), and a 's-hypothesis' nav link would be
            # a dead anchor + mislabeled. (Matches _synthesis_emit / _render_hypothesis_html's guard.)
            if isinstance(ctx.hypothesis, dict) and ctx.hypothesis.get("hypothesis"):
                k2, id2, t2, nav2, _ = _HYP_SYNTHESIS
                blocks.append(Block(k2, id2, t2, nav2))
                continue
        if pred(ctx):
            blocks.append(Block(kind, bid, title, nav))
    return blocks


def present_kinds(ctx: RenderContext) -> list[str]:
    """The ordered block-kind list — the parity contract both renderers must satisfy."""
    return [b.kind for b in build_view_model(ctx)]


__all__ = ["Block", "RenderContext", "build_view_model", "present_kinds"]
