#!/usr/bin/env python3
"""render_review.py — a SIMPLE static-HTML review of one target-profile run, for the team to review
the SKILL itself (a development artifact, not a customer deliverable).

Layout:
  TOP-LEVEL
    1. Cross-evidence synthesis + key input data (bullets) + cross-dimension edges (with a legend).
    2. 6-dimension risk assessment — deterministic engine reshape AND the literature 6-dim (side by side).
    3. Modality-fit — grouped (small-molecule/intracellular vs biologics/surface) engine fit + grounded-agent.
  PER SUB-SKILL
    a. LLM synthesis — key findings.  b. Key-questions -> outputs table.  c. Cards -> data -> rules -> verdict.
  Descriptive sub-skills (target-intrinsic) render a KEY BIOLOGY facts table instead of the a/b/c chain.
  A "How to read this" legend glosses the abstractions.

Inputs (one --full-package run dir; the rest optional / auto-detected):
  <run>/evidence_package.json, <run>/nomination.json, <run>/subskills/<short>/package.json
  <run>/hypothesis.json (or --hypothesis)          cross-evidence-hypothesis
  <T>-<I>-literature-risk/risk_assessment.json     literature 6-dim (auto-found beside run, or --literature)
  --grounded-dir DIR                               grounded_<axis>.json for the modality grounded column

Stdlib only; self-contained output. Reuses tp_render_md's 6-dim reshape so the review never drifts.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_SKILLS_ROOT = _HERE.parents[1]
for _p in (str(_HERE), str(_SKILLS_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from tp_render_md import _risk_by_category_from_sub_verdicts as _risk_reshape
except Exception:  # noqa: BLE001
    _risk_reshape = None

SUBSKILL_ORDER = [
    ("expression", "Tumor presence / expression"),
    ("selectivity", "Tumor selectivity"),
    ("dependency", "Functional requirement (dependency)"),
    ("mechanism", "Mechanism & pharmacology"),
    ("genomic_alteration", "Genomic alteration"),
    ("differentiation", "Differentiation landscape"),
    ("tractability_sm", "Tractability — small molecule"),
    ("surface_modality", "Surface / modality fit"),
    ("immune_context", "Immune context"),
    ("safety", "On-target safety liability"),
    ("target_intrinsic", "Target-intrinsic dossier (key biology)"),
    ("cis_coherence", "Cis-feature coherence"),
    ("combination_vulnerability", "Combination & vulnerability"),
]
SUBSKILL_LABEL = dict(SUBSKILL_ORDER)
QUESTION_TABLE_FACET = {"expression": "presence_facet", "selectivity": "selectivity_facet",
                        "dependency": "dependency_facet"}
RISK_INPUT_AXES = {
    "biological": ["expression", "selectivity", "dependency", "genomic_alteration"],
    "druggability": ["tractability_sm", "surface_modality"], "safety": ["safety"],
    "translational": [], "clinical": ["differentiation"], "commercial": ["differentiation"],
}
RISK_LEVEL_CLASS = {"LOW": "r-low", "LOW-MEDIUM": "r-low", "MEDIUM": "r-med",
                    "MEDIUM-HIGH": "r-high", "HIGH": "r-high"}
# Descriptive (verdict=None) sub-skills that get a KEY-BIOLOGY facts table, with the fields to surface.
DESCRIPTIVE_FIELDS = {
    "target_intrinsic": {
        "target-identity-summary": ["resolved_hgnc_symbol", "resolved_uniprot_canonical", "resolved_ensembl_id"],
        "target-development-level": ["tdl_class", "tdl_meaning", "target_family", "novelty_score"],
        "protein-domains-class": ["protein_class_primary", "n_domains", "domain_names", "domain_architecture"],
        "domain-modality-relevance": ["modality_implication_class", "modality_implication_basis"],
        "ppi-interactome": ["interactome_class", "n_high_confidence_interactors", "top_interactors", "n_corum_complexes"],
        "gene-ontology-annotation": ["annotation_class", "n_biological_process", "n_molecular_function", "n_cellular_component"],
        "reactome-pathway-membership": ["pathway_class", "top_level_pathways", "is_signaling"],
    },
}
# Plain-language glosses for the cross-evidence edge relations + hypothesis verdicts.
EDGE_RELATION_GLOSS = {
    "conditions": "A sets the context under which B holds (B is true given A).",
    "corroborates": "A independently supports / reinforces B.",
    "contradicts": "A directly opposes B — a coherence conflict to resolve.",
    "tensions_with": "A pulls against B — a caveat / partial conflict, not a hard contradiction.",
}
VERDICT_GLOSS = {
    "advanceable": "advance the target.",
    "advanceable_flagged": "advance, but with flagged caveats to watch.",
    "advanceable_with_caveat": "advance, conditional on stated caveats.",
    "conditional_on_biomarker": "advance only for a biomarker-defined patient subset.",
    "not_advanceable": "do not advance on current evidence.",
    "hold": "hold — a blocking concern is unresolved.",
}


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _tip(text: str, gloss: Optional[str]) -> str:
    """Render text with an optional hover gloss (title=), plus a dotted underline cue."""
    if not gloss:
        return _esc(text)
    return f"<abbr title=\"{_esc(gloss)}\">{_esc(text)}</abbr>"


def _polarity(rule_id: Optional[str]) -> tuple[str, str]:
    r = rule_id or ""
    if r.endswith("-veto") or "veto" in r:
        return ("⊘", "pol-veto")
    if r.endswith("-opposing") or "opposing" in r:
        return ("−", "pol-opp")
    if r.endswith("-supportive") or "supportive" in r:
        return ("+", "pol-sup")
    return ("·", "pol-neu")


def _load_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


def _signals_str(sig: Any) -> str:
    if isinstance(sig, dict):
        return ", ".join(f"{k}={v}" for k, v in sig.items() if v is not None) or "—"
    return "—" if sig is None else str(sig)


def _card_data_str(summary: Any, prefer: Optional[list] = None) -> str:
    if not isinstance(summary, dict):
        return "—"
    if prefer:
        picks = [(k, summary.get(k)) for k in prefer
                 if summary.get(k) is not None and not isinstance(summary.get(k), (dict, list))]
        if picks:
            return "; ".join(f"{k}={v}" for k, v in picks)
    picks = [(k, v) for k, v in summary.items()
             if (k.endswith("_class") or k.endswith("_call")) and not isinstance(v, (dict, list))
             and v is not None and not k.startswith("_")]
    if not picks:
        picks = [(k, v) for k, v in summary.items()
                 if not isinstance(v, (dict, list)) and v is not None and not k.startswith("_")][:3]
    return ", ".join(f"{k}={v}" for k, v in picks[:4]) or "—"


def _scalar(v: Any) -> Any:
    return v.get("value") if isinstance(v, dict) and "value" in v else v


# ---------------------------------------------------------------- (1) cross-evidence

def _bullets(items: list[str]) -> str:
    return "<ul class=bullets>" + "".join(f"<li>{b}</li>" for b in items if b) + "</ul>"


def _cross_evidence_section(hyp: Optional[dict], ep: Optional[dict], nom: Optional[dict]) -> str:
    syn = (nom or {}).get("llm_synthesis") or {}
    exec_summary = _scalar(syn.get("executive_summary"))
    tension = _scalar(syn.get("tension_analysis"))
    H = (hyp or {}).get("hypothesis") or {}
    thesis = (hyp or {}).get("thesis") or (H.get("causal_rationale") or {}).get("statement") \
        or exec_summary or ((hyp or {}).get("verdict") or {}).get("reason")

    input_bullets: list[str] = []
    for p in ((hyp or {}).get("evidence_paths") or []):
        cits = ", ".join(f"<span class=cit>{_esc(c)}</span>"
                         for c in {s.get("citation") for s in (p.get("steps") or []) if s.get("citation")})
        input_bullets.append(f"{_esc(p.get('claim'))} <span class=leads>⇒ {_esc(p.get('leads_to'))}</span>"
                             + (f"<div class=citline>{cits}</div>" if cits else ""))
    if not input_bullets and ep:
        sv = (ep.get("synthesis") or {}).get("sub_verdicts") or {}
        for short, label in SUBSKILL_ORDER:
            d = sv.get(short)
            if isinstance(d, dict) and d.get("verdict"):
                input_bullets.append(f"<b>{_esc(label)}</b>: {_esc(d.get('verdict'))} "
                                     f"<span class=cit>[{_esc(d.get('driving_rule_id'))}]</span>")

    edge_rows = []
    for e in ((hyp or {}).get("edges") or []):
        etype = e.get("type")
        ecls = {"contradicts": "pol-veto", "tensions_with": "pol-opp",
                "corroborates": "pol-sup", "conditions": "pol-neu"}.get(etype, "pol-neu")
        edge_rows.append(f"<tr class='{ecls}'><td class=etype>{_tip(etype, EDGE_RELATION_GLOSS.get(etype))}</td>"
                         f"<td class=edim>{_esc(e.get('from_dimension'))} → {_esc(e.get('to_dimension'))}</td>"
                         f"<td>{_esc(e.get('rationale'))}</td></tr>")
    legend = ("<div class=legend><b>Relations:</b> "
              + " · ".join(f"<span class=rel>{_esc(k)}</span> {_esc(v)}"
                           for k, v in EDGE_RELATION_GLOSS.items()) + "</div>")
    edges_html = (f"<h3>Cross-dimension edges — which sub-skill outputs drove or tensioned the thesis</h3>"
                  f"{legend}<table class=edges><tr><th>Relation</th><th>Between</th><th>Rationale</th></tr>"
                  f"{''.join(edge_rows)}</table>" if edge_rows else "")

    V = (hyp or {}).get("verdict") or {}
    vg = VERDICT_GLOSS.get(V.get("computed"))
    verdict_line = (f"<div class=xverdict><span class=vlabel>hypothesis verdict</span> "
                    f"<b>{_tip(V.get('computed'), vg)}</b> — <span class=vgloss>{_esc(vg or '')}</span>"
                    f"<div class=drives>gate ceiling: {_esc(V.get('gate_ceiling'))}"
                    f"{' · CLAMPED to the deterministic ceiling' if V.get('was_clamped') else ''}. "
                    f"{_esc(V.get('reason'))}</div></div>" if V else "")
    no_hyp = ("" if hyp else "<p class=muted>No hypothesis.json — leading with the composed Tier-3 "
              "synthesis. Run <code>cross-evidence-hypothesis</code> over the evidence package for the "
              "typed thesis + edges.</p>")
    return f"""<details class="sec xev" open>
      <summary>1 · Cross-evidence synthesis</summary>{no_hyp}
      <div class=thesis>{_esc(thesis)}</div>
      {verdict_line}
      <h3>Key input data used</h3>
      {_bullets(input_bullets) if input_bullets else '<p class=muted>No input summary available.</p>'}
      {f'<h3>Tension</h3><p class=prose>{_esc(tension)}</p>' if tension else ''}
      {edges_html}
    </details>"""


# ---------------------------------------------------------------- (2) risk (engine + literature)

def _risk_section(ep: Optional[dict]) -> str:
    if not ep:
        return ""
    sv = (ep.get("synthesis") or {}).get("sub_verdicts") or {}
    sub_results = {short: {"verdict": (d.get("verdict"), d.get("driving_rule_id"))}
                   for short, d in sv.items() if isinstance(d, dict)}
    triples = _risk_reshape(sub_results) if _risk_reshape else []
    rows = []
    for cat, level, driver in triples:
        cls = RISK_LEVEL_CLASS.get(level, "r-na")
        inputs = [f"{ax}={_esc(sv[ax].get('verdict'))}" for ax in RISK_INPUT_AXES.get(cat, [])
                  if isinstance(sv.get(ax), dict) and sv[ax].get("verdict")]
        rows.append(f"<tr><td class=dim>{_esc(cat)}</td>"
                    f"<td class=risk><span class='rbadge {cls}'>{_esc(level)}</span></td>"
                    f"<td>{_esc(driver)}</td><td class=inp>{'; '.join(inputs) or '—'}</td></tr>")
    return (f"<details class=sec open><summary>2 · 6-dimension risk assessment</summary>"
            f"<p class=sub>Deterministic reshape of THIS run's sub-verdicts. insufficient_evidence = "
            f"the target-profile run has no wired coverage for that dimension.</p>"
            f"<table class=risk6><tr><th>Dimension</th><th>Risk</th><th>What drove it</th>"
            f"<th>Contributing sub-verdicts</th></tr>{''.join(rows)}</table></details>")


# ---------------------------------------------------------------- (3) modality (grouped)

def _grounded_modality(grounded_dir: Optional[Path]) -> dict:
    out: dict = {}
    if not grounded_dir or not grounded_dir.is_dir():
        return out
    for axis in ("surface_modality", "tractability_sm", "safety"):
        g = _load_json(grounded_dir / f"grounded_{axis}.json")
        if isinstance(g, dict):
            findings = g.get("findings") or g.get("escalations") or []
            n = len(findings) if isinstance(findings, list) else 0
            out[axis] = f"{n} grounded finding(s)" if n else "no escalations"
    return out


MODALITY_GROUPS = [
    ("Small-molecule / intracellular", ["small_molecule", "degrader"], "tractability_sm"),
    ("Biologics / surface", ["adc", "bite_tce", "antibody"], "surface_modality"),
]
FIT_CLASS = {"favorable": "r-low", "conditional": "r-med", "unfavorable": "r-high"}


def _modality_row(ch: str, d: dict, grounded_axis_note: Optional[str]) -> str:
    fit = d.get("fit")
    cls = FIT_CLASS.get(fit, "r-na")
    by = d.get("by_axis") or {}
    by_str = "; ".join(f"{k}={v}" for k, v in by.items()) or (
        f"masked by {d.get('masked_by_axis')} (target is intracellular — biologics N/A)"
        if d.get("masked_by_axis") else "—")
    lim = d.get("limiting_axis")
    return (f"<tr><td class=dim>{_esc(ch)}</td>"
            f"<td class=risk><span class='rbadge {cls}'>{_esc(fit)}</span></td>"
            f"<td>{_esc(by_str)}{f' · limited by {_esc(lim)}' if lim else ''}</td>"
            f"<td class=inp>{_esc(grounded_axis_note) if grounded_axis_note else '—'}</td></tr>")


def _modality_section(nom: Optional[dict], grounded_dir: Optional[Path]) -> str:
    mf = (nom or {}).get("modality_fit_by_channel") or {}
    if not mf:
        return ""
    grounded = _grounded_modality(grounded_dir)
    blocks = []
    for group_label, channels, gaxis in MODALITY_GROUPS:
        agg = mf.get("biologics") if group_label.startswith("Biologics") else None
        rows = [_modality_row(ch, mf[ch], grounded.get(gaxis)) for ch in channels if isinstance(mf.get(ch), dict)]
        if not rows:
            continue
        agg_note = ""
        if agg and isinstance(agg, dict):
            agg_note = (f"<div class=grouphint>biologics (aggregate): <b>{_esc(agg.get('fit'))}</b>"
                        f"{' — ' + _esc('masked by ' + agg.get('masked_by_axis')) if agg.get('masked_by_axis') else ''}</div>")
        blocks.append(f"<h3>{_esc(group_label)}</h3>{agg_note}"
                      f"<table class=risk6><tr><th>Channel</th><th>Engine fit</th><th>By axis</th>"
                      f"<th>Grounded-agent</th></tr>{''.join(rows)}</table>")
    gnote = ("" if grounded_dir else " <span class=muted>(grounded-agent column empty — pass "
             "<code>--grounded-dir</code> from a <code>--ground</code> run)</span>")
    return (f"<details class=sec open><summary>3 · Modality-fit summary</summary>"
            f"<p class=sub>Deterministic engine fit per channel + grounded-agent{gnote}. Biologics is the "
            f"parent abstraction of ADC / bispecific-TCE / antibody; small-molecule and degrader are the "
            f"intracellular channels.</p>{''.join(blocks)}</details>")


# ---------------------------------------------------------------- per-sub-skill

def _synthesis_html(pkg: dict) -> str:
    s = pkg.get("llm_synthesis")
    if not isinstance(s, dict) or not s:
        return ("<div class='synth none'>LLM synthesis not generated for this run "
                "(re-run with <code>--synthesize-subskills</code>), or this sub-skill has no narrator.</div>")
    if "_synthesis_error" in s:
        return f"<div class='synth err'>LLM synthesis unavailable: {_esc(s.get('_synthesis_error'))}</div>"
    if s.get("_synthesis_skipped"):
        return "<div class='synth none'>LLM synthesis skipped.</div>"
    fields, model = {}, None
    for k, v in s.items():
        if k == "metric_legend" or k.startswith("_"):
            continue
        if isinstance(v, dict):
            model = model or v.get("_model_id")
        val = _scalar(v)
        if not isinstance(val, (dict, list)):
            fields[k] = val
    used = set()

    def _pick(*preds):
        for k in fields:
            if any(pr in k for pr in preds) and k not in used:
                used.add(k)
                return k, fields[k]
        return None, None

    tk, takeaway = _pick("relevance", "for_target", "fit_class", "_call")
    ck, conf = _pick("confidence")
    vk, caveat = _pick("caveat")
    # Concise lead: the headline judgment + confidence chip + the single key caveat.
    lead = ""
    if takeaway:
        lead = (f"<div class=synth-lead><b>{_esc(str(takeaway).replace('_',' '))}</b>"
                + (f" <span class=confchip>confidence: {_esc(str(conf).replace('_',' '))}</span>" if conf else "")
                + "</div>")
    caveat_line = (f"<div class=caveat><b>caveat:</b> {_esc(caveat)}</div>"
                   if caveat and str(caveat).lower() not in ("none", "n/a", "") else "")
    # Everything else (the longer rationale prose) folds away so the default view stays tight.
    rest = [(k, v) for k, v in fields.items() if k not in used]
    detail = ""
    if rest:
        inner = "".join(f"<p><span class=sk>{_esc(k.replace('_',' '))}:</span> {_esc(v)}</p>" for k, v in rest)
        detail = f"<details class=synth-more><summary>full narration</summary>{inner}</details>"
    prov = (f"<div class=prov>LLM narration (model: {_esc(model)}) — interprets the deterministic "
            f"outputs; never changes them.</div>" if model else "")
    body = lead + caveat_line + detail
    return f"<div class=synth>{body or '<p class=muted>(no narrative fields)</p>'}{prov}</div>"


def _question_table_html(short: str, nom: Optional[dict]) -> str:
    facet_key = QUESTION_TABLE_FACET.get(short)
    qt = ((nom or {}).get(facet_key) or {}).get("question_table") if facet_key else None
    if not isinstance(qt, list) or not qt:
        return ("<p class=muted>No key-question table for this sub-skill (only the focused-question "
                "skills — presence, selectivity, dependency — emit one).</p>")
    rows = []
    for q in qt:
        sig = q.get("signal") or {}
        conf = q.get("confidence") or {}
        pcls = {"supports": "pol-sup", "opposes": "pol-opp"}.get(sig.get("polarity"), "pol-neu")
        support = q.get("support")
        rows.append(f"<tr><td class=qid>{_esc(q.get('id'))}</td><td>{_esc(q.get('question'))}</td>"
                    f"<td class=qout><b>{_esc(q.get('primary'))}</b>"
                    f"{f'<div class=qsup>{_esc(support)}</div>' if support else ''}</td>"
                    f"<td class='{pcls}'>{_esc(sig.get('label'))}</td>"
                    f"<td class=conf>{_esc(conf.get('label'))}</td></tr>")
    return ("<p class=hint>Each row: a key sub-question → the measured output (data) that answered it, "
            "its signal direction, and confidence.</p>"
            f"<table class=qtab><tr><th>#</th><th>Key question</th><th>Output / data that answered it</th>"
            f"<th>Signal</th><th>Confidence</th></tr>{''.join(rows)}</table>")


def _chain_html(pkg: dict) -> str:
    driving = pkg.get("driving_rule_id")
    fired_rules = pkg.get("fired_rules")
    cards = pkg.get("cards") or []
    summ = {c.get("card_id"): (c.get("summary") or {}) for c in cards}
    rows = []
    if isinstance(fired_rules, list) and fired_rules:
        by_card: dict[str, list[dict]] = {}
        for f in fired_rules:
            by_card.setdefault(f.get("card_id") or "(unattributed)", []).append(f)
        card_ids = [c.get("card_id") for c in cards]
        ordered = [c for c in card_ids if c in by_card] + [c for c in by_card if c not in card_ids]
        seen = set()
        for cid in ordered:
            if cid in seen:
                continue
            seen.add(cid)
            for i, f in enumerate(by_card.get(cid, [])):
                glyph, cls = _polarity(f.get("rule_id"))
                star = " ★" if f.get("is_driving") else ""
                rows.append(f"<tr class='{cls}{' driving' if f.get('is_driving') else ''}'>"
                            f"<td class=card>{_esc(cid) if i == 0 else ''}</td>"
                            f"<td class=data>{_card_data_str(summ.get(cid)) if i == 0 else ''}</td>"
                            f"<td class=glyph>{glyph}</td>"
                            f"<td class=rule>{_esc(f.get('rule_id'))}{star} "
                            f"<span class=sig>{_esc(_signals_str(f.get('signals')))}</span></td></tr>")
        for cid in [c.get("card_id") for c in cards if c.get("card_id") not in by_card]:
            rows.append(f"<tr class=inert><td class=card>{_esc(cid)}</td>"
                        f"<td class=data>{_card_data_str(summ.get(cid))}</td>"
                        f"<td class=glyph>·</td><td class=rule>(no rule fired — display / verdict-inert)</td></tr>")
        head = "<tr><th>Card (evidence)</th><th>Data (the read)</th><th></th><th>Rule fired · signals</th></tr>"
    else:
        for rid in (pkg.get("fired_rule_ids") or []):
            glyph, cls = _polarity(rid)
            rows.append(f"<tr class='{cls}'><td class=rule>{_esc(rid)}{' ★' if rid == driving else ''}</td>"
                        f"<td class=glyph>{glyph}</td>")
        head = "<tr><th>Rule fired (card linkage unavailable in this run)</th><th></th></tr>"
    table = (f"<table class=chain>{head}{''.join(rows)}</table>" if rows else "<p class=muted>No rules fired.</p>")
    vbox = (f"<div class=verdict-box><span class=vlabel>verdict</span> <b>{_esc(pkg.get('verdict')) or '—'}</b>"
            f"<span class=drives>★ driving rule: {_esc(driving) or '—'}</span></div>")
    return ("<p class=hint>Reads left→right: each evidence card → the data value read from it → the "
            "interpretation rule it fired (+ supportive / − opposing / ⊘ veto / · neutral) → the verdict "
            "those rules resolve to. ★ = the rung that drove the verdict.</p>" + table + vbox)


def _why_verdict_html(short: str, nom: Optional[dict]) -> str:
    """Render the per-verdict NARRATIVE for one axis from nomination.json.narrative_by_axis[short]:
    what SET the verdict (movers), what pushed back and lost (dissenters), what would FLIP it
    (flip_conditions), and the open GAPS. Pure projection — no recompute. The deterministic
    counterpart to the LLM synthesis: it makes the abstract rule_ids/verdict tell their own story."""
    nba = (nom or {}).get("narrative_by_axis") or {}
    n = nba.get(short)
    if not isinstance(n, dict):
        return ("<p class=muted>No narrative for this axis (only resolver-backed sub-verdicts emit "
                "one; re-run target-profile so nomination.json carries <code>narrative_by_axis</code>).</p>")
    movers = n.get("movers") or []
    dissenters = n.get("dissenters") or []
    flips = n.get("flip_conditions") or []
    gaps = n.get("gaps") or []
    if not (movers or dissenters or flips or gaps):
        return "<p class=muted>Narrative empty (no movers, dissenters, or flips for this verdict).</p>"

    rows = []
    # SET BY — the winning driver (★) + same-direction referenced movers
    if movers:
        chips = []
        for m in movers:
            star = " ★" if m.get("role") == "driver" else ""
            chips.append(f"<abbr class=pol-sup title=\"{_esc(m.get('sentence') or '')}\">"
                         f"<code>{_esc(m.get('rule_id'))}</code>{star}</abbr>")
        rows.append(f"<div class=whyrow><span class=whytag>set by</span>"
                    f"<span class=whyval>{' '.join(chips)}</span></div>")
        drv = next((m for m in movers if m.get("role") == "driver"), None)
        if drv and drv.get("sentence"):
            rows.append(f"<div class=whysent>{_esc(drv['sentence'])}</div>")
    # DESPITE — dissenters (fired rules opposing the resolved call), deduped per rule with channels
    if dissenters:
        by_rule: dict[str, list] = {}
        sent: dict[str, str] = {}
        for d in dissenters:
            rid = d.get("rule_id")
            by_rule.setdefault(rid, []).append(d.get("channel"))
            sent.setdefault(rid, d.get("sentence") or "")
        chips = [f"<abbr class=pol-opp title=\"{_esc(sent.get(rid) or '')}\"><code>{_esc(rid)}</code> "
                 f"<span class=whych>({_esc(', '.join(c for c in chans if c))})</span></abbr>"
                 for rid, chans in by_rule.items()]
        rows.append(f"<div class=whyrow><span class=whytag>despite</span>"
                    f"<span class=whyval>{' '.join(chips)}</span></div>")
    # FLIPS IF — single-rule counterfactuals; ⚑ marks a Go/No-Go (recommendation) flip
    if flips:
        items = []
        for f in flips:
            rid, to = f.get("rule_id"), f.get("to_verdict")
            cond = "without" if f.get("present") else "with"
            flag = " <span class=whyflag title='crosses the Go/No-Go boundary'>⚑ rec</span>" \
                if f.get("recommendation_flip") else ""
            items.append(f"<span class=whyflip>{cond} <code>{_esc(rid)}</code> → "
                         f"<b>{_esc(to)}</b>{flag}</span>")
        rows.append(f"<div class=whyrow><span class=whytag>flips if</span>"
                    f"<span class=whyval>{' '.join(items)}</span></div>")
    # GAPS — acquire (held by ignorance) / strengthen (measured-but-underpowered)
    if gaps:
        labs = []
        for g in gaps:
            if g.get("kind") == "acquire":
                cids = ", ".join(c.get("card_id") for c in (g.get("missing_cards") or []) if c.get("card_id"))
                labs.append(f"acquire <code>{_esc(cids)}</code>" if cids else "acquire (missing data)")
            elif g.get("kind") == "strengthen":
                labs.append("strengthen (measured but underpowered)")
        if labs:
            rows.append(f"<div class=whyrow><span class=whytag>gaps</span>"
                        f"<span class=whyval>{' · '.join(labs)}</span></div>")
    return ("<p class=hint>Deterministic reasoning trace: what <b>set</b> the verdict, what fired "
            "<b>against</b> it and lost, and the single rule-toggles that would <b>flip</b> it. Hover a "
            "rule for its plain-English rationale.</p>"
            f"<div class=why>{''.join(rows)}</div>")


def _descriptive_facts_html(short: str, pkg: dict) -> str:
    spec = DESCRIPTIVE_FIELDS.get(short) or {}
    summ = {c.get("card_id"): (c.get("summary") or {}) for c in (pkg.get("cards") or [])}
    rows = []
    for cid, fields in spec.items():
        s = summ.get(cid)
        if not isinstance(s, dict):
            continue
        for f in fields:
            v = s.get(f)
            if v is None or (isinstance(v, (list, dict)) and not v):
                continue
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v[:8])
            rows.append(f"<tr><td class=fk>{_esc(f.replace('_',' '))}</td><td>{_esc(v)}</td>"
                        f"<td class=csrc>{_esc(cid)}</td></tr>")
    if not rows:
        return "<p class=muted>No descriptive fields available.</p>"
    return ("<p class=hint>Indication-independent target biology (descriptive — no verdict).</p>"
            f"<table class=facts><tr><th>Property</th><th>Value</th><th>Card</th></tr>{''.join(rows)}</table>")


def _subskill_section(short: str, pkg: dict, nom: Optional[dict]) -> str:
    label = SUBSKILL_LABEL.get(short, short)
    _, vcls = _polarity(pkg.get("driving_rule_id"))
    if short in DESCRIPTIVE_FIELDS:
        body = (f"<h4>Key biology facts</h4>{_descriptive_facts_html(short, pkg)}"
                f"<h4>Interpretation (LLM synthesis)</h4>{_synthesis_html(pkg)}")
        vchip = "descriptive · no verdict"
    else:
        body = (f"<h4>a · Interpretation (LLM synthesis — key findings)</h4>{_synthesis_html(pkg)}"
                f"<h4>b · Key questions → outputs (data used)</h4>{_question_table_html(short, nom)}"
                f"<h4>c · Cards → data → rules → verdict</h4>{_chain_html(pkg)}"
                f"<h4>d · Why this verdict — movers, dissenters, what would flip it</h4>"
                f"{_why_verdict_html(short, nom)}")
        vchip = _esc(pkg.get('verdict')) or 'verdict: none'
    return f"""
    <details class=subskill open>
      <summary><span class=ss-name>{_esc(label)}</span>
        <span class="ss-verdict {vcls}">{vchip}</span>
        <span class=ss-short>{_esc(short)}</span></summary>
      <div class=ss-body>{body}</div>
    </details>"""


# ---------------------------------------------------------------- assembly

_LEGEND = """<details class=howto><summary>How to read this review</summary><div class=howto-body>
<ul>
<li><b>Verdicts &amp; rules are deterministic</b> — computed by rules firing on card data. The
<b>LLM synthesis</b> per sub-skill only <i>interprets</i> them into plain language; it never changes a verdict.</li>
<li><b>Polarity:</b> <span class=pol-sup>+ supportive</span> · <span class=pol-opp>− opposing</span> ·
<span class=pol-veto>⊘ veto</span> · <span class=pol-neu>· neutral</span>. <b>★</b> marks the rule that drove the verdict.</li>
<li><b>Risk badges:</b> <span class="rbadge r-low">LOW</span> <span class="rbadge r-med">MEDIUM</span>
<span class="rbadge r-high">HIGH</span>; insufficient_evidence = that dimension has no wired data.</li>
<li><b>Cross-dimension edges</b> show how one sub-skill's output conditions / corroborates / contradicts / tensions another (hover a relation for its meaning).</li>
<li><b>Why this verdict (d)</b> is the deterministic reasoning trace: <b>set by</b> (the movers that produced the call, ★ = driver), <b>despite</b> (dissenting rules that fired but lost), and <b>flips if</b> (single rule-toggles that would change it; <span class=whyflag>⚑ rec</span> = crosses the Go/No-Go). Verdict-inert — it explains, never changes, the verdict.</li>
<li>Tokens in <code>mono</code> are card IDs / rule IDs / raw class values — the audit trail; hover dotted terms for a gloss.</li>
</ul></div></details>"""

_CSS = """
:root{--ink:#1a1a1a;--muted:#6c757d;--rule:#e6e6e6;--warm:#f8f9fa;--accent:#d6001c;
  --sup:#0a7d33;--opp:#b26a00;--veto:#b30015;--neu:#6c757d;--low:#0a7d33;--med:#b26a00;--high:#b30015;}
*{box-sizing:border-box}body{font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);margin:0;background:#fff}
.wrap{max-width:1060px;margin:0 auto;padding:28px 22px 80px}
h1{font:600 26px/1.2 Georgia,serif;margin:0 0 2px}
h2{font:600 19px/1.2 Georgia,serif;margin:34px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--rule)}
/* Collapsible top-level sections (1-4) — summary is styled to match the old h2 heading. */
details.sec{margin:34px 0 0}
details.sec>summary{font:600 19px/1.2 Georgia,serif;margin:0 0 10px;padding-bottom:6px;border-bottom:2px solid var(--rule);cursor:pointer;list-style:none}
details.sec>summary::-webkit-details-marker{display:none}
details.sec>summary::before{content:"▾ ";font-size:13px;color:var(--muted)}
details.sec:not([open])>summary::before{content:"▸ "}
h3{font:600 15px/1.2 Georgia,serif;margin:18px 0 6px;color:#333}
h4{font-size:12.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:16px 0 6px}
.sub{color:var(--muted);margin:0 0 8px;font-size:13px}.muted{color:var(--muted)}
.hint{color:#555;font-size:12px;margin:4px 0 6px;font-style:italic}
.prose{margin:4px 0}code{background:var(--warm);padding:1px 4px;border-radius:3px;font-size:.9em;font-family:ui-monospace,Menlo,monospace}
abbr{text-decoration:underline dotted;cursor:help}
table{border-collapse:collapse;width:100%;margin:6px 0;font-size:13px}
th{text-align:left;font-weight:600;color:var(--muted);border-bottom:1px solid var(--rule);padding:5px 8px}
td{padding:5px 8px;vertical-align:top;border-bottom:1px solid #f0f0f0}
.bullets{margin:6px 0;padding-left:20px}.bullets li{margin:5px 0}
.citline{margin-top:2px}.cit{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--muted);margin-right:6px}
.leads{color:var(--accent)}
.thesis{font:400 17px/1.5 Georgia,serif;background:var(--warm);padding:14px 18px;border-radius:6px;margin:8px 0}
.xverdict,.verdict-box{background:var(--warm);border-left:3px solid var(--accent);padding:8px 12px;margin:8px 0;border-radius:0 4px 4px 0}
.vlabel{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-right:8px}
.vgloss{color:#333}.drives{color:var(--muted);font-size:12px;margin-top:4px}
.legend{font-size:11.5px;color:#555;background:var(--warm);border-radius:5px;padding:6px 10px;margin:4px 0}
.legend .rel{font-weight:600;color:#333;margin-left:4px}
.edges td.etype{font-weight:600}.edges td.edim{font-family:ui-monospace,monospace;font-size:12px;white-space:nowrap}
.risk6 td.dim{font-weight:600;text-transform:capitalize;white-space:nowrap}.risk6 td.inp{color:#555;font-size:12px}
.grouphint{color:var(--muted);font-size:12px;margin:2px 0 4px}
.rbadge{display:inline-block;padding:2px 9px;border-radius:10px;font-weight:600;font-size:12px;background:var(--warm)}
.rbadge.r-low{color:var(--low)}.rbadge.r-med{color:var(--med)}.rbadge.r-high{color:var(--high)}.rbadge.r-na{color:var(--muted)}
details.subskill{border:1px solid var(--rule);border-radius:6px;margin:10px 0}
details.subskill>summary{cursor:pointer;padding:12px 14px;display:flex;align-items:center;gap:12px;list-style:none}
details.subskill>summary::-webkit-details-marker{display:none}
.ss-name{font-weight:600;flex:1}.ss-short{font-family:ui-monospace,monospace;font-size:11px;color:var(--muted)}
.ss-verdict{font-size:12px;font-weight:600;padding:2px 8px;border-radius:10px;background:var(--warm)}
.ss-verdict.pol-sup{color:var(--sup)}.ss-verdict.pol-opp{color:var(--opp)}.ss-verdict.pol-veto{color:var(--veto)}
.ss-body{padding:0 14px 14px}
.synth{background:#fafbfc;border:1px solid var(--rule);border-radius:5px;padding:10px 14px}
.synth p{margin:6px 0}.synth .sk{font-weight:600;color:#333}
.synth-lead{font-size:14.5px}.confchip{display:inline-block;background:#fff;border:1px solid var(--rule);border-radius:10px;padding:1px 8px;font-size:11.5px;color:#555;margin-left:8px}
.caveat{font-size:12.5px;color:var(--opp);margin-top:5px}
details.synth-more{margin-top:6px}details.synth-more>summary{cursor:pointer;color:var(--muted);font-size:12px}
.synth.none,.synth.err{color:var(--muted);font-style:italic;background:none;border:1px dashed var(--rule)}
.prov{color:var(--muted);font-size:11px;margin-top:6px}
.qtab td.qid{font-family:ui-monospace,monospace;color:var(--muted);width:34px}
.qtab td.qout{font-size:12.5px}.qtab .qsup{color:var(--muted);font-size:11.5px;margin-top:2px}
.qtab td.conf{color:#555;font-size:12px}
.facts td.fk{font-weight:600;text-transform:capitalize;white-space:nowrap}.facts td.csrc{font-family:ui-monospace,monospace;font-size:11px;color:var(--muted)}
.chain td.card{font-family:ui-monospace,monospace;font-size:11.5px;white-space:nowrap}
.chain td.data{font-family:ui-monospace,monospace;font-size:11px;color:#444}
.chain td.rule{font-family:ui-monospace,monospace;font-size:11.5px}.chain .sig{color:var(--muted)}
.chain td.glyph,.glyph{width:16px;text-align:center;font-weight:700}
tr.driving{background:#fff7f7}tr.inert td{color:var(--muted)}
.pol-sup .glyph,.pol-sup td.glyph,td.pol-sup,.pol-sup{color:var(--sup)}.pol-opp .glyph,.pol-opp td.glyph,td.pol-opp,.pol-opp{color:var(--opp)}
.pol-veto .glyph,.pol-veto td.glyph,.pol-veto{color:var(--veto)}.pol-neu .glyph,.pol-neu td.glyph,td.pol-neu{color:var(--neu)}
details.howto{margin:10px 0;border:1px solid var(--rule);border-radius:6px;background:var(--warm)}
details.howto>summary{cursor:pointer;padding:8px 12px;font-weight:600;font-size:13px}
.howto-body{padding:0 14px 10px;font-size:13px}.howto-body ul{margin:6px 0;padding-left:18px}.howto-body li{margin:4px 0}
.foot{color:var(--muted);font-size:12px;margin-top:40px;border-top:1px solid var(--rule);padding-top:10px}
/* "Why this verdict" narrative panel (d) — deterministic movers/dissenters/flips/gaps */
.why{background:#fafbfc;border:1px solid var(--rule);border-radius:5px;padding:8px 12px;display:flex;flex-direction:column;gap:5px}
.whyrow{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.whytag{flex:0 0 64px;text-transform:uppercase;letter-spacing:.05em;font-size:10px;font-weight:700;color:var(--muted);padding-top:2px}
.whyval{flex:1;font-size:12.5px}.whyval abbr{margin-right:8px;text-decoration:none}
.whyval code{background:#fff;border:1px solid var(--rule)}
.whysent{color:#555;font-size:12px;padding-left:72px;font-style:italic}
.whych{color:var(--muted);font-size:11px}
.whyflip{display:inline-block;margin:0 10px 3px 0;font-size:12px}
.whyflag{color:var(--veto);font-weight:600;font-size:11px}
"""


def _name(v: Any, *keys: str) -> str:
    """Pull a display string from a dict-or-scalar context field (target/indication may be dicts)."""
    if isinstance(v, dict):
        for k in keys:
            if v.get(k):
                return str(v[k])
        return json.dumps(v)
    return "" if v is None else str(v)


def build_html(run_dir: Path) -> str:
    """Render the review from ONLY this run's own artifacts under run_dir — no external inputs."""
    ep = _load_json(run_dir / "evidence_package.json")
    nom = _load_json(run_dir / "nomination.json")
    ctx = (ep or {}).get("context") or {}
    target = _name(ctx.get("target"), "symbol", "resolved_hgnc_symbol") or _name((nom or {}).get("target"), "symbol") or "?"
    indication = _name(ctx.get("indication"), "oncotree_code", "code") or _name((nom or {}).get("indication"), "oncotree_code") or "?"

    # In-run cross-evidence-hypothesis (emitted by --with-hypothesis); else the section falls back to
    # this run's Tier-3 composed synthesis. grounded_<axis>.json (emitted by --ground) also live in-run.
    hyp = _load_json(run_dir / "hypothesis.json") if (run_dir / "hypothesis.json").exists() else None
    grounded_dir = run_dir

    subdir = run_dir / "subskills"
    sections, n_synth = [], 0
    for short, _label in SUBSKILL_ORDER:
        pkg = _load_json(subdir / short / "package.json")
        if not pkg:
            continue
        sections.append(_subskill_section(short, pkg, nom))
        ls = pkg.get("llm_synthesis")
        if isinstance(ls, dict) and "_synthesis_error" not in ls and not ls.get("_synthesis_skipped"):
            n_synth += 1

    syn = (nom or {}).get("llm_synthesis") or {}
    rec = _scalar(syn.get("overall_recommendation"))
    if not rec:
        rg = (nom or {}).get("recommendation_gate") or {}
        rec = "hold / block" if rg.get("fired") else "nominate"
    conf = ((nom or {}).get("confidence_tier") or {})
    conf = conf.get("tier") if isinstance(conf, dict) else conf
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{_esc(target)} in {_esc(indication)} — target-profile review</title>
<style>{_CSS}</style></head><body><div class=wrap>
<h1>{_esc(target)} in {_esc(indication)}</h1>
<p class=sub>target-profile run review · recommendation: <b>{_esc(rec)}</b> · confidence: <b>{_esc(conf) or '—'}</b>
· {_esc(len(sections))} sub-skills · {n_synth} with LLM synthesis</p>
{_LEGEND}
{_cross_evidence_section(hyp, ep, nom)}
{_risk_section(ep)}
{_modality_section(nom, grounded_dir)}
<details class=sec open><summary>4 · Per-sub-skill</summary>
{''.join(sections) if sections else '<p class=muted>No subskills/ packages — run with --full-package.</p>'}
</details>
<div class=foot>Generated by render_review.py from {_esc(run_dir.name)}. Development artifact for skill review.</div>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a static-HTML review of a target-profile run.")
    ap.add_argument("--run", required=True, type=Path,
                    help="target-profile --full-package run dir. The review uses ONLY this run's own "
                         "artifacts (evidence_package / nomination / subskills / in-run hypothesis.json "
                         "from --with-hypothesis / in-run grounded_<axis>.json from --ground).")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    if not args.run.is_dir():
        raise SystemExit(f"run dir not found: {args.run}")
    out = args.out or (args.run / "review.html")
    out.write_text(build_html(args.run))
    print(f"[render_review] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
