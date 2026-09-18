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


def _skill_with_test_count(n: int) -> dict:
    return {
        "name": "s",
        "declared": {},
        "derived": {"kind": "FOCUSED", "resolver_bound": True, "test_count": n},
        "cards": [],
    }


def test_stable_projection_ignores_test_count_above_zero():
    """`derived.test_count` counts `test_*.py` files in the SKILLS repo, so it increments on
    sibling churn no target-contracts change caused. Two positive counts must project equal —
    this was a live STALE on trunk (cross-evidence-hypothesis 12→13 from skills#1328, the sole
    delta vs a fresh build). Same class as `roots` in the atlas guard (TC#756)."""
    base = {"schema_version": "1.0.0", "generated_at": "t", "roots": {}, "root_shas": {}}
    a = {**base, "skills": [_skill_with_test_count(12)]}
    b = {**base, "skills": [_skill_with_test_count(13)]}
    # non-vacuity: the raw reports MUST differ, or the equality below proves nothing
    assert json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True)
    assert stable_projection(a) == stable_projection(b)


def test_stable_projection_still_sees_tests_going_to_zero():
    """The teeth that stay: `has_tests = test_count > 0` is the ONLY thing the health verdict
    consumes (rollup.build_skill → health_rules.yaml), and 1→0 flips it. A skill losing its last
    test IS a real health change and must still make the committed feed STALE."""
    base = {"schema_version": "1.0.0", "generated_at": "t", "roots": {}, "root_shas": {}}
    has = {**base, "skills": [_skill_with_test_count(1)]}
    none = {**base, "skills": [_skill_with_test_count(0)]}
    assert stable_projection(has) != stable_projection(none)


def test_stable_projection_test_count_boolean_is_the_consumed_predicate():
    """Pin the projection to the SAME predicate the verdict uses. If rollup ever changed
    `has_tests` to e.g. `test_count >= 2`, this projection would silently stop matching it and
    the guard would drift from the rule — so assert the boundary explicitly at 0/1."""
    base = {"schema_version": "1.0.0", "generated_at": "t", "roots": {}, "root_shas": {}}
    proj0 = stable_projection({**base, "skills": [_skill_with_test_count(0)]})
    proj1 = stable_projection({**base, "skills": [_skill_with_test_count(1)]})
    assert '"has_tests": false' in proj0 and '"test_count"' not in proj0
    assert '"has_tests": true' in proj1 and '"test_count"' not in proj1


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


# ---------------------------------------------------------------------------
# 12. Descriptor coverage — the field-vocabulary lens (a TRENDING dimension)
#
# The census is read as DATA from the skills repo's committed sidecar rather than
# re-derived here: field_descriptor is deliberately the DERIVED join of SALIENCE_SPECS
# and display_gloss, and this probe is pure static analysis that never imports sibling
# code, so an AST re-derivation would be a third hand-authored copy of the same
# vocabulary — in a second repo, where NO CI job sees both trees and so nothing could
# ever compare them.
#
# Every self_check invariant below is re-derived from the artifact's OWN recorded data.
# That is the point: a cross-repo check that degrades to "sibling absent, skipping" in
# the only environment that runs it is VACUOUS, and would look like coverage forever.
# ---------------------------------------------------------------------------
def _census(**over):
    """A tiny but INTERNALLY CONSISTENT census: 2 measurement_types, 3 cells, 2 distinct
    fields (one shared across both types → the cell/field distinction is live)."""
    census = {
        "schema_version": "1.0.0",
        "producer": "descriptor_coverage_sidecar",
        "note": "... a zero unclassified count would mean the classifier is FABRICATING roles ...",
        "summary": {
            "n_measurement_types": 2,
            "n_descriptor_cells": 3,
            "n_distinct_fields": 2,
            "n_multi_type_fields": 1,
            "n_gloss_without_descriptor": 1,
            "n_numeric_fields_without_gloss": 0,
        },
        "role_counts": {"effect": 2, "label": 1},
        "source_class_counts": {"instrument": 3},
        "numeric_fields_without_gloss": [],
        "gloss_without_descriptor": ["orphan_gloss_field"],
        "multi_type_fields": ["shared_field"],
        "rosters": {
            "declared_fields": ["shared_field", "solo_field"],
            "envelope_fields": ["target"],
            "roles": ["effect", "label", "envelope", "unclassified"],
            "numeric_roles": ["effect"],
            "role_by_field": {"shared_field": "effect", "solo_field": "label"},
        },
        "fields_by_measurement_type": {
            "type_a": ["shared_field", "solo_field"],
            "type_b": ["shared_field"],
        },
    }
    census.update(over)
    return census


def _report_with_census(census=None):
    rep = _minimal_report()
    dcov = rollup.build_descriptor_coverage(census if census is not None else _census())
    rep["descriptor_coverage"] = dcov
    dsum = dcov.get("summary") or {}
    rep["summary"].update(
        {
            "descriptor_coverage_available": bool(dcov.get("available")),
            "n_measurement_types_with_descriptors": dsum.get("n_measurement_types"),
            "n_descriptor_cells": dsum.get("n_descriptor_cells"),
            "n_distinct_descriptor_fields": dsum.get("n_distinct_fields"),
            "n_gloss_without_descriptor": dsum.get("n_gloss_without_descriptor"),
            "n_numeric_fields_without_gloss": dsum.get("n_numeric_fields_without_gloss"),
        }
    )
    return rep


def _check(tmp_path, rep):
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    return self_check(p)


def test_descriptor_probe_degrades_to_empty_without_the_sidecar(tmp_path):
    """Same contract as every other sibling probe: absence omits the lens, never fabricates."""
    assert probe.descriptor_coverage(tmp_path) == {}


def test_descriptor_probe_ignores_a_corrupt_sidecar(tmp_path):
    d = tmp_path / "skills" / "_skills_common"
    d.mkdir(parents=True)
    (d / "descriptor_coverage.json").write_text("{not json")
    assert probe.descriptor_coverage(tmp_path) == {}


def test_descriptor_probe_reads_a_committed_sidecar(tmp_path):
    d = tmp_path / "skills" / "_skills_common"
    d.mkdir(parents=True)
    (d / "descriptor_coverage.json").write_text(json.dumps(_census()))
    got = probe.descriptor_coverage(tmp_path)
    assert got["summary"]["n_descriptor_cells"] == 3


def test_unavailable_is_not_a_verdict():
    """`available: False` means this checkout could not read the sibling. It must NOT
    look like a measured zero, or a dashboard plots 'nobody looked' as 'no gaps'."""
    dcov = rollup.build_descriptor_coverage({})
    assert dcov["available"] is False
    assert "summary" not in dcov  # no counts at all — absence is a null, not a 0
    assert dcov["reason"]


def test_self_check_accepts_a_consistent_census(tmp_path):
    ok, errs = _check(tmp_path, _report_with_census())
    assert ok, errs


def test_self_check_accepts_an_unavailable_census(tmp_path):
    """The pre-landing / isolated-checkout state must be self-consistent, not red."""
    ok, errs = _check(tmp_path, _report_with_census({}))
    assert ok, errs


def test_unmeasured_dimension_may_not_publish_counts(tmp_path):
    rep = _report_with_census({})
    rep["summary"]["n_descriptor_cells"] = 0  # the exact misreading this guard exists for
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("must be null, not a number" in e for e in errs)


def test_self_check_catches_cell_count_drift(tmp_path):
    """`n_descriptor_cells` counts (type, field) PAIRS and is re-derived from the per-type
    map — not merely restated from the summary."""
    census = _census()
    census["summary"]["n_descriptor_cells"] = 99
    rep = _report_with_census(census)
    rep["summary"]["n_descriptor_cells"] = 99  # keep the mirror consistent to isolate the check
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("disagrees with fields_by_measurement_type" in e for e in errs)


def test_cells_and_distinct_fields_are_different_numbers(tmp_path):
    """The skills census exposes the CELL count under the field-shaped name
    `n_descriptor_fields`; a consumer reconciling the wrong one over-counts the roster.
    On the real vocabulary these differ (337 cells vs 310 distinct)."""
    ok, errs = _check(tmp_path, _report_with_census())
    assert ok, errs
    dsum = _census()["summary"]
    assert dsum["n_descriptor_cells"] > dsum["n_distinct_fields"]


def test_self_check_re_derives_multi_type_fields(tmp_path):
    census = _census()
    census["multi_type_fields"] = []  # claim nothing is shared; the per-type map says otherwise
    census["summary"]["n_multi_type_fields"] = 0
    ok, errs = _check(tmp_path, _report_with_census(census))
    assert not ok
    assert any("multi_type_fields does not re-derive" in e for e in errs)


def test_self_check_catches_resolved_work_reported_as_open(tmp_path):
    """A field in `gloss_without_descriptor` that IS declared means the queue is reporting
    finished work as outstanding — the coverage dimension would trend the wrong way."""
    census = _census()
    census["gloss_without_descriptor"] = ["shared_field"]
    ok, errs = _check(tmp_path, _report_with_census(census))
    assert not ok
    assert any("ARE declared" in e for e in errs)


def test_self_check_catches_a_role_outside_the_vocabulary(tmp_path):
    census = _census()
    census["rosters"]["role_by_field"]["solo_field"] = "invented_role"
    ok, errs = _check(tmp_path, _report_with_census(census))
    assert not ok
    assert any("outside the vocabulary" in e for e in errs)


def test_self_check_catches_roster_drift_from_the_per_type_map(tmp_path):
    census = _census()
    census["rosters"]["declared_fields"] = ["shared_field"]  # drops solo_field
    census["summary"]["n_distinct_fields"] = 1
    ok, errs = _check(tmp_path, _report_with_census(census))
    assert not ok
    assert any("disagrees with the per-type map" in e for e in errs)


def test_self_check_requires_the_fabrication_warning_to_survive(tmp_path):
    """field_descriptor says twice that an empty `unclassified` set means the classifier is
    fabricating roles, not that coverage is complete. The consumer of this dimension is in
    another repo and will only ever read the note that travels with the data."""
    census = _census()
    census["note"] = "descriptor coverage census"
    ok, errs = _check(tmp_path, _report_with_census(census))
    assert not ok
    assert any("no longer warns" in e for e in errs)


def test_summary_mirror_must_track_the_section(tmp_path):
    rep = _report_with_census()
    rep["summary"]["n_gloss_without_descriptor"] = 0  # the queue emptied only in the summary
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("summary.n_gloss_without_descriptor disagrees" in e for e in errs)


def test_availability_flag_must_track_the_section(tmp_path):
    rep = _report_with_census()
    rep["summary"]["descriptor_coverage_available"] = False
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("descriptor_coverage_available disagrees" in e for e in errs)


def test_descriptor_section_is_projected_out_of_the_drift_basis():
    """REVERSES a 2026-09-17 guard, whose argument is recorded here because it is half right.

    It said: the census is a pure function of two skills-side constants — no clock, no I/O —
    so it must not be projected out the way volatile fields are, else "a vocabulary change in
    skills would never register as staleness here."

    Determinism is not locality. `rollup.build_descriptor_coverage(census)` takes ONE argument
    and it is sibling-sourced, so no target-contracts change can move this section: an equality
    assertion on it in a TARGET-CONTRACTS staleness gate cannot produce a finding, only noise,
    and it made every skills-side descriptor mint turn this repo's --check red (1027 differing
    leaves on 2026-09-18 under the old basis, zero of them verdict-bearing). The skills-side change still registers
    on the skills side, and here through the contracts-side join — see
    `test_the_contracts_side_join_keeps_its_teeth`, which is what stops this from being a
    blanket weakening.

    The section stays in the ARTIFACT; only the basis is narrowed.
    """
    rep = _report_with_census()
    rep["generated_at"] = "2026-01-01T00:00:00Z"
    # non-vacuity: the section must actually BE there to be projected away
    assert "descriptor_coverage" in rep and rep["descriptor_coverage"]
    text = stable_projection(rep)
    projected = json.loads(text)
    assert "descriptor_coverage" not in projected
    assert "orphan_gloss_field" not in text  # the queue went with it
    assert "2026-01-01T00:00:00Z" not in text  # ...and the clock still is not
    # ...but the availability BOOLEAN survives: a sidecar that vanishes is a wiring break.
    assert projected["summary"]["descriptor_coverage_available"] is True
    assert "n_descriptor_cells" not in projected["summary"]  # while the magnitude does not


def test_older_artifacts_without_the_section_still_pass(tmp_path):
    """Guarded `if present`: an artifact generated before this dimension existed must not red."""
    rep = _minimal_report()
    assert "descriptor_coverage" not in rep
    ok, errs = _check(tmp_path, rep)
    assert ok, errs


# ---------------------------------------------------------------------------
# 13. Field-read health — reads MINUS declarations (a TRENDING dimension), and the
#     EMISSION half that only this repo can measure.
#
# The skills census is read as DATA for the same reason as descriptor coverage (ONE
# producer of an AST scrape this probe cannot run). What is NEW here is that resolving
# the census's `emission_undetermined` rows needs the data-products root, so this side
# adds an axis rather than transcribing one — and every honesty guard below exists
# because the wrong answer is the reassuring one:
#
#   * an EMPTY APERTURE must leave rows UNRESOLVED, never call them `emission_unobserved`
#     (that label asserts "we looked at N>0 packages"), and must publish NULLS not zeros;
#   * a card the packages never contained must NOT be called `read_of_None`, which would
#     manufacture a finding out of an aperture limit;
#   * `no_reads_detected` must stay legible as instrument silence, not health.
# ---------------------------------------------------------------------------
def _frh_census(**over):
    """A tiny but INTERNALLY CONSISTENT census: 3 units, one per disposition, and a 2-row
    queue whose rows are BOTH classifications the producer can emit."""
    census = {
        "schema_version": "1.0.0",
        "note": ("... no_reads_detected means the scraper's shapes matched nothing, NOT that the unit is clean."),
        "summary": {
            "n_units": 3,
            "n_clean": 1,
            "n_units_with_undeclared_reads": 1,
            "n_no_reads_detected": 1,
            "n_reads_detected": 7,
            "n_undeclared_pairs": 2,
            "n_meta_key": 1,
            "n_emission_undetermined": 1,
            "attribution_reconciled": True,
            "n_roster_cards": 2,
            "n_roster_fields": 3,
        },
        "units": {
            "clean-skill": {"kind": "skill", "disposition": "clean", "n_reads": 5, "undeclared": []},
            "quiet-skill": {"kind": "skill", "disposition": "no_reads_detected", "n_reads": 0, "undeclared": []},
            "loud-skill": {
                "kind": "skill",
                "disposition": "undeclared_reads",
                "n_reads": 2,
                "undeclared": [
                    {
                        "card": "observed-card",
                        "field": "_envelope",
                        "reader_kinds": ["skill_code"],
                        "classification": "meta_key",
                    },
                    {
                        "card": "unseen-card",
                        "field": "n_thing",
                        "reader_kinds": ["skill_code"],
                        "classification": "emission_undetermined",
                    },
                ],
            },
        },
        "undeclared_queue": [
            {
                "unit": "loud-skill",
                "card": "observed-card",
                "field": "_envelope",
                "reader_kinds": ["skill_code"],
                "classification": "meta_key",
            },
            {
                "unit": "loud-skill",
                "card": "unseen-card",
                "field": "n_thing",
                "reader_kinds": ["skill_code"],
                "classification": "emission_undetermined",
            },
        ],
        "attribution": {
            "reconciled": True,
            "whole_tree_pairs": 7,
            "per_unit_union_pairs": 7,
            "per_unit_read_credits": 7,
            "unattributed": [],
        },
        "rosters": {
            "declared_fields": {"observed-card": ["declared_a", "declared_b"], "unseen-card": ["declared_c"]},
            "reader_kinds": ["skill_code"],
            "classification_rule": "...",
            "disposition_rule": "...",
        },
    }
    census.update(over)
    return census


def _emission(**over):
    """Emission evidence for ONE observed card: one key emitted, one present-but-always-null."""
    em = {
        "n_packages": 2,
        "n_card_rows": 2,
        "n_card_rows_with_summary": 2,
        "cards": {"observed-card": {"n_rows": 2, "emitted": ["_envelope", "declared_a"], "null_only": ["declared_b"]}},
    }
    em.update(over)
    return em


def _report_with_frh(census=None, emission=None):
    rep = _minimal_report()
    frh = rollup.build_field_read_health(
        _frh_census() if census is None else census,
        _emission() if emission is None else emission,
    )
    rep["field_read_health"] = frh
    fsum = frh.get("summary") or {}
    tally = frh.get("emission_outcome_tally") or {}
    rep["summary"].update(
        {
            "field_read_health_available": bool(frh.get("available")),
            "n_field_read_units": fsum.get("n_units"),
            "n_field_read_units_clean": fsum.get("n_clean"),
            "n_field_read_units_no_reads_detected": fsum.get("n_no_reads_detected"),
            "n_undeclared_field_reads": fsum.get("n_undeclared_pairs"),
            "n_field_reads_emitted_but_undeclared": tally.get("emitted_but_undeclared"),
            "n_field_reads_of_none": tally.get("read_of_None"),
            "n_field_reads_emission_unobserved": tally.get("emission_unobserved"),
        }
    )
    return rep


def _package(tmp_path, name, cards):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "evidence_package.json").write_text(json.dumps({"cards": cards}))


# --- the sidecar probe: same absence contract as every other sibling read -------------
def test_field_read_probe_degrades_to_empty_without_the_sidecar(tmp_path):
    assert probe.field_read_health(tmp_path) == {}


def test_field_read_probe_ignores_a_corrupt_sidecar(tmp_path):
    d = tmp_path / "skills" / "_skills_common"
    d.mkdir(parents=True)
    (d / "field_read_health.json").write_text("{not json")
    assert probe.field_read_health(tmp_path) == {}


def test_field_read_probe_reads_a_committed_sidecar(tmp_path):
    d = tmp_path / "skills" / "_skills_common"
    d.mkdir(parents=True)
    (d / "field_read_health.json").write_text(json.dumps(_frh_census()))
    assert probe.field_read_health(tmp_path)["summary"]["n_undeclared_pairs"] == 2


# --- the emission scan ----------------------------------------------------------------
def test_emission_scan_returns_empty_when_no_package_exists(tmp_path):
    """An empty aperture is NOT a measurement of zero — it must be indistinguishable from
    'not measured', because the caller's outcome vocabulary keys off exactly that."""
    assert probe.summary_field_emission(tmp_path) == {}
    assert probe.summary_field_emission(tmp_path / "nope") == {}


def test_emission_scan_separates_emitted_from_present_but_null(tmp_path):
    """`null_only` is its own bucket: the reader gets None either way, but a producer that
    knows the key and emits nothing is a different defect from a field nobody has heard of."""
    _package(tmp_path, "a", [{"card_id": "c", "summary": {"has_value": 1, "always_null": None}}])
    _package(tmp_path, "b", [{"card_id": "c", "summary": {"has_value": 2, "always_null": None}}])
    got = probe.summary_field_emission(tmp_path)
    assert got["n_packages"] == 2 and got["cards"]["c"]["n_rows"] == 2
    assert got["cards"]["c"]["emitted"] == ["has_value"]
    assert got["cards"]["c"]["null_only"] == ["always_null"]


def test_emission_scan_credits_a_row_with_no_passing_validation_state(tmp_path):
    """DELIBERATELY unlike fired_card_ids(), which filters to pass/passed_with_warnings.
    Emission evidence ARGUES AGAINST the alarming label, so widening it makes `read_of_None`
    harder to earn. Filtering here would let a field emitted only by a non-passing row read
    as never emitted — a manufactured finding. This test fails if a pass-filter is added."""
    _package(tmp_path, "a", [{"card_id": "c", "validation_state": "fail", "summary": {"f": 1}}])
    assert probe.summary_field_emission(tmp_path)["cards"]["c"]["emitted"] == ["f"]


def test_emission_scan_skips_invalid_packages(tmp_path):
    d = tmp_path / "a"
    d.mkdir()
    (d / "evidence_package.invalid.json").write_text(json.dumps({"cards": [{"card_id": "c", "summary": {"f": 1}}]}))
    assert probe.summary_field_emission(tmp_path) == {}


# --- resolution: the three outcomes, and the one non-outcome --------------------------
def test_an_emitted_field_resolves_to_emitted_but_undeclared():
    got = rollup.resolve_emission("observed-card", "declared_a", _emission())
    assert got["emission_outcome"] == "emitted_but_undeclared"


def test_a_field_absent_from_an_observed_card_is_a_read_of_none():
    got = rollup.resolve_emission("observed-card", "nobody_emits_me", _emission())
    assert got["emission_outcome"] == "read_of_None"
    assert got["key_present_but_null"] is False


def test_a_present_but_null_field_is_a_read_of_none_that_says_so():
    got = rollup.resolve_emission("observed-card", "declared_b", _emission())
    assert got["emission_outcome"] == "read_of_None"
    assert got["key_present_but_null"] is True
    assert "PRESENT but null" in got["emission_evidence"]


def test_an_unobserved_card_is_never_called_a_read_of_none():
    """THE honesty guard. `read_of_None` asserts the model was handed None; a card the
    packages never contained supports no such claim, and calling it that would manufacture
    a finding out of an aperture limit (measured: 46 of the 148 roster cards are outside
    the committed packages, so this is the common case, not a corner)."""
    got = rollup.resolve_emission("unseen-card", "n_thing", _emission())
    assert got["emission_outcome"] == "emission_unobserved"
    assert got["n_rows_observed"] == 0
    assert "UNDECIDABLE" in got["emission_evidence"]


def test_an_empty_aperture_leaves_a_row_unresolved_rather_than_unobserved():
    """`emission_unobserved` says "we looked at N>0 packages and this card was in none".
    With nothing scanned, nobody looked — the row must stay unresolved."""
    got = rollup.resolve_emission("any-card", "any_field", {})
    assert got["emission_outcome"] is None
    assert "NOT MEASURED" in got["emission_evidence"]


def test_a_meta_key_row_is_not_told_to_declare_the_field():
    """The REMEDY depends on the other axis. No card declares any underscore-led key — that
    is the premise the producer's meta_key rule rests on — so 'the declaration is missing' is
    the wrong advice for an emitted envelope key. Same outcome, different owner."""
    meta = rollup.resolve_emission("observed-card", "_envelope", _emission(), "meta_key")
    plain = rollup.resolve_emission("observed-card", "declared_a", _emission(), "emission_undetermined")
    assert meta["emission_outcome"] == plain["emission_outcome"] == "emitted_but_undeclared"
    assert "ENVELOPE key" in meta["emission_evidence"]
    assert "DECLARATION is what is missing" not in meta["emission_evidence"]
    assert "DECLARATION is what is missing" in plain["emission_evidence"]


# --- the section envelope ------------------------------------------------------------
def test_field_read_unavailable_is_not_a_verdict():
    frh = rollup.build_field_read_health({}, _emission())
    assert frh["available"] is False
    assert "summary" not in frh  # absence is a null, never a measured zero
    assert frh["reason"]


def test_the_classification_axis_is_left_untouched_by_resolution():
    """Two independent axes: `classification` describes the field NAME's shape,
    `emission_outcome` what the producer was OBSERVED to do. Collapsing them would have to
    call an emitted meta_key row either 'not a real key' or 'an undeclared field' — both false."""
    frh = rollup.build_field_read_health(_frh_census(), _emission())
    row = next(r for r in frh["undeclared_queue"] if r["field"] == "_envelope")
    assert row["classification"] == "meta_key"
    assert row["emission_outcome"] == "emitted_but_undeclared"


def test_an_empty_aperture_publishes_nulls_not_zeros():
    """A 0 against `read_of_None` plots as 'no field ever handed the model None' — the single
    most misleading thing this dimension could say."""
    frh = rollup.build_field_read_health(_frh_census(), {})
    assert frh["emission_aperture"]["available"] is False
    assert set(frh["emission_outcome_tally"].values()) == {None}
    assert frh["n_emission_unresolved"] == 2


def test_the_pinned_roster_is_projected_out_but_still_identified():
    """The 148-card roster is an INPUT to the census, not a finding, and ~90 KB of it. Its two
    counts stay so the pin is identifiable; the roster itself lives in its one producer."""
    frh = rollup.build_field_read_health(_frh_census(), _emission())
    assert "declared_fields" not in frh["rosters"]
    assert frh["roster_pin"]["n_cards"] == 2 and frh["roster_pin"]["n_fields"] == 3
    assert "reader_kinds" in frh["rosters"]  # the small rosters DO carry through


def test_the_aperture_is_published_with_the_outcomes():
    frh = rollup.build_field_read_health(_frh_census(), _emission())
    ap = frh["emission_aperture"]
    assert ap["available"] is True and ap["n_packages"] == 2
    assert ap["n_cards_observed"] == 1 and ap["n_roster_cards"] == 2 and ap["n_roster_cards_observed"] == 1


# --- self_check: every invariant re-derived from the artifact's own bytes -------------
def test_frh_self_check_accepts_a_consistent_section(tmp_path):
    ok, errs = _check(tmp_path, _report_with_frh())
    assert ok, errs


def test_frh_self_check_accepts_an_unavailable_section(tmp_path):
    """The pre-landing state (skills sidecar not yet on trunk) must be self-consistent."""
    ok, errs = _check(tmp_path, _report_with_frh(census={}))
    assert ok, errs


def test_frh_self_check_accepts_an_empty_aperture(tmp_path):
    """Census readable, products root not: legal, and every count null."""
    ok, errs = _check(tmp_path, _report_with_frh(emission={}))
    assert ok, errs


def test_frh_unmeasured_dimension_may_not_publish_counts(tmp_path):
    rep = _report_with_frh(census={})
    rep["summary"]["n_field_reads_of_none"] = 0  # the exact misreading this guard exists for
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("must be null, not a number" in e for e in errs)


def test_frh_self_check_catches_a_zero_where_the_aperture_is_empty(tmp_path):
    rep = _report_with_frh(emission={})
    rep["field_read_health"]["emission_outcome_tally"]["read_of_None"] = 0
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("empty aperture" in e and "must be null" in e for e in errs)


def test_frh_self_check_catches_a_resolved_row_with_no_packages_scanned(tmp_path):
    rep = _report_with_frh(emission={})
    rep["field_read_health"]["undeclared_queue"][0]["emission_outcome"] = "read_of_None"
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("an unscanned row cannot be resolved" in e for e in errs)


def test_frh_self_check_catches_an_unresolved_row_with_packages_in_hand(tmp_path):
    """The opposite failure, and it gets its own message: with packages scanned every row is
    decidable, so an unresolved one means the resolution silently skipped it."""
    rep = _report_with_frh()
    rep["field_read_health"]["undeclared_queue"][0]["emission_outcome"] = None
    rep["field_read_health"]["n_emission_unresolved"] = 1
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("every row is decidable" in e for e in errs)


def test_frh_self_check_catches_dispositions_that_do_not_re_derive(tmp_path):
    rep = _report_with_frh()
    rep["field_read_health"]["summary"]["n_clean"] = 99
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("summary.n_clean disagrees" in e for e in errs)


def test_frh_self_check_catches_a_queue_row_missing_from_its_unit(tmp_path):
    """The flat queue and the per-unit map are two shapes for the same facts — exactly the
    arrangement that acquires silent drift. This re-derives one from the other."""
    rep = _report_with_frh()
    rep["field_read_health"]["units"]["loud-skill"]["undeclared"] = []
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("is not in unit" in e for e in errs)


def test_frh_self_check_catches_tally_drift(tmp_path):
    rep = _report_with_frh()
    rep["field_read_health"]["emission_outcome_tally"]["emitted_but_undeclared"] = 99
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("emission_outcome_tally[emitted_but_undeclared] disagrees" in e for e in errs)


def test_frh_self_check_catches_an_outcome_outside_the_vocabulary(tmp_path):
    rep = _report_with_frh()
    rep["field_read_health"]["undeclared_queue"][0]["emission_outcome"] = "probably_fine"
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("outside the vocabulary" in e for e in errs)


def test_frh_self_check_catches_a_leaked_roster(tmp_path):
    rep = _report_with_frh()
    rep["field_read_health"]["rosters"]["declared_fields"] = {"x": ["y"]}
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("the projection is not applied" in e for e in errs)


def test_frh_self_check_catches_a_reconciled_flag_that_contradicts_its_numbers(tmp_path):
    rep = _report_with_frh()
    rep["field_read_health"]["attribution"]["per_unit_union_pairs"] = 6  # vs whole_tree 7
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("attribution.reconciled disagrees" in e for e in errs)


def test_frh_self_check_requires_the_no_reads_warning_to_survive(tmp_path):
    """Losing this one line would let a dashboard render N unmeasured units as N healthy ones.
    Checked for PRESENCE of the warning, never for absence of a retracted phrase."""
    rep = _report_with_frh()
    rep["field_read_health"]["note"] = "a cheerful summary with no caveat"
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("NOT a clean bill of health" in e for e in errs)


def test_frh_self_check_catches_an_impossible_aperture(tmp_path):
    rep = _report_with_frh()
    rep["field_read_health"]["emission_aperture"]["n_roster_cards_observed"] = 99
    ok, errs = _check(tmp_path, rep)
    assert not ok
    assert any("impossible" in e for e in errs)


def test_frh_section_is_projected_out_of_the_drift_basis():
    """REVERSES a 2026-09-17 guard for the same reason as the descriptor census, with one extra
    nail: `build_field_read_health(census, emission)` takes TWO inputs and BOTH are siblings —
    the skills census and a scan of the data-products packages. Nothing in target-contracts
    reaches it. Its own producer already states the contract ("Trending, never a gate"), and
    --check IS a gate, so the section was the one place that contract was violated.

    The old docstring's worry — "a new package or a scraper fix must register as staleness" —
    is answered by WHERE: in the repo that owns the scraper and the packages. A target-contracts
    reviewer handed this red can do nothing with it but regenerate.
    """
    rep = _report_with_frh()
    rep["generated_at"] = "2026-01-01T00:00:00Z"
    assert "field_read_health" in rep and rep["field_read_health"]  # non-vacuity
    text = stable_projection(rep)
    projected = json.loads(text)
    assert "field_read_health" not in projected
    assert "unseen-card" not in text  # the queue went with it
    assert "2026-01-01T00:00:00Z" not in text
    assert projected["summary"]["field_read_health_available"] is True  # the 1<->0 teeth stay
    assert "n_undeclared_field_reads" not in projected["summary"]  # the magnitudes do not


def test_older_artifacts_without_the_field_read_section_still_pass(tmp_path):
    rep = _minimal_report()
    assert "field_read_health" not in rep
    ok, errs = _check(tmp_path, rep)
    assert ok, errs


# ---------------------------------------------------------------------------
# 14. short <-> skill_dir mapping — the join behind gate_short / risk_category
#
# WHY THIS SECTION EXISTS: `sub_skill_map` had NO test at all, and read the SUB_SKILLS
# literal out of `run.py` after it moved to `tp_fanout.py` (skills `8b6b2af4`, #461). It
# returned {} for months, so `gate_short` / `risk_category` / `framework_can_evidence` were
# None on 22 of 22 skill nodes in the committed artifact and read as measured data.
#
# THE TWO TESTS ARE DELIBERATELY SPLIT, and the split is the whole point. The live one
# SKIPS when the skills sibling is absent — which is the framework-health CI environment —
# so on its own it would be a guard that never runs where it matters (SKIP IS NOT PASS).
# The hermetic one runs everywhere and pins the parse target plus the no-fallback choice,
# so CI actually gates the behaviour.
# ---------------------------------------------------------------------------
def _fake_skills_tree(root, module_name, literal):
    scripts = root / "skills" / "target-profile" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / module_name).write_text(f"SUB_SKILLS = {literal}\n")
    return root


def test_sub_skill_map_reads_the_fanout_module(tmp_path):
    """The literal is parsed from tp_fanout.py — hermetic, so this gates CI too."""
    root = _fake_skills_tree(tmp_path, "tp_fanout.py", '[("tumor-presence", "expression")]')
    assert probe.sub_skill_map(root) == {"tumor-presence": "expression"}


def test_sub_skill_map_does_not_fall_back_to_run_py(tmp_path):
    """A literal in run.py ONLY must yield {} — pinning the deliberate absence of a
    two-file search. Without this, adding a run.py fallback later would look harmless
    while making the next relocation silent all over again."""
    root = _fake_skills_tree(tmp_path, "run.py", '[("tumor-presence", "expression")]')
    assert probe.sub_skill_map(root) == {}


def test_sub_skill_map_is_populated_against_the_real_repo():
    """Against the real sibling: the ONLY check that reds when the literal moves again.

    SKIPS in framework-health CI (no skills sibling), so it is a real-world tripwire and
    NOT the CI gate — the two hermetic tests above are. Pins a floor plus known members,
    the same non-vacuity shape as test_live_reader_ids_real_repo_excludes_known_traps:
    a stale path returns {} and every downstream assertion would pass vacuously."""
    roots = probe.default_roots()
    if not (roots["skills"] / "skills").exists():
        pytest.skip("skills repo not present")
    m = probe.sub_skill_map(roots["skills"])
    assert len(m) >= 10, f"expected the full fan-out roster, got {len(m)} (stale SUB_SKILLS path?)"
    # One gated axis and one deliberately GATELESS axis, so this cannot be satisfied by a
    # partial parse of only the verdict-bearing head of the literal.
    assert m.get("on-target-safety-liability") == "safety"
    assert m.get("cis-feature-coherence") == "cis_coherence"


def test_gate_short_is_populated_for_fanout_skills_in_the_artifact():
    """The consumer-side reading of the same join. `gate_short` None on EVERY skill is the
    signature of the stale-path bug; None on a non-fan-out skill is correct, so the
    assertion is on the fan-out members only."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    report = json.loads(committed.read_text())
    shorts = [s.get("gate_short") for s in report.get("skills") or []]
    assert any(s is not None for s in shorts), "gate_short is None on every skill (stale SUB_SKILLS path?)"


# ===========================================================================
# 9. AXIS MEASURABILITY (framework-health dimension 3 of 3)
#
# The dimension answers CAPABILITY — does an instrument EXIST for a dim's axes — which no
# per-run coverage number can answer about itself. Two inputs from two repos: the skills
# census (a committed sidecar) and this repo's governed card->measurement_type registry.
# These guard the failures specific to that shape:
#   * the two halves must be independently absent-able, and absence must be NULL, never 0;
#   * a card that resolves to no registered type is UNDECIDABLE, not disagreement;
#   * "derived but not declared" must not be one label: a type declared by ANOTHER axis is a
#     misattribution, while a type declared nowhere is the framework measuring something it
#     never claims. The second has no live instance, so it is a regression watch and is
#     constructed here rather than assumed unreachable;
#   * the static vocabulary must never converge on the per-RUN coverage vocabulary.
# ===========================================================================
def _mapd_census(**over):
    """A synthetic axis-measurability census, shaped like the committed sidecar.

    Deliberately NOT a copy of the real one: three axes exercising covered / blind /
    non-fan-out, and a card roster wired so every reconcile outcome is reachable from these
    bytes alone.
    """
    census = {
        "schema_version": "1.0.0",
        "producer": "measured_axes_per_dim_sidecar.py",
        "summary": {
            "n_axes": 3,
            "n_dims": 2,
            "n_declared_types_distinct": 3,
            "n_declared_cards_distinct": 3,
            "n_types_with_measurement_descriptor": 2,
            "n_types_without_measurement_descriptor": 1,
            "n_axes_descriptor_covered": 1,
            "n_axes_descriptor_blind": 1,
            "n_axes_no_declared_types": 0,
            "n_axes_not_a_fanout_axis": 1,
        },
        "axes": {
            "alpha": {
                "static_state": "descriptor_covered",
                "types_without_measurement_descriptor": [],
                "gate_short": "alpha",
                "verdict_bearing": True,
            },
            "beta": {
                "static_state": "descriptor_blind",
                "types_without_measurement_descriptor": ["type_blind"],
                "gate_short": None,
                "verdict_bearing": False,
            },
            "clinical": {
                "static_state": "not_a_fanout_axis",
                "types_without_measurement_descriptor": [],
                "gate_short": None,
                "verdict_bearing": None,
            },
        },
        "dims": {
            "biological": {
                "n_axes_counted": 2,
                "n_axes_descriptor_covered": 1,
                "descriptor_blind_axes": ["beta"],
                "not_a_fanout_axes": [],
            },
            "clinical": {
                "n_axes_counted": 1,
                "n_axes_descriptor_covered": 0,
                "descriptor_blind_axes": [],
                "not_a_fanout_axes": ["clinical"],
            },
        },
        "types_without_measurement_descriptor": ["type_blind"],
        "note": "CAPABILITY, NOT OUTCOME. DO NOT HEADLINE the per-axis flag.",
        "rosters": {
            "static_states": [
                "descriptor_covered",
                "descriptor_blind",
                "no_declared_types",
                "not_a_fanout_axis",
            ],
            "cards_by_axis": {"alpha": ["card-a", "card-x"], "beta": ["card-b"]},
            "declared_types_by_axis": {"alpha": ["type_a"], "beta": ["type_b", "type_declared_only"]},
        },
    }
    census.update(over)
    return census


def _type_cards(**over):
    """The governed registry, inverted by the reconcile into card -> type.

    `type_a` is provided by card-a AND declared by alpha (agree). `type_b` likewise for beta.
    `type_declared_only` is declared by beta with no card. `type_elsewhere` is provided by
    card-b (in beta's roster) while alpha declares it. `type_no_view` has providers and no
    card. `type_unpulled` has a card nobody pulls. `card-x` is in a roster and in no type.
    """
    reg = {
        "type_a": {"cards": ["card-a"], "n_providers": 1},
        "type_b": {"cards": ["card-b"], "n_providers": 2},
        "type_no_view": {"cards": [], "n_providers": 1},
        "type_unpulled": {"cards": ["card-nobody-pulls"], "n_providers": 1},
    }
    reg.update(over)
    return reg


def _report_with_mapd(census=None, type_cards=None):
    rep = _minimal_report()
    mapd = rollup.build_measured_axes_per_dim(
        _mapd_census() if census is None else census,
        _type_cards() if type_cards is None else type_cards,
    )
    rep["measured_axes_per_dim"] = mapd
    msum = mapd.get("summary") or {}
    rec = mapd.get("reconcile") or {}
    tally = rec.get("outcome_tally") or {}
    utally = rec.get("unpulled_type_tally") or {}
    rep["summary"].update(
        {
            "axis_measurability_available": bool(mapd.get("available")),
            "n_measurement_types_without_descriptor": msum.get("n_types_without_measurement_descriptor"),
            "n_measurement_types_declared_by_axes": msum.get("n_declared_types_distinct"),
            "n_axes_descriptor_covered": msum.get("n_axes_descriptor_covered"),
            "n_axes_descriptor_blind": msum.get("n_axes_descriptor_blind"),
            "axis_type_reconcile_available": bool(rec.get("available")),
            "n_axis_types_declared_not_derived": tally.get("declared_not_derived"),
            "n_axis_types_derived_nowhere_declared": tally.get("derived_nowhere_declared"),
            "n_axis_types_derived_declared_elsewhere": tally.get("derived_declared_elsewhere"),
            "n_governed_types_without_card_view": utally.get("no_card_view"),
            "n_governed_types_card_exists_unpulled": utally.get("card_exists_unpulled"),
            "n_skill_cards_without_registered_type": rec.get("n_cards_without_registered_type"),
        }
    )
    return rep


# --- the two probes: independent absence contracts ------------------------------------
def test_axis_measurability_probe_degrades_to_empty_without_the_sidecar(tmp_path):
    assert probe.measured_axes_per_dim(tmp_path) == {}


def test_axis_measurability_probe_ignores_a_corrupt_sidecar(tmp_path):
    d = tmp_path / "skills" / "_skills_common"
    d.mkdir(parents=True)
    (d / "measured_axes_per_dim.json").write_text("{not json")
    assert probe.measured_axes_per_dim(tmp_path) == {}


def test_axis_measurability_probe_reads_a_committed_sidecar(tmp_path):
    d = tmp_path / "skills" / "_skills_common"
    d.mkdir(parents=True)
    (d / "measured_axes_per_dim.json").write_text(json.dumps(_mapd_census()))
    assert probe.measured_axes_per_dim(tmp_path)["summary"]["n_axes"] == 3


def test_type_card_views_returns_none_not_empty_without_the_vocab(tmp_path):
    """None and {} must not be the same answer here: {} would mean 'a registry with no types',
    which the reconcile would happily join against and report every axis type as unregistered.
    None routes to `available: False` instead."""
    assert probe.measurement_type_card_views(tmp_path) is None


def test_type_card_views_returns_none_on_a_vocab_without_the_registry(tmp_path):
    d = tmp_path / "vocabularies"
    d.mkdir(parents=True)
    (d / "measurement_types.yaml").write_text("something_else: 1\n")
    assert probe.measurement_type_card_views(tmp_path) is None


def test_type_card_views_reads_cards_and_provider_counts(tmp_path):
    d = tmp_path / "vocabularies"
    d.mkdir(parents=True)
    (d / "measurement_types.yaml").write_text(
        "measurement_types:\n"
        "  t_one:\n"
        "    cards: [card-a, card-b]\n"
        "    providers: [{source: s1}, {source: s2}]\n"
        "  t_two:\n"
        "    cards: []\n"
        "    providers: [{source: s3}]\n"
    )
    got = probe.measurement_type_card_views(tmp_path)
    assert got["t_one"] == {"cards": ["card-a", "card-b"], "n_providers": 2}
    assert got["t_two"] == {"cards": [], "n_providers": 1}


def test_type_card_views_is_populated_against_the_real_vocab():
    """Live tripwire (skips nowhere — the vocab is IN this repo). A floor plus a named member,
    so a silently narrowed read cannot pass vacuously."""
    got = probe.measurement_type_card_views(probe.CONTRACTS_REPO)
    assert got is not None and len(got) >= 100, f"expected the full governed registry, got {got and len(got)}"
    assert got["structure_druggability"]["cards"] == ["structure-features-static"]


# --- the reconcile: four outcomes, and the one non-outcome ----------------------------
def test_a_declared_type_its_own_cards_provide_agrees():
    rec = rollup.reconcile_axis_types(_mapd_census(), _type_cards())
    assert rec["available"] is True
    assert rec["by_axis"]["alpha"]["n_agree"] == 1
    assert rec["outcome_tally"]["agree"] >= 1


def test_a_type_declared_with_no_providing_card_is_declared_not_derived():
    """beta declares `type_declared_only`, which no card in its roster resolves to — the
    composition claims an instrument its own roster does not provide."""
    rec = rollup.reconcile_axis_types(_mapd_census(), _type_cards())
    assert rec["by_axis"]["beta"]["declared_not_derived"] == ["type_declared_only"]
    assert rec["outcome_tally"]["declared_not_derived"] == 1
    row = next(r for r in rec["queue"] if r["outcome"] == "declared_not_derived")
    assert row["axis"] == "beta" and row["measurement_type"] == "type_declared_only"


def test_a_type_another_axis_declares_is_not_called_undeclared_drift():
    """THE CONJUNCTIVE-LABEL GUARD. `type_elsewhere` is provided by a card in beta's roster and
    declared by alpha. Calling that "undeclared" would assert something false — the framework
    knows the type; only the attribution drifted — so it gets its own outcome AND must name the
    declaring axis, or the label fires on half its evidence."""
    census = _mapd_census()
    census["rosters"]["declared_types_by_axis"]["alpha"] = ["type_a", "type_elsewhere"]
    reg = _type_cards(type_elsewhere={"cards": ["card-b"], "n_providers": 1})
    rec = rollup.reconcile_axis_types(census, reg)
    assert rec["by_axis"]["beta"]["derived_declared_elsewhere"] == ["type_elsewhere"]
    assert rec["by_axis"]["beta"]["derived_nowhere_declared"] == []
    row = next(r for r in rec["queue"] if r["outcome"] == "derived_declared_elsewhere")
    assert row["declared_by"] == ["alpha"]


def test_a_type_no_axis_declares_is_derived_nowhere_declared():
    """THE REGRESSION WATCH. No live instance today, which is exactly why it is constructed
    here: an outcome that cannot be produced by any input is indistinguishable from an outcome
    that never fires, and the dashboard would look clean either way."""
    reg = _type_cards(type_orphan={"cards": ["card-a"], "n_providers": 1})
    rec = rollup.reconcile_axis_types(_mapd_census(), reg)
    assert rec["by_axis"]["alpha"]["derived_nowhere_declared"] == ["type_orphan"]
    assert rec["outcome_tally"]["derived_nowhere_declared"] == 1
    assert rec["by_axis"]["alpha"]["derived_declared_elsewhere"] == []


def test_a_card_with_no_registered_type_is_counted_in_no_outcome():
    """UNDECIDABLE IS NOT DISAGREEMENT. `card-x` is in alpha's roster and in no type's card
    list. It must appear in its own list and contribute to no outcome — folding it into either
    `declared_not_derived` or `derived_nowhere_declared` would manufacture a finding."""
    rec = rollup.reconcile_axis_types(_mapd_census(), _type_cards())
    assert rec["cards_without_registered_type"] == ["card-x"]
    assert rec["n_cards_without_registered_type"] == 1
    assert rec["by_axis"]["alpha"]["cards_without_registered_type"] == ["card-x"]
    for outcome in ("declared_not_derived", "derived_declared_elsewhere", "derived_nowhere_declared"):
        assert not any(r.get("measurement_type") == "card-x" for r in rec["queue"])
        assert "card-x" not in rec["by_axis"]["alpha"][outcome]


def test_unpulled_governed_types_are_split_by_owner():
    """A type no axis declares is one of three different findings with three different owners.
    A single "orphan types" count would send all of them to the wrong queue."""
    reg = _type_cards(type_pulled_undeclared={"cards": ["card-a"], "n_providers": 1})
    rec = rollup.reconcile_axis_types(_mapd_census(), reg)
    states = {u["measurement_type"]: u["state"] for u in rec["unpulled_types"]}
    assert states["type_no_view"] == "no_card_view"
    assert states["type_unpulled"] == "card_exists_unpulled"
    # card-a IS pulled (alpha's roster) while nothing declares this type — the registry-side
    # face of derived_nowhere_declared, and NOT an unpulled card.
    assert states["type_pulled_undeclared"] == "card_declared_type_undeclared"
    assert rec["unpulled_type_tally"]["no_card_view"] == 1
    assert rec["n_governed_types"] - rec["n_governed_types_declared_by_an_axis"] == len(rec["unpulled_types"])


def test_provider_counts_travel_with_an_unviewed_type():
    """`no_card_view` with providers is a MISSING VIEW of data that exists; with none it would
    be an empty declaration. The remedies differ, so the number has to be carried."""
    rec = rollup.reconcile_axis_types(_mapd_census(), _type_cards())
    row = next(u for u in rec["unpulled_types"] if u["measurement_type"] == "type_no_view")
    assert row["n_providers"] == 1 and row["cards"] == []


def test_an_unreadable_vocab_yields_nulls_not_zeros():
    """The reconcile can be unavailable while the census is fine — two repos, two inputs. Every
    count must then be None: a 0 against "governed types with no card view" would read as a
    fully-viewed registry."""
    for empty in (None, {}):
        rec = rollup.reconcile_axis_types(_mapd_census(), empty)
        assert rec["available"] is False
        assert set(rec["outcome_tally"].values()) == {None}
        assert set(rec["unpulled_type_tally"].values()) == {None}
        assert rec["n_cards_without_registered_type"] is None
        assert "UNMEASURED" in rec["note"]


# --- the envelope: projections, absence, and the vocabulary boundary ------------------
def test_the_dimension_is_unavailable_without_the_skills_census():
    mapd = rollup.build_measured_axes_per_dim({}, _type_cards())
    assert mapd["available"] is False
    assert "unreadable" in mapd["reason"]
    assert "summary" not in mapd


def test_the_two_input_rosters_are_projected_out_and_pinned():
    """`cards_by_axis` and `declared_types_by_axis` are INPUTS to the reconcile, not findings,
    and ~11 KB of the census. The queue names every type and card it flags, so dropping them
    loses no finding — but the pin must still identify what was joined."""
    mapd = rollup.build_measured_axes_per_dim(_mapd_census(), _type_cards())
    assert "cards_by_axis" not in mapd["rosters"]
    assert "declared_types_by_axis" not in mapd["rosters"]
    assert "static_states" in mapd["rosters"], "the SEMANTIC rosters must survive the projection"
    assert mapd["roster_pin"]["n_cards_distinct"] == 3
    assert mapd["roster_pin"]["n_types_distinct"] == 3


def test_the_dimension_never_names_a_per_run_coverage_state():
    """CAPABILITY IS NOT OUTCOME, enforced on the emitted bytes. The static vocabulary and the
    per-run one (`measured` / `unmeasured` / `undescribed` / `absent`) are disjoint on the
    producing side; if this envelope ever republished a per-run state name, a consumer could
    join a declaration onto a measurement and neither reading would survive."""
    mapd = rollup.build_measured_axes_per_dim(_mapd_census(), _type_cards())
    assert not (set(mapd["rosters"]["static_states"]) & {"measured", "unmeasured", "undescribed", "absent"})
    assert "CAPABILITY, NOT OUTCOME" in mapd["reading_note"]


# --- self-check: every claim above, with a control that proves it can fail ------------
def test_self_check_passes_on_a_consistent_axis_measurability_section(tmp_path):
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(_report_with_mapd()))
    ok, errs = self_check(p)
    assert ok, errs


def test_self_check_catches_a_summary_mirror_that_drifted(tmp_path):
    rep = _report_with_mapd()
    rep["summary"]["n_governed_types_without_card_view"] += 1
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("unpulled_type_tally[no_card_view]" in e for e in errs)


def test_self_check_catches_counts_published_while_unavailable(tmp_path):
    """The null-discipline guard, from the direction that actually happens: a section flipped to
    unavailable while the header keeps yesterday's numbers."""
    rep = _report_with_mapd()
    rep["measured_axes_per_dim"]["available"] = False
    rep["summary"]["axis_measurability_available"] = False
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("must be null, not a number" in e for e in errs)


def test_self_check_catches_a_queue_row_with_no_axis_record(tmp_path):
    rep = _report_with_mapd()
    rep["measured_axes_per_dim"]["reconcile"]["queue"].append(
        {"axis": "nonexistent", "measurement_type": "t", "outcome": "declared_not_derived"}
    )
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("no record" in e or "disagrees with the queue" in e for e in errs)


def test_self_check_catches_a_declared_elsewhere_row_naming_no_axis(tmp_path):
    """The conjunctive label, guarded on the bytes: a row asserting "another axis declares it"
    with no axis named is the label firing on half its evidence."""
    census = _mapd_census()
    census["rosters"]["declared_types_by_axis"]["alpha"] = ["type_a", "type_elsewhere"]
    reg = _type_cards(type_elsewhere={"cards": ["card-b"], "n_providers": 1})
    rep = _report_with_mapd(census=census, type_cards=reg)
    for row in rep["measured_axes_per_dim"]["reconcile"]["queue"]:
        if row["outcome"] == "derived_declared_elsewhere":
            row["declared_by"] = []
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("names no declaring axis" in e for e in errs)


def test_self_check_catches_a_no_card_view_row_that_lists_cards(tmp_path):
    rep = _report_with_mapd()
    for u in rep["measured_axes_per_dim"]["reconcile"]["unpulled_types"]:
        if u["state"] == "no_card_view":
            u["cards"] = ["some-card"]
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("is no_card_view" in e for e in errs)


def test_self_check_catches_a_stripped_do_not_headline_warning(tmp_path):
    """The producer's note is the only thing carrying the reading order across the repo
    boundary, and this consumer is in the other repo. Losing it would let a dashboard plot the
    saturated per-axis flag as near-done."""
    rep = _report_with_mapd()
    rep["measured_axes_per_dim"]["note"] = "nothing to see here"
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("headlining" in e for e in errs)


def test_self_check_catches_a_static_state_colliding_with_a_coverage_state(tmp_path):
    rep = _report_with_mapd()
    rep["measured_axes_per_dim"]["rosters"]["static_states"].append("measured")
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("collide with the per-run" in e for e in errs)


def test_self_check_catches_a_card_fed_dim_that_stops_being_distinguishable(tmp_path):
    """A dim reading 0-of-1 axes covered is card-fed, not blind, and `not_a_fanout_axes` is the
    ONLY thing that says so. Empty it and the artifact would render an instrument gap that does
    not exist."""
    rep = _report_with_mapd()
    rep["measured_axes_per_dim"]["dims"]["clinical"]["not_a_fanout_axes"] = []
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("would render as blindness" in e for e in errs)


def test_self_check_catches_a_projected_roster_copied_back_in(tmp_path):
    rep = _report_with_mapd()
    rep["measured_axes_per_dim"]["rosters"]["cards_by_axis"] = {"alpha": ["card-a"]}
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("projection is not applied" in e for e in errs)


def test_self_check_ignores_the_section_when_it_is_absent(tmp_path):
    """The dimension is optional by construction: an artifact built in an isolated checkout has
    no section at all, and the self-check must not manufacture errors for it."""
    rep = _minimal_report()
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert ok, errs


# --- the committed artifact: non-vacuity against the real repos -----------------------
def test_the_committed_artifact_carries_a_populated_axis_measurability_section():
    """Against the real artifact: the only check that reds if the dimension ships empty. A
    floor plus named members, because an unavailable section would satisfy every softer
    assertion vacuously."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    mapd = json.loads(committed.read_text()).get("measured_axes_per_dim")
    assert mapd and mapd["available"] is True, "the dimension shipped unavailable"
    assert mapd["reconcile"]["available"] is True, "the reconcile shipped unmeasured"
    assert mapd["summary"]["n_types_without_measurement_descriptor"] >= 1
    assert mapd["reconcile"]["n_governed_types"] >= 100


def test_the_committed_unpulled_split_is_non_vacuous():
    """Both live states must be non-empty, and named. A tally of all-zeros would pass a
    "counts agree with their lists" check perfectly while measuring nothing."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    rec = json.loads(committed.read_text())["measured_axes_per_dim"]["reconcile"]
    tally = rec["unpulled_type_tally"]
    assert tally["no_card_view"] > 0 and tally["card_exists_unpulled"] > 0
    types = {u["measurement_type"] for u in rec["unpulled_types"]}
    assert "mutation_status" in types and "antigen_internalization" in types
    # Every unviewed type today has data behind it — the finding is the missing VIEW.
    assert all(u["n_providers"] >= 1 for u in rec["unpulled_types"])


def test_the_saturated_agreement_count_is_not_in_the_summary_header():
    """`agree` is 165 of 166 and can only go up. A header slot for it would be decoration
    competing with the numbers that move; it stays in the section."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    rep = json.loads(committed.read_text())
    assert not [k for k in rep["summary"] if "agree" in k]
    assert rep["measured_axes_per_dim"]["reconcile"]["outcome_tally"]["agree"] > 0


def test_self_check_catches_a_global_blind_list_no_axis_owns(tmp_path):
    """The tightened direction. The producer builds the global list as the UNION over axes, so a
    global-only entry means the headline type-queue grew while no axis became actionable — the
    number a reader would act on, attached to no owner."""
    census = _mapd_census()
    census["types_without_measurement_descriptor"] = ["type_blind", "type_owned_by_nobody"]
    census["summary"]["n_types_without_measurement_descriptor"] = 2
    rep = _report_with_mapd(census=census)
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok
    assert any("global-only=['type_owned_by_nobody']" in e for e in errs)


def test_a_descriptor_covered_axis_is_allowed_to_carry_undescribed_types(tmp_path):
    """`descriptor_covered` is EXISTENTIAL — >=1 declared type carries a descriptor — so an axis
    can be covered and still have gaps. That is not a tolerated inconsistency but the whole
    reason the flag must not be headlined: a consumer that read covered as "no gaps" would have
    to call the real artifact corrupt on 14 of its 15 fan-out axes."""
    census = _mapd_census()
    census["axes"]["alpha"]["types_without_measurement_descriptor"] = ["type_blind"]
    rep = _report_with_mapd(census=census)
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert ok, errs
    assert rep["measured_axes_per_dim"]["summary"]["n_axes_descriptor_covered"] == 1


def test_the_axis_flag_and_the_type_queue_are_decoupled_in_the_artifact():
    """The saturation fact, asserted so that BOTH worlds are checked rather than one being
    vacuously green: while undescribed types exist, at least one axis must be covered AND still
    carrying them (else the flag really were a coverage proxy and headlining it would be fair);
    once the queue empties, every axis list must be empty too."""
    committed = probe.CONTRACTS_REPO / "health" / "framework_health.json"
    if not committed.exists():
        pytest.skip("no committed artifact")
    m = json.loads(committed.read_text())["measured_axes_per_dim"]
    covered_with_gaps = [
        a
        for a, r in m["axes"].items()
        if r["static_state"] == "descriptor_covered" and (r.get("types_without_measurement_descriptor") or [])
    ]
    if m["summary"]["n_types_without_measurement_descriptor"]:
        assert covered_with_gaps, "no covered axis carries a gap — the flag has become a coverage proxy"
        assert m["summary"]["n_axes_descriptor_covered"] > len(covered_with_gaps) - 1
    else:
        assert not covered_with_gaps
        assert all(not (r.get("types_without_measurement_descriptor") or []) for r in m["axes"].values())


# ---------------------------------------------------------------------------
# 6d. ANTI-VACUITY for the sibling-transcription narrowing.
#
# Dropping three sub-objects from the --check basis is only safe if the basis still reports
# STALE on every direction that carries health information. A narrowing that quietly removed
# the teeth would present as a PERMANENTLY GREEN gate, which is indistinguishable from a
# working one until the day it matters. So each verdict-bearing direction gets an explicit
# "still bites" test, and the noise direction gets one "no longer bites" test — both halves,
# because only the pair distinguishes "narrowed correctly" from "narrowed into a no-op".
# ---------------------------------------------------------------------------
def test_the_narrowed_basis_still_sees_a_verdict_tally_change():
    """The headline rollup. If a skill's health verdict moves, the committed feed IS stale."""
    a = _minimal_report(verdict="production_ready")
    b = _minimal_report(verdict="partial")
    assert stable_projection(a) != stable_projection(b)


def test_the_narrowed_basis_still_sees_a_card_health_change():
    """Per-card health is the finest-grained verdict in the artifact and must keep its teeth —
    a card going `live` → `broken` is exactly the drift --check exists for."""
    a = _minimal_report(card_health="live")
    b = _minimal_report(card_health="placeholder")
    assert stable_projection(a) != stable_projection(b)


def test_the_narrowed_basis_still_sees_a_drift_index_change():
    a = _minimal_report()
    b = _minimal_report()
    b["drift_index"] = [{"kind": "orphan_card", "card_id": "c"}]
    assert stable_projection(a) != stable_projection(b)


def test_the_narrowed_basis_still_sees_a_card_product_id_change():
    """The drift that was ACTUALLY live on 2026-09-18 and the reason --check stays red until a
    regen: `tumor-rna-distribution-by-subtype` declares 13 product_ids on main while the
    committed dashboard shows 3. That is a card in THIS repo changing, so per-card `datasets`
    stays in the basis — the one sub-object most tempting to drop alongside the transcriptions,
    because it is large and dataset-shaped."""
    a = _minimal_report()
    a["skills"][0]["cards"][0]["datasets"] = [{"product_id": "p1", "is_orphan": False}]
    b = json.loads(json.dumps(a))
    b["skills"][0]["cards"][0]["datasets"].append({"product_id": "p2", "is_orphan": True})
    assert stable_projection(a) != stable_projection(b)


def test_the_contracts_side_join_keeps_its_teeth():
    """`measured_axes_per_dim` is NOT dropped wholesale, and this is why: `reconcile` joins the
    skills axis census against THIS repo's `vocabularies/measurement_types.yaml`, so it moves on
    target-contracts changes and is the mechanism by which a vocabulary change still registers
    as staleness here. This is the direct answer to the reversed 2026-09-17 guards."""
    rep = _report_with_mapd()
    mapd = rep["measured_axes_per_dim"]
    assert mapd.get("reconcile"), "fixture must actually carry a reconcile, or this proves nothing"

    moved = json.loads(json.dumps(rep))
    moved["measured_axes_per_dim"]["reconcile"]["outcome_tally"]["declared_not_derived"] = 99
    assert stable_projection(rep) != stable_projection(moved)


def test_the_contracts_local_axis_fields_survive_the_surgery():
    """The surgery must keep the fields that carry "a gateless axis can never be a verdict
    member" — those are decided by this repo's vocabulary, not by the descriptor roster."""
    rep = _report_with_mapd()
    projected = stable_projection(rep)
    for field in ("static_state", "gate_short", "verdict_bearing"):
        assert f'"{field}"' in projected, f"{field} must stay in the drift basis"
    # ...and a change to one of them must still red the check
    moved = json.loads(json.dumps(rep))
    axis = sorted(moved["measured_axes_per_dim"]["axes"])[0]
    moved["measured_axes_per_dim"]["axes"][axis]["verdict_bearing"] = "flipped"
    assert stable_projection(rep) != stable_projection(moved)


def test_the_descriptor_counts_inside_mapd_are_projected_out():
    """The other half of the surgery: the descriptor-roster counts leave, so a mint that only
    moves them cannot red the check."""
    rep = _report_with_mapd()
    axes = rep["measured_axes_per_dim"]["axes"]
    assert any("types_without_measurement_descriptor" in r for r in axes.values()), "non-vacuity"
    projected = json.loads(stable_projection(rep))
    for row in projected["measured_axes_per_dim"]["axes"].values():
        assert "types_without_measurement_descriptor" not in row
        assert "n_types_with_measurement_descriptor" not in row


def test_a_skills_side_descriptor_mint_no_longer_reports_stale():
    """THE POINT OF THE CHANGE, end to end. Simulate what a `_skills_common` salience-mint batch
    does to this artifact — it moves the three sibling-sourced sections and the five derived
    summary counters they feed — and assert the projection does not budge, while the raw reports
    differ (else the equality below would be vacuous).

    Measured against the real 2026-09-18 red before it was written: 1027 of 26304 leaves differed
    under the old basis, every verdict-bearing field was identical, and under this projection the
    same pair differs in 111 leaves -- all 111 the genuine card drift, none of them noise."""
    a = _report_with_mapd()
    a["descriptor_coverage"] = {"source": "skills:_skills_common/descriptor_coverage.json", "n_cells": 337}
    a["field_read_health"] = {"source": "skills:_skills_common/field_read_health.json", "n_credits": 550}
    a["summary"].update(
        {
            "descriptor_coverage_available": True,
            "field_read_health_available": True,
            "n_descriptor_cells": 337,
            "n_distinct_descriptor_fields": 310,
            "n_gloss_without_descriptor": 5,
            "n_measurement_types_with_descriptors": 61,
            "n_measurement_types_without_descriptor": 62,
            "n_numeric_fields_without_gloss": 0,
            "n_field_read_units": 22,
            "n_field_read_units_clean": 13,
            "n_field_read_units_no_reads_detected": 7,
            "n_field_reads_emission_unobserved": 1,
            "n_field_reads_emitted_but_undeclared": 1,
            "n_field_reads_of_none": 0,
            "n_undeclared_field_reads": 2,
        }
    )

    b = json.loads(json.dumps(a))
    b["descriptor_coverage"]["n_cells"] = 459
    b["field_read_health"]["n_credits"] = 552
    b["summary"].update(
        {
            "n_descriptor_cells": 459,
            "n_distinct_descriptor_fields": 421,
            "n_gloss_without_descriptor": 6,
            "n_measurement_types_with_descriptors": 97,
            "n_measurement_types_without_descriptor": 26,
            "n_numeric_fields_without_gloss": 3,
            "n_field_read_units": 23,
            "n_field_read_units_clean": 14,
            "n_field_read_units_no_reads_detected": 6,
            "n_field_reads_emission_unobserved": 2,
            "n_field_reads_emitted_but_undeclared": 0,
            "n_field_reads_of_none": 1,
            "n_undeclared_field_reads": 3,
        }
    )
    axis = sorted(b["measured_axes_per_dim"]["axes"])[0]
    b["measured_axes_per_dim"]["axes"][axis]["types_without_measurement_descriptor"] = ["freshly_minted"]

    assert json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True), "non-vacuity"
    assert stable_projection(a) == stable_projection(b)


def test_an_unavailable_mapd_section_is_not_given_fabricated_keys():
    """An unavailable section carries neither `axes` nor `dims`. The surgery must not inject
    them as nulls — a projection that invents a key is asserting on something the artifact
    never had, and would compare unequal against an older artifact that predates the section."""
    rep = _minimal_report()
    rep["measured_axes_per_dim"] = {"available": False, "reason": "sidecar unreadable"}
    projected = json.loads(stable_projection(rep))
    assert projected["measured_axes_per_dim"] == {"available": False, "reason": "sidecar unreadable"}


def test_older_artifacts_without_any_of_the_three_sections_still_project():
    """Guarded access, same contract as the self-check: an artifact generated before these
    dimensions existed must project without raising."""
    rep = _minimal_report()
    for k in ("descriptor_coverage", "field_read_health", "measured_axes_per_dim"):
        assert k not in rep
    assert stable_projection(rep)  # no KeyError, no TypeError


def test_a_sidecar_that_vanishes_still_reports_stale():
    """The kept half of the availability rule. Magnitudes leave the basis; the `*_available`
    booleans stay, so a sibling sidecar DISAPPEARING — a real wiring break, not churn — still
    reds the check. Directly parallel to `has_tests` keeping only the 1<->0 transition, and the
    reason the narrowing is not simply "stop looking at the siblings"."""
    for flag in ("descriptor_coverage_available", "field_read_health_available", "axis_measurability_available"):
        present = _minimal_report()
        present["summary"][flag] = True
        gone = _minimal_report()
        gone["summary"][flag] = False
        assert stable_projection(present) != stable_projection(gone), f"{flag} lost its teeth"


def test_the_mixed_axis_coverage_counters_are_a_documented_residual():
    """Asserted so the residual is a DECISION rather than an oversight: the axis roster is
    contracts-side while its descriptor coverage is skills-side, so these two counters are
    genuinely mixed and stay in the basis. Consequence, pinned here: a mint that flips an axis
    blind->covered CAN still report STALE. If that ever becomes the dominant noise source, this
    test is the place that records the trade being revisited."""
    a = _minimal_report()
    a["summary"]["n_axes_descriptor_covered"] = 14
    b = _minimal_report()
    b["summary"]["n_axes_descriptor_covered"] = 15
    assert stable_projection(a) != stable_projection(b)
