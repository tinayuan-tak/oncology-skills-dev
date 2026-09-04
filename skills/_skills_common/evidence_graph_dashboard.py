"""evidence_graph_dashboard — render a self-contained HTML dashboard from the additive claim-graph
layer `decision.headline.evidence_graph` and NOTHING else.

`render_dashboard(graph)` consumes ONLY the graph's own id-keyed nodes/edges — no `.card.yaml`
reads, no free-text parsing, no positional guessing. Every card/rule/dataset/citation is resolved
by id via the graph's arrays; the heatmap is `cards[].signal`(color) × `confidence`(opacity); the
question table is `questions[]` joined to `literature.axes[].question_ids`; each card's provenance
chain is the pre-assembled `cards[].chain` (dataset → data → rule → verdict).

Presentation follows the framework dataviz conventions: the reserved status palette (supportive /
opposing / liability / neutral) is carried by a glyph + label as well as hue (never colour alone),
confidence is encoded as opacity, and the document is a single self-contained file with a validated
light palette + a dark variant. This module is DISPLAY-ONLY: it reads a projection, never a
decision.json field, and emits no decision state.

CLI (standalone, opt-in emission — not a dispatcher flag):
    python -m _skills_common.evidence_graph_dashboard <run_dir_or_decision.json> [--out dashboard.html]
Reads the run's decision.json, uses `headline.evidence_graph` if present, else builds one on the fly
(build_evidence_graph + the skill's questions.yaml), and writes a self-contained dashboard.html.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Optional

# ── display vocab (graph-native → presentation) ─────────────────────────────────────────────────
_GLYPH = {"supports": "△", "opposing": "▽", "opposes": "▽", "neutral": "•", "none": "·"}
_POL_COLOR = {"supports": "var(--supportive)", "opposing": "var(--opposing)",
              "opposes": "var(--opposing)", "neutral": "var(--neutral)", "none": "var(--neutral)"}
_CONF_OPACITY = {"high": 1.0, "moderate": 0.55, "low": 0.32}
_TIER_WIDTH = {"strong": 90, "moderate": 60, "weak": 30, "absent": 16, "uniform": 45,
               "high": 90, "low": 30}
# cosmetic layer label for the Cards section — an explicit lookup on the graph's own
# `measurement_type` node field (NOT string parsing / not a join); unknown types fall back to the
# raw measurement_type so other skills still group sensibly.
_LAYER = {
    "tumor_expression_distribution": "Bulk RNA", "cell_line_rna_expression": "Bulk RNA",
    "tumor_vs_adjacent_expression": "Bulk RNA · vs-normal", "tumor_elevation_breadth": "Bulk RNA · breadth",
    "tumor_protein_abundance": "Bulk protein", "cell_line_protein_abundance": "Bulk protein",
    "tumor_protein_ihc_presence": "Protein · IHC", "sc_tumor_celltype_expression": "Single-cell",
    "sc_normal_celltype_expression": "Single-cell · normal", "rna_protein_concordance": "RNA↔protein concordance",
    "normal_tissue_protein_breadth": "Normal tissue", "expression_purity_confound": "Confound",
}


def _esc(x) -> str:
    return html.escape("" if x is None else str(x))


def _is_liability(card: dict) -> bool:
    return "LIABILITY" in str((card.get("class") or {}).get("value") or "").upper()


def _card_color(card: dict) -> str:
    if _is_liability(card):
        return "var(--killer)"
    return _POL_COLOR.get((card.get("signal") or {}).get("polarity"), "var(--neutral)")


def _card_glyph(card: dict) -> str:
    if _is_liability(card):
        return "▽"
    return _GLYPH.get((card.get("signal") or {}).get("polarity"), "•")


def _opacity(conf: dict) -> float:
    return _CONF_OPACITY.get((conf or {}).get("level"), 0.4)


def _dots(conf: dict) -> str:
    n = (conf or {}).get("dots")
    n = n if isinstance(n, int) else 0
    return "●" * n + "○" * (3 - n) if 0 <= n <= 3 else "○○○"


def _lit_read_color(read: Optional[str]) -> str:
    return {"strongly_supports": "var(--supportive)", "supports": "var(--supportive)",
            "mixed": "var(--opposing)", "contradicts": "var(--killer)"}.get(read, "var(--neutral)")


def _lit_opacity(conf: Optional[str]) -> float:
    return {"high": 1.0, "moderate": 0.6, "low": 0.35}.get(conf, 0.4)


def _coherence(agreement: Optional[str]) -> tuple:
    """(glyph, color, title) for literature coherence vs the omics/deterministic call."""
    a = (agreement or "").lower()
    if a in ("agree", "extends"):
        return ("✓", "var(--supportive)", "literature coherent with omics")   # ✓
    if a == "contradicts":
        return ("✗", "var(--killer)", "literature contradicts omics")          # ✗
    if a in ("omics_blind", "omics_unavailable"):
        return ("≈", "var(--opposing)", "literature present, omics blind")     # ≈
    return ("·", "var(--neutral)", "no literature for this question")          # ·


def _axis_label(ax: dict, q_by_id: dict) -> str:
    """Human label for a literature axis = the question(s) it addresses (graph-native), not a letter."""
    labels = [q_by_id[q]["text"] for q in (ax.get("question_ids") or [])
              if q in q_by_id and q_by_id[q].get("text")]
    return " · ".join(labels) if labels else f"axis {ax.get('axis_id')}"


def _conf_label(conf: dict) -> str:
    """Explicit confidence: filled/empty dots + the level word (●●○ moderate)."""
    lvl = (conf or {}).get("level")
    return f"{_dots(conf)} {lvl}" if lvl else _dots(conf)


_CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--surface-2:#f3f3ef;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--hair:#e1e0d9;--border:rgba(11,11,11,.10);--supportive:#0ca30c;--opposing:#ec835a;--neutral:#8a8781;--killer:#d03b3b;--supportive-bg:#e7f5e7;--warn:#b26a00;--warn-bg:#fcf1db;--font:system-ui,-apple-system,"Segoe UI",sans-serif}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--surface-2:#232320;--ink:#fff;--ink2:#c3c2b7;--muted:#9b998f;--hair:#2c2c2a;--border:rgba(255,255,255,.10);--supportive:#31b531;--opposing:#ef9a76;--neutral:#9b988c;--killer:#e05b5b;--supportive-bg:#132a13;--warn:#e6a534;--warn-bg:#2a2113}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--surface-2:#232320;--ink:#fff;--ink2:#c3c2b7;--muted:#9b998f;--hair:#2c2c2a;--border:rgba(255,255,255,.10);--supportive:#31b531;--opposing:#ef9a76;--neutral:#9b988c;--killer:#e05b5b;--supportive-bg:#132a13;--warn:#e6a534;--warn-bg:#2a2113}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font-family:var(--font);font-size:13.5px;line-height:1.42}
.wrap{max-width:920px;margin:0 auto;padding:18px 16px 40px}
h1{margin:0;font-size:19px;font-weight:640}
code{font-family:ui-monospace,Menlo,monospace;font-size:.85em;background:var(--surface-2);padding:1px 4px;border-radius:4px;color:var(--ink2)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin:9px 0}
.muted{color:var(--muted)}
.kv{display:grid;grid-template-columns:92px 1fr;gap:2px 12px;margin-top:7px}
.kv dt{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.04em}.kv dd{margin:0}
.eyebrow{color:var(--muted);font-size:11.5px;letter-spacing:.08em;text-transform:uppercase}
.titlerow{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.vchip{display:inline-flex;align-items:center;gap:6px;font-weight:660;font-size:12.5px;padding:4px 11px;border-radius:999px;border:1px solid var(--border);color:var(--supportive);background:var(--supportive-bg)}
.hdr{border-left:4px solid var(--supportive);padding-left:14px}
.vline{font-size:15.5px;font-weight:600}
.g{font-weight:700}.g-sup{color:var(--supportive)}.g-opp{color:var(--opposing)}.g-neu{color:var(--neutral)}.g-kil{color:var(--killer)}
.dots{letter-spacing:1px;color:var(--ink2);font-size:11.5px}
.narr{border:1px dashed var(--border)}
.tag{display:inline-block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border:1px solid var(--border);border-radius:5px;padding:1px 6px}
.narr h2{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:8px 0 5px}
.narr p{margin:0 0 6px}.narr .meta{color:var(--muted);font-size:12px}
.summ h2{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:2px 0 5px}
.summ p{margin:0 0 6px}.summ .meta{color:var(--muted);font-size:11px;font-style:italic}
details.cite>summary{cursor:pointer;color:var(--ink2);font-size:12px;list-style:none;margin-top:6px}
details.cite>summary::-webkit-details-marker{display:none}
details.cite>summary::before{content:"\\25b8 ";color:var(--muted)}details.cite[open]>summary::before{content:"\\25be "}
.rulelist{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.seclabel{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin:16px 4px 3px;font-weight:640}
.hm{display:flex;flex-wrap:wrap;gap:10px 14px}
.hmg{display:flex;flex-direction:column;gap:4px}
.hmglab{font-size:10.5px;color:var(--muted);display:flex;align-items:center;gap:4px}
.hmcells{display:flex;gap:3px;align-items:center}
.hmcell{width:15px;height:15px;border-radius:4px;border:1px solid var(--border)}
.hmsep{width:1px;height:15px;background:var(--hair);margin:0 3px}
.litdot{width:16px;height:16px;border-radius:50%;border:1px solid var(--border);display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700}
.hmnote{color:var(--muted);font-size:11px;margin-top:8px}
.qtab{border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--surface)}
details.qr{border-top:1px solid var(--hair)}details.qr:first-child{border-top:none}
details.qr>summary{cursor:pointer;list-style:none;display:grid;grid-template-columns:14px 1fr 92px 104px;gap:10px;align-items:center;padding:8px 13px}
details.qr>summary::-webkit-details-marker{display:none}
.qcaret{color:var(--muted)}details.qr[open]>summary .qcaret::before{content:"\\25be"}details.qr:not([open])>summary .qcaret::before{content:"\\25b8"}
.qtitle{font-weight:550;font-size:13px}.qkey{color:var(--muted);font-size:11.5px;margin-top:1px}
.qstrip{display:flex;gap:3px;align-items:center;margin-top:4px;flex-wrap:wrap}
.qcell{width:11px;height:11px;border-radius:3px;border:1px solid var(--border)}
.qcount{color:var(--muted);font-size:10.5px;margin-left:4px}
.coh{font-weight:700;margin-right:3px}
.meterwrap{display:flex;align-items:center;gap:5px}
.meter{width:66px;height:7px;border-radius:4px;background:var(--surface-2);overflow:hidden;border:1px solid var(--border)}
.mfill{height:100%;display:block}
.qbody{padding:2px 13px 11px 38px;border-top:1px solid var(--hair);background:var(--surface-2)}
.qprimary{font-size:12px;color:var(--ink2);margin:7px 0}
.litaxis{border-left:3px solid var(--supportive);padding:2px 0 2px 9px;margin:7px 0;font-size:12px}
.litaxis.mixed{border-left-color:var(--opposing)}.litaxis.contra{border-left-color:var(--killer)}
.litmeta{color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em}
.vok{color:var(--supportive);font-size:10.5px}
.cardln{border:1px solid var(--border);border-radius:7px;background:var(--surface);margin:6px 0;padding:7px 10px}
.chead{font-size:11.5px;color:var(--muted);display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:3px}
.chead b{color:var(--ink2);font-weight:600}
.ccchip{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--ink2);background:var(--surface-2);border:1px solid var(--border);border-radius:999px;padding:0 7px;white-space:nowrap}
.cite-pill{display:inline-block;font-size:11px;color:var(--ink2);background:var(--surface-2);border:1px solid var(--border);border-radius:5px;padding:0 5px;margin:0 2px 2px 0}
.chainline{font-size:11.5px;line-height:1.7;color:var(--ink2)}
.chainline .lab{color:var(--muted);text-transform:uppercase;font-size:9px;letter-spacing:.04em;margin-right:2px}
.chainline .mono{font-family:ui-monospace,Menlo,monospace;font-size:10.5px}
.chainline .sep{color:var(--muted);margin:0 4px}
.pill-drv{background:var(--supportive-bg);color:var(--supportive);border:1px solid var(--border);border-radius:4px;padding:0 5px;font-size:9.5px;font-weight:700}
.pill-none{color:var(--muted);font-size:11px;font-style:italic}
details.sect2{margin:12px 0 0}
details.sect2>summary.sect2sum{cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center;gap:10px;padding:11px 14px;background:var(--surface);border:1px solid var(--border);border-radius:10px;font-weight:640;font-size:13px}
details.sect2>summary.sect2sum::-webkit-details-marker{display:none}
details.sect2[open]>summary.sect2sum{border-radius:10px 10px 0 0}
.sect2sum .car{color:var(--muted);margin-right:5px}
details.sect2:not([open]) .sect2sum .car::before{content:"\\25b8"}details.sect2[open] .sect2sum .car::before{content:"\\25be"}
.sect2body{border:1px solid var(--border);border-top:none;border-radius:0 0 10px 10px;padding:4px 10px 10px}
.pklayer{border:1px solid var(--border);border-radius:8px;margin:6px 0;background:var(--surface)}
.pklayer>summary{cursor:pointer;list-style:none;padding:8px 12px;font-size:12.5px;font-weight:560;display:flex;justify-content:space-between;align-items:center;gap:8px}
.pklayer>summary::-webkit-details-marker{display:none}
.pklayer>summary::before{content:"\\25b8 ";color:var(--muted)}.pklayer[open]>summary::before{content:"\\25be "}
.lbody{padding:0 12px 10px}.ccinline{color:var(--muted);font-size:11.5px}
footer{color:var(--muted);font-size:11.5px;margin-top:20px;border-top:1px solid var(--hair);padding-top:10px}
.legend{display:flex;flex-wrap:wrap;gap:14px;color:var(--ink2);font-size:11.5px;margin-top:6px}
.toggle{position:fixed;top:10px;right:12px;font-size:11.5px;color:var(--ink2);background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:4px 9px;cursor:pointer;z-index:10}
"""

_THEME_JS = ("(function(){var r=document.documentElement,n={auto:'light',light:'dark',dark:'auto'};"
             "r.dataset.theme=n[r.dataset.theme||'auto'];"
             "document.getElementById('tl').textContent=r.dataset.theme;})()")


def _cites_html(citation_ids, by_cit) -> str:
    out = []
    for cid in citation_ids or []:
        c = by_cit.get(cid)
        if not c:
            continue
        pmid = f" · PMID {_esc(c.get('pmid'))}" if c.get("pmid") else ""
        chk = " ✓" if c.get("verified") else ""
        out.append(f'<span class="cite-pill">{_esc(c.get("label"))}{pmid}{chk}</span>')
    return "".join(out)


def _header_html(g: dict) -> str:
    v = g.get("verdict") or {}
    pol = v.get("polarity") or "neutral"
    glyph = _GLYPH.get(pol, "•")
    conf = v.get("confidence") or {}
    cov = conf.get("coverage") or {}
    cov_txt = ""
    if isinstance(cov, dict) and cov:
        nm, na, nc = cov.get("n_measured"), cov.get("n_axes"), cov.get("n_critical_measured")
        if nm is not None and na is not None:
            cov_txt = f" · coverage {_esc(nm)}/{_esc(na)} axes"
            if nc is not None:
                cov_txt += f" · {_esc(nc)} critical"
    n_cards, n_q = len(g.get("cards") or []), len(g.get("questions") or [])
    tension = v.get("top_tension") or {}
    trow = ""
    if tension and tension.get("text"):
        sev = f" · sev {_esc(tension.get('severity'))}" if tension.get("severity") is not None else ""
        trow = (f'<dt>Tension</dt><dd style="color:var(--warn)">⚠ {_esc(tension.get("text"))}'
                f'{sev}</dd>')
    return (
        '<div class="card hdr"><div class="titlerow">'
        f'<div><div class="eyebrow">{_esc(g.get("skill"))}</div>'
        f'<h1>{_esc(g.get("target"))} · {_esc(g.get("indication"))}</h1></div>'
        f'<span class="vchip"><span class="g">{glyph}</span> {_esc(pol.upper())}</span></div>'
        '<dl class="kv">'
        f'<dt>Verdict</dt><dd><span class="vline">{_esc(v.get("call") or v.get("id"))}</span></dd>'
        f'<dt>Driving</dt><dd><code>{_esc(v.get("driving_rule_id"))}</code> · '
        f'<span class="dots">{_esc(conf.get("level") or "")}</span>{cov_txt} · {n_q} questions · {n_cards} cards</dd>'
        f'{trow}</dl></div>'
    )


def _narrative_html(g: dict) -> str:
    n = g.get("narrative") or {}
    if not n:
        return ""
    cites = n.get("cites") or {}
    rule_ids = cites.get("rule_ids") or []
    rl = "".join(f"<code>{_esc(r)}</code>" for r in rule_ids)
    rl_block = (f'<details class="cite"><summary>Grounded in {len(rule_ids)} rule(s)</summary>'
                f'<div class="rulelist">{rl}</div></details>') if rl else ""
    body = _esc(n.get("rationale") or "")
    caveat = f' <b>Caveat:</b> {_esc(n.get("key_caveat"))}' if n.get("key_caveat") else ""
    rel = _esc(n.get("relevance") or "")
    return (
        '<div class="card narr"><div style="display:flex;justify-content:space-between">'
        '<span class="tag">AI-generated</span>'
        '<span class="muted" style="font-size:11.5px">advisory · does not set the call</span></div>'
        '<h2>Narrative (AI gen)</h2>'
        f'<p>{body}{caveat}</p>'
        f'<div class="meta">relevance: <b>{rel}</b></div>{rl_block}</div>'
    )


def _summary_html(g: dict) -> str:
    """A DETERMINISTIC top-section narrative composed from the graph's verdict + question signals —
    always present (no LLM required), display-only. The AI narrative (when a --synthesize lane
    exists) renders below this as a separate 'Narrative (AI gen)' block."""
    v = g.get("verdict") or {}
    call = _esc(v.get("call") or v.get("id"))
    pol = v.get("polarity") or "neutral"
    conf = v.get("confidence") or {}
    cov = conf.get("coverage") or {}
    cov_txt = ""
    if isinstance(cov, dict) and cov.get("n_measured") is not None and cov.get("n_axes") is not None:
        cov_txt = f", coverage {_esc(cov.get('n_measured'))}/{_esc(cov.get('n_axes'))} axes"
        if cov.get("n_critical_measured") is not None:
            cov_txt += f" ({_esc(cov.get('n_critical_measured'))} critical)"
    qs = g.get("questions") or []
    sup = [q for q in qs if (q.get("signal") or {}).get("polarity") == "supports"]
    opp = [q for q in qs if (q.get("signal") or {}).get("polarity") in ("opposes", "opposing")]
    parts = [f'<b>{call}</b> — {_esc(pol)} call']
    if v.get("driving_rule_id"):
        parts.append(f' (driving rule <code>{_esc(v.get("driving_rule_id"))}</code>)')
    parts.append(f', {_esc(conf.get("level") or "unspecified")} confidence{cov_txt}, '
                 f'across {len(qs)} questions / {len(g.get("cards") or [])} cards.')
    if sup:
        parts.append(' <b>Supported by:</b> ' + _esc(", ".join(q.get("text") or q.get("id") for q in sup)))
    if opp:
        parts.append(' <b>Opposing:</b> ' + _esc(", ".join(q.get("text") or q.get("id") for q in opp)))
    t = v.get("top_tension") or {}
    if t and t.get("text"):
        sev = f" (severity {_esc(t.get('severity'))})" if t.get("severity") is not None else ""
        parts.append(f' <b>Key tension:</b> {_esc(t.get("text"))}{sev}.')
    return ('<div class="card summ"><h2>Summary</h2>'
            f'<p>{"".join(parts)}</p>'
            '<div class="meta">deterministic — composed from the verdict + question signals</div></div>')


def _fingerprint_html(g: dict) -> str:
    by_card = {c["id"]: c for c in g.get("cards") or []}
    lit_axis = {ax.get("axis_id"): ax for ax in (g.get("literature") or {}).get("axes") or []}
    groups = []
    for q in g.get("questions") or []:
        qglyph = _GLYPH.get((q.get("signal") or {}).get("polarity"), "•")
        cells = []
        for cid in q.get("card_ids") or []:
            c = by_card.get(cid)
            if not c:
                continue
            title = f'{cid} · {(c.get("signal") or {}).get("polarity")} · {(c.get("confidence") or {}).get("level")}'
            cells.append(f'<span class="hmcell" style="background:{_card_color(c)};opacity:{_opacity(c.get("confidence"))}" title="{_esc(title)}"></span>')
        # literature marker for this question (from its literature_axis_ids), else a faint "none" dot
        lit_ids = q.get("literature_axis_ids") or []
        if lit_ids:
            ax = lit_axis.get(lit_ids[0], {})
            cg, cc, ct = _coherence(ax.get("agreement_vs_omics"))
            lt = (f'<span class="litdot" style="color:{cc};background:transparent;'
                  f'opacity:{_lit_opacity(ax.get("confidence"))}" '
                  f'title="{_esc(ct)} · read {_esc(ax.get("read"))} · conf {_esc(ax.get("confidence"))}">{cg}</span>')
        else:
            lt = ('<span class="litdot" style="color:var(--neutral);background:transparent;opacity:.4" '
                  'title="no literature for this question">·</span>')
        groups.append(
            f'<div class="hmg"><div class="hmglab">{qglyph} {_esc(q.get("id"))}</div>'
            f'<div class="hmcells">{"".join(cells)}<span class="hmsep"></span>{lt}</div></div>'
        )
    return (
        '<div class="seclabel">Evidence fingerprint — omics signal × confidence + literature coherence</div>'
        f'<div class="card"><div class="hm">{"".join(groups)}</div>'
        '<div class="hmnote">▪ omics card — colour = signal (<b class="g-sup">green</b> supportive · '
        '<b class="g-opp">amber</b> opposing · <b class="g-kil">red</b> liability · grey neutral), '
        'opacity = confidence. &nbsp;·&nbsp; ○ literature coherence vs omics: '
        '<b style="color:var(--supportive)">✓</b> agrees · <b style="color:var(--killer)">✗</b> contradicts · '
        '<b style="color:var(--opposing)">≈</b> omics-blind · · none (opacity = lit confidence).</div></div>'
    )


def _question_table_html(g: dict) -> str:
    by_card = {c["id"]: c for c in g.get("cards") or []}
    by_cit = {c["id"]: c for c in g.get("citations") or []}
    lit_axis = {ax.get("axis_id"): ax for ax in (g.get("literature") or {}).get("axes") or []}
    rows = []
    for i, q in enumerate(g.get("questions") or []):
        sig, cf = q.get("signal") or {}, q.get("confidence") or {}
        pol = sig.get("polarity")
        color = _POL_COLOR.get(pol, "var(--neutral)")
        width = _TIER_WIDTH.get(sig.get("tier"), 50)
        glyph = _GLYPH.get(pol, "•")
        gcls = {"supports": "g-sup", "opposing": "g-opp", "opposes": "g-opp",
                "neutral": "g-neu", "none": "g-neu"}.get(pol, "g-neu")
        # key line: evidence_refs labels (graph-native), else the prose primary
        refs = q.get("evidence_refs") or []
        if refs:
            key = " · ".join(_esc(r.get("label")) for r in refs[:3])
        else:
            key = _esc((q.get("prose") or {}).get("primary") or "")
            key = key[:120] + ("…" if len(key) > 120 else "")
        # literature blocks
        lit_html = ""
        for aid in q.get("literature_axis_ids") or []:
            ax = lit_axis.get(aid, {})
            cls = {"mixed": " mixed", "contradicts": " contra"}.get(ax.get("read"), "")
            cg, cc, ct = _coherence(ax.get("agreement_vs_omics"))
            lit_html += (
                f'<div class="litaxis{cls}"><span class="litmeta">Literature</span> '
                f'<span class="coh" style="color:{cc}" title="{_esc(ct)}">{cg}</span>'
                f'<span class="vok">{_esc(ax.get("read"))} · {_esc(ax.get("agreement_vs_omics"))}</span><br>'
                f'{_esc(ax.get("assertion"))} {_cites_html(ax.get("citation_ids"), by_cit)}</div>'
            )
        # per-card chain lines
        card_html = ""
        for cid in q.get("card_ids") or []:
            c = by_card.get(cid)
            if not c:
                continue
            card_html += _card_chain_html(c)
        title = f'[{_esc(q.get("seq"))}] {_esc(q.get("id"))} · {_esc(q.get("text"))}'
        open_attr = " open" if i == 0 else ""
        # per-row card-signal strip (mirrors the fingerprint into the question header) + count
        strip_cells = "".join(
            f'<span class="qcell" style="background:{_card_color(by_card[cid])};'
            f'opacity:{_opacity((by_card[cid] or {}).get("confidence"))}" '
            f'title="{_esc(cid)} · {_esc((by_card[cid].get("signal") or {}).get("polarity"))}"></span>'
            for cid in (q.get("card_ids") or []) if cid in by_card
        )
        ncards = sum(1 for cid in (q.get("card_ids") or []) if cid in by_card)
        strip = (f'<div class="qstrip">{strip_cells}'
                 f'<span class="qcount">{ncards} card{"s" if ncards != 1 else ""}</span></div>')
        rows.append(
            f'<details class="qr"{open_attr}><summary><span class="qcaret"></span>'
            f'<div><div class="qtitle">{title}</div><div class="qkey">{key}</div>{strip}</div>'
            f'<div class="meterwrap"><span class="{gcls} g">{glyph}</span>'
            f'<span class="meter"><span class="mfill" style="width:{width}%;background:{color}"></span></span></div>'
            f'<div class="dots">{_conf_label(cf)}</div></summary>'
            f'<div class="qbody">{lit_html}{card_html}</div></details>'
        )
    return ('<div class="seclabel">Questions '
            '<span class="muted" style="text-transform:none;font-weight:400;letter-spacing:0">'
            '— per row: card-signal strip + confidence (●●● high · ●●○ moderate · ●○○ low); '
            'click to expand cards + data + literature</span></div>'
            f'<div class="qtab">{"".join(rows)}</div>')


def _card_chain_html(c: dict) -> str:
    ch = c.get("chain") or {}
    cls = c.get("class") or {}
    conf = c.get("confidence") or {}
    glyph = _card_glyph(c)
    gcls = "g-kil" if _is_liability(c) else {"supports": "g-sup", "opposing": "g-opp",
                                             "opposes": "g-opp"}.get((c.get("signal") or {}).get("polarity"), "g-neu")
    n = conf.get("n")
    n_txt = f' · n={_esc(n)}' if n not in (None, "") else ""
    chip = (f'<span class="ccchip"><span class="{gcls} g">{glyph}</span> '
            f'{_esc(cls.get("value"))}{n_txt}</span>')
    ds = ch.get("dataset_ids") or []
    ds_txt = " · ".join(_esc(d) for d in ds[:2]) + (f' +{len(ds) - 2}' if len(ds) > 2 else "")
    ds_txt = ds_txt or "—"
    data = " · ".join(f'{_esc(d.get("field"))}={_esc(d.get("value"))}' for d in (ch.get("data") or [])[:2]) or "—"
    if ch.get("rule_id"):
        rule = f'<span class="mono">{_esc(ch.get("rule_id"))}</span>'
        if ch.get("is_driving"):
            verdict = '<span class="sep">→</span><span class="pill-drv">DRIVING</span>'
        elif ch.get("contributes_to_verdict"):
            verdict = '<span class="sep">→</span>contributes'
        else:
            verdict = ""
    else:
        rule = '<span class="pill-none">display-only · no rule fired</span>'
        verdict = ""
    return (
        f'<div class="cardln"><div class="chead"><span>card · <b>{_esc(c.get("id"))}</b></span>{chip}</div>'
        f'<div class="chainline"><span class="lab">ds</span><span class="mono">{ds_txt}</span>'
        f'<span class="sep">→</span><span class="lab">data</span>{data}'
        f'<span class="sep">→</span><span class="lab">rule</span>{rule}{verdict}</div></div>'
    )


def _cards_and_lit_html(g: dict) -> str:
    cards = g.get("cards") or []
    # group by cosmetic layer label (explicit lookup on the graph's own measurement_type field)
    order, buckets = [], {}
    for c in cards:
        lab = _LAYER.get(c.get("measurement_type"), c.get("measurement_type") or "Other")
        if lab not in buckets:
            buckets[lab] = []
            order.append(lab)
        buckets[lab].append(c)
    layers = []
    for i, lab in enumerate(order):
        cs = buckets[lab]
        body = "".join(_card_chain_html(c) for c in cs)
        op = " open" if i == 0 else ""
        layers.append(f'<details class="pklayer"{op}><summary><span>{_esc(lab)}</span>'
                      f'<span class="ccinline">{len(cs)} card(s)</span></summary>'
                      f'<div class="lbody">{body}</div></details>')
    # literature layer
    lit = g.get("literature") or {}
    by_cit = {c["id"]: c for c in g.get("citations") or []}
    q_by_id = {q["id"]: q for q in g.get("questions") or []}
    lit_html = ""
    if lit.get("axes") or lit.get("blind_spots"):
        rows = ""
        for ax in lit.get("axes") or []:
            cg, cc, ct = _coherence(ax.get("agreement_vs_omics"))
            rows += (f'<div class="cardln"><div class="chead">'
                     f'<span><span class="coh" style="color:{cc}" title="{_esc(ct)}">{cg}</span>'
                     f'{_esc(_axis_label(ax, q_by_id))} — <b>{_esc(ax.get("read"))}</b></span>'
                     f'<span class="ccinline">{_esc(ax.get("agreement_vs_omics"))}</span></div>'
                     f'{_esc(ax.get("assertion"))} {_cites_html(ax.get("citation_ids"), by_cit)}</div>')
        for bs in lit.get("blind_spots") or []:
            rows += (f'<div class="cardln"><div class="chead"><span>blind spot</span></div>'
                     f'{_esc(bs.get("text"))} — <span class="muted">{_esc(bs.get("why_omics_blind"))}</span> '
                     f'{_cites_html(bs.get("citation_ids"), by_cit)}</div>')
        oc = _esc(lit.get("overall_consistency"))
        lit_html = (f'<details class="pklayer"><summary><span>Literature — all axes</span>'
                    f'<span class="ccinline">overall: {oc}</span></summary>'
                    f'<div class="lbody">{rows}</div></details>')
    n_cards = len(cards)
    n_vb = sum(1 for c in cards if c.get("role") == "verdict_bearing")
    inner = (f'<div class="seclabel">Cards &amp; literature — dataset → data → rule → verdict for all '
             f'{n_cards} ({n_vb} verdict-bearing)</div>'
             f'<div class="card" style="padding:8px 10px">{"".join(layers)}{lit_html}</div>')
    return inner


def render_dashboard(evidence_graph: dict) -> str:
    """Render a self-contained HTML dashboard from `evidence_graph` alone."""
    g = evidence_graph or {}
    top = _header_html(g) + _fingerprint_html(g) + _summary_html(g) + _narrative_html(g)
    detail = _question_table_html(g) + _cards_and_lit_html(g)
    v = g.get("verdict") or {}
    footer = (
        f'<footer>provenance · display-only view (never feeds the verdict) · {_esc(g.get("skill"))} · '
        f'{len(g.get("questions") or [])} questions · {len(g.get("cards") or [])} cards · '
        f'rendered from evidence_graph v{_esc(g.get("schema_version"))}'
        '<div class="legend"><span><b class="g-sup">△</b> supportive <b class="g-opp">▽</b> opposing '
        '<b class="g-kil">▽</b> liability <b class="g-neu">•</b> neutral</span>'
        '<span>confidence <b>●●●</b> high · <b>●●○</b> moderate · <b>●○○</b> low</span>'
        '<span>literature <b style="color:var(--supportive)">✓</b> agrees · '
        '<b style="color:var(--killer)">✗</b> contradicts · · none</span></div></footer>'
    )
    return (
        '<!doctype html><html lang="en" data-theme="auto"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_esc(g.get("skill"))} · {_esc(g.get("target"))} · {_esc(g.get("indication"))} — dashboard</title>'
        f'<style>{_CSS}</style></head><body>'
        f'<button class="toggle" onclick="{_THEME_JS}">theme: <span id="tl">auto</span></button>'
        '<div class="wrap">'
        f'{top}'
        '<details class="sect2"><summary class="sect2sum">'
        '<span><span class="car"></span>Detailed evidence — questions · cards · literature</span>'
        '<span class="muted" style="font-size:11px;font-weight:500">expand / collapse</span></summary>'
        f'<div class="sect2body">{detail}</div></details>'
        f'{footer}'
        '</div></body></html>'
    )


def _load_graph(path: Path) -> dict:
    """Resolve a run dir or a decision.json → the evidence_graph (built on the fly if not attached)."""
    dpath = path / "decision.json" if path.is_dir() else path
    decision = json.loads(dpath.read_text())
    graph = (decision.get("headline") or {}).get("evidence_graph")
    if graph:
        return graph
    # build on the fly: locate the skill's questions.yaml under skills/<skill>/
    from _skills_common.evidence_graph import build_evidence_graph, load_questions
    skills_root = Path(__file__).resolve().parent.parent
    skill_dir = skills_root / (decision.get("skill") or "")
    return build_evidence_graph(decision, questions=load_questions(skill_dir))


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    src = Path(args[0])
    out = None
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
    if out is None:
        out = (src / "dashboard.html") if src.is_dir() else src.with_name("dashboard.html")
    graph = _load_graph(src)
    out.write_text(render_dashboard(graph))
    print(f"wrote {out}")
    return 0


__all__ = ["render_dashboard", "main"]

if __name__ == "__main__":
    # allow `python -m _skills_common.evidence_graph_dashboard` and direct invocation
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    raise SystemExit(main(sys.argv))

