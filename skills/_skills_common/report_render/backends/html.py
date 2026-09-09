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

_MAX_INLINE_SVG_BYTES = 120_000  # inline the small decision-relevant plots (histograms/forests/bars/
# gauges); a giant per-point matplotlib scatter (100s of KB) falls back
# to a relative <img> rather than balloon the page past a few MB.

_POL_CLASS = {
    "killer": "pol-killer",
    "opposing": "pol-opposing",
    "neutral": "pol-neutral",
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
  /* ── design-token JOBS — each var belongs to exactly ONE semantic axis; never reuse across axes ──
       status     : --good/--warning/--serious/--critical + polarity (--supportive/--opposing/
                    --killer/--neutral/--none) + recommendation (--go/--hold/--kill). Green↔red,
                    ALWAYS paired with an icon/label (never color-alone).
       severity   : the status ramp reused for LOW/MED/HIGH risk tiles (green→amber→red).
       diverging  : --pos/--neg — signed 0-centred contribution bars, blue↔orange (CVD-safe).
                    --pos is an ALIAS of --blue (one brand/positive blue, not a third near-blue).
       omics↔lit  : --det (deterministic/omics fact) vs --lit (literature fact). --lit is a QUIET,
                    SUBORDINATE tone (literature is verdict-inert); its identity is carried by SHAPE
                    (litdot = ringed circle vs the omics square) + an agreement glyph, so its hue is
                    redundant and the det↔lit CVD ΔE sits in the legal WARN band BY DESIGN. Re-hued
                    off the old saturated purple (#7a3fb0, CVD ΔE 3.5 vs --det — a hard FAIL, and it
                    competed with the status palette for attention).
       chrome     : --page/--surface/--ink*/--line/--border/--hair/--muted + the --t-* tints. */
  --pos:var(--blue); --neg:#ec835a; --t-hold:rgba(224,145,42,.14);
  --det:#1c6fb0; --lit:#7d6b82; --t-lit:rgba(125,107,130,.12);
}
@media (prefers-color-scheme:dark) {
  :root:where(:not([data-theme=light])) {
    color-scheme:dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#8f8e86;
    --line:#2c2c2a; --border:rgba(255,255,255,0.10); --hair:#232321;
    --opposing:#ec835a; --killer:#e06060; --none:#5f5e57; --hold:#f0a63a;
    --t-good:rgba(12,163,12,.18); --t-serious:rgba(236,131,90,.20); --t-crit:rgba(224,96,96,.20);
    --t-neutral:rgba(143,142,134,.16); --t-blue:rgba(57,135,229,.16);
    --blue:#3987e5; --pos:var(--blue); --neg:#ec835a; --t-hold:rgba(240,166,58,.18);
    --det:#5aa6e0; --lit:#a99bb0; --t-lit:rgba(169,155,176,.18);
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
.char-analogs { font-size:12px; color:var(--muted); margin-top:4px; } .char-analogs .w { color:var(--muted); }
/* v6 hero polish: standout statement · addressable-population line · safety-reconciliation triplet · density toggle */
.headline { font-size:17px; line-height:1.5; font-weight:450; color:var(--ink); margin:12px 0 4px;
            padding:14px 18px; background:var(--surface); border:1px solid var(--border);
            border-left:4px solid var(--blue); border-radius:12px; } .headline b { font-weight:700; }
.h-pop { font-size:13px; color:var(--ink2); background:var(--t-blue); border:1px solid var(--border);
         border-radius:8px; padding:6px 11px; display:inline-block; margin:2px 0 6px; } .h-pop b { color:var(--ink); }
.recon { display:flex; flex-wrap:wrap; align-items:center; gap:2px; margin:8px 0; font-size:12.5px; }
.recon-box { border:1px solid var(--border); border-radius:8px; padding:6px 11px; background:var(--surface); }
.recon-box .rl { display:block; font-size:9.5px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
.recon-box b { color:var(--ink); } .recon-box.hi b { color:var(--critical); }
.recon-box.esc { background:var(--t-good); } .recon-box.esc b { color:var(--good); }
.recon-arrow { color:var(--muted); padding:0 8px; }
.density-bar { display:flex; justify-content:flex-end; gap:6px; align-items:center; font-size:12px; color:var(--muted); margin:0 0 10px; }
.density-bar .seg { display:inline-flex; border:1px solid var(--border); border-radius:999px; overflow:hidden; }
.density-bar button { border:0; background:var(--surface); color:var(--ink2); font-size:12px; padding:4px 11px; cursor:pointer; }
.density-bar button.on { background:var(--blue); color:#fff; }
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
/* lit×omics coherence cell states + cross-evidence convergence strip (consolidation Ph3b/3c) */
.coh-ok { color:var(--good); font-weight:650; } .coh-warn { color:var(--serious); font-weight:650; }
.coh-bad { color:var(--critical); font-weight:700; } .coh-gap { color:var(--muted); }
.cross-ev { border:1px dashed var(--border); border-left:3px solid var(--pos); border-radius:10px;
            background:var(--surface); padding:10px 13px; margin:10px 0; }
.cross-ev .ce-lbl { font-size:10px; text-transform:uppercase; letter-spacing:.05em; color:var(--pos); font-weight:700; }
.cross-ev .ce-chain { margin:6px 0; font-size:12.5px; color:var(--ink2); display:flex; flex-wrap:wrap; align-items:center; gap:4px; }
.cross-ev .ce-node { border:1px solid var(--border); border-radius:7px; background:var(--page); padding:2px 8px; font-weight:600; color:var(--ink); }
.cross-ev .ce-edge { color:var(--muted); font-size:11px; } .cross-ev .ce-edge small { text-transform:uppercase; letter-spacing:.03em; }
.cross-ev .ce-trust { font-size:12px; color:var(--ink2); margin-top:2px; }
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
/* 6-dimension collapsible spine (consolidation Ph3a): each dim tile is a <details> summary; expanding
   spans the full grid row and reveals its feeding signals (subskill→dimension crosswalk). */
.rd { min-width:0; }
.rd > summary { list-style:none; cursor:pointer; height:100%; }
.rd > summary::-webkit-details-marker { display:none; }
.rd[open] { grid-column:1 / -1; }
.rd[open] > summary.risk-tile { display:flex; align-items:center; justify-content:space-between; gap:12px; text-align:left; }
.rd-body { border:1px solid var(--border); border-top:none; border-radius:0 0 10px 10px; padding:8px 11px; background:var(--surface); }
.rd-mem { display:grid; grid-template-columns:minmax(120px,1fr) 2fr auto; gap:10px; align-items:baseline;
          font-size:12px; padding:4px 0; border-top:1px solid var(--hair); }
.rd-mem:first-child { border-top:none; }
.rd-src { font-weight:600; color:var(--ink); }
.rd-read { color:var(--ink2); }
.rd-lv { font-size:10px; font-weight:700; letter-spacing:.04em; color:var(--muted); text-transform:uppercase; }
.rd-blind { font-size:11.5px; color:var(--muted); margin-top:7px; }
.rd-mit { font-size:11.5px; color:var(--ink2); margin-top:4px; }
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
/* evidence-graph blocks (P3): fingerprint heatmap + dataset→data→rule→verdict chains + literature axes.
   ★ CANONICAL evidence-graph + composed-grid design system (dashboard consolidation, 2026-09-09):
   this is the SINGLE source for these components — the subskill sandbox (eg-sandbox-genomic.html) and
   the example-gallery previously copied .hmcell/.litdot/.cardln/.chainline from here. New subskill-
   dashboard design (metric-gloss, two-tone --det/--lit omics-vs-literature, per-question lit-coherence
   dots) lands HERE (+ the :root tokens above), NOT in a parallel renderer. Both the composed embedded
   drill-down and the standalone subskill dashboard render through these classes. */
.eg-inner { margin:6px 0 2px; }
.hm { display:flex; flex-wrap:wrap; gap:10px 14px; }
.hmg { display:flex; flex-direction:column; gap:4px; }
.hmglab { font-size:10.5px; color:var(--muted); display:flex; align-items:center; gap:4px; }
.hmcells { display:flex; gap:5px; align-items:center; flex-wrap:wrap; }
/* fill = signal (FULL opacity — never desaturated); the filled mark repeats the signal (secondary,
   non-hover encoding); the RING weight = confidence (thicker = higher). Confidence was previously
   opacity, which pushed a low-confidence status hue toward neutral. */
.hmcell { width:16px; height:16px; border-radius:4px; border:1px solid var(--border);
          display:inline-flex; align-items:center; justify-content:center;
          color:#fff; font-size:9.5px; font-weight:800; line-height:1; }
.hm-c3 { box-shadow:0 0 0 2px var(--ink2); } .hm-c2 { box-shadow:0 0 0 1px var(--muted); }
.hm-c1 {} .hm-c0 { opacity:.5; }
.hm-twin { margin-top:8px; } .hm-twin summary { cursor:pointer; color:var(--muted); font-size:11px; }
.hm-twin table { margin:6px 0 0; }
.hmsep { width:1px; height:16px; background:var(--hair); margin:0 3px; }
/* the literature dot's FILL carries agreement (agree/contradicts/omics-blind); its --lit RING signals
   "this is a literature signal" pre-attentively (the omics-vs-literature two-tone axis). */
.litdot { width:15px; height:15px; border-radius:50%; border:2px solid var(--lit); display:inline-flex;
          align-items:center; justify-content:center; font-size:9px; color:#fff; font-weight:700; }
.hmnote { color:var(--muted); font-size:11px; margin-top:8px; }
.cardln { border:1px solid var(--border); border-radius:7px; background:var(--surface); margin:6px 0; padding:7px 10px; }
.chead { font-size:11.5px; color:var(--muted); display:flex; justify-content:space-between; align-items:center;
         gap:8px; margin-bottom:3px; } .chead b { color:var(--ink2); font-weight:600; }
.ccchip { display:inline-flex; align-items:center; gap:5px; font-size:11px; color:var(--ink2);
          background:var(--page); border:1px solid var(--border); border-radius:999px; padding:0 7px; white-space:nowrap; }
/* card role badge — separate verdict-drivers from context at a glance (not by reading rule ids) */
.rbadge { display:inline-block; font-size:9px; font-weight:800; text-transform:uppercase; letter-spacing:.04em;
          border-radius:4px; padding:1px 5px; margin-right:6px; vertical-align:middle; }
.rbadge.rb-drv { background:var(--t-blue); color:var(--blue); }
.rbadge.rb-con { background:var(--t-neutral); color:var(--ink2); }
.rbadge.rb-ctx { background:transparent; color:var(--muted); border:1px solid var(--border); font-weight:700; }
.mttag { font-size:10px; color:var(--muted); margin-left:7px; } /* the card's data layer (measurement_type) */
/* literature axis cards read pre-attentively as literature (verdict-inert, subordinate) via a --lit
   left border — the omics-vs-literature two-tone axis, matching the fingerprint litdot ring. */
.litaxis { border-left:3px solid var(--lit); }
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
/* composed at-a-glance grid (COMPOSED_FINGERPRINT): the composed_evidence_graph index as a lens-grouped skill grid */
.cfp-verdict { font-size:13px; color:var(--ink2); margin:2px 0 13px; }
.cfp-verdict .rec { font-weight:750; color:var(--ink); text-transform:uppercase; letter-spacing:.02em; }
.cfp { display:flex; flex-direction:column; gap:9px; }
.cfp-lane { display:grid; grid-template-columns:92px 1fr; gap:10px; align-items:start; }
.cfp-lens { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); padding-top:6px; }
.cfp-chips { display:flex; flex-wrap:wrap; gap:6px; }
.cfp-chip { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--border); border-radius:8px;
            background:var(--surface); padding:3px 9px; font-size:12px; color:var(--ink2); }
.cfp-chip .ct { font-weight:640; color:var(--ink); }
.cfp-chip .cc { color:var(--muted); font-size:11px; }
.cfp-chip.deciding { border-color:var(--ink2); box-shadow:0 0 0 1px var(--ink2); }
.cfp-chip .clit { width:8px; height:8px; border-radius:50%; display:inline-block; border:1px solid var(--border); }
.cfp-dissent { margin-top:11px; font-size:12px; color:var(--ink2); }
.cfp-dissent .dhead { color:var(--serious); font-weight:700; }
.cfp-dissent b { color:var(--ink); }
/* ── standalone subskill-dashboard header (.hdr): a one-sentence read + a kv grid, bound to the carried
   graph verdict (call/confidence/polarity/driving-rule/tension). The `.headline` INSIDE .hdr is the
   compact sentence — reset off the report-hero `.headline` (17px blue hero) it would otherwise inherit. */
.hdr { border-left:4px solid var(--accent,var(--neutral)); padding-left:14px; }
.hdr .headline { font-size:14px; line-height:1.5; font-weight:450; margin:7px 0 3px; padding:0;
                 background:none; border:none; border-radius:0; color:var(--ink); }
.hdr .headline b { font-weight:700; } .caveat { color:var(--warning); }
.kv { display:grid; grid-template-columns:96px 1fr; gap:2px 12px; margin:7px 0 2px; }
.kv dt { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
.kv dd { margin:0; color:var(--ink2); } .kv dd b { color:var(--ink); }
.kv code { font-size:11px; }
.dots { letter-spacing:1px; color:var(--ink2); font-size:11.5px; white-space:nowrap; }
/* ── question drill-down (.qtab / details.qr): the per-question <summary> carries a meter (signal tier),
   confidence dots, a mini qstrip of the question's card signal cells, and an evidence-ref key. */
.qtab { border:1px solid var(--border); border-radius:10px; overflow:hidden; background:var(--surface); margin:6px 0; }
details.qr { border-top:1px solid var(--hair); } details.qr:first-child { border-top:none; }
details.qr > summary { cursor:pointer; list-style:none; display:grid;
    grid-template-columns:14px 1fr 96px 108px; gap:10px; align-items:center; padding:9px 13px; }
details.qr > summary::-webkit-details-marker { display:none; }
details.qr > summary .qcaret { color:var(--muted); font-weight:700; }
details.qr[open] > summary .qcaret::before { content:"▾"; } details.qr > summary .qcaret::before { content:"▸"; }
.qtitle { font-weight:560; font-size:13px; color:var(--ink); }
.qkey { color:var(--muted); font-size:11px; margin-top:1px; }
.qstrip { display:flex; gap:3px; align-items:center; margin-top:4px; flex-wrap:wrap; }
.qcell { width:11px; height:11px; border-radius:3px; border:1px solid var(--border); }
.qcell.hm-c3 { box-shadow:0 0 0 2px var(--ink2); } .qcell.hm-c2 { box-shadow:0 0 0 1px var(--muted); }
.qcell.hm-c0 { opacity:.5; }
.qcount { color:var(--muted); font-size:10.5px; margin-left:4px; }
.meter { width:66px; height:7px; border-radius:4px; background:var(--surface-2,var(--hair));
         overflow:hidden; border:1px solid var(--border); display:inline-block; vertical-align:middle; }
.mfill { height:100%; display:block; }
/* ── split metric-gloss (.kegloss text companion to the visual gauge) + top-strata table (.ketbl) */
.kegloss { font-size:11.5px; color:var(--ink2); margin:3px 0; }
.kegloss .m { color:var(--det); font-weight:600; } .kegloss .h { color:var(--muted); }
.ketbl { border-collapse:collapse; margin:4px 0; font-size:11.5px; width:100%; }
.ketbl td { border-top:1px solid var(--hair); padding:2px 6px; } .ketbl td:first-child { color:var(--muted); }
.kerole { display:inline-block; font-size:9.5px; text-transform:uppercase; color:var(--muted);
          border:1px solid var(--border); border-radius:4px; padding:0 5px; margin-left:5px; }
/* ── two-tone exec bullets: --det omics clause vs --lit literature clause (verdict-inert narrative) */
.bullets { margin:8px 0 4px; padding:0; list-style:none; }
.bullets li { margin:0 0 7px; padding-left:16px; position:relative; font-size:13px; }
.bullets li::before { content:"▸"; position:absolute; left:0; color:var(--b,var(--neutral)); font-weight:700; }
.fx-det { color:var(--det); } .fx-lit { color:var(--lit); }
.legendrow { font-size:11px; color:var(--muted); margin-top:6px; } .legendrow b { font-weight:600; }
/* ── theme toggle (auto / light / dark via data-theme on <html>) */
.theme-toggle { position:fixed; top:10px; right:12px; z-index:9; font-size:11.5px; color:var(--ink2);
    background:var(--surface); border:1px solid var(--border); border-radius:7px; padding:4px 9px; cursor:pointer; }
:root[data-theme=dark] {
  color-scheme:dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#8f8e86;
  --line:#2c2c2a; --border:rgba(255,255,255,0.10); --hair:#232321;
  --opposing:#ec835a; --killer:#e06060; --none:#5f5e57; --hold:#f0a63a;
  --t-good:rgba(12,163,12,.18); --t-serious:rgba(236,131,90,.20); --t-crit:rgba(224,96,96,.20);
  --t-neutral:rgba(143,142,134,.16); --t-blue:rgba(57,135,229,.16);
  --blue:#3987e5; --pos:var(--blue); --neg:#ec835a; --t-hold:rgba(240,166,58,.18);
  --det:#5aa6e0; --lit:#a99bb0; --t-lit:rgba(169,155,176,.18);
}
:root[data-theme=light] { color-scheme:light; }
""".strip()


# ── v6 convergence-layer composed dashboard (single-scroll: sticky hero → headline → folds → 3-view
#    switch → 6-dim spine / modality / lit×omics). Ported wholesale from the approved redesign-v6 mockup,
#    reusing the SAME :root design tokens already declared in _CSS above (--good/--warning/--critical/
#    --blue/--go/--hold/--kill/--t-*). Only NEW component classes live here; base selectors already in
#    _CSS (.card/.headline/.h-pop/.coh-*/body/.wrap/:root) are intentionally NOT re-declared so the
#    standalone-skill layout is untouched. VERDICT-INERT — display only. ──
_V6_CSS = """
.tnum { font-variant-numeric:tabular-nums; }
h2.sh { font-size:12.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
        margin:26px 0 12px; padding-bottom:7px; border-bottom:1px solid var(--hair); }
h2.sh .sub { text-transform:none; letter-spacing:0; font-weight:400; color:var(--muted); }
details.fold { margin:9px 0; border:1px solid var(--border); border-radius:12px; background:var(--surface); }
details.fold>summary { list-style:none; cursor:pointer; padding:13px 16px; font-size:13px; font-weight:640; color:var(--ink); }
details.fold>summary::-webkit-details-marker { display:none; }
details.fold>summary::before { content:"\\25B8  "; color:var(--muted); font-weight:400; }
details.fold[open]>summary::before { content:"\\25BE  "; }
details.fold>summary .fx { color:var(--muted); font-weight:400; font-size:11.5px; }
details.fold .foldbody { padding:0 15px 8px; }
details.fold .foldbody .card { border:0; padding:4px 0 10px; }
/* HERO */
.hero { position:sticky; top:0; z-index:5; background:var(--page); border-bottom:1px solid var(--border);
        padding:12px 0; margin-bottom:6px; }
.hgrid { display:grid; grid-template-columns:1.5fr auto 1fr; gap:22px; align-items:center; }
.h-t { font-size:24px; font-weight:730; letter-spacing:-.01em; margin:0; } .h-t .ind { color:var(--muted); font-weight:500; }
.h-arche { font-size:11.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:5px 0 5px; }
.vblock { text-align:center; padding:0 16px; border-left:1px solid var(--border); border-right:1px solid var(--border); }
.vchip { display:inline-flex; align-items:center; gap:8px; font-size:19px; font-weight:750; padding:6px 17px;
         border-radius:999px; text-transform:uppercase; }
.vchip .dot { width:10px; height:10px; border-radius:999px; }
.vchip.go { background:var(--t-good); color:var(--good); } .vchip.go .dot { background:var(--go); }
.vchip.hold { background:var(--t-hold); color:var(--hold); } .vchip.hold .dot { background:var(--hold); }
.vchip.kill { background:var(--t-crit); color:var(--kill); } .vchip.kill .dot { background:var(--kill); }
.vchip.none { background:var(--t-neutral); color:var(--muted); } .vchip.none .dot { background:var(--none); }
.vconf { font-size:12px; color:var(--muted); margin-top:6px; } .vconf b { color:var(--ink2); }
.dimmini { display:flex; flex-direction:column; gap:3px; font-size:10.5px; }
.dimmini .r { display:grid; grid-template-columns:74px 1fr 30px; gap:6px; align-items:center; }
.dimmini .mtrack { position:relative; height:5px; background:var(--hair); border-radius:99px; }
.dimmini .mtrack i { position:absolute; left:0; top:0; bottom:0; border-radius:99px; }
.dimmini .lv { font-weight:700; font-size:9.5px; text-align:right; }
.risk-low i { width:22%; background:var(--good); } .risk-low .lv { color:var(--good); }
.risk-med i { width:55%; background:var(--warning); } .risk-med .lv { color:var(--serious); }
.risk-high i { width:88%; background:var(--critical); } .risk-high .lv { color:var(--critical); }
.risk-na i { width:8%; background:var(--none); } .risk-na .lv { color:var(--muted); }
/* SYNTHESIS (convergence) */
.synth { display:grid; grid-template-columns:1.6fr 1fr; gap:15px; }
.exec { display:flex; flex-direction:column; gap:6px; }
.ebul { display:grid; grid-template-columns:12px 1fr; gap:8px; font-size:12.5px; color:var(--ink2); line-height:1.4; }
.ebul .pol { width:7px; height:7px; border-radius:50%; margin-top:6px; }
.ebul.sup .pol { background:var(--good); } .ebul.against .pol { background:var(--serious); }
.ebul.xev .pol { background:var(--blue); border-radius:2px; }
.ebul.xev>div { border-top:1px dashed var(--hair); padding-top:7px; }
.ebul.xev .xk { font-size:9.5px; text-transform:uppercase; letter-spacing:.04em; color:var(--blue); font-weight:700; display:block; }
.anchor { font-size:10px; color:var(--blue); background:var(--t-blue); border:1px solid var(--border);
          border-radius:5px; padding:0 5px; cursor:pointer; text-decoration:none; margin-left:4px; }
.tension { background:var(--t-hold); border:1px solid var(--border); border-radius:11px; padding:11px 13px; }
.tension .tl { font-size:10px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); font-weight:700; }
.tension p { margin:5px 0 0; font-size:12px; color:var(--ink2); }
/* VIEW SWITCH */
.views { display:flex; gap:6px; margin:22px 0 4px; }
.views button { border:1px solid var(--border); background:var(--surface); color:var(--ink2); font-size:13px;
                font-weight:600; padding:8px 16px; border-radius:10px; cursor:pointer; }
.views button.on { background:var(--ink); color:var(--page); border-color:var(--ink); }
.view { display:none; } .view.on { display:block; }
/* 6-DIM SPINE */
.dim { border:1px solid var(--border); border-radius:12px; background:var(--surface); margin:9px 0; }
.dim.blind { border-style:dashed; opacity:.92; }
.dim>summary { list-style:none; cursor:pointer; display:grid; grid-template-columns:16px 190px 1fr 78px;
               gap:13px; align-items:center; padding:12px 15px; }
.dim>summary::-webkit-details-marker { display:none; }
.dim .caret { color:var(--muted); transition:transform .15s; } .dim[open] .caret { transform:rotate(90deg); }
.dim .dn { font-size:14px; font-weight:660; }
.dim .dn .rr { font-size:10.5px; color:var(--muted); font-weight:500; text-transform:uppercase; letter-spacing:.04em; display:block; }
.dbar { position:relative; height:22px; }
.dbar .track { position:absolute; left:0; right:0; top:8px; height:7px; background:var(--hair); border-radius:99px; overflow:hidden; }
.dbar .track i { position:absolute; left:0; top:0; bottom:0; border-radius:99px; }
.dbar .scale { position:absolute; top:16px; left:0; right:0; display:flex; justify-content:space-between; font-size:8.5px; color:var(--muted); }
.dlevel { text-align:right; font-size:13px; font-weight:750; }
.dim.risk-low .dbar .track i { width:22%; background:var(--good); } .dim.risk-low .dlevel { color:var(--good); }
.dim.risk-med .dbar .track i { width:55%; background:var(--warning); } .dim.risk-med .dlevel { color:var(--serious); }
.dim.risk-high .dbar .track i { width:88%; background:var(--critical); } .dim.risk-high .dlevel { color:var(--critical); }
.dim.risk-na .dbar .track i { width:6%; background:var(--none); } .dim.risk-na .dlevel { color:var(--muted); font-size:11px; }
.dmembers { padding:2px 15px 13px 44px; border-top:1px solid var(--hair); margin-top:2px; padding-top:10px; }
.mem { display:grid; grid-template-columns:168px 1fr auto; gap:11px; align-items:center; font-size:12px; color:var(--ink2); padding:4px 0; }
.mem+.mem { border-top:1px solid var(--hair); }
.mem .mn { color:var(--ink); font-weight:600; } .mem .mn small { display:block; color:var(--muted); font-weight:400; font-size:10.5px; }
.mem .full { font-size:11px; color:var(--blue); text-decoration:none; white-space:nowrap; } .mem .full:hover { text-decoration:underline; }
.ctxtag { font-size:9px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); background:var(--t-neutral); border-radius:5px; padding:0 5px; margin-left:5px; }
.chip { display:inline-flex; gap:5px; font-size:11px; color:var(--ink2); background:var(--page); border:1px solid var(--border); border-radius:999px; padding:1px 8px; margin:1px 3px 0 0; }
.chip b { color:var(--ink); font-weight:640; } .chip.pos b { color:var(--good); } .chip.neg b { color:var(--kill); }
.spark { display:inline-block; position:relative; width:70px; height:12px; background:var(--hair); border-radius:3px; vertical-align:middle; }
.spark .iqr { position:absolute; top:2px; height:8px; background:var(--blue); opacity:.5; border-radius:2px; }
.spark .med { position:absolute; top:0; width:2px; height:12px; background:var(--blue); }
.spark .panel { position:absolute; top:0; width:2px; height:12px; background:var(--muted); }
.blindnote { font-size:11.5px; color:var(--muted); padding:2px 0; }
.flag { font-size:10px; color:var(--warning); font-weight:650; }
/* CONVERGENCE LAYER */
.analogs { font-size:11px; color:var(--muted); margin-top:5px; } .analogs b { color:var(--ink2); }
.conv { display:flex; flex-direction:column; gap:12px; }
.causal { display:flex; align-items:stretch; flex-wrap:wrap; gap:2px; }
.cnode { border:1px solid var(--border); border-radius:9px; background:var(--surface); padding:7px 11px; font-size:11.5px; max-width:180px; }
.cnode .ct { font-size:9px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); } .cnode b { color:var(--ink); }
.cnode.sup { border-left:3px solid var(--good); } .cnode.warn { border-left:3px solid var(--serious); }
.cedge { display:flex; flex-direction:column; justify-content:center; align-items:center; color:var(--muted);
         padding:0 7px; font-size:9px; text-transform:uppercase; letter-spacing:.03em; }
.cedge .ar { font-size:16px; line-height:1; color:var(--ink2); }
.conv .trust { display:flex; flex-wrap:wrap; gap:16px; font-size:11.5px; color:var(--ink2); background:var(--page);
         border:1px solid var(--border); border-radius:9px; padding:8px 12px; }
.trust { font-size:10.5px; color:var(--muted); margin-top:7px; }
.trust .k { color:var(--muted); text-transform:uppercase; font-size:9px; letter-spacing:.04em; margin-right:4px; }
.trust .ok { color:var(--good); font-weight:650; } .trust .warn { color:var(--serious); font-weight:650; }
.litctx { border:1px dashed var(--border); border-radius:10px; background:var(--t-neutral); padding:9px 12px; font-size:11.5px; color:var(--ink2); }
.litctx .lh { font-size:9.5px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); font-weight:700; }
.litchip { display:inline-flex; gap:4px; font-size:10px; color:var(--muted); background:var(--surface); border:1px dashed var(--border); border-radius:999px; padding:0 7px; margin:3px 3px 0 0; }
.dimlit { font-size:10.5px; color:var(--muted); border-top:1px dashed var(--hair); margin-top:6px; padding-top:5px; }
.headline .call { color:var(--good); font-weight:730; }
.litmk { font-size:10px; color:var(--muted); border:1px dashed var(--border); border-radius:5px; padding:0 6px; margin-left:7px; font-weight:500; white-space:nowrap; vertical-align:middle; }
.dn .lit { display:block; font-size:10px; color:var(--muted); font-weight:400; letter-spacing:0; text-transform:none; margin-top:2px; }
.cites { margin-top:7px; display:flex; flex-direction:column; gap:4px; font-size:11.5px; }
.cites .cr { color:var(--ink2); } .cite { color:var(--blue); text-decoration:none; font-weight:600; } .cite:hover { text-decoration:underline; }
.arche { display:grid; grid-template-columns:1.5fr 1fr 1fr; gap:18px; margin-top:6px; }
.arche-h { font-size:10px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); font-weight:700; margin-bottom:6px; }
.arche-x { font-size:12px; color:var(--ink2); margin:0; line-height:1.45; }
.mrowb, .anrow { display:grid; grid-template-columns:1fr 56px 34px; gap:7px; align-items:center; font-size:11px; color:var(--ink2); margin:3px 0; }
.mt, .ad { position:relative; height:7px; background:var(--hair); border-radius:99px; } .mt i, .ad i { position:absolute; left:0; top:0; bottom:0; border-radius:99px; }
.mt i { background:var(--blue); } .ad i { background:var(--muted); }
/* LIT x OMICS COHERENCE */
table.cohtab { border-collapse:collapse; width:100%; font-size:12px; }
table.cohtab th, table.cohtab td { border:1px solid var(--hair); padding:8px 10px; text-align:left; vertical-align:top; }
table.cohtab th { color:var(--muted); text-transform:uppercase; font-size:9.5px; letter-spacing:.04em; font-weight:600; }
table.cohtab td:first-child { font-weight:640; color:var(--ink); text-transform:capitalize; }
.rl-low { background:var(--t-good); } .rl-med { background:var(--t-hold); } .rl-high { background:var(--t-crit); } .rl-na { color:var(--muted); }
.cohtab .note { color:var(--muted); font-weight:400; font-size:10px; display:block; }
.aggnote { font-size:11.5px; color:var(--ink2); margin-top:11px; background:var(--page); border:1px solid var(--border); border-radius:9px; padding:10px 12px; }
/* MODALITY VIEW */
.mrow { display:grid; grid-template-columns:150px 1fr auto; gap:12px; align-items:center; font-size:12.5px; padding:5px 0; }
.mrow .mn { font-weight:600; } .mrow.na .mn { color:var(--muted); font-weight:500; }
.mbul { position:relative; height:12px; background:var(--hair); border-radius:99px; } .mbul i { position:absolute; left:0; top:0; bottom:0; border-radius:99px; }
.mbul.viable i { width:82%; background:var(--good); } .mbul.conditional i { width:52%; background:var(--hold); } .mbul.unfavorable i { width:24%; background:var(--critical); }
.mbul.na { opacity:.4; background:repeating-linear-gradient(45deg,var(--hair),var(--hair) 4px,transparent 4px,transparent 8px); }
.mwhy { color:var(--muted); font-size:11px; }
.matrix { border-collapse:collapse; font-size:10.5px; margin-top:14px; width:100%; }
.matrix th, .matrix td { border:1px solid var(--hair); padding:4px 6px; text-align:center; }
.matrix th { color:var(--muted); font-weight:600; font-size:9.5px; text-transform:uppercase; }
.matrix td.g { background:var(--t-good); } .matrix td.h { background:var(--t-hold); } .matrix td.b { background:var(--t-crit); }
.matrix td.n { background:var(--t-neutral); color:var(--muted); } .matrix td.off { color:var(--muted); }
.matrix td:first-child { text-align:left; color:var(--ink2); }
.dz { color:var(--muted); font-size:12px; margin:26px 0 0; border-top:1px solid var(--hair); padding-top:12px; }
@media (max-width:860px) {
  .hgrid, .synth { grid-template-columns:1fr; }
  .vblock { border:0; border-top:1px solid var(--border); border-bottom:1px solid var(--border); padding:12px 0; }
  .dim>summary { grid-template-columns:16px 1fr 60px; }
  .mem { grid-template-columns:1fr; }
  .arche { grid-template-columns:1fr; }
}
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
            vocab.COMPOSED_FINGERPRINT: self._composed_fingerprint,
        }

    def handled_kinds(self) -> set:
        return set(self._handlers)

    # -- structure -----------------------------------------------------------------------------
    def render(self, ir: ReportIR) -> str:
        title = f"Target report — {_esc(ir.target or '—')} × {_esc(ir.indication or '—')}"
        parts = [
            "<!doctype html>",
            '<html lang="en" data-theme="auto"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{title}</title><style>{_CSS}\n{_V6_CSS}\n{_lens_css()}</style></head><body>",
            # theme toggle: auto → light → dark on <html data-theme> (the dark media-query honours 'auto').
            '<button class="theme-toggle" onclick="var r=document.documentElement,'
            "n={auto:'light',light:'dark',dark:'auto'};r.dataset.theme=n[r.dataset.theme||'auto'];"
            'this.lastChild.textContent=r.dataset.theme;">theme: <span>auto</span></button>',
            "<div class='wrap'>",
        ]
        # v6 density control: Compact (collapse all <details>) / Detailed (default) / Expand-all — lets a
        # leadership reader stay high-level and a comp-bio reader open everything, on one page.
        parts.append(
            "<div class='density-bar'>density <span class='seg'>"
            "<button data-density='compact'>Compact</button>"
            "<button data-density='detailed' class='on'>Detailed</button>"
            "<button data-density='all'>Expand all</button></span></div>"
        )
        lenses = ir.lenses()
        if lenses:
            # COMPOSED report → the v6 convergence layout (single scroll: sticky hero → headline →
            # archetype/convergence folds → 3-view switch). The hero IS the report_header (recommendation +
            # 6-dim glance); no separate decision card / advisory banner card (their content is woven into
            # the hero + convergence fold). Verdict-inert — a pure re-projection of the same IR blocks.
            parts.append(self._v6_composed(ir))
        else:
            # flat fallback (standalone / un-lensed IR): the decision header + advisory banner stay as
            # persistent chrome cards, then overview blocks + per-skill sections.
            parts.append(self._wrap_card("".join(self._emit(ir.header)), extra="decision"))
            if getattr(ir, "banner", None) is not None:
                parts.append(self._wrap_card("".join(self._emit(ir.banner)), extra="narr"))
            for b in ir.overview:
                parts.append(self._wrap_card("".join(self._emit(b))))
            for sec in ir.sections:
                parts.append(self._emit_section(sec))
        if ir.about is not None:
            parts.append("".join(self._emit(ir.about)))
        parts.append(
            "<script>(function(){var b=document.querySelector('.density-bar');if(b){"
            "b.addEventListener('click',function(e){var t=e.target.closest('button');if(!t)return;"
            "[].forEach.call(b.querySelectorAll('button'),function(x){x.classList.toggle('on',x===t);});"
            "var m=t.getAttribute('data-density');"
            "if(m==='compact'){[].forEach.call(document.querySelectorAll('details'),function(d){d.open=false;});}"
            "else if(m==='all'){[].forEach.call(document.querySelectorAll('details'),function(d){d.open=true;});}"
            "});}"
            # v6 3-view switch (assess / modality / coherence): toggle .view.on by data-v; anchors jump to
            # a dimension after switching to the assessment view. Pure DOM toggling (no page reload).
            "var vb=document.querySelector('.views');if(vb){"
            "vb.addEventListener('click',function(e){var bt=e.target.closest('button');if(!bt)return;"
            "[].forEach.call(vb.children,function(x){x.classList.toggle('on',x===bt);});"
            "['assess','modality','coherence'].forEach(function(v){var el=document.getElementById('v-'+v);"
            "if(el)el.classList.toggle('on',bt.getAttribute('data-v')===v);});});"
            "[].forEach.call(document.querySelectorAll('.anchor'),function(a){a.addEventListener('click',function(){"
            "var ab=vb.querySelector('[data-v=assess]');if(ab)ab.click();});});}"
            "})();</script>"
        )
        parts.append("</div></body></html>")
        return "\n".join(parts) + "\n"

    # -- v6 composed convergence layout --------------------------------------------------------
    def _v6_composed(self, ir: ReportIR) -> str:
        """The approved redesign-v6 single-scroll layout, bound to the composed IR blocks. Assembles:
        sticky hero (report_header) → standout headline → archetype fold → convergence fold (synthesis) →
        3-view switch → 6-dim spine (risk_6dim) / modality (modality_matrix) / lit×omics (literature_risk).
        Remaining decision-detail blocks + the 15 per-skill sections are appended as collapsed folds so no
        composed content is lost. Verdict-inert display projection."""
        by_kind = {}
        for b in ir.overview:
            by_kind.setdefault(b.kind, b)
        hp = ir.header.payload
        parts = []
        # 1) sticky hero + 2) standout headline (both from report_header).
        parts.extend(self._report_header(hp))
        # honest LLM-vs-deterministic divergence: when the advisory synthesis leaned differently from the
        # deterministic call, surface that mismatch as a compact advisory strip (the deterministic call
        # stands). The full advisory exec summary is otherwise woven into the headline + convergence fold.
        if getattr(ir, "banner", None) is not None:
            mm = ir.banner.payload.get("mismatch")
            if isinstance(mm, dict) and mm.get("deterministic"):
                parts.append(
                    "<div class='card narr'><span class='tag'>AI-generated · advisory</span>"
                    f"<p class='kv mismatch'>⚠ <b>LLM read:</b> {_esc(mm.get('llm'))} · "
                    f"<b>deterministic call:</b> {_esc(mm['deterministic'])} — mismatch flagged "
                    "<span class='so-foot'>(the deterministic call stands)</span></p></div>"
                )
        # 3) archetype fold (header characterization).
        af = self._archetype_fold(hp)
        if af:
            parts.append(af)
        # 4) convergence fold (LLM synthesis: causal chain + trust + exec bullets + tension + litctx).
        syn = by_kind.get(vocab.SYNTHESIS)
        if syn is not None:
            conv = "".join(self._emit(syn))
            if conv.strip():
                parts.append(
                    "<details class='fold' open><summary>How the evidence converges "
                    "<span class='fx'>— cross-evidence causal chain · LLM synthesis · cited literature</span>"
                    f"</summary><div class='foldbody'><div class='card'>{conv}</div></div></details>"
                )
        # 5) the 3-view switch.
        parts.append(
            "<div class='views'>"
            "<button data-v='assess' class='on'>6-Dimension assessment</button>"
            "<button data-v='modality'>Modality</button>"
            "<button data-v='coherence'>Literature × omics</button></div>"
        )
        # 6) VIEW: 6-dimension spine (risk_6dim rendered as .dim/.dbar/.dmembers).
        r6 = by_kind.get(vocab.RISK_6DIM)
        spine = "".join(self._emit(r6)) if r6 is not None else ""
        parts.append(
            "<section class='view on' id='v-assess'>"
            "<h2 class='sh'>Target-validation assessment — 5 R's + translational "
            "<span class='sub'>· LOW risk = green = good · click a dimension for the signals feeding it</span></h2>"
            f"{spine}</section>"
        )
        # 7) VIEW: modality (modality_matrix rendered as .mrow/.mbul + .matrix).
        mm = by_kind.get(vocab.MODALITY_MATRIX)
        mod = "".join(self._emit(mm)) if mm is not None else ""
        parts.append(f"<section class='view' id='v-modality'>{mod}</section>")
        # 8) VIEW: literature × omics coherence (literature_risk rendered as .cohtab).
        lr = by_kind.get(vocab.LITERATURE_RISK)
        coh = "".join(self._emit(lr)) if lr is not None else ""
        parts.append(f"<section class='view' id='v-coherence'>{coh}</section>")
        # decision-detail + per-skill evidence: appended as collapsed folds so nothing the composed IR
        # carries is dropped from the HTML (the v6 look leads; the depth is one click away).
        placed = {vocab.SYNTHESIS, vocab.RISK_6DIM, vocab.MODALITY_MATRIX, vocab.LITERATURE_RISK}
        detail_blocks = [b for b in ir.overview if b.kind not in placed]
        if detail_blocks:
            inner = "".join(self._wrap_card("".join(self._emit(b))) for b in detail_blocks)
            parts.append(
                "<details class='fold'><summary>Decision detail "
                "<span class='fx'>— at-a-glance grid · deciding axis · flip conditions · biomarker · "
                f"subtype · coherence</span></summary><div class='foldbody'>{inner}</div></details>"
            )
        if ir.sections:
            secs = "".join(self._emit_section(sec, collapsed=True) for sec in ir.sections)
            # OPEN by default so the reader immediately SEES all N subskill sections as a scannable list
            # (each verdict chip + header); the inner per-skill sections stay individually collapsed, so
            # the page is discoverable without a wall of expanded detail. Density 'Compact' still folds it.
            parts.append(
                "<details class='fold' open><summary>Per-subskill evidence "
                f"<span class='fx'>— the {len(ir.sections)} embedded question-answering views</span>"
                f"</summary><div class='foldbody'>{secs}</div></details>"
            )
        return "".join(parts)

    def _archetype_fold(self, hp: dict) -> str:
        """v6 archetype fold: phenotype-class prose + soft-membership bars + nearest-analog bars, from the
        header characterization (verdict-inert). '' when no archetype characterization is present."""
        char = hp.get("characterization") or {}
        membership = char.get("membership") or char.get("mixture") or []
        analogs = char.get("analogs") or []
        if not (membership or analogs):
            return ""
        lead = membership[0]["label"] if membership else None
        analog_summary = " · ".join(_esc(a.get("target")) for a in analogs[:3]) if analogs else ""
        fx = " · ".join(
            x for x in (f"{_esc(lead)}" if lead else "", f"analogs {analog_summary}" if analog_summary else "") if x
        )
        prose = (
            "A data-driven classification (soft kNN membership against the reference archetype atlas) of "
            "what KIND of target this is — it routes narrative emphasis and picks comparators. Descriptive "
            "and verdict-inert."
        )
        if lead:
            prose = f"This target reads as <b>{_esc(lead)}</b>. " + prose
        mrows = "".join(
            f"<div class='mrowb'><span>{_esc(m.get('label'))}</span>"
            f"<span class='mt'><i style='width:{max(2, int(round((m.get('weight') or 0) * 100)))}%'></i></span>"
            f"<span>{int(round((m.get('weight') or 0) * 100))}%</span></div>"
            for m in membership[:5]
        )
        # nearest-analog bars: smaller distance = more similar → longer bar. Scale to the max shown distance.
        dists = [a.get("distance") for a in analogs if isinstance(a.get("distance"), (int, float))]
        dmax = max(dists) if dists else None
        arows = []
        for a in analogs[:3]:
            name = _esc(a.get("target")) + (f" · {_esc(a.get('indication'))}" if a.get("indication") else "")
            d = a.get("distance")
            if isinstance(d, (int, float)) and dmax:
                width = max(6, int(round((1 - (d / (dmax * 1.15))) * 100)))
                val = f"{d:g}"
            else:
                width, val = 40, "—"
            arows.append(
                f"<div class='anrow'><span>{name}</span>"
                f"<span class='ad'><i style='width:{width}%'></i></span><span>{_esc(val)}</span></div>"
            )
        return (
            f"<details class='fold'><summary>Target archetype <span class='fx'>— {fx}</span></summary>"
            "<div class='foldbody'><div class='card arche'>"
            f"<div><div class='arche-h'>Phenotype class</div><p class='arche-x'>{prose}</p></div>"
            f"<div><div class='arche-h'>Soft membership</div>{mrows}</div>"
            "<div><div class='arche-h'>Nearest analogs <span style='font-weight:400;text-transform:none;"
            f"letter-spacing:0'>(smaller = more similar)</span></div>{''.join(arows)}</div>"
            "</div></div></details>"
        )

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
            parts.append(f"<details class='fig-more'><summary>{len(extra)} more figure(s)</summary>{figs}</details>")
        inner = "".join(parts)
        if collapsed and blocks:
            summary = "".join(self._emit(blocks[0]))
            openattr = " open" if sec.is_deciding else ""
            cls = f"card {pol_cls} skill-collapse".replace("  ", " ").strip()
            return f"<details class='{cls}'{openattr}><summary>{summary}</summary>{inner}</details>"
        cls = f"card {pol_cls}".strip()
        return f"<section class='{cls}'>{inner}</section>"

    # -- handlers ------------------------------------------------------------------------------
    _REC_CLASS = {
        "nominate": "go",
        "advance": "go",
        "go": "go",
        "hold": "hold",
        "conditional": "hold",
        "watch": "hold",
        "kill": "kill",
        "decline": "kill",
        "no": "kill",
        "drop": "kill",
    }

    def _report_header(self, p: dict) -> list:
        tgt, ind = _esc(p.get("target") or "—"), _esc(p.get("indication") or "—")
        # standalone single-skill path: a plain target/indication frame (the skill's own call leads its
        # section) — NOT the composed v6 hero (which needs the target-level recommendation + risk glance).
        if p.get("single_skill"):
            return [
                f"<h1>{tgt} <span style='color:var(--muted);font-weight:520'>×</span> {ind}</h1>",
                "<p class='sub'>Single-skill evidence view.</p>",
            ]
        # ── v6 sticky hero: 3-column (LEFT identity + context pills · CENTER verdict chip · RIGHT 6-dim
        #    glance) ── followed by the standout headline. Verdict-inert display.
        left = [f"<h1 class='h-t'>{tgt} <span class='ind'>× {ind}</span></h1>"]
        char = p.get("characterization") or {}
        lead_label = (char.get("mixture") or [{}])[0].get("label") if char.get("mixture") else None
        arche_bits = [
            x
            for x in (
                _esc(lead_label) if lead_label else "",
                _esc(_humanize(p.get("thesis"))) if p.get("thesis") else "",
                _esc(_humanize(p.get("coherence_class"))) if p.get("coherence_class") else "",
            )
            if x
        ]
        if arche_bits:
            left.append(f"<div class='h-arche'>{' · '.join(arche_bits)}</div>")
        analogs = char.get("analogs") or []
        if analogs:
            al = " · ".join(f"<b>{_esc(a.get('target'))}</b>" for a in analogs[:3])
            left.append(f"<div class='analogs'>nearest archetype analogs: {al}</div>")
        lit = p.get("literature") if isinstance(p.get("literature"), dict) else None
        if lit and (lit.get("total_comentions") or lit.get("cited_pmids")):
            tot = lit.get("total_comentions")
            rec_m = lit.get("recent_comentions")
            txt = "cited co-mentions"
            if tot is not None:
                txt = f"<b>{int(tot):,}</b> cited co-mentions"
                if rec_m is not None:
                    txt += f" ({int(rec_m):,} recent)"
            left.append(f"<div class='analogs'>Literature: {txt} — see Literature × omics view below</div>")
        ap = p.get("addressable_population") if isinstance(p.get("addressable_population"), dict) else {}
        prev = ap.get("biomarker_prevalence")
        if prev is not None:
            try:
                prevpct = f"{float(prev) * 100:.3g}%"
            except (TypeError, ValueError):
                prevpct = _esc(prev)
            meta = " · ".join(
                x
                for x in (
                    _esc(ap.get("prevalence_source")) if ap.get("prevalence_source") else "",
                    f"n={_esc(ap.get('n_samples_in_indication'))}" if ap.get("n_samples_in_indication") else "",
                    _esc(ap.get("addressable_population_class")) if ap.get("addressable_population_class") else "",
                )
                if x
            )
            left.append(
                f"<div class='h-pop'>Addressable population <b>{prevpct}</b>"
                + (f" — {meta}" if meta else "")
                + "</div>"
            )
        cp = p.get("clinical_precedent") if isinstance(p.get("clinical_precedent"), dict) else None
        if cp and cp.get("highest_stage"):
            left.append(
                "<div class='h-pop' style='margin-top:6px;background:var(--t-good)'>Clinical precedent — "
                f"highest stage <b>{_esc(cp['highest_stage'])}</b></div>"
            )
        # CENTER: the verdict chip + confidence + groundedness stamp.
        rec = p.get("recommendation")
        center = []
        if rec:
            klass = self._REC_CLASS.get(str(rec).strip().lower().split()[0], "none")
            center.append(f"<span class='vchip {klass}'><span class='dot'></span>{_esc(_humanize(rec))}</span>")
            ct = _confidence_summary(p.get("confidence"))
            if ct:
                center.append(f"<div class='vconf'>confidence <b>{_esc(ct)}</b></div>")
            gr = p.get("groundedness") if isinstance(p.get("groundedness"), dict) else None
            if gr and gr.get("n_cited") is not None:
                center.append(
                    f"<div class='trust'>✓ synthesis grounded · {_esc(gr['n_cited'])} claims, "
                    f"{_esc(gr.get('n_invented') or 0)} invented</div>"
                )
        center_html = f"<div class='vblock'>{''.join(center)}</div>" if center else ""
        # RIGHT: the 6-dimension glance (reads the same risk_6dim dims as the assessment spine).
        right_html = self._dimmini(p.get("risk_dims") or [])
        out = [
            "<header class='hero'><div class='hgrid'>"
            f"<div>{''.join(left)}</div>{center_html}{right_html}"
            "</div></header>"
        ]
        # STANDOUT one-sentence statement, right below the hero.
        if p.get("overall_statement"):
            out.append(f"<p class='headline'>{_esc(p['overall_statement'])}</p>")
        # safety-reconciliation TRIPLET (a HIGH-magnitude veto suppressed by a spared modality is ONE
        # reconciled fact) — kept as a compact row under the headline.
        gate = p.get("gate") if isinstance(p.get("gate"), dict) else {}
        for v in gate.get("suppressed_vetoes") or []:
            if not isinstance(v, dict):
                continue
            by = v.get("suppressed_by") or {}
            chans = by.get("safe_channels") or []
            chan_txt = ", ".join(_esc(c) for c in chans) if chans else _esc(by.get("kind") or "a spared modality")
            out.append(
                "<div class='recon'>"
                f"<span class='recon-box hi'><span class='rl'>{_esc(v.get('short') or 'veto')} magnitude</span>"
                f"<b>{_esc(_humanize(v.get('verdict')) or 'HIGH')}</b></span>"
                "<span class='recon-arrow'>→</span>"
                f"<span class='recon-box esc'><span class='rl'>escapable by</span><b>{chan_txt}</b></span>"
                "<span class='recon-arrow'>→</span>"
                "<span class='recon-box'><span class='rl'>gate</span><b>veto suppressed</b></span>"
                "</div>"
            )
        return out

    _DIMMINI_CLASS = {3: "risk-high", 2: "risk-med", 1: "risk-low"}
    _DIMMINI_LV = {3: "HIGH", 2: "MED", 1: "LOW"}

    def _dimmini(self, dims: list) -> str:
        """The v6 hero 6-dim glance: one row per risk dimension (label · positioned bar · level), coloured
        by rank (LOW=green / MED=amber / HIGH=red / unrouted=grey). '' when no dims."""
        if not dims:
            return ""
        rows = []
        for d in dims:
            rank = d.get("rank")
            cls = self._DIMMINI_CLASS.get(rank, "risk-na")
            lv = self._DIMMINI_LV.get(rank, "unrouted")
            rows.append(
                f"<div class='r {cls}'><span>{_esc(str(d.get('dim')).title())}</span>"
                f"<span class='mtrack'><i></i></span><span class='lv'>{_esc(lv)}</span></div>"
            )
        return f"<div class='dimmini'>{''.join(rows)}</div>"

    def _skill_header(self, p: dict) -> list:
        glyph = vocab.polarity_glyph(p.get("polarity"))
        call = _humanize(p.get("call")) or None  # snake_case machine verdict → readable
        verdict = call or (
            "context (descriptive)"
            if p.get("role") in ("descriptive", "inert")
            else vocab.polarity_label(p.get("polarity"))
        )
        deciding = " <span class='deciding'>deciding axis</span>" if p.get("is_deciding") else ""
        color = self._EG_POL_COLOR.get(p.get("polarity"), "var(--neutral)")
        # the sandbox `.hdr`: accent spine + stitle + one-sentence headline + kv grid (bound to the graph
        # verdict when carried; degrades to just the stitle/phrase when the skill has no rich graph).
        out = [
            f'<div class="hdr" style="--accent:{color}">'
            f"<div class='stitle'><span class='glyph'>{_esc(glyph)}</span>"
            f"{_esc(p.get('title'))} — {_esc(verdict)}{deciding}</div>"
        ]
        if p.get("honest_phrase"):
            out.append(f"<div class='phrase'>{_esc(p['honest_phrase'])}</div>")
        out.extend(self._skill_headline_and_kv(p, verdict))
        out.append("</div>")
        return out

    def _skill_headline_and_kv(self, p: dict, verdict: str) -> list:
        """The sandbox one-sentence `.headline` (call + confidence + polarity + driving rule + ⚠ caveat)
        and the `.kv` grid (Verdict / Driving+coverage+q&card counts / Tension), from the carried graph
        verdict summary. [] when the skill carries no rich graph — the lean stitle/phrase stands alone."""
        g = p.get("graph")
        if not isinstance(g, dict):
            return []
        call = _humanize(g.get("call")) or verdict
        conf = g.get("confidence_level")
        pol = g.get("polarity") or p.get("polarity")
        # headline sentence
        sent = f"<b>{_esc(call)}</b> — "
        sent += f"{_esc(conf)}-confidence " if conf else ""
        sent += f"{_esc(pol)} call" if pol else "call"
        if g.get("driving_rule_id"):
            sent += f" (driving: <code>{_esc(g['driving_rule_id'])}</code>)"
        sent += "."
        tension = g.get("top_tension") if isinstance(g.get("top_tension"), dict) else None
        if tension and tension.get("text"):
            sent += f" <span class='caveat'>⚠ {_esc(tension['text'])}.</span>"
        out = [f'<div class="headline">{sent}</div>']
        # kv grid
        cov = g.get("coverage") if isinstance(g.get("coverage"), dict) else {}
        drv_bits = []
        if g.get("driving_rule_id"):
            drv_bits.append(f"<code>{_esc(g['driving_rule_id'])}</code>")
        if conf:
            drv_bits.append(f"<span class='dots'>{_esc(conf)}</span>")
        if g.get("confidence_basis"):
            drv_bits.append(f"basis: {_esc(g['confidence_basis'])}")
        if cov.get("n_measured") is not None and cov.get("n_axes") is not None:
            ct = f"coverage {_esc(cov['n_measured'])}/{_esc(cov['n_axes'])} axes"
            if cov.get("n_critical_measured") is not None:
                ct += f" · {_esc(cov['n_critical_measured'])} critical"
            drv_bits.append(ct)
        drv_bits.append(f"{_esc(g.get('n_questions', 0))} q · {_esc(g.get('n_cards', 0))} cards")
        rows = [("Verdict", f"<b>{_esc(call)}</b>"), ("Driving", " · ".join(drv_bits))]
        if tension and tension.get("text"):
            sev = f" · sev {_esc(tension['severity'])}" if tension.get("severity") is not None else ""
            rows.append(("Tension", f"<span class='caveat'>⚠ {_esc(tension['text'])}{sev}</span>"))
        kv = "".join(f"<dt>{_esc(k)}</dt><dd>{v}</dd>" for k, v in rows)
        out.append(f'<dl class="kv">{kv}</dl>')
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
        return [
            f"<p class='kv'><b>Signals</b> ({p.get('shown', len(chips))}/{p.get('total', len(chips))}):</p>"
            f"<ul class='chips'>{items}</ul>"
        ]

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
        body = [
            [r.get("metric") or r.get("label"), r.get("value"), r.get("sample_context") or r.get("context")]
            for r in rows
        ]
        return ["<p class='section-label'>Metrics</p>", self._table(["metric", "value", "context"], body)]

    def _figure(self, p: dict) -> list:
        cap = _esc(p.get("caption") or "figure")
        ref = p.get("ref")
        badge = self._fig_badge(p.get("status"))
        if p.get("show_image") and ref:
            # inline only the PRIMARY (shown-inline) figures → self-contained + lean; the collapsed
            # "more figures" keep relative paths so the page doesn't balloon to megabytes.
            src = (self._inline_src(ref) if p.get("primary") else None) or _esc(ref)
            return [
                f"<figure><img src='{src}' alt='{cap}' loading='lazy'><figcaption>{badge}{cap}</figcaption></figure>"
            ]
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
            if not str(fp).startswith(str(self.asset_root.resolve())):  # path-escape guard
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
        return f"<span class='fig-badge sig-{sig}'>{_esc(status.get('icon') or '')} {_esc(status.get('label'))}</span> "

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
            bits.append(
                f"Spec: level={_esc(spec.get('level'))} · medium={_esc(spec.get('medium'))} · "
                f"scope={_esc(spec.get('scope'))} · lead={_esc(spec.get('lead'))}."
            )
        return [f"<div class='about'>{'<br>'.join(bits)}</div>"]

    # -- report-level overview (absorbed tp_dashboard v2 IA, spine-sourced) --------------------
    def _signals_overview(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        c = p.get("counts") or {}
        svg = _signal_strip_svg(rows, p.get("deciding_short"))
        lede = (
            "<p class='lede'>Each bar is one <b>gating subskill's verdict</b>, rolled up from its "
            "evidence cards (count shown per row). Bar direction/length is the subskill's polarity on "
            "the framework's ordinal scale — right supports the target, left counts against; a dot is "
            "neutral, a dashed box is not-evaluated. Descriptive (non-gating) subskills are context, "
            "listed below, not bars.</p>"
        )
        foot = (
            f"<p class='so-foot'><b>{c.get('support', 0)}</b> support · "
            f"<b>{c.get('neutral', 0)}</b> neutral · <b>{c.get('against', 0)}</b> against"
        )
        desc = p.get("descriptive") or []
        if desc:
            foot += " &nbsp;·&nbsp; descriptive context: " + _esc(", ".join(desc))
        foot += "</p>"
        return [f"<h2>Signals across subskills</h2>{lede}<div class='signal-strip'>{svg}</div>{foot}"]

    _DIM_CLASS = {3: "risk-high", 2: "risk-med", 1: "risk-low"}
    _DIM_LEVEL = {3: "HIGH", 2: "MED", 1: "LOW"}

    def _risk_6dim(self, p: dict) -> list:
        """The v6 6-dimension spine: one `<details class='dim risk-…'>` per dimension — a summary with the
        dimension name, a positioned low→med→high `.dbar`, and its `.dlevel`; the body `.dmembers` lists
        the feeding subskill signals (source · plain reading · level) + blind-spots / reconciliation."""
        dims = p.get("dims") or []
        if not dims:
            return []
        out = []
        for d in dims:
            rank = d.get("rank")
            cls = self._DIM_CLASS.get(rank, "risk-na")
            blind = " blind" if (cls == "risk-na") else ""
            level = self._DIM_LEVEL.get(rank) or (d.get("bin") if rank is None else None) or "unrouted"
            name = _esc(str(d.get("dim")).title())
            role = _esc(str(d.get("dim")))
            did = f"dim-{role}"
            summary = (
                f"<summary><span class='caret'>▸</span>"
                f"<span class='dn'>{name}<span class='rr'>{role}</span></span>"
                "<span class='dbar'><span class='track'><i></i></span>"
                "<span class='scale'><span>low</span><span>med</span><span>high</span></span></span>"
                f"<span class='dlevel'>{_esc(level)}</span></summary>"
            )
            members = d.get("members") or []
            mem_rows = "".join(
                f"<div class='mem'><span class='mn'>{_esc(m.get('source'))}"
                f"<small>{_esc(m.get('source'))}</small></span>"
                f"<span>{_esc(m.get('read') or '')}</span>"
                + (
                    f"<span class='dlevel' style='font-size:11px'>{_esc(m.get('level'))}</span>"
                    if m.get("level")
                    else "<span></span>"
                )
                + "</div>"
                for m in members
            )
            body = mem_rows
            bs = d.get("blind_spots") or []
            if bs:
                body += (
                    "<div class='dimlit'>⚑ blind spots (omics can't see): "
                    + _esc(", ".join(str(b) for b in bs))
                    + "</div>"
                )
            if d.get("mitigation"):
                body += f"<div class='dimlit'>↪ reconciliation: {_esc(str(d.get('mitigation')))}</div>"
            if not members and not bs and not d.get("mitigation"):
                body = "<div class='blindnote'>Engine-blind dimension — no feeding signal routed.</div>"
            out.append(
                f'<details class="dim {cls}{blind}" id="{did}">{summary}<div class="dmembers">{body}</div></details>'
            )
        return ["".join(out)]

    _EBUL_CLASS = {"supportive": "sup", "opposing": "against", "killer": "against", "neutral": "sup"}

    def _synthesis(self, p: dict) -> list:
        """SYNTHESIS is context-aware. The COMPOSED report (mode != 'bullets') renders the v6
        convergence layout (cross-evidence causal chain + integrator trust row + polarity exec
        bullets + central tension + cited literature). A STANDALONE subskill (mode == 'bullets')
        renders the sandbox two-tone AI-generated bullets + verbose expander. One handler, both
        approved designs, keyed on the block payload the builders set. Verdict-inert."""
        if p.get("mode") == "bullets":
            return self._synthesis_bullets(p)
        return self._synthesis_convergence(p)

    def _synthesis_convergence(self, p: dict) -> list:
        """The v6 convergence block (`.conv`): the cross-evidence causal chain (cnode → cedge → …), the
        integrator TRUST row, the LLM synthesis (`.exec` polarity bullets + `.tension` central tension),
        and the cited-literature `.litctx`. Verdict-inert — an advisory second read beside the spine."""
        conv = []
        ce = p.get("cross_evidence") or {}
        chain = ce.get("chain") or []
        if chain:
            warn_nodes = {c.get("from") for c in chain if c.get("type") == "contradicts"} | {
                c.get("to") for c in chain if c.get("type") == "contradicts"
            }

            def _node(short):
                ncls = "warn" if short in warn_nodes else "sup"
                return f"<div class='cnode {ncls}'><div class='ct'></div><b>{_esc(vocab.skill_title(short))}</b></div>"

            steps = []
            for c in chain:
                steps.append(_node(c.get("from")))
                steps.append(
                    f"<div class='cedge'><span class='ar'>→</span>{_esc(_humanize(c.get('type')) or '')}</div>"
                )
            if chain[-1].get("to"):
                steps.append(_node(chain[-1].get("to")))
            conv.append(f"<div class='causal'>{''.join(steps)}</div>")
        # TRUST row (cross-evidence defensibility + honest certainty divergence vs the spine).
        trust = []
        if ce.get("verdict"):
            trust.append(f"<span><span class='k'>Cross-evidence verdict</span><b>{_esc(ce['verdict'])}</b></span>")
        if ce.get("traceable") is not None or ce.get("coherence_violations") is not None:
            tr = _esc(ce.get("traceable") or "—")
            cv = _esc(ce.get("coherence_violations") if ce.get("coherence_violations") is not None else "—")
            trust.append(
                f"<span><span class='k'>Defensibility</span><span class='ok'>{tr} clauses traceable · "
                f"{cv} violations</span></span>"
            )
        if ce.get("certainty"):
            lim = f" (weakest link = {_esc(ce['limiting'])})" if ce.get("limiting") else ""
            trust.append(
                f"<span><span class='k'>Integrator certainty</span>"
                f"<span class='warn'>{_esc(_humanize(ce['certainty']))}</span>{lim}</span>"
            )
        if trust:
            conv.append(f"<div class='trust'>{''.join(trust)}</div>")
        # SYNTHESIS: polarity exec bullets + the integrator independent-read bullet + the central tension.
        bullets = p.get("exec_bullets") or []
        ebuls = []
        for b in bullets:
            cls = self._EBUL_CLASS.get(b.get("polarity"), "sup")
            ebuls.append(f"<div class='ebul {cls}'><span class='pol'></span><div>{_esc(b.get('text'))}</div></div>")
        if ce.get("verdict") or ce.get("certainty"):
            lim = f" (weakest link: {_esc(ce['limiting'])})" if ce.get("limiting") else ""
            ebuls.append(
                "<div class='ebul xev'><span class='pol'></span><div>"
                "<span class='xk'>Cross-evidence integrator · independent read</span>"
                f"{_esc(_humanize(ce.get('verdict')) or 'independent read')}, certainty "
                f"<b>{_esc(_humanize(ce.get('certainty')) or 'n/a')}</b>{lim} — a second opinion surfaced "
                "beside the composed spine, not reconciled into it.</div></div>"
            )
        exec_html = f"<div class='exec'>{''.join(ebuls)}</div>" if ebuls else ""
        tension_html = ""
        if p.get("tension_analysis"):
            tension_html = (
                f"<div class='tension'><div class='tl'>Central tension</div><p>{_esc(p['tension_analysis'])}</p></div>"
            )
        if exec_html or tension_html:
            conv.append(f"<div class='synth'>{exec_html}{tension_html}</div>")
        # LITCTX: cited co-mention literature (verdict-inert context).
        lit = p.get("literature") if isinstance(p.get("literature"), dict) else None
        if lit and (lit.get("total_comentions") or lit.get("cited_pmids")):
            head = (
                "<div class='lh'>Literature — cited co-mentions · VERDICT-INERT (text-mined; informs "
                "context, never changes the call)</div>"
            )
            vol = ""
            if lit.get("total_comentions") is not None:
                vol = f"<div style='margin-top:5px'><b>{int(lit['total_comentions']):,}</b> publications co-mention this target + indication"
                if lit.get("recent_comentions") is not None:
                    vol += f" (<b>{int(lit['recent_comentions']):,}</b> recent"
                    vol += f", latest {_esc(lit['latest_year'])}" if lit.get("latest_year") else ""
                    vol += ")"
                vol += " — co-occurrence volume, not curated causal support.</div>"
            cites = ""
            pmids = lit.get("cited_pmids") or []
            if pmids:
                links = "".join(
                    f"<div class='cr'><a class='cite' href='https://pubmed.ncbi.nlm.nih.gov/{_esc(pm)}' "
                    f"target='_blank'>PMID {_esc(pm)}</a></div>"
                    for pm in pmids
                )
                cites = f"<div class='cites'>{links}</div>"
            conv.append(f"<div class='litctx'>{head}{vol}{cites}</div>")
        # grounding provenance: the rule-ids lifted out of the exec prose → a collapsed affordance so the
        # narrative reads clean while the framework grounding stays one click away.
        rule_cites = p.get("citations") or []
        if rule_cites:
            codes = "".join(f"<code>{_esc(c)}</code>" for c in rule_cites)
            conv.append(
                f"<details class='cite-prov'><summary>Grounded in {len(rule_cites)} framework "
                f"rules</summary>{codes}</details>"
            )
        if not conv:
            return []
        return [f"<div class='conv'>{''.join(conv)}</div>"]

    def _synthesis_bullets(self, p: dict) -> list:
        out = ["<span class='tag'>AI-generated</span><h2>Synthesis</h2>"]
        _GLYPH = {"supportive": "△", "opposing": "▽", "killer": "▲", "neutral": "◆", "not_applicable": "·"}
        _CLS = {"supportive": "g-sup", "opposing": "g-opp", "killer": "g-kill", "neutral": "g-neu"}
        _POLCOL = {
            "supportive": "var(--supportive)",
            "opposing": "var(--opposing)",
            "killer": "var(--killer)",
            "neutral": "var(--neutral)",
        }
        bullets = p.get("exec_bullets") or []
        if bullets:
            lis = []
            for b in bullets:
                pol = b.get("polarity")
                anchors = b.get("cites") or {}
                ids = (anchors.get("card_ids") or []) + (anchors.get("citation_ids") or [])
                anc = (f" <span class='ke-anchor'>[{_esc(', '.join(ids[:3]))}]</span>") if ids else ""
                # two-tone: the omics/deterministic clause reads --det, the literature clause --lit
                # (verdict-inert; the split is a heuristic on the word "literature").
                lis.append(
                    f"<li style='--b:{_POLCOL.get(pol, 'var(--neutral)')}'>"
                    f"<span class='{_CLS.get(pol, 'g-neu')}'>{_GLYPH.get(pol, '•')}</span> "
                    f"{_two_tone(b.get('text'))}{anc}</li>"
                )
            out.append("<ul class='bullets exec-bullets'>" + "".join(lis) + "</ul>")
            out.append(
                "<div class='legendrow'><b class='fx-det'>■</b> omics/deterministic fact &nbsp; "
                "<b class='fx-lit'>■</b> literature fact</div>"
            )
        verbose_frag = []
        if p.get("executive_summary"):
            verbose_frag.append(f"<p>{_esc(p['executive_summary'])}</p>")
        if p.get("tension_analysis"):
            verbose_frag.append(f"<p class='kv'><b>Tensions:</b> {_esc(p['tension_analysis'])}</p>")
        args = p.get("arguments") or []
        if args:
            verbose_frag.append(
                "<ul class='chips'>" + "".join(f"<li>{_esc(_arg_summary(a))}</li>" for a in args) + "</ul>"
            )
        if verbose_frag:
            # bullets lead; the verbose prose is demoted behind an expander (Stage-2 secondary read).
            if bullets:
                out.append(
                    "<details class='full-narrative'><summary>Full narrative</summary>"
                    + "".join(verbose_frag)
                    + "</details>"
                )
            else:
                out.extend(verbose_frag)
        cites = p.get("citations") or []
        if cites:
            # rule-ids lifted out of the prose → a collapsed grounding affordance (hover/expand), so the
            # executive text reads clean while the provenance stays one click away.
            codes = "".join(f"<code>{_esc(c)}</code>" for c in cites)
            out.append(
                f"<details class='cite-prov'><summary>Grounded in {len(cites)} framework "
                f"rules</summary>{codes}</details>"
            )
        ce = p.get("cross_evidence")
        if ce:
            chain = ce.get("chain") or []
            steps = "".join(
                f"<span class='ce-node'>{_esc(c.get('from'))}</span>"
                f"<span class='ce-edge'>→ <small>{_esc(c.get('type') or '')}</small></span>"
                for c in chain
            )
            if chain and chain[-1].get("to"):
                steps += f"<span class='ce-node'>{_esc(chain[-1].get('to'))}</span>"
            trust = []
            if ce.get("verdict"):
                trust.append(f"verdict <b>{_esc(ce['verdict'])}</b>")
            if ce.get("certainty"):
                lim = f" (weakest link: {_esc(ce['limiting'])})" if ce.get("limiting") else ""
                trust.append(f"certainty <b>{_esc(ce['certainty'])}</b>{lim}")
            if ce.get("traceable"):
                trust.append(f"{_esc(ce['traceable'])} clauses traceable")
            if ce.get("coherence_violations") is not None:
                trust.append(f"{_esc(ce['coherence_violations'])} coherence violations")
            out.append(
                "<div class='cross-ev'><div class='ce-lbl'>Cross-evidence integrator · independent read</div>"
                + (f"<div class='ce-chain'>{steps}</div>" if steps else "")
                + (f"<div class='ce-trust'>{' · '.join(trust)}</div>" if trust else "")
                + "<div class='so-foot'>an independent second read, surfaced beside the spine's — not "
                "reconciled into it.</div></div>"
            )
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

    _MOD_COL_SHORT = {
        "small_molecule": "SM",
        "degrader": "Degrader",
        "biologics": "Biologic",
        "adc": "ADC",
        "bite_tce": "TCE",
        "antibody": "Antibody",
    }
    _MX_CELL = {"supportive": "g", "neutral": "n", "opposing": "h", "killer": "b"}

    def _modality_matrix(self, p: dict) -> list:
        """The v6 modality view: per-modality `.mrow` + `.mbul` viability bars (from modality_fit_by_channel),
        then the gate×modality `.matrix` ordinal grid (comp-bio power object). Verdict-inert display."""
        channels = p.get("channels") or []
        cols, rows = p.get("columns") or [], p.get("rows") or []
        if not channels and not (cols and rows):
            return []
        out = ["<h2 class='sh'>Modality fit <span class='sub'>· which drug format is viable, and why</span></h2>"]
        if channels:
            mrows = []
            for c in channels:
                st = c.get("status") or "unfavorable"
                if st == "not_applicable":
                    reason = _humanize(c.get("masked_by_axis")) or "not applicable to this target's biology"
                    mrows.append(
                        f"<div class='mrow na'><span class='mn'>{_esc(c.get('name'))}</span>"
                        f"<div class='mbul na'></div><span class='mwhy'>not applicable — {_esc(reason)}</span></div>"
                    )
                else:
                    why = c.get("label") or _humanize(st)
                    if c.get("limiting_axis"):
                        why = f"{_humanize(st)} — limited by {vocab.skill_title(c['limiting_axis'])}"
                    mrows.append(
                        f"<div class='mrow'><span class='mn'>{_esc(c.get('name'))}</span>"
                        f"<div class='mbul {_esc(st)}'><i></i></div><span class='mwhy'>{_esc(why)}</span></div>"
                    )
            out.append(f"<div class='card'>{''.join(mrows)}</div>")
        if cols and rows:
            head = "".join(f"<th>{_esc(self._MOD_COL_SHORT.get(c, str(c).replace('_', ' ')))}</th>" for c in cols)
            trs = []
            for r in rows:
                cells = r.get("cells") or {}
                tds = ""
                for m in cols:
                    cell = cells.get(m) or {}
                    if not cell.get("on_scale"):
                        tds += "<td class='off'>n/a</td>"
                    else:
                        cls = self._MX_CELL.get(cell.get("signal"), "n")
                        ordv = cell.get("ordinal")
                        val = f"{ordv:+d}" if isinstance(ordv, int) else _esc(cell.get("signal") or "")
                        tds += f"<td class='{cls}'>{_esc(val)}</td>"
                trs.append(f"<tr><td>{_esc(vocab.skill_title(r.get('short')))}</td>{tds}</tr>")
            legend = f"<p class='blindnote'>{_esc(p['glyph_legend'])}</p>" if p.get("glyph_legend") else ""
            out.append(
                "<h2 class='sh'>Gate × modality matrix <span class='sub'>· comp-bio power object — ordinal "
                "−3…+2, off-scale = n/a</span></h2>"
                "<div class='card' style='overflow-x:auto'>"
                f"<table class='matrix'><tr><th>Axis (gate)</th>{head}</tr>{''.join(trs)}</table>{legend}</div>"
            )
        return out

    _RL_CLASS = {"LOW": "rl-low", "MED": "rl-med", "MEDIUM": "rl-med", "HIGH": "rl-high"}
    _COH_CELL = {
        "agree": ("coh-ok", "✓ agree"),
        "grade-divergence": ("coh-warn", "△ grade divergence"),
        "contradicts": ("coh-bad", "✗ contradicts"),
        "literature-only": ("coh-gap", "⚠ literature-only"),
        "omics-only": ("coh-gap", "⚠ omics-only"),
    }

    def _rl(self, level) -> str:
        return self._RL_CLASS.get(str(level or "").upper(), "rl-na")

    def _literature_risk(self, p: dict) -> list:
        """The v6 lit×omics coherence `table.cohtab`: deep-research literature risk (cited PubMed) beside
        the deterministic omics (risk_6dim), per dimension, with an agreement read + an aggregate note.
        Literature is VERDICT-INERT context — it corroborates or flags, never overrides."""
        dims = p.get("dims") or []
        if not dims:
            return []
        trs = []
        n_agree = 0
        for d in dims:
            coh = d.get("coherence") or "—"
            if coh == "agree":
                n_agree += 1
            cc, ctxt = self._COH_CELL.get(coh, ("coh-gap", _esc(coh)))
            pm = d.get("pmids") or []
            pmtxt = f" <span class='note'>({len(pm)} PMIDs)</span>" if pm else ""
            ob = d.get("omics_bin") or "—"
            rl = d.get("risk_level") or "not_assessed"
            interp = _esc(d.get("interpretation") or "")
            interp_short = interp[:220] + ("…" if len(interp) > 220 else "")
            trs.append(
                f"<tr><td>{_esc(d.get('dim'))}</td>"
                f"<td class='{self._rl(ob)}'>{_esc(ob)}</td>"
                f"<td class='{self._rl(rl)}'>{_esc(rl)}{pmtxt}"
                f"<span class='note'>{interp_short}</span></td>"
                f"<td class='{cc}'>{ctxt}</td></tr>"
            )
        agg = (
            f"<div class='aggnote'><b>Aggregate:</b> {n_agree}/{len(dims)} dimension(s) concordant between the "
            "deterministic omics bin and the deep-research literature grade. Literature is "
            "<b>verdict-inert context</b> (citable_in_nominations = false) — it corroborates or flags, never "
            "overrides. Coherence is pre-computed per dimension (contradicts_deterministic + anchor read).</div>"
        )
        return [
            "<h2 class='sh'>Literature × omics coherence <span class='sub'>· deep-research literature risk "
            "(cited PubMed) vs deterministic omics (risk_6dim), per dimension, with agreement</span></h2>"
            "<div class='card' style='overflow-x:auto'>"
            "<table class='cohtab'><tr><th>Dimension</th><th>Omics — deterministic (risk_6dim)</th>"
            "<th>Deep-research literature (cited)</th><th>Coherence</th></tr>"
            f"{''.join(trs)}</table>{agg}</div>"
        ]

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
                items.append(f"<li><b>{_esc(r['axis'])}</b>: the call rests on {cond} — absent it → {tv}{dirn}</li>")
            else:
                items.append(f"<li><b>{_esc(r['axis'])}</b>: would become {tv}{dirn}</li>")
        return [f"<h2>What would change the call</h2><ul class='chips'>{''.join(items)}</ul>"]

    def _subtype(self, p: dict) -> list:
        if not p.get("verdict") and not p.get("subtypes"):
            return []
        axes = _esc(", ".join(p.get("axes_available") or []) or "—")
        out = [
            "<h2>Subtype stratification</h2>",
            f"<p class='kv'><b>Verdict:</b> {_esc(_humanize(p.get('verdict')))} "
            f"<span class='so-foot'>({p.get('n_evaluated', 0)} subtypes on {axes})</span></p>",
        ]
        for label, key in (
            ("Convergent", "convergent_subtypes"),
            ("Associated", "associated_subtypes"),
            ("Evaluated", "subtypes"),
        ):
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
        for lab, key in (
            ("driver role", "alteration_role"),
            ("mutation stratification", "mutation_stratification"),
            ("subtype stratification", "subtype_stratification"),
            ("survival", "survival_association"),
        ):
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
                + (
                    f" <span class='so-foot'>[{_esc(h.get('evidence_strength'))}]</span>"
                    if h.get("evidence_strength")
                    else ""
                )
                + "</li>"
                for h in hyps
            )
            out.append(f"<ul class='chips'>{li}</ul>")
        return out

    # -- faceted-rollup blocks (PR2) -----------------------------------------------------------
    def _synthesis_banner(self, p: dict) -> list:
        out = ["<span class='tag'>AI-generated · advisory</span><span class='so-foot'> — does not set the call</span>"]
        if p.get("executive_summary"):
            out.append(f"<p>{_esc(p['executive_summary'])}</p>")
        mm = p.get("mismatch")
        if isinstance(mm, dict) and mm.get("deterministic"):
            out.append(
                f"<p class='kv mismatch'>⚠ <b>LLM read:</b> {_esc(mm.get('llm'))} · "
                f"<b>deterministic call:</b> {_esc(mm['deterministic'])} — mismatch flagged "
                f"<span class='so-foot'>(the deterministic call stands)</span></p>"
            )
        cites = p.get("citations") or []
        if cites:
            codes = "".join(f"<code>{_esc(c)}</code>" for c in cites)
            out.append(
                f"<details class='cite-prov'><summary>Grounded in {len(cites)} framework "
                f"rules</summary>{codes}</details>"
            )
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
        return [
            "<p class='section-label'>AI read <span class='so-foot'>· advisory</span></p>"
            f"<ul class='chips notes'>{''.join(items)}</ul>"
        ]

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
                color = {
                    "supportive": "var(--supportive)",
                    "opposing": "var(--opposing)",
                    "killer": "var(--killer)",
                    "neutral": "var(--neutral)",
                }.get(pol, "var(--neutral)")
                glyph = vocab.polarity_glyph(pol)
            rpoints.append(
                {
                    "x": pt.get("confidence_x"),
                    "y": pt.get("signal_y"),
                    "label": (pt.get("name") if is_sg else pt.get("title")) or "",
                    "color": color,
                    "glyph": glyph,
                    "ring": bool(pt.get("conflict")),
                    "deciding": bool(pt.get("is_deciding")),
                }
            )
        title = "Signals × confidence" + (" — sub-groups" if is_sg else "")
        svg = _scatter_svg(rpoints, p.get("y_ticks") or [], p.get("x_ticks") or [])
        head = (
            f"<p class='section-label'>{_esc(title)}</p>"
            if is_sg
            else f"<h2>{_esc(title)} <span class='so-foot'>— each point is a gating subskill; "
            f"x = confidence, y = signal strength, colour = direction</span></h2>"
        )
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
        return [
            "<p class='section-label'>Sub-group bands</p>",
            self._table(["sub-group", "signal", "confidence", "sources"], body),
        ]

    def _cross_cutting(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        body = [[_esc(r.get("question")), _esc(r.get("owner")), _esc(_humanize(r.get("informs")))] for r in rows]
        return [
            "<h2>Cross-cutting questions <span class='so-foot'>— measured by one axis, informs another</span></h2>",
            self._table(["question", "measured by", "informs"], body),
        ]

    # -- evidence-graph blocks (P3): the RICH embedded view == the standalone dashboard ----------
    _EG_POL_COLOR = {
        "supportive": "var(--supportive)",
        "opposing": "var(--opposing)",
        "killer": "var(--killer)",
        "neutral": "var(--neutral)",
    }
    _EG_POL_CLS = {"supportive": "g-sup", "opposing": "g-opp", "killer": "g-kil", "neutral": "g-neu"}
    _EG_DOTS_OPACITY = {3: "1", 2: ".6", 1: ".38", 0: ".3"}
    # Compact FILLED polarity mark stamped INSIDE each heatmap cell — a secondary (non-colour, non-hover)
    # encoding of the signal, so the mark is not colour-only (the vocab △/▽ outlines + the ⛔ emoji do
    # not read at 15px on a coloured fill; vocab is left untouched). Confidence is a discrete RING weight
    # (thicker = higher), NOT opacity — opacity desaturated a status hue toward neutral, letting a
    # low-confidence supportive cell read as neutral (the confidence channel corrupting the identity one).
    _HMCELL_GLYPH = {"supportive": "▲", "opposing": "▼", "killer": "✕", "neutral": "•"}
    _HM_CONF_CLS = {3: "hm-c3", 2: "hm-c2", 1: "hm-c1", 0: "hm-c0"}
    _HM_CONF_WORD = {3: "high", 2: "moderate", 1: "low", 0: "n/a"}
    # literature-vs-omics agreement glyph inside the litdot (concordance at a glance, not the old
    # “ cited/not mark): ✓ agree · ✗ contradicts · ≈ mixed · · none.
    _LIT_AGREE_GLYPH = {
        "agree": "✓",
        "consistent": "✓",
        "corroborates": "✓",
        "contradicts": "✗",
        "inconsistent": "✗",
        "mixed": "≈",
    }

    def _eg_color(self, polarity, liability=False) -> str:
        if liability:
            return "var(--killer)"
        return self._EG_POL_COLOR.get(polarity, "var(--neutral)")

    def _evidence_fingerprint(self, p: dict) -> list:
        qs = p.get("questions") or []
        if not qs:
            return []
        groups = []
        twin_rows = []  # accessible table twin (keyboard / print / screen-reader path — not hover-only)
        for q in qs:
            gcls = self._EG_POL_CLS.get(q.get("polarity"), "g-neu")
            glyph = vocab.polarity_glyph(q.get("polarity"))
            qtext = q.get("text") or q.get("id") or ""
            cells = []
            for c in q.get("cells") or []:
                pol = "killer" if c.get("liability") else (c.get("polarity") or "neutral")
                col = self._eg_color(c.get("polarity"), c.get("liability"))
                dots = c.get("dots") if isinstance(c.get("dots"), int) else -1
                ccls = self._HM_CONF_CLS.get(dots, "hm-c0")
                cword = self._HM_CONF_WORD.get(dots, "n/a")
                cg = self._HMCELL_GLYPH.get(pol, "·")
                liab = " · liability" if c.get("liability") else ""
                tip = f"{c.get('card_id')} · {c.get('polarity')} · confidence {cword}{liab}"
                # fill = signal (FULL opacity, never desaturated); glyph = signal (secondary); ring = confidence
                cells.append(f"<span class='hmcell {ccls}' title='{_esc(tip)}' style='background:{col}'>{cg}</span>")
                twin_rows.append(
                    f"<tr><td>{_esc(qtext)}</td><td class='mono'>{_esc(str(c.get('card_id') or ''))}</td>"
                    f"<td>{_esc(str(c.get('polarity') or '—'))}{_esc(liab)}</td><td>{_esc(cword)}</td></tr>"
                )
            lit = q.get("lit")
            if lit:
                agr = lit.get("agreement") or lit.get("read")
                lcol = {"agree": "var(--supportive)", "mixed": "var(--opposing)", "contradicts": "var(--killer)"}.get(
                    agr, "var(--neutral)"
                )
                # glyph = literature-vs-omics AGREEMENT (✓ agree · ✗ contradicts · ≈ mixed · · none),
                # not the old “ cited/not mark — the reader sees concordance at a glance. Cited status
                # stays in the tooltip + the table twin.
                mark = self._LIT_AGREE_GLYPH.get(agr, "·")
                cited = " · cited" if lit.get("cited") else ""
                litdot = (
                    f"<span class='hmsep'></span><span class='litdot' style='background:{lcol}' "
                    f"title='literature · {_esc(str(lit.get('read')))} · {_esc(str(agr))}{cited}'>{mark}</span>"
                )
            else:
                litdot = (
                    "<span class='hmsep'></span><span class='litdot' style='opacity:.25' "
                    "title='no literature for this question'>·</span>"
                )
            lbl = _esc(qtext)
            groups.append(
                f"<div class='hmg'><div class='hmglab'><span class='{gcls}'>{_esc(glyph)}</span> {lbl}</div>"
                f"<div class='hmcells'>{''.join(cells)}{litdot}</div></div>"
            )
        note = (
            "<div class='hmnote'>card — fill + mark = signal (▲ supportive · ▼ opposing · ✕ "
            "liability/killer · • neutral), ring = confidence (thicker = higher) &nbsp;·&nbsp; ● "
            "literature (✓ agree · ✗ contradicts · ≈ mixed · · none)</div>"
        )
        twin = (
            "<details class='hm-twin'><summary>Table view</summary>"
            "<table><thead><tr><th>Question</th><th>Card</th><th>Signal</th><th>Confidence</th></tr></thead>"
            f"<tbody>{''.join(twin_rows)}</tbody></table></details>"
        )
        return [
            "<h2>Evidence fingerprint <span class='so-foot'>— per question: one cell per contributing "
            "card (fill+mark = signal, ring = confidence); literature dot colour = agreement</span></h2>"
            f"<div class='eg-inner'><div class='hm'>{''.join(groups)}</div>{note}{twin}</div>"
        ]

    _CFP_LIT_COLOR = {
        "consistent": "var(--supportive)",
        "corroborates": "var(--supportive)",
        "agree": "var(--supportive)",
        "mixed": "var(--warning)",
        "inconsistent": "var(--killer)",
        "contradicts": "var(--killer)",
    }

    def _composed_fingerprint(self, p: dict) -> list:
        """The composed at-a-glance grid: every subskill's verdict as a chip, grouped by lens, with the
        deciding axis outlined and a literature-agreement dot. Reads the COMPOSED_FINGERPRINT block (built
        from the target_report.evidence_graph index) — the composed analog of the per-question fingerprint."""
        lanes = p.get("lanes") or []
        if not lanes:
            return []
        v = p.get("verdict") or {}
        vbits = []
        if v.get("recommendation"):
            vbits.append(f"<span class='rec'>{_esc(_humanize(v['recommendation']))}</span>")
        if v.get("confidence"):
            vbits.append(f"confidence {_esc(_humanize(v['confidence']))}")
        deciding = v.get("deciding_shorts") or []
        if deciding:
            vbits.append("deciding: " + _esc(", ".join(vocab.skill_title(s) for s in deciding)))
        verdict_line = f"<div class='cfp-verdict'>Call → {' · '.join(vbits)}</div>" if vbits else ""
        lanehtml = []
        for lane in lanes:
            chips = []
            for s in lane.get("skills") or []:
                pol = s.get("polarity")
                gcls = self._EG_POL_CLS.get(pol, "g-neu")
                call = _humanize(s.get("call")) or vocab.polarity_label(pol)
                lc = s.get("literature_consistency")
                litdot = ""
                if lc:
                    lcol = self._CFP_LIT_COLOR.get(str(lc), "var(--neutral)")
                    litdot = f"<span class='clit' style='background:{lcol}'></span>"
                dec = " deciding" if s.get("deciding") else ""
                tip = f"{s.get('short')} · {call}"
                if s.get("confidence"):
                    tip += f" · confidence {s.get('confidence')}"
                if lc:
                    tip += f" · literature {lc}"
                inner = (
                    f"<span class='{gcls}'>{_esc(vocab.polarity_glyph(pol))}</span>"
                    f"<span class='ct'>{_esc(s.get('title'))}</span>"
                )
                if call:
                    inner += f"<span class='cc'>{_esc(call)}</span>"
                chips.append(f"<span class='cfp-chip{dec}' title='{_esc(tip)}'>{inner}{litdot}</span>")
            lanehtml.append(
                f"<div class='cfp-lane'><div class='cfp-lens'>{_esc(lane.get('title'))}</div>"
                f"<div class='cfp-chips'>{''.join(chips)}</div></div>"
            )
        dissent = p.get("dissent") or []
        dhtml = ""
        if dissent:
            rows = []
            for d in dissent:
                src = vocab.skill_title(d["source"]) if d.get("source") else "a signal"
                note = _esc(d.get("note")) if d.get("note") else "dissents from the call"
                rt = f" → resolved to <b>{_esc(_humanize(d.get('resolved_to')))}</b>" if d.get("resolved_to") else ""
                rows.append(f"<div><b>{_esc(src)}</b>: {note}{rt}</div>")
            dhtml = f"<div class='cfp-dissent'><span class='dhead'>⚠ Dissent</span>{''.join(rows)}</div>"
        return [
            "<h2>At a glance <span class='so-foot'>— every subskill's verdict, grouped by lens; the "
            "deciding axis is outlined, the dot shows literature agreement</span></h2>"
            f"{verdict_line}<div class='cfp'>{''.join(lanehtml)}</div>{dhtml}"
        ]

    def _gauge(self, c: dict) -> str:
        """Visual reference-frame ruler(s) for a card — one track per interpretation[] frame (a card may
        carry >1: a pan-cancer rank AND a within-panel position). Each track has floor/cut/ceiling (or
        comparator) ticks + a polarity-coloured value marker, captioned by the plain gauge words. '' when
        the card has no ruler."""
        interp = c.get("interpretation") or []
        words_all = c.get("gauges") or ([c.get("gauge")] if c.get("gauge") else [])
        tracks = []
        for i, gv in enumerate(interp):
            if isinstance(gv, dict):
                tracks.append(self._gauge_track(c, gv, words_all[i] if i < len(words_all) else None))
        return "".join(t for t in tracks if t)

    def _gauge_track(self, c: dict, gv: dict, words) -> str:
        """One visual track for a single gauged_value (see _gauge). On a plain numeric axis (min→max of the
        points) so the marker placement can't invert; the words carry the past/short-of-cut reading."""
        if not gv or gv.get("value") is None:
            return ""
        val = gv.get("value")
        anchors = [
            a
            for a in ((gv.get("frame") or {}).get("anchors") or [])
            if isinstance(a, dict) and isinstance(a.get("value"), (int, float)) and not isinstance(a.get("value"), bool)
        ]
        pts = ([val] if isinstance(val, (int, float)) and not isinstance(val, bool) else []) + [
            a["value"] for a in anchors
        ]
        if len(pts) < 2:  # not enough to draw a track — words only
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
                comp_mark = (
                    f"<span class='gmark gcomp' style='left:{_pos(a['value']):.1f}%;"
                    f"color:var(--muted)' title='{_esc(_alab(a))} {_esc(a['value'])}'></span>"
                )
                continue
            cls = "gtick gcut" if a.get("role") == "cut" else "gtick"
            ticks.append(
                f"<span class='{cls}' style='left:{_pos(a['value']):.1f}%'>"
                f"<span class='gtlab'>{_esc(_alab(a))}</span></span>"
            )
        key = "killer" if c.get("liability") else c.get("polarity")
        color = self._EG_POL_COLOR.get(key, "var(--neutral)")
        mark = (
            f"<span class='gmark' style='left:{_pos(val):.1f}%;color:{color}' "
            f"title='{_esc(gv.get('metric'))} {_esc(val)}'></span>"
        )
        cap = f"<div class='gcap'>{_esc(words)}</div>" if words else ""
        return (
            f"<div class='gauge'><div class='gtrack'><span class='grail'></span>"
            f"{''.join(ticks)}{comp_mark}{mark}</div>{cap}</div>"
        )

    # meter width by the question's signal tier (the sandbox `.mfill` scale) — the bar length reads the
    # strength at a glance; DIRECTION stays in the polarity glyph + colour (position ≠ direction, CVD-safe).
    _METER_W = {"strong": 90, "moderate": 60, "weak": 30, "absent": 16, "uniform": 45, "high": 90, "low": 30}

    @staticmethod
    def _dots_str(n) -> str:
        n = n if isinstance(n, int) and 0 <= n <= 3 else 0
        return "●" * n + "○" * (3 - n)

    def _chain_card_row(self, c: dict) -> str:
        """One card's dataset→data→rule→verdict drill row (shared by the question-grouped `.qr` view and
        the measurement-type `pklayer` fallback): role badge + signal glyph, plain description, Reads:
        <class>, the visual gauge, the split metric-gloss (.kegloss) + top-strata table (.ketbl), and the
        provenance chain line."""
        key = "killer" if c.get("liability") else c.get("polarity")
        gl, gcls = vocab.polarity_glyph(key), self._EG_POL_CLS.get(key, "g-neu")
        ds = " · ".join(c.get("dataset_ids") or []) or "—"
        data = " · ".join(f"{_esc(d.get('field'))}={_esc(d.get('value'))}" for d in (c.get("data") or [])) or "—"
        if c.get("rule_id"):
            drv = "<span class='pill-drv'>DRIVING</span> " if c.get("is_driving") else ""
            rule = f"{drv}<span class='mono'>{_esc(c.get('rule_id'))}</span>"
        else:
            rule = "<span class='pill-none'>display-only · no rule fired</span>"
        nfrag = f" · n={_esc(c.get('n'))}" if c.get("n") is not None else ""
        # class-led plain-language order: description → Reads: <class> → gauge → split gloss → chain drill
        desc = c.get("description")
        desc_line = f"<div class='cdesc'>{_esc(desc)}</div>" if desc else ""
        reads = c.get("reads")
        reads_line = f"<div class='cread'>Reads: <b class='{gcls}'>{_esc(reads)}</b></div>" if reads else ""
        gauge = self._gauge(c)  # the reference-frame ruler (visual support layer)
        kegloss = self._kegloss_html(c)  # the TEXT companion (metric label = value · n · stat + help)
        ketbl = self._ketbl_html(c)  # the top-strata table
        # the compact narrator-grounding key line (omnibus + categorical + subtype the effect-only
        # kegloss doesn't carry) — kept as the comprehensive one-liner beside the split gloss.
        ke = c.get("key_evidence_summary")
        ke_line = (
            f"<div class='chainline keyev'><span class='lab'>key</span> <span class='mono'>{_esc(ke)}</span></div>"
            if ke
            else ""
        )
        if c.get("is_driving"):
            badge = "<span class='rbadge rb-drv'>drives verdict</span>"
        elif c.get("contributes"):
            badge = "<span class='rbadge rb-con'>contributes</span>"
        else:
            badge = "<span class='rbadge rb-ctx'>context</span>"
        mt = c.get("measurement_type")
        mttag = f"<span class='mttag'>{_esc(str(mt).replace('_', ' '))}</span>" if mt else ""
        return (
            f"<div class='cardln'><div class='chead'><span>{badge}<b>{_esc(c.get('id'))}</b>{mttag}</span>"
            f"<span class='ccchip'><span class='{gcls}'>{_esc(gl)}</span>{nfrag}</span></div>"
            f"{desc_line}{reads_line}{gauge}{kegloss}{ketbl}{ke_line}"
            f"<div class='chainline'><span class='lab'>ds</span> <span class='mono'>{_esc(ds)}</span>"
            f" <span class='sep'>→</span> <span class='lab'>data</span> {data}"
            f" <span class='sep'>→</span> <span class='lab'>rule</span> {rule}</div></div>"
        )

    def _kegloss_html(self, c: dict) -> str:
        """The sandbox split metric-gloss: `<metric label> = <value> · n=… · <stat>=<value>` on the
        omics tone (--det) + a muted plain-language help line. '' when the card carries no numeric effect
        (the key_evidence_summary + gauge already cover the categorical cards)."""
        kg = c.get("kegloss")
        if not isinstance(kg, dict) or kg.get("value") is None:
            return ""
        head = f"<span class='m'>{_esc(kg.get('label'))} = {_esc(kg.get('value'))}</span>"
        if kg.get("n") is not None:
            head += f" · n={_esc(kg.get('n'))}"
        if kg.get("stat") and kg.get("stat_value") is not None:
            head += f" · {_esc(kg.get('stat'))}={_esc(kg.get('stat_value'))}"
        help_line = f"<br><span class='h'>{_esc(kg.get('help'))}</span>" if kg.get("help") else ""
        return f"<div class='kegloss'>{head}{help_line}</div>"

    def _ketbl_html(self, c: dict) -> str:
        """The key_evidence.top_strata table (.ketbl): indication / strongest / weakest stratum rows."""
        strata = c.get("top_strata") or []
        if not strata:
            return ""
        rows = []
        for s in strata:
            if not isinstance(s, dict):
                continue
            role = f"<span class='kerole'>{_esc(s.get('role'))}</span>" if s.get("role") else ""
            val = _esc(s.get("value"))
            if s.get("n") is not None:
                val += f" (n={_esc(s.get('n'))})"
            if s.get("q") is not None:
                val += f" · q={_esc(s.get('q'))}"
            rows.append(f"<tr><td>{_esc(s.get('label'))}{role}</td><td>{val}</td></tr>")
        return f"<table class='ketbl'>{''.join(rows)}</table>" if rows else ""

    def _qstrip_html(self, cards: list) -> str:
        """The mini per-card signal strip in a question <summary> — one small cell per contributing card
        (fill = signal polarity, ring = confidence), echoing the fingerprint at question granularity."""
        cells = []
        for c in cards or []:
            col = self._eg_color(c.get("polarity"), c.get("liability"))
            dots = c.get("dots") if isinstance(c.get("dots"), int) else -1
            ccls = self._HM_CONF_CLS.get(dots, "hm-c0")
            cells.append(f"<span class='qcell {ccls}' style='background:{col}' title='{_esc(c.get('id'))}'></span>")
        return "".join(cells)

    def _card_chain(self, p: dict) -> list:
        layers = p.get("layers") or []
        if not layers:
            return []
        out = ["<p class='section-label'>Cards — dataset → data → rule → verdict</p>"]
        by_question = p.get("grouped_by") == "question"
        if by_question:
            groups = []
            for i, lyr in enumerate(layers):
                cards = lyr.get("cards") or []
                rows = "".join(self._chain_card_row(c) for c in cards)
                pol = lyr.get("polarity")
                color = self._EG_POL_COLOR.get(pol, "var(--neutral)")
                gcls = self._EG_POL_CLS.get(pol, "g-neu")
                glyph = vocab.polarity_glyph(pol)
                width = self._METER_W.get(lyr.get("tier"), 50)
                meter = (
                    f"<span class='meter'><span class='mfill' style='width:{width}%;background:{color}'></span></span>"
                )
                dots = self._dots_str(lyr.get("dots"))
                conf = _esc(lyr.get("conf_level") or "")
                key = f"<div class='qkey'>{_esc(lyr.get('key'))}</div>" if lyr.get("key") else ""
                strip = self._qstrip_html(cards)
                openattr = " open" if i == 0 else ""
                groups.append(
                    f'<details class="qr"{openattr}><summary>'
                    f"<span class='qcaret'></span>"
                    f"<div><div class='qtitle'>{_esc(lyr.get('layer'))}</div>{key}"
                    f"<div class='qstrip'>{strip}<span class='qcount'>{len(cards)} cards</span></div></div>"
                    f"<div><span class='{gcls}'>{_esc(glyph)}</span> {meter}</div>"
                    f"<div class='dots'>{dots} {conf}</div>"
                    f"</summary><div class='lbody'>{rows}</div></details>"
                )
            out.append(f'<div class="qtab">{"".join(groups)}</div>')
            return out
        # measurement-type fallback (gateless / unmapped skills): the lean accordion, unchanged.
        for lyr in layers:
            cards = lyr.get("cards") or []
            rows = "".join(self._chain_card_row(c) for c in cards)
            out.append(
                f"<details class='pklayer'><summary><span>{_esc(lyr.get('layer'))}</span>"
                f"<span class='ccinline'>{len(cards)} card(s)</span></summary>"
                f"<div class='lbody'>{rows}</div></details>"
            )
        return out

    def _literature_axes(self, p: dict) -> list:
        axes = p.get("axes") or []
        blind = p.get("blind_spots") or []
        if not axes and not blind:
            return []

        def _cite_pills(cites):
            out = []
            for c in cites or []:
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
                f"<div class='cardln litaxis'><div class='chead'><span>axis {_esc(a.get('axis_id'))} — "
                f"<b>{_esc(a.get('read'))}</b></span><span class='ccchip'><span class='{acls}'>{_esc(agr)}</span>"
                f" · {_esc(a.get('confidence'))}{qtag}</span></div>"
                f"{_esc(a.get('assertion') or '')} {_cite_pills(a.get('citations'))}</div>"
            )
        for b in blind:
            why = f" <span class='so-foot'>{_esc(b.get('why_omics_blind'))}</span>" if b.get("why_omics_blind") else ""
            rows.append(
                f"<div class='cardln litaxis'><div class='chead'><span>blind spot</span></div>"
                f"{_esc(b.get('text') or '')}{why} {_cite_pills(b.get('citations'))}</div>"
            )
        oc = p.get("overall_consistency")
        head = (
            "<h2>Literature <span class='so-foot'>— per-axis agreement vs omics"
            f"{(' · overall ' + _esc(oc)) if oc else ''}</span></h2>"
        )
        return [head + "".join(rows)]


import re as _re

_LIT_SPLIT = _re.compile(r"(literature)", _re.IGNORECASE)


def _two_tone(text) -> str:
    """Split one narrative bullet into an omics clause (--det) + a literature clause (--lit) on the first
    occurrence of the word "literature" — the sandbox's omics-vs-literature two-tone. No match → the whole
    clause reads as the omics tone. Escapes each clause; verdict-inert display only."""
    s = "" if text is None else str(text)
    m = _LIT_SPLIT.search(s)
    if not m:
        return f"<span class='fx-det'>{escape(s)}</span>"
    return f"<span class='fx-det'>{escape(s[: m.start()])}</span><span class='fx-lit'>{escape(s[m.start() :])}</span>"


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
    s = [
        f"<svg viewBox='0 0 {W} {H}' width='100%' role='img' aria-label='signal by confidence' "
        f"style='font-family:-apple-system,Segoe UI,sans-serif'>"
    ]
    # gridlines + y tick labels (bottom→top)
    for yi, yt in enumerate(y_ticks):
        y = T + (ny - 1 - yi) * cellh + cellh / 2
        s.append(f"<line x1='{L}' y1='{y:.1f}' x2='{L + nx * cellw}' y2='{y:.1f}' stroke='{line}' stroke-width='1'/>")
        s.append(f"<text x='{L - 8}' y='{y + 4:.1f}' text-anchor='end' font-size='11' fill='{muted}'>{_esc(yt)}</text>")
    # x tick labels
    for xi, xt in enumerate(x_ticks):
        x = L + (xi + 0.5) * cellw
        s.append(
            f"<text x='{x:.1f}' y='{H - B + 26}' text-anchor='middle' font-size='11' fill='{muted}'>{_esc(xt)}</text>"
        )
    s.append(
        f"<text x='{L + nx * cellw}' y='{H - B + 26}' text-anchor='end' font-size='10.5' "
        f"fill='{muted}'>confidence →</text>"
    )
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
            ring = (
                ("<circle cx='%.1f' cy='%.1f' r='9' fill='none' stroke='#b26a00' stroke-width='1.5'/>" % (px, y))
                if pt.get("ring")
                else ""
            )
            dec = "  ◆" if pt.get("deciding") else ""
            s.append(ring)
            s.append(
                f"<circle cx='{px:.1f}' cy='{y:.1f}' r='6' fill='{pt['color']}' stroke='#fff' stroke-width='1.5'/>"
            )
            s.append(
                f"<text x='{px + 9:.1f}' y='{y + 4:.1f}' font-size='11' fill='{ink}'>{_esc(pt['label'])}{dec}</text>"
            )
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
    return (
        base + f"{active}{{color:var(--ink);border-color:var(--border);"
        f"border-bottom-color:var(--surface);background:var(--surface);}}" + f"{visible}{{display:block;}}"
    )


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
    pos, neg, neu, gap, ink, muted, line = ("#1a6b1a", "#a1231d", "#8a5a00", "#8592a0", "#141c26", "#6b7783", "#d5dde4")
    s = [
        f"<svg viewBox='0 0 {W} {H}' width='100%' role='img' aria-label='Signal per skill' "
        f"style='font-family:-apple-system,Segoe UI,sans-serif'>",
        f"<text x='{cx - 6}' y='16' text-anchor='end' font-size='10.5' font-weight='700' fill='{neg}'>"
        f"◀ counts against</text>",
        f"<text x='{cx + 6}' y='16' text-anchor='start' font-size='10.5' font-weight='700' fill='{pos}'>"
        f"supports ▶</text>",
        f"<line x1='{cx}' y1='{TOP - 4}' x2='{cx}' y2='{H - BOT + 2}' stroke='{line}' stroke-width='1.5'/>",
    ]
    for i, r in enumerate(rows):
        cyr = TOP + i * RH + RH / 2
        lv = r.get("level")
        dec = "  ◆ deciding" if r.get("is_deciding") else ""
        # plain-language sublabel: prefer the honest_phrase, fall back to a de-snake-cased call.
        sub = r.get("honest_phrase") or _humanize(r.get("call")) or r.get("polarity") or ""
        s.append(
            f"<text x='{LBL - 14}' y='{cyr - 2:.1f}' text-anchor='end' font-size='12.5' fill='{ink}'>"
            f"{_esc(r.get('title'))}</text>"
        )
        # a thesis-expected negative renders as a neutral dot; append the reason so the reframe is explicit.
        note = f"  · {r['expected_note']}" if r.get("expected_note") else ""
        nc = r.get("n_cards")
        cards = f"  · {nc} cards" if nc else ""  # where the signal comes from (rollup provenance)
        vline = _esc(str(sub) + note + cards) + ("  · not evaluated" if lv is None else "") + dec
        s.append(
            f"<text x='{LBL - 14}' y='{cyr + 12:.1f}' text-anchor='end' font-size='10.5' fill='{muted}'>{vline}</text>"
        )
        if lv is None:
            s.append(
                f"<rect x='{cx - 6}' y='{cyr - 6:.1f}' width='12' height='12' rx='2' fill='none' "
                f"stroke='{gap}' stroke-width='1.5' stroke-dasharray='2 2'/>"
            )
        elif lv == 0:
            s.append(f"<circle cx='{cx}' cy='{cyr:.1f}' r='5.5' fill='none' stroke='{neu}' stroke-width='2'/>")
        else:
            w = abs(lv) * UNIT
            col = pos if lv > 0 else neg
            bx = cx if lv > 0 else cx - w
            s.append(f"<rect x='{bx:.1f}' y='{cyr - 7:.1f}' width='{w:.1f}' height='14' rx='4' fill='{col}'/>")
    s.append("</svg>")
    return "".join(s)


# reuse the text backend's shape-tolerant summarizers (single source, no vocab drift).
from .text import (  # noqa: E402
    _chip_summary,
    _confidence_summary,
    _humanize,
    _qt_conf,
    _qt_question,
    _qt_signal,
)

__all__ = ["HtmlBackend"]
