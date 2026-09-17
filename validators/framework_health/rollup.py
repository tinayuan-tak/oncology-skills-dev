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
    # RETIRED 2026-09-11 — `card_consumed_but_no_spec`. It was demoted warn->info on
    # 2026-08-05 for drowning the actionable warns, but its PREMISE was never tested and is
    # FALSE: it asserted a consumed card "can never fire in an emitted package until added to
    # a dashboard_spec". Adjudicated against the live emission path, three ways:
    #   1. FALSIFIED BY THE FEED'S OWN DATA — 67 of the 102 flagged cards carry
    #      fires_in_real_package=true, i.e. they already validated pass/passed_with_warnings
    #      inside committed evidence packages while in NO spec. The flag's claim is not merely
    #      pessimistic, it contradicts observed firings.
    #   2. NO EMISSION PATH READS A SPEC — `load_dashboard_spec()` has ZERO callers across all
    #      five repos, and the live emitters (skills _skills_common/dispatcher.py and
    #      target-profile/scripts/tp_evidence_package.py) stamp dashboard_spec_ref="skill:<name>",
    #      a synthetic literal that is never a dashboard_id. Card-set determination comes from
    #      SUB_SKILL_CARDS / cards_used.
    #   3. THE PREMISE IS AN ARTIFACT OF A RETIRED ENGINE — spec-driven card admission belonged
    #      to compose-dashboard (see skills _skills_common/compose_core.py's card-set-determination
    #      note, and envelope.py on the axis_resolution/selected_base_dashboard structure "that
    #      only compose-dashboard has"). compose-dashboard was retired 2026-08-20 (#654).
    # The 35 flagged cards that have NOT fired are not emission gaps either: 33 are status:wired
    # but not yet exercised (most without a live reader), 1 placeholder, 1 self-produced — a state
    # already reported honestly by has_live_reader / fires_in_real_package / card_health, and by
    # `card_registered_never_fires` above, which asks the same question with the CORRECT condition
    # (has a live reader AND did not fire). So this code was redundant where it was right and
    # wrong where it was loud: 17 of the framework's 23 open drift flags, all false.
    # The DESCRIPTIVE card fields (in_dashboard_spec / dashboard_specs / consumed_but_no_spec) are
    # retained — "this card is in no spec" is a true statement about spec coverage — but they no
    # longer raise drift, and the Cards tab no longer claims they cannot fire.
    # P4 modality-vector lens. WARN (not error) deliberately: validate_cards.py already ENFORCES
    # these at commit time (missing=error, drift=warning) and blocks merge, so a healthy repo never
    # carries them. The dashboard is a VISIBILITY layer, not a second enforcer — warn surfaces P4
    # hygiene without flipping skill_health to broken_or_drift (which would couple skill LIVENESS to
    # routing metadata, violating the P4-is-parallel-to-verdict-spine invariant).
    "modality_relevance_missing": "warn",
    "modality_relevance_drift": "warn",
}


# ---------------------------------------------------------------------------
# STATIC access-cost lens (NO network, NO timing — a structural proxy for "how
# expensive is this dataset to access", derived purely from manifest metadata).
# Deliberately NOT a live read: the dashboard's whole contract is offline +
# deterministic + checkout-only-CI + --check-stable. Real latency is a runtime-
# observability concern (would need durations emitted into evidence-package
# provenance first — see the access-cost plan). This lens answers the adjacent,
# statically-answerable question: which consumed data is big/unoptimized to query.
# ---------------------------------------------------------------------------
_GB = 1024**3
_SORT_KEY_SIZE_FLOOR = 1 * _GB  # below this, a missing sort-key isn't worth flagging
_ACCESS_COST_HIGH_GB = 20  # >= → high (a heavy dataset)
_ACCESS_COST_MODERATE_GB = 2  # >= → moderate


def _tally(nodes: list[dict], key: str) -> dict[str, int]:
    """Count nodes by a string field value (skips None)."""
    out: dict[str, int] = {}
    for n in nodes:
        v = n.get(key)
        if v is not None:
            out[v] = out.get(v, 0) + 1
    return out


def _access_cost(size_bytes, file_count, n_consumers) -> str:
    """Static access-cost band from size (+ file-count sprawl), scoped to whether anything
    consumes it. Returns high|moderate|low|negligible|unknown. Pure metadata arithmetic —
    a large, many-file, widely-consumed dataset is where an access optimization pays off."""
    if not size_bytes:
        return "unknown"
    gb = size_bytes / _GB
    # file sprawl bumps cost: many small files = many S3 round-trips even at modest size.
    sprawl = (file_count or 0) >= 2000
    if gb >= _ACCESS_COST_HIGH_GB or (sprawl and gb >= _ACCESS_COST_MODERATE_GB):
        band = "high"
    elif gb >= _ACCESS_COST_MODERATE_GB or sprawl:
        band = "moderate"
    else:
        band = "low"
    # An unconsumed dataset's access cost is not a framework concern — downgrade the label
    # so hotspot ranking surfaces CONSUMED heavy data, not idle catalog bulk.
    if n_consumers == 0 and band in ("high", "moderate"):
        return band + "_unused"
    return band


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
    """First-match-wins over an ordered ladder → (verdict, rule_id).

    Both ladders in health_rules.yaml END in a `when: {}` catch-all, so a match is
    guaranteed. If that catch-all is ever removed we want a LOUD failure, not a
    silent degrade to a made-up "partial" verdict — that would let an unclassified
    component quietly read healthy. Hence raise rather than return a default.
    """
    for rung in ladder:
        if _match(rung.get("when", {}), ctx):
            return rung["verdict"], rung["id"]
    raise ValueError(
        "no health-rule rung matched — the ladder is missing its `when: {}` "
        "catch-all (health_rules.yaml). Refusing to invent a default verdict."
    )


def load_rules() -> dict:
    return yaml.safe_load(_RULES_PATH.read_text())


# ---------------------------------------------------------------------------
# Card + skill roll-up
# ---------------------------------------------------------------------------
def roll_up_card(card_signals: dict, rules: dict) -> dict:
    verdict, reason_id = _resolve(rules["card_health"], card_signals)
    reason_text = next((r["reason"] for r in rules["card_health"] if r["id"] == reason_id), "")
    return {**card_signals, "card_health": verdict, "health_reason": reason_id, "reason_text": reason_text}


def compute_drift(skill: dict, cards: list[dict]) -> list[dict]:
    """Declared-vs-derived mismatches. Each flag: {code, severity, detail}.

    Took a `spec_cards` map until 2026-09-11, when the only flag that consumed it
    (`card_consumed_but_no_spec`) was retired as a false-alarm class — see DRIFT_SEVERITY.
    Dropped rather than left ignored so no future reader has to re-adjudicate whether it
    is load-bearing. Spec coverage is still reported on the card nodes.
    """
    flags: list[dict] = []
    dec, der = skill["declared"], skill["derived"]

    def add(code: str, detail: str) -> None:
        flags.append({"code": code, "severity": DRIFT_SEVERITY.get(code, "info"), "detail": detail})

    declared_wired = (dec.get("status") == "wired") or (
        "wired" in (dec.get("prose_markers") or []) and dec.get("status") not in ("not_wired", "partial")
    )

    # status:wired but no entrypoint
    if declared_wired and not der["has_entrypoint"]:
        add("status_wired_no_entrypoint", "declared wired but scripts/run.py is absent")

    # status:wired but a consumed card is broken
    if declared_wired:
        broken = [c["card_id"] for c in cards if c.get("card_health") == "broken"]
        if broken:
            add("status_wired_card_broken", f"declared wired but consumed card(s) broken: {', '.join(sorted(broken))}")

    # declared cards_used vs run.py CARDS mismatch (COMPOSED skills use SUB_SKILL_CARDS, skip)
    if der["kind"] == "FOCUSED":
        used = set(dec.get("cards_used") or [])
        runpy = set(der.get("cards_in_runpy") or [])
        if used and runpy and used != runpy:
            only_used = sorted(used - runpy)
            only_runpy = sorted(runpy - used)
            add(
                "declared_cards_mismatch_runpy",
                f"SKILL.md cards_used vs run.py CARDS differ (only in SKILL.md: {only_used}; only in run.py: {only_runpy})",
            )

    # missing status field entirely (has an entrypoint + composition but no status)
    if der["has_entrypoint"] and dec.get("status") is None and der["kind"] not in ("PLACEHOLDER",):
        add("missing_status_field", "no machine-readable status: field in SKILL.md frontmatter")

    # card registered in live map but never fires ANYWHERE (info-level, surfaced per skill).
    #
    # Reads fires_in_any_run (governed packages UNION exploratory skill-runs), NOT the governed-only
    # fires_in_real_package. The claim this flag makes is "has a reader but has never been shown to
    # work end-to-end", and a single exploratory run that emits the card with validation_state=pass
    # falsifies exactly that. Using the governed-only signal reported 8 cards as dead that were
    # provably live in the 2026-09-11 panel (immune-context → immune_intermediate, surface-bulk-pair-
    # selectivity → selective_but_broad_tissue_liability, ...), and whose interpretation rules appear
    # in that run's fired-rule list. fires_in_real_package stays governed-only and byte-stable for
    # the coverage/promotion accounting that legitimately means "concurrence-reviewed".
    never = [
        c["card_id"]
        for c in cards
        if c.get("has_live_reader")
        and not (c.get("fires_in_any_run") or c.get("fires_in_real_package"))
        and c.get("card_health") != "broken"
    ]
    if never:
        add(
            "card_registered_never_fires",
            f"consumed card(s) have a live reader but never fired in any real run "
            f"(governed or exploratory): {', '.join(sorted(never))}",
        )

    # Stale methods.call label: the card claims a method the dispatcher does not import.
    stale = [c["card_id"] for c in cards if c.get("stale_method_label")]
    if stale:
        add(
            "stale_method_label",
            f"card methods.call label differs from the dispatcher's actual import: {', '.join(sorted(stale))}",
        )

    # Broken data reference: a consumed card names a product_id absent from the catalog.
    missing_ds = sorted({d["product_id"] for c in cards for d in c.get("datasets", []) if not d.get("in_catalog")})
    if missing_ds:
        add(
            "dataset_ref_not_in_catalog",
            f"consumed card(s) reference dataset product_id(s) not in the data-catalog: {', '.join(missing_ds)}",
        )

    # Spec-coverage: NO drift flag is raised for "consumed but in no dashboard_spec" — see the
    # RETIRED note in DRIFT_SEVERITY for the adjudication (the emission path does not read a spec,
    # and 67 of the 102 formerly-flagged cards had already fired inside real packages). Spec
    # coverage is still REPORTED per card (in_dashboard_spec / dashboard_specs), and the honest
    # "consumed but not proven live" question is asked by `card_registered_never_fires` above.

    # P4 modality-vector: a consumed card whose measurement_type ROUTES to a modality-fit gate
    # but does not declare modality_relevance is stranded on the biology axis (mirrors the
    # commit-time validator's MODALITY_RELEVANCE_MISSING error). Declared-but-out-of-subset is
    # drift (validator warning). Skips the `unknown` verdict (vocab-absent isolated checkout).
    mr_missing = sorted({c["card_id"] for c in cards if c.get("modality_routing") == "missing"})
    if mr_missing:
        add(
            "modality_relevance_missing",
            f"consumed card(s) route to a modality-fit gate but declare no modality_relevance "
            f"(stranded on the biology axis; P4): {', '.join(mr_missing)}",
        )
    mr_drift = sorted({c["card_id"] for c in cards if c.get("modality_routing") == "drift"})
    if mr_drift:
        add(
            "modality_relevance_drift",
            f"consumed card(s) declare modality_relevance values outside their measurement_type's "
            f"routing set: {', '.join(mr_drift)}",
        )

    return flags


def roll_up_skill(skill: dict, cards: list[dict], drift: list[dict], rules: dict) -> dict:
    """Assemble the skill node + its rolled-up verdict."""
    der = skill["derived"]
    # `wired` is the reader-exists-never-fired state formerly labeled `partial` (split out 2026-08-31
    # so the tally stops reading it as a defect); it is treated IDENTICALLY to `partial` in every
    # skill-rollup signal below, so skill_health verdicts stay byte-stable — only the card label + tally move.
    unhealthy = [c for c in cards if c.get("card_health") in ("broken", "placeholder", "blocked", "partial", "wired")]

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
        c.get("card_health") in ("live", "wired", "partial", "self_produced") for c in core
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

    # P4 modality-vector coverage over this skill's consumed cards (routing metadata, parallel to
    # health_verdict — never feeds it). "required" = cards whose measurement_type routes to a
    # modality-fit gate; "declared" = of those, how many carry the field. missing/drift are the
    # non-compliant states (also surfaced as drift flags).
    n_p4_required = sum(1 for c in cards if c.get("modality_routing") in ("declared", "missing", "drift"))
    n_p4_declared = sum(1 for c in cards if c.get("modality_routing") in ("declared", "drift"))

    return {
        "name": skill["name"],
        "declared": skill["declared"],
        "derived": der,
        "cards": cards,
        "n_core_cards": len(core),
        "n_cards": len(cards),
        "n_cards_live": sum(1 for c in cards if c.get("card_health") == "live"),
        "n_p4_required": n_p4_required,
        "n_p4_declared": n_p4_declared,
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
    # Merged liveness: cards fired in ANY real run (governed ∪ exploratory) from the committed
    # output registry; == fired_ids when no registry catalog is present (graceful degrade).
    fired_any_ids = probe.fired_card_ids_any(roots["products"])
    ss_map = probe.sub_skill_map(roots["skills"])  # skill_dir -> short
    gcov = probe.gate_coverage_by_short(roots["contracts"])  # short -> coverage entry
    catalog = probe.catalog_manifests(roots["catalog"])  # product_id -> manifest meta
    catalog_ids = set(catalog)
    modality_types = probe.modality_relevant_types(roots["contracts"])  # P4: type -> routing set (None if vocab absent)
    # card_id -> [spec names]. DESCRIPTIVE ONLY (reported on the card nodes); it no longer
    # feeds any drift flag — see the RETIRED note in DRIFT_SEVERITY.
    spec_cards = probe.dashboard_spec_card_ids(roots["contracts"])
    run_health = probe.subskill_run_health(roots["skills"])  # skill_name -> "runs clean?" record ({} if absent)
    # FIELD-VOCABULARY lens: the skills repo's committed descriptor-coverage census ({} if absent).
    descriptor_census = probe.descriptor_coverage(roots["skills"])
    # FIELD-READ lens: the skills repo's committed reads-MINUS-declarations census ({} if absent),
    # resolved against field-level emission evidence from the products root ({} if unreadable).
    # Two INDEPENDENT siblings, so either can be absent — hence two separate `available` flags.
    field_read_census = probe.field_read_health(roots["skills"])
    field_emission = probe.summary_field_emission(roots["products"])

    # probe_card is called from BOTH the per-skill loop and the card-universe loop,
    # with identical constant args (roots + the precomputed index sets) for the whole
    # build. Cache on card_id so each card's yaml is parsed from disk ONCE per run
    # (was ~2.5x: 179 calls / 71 cards). Output is byte-identical — self_check guards it.
    _card_cache: dict[str, dict] = {}

    def probe_card_cached(cid: str) -> dict:
        if cid not in _card_cache:
            _card_cache[cid] = probe.probe_card(
                cid,
                roots["contracts"],
                roots["methods"],
                live_ids,
                fired_ids,
                dispatch_modules,
                catalog_ids,
                modality_types,
                fired_any_ids=fired_any_ids,
                skill_names=set(skill_names),
            )
        # Return a shallow copy: callers augment the dict (consumers, is_orphan, …)
        # and mutating the cached original would leak fields across the two loops.
        return dict(_card_cache[cid])

    skill_names = probe.list_skill_names(roots["skills"])

    skill_nodes: list[dict] = []
    for name in skill_names:
        sig = probe.probe_skill(skills_dir / name)
        # Cards a skill consumes: union of declared cards_used + run.py CARDS.
        card_ids = sorted(
            set(sig["declared"].get("cards_used") or []) | set(sig["derived"].get("cards_in_runpy") or [])
        )
        cards = [roll_up_card(probe_card_cached(cid), rules) for cid in card_ids]
        drift = compute_drift(sig, cards)
        node = roll_up_skill(sig, cards, drift, rules)
        # Attach risk_category / coverage via the short mapping (for matrix grouping).
        short = ss_map.get(name)
        node["gate_short"] = short
        node["risk_category"] = (gcov.get(short) or {}).get("risk_category") if short else None
        node["framework_can_evidence"] = (gcov.get(short) or {}).get("framework_can_evidence") if short else None
        # "RUNS CLEAN?" tier — the deterministic smoke result for this subskill (offline; NO live
        # data). One of: clean | clean_uninstrumented | error | unknown (absent from the harness
        # output, e.g. a non-wired/support skill or the artifact isn't present in this checkout).
        rh = run_health.get(name)
        node["runs_clean"] = rh.get("smoke") if rh else "unknown"
        node["run_health"] = rh.get("run_health") if rh else None  # status + cards + timings (or None)
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
        cn = roll_up_card(probe_card_cached(cid), rules)
        cn["consumers"] = sorted(consumers.get(cid, []))
        cn["n_consumers"] = len(cn["consumers"])
        cn["is_orphan"] = cn["n_consumers"] == 0  # on disk but pulled by no skill
        # A placeholder/dormant card is unconsumed BY DESIGN (a staged forward-declaration awaiting its
        # data + skill-wiring, often already declared in a dashboard_spec) → STAGED, not a dead orphan.
        # Separated so the dead-orphan alarm counts only cards that SHOULD have a consumer but don't.
        cn["is_staged_orphan"] = cn["is_orphan"] and bool(cn.get("is_placeholder"))
        cn["dashboard_specs"] = sorted(spec_cards.get(cid, []))
        cn["in_dashboard_spec"] = bool(cn["dashboard_specs"])
        # Spec coverage, DESCRIPTIVE: consumed by >=1 skill but listed in no dashboard_spec.
        # This says nothing about whether the card can fire — the emission path does not read a
        # spec (see the RETIRED note in DRIFT_SEVERITY; 67 such cards have fired in real
        # packages). "Can it fire?" is answered by fires_in_real_package / has_live_reader.
        cn["consumed_but_no_spec"] = cn["n_consumers"] > 0 and not cn["in_dashboard_spec"]
        card_nodes.append(cn)

    card_tally: dict[str, int] = {}
    for c in card_nodes:
        card_tally[c["card_health"]] = card_tally.get(c["card_health"], 0) + 1

    # P4 modality-routing tally over the deduped card universe (parallel to card_health).
    modality_tally: dict[str, int] = {}
    for c in card_nodes:
        modality_tally[c["modality_routing"]] = modality_tally.get(c["modality_routing"], 0) + 1

    # P4 drift at the CARD-UNIVERSE level — catches non-compliant cards that per-skill
    # compute_drift misses because they are ORPHANS (pulled by no skill → never seen in a
    # skill's card list). Surfaced in the top-level drift_index with a null skill so the
    # "silent gap" (an orphan card that routes but declares nothing) is never invisible.
    card_level_p4_drift: list[dict] = []
    for c in card_nodes:
        if c["is_orphan"] and c["modality_routing"] in ("missing", "drift"):
            code = "modality_relevance_missing" if c["modality_routing"] == "missing" else "modality_relevance_drift"
            card_level_p4_drift.append(
                {
                    "skill": None,
                    "card_id": c["card_id"],
                    "code": code,
                    "severity": DRIFT_SEVERITY[code],
                    "detail": f"orphan card {c['card_id']} (pulled by no skill) has modality_routing="
                    f"{c['modality_routing']} — P4 non-compliance invisible in the skill view",
                }
            )

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
    # Placeholder cards forward-declare products that are not built yet BY DESIGN; a dataset ref whose
    # ONLY consumers are placeholders is a PENDING forward-declaration, not a broken code reference.
    _placeholder_ids = {c["card_id"] for c in card_nodes if c.get("is_placeholder")}

    ds_universe = sorted(set(catalog) | set(ds_consumers))
    dataset_nodes: list[dict] = []
    for pid in ds_universe:
        meta = catalog.get(pid) or {}
        consumers = sorted(set(ds_consumers.get(pid, [])))
        in_cat = pid in catalog
        size_b = meta.get("size_bytes")
        n_cons = len(consumers)
        has_sort_key = meta.get("has_sort_key")
        node = {
            "product_id": pid,
            "in_catalog": in_cat,
            "kind": meta.get("kind"),
            "provider": meta.get("provider"),
            "version": meta.get("version"),
            "size_bytes": size_b,
            "file_count": meta.get("file_count"),
            "system_of_record": meta.get("system_of_record"),
            "n_derived_from": len(meta.get("derived_from") or []),
            "consumed_by_cards": consumers,
            "n_consumers": n_cons,
            "is_orphan": in_cat and not consumers,  # cataloged, no card pulls it
            # all consumers are placeholder cards → a not-yet-built product is expected, not broken.
            "all_consumers_placeholder": bool(consumers) and all(cid in _placeholder_ids for cid in consumers),
            "has_sort_key": has_sort_key,
        }
        # BROKEN = a card names a product missing from the catalog. But if the ONLY consumers are
        # placeholder cards, the missing product is an intentional forward-declaration → PENDING, not
        # broken (don't inflate the defect count with declared-but-unbuilt placeholder products).
        node["is_broken_ref"] = (not in_cat) and bool(consumers) and not node["all_consumers_placeholder"]
        node["is_pending_ref"] = (not in_cat) and bool(consumers) and node["all_consumers_placeholder"]
        node["access_cost"] = _access_cost(size_b, meta.get("file_count"), n_cons)
        # A CONSUMED (n_cons>0), sizeable, in-catalog DERIVED product with NO declared sort/partition
        # key is expensive to query — the one static access-latency signal worth acting on. SOURCE
        # snapshots are exempt: the gene-sorted-pushdown invariant governs DERIVED products, not raw
        # upstream releases (which method readers load by their own logic). Not flagged for orphans
        # (nobody queries them) or tiny/unsized datasets.
        node["missing_sort_key"] = bool(
            in_cat
            and meta.get("kind") == "derived"
            and n_cons > 0
            and has_sort_key is False
            and (size_b or 0) >= _SORT_KEY_SIZE_FLOOR
        )
        dataset_nodes.append(node)

    graph = build_graph(skill_nodes, card_nodes)
    dcov = build_descriptor_coverage(descriptor_census)
    dsum = dcov.get("summary") or {}
    frh = build_field_read_health(field_read_census, field_emission)
    fsum = frh.get("summary") or {}
    ftally = frh.get("emission_outcome_tally") or {}

    # Verdict tallies + drift roll-up for the summary header.
    tally: dict[str, int] = {}
    for n in skill_nodes:
        tally[n["health_verdict"]] = tally.get(n["health_verdict"], 0) + 1
    all_drift = [{"skill": n["name"], **d} for n in skill_nodes for d in n["drift_flags"]]
    # Append orphan-card P4 drift (skill=None) so an orphan's non-compliance is never invisible.
    all_drift.extend(card_level_p4_drift)

    return {
        "summary": {
            "n_skills": len(skill_nodes),
            "verdict_tally": tally,
            # "runs clean?" tier (deterministic offline smoke; {} when the skills artifact is absent):
            "runs_clean_tally": _tally(skill_nodes, "runs_clean"),
            "n_runs_clean": sum(1 for n in skill_nodes if n.get("runs_clean") == "clean"),
            "n_runs_clean_error": sum(1 for n in skill_nodes if n.get("runs_clean") == "error"),
            "n_drift_flags": len(all_drift),
            "n_error_drift": sum(1 for d in all_drift if d["severity"] == "error"),
            "n_unregistered_skills": len(reg["unregistered"]),
            "n_live_reader_cards": len(live_ids),
            "n_cards_firing_in_real_packages": len(fired_ids),
            "n_cards_firing_in_any_run": len(fired_any_ids),  # governed ∪ exploratory (registry)
            "n_cards": len(card_nodes),
            "card_health_tally": card_tally,
            # P4 modality-vector lens (routing metadata, parallel to card_health):
            "modality_routing_tally": modality_tally,
            "n_p4_required_cards": sum(v for k, v in modality_tally.items() if k in ("declared", "missing", "drift")),
            "n_p4_declared_cards": sum(v for k, v in modality_tally.items() if k in ("declared", "drift")),
            "n_p4_missing_cards": modality_tally.get("missing", 0),
            "n_p4_drift_cards": modality_tally.get("drift", 0),
            # DEAD orphans only: on-disk cards nothing consumes AND not a staged placeholder/dormant
            # forward-declaration. Staged orphans are counted separately (not a defect).
            "n_orphan_cards": sum(1 for c in card_nodes if c["is_orphan"] and not c.get("is_staged_orphan")),
            "n_staged_orphan_cards": sum(1 for c in card_nodes if c.get("is_staged_orphan")),
            "n_cards_consumed_but_no_spec": sum(1 for c in card_nodes if c.get("consumed_but_no_spec")),
            "n_datasets": len(dataset_nodes),
            "n_datasets_in_catalog": sum(1 for d in dataset_nodes if d["in_catalog"]),
            "n_orphan_datasets": sum(1 for d in dataset_nodes if d["is_orphan"]),
            "n_broken_dataset_refs": sum(1 for d in dataset_nodes if d["is_broken_ref"]),
            "n_pending_placeholder_refs": sum(1 for d in dataset_nodes if d.get("is_pending_ref")),
            # STATIC access-cost lens (metadata-derived; NO network/timing):
            "n_datasets_high_access_cost": sum(1 for d in dataset_nodes if d.get("access_cost") == "high"),
            "n_datasets_missing_sort_key": sum(1 for d in dataset_nodes if d.get("missing_sort_key")),
            "access_cost_tally": _tally(dataset_nodes, "access_cost"),
            # FIELD-VOCABULARY lens (trending, NEVER a gate — starts partial by design).
            # `descriptor_coverage_available: False` means this checkout could not read the
            # skills sibling; it is "not measured", NOT "no gaps". Every count below is None
            # in that case rather than 0, so an unmeasured dimension can never be plotted as
            # a clean one.
            "descriptor_coverage_available": bool(dcov.get("available")),
            "n_measurement_types_with_descriptors": dsum.get("n_measurement_types"),
            "n_descriptor_cells": dsum.get("n_descriptor_cells"),
            "n_distinct_descriptor_fields": dsum.get("n_distinct_fields"),
            # The LIVE queue: a curated METRIC_GLOSS entry that no spec declares (display
            # semantics exist, the salience layer cannot see the field). The opposite
            # direction — a numeric field with no gloss — is currently complete, so it is a
            # regression ratchet rather than a trend; both are carried, named apart.
            "n_gloss_without_descriptor": dsum.get("n_gloss_without_descriptor"),
            "n_numeric_fields_without_gloss": dsum.get("n_numeric_fields_without_gloss"),
            # FIELD-READ lens (trending, NEVER a gate). The COMPLEMENT of descriptor coverage
            # and of the skills-side aperture census: reads MINUS declarations. Same null
            # discipline — unavailable means "not measured", so every count is None, never 0.
            "field_read_health_available": bool(frh.get("available")),
            "n_field_read_units": fsum.get("n_units"),
            "n_field_read_units_clean": fsum.get("n_clean"),
            # NOT a flavour of clean: the scrape recognises a fixed set of call shapes and a unit
            # it cannot see scrapes to zero reads. Carried in the header precisely so the
            # instrument's blind spot is as visible as its findings.
            "n_field_read_units_no_reads_detected": fsum.get("n_no_reads_detected"),
            "n_undeclared_field_reads": fsum.get("n_undeclared_pairs"),
            # The resolved split this repo adds — null when no package was readable.
            "n_field_reads_emitted_but_undeclared": ftally.get("emitted_but_undeclared"),
            "n_field_reads_of_none": ftally.get("read_of_None"),
            "n_field_reads_emission_unobserved": ftally.get("emission_unobserved"),
        },
        "registry_drift": reg,
        "descriptor_coverage": dcov,
        "field_read_health": frh,
        "skills": skill_nodes,
        "cards": card_nodes,
        "datasets": dataset_nodes,
        "graph": graph,
        "drift_index": all_drift,
    }


# ---------------------------------------------------------------------------
# Descriptor-coverage section — the FIELD-VOCABULARY lens.
#
# A TRENDING dimension, never a gate: it starts partial by design and its whole
# purpose is to make the pivot's progress visible (invisibility, not code, was the
# churn root-cause). A pure transcription of the skills repo's committed census —
# NO logic of its own — so `self_check` can re-derive every count from the section
# itself. See probe.descriptor_coverage for why this is read as DATA rather than
# re-derived here.
# ---------------------------------------------------------------------------
def build_descriptor_coverage(census: dict) -> dict:
    """Wrap the skills census in the dimension envelope the dashboard consumes.

    Deliberately transcription, not reshaping: a second SHAPE for the same facts is the
    cheapest way to acquire drift between two repos that no CI job can compare. The only
    added fields are `available` (so absence is explicit rather than an empty tally that
    reads like a measured zero) and `source`.

    `available: False` is NOT a health verdict — it means this checkout could not see the
    skills sibling. A consumer must render it as "not measured", never as "no gaps".
    """
    if not census:
        return {
            "available": False,
            "source": "skills:_skills_common/descriptor_coverage.json",
            "reason": "sidecar absent — skills sibling not readable from this checkout",
        }
    return {
        "available": True,
        "source": "skills:_skills_common/descriptor_coverage.json",
        "schema_version": census.get("schema_version"),
        **{k: v for k, v in census.items() if k != "schema_version"},
    }


# ---------------------------------------------------------------------------
# Field-read-health section — reads MINUS declarations, per unit, PLUS the emission
# half that only this repo can measure.
#
# The skills census deliberately stops short: it classifies every undeclared read it
# cannot explain as `emission_undetermined`, because deciding between "the producer
# emits this and no card declares it" and "nothing emits it, so the model was handed
# None" needs OBSERVED PACKAGES, and the skills repo has none it can trust (its own
# fixtures are partly synthetic — crediting a field as emitted because a fixture names
# it would make the metric measure our own paperwork). This side has the data-products
# root, so this is where that split gets made.
#
# Trending, never a gate — same contract as descriptor_coverage.
# ---------------------------------------------------------------------------
#: The three answers the emission scan can give. `emission_unobserved` is NOT a hedge: it is
#: the only honest answer when the card never appeared in an observed package, and without it
#: `read_of_None` would be asserted from zero evidence. Measured against the committed products
#: root it is also the BEST-witnessed of the three — the outcome for the census's one
#: emission_undetermined row.
#:
#: `read_of_None` currently has NO live witness, and that is the point rather than a gap: the
#: one instance that ever existed (clinical-precedent.n_agents_engaging_target, a field nothing
#: emitted and nothing declared that a skill read anyway) was FIXED in skills #1405, which is
#: what motivated this whole dimension. So this outcome is a REGRESSION WATCH, and a
#: non-zero count here is the finding the dashboard exists to surface.
_EMISSION_OUTCOMES = ("emitted_but_undeclared", "read_of_None", "emission_unobserved")

_FRH_SOURCE = "skills:_skills_common/field_read_health.json"


def resolve_emission(card: str, field: str, emission: dict, classification: str | None = None) -> dict:
    """Resolve one undeclared (card, field) read against the observed-package evidence.

    Outcome, and the evidence for it, as a dict to merge into the queue row. Never mutates
    the skills-side `classification`: that axis records the FIELD NAME's shape (a leading
    underscore cannot be a declared field) while this one records what the producer was
    OBSERVED to do. They are independent, and the live artifact proves it — `_schema` is
    classified `meta_key` and is nevertheless emitted in every observed package, so
    collapsing the two axes would have to call that row either "not a real key" or "an
    undeclared field", and both are false.

    An EMPTY APERTURE yields outcome None, not `emission_unobserved`. The difference is the
    whole point: `emission_unobserved` says "we looked at N>0 packages and this card was in
    none of them"; a missing products root means nobody looked, and an unmeasured row must
    stay unresolved rather than acquire the most reassuring-sounding label available.
    """
    cards = (emission or {}).get("cards") or {}
    if not cards:
        return {
            "emission_outcome": None,
            "emission_evidence": (
                "NOT MEASURED — no evidence package was readable under the data-products root, so "
                "this read stays emission_undetermined rather than being called unobserved"
            ),
        }
    n_pkg = emission.get("n_packages")
    rec = cards.get(card)
    if rec is None:
        return {
            "emission_outcome": "emission_unobserved",
            "n_rows_observed": 0,
            "emission_evidence": (
                f"card absent from all {n_pkg} observed package(s) — whether the producer emits "
                f"'{field}' is UNDECIDABLE at this aperture, NOT evidence that it does not"
            ),
        }
    if field in (rec.get("emitted") or ()):
        # THE REMEDY DEPENDS ON THE OTHER AXIS, and stating it unconditionally was a defect: for a
        # meta_key row "declare it" is the WRONG advice. No card declares any underscore-led key —
        # that is precisely the premise the producer's meta_key rule rests on — so an emitted
        # `_`-led key is an ENVELOPE key travelling on an undeclared producer→reader channel, not a
        # missing card field. Same outcome, different owner.
        return {
            "emission_outcome": "emitted_but_undeclared",
            "n_rows_observed": rec.get("n_rows"),
            "emission_evidence": (
                f"'{field}' carried a non-null value in an observed package, so the producer emits it. "
                + (
                    "It is an ENVELOPE key (underscore-led; no card declares any), so the read is "
                    "satisfied today but travels on a channel outside the declared contract — the gap "
                    "is documentation/coupling, NOT a missing card field."
                    if classification == "meta_key"
                    else "The DECLARATION is what is missing — a contracts-side fix."
                )
            ),
        }
    null_only = field in (rec.get("null_only") or ())
    return {
        "emission_outcome": "read_of_None",
        "n_rows_observed": rec.get("n_rows"),
        "key_present_but_null": null_only,
        "emission_evidence": (
            f"card observed in {rec.get('n_rows')} row(s) and '{field}' was "
            + (
                "PRESENT but null in every one — the producer knows the key and emits nothing for it"
                if null_only
                else "absent from every one — the reader is handed None"
            )
        ),
    }


def build_field_read_health(census: dict, emission: dict) -> dict:
    """Wrap the skills census in the dimension envelope, with each undeclared read resolved.

    Transcription plus ONE added axis, for the reason build_descriptor_coverage gives: a second
    SHAPE for the same facts is the cheapest way to acquire drift between two repos no CI job can
    compare. The added axis is `emission_outcome` per queue row (and its tally), which is not a
    reshaping of the census — it is the half the census could not measure.

    ONE PROJECTION, named so it cannot be mistaken for a measurement: `rosters.declared_fields`
    (the pinned 148-card / 1807-field roster, ~90 KB) is NOT copied through. It is an input to the
    census, not a finding, and no consumer of this dashboard reads it; `roster_pin` keeps its two
    counts so the pin stays identifiable. The roster is still fully available in the skills
    artifact, which is the ONE producer of it.

    `available: False` is NOT a health verdict — it means this checkout could not see the skills
    sibling. A consumer must render it as "not measured", never as "no undeclared reads".
    """
    if not census:
        return {
            "available": False,
            "source": _FRH_SOURCE,
            # Two ways to get here and the artifact should not pretend to know which: the sibling
            # is unreadable (isolated checkout, another branch), or it is readable and simply does
            # not publish the census yet. The second is the state this dimension SHIPS in, until
            # the skills-side producer lands on trunk.
            "reason": "census absent — the skills sibling is unreadable, or does not publish it yet",
        }

    roster = ((census.get("rosters") or {}).get("declared_fields")) or {}
    observed = (emission or {}).get("cards") or {}

    queue = [
        {**row, **resolve_emission(row.get("card"), row.get("field"), emission, row.get("classification"))}
        for row in (census.get("undeclared_queue") or [])
    ]
    # NULLS, not zeros, when nothing was scanned: a 0 against `read_of_None` plots as "no field
    # ever handed the model None", which is the single most misleading thing this dimension could
    # say. An empty aperture measures nothing, and the counts have to admit it.
    tally = (
        {o: sum(1 for r in queue if r.get("emission_outcome") == o) for o in _EMISSION_OUTCOMES}
        if observed
        else dict.fromkeys(_EMISSION_OUTCOMES)
    )

    if not observed:
        aperture = {
            "available": False,
            "n_packages": 0,
            "reason": "no evidence package readable under the data-products root",
            "note": (
                "UNMEASURED, not clean: every undeclared read stays emission_undetermined. Do not "
                "plot a zero here — nothing was scanned."
            ),
        }
    else:
        aperture = {
            "available": True,
            "n_packages": emission.get("n_packages"),
            "n_card_rows": emission.get("n_card_rows"),
            "n_card_rows_with_summary": emission.get("n_card_rows_with_summary"),
            "n_cards_observed": len(observed),
            "n_roster_cards": len(roster) or None,
            "n_roster_cards_observed": sum(1 for c in roster if c in observed) if roster else None,
            "note": (
                "PUBLISHED BECAUSE IT IS NARROW. Every outcome below is conditional on these "
                "packages; a card outside them yields emission_unobserved, which is a statement "
                "about the aperture and NOT about the producer. Widening the aperture can only "
                "move rows OUT of emission_unobserved, never into it."
            ),
        }

    body = {k: v for k, v in census.items() if k not in ("schema_version", "rosters", "undeclared_queue")}
    return {
        "available": True,
        "source": _FRH_SOURCE,
        "schema_version": census.get("schema_version"),
        **body,
        "rosters": {k: v for k, v in (census.get("rosters") or {}).items() if k != "declared_fields"},
        "roster_pin": {
            "n_cards": len(roster),
            "n_fields": sum(len(v) for v in roster.values()),
            "note": "the pinned roster itself is NOT copied here — see build_field_read_health",
        },
        "undeclared_queue": queue,
        "emission_outcomes": list(_EMISSION_OUTCOMES),
        "emission_outcome_tally": tally,
        "n_emission_unresolved": sum(1 for r in queue if r.get("emission_outcome") is None),
        "emission_aperture": aperture,
        "resolution_note": (
            "The skills census cannot split emission_undetermined (no observed packages it can "
            "trust); this side can, and does it per row against the data-products root. The "
            "skills-side `classification` is left untouched — it describes the field NAME's shape, "
            "while `emission_outcome` describes what the producer was OBSERVED to do. A row can be "
            "meta_key AND emitted_but_undeclared, and one live row is."
        ),
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
    nodes: dict[str, dict] = {}  # id -> node (dedup)
    edges: list[dict] = []

    def add_node(nid: str, layer: str, label: str, health: str | None = None, meta: dict | None = None):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "layer": layer, "label": label, "health": health, **(meta or {})}

    # Skills + their resolver edge.
    for n in skill_nodes:
        sid = f"skill:{n['name']}"
        add_node(
            sid,
            "skill",
            n["name"],
            n["health_verdict"],
            {"kind": n["derived"].get("kind"), "risk_category": n.get("risk_category")},
        )
        gate = n["derived"].get("resolver_gate")
        if gate:
            rid = f"resolver:{gate}"
            add_node(rid, "resolver", gate, "live" if n["derived"].get("resolver_bound") else "broken")
            edges.append({"src": sid, "dst": rid, "rel": "resolves_via"})

    # Cards + method backing + card→consuming-skill edges.
    for c in card_nodes:
        cid = f"card:{c['card_id']}"
        add_node(
            cid,
            "card",
            c["card_id"],
            c["card_health"],
            {"is_orphan": c.get("is_orphan", False), "measurement_type": c.get("measurement_type")},
        )
        for sk in c.get("consumers", []):
            edges.append({"src": f"skill:{sk}", "dst": cid, "rel": "consumes"})
        mod = c.get("dispatch_module")
        if mod:
            top = mod.split(".")[0]  # strip .read/.cli suffix
            mid = f"method:{top}"
            add_node(mid, "method", top, "live" if c.get("method_dir_exists") else "broken")
            edges.append({"src": cid, "dst": mid, "rel": "backed_by"})

    # Deterministic ordering: by (layer, id) for nodes, by tuple for edges.
    node_list = sorted(nodes.values(), key=lambda n: (_LAYERS.get(n["layer"], 9), n["id"]))
    edge_list = sorted(edges, key=lambda e: (e["src"], e["dst"], e["rel"]))
    # De-dupe edges (a method backing many cards can repeat skill→card→method chains).
    seen = set()
    deduped = []
    for e in edge_list:
        k = (e["src"], e["dst"], e["rel"])
        if k not in seen:
            seen.add(k)
            deduped.append(e)

    counts = {layer: sum(1 for n in node_list if n["layer"] == layer) for layer in _LAYERS}
    return {
        "nodes": node_list,
        "edges": deduped,
        "layer_counts": counts,
        "n_nodes": len(node_list),
        "n_edges": len(deduped),
    }
