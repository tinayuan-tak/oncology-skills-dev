"""HTML dashboard backend — a self-contained, single-file document (own CSS, light + dark).

Deliberately NOT built on tp_render_html's skeleton (that file is under active redesign on a parallel
branch — coupling would collide). It reuses only the stable single-vocabulary `ordinal_view` polarity
scale via `vocab`. Like every backend it is dumb: one {block-kind → HTML fragment} handler set, no
selection logic (the IR builder already tiered/scoped/medium-resolved every block).
"""
from __future__ import annotations

from html import escape

from .. import vocab
from ..ir import Block, ReportIR, Section

_POL_CLASS = {
    "killer": "pol-killer", "opposing": "pol-opposing", "neutral": "pol-neutral",
    "supportive": "pol-supportive",
}


def _esc(x) -> str:
    return escape("" if x is None else str(x))


_CSS = """
:root {
  --bg:#f7f8fa; --card:#ffffff; --ink:#1a1d24; --muted:#5b6472; --line:#e3e7ee;
  --killer:#c02929; --opposing:#c77714; --neutral:#8a94a6; --supportive:#2e8b57; --none:#9aa4b2;
  --go:#2e8b57; --hold:#c77714; --kill:#c02929;
}
@media (prefers-color-scheme: dark) {
  :root { --bg:#0f1216; --card:#171b21; --ink:#e6e9ef; --muted:#9aa4b2; --line:#252b34;
          --killer:#ef6a6a; --opposing:#e0a24a; --neutral:#8a94a6; --supportive:#5bbf85; --none:#6b7482; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
.wrap { max-width:900px; margin:0 auto; padding:28px 20px 64px; }
h1 { font-size:24px; margin:0 0 4px; }
.sub { color:var(--muted); margin:0 0 20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:16px 18px; margin:0 0 14px; border-left:5px solid var(--none); }
.card.pol-killer { border-left-color:var(--killer); }
.card.pol-opposing { border-left-color:var(--opposing); }
.card.pol-neutral { border-left-color:var(--neutral); }
.card.pol-supportive { border-left-color:var(--supportive); }
.decision { border-left-width:5px; border-left-color:var(--neutral); }
.stitle { font-size:17px; font-weight:650; margin:0 0 2px; display:flex; align-items:center; gap:8px; }
.glyph { font-size:16px; }
.phrase { color:var(--muted); margin:2px 0 10px; font-style:italic; }
.kv { margin:3px 0; }
.kv b { color:var(--muted); font-weight:600; }
.badge { display:inline-block; padding:2px 10px; border-radius:999px; font-weight:650;
         font-size:13px; color:#fff; background:var(--none); }
.badge.go { background:var(--go); } .badge.hold { background:var(--hold); } .badge.kill { background:var(--kill); }
.deciding { font-size:12px; color:var(--muted); border:1px solid var(--line); border-radius:6px;
            padding:1px 6px; margin-left:6px; }
ul.chips { margin:6px 0; padding-left:20px; } ul.chips li { margin:2px 0; }
table { border-collapse:collapse; width:100%; margin:8px 0; font-size:14px; }
th,td { text-align:left; padding:5px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; }
figure { margin:10px 0; } figure img { max-width:100%; border:1px solid var(--line); border-radius:8px; }
figcaption { color:var(--muted); font-size:13px; margin-top:4px; }
.fig-badge { display:inline-block; font-size:11px; font-weight:700; letter-spacing:.03em;
             border-radius:999px; padding:1px 8px; margin-right:6px; color:#fff;
             background:var(--none); vertical-align:middle; }
.fig-badge.sig-supportive { background:var(--supportive); }
.fig-badge.sig-neutral { background:var(--neutral); }
.fig-badge.sig-opposing { background:var(--opposing); }
.fig-badge.sig-killer { background:var(--killer); }
.fig-badge.sig-insufficient, .fig-badge.sig-not_applicable { background:var(--none); }
.fig-badge.sig-context { background:transparent; color:var(--muted); border:1px solid var(--line); }
.unmeasured { color:var(--muted); font-size:13px; font-style:italic; }
.prov { color:var(--muted); font-size:13px; }
.about { color:var(--muted); font-size:13px; margin-top:22px; }
.section-label { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
.signal-strip { margin:4px 0; overflow-x:auto; }
.so-foot { color:var(--muted); font-size:13px; margin:8px 0 0; }
.risk-tiles { display:grid; grid-template-columns:repeat(6,1fr); gap:8px; margin:6px 0 2px; }
@media (max-width:760px) { .risk-tiles { grid-template-columns:repeat(3,1fr); } }
.risk-tile { border:1px solid var(--line); border-top-width:3px; border-radius:9px; padding:9px 8px;
             text-align:center; }
.risk-tile .rt-dim { font-size:11px; font-weight:650; color:var(--muted); line-height:1.25; }
.risk-tile .rt-bin { font-size:16px; font-weight:750; margin-top:3px; }
.risk-tile.rt-high { border-top-color:var(--killer); }
.risk-tile.rt-high .rt-bin { color:var(--killer); }
.risk-tile.rt-med { border-top-color:var(--opposing); }
.risk-tile.rt-med .rt-bin { color:var(--opposing); }
.risk-tile.rt-low { border-top-color:var(--supportive); }
.risk-tile.rt-low .rt-bin { color:var(--supportive); }
.risk-tile.rt-blind .rt-bin { color:var(--muted); font-size:13px; font-weight:600; }
.tag { display:inline-block; font-size:10px; text-transform:uppercase; letter-spacing:.06em;
       font-weight:700; color:var(--muted); border:1px solid var(--line); border-radius:6px;
       padding:1px 7px; margin-bottom:6px; }
td.mx-pos { background:rgba(46,139,87,.16); }
td.mx-neg { background:rgba(199,119,20,.16); }
td.mx-killer { background:rgba(192,41,41,.18); font-weight:650; }
td.mx-zero { background:rgba(138,148,166,.10); }
td.mx-off { color:var(--muted); }
.cite-prov { color:var(--muted); font-size:13px; margin:6px 0 2px; }
.cite-prov summary { cursor:pointer; }
.cite-prov code { font-size:12px; background:var(--bg); border:1px solid var(--line);
                  border-radius:4px; padding:0 5px; margin:2px 3px 0 0; display:inline-block; }
""".strip()


class HtmlBackend:
    def __init__(self):
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
        inner = "".join("".join(self._emit(b)) for b in sec.blocks)
        return f"<section class='{cls}'>{inner}</section>"

    # -- handlers ------------------------------------------------------------------------------
    def _report_header(self, p: dict) -> list:
        tgt, ind = _esc(p.get("target") or "—"), _esc(p.get("indication") or "—")
        out = [f"<h1>Target report — {tgt} × {ind}</h1>"]
        if p.get("thesis"):
            out.append(f"<p class='sub'>{_esc(_humanize(p['thesis']))}</p>")
        rec = p.get("recommendation")
        if rec:
            # map the actual recommendation vocabulary → semantic badge color (was only go/hold/kill,
            # so "nominate"/"advance"/"decline" fell through to the grey 'none' chip — bug).
            klass = {"nominate": "go", "advance": "go", "go": "go",
                     "hold": "hold", "conditional": "hold", "watch": "hold",
                     "kill": "kill", "decline": "kill", "no": "kill", "drop": "kill"}.get(
                str(rec).strip().lower().split()[0], "")
            out.append(f"<p class='kv'><b>Recommendation:</b> "
                       f"<span class='badge {klass}'>{_esc(rec)}</span></p>")
        ct = _confidence_summary(p.get("confidence"))
        if ct:
            out.append(f"<p class='kv'><b>Confidence:</b> {_esc(ct)}</p>")
        if p.get("deciding_title"):
            out.append(f"<p class='kv'><b>Deciding axis:</b> {_esc(p['deciding_title'])}</p>")
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
            return [f"<figure><img src='{_esc(ref)}' alt='{cap}'>"
                    f"<figcaption>{badge}{cap}</figcaption></figure>"]
        loc = f" <span class='prov'>[{_esc(ref)}]</span>" if ref else ""
        return [f"<p class='kv'>{badge}<b>Figure:</b> {cap}{loc}</p>"]

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
        foot = (f"<p class='so-foot'>{c.get('support', 0)} support · {c.get('neutral', 0)} neutral · "
                f"{c.get('against', 0)} against")
        desc = p.get("descriptive") or []
        if desc:
            foot += " · descriptive: " + _esc(", ".join(desc))
        foot += "</p>"
        return [f"<h2>Signals across skills</h2><div class='signal-strip'>{svg}</div>{foot}"]

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

    def _modality_matrix(self, p: dict) -> list:
        from ...ordinal_view import _cell_glyph
        cols, rows = p.get("columns") or [], p.get("rows") or []
        if not rows or not cols:
            return []
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
        legend = (f"<p class='so-foot'>{_esc(p['glyph_legend'])}</p>" if p.get("glyph_legend") else "")
        # collapse the long NOT-SPINE-SAFE caveat into a click-to-expand provenance disclosure.
        disc = (f"<details class='cite-prov'><summary>Reading this matrix — caveats</summary>"
                f"<p class='prov'>{_esc(p['disclaimer'])}</p></details>" if p.get("disclaimer") else "")
        return [f"<h2>Modality-fit matrix</h2><table><thead><tr><th>Gate</th>{head}<th>Verdict</th></tr>"
                f"</thead><tbody>{''.join(trs)}</tbody></table>{legend}{disc}"]

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
        name = _esc(", ".join(axes) if axes else (p.get("title") or p.get("short") or "—"))
        detail = _esc(p.get("routing") or (_humanize(p.get("basis")) if p.get("basis") else ""))
        return [f"<h2>Deciding axis</h2><p class='kv'><b>{name}</b>"
                + (f" — {detail}" if detail else "") + "</p>"]


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
        vline = _esc(str(sub)) + ("  · not evaluated" if lv is None else "") + dec
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
