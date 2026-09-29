"""product_page.py — the per-subskill "product page": a target-invariant, five-panel view of
one subskill's full capability, assembled from the atlas graph + the extraction shims + the
coverage ledgers + the framework-health live overlay + the axis registry.

Pure ``build(...) → dict`` (the ``concepts.py`` / ``flow.py`` pattern): no skill execution, no
network. The five panels (see the product-showcase plan):

  1. spine        — data source → method → card → summary field (+type, observed) → rule
                    (gating/display) → verdict token → collapsed skill verdict → output shape.
  2. card_drilldown — per card: fields + observed ranges + source datasets (+license) + live/dark.
  3. optionality  — the deterministic spine vs the optional, verdict-inert lanes a user can toggle.
  4. rollup       — how the subskill's verdict flows into the target-profile nomination
                    (short → gate / gateless → risk-6dim bin), with the registry↔code drift.
  5. cards_questions — axis → sub-group → question → measurement_type → card (from the registry).

Verdict precedence comes from the ladder shim (``ladder_extract``): a python-ladder skill's rungs,
or a resolver-backed skill's ``graph["resolvers"][gate]``. The subskill→gate / subskill→risk maps
and the registry↔code risk drift come from ``code_maps_extract``.

stdlib + pyyaml + json.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

try:
    from . import code_maps_extract as _cm
    from . import ladder_extract as _ladder
except Exception:  # pragma: no cover - bare-path fallback (matches sibling living modules)
    import code_maps_extract as _cm  # type: ignore
    import ladder_extract as _ladder  # type: ignore

DEFAULT_SKILL = "tumor-presence"

# The optional lanes a user can toggle around the deterministic spine. Curated from the skill's
# SKILL.md command-line flags (the flag table is prose, not structured). Real flag names.
#
# `verdict_inert` is CURATED DISPLAY METADATA rendered as a chip — it is NOT an enforced property.
# The assembler used to hard-error unless every lane was tagged verdict_inert (SK#2091 removed it):
# the tag is a hardcoded True in this very list, so the check asserted its own literal and could
# never fail — a vacuous gate keyed on verdict-inertness. Whether a lane really is off the spine is
# argued where it can bite, in each lane's own skill tests, not by re-reading this constant.
_OPTIONALITY_LANES = [
    {
        "flag": "--synthesize",
        "lane": "LLM narrative",
        "label": "LLM narration",
        "adds": "decision['llm_synthesis'] (prose, sibling key)",
        "note": "Opt-in Bedrock narration. The verdict spine is byte-identical with or without it; "
        "degrades to a _synthesis_error note if Bedrock is unavailable.",
        "verdict_inert": True,
    },
    {
        "flag": "--literature",
        "lane": "literature",
        "label": "Literature lane",
        "adds": "decision['literature_synthesis']",
        "note": "Opt-in retrieval-grounded literature lane, independent of --synthesize. Absent "
        "without the flag; never a gate input.",
        "verdict_inert": True,
    },
    {
        "flag": "--figures",
        "lane": "figures",
        "label": "Figures",
        "adds": "figures/*",
        "note": "Opt-in figure emission. decision.json is byte-identical; figures/ is empty by default.",
        "verdict_inert": True,
    },
    {
        "flag": "--emit-envelope",
        "lane": "emit_mode",
        "label": "Envelope emit mode",
        "adds": "evidence_package.json (beside decision.json)",
        "note": "Additive output surface; the decision spine is unchanged.",
        "verdict_inert": True,
    },
    {
        "flag": "--data-mode / --release-pin",
        "lane": "data_mode",
        "label": "Data-mode / pin",
        "adds": "governance block in the emitted envelope",
        "note": "Carried into the envelope governance block ONLY — inert unless --emit-envelope is set.",
        "verdict_inert": True,
    },
    {
        "flag": "--modality",
        "lane": "modality",
        "label": "Modality lens",
        "adds": "presence_verdict_by_modality projection",
        "note": "Post-hoc modality lens over the same fired rules; the pooled verdict is unchanged.",
        "verdict_inert": True,
    },
    {
        "flag": "--subtypes",
        "lane": "subtype",
        "label": "Subtype panorama",
        "adds": "subtype_presence_panorama (descriptive)",
        "note": "Opt-in descriptive per-subtype panorama; the pooled presence_verdict is byte-stable.",
        "verdict_inert": True,
    },
]

_LEDGER_FILES = {
    "emission_ledger": "coverage/emission_ledger.yaml",
    "summary_field_types": "coverage/summary_field_types.yaml",
    "rule_role_partition": "coverage/rule_role_partition.yaml",
    "wiring_reconciliation": "coverage/wiring_reconciliation.yaml",
}


def load_ledgers(tc_root: str | Path) -> dict:
    """Load the four coverage ledgers the product page joins. Missing/unreadable → empty dict for
    that ledger (the panels degrade to what the graph alone supplies rather than aborting)."""
    tc_root = Path(tc_root)
    out = {}
    for key, rel in _LEDGER_FILES.items():
        p = tc_root / rel
        try:
            out[key] = yaml.safe_load(p.read_text()) or {}
        except Exception:
            out[key] = {}
    return out


def _pinned_enum(tc_root: str | Path, skill: str) -> list[str] | None:
    """The skill's pinned verdict-token enum from ``schemas/_skill_output/pins/<skill>.pins.json``
    (``$defs.*_verdict_enum.enum``). Lives in target-contracts, so it is available even on a
    sibling-free runner. Returns the first ``$defs`` object carrying a string ``enum`` list."""
    p = Path(tc_root) / "schemas" / "_skill_output" / "pins" / f"{skill}.pins.json"
    try:
        pins = json.loads(p.read_text())
    except Exception:
        return None
    string_enums: dict[str, list[str]] = {}
    for name, spec in (pins.get("$defs") or {}).items():
        enum = spec.get("enum") if isinstance(spec, dict) else None
        if isinstance(enum, list) and all(isinstance(e, str) for e in enum):
            string_enums[name] = enum
    if not string_enums:
        return None
    # A pins file may declare several string enums (e.g. surface-modality-fit pins both a
    # ``fit_class_enum`` summary label and the operative ``surface_modality_verdict_enum``). The
    # verdict tokens the resolver emits live in the ``*_verdict_enum`` def — prefer it over the
    # first-declared enum, which would otherwise shadow it with an unrelated class vocabulary.
    for name, enum in string_enums.items():
        if name.endswith("_verdict_enum"):
            return enum
    return next(iter(string_enums.values()))


def _run_py(sk_root: str | Path, skill: str) -> Path:
    return Path(sk_root) / "skills" / skill / "scripts" / "run.py"


def _rule_to_verdict(ladder: dict, graph: dict) -> dict[str, list[str]]:
    """rule_id → the verdict token(s) it drives. For a python-ladder skill each rung is a direct
    (rule_id → verdict); for a resolver-backed skill invert ``graph["resolvers"][gate].verdicts``
    (each ``{verdict, refs:[rule_id,...]}``), where a rule can co-fire into several verdicts."""
    out: dict[str, set[str]] = {}
    if ladder.get("verdict_source") == "python_ladder":
        for rung in ladder.get("rungs") or []:
            out.setdefault(rung["rule_id"], set()).add(rung["verdict"])
    else:
        gate = ladder.get("gate")
        resolver = (graph.get("resolvers") or {}).get(gate) or {}
        for v in resolver.get("verdicts") or []:
            for rid in v.get("refs") or []:
                out.setdefault(rid, set()).add(v.get("verdict"))
    return {rid: sorted(vs) for rid, vs in out.items()}


def _card_datasets(card: dict) -> list[dict]:
    """The card's resolved source datasets, reduced to the provenance the product page shows."""
    rows = []
    for d in card.get("datasets") or []:
        rows.append(
            {
                "resolved_id": d.get("resolved_id"),
                "provider": d.get("provider"),
                "license": d.get("license"),
                "in_catalog": d.get("in_catalog"),
                "resolution": d.get("resolution"),
                "gap_category": d.get("gap_category"),
            }
        )
    return rows


def _field_name(f) -> str | None:
    """A card's ``summary_fields`` entry is either a bare field name (str) or a lens-conditional
    field record (``{"name": ..., "lens_conditional_on": "modality", ...}`` — e.g. the ADC/TCE
    grade fields emitted only under ``--modality``). Reduce either form to the field name so a
    dict entry cannot flow into a dict lookup key (which would raise ``unhashable type``)."""
    if isinstance(f, str):
        return f
    if isinstance(f, dict):
        n = f.get("name")
        return n if isinstance(n, str) else None
    return None


def _field_record(card_id: str, field: str, card: dict, ledgers: dict) -> dict:
    """A summary field with its type, declared vocab, and observed value counts."""
    ftypes = (ledgers.get("summary_field_types") or {}).get("by_card") or {}
    emis = (ledgers.get("emission_ledger") or {}).get("by_card") or {}
    declared = (card.get("vocabulary") or {}).get(field)
    ce = (emis.get(card_id) or {}).get(field) or {}
    return {
        "name": field,
        "type": (ftypes.get(card_id) or {}).get(field),
        "declared": declared,
        "observed": ce.get("observed"),
        "top": ce.get("top"),
        "saturation": ce.get("saturation"),
        "out_of_vocab": ce.get("out_of_vocab") or [],
    }


def _is_live(card_id: str, card: dict, health_cards: dict) -> dict:
    """Live/dark overlay for a card: the atlas per-card ``health`` string plus the richer
    framework-health signals when present."""
    hc = health_cards.get(card_id) or {}
    return {
        "health": card.get("health") or hc.get("card_health"),
        "has_live_reader": hc.get("has_live_reader"),
        "method_call": hc.get("method_call") or (card.get("methods") or [{}])[0].get("call"),
        "fires_in_real_package": hc.get("fires_in_real_package"),
        "is_placeholder": hc.get("is_placeholder"),
    }


def _panel_spine(skill_rec, cards, ladder, r2v, gating_set, ledgers, health_cards, enum) -> dict:
    """Panel 1 — the deterministic spine, per verdict-bearing card of the skill. A card is
    verdict-bearing (spine-relevant) when it owns at least one rule that drives a verdict token
    (a rung of the ladder / a resolver ref) — derived from the actual wiring, not a declared list."""
    ladder_rules = set(r2v)
    rows = []
    for card_id in skill_rec.get("cards_used") or []:
        card = cards.get(card_id) or {}
        card_rules = card.get("rules") or []
        verdict_rule_ids = {r.get("rule_id") for r in card_rules} & ladder_rules
        if not verdict_rule_ids:
            continue  # display-only / comparator card — surfaced in panel 2, not the spine
        rule_rows = []
        fields = set()
        for r in card_rules:
            rid = r.get("rule_id")
            if rid not in ladder_rules:
                continue
            fields.add(r.get("field"))
            rule_rows.append(
                {
                    "rule_id": rid,
                    "field": r.get("field"),
                    "condition": r.get("condition"),
                    "signals": r.get("signals"),
                    "is_killer": r.get("is_killer"),
                    "role": "gating" if rid in gating_set else "display",
                    "verdicts": r2v.get(rid) or [],
                }
            )
        rows.append(
            {
                "card_id": card_id,
                "question": card.get("question"),
                "measurement": card.get("measurement"),
                "measurement_type": card.get("measurement_type"),
                "sample_context": card.get("sample_context"),
                "datasets": _card_datasets(card),
                "methods": [m.get("call") for m in (card.get("methods") or []) if m.get("call")],
                "fields": [_field_record(card_id, f, card, ledgers) for f in sorted(x for x in fields if x)],
                "rules": rule_rows,
                "live": _is_live(card_id, card, health_cards),
            }
        )
    return {
        "verdict_bearing_cards": [r["card_id"] for r in rows],
        "cards": rows,
        "verdict_source": ladder.get("verdict_source"),
        "gate": ladder.get("gate"),
        "verdict_enum": enum,
        "output_shape": skill_rec.get("output_shape"),
        "collapsed_verdict_field": f"{skill_rec.get('name', '').replace('-', '_')}_verdict",
    }


def _panel_card_drilldown(skill_rec, cards, ledgers, health_cards, verdict_card_ids) -> list[dict]:
    """Panel 2 — per-card drill-down for every card the skill composes."""
    wiring = (ledgers.get("wiring_reconciliation") or {}).get("by_card") or {}
    ftypes = (ledgers.get("summary_field_types") or {}).get("by_card") or {}
    rows = []
    for card_id in skill_rec.get("cards_used") or []:
        card = cards.get(card_id) or {}
        raw_fields = card.get("summary_fields") or list((ftypes.get(card_id) or {}).keys())
        field_names = [fn for fn in (_field_name(f) for f in raw_fields) if fn]
        rows.append(
            {
                "card_id": card_id,
                "question": card.get("question"),
                "is_verdict_bearing": card_id in verdict_card_ids,
                "measurement_type": card.get("measurement_type"),
                "fields": [_field_record(card_id, f, card, ledgers) for f in field_names],
                "datasets": _card_datasets(card),
                "live": _is_live(card_id, card, health_cards),
                "wiring": (wiring.get(card_id) or {}).get("confidence"),
                "example_gallery_ref": card_id,  # the worked-example companion renders this card live
            }
        )
    return rows


def _panel_optionality() -> dict:
    """Panel 3 — the deterministic spine vs the optional, off-spine lanes."""
    return {
        "deterministic_spine": "cards → rules → ladder → presence_verdict (byte-stable)",
        "lanes": [dict(k) for k in _OPTIONALITY_LANES],
    }


def _panel_rollup(skill, short, code_maps, axes_q, drift_rows) -> dict:
    """Panel 4 — how the subskill's verdict flows to the nomination: short → gate (or gateless) →
    risk-6dim bin, honest about gateless axes and the registry↔code drift."""
    short_to_gate = code_maps.get("short_to_gate") or {}
    axis_to_dim = code_maps.get("axis_to_dim") or {}
    context_dim = code_maps.get("context_dim") or {}
    exclusions = code_maps.get("axis_dim_exclusions") or {}
    gate = short_to_gate.get(short)
    if short in axis_to_dim:
        risk_dim, risk_source = axis_to_dim[short], "AXIS_TO_DIM"
    elif short in context_dim:
        risk_dim, risk_source = context_dim[short], "_CONTEXT_DIM"
    else:
        risk_dim, risk_source = None, None
    return {
        "short": short,
        "gate": gate,
        "gateless": gate is None,
        "band": (axes_q or {}).get("band"),
        "risk_dim": risk_dim,
        "risk_source": risk_source,
        "exclusion_state": exclusions.get(short),
        "registry_risk_category": (axes_q or {}).get("risk_category"),
        "foreign_consumers": (axes_q or {}).get("foreign_consumers") or [],
        "drift": next((d for d in drift_rows if d.get("short") == short), None),
    }


def _panel_cards_questions(skill, axes_registry, mtype_to_cards) -> dict:
    """Panel 5 — the question hierarchy: axis → sub-group → question → measurement_type → card."""
    hier = (axes_registry.get("question_hierarchies") or {}).get(skill) or {}

    def _mt_rows(mts):
        return [{"measurement_type": mt, "cards": mtype_to_cards.get(mt, [])} for mt in (mts or [])]

    sub_groups = []
    for sg in hier.get("sub_groups") or []:
        sub_groups.append(
            {
                "id": sg.get("id"),
                "claim_axes": sg.get("claim_axes"),
                "context_types": sg.get("context_types"),
                "questions": [
                    {
                        "id": q.get("id"),
                        "role": q.get("role"),
                        "measurement_types": _mt_rows(q.get("measurement_types")),
                    }
                    for q in sg.get("questions") or []
                ],
            }
        )
    other_lenses = [
        {"lens": ol.get("lens"), "measurement_types": _mt_rows(ol.get("measurement_types"))}
        for ol in hier.get("other_lenses") or []
    ]
    return {"axis": hier.get("axis"), "sub_groups": sub_groups, "other_lenses": other_lenses}


def build(graph, health, ledgers, axes_registry, skill, *, sk_root=None, tc_root=None) -> dict:
    """Assemble the five-panel product block for one subskill. See module docstring."""
    cards = graph.get("cards") or {}
    skills = graph.get("skills") or {}
    skill_rec = dict(skills.get(skill) or {})
    skill_rec.setdefault("name", skill)

    health_cards = {c.get("card_id"): c for c in (health or {}).get("cards") or []}
    gating_set = set(((ledgers.get("rule_role_partition") or {}).get("gating")) or [])

    code_maps = _cm.extract_code_maps(sk_root) if sk_root else {"errors": ["no sk_root"]}
    short = next((s["short"] for s in code_maps.get("sub_skills") or [] if s["skill"] == skill), None)

    enum = _pinned_enum(tc_root, skill) if tc_root else None
    run_py = _run_py(sk_root, skill) if sk_root else None
    graph_rule_ids = {r.get("rule_id") for c in cards.values() for r in (c.get("rules") or [])}
    if run_py and run_py.exists():
        ladder = _ladder.extract_ladder(run_py, enum=enum, graph_rule_ids=graph_rule_ids)
    else:
        ladder = {"verdict_source": None, "gate": None, "ladders": [], "rungs": [], "errors": ["run.py absent"]}

    r2v = _rule_to_verdict(ladder, graph)

    # Honesty cross-check for the reclassified "no verdict source" bucket: a skill whose short is
    # a GATING axis (present in the code-map's _SHORT_TO_GATE) MUST have resolved a gate / ladder.
    # If it did not, we mis-parsed a real verdict source — surface it rather than silently letting
    # a gating skill degrade to a clean gateless block (a false green). A gateless / support skill
    # (short absent from _SHORT_TO_GATE) legitimately carries no verdict source and is NOT flagged.
    verdict_source_errors: list[str] = []
    gating_gate = (code_maps.get("short_to_gate") or {}).get(short)
    if gating_gate and ladder.get("verdict_source") is None:
        verdict_source_errors.append(
            f"{skill}: short '{short}' is a gating axis (gate '{gating_gate}') but no verdict "
            "ladder or resolver gate was recovered from run.py"
        )

    # measurement_type → card_ids (for panel 5's bottom join)
    mtype_to_cards: dict[str, list[str]] = {}
    for cid, c in cards.items():
        mt = c.get("measurement_type")
        if mt:
            mtype_to_cards.setdefault(mt, []).append(cid)
    for v in mtype_to_cards.values():
        v.sort()

    axes_registry = axes_registry or {}
    axes_q = next((q for q in axes_registry.get("questions") or [] if q.get("short") == short), None)
    drift_rows = _cm.risk_drift(code_maps, axes_registry)

    spine = _panel_spine(skill_rec, cards, ladder, r2v, gating_set, ledgers, health_cards, enum)
    verdict_card_ids = set(spine["verdict_bearing_cards"])

    return {
        "skill": skill,
        "short": short,
        "status": skill_rec.get("status"),
        "phase": skill_rec.get("phase"),
        "n_cards": len(skill_rec.get("cards_used") or []),
        "verdict_source": ladder.get("verdict_source"),
        "ladder": ladder,
        "panels": {
            "spine": spine,
            "card_drilldown": _panel_card_drilldown(skill_rec, cards, ledgers, health_cards, verdict_card_ids),
            "optionality": _panel_optionality(),
            "rollup": _panel_rollup(skill, short, code_maps, axes_q, drift_rows),
            "cards_questions": _panel_cards_questions(skill, axes_registry, mtype_to_cards),
        },
        "errors": (ladder.get("errors") or []) + verdict_source_errors + (code_maps.get("errors") or []),
    }


def build_product_pages(graph, health, axes_registry, *, tc_root, sk_root, skills=(DEFAULT_SKILL,)) -> dict:
    """Build product blocks for the given skills + the skill-invariant registry↔code risk drift.

    Attached by ``build_living_doc.assemble()`` as ``graph["product_page"]``::

        {"skills": {skill: block, ...}, "risk_drift": [...], "default_skill": ...}
    """
    ledgers = load_ledgers(tc_root)
    code_maps = _cm.extract_code_maps(sk_root)
    by_skill = {s: build(graph, health, ledgers, axes_registry, s, sk_root=sk_root, tc_root=tc_root) for s in skills}
    return {
        "skills": by_skill,
        "risk_drift": _cm.risk_drift(code_maps, axes_registry or {}),
        "default_skill": DEFAULT_SKILL if DEFAULT_SKILL in by_skill else (next(iter(by_skill), None)),
    }
