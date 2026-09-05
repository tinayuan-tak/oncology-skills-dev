"""HTML dashboard backend — a self-contained, single-file document (own CSS, light + dark).

Self-contained: it reuses only the stable single-vocabulary `ordinal_view` polarity
scale via `vocab`. Like every backend it is dumb: one {block-kind → HTML fragment} handler set, no
selection logic (the IR builder already tiered/scoped/medium-resolved every block).
"""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path

from .. import vocab
from ..ir import Block, ReportIR, Section

_MAX_INLINE_SVG_BYTES = 120_000   # inline the small decision-relevant plots (histograms/forests/bars/
                                  # gauges); a giant per-point matplotlib scatter (100s of KB) falls back
                                  # to a relative <img> rather than balloon the page past a few MB.

_POL_CLASS = {
    "killer": "pol-killer", "opposing": "pol-opposing", "neutral": "pol-neutral",
    "supportive": "pol-supportive",
}


def _esc(x) -> str:
    return escape("" if x is None else str(x))


_CSS = """
:root {
  color-scheme:light;
  --page:#f4f4f1; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --line:#e6e5df; --border:rgba(11,11,11,0.09); --hair:#ecebe4;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b; --blue:#2a78d6;
  /* framework polarity → reserved status palette */
  --supportive:#0ca30c; --neutral:#898781; --opposing:#ec835a; --killer:#d03b3b; --none:#b6b5ad;
  --go:#0ca30c; --hold:#e0912a; --kill:#d03b3b;
  /* soft tints (status-on-surface, for cell/pill backgrounds) */
  --t-good:rgba(12,163,12,.11); --t-serious:rgba(236,131,90,.15); --t-crit:rgba(208,59,59,.13);
  --t-neutral:rgba(137,135,129,.12); --t-blue:rgba(42,120,214,.10);
}
@media (prefers-color-scheme:dark) {
  :root:where(:not([data-theme=light])) {
    color-scheme:dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#8f8e86;
    --line:#2c2c2a; --border:rgba(255,255,255,0.10); --hair:#232321;
    --opposing:#ec835a; --killer:#e06060; --none:#5f5e57; --hold:#f0a63a;
    --t-good:rgba(12,163,12,.18); --t-serious:rgba(236,131,90,.20); --t-crit:rgba(224,96,96,.20);
    --t-neutral:rgba(143,142,134,.16); --t-blue:rgba(57,135,229,.16);
  }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--page); color:var(--ink);
       font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       -webkit-font-smoothing:antialiased; }
.wrap { max-width:1120px; margin:0 auto; padding:32px 28px 72px; }
h1 { font-size:27px; font-weight:680; margin:0 0 2px; letter-spacing:-0.01em; }
h2 { font-size:18px; font-weight:660; margin:0 0 10px; letter-spacing:-0.005em; }
h3 { font-size:14px; font-weight:650; margin:0 0 6px; }
.sub { color:var(--ink2); margin:0 0 14px; font-size:15px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:14px;
        padding:20px 24px; margin:0 0 18px; box-shadow:0 1px 2px rgba(11,11,11,0.03); }
/* a thin polarity spine on per-skill cards only (report-level cards stay clean) */
.card.pol-killer { border-left:4px solid var(--killer); }
.card.pol-opposing { border-left:4px solid var(--opposing); }
.card.pol-neutral { border-left:4px solid var(--neutral); }
.card.pol-supportive { border-left:4px solid var(--supportive); }
.decision { background:linear-gradient(180deg,var(--surface),var(--surface)); border-color:var(--border); }
.stitle { font-size:16px; font-weight:660; margin:0 0 2px; display:flex; align-items:center; gap:9px; }
.glyph { font-size:15px; }
.phrase { color:var(--ink2); margin:3px 0 12px; }
.kv { margin:4px 0; color:var(--ink2); }
.kv b { color:var(--ink); font-weight:640; }
/* recommendation is a SUBORDINATE line, not a shouty pill */
.rec { display:inline-flex; align-items:center; gap:7px; font-weight:640; font-size:14px; }
.rec .dot { width:9px; height:9px; border-radius:999px; background:var(--none); display:inline-block; }
.rec.go .dot { background:var(--go); } .rec.hold .dot { background:var(--hold); } .rec.kill .dot { background:var(--kill); }
.rec .word { text-transform:capitalize; }
.deciding { font-size:11px; color:var(--ink2); background:var(--t-blue); border-radius:6px;
            padding:1px 7px; margin-left:6px; font-weight:600; }
/* target characterization "reads as" chips */
.char { margin:10px 0 4px; }
.char .lbl { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin-bottom:5px; }
.char-chip { display:inline-flex; align-items:baseline; gap:6px; padding:4px 11px; margin:0 6px 6px 0;
             border:1px solid var(--border); border-radius:999px; background:var(--surface); font-size:13px; }
.char-chip .w { color:var(--muted); font-variant-numeric:tabular-nums; font-size:12px; }
.char-chip.lead { background:var(--t-blue); border-color:transparent; font-weight:600; }
ul.chips { margin:8px 0; padding-left:20px; } ul.chips li { margin:3px 0; }
table { border-collapse:collapse; width:100%; margin:10px 0; font-size:14px; }
th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--hair); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
figure { margin:12px 0; } figure img { max-width:100%; border:1px solid var(--border); border-radius:10px;
        background:var(--surface); }
figcaption { color:var(--ink2); font-size:13px; margin-top:5px; }
.fig-more { margin:6px 0 2px; } .fig-more summary { cursor:pointer; color:var(--muted); font-size:13px; }
.fig-badge { display:inline-flex; align-items:center; gap:4px; font-size:11px; font-weight:700;
             letter-spacing:.02em; border-radius:999px; padding:2px 9px; margin-right:7px;
             vertical-align:middle; border:1px solid transparent; }
.fig-badge.sig-supportive { background:var(--t-good); color:var(--ink); border-color:var(--good); }
.fig-badge.sig-neutral { background:var(--t-neutral); color:var(--ink2); border-color:var(--none); }
.fig-badge.sig-opposing { background:var(--t-serious); color:var(--ink); border-color:var(--serious); }
.fig-badge.sig-killer { background:var(--t-crit); color:var(--ink); border-color:var(--critical); }
.fig-badge.sig-insufficient, .fig-badge.sig-not_applicable { background:var(--t-neutral); color:var(--ink2); border-color:var(--none); }
.fig-badge.sig-context { background:transparent; color:var(--muted); border-color:var(--border); }
.unmeasured { color:var(--muted); font-size:13px; }
.prov { color:var(--muted); font-size:12.5px; }
.about { color:var(--muted); font-size:12.5px; margin-top:24px; border-top:1px solid var(--hair); padding-top:14px; }
.section-label { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:10px 0 2px; }
.lede { color:var(--ink2); margin:0 0 12px; }
.signal-strip { margin:6px 0; overflow-x:auto; }
.scatter-wrap { margin:6px 0; overflow-x:auto; }
.so-foot { color:var(--muted); font-size:13px; margin:10px 0 0; }
.risk-tiles { display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin:8px 0 2px; }
@media (max-width:760px) { .risk-tiles { grid-template-columns:repeat(3,1fr); } }
.risk-tile { border:1px solid var(--border); border-top-width:3px; border-radius:10px; padding:11px 8px;
             text-align:center; background:var(--surface); }
.risk-tile .rt-dim { font-size:11px; font-weight:650; color:var(--muted); line-height:1.25; }
.risk-tile .rt-bin { font-size:15px; font-weight:750; margin-top:4px; }
.risk-tile.rt-high { border-top-color:var(--critical); } .risk-tile.rt-high .rt-bin { color:var(--critical); }
.risk-tile.rt-med { border-top-color:var(--warning); } .risk-tile.rt-med .rt-bin { color:var(--serious); }
.risk-tile.rt-low { border-top-color:var(--good); } .risk-tile.rt-low .rt-bin { color:var(--good); }
.risk-tile.rt-blind .rt-bin { color:var(--muted); font-size:12px; font-weight:600; }
.tag { display:inline-block; font-size:10px; text-transform:uppercase; letter-spacing:.06em;
       font-weight:700; color:var(--muted); border:1px solid var(--border); border-radius:6px;
       padding:1px 7px; margin-bottom:8px; }
/* modality-fit status list */
.mod-row { display:grid; grid-template-columns:170px 130px 1fr; gap:14px; align-items:center;
           padding:11px 4px; border-bottom:1px solid var(--hair); }
.mod-row:last-child { border-bottom:none; }
.mod-name { font-weight:600; }
.mod-row.na .mod-name { color:var(--muted); }
.pill { display:inline-flex; align-items:center; gap:6px; padding:3px 11px; border-radius:999px;
        font-weight:650; font-size:13px; border:1px solid var(--c,var(--none));
        background:var(--tc,var(--t-neutral)); color:var(--ink); }
.pill .ic { color:var(--c); font-weight:800; }
.pill.viable { --c:var(--good); --tc:var(--t-good); }
.pill.conditional { --c:var(--warning); --tc:rgba(250,178,25,.16); }
.pill.unfavorable { --c:var(--critical); --tc:var(--t-crit); }
.pill.not_applicable { --c:var(--none); --tc:transparent; border-style:dashed; color:var(--muted); }
.mod-why { color:var(--ink2); }
.axis-chip { display:inline-flex; gap:4px; font-size:12px; color:var(--ink2); padding:1px 8px;
             margin:2px 5px 0 0; border:1px solid var(--border); border-radius:6px; white-space:nowrap; }
.axis-chip .ic { font-weight:800; }
.axis-chip.viable .ic { color:var(--good); } .axis-chip.conditional .ic { color:var(--warning); }
.axis-chip.unfavorable .ic { color:var(--critical); } .axis-chip.killer .ic { color:var(--critical); }
td.mx-pos { background:var(--t-good); } td.mx-neg { background:var(--t-serious); }
td.mx-killer { background:var(--t-crit); font-weight:650; } td.mx-zero { background:var(--t-neutral); }
td.mx-off { color:var(--muted); }
.cite-prov { color:var(--muted); font-size:13px; margin:8px 0 2px; }
.cite-prov summary { cursor:pointer; }
.cite-prov code { font-size:12px; background:var(--page); border:1px solid var(--border);
                  border-radius:4px; padding:0 5px; margin:2px 3px 0 0; display:inline-block; }
/* advisory synthesis banner (persistent chrome, above the lens tabs) */
.card.narr { border-style:dashed; }
.mismatch { color:var(--serious); }
ul.chips.notes li { margin:4px 0; }
.g-sup { color:var(--supportive); font-weight:700; } .g-opp { color:var(--opposing); font-weight:700; }
.g-warn { color:var(--warning); font-weight:700; }
.conflict { color:var(--warning); font-weight:700; }
/* collapsed per-skill sections under the Signals lens (the embedded sub-skill views) */
details.skill-collapse > summary { cursor:pointer; list-style:none; }
details.skill-collapse > summary::-webkit-details-marker { display:none; }
details.skill-collapse > summary::before { content:"▸ "; color:var(--muted); font-weight:700; }
details.skill-collapse[open] > summary::before { content:"▾ "; }
details.skill-collapse > summary .stitle { display:inline-flex; }
details.skill-collapse > summary .phrase { margin:3px 0 0; }
.g-neu { color:var(--neutral); font-weight:700; } .g-kil { color:var(--killer); font-weight:700; }
/* evidence-graph blocks (P3): fingerprint heatmap + dataset→data→rule→verdict chains + literature axes */
.eg-inner { margin:6px 0 2px; }
.hm { display:flex; flex-wrap:wrap; gap:10px 14px; }
.hmg { display:flex; flex-direction:column; gap:4px; }
.hmglab { font-size:10.5px; color:var(--muted); display:flex; align-items:center; gap:4px; }
.hmcells { display:flex; gap:3px; align-items:center; }
.hmcell { width:15px; height:15px; border-radius:4px; border:1px solid var(--border); }
.hmsep { width:1px; height:15px; background:var(--hair); margin:0 3px; }
.litdot { width:15px; height:15px; border-radius:50%; border:1px solid var(--border); display:inline-flex;
          align-items:center; justify-content:center; font-size:9px; color:#fff; font-weight:700; }
.hmnote { color:var(--muted); font-size:11px; margin-top:8px; }
.cardln { border:1px solid var(--border); border-radius:7px; background:var(--surface); margin:6px 0; padding:7px 10px; }
.chead { font-size:11.5px; color:var(--muted); display:flex; justify-content:space-between; align-items:center;
         gap:8px; margin-bottom:3px; } .chead b { color:var(--ink2); font-weight:600; }
.ccchip { display:inline-flex; align-items:center; gap:5px; font-size:11px; color:var(--ink2);
          background:var(--page); border:1px solid var(--border); border-radius:999px; padding:0 7px; white-space:nowrap; }
.chainline { font-size:11.5px; line-height:1.7; color:var(--ink2); }
.chainline .lab { color:var(--muted); text-transform:uppercase; font-size:9px; letter-spacing:.04em; margin-right:2px; }
.chainline .mono, .mono { font-family:ui-monospace,Menlo,monospace; font-size:10.5px; }
.chainline .sep { color:var(--muted); margin:0 4px; }
.cdesc { font-size:11.5px; color:var(--muted); line-height:1.5; margin:1px 0 3px; }
.cread { font-size:12px; color:var(--ink2); margin:2px 0 4px; } .cread b { font-weight:640; }
.chainline.keyev .lab { background:var(--page); }
.gauge { margin:3px 0 5px; }
.gtrack { position:relative; height:16px; margin:9px 0 2px; }
.gtrack .grail { position:absolute; top:7px; left:0; right:0; height:2px; background:var(--border); border-radius:2px; }
.gtick { position:absolute; top:2px; width:1px; height:12px; background:var(--muted); transform:translateX(-50%); }
.gtick.gcut { background:var(--ink2); height:14px; top:1px; }
.gtick .gtlab { position:absolute; top:13px; left:50%; transform:translateX(-50%); font-size:8.5px; color:var(--muted); white-space:nowrap; }
.gmark { position:absolute; top:3px; width:10px; height:10px; border-radius:50%; transform:translateX(-50%); border:1.5px solid var(--surface); box-shadow:0 0 0 1px currentColor; }
.gmark.gcomp { width:8px; height:8px; top:4px; opacity:.55; }
.gcap { font-size:11px; color:var(--ink2); }
.pill-drv { background:var(--t-good,rgba(12,163,12,.12)); color:var(--supportive); border:1px solid var(--border);
            border-radius:4px; padding:0 5px; font-size:9.5px; font-weight:700; }
.pill-none { color:var(--muted); font-size:11px; font-style:italic; }
details.pklayer { border:1px solid var(--border); border-radius:8px; margin:6px 0; background:var(--surface); }
details.pklayer > summary { cursor:pointer; list-style:none; padding:7px 11px; font-size:12px; font-weight:560;
                           display:flex; justify-content:space-between; gap:8px; }
details.pklayer > summary::-webkit-details-marker { display:none; }
details.pklayer > summary::before { content:"▸ "; color:var(--muted); }
details.pklayer[open] > summary::before { content:"▾ "; }
.pklayer .lbody { padding:0 11px 8px; }
.ccinline { color:var(--muted); font-size:11.5px; white-space:nowrap; }
.cite-pill { display:inline-block; font-size:11px; color:var(--ink2); background:var(--page); border:1px solid var(--border);
             border-radius:5px; padding:0 5px; margin:0 2px 2px 0; }
""".strip()


class HtmlBackend:
    def __init__(self, asset_root=None):
        # asset_root = the run dir where `figures/` lives. When set, SVGs are INLINED as data-URIs so
        # the report is self-contained (renders in a VSCode webview / email / a moved file). When None,
        # figures fall back to relative <img src> (only resolves in a browser opened from the run dir).
        self.asset_root = Path(asset_root) if asset_root else None
        self._handlers = {
            vocab.REPORT_HEADER: self._report_header,
            vocab.SKILL_HEADER: self._skill_header,
            vocab.CONFIDENCE: self._confidence,
            vocab.TENSION: self._tension,
            vocab.CLAIM_CHIPS: self._claim_chips,
            vocab.QUESTION_TABLE: self._question_table,
            vocab.PHASE_METRICS: self._phase_metrics,
            vocab.FIGURE: self._figure,
            vocab.PROVENANCE: self._provenance,
            vocab.UNMEASURED: self._unmeasured,
            vocab.ABOUT: self._about,
            vocab.SIGNALS_OVERVIEW: self._signals_overview,
            vocab.RISK_6DIM: self._risk_6dim,
            vocab.SYNTHESIS: self._synthesis,
            vocab.COHERENCE: self._coherence,
            vocab.MODALITY_MATRIX: self._modality_matrix,
            vocab.LITERATURE_RISK: self._literature_risk,
            vocab.DECIDING_AXIS: self._deciding_axis,
            vocab.FLIP_CONDITIONS: self._flip_conditions,
            vocab.SUBTYPE: self._subtype,
            vocab.BIOMARKER: self._biomarker,
            vocab.SYNTHESIS_BANNER: self._synthesis_banner,
            vocab.SYNTHESIS_NOTE: self._synthesis_note,
            vocab.SIGNALS_SCATTER: self._signals_scatter,
            vocab.SUBGROUP_BANDS: self._subgroup_bands,
            vocab.CROSS_CUTTING_QUESTIONS: self._cross_cutting,
            vocab.EVIDENCE_FINGERPRINT: self._evidence_fingerprint,
            vocab.CARD_CHAIN: self._card_chain,
            vocab.LITERATURE_AXES: self._literature_axes,
        }

    def handled_kinds(self) -> set:
        return set(self._handlers)

    # -- structure -----------------------------------------------------------------------------
    def render(self, ir: ReportIR) -> str:
        title = f"Target report — {_esc(ir.target or '—')} × {_esc(ir.indication or '—')}"
        parts = [
            "<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{title}</title><style>{_CSS}\n{_lens_css()}</style></head><body><div class='wrap'>",
        ]
        # the decision header + the advisory AI synthesis banner are persistent report chrome (above the
        # lens tabs) — the recommendation + the cross-lens exec summary stay visible on every lens.
        parts.append(self._wrap_card("".join(self._emit(ir.header)), extra="decision"))
        if getattr(ir, "banner", None) is not None:
            parts.append(self._wrap_card("".join(self._emit(ir.banner)), extra="narr"))
        lenses = ir.lenses()
        if lenses:
            parts.append(self._lens_tabs(lenses))          # faceted composed view: a tab per lens
        else:
            for b in ir.overview:                          # flat fallback (standalone / un-lensed IR)
                parts.append(self._wrap_card("".join(self._emit(b))))
            for sec in ir.sections:
                parts.append(self._emit_section(sec))
        if ir.about is not None:
            parts.append("".join(self._emit(ir.about)))
        parts.append("</div></body></html>")
        return "\n".join(parts) + "\n"

    def _lens_tabs(self, lenses) -> str:
        """The faceted lens-switcher: co-equal, full-width panels the reader toggles. Pure-CSS
        (radio-input + `:checked ~` sibling selectors — no JS, so it renders self-contained in a webview
        / email / moved file). All panels are in the DOM (only visibility toggles), so every backend
        surfaces the same content; the non-interactive backends linearize the same lenses as sections."""
        radios, navs, panels = [], [], []
        for i, (lid, title, items) in enumerate(lenses):
            checked = " checked" if i == 0 else ""
            radios.append(f"<input class='lens-radio' type='radio' name='lens' id='lp-{_esc(lid)}'{checked}>")
            navs.append(f"<label for='lp-{_esc(lid)}'>{_esc(title)}</label>")
            body = []
            for kind, item in items:
                if kind == "section":
                    # per-skill sections (Signals lens) collapse into a scannable list of signal rows;
                    # each expands into the full embedded sub-skill view.
                    body.append(self._emit_section(item, collapsed=(lid == vocab.LENS_SIGNALS)))
                else:
                    body.append(self._wrap_card("".join(self._emit(item))))
            panels.append(f"<section class='lens-panel ln-{_esc(lid)}'>{''.join(body)}</section>")
        return ("<div class='lens-tabs'>" + "".join(radios)
                + "<nav class='lens-nav' role='tablist'>" + "".join(navs) + "</nav>"
                + "".join(panels) + "</div>")

    def _emit(self, block: Block) -> list:
        return self._handlers[block.kind](block.payload)

    def _wrap_card(self, inner: str, extra: str = "") -> str:
        cls = f"card {extra}".strip()
        return f"<section class='{cls}'>{inner}</section>"

    def _emit_section(self, sec: Section, collapsed: bool = False) -> str:
        blocks = sec.blocks or []
        pol = blocks[0].payload.get("polarity") if blocks else None
        pol_cls = _POL_CLASS.get(pol or "", "")
        # collapsed (composed Signals lens): the skill header is the compact <summary> and the rest of the
        # embedded sub-skill view is the collapsed body — so 15 full views default to a light, scannable
        # list of signal rows (the deciding axis opens by default). blocks[0] is always the SKILL_HEADER.
        body_blocks = blocks[1:] if (collapsed and blocks) else blocks
        # FIGURE grouping: show the PRIMARY figure per card inline; collapse the rest into one
        # "N more figures" <details> so a dependency card with 18 plots is not a data-dump.
        parts, extra = [], []
        for b in body_blocks:
            if b.kind == vocab.FIGURE and not b.payload.get("primary"):
                extra.append(b)
                continue
            parts.append("".join(self._emit(b)))
        if extra:
            figs = "".join("".join(self._emit(b)) for b in extra)
            parts.append(f"<details class='fig-more'><summary>{len(extra)} more figure(s)</summary>"
                         f"{figs}</details>")
        inner = "".join(parts)
        if collapsed and blocks:
            summary = "".join(self._emit(blocks[0]))
            openattr = " open" if sec.is_deciding else ""
            cls = f"card {pol_cls} skill-collapse".replace("  ", " ").strip()
            return f"<details class='{cls}'{openattr}><summary>{summary}</summary>{inner}</details>"
        cls = f"card {pol_cls}".strip()
        return f"<section class='{cls}'>{inner}</section>"

    # -- handlers ------------------------------------------------------------------------------
    def _report_header(self, p: dict) -> list:
        tgt, ind = _esc(p.get("target") or "—"), _esc(p.get("indication") or "—")
        out = [f"<h1>{tgt} <span style='color:var(--muted);font-weight:520'>×</span> {ind}</h1>",
               "<p class='sub'>Target profile — evidence across 14 subskills; the recommendation is a "
               "subordinate summary of the signals below.</p>"]
        # LEAD with what the target IS (data-backed archetype characterization), before any verdict.
        char = p.get("characterization") or {}
        mix = char.get("mixture") or []
        if mix:
            chips = "".join(
                f"<span class='char-chip{' lead' if i == 0 else ''}'>{_esc(m.get('label'))}"
                f"<span class='w'>{int(round((m.get('weight') or 0)*100))}%</span></span>"
                for i, m in enumerate(mix))
            out.append("<div class='char'><div class='lbl'>Target characterization "
                       "(archetype membership vs. reference atlas)</div>" + chips + "</div>")
        if p.get("thesis"):
            out.append(f"<p class='kv'><b>Working thesis:</b> {_esc(_humanize(p['thesis']))} "
                       "<span class='prov'>(cross-axis coherence framing)</span></p>")
        rec = p.get("recommendation")
        if rec:
            klass = {"nominate": "go", "advance": "go", "go": "go",
                     "hold": "hold", "conditional": "hold", "watch": "hold",
                     "kill": "kill", "decline": "kill", "no": "kill", "drop": "kill"}.get(
                str(rec).strip().lower().split()[0], "")
            dec = (f" <span class='deciding'>deciding: {_esc(p['deciding_title'])}</span>"
                   if p.get("deciding_title") else "")
            ct = _confidence_summary(p.get("confidence"))
            conf = f" <span class='prov'>· confidence: {_esc(ct)}</span>" if ct else ""
            out.append(f"<p class='kv'><b>Provisional call:</b> "
                       f"<span class='rec {klass}'><span class='dot'></span>"
                       f"<span class='word'>{_esc(rec)}</span></span>{dec}{conf}</p>")
        dissent = p.get("dissent") or []
        if dissent:
            items = "".join(f"<li>{_esc(_dissent_summary(d))}</li>" for d in dissent)
            out.append(f"<p class='kv'><b>Dissent:</b> {len(dissent)} note(s)</p><ul class='chips'>{items}</ul>")
        return out

    def _skill_header(self, p: dict) -> list:
        glyph = vocab.polarity_glyph(p.get("polarity"))
        call = _humanize(p.get("call")) or None   # snake_case machine verdict → readable
        verdict = call or ("context (descriptive)" if p.get("role") in ("descriptive", "inert")
                           else vocab.polarity_label(p.get("polarity")))
        deciding = " <span class='deciding'>deciding axis</span>" if p.get("is_deciding") else ""
        out = [f"<div class='stitle'><span class='glyph'>{_esc(glyph)}</span>"
               f"{_esc(p.get('title'))} — {_esc(verdict)}{deciding}</div>"]
        if p.get("honest_phrase"):
            out.append(f"<div class='phrase'>{_esc(p['honest_phrase'])}</div>")
        return out

    def _confidence(self, p: dict) -> list:
        s = _confidence_summary(p.get("confidence"))
        return [f"<p class='kv'><b>Confidence:</b> {_esc(s)}</p>"] if s else []

    def _tension(self, p: dict) -> list:
        t = p.get("tension") or {}
        if not t.get("text"):
            return []
        sev = f" ({_esc(t['severity'])})" if t.get("severity") else ""
        return [f"<p class='kv'><b>Tension:</b> {_esc(t['text'])}{sev}</p>"]

    def _claim_chips(self, p: dict) -> list:
        chips = p.get("chips") or []
        if not chips:
            return []
        items = "".join(f"<li>{_esc(_chip_summary(c))}</li>" for c in chips)
        return [f"<p class='kv'><b>Signals</b> ({p.get('shown', len(chips))}/{p.get('total', len(chips))}):</p>"
                f"<ul class='chips'>{items}</ul>"]

    def _table(self, headers, rows) -> str:
        th = "".join(f"<th>{_esc(h)}</th>" for h in headers)
        trs = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"

    def _question_table(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        body = [[_qt_question(r), _qt_signal(r), _qt_conf(r)] for r in rows]
        return ["<p class='section-label'>Questions</p>", self._table(["question", "signal", "confidence"], body)]

    def _phase_metrics(self, p: dict) -> list:
        rows = [r for r in (p.get("rows") or []) if isinstance(r, dict)]
        if not rows:
            return []
        body = [[r.get("metric") or r.get("label"), r.get("value"),
                 r.get("sample_context") or r.get("context")] for r in rows]
        return ["<p class='section-label'>Metrics</p>", self._table(["metric", "value", "context"], body)]

    def _figure(self, p: dict) -> list:
        cap = _esc(p.get("caption") or "figure")
        ref = p.get("ref")
        badge = self._fig_badge(p.get("status"))
        if p.get("show_image") and ref:
            # inline only the PRIMARY (shown-inline) figures → self-contained + lean; the collapsed
            # "more figures" keep relative paths so the page doesn't balloon to megabytes.
            src = (self._inline_src(ref) if p.get("primary") else None) or _esc(ref)
            return [f"<figure><img src='{src}' alt='{cap}' loading='lazy'>"
                    f"<figcaption>{badge}{cap}</figcaption></figure>"]
        loc = f" <span class='prov'>[{_esc(ref)}]</span>" if ref else ""
        return [f"<p class='kv'>{badge}<b>Figure:</b> {cap}{loc}</p>"]

    def _inline_src(self, ref):
        """Read `asset_root/<ref>` and return an SVG data-URI, so the figure renders in any viewer
        (VSCode webview / email / moved file), not only a browser opened from the run dir. Returns None
        (→ caller falls back to the relative path) when there's no asset_root, the file is missing, it
        is not an SVG, or it exceeds the inline cap."""
        if not self.asset_root or not ref or not str(ref).lower().endswith(".svg"):
            return None
        try:
            fp = (self.asset_root / ref).resolve()
            if not str(fp).startswith(str(self.asset_root.resolve())):   # path-escape guard
                return None
            raw = fp.read_bytes()
            if not raw or len(raw) > _MAX_INLINE_SVG_BYTES:
                return None
            return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")
        except OSError:
            return None

    @staticmethod
    def _fig_badge(status) -> str:
        """The verdict pill beside a figure (reserved status palette, icon+label so it survives CVD /
        greyscale — never colour-alone). `context` is an outlined no-call, not a filled negative."""
        if not isinstance(status, dict) or not status.get("label"):
            return ""
        sig = _esc(status.get("signal") or "context")
        return (f"<span class='fig-badge sig-{sig}'>{_esc(status.get('icon') or '')} "
                f"{_esc(status.get('label'))}</span> ")

    def _provenance(self, p: dict) -> list:
        prov = p.get("provenance") or {}
        drv = _esc(prov.get("driving_rule_id") or "—")
        fired = len(prov.get("fired_rule_ids") or [])
        used = len(prov.get("cards_used") or [])
        missing = prov.get("cards_missing") or []
        line = f"driving rule {drv}; {fired} rule(s) fired; {used} card(s) used"
        if missing:
            line += f"; cards missing: {_esc(', '.join(map(str, missing)))}"
        return [f"<p class='prov'>{line}</p>"]

    def _unmeasured(self, p: dict) -> list:
        return [f"<p class='unmeasured'>{_esc(p.get('note') or 'not measured')}</p>"]

    def _about(self, p: dict) -> list:
        bits = []
        if p.get("note"):
            bits.append(_esc(p["note"]))
        leg = (p.get("polarity_legend") or {}).get("on_scale") or {}
        if leg:
            scale = ", ".join(f"{_esc(k)}={v:+d}" for k, v in sorted(leg.items(), key=lambda t: -t[1]))
            bits.append(f"Ordinal polarity scale (order-preserving, not metric): {scale}.")
        spec = p.get("spec") or {}
        if spec:
            bits.append(f"Spec: level={_esc(spec.get('level'))} · medium={_esc(spec.get('medium'))} · "
                        f"scope={_esc(spec.get('scope'))} · lead={_esc(spec.get('lead'))}.")
        return [f"<div class='about'>{'<br>'.join(bits)}</div>"]

    # -- report-level overview (absorbed tp_dashboard v2 IA, spine-sourced) --------------------
    def _signals_overview(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        c = p.get("counts") or {}
        svg = _signal_strip_svg(rows, p.get("deciding_short"))
        lede = ("<p class='lede'>Each bar is one <b>gating subskill's verdict</b>, rolled up from its "
                "evidence cards (count shown per row). Bar direction/length is the subskill's polarity on "
                "the framework's ordinal scale — right supports the target, left counts against; a dot is "
                "neutral, a dashed box is not-evaluated. Descriptive (non-gating) subskills are context, "
                "listed below, not bars.</p>")
        foot = (f"<p class='so-foot'><b>{c.get('support', 0)}</b> support · "
                f"<b>{c.get('neutral', 0)}</b> neutral · <b>{c.get('against', 0)}</b> against")
        desc = p.get("descriptive") or []
        if desc:
            foot += " &nbsp;·&nbsp; descriptive context: " + _esc(", ".join(desc))
        foot += "</p>"
        return [f"<h2>Signals across subskills</h2>{lede}<div class='signal-strip'>{svg}</div>{foot}"]

    def _risk_6dim(self, p: dict) -> list:
        dims = p.get("dims") or []
        if not dims:
            return []
        tiles = []
        for d in dims:
            rank = d.get("rank")
            cls = {3: "rt-high", 2: "rt-med", 1: "rt-low"}.get(rank, "rt-blind")
            lab = d.get("bin") or "n/e"
            tiles.append(f"<div class='risk-tile {cls}'><div class='rt-dim'>{_esc(str(d.get('dim')).title())}"
                         f"</div><div class='rt-bin'>{_esc(lab)}</div></div>")
        return [f"<h2>Risk by dimension</h2><div class='risk-tiles'>{''.join(tiles)}</div>"]

    def _synthesis(self, p: dict) -> list:
        out = ["<span class='tag'>AI-generated</span><h2>Synthesis</h2>"]
        _GLYPH = {"supportive": "△", "opposing": "▽", "killer": "▲", "neutral": "◆", "not_applicable": "·"}
        _CLS = {"supportive": "g-sup", "opposing": "g-opp", "killer": "g-kill", "neutral": "g-neu"}
        bullets = p.get("exec_bullets") or []
        if bullets:
            lis = []
            for b in bullets:
                pol = b.get("polarity")
                anchors = (b.get("cites") or {})
                ids = (anchors.get("card_ids") or []) + (anchors.get("citation_ids") or [])
                anc = (f" <span class='ke-anchor'>[{_esc(', '.join(ids[:3]))}]</span>") if ids else ""
                lis.append(f"<li><span class='{_CLS.get(pol,'g-neu')}'>{_GLYPH.get(pol,'•')}</span> "
                           f"{_esc(b.get('text'))}{anc}</li>")
            out.append("<ul class='exec-bullets'>" + "".join(lis) + "</ul>")
        verbose_frag = []
        if p.get("executive_summary"):
            verbose_frag.append(f"<p>{_esc(p['executive_summary'])}</p>")
        if p.get("tension_analysis"):
            verbose_frag.append(f"<p class='kv'><b>Tensions:</b> {_esc(p['tension_analysis'])}</p>")
        args = p.get("arguments") or []
        if args:
            verbose_frag.append("<ul class='chips'>"
                                + "".join(f"<li>{_esc(_arg_summary(a))}</li>" for a in args) + "</ul>")
        if verbose_frag:
            # bullets lead; the verbose prose is demoted behind an expander (Stage-2 secondary read).
            if bullets:
                out.append("<details class='full-narrative'><summary>Full narrative</summary>"
                           + "".join(verbose_frag) + "</details>")
            else:
                out.extend(verbose_frag)
        cites = p.get("citations") or []
        if cites:
            # rule-ids lifted out of the prose → a collapsed grounding affordance (hover/expand), so the
            # executive text reads clean while the provenance stays one click away.
            codes = "".join(f"<code>{_esc(c)}</code>" for c in cites)
            out.append(f"<details class='cite-prov'><summary>Grounded in {len(cites)} framework "
                       f"rules</summary>{codes}</details>")
        return out

    def _coherence(self, p: dict) -> list:
        # thesis is in the header; this block adds the coherence class + any caveats.
        out = []
        if p.get("coherence"):
            out.append(f"<p class='kv'><b>Coherence:</b> {_esc(_humanize(p['coherence']))}</p>")
        cav = p.get("caveats") or []
        if cav:
            out.append("<ul class='chips'>" + "".join(f"<li>{_esc(c)}</li>" for c in cav) + "</ul>")
        return out

    _CELL_CLASS = {"supportive": "mx-pos", "neutral": "mx-zero", "opposing": "mx-neg",
                   "killer": "mx-killer"}
    _MOD_ICON = {"viable": "✓", "conditional": "~", "unfavorable": "✕", "not_applicable": "⊘",
                 "killer": "✕"}
    _AXIS_STATUS = {"favorable": "viable", "viable": "viable", "conditional": "conditional",
                    "unfavorable": "unfavorable", "killer": "killer", "opposing": "unfavorable"}

    def _modality_matrix(self, p: dict) -> list:
        """Per-modality FIT readout (from modality_fit_by_channel) — a status list, not an ordinal grid.
        The raw gate×modality grid is retained as a drill-down (it keeps the killer-vs-opposing shape)."""
        channels = p.get("channels") or []
        cols, rows = p.get("columns") or [], p.get("rows") or []
        if not channels and not (cols and rows):
            return []
        out = ["<h2>Modality fit <span class='so-foot'>— which drug format is viable, and why</span></h2>"]
        if channels:
            applic = [c for c in channels if c.get("status") != "not_applicable"]
            na = [c for c in channels if c.get("status") == "not_applicable"]
            out.append(f"<p class='lede'>{self._mod_lede(applic, na)}</p>")
            body = [self._mod_row(c) for c in applic]
            if na:
                names = " · ".join(c.get("name", "") for c in na)
                reason = next((_humanize(c.get("masked_by_axis")) for c in na if c.get("masked_by_axis")),
                              "not applicable to this target's biology")
                body.append(f"<div class='mod-row na'><span class='mod-name'>{_esc(names)}</span>"
                            f"<span class='pill not_applicable'><span class='ic'>⊘</span>Not applicable</span>"
                            f"<span class='mod-why'>{_esc(reason)}</span></div>")
            out.append("<div class='mod-fit'>" + "".join(body) + "</div>")
        if cols and rows:
            out.append(self._modality_grid_details(cols, rows, p))
        return out

    def _mod_lede(self, applic: list, na: list) -> str:
        viable = [c["name"] for c in applic if c.get("status") == "viable"]
        cond = [c["name"] for c in applic if c.get("status") == "conditional"]
        if viable:
            s = f"Viable route(s): <b>{_esc(', '.join(viable))}</b>."
        elif cond:
            s = f"No clearly viable format; <b>{_esc(', '.join(cond))}</b> conditional on de-risking."
        else:
            s = "No clearly viable format among the applicable modalities."
        lims = sorted({vocab.skill_title(c["limiting_axis"]) for c in applic if c.get("limiting_axis")})
        if lims:
            s += f" Held back by <b>{_esc(', '.join(lims))}</b>."
        if na:
            s += f" {len(na)} surface format(s) not applicable to this target's biology."
        return s

    def _mod_row(self, c: dict) -> str:
        st = c.get("status") or "unfavorable"
        ic = self._MOD_ICON.get(st, "")
        why = (f"Limited by <b>{_esc(vocab.skill_title(c['limiting_axis']))}</b>"
               if c.get("limiting_axis") else "")
        chips = ""
        for ax, val in (c.get("by_axis") or {}).items():
            astat = self._AXIS_STATUS.get(val, "unfavorable")
            chips += (f"<span class='axis-chip {astat}'><span class='ic'>{self._MOD_ICON.get(astat, '')}"
                      f"</span>{_esc(vocab.skill_title(ax))}</span>")
        return (f"<div class='mod-row'><span class='mod-name'>{_esc(c.get('name'))}</span>"
                f"<span class='pill {st}'><span class='ic'>{ic}</span>{_esc(c.get('label'))}</span>"
                f"<span class='mod-why'>{why} {chips}</span></div>")

    def _modality_grid_details(self, cols: list, rows: list, p: dict) -> str:
        from ...ordinal_view import _cell_glyph
        head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
        trs = []
        for r in rows:
            cells = r.get("cells") or {}
            tds = ""
            for m in cols:
                cell = cells.get(m) or {}
                cls = self._CELL_CLASS.get(cell.get("signal"), "mx-off") if cell.get("on_scale") else "mx-off"
                tds += f"<td class='{cls}'>{_esc(_cell_glyph(cell))}</td>"
            trs.append(f"<tr><td>{_esc(vocab.skill_title(r.get('short')))}</td>{tds}"
                       f"<td>{_esc(_humanize(r.get('verdict')) if r.get('verdict') else '—')}</td></tr>")
        legend = f"<p class='so-foot'>{_esc(p['glyph_legend'])}</p>" if p.get("glyph_legend") else ""
        disc = f"<p class='prov'>{_esc(p['disclaimer'])}</p>" if p.get("disclaimer") else ""
        return (f"<details class='cite-prov'><summary>Per-axis × modality detail (raw ordinal grid + "
                f"caveats)</summary><table><thead><tr><th>Axis (gate)</th>{head}<th>Verdict</th></tr>"
                f"</thead><tbody>{''.join(trs)}</tbody></table>{legend}{disc}</details>")

    def _literature_risk(self, p: dict) -> list:
        dims = p.get("dims") or []
        if not dims:
            return []
        trs = []
        for d in dims:
            pm = d.get("pmids") or []
            pmtxt = f" <span class='prov'>({len(pm)} PMIDs)</span>" if pm else ""
            trs.append(f"<tr><td>{_esc(d.get('dim'))}</td><td>{_esc(d.get('risk_level') or '—')}</td>"
                       f"<td>{_esc(d.get('interpretation') or '')}{pmtxt}</td></tr>")
        return ["<h2>Literature risk <span class='so-foot'>— context, never a gate</span></h2>"
                f"<table><thead><tr><th>Dimension</th><th>Risk</th><th>Interpretation</th></tr></thead>"
                f"<tbody>{''.join(trs)}</tbody></table>"]

    def _deciding_axis(self, p: dict) -> list:
        axes = p.get("axes") or []
        name = ", ".join(axes) if axes else (p.get("title") or p.get("short"))
        detail = _esc(p.get("routing") or (_humanize(p.get("basis")) if p.get("basis") else ""))
        if name:
            body = f"<b>{_esc(name)}</b>" + (f" — {detail}" if detail else "")
        else:
            # no NAMED axis — lead with the routing, never an empty "— —" pair.
            body = detail or "—"
        return [f"<h2>Deciding axis</h2><p class='kv'>{body}</p>"]

    def _flip_conditions(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        items = []
        for r in rows:
            tv = _esc(_humanize(r.get("to_verdict")) or "a different call")
            dirn = f" <span class='so-foot'>({_esc(r['direction'])})</span>" if r.get("direction") else ""
            if r.get("present"):
                cond = _esc(_humanize(r.get("condition")) or "a load-bearing signal")
                items.append(f"<li><b>{_esc(r['axis'])}</b>: the call rests on {cond} — "
                             f"absent it → {tv}{dirn}</li>")
            else:
                items.append(f"<li><b>{_esc(r['axis'])}</b>: would become {tv}{dirn}</li>")
        return [f"<h2>What would change the call</h2><ul class='chips'>{''.join(items)}</ul>"]

    def _subtype(self, p: dict) -> list:
        if not p.get("verdict") and not p.get("subtypes"):
            return []
        axes = _esc(", ".join(p.get("axes_available") or []) or "—")
        out = ["<h2>Subtype stratification</h2>",
               f"<p class='kv'><b>Verdict:</b> {_esc(_humanize(p.get('verdict')))} "
               f"<span class='so-foot'>({p.get('n_evaluated', 0)} subtypes on {axes})</span></p>"]
        for label, key in (("Convergent", "convergent_subtypes"), ("Associated", "associated_subtypes"),
                           ("Evaluated", "subtypes")):
            vals = p.get(key) or []
            if vals:
                out.append(f"<p class='kv'><b>{label}:</b> {_esc(', '.join(map(str, vals)))}</p>")
        return out

    def _biomarker(self, p: dict) -> list:
        if not p.get("verdict"):
            return []
        out = ["<h2>Patient-selection biomarker</h2>"]
        head = f"<p class='kv'><b>Verdict:</b> {_esc(_humanize(p['verdict']))}"
        if p.get("preferred_assay"):
            head += f" · preferred assay: {_esc(_humanize(p['preferred_assay']))}"
        out.append(head + "</p>")
        strat = []
        for lab, key in (("driver role", "alteration_role"), ("mutation stratification", "mutation_stratification"),
                         ("subtype stratification", "subtype_stratification"), ("survival", "survival_association")):
            if p.get(key):
                strat.append(f"{lab}: {_esc(_humanize(p[key]))}")
        if strat:
            out.append("<p class='kv'>" + "; ".join(strat) + "</p>")
        uses = p.get("intended_uses") or []
        if uses:
            out.append(f"<p class='kv'><b>Intended uses:</b> {_esc(', '.join(_humanize(u) for u in uses))}</p>")
        hyps = p.get("hypotheses") or []
        if hyps:
            li = "".join(
                f"<li>{_esc(_humanize(h.get('intended_use')))}: {_esc(_humanize(h.get('basis')))}"
                + (f" <span class='so-foot'>[{_esc(h.get('evidence_strength'))}]</span>"
                   if h.get("evidence_strength") else "") + "</li>"
                for h in hyps)
            out.append(f"<ul class='chips'>{li}</ul>")
        return out

    # -- faceted-rollup blocks (PR2) -----------------------------------------------------------
    def _synthesis_banner(self, p: dict) -> list:
        out = ["<span class='tag'>AI-generated · advisory</span>"
               "<span class='so-foot'> — does not set the call</span>"]
        if p.get("executive_summary"):
            out.append(f"<p>{_esc(p['executive_summary'])}</p>")
        mm = p.get("mismatch")
        if isinstance(mm, dict) and mm.get("deterministic"):
            out.append(f"<p class='kv mismatch'>⚠ <b>LLM read:</b> {_esc(mm.get('llm'))} · "
                       f"<b>deterministic call:</b> {_esc(mm['deterministic'])} — mismatch flagged "
                       f"<span class='so-foot'>(the deterministic call stands)</span></p>")
        cites = p.get("citations") or []
        if cites:
            codes = "".join(f"<code>{_esc(c)}</code>" for c in cites)
            out.append(f"<details class='cite-prov'><summary>Grounded in {len(cites)} framework "
                       f"rules</summary>{codes}</details>")
        return out

    def _synthesis_note(self, p: dict) -> list:
        notes = p.get("notes") or []
        if not notes:
            return []
        items = []
        for n in notes:
            stance = (n.get("stance") or "").strip()
            ic = {"for": "▲", "against": "▽", "tension": "⚖"}.get(stance, "·")
            cls = {"for": "g-sup", "against": "g-opp", "tension": "g-warn"}.get(stance, "")
            items.append(f"<li><span class='{cls}'>{ic}</span> {_esc(n.get('text', ''))}</li>")
        return ["<p class='section-label'>AI read <span class='so-foot'>· advisory</span></p>"
                f"<ul class='chips notes'>{''.join(items)}</ul>"]

    def _signals_scatter(self, p: dict) -> list:
        pts = p.get("points") or []
        if not pts:
            return []
        is_sg = p.get("scope") == "subgroups"
        rpoints = []
        for pt in pts:
            if is_sg:
                color, glyph = ("var(--blue)", "●")
            else:
                pol = pt.get("polarity")
                color = {"supportive": "var(--supportive)", "opposing": "var(--opposing)",
                         "killer": "var(--killer)", "neutral": "var(--neutral)"}.get(pol, "var(--neutral)")
                glyph = vocab.polarity_glyph(pol)
            rpoints.append({"x": pt.get("confidence_x"), "y": pt.get("signal_y"),
                            "label": (pt.get("name") if is_sg else pt.get("title")) or "",
                            "color": color, "glyph": glyph,
                            "ring": bool(pt.get("conflict")), "deciding": bool(pt.get("is_deciding"))})
        title = "Signals × confidence" + (" — sub-groups" if is_sg else "")
        svg = _scatter_svg(rpoints, p.get("y_ticks") or [], p.get("x_ticks") or [])
        head = (f"<p class='section-label'>{_esc(title)}</p>" if is_sg
                else f"<h2>{_esc(title)} <span class='so-foot'>— each point is a gating subskill; "
                     f"x = confidence, y = signal strength, colour = direction</span></h2>")
        return [f"{head}<div class='scatter-wrap'>{svg}</div>"]

    def _subgroup_bands(self, p: dict) -> list:
        rows = p.get("sub_groups") or []
        if not rows:
            return []
        body = []
        for r in rows:
            conf = _esc(_humanize(r.get("confidence")))
            src = f"{r.get('n_agree', 0)}/{r.get('n_sources', 0)}"
            warn = " <span class='conflict'>⚠</span>" if r.get("conflict") else ""
            body.append([_esc(r.get("name")), _esc(r.get("signal")), conf, src + warn])
        return ["<p class='section-label'>Sub-group bands</p>",
                self._table(["sub-group", "signal", "confidence", "sources"], body)]

    def _cross_cutting(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        body = [[_esc(r.get("question")), _esc(r.get("owner")), _esc(_humanize(r.get("informs")))]
                for r in rows]
        return ["<h2>Cross-cutting questions <span class='so-foot'>— measured by one axis, informs "
                "another</span></h2>", self._table(["question", "measured by", "informs"], body)]

    # -- evidence-graph blocks (P3): the RICH embedded view == the standalone dashboard ----------
    _EG_POL_COLOR = {"supportive": "var(--supportive)", "opposing": "var(--opposing)",
                     "killer": "var(--killer)", "neutral": "var(--neutral)"}
    _EG_POL_CLS = {"supportive": "g-sup", "opposing": "g-opp", "killer": "g-kil", "neutral": "g-neu"}
    _EG_DOTS_OPACITY = {3: "1", 2: ".6", 1: ".38", 0: ".3"}

    def _eg_color(self, polarity, liability=False) -> str:
        if liability:
            return "var(--killer)"
        return self._EG_POL_COLOR.get(polarity, "var(--neutral)")

    def _evidence_fingerprint(self, p: dict) -> list:
        qs = p.get("questions") or []
        if not qs:
            return []
        groups = []
        for q in qs:
            gcls = self._EG_POL_CLS.get(q.get("polarity"), "g-neu")
            glyph = vocab.polarity_glyph(q.get("polarity"))
            cells = []
            for c in (q.get("cells") or []):
                col = self._eg_color(c.get("polarity"), c.get("liability"))
                op = self._EG_DOTS_OPACITY.get(c.get("dots") if isinstance(c.get("dots"), int) else -1, ".3")
                tip = f"{c.get('card_id')} · {c.get('polarity')}" + (" · liability" if c.get("liability") else "")
                cells.append(f"<span class='hmcell' title='{_esc(tip)}' "
                             f"style='background:{col};opacity:{op}'></span>")
            lit = q.get("lit")
            if lit:
                agr = lit.get("agreement") or lit.get("read")
                lcol = {"agree": "var(--supportive)", "mixed": "var(--opposing)",
                        "contradicts": "var(--killer)"}.get(agr, "var(--neutral)")
                mark = "“" if lit.get("cited") else "·"
                litdot = (f"<span class='hmsep'></span><span class='litdot' style='background:{lcol}' "
                          f"title='literature · {_esc(str(lit.get('read')))} · {_esc(str(agr))}'>{mark}</span>")
            else:
                litdot = ("<span class='hmsep'></span><span class='litdot' style='opacity:.25' "
                          "title='no literature for this question'>·</span>")
            lbl = _esc(q.get("text") or q.get("id") or "")
            groups.append(f"<div class='hmg'><div class='hmglab'><span class='{gcls}'>{_esc(glyph)}</span> {lbl}</div>"
                          f"<div class='hmcells'>{''.join(cells)}{litdot}</div></div>")
        note = ("<div class='hmnote'>▪ card — colour = signal (green supportive · amber opposing · red "
                "liability/killer · grey neutral), opacity = confidence &nbsp;·&nbsp; ● literature "
                "(colour = agreement · “ cited · · none)</div>")
        return ["<h2>Evidence fingerprint <span class='so-foot'>— per question: one cell per contributing "
                "card (colour = signal, opacity = confidence); literature dot colour = agreement</span></h2>"
                f"<div class='eg-inner'><div class='hm'>{''.join(groups)}</div>{note}</div>"]

    def _gauge(self, c: dict) -> str:
        """Visual reference-frame ruler for a card's interpretation[0] — a track with floor/cut/ceiling
        (or comparator) ticks + a polarity-coloured value marker, captioned by the plain gauge words. On a
        plain numeric axis (min→max of the points) so the marker placement can't invert; the words carry
        the past/short-of-cut reading. '' when the card has no ruler."""
        interp = c.get("interpretation") or []
        gv = interp[0] if interp and isinstance(interp[0], dict) else None
        words = c.get("gauge")
        if not gv or gv.get("value") is None:
            return ""
        val = gv.get("value")
        anchors = [a for a in ((gv.get("frame") or {}).get("anchors") or [])
                   if isinstance(a, dict) and isinstance(a.get("value"), (int, float)) and not isinstance(a.get("value"), bool)]
        pts = ([val] if isinstance(val, (int, float)) and not isinstance(val, bool) else []) + [a["value"] for a in anchors]
        if len(pts) < 2:                                  # not enough to draw a track — words only
            return f"<div class='gauge'><div class='gcap'>{_esc(words)}</div></div>" if words else ""
        lo, hi = min(pts), max(pts)
        span = (hi - lo) or 1.0

        def _pos(x):
            return max(0.0, min(100.0, (x - lo) / span * 100.0))

        def _alab(a):
            return str(a.get("label") or a.get("role") or "").replace("_", " ")

        ticks = []
        comp_mark = ""
        for a in anchors:
            if a.get("role") == "comparator":
                comp_mark = (f"<span class='gmark gcomp' style='left:{_pos(a['value']):.1f}%;"
                             f"color:var(--muted)' title='{_esc(_alab(a))} {_esc(a['value'])}'></span>")
                continue
            cls = "gtick gcut" if a.get("role") == "cut" else "gtick"
            ticks.append(f"<span class='{cls}' style='left:{_pos(a['value']):.1f}%'>"
                         f"<span class='gtlab'>{_esc(_alab(a))}</span></span>")
        key = "killer" if c.get("liability") else c.get("polarity")
        color = self._EG_POL_COLOR.get(key, "var(--neutral)")
        mark = (f"<span class='gmark' style='left:{_pos(val):.1f}%;color:{color}' "
                f"title='{_esc(gv.get('metric'))} {_esc(val)}'></span>")
        cap = f"<div class='gcap'>{_esc(words)}</div>" if words else ""
        return (f"<div class='gauge'><div class='gtrack'><span class='grail'></span>"
                f"{''.join(ticks)}{comp_mark}{mark}</div>{cap}</div>")

    def _card_chain(self, p: dict) -> list:
        layers = p.get("layers") or []
        if not layers:
            return []
        out = ["<p class='section-label'>Cards — dataset → data → rule → verdict</p>"]
        for lyr in layers:
            cards = lyr.get("cards") or []
            rows = []
            for c in cards:
                key = "killer" if c.get("liability") else c.get("polarity")
                gl, gcls = vocab.polarity_glyph(key), self._EG_POL_CLS.get(key, "g-neu")
                ds = " · ".join(c.get("dataset_ids") or []) or "—"
                data = " · ".join(f"{_esc(d.get('field'))}={_esc(d.get('value'))}"
                                  for d in (c.get("data") or [])) or "—"
                if c.get("rule_id"):
                    drv = "<span class='pill-drv'>DRIVING</span> " if c.get("is_driving") else ""
                    rule = f"{drv}<span class='mono'>{_esc(c.get('rule_id'))}</span>"
                else:
                    rule = "<span class='pill-none'>display-only · no rule fired</span>"
                nfrag = f" · n={_esc(c.get('n'))}" if c.get("n") is not None else ""
                ke = c.get("key_evidence_summary")
                ke_line = (f"<div class='chainline keyev'><span class='lab'>key</span> "
                           f"<span class='mono'>{_esc(ke)}</span></div>") if ke else ""
                # class-led plain-language order: description → Reads: <class> → key gauge → chain drill
                desc = c.get("description")
                desc_line = f"<div class='cdesc'>{_esc(desc)}</div>" if desc else ""
                reads = c.get("reads")
                reads_line = (f"<div class='cread'>Reads: <b class='{gcls}'>{_esc(reads)}</b></div>"
                              if reads else "")
                gauge = self._gauge(c)                       # the reference-frame ruler (support layer)
                rows.append(
                    f"<div class='cardln'><div class='chead'><span><b>{_esc(c.get('id'))}</b></span>"
                    f"<span class='ccchip'><span class='{gcls}'>{_esc(gl)}</span>{nfrag}</span></div>"
                    f"{desc_line}{reads_line}{gauge}{ke_line}"
                    f"<div class='chainline'><span class='lab'>ds</span> <span class='mono'>{_esc(ds)}</span>"
                    f" <span class='sep'>→</span> <span class='lab'>data</span> {data}"
                    f" <span class='sep'>→</span> <span class='lab'>rule</span> {rule}</div></div>")
            out.append(f"<details class='pklayer'><summary><span>{_esc(lyr.get('layer'))}</span>"
                       f"<span class='ccinline'>{len(cards)} card(s)</span></summary>"
                       f"<div class='lbody'>{''.join(rows)}</div></details>")
        return out

    def _literature_axes(self, p: dict) -> list:
        axes = p.get("axes") or []
        blind = p.get("blind_spots") or []
        if not axes and not blind:
            return []

        def _cite_pills(cites):
            out = []
            for c in (cites or []):
                lbl = c.get("label") or "citation"
                pmid = f" · PMID {c.get('pmid')}" if c.get("pmid") else ""
                vf = " ✓" if c.get("verified") else ""
                out.append(f"<span class='cite-pill'>{_esc(lbl)}{_esc(pmid)}{vf}</span>")
            return "".join(out)

        rows = []
        for a in axes:
            agr = a.get("agreement") or a.get("read")
            acls = {"agree": "g-sup", "mixed": "g-opp", "contradicts": "g-kil"}.get(agr, "")
            qs = ", ".join(a.get("question_ids") or [])
            qtag = f" · →{_esc(qs)}" if qs else ""
            rows.append(
                f"<div class='cardln'><div class='chead'><span>axis {_esc(a.get('axis_id'))} — "
                f"<b>{_esc(a.get('read'))}</b></span><span class='ccchip'><span class='{acls}'>{_esc(agr)}</span>"
                f" · {_esc(a.get('confidence'))}{qtag}</span></div>"
                f"{_esc(a.get('assertion') or '')} {_cite_pills(a.get('citations'))}</div>")
        for b in blind:
            why = f" <span class='so-foot'>{_esc(b.get('why_omics_blind'))}</span>" if b.get("why_omics_blind") else ""
            rows.append(f"<div class='cardln'><div class='chead'><span>blind spot</span></div>"
                        f"{_esc(b.get('text') or '')}{why} {_cite_pills(b.get('citations'))}</div>")
        oc = p.get("overall_consistency")
        head = ("<h2>Literature <span class='so-foot'>— per-axis agreement vs omics"
                f"{(' · overall ' + _esc(oc)) if oc else ''}</span></h2>")
        return [head + "".join(rows)]


def _scatter_svg(points, y_ticks, x_ticks) -> str:
    """A compact grid scatter: x = confidence (x_ticks left→right), y = signal (y_ticks bottom→top).
    Position encodes value; colour + glyph carry direction (CVD-safe). A point with unknown confidence
    (x=None) is pinned at the left 'low' column. Overlapping points in a cell fan out horizontally."""
    if not points or not y_ticks or not x_ticks:
        return ""
    ny, nx = len(y_ticks), len(x_ticks)
    L, T, B, RGT = 96, 16, 42, 150
    cellw, cellh = 150, 44
    W, H = L + nx * cellw + RGT, T + ny * cellh + B
    ink, muted, line = "#141c26", "#6b7783", "#d5dde4"
    s = [f"<svg viewBox='0 0 {W} {H}' width='100%' role='img' aria-label='signal by confidence' "
         f"style='font-family:-apple-system,Segoe UI,sans-serif'>"]
    # gridlines + y tick labels (bottom→top)
    for yi, yt in enumerate(y_ticks):
        y = T + (ny - 1 - yi) * cellh + cellh / 2
        s.append(f"<line x1='{L}' y1='{y:.1f}' x2='{L + nx * cellw}' y2='{y:.1f}' stroke='{line}' "
                 f"stroke-width='1'/>")
        s.append(f"<text x='{L - 8}' y='{y + 4:.1f}' text-anchor='end' font-size='11' fill='{muted}'>"
                 f"{_esc(yt)}</text>")
    # x tick labels
    for xi, xt in enumerate(x_ticks):
        x = L + (xi + 0.5) * cellw
        s.append(f"<text x='{x:.1f}' y='{H - B + 26}' text-anchor='middle' font-size='11' fill='{muted}'>"
                 f"{_esc(xt)}</text>")
    s.append(f"<text x='{L + nx * cellw}' y='{H - B + 26}' text-anchor='end' font-size='10.5' "
             f"fill='{muted}'>confidence →</text>")
    # points, fanned out within a shared cell
    from collections import defaultdict
    cell = defaultdict(list)
    for pt in points:
        cell[(pt.get("x"), pt.get("y"))].append(pt)
    for (xi, yi), pts in cell.items():
        col = 0 if xi is None else xi
        base_x = L + (col + 0.5) * cellw
        y = T + (ny - 1 - (yi or 0)) * cellh + cellh / 2
        k = len(pts)
        for j, pt in enumerate(pts):
            dx = (j - (k - 1) / 2) * 15
            px = base_x + dx
            ring = ("<circle cx='%.1f' cy='%.1f' r='9' fill='none' stroke='#b26a00' "
                    "stroke-width='1.5'/>" % (px, y)) if pt.get("ring") else ""
            dec = "  ◆" if pt.get("deciding") else ""
            s.append(ring)
            s.append(f"<circle cx='{px:.1f}' cy='{y:.1f}' r='6' fill='{pt['color']}' "
                     f"stroke='#fff' stroke-width='1.5'/>")
            s.append(f"<text x='{px + 9:.1f}' y='{y + 4:.1f}' font-size='11' fill='{ink}'>"
                     f"{_esc(pt['label'])}{dec}</text>")
    s.append("</svg>")
    return "".join(s)


def _lens_css() -> str:
    """CSS for the faceted lens-switcher, generated for the known lenses (vocab.LENS_ORDER) so the
    `:checked ~` visibility/active rules exist for whatever lens ids the builder emits. Kept out of the
    static _CSS block so it tracks LENS_ORDER without hand-editing."""
    active = ",\n".join(f"#lp-{l}:checked ~ .lens-nav label[for=lp-{l}]" for l in vocab.LENS_ORDER)
    visible = ",\n".join(f"#lp-{l}:checked ~ .lens-panel.ln-{l}" for l in vocab.LENS_ORDER)
    base = (
        ".lens-tabs input.lens-radio{position:absolute;width:0;height:0;opacity:0;pointer-events:none;}"
        ".lens-nav{display:flex;gap:4px;flex-wrap:wrap;border-bottom:2px solid var(--border);"
        "margin:22px 0 18px;}"
        ".lens-nav label{padding:8px 16px;cursor:pointer;font-weight:640;font-size:14px;color:var(--muted);"
        "border:1px solid transparent;border-bottom:none;border-radius:10px 10px 0 0;margin-bottom:-2px;}"
        ".lens-nav label:hover{color:var(--ink2);}"
        ".lens-panel{display:none;}"
    )
    if not vocab.LENS_ORDER:
        return base
    return (base
            + f"{active}{{color:var(--ink);border-color:var(--border);"
              f"border-bottom-color:var(--surface);background:var(--surface);}}"
            + f"{visible}{{display:block;}}")


def _signal_strip_svg(rows, deciding_short) -> str:
    """Inline diverging-strip SVG (self-contained, both embed modes): one row per scored skill, bars
    right = supports / left = counts-against, width ∝ |ordinal level|; neutral = a dot, off-scale = a
    dashed hollow square (a gap, NOT 'worst'). Direction is encoded by side + label too (CVD-safe).
    Ported from the tp_dashboard v2 design; fed from the spine's canonical polarity level."""
    # worst-first (killer −3 → supportive +2), matching the killers-lead per-skill section order;
    # off-scale (level None) trails. (Was descending → supportive-first, contradicting the sections.)
    def _key(r):
        lv = r.get("level")
        return (0, lv) if lv is not None else (1, 0)
    rows = sorted(rows, key=_key)
    n = len(rows)
    LBL, AX = 300, 122
    UNIT = AX / 3.0
    W, RH, TOP, BOT = LBL + 2 * AX + 16, 34, 30, 10
    H, cx = TOP + n * RH + BOT, LBL + AX
    pos, neg, neu, gap, ink, muted, line = ("#1a6b1a", "#a1231d", "#8a5a00", "#8592a0",
                                            "#141c26", "#6b7783", "#d5dde4")
    s = [f"<svg viewBox='0 0 {W} {H}' width='100%' role='img' aria-label='Signal per skill' "
         f"style='font-family:-apple-system,Segoe UI,sans-serif'>",
         f"<text x='{cx-6}' y='16' text-anchor='end' font-size='10.5' font-weight='700' fill='{neg}'>"
         f"◀ counts against</text>",
         f"<text x='{cx+6}' y='16' text-anchor='start' font-size='10.5' font-weight='700' fill='{pos}'>"
         f"supports ▶</text>",
         f"<line x1='{cx}' y1='{TOP-4}' x2='{cx}' y2='{H-BOT+2}' stroke='{line}' stroke-width='1.5'/>"]
    for i, r in enumerate(rows):
        cyr = TOP + i * RH + RH / 2
        lv = r.get("level")
        dec = "  ◆ deciding" if r.get("is_deciding") else ""
        # plain-language sublabel: prefer the honest_phrase, fall back to a de-snake-cased call.
        sub = r.get("honest_phrase") or _humanize(r.get("call")) or r.get("polarity") or ""
        s.append(f"<text x='{LBL-14}' y='{cyr-2:.1f}' text-anchor='end' font-size='12.5' fill='{ink}'>"
                 f"{_esc(r.get('title'))}</text>")
        # a thesis-expected negative renders as a neutral dot; append the reason so the reframe is explicit.
        note = f"  · {r['expected_note']}" if r.get("expected_note") else ""
        nc = r.get("n_cards")
        cards = f"  · {nc} cards" if nc else ""       # where the signal comes from (rollup provenance)
        vline = _esc(str(sub) + note + cards) + ("  · not evaluated" if lv is None else "") + dec
        s.append(f"<text x='{LBL-14}' y='{cyr+12:.1f}' text-anchor='end' font-size='10.5' "
                 f"fill='{muted}'>{vline}</text>")
        if lv is None:
            s.append(f"<rect x='{cx-6}' y='{cyr-6:.1f}' width='12' height='12' rx='2' fill='none' "
                     f"stroke='{gap}' stroke-width='1.5' stroke-dasharray='2 2'/>")
        elif lv == 0:
            s.append(f"<circle cx='{cx}' cy='{cyr:.1f}' r='5.5' fill='none' stroke='{neu}' stroke-width='2'/>")
        else:
            w = abs(lv) * UNIT
            col = pos if lv > 0 else neg
            bx = cx if lv > 0 else cx - w
            s.append(f"<rect x='{bx:.1f}' y='{cyr-7:.1f}' width='{w:.1f}' height='14' rx='4' fill='{col}'/>")
    s.append("</svg>")
    return "".join(s)


# reuse the text backend's shape-tolerant summarizers (single source, no vocab drift).
from .text import (_arg_summary, _chip_summary, _confidence_summary, _dissent_summary,  # noqa: E402
                   _humanize, _qt_conf, _qt_question, _qt_signal)

__all__ = ["HtmlBackend"]
