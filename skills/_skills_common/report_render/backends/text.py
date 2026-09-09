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
        lines: list = []
        lines += self._emit(ir.header)
        if getattr(ir, "banner", None) is not None:  # persistent advisory banner (chrome, above tabs)
            lines.append("")
            lines += self._emit(ir.banner)
        lenses = ir.lenses()
        if lenses:
            # faceted composed report: the interactive tabs linearize into sequential lens sections,
            # in the canonical LENS_ORDER (Decision → Signals → Modality → Risk → Biology).
            for _lens_id, title, items in lenses:
                lines.append("")
                lines += self._h1(title)
                for kind, item in items:
                    lines.append("")
                    lines += self._emit_section(item) if kind == "section" else self._emit(item)
        else:
            # flat fallback (standalone single-skill / un-lensed IR) — byte-identical to the prior layout.
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
            out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
            out += ["| " + " | ".join(r) + " |" for r in rows]
            return out
        # plain text: fixed-width columns
        widths = [
            max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i]) for i in range(len(headers))
        ]
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
        # the call is a snake_case machine verdict (lineage_selective) — humanize it for the header.
        call = _humanize(p.get("call")) or None
        # call=None (gateless descriptive/inert) → label it plainly as context, never "not scored".
        verdict = call or (
            "context (descriptive)"
            if p.get("role") in ("descriptive", "inert")
            else vocab.polarity_label(p.get("polarity"))
        )
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
        # the source is an internal facet id (e.g. "key_signals.caveat", "normal_liability_flag") —
        # humanize it (drop the dotted namespace, de-snake) rather than leak the raw token.
        src = t.get("source")
        src = str(src).replace("_", " ").replace(".", " ") if src else None
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
        table = [
            [r.get("metric") or r.get("label"), r.get("value"), r.get("sample_context") or r.get("context")]
            for r in rows
            if isinstance(r, dict)
        ]
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
        out = [f"{self._b('Provenance')}: driving rule {drv}; {len(fired)} rule(s) fired; {len(used)} card(s) used"]
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
            out.append(
                f"Spec: level={spec.get('level')} · medium={spec.get('medium')} · "
                f"scope={spec.get('scope')} · lead={spec.get('lead')}."
            )
        return out

    def _signals_overview(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        c = p.get("counts") or {}
        out = self._h2("Signals across skills")
        out.append(f"{c.get('support', 0)} support · {c.get('neutral', 0)} neutral · {c.get('against', 0)} against")
        for r in rows:
            g = vocab.polarity_glyph(r.get("polarity"))
            sub = r.get("honest_phrase") or _humanize(r.get("call")) or vocab.polarity_label(r.get("polarity"))
            tail = "  [deciding]" if r.get("is_deciding") else ""
            # a thesis-expected negative (e.g. dependency under a surface-antigen thesis) is shown as a
            # neutral bar with its raw polarity + the reason, so it reads as reframed, not silently dropped.
            note = r.get("expected_note")
            if note:
                tail += f" _({note})_"
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
        _GLYPH = {"supportive": "△", "opposing": "▽", "killer": "▲", "neutral": "◆", "not_applicable": "·"}
        bullets = p.get("exec_bullets") or []
        for b in bullets:
            g = _GLYPH.get(b.get("polarity"), "•")
            out.append(self._bullet(f"{g} {b.get('text')}"))
        if bullets and (p.get("executive_summary") or p.get("tension_analysis") or p.get("arguments")):
            out.append(self._b("Full narrative") + ":" if not self.md else f"_{self._b('Full narrative')}_:")
        if p.get("executive_summary"):
            out.append(str(p["executive_summary"]))
        if p.get("tension_analysis"):
            out.append(f"{self._b('Tensions')}: {p['tension_analysis']}")
        for a in p.get("arguments") or []:
            out.append(self._bullet(_arg_summary(a)))
        cites = p.get("citations") or []
        if cites:
            # rule-ids lifted out of the prose → a compact grounding footnote (provenance affordance).
            joined = ", ".join(cites)
            out.append(
                f"_Grounded in {len(cites)} framework rules: {joined}._"
                if self.md
                else f"Grounded in {len(cites)} framework rules: {joined}"
            )
        return out

    def _coherence(self, p: dict) -> list:
        # thesis is in the header; this block adds the coherence class + any caveats.
        bits = []
        if p.get("coherence"):
            bits.append(f"{self._b('Coherence')}: {_humanize(p['coherence'])}")
        for c in p.get("caveats") or []:
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
            body.append(
                [vocab.skill_title(r.get("short"))]
                + glyphs
                + [_humanize(r.get("verdict")) if r.get("verdict") else "—"]
            )
        out = self._h2("Modality-fit matrix") + self._table(["gate"] + list(cols) + ["verdict"], body)
        if p.get("glyph_legend"):
            out.append(p["glyph_legend"])  # inline glyph key
        if p.get("disclaimer"):
            out.append(_collapse_disclaimer(p["disclaimer"]))  # first sentence only; rest → provenance
        return out

    def _literature_risk(self, p: dict) -> list:
        dims = p.get("dims") or []
        if not dims:
            return []
        rows = [
            [d.get("dim"), d.get("omics_bin") or "—", d.get("risk_level") or "not_assessed", d.get("coherence") or "—"]
            for d in dims
        ]
        return self._h2("Literature × omics coherence (context)") + self._table(
            ["dimension", "omics", "literature", "coherence"], rows
        )

    def _deciding_axis(self, p: dict) -> list:
        axes = p.get("axes") or []
        name = ", ".join(axes) if axes else (p.get("title") or p.get("short"))
        routing = p.get("routing") or (f"({_humanize(p['basis'])})" if p.get("basis") else "")
        if name:
            line = f"{self._b('Deciding axis')}: {name}"
            if routing:
                line += f" — {routing}"
        else:
            # no NAMED axis (e.g. gate-forced hold, or "cannot decide") — lead with the routing text,
            # never render an empty "— —" placeholder pair.
            line = f"{self._b('Deciding axis')}: {routing or '—'}"
        return [line]

    def _flip_conditions(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        out = self._h2("What would change the call")
        for r in rows:
            tv = _humanize(r.get("to_verdict")) or "a different call"
            if r.get("present"):
                # a live, load-bearing signal — name it (it's distinct + informative).
                cond = _humanize(r.get("condition")) or "a load-bearing signal"
                line = f"{r['axis']}: the call rests on {cond} — absent it → {tv}"
            else:
                # a latent counterfactual — the rule id ≈ the verdict it produces, so lead with the outcome.
                line = f"{r['axis']}: would become {tv}"
            if r.get("direction"):
                line += f" ({r['direction']})"
            out.append(self._bullet(line))
        return out

    def _subtype(self, p: dict) -> list:
        if not p.get("verdict") and not p.get("subtypes"):
            return []
        out = self._h2("Subtype stratification")
        axes = ", ".join(p.get("axes_available") or []) or "—"
        out.append(
            f"{self._b('Verdict')}: {_humanize(p.get('verdict'))} "
            f"({p.get('n_evaluated', 0)} subtypes evaluated on {axes})"
        )
        for label, key in (
            ("Convergent subtypes", "convergent_subtypes"),
            ("Associated subtypes", "associated_subtypes"),
            ("Evaluated", "subtypes"),
        ):
            vals = p.get(key) or []
            if vals:
                out.append(f"{self._b(label)}: {', '.join(map(str, vals))}")
        return out

    def _biomarker(self, p: dict) -> list:
        if not p.get("verdict"):
            return []
        out = self._h2("Patient-selection biomarker")
        head = f"{self._b('Verdict')}: {_humanize(p['verdict'])}"
        if p.get("preferred_assay"):
            head += f" · preferred assay: {_humanize(p['preferred_assay'])}"
        out.append(head)
        strat = []
        for lab, key in (
            ("driver role", "alteration_role"),
            ("mutation stratification", "mutation_stratification"),
            ("subtype stratification", "subtype_stratification"),
            ("survival", "survival_association"),
        ):
            if p.get(key):
                strat.append(f"{lab}: {_humanize(p[key])}")
        if strat:
            out.append("; ".join(strat))
        uses = p.get("intended_uses") or []
        if uses:
            out.append(f"{self._b('Intended uses')}: {', '.join(_humanize(u) for u in uses)}")
        for h in p.get("hypotheses") or []:
            iu, basis, es = _humanize(h.get("intended_use")), _humanize(h.get("basis")), h.get("evidence_strength")
            out.append(self._bullet(f"{iu}: {basis}" + (f" [{es}]" if es else "")))
        return out

    # -- faceted-rollup blocks (PR2) -----------------------------------------------------------
    def _synthesis_banner(self, p: dict) -> list:
        out = [f"{self._b('AI synthesis')} (advisory — does not set the call)"]
        if p.get("executive_summary"):
            out.append(str(p["executive_summary"]))
        mm = p.get("mismatch")
        if isinstance(mm, dict) and mm.get("deterministic"):
            out.append(
                f"⚠ LLM read: {mm.get('llm')} · deterministic call: {mm['deterministic']} "
                f"— mismatch flagged (the deterministic call stands)."
            )
        cites = p.get("citations") or []
        if cites:
            joined = ", ".join(cites)
            out.append(
                f"_Grounded in {len(cites)} framework rules: {joined}._"
                if self.md
                else f"Grounded in {len(cites)} framework rules: {joined}"
            )
        return out

    def _synthesis_note(self, p: dict) -> list:
        notes = p.get("notes") or []
        if not notes:
            return []
        out = [f"{self._b('AI read')} (advisory):"]
        for n in notes:
            stance = (n.get("stance") or "").strip()
            tag = {"for": "+ ", "against": "− ", "tension": "⚖ "}.get(stance, "")
            out.append(self._bullet(f"{tag}{n.get('text', '')}", indent=1))
        return out

    def _signals_scatter(self, p: dict) -> list:
        pts = p.get("points") or []
        if not pts:
            return []
        is_sg = p.get("scope") == "subgroups"
        head = "sub-group" if is_sg else "skill"
        rows = [
            [(pt.get("name") if is_sg else pt.get("title")), pt.get("signal_tier"), _humanize(pt.get("confidence"))]
            for pt in pts
        ]
        title = "Signals × confidence" + (" (sub-groups)" if is_sg else "")
        return self._h2(title) + self._table([head, "signal", "confidence"], rows)

    def _subgroup_bands(self, p: dict) -> list:
        rows = p.get("sub_groups") or []
        if not rows:
            return []
        table = [
            [
                r.get("name"),
                r.get("signal"),
                _humanize(r.get("confidence")),
                f"{r.get('n_agree', 0)}/{r.get('n_sources', 0)}" + (" ⚠" if r.get("conflict") else ""),
            ]
            for r in rows
        ]
        return self._h2("Sub-group bands") + self._table(["sub-group", "signal", "confidence", "sources"], table)

    def _cross_cutting(self, p: dict) -> list:
        rows = p.get("rows") or []
        if not rows:
            return []
        table = [[r.get("question"), r.get("owner"), _humanize(r.get("informs"))] for r in rows]
        return self._h2("Cross-cutting questions") + self._table(["question", "measured by", "informs"], table)

    def _composed_fingerprint(self, p: dict) -> list:
        """Composed at-a-glance grid (from the target_report.evidence_graph index) linearized to a
        lens × subskill verdict table + the verdict line + dissent bullets."""
        lanes = p.get("lanes") or []
        if not lanes:
            return []
        out = self._h2("At a glance")
        v = p.get("verdict") or {}
        vbits = []
        if v.get("recommendation"):
            vbits.append(f"{self._b('Call')}: {_humanize(v['recommendation'])}")
        if v.get("confidence"):
            vbits.append(f"confidence {_humanize(v['confidence'])}")
        deciding = v.get("deciding_shorts") or []
        if deciding:
            vbits.append("deciding: " + ", ".join(vocab.skill_title(s) for s in deciding))
        if vbits:
            out.append(" · ".join(vbits))
        rows = []
        for lane in lanes:
            for s in lane.get("skills") or []:
                g = vocab.polarity_glyph(s.get("polarity"))
                call = _humanize(s.get("call")) or vocab.polarity_label(s.get("polarity")) or ""
                rows.append(
                    [
                        lane.get("title"),
                        f"{g} {s.get('title')}",
                        call,
                        _humanize(s.get("confidence")) or "—",
                        "deciding" if s.get("deciding") else "",
                        _humanize(s.get("literature_consistency")) or "—",
                    ]
                )
        out += self._table(["lens", "subskill", "verdict", "confidence", "role", "literature"], rows)
        dissent = p.get("dissent") or []
        if dissent:
            out.append(f"{self._b('Dissent')}:")
            for d in dissent:
                src = vocab.skill_title(d["source"]) if d.get("source") else "a signal"
                note = d.get("note") or "dissents from the call"
                rt = f" → resolved to {_humanize(d.get('resolved_to'))}" if d.get("resolved_to") else ""
                out.append(self._bullet(f"{src}: {note}{rt}", indent=1))
        return out

    # -- evidence-graph blocks (P3): degraded tables of the RICH embedded view -------------------
    def _evidence_fingerprint(self, p: dict) -> list:
        qs = p.get("questions") or []
        if not qs:
            return []
        rows = []
        for q in qs:
            lit = q.get("lit") or {}
            rows.append(
                [
                    q.get("text") or q.get("id"),
                    f"{q.get('polarity') or '—'}/{q.get('tier') or '—'}",
                    "●" * (q.get("dots") or 0) or "—",
                    str(len(q.get("cells") or [])),
                    _humanize(lit.get("agreement")) if lit else "—",
                ]
            )
        return self._h2("Evidence fingerprint") + self._table(
            ["question", "signal", "conf", "cards", "literature"], rows
        )

    def _card_chain(self, p: dict) -> list:
        layers = p.get("layers") or []
        if not layers:
            return []
        rows = []
        for lyr in layers:
            for c in lyr.get("cards") or []:
                rule = ("→ " + c.get("rule_id")) if c.get("rule_id") else "display-only"
                # class-led plain reading: humanized class ("Reads:") + the reference-frame gauge (words)
                # when the card carries a ruler, else the glossed key-evidence one-liner.
                gauges = " · ".join(c.get("gauges") or [])  # all reference-frame rulers (multi-frame)
                rows.append(
                    [
                        lyr.get("layer"),
                        c.get("id"),
                        c.get("reads") or c.get("class_value"),
                        rule,
                        gauges or c.get("gauge") or c.get("key_evidence_summary") or "",
                    ]
                )
        return self._h2("Cards — dataset → data → rule → verdict") + self._table(
            ["layer", "card", "class", "rule", "key evidence"], rows
        )

    def _literature_axes(self, p: dict) -> list:
        axes = p.get("axes") or []
        blind = p.get("blind_spots") or []
        if not axes and not blind:
            return []
        rows = [
            [a.get("axis_id"), a.get("read"), _humanize(a.get("agreement")), ", ".join(a.get("question_ids") or [])]
            for a in axes
        ]
        out = self._h2("Literature — per-axis agreement") + self._table(
            ["axis", "read", "agreement", "questions"], rows
        )
        for b in blind:
            out.append(f"  blind spot: {b.get('text') or ''}")
        oc = p.get("overall_consistency")
        if oc:
            out.append(f"  overall consistency: {oc}")
        return out


# ------------------------------------------------------------------------------------------------
# small pure summarizers (shared shape-tolerant readers over spine slots)
# ------------------------------------------------------------------------------------------------
# internal confidence-basis tokens → plain language (the basis is an engine identifier, not prose).
_BASIS_GLOSS = {
    "certainty_model_sidecar": "cross-axis certainty model",
    "gate_scorecard": "gate scorecard",
    "coverage_only": "measurement coverage",
    "single_axis": "a single axis",
}


def _gloss_basis(basis) -> Optional[str]:
    if not basis:
        return None
    return _BASIS_GLOSS.get(basis, _humanize(basis))


def _confidence_summary(conf) -> Optional[str]:
    if not isinstance(conf, dict):
        return str(conf) if conf else None
    level = conf.get("level") or conf.get("tier")
    basis = _gloss_basis(conf.get("basis"))
    cov = conf.get("coverage")
    if isinstance(cov, dict):  # {n_measured, n_axes, n_critical_measured} — format, never str(dict)
        nm, na, nc = cov.get("n_measured"), cov.get("n_axes"), cov.get("n_critical_measured")
        cov = (f"{nm}/{na} axes" + (f" ({nc} critical)" if nc is not None else "")) if na is not None else None
    parts = [p for p in [level, f"basis: {basis}" if basis else None, f"coverage: {cov}" if cov else None] if p]
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


def _collapse_disclaimer(text) -> str:
    """The ordinal-matrix disclaimer is a long multi-sentence caveat. Collapse it to its lead sentence
    (the ORDINAL-VIEW warning) for the inline view; the full caveat lives in the block payload for a
    consumer that wants it (html shows it in a <details>)."""
    s = str(text or "").strip()
    if not s:
        return ""
    lead = s.split(". ", 1)[0].rstrip(".")
    return f"{lead}. (Full caveat in provenance.)"


def _arg_summary(a) -> str:
    if not isinstance(a, dict):
        return str(a)
    return str(a.get("claim") or a.get("text") or a.get("argument") or a)


__all__ = ["TextBackend"]
