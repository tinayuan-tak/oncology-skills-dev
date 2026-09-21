"""Hermetic tests for eval/card_chain_audit.py.

No live data, no sibling-repo catalog: findings are driven off hand-built ``declared`` dicts, a fake
catalog, and a synthetic trace. Each guard is paired with an anti-vacuity control (the clean case that
must NOT fire), and the two honesty rules are asserted directly:
  * unmeasured (``measured is None``) suppresses the measured-dependent findings — null, not a false clean;
  * a traced-zero-reads card (``measured == []``) is distinct from unmeasured and DOES fire never-read;
  * re-derivation has teeth — a mutated emitted value flips ``match`` to False.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import importlib  # noqa: E402
import json  # noqa: E402

import card_chain_audit as cca  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_owner_index_cache():
    # _owner_index caches by id(catalog); short-lived test catalogs can reuse an id after GC, so clear the
    # cache around every test to keep the fake catalogs isolated. (In production the catalog is a long-lived
    # lru_cached singleton, so the id-keyed cache is stable.)
    cca._OWNER_INDEX_CACHE.clear()
    yield
    cca._OWNER_INDEX_CACHE.clear()


# ── fake catalog ────────────────────────────────────────────────────────────────────────────────────
class _Rec:
    def __init__(self, mid, s3_uri, derived_from=None, raw=None):
        self.id = mid
        self.s3_uri = s3_uri
        self.type = "derived"
        self.parquet_schema = []
        self.query_optimization = None
        self.license = None
        self.derived_from = list(derived_from or [])
        # the full manifest yaml dict — carries parameters.companion_summary_path / sidecar_s3_uri, which
        # _owner_index reads so a read of a documented companion object resolves to the owning manifest
        self.raw = raw or {}


class _Catalog:
    def __init__(self, recs):
        self.manifests = {r.id: r for r in recs}


def _kinds(findings):
    return [f["kind"] for f in findings]


# ── uri helpers ───────────────────────────────────────────────────────────────────────────────────────
def test_uri_class_distinguishes_local_cache_from_s3():
    assert cca._uri_class("/home/x/.cache/f.csv") == "local_cache"
    assert cca._uri_class("file:///tmp/f.csv") == "local_cache"
    assert cca._uri_class("onc-compbio/data-catalog/derived/x/f.parquet") == "s3_object"
    assert cca._uri_class("s3://onc-compbio/x/f.parquet") == "s3_object"
    assert cca._uri_class(None) == "unknown"


def test_manifest_owns_exact_and_directory_prefix():
    # exact single-file (derived) match, tolerant of the s3:// scheme on one side only
    assert cca._manifest_owns("bucket/derived/m/f.parquet", "s3://bucket/derived/m/f.parquet")
    # directory-prefix (source/multi-file) match
    assert cca._manifest_owns("bucket/sources/m/sub/f.csv", "s3://bucket/sources/m/")
    # a sibling object under the same dir but NOT under a single-file manifest is NOT owned
    assert not cca._manifest_owns("bucket/derived/m/f.allgene_null.parquet", "s3://bucket/derived/m/f.parquet")
    assert not cca._manifest_owns("bucket/x/f.parquet", None)


# ── declared_call_unresolved ──────────────────────────────────────────────────────────────────────────
def test_declared_call_unresolved_fires_and_clean_case_does_not():
    unresolvable = {"method_calls": [{"call": "no-such-call-xyz", "resolvable": False}], "manifests": []}
    resolvable = {"method_calls": [{"call": "whatever", "resolvable": True}], "manifests": []}
    assert "declared_call_unresolved" in _kinds(cca.detect_findings(unresolvable, [], {}, None))
    # anti-vacuity: a resolvable call must NOT fire
    assert "declared_call_unresolved" not in _kinds(cca.detect_findings(resolvable, [], {}, None))
    # a card that declares NO calls at all is not "unresolved"
    assert "declared_call_unresolved" not in _kinds(
        cca.detect_findings({"method_calls": [], "manifests": []}, [], {}, None)
    )


# ── field_declared_but_absent_from_summary ────────────────────────────────────────────────────────────
def test_field_declared_but_absent_fires_only_for_missing():
    declared = {"method_calls": [], "summary_fields": ["present_field", "missing_field"], "manifests": []}
    summary = {"present_field": 1.0}
    findings = cca.detect_findings(declared, [], summary, None)
    missing = [f["field"] for f in findings if f["kind"] == "field_declared_but_absent_from_summary"]
    assert missing == ["missing_field"]  # present_field must NOT appear (anti-vacuity)


def test_field_name_normalizes_dict_and_bare_string():
    # a card may declare summary_fields as bare names OR as {name, description, lens_conditional_on} dicts
    assert cca._field_name("plain") == "plain"
    assert cca._field_name({"name": "adc_grade", "description": "…"}) == "adc_grade"
    assert cca._field_name({"field": "x"}) == "x"
    assert cca._field_name({"no_name_key": 1}) is None  # unnameable ⇒ dropped by the caller


def test_dict_shaped_summary_fields_do_not_crash_and_lens_conditional_is_excluded():
    # regression: a dict-shaped summary_fields entry once raised "unhashable type: dict" on `f not in
    # summary`. A lens-conditional field absent from a non-lensed run must NOT be flagged.
    declared = {
        "method_calls": [],
        "summary_fields": ["always_field", "adc_grade"],  # names (as build_declared normalizes them)
        "conditional_summary_fields": ["adc_grade"],  # emitted only under the --modality lens
        "manifests": [],
    }
    summary = {"always_field": 1}  # adc_grade absent because no lens was invoked
    findings = cca.detect_findings(declared, [], summary, None)
    kinds = [f["kind"] for f in findings]
    assert "field_declared_but_absent_from_summary" not in kinds  # conditional field is not "missing"
    # teeth: a NON-conditional absent field still fires
    declared["summary_fields"] = ["always_field", "missing_nonconditional"]
    findings2 = cca.detect_findings(declared, [], summary, None)
    absent = [f["field"] for f in findings2 if f["kind"] == "field_declared_but_absent_from_summary"]
    assert absent == ["missing_nonconditional"]


# ── declared_input_not_read_this_run + read_object_not_in_any_manifest ────────────────────────────────
def test_never_read_and_uncataloged_object_with_fake_catalog():
    cat = _Catalog(
        [_Rec("read-mani", "s3://b/derived/read/f.parquet"), _Rec("unread-mani", "s3://b/derived/unread/f.parquet")]
    )
    declared = {
        "method_calls": [],
        "manifests": [
            {"manifest_id": "read-mani", "in_catalog": True, "s3_uri": "s3://b/derived/read/f.parquet"},
            {"manifest_id": "unread-mani", "in_catalog": True, "s3_uri": "s3://b/derived/unread/f.parquet"},
        ],
    }
    measured = [
        {"op": "pyarrow.read_table", "uri": "b/derived/read/f.parquet", "uri_class": "s3_object"},
        {"op": "pyarrow.read_table", "uri": "b/derived/orphan/g.parquet", "uri_class": "s3_object"},
        {"op": "pandas.read_csv", "uri": "/home/x/.cache/local.csv", "uri_class": "local_cache"},
    ]
    findings = cca.detect_findings(declared, measured, {}, cat)
    never = [f["manifest_id"] for f in findings if f["kind"] == "declared_input_not_read_this_run"]
    orphan = [f["uri"] for f in findings if f["kind"] == "read_object_not_in_any_manifest"]
    assert never == ["unread-mani"]  # read-mani WAS read → must not fire (anti-vacuity)
    assert orphan == ["b/derived/orphan/g.parquet"]  # the local_cache read is NOT flagged as uncataloged


# ── source→derived lineage hop ────────────────────────────────────────────────────────────────────────
def test_declared_source_read_via_derived_reprojection_is_not_flagged():
    # the card declares a SOURCE; the run opens the DERIVED product (derived_from that source).
    cat = _Catalog(
        [
            _Rec("depmap-source", "s3://b/sources/depmap/"),
            _Rec("depmap-parquet", "s3://b/derived/depmap-parquet/f.parquet", derived_from=["depmap-source"]),
        ]
    )
    declared = {
        "method_calls": [],
        "manifests": [{"manifest_id": "depmap-source", "in_catalog": True, "s3_uri": "s3://b/sources/depmap/"}],
    }
    measured = [{"op": "pyarrow.read_table", "uri": "b/derived/depmap-parquet/f.parquet", "uri_class": "s3_object"}]
    # the source is satisfied THROUGH the derived read → must NOT be flagged
    assert "declared_input_not_read_this_run" not in _kinds(cca.detect_findings(declared, measured, {}, cat))
    # teeth: sever the lineage and it DOES fire — proving the hop is what suppressed it
    cat.manifests["depmap-parquet"].derived_from = []
    assert "declared_input_not_read_this_run" in _kinds(cca.detect_findings(declared, measured, {}, cat))


# ── unmeasured ⇒ null, not 0 ─────────────────────────────────────────────────────────────────────────
def test_unmeasured_suppresses_measured_dependent_findings():
    cat = _Catalog([_Rec("m", "s3://b/derived/m/f.parquet")])
    declared = {
        "method_calls": [{"call": "no-such-call", "resolvable": False}],
        "summary_fields": ["absent"],
        "manifests": [{"manifest_id": "m", "in_catalog": True, "s3_uri": "s3://b/derived/m/f.parquet"}],
    }
    findings = cca.detect_findings(declared, None, {}, cat)  # measured is None ⇒ UNMEASURED
    kinds = _kinds(findings)
    # measured-dependent findings must NOT appear when unmeasured (no false clean either way)
    assert "declared_input_not_read_this_run" not in kinds
    assert "read_object_not_in_any_manifest" not in kinds
    # anti-vacuity: measurement-independent findings STILL fire, so the empty measured set is the cause
    assert "declared_call_unresolved" in kinds
    assert "field_declared_but_absent_from_summary" in kinds


def test_traced_zero_reads_is_distinct_from_unmeasured():
    cat = _Catalog([_Rec("m", "s3://b/derived/m/f.parquet")])
    declared = {
        "method_calls": [],
        "manifests": [{"manifest_id": "m", "in_catalog": True, "s3_uri": "s3://b/derived/m/f.parquet"}],
    }
    # measured == [] (traced, zero reads) DOES fire not-read-this-run, unlike measured is None above
    findings = cca.detect_findings(declared, [], {}, cat)
    assert "declared_input_not_read_this_run" in _kinds(findings)


def test_build_measured_none_vs_empty():
    trace = {"cards": {"present-zero": [], "present-one": [{"op": "x", "uri": "b/k/f.parquet"}]}}
    assert cca.build_measured("absent-card", trace) is None  # not in trace ⇒ unmeasured (null)
    assert cca.build_measured("present-zero", trace) == []  # traced, zero reads
    assert len(cca.build_measured("present-one", trace)) == 1
    assert cca.build_measured("any", None) is None  # run not traced at all ⇒ null


# ── re-derivation has teeth ───────────────────────────────────────────────────────────────────────────
def test_close_numeric_integer_and_none():
    assert cca._close(2446, 2446.0) is True
    assert cca._close(2446, 2447) is False
    assert cca._close(0.6308, 0.63080001) is True
    assert cca._close(0.6308, 0.7) is False
    assert cca._close("x", 1.0) is None  # non-numeric ⇒ null, not a spurious mismatch
    assert cca._close(None, 1.0) is None


def test_rederive_mismatch_fires_on_mutation_and_clean_run_is_clean(monkeypatch):
    # synthetic panel scores → deterministic expected scalars, no live S3
    monkeypatch.setattr(cca, "_read_panel_scores", lambda event: [0.0, 2.0, 6.0, 6.0])
    event = {
        "op": "pyarrow.read_table",
        "uri": "b/derived/depmap-26q1-parquet-v1/OmicsExpressionX.parquet",
        "columns": ["EPCAM (4072)", "ModelID", "IsDefaultEntryForModel"],
    }
    # correct emitted values (n=4; >=1.0 → 3/4; >=5.0 → 2/4; <1.0 → 1/4; median of [0,2,6,6] = 4.0)
    good = {
        "n_cell_lines_evaluated": 4,
        "median_log2tpm_panel": 4.0,
        "fraction_expressed": 0.75,
        "fraction_highly_expressed": 0.5,
        "fraction_not_expressed": 0.25,
    }
    out = cca._rederive_cellline_rna_distribution([event], good, do_read=True)
    assert out["n_cell_lines_evaluated"]["match"] is True
    assert out["fraction_expressed"]["match"] is True
    assert all(v.get("match") is not False for v in out.values() if v.get("measured"))  # clean run is clean

    bad = dict(good, fraction_expressed=0.10)  # mutate one emitted value
    out2 = cca._rederive_cellline_rna_distribution([event], bad, do_read=True)
    assert out2["fraction_expressed"]["match"] is False  # re-derivation catches the mutation → teeth

    # method-internal fields are honestly non-rederivable, never silently "matched"
    assert out["distribution_pattern"]["rederivable"] is False


def test_rederive_empty_scores_is_unmeasured_not_crash(monkeypatch):
    # a read that returns no rows (e.g. a wrong dedup filter) must degrade to unmeasured, never crash
    monkeypatch.setattr(cca, "_read_panel_scores", lambda event: [])
    event = {"op": "pyarrow.read_table", "uri": "b/x/OmicsExpressionX.parquet", "columns": ["G", "ModelID"]}
    out = cca._rederive_cellline_rna_distribution([event], {"n_cell_lines_evaluated": 4}, do_read=True)
    assert out["n_cell_lines_evaluated"]["measured"] is False
    assert "match" not in out["n_cell_lines_evaluated"]


def test_rederive_without_read_flag_is_unmeasured_not_matched():
    event = {"op": "pyarrow.read_table", "uri": "b/x/OmicsExpressionX.parquet", "columns": []}
    out = cca._rederive_cellline_rna_distribution([event], {"n_cell_lines_evaluated": 4}, do_read=False)
    # do_read=False ⇒ scalar fields report unmeasured (rederivable True, measured False), never a match verdict
    assert out["n_cell_lines_evaluated"]["measured"] is False
    assert "match" not in out["n_cell_lines_evaluated"]


def test_unknown_card_has_no_rederiver():
    assert cca.build_rederived("tumor-rna-distribution", [], {}, do_read=False) is None


# ── emitted values: scalar vs complex split ───────────────────────────────────────────────────────────
def test_split_summary_separates_scalars_from_complex_fields():
    summary = {
        "n_cell_lines_evaluated": 2446,
        "median_log2tpm_panel": 2.5138,
        "distribution_pattern": "bimodal",
        "per_lineage": [{"lineage": "COADREAD", "n": 40}],  # list ⇒ complex
        "thresholds": {"expressed": 1.0},  # dict ⇒ complex
    }
    out = cca._split_summary(summary)
    # the actual output DATA (the values a reviewer reads) survive as scalars
    assert out["scalars"] == {
        "n_cell_lines_evaluated": 2446,
        "median_log2tpm_panel": 2.5138,
        "distribution_pattern": "bimodal",
    }
    # list/dict fields are named only, never inlined as values
    assert sorted(out["complex_fields"]) == ["per_lineage", "thresholds"]
    assert out["n_fields"] == 5  # counts EVERY field, scalar or complex


def test_split_summary_empty():
    out = cca._split_summary({})
    assert out == {"scalars": {}, "complex_fields": [], "n_fields": 0}


# ── health status: did the card extract data as expected? ─────────────────────────────────────────────
def _health(summary, measured, findings, declared=None):
    return cca._card_health(summary, measured, findings, declared or {})["status"]


def test_health_ok_when_traced_emitted_and_no_downgrading_finding():
    assert _health({"n": 2446}, [{"op": "x", "uri": "b/k/f.parquet"}], []) == "ok"


def test_health_opaque_for_emitted_but_untraced_run():
    # the sc-normal case: a full summary emitted, but the run carries no trace at all (measured is None)
    assert _health({"cell_types": 143, "liability": "HIGH"}, None, []) == "opaque"


def test_health_opaque_for_emitted_but_zero_traced_reads():
    # emitted output yet the tracer captured zero reads for this card ⇒ audit blind spot, not broken
    assert _health({"cell_types": 143}, [], []) == "opaque"


def test_health_value_mismatch_dominates_everything():
    # a re-derived disagreement is the worst state and wins even over an off-contract read
    findings = [{"kind": "rederived_mismatch", "field": "x"}, {"kind": "read_object_not_in_any_manifest", "uri": "u"}]
    assert _health({"x": 1}, [{"op": "x", "uri": "u"}], findings) == "value_mismatch"


def test_health_no_output_when_traced_but_empty_summary():
    # traced reads happened but nothing was emitted — distinct from opaque (which HAS output)
    assert _health({}, [{"op": "x", "uri": "b/k/f.parquet"}], []) == "no_output"


def test_health_unmeasured_when_neither_traced_nor_emitted():
    assert _health({}, None, []) == "unmeasured"


def test_health_off_contract_read_when_uncataloged_object_read():
    findings = [{"kind": "read_object_not_in_any_manifest", "uri": "b/orphan/g.parquet"}]
    assert _health({"n": 1}, [{"op": "x", "uri": "b/orphan/g.parquet"}], findings) == "off_contract_read"


def test_health_partial_output_when_a_declared_field_is_missing():
    declared = {"summary_fields": ["present", "absent"]}
    findings = [{"kind": "field_declared_but_absent_from_summary", "field": "absent"}]
    assert _health({"present": 1}, [{"op": "x", "uri": "b/k/f.parquet"}], findings, declared) == "partial_output"


def test_health_not_read_this_run_does_not_downgrade():
    # declared_input_not_read_this_run is a benign per-run coverage dimension — a card that emitted
    # its outputs over traced reads is still OK even when one declared input went unread this run.
    findings = [{"kind": "declared_input_not_read_this_run", "manifest_id": "unread-mani"}]
    assert _health({"n": 2446}, [{"op": "x", "uri": "b/k/f.parquet"}], findings) == "ok"


# ── corpus mode: read-by-zero-across-a-matrix = declared_input_dead ────────────────────────────────────
def _report(cards):
    """Minimal per-run audit report shape for the corpus bricks (only the fields _card_read_status reads)."""
    return {"cards": cards}


def _card(card_id, measured, manifest_ids, not_read=()):
    manifests = [{"manifest_id": m, "in_catalog": True, "s3_uri": f"s3://b/{m}/f.parquet"} for m in manifest_ids]
    findings = [{"kind": "declared_input_not_read_this_run", "manifest_id": m} for m in not_read]
    return {"card_id": card_id, "measured": measured, "declared": {"manifests": manifests}, "findings": findings}


def test_card_read_status_omits_untraced_and_maps_read_from_not_read():
    rep = _report(
        [
            _card("c1", [{"op": "x"}], ["read-mani", "unread-mani"], not_read=["unread-mani"]),
            _card("c2", None, ["whatever"]),  # untraced ⇒ omitted entirely, never recorded as unread
        ]
    )
    status = cca._card_read_status(rep)
    assert "c2" not in status  # untraced card gives no evidence either way
    assert status["c1"] == {"read-mani": True, "unread-mani": False}


def test_card_read_status_skips_not_in_catalog_and_uncataloged_inputs():
    card = {
        "card_id": "c",
        "measured": [{"op": "x"}],
        "declared": {
            "manifests": [
                {"manifest_id": "good", "in_catalog": True, "s3_uri": "s3://b/good/f.parquet"},
                {"manifest_id": "no-cat", "in_catalog": False, "s3_uri": "s3://b/x/f.parquet"},
                {"manifest_id": "no-uri", "in_catalog": True, "s3_uri": None},
            ]
        },
        "findings": [],
    }
    assert cca._card_read_status(_report([card]))["c"] == {"good": True}  # only the in-catalog + s3 input counts


def test_card_read_status_run_level_union_clears_shared_cache_reader():
    # The lru_cache-sharing case: 'reader' physically reads shared-mani; 'consumer' declares it but records
    # 0 events for it (warm cache) so it lands in consumer's not_read. The run-level union must still score
    # shared-mani read for consumer — any traced card reading it means the wiring is live, not dead.
    rep = _report(
        [
            _card("reader", [{"op": "x"}], ["shared-mani"]),
            _card(
                "consumer", [{"op": "y"}], ["shared-mani", "own-dead-mani"], not_read=["shared-mani", "own-dead-mani"]
            ),
        ]
    )
    status = cca._card_read_status(rep)
    assert status["reader"] == {"shared-mani": True}
    # shared-mani cleared by the union (reader read it); own-dead-mani read by NObody → stays False
    assert status["consumer"] == {"shared-mani": True, "own-dead-mani": False}


def test_card_read_status_union_draws_only_from_traced_cards():
    # An untraced card's declared inputs must not seed the union (it contributes no read evidence).
    rep = _report(
        [
            _card("untraced", None, ["ghost-mani"]),
            _card("consumer", [{"op": "y"}], ["ghost-mani"], not_read=["ghost-mani"]),
        ]
    )
    status = cca._card_read_status(rep)
    assert "untraced" not in status
    assert status["consumer"] == {"ghost-mani": False}  # untraced card cannot vouch for a read


def test_aggregate_flags_dead_only_when_read_by_zero_and_above_breadth_floor():
    # dead-mani: declared+traced in all 3 runs, read in NONE → dead. live-mani: read in ≥1 → never dead.
    matrices = [
        {"card": {"dead-mani": False, "live-mani": True}},
        {"card": {"dead-mani": False, "live-mani": False}},
        {"card": {"dead-mani": False, "live-mani": True}},
    ]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2)
    by_mid = {i["manifest_id"]: i for i in cards[0]["inputs"]}
    assert by_mid["dead-mani"]["dead"] is True
    assert by_mid["dead-mani"]["read_runs"] == 0 and by_mid["dead-mani"]["declared_traced_runs"] == 3
    assert by_mid["live-mani"]["dead"] is False  # anti-vacuity: a read-at-least-once input must NOT be dead
    assert {d["manifest_id"] for d in dead} == {"dead-mani"}


# ── run-artifact adapter: decision.json vs evidence_package.json ──────────────────────────────────────
def test_run_artifact_none_when_neither_present(tmp_path):
    assert cca._run_artifact(tmp_path) is None


def test_load_run_reads_decision_json(tmp_path):
    (tmp_path / "decision.json").write_text(
        json.dumps(
            {
                "target": "KRAS",
                "indication": "COADREAD",
                "cards": [{"card_id": "c1", "summary": {"n": 5}, "input_manifest_ids": ["m1", "m2"]}],
            }
        )
    )
    cards, target, indication = cca._load_run(tmp_path)
    assert (target, indication) == ("KRAS", "COADREAD")
    assert cards == [{"card_id": "c1", "summary": {"n": 5}, "input_manifest_ids": ["m1", "m2"]}]


def test_load_run_reads_evidence_package_from_provenance_and_context(tmp_path):
    # target-profile shape: manifest ids under provenance, target/indication structured under context.
    (tmp_path / "evidence_package.json").write_text(
        json.dumps(
            {
                "context": {"target": {"symbol": "AURKB"}, "indication": {"oncotree_code": "COADREAD"}},
                "cards": [
                    {
                        "card_id": "c1",
                        "summary": {"n": 7},
                        "provenance": {"input_manifest_ids": ["p1", "p2"]},
                    }
                ],
            }
        )
    )
    cards, target, indication = cca._load_run(tmp_path)
    assert (target, indication) == ("AURKB", "COADREAD")
    # input_manifest_ids lifted out of provenance to the normalized top level
    assert cards == [{"card_id": "c1", "summary": {"n": 7}, "input_manifest_ids": ["p1", "p2"]}]


def test_load_run_prefers_decision_json_when_both_present(tmp_path):
    (tmp_path / "decision.json").write_text(json.dumps({"target": "KRAS", "indication": "COADREAD", "cards": []}))
    (tmp_path / "evidence_package.json").write_text(
        json.dumps({"context": {"target": {"symbol": "AURKB"}, "indication": {"oncotree_code": "PAAD"}}, "cards": []})
    )
    _, target, indication = cca._load_run(tmp_path)
    assert (target, indication) == ("KRAS", "COADREAD")  # decision.json wins


def test_aggregate_breadth_floor_suppresses_single_observation():
    # declared+traced in only ONE run, unread — no better evidence than the single-run dimension.
    matrices = [{"card": {"lonely": False}}]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2)
    rec = cards[0]["inputs"][0]
    assert rec["declared_traced_runs"] == 1 and rec["read_runs"] == 0
    assert rec["dead"] is False and dead == []  # below floor ⇒ counted but NOT flagged
    # teeth: drop the floor to 1 and the SAME evidence now fires — proving the floor is what suppressed it
    _, dead1 = cca._aggregate_read_matrices(matrices, min_runs=1)
    assert [d["manifest_id"] for d in dead1] == ["lonely"]


# ── cohort-conditionality: a per-cohort shard menu is not dead wiring ──────────────────────────────────
def test_family_key_groups_cohort_shards_and_skips_short_ids():
    # per-indication shards share (first 3 tokens, last token) ⇒ one family
    assert cca._family_key("tcga-subgroup-assignments-coadread-v1") == (("tcga", "subgroup", "assignments"), "v1")
    assert cca._family_key("tcga-subgroup-assignments-hnsc-v1") == (("tcga", "subgroup", "assignments"), "v1")
    # a co-required sibling with a different first-3 stem is a DIFFERENT family (never merged with the menu)
    assert cca._family_key("tcga-tumor-tpm-per-sample-v1") != cca._family_key("tcga-subgroup-assignments-hnsc-v1")
    # <4 tokens ⇒ no varying middle ⇒ not grouped (singleton)
    assert cca._family_key("depmap-26q1-v1") is None
    assert cca._family_key("a-b-c") is None


def test_cohort_menu_member_read_selectively_is_conditional_not_dead():
    # 3-shard menu, each run reads exactly ONE shard (mutually exclusive); shard z is never selected.
    matrices = [
        {"c": {"fam-aa-bb-x-v1": True, "fam-aa-bb-y-v1": False, "fam-aa-bb-z-v1": False}},
        {"c": {"fam-aa-bb-x-v1": False, "fam-aa-bb-y-v1": True, "fam-aa-bb-z-v1": False}},
    ]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2)
    by_mid = {i["manifest_id"]: i for i in cards[0]["inputs"]}
    # z is read-by-zero across both runs but the family is read SELECTIVELY ⇒ conditional, kept out of dead
    assert by_mid["fam-aa-bb-z-v1"]["read_runs"] == 0  # still visible, not masked
    assert by_mid["fam-aa-bb-z-v1"]["conditional_unselected"] is True
    assert by_mid["fam-aa-bb-z-v1"]["dead"] is False
    assert by_mid["fam-aa-bb-z-v1"]["family_size"] == 3 and by_mid["fam-aa-bb-z-v1"]["family_read_members"] == 2
    assert dead == []
    # the selected shards are plainly read and carry NO conditional tag
    assert "conditional_unselected" not in by_mid["fam-aa-bb-x-v1"]


def test_conditional_discriminator_requires_selective_sibling_reads():
    # THE anti-masking teeth: the same never-read member flips verdict purely on the sibling read pattern.
    dead_member = "fam-pp-qq-dead-v1"
    # SELECTIVE siblings (read one-at-a-time, max_coread=1 < size) ⇒ dead_member downgraded to conditional
    selective = [
        {"c": {dead_member: False, "fam-pp-qq-aa-v1": True, "fam-pp-qq-bb-v1": False}},
        {"c": {dead_member: False, "fam-pp-qq-aa-v1": False, "fam-pp-qq-bb-v1": True}},
    ]
    _, dead = cca._aggregate_read_matrices(selective, min_runs=2)
    assert [d["manifest_id"] for d in dead] == []  # menu evidence clears the read-0 member
    # NEVER-READ family (no sibling ever read) ⇒ no menu evidence ⇒ ALL three stay DEAD (blind-spot/breadth)
    never = [
        {"c": {dead_member: False, "fam-pp-qq-aa-v1": False, "fam-pp-qq-bb-v1": False}},
        {"c": {dead_member: False, "fam-pp-qq-aa-v1": False, "fam-pp-qq-bb-v1": False}},
    ]
    cards2, dead2 = cca._aggregate_read_matrices(never, min_runs=2)
    assert {d["manifest_id"] for d in dead2} == {dead_member, "fam-pp-qq-aa-v1", "fam-pp-qq-bb-v1"}
    by_mid = {i["manifest_id"]: i for i in cards2[0]["inputs"]}
    assert "conditional_unselected" not in by_mid[dead_member]  # never-read is NOT a menu


def test_coread_family_is_not_a_menu():
    # co-required pair read TOGETHER every run (max_coread == family_size) ⇒ not a menu; both plainly read.
    matrices = [
        {"c": {"co-mm-nn-alpha-v1": True, "co-mm-nn-beta-v1": True}},
        {"c": {"co-mm-nn-alpha-v1": True, "co-mm-nn-beta-v1": True}},
    ]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2)
    by_mid = {i["manifest_id"]: i for i in cards[0]["inputs"]}
    assert dead == []
    assert by_mid["co-mm-nn-alpha-v1"]["family_size"] == 2  # grouped as a family …
    assert "conditional_unselected" not in by_mid["co-mm-nn-alpha-v1"]  # … but co-read ⇒ never a menu
    assert "conditional_unselected" not in by_mid["co-mm-nn-beta-v1"]


# ── blind spots: an opaque owner (emitted output, 0 captured reads) is not demonstrated dead wiring ────
def test_card_opacity_maps_traced_opaque_and_omits_untraced():
    rep = {
        "cards": [
            {"card_id": "opaque_c", "measured": [], "health": {"status": "opaque"}},  # traced, 0 reads
            {"card_id": "ok_c", "measured": [{"op": "x"}], "health": {"status": "ok"}},
            {"card_id": "silent_c", "measured": [], "health": {"status": "no_output"}},  # emitted nothing
            {"card_id": "untraced_c", "measured": None, "health": {"status": "opaque"}},  # omitted entirely
        ]
    }
    op = cca._card_opacity(rep)
    assert op == {"opaque_c": True, "ok_c": False, "silent_c": False}  # no_output is NOT opaque; untraced omitted


def test_blind_spot_opaque_owner_reclassified_not_dead():
    # read-by-nobody input whose owning card was opaque (0 captured reads) in BOTH runs ⇒ blind spot, not dead.
    matrices = [{"c": {"mystery-mani": False}}, {"c": {"mystery-mani": False}}]
    opacities = [{"c": True}, {"c": True}]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2, opacities=opacities)
    rec = cards[0]["inputs"][0]
    assert rec["read_runs"] == 0 and rec["declared_traced_runs"] == 2  # still counted + visible
    assert rec["blind_spot_opaque"] is True
    assert rec["dead"] is False
    assert dead == []  # kept OUT of the dead-wiring verdict


def test_blind_spot_requires_opacity_in_ALL_runs_else_stays_dead():
    # THE anti-masking teeth: the SAME read-0 input flips on whether the owner was observed reading.
    matrices = [{"c": {"mystery-mani": False}}, {"c": {"mystery-mani": False}}]
    # opaque in only ONE run (in the other the card WAS observed reading, just not this object) ⇒ genuine dead
    partial = [{"c": True}, {"c": False}]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2, opacities=partial)
    rec = cards[0]["inputs"][0]
    assert "blind_spot_opaque" not in rec
    assert rec["dead"] is True
    assert [d["manifest_id"] for d in dead] == ["mystery-mani"]


def test_no_opacities_arg_never_reclassifies_as_blind_spot():
    # backward compat: without an opacity map the detector cannot infer opacity ⇒ a read-0 input stays dead.
    matrices = [{"c": {"mystery-mani": False}}, {"c": {"mystery-mani": False}}]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2)
    rec = cards[0]["inputs"][0]
    assert "blind_spot_opaque" not in rec
    assert rec["dead"] is True and [d["manifest_id"] for d in dead] == ["mystery-mani"]


def test_blind_spot_precedes_conditional_when_owner_opaque_in_all_runs():
    # a family read only via the run-union (owner opaque throughout) ⇒ blind spot dominates the menu label.
    matrices = [
        {"c": {"fam-gg-hh-x-v1": True, "fam-gg-hh-y-v1": False}},
        {"c": {"fam-gg-hh-x-v1": False, "fam-gg-hh-y-v1": False}},
    ]
    opacities = [{"c": True}, {"c": True}]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2, opacities=opacities)
    by_mid = {i["manifest_id"]: i for i in cards[0]["inputs"]}
    assert by_mid["fam-gg-hh-y-v1"]["blind_spot_opaque"] is True
    assert "conditional_unselected" not in by_mid["fam-gg-hh-y-v1"]  # blind spot wins over the menu tag
    assert by_mid["fam-gg-hh-y-v1"]["dead"] is False and dead == []


# ── partial blind spots (reader references the id; 0-read = warm-cache capture artifact) ─────────────
def _make_methods_pkg(root: Path, modules: dict[str, str]) -> None:
    """Write a fake importable ``methods`` package under ``root`` — ``{module_name: read.py source}``."""
    (root / "methods").mkdir(parents=True, exist_ok=True)
    (root / "methods" / "__init__.py").write_text("")
    for name, src in modules.items():
        pkg = root / "methods" / name
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "read.py").write_text(src)


@pytest.fixture
def _reader_source_env(monkeypatch, tmp_path):
    """Prepend a tmp dir to sys.path and clear all caches that would leak one test's fake ``methods``
    package into the next: the memoized reader-source lru_cache, importlib's finder caches, AND any
    ``methods*`` already in ``sys.modules`` (a cached parent package pins ``methods.__path__`` to the
    prior test's tmp dir, so a later ``find_spec`` would look in the wrong place)."""

    def _purge():
        for name in [m for m in sys.modules if m == "methods" or m.startswith("methods.")]:
            del sys.modules[name]
        importlib.invalidate_caches()
        cca._reader_source_for_call.cache_clear()

    monkeypatch.syspath_prepend(str(tmp_path))
    _purge()
    yield tmp_path
    _purge()


def test_reader_references_finds_manifest_id_in_call_package(_reader_source_env):
    # the id lives as a literal in the call's own reader package (the measured-potency shape)
    _make_methods_pkg(_reader_source_env, {"pkg_a": 'PROD = "widget-per-protein-v1"\n'})
    assert cca._reader_references("pkg-a", "widget-per-protein-v1") is True
    assert cca._reader_references("pkg-a", "unrelated-product-v9") is False


def test_reader_references_follows_one_hop_import_to_sibling(_reader_source_env):
    # the call's package only imports the sibling that holds the id literal (the pathway-node/paralog shape)
    _make_methods_pkg(
        _reader_source_env,
        {
            "pkg_root": "from methods.pkg_sib.read import load as _load\n",
            "pkg_sib": 'DERIVED = "buffering-per-gene-v1"\n',
        },
    )
    assert cca._reader_references("pkg-root", "buffering-per-gene-v1") is True


def test_reader_references_absent_when_no_code_reference(_reader_source_env):
    # the two GENUINE dead cases: reader reimplements from raw / declares an unwired additive ⇒ 0 refs
    _make_methods_pkg(_reader_source_env, {"pkg_raw": 'RAW = "some-nightly-snapshot.tsv"\n'})
    assert cca._reader_references("pkg-raw", "reviewed-per-gene-v1") is False


def test_reader_references_unresolvable_call_is_false(_reader_source_env):
    # no such module ⇒ empty source ⇒ False (best-effort; fails toward NOT reclassifying)
    assert cca._reader_references("no-such-method-xyz", "any-product-v1") is False
    assert cca._reader_references("", "any-product-v1") is False


def test_blind_spot_partial_reclassifies_referenced_dead_input_not_dead():
    # owner is NOT opaque (it read other objects every run) but the reader HAS code for this id ⇒ its
    # 0-read is a warm-cache capture artifact, not dead wiring.
    matrices = [{"c": {"cached-mani": False}}, {"c": {"cached-mani": False}}]
    reader_refs = {"c": {"cached-mani"}}
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2, reader_refs=reader_refs)
    rec = cards[0]["inputs"][0]
    assert rec["read_runs"] == 0 and rec["declared_traced_runs"] == 2  # still counted + visible
    assert rec["blind_spot_partial"] is True
    assert rec["dead"] is False
    assert dead == []  # kept OUT of the dead-wiring verdict


def test_unreferenced_dead_input_stays_dead_even_with_reader_refs():
    # THE anti-masking teeth: an input the reader NEVER references (civic-per-gene / genie-sv-recurrence)
    # stays dead even though reader_refs is supplied for OTHER inputs on the card.
    matrices = [{"c": {"unwired-mani": False, "cached-mani": False}}] * 2
    reader_refs = {"c": {"cached-mani"}}  # only cached-mani is referenced
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2, reader_refs=reader_refs)
    by_mid = {i["manifest_id"]: i for i in cards[0]["inputs"]}
    assert by_mid["cached-mani"]["blind_spot_partial"] is True and by_mid["cached-mani"]["dead"] is False
    assert "blind_spot_partial" not in by_mid["unwired-mani"]
    assert by_mid["unwired-mani"]["dead"] is True
    assert [d["manifest_id"] for d in dead] == ["unwired-mani"]


def test_no_reader_refs_arg_never_reclassifies_as_partial():
    # backward compat: without a reader_refs map a read-0 non-opaque input stays dead (pre-fix behavior).
    matrices = [{"c": {"cached-mani": False}}, {"c": {"cached-mani": False}}]
    cards, dead = cca._aggregate_read_matrices(matrices, min_runs=2)
    rec = cards[0]["inputs"][0]
    assert "blind_spot_partial" not in rec
    assert rec["dead"] is True and [d["manifest_id"] for d in dead] == ["cached-mani"]


def test_blind_spot_opaque_precedes_partial_when_owner_opaque_in_all_runs():
    # an input that is BOTH referenced and owned by an all-opaque card is the STRONGER opaque blind spot.
    matrices = [{"c": {"cached-mani": False}}, {"c": {"cached-mani": False}}]
    cards, dead = cca._aggregate_read_matrices(
        matrices, min_runs=2, opacities=[{"c": True}, {"c": True}], reader_refs={"c": {"cached-mani"}}
    )
    rec = cards[0]["inputs"][0]
    assert rec["blind_spot_opaque"] is True
    assert "blind_spot_partial" not in rec  # opaque wins; not double-tagged
    assert rec["dead"] is False and dead == []


# ── re-derivation honesty: reason_class taxonomy + per-lineage re-derivation ────────────────────────
def test_rederive_reason_class_splits_input_absent_from_method_internal():
    # no OmicsExpression read in the trace ⇒ scalars are input_absent_from_trace, NOT method_internal
    out = cca._rederive_cellline_rna_distribution([], {"n_cell_lines_evaluated": 4}, do_read=True)
    assert out["n_cell_lines_evaluated"]["reason_class"] == "input_absent_from_trace"
    assert out["n_cell_lines_evaluated"]["measured"] is False
    # genuinely method-internal fields keep method_internal regardless of what was traced
    assert out["distribution_pattern"]["reason_class"] == "method_internal"
    assert out["isoform_expression_class"]["reason_class"] == "method_internal"
    # allgene_percentile needs a DIFFERENT object never read by this card — that is input-absent, not
    # method-internal (the split the whole change is about)
    assert out["allgene_percentile"]["reason_class"] == "input_absent_from_trace"


def test_rederive_not_requested_is_its_own_reason_class():
    event = {"op": "pyarrow.read_table", "uri": "b/x/OmicsExpressionX.parquet", "columns": ["G", "ModelID"]}
    out = cca._rederive_cellline_rna_distribution([event], {"n_cell_lines_evaluated": 4}, do_read=False)
    # input present + re-derivable, but --rederive not passed ⇒ distinct from input-absent
    assert out["n_cell_lines_evaluated"]["reason_class"] == "not_requested"
    assert "match" not in out["n_cell_lines_evaluated"]


def _lin(vals):
    import numpy as np

    a = np.asarray(vals, dtype=float)
    return {"n": len(vals), "median_log2tpm": float(np.median(a)), "fraction_expressed": float(np.mean(a >= 1.0))}


def test_rederive_per_lineage_matches_and_catches_mismatch(monkeypatch):
    event = {"op": "pyarrow.read_table", "uri": "b/x/OmicsExpressionX.parquet", "columns": ["G (1)", "ModelID"]}
    lung_vals = [0.5, 2.0, 6.0, 6.0, 3.0]  # 5 models (>= min lineage size)
    bowel_vals = [0.0, 0.0, 0.5, 2.0, 7.0]  # 5 models
    model_scores = {f"M{i}": v for i, v in enumerate(lung_vals + bowel_vals)}
    lineage_map = {**{f"M{i}": "Lung" for i in range(5)}, **{f"M{i}": "Bowel" for i in range(5, 10)}}
    monkeypatch.setattr(cca, "_read_panel_scores_by_model", lambda e: model_scores)
    monkeypatch.setattr(cca, "_read_lineage_map", lambda m: lineage_map)

    emitted_rows = [{"lineage": "Lung", **_lin(lung_vals)}, {"lineage": "Bowel", **_lin(bowel_vals)}]
    res = cca._rederive_per_lineage(event, [event], emitted_rows)
    assert res["match"] is True and res["measured"] is True and res["n_lineages_checked"] == 2
    assert res["reason_class"] == "matched"

    # teeth: corrupt one lineage's median ⇒ the per-lineage re-derivation goes red
    bad_rows = [dict(emitted_rows[0], median_log2tpm=emitted_rows[0]["median_log2tpm"] + 2.0), emitted_rows[1]]
    bad = cca._rederive_per_lineage(event, [event], bad_rows)
    assert bad["match"] is False and bad["reason_class"] == "mismatch"
    assert "Lung.median_log2tpm" in bad["rederived"]


def test_rederive_per_lineage_missing_lineage_map_is_input_absent(monkeypatch):
    event = {"op": "pyarrow.read_table", "uri": "b/x/OmicsExpressionX.parquet", "columns": ["G (1)", "ModelID"]}
    monkeypatch.setattr(cca, "_read_panel_scores_by_model", lambda e: {"M0": 1.0})
    monkeypatch.setattr(cca, "_read_lineage_map", lambda m: None)  # Model.csv not traced / unreadable
    emitted = [{"lineage": "Lung", "n": 5, "median_log2tpm": 1.0, "fraction_expressed": 1.0}]
    res = cca._rederive_per_lineage(event, [event], emitted)
    assert res["measured"] is False and res["reason_class"] == "input_absent_from_trace"


def test_rederive_per_lineage_empty_emitted_is_benign_not_mismatch():
    # a card that emitted no per-lineage table must not read as a spurious mismatch
    event = {"op": "pyarrow.read_table", "uri": "b/x/OmicsExpressionX.parquet", "columns": []}
    res = cca._rederive_per_lineage(event, [event], [])
    assert res["match"] is None and res["n_lineages_checked"] == 0


def test_read_lineage_map_reads_local_csv(tmp_path):
    import pandas as pd

    p = tmp_path / "Model.csv"
    pd.DataFrame({"ModelID": ["ACH-1", "ACH-2"], "OncotreeLineage": ["Lung", None], "Other": [1, 2]}).to_csv(
        p, index=False
    )
    measured = [{"op": "pandas.read_csv", "uri": str(p)}]
    out = cca._read_lineage_map(measured)
    assert out == {"ACH-1": "Lung", "ACH-2": None}
    # no Model.csv read in the trace ⇒ None (input absent), never a crash
    assert cca._read_lineage_map([{"op": "pandas.read_csv", "uri": "/tmp/Other.csv"}]) is None


# ── owner resolution: companion / sidecar / unique-basename attribution gaps ──────────────────────────
def test_owning_manifest_credits_companion_summary_object():
    # G1 (paralog-GI): the manifest's PRIMARY s3_uri is the per-line table, but the card reads the documented
    # parameters.companion_summary_path (the *_summary.parquet). Exact match on s3_uri alone misses it.
    cat = _Catalog(
        [
            _Rec(
                "dede-gi",
                "s3://b/derived/dede/dede_gi_per_pair_line.parquet",
                raw={"parameters": {"companion_summary_path": "dede_gi_per_pair_summary.parquet"}},
            )
        ]
    )
    # the primary object resolves…
    assert cca._owning_manifest("b/derived/dede/dede_gi_per_pair_line.parquet", cat) == "dede-gi"
    # …and so does the companion the card actually opens
    assert cca._owning_manifest("b/derived/dede/dede_gi_per_pair_summary.parquet", cat) == "dede-gi"


def test_owning_manifest_companion_anti_vacuity_without_the_param():
    # teeth: strip the companion_summary_path and the SAME summary read is no longer credited — proving the
    # companion parameter is what resolves it, not an incidental basename/prefix match.
    cat = _Catalog([_Rec("dede-gi", "s3://b/derived/dede/dede_gi_per_pair_line.parquet")])
    assert cca._owning_manifest("b/derived/dede/dede_gi_per_pair_summary.parquet", cat) is None


def test_owning_manifest_credits_sidecar_object():
    cat = _Catalog(
        [
            _Rec(
                "m",
                "s3://b/derived/m/f.parquet",
                raw={"parameters": {"sidecar_s3_uri": "s3://b/derived/m/side.parquet"}},
            )
        ]
    )
    assert cca._owning_manifest("b/derived/m/side.parquet", cat) == "m"


def test_owning_manifest_unique_basename_fallback_credits_local_cache_copy():
    # G2 (local cache): the physical read is a /home/.../.cache/<x>/surfaceome_family.parquet copy of the
    # manifest's own object; its path is not an s3 uri so exact/prefix both miss. A UNIQUE basename resolves it.
    cat = _Catalog([_Rec("surfaceome", "s3://b/derived/surfaceome/surfaceome_family.parquet")])
    assert cca._owning_manifest("/home/x/.cache/framework-abc/surfaceome_family.parquet", cat) == "surfaceome"


def test_owning_manifest_ambiguous_basename_is_not_credited():
    # teeth: two manifests own the SAME basename ⇒ the fallback must refuse to guess (never mis-credit).
    cat = _Catalog(
        [
            _Rec("maf-a", "s3://b/derived/a/per_sample_maf.parquet"),
            _Rec("maf-b", "s3://b/derived/b/per_sample_maf.parquet"),
        ]
    )
    assert cca._owning_manifest("/home/x/.cache/framework-abc/per_sample_maf.parquet", cat) is None
    # each canonical s3 object still resolves exactly (the ambiguity only defeats the basename fallback)
    assert cca._owning_manifest("b/derived/a/per_sample_maf.parquet", cat) == "maf-a"


def test_reachable_from_events_folds_owner_and_derived_from_lineage():
    # G3: a read of the DERIVED product reaches BOTH the derived id and the raw source it derives from.
    cat = _Catalog(
        [
            _Rec("mc3-source", "s3://b/sources/mc3/"),
            _Rec("mc3-per-sample", "s3://b/derived/mc3ps/per_sample.parquet", derived_from=["mc3-source"]),
        ]
    )
    reached = cca._reachable_from_events(
        [{"op": "pyarrow.read_table", "uri": "b/derived/mc3ps/per_sample.parquet"}], cat
    )
    assert reached == {"mc3-per-sample", "mc3-source"}
    # an unresolvable uri contributes nothing (never a crash)
    assert cca._reachable_from_events([{"op": "x", "uri": "b/nowhere/z.parquet"}], cat) == set()
    assert cca._reachable_from_events(None, cat) == set()


def test_detect_findings_companion_read_is_neither_unread_nor_uncataloged():
    # end-to-end (G1): the card declares the paralog-GI manifest and the run opens its companion summary.
    # Neither declared_input_not_read_this_run nor read_object_not_in_any_manifest may fire.
    cat = _Catalog(
        [
            _Rec(
                "dede-gi",
                "s3://b/derived/dede/dede_gi_per_pair_line.parquet",
                raw={"parameters": {"companion_summary_path": "dede_gi_per_pair_summary.parquet"}},
            )
        ]
    )
    declared = {
        "method_calls": [],
        "manifests": [
            {
                "manifest_id": "dede-gi",
                "in_catalog": True,
                "s3_uri": "s3://b/derived/dede/dede_gi_per_pair_line.parquet",
            }
        ],
    }
    measured = [
        {"op": "pyarrow.read_table", "uri": "b/derived/dede/dede_gi_per_pair_summary.parquet", "uri_class": "s3_object"}
    ]
    kinds = _kinds(cca.detect_findings(declared, measured, {}, cat))
    assert "declared_input_not_read_this_run" not in kinds
    assert "read_object_not_in_any_manifest" not in kinds


def test_card_read_status_credits_source_via_cross_card_derived_read():
    # G3 at corpus grain: card A declares the raw SOURCE and records 0 events (lru_cache sharing); a DIFFERENT
    # card B reads the DERIVED product. The run-level union of reachable_manifest_ids must credit A's source.
    rep = {
        "cards": [
            {
                "card_id": "A",
                "measured": [],  # traced, zero own events
                "declared": {
                    "manifests": [{"manifest_id": "mc3-source", "in_catalog": True, "s3_uri": "s3://b/sources/mc3/"}]
                },
                "reachable_manifest_ids": [],  # A itself reached nothing
                "findings": [{"kind": "declared_input_not_read_this_run", "manifest_id": "mc3-source"}],
            },
            {
                "card_id": "B",
                "measured": [{"op": "pyarrow.read_table", "uri": "b/derived/mc3ps/per_sample.parquet"}],
                "declared": {"manifests": []},
                # B's read reached the derived product AND, via derived_from, the source A declares
                "reachable_manifest_ids": ["mc3-per-sample", "mc3-source"],
                "findings": [],
            },
        ]
    }
    status = cca._card_read_status(rep)
    assert status["A"] == {"mc3-source": True}  # credited through B's derived read — not dead


def test_card_read_status_source_stays_unread_when_no_card_reaches_it():
    # anti-vacuity for the above: with B reaching only the derived product (lineage severed / different
    # source), A's declared source is NOT in the union and stays unread.
    rep = {
        "cards": [
            {
                "card_id": "A",
                "measured": [],
                "declared": {
                    "manifests": [{"manifest_id": "mc3-source", "in_catalog": True, "s3_uri": "s3://b/sources/mc3/"}]
                },
                "reachable_manifest_ids": [],
                "findings": [{"kind": "declared_input_not_read_this_run", "manifest_id": "mc3-source"}],
            },
            {
                "card_id": "B",
                "measured": [{"op": "pyarrow.read_table", "uri": "b/derived/other/x.parquet"}],
                "declared": {"manifests": []},
                "reachable_manifest_ids": ["some-other-mani"],  # does NOT reach mc3-source
                "findings": [],
            },
        ]
    }
    assert cca._card_read_status(rep)["A"] == {"mc3-source": False}
