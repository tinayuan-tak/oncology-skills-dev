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

from .rollup import DRIFT_SEVERITY   # code -> severity, to color the drift-code glossary

# Status color ramp (from the coverage-matrix slide palette).
_GREEN, _AMBER, _RED, _GREY, _PURPLE = "#0ca30c", "#fab219", "#c0392b", "#898781", "#6c5aa8"
_TEAL = "#199e70"   # ready_unproven: works-but-not-yet-fired (distinct from proven green)

SKILL_COLORS = {
    "production_ready": _GREEN,
    "ready_unproven": _TEAL,
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

# What each drift SEVERITY means — surfaced inline + on hover so "info" isn't mistaken
# for a defect. error = breaks the verdict; warn = real gap to fix; info = roadmap/coverage.
SEVERITY_GLOSS = {
    "error": "breaks the skill's verdict — declared status contradicts what's on disk (forces broken_or_drift)",
    "warn": "a real gap to fix, but it does NOT break the verdict",
    "info": "not a defect — a roadmap/coverage signal (something true and worth surfacing; no one did anything wrong)",
}
SEVERITY_LABEL = {"error": "error (breaks verdict)", "warn": "warn (fix, non-breaking)",
                  "info": "info (roadmap, not a defect)"}

# Every drift code → a plain-language sentence (the "full relabel": show a readable label,
# keep the machine code as a secondary breadcrumb). Keeps the UI legible without renaming the
# codes themselves (they are load-bearing in rollup.py + tests).
DRIFT_CODE_LABEL = {
    "status_wired_no_entrypoint": "declared “wired” but has no runnable entrypoint",
    "status_wired_card_broken": "declared “wired” but a card it needs is broken",
    "skillmd_cites_nonexistent_entrypoint": "SKILL.md points at an entrypoint file that doesn’t exist",
    "declared_cards_mismatch_runpy": "SKILL.md’s card list disagrees with what run.py actually loads",
    "fanout_count_mismatch": "composed skill fans out to a different number of sub-skills than declared",
    "missing_status_field": "SKILL.md has no machine-readable status: field",
    "card_registered_never_fires": "card is wired but has never fired in a real evidence package yet",
    "stale_method_label": "card’s method label differs from the method the dispatcher actually imports",
    "dataset_ref_not_in_catalog": "card references a dataset that isn’t registered in the data-catalog",
    "card_consumed_but_no_spec": "a skill pulls this card, but no dashboard_spec does — so it can never fire",
    "modality_relevance_missing": "card routes to a modality-fit gate but declares no modality_relevance (P4)",
    "modality_relevance_drift": "card’s declared modality_relevance is outside its type’s routing set (P4)",
}

# One-line definition of "P4" — the roadmap term used for the modality-routing lens, expanded
# everywhere it appears so a reader needn't know the master-sequencing plan.
P4_GLOSS = ("P4 = the roadmap’s modality-vector layer: each card declares modality_relevance — "
            "which drug modalities (small-molecule, degrader, ADC, TCE, antibody) its evidence "
            "informs — so its signal routes to the right modality-fit gate instead of being "
            "stranded on the biology axis. This lens is metadata PARALLEL to health; it never "
            "changes a card’s health.")

# Plain-language glosses shown on hover (title=) so outsiders needn't learn the vocab.
SKILL_GLOSS = {
    "production_ready": "wired + tested, and ≥1 core card has fired in a real package (proven)",
    "ready_unproven": "wired + tested, readers work, but no core card has fired in a real package yet",
    "partial": "works, but some consumed data hasn't landed / fired yet",
    "placeholder": "question declared, not yet wired to any data",
    "broken_or_drift": "declared status contradicts what's actually on disk",
}
CARD_GLOSS = {
    "live": "fires (passed/warned) in a real evidence package",
    "partial": "has a live reader but hasn't fired in a real package yet",
    "blocked": "no live reader — cannot pull data (honest gap)",
    "placeholder": "declared placeholder / blocked-status card",
    "broken": "no path to data: no reader + no backing method, never fires",
}

# P4 modality-vector lens (routing metadata, PARALLEL to card_health — never affects it).
MODALITY_COLORS = {
    "declared": _GREEN,       # routes to a modality-fit gate AND declares its vector
    "not_required": _GREY,    # biology-axis type, correctly silent
    "missing": _RED,          # routes but declares nothing — stranded (validator ERROR state)
    "drift": _AMBER,          # declares values outside its type's routing set (validator WARNING)
    "not_applicable": _GREY,  # no card yaml on disk
    "unknown": _GREY,         # vocab unavailable (isolated checkout)
}
MODALITY_GLOSS = {
    "declared": "measurement_type routes to a modality-fit gate (SM/degrader/ADC/TCE/antibody) and the card declares modality_relevance",
    "not_required": "biology-axis measurement_type — correctly declares no modality_relevance",
    "missing": "routes to a modality-fit gate but declares NO modality_relevance — stranded on the biology axis (P4)",
    "drift": "declares modality_relevance values outside its measurement_type's routing set",
    "not_applicable": "no .card.yaml on disk — routing not applicable",
    "unknown": "measurement_types vocab unavailable — no P4 verdict asserted",
}


# STATIC access-cost lens colors/labels/gloss (a metadata-derived proxy — NOT a live read).
ACCESS_COST_COLORS = {
    "high": _RED, "moderate": _AMBER, "low": _GREEN,
    "high_unused": _GREY, "moderate_unused": _GREY, "unknown": _GREY,
}
ACCESS_COST_LABEL = {
    "high": "high", "moderate": "moderate", "low": "low",
    "high_unused": "high (unused)", "moderate_unused": "moderate (unused)", "unknown": "size unknown",
}
ACCESS_COST_GLOSS = {
    "high": "large (≥20GB, or ≥2GB across many files) AND consumed by a card — an access-optimization payoff",
    "moderate": "moderately sized (≥2GB or many files) and consumed",
    "low": "small — cheap to access",
    "high_unused": "large but consumed by no card — not a framework access concern",
    "moderate_unused": "moderately sized but consumed by no card",
    "unknown": "manifest declares no total_size_bytes — cost can't be estimated statically",
}


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _chip(text: str, color: str, gloss: str | None = None) -> str:
    t = f' title="{_esc(gloss)}"' if gloss else ""
    return f'<span class="chip" style="background:{color}"{t}>{_esc(text)}</span>'


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
        f'<td>{_chip(v, SKILL_COLORS.get(v, _GREY), SKILL_GLOSS.get(v))}</td>'
        f'<td class="declared">{_esc(dec_status)}</td>'
        f'<td>{_esc(der["kind"])}</td>'
        f'<td>{"✓" if der["resolver_bound"] else "—"}</td>'
        f'<td>{_esc(der.get("test_count", 0))}</td>'
        f'<td>{n_live}/{n_cards}</td>'
        f'<td>{drift_badge}</td>'
        f'</tr>'
    )


def _skill_detail(n: dict) -> str:
    def _datasets_cell(c: dict) -> str:
        ds = c.get("datasets") or []
        if not ds:
            return "<span class='consumers'>—</span>"
        bits = []
        for d in ds:
            ok = d.get("in_catalog")
            mark = "✓" if ok else "✗"
            col = _GREEN if ok else _RED
            tip = ("in catalog" if d.get("matched_by") == "exact"
                   else f"resolved by prefix → {d.get('resolved_id')}" if d.get("matched_by") == "prefix"
                   else "NOT in data-catalog")
            bits.append(f"<span style='color:{col}' title='{_esc(tip)}'>{mark}</span> {_esc(d['product_id'])}")
        return "<br>".join(bits)

    cards_html = ""
    for c in sorted(n["cards"], key=lambda c: c["card_id"]):
        ch = c["card_health"]
        cards_html += (
            f'<tr><td>{_esc(c["card_id"])}</td>'
            f'<td>{_chip(ch, CARD_COLORS.get(ch, _GREY), CARD_GLOSS.get(ch))}</td>'
            f'<td>{"✓" if c["has_live_reader"] else "—"}</td>'
            f'<td>{"✓" if c["fires_in_real_package"] else "—"}</td>'
            f'<td>{_esc(c.get("measurement_type") or "—")}</td>'
            f'<td>{_esc((c.get("dispatch_module") or c.get("method_call") or "—").split(".")[0])}</td>'
            f'<td class="dscell">{_datasets_cell(c)}</td></tr>'
        )
    drift_html = ""
    for d in n["drift_flags"]:
        drift_html += (
            f'<li>{_chip(d["severity"], SEVERITY_COLORS.get(d["severity"], _PURPLE))} '
            f'<b>{_esc(d["code"])}</b> — {_esc(d["detail"])}</li>'
        )
    return (
        f'<tr class="detail" style="display:none"><td colspan="9"><div class="det">'
        f'<p class="why"><b>Verdict:</b> {_chip(n["health_verdict"], SKILL_COLORS.get(n["health_verdict"], _GREY), SKILL_GLOSS.get(n["health_verdict"]))} '
        f'— {_esc(n["reason_text"])} <span class="rid">({_esc(n["health_reason"])})</span></p>'
        + (f'<p><b>Drift flags:</b></p><ul class="drift">{drift_html}</ul>' if drift_html else "")
        + (f'<p class="why"><b>Cards → method → datasets</b> (the full dependency chain this skill pulls):</p>'
           f'<table class="cards"><thead><tr><th>card</th><th>health</th><th>live reader</th>'
           f'<th>fires in real pkg</th><th>measurement_type</th><th>method</th><th>datasets (product_id · ✓ in catalog)</th></tr></thead>'
           f'<tbody>{cards_html}</tbody></table>' if cards_html else "<p><i>consumes no cards</i></p>")
        + '</div></td></tr>'
    )


# Skill-verdict actionability rank — higher sorts first (what to fix next).
_VERDICT_RANK = {"broken_or_drift": 4, "partial": 3, "ready_unproven": 2,
                 "placeholder": 1, "production_ready": 0}


def _skill_actionability(n: dict) -> tuple:
    """Sort key (descending): worst-drift severity, then verdict rank, then name.
    Floats drifting/broken skills to the top of their risk group — the fix-next order."""
    worst = max((_SEV_RANK.get(d["severity"], 0) for d in n.get("drift_flags", [])), default=0)
    return (-worst, -_VERDICT_RANK.get(n["health_verdict"], 0), n["name"])


def _matrix(report: dict) -> str:
    # Group skills by risk_category (the AZ-5R spine), ungrouped last. WITHIN each
    # group, order by actionability (most-drifting / least-ready first) so the top of
    # every group is the next thing to fix — not alphabetical.
    groups: dict[str, list] = {}
    for n in report["skills"]:
        groups.setdefault(n.get("risk_category") or "ungrouped", []).append(n)
    body = ""
    for cat in sorted(groups, key=lambda c: (c == "ungrouped", c)):
        body += f'<tr class="grp"><td colspan="9">{_esc(cat)}</td></tr>'
        for n in sorted(groups[cat], key=_skill_actionability):
            body += _skill_row(n) + _skill_detail(n)
    return (
        '<table class="matrix"><thead><tr>'
        '<th>skill</th><th>risk category</th><th>DERIVED health</th><th>DECLARED status</th>'
        '<th>kind</th><th>resolver</th><th>tests</th><th>cards live</th><th>drift</th>'
        '</tr></thead><tbody>' + body + '</tbody></table>'
    )


def _severity_key() -> str:
    """Inline, always-visible legend defining the three drift severities — so 'info'
    is never mistaken for a defect. Rendered as a caption line under section headers."""
    bits = " · ".join(
        f'{_chip(sev, SEVERITY_COLORS[sev], SEVERITY_GLOSS[sev])} {_esc(SEVERITY_GLOSS[sev])}'
        for sev in ("error", "warn", "info")
    )
    return f'<div class="sevkey">{bits}</div>'


def _drift_li(d: dict) -> str:
    """One drift line: readable label first, machine code as a secondary breadcrumb,
    severity chip carrying its plain-language meaning on hover."""
    sev = d["severity"]
    label = DRIFT_CODE_LABEL.get(d["code"], d["code"])
    return (f'<li>{_chip(SEVERITY_LABEL.get(sev, sev), SEVERITY_COLORS.get(sev, _PURPLE), SEVERITY_GLOSS.get(sev))} '
            f'<b>{_esc(d["skill"])}</b> — {_esc(label)} '
            f'<code class="driftcode">{_esc(d["code"])}</code><br>'
            f'<span class="driftdetail">{_esc(d["detail"])}</span></li>')


def _drift_code_glossary() -> str:
    """Every drift code → readable label + its severity chip + the machine code, sorted
    error→warn→info so the reader sees breaking codes first. Feeds the always-visible glossary."""
    rows = sorted(DRIFT_CODE_LABEL.items(),
                  key=lambda kv: (-_SEV_RANK.get(DRIFT_SEVERITY.get(kv[0], "info"), 0), kv[0]))
    out = ""
    for code, label in rows:
        sev = DRIFT_SEVERITY.get(code, "info")
        out += (f'<li>{_chip(sev, SEVERITY_COLORS.get(sev, _PURPLE), SEVERITY_GLOSS.get(sev))} '
                f'<b>{_esc(label)}</b> <code class="driftcode">{_esc(code)}</code></li>')
    return out


def _alerts(report: dict) -> str:
    errs = [d for d in report["drift_index"] if d["severity"] == "error"]
    warns = [d for d in report["drift_index"] if d["severity"] == "warn"]
    if not errs and not warns:
        return ('<div class="banner ok">No error- or warn-severity drift detected. '
                '(info-level items are roadmap/coverage signals, not defects — see the Cards tab.)</div>')

    # Errors are actionable → always visible. Warns fold into a <details> (native,
    # no JS), with a per-code breakdown in the summary so the gist reads collapsed.
    err_html = f'<ul>{"".join(_drift_li(d) for d in errs)}</ul>' if errs else ""
    warns_block = ""
    if warns:
        by_code: dict[str, int] = {}
        for d in warns:
            by_code[d["code"]] = by_code.get(d["code"], 0) + 1
        breakdown = " · ".join(f"{n} × {DRIFT_CODE_LABEL.get(code, code)}"
                               for code, n in sorted(by_code.items()))
        warns_block = (
            f'<details class="warns"><summary>{len(warns)} warnings '
            f'<span class="brk">({breakdown})</span></summary>'
            f'<ul>{"".join(_drift_li(d) for d in warns)}</ul></details>'
        )
    return (f'<div class="banner alert"><h3>⚠ Drift &amp; alerts '
            f'({len(errs)} error, {len(warns)} warn) '
            f'<span class="hdrnote">— severity ≠ badness; see key below</span></h3>'
            f'{_severity_key()}{err_html}{warns_block}</div>')


_SEV_RANK = {"error": 3, "warn": 2, "info": 1}

# Fix-next punch list: map each actionable drift code to an imperative "what to do".
# Info-severity codes (roadmap/coverage signals, not defects) are intentionally omitted
# — the punch list is the ACTIONABLE queue, not the full drift index.
_PUNCH_ACTION = {
    "status_wired_no_entrypoint": "add scripts/run.py (declared wired, no entrypoint)",
    "status_wired_card_broken": "fix/replace the broken card, or correct the declared status",
    "skillmd_cites_nonexistent_entrypoint": "fix the SKILL.md entrypoint reference",
    "dataset_ref_not_in_catalog": "catalog the dataset, or fix the product_id the card names",
    "declared_cards_mismatch_runpy": "reconcile SKILL.md cards_used with run.py CARDS",
    "missing_status_field": "add a machine-readable status: to SKILL.md frontmatter",
    "modality_relevance_missing": "declare modality_relevance on the routing card (P4)",
    "modality_relevance_drift": "fix modality_relevance values to the type's routing set (P4)",
}


def _fix_next(report: dict) -> str:
    """Actionable punch list: the drift index collapsed by code, error→warn only (info
    codes are roadmap/coverage, not defects), each with an imperative action + the
    specific component ids to act on. A pure derivation of drift_index — no new state."""
    di = report.get("drift_index", [])
    actionable = [d for d in di if d["severity"] in ("error", "warn")]
    if not actionable:
        return ('<div class="panel"><h3>✓ Fix-next</h3>'
                '<p>No error- or warn-severity items. Nothing actionable is outstanding.</p></div>')
    by_code: dict[str, list] = {}
    for d in actionable:
        by_code.setdefault(d["code"], []).append(d)
    ordered = sorted(by_code.items(),
                     key=lambda kv: (-_SEV_RANK.get(kv[1][0]["severity"], 0), -len(kv[1]), kv[0]))
    rows = ""
    for code, items in ordered:
        sev = items[0]["severity"]
        action = _PUNCH_ACTION.get(code, "review — see drift detail")
        # collect the distinct component ids this code implicates (skills + any card
        # ids named in the detail are already in the detail; show the skills here).
        skills = sorted({d["skill"] for d in items if d.get("skill")})
        who = ", ".join(skills[:6]) + (f" +{len(skills)-6} more" if len(skills) > 6 else "")
        rows += (
            f'<tr><td>{_chip(str(len(items)), SEVERITY_COLORS.get(sev, _PURPLE))}</td>'
            f'<td><b>{_esc(action)}</b><div class="pcode">{_esc(code)}</div></td>'
            f'<td class="consumers">{_esc(who) or "—"}</td></tr>'
        )
    return (
        '<div class="panel"><h3>Fix-next — the actionable queue (error + warn, most-impactful first)</h3>'
        '<table class="punch"><thead><tr><th>n</th><th>action · code</th><th>affected skills</th>'
        '</tr></thead><tbody>' + rows + '</tbody></table></div>'
    )


def _delta_ribbon(report: dict) -> str:
    """A one-line 'what changed since the last committed artifact' ribbon. Reads the
    volatile `delta` envelope field (None on first-ever run or when unchanged)."""
    d = report.get("delta")
    if not d or not d.get("has_prior"):
        return ""

    def _mv(n: int, noun: str) -> str | None:
        if n == 0:
            return None
        arrow = "▲" if n > 0 else "▼"
        col = _GREEN if n > 0 else _RED
        return f'<span style="color:{col}">{arrow} {abs(n)} {noun}</span>'

    bits = [x for x in (
        _mv(d.get("n_skills", 0), "skills"),
        _mv(d.get("n_cards", 0), "cards"),
        _mv(d.get("n_drift_flags", 0), "drift flags"),
        _mv(d.get("n_error_drift", 0), "error drift"),
    ) if x]
    named = []
    if d.get("skills_added"):
        named.append(f'+skills: {_esc(", ".join(d["skills_added"]))}')
    if d.get("skills_removed"):
        named.append(f'−skills: {_esc(", ".join(d["skills_removed"]))}')
    if d.get("cards_added"):
        ca = d["cards_added"]
        named.append(f'+{len(ca)} card' + ("s" if len(ca) != 1 else "")
                     + f': {_esc(", ".join(ca[:8]))}' + (" …" if len(ca) > 8 else ""))
    when = _esc((d.get("prior_generated_at") or "")[:10])
    body = " · ".join(bits) if bits else "no count changes"
    named_html = ("<div class='dnamed'>" + " · ".join(named) + "</div>") if named else ""
    return (f'<div class="delta"><b>Since last run</b> ({when}): {body}{named_html}</div>')


def _summary_cards(report: dict) -> str:
    s = report["summary"]
    t = s["verdict_tally"]
    return _stat_strip([
        ("ready", t.get("production_ready", 0), _GREEN),
        ("ready (unproven)", t.get("ready_unproven", 0), _TEAL),
        ("partial", t.get("partial", 0), _AMBER),
        ("placeholder", t.get("placeholder", 0), _GREY),
        ("drift", t.get("broken_or_drift", 0), _RED),
        ("error drift", s["n_error_drift"], _PURPLE),
        ("unregistered", s["n_unregistered_skills"], _GREY),
    ])


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
:root{--bg:#f7f6f1;--card:#fff;--ink:#0b0b0b;--muted:#52514e;--line:#e1e0d9;--zebra:#faf9f5}
*{box-sizing:border-box}
body{margin:0;font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#0b0b0b;color:#fff;padding:12px 24px}
header h1{margin:0;font-size:16px;display:inline}
header .meta{color:#898781;font-size:11px;margin-left:10px}
header .headline{color:#fff;font-size:13px;margin-top:5px}
header .orient{color:#9b9a93;font-size:11px;margin-top:3px}
main{max-width:1180px;margin:0 auto;padding:14px 24px}
h2{font-size:14px;margin:14px 0 8px}
.chip{display:inline-block;padding:1px 7px;border-radius:9px;color:#fff;font-size:10.5px;font-weight:600;white-space:nowrap}
/* compact inline stat strip replaces the big tile row */
.strip{display:flex;flex-wrap:wrap;gap:16px;align-items:center;background:var(--card);
 border:1px solid var(--line);border-radius:6px;padding:7px 14px;margin:10px 0;font-size:13px}
.strip .stat{display:inline-flex;align-items:center;gap:5px;color:var(--muted)}
.strip .stat b{color:var(--ink);font-size:14px}
.strip .dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.banner{border-radius:6px;padding:9px 14px;margin:10px 0;font-size:12px}
.banner.ok{background:#eaf6ea;border:1px solid #0ca30c}
.banner.alert{background:#fdf3e7;border:1px solid #fab219}
.banner h3{margin:0 0 5px;font-size:13px}.banner ul{margin:0;padding-left:16px}
.banner li{margin:1px 0}
details.warns{margin-top:4px}
details.warns>summary{cursor:pointer;font-weight:600;color:#7a5b12;list-style:none;user-select:none}
details.warns>summary::-webkit-details-marker{display:none}
details.warns[open]>summary{margin-bottom:4px}
details.warns .brk{font-weight:400;color:#a08a5a;font-size:11px}
details.warns>summary::before{content:"▸ ";color:#a08a5a}
details.warns[open]>summary::before{content:"▾ "}
/* NOTE: no overflow:hidden here — it clipped expanded drill-down content (the
   nested cards table) that grows a detail row past the table's box. Round the
   header-row corners instead so we keep the look without clipping descendants. */
.matrix{width:100%;border-collapse:collapse;background:var(--card);border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.matrix thead th:first-child{border-top-left-radius:6px}
.matrix thead th:last-child{border-top-right-radius:6px}
.matrix th{background:#52514e;color:#fff;text-align:left;padding:5px 9px;font-size:11px;font-weight:600;position:sticky;top:0}
.matrix td{padding:3px 9px;border-top:1px solid var(--line);font-size:12px}
.matrix tbody tr:nth-child(even of :not(.detail)){background:var(--zebra)}
.matrix tr.grp td{background:#e1e0d9;font-weight:700;text-transform:capitalize;font-size:11px;padding:3px 9px}
.skrow{cursor:pointer}.skrow:hover{background:#eef0f5}.skrow .nm{font-weight:600}
.skrow td:first-child::before{content:"▸ ";color:#b0afa8}
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
.tabs{display:flex;gap:3px;margin:12px 0 0;border-bottom:2px solid var(--line);
 position:sticky;top:0;background:var(--bg);z-index:5;padding-top:2px}
.tab{padding:6px 15px;cursor:pointer;font-weight:600;font-size:13px;color:var(--muted);
 border:2px solid transparent;border-bottom:none;border-radius:5px 5px 0 0}
.tab.active{background:var(--card);color:var(--ink);border-color:var(--line);
 box-shadow:0 -1px 2px rgba(0,0,0,.04);margin-bottom:-2px}
.tabpane{display:none}.tabpane.active{display:block}
.orphan td{background:#faf3f3}
.consumers{color:var(--muted);font-size:11px}
.delta{background:#eef0f5;border:1px solid var(--line);border-left:3px solid #6c5aa8;
 border-radius:5px;padding:6px 12px;margin:10px 0;font-size:12px}
.delta .dnamed{color:var(--muted);font-size:11px;margin-top:3px}
table.punch{width:100%;border-collapse:collapse;margin-top:4px}
table.punch th{background:#898781;color:#fff;font-size:11px;text-align:left;padding:4px 8px}
table.punch td{border-top:1px solid var(--line);padding:5px 8px;font-size:12px;vertical-align:top}
table.punch td:first-child{width:36px;text-align:center}
.pcode{color:var(--muted);font-size:10.5px;font-family:ui-monospace,Menlo,monospace;margin-top:2px}
/* self-documenting glosses (severity key, inline captions, drift-code breadcrumbs) */
.sevkey{font-size:11px;color:var(--muted);margin:4px 0 8px;line-height:1.9}
.captn{font-size:11px;color:var(--muted);margin:6px 2px 2px;line-height:1.5}
.hdrnote{font-weight:400;color:#a08a5a;font-size:11px}
.driftcode{background:#eceae2;color:#6b6a64;padding:0 4px;border-radius:3px;font-size:10px;
 font-family:ui-monospace,Menlo,monospace}
.driftdetail{color:var(--muted);font-size:11px}
ul.glosslist{margin:4px 0;padding-left:16px}ul.glosslist li{margin:3px 0;font-size:12px}
"""

_JS = """
function tog(row){var d=row.nextElementSibling;
 if(d&&d.classList.contains('detail')){d.style.display=d.style.display==='none'?'table-row':'none';}}
function tab(id){
 document.querySelectorAll('.tabpane').forEach(function(p){p.classList.remove('active')});
 document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active')});
 document.getElementById('pane-'+id).classList.add('active');
 document.getElementById('tab-'+id).classList.add('active');
}
// Graph: hover a node -> highlight its incident edges, dim the rest.
document.addEventListener('DOMContentLoaded',function(){
 var svg=document.getElementById('fh-graph'); if(!svg)return;
 var edges=svg.querySelectorAll('.fh-edge');
 svg.querySelectorAll('.fh-node').forEach(function(node){
  node.addEventListener('mouseenter',function(){
   var id=node.getAttribute('data-id');
   edges.forEach(function(e){
    var on=(e.getAttribute('data-s')===id||e.getAttribute('data-d')===id);
    e.style.stroke=on?'#6c5aa8':'#c9c8c1';
    e.style.strokeWidth=on?'1.6':'0.7';
    e.style.opacity=on?'0.95':'0.12';
   });
  });
  node.addEventListener('mouseleave',function(){
   edges.forEach(function(e){e.style.stroke='#c9c8c1';e.style.strokeWidth='0.7';e.style.opacity='0.55';});
  });
 });
});
"""


def _cards_table(report: dict) -> str:
    """Card-centric inventory: every card once, deduped, grouped by health, with
    consuming skills + orphan flag + method backing."""
    cards = report.get("cards", [])
    # Group by card_health; order worst→best so problems surface at the top,
    # but float orphans (any health) into their own leading group.
    health_order = ["broken", "placeholder", "blocked", "partial", "live"]
    orphans = [c for c in cards if c.get("is_orphan")]
    groups: dict[str, list] = {}
    for c in cards:
        if c.get("is_orphan"):
            continue
        groups.setdefault(c["card_health"], []).append(c)

    def _row(c: dict, orphan: bool = False) -> str:
        ch = c["card_health"]
        consumers = c.get("consumers") or []
        cons_txt = ("<span class='consumers'>— orphan: no skill consumes</span>"
                    if not consumers else
                    f"<span class='consumers'>{_esc(', '.join(consumers))}</span>")
        method = c.get("dispatch_module") or c.get("method_call") or "—"
        cls = " class='orphan'" if orphan else ""
        # spec-coverage cell: which dashboard_spec(s) list it, or a red "no spec" flag
        # for a consumed card that no spec pulls (can never fire in a package).
        if c.get("consumed_but_no_spec"):
            spec_cell = _chip("no spec", _RED, "consumed by a skill but in no dashboard_spec — can't fire in a package")
        elif c.get("in_dashboard_spec"):
            spec_cell = f"<span class='consumers'>{_esc(', '.join(c.get('dashboard_specs') or []))}</span>"
        else:
            spec_cell = "<span class='consumers'>—</span>"
        # P4 modality-routing cell (parallel to health; declared modalities shown on the chip
        # when present so the routing vector is legible at a glance).
        mroute = c.get("modality_routing", "unknown")
        mr_vals = c.get("modality_relevance") or []
        mr_label = mroute if not mr_vals else f"{mroute}: {', '.join(mr_vals)}"
        p4_cell = _chip(mr_label, MODALITY_COLORS.get(mroute, _GREY), MODALITY_GLOSS.get(mroute))
        return (
            f"<tr{cls}><td class='nm'>{_esc(c['card_id'])}</td>"
            f"<td>{_chip(ch, CARD_COLORS.get(ch, _GREY), CARD_GLOSS.get(ch))}</td>"
            f"<td>{'✓' if c.get('has_live_reader') else '—'}</td>"
            f"<td>{'✓' if c.get('fires_in_real_package') else '—'}</td>"
            f"<td>{spec_cell}</td>"
            f"<td>{_esc(c.get('measurement_type') or '—')}</td>"
            f"<td>{p4_cell}</td>"
            f"<td>{_esc(method)}</td>"
            f"<td>{len(consumers)} {cons_txt}</td></tr>"
        )

    body = ""
    if orphans:
        body += (f"<tr class='grp'><td colspan='9'>⚠ ORPHAN CARDS — defined on disk, "
                 f"consumed by no skill ({len(orphans)}) — the pull-model's unclaimed-measurement signal</td></tr>")
        for c in sorted(orphans, key=lambda c: c["card_id"]):
            body += _row(c, orphan=True)
    for h in health_order:
        if h not in groups:
            continue
        body += f"<tr class='grp'><td colspan='9'>{h} ({len(groups[h])})</td></tr>"
        for c in sorted(groups[h], key=lambda c: c["card_id"]):
            body += _row(c)

    return (
        "<table class='matrix'><thead><tr>"
        "<th>card</th><th>health</th><th>live reader</th><th>fires in real pkg</th>"
        f"<th>in spec</th><th>measurement_type</th><th title='{_esc(P4_GLOSS)}'>modality routing "
        f"<span class='hdrnote'>(P4)</span></th><th>method (dispatcher)</th><th>consumed by</th>"
        "</tr></thead><tbody>" + body + "</tbody></table>"
    )


def _fmt_bytes(n) -> str:
    if not n:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.0f} PB"


def _datasets_table(report: dict) -> str:
    """Dataset-centric inventory: every data product (catalog ∪ card-referenced),
    joined to consuming cards. Framework-consumed datasets first (the relevant set),
    then broken refs, then the wider catalog (collapsed by default via grouping)."""
    ds = report.get("datasets", [])
    consumed = [d for d in ds if d["n_consumers"] > 0 and not d["is_broken_ref"]]
    broken = [d for d in ds if d["is_broken_ref"]]
    catalog_only = [d for d in ds if d["n_consumers"] == 0 and d["in_catalog"]]

    def _row(d: dict) -> str:
        badge = (_chip("in catalog", _GREEN) if d["in_catalog"] else _chip("NOT in catalog", _RED))
        kind = d.get("kind") or "—"
        cons = d.get("consumed_by_cards") or []
        cons_txt = (f"<span class='consumers'>{_esc(', '.join(cons))}</span>" if cons
                    else "<span class='consumers'>— used by no card</span>")
        # STATIC access-cost cell: cost band chip + a sort-key indicator (✓ optimized /
        # ⚠ none = expensive to query when consumed). Neither is a live measurement.
        ac = d.get("access_cost")
        cost_cell = _chip(ACCESS_COST_LABEL.get(ac, ac or "—"),
                          ACCESS_COST_COLORS.get(ac, _GREY), ACCESS_COST_GLOSS.get(ac)) if ac else "—"
        hsk = d.get("has_sort_key")
        if d.get("missing_sort_key"):
            sk = "<span style='color:%s' title='consumed + large + no sort/partition key → expensive to query'>⚠ no sort-key</span>" % _RED
        elif hsk is True:
            sk = "<span style='color:%s' title='declares a query_optimization sort/partition key'>✓</span>" % _GREEN
        else:
            sk = "<span class='consumers'>—</span>"
        return (
            f"<tr><td class='nm'>{_esc(d['product_id'])}</td>"
            f"<td>{badge}</td><td>{_esc(kind)}</td>"
            f"<td>{_esc(_fmt_bytes(d.get('size_bytes')))}</td>"
            f"<td>{cost_cell}</td><td>{sk}</td>"
            f"<td>{d.get('n_consumers', 0)} {cons_txt}</td></tr>"
        )

    ncol = 7
    body = ""
    if broken:
        body += (f"<tr class='grp'><td colspan='{ncol}'>⚠ REFERENCED BUT NOT IN CATALOG — a card names a "
                 f"product_id with no manifest ({len(broken)}): not-yet-landed data, or a resource "
                 f"tracked outside manifests/ (resolver-releases, subgroup-catalogs)</td></tr>")
        for d in sorted(broken, key=lambda d: d["product_id"]):
            body += _row(d)
    # Consumed datasets sorted by access cost (heaviest first) — the actionable order.
    body += f"<tr class='grp'><td colspan='{ncol}'>CONSUMED BY CARDS — the framework's active data footprint ({len(consumed)}); heaviest-to-access first</td></tr>"
    for d in sorted(consumed, key=lambda d: (-(d.get("size_bytes") or 0), d["product_id"])):
        body += _row(d)
    body += (f"<tr class='grp'><td colspan='{ncol}'>CATALOG AT LARGE — cataloged, not consumed by any card "
             f"({len(catalog_only)}); org-wide inventory, not a framework gap</td></tr>")
    for d in sorted(catalog_only, key=lambda d: d["product_id"]):
        body += _row(d)

    return (
        "<table class='matrix'><thead><tr>"
        "<th>dataset (product_id)</th><th>catalog</th><th>kind</th>"
        "<th>size</th><th>access cost</th><th>sort-key</th><th>consumed by cards</th>"
        "</tr></thead><tbody>" + body + "</tbody></table>"
    )


def _dataset_summary_cards(report: dict) -> str:
    s = report["summary"]
    strip = _stat_strip([
        ("in catalog", s.get("n_datasets_in_catalog", 0), _GREEN),
        ("consumed by cards", sum(1 for d in report.get("datasets", []) if d["n_consumers"] > 0 and d["in_catalog"]), _PURPLE),
        ("broken refs", s.get("n_broken_dataset_refs", 0), _RED),
        ("catalog, unused", s.get("n_orphan_datasets", 0), _GREY),
        ("high access-cost", s.get("n_datasets_high_access_cost", 0), _RED),
        ("consumed, no sort-key", s.get("n_datasets_missing_sort_key", 0), _AMBER),
    ])
    caption = ('<div class="captn"><b>Access cost</b> is a STATIC proxy from manifest metadata '
               '(size × file-count × consumers) — <i>not</i> a measured read latency. '
               '“no sort-key” flags a large, consumed dataset whose manifest declares no '
               'query_optimization key (the ~4× sorted-read/pushdown lever). Real timing would need '
               'runtime instrumentation — deliberately out of this offline probe.</div>')
    return strip + caption


def _card_summary_cards(report: dict) -> str:
    s = report["summary"]
    t = s.get("card_health_tally", {})
    return _stat_strip(
        [(h, t.get(h, 0), CARD_COLORS[h]) for h in ("live", "partial", "blocked", "placeholder", "broken")]
        + [("orphan cards", s.get("n_orphan_cards", 0), _RED),
           ("consumed, no spec", s.get("n_cards_consumed_but_no_spec", 0), _RED)]
    )


def _p4_summary_cards(report: dict) -> str:
    """P4 modality-vector adoption strip (routing metadata, parallel to card health).

    'declared / required' is the headline coverage ratio: of the cards whose measurement_type
    routes to a modality-fit gate, how many declare their modality_relevance vector. missing/drift
    are the non-compliant states (also enforced at commit time by validate_cards.py)."""
    s = report["summary"]
    req = s.get("n_p4_required_cards", 0)
    dec = s.get("n_p4_declared_cards", 0)
    mt = s.get("modality_routing_tally", {})
    coverage = f"{dec}/{req} declared" if req else "0/0"
    strip = _stat_strip([
        (f"modality routing · {coverage}", mt.get("declared", 0), _GREEN),
        ("missing (stranded)", s.get("n_p4_missing_cards", 0), _RED),
        ("drift", s.get("n_p4_drift_cards", 0), _AMBER),
        ("not required (biology-axis)", mt.get("not_required", 0), _GREY),
    ])
    caption = (f'<div class="captn"><b>Modality routing (roadmap “P4”)</b> — {_esc(P4_GLOSS)}</div>')
    return strip + caption


# Any node health value -> a color (skills + cards share the ramp; resolver/method
# use live/broken).
_NODE_COLOR = {**SKILL_COLORS, **CARD_COLORS, "live": _GREEN, "broken": _RED, None: _GREY}


def _graph_svg(report: dict) -> str:
    """Option-A layered flow: Skills | Resolvers | Cards | Methods, left→right,
    hand-rolled inline SVG (no CDN, deterministic). Nodes colored by health;
    orphan cards ringed. Edges drawn as faint cubic curves; hovering a node
    highlights its incident edges (vanilla JS, no lib)."""
    g = report.get("graph")
    if not g or not g["nodes"]:
        return "<p><i>no graph data</i></p>"

    layers = ["skill", "resolver", "card", "method"]
    titles = {"skill": "Skills", "resolver": "Resolvers", "card": "Cards", "method": "Methods"}
    by_layer = {ly: [n for n in g["nodes"] if n["layer"] == ly] for ly in layers}

    # Geometry
    col_x = {"skill": 90, "resolver": 340, "card": 620, "method": 900}
    node_w, node_h, v_gap, top = 150, 20, 6, 70
    max_rows = max(len(v) for v in by_layer.values())
    height = top + max_rows * (node_h + v_gap) + 30
    width = 1060

    # Assign each node a y (center) by its order within the column.
    pos: dict[str, tuple[float, float]] = {}
    for ly in layers:
        for i, n in enumerate(by_layer[ly]):
            y = top + i * (node_h + v_gap) + node_h / 2
            pos[n["id"]] = (col_x[ly], y)

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
             f'style="max-width:{width}px" font-family="inherit" id="fh-graph">']

    # Column headers.
    for ly in layers:
        parts.append(f'<text x="{col_x[ly] + node_w/2}" y="40" text-anchor="middle" '
                     f'font-size="13" font-weight="700" fill="#0b0b0b">{titles[ly]} '
                     f'<tspan fill="#898781" font-weight="400">({len(by_layer[ly])})</tspan></text>')

    # Edges first (under nodes). Cubic curve from right edge of src to left edge of dst.
    for e in g["edges"]:
        if e["src"] not in pos or e["dst"] not in pos:
            continue
        x1, y1 = pos[e["src"]]; x2, y2 = pos[e["dst"]]
        x1 += node_w  # exit right side of source box
        mx = (x1 + x2) / 2
        parts.append(
            f'<path d="M{x1:.0f},{y1:.0f} C{mx:.0f},{y1:.0f} {mx:.0f},{y2:.0f} {x2:.0f},{y2:.0f}" '
            f'fill="none" stroke="#c9c8c1" stroke-width="0.7" opacity="0.55" '
            f'data-s="{_esc(e["src"])}" data-d="{_esc(e["dst"])}" class="fh-edge"/>')

    # Nodes.
    for n in g["nodes"]:
        x, yc = pos[n["id"]]
        y = yc - node_h / 2
        col = _NODE_COLOR.get(n.get("health"), _GREY)
        ring = ' stroke="#c0392b" stroke-width="2" stroke-dasharray="3,2"' if n.get("is_orphan") else ' stroke="#00000022" stroke-width="0.5"'
        label = n["label"]
        disp = label if len(label) <= 22 else label[:21] + "…"
        parts.append(
            f'<g class="fh-node" data-id="{_esc(n["id"])}">'
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{node_w}" height="{node_h}" rx="4" '
            f'fill="{col}"{ring}><title>{_esc(label)} · {_esc(n.get("health") or "—")}'
            f'{" · ORPHAN" if n.get("is_orphan") else ""}</title></rect>'
            f'<text x="{x+6:.0f}" y="{yc+3.5:.0f}" font-size="9.5" fill="#fff" '
            f'style="pointer-events:none">{_esc(disp)}</text></g>')

    parts.append("</svg>")
    return "".join(parts)


def _graph_legend() -> str:
    return (
        '<div class="panel"><h3>Reading the graph</h3>'
        '<p>Data flows <b>right → left</b>: a skill (left) resolves a verdict via its '
        '<b>resolver</b>, pulling <b>cards</b>, each backed by a <b>method</b> (right). '
        'Edges: skill—consumes→card, card—backed_by→method, skill—resolves_via→resolver. '
        'Nodes are colored by health; <b style="color:#c0392b">red-dashed cards</b> are orphans '
        '(no skill consumes). Hover any node to highlight its connections.</p></div>'
    )


def _headline(report: dict) -> str:
    """Auto-generated gestalt sentence — the whole picture in one line."""
    s = report["summary"]
    t = s.get("verdict_tally", {})
    g = report.get("graph") or {}
    n_res = (g.get("layer_counts") or {}).get("resolver", 0)
    ready, partial = t.get("production_ready", 0), t.get("partial", 0)
    unproven = t.get("ready_unproven", 0)
    placeholder = t.get("placeholder", 0)
    broken = t.get("broken_or_drift", 0)
    bits = [f"<b>{ready}</b> skills proven production-ready"]
    if unproven:
        bits.append(f"<b>{unproven}</b> ready but unproven (wired, not yet fired end-to-end)")
    if partial:
        bits.append(f"<b>{partial}</b> partial — data-wiring is the active frontier")
    if placeholder:
        bits.append(f"<b>{placeholder}</b> placeholder")
    if broken:
        bits.append(f"<b style='color:#ffb3a7'>{broken}</b> drift")
    res_txt = (f"Reasoning engine fully wired ({n_res}/{n_res} resolvers); " if n_res else "")
    return f"{res_txt}{'; '.join(bits)}."


def _stat_strip(items: list[tuple]) -> str:
    """Thin inline stat strip: ● N label · ● N label … — replaces the big tile row.
    items = [(label, count, color), ...]"""
    parts = []
    for lbl, num, col in items:
        parts.append(f'<span class="stat"><span class="dot" style="background:{col}"></span>'
                     f'<b>{num}</b> {_esc(lbl)}</span>')
    return f'<div class="strip">{"".join(parts)}</div>'


def render(report: dict) -> str:
    s = report["summary"]
    gen = report.get("generated_at", "")
    subtitle = (f'{s["n_skills"]} skills · {s.get("n_cards", 0)} cards · '
                f'{s.get("n_datasets_in_catalog", 0)} datasets · {_esc(gen[:10])}')
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
<header><h1>Framework Health Dashboard</h1><span class="meta">{subtitle}</span>
<div class="headline">{_headline(report)}</div>
<div class="orient">Health is DERIVED from real files/tests/data (not self-reported status); hover a health chip for its meaning · click a skill row to expand its wiring.</div></header>
<main>
<div class="tabs">
  <div class="tab active" id="tab-skills" onclick="tab('skills')">Skills ({s["n_skills"]})</div>
  <div class="tab" id="tab-cards" onclick="tab('cards')">Cards ({s.get("n_cards", 0)})</div>
  <div class="tab" id="tab-datasets" onclick="tab('datasets')">Datasets ({s.get("n_datasets_in_catalog", 0)})</div>
  <div class="tab" id="tab-graph" onclick="tab('graph')">Graph</div>
</div>

<div class="tabpane active" id="pane-skills">
{_delta_ribbon(report)}
{_summary_cards(report)}
{_fix_next(report)}
{_alerts(report)}
<h2>Skill matrix — grouped by risk category, most-actionable first within each group</h2>
{_matrix(report)}
{_registry_panel(report)}
</div>

<div class="tabpane" id="pane-cards">
{_card_summary_cards(report)}
{_p4_summary_cards(report)}
<h2>Card inventory — every card once, deduped, joined to consuming skills</h2>
{_cards_table(report)}
</div>

<div class="tabpane" id="pane-datasets">
{_dataset_summary_cards(report)}
<h2>Data catalog — every product a card pulls, joined to consuming cards</h2>
{_datasets_table(report)}
</div>

<div class="tabpane" id="pane-graph">
<h2>Component graph — layered flow (Skills → Resolvers → Cards → Methods)</h2>
{_graph_legend()}
<div style="overflow-x:auto;background:#fff;border:1px solid #e1e0d9;border-radius:6px;padding:8px">
{_graph_svg(report)}
</div>
</div>

<div class="panel"><h3>How to read this dashboard — glossary</h3>
<p><b>Skill health:</b> {' '.join(_chip(k, v) for k, v in SKILL_COLORS.items())}</p>
<p><b>Card health:</b> {' '.join(_chip(k, v) for k, v in CARD_COLORS.items())}</p>
<p><b>broken</b> = no path to data (no reader + no backing method, never fires);
<b>blocked</b> = no live reader (honest gap); <b>partial</b> = reader exists but hasn't fired in a real package yet;
<b>live</b> = has fired (passed/warned) in a real evidence package; <b>orphan</b> = card defined on disk but consumed by no skill (unclaimed measurement).</p>

<h3>Drift severity — <span class="hdrnote">severity is about IMPACT, not badness</span></h3>
<p>{' '.join(_chip(SEVERITY_LABEL[s], SEVERITY_COLORS[s]) for s in ("error", "warn", "info"))}</p>
<p><b>error</b> = {_esc(SEVERITY_GLOSS["error"])}; <b>warn</b> = {_esc(SEVERITY_GLOSS["warn"])};
<b>info</b> = {_esc(SEVERITY_GLOSS["info"])}. Only error + warn appear in the Fix-next queue; info items are shown for transparency.</p>

<h3>Drift codes — what each one means</h3>
<ul class="glosslist">{_drift_code_glossary()}</ul>

<h3>Modality routing <span class="hdrnote">(roadmap term “P4”)</span></h3>
<p>{_esc(P4_GLOSS)}</p>
<p>{' '.join(_chip(k, v) for k, v in MODALITY_COLORS.items() if k not in ("not_applicable", "unknown"))}</p>
<p><b>declared</b> = measurement_type routes to a modality-fit gate (small-molecule/degrader/ADC/TCE/antibody) and the card declares its vector;
<b>not required</b> = biology-axis type, correctly silent; <b>missing</b> = routes but declares nothing (stranded — validator error);
<b>drift</b> = declares values outside its type's routing set. Routing is metadata PARALLEL to health — it never changes a card's health.</p>
</div>
</main>
<footer>Generated by validators/framework_health — a derived artifact. Regenerate; do not hand-edit. Run with --check to guard staleness in CI.</footer>
<script>{_JS}</script>
</body></html>"""
