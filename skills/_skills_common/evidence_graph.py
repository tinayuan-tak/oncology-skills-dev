"""evidence_graph — the additive, byte-stable "claim graph" at decision.headline.evidence_graph.

A one-way, DISPLAY-ONLY projection over data already present in a subskill's `decision` dict, so a
downstream renderer can draw the whole dashboard (verdict header, signal×confidence heatmap, question
table with per-question omics + literature, and each card's dataset→data→rule→verdict chain) with
ZERO heuristic joins, zero `.card.yaml` reads, and zero free-text parsing. It introduces NO new
science, feeds NO rule/resolver/gate, and changes NO existing field — `evidence_graph` is the only
key added (attached by reference into `decision["headline"]` at the dispatcher seam).

Nodes carry stable ids and edges are explicit. Datasets and citations are deduplicated into id-keyed
arrays; every other node references them by id. Both directions of the hot edges are materialized
(`questions[].card_ids` and `cards[].question_ids`). Referential integrity is a hard invariant: every
id referenced by an edge resolves to a node in the same package.

Canonical vocabulary comes from the per-skill `questions.yaml` registry (see load_questions): a stable
semantic `question_id` slug + a unified `axis_id` set shared by the question hierarchy AND the
literature lane. The literature axis→question crosswalk is derived from that registry, giving the
otherwise-missing link (e.g. presence axis B → elevated_vs_normal).

Fail-soft throughout: absent `literature_synthesis`/`llm_synthesis` (or their error stubs) yield empty
`literature`/`narrative` sub-objects; a skill without a `questions.yaml` still emits a
referentially-intact graph with best-effort (null) question anchoring.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

SCHEMA_VERSION = "1.0"


# ── canonical question registry loader ─────────────────────────────────────────────────────────────
def load_questions(skill_dir) -> list:
    """Load the per-skill canonical question registry (`<skill_dir>/questions.yaml` → questions[]).
    Fail-soft: returns [] when the file is absent or unreadable (a skill not yet migrated)."""
    try:
        p = Path(skill_dir) / "questions.yaml"
        if not p.exists():
            return []
        doc = yaml.safe_load(p.read_text()) or {}
        qs = doc.get("questions") or []
        return [q for q in qs if isinstance(q, dict) and q.get("id")]
    except Exception:  # noqa: BLE001 — display-only projection; never break the spine
        return []


# ── small provenance-unwrap helper (a --literature-only decision.json can re-wrap axes) ─────────────
def _unwrap(v):
    """Unwrap an llm-provenance-stamped value ({value,_source:'llm_synthesized',...}) → its value."""
    if isinstance(v, dict) and "value" in v and v.get("_source") == "llm_synthesized":
        return v["value"]
    return v


# ── signal / confidence projection (reuse existing display vocab; no new scoring) ───────────────────
_POLARITY = {"supports": "supports", "opposes": "opposes", "neutral": "neutral", "none": "none"}


def _question_signal(row: dict) -> dict:
    s = row.get("signal") or {}
    return {"tier": s.get("tier"), "polarity": _POLARITY.get(s.get("polarity"), s.get("polarity")),
            "label": s.get("label")}


def _question_confidence(row: dict) -> dict:
    cf = row.get("confidence") or {}
    return {"level": cf.get("tier"), "dots": cf.get("dots"), "label": cf.get("label")}


def _card_signal(cap: dict, sg_tier: Optional[str], fired: bool, is_liability: bool) -> dict:
    """A coarse per-card signal for the heatmap. `tier` (strength) reuses the card's subgroup-source
    tier when the framework bound it to a sub-group (else None — honest gap); `polarity` is the coarse
    3-way (fired→supports / liability class→opposing / else neutral); `label` = the card's class."""
    if is_liability:
        polarity = "opposing"
    elif fired:
        polarity = "supports"
    else:
        polarity = "neutral"
    return {"tier": sg_tier, "polarity": polarity, "label": cap.get("class")}


_CONF_DOTS = {"high": 3, "moderate": 2, "low": 1, "standard": 2, "unknown": 0, "unmeasured": 0}


def _card_confidence(cap: dict, n: Optional[float]) -> dict:
    es = cap.get("evidence_state")
    level = "high" if es == "measured" else ("low" if es in ("comparator", "inferred") else "moderate")
    return {"level": level, "dots": _CONF_DOTS.get(level, 0), "evidence_state": es, "n": n}


# ── card ↔ question join (measurement_type membership, with subtype-tier disambiguation) ────────────
def _ambiguous_measurement_types(caps: dict) -> set:
    """measurement_types carried by BOTH a subtype-tier and a non-subtype card in this package — for
    these the subtype flag disambiguates which question a card joins (whole-cohort vs by-subtype)."""
    by_mt_subtype, by_mt_whole = set(), set()
    for cap in caps.values():
        mt = cap.get("measurement_type")
        if not mt:
            continue
        (by_mt_subtype if cap.get("tier") == "subtype" else by_mt_whole).add(mt)
    return by_mt_subtype & by_mt_whole


def _card_question_ids(cap: dict, questions: list, ambiguous: set) -> list:
    """Question slugs this card belongs to: its measurement_type ∈ the question's measurement_types,
    with subtype-tier disambiguation for measurement_types shared by a whole-cohort + by-subtype pair."""
    mt = cap.get("measurement_type")
    is_subtype = cap.get("tier") == "subtype"
    out = []
    for q in questions:
        mts = q.get("measurement_types") or []
        if mt not in mts:
            continue
        if mt in ambiguous and bool(q.get("subtype", False)) != is_subtype:
            continue
        out.append(q["id"])
    return out


# ── citation id minting (stable, deterministic) ─────────────────────────────────────────────────────
_AUTHOR_YEAR = re.compile(r"^\s*([A-Za-z][A-Za-z'\-]+).*?((?:19|20)\d{2})")


def _citation_id(cite: dict, taken: set) -> str:
    label = str(cite.get("label") or "")
    m = _AUTHOR_YEAR.match(label)
    if m:
        base = (m.group(1) + m.group(2)).lower()
    elif cite.get("pmid"):
        base = f"pmid{cite['pmid']}"
    else:
        base = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "citation"
    cid = base
    i = 2
    while cid in taken:
        cid = f"{base}-{i}"
        i += 1
    taken.add(cid)
    return cid


# ── narrative anchor extraction (single-lens rationale cites card_id/rule_id in plain prose) ─────────
_ID_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+){2,}")


def _narrative_cites(text: str, card_ids: set, rule_ids: set) -> tuple:
    """Anchor a narrative to the package by exact card_id/rule_id substrings appearing in its prose
    (order-preserving dedup). Display-only: never invents an id not present in the package."""
    found_cards, found_rules = [], []
    for tok in _ID_TOKEN.findall(text or ""):
        if tok in card_ids and tok not in found_cards:
            found_cards.append(tok)
        if tok in rule_ids and tok not in found_rules:
            found_rules.append(tok)
    return found_cards, found_rules


# ── the builder ──────────────────────────────────────────────────────────────────────────────────
def build_evidence_graph(decision: dict, questions: Optional[list] = None) -> dict:
    """Assemble decision.headline.evidence_graph as a pure projection/JOIN over `decision`.

    `questions` is the canonical registry (load_questions); when None or empty the graph still emits
    with best-effort (null) question anchoring. Deterministic ordering throughout (questions by seq;
    cards in decision.cards order; sorted dedup for datasets/citations) so the emitted JSON is
    byte-stable.
    """
    decision = decision or {}
    h = decision.get("headline") or {}
    questions = questions or []
    caps = ((h.get("evidence_capsules") or {}).get("capsules")) or {}
    cards_list = decision.get("cards") or []
    fired_rules = decision.get("fired_rules") or []

    # verdict spine (read-only)
    hb = h.get("headline_block") or {}
    hb_verdict = hb.get("verdict") or {}
    driving_rule_id = h.get("driving_rule_id") or hb_verdict.get("driving_rule_id")
    verdict_call = (h.get("presence_verdict") or hb_verdict.get("call")
                    or h.get("verdict"))

    fired_by_card: dict = {}
    driving_card_id = None
    for r in fired_rules:
        cid, rid = r.get("card_id"), r.get("rule_id")
        if cid:
            fired_by_card.setdefault(cid, []).append(r)
        if rid and rid == driving_rule_id:
            driving_card_id = cid
    verdict_bearing_cards = set(fired_by_card.keys())

    # per-card (strength tier, sample-size n) from the framework's own subgroup-source binding — the
    # authoritative per-card corroboration read (only for cards bound to a sub-group; else None).
    sg_by_card: dict = {}
    for _blk in (h.get("subgroup_signals") or {}).values():
        if not isinstance(_blk, dict):
            continue
        for _s in (_blk.get("sources") or []):
            if isinstance(_s, dict) and _s.get("card") and _s.get("card") not in sg_by_card:
                sg_by_card[_s["card"]] = (_s.get("tier"), _s.get("n"))

    # ordered questions (by seq); keep the registry rows as-is for anchoring
    questions = sorted(questions, key=lambda q: q.get("seq", 1_000_000))
    ambiguous = _ambiguous_measurement_types(caps)

    # question_table rows keyed by legacy_id (Q1..Q7), for signal/confidence/prose (never mutated)
    qt_rows = {r.get("id"): r for r in (h.get("question_table") or []) if isinstance(r, dict)}

    # ── cards[] (all cards, both edge directions) ──
    card_nodes, dataset_ids_seen = [], []
    card_qids: dict = {}
    for c in cards_list:
        cid = c.get("card_id")
        cap = caps.get(cid, {}) or {}
        rules_for = fired_by_card.get(cid, [])
        rule_ids = [r.get("rule_id") for r in rules_for if r.get("rule_id")]
        is_vb = cid in verdict_bearing_cards
        is_liability = str(cap.get("class") or "").upper().endswith("LIABILITY") or "liability" in str(cap.get("class") or "").lower()
        qids = _card_question_ids(cap, questions, ambiguous) if cap else []
        card_qids[cid] = qids
        # class field/value — from the fired rule (verdict-bearing) else the first categorical anchor.
        if rules_for:
            class_field, class_value = rules_for[0].get("field"), rules_for[0].get("value")
        else:
            anchors = cap.get("categorical_anchors") or []
            first = anchors[0] if anchors else {}
            class_field, class_value = first.get("field"), (cap.get("class") if cap.get("class") is not None else first.get("value"))
        dataset_ids = list(c.get("input_manifest_ids") or [])
        for d in dataset_ids:
            if d not in dataset_ids_seen:
                dataset_ids_seen.append(d)
        numeric = cap.get("numeric_anchors") or []
        sg_tier, sg_n = sg_by_card.get(cid, (None, None))
        chain = {
            "dataset_ids": dataset_ids,
            "data": [{"field": a.get("metric"), "value": a.get("value")} for a in numeric[:4]],
            "rule_id": (rule_ids[0] if rule_ids else None),
            "contributes_to_verdict": is_vb,
            "is_driving": cid == driving_card_id,
        }
        key_fields = {a.get("metric"): a.get("value") for a in numeric if a.get("metric")}
        card_nodes.append({
            "id": cid,
            "measurement_type": cap.get("measurement_type"),
            "tier": cap.get("tier"),
            "role": "verdict_bearing" if is_vb else "display_only",
            "question_ids": qids,
            "axis_id": next((q.get("axis_id") for q in questions if q["id"] in qids and q.get("axis_id")), None),
            "signal": _card_signal(cap, sg_tier, is_vb, is_liability),
            "confidence": _card_confidence(cap, sg_n),
            "class": {"field": class_field, "value": class_value},
            "dataset_ids": dataset_ids,
            "rule_ids": rule_ids,
            "chain": chain,
            "key_fields": key_fields,
        })

    # ── questions[] (both edge directions; literature axis crosswalk fed later) ──
    q_nodes = []
    for q in questions:
        qid = q["id"]
        # cards whose question_ids include this question (inverse of the card→question join)
        q_card_ids = [c["id"] for c in card_nodes if qid in c["question_ids"]]
        q_rule_ids = []
        for cnode in card_nodes:
            if cnode["id"] in q_card_ids:
                for rid in cnode["rule_ids"]:
                    if rid not in q_rule_ids:
                        q_rule_ids.append(rid)
        row = qt_rows.get(q.get("legacy_id"), {})
        evidence_refs = []
        for cnode in card_nodes:
            if cnode["id"] in q_card_ids and cnode["class"].get("value") is not None:
                evidence_refs.append({
                    "card_id": cnode["id"], "field": cnode["class"].get("field"),
                    "value": cnode["class"].get("value"),
                    "label": f"{cnode['id']} {cnode['class'].get('value')}",
                })
        q_nodes.append({
            "id": qid,
            "seq": q.get("seq"),
            "text": q.get("text") or row.get("question"),
            "axis_id": q.get("axis_id"),
            "role": q.get("role"),
            "signal": _question_signal(row),
            "confidence": _question_confidence(row),
            "card_ids": q_card_ids,
            "rule_ids": q_rule_ids,
            "literature_axis_ids": [],  # filled by the literature crosswalk below
            "evidence_refs": evidence_refs,
            "prose": {"primary": row.get("primary"), "support": row.get("support")},
        })
    q_by_id = {q["id"]: q for q in q_nodes}

    # ── rules[] ──
    rule_nodes = []
    for r in fired_rules:
        rid = r.get("rule_id")
        rule_nodes.append({
            "id": rid, "card_id": r.get("card_id"), "field": r.get("field"),
            "value": r.get("value"), "dominant": bool(r.get("dominant")),
            "is_driving": rid == driving_rule_id,
            "rationale": r.get("rationale_summary"),
        })

    # ── datasets[] (dedup, sorted for byte-stability) ──
    dataset_nodes = [{"id": d, "s3_uri": None, "license": None} for d in sorted(set(dataset_ids_seen))]

    # ── literature + citations (Phase 3) ──
    literature, citation_nodes = _build_literature(decision, questions, q_by_id)

    # ── narrative (Phase 4) ──
    narrative = _build_narrative(decision, card_nodes, rule_nodes, q_nodes)

    # ── verdict node ──
    conf = hb.get("confidence") or {}
    tension = hb.get("top_tension") or {}
    tension_cards = [c for c in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", str(tension.get("text") or ""))
                     if c in {cn["id"] for cn in card_nodes}]
    verdict_node = {
        "id": verdict_call,
        "call": hb_verdict.get("phrase") or hb.get("headline_text") or verdict_call,
        "polarity": hb_verdict.get("polarity"),
        "driving_rule_id": driving_rule_id,
        "confidence": {"level": conf.get("level"), "coverage": conf.get("coverage")},
        "top_tension": ({"text": tension.get("text"), "severity": tension.get("severity"),
                         "source_card_ids": tension_cards} if tension else None),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "skill": decision.get("skill"),
        "target": decision.get("target"),
        "indication": decision.get("indication"),
        "verdict": verdict_node,
        "questions": q_nodes,
        "cards": card_nodes,
        "rules": rule_nodes,
        "datasets": dataset_nodes,
        "literature": literature,
        "citations": citation_nodes,
        "narrative": narrative,
    }


def _build_literature(decision: dict, questions: list, q_by_id: dict) -> tuple:
    """Project decision.literature_synthesis into {axes[], blind_spots[], overall_consistency,
    key_divergence} with the axis→question crosswalk + hoisted top-level citations[]. Fail-soft:
    absent/errored/skipped → ({}, [])."""
    lit = decision.get("literature_synthesis")
    if not isinstance(lit, dict) or any(k in lit for k in ("_literature_error", "_literature_skipped")):
        return {}, []

    # crosswalk: axis_id → question_ids (verdict/display questions on that axis, NOT corroboration ones)
    axis_to_questions: dict = {}
    for q in questions:
        ax = q.get("axis_id")
        if ax and q.get("role") != "corroboration":
            axis_to_questions.setdefault(ax, []).append(q["id"])

    axes_raw = _unwrap(lit.get("axes")) or []
    blind_raw = _unwrap(lit.get("blind_spots")) or []
    taken: set = set()

    def _cite_ids(cite_list) -> list:
        ids = []
        for c in (cite_list or []):
            if not isinstance(c, dict):
                continue
            ids.append((c, _citation_id(c, taken)))
        return ids

    citation_nodes, seen_pairs = [], {}
    axes_out = []
    for ax in axes_raw:
        if not isinstance(ax, dict):
            continue
        axis_id = ax.get("axis_key")
        cite_ids = []
        for cite, cid in _cite_ids(ax.get("citations")):
            citation_nodes.append({"id": cid, "label": cite.get("label"),
                                   "pmid": cite.get("pmid"), "doi": cite.get("doi"),
                                   "verified": bool(cite.get("verified"))})
            cite_ids.append(cid)
        qids = list(axis_to_questions.get(axis_id, []))
        for qid in qids:
            if qid in q_by_id and axis_id not in q_by_id[qid]["literature_axis_ids"]:
                q_by_id[qid]["literature_axis_ids"].append(axis_id)
        axes_out.append({
            "axis_id": axis_id, "question_ids": qids,
            "read": ax.get("literature_read"),
            "agreement_vs_omics": ax.get("agreement_vs_omics"),
            "confidence": ax.get("confidence"),
            "assertion": ax.get("assertion"),
            "citation_ids": cite_ids,
        })

    blind_out = []
    for bs in blind_raw:
        if not isinstance(bs, dict):
            continue
        cite_ids = []
        for cite, cid in _cite_ids(bs.get("citations")):
            citation_nodes.append({"id": cid, "label": cite.get("label"),
                                   "pmid": cite.get("pmid"), "doi": cite.get("doi"),
                                   "verified": bool(cite.get("verified"))})
            cite_ids.append(cid)
        blind_out.append({"text": bs.get("signal"), "why_omics_blind": bs.get("why_omics_blind"),
                          "citation_ids": cite_ids})

    literature = {
        "axes": axes_out,
        "blind_spots": blind_out,
        "overall_consistency": _unwrap(lit.get("overall_consistency")),
        "key_divergence": _unwrap(lit.get("key_divergence")),
    }
    return literature, citation_nodes


def _build_narrative(decision: dict, card_nodes: list, rule_nodes: list, q_nodes: list) -> dict:
    """Project decision.llm_synthesis into an anchored narrative. Fail-soft: absent/error stub → {}."""
    syn = decision.get("llm_synthesis")
    if not isinstance(syn, dict) or any(k in syn for k in ("_synthesis_error", "_synthesis_skipped")):
        return {}
    card_ids = {c["id"] for c in card_nodes}
    rule_ids = {r["id"] for r in rule_nodes if r["id"]}
    # focused llm_synthesis stamps each field as {value,_source:"llm_synthesized",...}; unwrap so the
    # graph carries plain scalars (mirrors _build_literature, which already unwraps its axes).
    text = " ".join(str(_unwrap(syn.get(k)) or "") for k in ("rationale", "key_caveat", "context_read",
                                                             "key_signals_summary"))
    cited_cards, cited_rules = _narrative_cites(text, card_ids, rule_ids)
    cited_qids = [q["id"] for q in q_nodes if set(q["card_ids"]) & set(cited_cards)]
    return {
        "relevance": _unwrap(syn.get("relevance")) or _unwrap(syn.get("context_read")),
        "rationale": _unwrap(syn.get("rationale")) or _unwrap(syn.get("key_signals_summary")),
        "confidence_qualifier": _unwrap(syn.get("confidence_qualifier")),
        "key_caveat": _unwrap(syn.get("key_caveat")),
        "cites": {"question_ids": cited_qids, "card_ids": cited_cards, "rule_ids": cited_rules},
    }


__all__ = ["build_evidence_graph", "load_questions", "SCHEMA_VERSION"]
