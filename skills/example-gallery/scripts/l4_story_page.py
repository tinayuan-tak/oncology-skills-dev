#!/usr/bin/env python3
"""l4_story_page.py — render an L4 target-synthesis object as a static HTML "target story" page
(epic #1986, C2 #1997 — the showable demo artifact).

Consumes `_skills_common.l4_synthesis.assemble_target_synthesis(decision)` DIRECTLY as a pure
read-over on a live-emitted decision/envelope — no envelope-emission wiring (that is C1 #1996,
deferred post-cutover). This module owns ONLY the render: `synthesis` (or `None`) + the raw
`decision` in -> one self-contained HTML string out.

FACET-AGNOSTIC BY DESIGN: iterates the facets the assembler actually returned, in the schema's
canonical `FACET_NAMES` order. Four facets get a PURPOSE-BUILT layout because this module
understands their payload shape (thesis_archetype, opportunity_drivers, liabilities_contradictions,
critical_unknowns, all landed C0a-C0d). Any OTHER declared facet — built now or later (#2008
modality_implications, #2009 next_evidence, decision_dimensions, decision_state) — renders via the
generic `statements` list every facet-result carries (schema.iter_statements). So a later facet
builder landing enriches the page with NO code change here: it just stops being an "absent" section.

Absence discipline ("missing != negative" — the L4 governance rule):
  * A facet key absent from `synthesis["facets"]` renders as an HONEST "not yet resolved" note, never
    fabricated content.
  * `synthesis is None` (nothing resolved at all) renders the sparsest honest page: target/indication
    + a plain statement that no L4 facet resolved for this envelope.

Traceability is the load-bearing UX: every rendered statement shows the claim ref(s) it cites as a
small chip (claim_id + vector/domain/frame), and — where the ref resolves to a card the run actually
emitted a figure for — the chip becomes a jump-link into that figure, embedded via the SAME
`fig_map_from_existing` / `_card_figures_html` seam `generate_example_gallery.py` already uses (no
duplicate figure logic; the story page and the flat gallery page can never show a different figure
for the same card).

Deterministic modulo timestamp: pass `generated_at` explicitly for byte-stable test output; omitted,
it stamps the current UTC time (display-only, not part of any assertable content).
"""

from __future__ import annotations

import datetime as _dt
import html
from pathlib import Path
from typing import Mapping, Optional

from _skills_common.l4_synthesis import schema as S  # noqa: E402

# Reuse the existing gallery's CSS + figure-embedding seam so a story page and a flat card page never
# drift in look-and-feel or in which figure they show for a given card.
from generate_example_gallery import (  # noqa: E402
    _CSS,
    _ZOOM_JS,
    _card_figures_html,
)

_STORY_CSS = """
.l4wrap{max-width:1040px;margin:0 auto;padding:24px}
.archband{border-radius:10px;padding:16px 20px;margin:10px 0 18px;color:#fff}
.archband.supported,.archband.supported_with_caveats{background:linear-gradient(135deg,#14532d,#166534)}
.archband.contested,.archband.insufficient{background:linear-gradient(135deg,#7c2d12,#9a3412)}
.archband.limited_evidence,.archband.partial{background:linear-gradient(135deg,#78350f,#a16207)}
.archband .atype{font-size:12px;text-transform:uppercase;letter-spacing:.06em;opacity:.85}
.archband .aval{font-size:22px;font-weight:700;margin:2px 0 8px}
.archband .thesisnote{font-size:13.5px;opacity:.95}
.domstrip{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 22px}
.domchip{font-size:11.5px;padding:3px 10px;border-radius:14px;font-weight:600}
.domchip.assessed{background:#dcfce7;color:#166534}
.domchip.unassessed{background:#f3f4f6;color:#6b7280}
.facet{border:1px solid #e3e6ea;border-radius:10px;background:#fff;margin:16px 0;padding:14px 18px}
.facet.absent{background:#fafbfc;border-style:dashed}
.facet h2{font-size:16px;margin:0 0 8px;display:flex;align-items:center;gap:8px}
.facet .built-by{font-size:10.5px;color:#99a;font-weight:400}
.statement{border-top:1px solid #f0f2f5;padding:8px 0;font-size:13.5px}
.statement:first-of-type{border-top:none}
.claimrefs{margin-top:4px}
.cref{display:inline-block;font-size:10.5px;background:#eef2ff;color:#3730a3;border-radius:10px;
  padding:1px 8px;margin:2px 4px 0 0;font-family:ui-monospace,Menlo,Consolas,monospace}
.cref a{color:inherit;text-decoration:none} .cref a:hover{text-decoration:underline}
.driver-row,.liab-row,.unk-row{border-top:1px solid #f0f2f5;padding:8px 0}
.driver-row:first-child,.liab-row:first-child{border-top:none}
.dtag{font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;color:#556;background:#f5f6f8;
  border-radius:4px;padding:1px 6px;margin-right:6px}
.contra-note{color:#8a5a2b;background:#fdf6ec;border-radius:6px;padding:8px 11px;font-size:13px;margin:6px 0}
table.unktbl{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
table.unktbl th,table.unktbl td{border:1px solid #e8ebef;padding:5px 9px;text-align:left;vertical-align:top}
table.unktbl th{background:#f5f6f8}
.stchip{display:inline-block;font-size:11px;font-weight:600;border-radius:10px;padding:1px 9px}
.stchip.KNOWN{background:#dcfce7;color:#166534}
.stchip.UNKNOWN{background:#fef9c3;color:#854d0e}
.stchip.CONTRADICTED{background:#fee2e2;color:#991b1b}
.stchip.NOT_ASSESSED{background:#f3f4f6;color:#6b7280}
.dcflag{color:#991b1b;font-weight:700;font-size:11px}
.figjump{margin:6px 0}
.absentnote{color:#889;font-size:13px;font-style:italic}
.storyfig{margin:6px 0}
"""

_FACET_TITLES = {
    S.FACET_THESIS_ARCHETYPE: "Thesis & Archetype",
    S.FACET_OPPORTUNITY_DRIVERS: "Opportunity Drivers",
    S.FACET_LIABILITIES_CONTRADICTIONS: "Liabilities & Contradictions",
    S.FACET_CRITICAL_UNKNOWNS: "Critical Unknowns",
    S.FACET_MODALITY_IMPLICATIONS: "Modality Implications",
    S.FACET_NEXT_EVIDENCE: "Next Evidence (Value of Information)",
    S.FACET_DECISION_DIMENSIONS: "Decision Dimensions (5R)",
    S.FACET_DECISION_STATE: "Decision State",
}


def _esc(v) -> str:
    return html.escape(str(v))


# ── claim-ref -> card_id resolution (for the figure jump-links) ────────────────────────────────────
def _claim_vectors_from_decision(decision: Mapping) -> dict:
    """The same two named claim vectors `l4_synthesis.context.read_context` gathers, reconstructed
    here read-only (we never import context's private dataclass — this module only needs the dict)."""
    h = decision.get("headline") if isinstance(decision, Mapping) else None
    h = h if isinstance(h, Mapping) else {}
    return {
        "pooled_claim_vector": h.get("claim_vector") if isinstance(h.get("claim_vector"), Mapping) else {},
        "by_subtype_claim_vector": (
            h.get("claim_vector_by_subtype") if isinstance(h.get("claim_vector_by_subtype"), Mapping) else {}
        ),
    }


def _card_ids_for_ref(ref: Mapping, claim_vectors: Mapping) -> list:
    """Best-effort: which card_id(s) a claim ref's underlying claim-vector entry cites. The claim
    vector carries TWO distinct entry shapes this walks: the per-letter (A/B/C/D) island shape
    (`evidence_atom.cite.card_id` / `corr_cite.card_id`) and the L3d cross-source concordance shape
    (`source_support: [{provenance: {card_id}}]`, e.g. `tumor_presence_concordance`,
    `abundance_concordance` — what the L3d chapters' own claim refs cite). Never raises; [] when
    unresolvable (a domain/frame ref, or a claim_id the vector doesn't carry a cite for) — the chip
    then renders as plain text with no jump-link, never a fabricated one."""
    vec = ref.get("vector") if isinstance(ref, Mapping) else None
    cid = ref.get("claim_id") if isinstance(ref, Mapping) else None
    if not vec or not cid:
        return []
    entry = claim_vectors.get(vec, {})
    entry = entry.get(cid) if isinstance(entry, Mapping) else None
    if not isinstance(entry, Mapping):
        return []
    out: list = []
    for key in ("evidence_atom", "corr_cite"):
        blob = entry.get(key)
        if not isinstance(blob, Mapping):
            continue
        cite = blob.get("cite") if key == "evidence_atom" else blob
        if isinstance(cite, Mapping) and isinstance(cite.get("card_id"), str):
            out.append(cite["card_id"])
    for support in entry.get("source_support") or []:
        if not isinstance(support, Mapping):
            continue
        prov = support.get("provenance")
        if isinstance(prov, Mapping) and isinstance(prov.get("card_id"), str):
            out.append(prov["card_id"])
    seen = set()
    return [c for c in out if not (c in seen or seen.add(c))]


def _claim_ref_chip(ref: Mapping, claim_vectors: Mapping, cards_with_figures: set) -> str:
    parts = [f"claim_id={_esc(ref.get('claim_id'))}"]
    for k in ("vector", "domain", "frame"):
        if ref.get(k):
            parts.append(f"{k}={_esc(ref.get(k))}")
    label = " ".join(parts)
    card_ids = [c for c in _card_ids_for_ref(ref, claim_vectors) if c in cards_with_figures]
    if card_ids:
        anchor = f"#card_{_esc(card_ids[0])}"
        return f'<span class="cref"><a href="{anchor}">{label} → fig</a></span>'
    return f'<span class="cref">{label}</span>'


def _refs_html(refs: list, claim_vectors: Mapping, cards_with_figures: set) -> str:
    if not refs:
        return ""
    chips = "".join(_claim_ref_chip(r, claim_vectors, cards_with_figures) for r in refs if isinstance(r, Mapping))
    return f'<div class="claimrefs">{chips}</div>'


def _figures_for_refs(
    refs: list, claim_vectors: Mapping, run_dir: Optional[Path], fig_map: Mapping, interactive: bool
) -> str:
    """Inline the figure(s) for the FIRST card a statement's refs resolve to that the run actually
    emitted a figure for. Best-effort/additive — a statement with no resolvable, figured card renders
    with no figure block (never a placeholder)."""
    if not run_dir or not fig_map:
        return ""
    for ref in refs or []:
        if not isinstance(ref, Mapping):
            continue
        for cid in _card_ids_for_ref(ref, claim_vectors):
            descs = fig_map.get(cid)
            if descs:
                figs = _card_figures_html(run_dir, descs, interactive)
                if figs:
                    return f'<div class="storyfig">{figs}</div>'
    return ""


# ── generic statement rendering (the facet-agnostic fallback) ──────────────────────────────────────
def _statement_html(st: Mapping, claim_vectors: Mapping, cards_with_figures: set, run_dir, fig_map, interactive) -> str:
    refs = st.get("claim_ids") or []
    return (
        '<div class="statement">'
        f"{_esc(st.get('text'))}"
        + _refs_html(refs, claim_vectors, cards_with_figures)
        + _figures_for_refs(refs, claim_vectors, run_dir, fig_map, interactive)
        + "</div>"
    )


def _generic_facet_body(fr: Mapping, claim_vectors, cards_with_figures, run_dir, fig_map, interactive) -> str:
    statements = list(S.iter_statements(fr))
    if not statements:
        return '<div class="absentnote">Facet resolved but carries no statements.</div>'
    return "".join(
        _statement_html(st, claim_vectors, cards_with_figures, run_dir, fig_map, interactive) for st in statements
    )


# ── purpose-built facet layouts ──────────────────────────────────────────────────────────────────
def _thesis_archetype_body(fr: Mapping, claim_vectors, cards_with_figures, run_dir, fig_map, interactive) -> str:
    thesis = fr.get("thesis") or {}
    out = [
        f"<p><b>State:</b> {_esc(thesis.get('state'))} &middot; "
        f"<b>Assessed domain(s):</b> {_esc(', '.join(thesis.get('assessed_domains') or []))}</p>",
        f"<p>{_esc(thesis.get('narrative'))}</p>",
    ]
    out.append(_refs_html(thesis.get("supported_by") or [], claim_vectors, cards_with_figures))
    out.append(f"<p><b>Archetype:</b> {_esc(fr.get('archetype'))} — {_esc(fr.get('archetype_basis'))}</p>")
    promote = fr.get("archetype_promote_when") or []
    if promote:
        out.append(f"<p class='absentnote'>Would promote once assessed: {_esc(', '.join(promote))}</p>")
    return "".join(out)


def _opportunity_drivers_body(fr: Mapping, claim_vectors, cards_with_figures, run_dir, fig_map, interactive) -> str:
    drivers = fr.get("drivers") or []
    if not drivers:
        return (
            '<div class="absentnote">No corroborated-positive chapter resolved — no drivers (never fabricated).</div>'
        )
    out = []
    for d in drivers:
        out.append(
            '<div class="driver-row">'
            f'<span class="dtag">{_esc(d.get("domain"))}</span>'
            f'<span class="dtag">{_esc(d.get("aspect"))}</span>'
            f"{_esc(d.get('statement'))}"
            + _refs_html(d.get("claim_ids") or [], claim_vectors, cards_with_figures)
            + _figures_for_refs(d.get("claim_ids") or [], claim_vectors, run_dir, fig_map, interactive)
            + "</div>"
        )
    return "".join(out)


def _liabilities_contradictions_body(
    fr: Mapping, claim_vectors, cards_with_figures, run_dir, fig_map, interactive
) -> str:
    liabilities = fr.get("liabilities") or []
    contradictions = fr.get("contradictions") or []
    out = ['<h3 style="font-size:13px;margin:4px 0">Liabilities</h3>']
    if not liabilities:
        out.append('<div class="absentnote">None found on the assessed domain(s).</div>')
    for lia in liabilities:
        out.append(
            '<div class="liab-row">'
            f'<span class="dtag">{_esc(lia.get("domain"))}</span>'
            f'<span class="dtag">{_esc(lia.get("aspect"))}</span>'
            f"{_esc(lia.get('liability'))}"
            + _refs_html(lia.get("claim_ids") or [], claim_vectors, cards_with_figures)
            + "</div>"
        )
    out.append('<h3 style="font-size:13px;margin:14px 0 4px">Contradictions</h3>')
    if not contradictions:
        out.append('<div class="absentnote">None found — the assessed domain(s) read internally consistent.</div>')
    for con in contradictions:
        out.append(
            '<div class="contra-note">'
            f"{_esc(con.get('note'))}"
            + _refs_html(con.get("between") or [], claim_vectors, cards_with_figures)
            + "</div>"
        )
    return "".join(out)


def _critical_unknowns_body(fr: Mapping, claim_vectors, cards_with_figures, run_dir, fig_map, interactive) -> str:
    unknowns = fr.get("critical_unknowns") or []
    if not unknowns:
        return '<div class="absentnote">No critical-unknown entries.</div>'
    rows = []
    for u in unknowns:
        dc = '<span class="dcflag">DECISION-CRITICAL</span>' if u.get("decision_critical") else ""
        rows.append(
            "<tr>"
            f"<td>{_esc(u.get('question'))}</td>"
            f'<td><span class="stchip {_esc(u.get("status"))}">{_esc(u.get("status"))}</span></td>'
            f"<td>{_esc(u.get('current_status'))}</td>"
            f"<td>{dc}</td>"
            f"<td>{_refs_html(u.get('claim_ids') or [], claim_vectors, cards_with_figures)}</td>"
            "</tr>"
        )
    return (
        '<table class="unktbl"><thead><tr><th>Question</th><th>Status</th><th>Current status</th>'
        "<th></th><th>Claim refs</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


_FACET_BODY_RENDERERS = {
    S.FACET_THESIS_ARCHETYPE: _thesis_archetype_body,
    S.FACET_OPPORTUNITY_DRIVERS: _opportunity_drivers_body,
    S.FACET_LIABILITIES_CONTRADICTIONS: _liabilities_contradictions_body,
    S.FACET_CRITICAL_UNKNOWNS: _critical_unknowns_body,
}


def _absent_facet_html(name: str) -> str:
    title = _FACET_TITLES.get(name, name)
    return (
        f'<div class="facet absent" id="facet-{_esc(name)}">'
        f'<h2>{_esc(title)} <span class="absentnote">— not yet resolved</span></h2>'
        '<div class="absentnote">This facet has not resolved for this envelope. Honestly absent — '
        "not a negative signal (missing ≠ negative).</div></div>"
    )


def _facet_html(name: str, fr: Mapping, claim_vectors, cards_with_figures, run_dir, fig_map, interactive) -> str:
    title = _FACET_TITLES.get(name, name.replace("_", " ").title())
    built_by = fr.get("built_by")
    renderer = _FACET_BODY_RENDERERS.get(name, _generic_facet_body)
    body = renderer(fr, claim_vectors, cards_with_figures, run_dir, fig_map, interactive)
    return (
        f'<div class="facet" id="facet-{_esc(name)}">'
        f"<h2>{_esc(title)}" + (f' <span class="built-by">{_esc(built_by)}</span>' if built_by else "") + "</h2>"
        f"{body}</div>"
    )


def _archetype_band_html(synthesis: Mapping) -> str:
    thesis = synthesis.get("thesis") or {}
    state = thesis.get("state") or "insufficient"
    archetype = synthesis.get("archetype") or S.ARCHETYPE_UNDETERMINED
    narrative = thesis.get("narrative") or ""
    return (
        f'<div class="archband {_esc(state)}">'
        f'<div class="atype">Target archetype</div>'
        f'<div class="aval">{_esc(archetype)}</div>'
        f'<div class="thesisnote">{_esc(narrative)}</div>'
        "</div>"
    )


def _domain_strip_html(synthesis: Mapping) -> str:
    assessed = synthesis.get("assessed_domains") or []
    unassessed = synthesis.get("unassessed_domains") or []
    chips = "".join(f'<span class="domchip assessed">{_esc(d)} ✓ assessed</span>' for d in assessed)
    chips += "".join(f'<span class="domchip unassessed">{_esc(d)} — not assessed</span>' for d in unassessed)
    return f'<div class="domstrip">{chips}</div>' if chips else ""


def _cards_with_figures(fig_map: Optional[Mapping]) -> set:
    return set((fig_map or {}).keys())


def render_story_page(
    synthesis: Optional[Mapping],
    decision: Mapping,
    *,
    target: str,
    indication: Optional[str] = None,
    run_dir: Optional[Path] = None,
    fig_map: Optional[Mapping] = None,
    interactive: bool = False,
    generated_at: Optional[str] = None,
) -> str:
    """Render one L4 target-synthesis object as a self-contained static HTML "target story" page.

    `synthesis` is the (possibly-`None`) return of `assemble_target_synthesis(decision, ...)`.
    `decision` is the raw decision/envelope it was assembled over (used only to resolve claim-ref ->
    card_id -> figure jump-links; never re-interpreted for a verdict — this renderer is verdict-inert
    by construction, it never reads `decision["headline"]["*_verdict"]`).
    """
    claim_vectors = _claim_vectors_from_decision(decision)
    cards_with_figures = _cards_with_figures(fig_map)
    gen = generated_at or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    title = f"{target}" + (f" / {indication}" if indication else "") + " — L4 target story"
    body = [
        f"<h1>{_esc(title)}</h1>",
        f'<p class="sub">Generated {_esc(gen)} &middot; epic #1986 (L4 target synthesis)</p>',
    ]

    if synthesis is None:
        body.append(
            '<div class="facet absent"><h2>No L4 synthesis resolved</h2>'
            '<div class="absentnote">No facet builder resolved a statement for this envelope — '
            "honestly absent, not a negative call. See the underlying decision/evidence package for "
            "what WAS measured.</div></div>"
        )
    else:
        body.append(_archetype_band_html(synthesis))
        body.append(_domain_strip_html(synthesis))
        facets = synthesis.get("facets") or {}
        for name in S.FACET_NAMES:
            fr = facets.get(name)
            if fr is None:
                body.append(_absent_facet_html(name))
            else:
                body.append(_facet_html(name, fr, claim_vectors, cards_with_figures, run_dir, fig_map, interactive))

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{_esc(title)}</title><style>{_CSS}{_STORY_CSS}</style></head>"
        f'<body><div class="wrap l4wrap">{"".join(body)}</div>{_ZOOM_JS}</body></html>'
    )
