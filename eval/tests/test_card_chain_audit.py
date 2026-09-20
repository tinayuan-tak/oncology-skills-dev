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

import card_chain_audit as cca  # noqa: E402


# ── fake catalog ────────────────────────────────────────────────────────────────────────────────────
class _Rec:
    def __init__(self, mid, s3_uri, derived_from=None):
        self.id = mid
        self.s3_uri = s3_uri
        self.type = "derived"
        self.parquet_schema = []
        self.query_optimization = None
        self.license = None
        self.derived_from = list(derived_from or [])


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
