"""rollup.py — deterministic first-match health verdict + drift flags.

Consumes the derived probe signals (probe.py) and the declarative ladders
(health_rules.yaml) and produces, per skill: a card_health per consumed card, a
set of drift_flags (declared-vs-derived mismatches), and a rolled-up
health_verdict + health_reason (the matched rule id — the driving_rule_id analogue).

The interpreter holds NO verdict thresholds: precedence and conditions live in
health_rules.yaml, exactly as the resolver interpreter defers to resolver YAMLs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import probe

_RULES_PATH = Path(__file__).resolve().parent / "health_rules.yaml"

# Drift codes and their severity. error-severity drift forces broken_or_drift.
DRIFT_SEVERITY = {
    "status_wired_no_entrypoint": "error",
    "status_wired_card_broken": "error",
    "skillmd_cites_nonexistent_entrypoint": "error",
    "declared_cards_mismatch_runpy": "warn",
    "fanout_count_mismatch": "warn",
    "missing_status_field": "warn",
    "card_registered_never_fires": "info",
    "stale_method_label": "info",
    "dataset_ref_not_in_catalog": "warn",
    "card_consumed_but_no_spec": "warn",
}


# ---------------------------------------------------------------------------
# Condition matcher (shared by both ladders)
# ---------------------------------------------------------------------------
def _get(ctx: dict, dotted: str) -> Any:
    cur: Any = ctx
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _match(cond: dict, ctx: dict) -> bool:
    """Evaluate one condition dict against a flat/nested context.

    Empty dict {} always matches (the fallback rung). Supports all/any nesting
    and the <key>, <key>__in, <key>__truthy operators.
    """
    if not cond:
        return True
    for key, val in cond.items():
        if key == "all":
            if not all(_match(c, ctx) for c in val):
                return False
        elif key == "any":
            if not any(_match(c, ctx) for c in val):
                return False
        elif key.endswith("__in"):
            if _get(ctx, key[:-4]) not in val:
                return False
        elif key.endswith("__truthy"):
            if bool(_get(ctx, key[:-8])) != bool(val):
                return False
        else:
            if _get(ctx, key) != val:
                return False
    return True


def _resolve(ladder: list[dict], ctx: dict) -> tuple[str, str]:
    """First-match-wins over an ordered ladder → (verdict, rule_id)."""
    for rung in ladder:
        if _match(rung.get("when", {}), ctx):
            return rung["verdict"], rung["id"]
    return "partial", "no-rung-matched"


def load_rules() -> dict:
    return yaml.safe_load(_RULES_PATH.read_text())


# ---------------------------------------------------------------------------
# Card + skill roll-up
# ---------------------------------------------------------------------------
def roll_up_card(card_signals: dict, rules: dict) -> dict:
    verdict, reason_id = _resolve(rules["card_health"], card_signals)
    reason_text = next(
        (r["reason"] for r in rules["card_health"] if r["id"] == reason_id), ""
    )
    return {**card_signals, "card_health": verdict, "health_reason": reason_id, "reason_text": reason_text}


def compute_drift(skill: dict, cards: list[dict], spec_cards: dict | None = None) -> list[dict]:
    """Declared-vs-derived mismatches. Each flag: {code, severity, detail}."""
    flags: list[dict] = []
    dec, der = skill["declared"], skill["derived"]
    spec_cards = spec_cards or {}

    def add(code: str, detail: str) -> None:
        flags.append({"code": code, "severity": DRIFT_SEVERITY.get(code, "info"), "detail": detail})

    declared_wired = (dec.get("status") == "wired") or ("wired" in (dec.get("prose_markers") or [])
                                                         and dec.get("status") not in ("not_wired", "partial"))

    # status:wired but no entrypoint
    if declared_wired and not der["has_entrypoint"]:
        add("status_wired_no_entrypoint", "declared wired but scripts/run.py is absent")

    # status:wired but a consumed card is broken
    if declared_wired:
        broken = [c["card_id"] for c in cards if c.get("card_health") == "broken"]
        if broken:
            add("status_wired_card_broken",
                f"declared wired but consumed card(s) broken: {', '.join(sorted(broken))}")

    # declared cards_used vs run.py CARDS mismatch (COMPOSED skills use SUB_SKILL_CARDS, skip)
    if der["kind"] == "FOCUSED":
        used = set(dec.get("cards_used") or [])
        runpy = set(der.get("cards_in_runpy") or [])
        if used and runpy and used != runpy:
            only_used = sorted(used - runpy)
            only_runpy = sorted(runpy - used)
            add("declared_cards_mismatch_runpy",
                f"SKILL.md cards_used vs run.py CARDS differ (only in SKILL.md: {only_used}; only in run.py: {only_runpy})")

    # missing status field entirely (has an entrypoint + composition but no status)
    if der["has_entrypoint"] and dec.get("status") is None and der["kind"] not in ("PLACEHOLDER",):
        add("missing_status_field", "no machine-readable status: field in SKILL.md frontmatter")

    # card registered in live map but never fires (info-level, surfaced per skill)
    never = [c["card_id"] for c in cards
             if c.get("has_live_reader") and not c.get("fires_in_real_package")
             and c.get("card_health") != "broken"]
    if never:
        add("card_registered_never_fires",
            f"consumed card(s) have a live reader but never fired in a real package: {', '.join(sorted(never))}")

    # Stale methods.call label: the card claims a method the dispatcher does not import.
    stale = [c["card_id"] for c in cards if c.get("stale_method_label")]
    if stale:
        add("stale_method_label",
            f"card methods.call label differs from the dispatcher's actual import: {', '.join(sorted(stale))}")

    # Broken data reference: a consumed card names a product_id absent from the catalog.
    missing_ds = sorted({d["product_id"] for c in cards for d in c.get("datasets", [])
                         if not d.get("in_catalog")})
    if missing_ds:
        add("dataset_ref_not_in_catalog",
            f"consumed card(s) reference dataset product_id(s) not in the data-catalog: {', '.join(missing_ds)}")

    # Spec-coverage gap: cards this skill consumes that are in NO dashboard_spec, so
    # they can never fire in an emitted package (the emission path pulls from a spec).
    # Only flag cards that actually EXIST (a missing/placeholder card is a different
    # problem already surfaced). This is the skill/spec divergence.
    no_spec = sorted({c["card_id"] for c in cards
                      if c.get("card_yaml_exists") and not c.get("is_placeholder")
                      and c["card_id"] not in spec_cards})
    if no_spec:
        add("card_consumed_but_no_spec",
            f"consumed card(s) are in NO dashboard_spec — cannot fire in an emitted "
            f"package until added to a spec: {', '.join(no_spec)}")

    return flags


def roll_up_skill(skill: dict, cards: list[dict], drift: list[dict], rules: dict) -> dict:
    """Assemble the skill node + its rolled-up verdict."""
    der = skill["derived"]
    unhealthy = [c for c in cards if c.get("card_health") in ("broken", "placeholder", "blocked", "partial")]

    # CORE cards = the verdict-driving subset (rules_scope). Cards in cards_used but
    # NOT rules_scope are additive/verdict-inert facets (biomarker facets, confidence
    # meta) whose not-yet-firing must NOT sink an otherwise-wired skill. If rules_scope
    # is empty, every consumed card counts as core.
    scope = set(skill["declared"].get("rules_scope") or [])
    core = [c for c in cards if (not scope) or (c["card_id"] in scope)]
    # "healthy" for a core card = live OR partial (reader exists, just no real package
    # yet) — but NOT broken/placeholder/blocked. This tolerates the thin-data frontier
    # while still catching genuine breakage.
    core_cards_healthy = bool(core) and all(
        c.get("card_health") in ("live", "partial") for c in core
    )
    # PROVEN vs UNPROVEN: has at least one core card actually FIRED in a real
    # package (card_health == live)? If cores are all "partial" (readers work but
    # nothing has fired end-to-end yet), the skill is ready-but-unproven, not proven.
    core_cards_fired = any(c.get("card_health") == "live" for c in core)

    ctx = {
        **skill,
        "has_error_drift": any(d["severity"] == "error" for d in drift),
        "has_unhealthy_cards": len(unhealthy) > 0,
        "core_cards_healthy": core_cards_healthy,
        "core_cards_fired": core_cards_fired,
        "consumes_cards": len(cards) > 0,
        "has_tests": der.get("test_count", 0) > 0,
    }
    verdict, reason_id = _resolve(rules["skill_health"], ctx)
    reason_text = next((r["reason"] for r in rules["skill_health"] if r["id"] == reason_id), "")

    return {
        "name": skill["name"],
        "declared": skill["declared"],
        "derived": der,
        "cards": cards,
        "n_core_cards": len(core),
        "n_cards": len(cards),
        "n_cards_live": sum(1 for c in cards if c.get("card_health") == "live"),
        "drift_flags": drift,
        "health_verdict": verdict,
        "health_reason": reason_id,
        "reason_text": reason_text,
    }


# ---------------------------------------------------------------------------
# Top-level assembly
# ---------------------------------------------------------------------------
def build_health(roots: dict[str, Path]) -> dict:
    """Probe every skill + its cards, roll up, and assemble the full report body.

    Returns the report WITHOUT volatile envelope fields (generated_at, git-shas)
    — the CLI adds those so --check can compare a stable projection.
    """
    rules = load_rules()
    skills_dir = roots["skills"] / "skills"

    live_ids = set(probe.live_reader_card_ids(roots["skills"]))
    dispatch_modules = probe.dispatcher_method_imports(roots["skills"])
    fired_ids = probe.fired_card_ids(roots["products"])
    ss_map = probe.sub_skill_map(roots["skills"])           # skill_dir -> short
    gcov = probe.gate_coverage_by_short(roots["contracts"])  # short -> coverage entry
    catalog = probe.catalog_manifests(roots["catalog"])      # product_id -> manifest meta
    catalog_ids = set(catalog)
    spec_cards = probe.dashboard_spec_card_ids(roots["contracts"])  # card_id -> [spec names]

    skill_names = probe.list_skill_names(roots["skills"])

    skill_nodes: list[dict] = []
    for name in skill_names:
        sig = probe.probe_skill(skills_dir / name)
        # Cards a skill consumes: union of declared cards_used + run.py CARDS.
        card_ids = sorted(set(sig["declared"].get("cards_used") or [])
                          | set(sig["derived"].get("cards_in_runpy") or []))
        cards = [
            roll_up_card(
                probe.probe_card(cid, roots["contracts"], roots["methods"],
                                 live_ids, fired_ids, dispatch_modules, catalog_ids),
                rules,
            )
            for cid in card_ids
        ]
        drift = compute_drift(sig, cards, spec_cards)
        node = roll_up_skill(sig, cards, drift, rules)
        # Attach risk_category / coverage via the short mapping (for matrix grouping).
        short = ss_map.get(name)
        node["gate_short"] = short
        node["risk_category"] = (gcov.get(short) or {}).get("risk_category") if short else None
        node["framework_can_evidence"] = (gcov.get(short) or {}).get("framework_can_evidence") if short else None
        skill_nodes.append(node)

    reg = probe.registry_drift(roots["skills"], skill_names)

    # -----------------------------------------------------------------------
    # CARD-CENTRIC view: every card ONCE, deduped, joined to consuming skills.
    # Universe = cards on disk ∪ every card any skill consumes. A card on disk
    # that no skill consumes is an ORPHAN (invisible in the skill matrix — the
    # card-side dual of an unregistered skill / the pull-model's "unclaimed
    # measurement" signal). A consumed id with no card on disk is a broken ref.
    # -----------------------------------------------------------------------
    consumers: dict[str, list[str]] = {}
    for n in skill_nodes:
        for c in n["cards"]:
            consumers.setdefault(c["card_id"], []).append(n["name"])

    disk_ids = set(probe.list_all_card_ids(roots["contracts"]))
    universe = sorted(disk_ids | set(consumers))

    card_nodes: list[dict] = []
    for cid in universe:
        cn = roll_up_card(
            probe.probe_card(cid, roots["contracts"], roots["methods"],
                             live_ids, fired_ids, dispatch_modules, catalog_ids),
            rules,
        )
        cn["consumers"] = sorted(consumers.get(cid, []))
        cn["n_consumers"] = len(cn["consumers"])
        cn["is_orphan"] = (cn["n_consumers"] == 0)  # on disk but pulled by no skill
        cn["dashboard_specs"] = sorted(spec_cards.get(cid, []))
        cn["in_dashboard_spec"] = bool(cn["dashboard_specs"])
        # Coverage gap: a card consumed by ≥1 skill but in NO dashboard_spec can
        # never fire in an emitted package (emission pulls from a spec). Distinct
        # from "unfired-but-in-spec" — this is a spec/skill divergence, not a run gap.
        cn["consumed_but_no_spec"] = (cn["n_consumers"] > 0 and not cn["in_dashboard_spec"])
        card_nodes.append(cn)

    card_tally: dict[str, int] = {}
    for c in card_nodes:
        card_tally[c["card_health"]] = card_tally.get(c["card_health"], 0) + 1

    # -----------------------------------------------------------------------
    # DATASET-CENTRIC view: every data product (catalog manifest ∪ every
    # product_id a card references), joined to the cards that pull it.
    #   - referenced + in catalog                → ok
    #   - referenced but NOT in catalog          → broken data reference (drift)
    #   - in catalog but referenced by no card   → ORPHAN dataset (unused ingest)
    # -----------------------------------------------------------------------
    # Key each reference by its RESOLVED catalog id (prefix matches collapse onto
    # their real manifest) so a version-suffix convention isn't miscounted as broken.
    ds_consumers: dict[str, list[str]] = {}
    for c in card_nodes:
        for d in c.get("datasets", []):
            key = d.get("resolved_id") or d["product_id"]
            ds_consumers.setdefault(key, []).append(c["card_id"])

    ds_universe = sorted(set(catalog) | set(ds_consumers))
    dataset_nodes: list[dict] = []
    for pid in ds_universe:
        meta = catalog.get(pid) or {}
        consumers = sorted(set(ds_consumers.get(pid, [])))
        in_cat = pid in catalog
        dataset_nodes.append({
            "product_id": pid,
            "in_catalog": in_cat,
            "kind": meta.get("kind"),
            "provider": meta.get("provider"),
            "version": meta.get("version"),
            "size_bytes": meta.get("size_bytes"),
            "file_count": meta.get("file_count"),
            "system_of_record": meta.get("system_of_record"),
            "n_derived_from": len(meta.get("derived_from") or []),
            "consumed_by_cards": consumers,
            "n_consumers": len(consumers),
            "is_orphan": in_cat and not consumers,       # cataloged, no card pulls it
            "is_broken_ref": (not in_cat) and bool(consumers),  # a card names a missing dataset
        })

    graph = build_graph(skill_nodes, card_nodes)

    # Verdict tallies + drift roll-up for the summary header.
    tally: dict[str, int] = {}
    for n in skill_nodes:
        tally[n["health_verdict"]] = tally.get(n["health_verdict"], 0) + 1
    all_drift = [
        {"skill": n["name"], **d}
        for n in skill_nodes for d in n["drift_flags"]
    ]

    return {
        "summary": {
            "n_skills": len(skill_nodes),
            "verdict_tally": tally,
            "n_drift_flags": len(all_drift),
            "n_error_drift": sum(1 for d in all_drift if d["severity"] == "error"),
            "n_unregistered_skills": len(reg["unregistered"]),
            "n_live_reader_cards": len(live_ids),
            "n_cards_firing_in_real_packages": len(fired_ids),
            "n_cards": len(card_nodes),
            "card_health_tally": card_tally,
            "n_orphan_cards": sum(1 for c in card_nodes if c["is_orphan"]),
            "n_cards_consumed_but_no_spec": sum(1 for c in card_nodes if c.get("consumed_but_no_spec")),
            "n_datasets": len(dataset_nodes),
            "n_datasets_in_catalog": sum(1 for d in dataset_nodes if d["in_catalog"]),
            "n_orphan_datasets": sum(1 for d in dataset_nodes if d["is_orphan"]),
            "n_broken_dataset_refs": sum(1 for d in dataset_nodes if d["is_broken_ref"]),
        },
        "registry_drift": reg,
        "skills": skill_nodes,
        "cards": card_nodes,
        "datasets": dataset_nodes,
        "graph": graph,
        "drift_index": all_drift,
    }


# ---------------------------------------------------------------------------
# Graph section (Option A: layered flow Skills | Resolvers | Cards | Methods).
# A pure transform of the skill+card nodes — NO new probing. Emitted as plain
# nodes+edges data so self_check can verify every edge endpoint resolves to a
# node (a dangling edge is drift), and the SVG layout stays a pure render.
# ---------------------------------------------------------------------------
# Layer index fixes left→right column order (data flows verdict←…←data).
_LAYERS = {"skill": 0, "resolver": 1, "card": 2, "method": 3}


def build_graph(skill_nodes: list[dict], card_nodes: list[dict]) -> dict:
    nodes: dict[str, dict] = {}   # id -> node (dedup)
    edges: list[dict] = []

    def add_node(nid: str, layer: str, label: str, health: str | None = None, meta: dict | None = None):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "layer": layer, "label": label,
                          "health": health, **(meta or {})}

    # Skills + their resolver edge.
    for n in skill_nodes:
        sid = f"skill:{n['name']}"
        add_node(sid, "skill", n["name"], n["health_verdict"],
                 {"kind": n["derived"].get("kind"), "risk_category": n.get("risk_category")})
        gate = n["derived"].get("resolver_gate")
        if gate:
            rid = f"resolver:{gate}"
            add_node(rid, "resolver", gate,
                     "live" if n["derived"].get("resolver_bound") else "broken")
            edges.append({"src": sid, "dst": rid, "rel": "resolves_via"})

    # Cards + method backing + card→consuming-skill edges.
    for c in card_nodes:
        cid = f"card:{c['card_id']}"
        add_node(cid, "card", c["card_id"], c["card_health"],
                 {"is_orphan": c.get("is_orphan", False),
                  "measurement_type": c.get("measurement_type")})
        for sk in c.get("consumers", []):
            edges.append({"src": f"skill:{sk}", "dst": cid, "rel": "consumes"})
        mod = c.get("dispatch_module")
        if mod:
            top = mod.split(".")[0]                # strip .read/.cli suffix
            mid = f"method:{top}"
            add_node(mid, "method", top,
                     "live" if c.get("method_dir_exists") else "broken")
            edges.append({"src": cid, "dst": mid, "rel": "backed_by"})

    # Deterministic ordering: by (layer, id) for nodes, by tuple for edges.
    node_list = sorted(nodes.values(), key=lambda n: (_LAYERS.get(n["layer"], 9), n["id"]))
    edge_list = sorted(edges, key=lambda e: (e["src"], e["dst"], e["rel"]))
    # De-dupe edges (a method backing many cards can repeat skill→card→method chains).
    seen = set(); deduped = []
    for e in edge_list:
        k = (e["src"], e["dst"], e["rel"])
        if k not in seen:
            seen.add(k); deduped.append(e)

    counts = {layer: sum(1 for n in node_list if n["layer"] == layer) for layer in _LAYERS}
    return {"nodes": node_list, "edges": deduped,
            "layer_counts": counts, "n_nodes": len(node_list), "n_edges": len(deduped)}
