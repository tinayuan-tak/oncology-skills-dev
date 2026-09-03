"""Text + Markdown backend — one dumb {block-kind → handler} renderer, `markdown=` toggles syntax.

The backend makes NO selection decisions (the IR builder already tiered/scoped/limited every block);
it only knows how to turn each block kind into lines. `medium` is irrelevant here — a text target always
uses each block's text form, and a FIGURE block degrades to its caption + fallback text.
"""
from __future__ import annotations

from typing import Optional

from .. import vocab
from ..ir import Block, ReportIR, Section


class TextBackend:
    def __init__(self, markdown: bool = False):
        self.md = markdown
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
        lines: list = []
        lines += self._emit(ir.header)
        for sec in ir.sections:
            lines.append("")
            lines += self._emit_section(sec)
        if ir.about is not None:
            lines.append("")
            lines += self._emit(ir.about)
        # collapse trailing blanks, ensure single trailing newline
        text = "\n".join(lines).rstrip() + "\n"
        return text

    def _emit(self, block: Block) -> list:
        return self._handlers[block.kind](block.payload)

    def _emit_section(self, sec: Section) -> list:
        out = []
        for b in sec.blocks:
            out += self._emit(b)
        return out

    # -- syntax helpers ------------------------------------------------------------------------
    def _h1(self, s: str) -> list:
        return [f"# {s}"] if self.md else [s, "=" * len(s)]

    def _h2(self, s: str) -> list:
        return [f"## {s}"] if self.md else ["", s, "-" * len(s)]

    def _b(self, s: str) -> str:
        return f"**{s}**" if self.md else s.upper()

    def _bullet(self, s: str, indent: int = 0) -> str:
        return f"{'  ' * indent}- {s}"

    def _table(self, headers: list, rows: list) -> list:
        rows = [[("" if c is None else str(c)) for c in r] for r in rows]
        if self.md:
            out = ["| " + " | ".join(headers) + " |",
                   "|" + "---|" * len(headers)]
            out += ["| " + " | ".join(r) + " |" for r in rows]
            return out
        # plain text: fixed-width columns
        widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
                  for i in range(len(headers))]
        fmt = lambda cols: "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
        out = [fmt(headers), fmt(["-" * w for w in widths])]
        out += [fmt(r) for r in rows]
        return out

    # -- block handlers ------------------------------------------------------------------------
    def _report_header(self, p: dict) -> list:
        tgt = p.get("target") or "—"
        ind = p.get("indication") or "—"
        out = self._h1(f"Target report — {tgt} × {ind}")
        rec = p.get("recommendation")
        if rec:
            out.append("")
            out.append(f"{self._b('Recommendation')}: {rec}")
        conf = p.get("confidence")
        ct = _confidence_summary(conf)
        if ct:
            out.append(f"{self._b('Confidence')}: {ct}")
        if p.get("deciding_title"):
            out.append(f"{self._b('Deciding axis')}: {p['deciding_title']}")
        dissent = p.get("dissent") or []
        if dissent:
            out.append(f"{self._b('Dissent')}: {len(dissent)} unresolved-tension note(s)")
            for d in dissent:
                out.append(self._bullet(_dissent_summary(d), indent=1))
        return out

    def _skill_header(self, p: dict) -> list:
        glyph = vocab.polarity_glyph(p.get("polarity"))
        title = p.get("title") or p.get("short")
        call = p.get("call")
        # call=None (gateless) → lead with the honest phrase, never a blank verdict.
        verdict = call if call else vocab.polarity_label(p.get("polarity"))
        head = f"{glyph} {title} — {verdict}"
        if p.get("is_deciding"):
            head += "  [deciding axis]"
        out = self._h2(head)
        phrase = p.get("honest_phrase")
        if phrase:
            out.append(phrase if not self.md else f"_{phrase}_")
        return out

    def _confidence(self, p: dict) -> list:
        s = _confidence_summary(p.get("confidence"))
        return [f"{self._b('Confidence')}: {s}"] if s else []

    def _tension(self, p: dict) -> list:
        t = p.get("tension") or {}
        text = t.get("text")
        if not text:
            return []
        sev = t.get("severity")
        src = t.get("source")
        tail = " ".join(x for x in [f"({sev})" if sev else "", f"— {src}" if src else ""] if x)
        return [f"{self._b('Tension')}: {text} {tail}".rstrip()]

    def _claim_chips(self, p: dict) -> list:
        chips = p.get("chips") or []
        if not chips:
            return []
        out = [f"{self._b('Signals')} ({p.get('shown', len(chips))}/{p.get('total', len(chips))}):"]
        for c in chips:
            out.append(self._bullet(_chip_summary(c), indent=1))
        return out

    def _question_table(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        table = [[_qt_question(r), _qt_signal(r), _qt_conf(r)] for r in rows]
        return [f"{self._b('Questions')}:"] + self._table(["question", "signal", "confidence"], table)

    def _phase_metrics(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        table = [[r.get("metric") or r.get("label"), r.get("value"),
                  r.get("sample_context") or r.get("context")] for r in rows if isinstance(r, dict)]
        return [f"{self._b('Metrics')}:"] + self._table(["metric", "value", "context"], table)

    def _figure(self, p: dict) -> list:
        cap = p.get("caption") or "figure"
        ref = p.get("ref")
        if self.md and ref:
            return [f"![{cap}]({ref})"]
        # text-only fallback: name the figure + its caption (the figure→text degrade path)
        loc = f" [{ref}]" if ref else ""
        return [f"{self._b('Figure')}: {cap}{loc}"]

    def _provenance(self, p: dict) -> list:
        prov = p.get("provenance") or {}
        drv = prov.get("driving_rule_id") or "—"
        fired = prov.get("fired_rule_ids") or []
        used = prov.get("cards_used") or []
        missing = prov.get("cards_missing") or []
        out = [f"{self._b('Provenance')}: driving rule {drv}; {len(fired)} rule(s) fired; "
               f"{len(used)} card(s) used"]
        if missing:
            out.append(self._bullet(f"cards missing: {', '.join(map(str, missing))}", indent=1))
        return out

    def _unmeasured(self, p: dict) -> list:
        note = p.get("note") or f"{p.get('slot', 'slot')}: not measured"
        return [f"{self._b('Unmeasured')}: {note}"]

    def _about(self, p: dict) -> list:
        out = self._h2("About this report")
        if p.get("note"):
            out.append(p["note"])
        leg = (p.get("polarity_legend") or {}).get("on_scale") or {}
        if leg:
            scale = ", ".join(f"{k}={v:+d}" for k, v in sorted(leg.items(), key=lambda t: -t[1]))
            out.append(f"Ordinal polarity scale (order-preserving, not metric): {scale}.")
        spec = p.get("spec") or {}
        if spec:
            out.append(f"Spec: level={spec.get('level')} · medium={spec.get('medium')} · "
                       f"scope={spec.get('scope')} · lead={spec.get('lead')}.")
        return out


# ------------------------------------------------------------------------------------------------
# small pure summarizers (shared shape-tolerant readers over spine slots)
# ------------------------------------------------------------------------------------------------
def _confidence_summary(conf) -> Optional[str]:
    if not isinstance(conf, dict):
        return str(conf) if conf else None
    level = conf.get("level") or conf.get("tier")
    basis = conf.get("basis")
    cov = conf.get("coverage")
    parts = [p for p in [level, f"basis: {basis}" if basis else None,
                         f"coverage: {cov}" if cov else None] if p]
    return " · ".join(map(str, parts)) if parts else None


def _dissent_summary(d) -> str:
    if not isinstance(d, dict):
        return str(d)
    src = d.get("source") or "source"
    detail = d.get("detail") or d.get("text") or ""
    resolved = d.get("resolved_to")
    tail = f" → {resolved}" if resolved else ""
    return f"{src}: {detail}{tail}".strip()


def _chip_summary(c) -> str:
    if not isinstance(c, dict):
        return str(c)
    label = c.get("label") or c.get("key") or "signal"
    signal = c.get("signal")
    corr = c.get("corroboration")
    ev = c.get("evidence")
    bits = [f"{label}: {signal}" if signal else str(label)]
    if corr:
        bits.append(f"[{corr}]")
    if ev:
        bits.append(f"— {ev}")
    return " ".join(map(str, bits))


def _qt_question(r) -> str:
    if not isinstance(r, dict):
        return str(r)
    return str(r.get("question") or r.get("q") or r.get("label") or r.get("key") or "")


def _qt_signal(r) -> str:
    if not isinstance(r, dict):
        return ""
    return str(r.get("signal") or r.get("call") or r.get("answer") or r.get("value") or "")


def _qt_conf(r) -> str:
    if not isinstance(r, dict):
        return ""
    return str(r.get("confidence") or r.get("conf") or "")


__all__ = ["TextBackend"]
