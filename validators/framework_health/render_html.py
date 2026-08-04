"""render_html.py — framework_health.json -> self-contained HTML dashboard.

Mirrors render-evidence-package/render_markdown.py: a dependency-light pure
renderer that walks the report structure and emits output, adding no new
analysis. Self-contained (inline CSS + tiny vanilla JS, no CDN) so an outsider
can open the file directly; kept well under the VS Code Simple Browser ~4.5MB cap.

Palette anchored to ~/dev/framework-slides/04_coverage_matrix.svg so the
dashboard reads as the same family as the framework deck.
"""

from __future__ import annotations

import html
import json

# Status color ramp (from the coverage-matrix slide palette).
_GREEN, _AMBER, _RED, _GREY, _PURPLE = "#0ca30c", "#fab219", "#c0392b", "#898781", "#6c5aa8"

SKILL_COLORS = {
    "production_ready": _GREEN,
    "partial": _AMBER,
    "placeholder": _GREY,
    "broken_or_drift": _RED,
}
CARD_COLORS = {
    "live": _GREEN,
    "partial": _AMBER,
    "blocked": "#b8860b",
    "placeholder": _GREY,
    "broken": _RED,
}
SEVERITY_COLORS = {"error": _RED, "warn": _AMBER, "info": _PURPLE}


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _chip(text: str, color: str) -> str:
    return f'<span class="chip" style="background:{color}">{_esc(text)}</span>'


def _skill_row(n: dict) -> str:
    v = n["health_verdict"]
    dec_status = n["declared"]["status"] or "—"
    der = n["derived"]
    # Drift arrow if declared vs derived disagree.
    drift_badge = ""
    if n["drift_flags"]:
        worst = max((d["severity"] for d in n["drift_flags"]),
                    key=lambda s: {"error": 3, "warn": 2, "info": 1}.get(s, 0))
        drift_badge = _chip(f"⚠ {len(n['drift_flags'])}", SEVERITY_COLORS.get(worst, _PURPLE))
    n_cards = len(n["cards"])
    n_live = sum(1 for c in n["cards"] if c["card_health"] == "live")
    return (
        f'<tr class="skrow" onclick="tog(this)">'
        f'<td class="nm">{_esc(n["name"])}</td>'
        f'<td>{_esc(n.get("risk_category") or "—")}</td>'
        f'<td>{_chip(v, SKILL_COLORS.get(v, _GREY))}</td>'
        f'<td class="declared">{_esc(dec_status)}</td>'
        f'<td>{_esc(der["kind"])}</td>'
        f'<td>{"✓" if der["resolver_bound"] else "—"}</td>'
        f'<td>{_esc(der.get("test_count", 0))}</td>'
        f'<td>{n_live}/{n_cards}</td>'
        f'<td>{drift_badge}</td>'
        f'</tr>'
    )


def _skill_detail(n: dict) -> str:
    cards_html = ""
    for c in sorted(n["cards"], key=lambda c: c["card_id"]):
        ch = c["card_health"]
        cards_html += (
            f'<tr><td>{_esc(c["card_id"])}</td>'
            f'<td>{_chip(ch, CARD_COLORS.get(ch, _GREY))}</td>'
            f'<td>{"✓" if c["has_live_reader"] else "—"}</td>'
            f'<td>{"✓" if c["fires_in_real_package"] else "—"}</td>'
            f'<td>{_esc(c.get("method_call") or "—")}</td>'
            f'<td class="rsn">{_esc(c["reason_text"])}</td></tr>'
        )
    drift_html = ""
    for d in n["drift_flags"]:
        drift_html += (
            f'<li>{_chip(d["severity"], SEVERITY_COLORS.get(d["severity"], _PURPLE))} '
            f'<b>{_esc(d["code"])}</b> — {_esc(d["detail"])}</li>'
        )
    return (
        f'<tr class="detail" style="display:none"><td colspan="9"><div class="det">'
        f'<p class="why"><b>Verdict:</b> {_chip(n["health_verdict"], SKILL_COLORS.get(n["health_verdict"], _GREY))} '
        f'— {_esc(n["reason_text"])} <span class="rid">({_esc(n["health_reason"])})</span></p>'
        + (f'<p><b>Drift flags:</b></p><ul class="drift">{drift_html}</ul>' if drift_html else "")
        + (f'<table class="cards"><thead><tr><th>card</th><th>health</th><th>live reader</th>'
           f'<th>fires in real pkg</th><th>method</th><th>reason</th></tr></thead>'
           f'<tbody>{cards_html}</tbody></table>' if cards_html else "<p><i>consumes no cards</i></p>")
        + '</div></td></tr>'
    )


def _matrix(report: dict) -> str:
    # Group skills by risk_category (the AZ-5R spine), ungrouped last.
    groups: dict[str, list] = {}
    for n in report["skills"]:
        groups.setdefault(n.get("risk_category") or "ungrouped", []).append(n)
    body = ""
    for cat in sorted(groups, key=lambda c: (c == "ungrouped", c)):
        body += f'<tr class="grp"><td colspan="9">{_esc(cat)}</td></tr>'
        for n in sorted(groups[cat], key=lambda n: n["name"]):
            body += _skill_row(n) + _skill_detail(n)
    return (
        '<table class="matrix"><thead><tr>'
        '<th>skill</th><th>risk category</th><th>DERIVED health</th><th>DECLARED status</th>'
        '<th>kind</th><th>resolver</th><th>tests</th><th>cards live</th><th>drift</th>'
        '</tr></thead><tbody>' + body + '</tbody></table>'
    )


def _alerts(report: dict) -> str:
    errs = [d for d in report["drift_index"] if d["severity"] == "error"]
    warns = [d for d in report["drift_index"] if d["severity"] == "warn"]
    if not errs and not warns:
        return '<div class="banner ok">No error- or warn-severity drift detected.</div>'
    items = ""
    for d in errs + warns:
        items += (f'<li>{_chip(d["severity"], SEVERITY_COLORS[d["severity"]])} '
                  f'<b>{_esc(d["skill"])}</b> · {_esc(d["code"])} — {_esc(d["detail"])}</li>')
    return (f'<div class="banner alert"><h3>⚠ Drift &amp; alerts '
            f'({len(errs)} error, {len(warns)} warn)</h3><ul>{items}</ul></div>')


def _summary_cards(report: dict) -> str:
    s = report["summary"]
    tally = s["verdict_tally"]
    tiles = ""
    for v in ("production_ready", "partial", "placeholder", "broken_or_drift"):
        tiles += (f'<div class="tile" style="border-color:{SKILL_COLORS[v]}">'
                  f'<div class="num">{tally.get(v, 0)}</div><div class="lbl">{_esc(v)}</div></div>')
    tiles += (f'<div class="tile" style="border-color:{_PURPLE}">'
              f'<div class="num">{s["n_error_drift"]}</div><div class="lbl">error drift</div></div>')
    tiles += (f'<div class="tile" style="border-color:{_GREY}">'
              f'<div class="num">{s["n_unregistered_skills"]}</div><div class="lbl">unregistered skills</div></div>')
    return f'<div class="tiles">{tiles}</div>'


def _registry_panel(report: dict) -> str:
    reg = report["registry_drift"]
    unreg = reg["unregistered"]
    if not unreg:
        return '<div class="panel"><h3>Registry vs disk</h3><p>All skills registered.</p></div>'
    lis = "".join(f"<li>{_esc(x)}</li>" for x in unreg)
    return (f'<div class="panel"><h3>Registry vs disk drift</h3>'
            f'<p>{len(unreg)} skill(s) on disk but absent from '
            f'<code>.claude-plugin/marketplace.json</code>:</p><ul class="cols">{lis}</ul></div>')


_CSS = """
:root{--bg:#f7f6f1;--card:#fff;--ink:#0b0b0b;--muted:#52514e;--line:#e1e0d9}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#0b0b0b;color:#fff;padding:20px 28px}
header h1{margin:0;font-size:20px}header .sub{color:#c9c8c1;font-size:13px;margin-top:4px}
main{max-width:1200px;margin:0 auto;padding:20px 28px}
.chip{display:inline-block;padding:2px 8px;border-radius:10px;color:#fff;font-size:11px;font-weight:600;white-space:nowrap}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.tile{background:var(--card);border-left:5px solid;border-radius:6px;padding:12px 16px;min-width:120px;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.tile .num{font-size:26px;font-weight:700}.tile .lbl{color:var(--muted);font-size:12px}
.banner{border-radius:6px;padding:14px 18px;margin:16px 0}
.banner.ok{background:#eaf6ea;border:1px solid #0ca30c}
.banner.alert{background:#fdf3e7;border:1px solid #fab219}
.banner h3{margin:0 0 8px}.banner ul{margin:0;padding-left:18px}
.matrix{width:100%;border-collapse:collapse;background:var(--card);border-radius:6px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.matrix th{background:#52514e;color:#fff;text-align:left;padding:8px 10px;font-size:12px;font-weight:600}
.matrix td{padding:7px 10px;border-top:1px solid var(--line);font-size:13px}
.matrix tr.grp td{background:#e1e0d9;font-weight:700;text-transform:capitalize;font-size:12px}
.skrow{cursor:pointer}.skrow:hover{background:#f2f1ea}.skrow .nm{font-weight:600}
.declared{color:var(--muted)}
.det{padding:6px 4px 12px}.det .why{margin:6px 0}.det .rid{color:var(--muted);font-size:12px}
.det ul.drift{margin:6px 0}.det .cards{width:100%;border-collapse:collapse;margin-top:8px}
.det .cards th{background:#898781;color:#fff;font-size:11px;padding:5px 8px;text-align:left}
.det .cards td{font-size:12px;padding:4px 8px;border-top:1px solid var(--line)}
.det .rsn{color:var(--muted)}
.panel{background:var(--card);border-radius:6px;padding:14px 18px;margin:16px 0;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.panel h3{margin:0 0 8px}ul.cols{columns:3;margin:0;padding-left:18px}
footer{color:var(--muted);font-size:12px;padding:10px 28px 30px;max-width:1200px;margin:0 auto}
code{background:#e1e0d9;padding:1px 5px;border-radius:3px}
"""

_JS = """
function tog(row){var d=row.nextElementSibling;
 if(d&&d.classList.contains('detail')){d.style.display=d.style.display==='none'?'table-row':'none';}}
"""


def render(report: dict) -> str:
    s = report["summary"]
    gen = report.get("generated_at", "")
    subtitle = (f'{s["n_skills"]} skills · {s["n_live_reader_cards"]} live-reader cards · '
                f'{s["n_cards_firing_in_real_packages"]} firing in real packages · generated {_esc(gen)}')
    # A stable hash of the projection is embedded for HTML-staleness detection.
    from .build_framework_health import stable_projection  # local import avoids cycle at module load
    import hashlib
    health_hash = hashlib.sha256(stable_projection(report).encode()).hexdigest()[:16]
    return f"""<!doctype html>
<!-- health-hash: {health_hash} -->
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Framework Health Dashboard</title>
<style>{_CSS}</style></head><body>
<header><h1>Framework Health Dashboard</h1><div class="sub">{subtitle}</div>
<div class="sub">Health is DERIVED from ground truth (files, tests, live readers, real packages) and reconciled against declared status. Click a row to expand.</div></header>
<main>
{_summary_cards(report)}
{_alerts(report)}
<h2>Component matrix</h2>
{_matrix(report)}
{_registry_panel(report)}
<div class="panel"><h3>Legend</h3>
<p><b>Skill health:</b> {' '.join(_chip(k, v) for k, v in SKILL_COLORS.items())}</p>
<p><b>Card health:</b> {' '.join(_chip(k, v) for k, v in CARD_COLORS.items())}</p>
<p><b>broken</b> = a consumed card is registered but its backing method is unbuilt/never fires (silent drift);
<b>blocked</b> = no live reader (honest gap); <b>partial</b> = reader exists but hasn't fired in a real package yet.</p>
</div>
</main>
<footer>Generated by validators/framework_health — a derived artifact. Regenerate; do not hand-edit. Run with --check to guard staleness in CI.</footer>
<script>{_JS}</script>
</body></html>"""
