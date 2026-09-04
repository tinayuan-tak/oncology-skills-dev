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
        lines: list = []
        lines += self._emit(ir.header)
        for b in ir.overview:
            lines.append("")
            lines += self._emit(b)
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
        if p.get("thesis"):
            out.append(f"{self._b('Thesis')}: {_humanize(p['thesis'])}")
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
        # call=None (gateless descriptive/inert) → label it plainly as context, never "not scored".
        verdict = call or ("context (descriptive)" if p.get("role") in ("descriptive", "inert")
                           else vocab.polarity_label(p.get("polarity")))
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
        st = p.get("status") if isinstance(p.get("status"), dict) else None
        badge = f"{st.get('icon')} {st.get('label')} — " if (st and st.get("label")) else ""
        if self.md and ref:
            # keep the verdict in the caption so the figure↔verdict binding survives the markdown embed.
            return [f"![{badge}{cap}]({ref})"]
        # text-only fallback: badge + name the figure + its caption (the figure→text degrade path)
        loc = f" [{ref}]" if ref else ""
        return [f"{self._b('Figure')}: {badge}{cap}{loc}"]

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


    def _signals_overview(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        c = p.get("counts") or {}
        out = self._h2("Signals across skills")
        out.append(f"{c.get('support', 0)} support · {c.get('neutral', 0)} neutral · "
                   f"{c.get('against', 0)} against")
        for r in rows:
            g = vocab.polarity_glyph(r.get("polarity"))
            sub = r.get("honest_phrase") or _humanize(r.get("call")) or vocab.polarity_label(r.get("polarity"))
            tail = "  [deciding]" if r.get("is_deciding") else ""
            out.append(self._bullet(f"{g} {r.get('title')} — {sub}{tail}"))
        desc = p.get("descriptive") or []
        if desc:
            out.append(f"descriptive (context): {', '.join(desc)}")
        return out

    def _risk_6dim(self, p: dict) -> list:
        dims = p.get("dims") or []
        if not dims:
            return []
        rows = [[d.get("dim"), (d.get("bin") or "not evidenced")] for d in dims]
        return self._h2("Risk by dimension") + self._table(["dimension", "risk"], rows)

    def _synthesis(self, p: dict) -> list:
        out = self._h2("Synthesis (AI-generated)")
        if p.get("executive_summary"):
            out.append(str(p["executive_summary"]))
        if p.get("tension_analysis"):
            out.append(f"{self._b('Tensions')}: {p['tension_analysis']}")
        for a in (p.get("arguments") or []):
            out.append(self._bullet(_arg_summary(a)))
        return out

    def _coherence(self, p: dict) -> list:
        # thesis is in the header; this block adds the coherence class + any caveats.
        bits = []
        if p.get("coherence"):
            bits.append(f"{self._b('Coherence')}: {_humanize(p['coherence'])}")
        for c in (p.get("caveats") or []):
            bits.append(self._bullet(str(c)))
        return bits

    def _modality_matrix(self, p: dict) -> list:
        from ...ordinal_view import _cell_glyph  # single-source glyphs (backends → report_render → _skills_common)
        cols, rows = p.get("columns") or [], p.get("rows") or []
        if not rows or not cols:
            return []
        body = []
        for r in rows:
            cells = r.get("cells") or {}
            glyphs = [_cell_glyph(cells.get(m) or {}) for m in cols]
            body.append([vocab.skill_title(r.get("short"))] + glyphs
                        + [_humanize(r.get("verdict")) if r.get("verdict") else "—"])
        return self._h2("Modality-fit matrix") + self._table(["gate"] + list(cols) + ["verdict"], body)

    def _literature_risk(self, p: dict) -> list:
        dims = p.get("dims") or []
        if not dims:
            return []
        rows = [[d.get("dim"), d.get("risk_level") or "—", (d.get("interpretation") or "")[:80]]
                for d in dims]
        return self._h2("Literature risk (context)") + self._table(["dimension", "risk", "note"], rows)

    def _deciding_axis(self, p: dict) -> list:
        axes = p.get("axes") or []
        name = ", ".join(axes) if axes else (p.get("title") or p.get("short") or "—")
        line = f"{self._b('Deciding axis')}: {name}"
        if p.get("routing"):
            line += f" — {p['routing']}"
        elif p.get("basis"):
            line += f" ({_humanize(p['basis'])})"
        return [line]


# ------------------------------------------------------------------------------------------------
# small pure summarizers (shared shape-tolerant readers over spine slots)
# ------------------------------------------------------------------------------------------------
def _confidence_summary(conf) -> Optional[str]:
    if not isinstance(conf, dict):
        return str(conf) if conf else None
    level = conf.get("level") or conf.get("tier")
    basis = conf.get("basis")
    cov = conf.get("coverage")
    if isinstance(cov, dict):  # {n_measured, n_axes, n_critical_measured} — format, never str(dict)
        nm, na, nc = cov.get("n_measured"), cov.get("n_axes"), cov.get("n_critical_measured")
        cov = (f"{nm}/{na} axes" + (f" ({nc} critical)" if nc is not None else "")) if na is not None else None
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


def _qt_cell(v) -> str:
    """Display text for a question-table signal/confidence cell. `question_table_core.row()` puts a DICT
    there — signal `{tier, fill, polarity, label}`, confidence `{tier, dots, label}` — so surface its
    human `label` (else the `tier`), not the raw dict repr. A plain string cell (older shapes) passes
    through; None → empty."""
    if isinstance(v, dict):
        return str(v.get("label") or v.get("tier") or "")
    return "" if v is None else str(v)


def _qt_signal(r) -> str:
    if not isinstance(r, dict):
        return ""
    return _qt_cell(r.get("signal") or r.get("call") or r.get("answer") or r.get("value"))


def _qt_conf(r) -> str:
    if not isinstance(r, dict):
        return ""
    return _qt_cell(r.get("confidence") or r.get("conf"))


def _humanize(x) -> str:
    return str(x).replace("_", " ") if x is not None else ""


def _arg_summary(a) -> str:
    if not isinstance(a, dict):
        return str(a)
    return str(a.get("claim") or a.get("text") or a.get("argument") or a)


__all__ = ["TextBackend"]
