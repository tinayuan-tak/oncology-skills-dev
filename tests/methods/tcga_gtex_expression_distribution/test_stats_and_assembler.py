"""Per-sample cellline-rna-distribution layer: stats primitives + the Q1 assembler.

No S3: stats are pure numpy; the assembler is tested with monkeypatched readers. Pins the plan's
Q1 outputs (percentiles, detectable/moderate/high fractions, CoV, distribution_pattern) + the Q2
headline metric (fraction of tumors above the Nth percentile of normal) + the tumor_expression_class
ladder + data_unavailable safety.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution import stats as S  # noqa: E402
from methods.tcga_gtex_expression_distribution import read as R  # noqa: E402


# ---- stats primitives ----
def test_five_number_empty_is_coverage_gap():
    fn = S.five_number([])
    assert fn["n"] == 0 and fn["median"] is None and fn["p95"] is None


def test_expression_fractions_absolute_cutoffs():
    # 3 high (>=5.67), 1 moderate (>=3.46), 1 off (<1) → detectable 4/5, moderate 4/5, high 3/5
    vals = [6.0, 6.5, 7.0, 4.0, 0.2]
    f = S.expression_fractions(vals)
    assert f["detectable_fraction"] == pytest.approx(0.8)
    assert f["high_fraction"] == pytest.approx(0.6)


def test_cov_on_linear_and_divide_by_zero():
    assert S.coefficient_of_variation([0.0] * 10) == 0.0
    assert S.coefficient_of_variation([0.1] * 8 + [7.0] * 8) > 0.5


def test_distribution_pattern_three_shapes():
    assert S.distribution_pattern([0.1] * 10 + [7.0] * 10) == "bimodal"
    assert S.distribution_pattern([0.1] * 16 + [6.5] * 2) == "long_tail"
    assert S.distribution_pattern(list(np.linspace(2.0, 4.0, 20))) == "continuous"
    assert S.distribution_pattern([6.0, 0.1, 6.0]) == "continuous"     # n<8 guard


def test_fraction_above_normal_percentile_headline_metric():
    tumor = [6.0, 6.5, 7.0, 5.5, 6.2] * 4
    normal = [1.0, 1.5, 0.8, 1.2, 1.1] * 4
    r = S.fraction_above_normal_percentile(tumor, normal, 95)
    assert r["fraction_tumor_above"] == pytest.approx(1.0)     # tumor fully above normal p95
    assert r["n_tumor"] == 20 and r["n_normal"] == 20
    # empty normal arm → coverage gap, not a fabricated fraction
    assert S.fraction_above_normal_percentile(tumor, [], 95)["fraction_tumor_above"] is None


def test_distribution_overlap_separated_vs_identical():
    sep = S.distribution_overlap([6.0, 6.5, 7.0] * 5, [1.0, 1.2, 0.8] * 5)
    assert sep is not None and sep < 0.1                      # cleanly separated
    ident = S.distribution_overlap([3.0, 3.5, 4.0] * 5, [3.0, 3.5, 4.0] * 5)
    assert ident > 0.8                                        # identical → high overlap


# ---- Q3 normal-tissue-liability primitive ----
def test_normal_tissue_liability_critical_organ_flag():
    # a target high in a CRITICAL organ (BRAIN) → critical_organ_liability regardless of breadth
    atlas = {"BRAIN": [8.0] * 20, "SKIN": [0.2] * 20, "COLON": [0.1] * 20}
    r = S.normal_tissue_liability(atlas)
    assert r["highest_tissue"] == "BRAIN" and r["critical_organ_argmax"] == "BRAIN"
    assert r["critical_organ_max"] >= S.HIGH_LOG2TPM
    assert r["n_tissues_tested"] == 3


def test_normal_tissue_liability_breadth_and_gap():
    # broadly expressed (all detectable) → breadth 1.0
    broad = S.normal_tissue_liability({"A": [4.0] * 10, "B": [4.0] * 10, "C": [4.0] * 10})
    assert broad["tissue_breadth_fraction"] == pytest.approx(1.0)
    # empty atlas → coverage gap, not fabricated
    assert S.normal_tissue_liability({})["n_tissues_tested"] == 0


# ---- Q2 percentile-crossing assembler (monkeypatched readers, no S3) ----
def test_q2_strongly_tumor_enriched(monkeypatch):
    # tumor mostly above normal p95 + separated distributions → strongly_tumor_enriched
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [6.0, 6.5, 7.0, 6.2] * 10)
    monkeypatch.setattr(R, "read_normal_samples", lambda t, i: ([1.0, 1.2, 0.8] * 10, "COLON"))
    out = R.read_tumor_vs_normal_percentile_crossing("CEACAM5", "COADREAD")
    assert out["selectivity_class"] == "strongly_tumor_enriched"
    assert out["fraction_tumor_above_normal_p95"] > 0.9
    assert out["distribution_overlap_tumor_normal"] < 0.4


def test_q2_minimally_enriched_and_data_gap(monkeypatch):
    # tumor ~ normal → minimally/not enriched
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [3.0, 3.5, 4.0] * 10)
    monkeypatch.setattr(R, "read_normal_samples", lambda t, i: ([3.0, 3.5, 4.0] * 10, "COLON"))
    out = R.read_tumor_vs_normal_percentile_crossing("KRAS", "COADREAD")
    assert out["selectivity_class"] in ("minimally_enriched", "not_enriched")
    # no matched normal → data_unavailable (not a fabricated 0)
    monkeypatch.setattr(R, "read_normal_samples", lambda t, i: ([], None))
    gap = R.read_tumor_vs_normal_percentile_crossing("X", "COADREAD")
    assert gap["selectivity_class"] == "data_unavailable"


def test_q3_liability_assembler(monkeypatch):
    monkeypatch.setattr(R, "read_all_normal_tissues",
                        lambda t: {"BRAIN": [8.0] * 20, "SKIN": [0.1] * 20})
    out = R.read_normal_tissue_liability("GFAP")
    assert out["liability_class"] == "critical_organ_liability"
    monkeypatch.setattr(R, "read_all_normal_tissues", lambda t: {})
    assert R.read_normal_tissue_liability("GHOST")["liability_class"] == "data_unavailable"


def test_q2_q3_cli_build_and_liability_figure(tmp_path, monkeypatch):
    """CLI build_* entry points + the Q3 liability atlas figure (monkeypatched, no S3)."""
    import importlib
    pytest.importorskip("matplotlib")
    cli = importlib.import_module("methods.tcga_gtex_expression_distribution.cli")
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [6.0, 6.5, 7.0] * 10)
    monkeypatch.setattr(R, "read_normal_samples", lambda t, i: ([1.0, 1.2] * 10, "COLON"))
    q2 = cli.build_selectivity_crossing_summary("CEACAM5", "COADREAD")
    assert q2["selectivity_class"] == "strongly_tumor_enriched" and "method_version" in q2
    monkeypatch.setattr(R, "read_all_normal_tissues",
                        lambda t: {"BRAIN": [8.0] * 20, "COLON": [0.1] * 20, "SKIN": [0.2] * 20})
    q3 = cli.build_normal_liability_summary("GFAP")
    assert q3["liability_class"] == "critical_organ_liability"
    svg = cli.emit_liability_svg("GFAP", tmp_path)
    assert svg is not None and svg.exists()
    specs = cli.emit_liability_plotly_specs("GFAP", tmp_path)
    assert [s["id"] for s in specs] == ["normal_tissue_liability_atlas"]
    # data-gap safety
    monkeypatch.setattr(R, "read_all_normal_tissues", lambda t: {})
    assert cli.emit_liability_svg("GHOST", tmp_path) is None


# ---- Q1 assembler (monkeypatched readers, no S3) ----
def test_assembler_broadly_high(monkeypatch):
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [6.0, 6.5, 7.0, 5.8, 6.1] * 4)
    out = R.read_tumor_expression_distribution("KRAS", "COADREAD")
    assert out["n_tumor_samples"] == 20
    assert out["tumor_expression_class"] == "broadly_high"
    assert out["distribution_pattern"] == "continuous"
    assert out["high_fraction"] >= 0.5 and out["median_log2tpm"] > 5


def test_assembler_subset_high_bimodal(monkeypatch):
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [0.1] * 12 + [6.5] * 8)
    out = R.read_tumor_expression_distribution("X", "COADREAD")
    assert out["distribution_pattern"] == "bimodal"
    assert out["tumor_expression_class"] == "subset_high"     # a target-high subset → patient selection


def test_assembler_data_unavailable(monkeypatch):
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [])
    out = R.read_tumor_expression_distribution("GHOST", "COADREAD")
    assert out["tumor_expression_class"] == "data_unavailable" and out["n_tumor_samples"] == 0
    # Phase 1C: the data-gap branch still carries the allgene fields (null), so the card's
    # declared summary_fields are always present — a consumer never KeyErrors on them.
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    assert "allgene_percentile_context" in out


# ---- Phase 1C: allgene percentile merged into the Q1 assembler (no S3) ----
def test_assembler_merges_allgene_percentile(monkeypatch):
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [6.0, 6.5, 7.0, 5.8] * 5)
    # patch the reader's lookup seam (not S3) — assert the fields flow through verbatim.
    monkeypatch.setattr(R, "_tumor_allgene_percentile", lambda target, studies: {
        "allgene_percentile": 99.9, "allgene_percentile_class": "top_1pct",
        "allgene_percentile_context": "tcga_tumor:COAD,READ (allgene-tumor-rank-v1)",
        "allgene_percentile_by_study": {"COAD": 99.9, "READ": 99.92}})
    out = R.read_tumor_expression_distribution("CEACAM5", "COADREAD")
    assert out["allgene_percentile"] == pytest.approx(99.9)
    assert out["allgene_percentile_class"] == "top_1pct"
    assert out["allgene_percentile_by_study"] == {"COAD": 99.9, "READ": 99.92}
    # the enrichment must NOT disturb the core distribution verdict (one-directional).
    assert out["tumor_expression_class"] == "broadly_high"


def test_tumor_allgene_percentile_seam_offline(monkeypatch):
    """The _tumor_allgene_percentile seam resolves symbol→ensembl + delegates to the lookup,
    both patched — proves the reader wires the accessor without touching S3."""
    monkeypatch.setattr(R, "_symbol_to_ensembl_ids", lambda s: ["ENSG00000105383"])
    import methods.allgene_percentile_precompute.lookup as _lk
    monkeypatch.setattr(_lk, "_tumor_rows",
                        lambda ids, source: (("COAD", 88.0, 500, 41000, 4.0),))
    out = R._tumor_allgene_percentile("CD33", ["COAD"])
    assert out["allgene_percentile"] == pytest.approx(88.0)
    assert out["allgene_percentile_class"] == "mid"


# ---- subtype layer (synthetic shard + bridged reader; no S3) ----
import pandas as pd  # noqa: E402


def _fake_assignments(rows):
    """rows: list of (case, stratum_id, is_member). Minimal assignment-shard shape."""
    return pd.DataFrame(rows, columns=["sample_id", "stratum_id", "is_member"])


def _wire_subtype(monkeypatch, *, pooled_vals, bridged_rows, assignment_rows):
    """Wire the substrate hops the landscape assembler calls, all offline:
    pooled distribution, the case-bridged per-sample frame, and the assignment shard."""
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: pooled_vals)
    monkeypatch.setattr(R, "read_tumor_samples_with_case",
                        lambda t, i: pd.DataFrame(bridged_rows, columns=["case", "log2_tpm"]))
    # The assembler also calls read_normal_samples (GTEx). Mock it to genuine-absence (empty) so the
    # subtype tests stay OFFLINE — they must not depend on a live GTEx S3 read. (Previously this hop
    # silently returned empty via a broad except that MASKED a creds/AccessDenied failure; that mask
    # was removed, so the read now propagates and the offline test must mock it explicitly.)
    monkeypatch.setattr(R, "read_normal_samples", lambda t, i: ([], None))
    # patch load_assignments + compute_join_coverage where the assembler imports them
    import methods.subgroup_common.loaders as _loaders
    import methods.subgroup_common.scoping as _scoping
    monkeypatch.setattr(_loaders, "load_assignments",
                        lambda mid, **kw: _fake_assignments(assignment_rows))
    monkeypatch.setattr(_scoping, "load_assignments",
                        lambda mid, **kw: _fake_assignments(assignment_rows))


def test_subtype_enriched_and_depleted_fire(monkeypatch):
    # pooled median ~2.0; stratum HI (cases h*) high ~4.0 → enriched; LO (cases l*) low ~0.5 → depleted.
    hi = [(f"h{i}", 4.0) for i in range(40)]
    lo = [(f"l{i}", 0.5) for i in range(40)]
    bridged = hi + lo
    pooled = [4.0] * 40 + [0.5] * 40
    assign = ([(f"h{i}", "SUBTYPE_HI", True) for i in range(40)]
              + [(f"l{i}", "SUBTYPE_LO", True) for i in range(40)])
    _wire_subtype(monkeypatch, pooled_vals=pooled, bridged_rows=bridged, assignment_rows=assign)
    res = R.read_tumor_expression_subtype_landscape("X", "COADREAD")
    assert res["subtype_axis_available"] is True
    sig = {r["stratum_id"]: r["subtype_signal"] for r in res["subtype_landscape"]}
    assert sig["SUBTYPE_HI"] == "subtype_enriched"
    assert sig["SUBTYPE_LO"] == "subtype_depleted"
    assert res["n_subtypes_measured"] == 2 and res["n_subtypes_enriched"] == 1


def test_landscape_emits_subtype_omnibus(monkeypatch):
    # two powered, well-separated strata → the omnibus fires with a large effect size.
    hi = [(f"h{i}", 4.0 + (i % 5) * 0.1) for i in range(40)]
    lo = [(f"l{i}", 0.5 + (i % 5) * 0.1) for i in range(40)]
    _wire_subtype(monkeypatch, pooled_vals=[v for _c, v in hi + lo], bridged_rows=hi + lo,
                  assignment_rows=[(f"h{i}", "SUBTYPE_HI", True) for i in range(40)]
                                  + [(f"l{i}", "SUBTYPE_LO", True) for i in range(40)])
    res = R.read_tumor_expression_subtype_landscape("X", "COADREAD")
    assert res["subtype_effect_size_class"] == "large"
    assert res["subtype_variance_explained"] > 0.14
    assert res["subtype_omnibus_kruskal_h"] is not None
    assert res["which_subtypes_separate"] == {"highest": "SUBTYPE_HI", "lowest": "SUBTYPE_LO"}
    assert res["n_subtypes_measured"] == 2


def test_omnibus_excludes_underpowered_strata(monkeypatch):
    # only the POWERED strata enter the omnibus; an n<30 stratum must not be tested.
    # A + B have real overlapping spread + near-equal centers → negligible effect (rank-based
    # KW needs within-group spread; two CONSTANT groups would rank-separate perfectly — see
    # test_class_tracks_effect_not_p for the spread-based effect-vs-p property).
    _rng = np.random.default_rng(7)
    small = [(f"s{i}", 8.0 + _rng.normal(0, 1)) for i in range(10)]   # n=10 < floor → excluded
    big_a = [(f"a{i}", float(v)) for i, v in enumerate(_rng.normal(4.0, 1.0, 40))]
    big_b = [(f"b{i}", float(v)) for i, v in enumerate(_rng.normal(4.05, 1.0, 40))]
    _wire_subtype(monkeypatch, pooled_vals=[v for _c, v in small + big_a + big_b],
                  bridged_rows=small + big_a + big_b,
                  assignment_rows=[(f"s{i}", "RARE", True) for i in range(10)]
                                  + [(f"a{i}", "A", True) for i in range(40)]
                                  + [(f"b{i}", "B", True) for i in range(40)])
    res = R.read_tumor_expression_subtype_landscape("X", "COADREAD")
    assert res["n_subtypes_tested"] == 2                    # RARE (underpowered) excluded
    assert res["subtype_effect_size_class"] == "negligible"


def test_omnibus_data_unavailable_when_one_powered_stratum(monkeypatch):
    # a single powered stratum → no across-subtype contrast possible.
    big = [(f"b{i}", 4.0) for i in range(50)]
    small = [(f"s{i}", 6.0) for i in range(10)]
    _wire_subtype(monkeypatch, pooled_vals=[v for _c, v in big + small], bridged_rows=big + small,
                  assignment_rows=[(f"b{i}", "COMMON", True) for i in range(50)]
                                  + [(f"s{i}", "RARE", True) for i in range(10)])
    res = R.read_tumor_expression_subtype_landscape("X", "COADREAD")
    assert res["subtype_effect_size_class"] == "data_unavailable"
    assert res["subtype_variance_explained"] is None


def test_subtype_underpowered_gets_null_signal_not_scoped_call(monkeypatch):
    # a stratum below the n=30 floor must carry stats for context but a NULL signal + underpowered.
    small = [(f"s{i}", 6.0) for i in range(10)]      # n=10 < 30
    big = [(f"b{i}", 2.0) for i in range(50)]
    _wire_subtype(monkeypatch, pooled_vals=[6.0] * 10 + [2.0] * 50,
                  bridged_rows=small + big,
                  assignment_rows=[(f"s{i}", "RARE", True) for i in range(10)]
                                  + [(f"b{i}", "COMMON", True) for i in range(50)])
    res = R.read_tumor_expression_subtype_landscape("X", "COADREAD")
    rec = {r["stratum_id"]: r for r in res["subtype_landscape"]}
    assert rec["RARE"]["evidence_state"] == "underpowered"
    assert rec["RARE"]["subgroup_n_floor_met"] is False
    assert rec["RARE"]["subtype_signal"] is None          # never a scoped call when underpowered
    assert rec["RARE"]["median_log2tpm"] is not None       # but stats survive for context
    assert rec["COMMON"]["evidence_state"] == "measured"


def test_subtype_no_shard_indication_axis_unavailable(monkeypatch):
    # an indication with no landed tumor shard → honest axis-unavailable, pooled still returned.
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [5.0] * 30)
    res = R.read_tumor_expression_subtype_landscape("X", "BRCA")
    assert res["subtype_axis_available"] is False
    assert res["subtype_landscape"] == []
    assert res["tumor_expression_class"] != "data_unavailable"   # pooled distribution still computed
    assert "no landed tumor assignment shard" in res["_subtype_note"]


def test_subtype_compute_all_spotlight_one(monkeypatch):
    # spotlight a subtype → it moves the spotlight, NEVER drops the other strata (compute-all).
    a = [(f"a{i}", 4.0) for i in range(40)]
    b = [(f"b{i}", 3.9) for i in range(40)]
    _wire_subtype(monkeypatch, pooled_vals=[4.0] * 40 + [3.9] * 40, bridged_rows=a + b,
                  assignment_rows=[(f"a{i}", "A", True) for i in range(40)]
                                  + [(f"b{i}", "B", True) for i in range(40)])
    res = R.read_tumor_expression_subtype_landscape("X", "COADREAD", subtype="A")
    assert res["spotlight_subtype"] == "A"
    assert {r["stratum_id"] for r in res["subtype_landscape"]} == {"A", "B"}  # both computed


# ---- CLI emission (monkeypatched readers, no S3) ----
def test_cli_emits_full_bar(tmp_path, monkeypatch):
    """CLI emits Tier1 summary.json + Tier2 plot_data + Tier3 SVG + plotly + manifest w/ plotly slot."""
    import importlib, json
    pytest.importorskip("matplotlib")
    pytest.importorskip("pyarrow")
    cli = importlib.import_module("methods.tcga_gtex_expression_distribution.cli")
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: [6.0, 6.5, 7.0, 5.8] * 5)
    monkeypatch.setattr(R, "read_normal_samples", lambda t, i: ([1.0, 1.2, 0.8] * 5, "COLON"))
    # build_summary also computes the subtype landscape (read_tumor_samples_with_case → GTEx/TCGA
    # long product). This test does not exercise subtypes; mock the case-bridged read to an empty
    # frame so it stays OFFLINE (the removed broad-except no longer masks the live read's AccessDenied).
    monkeypatch.setattr(R, "read_tumor_samples_with_case",
                        lambda t, i: pd.DataFrame(columns=["case", "log2_tpm"]))
    summary = cli.build_summary("KRAS", "COADREAD")
    assert summary["tumor_expression_class"] == "broadly_high"
    assert summary["fraction_tumor_above_normal_p95"] == pytest.approx(1.0)  # tumor >> normal
    assert summary["matched_normal_tissue"] == "COLON"
    cli.emit_plot_data("KRAS", "COADREAD", tmp_path)
    cli.emit_svg("KRAS", "COADREAD", summary, tmp_path)
    specs = cli.emit_plotly_specs("KRAS", "COADREAD", tmp_path)
    cli.emit_manifest("KRAS", "COADREAD", summary, tmp_path, specs)
    assert (tmp_path / "plot_data_expression_distribution.parquet").exists()
    assert (tmp_path / "figure_expression_distribution.svg").exists()
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert [f["id"] for f in man["plotly_figures"]] == ["expression_distribution_per_sample"]


def test_cli_pooled_carries_rollup_not_full_landscape(monkeypatch):
    """POOLED build_summary carries only the subtype ROLLUP (scalars + non-uniform digest), NOT the
    full per-stratum table — the full panorama lives on the sibling card (build_subtype_panorama).
    Cramming all strata into the pooled card overflows the synthesis prompt char-cap (measured)."""
    import importlib
    cli = importlib.import_module("methods.tcga_gtex_expression_distribution.cli")
    # HI enriched (~4.0) vs LO depleted (~0.5) vs MID uniform (~2.0); pooled median ~2.0.
    _wire_subtype(monkeypatch, pooled_vals=[4.0] * 40 + [2.0] * 40 + [0.5] * 40,
                  bridged_rows=[(f"a{i}", 4.0) for i in range(40)] + [(f"m{i}", 2.0) for i in range(40)]
                               + [(f"b{i}", 0.5) for i in range(40)],
                  assignment_rows=[(f"a{i}", "HI", True) for i in range(40)]
                                  + [(f"m{i}", "MID", True) for i in range(40)]
                                  + [(f"b{i}", "LO", True) for i in range(40)])
    # set AFTER _wire_subtype (which defaults read_normal_samples to empty) so the matched-normal
    # value this test asserts on ("COLON") wins.
    monkeypatch.setattr(R, "read_normal_samples", lambda t, i: ([1.0] * 10, "COLON"))
    summary = cli.build_summary("X", "COADREAD")
    assert summary["subtype_axis_available"] is True
    assert summary["n_subtypes_measured"] == 3
    # pooled card does NOT carry the full landscape (that overflows the prompt budget)
    assert "subtype_landscape" not in summary
    # only the NON-UNIFORM strata make the compact digest (HI enriched + LO depleted, not MID)
    digest = {r["stratum_id"]: r["subtype_signal"] for r in summary["subtype_signals_nonuniform"]}
    assert digest == {"HI": "subtype_enriched", "LO": "subtype_depleted"}
    # pooled + normal fields untouched
    assert summary["median_log2tpm"] is not None and summary["matched_normal_tissue"] == "COLON"


def test_cli_subtype_svg_and_plotly_emit(tmp_path, monkeypatch):
    """The subtype panel (SVG + plotly) emits one row per stratum from the shared value reader,
    and is data_unavailable-safe (no shard → None / [])."""
    import importlib
    pytest.importorskip("matplotlib")
    cli = importlib.import_module("methods.tcga_gtex_expression_distribution.cli")
    # wire read_tumor_subtype_values directly (the emitters' substrate)
    monkeypatch.setattr(R, "read_tumor_subtype_values", lambda t, i: {
        "available": True, "pooled_median": 2.0, "assignment_manifest": "m",
        "pooled_values": [4.0] * 40 + [1.0] * 40,
        "strata": [
            {"stratum_id": "HI", "values": [4.0] * 40, "subtype_signal": "subtype_enriched",
             "evidence_state": "measured", "subgroup_n_floor_met": True, "n": 40, "median": 4.0},
            {"stratum_id": "LO", "values": [1.0] * 40, "subtype_signal": "subtype_depleted",
             "evidence_state": "measured", "subgroup_n_floor_met": True, "n": 40, "median": 1.0},
        ]})
    svg = cli.emit_subtype_svg("X", "COADREAD", tmp_path)
    assert svg is not None and svg.exists()
    specs = cli.emit_subtype_plotly_specs("X", "COADREAD", tmp_path)
    assert [s["id"] for s in specs] == ["expression_distribution_subtype_panel"]
    assert (tmp_path / "figure_expression_distribution_subtype.plotly.json").exists()
    # no-shard safety
    monkeypatch.setattr(R, "read_tumor_subtype_values",
                        lambda t, i: {"available": False, "strata": [], "pooled_median": None})
    assert cli.emit_subtype_svg("X", "BRCA", tmp_path) is None
    assert cli.emit_subtype_plotly_specs("X", "BRCA", tmp_path) == []


def test_cli_subtype_panorama_carries_full_per_subgroup_metrics(monkeypatch):
    """build_subtype_panorama returns the FULL per-stratum table as per_subgroup_metrics — the
    shape the tumor-rna-distribution-by-subtype card declares."""
    import importlib
    cli = importlib.import_module("methods.tcga_gtex_expression_distribution.cli")
    _wire_subtype(monkeypatch, pooled_vals=[4.0] * 40 + [2.0] * 40,
                  bridged_rows=[(f"a{i}", 4.0) for i in range(40)] + [(f"b{i}", 2.0) for i in range(40)],
                  assignment_rows=[(f"a{i}", "HI", True) for i in range(40)]
                                  + [(f"b{i}", "LO", True) for i in range(40)])
    pan = cli.build_subtype_panorama("X", "COADREAD")
    assert pan["subtype_axis_available"] is True and pan["n_subtypes_measured"] == 2
    assert {r["stratum_id"] for r in pan["per_subgroup_metrics"]} == {"HI", "LO"}


# ---- Phase B: crossing-by-subtype panorama (monkeypatched landscape, no S3) ----
from methods.tcga_gtex_expression_distribution import cli as C  # noqa: E402


def _fake_landscape(**over):
    base = {
        "subtype_axis_available": True, "matched_normal_tissue": "COLON",
        "normal_comparator_type": "matched", "assignment_manifest": "tcga-subgroup-assignments-coadread-v1",
        "subtype_landscape": [
            # a strongly-enriched stratum (frac_p95 high, clean separation)
            {"stratum_id": "MSI_H", "evidence_state": "measured", "n_tumor_samples": 60,
             "fraction_tumor_above_normal_p95": 0.82, "fraction_tumor_above_normal_p99": 0.7,
             "distribution_overlap_tumor_normal": 0.2},
            # a not-enriched stratum (frac_p95 ~0)
            {"stratum_id": "MSS", "evidence_state": "measured", "n_tumor_samples": 120,
             "fraction_tumor_above_normal_p95": 0.03, "fraction_tumor_above_normal_p99": 0.0,
             "distribution_overlap_tumor_normal": 0.9},
            # an underpowered stratum → data_unavailable, excluded from rollup
            {"stratum_id": "RARE", "evidence_state": "underpowered", "n_tumor_samples": 8,
             "fraction_tumor_above_normal_p95": None, "fraction_tumor_above_normal_p99": None,
             "distribution_overlap_tumor_normal": None},
        ],
    }
    base.update(over)
    return base


def test_crossing_subtype_panorama_classifies_and_rolls_up(monkeypatch):
    monkeypatch.setattr(C._read, "read_tumor_expression_subtype_landscape",
                        lambda t, i: _fake_landscape())
    out = C.build_selectivity_crossing_subtype_panorama("CEACAM5", "COADREAD")
    by = {m["stratum_id"]: m for m in out["per_subgroup_metrics"]}
    # per-stratum classification reuses the pooled crossing vocabulary
    assert by["MSI_H"]["percentile_crossing_class"] == "strongly_tumor_enriched"
    assert by["MSS"]["percentile_crossing_class"] == "not_enriched"
    assert by["RARE"]["percentile_crossing_class"] == "data_unavailable"
    # rollup: one strongly-enriched, measured=2 (RARE excluded), and the range spans a class boundary
    assert out["n_subtypes_measured"] == 2
    assert out["n_subtypes_strongly_enriched"] == 1
    assert out["max_subtype_fraction_above_normal_p95"] == 0.82
    assert out["crossing_varies_by_subtype"] is True


def test_crossing_subtype_panorama_data_unavailable_safe(monkeypatch):
    monkeypatch.setattr(C._read, "read_tumor_expression_subtype_landscape",
                        lambda t, i: {"subtype_axis_available": False, "subtype_landscape": [],
                                      "_subtype_note": "no landed tumor assignment shard"})
    out = C.build_selectivity_crossing_subtype_panorama("X", "UNKNOWN")
    assert out["per_subgroup_metrics"] == []
    assert out["n_subtypes_measured"] == 0
    assert out["crossing_varies_by_subtype"] is False
    assert out["max_subtype_fraction_above_normal_p95"] is None
    assert out["_subtype_note"] == "no landed tumor assignment shard"


def test_subtype_panorama_projects_axis_quality_and_purity_spread(monkeypatch):
    """Regression: build_subtype_panorama must project subtype_axis_quality (the honest capability grade)
    and subtype_purity_spread — both declared by the tumor-rna-distribution-by-subtype card and computed
    by the reader. They were previously dropped, leaving the tumor-side `subtype_axis_quality` headline
    field permanently null while subtype_axis_available:true masked an underpowered axis."""
    land = _fake_landscape(subtype_axis_quality="underpowered",
                           subtype_purity_spread={"max_median_purity": 0.8, "min_median_purity": 0.5,
                                                  "delta": 0.3})
    monkeypatch.setattr(C._read, "read_tumor_expression_subtype_landscape",
                        lambda t, i, plot_data_out=None: land)
    pan = C.build_subtype_panorama("X", "COADREAD")
    assert pan["subtype_axis_quality"] == "underpowered"
    assert pan["subtype_purity_spread"] == {"max_median_purity": 0.8, "min_median_purity": 0.5,
                                            "delta": 0.3}
