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

from validators.framework_health import probe, rollup
from validators.framework_health.build_framework_health import stable_projection, self_check


# ---------------------------------------------------------------------------
# 1 + 2. AST literal / dict-key extraction excludes comments & commented tails
# ---------------------------------------------------------------------------
def test_dict_keys_exclude_commented_tail():
    src = textwrap.dedent('''
        CARD_DISPATCHERS = {
            "live-a": fn_a,
            "live-b": fn_b,
            # "commented-c": fn_c,   <- a commented example tail, must be excluded
        }
    ''')
    tree = ast.parse(src)
    keys = probe._find_dict_keys(tree, "CARD_DISPATCHERS")
    assert keys == ["live-a", "live-b"]
    assert "commented-c" not in keys


def test_cards_list_literal_strips_inline_comments():
    src = textwrap.dedent('''
        CARDS = [
            "card-one",     # a facet card
            "card-two",     # another
        ]
    ''')
    tree = ast.parse(src)
    assert probe._find_assign_literal(tree, "CARDS") == ["card-one", "card-two"]


def test_live_reader_ids_real_repo_excludes_known_traps():
    """Against the real repo: the commented-tail cards must not appear as live."""
    roots = probe.default_roots()
    if not (roots["skills"] / "skills").exists():
        pytest.skip("skills repo not present")
    live = set(probe.live_reader_card_ids(roots["skills"]))
    for trap in ("rwd-stratified-expression", "antigen-prevalence", "subgroup-stratified-expression"):
        assert trap not in live, f"{trap} is a commented example, must not count as live"


# ---------------------------------------------------------------------------
# 3. Dispatcher import resolution (authoritative backing) + submodule suffix
# ---------------------------------------------------------------------------
def test_dispatcher_method_imports_resolves_real_module(tmp_path):
    lr = tmp_path / "skills" / "compose-dashboard" / "scripts"
    lr.mkdir(parents=True)
    (lr / "_live_readers.py").write_text(textwrap.dedent('''
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
    '''))
    got = probe.dispatcher_method_imports(tmp_path)
    assert got == {"card-x": "dge_deseq2", "card-y": "opentargets_clingen.read"}


def test_probe_card_uses_dispatcher_not_stale_label(tmp_path):
    """A stale methods.call label must NOT drive backing when a dispatcher exists."""
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.card.yaml").write_text(textwrap.dedent('''
        card_id: c
        methods:
          - call: totally-stale-label
        measurement_type: mt
    '''))
    methods = tmp_path / "methods"
    (methods / "methods" / "real_module").mkdir(parents=True)
    (methods / "methods" / "real_module" / "read.py").write_text("def read(): pass")
    out = probe.probe_card(
        "c", tmp_path, methods,
        live_ids={"c"}, fired_ids=set(),
        dispatch_modules={"c": "real_module.read"},   # dispatcher routes to the REAL module
    )
    assert out["method_dir_exists"] is True          # resolved via dispatcher, suffix stripped
    assert out["stale_method_label"] is True         # label != dispatcher module -> flagged
    assert out["method_call"] == "totally-stale-label"


def test_catalog_manifests_registers_product_id_alias(tmp_path):
    """A manifest's product_id: field becomes an alias key so an indication-
    parameterized card (naming the logical registry product) resolves without
    hard-coding one indication's per-manifest id (dataset_ref_not_in_catalog fix)."""
    derived = tmp_path / "manifests" / "derived"
    derived.mkdir(parents=True)
    (tmp_path / "manifests" / "sources").mkdir(parents=True)
    # Per-indication manifest whose id != its logical product_id
    (derived / "coadread-dge-df06320.yaml").write_text(textwrap.dedent('''
        id: coadread-dge-df06320
        product_id: expression-rna-tumor-vs-adjacent
        provider: takeda
    '''))
    cat = probe.catalog_manifests(tmp_path)
    # Both the real id AND the product_id alias resolve
    assert "coadread-dge-df06320" in cat                       # real manifest id
    assert "expression-rna-tumor-vs-adjacent" in cat           # product_id alias
    assert cat["coadread-dge-df06320"].get("is_product_alias") is None   # real id, not an alias
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
    ({"card_yaml_exists": True, "fires_in_real_package": False, "is_placeholder": True},
     "placeholder", "card-placeholder"),
    ({"card_yaml_exists": True, "fires_in_real_package": False, "has_live_reader": False,
      "method_dir_exists": False}, "broken", "card-no-path"),
    ({"card_yaml_exists": True, "fires_in_real_package": False, "has_live_reader": True,
      "method_dir_exists": False}, "broken", "card-registered-method-unbuilt"),
    ({"card_yaml_exists": True, "fires_in_real_package": False, "has_live_reader": True,
      "method_dir_exists": True}, "partial", "card-reader-never-fires"),
    ({"card_yaml_exists": True, "fires_in_real_package": False, "has_live_reader": False},
     "blocked", "card-no-reader-no-fire"),
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
    signals = {"card_yaml_exists": True, "fires_in_real_package": True,
               "has_live_reader": True, "method_dir_exists": False}
    verdict, reason = rollup._resolve(rules["card_health"], signals)
    assert verdict == "live" and reason == "card-live-fired"


def _skill_for_rollup(cards):
    return {
        "name": "s", "declared": {"status": None, "prose_markers": [], "rules_scope": []},
        "derived": {"kind": "FOCUSED", "has_entrypoint": True, "test_count": 1},
    }


def test_ready_unproven_vs_production_ready():
    """The proven/unproven split + TRUTHFUL reason text (the reported bug: a skill
    read production_ready 'all core cards live' while 0/N were live)."""
    rules = rollup.load_rules()

    # all core cards partial (readers work, nothing fired) -> ready_unproven, and the
    # reason must NOT claim cards are live.
    partial_cards = [{"card_id": "c1", "card_health": "partial"},
                     {"card_id": "c2", "card_health": "partial"}]
    node = rollup.roll_up_skill(_skill_for_rollup(partial_cards), partial_cards, [], rules)
    assert node["health_verdict"] == "ready_unproven"
    assert "live" not in node["reason_text"].lower() or "readers work" in node["reason_text"].lower()
    assert "no core card has fired" in node["reason_text"]

    # ≥1 core card fired -> production_ready (proven)
    fired_cards = [{"card_id": "c1", "card_health": "live"},
                   {"card_id": "c2", "card_health": "partial"}]
    node2 = rollup.roll_up_skill(_skill_for_rollup(fired_cards), fired_cards, [], rules)
    assert node2["health_verdict"] == "production_ready"
    assert "fired in a real package" in node2["reason_text"]


def test_match_operators():
    ctx = {"a": 1, "b": {"c": "x"}, "k": "partial"}
    assert rollup._match({}, ctx) is True                       # empty always matches
    assert rollup._match({"a": 1}, ctx) is True
    assert rollup._match({"b.c": "x"}, ctx) is True             # dotted path
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
    assert stable_projection(a) == stable_projection(b)   # only volatile fields differ


def test_stable_projection_detects_real_change():
    base = {"schema_version": "1.0.0", "generated_at": "t", "roots": {}, "root_shas": {}}
    a = {**base, "summary": {"n_skills": 3}}
    b = {**base, "summary": {"n_skills": 4}}
    assert stable_projection(a) != stable_projection(b)


# ---------------------------------------------------------------------------
# 6b. --self-check: CI-safe integrity check that needs NO sibling repos
# ---------------------------------------------------------------------------
def _minimal_report(card_health="live", verdict="production_ready"):
    card = {"card_id": "c", "card_yaml_exists": True, "fires_in_real_package": True,
            "card_health": card_health}
    skill = {"name": "s", "cards": [card], "health_verdict": verdict}
    return {"schema_version": "1.0.0",
            "summary": {"verdict_tally": {verdict: 1}},
            "skills": [skill], "registry_drift": {}, "drift_index": []}


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
    rep["cards"] = [{
        "card_id": "orphan-x", "card_yaml_exists": True, "fires_in_real_package": True,
        "card_health": "live", "n_consumers": 0, "is_orphan": True,
    }]
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
        "name": name, "health_verdict": verdict,
        "derived": {"kind": "FOCUSED", "resolver_gate": gate, "resolver_bound": bound},
        "risk_category": None, "cards": cards or [],
    }


def test_build_graph_layers_and_edges():
    skills = [_mk_skill("skill-a", gate="dependency")]
    cards = [{"card_id": "card-a", "card_health": "live", "consumers": ["skill-a"],
              "dispatch_module": "meth_a.read", "method_dir_exists": True, "is_orphan": False,
              "measurement_type": "mt"}]
    g = rollup.build_graph(skills, cards)
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"skill:skill-a", "resolver:dependency", "card:card-a", "method:meth_a"}
    rels = {(e["src"], e["dst"], e["rel"]) for e in g["edges"]}
    assert ("skill:skill-a", "resolver:dependency", "resolves_via") in rels
    assert ("skill:skill-a", "card:card-a", "consumes") in rels
    assert ("card:card-a", "method:meth_a", "backed_by") in rels   # .read suffix stripped
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
    rep["graph"] = {"nodes": [{"id": "skill:x", "layer": "skill"}],
                    "edges": [{"src": "skill:x", "dst": "card:ghost", "rel": "consumes"}],
                    "n_nodes": 1, "n_edges": 1}
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
        "id: ds-a\nprovider: acme\nversion: v1\ntotal_size_bytes: 1024\n")
    cat = probe.catalog_manifests(tmp_path)
    assert "ds-a" in cat and cat["ds-a"]["kind"] == "source" and cat["ds-a"]["provider"] == "acme"


def test_probe_card_dataset_exact_and_prefix_match(tmp_path):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.card.yaml").write_text(
        "card_id: c\nrequired_inputs:\n  - product_id: depmap-predictability\n"
        "  - product_id: exact-ds\nmethods:\n  - call: m\n")
    methods = tmp_path / "methods"; (methods / "methods").mkdir(parents=True)
    out = probe.probe_card("c", tmp_path, methods, set(), set(), {},
                           catalog_ids={"exact-ds", "depmap-predictability-26q1-v2"})
    ds = {d["product_id"]: d for d in out["datasets"]}
    assert ds["exact-ds"]["matched_by"] == "exact" and ds["exact-ds"]["in_catalog"]
    assert ds["depmap-predictability"]["matched_by"] == "prefix"
    assert ds["depmap-predictability"]["resolved_id"] == "depmap-predictability-26q1-v2"


def test_probe_card_dataset_broken_ref(tmp_path):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "c.card.yaml").write_text(
        "card_id: c\nrequired_inputs:\n  - product_id: ghost-ds\n")
    methods = tmp_path / "methods"; (methods / "methods").mkdir(parents=True)
    out = probe.probe_card("c", tmp_path, methods, set(), set(), {}, catalog_ids={"real-ds"})
    d = out["datasets"][0]
    assert d["product_id"] == "ghost-ds" and not d["in_catalog"] and d["matched_by"] is None


def test_self_check_catches_inconsistent_dataset_flags(tmp_path):
    rep = _minimal_report()
    rep["datasets"] = [{"product_id": "x", "in_catalog": True, "n_consumers": 0,
                        "is_orphan": False, "is_broken_ref": False}]  # should be orphan=True
    p = tmp_path / "framework_health.json"
    p.write_text(json.dumps(rep))
    ok, errs = self_check(p)
    assert not ok and any("is_orphan" in e for e in errs)


def test_matrix_css_has_no_overflow_hidden_clip():
    """Regression guard: .matrix must NOT carry overflow:hidden — it clipped the
    expanded drill-down (the nested cards table grows a detail row past the table
    box and gets cut off). See the drill-down-clip fix."""
    from validators.framework_health import render_html
    css = render_html._CSS
    import re
    m = re.search(r'\.matrix\{([^}]*)\}', css)
    assert m, ".matrix rule not found"
    assert "overflow:hidden" not in m.group(1), \
        ".matrix must not clip — overflow:hidden hides expanded drill-down content"


def test_drilldown_table_present_and_closed_in_render():
    """The skill drill-down must emit a fully-closed cards table for a card-consuming
    skill (structural guard that the detail renders end to end)."""
    from validators.framework_health import render_html
    n = {
        "name": "s", "health_verdict": "partial", "health_reason": "x", "reason_text": "r",
        "declared": {"status": "wired", "prose_markers": []},
        "derived": {"kind": "FOCUSED", "resolver_gate": "g", "resolver_bound": True,
                    "test_count": 1, "cards_in_runpy": ["c1"]},
        "drift_flags": [],
        "cards": [{"card_id": "c1", "card_health": "live", "has_live_reader": True,
                   "fires_in_real_package": True, "measurement_type": "mt",
                   "dispatch_module": "m.read", "reason_text": "r",
                   "datasets": [{"product_id": "d1", "in_catalog": True, "matched_by": "exact"},
                                {"product_id": "d2", "in_catalog": False, "matched_by": None}]}],
        "risk_category": None,
    }
    detail = render_html._skill_detail(n)
    assert detail.count("<table") == detail.count("</table>")   # balanced
    assert 'class="dscell"' in detail                            # datasets cell present
    assert "d1" in detail and "d2" in detail                     # both datasets rendered


def test_dashboard_spec_card_ids_scan(tmp_path):
    d = tmp_path / "dashboards"; d.mkdir()
    (d / "a.dashboard_spec.yaml").write_text(
        "dashboard_id: spec-a\nrequired_cards:\n  - card_id: c1\noptional_cards:\n  - card_id: c2\n")
    got = probe.dashboard_spec_card_ids(tmp_path)
    assert got == {"c1": ["spec-a"], "c2": ["spec-a"]}


def test_consumed_but_no_spec_drift(tmp_path):
    # a real card, consumed by a skill, in no spec -> flagged; placeholder/missing not flagged
    skill = {"declared": {"status": "wired", "prose_markers": []},
             "derived": {"kind": "FOCUSED", "has_entrypoint": True, "cards_in_runpy": []}}
    cards = [
        {"card_id": "in-spec", "card_yaml_exists": True, "is_placeholder": False},
        {"card_id": "no-spec", "card_yaml_exists": True, "is_placeholder": False},
        {"card_id": "placeholder-card", "card_yaml_exists": True, "is_placeholder": True},
    ]
    spec_cards = {"in-spec": ["spec-a"]}
    flags = rollup.compute_drift(skill, cards, spec_cards)
    codes = {f["code"]: f for f in flags}
    assert "card_consumed_but_no_spec" in codes
    detail = codes["card_consumed_but_no_spec"]["detail"]
    assert "no-spec" in detail
    assert "in-spec" not in detail            # it IS in a spec
    assert "placeholder-card" not in detail   # placeholder excluded


def test_self_check_catches_bad_spec_flag(tmp_path):
    rep = _minimal_report()
    rep["cards"] = [{"card_id": "x", "card_yaml_exists": True, "fires_in_real_package": True,
                     "card_health": "live", "n_consumers": 1, "is_orphan": False,
                     "in_dashboard_spec": True, "consumed_but_no_spec": True}]  # inconsistent
    rep["summary"]["verdict_tally"] = {"production_ready": 1}
    rep["skills"] = [{"name": "s", "cards": rep["cards"], "health_verdict": "production_ready"}]
    p = tmp_path / "framework_health.json"; p.write_text(json.dumps(rep))
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
        assert d["is_broken_ref"] == ((not d["in_catalog"]) and d["n_consumers"] > 0)


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
        tmp_path, "no-status",
        skill_md="---\nname: no-status\ncomposition:\n  cards_used: []\n---\nbody\n",
        run_py="from _skills_common.dispatcher import run_wired_skill\n"
               "resolve_verdict_for_gate(f, 'dependency')\n",
    )
    sig = probe.probe_skill(d)
    assert sig["declared"]["status"] is None
    drift = rollup.compute_drift(sig, [])
    assert any(f["code"] == "missing_status_field" for f in drift)


def test_placeholder_skill_classified(tmp_path):
    d = _write_skill(
        tmp_path, "ph",
        skill_md="---\nname: ph\nstatus: not_wired\n---\nPLACEHOLDER SKILL\n",
        run_py="from _skills_common import emit_placeholder\nemit_placeholder()\n",
    )
    sig = probe.probe_skill(d)
    assert sig["derived"]["kind"] == "PLACEHOLDER"
    assert sig["derived"]["is_placeholder"] is True


def test_prose_markers_are_advisory_only(tmp_path):
    """A skill body mentioning 'placeholder' (describing others) must not set status."""
    d = _write_skill(
        tmp_path, "px",
        skill_md="---\nname: px\nstatus: wired\n---\nfans out; some are placeholder still\n",
        run_py="SUB_SKILLS = [('a','a')]\n",
    )
    sig = probe.probe_skill(d)
    assert sig["declared"]["status"] == "wired"
    assert "placeholder" in sig["declared"]["prose_markers"]   # detected but advisory


def test_entrypoint_fallback_non_runpy(tmp_path):
    """Orchestration skills use a non-run.py entrypoint — must still count as present."""
    d = tmp_path / "skills" / "orch"
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: orch\n---\n")
    (d / "scripts" / "compose_dashboard.py").write_text("x = 1\n")
    sig = probe.probe_skill(d)
    assert sig["derived"]["has_entrypoint"] is True
    assert sig["derived"]["entrypoint"] == "compose_dashboard.py"
