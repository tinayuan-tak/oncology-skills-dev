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
.unmeasured { color:var(--muted); font-size:13px; font-style:italic; }
.prov { color:var(--muted); font-size:13px; }
.about { color:var(--muted); font-size:13px; margin-top:22px; }
.section-label { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
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
        rec = p.get("recommendation")
        if rec:
            klass = {"go": "go", "hold": "hold", "kill": "kill", "no": "kill"}.get(
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
        call = p.get("call")
        verdict = call if call else vocab.polarity_label(p.get("polarity"))
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
        if p.get("show_image") and ref:
            return [f"<figure><img src='{_esc(ref)}' alt='{cap}'><figcaption>{cap}</figcaption></figure>"]
        loc = f" <span class='prov'>[{_esc(ref)}]</span>" if ref else ""
        return [f"<p class='kv'><b>Figure:</b> {cap}{loc}</p>"]

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


# reuse the text backend's shape-tolerant summarizers (single source, no vocab drift).
from .text import (_chip_summary, _confidence_summary, _dissent_summary,  # noqa: E402
                   _qt_conf, _qt_question, _qt_signal)

__all__ = ["HtmlBackend"]
