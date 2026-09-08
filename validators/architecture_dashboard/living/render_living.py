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
    _UNIFIED_CSS,
    AMBER,
    GREY,
    MILLER_CSS,
    PURPLE,
    RED,
    SEV_COLOR,
    TEAL,
    _chip,
    _esc,
    _strip,
)

try:
    from .glossary import humanize
except Exception:  # when run as a bare module (sys.path insert), fall back
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from glossary import humanize  # type: ignore


# component_type -> glossary kind for token lookup
_COMP_KIND = {
    "card": "card",
    "interpretation_rule": "rule",
    "resolver": "gate",
    "evidence_package": None,
    "source_manifest": None,
    "skill": None,
    "framework": None,
    "method": None,
}


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
_SEV_LABEL = {
    "error": "Errors — broken wiring (fix first)",
    "warn": "Warnings — drifting / incomplete",
    "info": "Coverage gaps & backlog — honest missing pieces",
}


def _gaps(graph):
    G = graph.get("gaps") or {}
    items = G.get("items") or []
    s = G.get("summary") or {}
    run = G.get("validators_run") or []

    if not items:
        return '<p class="muted">No gaps found — every validator, health signal, and coverage check is clean. ✓</p>'

    top = _strip(
        [
            ("errors", s.get("n_error", 0), RED),
            ("warnings", s.get("n_warn", 0), AMBER),
            ("info / backlog", s.get("n_info", 0), PURPLE),
            ("validators run", len(run), TEAL),
        ]
    )
    intro = (
        '<p class="muted">One ranked view of every missing or broken piece the framework '
        "detects — aggregated from the gap-detection validators, the health rollup, and the "
        "coverage registry, so you do not have to read scattered CI logs. "
        "<b>Errors</b> break the build; <b>warnings</b> are drift; <b>info</b> are honest "
        "coverage gaps, not defects. Hover any row for the plain-language meaning.</p>"
    )

    by_sev = {}
    for r in items:
        by_sev.setdefault(r["severity"], []).append(r)

    body = ""
    for sev in _SEV_ORDER:
        rows = by_sev.get(sev, [])
        if not rows:
            continue
        body += (
            f'<tr class="grp"><td colspan="5">{_chip(sev, SEV_COLOR.get(sev, PURPLE))} '
            f"{_esc(_SEV_LABEL[sev])} ({len(rows)})</td></tr>"
        )
        for r in rows:
            kind = _COMP_KIND.get(r["component_type"])
            comp = _tok(graph, kind, r["component_id"]) if r["component_id"] else _chip(r["component_type"], GREY)
            body += (
                f"<tr><td>{_tok(graph, 'gap_type', r['gap_type'], mono=False)}</td>"
                f"<td>{_chip(r['component_type'], GREY)}</td>"
                f'<td class="nm">{comp}</td>'
                f"<td>{_esc(r['message'])}</td>"
                f'<td class="consumers"><code class="rawid">{_esc(r["source"])}</code>'
                f'<span class="tokplain">{_esc(r["source"])}</span></td></tr>'
            )
    table = (
        '<table class="tbl"><thead><tr><th>gap</th><th>component</th><th>which</th>'
        "<th>what &amp; why</th><th>found by</th></tr></thead><tbody>" + body + "</tbody></table>"
    )
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
            enum = '<div class="enum">' + " ".join(_chip(e, GREY) for e in f["enum"]) + "</div>"
        rows += (
            f'<tr><td class="nm"><code>{_esc(f["name"])}</code></td>'
            f'<td class="muted">{_esc(f.get("type") or "")}</td><td>{req}</td>'
            f'<td class="muted">{_esc(f.get("desc") or "")}{enum}</td></tr>'
        )
    branch_html = ""
    if sch.get("branches"):
        branch_html = (
            '<p class="muted">Tagged union — one of: '
            + " · ".join("{" + ", ".join(_esc(k) for k in b) + "}" for b in sch["branches"])
            + "</p>"
        )
    path = (
        f'<div class="captn">schema: <code>{_esc(sch.get("path") or "?")}</code> '
        f"({sch.get('n_props', 0)} properties, {len(sch.get('required', []))} required)</div>"
    )
    return (
        path
        + branch_html
        + (
            '<table class="tbl"><thead><tr><th>field</th><th>type</th><th></th><th>notes</th></tr>'
            "</thead><tbody>" + rows + "</tbody></table>"
            if rows
            else ""
        )
    )


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
    tbl = (
        ('<table class="tbl"><tbody>' + rows + "</tbody></table>")
        if rows
        else '<div class="muted">(no load-bearing fields surfaced)</div>'
    )
    return src + tbl


def _concepts(graph):
    C = graph.get("concepts") or []
    if not C:
        return '<div class="empty">no concepts (concepts.yaml missing?)</div>'
    intro = (
        '<p class="muted">The building blocks, from raw dataset to composed output. Each block: '
        "what it IS, its <b>schema</b> shape, a <b>real example</b> harvested live from the repos, "
        "and where it is defined. This is the conceptual companion to the Explorer (which shows how "
        "specific instances are wired together).</p>"
    )
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
    intro = (
        f'<p class="muted">{N.get("n_docs", 0)} design docs '
        f"({N.get('n_keyed', 0)} keyed to a component). The prose behind the contracts — "
        "grouped by the component each explains. Links open the source markdown.</p>"
    )
    # component order = concepts order, then "general"
    comp_order = [c["id"] for c in (graph.get("concepts") or [])] + ["general"]
    seen = set()
    body = ""
    for comp in comp_order:
        stems = byc.get(comp)
        if not stems:
            continue
        lbl = ((graph.get("glossary") or {}).get("component_type") or {}).get(comp, {}).get("label") or humanize(comp)
        body += f'<h2>{_esc(lbl)}</h2><div class="doclist">'
        for stem in stems:
            if (comp, stem) in seen:
                continue
            seen.add((comp, stem))
            d = docs.get(stem)
            if not d:
                continue
            body += (
                f'<div class="doccard"><div class="docttl">{_esc(d["title"])} '
                f'<span class="rawid">{_esc(d["repo"])}/{_esc(d["path"])}</span></div>'
                f'<div class="docsum muted">{_esc(d["summary"])}</div></div>'
            )
        body += "</div>"
    return intro + body


# --------------------------------------------------------------------------- #
# FLOW — the workflow schema diagrams at multiple altitudes
# --------------------------------------------------------------------------- #
_KIND_COLOR = {
    "source_manifest": TEAL,
    "derived_manifest": TEAL,
    "method": "#199e70",
    "card": PURPLE,
    "interpretation_rule": AMBER,
    "resolver": RED,
    "skill": "#2b6cb0",
    "evidence_package": GREY,
}


def _pnode(graph, st):
    kc = _KIND_COLOR.get(st.get("kind"), GREY)
    badge = st.get("component_label") or st.get("kind") or ""
    jump = (
        ' onclick="event.stopPropagation();showTab(\'concepts\')" title="see this component in Concepts"'
        if st.get("concept_present")
        else ""
    )
    tokchip = ""
    if st.get("token") and st.get("token_gloss"):
        tg = st["token_gloss"]
        tokchip = (
            f'<div class="ptok" title="{_esc(tg.get("plain_english"))}">'
            f'{_esc(tg.get("label"))}<code class="rawid">{_esc(st["token"])}</code></div>'
        )
    ex = f'<div class="pex">{_esc(st["example"])}</div>' if st.get("example") else ""
    art = f'<div class="part">▸ {_esc(st["artifact"])}</div>' if st.get("artifact") else ""
    # zoom-in: a stage that expands into another level is clickable
    drill = st.get("drill_idx")
    zoom, cls, onclick = "", "pnode", ""
    if drill is not None:
        zoom = '<div class="pzoom">⤢ zoom in</div>'
        cls = "pnode drillable"
        onclick = f' onclick="selFlow({drill})" title="zoom into this abstraction"'
    return (
        f'<div class="{cls}" style="border-top:3px solid {kc}"{onclick}>'
        f'<div class="pbadge" style="color:{kc}"{jump}>{_esc(badge)}</div>'
        f'<div class="ptitle">{_esc(st["label"])}</div>'
        f'<div class="pplain">{_esc(st["plain"])}</div>'
        f"{tokchip}{ex}{art}{zoom}</div>"
    )


def _lane(lane):
    if not lane:
        return ""
    steps = "".join(f"<li>{_esc(s)}</li>" for s in lane.get("steps", []))
    di = lane.get("drill_idx")
    zoom = f'<button class="lanezoom" onclick="selFlow({di})">⤢ zoom into this lane</button>' if di is not None else ""
    return (
        f'<div class="lane"><div class="laneup">▲ from <b>{_esc(lane.get("from"))}</b></div>'
        f'<div class="lanehd">{_esc(lane.get("label"))}{zoom}</div>'
        f'<ul class="lanesteps">{steps}</ul>'
        f'<div class="laneinv">{_esc(lane.get("invariant"))}</div></div>'
    )


def _pipeline(graph, lv):
    nodes = '<span class="parrow">▸</span>'.join(_pnode(graph, st) for st in lv["stages"])
    return f'<div class="pipe">{nodes}</div>' + _lane(lv.get("lane"))


def _hub(graph, lv):
    c = lv["center"]
    kc = _KIND_COLOR.get(c.get("kind"), PURPLE)
    vb = _chip(
        "verdict-bearing" if lv.get("verdict_bearing") else "verdict-inert",
        PURPLE if lv.get("verdict_bearing") else GREY,
    )
    center = (
        f'<div class="hubcenter" style="border:2px solid {kc}">'
        f'<div class="pbadge" style="color:{kc}" onclick="showTab(\'concepts\')">'
        f"{_esc(c.get('component_label'))}</div>"
        f'<div class="ptitle">{_esc(c["label"])}</div>'
        f'<div class="pplain">{_esc(c["plain"])}</div>{vb}</div>'
    )
    sats = ""
    for s in lv["satellites"]:
        kc2 = _KIND_COLOR.get(s.get("kind"), GREY)
        items = "".join(f"<li><code>{_esc(i)}</code></li>" for i in s["items"])
        sats += (
            f'<div class="hubsat" style="border-left:3px solid {kc2}">'
            f'<div class="satrole">{_esc(s["role"])}</div><ul>{items}</ul></div>'
        )
    return f'<div class="hub">{center}<div class="hubsats">{sats}</div></div>'


def _flow(graph):
    F = graph.get("flow") or {}
    levels = F.get("levels") or []
    if not levels:
        return '<div class="empty">no flow model</div>'
    w = F.get("worked") or {}
    intro = (
        '<p class="muted">The framework at different zoom levels — pick an altitude. The '
        f"concrete values trace one real slice (<b>{_esc(w.get('target'))}</b> in "
        f"<b>{_esc(w.get('indication'))}</b>, {_esc(w.get('gate'))} gate); the tokens are real "
        "contract ids (a self-check fails if any goes stale). Click a component badge to open "
        "it in Concepts.</p>"
    )
    pick = (
        '<div class="flowpick">'
        + "".join(
            f'<button class="flowbtn{" active" if i == 0 else ""}" id="flowbtn-{i}" '
            f'onclick="selFlow({i})">{_esc(lv["title"])}</button>'
            for i, lv in enumerate(levels)
        )
        + "</div>"
    )
    panes = ""
    for i, lv in enumerate(levels):
        body = _hub(graph, lv) if lv.get("layout") == "hub" else _pipeline(graph, lv)
        # breadcrumb: zoom OUT to parent + the child levels this one drills INTO
        crumb = ""
        if lv.get("parent_idx") is not None:
            pt = levels[lv["parent_idx"]]["title"]
            crumb += f'<button class="crumb up" onclick="selFlow({lv["parent_idx"]})">↑ zoom out · {_esc(pt)}</button>'
        for ch in lv.get("child_idx") or []:
            crumb += f'<button class="crumb down" onclick="selFlow({ch["idx"]})">⤢ {_esc(ch["title"])}</button>'
        crumb_html = f'<div class="crumbs">{crumb}</div>' if crumb else ""
        # a level with a wire schematic gets a schematic ⇄ boxes toggle (schematic leads on card level)
        if lv.get("schematic"):
            lead = bool(lv.get("default_schem"))
            tog = (
                f'<div class="viewtog">'
                f'<button class="vbtn{" active" if lead else ""}" id="vbtn-schem-{i}" '
                f"onclick=\"flowView({i},'schem')\">◫ schematic</button>"
                f'<button class="vbtn{"" if lead else " active"}" id="vbtn-boxes-{i}" '
                f"onclick=\"flowView({i},'boxes')\">▤ boxes</button></div>"
            )
            content = (
                tog
                + f'<div class="fv fv-schem{" on" if lead else ""}" id="fvs-{i}">'
                + _schematic_pre(lv["schematic"])
                + "</div>"
                + f'<div class="fv fv-boxes{"" if lead else " on"}" id="fvb-{i}">{body}</div>'
            )
        else:
            content = body
        panes += (
            f'<div class="flvl{" active" if i == 0 else ""}" id="flvl-{i}">'
            f'{crumb_html}<div class="flsub">{_esc(lv.get("subtitle"))}</div>{content}</div>'
        )
    return intro + pick + panes


def _schematic_pre(art):
    return f'<pre class="schem">{_esc(art)}</pre>'


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
/* flow diagrams */
.flowpick{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 14px}
.flowbtn{padding:6px 12px;border:1px solid var(--line);border-radius:16px;background:var(--card);
  font-size:11.5px;font-weight:600;color:var(--muted);cursor:pointer}
.flowbtn.active{background:var(--purple);color:#fff;border-color:var(--purple)}
.flvl{display:none}.flvl.active{display:block}
.flsub{background:#161616;color:#e8e8e8;border-radius:8px;padding:10px 14px;margin:0 0 14px;font-size:12.5px;line-height:1.55}
.pipe{display:flex;flex-wrap:wrap;align-items:stretch;gap:0}
.pnode{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;
  width:210px;min-width:210px;flex:0 0 auto;box-shadow:0 1px 3px rgba(0,0,0,.07)}
.parrow{display:flex;align-items:center;color:var(--purple);font-size:22px;font-weight:700;padding:0 6px}
.pbadge{font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;cursor:pointer}
.ptitle{font-weight:700;font-size:13px;margin:2px 0 4px}
.pplain{font-size:11px;color:var(--muted);line-height:1.45}
.ptok{margin-top:6px;font-size:11px;background:#f3f0fa;border:1px solid #e0d8f2;border-radius:4px;padding:2px 6px}
.pex{margin-top:6px;font-size:11px;font-family:ui-monospace,Menlo,monospace;background:#f5f4ef;border-radius:4px;padding:3px 6px;word-break:break-word}
.part{margin-top:5px;font-size:11px;font-family:ui-monospace,Menlo,monospace;color:#199e70;font-weight:600}
.lane{margin:14px 0 0;background:#fbfaf6;border:1px dashed var(--purple);border-radius:8px;padding:10px 14px}
.laneup{font-size:11px;color:var(--purple);font-weight:700;margin-bottom:2px}
.lanehd{font-weight:700;font-size:12.5px}
.lanesteps{margin:5px 0;padding-left:18px;font-size:11.5px;color:var(--muted);line-height:1.5}
.laneinv{font-size:12px;font-weight:700;margin-top:4px}
.hub{display:grid;grid-template-columns:280px 1fr;gap:16px;align-items:start}
.hubcenter{background:var(--card);border-radius:10px;padding:14px}
.hubsats{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.hubsat{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 10px}
.satrole{font-size:9.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.hubsat ul{margin:0;padding-left:16px;font-size:11px;line-height:1.5}
.pnode.drillable{cursor:pointer;transition:.1s}
.pnode.drillable:hover{border-color:var(--purple);box-shadow:0 3px 12px rgba(108,90,168,.2);transform:translateY(-1px)}
.pzoom{margin-top:7px;font-size:10px;font-weight:700;color:var(--purple);text-transform:uppercase;letter-spacing:.04em}
.crumbs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.crumb{font-size:11px;font-weight:600;border:1px solid var(--line);border-radius:14px;padding:4px 11px;cursor:pointer;background:var(--card)}
.crumb.up{color:#2b6cb0;border-color:#bcd0ea}
.crumb.down{color:var(--purple);border-color:#e0d8f2}
.crumb:hover{filter:brightness(.97)}
.lanezoom{margin-left:10px;font-size:10.5px;font-weight:700;color:var(--purple);background:none;border:1px solid #e0d8f2;border-radius:12px;padding:2px 9px;cursor:pointer}
.viewtog{display:flex;gap:4px;margin:0 0 10px}
.vbtn{font-size:11px;font-weight:600;border:1px solid var(--line);border-radius:6px;padding:4px 12px;cursor:pointer;background:var(--card);color:var(--muted)}
.vbtn.active{background:#161616;color:#fff;border-color:#161616}
.fv{display:none}.fv.on{display:block}
pre.schem{background:#161616;color:#e8e8e8;border-radius:8px;padding:14px 16px;overflow-x:auto;
  font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;line-height:1.35;white-space:pre;margin:0}
@media(max-width:900px){.pnode{width:100%;min-width:0}.parrow{transform:rotate(90deg);padding:2px 0}
  .pipe{flex-direction:column}.hub{grid-template-columns:1fr}.hubsats{grid-template-columns:1fr}}
"""


def render_html(graph: dict) -> str:
    s = graph["summary"]
    H = graph.get("health") or {}
    G = graph.get("gaps") or {}
    gs = G.get("summary") or {}
    hgen = _esc(str(H.get("generated_at", ""))[:19])
    agen = _esc(str(graph.get("generated_at", ""))[:19])
    shas = " · ".join(f"{k}@{v}" for k, v in (graph.get("root_shas") or {}).items() if v)
    # escape "<" so a literal "</script>" anywhere in embedded graph text (design-doc prose,
    # evidence-package example fields, card questions) cannot terminate this <script> element.
    data_json = json.dumps(graph, separators=(",", ":")).replace("<", "\\u003c")

    gaps_badge = ""
    if gs.get("n_error") or gs.get("n_warn"):
        gaps_badge = (
            f' <span class="tabbadge" style="background:{RED if gs.get("n_error") else AMBER}">'
            f"{gs.get('n_error', 0)}!·{gs.get('n_warn', 0)}⚠</span>"
        )

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Framework Atlas</title>
<style>{MILLER_CSS}{_UNIFIED_CSS}{_LIVING_CSS}
.tabbadge{{color:#fff;border-radius:9px;padding:0 6px;font-size:10px;font-weight:700}}
</style></head><body>
<header><h1>Framework Atlas</h1>
<span class="meta">{s["n_skills"]} skills · {s["n_cards"]} cards · {s["n_datasets"]} datasets · {s["n_resolvers"]} resolvers/{s["n_verdicts"]} verdicts</span>
<div class="orient">Auto-generated from the contracts. <b>Gaps</b> = missing/broken pieces · <b>Concepts</b> = the building blocks + schemas + real examples · <b>Explorer</b> = the wiring · <b>Docs</b> = the prose. Generated {agen} · health {hgen} · {shas}</div>
</header>
<div class="utabs">
  <div class="utab active" id="utab-overview" onclick="showTab('overview')">Overview</div>
  <div class="utab" id="utab-flow" onclick="showTab('flow')">Flow</div>
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
<div class="upane" id="pane-flow"><main><h2>Flow — the framework at every altitude</h2>{_flow(graph)}</main></div>
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
function selFlow(i){{
  showTab('flow');
  document.querySelectorAll('.flvl').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.flowbtn').forEach(b=>b.classList.remove('active'));
  var pane=document.getElementById('flvl-'+i), btn=document.getElementById('flowbtn-'+i);
  if(pane) pane.classList.add('active');
  if(btn){{ btn.classList.add('active'); btn.scrollIntoView({{block:'nearest',inline:'center'}}); }}
  window.scrollTo({{top:0,behavior:'smooth'}});
}}
function flowView(i,mode){{
  var b=document.getElementById('fvb-'+i), s=document.getElementById('fvs-'+i);
  if(b) b.classList.toggle('on', mode==='boxes');
  if(s) s.classList.toggle('on', mode==='schem');
  ['schem','boxes'].forEach(function(m){{
    var x=document.getElementById('vbtn-'+m+'-'+i); if(x) x.classList.toggle('active', m===mode);
  }});
}}
</script>
</body></html>"""
