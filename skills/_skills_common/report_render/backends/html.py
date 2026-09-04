"""HTML dashboard backend — a self-contained, single-file document (own CSS, light + dark).

Deliberately NOT built on tp_render_html's skeleton (that file is under active redesign on a parallel
branch — coupling would collide). It reuses only the stable single-vocabulary `ordinal_view` polarity
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
        }

    def handled_kinds(self) -> set:
        return set(self._handlers)

    # -- structure -----------------------------------------------------------------------------
    def render(self, ir: ReportIR) -> str:
        title = f"Target report — {_esc(ir.target or '—')} × {_esc(ir.indication or '—')}"
        parts = [
            "<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{title}</title><style>{_CSS}</style></head><body><div class='wrap'>",
        ]
        parts.append(self._wrap_card("".join(self._emit(ir.header)), extra="decision"))
        for b in ir.overview:
            parts.append(self._wrap_card("".join(self._emit(b))))
        for sec in ir.sections:
            parts.append(self._emit_section(sec))
        if ir.about is not None:
            parts.append("".join(self._emit(ir.about)))
        parts.append("</div></body></html>")
        return "\n".join(parts) + "\n"

    def _emit(self, block: Block) -> list:
        return self._handlers[block.kind](block.payload)

    def _wrap_card(self, inner: str, extra: str = "") -> str:
        cls = f"card {extra}".strip()
        return f"<section class='{cls}'>{inner}</section>"

    def _emit_section(self, sec: Section) -> str:
        pol = sec.blocks[0].payload.get("polarity") if sec.blocks else None
        cls = f"card {_POL_CLASS.get(pol or '', '')}".strip()
        # FIGURE grouping: show the PRIMARY figure per card inline; collapse the rest into one
        # "N more figures" <details> so a dependency card with 18 plots is not a data-dump.
        parts, extra = [], []
        for b in sec.blocks:
            if b.kind == vocab.FIGURE and not b.payload.get("primary"):
                extra.append(b)
                continue
            parts.append("".join(self._emit(b)))
        if extra:
            figs = "".join("".join(self._emit(b)) for b in extra)
            parts.append(f"<details class='fig-more'><summary>{len(extra)} more figure(s)</summary>"
                         f"{figs}</details>")
        return f"<section class='{cls}'>{''.join(parts)}</section>"

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
        if p.get("executive_summary"):
            out.append(f"<p>{_esc(p['executive_summary'])}</p>")
        if p.get("tension_analysis"):
            out.append(f"<p class='kv'><b>Tensions:</b> {_esc(p['tension_analysis'])}</p>")
        args = p.get("arguments") or []
        if args:
            out.append("<ul class='chips'>"
                       + "".join(f"<li>{_esc(_arg_summary(a))}</li>" for a in args) + "</ul>")
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
