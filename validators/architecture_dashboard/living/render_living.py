"""render_living.py — the living document, a SUPERSET of the unified dashboard.

Reuses every renderer, helper, palette, and the Miller/JS from render_unified + render_arch
(import-only; those files are untouched) and adds three panes — Gaps, Concepts, Docs — plus
the baked-in legibility layer (`_tok`): every machine token is shown as a human label with the
raw id secondary (a "show raw ids" toggle reveals them) and its plain-English gloss as a tooltip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# make the sibling dashboard modules importable (they import each other by bare name)
_ARCH = Path(__file__).resolve().parent.parent
if str(_ARCH) not in sys.path:
    sys.path.insert(0, str(_ARCH))

import render_arch  # noqa: E402
import render_unified as U  # noqa: E402
from render_unified import (  # noqa: E402
    GREEN, AMBER, RED, GREY, PURPLE, TEAL, SEV_COLOR, _esc, _chip, _strip,
    MILLER_CSS, _UNIFIED_CSS,
)

try:
    from .glossary import humanize
except Exception:  # when run as a bare module (sys.path insert), fall back
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from glossary import humanize  # type: ignore


# component_type -> glossary kind for token lookup
_COMP_KIND = {"card": "card", "interpretation_rule": "rule", "resolver": "gate",
              "evidence_package": None, "source_manifest": None, "skill": None,
              "framework": None, "method": None}


def _tok(graph, kind, token, mono=True):
    """Legibility render contract: human label PRIMARY, raw id secondary (hidden until the
    'show raw ids' toggle), plain-English gloss as tooltip. `_gloss` is the ONLY path a
    token reaches HTML."""
    if token in (None, ""):
        return "—"
    entry = ((graph.get("glossary") or {}).get(kind) or {}).get(token) if kind else None
    label = entry["label"] if entry else humanize(token)
    pe = entry["plain_english"] if entry else ""
    raw = f'<code class="rawid">{_esc(token)}</code>' if mono else f'<span class="rawid">{_esc(token)}</span>'
    ti = f' title="{_esc(pe)}"' if pe else ""
    return f'<span class="tok"{ti}>{_esc(label)}{raw}</span>'


# --------------------------------------------------------------------------- #
# GAPS (primary tab)
# --------------------------------------------------------------------------- #
_SEV_ORDER = ["error", "warn", "info"]
_SEV_LABEL = {"error": "Errors — broken wiring (fix first)",
              "warn": "Warnings — drifting / incomplete",
              "info": "Coverage gaps & backlog — honest missing pieces"}


def _gaps(graph):
    G = graph.get("gaps") or {}
    items = G.get("items") or []
    s = G.get("summary") or {}
    run = G.get("validators_run") or []

    if not items:
        return ('<p class="muted">No gaps found — every validator, health signal, and coverage '
                'check is clean. ✓</p>')

    top = _strip([
        ("errors", s.get("n_error", 0), RED),
        ("warnings", s.get("n_warn", 0), AMBER),
        ("info / backlog", s.get("n_info", 0), PURPLE),
        ("validators run", len(run), TEAL),
    ])
    intro = ('<p class="muted">One ranked view of every missing or broken piece the framework '
             'detects — aggregated from the gap-detection validators, the health rollup, and the '
             'coverage registry, so you do not have to read scattered CI logs. '
             '<b>Errors</b> break the build; <b>warnings</b> are drift; <b>info</b> are honest '
             'coverage gaps, not defects. Hover any row for the plain-language meaning.</p>')

    by_sev = {}
    for r in items:
        by_sev.setdefault(r["severity"], []).append(r)

    body = ""
    for sev in _SEV_ORDER:
        rows = by_sev.get(sev, [])
        if not rows:
            continue
        body += (f'<tr class="grp"><td colspan="5">{_chip(sev, SEV_COLOR.get(sev, PURPLE))} '
                 f'{_esc(_SEV_LABEL[sev])} ({len(rows)})</td></tr>')
        for r in rows:
            kind = _COMP_KIND.get(r["component_type"])
            comp = _tok(graph, kind, r["component_id"]) if r["component_id"] else \
                _chip(r["component_type"], GREY)
            body += (
                f'<tr><td>{_tok(graph, "gap_type", r["gap_type"], mono=False)}</td>'
                f'<td>{_chip(r["component_type"], GREY)}</td>'
                f'<td class="nm">{comp}</td>'
                f'<td>{_esc(r["message"])}</td>'
                f'<td class="consumers"><code class="rawid">{_esc(r["source"])}</code>'
                f'<span class="tokplain">{_esc(r["source"])}</span></td></tr>')
    table = ('<table class="tbl"><thead><tr><th>gap</th><th>component</th><th>which</th>'
             '<th>what &amp; why</th><th>found by</th></tr></thead><tbody>' + body + '</tbody></table>')
    return top + intro + table


# --------------------------------------------------------------------------- #
# CONCEPTS (secondary tab) — flow-tab blocks per component type
# --------------------------------------------------------------------------- #
def _schema_block(sch):
    if sch.get("error"):
        return f'<div class="muted">{_esc(sch["error"])}</div>'
    rows = ""
    for f in sch.get("fields", []):
        req = '<b class="req">required</b>' if f.get("required") else '<span class="muted">optional</span>'
        enum = ""
        if f.get("enum"):
            enum = '<div class="enum">' + " ".join(_chip(e, GREY) for e in f["enum"]) + '</div>'
        rows += (f'<tr><td class="nm"><code>{_esc(f["name"])}</code></td>'
                 f'<td class="muted">{_esc(f.get("type") or "")}</td><td>{req}</td>'
                 f'<td class="muted">{_esc(f.get("desc") or "")}{enum}</td></tr>')
    branch_html = ""
    if sch.get("branches"):
        branch_html = ('<p class="muted">Tagged union — one of: ' +
                       " · ".join("{" + ", ".join(_esc(k) for k in b) + "}" for b in sch["branches"]) + "</p>")
    path = f'<div class="captn">schema: <code>{_esc(sch.get("path") or "?")}</code> ' \
           f'({sch.get("n_props", 0)} properties, {len(sch.get("required", []))} required)</div>'
    return (path + branch_html +
            ('<table class="tbl"><thead><tr><th>field</th><th>type</th><th></th><th>notes</th></tr>'
             '</thead><tbody>' + rows + '</tbody></table>' if rows else ""))


def _example_block(ex):
    if not ex.get("resolved"):
        return f'<div class="muted">{_esc(ex.get("note") or "no example resolved")}</div>'
    src = f'<div class="captn">real instance: <code>{_esc(ex.get("source_path"))}</code></div>'
    fields = ex.get("fields") or {}
    rows = ""
    for k, v in fields.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, separators=(",", ": "))
        rows += f'<tr><td class="nm"><code>{_esc(k)}</code></td><td>{_esc(v)}</td></tr>'
    tbl = ('<table class="tbl"><tbody>' + rows + '</tbody></table>') if rows else \
        '<div class="muted">(no load-bearing fields surfaced)</div>'
    return src + tbl


def _concepts(graph):
    C = graph.get("concepts") or []
    if not C:
        return '<div class="empty">no concepts (concepts.yaml missing?)</div>'
    intro = ('<p class="muted">The building blocks, from raw dataset to composed output. Each block: '
             'what it IS, its <b>schema</b> shape, a <b>real example</b> harvested live from the repos, '
             'and where it is defined. This is the conceptual companion to the Explorer (which shows how '
             'specific instances are wired together).</p>')
    blocks = ""
    for i, c in enumerate(C):
        di = c.get("defined_in") or {}
        count = di.get("count")
        cnt_chip = _chip(f"{count} in repo", TEAL) if count is not None else ""
        name = f"ct{i}"
        blocks += f'''
<div class="cblock">
  <div class="chead"><span class="cnum">{c.get("order")}</span>
    <span class="ctitle">{_esc(c.get("title"))}</span> {cnt_chip}
    <span class="cdef muted">{_esc(di.get("glob") or "")} <span class="rawid">({_esc(di.get("root_name"))})</span></span>
  </div>
  <div class="flowtabs">
    <input type="radio" name="{name}" id="{name}-a" checked><label for="{name}-a">Concept</label>
    <input type="radio" name="{name}" id="{name}-b"><label for="{name}-b">Schema</label>
    <input type="radio" name="{name}" id="{name}-c"><label for="{name}-c">Example</label>
    <div class="ftpane ft-a"><p>{_esc(c.get("narration"))}</p></div>
    <div class="ftpane ft-b">{_schema_block(c.get("schema") or {})}</div>
    <div class="ftpane ft-c">{_example_block(c.get("example") or {})}</div>
  </div>
</div>'''
    return intro + blocks


# --------------------------------------------------------------------------- #
# DOCS (fold) tab
# --------------------------------------------------------------------------- #
def _narrative(graph):
    N = graph.get("narrative") or {}
    docs = {d["stem"]: d for d in N.get("docs") or []}
    byc = N.get("by_component") or {}
    if not docs:
        return '<div class="empty">no design docs indexed</div>'
    intro = (f'<p class="muted">{N.get("n_docs", 0)} design docs '
             f'({N.get("n_keyed", 0)} keyed to a component). The prose behind the contracts — '
             'grouped by the component each explains. Links open the source markdown.</p>')
    # component order = concepts order, then "general"
    comp_order = [c["id"] for c in (graph.get("concepts") or [])] + ["general"]
    seen = set()
    body = ""
    for comp in comp_order:
        stems = byc.get(comp)
        if not stems:
            continue
        lbl = ((graph.get("glossary") or {}).get("component_type") or {}).get(comp, {}).get("label") \
            or humanize(comp)
        body += f'<h2>{_esc(lbl)}</h2><div class="doclist">'
        for stem in stems:
            if (comp, stem) in seen:
                continue
            seen.add((comp, stem))
            d = docs.get(stem)
            if not d:
                continue
            body += (f'<div class="doccard"><div class="docttl">{_esc(d["title"])} '
                     f'<span class="rawid">{_esc(d["repo"])}/{_esc(d["path"])}</span></div>'
                     f'<div class="docsum muted">{_esc(d["summary"])}</div></div>')
        body += '</div>'
    return intro + body


# --------------------------------------------------------------------------- #
# CSS + shell
# --------------------------------------------------------------------------- #
_LIVING_CSS = """
.tok .rawid{display:none;margin-left:6px;color:var(--muted);font-size:10.5px;background:#eee;padding:0 4px;border-radius:3px}
body.showraw .tok .rawid,body.showraw .rawid{display:inline}
.rawid{display:none}
.tokplain{display:none}
.rawtoggle{margin-left:auto;font-size:11px;color:#cfcfca;cursor:pointer;user-select:none;display:flex;align-items:center;gap:6px}
.rawtoggle input{cursor:pointer}
.cblock{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:10px 0;overflow:hidden}
.chead{display:flex;align-items:center;gap:10px;padding:9px 14px;background:#f3f2ec;border-bottom:1px solid var(--line);flex-wrap:wrap}
.cnum{background:var(--purple);color:#fff;width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
.ctitle{font-weight:700;font-size:14px}
.cdef{font-size:11px;margin-left:6px}
.flowtabs{padding:12px 14px}
.flowtabs input[type=radio]{display:none}
.flowtabs>label{display:inline-block;padding:5px 14px;margin:0 3px 8px 0;border:1px solid var(--line);border-radius:14px;font-size:12px;font-weight:600;cursor:pointer;color:var(--muted)}
.flowtabs .ftpane{display:none;font-size:12.5px;line-height:1.55}
.flowtabs>#ct0-a:checked~.ft-a,.flowtabs>#ct1-a:checked~.ft-a,.flowtabs>#ct2-a:checked~.ft-a,.flowtabs>#ct3-a:checked~.ft-a,.flowtabs>#ct4-a:checked~.ft-a,.flowtabs>#ct5-a:checked~.ft-a,.flowtabs>#ct6-a:checked~.ft-a,.flowtabs>#ct7-a:checked~.ft-a{display:block}
.flowtabs>#ct0-b:checked~.ft-b,.flowtabs>#ct1-b:checked~.ft-b,.flowtabs>#ct2-b:checked~.ft-b,.flowtabs>#ct3-b:checked~.ft-b,.flowtabs>#ct4-b:checked~.ft-b,.flowtabs>#ct5-b:checked~.ft-b,.flowtabs>#ct6-b:checked~.ft-b,.flowtabs>#ct7-b:checked~.ft-b{display:block}
.flowtabs>#ct0-c:checked~.ft-c,.flowtabs>#ct1-c:checked~.ft-c,.flowtabs>#ct2-c:checked~.ft-c,.flowtabs>#ct3-c:checked~.ft-c,.flowtabs>#ct4-c:checked~.ft-c,.flowtabs>#ct5-c:checked~.ft-c,.flowtabs>#ct6-c:checked~.ft-c,.flowtabs>#ct7-c:checked~.ft-c{display:block}
.flowtabs input:checked+label{color:#fff;background:var(--purple);border-color:var(--purple)}
.enum{margin-top:3px}
.req{color:var(--purple);font-size:11px}
.doclist{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:6px 0 14px}
.doccard{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:9px 12px}
.docttl{font-weight:700;font-size:12.5px;margin-bottom:3px}
.docsum{font-size:11.5px;line-height:1.5}
@media(max-width:900px){.doclist{grid-template-columns:1fr}}
"""


def render_html(graph: dict) -> str:
    s = graph["summary"]
    H = graph.get("health") or {}
    G = graph.get("gaps") or {}
    gs = G.get("summary") or {}
    hgen = _esc(str(H.get("generated_at", ""))[:19])
    agen = _esc(str(graph.get("generated_at", ""))[:19])
    shas = " · ".join(f"{k}@{v}" for k, v in (graph.get("root_shas") or {}).items() if v)
    data_json = json.dumps(graph, separators=(",", ":"))

    gaps_badge = ""
    if gs.get("n_error") or gs.get("n_warn"):
        gaps_badge = f' <span class="tabbadge" style="background:{RED if gs.get("n_error") else AMBER}">' \
                     f'{gs.get("n_error", 0)}!·{gs.get("n_warn", 0)}⚠</span>'

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Living Architecture Document</title>
<style>{MILLER_CSS}{_UNIFIED_CSS}{_LIVING_CSS}
.tabbadge{{color:#fff;border-radius:9px;padding:0 6px;font-size:10px;font-weight:700}}
</style></head><body>
<header><h1>Living Architecture Document</h1>
<span class="meta">{s['n_skills']} skills · {s['n_cards']} cards · {s['n_datasets']} datasets · {s['n_resolvers']} resolvers/{s['n_verdicts']} verdicts</span>
<div class="orient">Auto-generated from the contracts. <b>Gaps</b> = missing/broken pieces · <b>Concepts</b> = the building blocks + schemas + real examples · <b>Explorer</b> = the wiring · <b>Docs</b> = the prose. Generated {agen} · health {hgen} · {shas}</div>
</header>
<div class="utabs">
  <div class="utab active" id="utab-overview" onclick="showTab('overview')">Overview</div>
  <div class="utab" id="utab-gaps" onclick="showTab('gaps')">Gaps{gaps_badge}</div>
  <div class="utab" id="utab-concepts" onclick="showTab('concepts')">Concepts</div>
  <div class="utab" id="utab-explorer" onclick="showTab('explorer')">Explorer</div>
  <div class="utab" id="utab-axes" onclick="showTab('axes')">Axes</div>
  <div class="utab" id="utab-health" onclick="showTab('health')">Health</div>
  <div class="utab" id="utab-cards" onclick="showTab('cards')">Cards</div>
  <div class="utab" id="utab-datasets" onclick="showTab('datasets')">Datasets</div>
  <div class="utab" id="utab-coverage" onclick="showTab('coverage')">Coverage</div>
  <div class="utab" id="utab-docs" onclick="showTab('docs')">Docs</div>
  <label class="rawtoggle"><input type="checkbox" id="rawtog" onchange="document.body.classList.toggle('showraw',this.checked)"> show raw ids</label>
</div>

<div class="upane active" id="pane-overview"><main>{U._overview(graph)}</main></div>
<div class="upane" id="pane-gaps"><main><h2>Gaps — every missing or broken piece, ranked</h2>{_gaps(graph)}</main></div>
<div class="upane" id="pane-concepts"><main><h2>Concepts &amp; schemas — the building blocks</h2>{_concepts(graph)}</main></div>

<div class="upane" id="pane-explorer">
  <div class="toolbar">
    <div class="modebtns">
      <button class="modebtn active" id="mode-skill" onclick="setMode('skill')">Skill-first</button>
      <button class="modebtn" id="mode-dataset" onclick="setMode('dataset')">Dataset-first</button>
    </div>
    <input class="search" id="search" placeholder="filter first column…" oninput="onSearch()">
    <div class="legend" id="legend"></div>
  </div>
  <div id="miller"></div>
</div>

<div class="upane" id="pane-axes"><main><h2>Objective → axis → card ontology</h2>{U._axes(graph)}</main></div>
<div class="upane" id="pane-health"><main><h2>Skill health matrix</h2>{U._health(graph)}</main></div>
<div class="upane" id="pane-cards"><main><h2>Card inventory</h2>{U._cards(graph)}</main></div>
<div class="upane" id="pane-datasets"><main><h2>Dataset inventory</h2>{U._datasets(graph)}</main></div>
<div class="upane" id="pane-coverage"><main><h2>Output coverage</h2>{U._coverage(graph)}</main></div>
<div class="upane" id="pane-docs"><main><h2>Docs — the prose behind the contracts</h2>{_narrative(graph)}</main></div>

<script>
const DATA = {data_json};
{render_arch._JS}
function showTab(id){{
  document.querySelectorAll('.upane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.utab').forEach(t=>t.classList.remove('active'));
  document.getElementById('pane-'+id).classList.add('active');
  document.getElementById('utab-'+id).classList.add('active');
}}
</script>
</body></html>"""
