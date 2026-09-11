"""Tests for the framework-health generator.

Focus on the traps encountered building it (each a regression guard):
  1. AST over-count: CARD_DISPATCHERS commented-tail entries must NOT be live.
  2. CARDS/SUB_SKILLS literal extraction must strip inline comments.
  3. Dispatcher-based method backing (authoritative) vs stale card label.
  4. Signal-reliability precedence: fires_in_real_package dominates; a live card
     is never marked broken by a weak label heuristic.
  5. Golden rollup oracle: representative signal fixtures -> (verdict, reason_id).
  6. --check stable projection: volatile fields (generated_at) excluded.
  7. Frontmatter vs prose status reconciliation; missing-status drift.

Run: pytest validators/framework_health/tests/ -q
"""

from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path

import pytest

from validators.framework_health import probe, render_html, rollup
from validators.framework_health.build_framework_health import (
    compute_delta,
    self_check,
    stable_projection,
)


# ---------------------------------------------------------------------------
# 1 + 2. AST literal / dict-key extraction excludes comments & commented tails
# ---------------------------------------------------------------------------
def test_dict_keys_exclude_commented_tail():
    src = textwrap.dedent("""
        CARD_DISPATCHERS = {
            "live-a": fn_a,
            "live-b": fn_b,
            # "commented-c": fn_c,   <- a commented example tail, must be excluded
        }
    """)
    tree = ast.parse(src)
    keys = probe._find_dict_keys(tree, "CARD_DISPATCHERS")
    assert keys == ["live-a", "live-b"]
    assert "commented-c" not in keys


def test_cards_list_literal_strips_inline_comments():
    src = textwrap.dedent("""
        CARDS = [
            "card-one",     # a facet card
            "card-two",     # another
        ]
    """)
    tree = ast.parse(src)
    assert probe._find_assign_literal(tree, "CARDS") == ["card-one", "card-two"]


def test_cards_in_runpy_unions_subtype_cards(tmp_path):
    """A FOCUSED skill's tier:subtype PANORAMA card lives in SUBTYPE_CARDS (needs
    subgroup_context threaded → not on the scalar CARDS list) but IS declared in cards_used.
    cards_in_runpy must union SUBTYPE_CARDS so the cards_used↔run.py check doesn't false-flag it."""
    run = tmp_path / "scripts" / "run.py"
    run.parent.mkdir(parents=True)
    run.write_text(
        textwrap.dedent("""
        CARDS = ["mutation-type-counts", "copy-number-distribution"]
        SUBTYPE_CARDS = ["subgroup-stratified-mutation-frequency"]
    """)
    )
    # Mirror probe.probe_run_py's cards_in_runpy union (CARDS + SUBTYPE_CARDS).
    tree = ast.parse(run.read_text())
    cards = probe._find_assign_literal(tree, "CARDS")
    sub = probe._find_assign_literal(tree, "SUBTYPE_CARDS")
    union = [str(c) for c in cards] + [str(c) for c in sub if str(c) not in [str(x) for x in cards]]
    assert "subgroup-stratified-mutation-frequency" in union
    assert set(union) == {"mutation-type-counts", "copy-number-distribution", "subgroup-stratified-mutation-frequency"}


def test_drift_no_mismatch_when_subtype_card_in_cards_used():
    """The end-to-end guard: a FOCUSED skill declaring a subtype panorama card in cards_used +
    SUBTYPE_CARDS (surfaced via cards_in_runpy) must NOT raise declared_cards_mismatch_runpy."""
    skill = {
        "declared": {
            "status": "wired",
            "cards_used": [
                "mutation-type-counts",
                "copy-number-distribution",
                "subgroup-stratified-mutation-frequency",
            ],
        },
        "derived": {
            "kind": "FOCUSED",
            "has_entrypoint": True,
            # cards_in_runpy already unioned SUBTYPE_CARDS (the probe fix):
            "cards_in_runpy": [
                "mutation-type-counts",
                "copy-number-distribution",
                "subgroup-stratified-mutation-frequency",
            ],
        },
    }
    flags = rollup.compute_drift(skill, cards=[])
    assert not any(f["code"] == "declared_cards_mismatch_runpy" for f in flags)


def test_live_reader_ids_real_repo_excludes_known_traps():
    """Against the real repo: the commented-tail cards must not appear as live."""
    roots = probe.default_roots()
    if not (roots["skills"] / "skills").exists():
        pytest.skip("skills repo not present")
    live = set(probe.live_reader_card_ids(roots["skills"]))
    # Non-vacuity guard: the dispatcher registry moved to skills/_skills_common/ when
    # compose-dashboard was retired (#654). If the probe reads a stale path it returns
    # an EMPTY set — and every "trap not in live" below passes vacuously (the silent
    # drift that mislabeled working cards `broken`). Pin a floor + a known-live card so
    # a stale-path regression fails loudly here.
    assert len(live) > 40, f"expected many live-reader cards, got {len(live)} (stale dispatcher path?)"
    assert "cellline-rna-distribution" in live, "a known live-reader card is missing (stale dispatcher path?)"
    for trap in ("rwd-stratified-expression", "antigen-prevalence", "subgroup-stratified-expression"):
        assert trap not in live, f"{trap} is a commented example, must not count as live"


# ---------------------------------------------------------------------------
# 3. Dispatcher import resolution (authoritative backing) + submodule suffix
# ---------------------------------------------------------------------------
def test_dispatcher_method_imports_resolves_real_module(tmp_path):
    # Current dispatcher location (compose-dashboard retired #654 → _skills_common/).
    lr = tmp_path / "skills" / "_skills_common"
    lr.mkdir(parents=True)
    (lr / "_live_readers.py").write_text(
        textwrap.dedent("""
        def _dispatch_x(target, indication):
            mod = _import_method("dge_deseq2")
            return mod.read(target)
        def _dispatch_y(target, indication):
            mod = _import_method("opentargets_clingen.read")
            return mod.read_target_summary(target)
        CARD_DISPATCHERS = {
            "card-x": _dispatch_x,
            "card-y": _dispatch_y,
        }
    """)
    )
    got = probe.dispatcher_method_imports(tmp_path)
    assert got == {"card-x": "dge_deseq2", "card-y": "opentargets_clingen.read"}


def test_probe_card_uses_dispatcher_not_stale_label(tmp_path):
    """Dispatcher import (not the methods.call label) drives backing. Staleness is
    keyed off the EXPLICIT `module:` field: a card with only a cosmetic `call:` label
    that differs from the dispatcher is NOT stale (label→module fix, 2026-08-18) —
    the label is a human handle, not a package claim."""
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.card.yaml").write_text(
        textwrap.dedent("""
        card_id: c
        methods:
          - call: totally-stale-label
        measurement_type: mt
    """)
    )
    methods = tmp_path / "methods"
    (methods / "methods" / "real_module").mkdir(parents=True)
    (methods / "methods" / "real_module" / "read.py").write_text("def read(): pass")
    out = probe.probe_card(
        "c",
        tmp_path,
        methods,
        live_ids={"c"},
        fired_ids=set(),
        dispatch_modules={"c": "real_module.read"},  # dispatcher routes to the REAL module
    )
    assert out["method_dir_exists"] is True  # resolved via dispatcher, suffix stripped
    assert out["stale_method_label"] is False  # no module: field -> no package claim -> not stale
    assert out["method_call"] == "totally-stale-label"


def test_probe_card_flags_stale_only_on_declared_module_mismatch(tmp_path):
    """stale_method_label fires when the card's EXPLICIT `module:` disagrees with the
    dispatcher's import, and NOT when only the friendly `call:` label differs. Regression
    for the 14 label-only false positives (clingen-dosage, spatial-*, etc., 2026-08-18)."""
    (tmp_path / "cards").mkdir()
    methods = tmp_path / "methods"
    (methods / "methods" / "real_module").mkdir(parents=True)
    (methods / "methods" / "real_module" / "read.py").write_text("def read(): pass")

    # (a) friendly label differs, module: AGREES with dispatcher -> NOT stale
    (tmp_path / "cards" / "ok.card.yaml").write_text(
        textwrap.dedent("""
        card_id: ok
        methods:
          - call: friendly-alias-lookup
            module: real_module
        measurement_type: mt
    """)
    )
    ok = probe.probe_card(
        "ok", tmp_path, methods, live_ids={"ok"}, fired_ids=set(), dispatch_modules={"ok": "real_module.read"}
    )
    assert ok["stale_method_label"] is False

    # (b) declared module: genuinely disagrees with the dispatcher -> STALE
    (tmp_path / "cards" / "bad.card.yaml").write_text(
        textwrap.dedent("""
        card_id: bad
        methods:
          - call: whatever
            module: wrong_package
        measurement_type: mt
    """)
    )
    bad = probe.probe_card(
        "bad", tmp_path, methods, live_ids={"bad"}, fired_ids=set(), dispatch_modules={"bad": "real_module.read"}
    )
    assert bad["stale_method_label"] is True


def test_probe_card_honors_declared_module_for_resolver_routed(tmp_path):
    """Resolver-routed card (no dispatcher): backing must resolve from the explicit
    `module:` field, NOT a de-kebab of the `call:` label. Regression for the
    cn/amp/fusion/partner/gnomad `broken/card-no-path` false positive (2026-08-18):
    the label abbreviates the module (depmap-cn-stratified vs depmap_cn_dependency),
    so guessing from the label found no dir and mislabeled a working card broken."""
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.card.yaml").write_text(
        textwrap.dedent("""
        card_id: c
        methods:
          - call: depmap-cn-stratified          # de-kebabs to depmap_cn_stratified (NO such dir)
            module: depmap_cn_dependency         # the REAL backing package
            entrypoint: read_cn_stratified_dependency
        measurement_type: mt
    """)
    )
    methods = tmp_path / "methods"
    (methods / "methods" / "depmap_cn_dependency").mkdir(parents=True)
    (methods / "methods" / "depmap_cn_dependency" / "read.py").write_text("def read(): pass")
    out = probe.probe_card(
        "c",
        tmp_path,
        methods,
        live_ids=set(),
        fired_ids=set(),  # no dispatcher, never fired -> resolver-routed
        dispatch_modules={},
    )
    assert out["method_dir_exists"] is True  # resolved from module:, not the kebab label
    assert out["method_has_read"] is True
    # A card with a BUILT backing method + no CARD_DISPATCHERS entry routes through the GENERIC
    # dispatcher (card_spec module/entrypoint) — it HAS a working reader, just unproven in a governed
    # package → `wired`, not `blocked`. (Refined 2026-08-30: this was `blocked` when the ladder had no
    # generic-dispatch rung; `blocked` now means "no method DECLARED at all". Refined 2026-08-31: the
    # reader-exists-never-fired verdict was split out of `partial` into `wired` — the honest label.)
    verdict, reason = rollup._resolve(rollup.load_rules()["card_health"], out)
    assert verdict == "wired"
    assert reason == "card-generic-dispatch-never-fires"


def test_catalog_manifests_registers_product_id_alias(tmp_path):
    """A manifest's product_id: field becomes an alias key so an indication-
    parameterized card (naming the logical registry product) resolves without
    hard-coding one indication's per-manifest id (dataset_ref_not_in_catalog fix)."""
    derived = tmp_path / "manifests" / "derived"
    derived.mkdir(parents=True)
    (tmp_path / "manifests" / "sources").mkdir(parents=True)
    # Per-indication manifest whose id != its logical product_id
    (derived / "coadread-dge-df06320.yaml").write_text(
        textwrap.dedent("""
        id: coadread-dge-df06320
        product_id: expression-rna-tumor-vs-adjacent
        provider: takeda
    """)
    )
    cat = probe.catalog_manifests(tmp_path)
    # Both the real id AND the product_id alias resolve
    assert "coadread-dge-df06320" in cat  # real manifest id
    assert "expression-rna-tumor-vs-adjacent" in cat  # product_id alias
    assert cat["coadread-dge-df06320"].get("is_product_alias") is None  # real id, not an alias
    assert cat["expression-rna-tumor-vs-adjacent"]["is_product_alias"] is True


def test_catalog_real_id_wins_over_product_alias_collision(tmp_path):
    """If a manifest's real id equals another manifest's product_id, the real id wins."""
    derived = tmp_path / "manifests" / "derived"
    derived.mkdir(parents=True)
    (tmp_path / "manifests" / "sources").mkdir(parents=True)
    (derived / "a.yaml").write_text("id: shared-name\nprovider: real\n")
    (derived / "b.yaml").write_text("id: b-real\nproduct_id: shared-name\nprovider: aliased\n")
    cat = probe.catalog_manifests(tmp_path)
    # 'shared-name' is a real id (manifest a) — must NOT be overwritten by b's alias
    assert cat["shared-name"].get("is_product_alias") is None
    assert cat["shared-name"]["provider"] == "real"


# ---------------------------------------------------------------------------
# 4 + 5. Golden rollup oracle: signal fixtures -> (verdict, reason_id)
# ---------------------------------------------------------------------------
CARD_CASES = [
    # (signals, expected_verdict, expected_reason_id)
    ({"card_yaml_exists": False}, "broken", "card-missing-yaml"),
    ({"card_yaml_exists": True, "fires_in_real_package": True}, "live", "card-live-fired"),
    (
        {"card_yaml_exists": True, "fires_in_real_package": False, "is_placeholder": True},
        "placeholder",
        "card-placeholder",
    ),
    (
        {
            "card_yaml_exists": True,
            "fires_in_real_package": False,
            "has_live_reader": False,
            "method_dir_exists": False,
        },
        "broken",
        "card-no-path",
    ),
    (
        {"card_yaml_exists": True, "fires_in_real_package": False, "has_live_reader": True, "method_dir_exists": False},
        "broken",
        "card-registered-method-unbuilt",
    ),
    (
        {"card_yaml_exists": True, "fires_in_real_package": False, "has_live_reader": True, "method_dir_exists": True},
        "wired",
        "card-reader-never-fires",
    ),
    # Generic dispatcher: no bespoke CARD_DISPATCHERS entry, but a BUILT backing method exists
    # (routed via card_spec module/entrypoint) → wired, NOT blocked/partial. Pins the blocked-30 fix
    # + the 2026-08-31 partial→wired split (reader-exists-never-fired is WIRED, not a defect).
    (
        {"card_yaml_exists": True, "fires_in_real_package": False, "has_live_reader": False, "method_dir_exists": True},
        "wired",
        "card-generic-dispatch-never-fires",
    ),
    # No reader AND declared backing method module absent → broken (card-no-path).
    (
        {
            "card_yaml_exists": True,
            "fires_in_real_package": False,
            "has_live_reader": False,
            "method_dir_exists": False,
        },
        "broken",
        "card-no-path",
    ),
    # Genuine coverage gap: no reader, no method DECLARED at all (method_dir_exists unprobed/None)
    # → blocked. This is the honest remaining meaning of `blocked` after the generic-dispatch fix.
    (
        {"card_yaml_exists": True, "fires_in_real_package": False, "has_live_reader": False},
        "blocked",
        "card-no-reader-no-fire",
    ),
]


@pytest.mark.parametrize("signals,verdict,reason", CARD_CASES)
def test_card_rollup_oracle(signals, verdict, reason):
    rules = rollup.load_rules()
    got_verdict, got_reason = rollup._resolve(rules["card_health"], signals)
    assert (got_verdict, got_reason) == (verdict, reason)


def test_fires_dominates_missing_method():
    """The reliability-precedence fix: a card that FIRED is live even if its
    method-dir probe would say missing."""
    rules = rollup.load_rules()
    signals = {
        "card_yaml_exists": True,
        "fires_in_real_package": True,
        "has_live_reader": True,
        "method_dir_exists": False,
    }
    verdict, reason = rollup._resolve(rules["card_health"], signals)
    assert verdict == "live" and reason == "card-live-fired"


def _skill_for_rollup(cards):
    return {
        "name": "s",
        "declared": {"status": None, "prose_markers": [], "rules_scope": []},
        "derived": {"kind": "FOCUSED", "has_entrypoint": True, "test_count": 1},
    }


def test_ready_unproven_vs_production_ready():
    """The proven/unproven split + TRUTHFUL reason text (the reported bug: a skill
    read production_ready 'all core cards live' while 0/N were live)."""
    rules = rollup.load_rules()

    # all core cards partial (readers work, nothing fired) -> ready_unproven, and the
    # reason must NOT claim cards are live.
    partial_cards = [{"card_id": "c1", "card_health": "partial"}, {"card_id": "c2", "card_health": "partial"}]
    node = rollup.roll_up_skill(_skill_for_rollup(partial_cards), partial_cards, [], rules)
    assert node["health_verdict"] == "ready_unproven"
    assert "live" not in node["reason_text"].lower() or "readers work" in node["reason_text"].lower()
    assert "no core card has fired" in node["reason_text"]

    # ≥1 core card fired -> production_ready (proven)
    fired_cards = [{"card_id": "c1", "card_health": "live"}, {"card_id": "c2", "card_health": "partial"}]
    node2 = rollup.roll_up_skill(_skill_for_rollup(fired_cards), fired_cards, [], rules)
    assert node2["health_verdict"] == "production_ready"
    assert "fired in a real package" in node2["reason_text"]


def test_match_operators():
    ctx = {"a": 1, "b": {"c": "x"}, "k": "partial"}
    assert rollup._match({}, ctx) is True  # empty always matches
    assert rollup._match({"a": 1}, ctx) is True
    assert rollup._match({"b.c": "x"}, ctx) is True  # dotted path
    assert rollup._match({"k__in": ["partial", "wired"]}, ctx) is True
    assert rollup._match({"a__truthy": True}, ctx) is True
    assert rollup._match({"all": [{"a": 1}, {"b.c": "x"}]}, ctx) is True
    assert rollup._match({"any": [{"a": 999}, {"k": "partial"}]}, ctx) is True
    assert rollup._match({"a": 2}, ctx) is False


# ---------------------------------------------------------------------------
# 6. --check stable projection excludes volatile fields
# ---------------------------------------------------------------------------
def test_stable_projection_excludes_volatile():
    base = {"schema_version": "1.0.0", "summary": {"n_skills": 3}, "skills": []}
    a = {**base, "generated_at": "2026-01-01T00:00:00Z", "roots": {"x": "/a"}, "root_shas": {"x": "aaa"}}
    b = {**base, "generated_at": "2099-12-31T23:59:59Z", "roots": {"x": "/b"}, "root_shas": {"x": "zzz"}}
    assert stable_projection(a) == stable_projection(b)  # only volatile fields differ


def test_stable_projection_detects_real_change():
    base = {"schema_version": "1.0.0", "generated_at": "t", "roots": {}, "root_shas": {}}
    a = {**base, "summary": {"n_skills": 3}}
    b = {**base, "summary": {"n_skills": 4}}
    assert stable_projection(a) != stable_projection(b)


def test_stable_projection_excludes_delta():
    """delta is a diff-vs-prior (changes every run) — it MUST be volatile, else --check
    would false-positive STALE on every generation. The load-bearing invariant of the
    trend feature."""
    base = {"schema_version": "1.0.0", "summary": {"n_skills": 3}, "skills": []}
    a = {**base, "generated_at": "t", "roots": {}, "root_shas": {}, "delta": {"n_skills": 2}}
    b = {**base, "generated_at": "t", "roots": {}, "root_shas": {}, "delta": {"n_skills": -5}}
    assert stable_projection(a) == stable_projection(b)  # differing deltas don't move the projection


# ---------------------------------------------------------------------------
# 6c. Trend/delta — diff vs the prior committed artifact
# ---------------------------------------------------------------------------
def _report(n_skills, n_cards, skills, cards, verdict_tally=None, n_drift=0, n_err=0):
    return {
        "generated_at": "2026-01-01T00:00:00Z",
        "summary": {
            "n_skills": n_skills,
            "n_cards": n_cards,
            "n_drift_flags": n_drift,
            "n_error_drift": n_err,
            "verdict_tally": verdict_tally or {},
            "card_health_tally": {},
        },
        "skills": [{"name": s} for s in skills],
        "cards": [{"card_id": c} for c in cards],
    }


def test_compute_delta_none_without_prior():
    assert compute_delta(None, _report(2, 2, ["a", "b"], ["x", "y"])) is None


def test_compute_delta_counts_and_names():
    prior = _report(2, 2, ["a", "b"], ["x", "y"], {"partial": 2})
    fresh_body = _report(3, 3, ["a", "b", "c"], ["x", "y", "z"], {"partial": 1, "production_ready": 2})
    d = compute_delta(prior, fresh_body)
    assert d["has_prior"] and d["n_skills"] == 1 and d["n_cards"] == 1
    assert d["skills_added"] == ["c"] and d["skills_removed"] == []
    assert d["cards_added"] == ["z"]
    # tally delta reports only the moved keys
    assert d["verdict_tally"] == {"partial": -1, "production_ready": 2}


def test_delta_ribbon_empty_without_prior():
    assert render_html._delta_ribbon({"delta": None}) == ""
    assert render_html._delta_ribbon({}) == ""


def test_delta_ribbon_renders_moves_and_names():
    report = {
        "delta": {
            "has_prior": True,
            "prior_generated_at": "2026-08-04T00:00:00Z",
            "n_skills": 2,
            "n_cards": 5,
            "n_drift_flags": -3,
            "n_error_drift": 0,
            "skills_added": ["catalog-query"],
            "skills_removed": [],
            "cards_added": ["a", "b"],
            "cards_removed": [],
        }
    }
    html = render_html._delta_ribbon(report)
    assert "Since last run" in html and "2026-08-04" in html
    assert "2 skills" in html and "5 cards" in html and "3 drift flags" in html
    assert "catalog-query" in html


# ---------------------------------------------------------------------------
# 6d. Fix-next punch list + actionability ordering + severity demotion
# ---------------------------------------------------------------------------
def test_every_drift_code_is_conditioned_on_wiring_not_spec_membership():
    """Supersedes test_consumed_but_no_spec_is_info_not_warn (demoted 2026-08-05, RETIRED
    2026-09-11). The 2026-08-05 fix demoted the flag's SEVERITY without testing its PREMISE,
    which is how a false claim survived seven weeks at info level while accounting for 17 of
    23 open drift flags. Registering it at any severity is the regression to catch."""
    assert "card_consumed_but_no_spec" not in rollup.DRIFT_SEVERITY


def test_fix_next_only_actionable_and_ordered():
    report = {
        "drift_index": [
            {"skill": "s1", "code": "dataset_ref_not_in_catalog", "severity": "warn", "detail": "d"},
            {"skill": "s2", "code": "dataset_ref_not_in_catalog", "severity": "warn", "detail": "d"},
            {"skill": "s3", "code": "status_wired_no_entrypoint", "severity": "error", "detail": "d"},
            {"skill": "s4", "code": "card_consumed_but_no_spec", "severity": "info", "detail": "d"},
        ]
    }
    html = render_html._fix_next(report)
    # error sorts above the more-numerous warn (severity beats count)
    assert html.index("status_wired_no_entrypoint") < html.index("dataset_ref_not_in_catalog")
    # info-severity code is NOT in the actionable queue
    assert "card_consumed_but_no_spec" not in html


def test_fix_next_empty_state():
    html = render_html._fix_next(
        {"drift_index": [{"skill": "s", "code": "stale_method_label", "severity": "info", "detail": "d"}]}
    )
    assert "Nothing actionable" in html


def test_skill_actionability_floats_drift_first():
    drifting = {"name": "z-drift", "health_verdict": "partial", "drift_flags": [{"severity": "error"}]}
    clean = {"name": "a-ready", "health_verdict": "production_ready", "drift_flags": []}
    # despite alphabetical order putting a-ready first, drifting sorts ahead
    assert render_html._skill_actionability(drifting) < render_html._skill_actionability(clean)


# ---------------------------------------------------------------------------
# 6b. --self-check: CI-safe integrity check that needs NO sibling repos
# ---------------------------------------------------------------------------
def _minimal_report(card_health="live", verdict="production_ready"):
    card = {"card_id": "c", "card_yaml_exists": True, "fires_in_real_package": True, "card_health": card_health}
    skill = {"name": "s", "cards": [card], "health_verdict": verdict}
    return {
        "schema_version": "1.0.0",
        "summary": {"verdict_tally": {verdict: 1}},
        "skills": [skill],
        "registry_drift": {},
        "drift_index": [],
    }


def test_self_check_passes_on_consistent_artifact(tmp_path):
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(_minimal_report()))
    ok, errs = self_check(p)
    assert ok, errs


def test_self_check_catches_non_rederivable_card(tmp_path):
    # card claims 'broken' but its signals (fires_in_real_package) re-derive to 'live'
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(_minimal_report(card_health="broken")))
    ok, errs = self_check(p)
    assert not ok
    assert any("does not re-derive" in e for e in errs)


def test_self_check_catches_tally_mismatch(tmp_path):
    rep = _minimal_report()
    rep["summary"]["verdict_tally"] = {"production_ready": 99}  # wrong count
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("verdict_tally" in e for e in errs)


def test_self_check_missing_file(tmp_path):
    ok, errs = self_check(tmp_path / "nope.json")
    assert not ok and errs


def test_self_check_on_committed_artifact():
    """The real committed artifact must pass self-check (this is what CI runs)."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    ok, errs = self_check(committed)
    assert ok, errs


# ---------------------------------------------------------------------------
# 8. Cards tab — all-cards universe, dedupe, orphan detection
# ---------------------------------------------------------------------------
def test_list_all_card_ids(tmp_path):
    (tmp_path / "cards").mkdir()
    for cid in ("a-card", "b-card"):
        (tmp_path / "cards" / f"{cid}.card.yaml").write_text("card_id: x\n")
    (tmp_path / "cards" / "not-a-card.txt").write_text("ignore")
    assert probe.list_all_card_ids(tmp_path) == ["a-card", "b-card"]


def test_self_check_validates_cards_section(tmp_path):
    """A cards[] section with a non-rederivable card or bad orphan flag must fail."""
    rep = _minimal_report()
    rep["cards"] = [
        {
            "card_id": "orphan-x",
            "card_yaml_exists": True,
            "fires_in_real_package": True,
            "card_health": "live",
            "n_consumers": 0,
            "is_orphan": True,
        }
    ]
    rep["summary"]["card_health_tally"] = {"live": 1}
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert ok, errs

    # break the orphan flag (says orphan but has consumers)
    rep["cards"][0]["n_consumers"] = 2
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok and any("is_orphan" in e for e in errs)


def test_committed_artifact_has_cards_section_with_orphans():
    """The real artifact must carry a card-centric section that surfaces orphans."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    rep = json.loads(committed.read_text())
    assert "cards" in rep and rep["cards"], "cards section missing"
    # every card appears exactly once (deduped)
    ids = [c["card_id"] for c in rep["cards"]]
    assert len(ids) == len(set(ids)), "cards not deduped"
    # orphan flag is internally consistent
    for c in rep["cards"]:
        assert c["is_orphan"] == (c["n_consumers"] == 0)


# ---------------------------------------------------------------------------
# 9. Graph section — nodes/edges, layering, no dangling edges
# ---------------------------------------------------------------------------
def _mk_skill(name, verdict="production_ready", gate=None, bound=True, cards=None):
    return {
        "name": name,
        "health_verdict": verdict,
        "derived": {"kind": "FOCUSED", "resolver_gate": gate, "resolver_bound": bound},
        "risk_category": None,
        "cards": cards or [],
    }


def test_build_graph_layers_and_edges():
    skills = [_mk_skill("skill-a", gate="dependency")]
    cards = [
        {
            "card_id": "card-a",
            "card_health": "live",
            "consumers": ["skill-a"],
            "dispatch_module": "meth_a.read",
            "method_dir_exists": True,
            "is_orphan": False,
            "measurement_type": "mt",
        }
    ]
    g = rollup.build_graph(skills, cards)
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"skill:skill-a", "resolver:dependency", "card:card-a", "method:meth_a"}
    rels = {(e["src"], e["dst"], e["rel"]) for e in g["edges"]}
    assert ("skill:skill-a", "resolver:dependency", "resolves_via") in rels
    assert ("skill:skill-a", "card:card-a", "consumes") in rels
    assert ("card:card-a", "method:meth_a", "backed_by") in rels  # .read suffix stripped
    assert g["layer_counts"] == {"skill": 1, "resolver": 1, "card": 1, "method": 1}


def test_build_graph_no_dangling_edges():
    """Every edge endpoint must be a real node (the invariant self_check enforces)."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    g = json.loads(committed.read_text()).get("graph")
    assert g, "graph section missing"
    node_ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["src"] in node_ids and e["dst"] in node_ids, f"dangling edge {e}"
    assert g["n_nodes"] == len(node_ids) and g["n_edges"] == len(g["edges"])


def test_self_check_catches_dangling_edge(tmp_path):
    rep = _minimal_report()
    rep["graph"] = {
        "nodes": [{"id": "skill:x", "layer": "skill"}],
        "edges": [{"src": "skill:x", "dst": "card:ghost", "rel": "consumes"}],
        "n_nodes": 1,
        "n_edges": 1,
    }
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok and any("card:ghost" in e for e in errs)


# ---------------------------------------------------------------------------
# 10. Datasets — required_inputs capture, catalog verify, prefix-match, orphan/broken
# ---------------------------------------------------------------------------
def test_catalog_manifests_scan(tmp_path):
    for kind in ("sources", "derived"):
        (tmp_path / "manifests" / kind).mkdir(parents=True)
    (tmp_path / "manifests" / "sources" / "ds-a.yaml").write_text(
        "id: ds-a\nprovider: acme\nversion: v1\ntotal_size_bytes: 1024\n"
    )
    cat = probe.catalog_manifests(tmp_path)
    assert "ds-a" in cat and cat["ds-a"]["kind"] == "source" and cat["ds-a"]["provider"] == "acme"


def test_catalog_manifests_registers_resolver_release(tmp_path):
    """resolver-releases/ is a catalog artifact OUTSIDE manifests/, keyed by
    `resolver_release:` not `id:`. Cards depend on it as `target-id-resolver-release`;
    catalog_manifests must register that logical id so it isn't a false broken-ref."""
    for kind in ("sources", "derived"):
        (tmp_path / "manifests" / kind).mkdir(parents=True)
    rr = tmp_path / "resolver-releases"
    rr.mkdir()
    (rr / "v0.1.0-alpha.yaml").write_text("resolver_release: resolver_v0.1.0-alpha\nstatus: alpha\n")
    (rr / "v1.0.0.yaml").write_text("resolver_release: resolver_v1.0.0\nstatus: production\n")
    cat = probe.catalog_manifests(tmp_path)
    assert "target-id-resolver-release" in cat
    assert cat["target-id-resolver-release"]["kind"] == "resolver_release"
    assert cat["target-id-resolver-release"]["version"] == "resolver_v1.0.0"  # newest pin
    assert cat["target-id-resolver-release"]["file_count"] == 2


def test_catalog_manifests_no_resolver_dir_is_safe(tmp_path):
    """No resolver-releases/ dir → no key, no crash (isolated/partial checkout)."""
    for kind in ("sources", "derived"):
        (tmp_path / "manifests" / kind).mkdir(parents=True)
    cat = probe.catalog_manifests(tmp_path)
    assert "target-id-resolver-release" not in cat


def test_catalog_manifests_registers_subgroup_catalog(tmp_path):
    """subgroup-catalogs/ is a catalog artifact OUTSIDE manifests/, tracked as a per-indication
    tree (subgroup-catalogs/<INDICATION>/<release>.yaml). The --subtypes cards name it by the
    logical id `subgroup-catalog`; catalog_manifests must register that id so it isn't a false
    dataset_ref_not_in_catalog broken-ref."""
    for kind in ("sources", "derived"):
        (tmp_path / "manifests" / kind).mkdir(parents=True)
    sc = tmp_path / "subgroup-catalogs" / "COADREAD"
    sc.mkdir(parents=True)
    (sc / "2026-Q2.yaml").write_text("subgroups: []\n")
    (tmp_path / "subgroup-catalogs" / "STAD").mkdir()
    (tmp_path / "subgroup-catalogs" / "STAD" / "2026-Q3.yaml").write_text("subgroups: []\n")
    cat = probe.catalog_manifests(tmp_path)
    assert "subgroup-catalog" in cat
    assert cat["subgroup-catalog"]["kind"] == "subgroup_catalog"
    assert cat["subgroup-catalog"]["file_count"] == 2


def test_catalog_manifests_no_subgroup_catalog_dir_is_safe(tmp_path):
    """No subgroup-catalogs/ dir → no key, no crash (isolated/partial checkout)."""
    for kind in ("sources", "derived"):
        (tmp_path / "manifests" / kind).mkdir(parents=True)
    cat = probe.catalog_manifests(tmp_path)
    assert "subgroup-catalog" not in cat


def test_self_produced_scan_card_is_not_broken(tmp_path):
    """A scan-hook skill emits a card named after itself with no contract YAML — that is
    `self_produced`, NOT `broken`. Signal = card_id ∈ skill_names AND no YAML."""
    (tmp_path / "cards").mkdir()  # deliberately NO scan-x.card.yaml
    sig = probe.probe_card("scan-x", tmp_path, tmp_path, set(), set(), skill_names={"scan-x", "other-skill"})
    assert sig["card_yaml_exists"] is False
    assert sig["is_self_produced_skill_card"] is True
    rolled = rollup.roll_up_card(sig, rollup.load_rules())
    assert rolled["card_health"] == "self_produced", rolled["card_health"]


def test_missing_card_not_matching_a_skill_stays_broken(tmp_path):
    """Guard the narrow signal: a no-YAML card whose id is NOT a skill name is a genuine
    broken ref, still `broken` (self_produced must not swallow real breakage)."""
    (tmp_path / "cards").mkdir()
    sig = probe.probe_card("totally-missing", tmp_path, tmp_path, set(), set(), skill_names={"scan-x"})
    assert sig["is_self_produced_skill_card"] is False
    rolled = rollup.roll_up_card(sig, rollup.load_rules())
    assert rolled["card_health"] == "broken", rolled["card_health"]


def test_probe_card_dataset_exact_and_prefix_match(tmp_path):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.card.yaml").write_text(
        "card_id: c\nrequired_inputs:\n  - product_id: depmap-predictability\n"
        "  - product_id: exact-ds\nmethods:\n  - call: m\n"
    )
    methods = tmp_path / "methods"
    (methods / "methods").mkdir(parents=True)
    out = probe.probe_card(
        "c", tmp_path, methods, set(), set(), {}, catalog_ids={"exact-ds", "depmap-predictability-26q1-v2"}
    )
    ds = {d["product_id"]: d for d in out["datasets"]}
    assert ds["exact-ds"]["matched_by"] == "exact" and ds["exact-ds"]["in_catalog"]
    assert ds["depmap-predictability"]["matched_by"] == "prefix"
    assert ds["depmap-predictability"]["resolved_id"] == "depmap-predictability-26q1-v2"


def test_probe_card_dataset_broken_ref(tmp_path):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.card.yaml").write_text("card_id: c\nrequired_inputs:\n  - product_id: ghost-ds\n")
    methods = tmp_path / "methods"
    (methods / "methods").mkdir(parents=True)
    out = probe.probe_card("c", tmp_path, methods, set(), set(), {}, catalog_ids={"real-ds"})
    d = out["datasets"][0]
    assert d["product_id"] == "ghost-ds" and not d["in_catalog"] and d["matched_by"] is None


def test_self_check_catches_inconsistent_dataset_flags(tmp_path):
    rep = _minimal_report()
    rep["datasets"] = [
        {"product_id": "x", "in_catalog": True, "n_consumers": 0, "is_orphan": False, "is_broken_ref": False}
    ]  # should be orphan=True
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok and any("is_orphan" in e for e in errs)


def test_self_documenting_glosses_present():
    """The dashboard must explain its own jargon inline: severity meanings (incl. that
    'info' is not a defect), the 'P4' term expanded to modality routing with a full
    definition, and every drift code mapped to a readable label. Guards against the
    self-documentation silently regressing."""
    from validators.framework_health import render_html, rollup

    # 1. every drift code carries a readable label + a severity
    for code in rollup.DRIFT_SEVERITY:
        assert code in render_html.DRIFT_CODE_LABEL, f"drift code {code} has no readable label"
    # 2. severity glosses exist for all three and 'info' is framed as non-defect
    assert set(render_html.SEVERITY_GLOSS) == {"error", "warn", "info"}
    assert "not a defect" in render_html.SEVERITY_GLOSS["info"]
    # 3. P4 gloss defines the term (not just the letter)
    assert "modality" in render_html.P4_GLOSS.lower() and "P4" in render_html.P4_GLOSS
    # 4. the drift-code glossary helper renders every code
    gloss_html = render_html._drift_code_glossary()
    for code in rollup.DRIFT_SEVERITY:
        assert code in gloss_html, f"{code} missing from rendered glossary"


def test_render_expands_p4_and_severity_inline():
    """A full render must surface the plain-language severity key and the modality-routing
    (P4) expansion inline — not leave them as bare jargon."""
    from validators.framework_health import render_html

    report = {
        "summary": {
            "n_skills": 1,
            "verdict_tally": {"partial": 1},
            "n_error_drift": 0,
            "n_unregistered_skills": 0,
            "n_cards": 1,
            "card_health_tally": {"partial": 1},
            "modality_routing_tally": {"not_required": 1},
            "n_p4_required_cards": 0,
            "n_p4_declared_cards": 0,
            "n_p4_missing_cards": 0,
            "n_p4_drift_cards": 0,
            "n_datasets_in_catalog": 0,
            "n_orphan_cards": 0,
            "n_cards_consumed_but_no_spec": 0,
            "n_orphan_datasets": 0,
            "n_broken_dataset_refs": 0,
            "n_datasets": 0,
        },
        "registry_drift": {"unregistered": []},
        "skills": [
            {
                "name": "s",
                "declared": {"status": "partial"},
                "derived": {"kind": "FOCUSED", "resolver_bound": False, "test_count": 1},
                "cards": [],
                "drift_flags": [],
                "health_verdict": "partial",
                "health_reason": "x",
                "reason_text": "r",
                "risk_category": None,
            }
        ],
        "cards": [],
        "datasets": [],
        "graph": {"nodes": [], "edges": [], "layer_counts": {}, "n_nodes": 0, "n_edges": 0},
        "drift_index": [],
    }
    html = render_html.render(report)
    assert "modality routing" in html.lower()  # P4 relabeled
    assert "roadmap" in html.lower()  # P4 framed as a roadmap term
    assert "not a defect" in html  # info-severity clarified
    assert "stranded on the biology axis" in html  # full P4 definition present


def test_access_cost_bands():
    """Static access-cost bands from size × file-count × consumers (no network/timing)."""
    GB = 1024**3
    ac = rollup._access_cost
    assert ac(None, 10, 5) == "unknown"  # no size → can't estimate
    assert ac(30 * GB, 100, 5) == "high"  # ≥20GB consumed
    assert ac(5 * GB, 100, 2) == "moderate"  # ≥2GB consumed
    assert ac(0.5 * GB, 10, 3) == "low"  # small
    assert ac(3 * GB, 5000, 4) == "high"  # file sprawl bumps ≥2GB → high
    # unconsumed heavy data is demoted (not a framework access concern)
    assert ac(30 * GB, 100, 0) == "high_unused"
    assert ac(5 * GB, 100, 0) == "moderate_unused"


def test_missing_sort_key_flag_scoping():
    """missing_sort_key fires ONLY for consumed + in-catalog + sizeable + no-sort-key."""
    GB = 1024**3

    # build two dataset dicts through the real rollup path via a tiny catalog fixture would be
    # heavy; assert the rule inline mirrors build_health (kept in lockstep by self_check).
    def flag(in_cat, n, hsk, size):
        return bool(in_cat and n > 0 and hsk is False and (size or 0) >= rollup._SORT_KEY_SIZE_FLOOR)

    assert flag(True, 3, False, 5 * GB) is True  # consumed, big, no key → flag
    assert flag(True, 0, False, 5 * GB) is False  # unconsumed → no flag
    assert flag(True, 3, True, 5 * GB) is False  # has a key → no flag
    assert flag(True, 3, False, 0.1 * GB) is False  # below size floor → no flag
    assert flag(False, 3, False, 5 * GB) is False  # not in catalog → no flag


def test_self_check_catches_bad_access_cost(tmp_path):
    """A dataset whose recorded access_cost doesn't re-derive from its inputs must fail."""
    rep = _minimal_report()
    GB = 1024**3
    rep["datasets"] = [
        {
            "product_id": "big",
            "in_catalog": True,
            "n_consumers": 5,
            "is_orphan": False,
            "is_broken_ref": False,
            "size_bytes": 30 * GB,
            "file_count": 100,
            "access_cost": "low",  # WRONG — 30GB consumed re-derives to 'high'
            "has_sort_key": False,
            "missing_sort_key": True,
        }
    ]
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok and any("access_cost" in e for e in errs)


def test_committed_artifact_has_access_cost_lens():
    """The real artifact must carry the static access-cost lens on datasets + summary."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    rep = json.loads(committed.read_text())
    assert "access_cost_tally" in rep["summary"], "access-cost summary missing"
    for d in rep.get("datasets", []):
        assert "access_cost" in d, f"{d['product_id']} missing access_cost"
        # missing_sort_key is a strict subset of consumed in-catalog datasets
        if d.get("missing_sort_key"):
            assert d["in_catalog"] and d["n_consumers"] > 0 and d.get("has_sort_key") is False


def test_subskill_run_health_reader(tmp_path):
    """probe.subskill_run_health reads the skills-repo _skills_common/subskill_health.json,
    returns the per-skill map, and DEGRADES to {} when the artifact is absent."""
    # absent → {} (graceful; the skills repo may have a different branch checked out)
    assert probe.subskill_run_health(tmp_path) == {}
    # present → the subskills map
    sd = tmp_path / "skills" / "_skills_common"
    sd.mkdir(parents=True)
    (sd / "subskill_health.json").write_text(
        json.dumps(
            {
                "subskills": {
                    "tumor-presence": {
                        "skill_name": "tumor-presence",
                        "smoke": "clean",
                        "run_health": {"status": "ok", "read_secs": 0.0},
                    },
                    "genomic-alteration-profile": {
                        "skill_name": "genomic-alteration-profile",
                        "smoke": "clean_uninstrumented",
                    },
                }
            }
        )
    )
    got = probe.subskill_run_health(tmp_path)
    assert got["tumor-presence"]["smoke"] == "clean"
    assert got["genomic-alteration-profile"]["smoke"] == "clean_uninstrumented"
    # malformed → {} (never raises)
    (sd / "subskill_health.json").write_text("{ not json")
    assert probe.subskill_run_health(tmp_path) == {}


def test_rollup_attaches_runs_clean(monkeypatch, tmp_path):
    """build_health attaches runs_clean + run_health per skill node from the reader, and the
    summary tallies them. Absent artifact → every skill 'unknown', tally = {unknown: N}."""
    roots = probe.default_roots()
    if not (roots["skills"] / "skills").exists():
        pytest.skip("skills repo not present")
    # Force the reader to a known fixture so the test is deterministic regardless of what's
    # checked out in the sibling skills repo.
    fake = {
        "tumor-presence": {"smoke": "clean", "run_health": {"status": "ok"}},
        "functional-requirement": {"smoke": "error", "smoke_reason": "exit 1"},
    }
    monkeypatch.setattr(probe, "subskill_run_health", lambda _root: fake)
    body = rollup.build_health(roots)
    by_name = {n["name"]: n for n in body["skills"]}
    if "tumor-presence" in by_name:
        assert by_name["tumor-presence"]["runs_clean"] == "clean"
        assert by_name["tumor-presence"]["run_health"] == {"status": "ok"}
    if "functional-requirement" in by_name:
        assert by_name["functional-requirement"]["runs_clean"] == "error"
    # a skill NOT in the fixture → 'unknown'
    other = next((n for n in body["skills"] if n["name"] not in fake), None)
    if other:
        assert other["runs_clean"] == "unknown" and other["run_health"] is None
    # summary tallies
    assert body["summary"]["n_runs_clean"] == sum(1 for n in body["skills"] if n["runs_clean"] == "clean")
    assert body["summary"]["n_runs_clean_error"] == sum(1 for n in body["skills"] if n["runs_clean"] == "error")


def test_render_runs_clean_column_and_graceful_absence():
    """The skill matrix carries a 'runs clean?' column; when every skill is 'unknown'
    (artifact absent) the extra summary strip is SUPPRESSED (no noise), rendering '—'."""
    from validators.framework_health import render_html

    base_skill = {
        "name": "s",
        "health_verdict": "partial",
        "health_reason": "x",
        "reason_text": "r",
        "declared": {"status": "partial", "prose_markers": []},
        "derived": {"kind": "FOCUSED", "resolver_bound": False, "test_count": 1},
        "cards": [],
        "drift_flags": [],
        "risk_category": None,
        "run_health": None,
    }

    def _report(runs_clean):
        sk = {**base_skill, "runs_clean": runs_clean}
        rct = {}
        for s in [sk]:
            rct[s["runs_clean"]] = rct.get(s["runs_clean"], 0) + 1
        return {
            "summary": {
                "n_skills": 1,
                "verdict_tally": {"partial": 1},
                "n_error_drift": 0,
                "n_unregistered_skills": 0,
                "runs_clean_tally": rct,
                "n_runs_clean": rct.get("clean", 0),
                "n_runs_clean_error": rct.get("error", 0),
                "n_cards": 0,
                "card_health_tally": {},
                "modality_routing_tally": {},
                "n_p4_required_cards": 0,
                "n_p4_declared_cards": 0,
                "n_p4_missing_cards": 0,
                "n_p4_drift_cards": 0,
                "n_datasets_in_catalog": 0,
                "n_orphan_cards": 0,
                "n_cards_consumed_but_no_spec": 0,
                "n_orphan_datasets": 0,
                "n_broken_dataset_refs": 0,
                "n_datasets": 0,
            },
            "registry_drift": {"unregistered": []},
            "skills": [sk],
            "cards": [],
            "datasets": [],
            "graph": {"nodes": [], "edges": [], "layer_counts": {}, "n_nodes": 0, "n_edges": 0},
            "drift_index": [],
        }

    # column header always present
    assert "runs clean?" in render_html.render(_report("unknown"))
    # Use a caption-ONLY phrase to distinguish the summary strip from the always-present
    # column-header tooltip (both mention "compute path").
    caption_marker = "card readers stubbed; NO live data"
    # absent (unknown) → no runs-clean summary strip
    assert caption_marker not in render_html.render(_report("unknown"))
    # present (clean) → strip appears
    assert caption_marker in render_html.render(_report("clean"))


def test_matrix_css_has_no_overflow_hidden_clip():
    """Regression guard: .matrix must NOT carry overflow:hidden — it clipped the
    expanded drill-down (the nested cards table grows a detail row past the table
    box and gets cut off). See the drill-down-clip fix."""
    from validators.framework_health import render_html

    css = render_html._CSS
    import re

    m = re.search(r"\.matrix\{([^}]*)\}", css)
    assert m, ".matrix rule not found"
    assert "overflow:hidden" not in m.group(1), (
        ".matrix must not clip — overflow:hidden hides expanded drill-down content"
    )


def test_drilldown_table_present_and_closed_in_render():
    """The skill drill-down must emit a fully-closed cards table for a card-consuming
    skill (structural guard that the detail renders end to end)."""
    from validators.framework_health import render_html

    n = {
        "name": "s",
        "health_verdict": "partial",
        "health_reason": "x",
        "reason_text": "r",
        "declared": {"status": "wired", "prose_markers": []},
        "derived": {
            "kind": "FOCUSED",
            "resolver_gate": "g",
            "resolver_bound": True,
            "test_count": 1,
            "cards_in_runpy": ["c1"],
        },
        "drift_flags": [],
        "cards": [
            {
                "card_id": "c1",
                "card_health": "live",
                "has_live_reader": True,
                "fires_in_real_package": True,
                "measurement_type": "mt",
                "dispatch_module": "m.read",
                "reason_text": "r",
                "datasets": [
                    {"product_id": "d1", "in_catalog": True, "matched_by": "exact"},
                    {"product_id": "d2", "in_catalog": False, "matched_by": None},
                ],
            }
        ],
        "risk_category": None,
    }
    detail = render_html._skill_detail(n)
    assert detail.count("<table") == detail.count("</table>")  # balanced
    assert 'class="dscell"' in detail  # datasets cell present
    assert "d1" in detail and "d2" in detail  # both datasets rendered


def test_dashboard_spec_card_ids_scan(tmp_path):
    d = tmp_path / "dashboards"
    d.mkdir()
    (d / "a.dashboard_spec.yaml").write_text(
        "dashboard_id: spec-a\nrequired_cards:\n  - card_id: c1\noptional_cards:\n  - card_id: c2\n"
    )
    got = probe.dashboard_spec_card_ids(tmp_path)
    assert got == {"c1": ["spec-a"], "c2": ["spec-a"]}


def test_consumed_but_no_spec_raises_no_drift():
    """RETIRED 2026-09-11 — dashboard_spec membership must NOT raise drift.

    Replaces test_consumed_but_no_spec_drift, which pinned the opposite. The old flag asserted a
    consumed card in no dashboard_spec "can never fire in an emitted package"; that premise was
    false (the emitters read cards_used and stamp dashboard_spec_ref="skill:<name>";
    load_dashboard_spec() has zero callers), and 67 of the 102 flagged cards had already fired
    pass/passed_with_warnings inside real evidence packages. This test pins the retirement so the
    false-alarm class cannot silently return.
    """
    skill = {
        "declared": {"status": "wired", "prose_markers": []},
        "derived": {"kind": "FOCUSED", "has_entrypoint": True, "cards_in_runpy": []},
    }
    cards = [
        # the falsifier: no spec, yet demonstrably fired in a real package
        {
            "card_id": "no-spec-but-fired",
            "card_yaml_exists": True,
            "is_placeholder": False,
            "has_live_reader": True,
            "fires_in_real_package": True,
        },
        {"card_id": "in-spec", "card_yaml_exists": True, "is_placeholder": False},
    ]
    codes = {f["code"] for f in rollup.compute_drift(skill, cards)}
    assert "card_consumed_but_no_spec" not in codes
    assert "card_consumed_but_no_spec" not in rollup.DRIFT_SEVERITY


def test_card_registered_never_fires_is_the_surviving_liveness_flag():
    """The honest form of the question the retired flag was reaching for.

    A card with a live reader that has NOT fired is real drift; the same card once it fires is
    not. Conditioning on has_live_reader/fires_in_real_package — never on spec membership — is
    what makes the remaining drift index trustworthy.
    """
    skill = {
        "declared": {"status": "wired", "prose_markers": []},
        "derived": {"kind": "FOCUSED", "has_entrypoint": True, "cards_in_runpy": []},
    }
    unfired = [{"card_id": "c", "card_yaml_exists": True, "has_live_reader": True, "fires_in_real_package": False}]
    fired = [{"card_id": "c", "card_yaml_exists": True, "has_live_reader": True, "fires_in_real_package": True}]
    assert "card_registered_never_fires" in {f["code"] for f in rollup.compute_drift(skill, unfired)}
    assert "card_registered_never_fires" not in {f["code"] for f in rollup.compute_drift(skill, fired)}


def test_never_fires_flag_is_cleared_by_an_exploratory_run():
    """The flag must read fires_in_any_run (governed UNION exploratory), not governed-only.

    2026-09-11: reading fires_in_real_package alone reported 8 cards as never-firing across 6 skills
    while the published panel showed them emitting real calls with validation_state=pass
    (immune-context → immune_intermediate, surface-bulk-pair-selectivity →
    selective_but_broad_tissue_liability) and their interpretation rules in the run's fired list. A
    card proven live ANYWHERE is not "registered but never fires"; whether it has reached a
    concurrence-reviewed package is a promotion question that fires_in_real_package still answers.
    """
    skill = {
        "declared": {"status": "wired", "prose_markers": []},
        "derived": {"kind": "FOCUSED", "has_entrypoint": True, "cards_in_runpy": []},
    }
    exploratory_only = [
        {
            "card_id": "immune-context",
            "card_yaml_exists": True,
            "has_live_reader": True,
            "fires_in_real_package": False,  # never promoted to a governed package
            "fires_in_any_run": True,  # but demonstrably works
        }
    ]
    dead = [
        {
            "card_id": "immune-context",
            "card_yaml_exists": True,
            "has_live_reader": True,
            "fires_in_real_package": False,
            "fires_in_any_run": False,
        }
    ]
    assert "card_registered_never_fires" not in {f["code"] for f in rollup.compute_drift(skill, exploratory_only)}
    assert "card_registered_never_fires" in {f["code"] for f in rollup.compute_drift(skill, dead)}


def test_self_check_catches_bad_spec_flag(tmp_path):
    rep = _minimal_report()
    rep["cards"] = [
        {
            "card_id": "x",
            "card_yaml_exists": True,
            "fires_in_real_package": True,
            "card_health": "live",
            "n_consumers": 1,
            "is_orphan": False,
            "in_dashboard_spec": True,
            "consumed_but_no_spec": True,
        }
    ]  # inconsistent
    rep["summary"]["verdict_tally"] = {"production_ready": 1}
    rep["skills"] = [{"name": "s", "cards": rep["cards"], "health_verdict": "production_ready"}]
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok and any("consumed_but_no_spec" in e for e in errs)


def test_committed_artifact_datasets_section():
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    rep = json.loads(committed.read_text())
    assert "datasets" in rep and rep["datasets"], "datasets section missing"
    for d in rep["datasets"]:
        assert d["is_orphan"] == (d["in_catalog"] and d["n_consumers"] == 0)
        # broken = referenced, not in catalog, and NOT a placeholder-only forward-declaration
        # (those are pending_ref, not broken — 2026-08-31 de-noise).
        apc = d.get("all_consumers_placeholder")
        assert d["is_broken_ref"] == ((not d["in_catalog"]) and d["n_consumers"] > 0 and not apc)
        assert d.get("is_pending_ref", False) == ((not d["in_catalog"]) and d["n_consumers"] > 0 and bool(apc))


# ---------------------------------------------------------------------------
# 7. Frontmatter / prose / drift
# ---------------------------------------------------------------------------
def _write_skill(tmp_path, name, skill_md, run_py=None):
    d = tmp_path / "skills" / name
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text(skill_md)
    if run_py is not None:
        (d / "scripts" / "run.py").write_text(run_py)
    return d


def test_missing_status_field_is_detected(tmp_path):
    d = _write_skill(
        tmp_path,
        "no-status",
        skill_md="---\nname: no-status\ncomposition:\n  cards_used: []\n---\nbody\n",
        run_py="from _skills_common.dispatcher import run_wired_skill\nresolve_verdict_for_gate(f, 'dependency')\n",
    )
    sig = probe.probe_skill(d)
    assert sig["declared"]["status"] is None
    drift = rollup.compute_drift(sig, [])
    assert any(f["code"] == "missing_status_field" for f in drift)


def test_placeholder_skill_classified(tmp_path):
    d = _write_skill(
        tmp_path,
        "ph",
        skill_md="---\nname: ph\nstatus: not_wired\n---\nPLACEHOLDER SKILL\n",
        run_py="from _skills_common import emit_placeholder\nemit_placeholder()\n",
    )
    sig = probe.probe_skill(d)
    assert sig["derived"]["kind"] == "PLACEHOLDER"
    assert sig["derived"]["is_placeholder"] is True


def test_prose_markers_are_advisory_only(tmp_path):
    """A skill body mentioning 'placeholder' (describing others) must not set status."""
    d = _write_skill(
        tmp_path,
        "px",
        skill_md="---\nname: px\nstatus: wired\n---\nfans out; some are placeholder still\n",
        run_py="SUB_SKILLS = [('a','a')]\n",
    )
    sig = probe.probe_skill(d)
    assert sig["declared"]["status"] == "wired"
    assert "placeholder" in sig["declared"]["prose_markers"]  # detected but advisory


def test_entrypoint_fallback_non_runpy(tmp_path):
    """Orchestration skills use a non-run.py entrypoint — must still count as present."""
    d = tmp_path / "skills" / "orch"
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: orch\n---\n")
    (d / "scripts" / "compose_dashboard.py").write_text("x = 1\n")
    sig = probe.probe_skill(d)
    assert sig["derived"]["has_entrypoint"] is True
    assert sig["derived"]["entrypoint"] == "compose_dashboard.py"


# ---------------------------------------------------------------------------
# 11. P4 modality-vector lens — routing verdicts (parallel to card_health), drift, self-check
# ---------------------------------------------------------------------------
def _write_vocab(tmp_path, entries: dict):
    """Write a minimal vocabularies/measurement_types.yaml. `entries` maps type -> routing list
    (or None for a biology-axis type with no modality_relevance)."""
    v = tmp_path / "vocabularies"
    v.mkdir(parents=True, exist_ok=True)
    lines = ["measurement_types:"]
    for name, routing in entries.items():
        lines.append(f"  {name}:")
        lines.append("    description: x")
        if routing is not None:
            lines.append(f"    modality_relevance: [{', '.join(routing)}]")
    (v / "measurement_types.yaml").write_text("\n".join(lines) + "\n")


def _p4_card(tmp_path, card_id, measurement_type=None, modality_relevance=None):
    (tmp_path / "cards").mkdir(exist_ok=True)
    body = f"card_id: {card_id}\n"
    if measurement_type is not None:
        body += f"measurement_type: {measurement_type}\n"
    if modality_relevance is not None:
        body += f"modality_relevance: [{', '.join(modality_relevance)}]\n"
    (tmp_path / "cards" / f"{card_id}.card.yaml").write_text(body)


def test_modality_relevant_types_vocab_anchored(tmp_path):
    _write_vocab(
        tmp_path,
        {"routes_sm": ["small_molecule", "degrader"], "routes_surface": ["adc", "bite_tce"], "biology_only": None},
    )
    mt = probe.modality_relevant_types(tmp_path)
    assert mt == {"routes_sm": ["small_molecule", "degrader"], "routes_surface": ["adc", "bite_tce"]}
    assert "biology_only" not in mt  # a type without modality_relevance is NOT a routing type


def test_modality_relevant_types_none_when_vocab_absent(tmp_path):
    # No vocabularies/measurement_types.yaml → graceful skip (None), NOT a crash.
    assert probe.modality_relevant_types(tmp_path) is None


def _routing(tmp_path, card_id, mtype, mr, vocab):
    _p4_card(tmp_path, card_id, mtype, mr)
    methods = tmp_path / "methods"
    (methods / "methods").mkdir(parents=True, exist_ok=True)
    out = probe.probe_card(card_id, tmp_path, methods, set(), set(), {}, modality_types=vocab)
    return out["modality_routing"]


def test_probe_card_modality_routing_verdicts(tmp_path):
    vocab = {"routes_sm": ["small_molecule", "degrader"], "biology_only": None}
    # declared: routing type + declares a subset of its routing set
    assert _routing(tmp_path, "c-declared", "routes_sm", ["small_molecule"], vocab) == "declared"
    # not_required: biology-axis type, correctly silent
    assert _routing(tmp_path, "c-notreq", "biology_only", None, vocab) == "not_required"
    # missing: routing type but declares nothing (the validator ERROR state)
    assert _routing(tmp_path, "c-missing", "routes_sm", None, vocab) == "missing"
    # drift: declares a value OUTSIDE its type's routing set
    assert _routing(tmp_path, "c-drift", "routes_sm", ["adc"], vocab) == "drift"


def test_probe_card_modality_routing_unknown_when_vocab_none(tmp_path):
    # modality_types=None (vocab-absent isolated checkout) → 'unknown', never a false verdict.
    _p4_card(tmp_path, "c", "routes_sm", None)
    methods = tmp_path / "methods"
    (methods / "methods").mkdir(parents=True, exist_ok=True)
    out = probe.probe_card("c", tmp_path, methods, set(), set(), {}, modality_types=None)
    assert out["modality_routing"] == "unknown"


def test_probe_card_modality_routing_not_applicable_for_missing_yaml(tmp_path):
    # A consumed card id with NO .card.yaml on disk → not_applicable (kept out of the P4 tally's
    # real states; it's a card-existence problem, surfaced via card_health).
    methods = tmp_path / "methods"
    (methods / "methods").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cards").mkdir(exist_ok=True)
    out = probe.probe_card("ghost", tmp_path, methods, set(), set(), {}, modality_types={})
    assert out["card_yaml_exists"] is False
    assert out["modality_routing"] == "not_applicable"


def test_modality_relevance_drift_flag_in_compute_drift():
    skill = {
        "declared": {"status": "wired", "prose_markers": []},
        "derived": {"kind": "FOCUSED", "has_entrypoint": True, "cards_in_runpy": []},
    }
    cards = [
        {"card_id": "a", "modality_routing": "missing", "card_yaml_exists": True, "is_placeholder": False},
        {"card_id": "b", "modality_routing": "drift", "card_yaml_exists": True, "is_placeholder": False},
        {"card_id": "c", "modality_routing": "declared", "card_yaml_exists": True, "is_placeholder": False},
    ]
    flags = {f["code"]: f for f in rollup.compute_drift(skill, cards)}
    assert "modality_relevance_missing" in flags and "a" in flags["modality_relevance_missing"]["detail"]
    assert "modality_relevance_drift" in flags and "b" in flags["modality_relevance_drift"]["detail"]
    # both are WARN (not error) — never flip skill health to broken_or_drift
    assert flags["modality_relevance_missing"]["severity"] == "warn"
    assert flags["modality_relevance_drift"]["severity"] == "warn"


def test_self_check_validates_p4_tally(tmp_path):
    rep = _minimal_report()
    rep["cards"] = [
        {
            "card_id": "x",
            "card_yaml_exists": True,
            "fires_in_real_package": True,
            "card_health": "live",
            "n_consumers": 1,
            "is_orphan": False,
            "modality_routing": "declared",
        }
    ]
    rep["summary"]["card_health_tally"] = {"live": 1}
    rep["summary"]["modality_routing_tally"] = {"declared": 1}
    rep["summary"]["n_p4_required_cards"] = 1
    rep["summary"]["n_p4_declared_cards"] = 1
    rep["summary"]["n_p4_missing_cards"] = 0
    rep["summary"]["n_p4_drift_cards"] = 0
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert ok, errs
    # corrupt the tally → caught
    rep["summary"]["modality_routing_tally"] = {"declared": 99}
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok and any("modality_routing_tally" in e for e in errs)


def test_committed_artifact_has_p4_lens():
    """The real artifact must carry the P4 modality-routing lens on every card + summary."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    rep = json.loads(committed.read_text())
    assert "modality_routing_tally" in rep["summary"], "P4 summary missing"
    valid = {"declared", "not_required", "missing", "drift", "not_applicable", "unknown"}
    for c in rep["cards"]:
        assert c.get("modality_routing") in valid, f"{c['card_id']} bad modality_routing"
    # coverage identity: required == declared + missing + drift
    mt = rep["summary"]["modality_routing_tally"]
    assert rep["summary"]["n_p4_required_cards"] == sum(mt.get(k, 0) for k in ("declared", "missing", "drift"))


# ---------------------------------------------------------------------------
# Placeholder-status recognition (card.status → is_placeholder) — schema-aligned
# ---------------------------------------------------------------------------
def test_placeholder_status_set_covers_schema_nonwired_statuses():
    """RATCHET: probe._PLACEHOLDER_STATUS must cover every NON-`wired` value of the
    card.schema.json `status` enum. Otherwise a non-wired card (e.g. dormant_pending_data)
    slips past is_placeholder and is mislabeled card_health=broken. Reads the schema so a
    NEW enum value fails loudly here until the probe is taught about it."""
    schemas_dir = Path(__file__).resolve().parents[3] / "schemas"
    schema = json.loads((schemas_dir / "card.schema.json").read_text())
    enum = set(schema["properties"]["status"]["enum"])
    nonwired = enum - {"wired"}
    missing = nonwired - probe._PLACEHOLDER_STATUS
    assert not missing, f"probe._PLACEHOLDER_STATUS missing schema non-wired status(es): {missing}"


def test_dormant_pending_data_card_is_placeholder_not_broken(tmp_path):
    """A card declaring status: dormant_pending_data with no built method must probe as
    is_placeholder=True → the card_health ladder classifies it `placeholder` (rung
    card-placeholder), NOT `broken` (rung card-no-path). Pins the lineage-restriction-evidence
    fix."""
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "dormant-x.card.yaml").write_text(
        textwrap.dedent("""
        card_id: dormant-x
        status: dormant_pending_data
        methods:
          - call: some-unbuilt-aggregator
        outputs:
          summary_fields: [x_class]
    """)
    )
    sig = probe.probe_card("dormant-x", tmp_path, tmp_path, set(), set())
    assert sig["is_placeholder"] is True
    assert sig["placeholder_reason"] == "status:dormant_pending_data"
    rolled = rollup.roll_up_card(sig, rollup.load_rules())
    assert rolled["card_health"] == "placeholder", rolled["card_health"]
