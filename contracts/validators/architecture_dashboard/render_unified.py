"""render_unified.py — ONE self-contained HTML: Overview → Explorer / Health / Cards / Datasets.

Reuses the Miller-columns CSS+JS from render_arch (imported, not duplicated) for the
Explorer tab; renders Overview / Health / Cards / Datasets as Python-generated static
HTML from the merged graph (arch wiring + framework_health overlay). One palette, one build.
"""

from __future__ import annotations

import html
import json
import re

import render_arch  # reuse Miller-columns CSS + behavior

# ---- palette (Python side; mirrors render_arch JS `C`) --------------------
GREEN, AMBER, RED, GREY, PURPLE, TEAL, DARK = (
    "#0ca30c",
    "#fab219",
    "#c0392b",
    "#898781",
    "#6c5aa8",
    "#199e70",
    "#52514e",
)
VERDICT_COLOR = {
    "production_ready": GREEN,
    "ready_unproven": TEAL,
    "operational": TEAL,
    "partial": AMBER,
    "placeholder": GREY,
    "broken_or_drift": RED,
    "wired": GREEN,
    "not_wired": GREY,
    "unknown": GREY,
}
CARD_COLOR = {"live": GREEN, "partial": AMBER, "blocked": "#b8860b", "placeholder": GREY, "broken": RED}
SEV_COLOR = {"error": RED, "warn": AMBER, "info": PURPLE}
RES_COLOR = {"manifest": GREEN, "non-manifest resource": AMBER, "uncataloged": RED}

# Miller CSS extracted from render_arch so the Explorer tab's classes always match.
_m = re.search(r"<style>(.*?)</style>", render_arch._HTML_HEAD, re.DOTALL)
MILLER_CSS = _m.group(1) if _m else ""


def _esc(x):
    return html.escape("" if x is None else str(x))


def _chip(t, color, title=None):
    ti = f' title="{_esc(title)}"' if title else ""
    return f'<span class="chip" style="background:{color}"{ti}>{_esc(t)}</span>'


def _dot(color, t=""):
    return f'<span class="hdot" style="background:{color}" title="{_esc(t)}"></span>'


def _strip(items):
    parts = "".join(
        f'<span class="stat"><span class="hdot" style="background:{c}"></span><b>{n}</b> {_esc(l)}</span>'
        for l, n, c in items
    )
    return f'<div class="strip">{parts}</div>'


# ---------------------------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------------------------
def _overview(g):
    s = g["summary"]
    H = g.get("health") or {}
    hs = H.get("summary", {})
    vt = hs.get("verdict_tally", {})
    cht = hs.get("card_health_tally", {})

    # hero line
    ready = vt.get("production_ready", 0)
    partial = vt.get("partial", 0)
    err = hs.get("n_error_drift", 0)
    hero = (
        f"<b>{s['n_skills']}</b> skills · <b>{s['n_cards']}</b> cards "
        f"(<b>{s['n_verdict_bearing_cards']}</b> verdict-bearing) · "
        f"<b>{s['n_datasets']}</b> datasets · <b>{s['n_resolvers']}</b> resolvers / "
        f"<b>{s['n_verdicts']}</b> verdicts. "
        f'{ready} production-ready, {partial} partial, <b style="color:{"#ffb3a7" if err else "#7fe0a0"}">'
        f"{err} error-drift</b>."
    )

    # skill verdict strip (clickable → Health)
    skill_strip = (
        _strip(
            [
                ("production-ready", vt.get("production_ready", 0), GREEN),
                ("ready (unproven)", vt.get("ready_unproven", 0), TEAL),
                ("partial", vt.get("partial", 0), AMBER),
                ("placeholder", vt.get("placeholder", 0), GREY),
                ("drift", vt.get("broken_or_drift", 0), RED),
            ]
        )
        if vt
        else '<div class="captn">no health data loaded</div>'
    )

    card_strip = (
        _strip(
            [
                ("live", cht.get("live", 0), GREEN),
                ("partial", cht.get("partial", 0), AMBER),
                ("blocked", cht.get("blocked", 0), "#b8860b"),
                ("broken", cht.get("broken", 0), RED),
            ]
        )
        if cht
        else ""
    )

    # dataset resolution strip
    res_tally = {"manifest": 0, "non-manifest resource": 0, "uncataloged": 0}
    fam = 0
    for d in g["datasets"].values():
        res_tally[d.get("resolution", "uncataloged")] = res_tally.get(d.get("resolution", "uncataloged"), 0) + 1
        if (d.get("family") or {}).get("is_family"):
            fam += 1
    ds_strip = _strip(
        [
            ("in manifest", res_tally["manifest"], GREEN),
            ("non-manifest resource", res_tally["non-manifest resource"], AMBER),
            ("uncataloged", res_tally["uncataloged"], RED),
            ("indication families", fam, TEAL),
        ]
    )

    # coverage frontier
    blocked = cht.get("blocked", 0)
    uncat = [d for d in g["datasets"].values() if not d["in_catalog"]]
    frontier = (
        '<div class="panel"><h3>Coverage frontier <span class="sub">— honest backlog, not drift</span></h3>'
        f"<p>{blocked} <b>blocked cards</b> (declared measurements with no live reader yet) · "
        f"{vt.get('partial', 0)} <b>partial skills</b> (data not fully landed) · "
        f'{len(uncat)} <b>uncataloged dataset refs</b>:</p><ul class="frontier">'
    )
    for d in sorted(uncat, key=lambda d: d["product_id"]):
        gc = d.get("gap_category") or "uncataloged"
        note = d.get("gap_note") or ""
        frontier += (
            f"<li>{_chip(gc, RED)} <b>{_esc(d['product_id'])}</b> "
            f'<span class="consumers">→ {len(d["consumed_by_cards"])} card(s)</span>'
            f'<div class="frnote">{_esc(note)}</div></li>'
        )
    frontier += "</ul></div>"

    # fix-next (drift warn+error grouped by code)
    di = H.get("drift_index", [])
    actionable = [d for d in di if d["severity"] in ("error", "warn")]
    fix = '<div class="panel"><h3>Fix-next <span class="sub">— actionable drift (error + warn)</span></h3>'
    if actionable:
        by = {}
        for d in actionable:
            by.setdefault(d["code"], []).append(d)
        fix += '<table class="tbl"><thead><tr><th>n</th><th>code</th><th>affected</th></tr></thead><tbody>'
        for code, items in sorted(by.items(), key=lambda kv: -len(kv[1])):
            sev = items[0]["severity"]
            who = ", ".join(sorted({d.get("skill") or d.get("card") or "" for d in items}))
            fix += (
                f"<tr><td>{_chip(str(len(items)), SEV_COLOR.get(sev, PURPLE))}</td>"
                f'<td><code>{_esc(code)}</code></td><td class="consumers">{_esc(who)}</td></tr>'
            )
        fix += "</tbody></table>"
    else:
        fix += "<p>No error/warn drift outstanding. ✓</p>"
    fix += "</div>"

    # tiles → tabs
    tiles = (
        '<div class="tiles">'
        f'<div class="tile" onclick="showTab(\'explorer\')"><div class="tn">{s["n_skills"]}</div>'
        '<div class="tl">Skills → Explorer</div><div class="td">click through the wiring: skill → cards → datasets · methods · outputs · rules → verdict</div></div>'
        f'<div class="tile" onclick="showTab(\'health\')"><div class="tn">{vt.get("partial", 0) + vt.get("broken_or_drift", 0)}</div>'
        '<div class="tl">to watch → Health</div><div class="td">derived health, drift, runs-clean, fix-next queue</div></div>'
        f'<div class="tile" onclick="showTab(\'cards\')"><div class="tn">{s["n_cards"]}</div>'
        '<div class="tl">Cards</div><div class="td">every card: inputs, outputs, rules, verdict, health</div></div>'
        f'<div class="tile" onclick="showTab(\'datasets\')"><div class="tn">{s["n_datasets"]}</div>'
        '<div class="tl">Datasets</div><div class="td">catalog resolution, indication families, coverage gaps</div></div>'
        + (
            f'<div class="tile" onclick="showTab(\'coverage\')"><div class="tn">'
            f"{(g.get('coverage') or {}).get('summary', {}).get('n_cells', 0)}</div>"
            '<div class="tl">Outputs → Coverage</div><div class="td">what the framework has produced: '
            "governed + exploratory outputs, coverage grid, liveness signal</div></div>"
            if g.get("coverage")
            else ""
        )
        + "</div>"
    )

    return (
        f'<div class="hero">{hero}</div>'
        + tiles
        + "<h2>Skills — health</h2>"
        + skill_strip
        + card_strip
        + "<h2>Datasets — catalog resolution</h2>"
        + ds_strip
        + '<div class="grid2">'
        + fix
        + frontier
        + "</div>"
    )


# ---------------------------------------------------------------------------
# HEALTH matrix
# ---------------------------------------------------------------------------
def _health(g):
    H = g.get("health")
    if not H:
        return '<div class="empty">no health data loaded — run with fresh framework_health</div>'
    skills = H["skills"]
    # group by risk_category
    groups = {}
    for name, s in skills.items():
        groups.setdefault(s.get("risk_category") or "ungrouped", []).append((name, s))
    rank = {"broken_or_drift": 0, "partial": 1, "ready_unproven": 2, "operational": 3, "production_ready": 4}
    body = ""
    for cat in sorted(groups, key=lambda c: (c == "ungrouped", c)):
        body += f'<tr class="grp"><td colspan="9">{_esc(cat)}</td></tr>'
        for name, s in sorted(groups[cat], key=lambda kv: rank.get(kv[1]["verdict"], 9)):
            v = s["verdict"]
            drift = s.get("drift_flags", [])
            dbadge = ""
            if drift:
                worst = max((d["severity"] for d in drift), key=lambda x: {"error": 3, "warn": 2, "info": 1}.get(x, 0))
                dbadge = _chip(
                    f"⚠{len(drift)}",
                    SEV_COLOR.get(worst, PURPLE),
                    "; ".join(f"{d['severity']}:{d['code']}" for d in drift),
                )
            rc = s.get("runs_clean")
            rc_cell = "—" if rc in (None, "unknown") else _chip(rc, GREEN if rc.startswith("clean") else RED)
            body += (
                f'<tr><td class="nm">{_esc(name)}</td>'
                f"<td>{_chip(v, VERDICT_COLOR.get(v, GREY), s.get('reason_text'))}</td>"
                f"<td>{rc_cell}</td>"
                f'<td class="consumers">{_esc(s.get("declared_status") or "—")}</td>'
                f"<td>{_esc(s.get('kind') or '—')}</td>"
                f"<td>{'✓' if s.get('resolver_bound') else '—'}</td>"
                f"<td>{_esc(s.get('test_count') or 0)}</td>"
                f"<td>{s.get('n_cards_live') or 0}/{s.get('n_cards') or 0}</td>"
                f"<td>{dbadge}</td></tr>"
            )
    return (
        '<table class="tbl matrix"><thead><tr>'
        "<th>skill</th><th>derived health</th><th>runs clean?</th><th>declared</th>"
        "<th>kind</th><th>resolver</th><th>tests</th><th>cards live</th><th>drift</th>"
        "</tr></thead><tbody>" + body + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# CARDS inventory
# ---------------------------------------------------------------------------
def _cards(g):
    cards = g["cards"]
    order = ["broken", "blocked", "partial", "live", None]
    groups = {}
    for cid, c in cards.items():
        groups.setdefault(c.get("health"), []).append(c)
    body = ""
    for h in order:
        if h not in groups:
            continue
        lbl = h or "health-unknown"
        body += f'<tr class="grp"><td colspan="7">{_esc(lbl)} ({len(groups[h])})</td></tr>'
        for c in sorted(groups[h], key=lambda c: c["card_id"]):
            ch = c.get("health")
            nv = len(c.get("verdicts") or [])
            vb = _chip(f"{nv}▸verdict", PURPLE) if nv else '<span class="consumers">inert</span>'
            method = c["methods"][0]["call"] if c.get("methods") else "—"
            cons = c.get("consumers") or []
            body += (
                f'<tr><td class="nm">{_esc(c["card_id"])}</td>'
                f"<td>{_chip(ch, CARD_COLOR.get(ch, GREY)) if ch else '—'}</td>"
                f"<td>{vb}</td>"
                f"<td>{_esc(c.get('measurement_type') or '—')}</td>"
                f"<td><code>{_esc(method)}</code></td>"
                f"<td>{len(c.get('datasets') or [])}</td>"
                f'<td class="consumers">{len(cons)} {_esc(", ".join(cons[:3]))}{"…" if len(cons) > 3 else ""}</td></tr>'
            )
    return (
        '<table class="tbl"><thead><tr><th>card</th><th>health</th><th>verdict</th>'
        "<th>measurement_type</th><th>method</th><th>datasets</th><th>consumed by</th>"
        "</tr></thead><tbody>" + body + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# DATASETS inventory
# ---------------------------------------------------------------------------
def _fmt_bytes(n):
    if not n:
        return "—"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.0f} PB"


def _datasets(g):
    ds = list(g["datasets"].values())
    groups = {"uncataloged": [], "non-manifest resource": [], "manifest": []}
    for d in ds:
        groups.setdefault(d.get("resolution", "uncataloged"), []).append(d)
    RES_LABEL = {
        "uncataloged": "Uncataloged references — a card names a product_id with no catalog record (gaps)",
        "non-manifest resource": "Non-manifest catalog resources — real, tracked outside manifests/ (subgroup-catalogs, resolver-releases)",
        "manifest": "In manifests — source + derived data products",
    }
    body = ""
    for res in ("uncataloged", "non-manifest resource", "manifest"):
        items = groups.get(res, [])
        if not items:
            continue
        body += f'<tr class="grp"><td colspan="6">{_esc(RES_LABEL.get(res, res))} ({len(items)})</td></tr>'
        for d in sorted(items, key=lambda d: (-(d.get("size_bytes") or 0), d["product_id"])):
            fam = d.get("family") or {}
            fam_cell = _chip(f"▦{fam['count']}", TEAL, "indication family") if fam.get("is_family") else "—"
            gap = _chip(d["gap_category"], RED) if d.get("gap_category") else ""
            body += (
                f'<tr><td class="nm">{_esc(d["product_id"])} {gap}</td>'
                f"<td>{_chip(d.get('resolution', '?'), RES_COLOR.get(d.get('resolution'), GREY))}</td>"
                f"<td>{_esc(d.get('kind') or '—')}</td>"
                f"<td>{fam_cell}</td>"
                f"<td>{_fmt_bytes(d.get('size_bytes'))}</td>"
                f'<td class="consumers">{len(d.get("consumed_by_cards") or [])} card(s) · '
                f"{len(d.get('consumed_by_skills') or [])} skill(s)</td></tr>"
            )
    return (
        '<table class="tbl"><thead><tr><th>dataset (product_id)</th><th>resolution</th>'
        "<th>kind</th><th>family</th><th>size</th><th>consumed by</th>"
        "</tr></thead><tbody>" + body + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# SHELL
# ---------------------------------------------------------------------------
_UNIFIED_CSS = """
.hero{background:#161616;color:#eee;border-radius:8px;padding:12px 16px;margin:12px 0;font-size:14px;line-height:1.6}
.hero b{color:#fff}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;cursor:pointer;transition:.1s}
.tile:hover{border-color:var(--purple);box-shadow:0 2px 8px rgba(108,90,168,.15)}
.tile .tn{font-size:26px;font-weight:700;color:var(--purple)}
.tile .tl{font-weight:700;font-size:12px;margin:2px 0}
.tile .td{font-size:10.5px;color:var(--muted);line-height:1.35}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start}
@media(max-width:900px){.tiles{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}}
.strip{display:flex;flex-wrap:wrap;gap:16px;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:7px 14px;margin:8px 0;font-size:13px}
.strip .stat{display:inline-flex;align-items:center;gap:5px;color:var(--muted)}
.strip .stat b{color:var(--ink);font-size:14px}
.hdot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:0 0 auto}
.tbl{width:100%;border-collapse:collapse;background:var(--card);border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.08);font-size:12px;margin:8px 0}
.tbl th{background:#52514e;color:#fff;text-align:left;padding:5px 9px;font-size:11px;position:sticky;top:0}
.tbl td{padding:4px 9px;border-top:1px solid var(--line)}
.tbl td.nm{font-weight:600}
.tbl tr.grp td{background:#e1e0d9;font-weight:700;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;padding:3px 9px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:0}
.panel h3{margin:0 0 8px;font-size:14px}
.panel .sub{font-weight:400;color:var(--muted);font-size:11px}
ul.frontier{margin:4px 0;padding-left:2px;list-style:none}
ul.frontier li{margin:6px 0;font-size:12px}
ul.frontier .frnote{color:var(--muted);font-size:11px;margin:2px 0 0 4px;line-height:1.4}
.consumers{color:var(--muted);font-size:11px}
.captn{color:var(--muted);font-size:11px;font-style:italic}
.utabs{display:flex;gap:3px;padding:0 22px;background:#0b0b0b;border-bottom:1px solid #333}
.utab{padding:9px 18px;cursor:pointer;font-weight:600;font-size:13px;color:#b9b8b1;border-bottom:3px solid transparent}
.utab.active{color:#fff;border-bottom-color:var(--purple)}
.upane{display:none}.upane.active{display:block}
.upane#pane-explorer.active{display:flex;flex-direction:column}
main{max-width:1220px;margin:0 auto;padding:14px 22px}
main.wide{max-width:100%;padding:0}
h2{font-size:14px;margin:16px 0 6px}
"""


COV_COLOR = {"captured": GREEN, "partial": AMBER, "blind": RED, "license_blocked": PURPLE, "out_of_scope": GREY}


def _axis_skill_pill(g, name):
    """A skill name that jumps into the Explorer tab and opens that skill."""
    if not name:
        return "—"
    sk = (g.get("skills") or {}).get(name)
    nc = f" · {sk['n_cards']}c" if sk else ""
    return (
        f'<span class="pill" title="open in Explorer" '
        f"onclick=\"showTab('explorer');setMode('skill');selSkill('{_esc(name)}')\">"
        f"{_esc(name)}{nc}</span>"
    )


def _axes(g):
    """The objective→axis→card organizing layer (vocabularies/target_profiling_axes.yaml)."""
    ax = g.get("axes")
    if not ax:
        return '<div class="empty">no axis ontology (vocabularies/target_profiling_axes.yaml) found</div>'
    qs = ax.get("questions", [])
    cv = ax.get("coverage_vocab", {})
    legend = " · ".join(_chip(k, COV_COLOR.get(k, GREY), v) for k, v in cv.items())

    def band_rows(band):
        rows = ""
        for q in [q for q in qs if q.get("band") == band]:
            cov = q.get("coverage")
            badges = ""
            if q.get("characterization_only"):
                badges += " " + _chip(
                    "advisory", GREY, "characterization-only — does not move the deterministic verdict"
                )
            if q.get("status"):
                badges += " " + _chip(q["status"], PURPLE)
            fr = []
            if q.get("receives_facets"):
                fr.append("facets: " + ", ".join(q["receives_facets"]))
            if q.get("reports_into"):
                fr.append("→ reports into: " + ", ".join(q["reports_into"]))
            note = q.get("coverage_note") or q.get("evidences") or ""
            rows += (
                f'<tr><td class="nm">{_esc(q.get("short"))}{badges}'
                f'<div class="muted">{_esc(q.get("question"))}</div></td>'
                f"<td>{_chip(cov or '—', COV_COLOR.get(cov, GREY), note)}</td>"
                f"<td>{_axis_skill_pill(g, q.get('home_skill'))}</td>"
                f"<td>{' '.join(_axis_skill_pill(g, c) for c in (q.get('foreign_consumers') or [])) or '<span class=muted>—</span>'}</td>"
                f'<td class="muted">{_esc("; ".join(fr) or "—")}</td>'
                f'<td class="muted">{_esc(", ".join(q.get("conditioned_by") or []) or "—")}</td></tr>'
            )
        return rows

    def band_table(band):
        return (
            '<table class="tbl"><thead><tr><th>axis · question</th><th>coverage</th>'
            "<th>home skill</th><th>foreign consumers</th><th>facets / reports-into</th>"
            f"<th>conditioned by</th></tr></thead><tbody>{band_rows(band)}</tbody></table>"
        )

    conds = ax.get("conditioner_axes") or []
    cond_html = " ".join(_chip(c["id"], TEAL, c.get("note", "")) for c in conds) or "—"
    return (
        f'<p class="muted">Canonical objective→axis→card ontology '
        f"(<code>target_profiling_axes v{_esc(ax.get('version'))}</code>) — the decision questions a full "
        f"target profile must answer, the evidence axis for each, its framework coverage standing, and the "
        f"home / foreign skills that report into it. Click a skill to open it in the Explorer.</p>"
        f'<div class="strip"><b>coverage:</b> {legend}</div>'
        f"<h2>Necessity — “is this real, actionable biology?” (ANY-OF, modality-independent)</h2>{band_table('necessity')}"
        f"<h2>Sufficiency — “will it become a drug in this modality?” (per-lens)</h2>{band_table('sufficiency')}"
        f'<h2>Conditioner axes — refine the questions, but are not themselves questions</h2><div style="margin:6px 0">{cond_html}</div>'
    )


# ---------------------------------------------------------------------------
# COVERAGE — the output layer (what the framework has PRODUCED)
# ---------------------------------------------------------------------------
def _coverage(g):
    """The output registry: governed evidence packages ∪ exploratory skill-runs, as a
    coverage grid, plus the card-firing signal that feeds framework_health."""
    C = g.get("coverage")
    if not C:
        return (
            '<div class="empty">no output registry found — commit <code>catalog.json</code> at '
            "the data-products root (generated by validators/output_registry) to populate this tab</div>"
        )
    s = C.get("summary", {})
    grid = C.get("grid", {})
    fr = C.get("firings", {})
    profiles = C.get("profiles", {})  # cell -> {release_url, s3_prefix, ...}
    lanes = grid.get("lanes", [])
    cells = grid.get("cells", [])
    G = grid.get("grid", {})
    gen = _esc(str(C.get("generated_at", ""))[:19])

    top = _strip(
        [
            ("outputs", s.get("n_entries", 0), PURPLE),
            ("governed", s.get("n_governed", 0), GREEN),
            ("exploratory", s.get("n_exploratory", 0), AMBER),
            ("cells", s.get("n_cells", 0), TEAL),
            ("exploratory-only", s.get("n_cells_exploratory_only", 0), AMBER),
            ("both tiers", s.get("n_cells_both", 0), GREEN),
        ]
    )

    # signal-merge callout — the cards feeding framework_health.fires_in_any_run
    gov = set(fr.get("fired_card_ids_governed") or [])
    anyr = set(fr.get("fired_card_ids_any") or [])
    added = sorted(anyr - gov)
    sig = (
        '<div class="panel"><h3>Liveness signal merge '
        '<span class="sub">— feeds framework_health <code>fires_in_any_run</code></span></h3>'
        f"<p><b>{len(gov)}</b> cards fired in governed packages · <b>{len(anyr)}</b> in ANY real run "
        "(governed ∪ exploratory).</p>"
    )
    if added:
        sig += (
            f'<p class="consumers">+{len(added)} card(s) proven live in exploratory runs only '
            '(invisible to the governed-package signal):</p><ul class="frontier">'
        )
        for c in added:
            n = len(((fr.get("by_card") or {}).get(c) or {}).get("exploratory") or [])
            sig += (
                f'<li>{_chip("◐ exploratory", AMBER)} <b>{_esc(c)}</b> <span class="consumers">— {n} run(s)</span></li>'
            )
        sig += "</ul>"
    sig += "</div>"

    frontier = (
        '<div class="panel"><h3>Promotion backlog <span class="sub">— exploratory → governed</span></h3>'
        f"<p>{s.get('n_cells_exploratory_only', 0)} target×indication cell(s) exist only as "
        "exploratory runs — candidates to promote into governed evidence packages.</p></div>"
    )

    def _lane_hdr(l):
        return "governed (compose)" if l == "governed" else l

    head = "".join(f"<th>{_esc(_lane_hdr(l))}</th>" for l in lanes)
    rows = ""
    for cell in cells:
        tds = ""
        for l in lanes:
            c = (G.get(cell) or {}).get(l)
            if not c:
                tds += '<td><span class="consumers">·</span></td>'
            else:
                col = GREEN if c.get("tier") == "governed" else AMBER
                v = str(c.get("verdict") or "✓")
                tds += f"<td>{_chip(v[:48], col, v)}</td>"
        # link the cell to its published full target-profile when one exists (catalog keys T-I)
        prof = profiles.get(cell.replace("/", "-"))
        url = prof.get("release_url") if isinstance(prof, dict) else None
        cell_cell = f'<a href="{_esc(url)}" title="open full target profile">{_esc(cell)} ▸</a>' if url else _esc(cell)
        rows += f'<tr><td class="nm">{cell_cell}</td>{tds}</tr>'
    table = (
        f'<table class="tbl matrix"><thead><tr><th>target / indication</th>{head}</tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )

    return (
        '<p class="muted">Every standardized output the framework has produced, across both tiers — '
        "<b>governed</b> concurrence-reviewed evidence packages and <b>exploratory</b> skill-runs. "
        f"Derived from the output registry (data-products <code>catalog.json</code>). Snapshot {gen}.</p>"
        + top
        + '<div class="grid2">'
        + sig
        + frontier
        + "</div>"
        + "<h2>Coverage grid — target × indication × output lane</h2>"
        + table
    )


def render_html(graph: dict) -> str:
    s = graph["summary"]
    H = graph.get("health") or {}
    hgen = _esc(str(H.get("generated_at", ""))[:19])
    agen = _esc(str(graph.get("generated_at", ""))[:19])
    shas = " · ".join(f"{k}@{v}" for k, v in (graph.get("root_shas") or {}).items() if v)
    data_json = json.dumps(graph, separators=(",", ":"))
    # reuse render_arch's Miller toolbar+container markup (extract the body between </header> and <div id="miller"> ... )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Framework Dashboard</title>
<style>{MILLER_CSS}{_UNIFIED_CSS}</style></head><body>
<header><h1>Framework Dashboard</h1>
<span class="meta">{s["n_skills"]} skills · {s["n_cards"]} cards · {s["n_datasets"]} datasets · {s["n_resolvers"]} resolvers/{s["n_verdicts"]} verdicts</span>
<div class="orient">One product: <b>Overview</b> → drill into wiring (<b>Explorer</b>), status (<b>Health</b>), <b>Cards</b>, <b>Datasets</b>. Arch generated {agen} · health {hgen} · {shas}</div>
</header>
<div class="utabs">
  <div class="utab active" id="utab-overview" onclick="showTab('overview')">Overview</div>
  <div class="utab" id="utab-axes" onclick="showTab('axes')">Axes</div>
  <div class="utab" id="utab-explorer" onclick="showTab('explorer')">Explorer</div>
  <div class="utab" id="utab-health" onclick="showTab('health')">Health</div>
  <div class="utab" id="utab-cards" onclick="showTab('cards')">Cards</div>
  <div class="utab" id="utab-datasets" onclick="showTab('datasets')">Datasets</div>
  <div class="utab" id="utab-coverage" onclick="showTab('coverage')">Coverage</div>
</div>

<div class="upane active" id="pane-overview"><main>{_overview(graph)}</main></div>
<div class="upane" id="pane-axes"><main><h2>Objective → axis → card ontology — the organizing layer</h2>{_axes(graph)}</main></div>

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

<div class="upane" id="pane-health"><main><h2>Skill health matrix — grouped by risk category, most-actionable first</h2>{_health(graph)}</main></div>
<div class="upane" id="pane-cards"><main><h2>Card inventory — grouped by health</h2>{_cards(graph)}</main></div>
<div class="upane" id="pane-datasets"><main><h2>Dataset inventory — grouped by catalog resolution</h2>{_datasets(graph)}</main></div>
<div class="upane" id="pane-coverage"><main><h2>Output coverage — what the framework has produced</h2>{_coverage(graph)}</main></div>

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
