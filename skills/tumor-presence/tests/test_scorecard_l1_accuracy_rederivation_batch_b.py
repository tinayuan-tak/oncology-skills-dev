"""Scorecard L1 accuracy batch B (#2044) — the DGE product family, EPCAM/COADREAD re-derivation.

FILE-DISJOINT sibling of test_scorecard_l1_accuracy_rederivation.py (#1988, A0c exemplar) and
test_scorecard_l1_accuracy_rederivation_batch_a.py (#2043) — do NOT edit either; this one covers the
next two verdict-bearing cards of the DGE product family. Same method: it reuses analysis-methods' T3
recomputation anchors (plan foamy-bird Stage I) and BRIDGES them one step further than
analysis-methods' own tests — RE-DERIVING through the REAL reader from the frozen raw input (so the
anchor's expected_* cannot have been hand-tuned to the golden) and asserting the re-derived number
ALSO equals what tumor-presence's own committed golden (`tests/fixtures/epcam_coadread_decision.json`)
emits for the same card. Two repos' independent captures meeting at the same float64 value is the
reconciliation.

Covers the two verdict-bearing cards batch B adds a landed T3 anchor for:
  - tumor-rna-vs-adjacent   (per-indication tumor-vs-adjacent DESeq2 product ->
                             methods.dge_deseq2.read.read_dge_gene_row)
  - tumor-elevation-breadth (two-layer: cptac_protein_deg.read.read_tumor_elevation_breadth +
                             dge_deseq2.derive_pancan_stack.read_rna_tumor_elevation_breadth)

BOUNDARY (recorded here and in the shard evidence): these anchors validate the READ/AGGREGATION path,
NOT the upstream DEG/DESeq2 runs. tumor-rna-vs-adjacent's `gtex_log2_fc`/`gtex_q_value` come from a
SEPARATE GTEx reader (not read_dge_gene_row) and are not bridged. The adjacent-arm adequacy logic
(#864/#865) is NOT on read_dge_gene_row's path (sensitivity-family only).

DATA-LEVEL FINDING (honestly recorded, not silently normalized): the tumor-elevation-breadth RNA
layer's `rna_n_indications_tested` in the committed golden is 26, but the current
`pancan-dge-tumor-vs-normal-v1` product tests 27 indications — the product gained ONE
non-elevated indication AFTER the golden was captured. The elevated NUMERATOR (n_elevated=10),
the elevated indication SET, and the median max-log2fc are byte-identical between the golden and the
current reader; only the denominator (`n_indications_tested`) and its dependent `rna_fraction_elevated`
shifted. This is a benign upstream product-vintage advance, pinned as denominator-only by
`test_elevation_breadth_rna_drift_is_denominator_only_and_non_elevated` below. The bridge asserts the
stable RNA fields; the golden fixture is NOT regenerated (verdict + goldens stay byte-stable).

OFFLINE — reads only committed fixtures (this repo's golden + analysis-methods' committed anchors),
no S3, no creds. Skips (not fails) if the analysis-methods sibling checkout lacks the batch-B anchors,
so a partial checkout / pre-merge CI degrades honestly instead of red on an unrelated absence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
for _p in (str(SKILLS_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _skills_common.paths import analysis_methods_root  # noqa: E402

AM_ROOT = analysis_methods_root()
RECOMPUTATION_DIR = AM_ROOT / "tests" / "calibration" / "recomputation"
ANCHOR_DIR = RECOMPUTATION_DIR / "anchors"
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"

_RVA_ANCHOR = ANCHOR_DIR / "epcam_coadread.tumor_rna_vs_adjacent.json"
_TEB_ANCHOR = ANCHOR_DIR / "epcam.tumor_elevation_breadth.json"

pytestmark = pytest.mark.skipif(
    not (_RVA_ANCHOR.exists() and _TEB_ANCHOR.exists()),
    reason=f"analysis-methods batch-B DGE anchors not found under {ANCHOR_DIR} (sibling checkout pre-merge/partial)",
)


def _golden_card(card_id: str) -> dict:
    d = json.loads(GOLDEN.read_text())
    for c in d["cards"]:
        if c["card_id"] == card_id:
            return c["summary"]
    raise AssertionError(f"golden fixture carries no card {card_id!r}")


# ── tumor-rna-vs-adjacent ──────────────────────────────────────────────────────────────────────


def _rederive_rna_vs_adjacent(anchor: dict) -> dict:
    """Re-derive through the REAL read_dge_gene_row from the frozen raw gene row + all-gene null."""
    import onc_methods.dge_deseq2.read as rd  # noqa: PLC0415

    null_table = pq.read_table(RECOMPUTATION_DIR / anchor["null_fixture"], columns=["log2FoldChange"])
    null_vec = tuple(float(v) for v in null_table.column("log2FoldChange").to_pylist())
    one_row = pa.table({k: pa.array([v]) for k, v in anchor["raw_gene_row"].items()})

    with (
        mock.patch.object(rd, "_load_manifest", lambda mid: {"s3_uri": "s3://frozen/anchor.parquet"}),
        mock.patch.object(rd, "_get_s3fs", lambda: None),
        mock.patch.object(rd, "_allgene_log2fc_null", lambda mid, column="log2FoldChange": tuple(null_vec)),
        mock.patch("pyarrow.parquet.read_table", lambda *a, **k: one_row),
    ):
        return rd.read_dge_gene_row(anchor["target"], anchor["manifest_id"], return_field_map=True)


def test_tumor_rna_vs_adjacent_rederives_from_raw_substrate_and_matches_golden():
    """EPCAM/COADREAD raw DESeq2 gene row + all-gene null -> read_dge_gene_row must reproduce BOTH the
    analysis-methods anchor's pinned numbers AND the tumor-presence golden's tumor-rna-vs-adjacent card
    summary — two independent captures agreeing at full float64 precision."""
    anchor = json.loads(_RVA_ANCHOR.read_text())
    summary = _rederive_rna_vs_adjacent(anchor)

    # Anchor-side reconciliation (analysis-methods' own promise, independently re-run here).
    assert summary["expression_call_class"] == anchor["expected_expression_call_class"]
    assert summary["log2_fc"] == anchor["expected_log2_fc"]
    assert summary["allgene_percentile"] == anchor["expected_allgene_percentile"]

    # THE BRIDGE: the skill's own committed golden must carry the identical numbers, independently.
    # Only fields read_dge_gene_row emits are bridged (gtex_* come from a separate reader).
    golden = _golden_card("tumor-rna-vs-adjacent")
    assert golden["log2_fc"] == summary["log2_fc"]
    assert golden["q_value"] == summary["q_value"]
    assert golden["n_tumor"] == summary["n_tumor"]
    assert golden["n_adjacent"] == summary["n_adjacent"]
    assert golden["base_mean"] == summary["base_mean"]
    assert golden["is_significant_provider_call"] == summary["is_significant_provider_call"]
    assert golden["is_actionable_provider_call"] == summary["is_actionable_provider_call"]
    assert golden["is_upregulated_provider_call"] == summary["is_upregulated_provider_call"]
    assert golden["expression_call_class"] == summary["expression_call_class"]
    assert golden["allgene_percentile"] == summary["allgene_percentile"]
    assert golden["allgene_percentile_class"] == summary["allgene_percentile_class"]
    assert golden["allgene_percentile_context"] == summary["allgene_percentile_context"]


def test_tumor_rna_vs_adjacent_teeth_flipping_significance_breaks_the_golden_match():
    """Teeth: force the gene non-significant and the re-derived class must NOT match the golden's real
    call — proving the bridge is a live function of the frozen row, not a self-echo."""
    anchor = json.loads(_RVA_ANCHOR.read_text())
    mutated = dict(anchor)
    mutated["raw_gene_row"] = dict(anchor["raw_gene_row"])
    mutated["raw_gene_row"]["padj"] = 0.9
    summary = _rederive_rna_vs_adjacent(mutated)
    golden = _golden_card("tumor-rna-vs-adjacent")
    assert summary["expression_call_class"] == "not_informative"
    # EPCAM's real golden call is not_informative already, so also assert a numeric field moved off it
    # via a second, direction-bearing perturbation (a strong up log2FC).
    mutated["raw_gene_row"]["padj"] = 1e-30
    mutated["raw_gene_row"]["log2FoldChange"] = 5.0
    summary2 = _rederive_rna_vs_adjacent(mutated)
    assert summary2["expression_call_class"] == "strong_upregulation"
    assert summary2["expression_call_class"] != golden["expression_call_class"]


# ── tumor-elevation-breadth (two-layer) ──────────────────────────────────────────────────────────

# Golden carries a SUBSET of each reader's emitted fields; bridge only those the golden projects.
_TEB_PROTEIN_GOLDEN_FIELDS = (
    "tumor_elevation_breadth_class",
    "n_cohorts_tested",
    "n_cohorts_elevated",
    "n_cohorts_sig_up_effect_negligible",
    "fraction_elevated",
    "median_effect_across_elevated",
    "most_elevated_cohorts",
    "cohorts_tested",
)


def _rederive_teb_protein(anchor: dict) -> dict:
    import onc_methods.cptac_protein_deg.read as cp  # noqa: PLC0415

    cohort_rows = pq.read_table(RECOMPUTATION_DIR / anchor["cptac_cohort_rows_fixture"]).to_pylist()
    with mock.patch.object(cp, "read_all_cohorts", lambda t: [dict(r) for r in cohort_rows]):
        return cp.read_tumor_elevation_breadth("EPCAM")


def _rederive_teb_rna(anchor: dict) -> dict:
    import onc_methods.dge_deseq2.derive_pancan_stack as ps  # noqa: PLC0415
    import pyarrow.fs as pafs  # noqa: PLC0415

    rna_rows = pq.read_table(RECOMPUTATION_DIR / anchor["rna_stack_rows_fixture"]).to_pylist()
    frozen = pa.Table.from_pylist(rna_rows)
    ps.read_rna_tumor_elevation_breadth.cache_clear()
    with (
        mock.patch.object(pafs, "S3FileSystem", lambda *a, **k: None),
        mock.patch("pyarrow.parquet.read_table", lambda *a, **k: frozen),
    ):
        try:
            return ps.read_rna_tumor_elevation_breadth("EPCAM")
        finally:
            ps.read_rna_tumor_elevation_breadth.cache_clear()


def test_tumor_elevation_breadth_protein_layer_rederives_and_matches_golden():
    """EPCAM per-cohort CPTAC rows -> read_tumor_elevation_breadth must reproduce BOTH the anchor's
    pinned protein roll-up AND the golden's tumor-elevation-breadth protein fields (the primary layer
    the product->reader binding names)."""
    anchor = json.loads(_TEB_ANCHOR.read_text())
    summary = _rederive_teb_protein(anchor)
    golden = _golden_card("tumor-elevation-breadth")
    for f in _TEB_PROTEIN_GOLDEN_FIELDS:
        assert summary[f] == anchor["expected_protein"][f], f"anchor drift on protein {f}"
        assert golden[f] == summary[f], f"golden bridge failed on protein {f}"


def test_tumor_elevation_breadth_rna_layer_stable_fields_rederive_and_match_golden():
    """RNA layer: bridge the vintage-STABLE fields (breadth class, elevated numerator, median, and the
    elevated indication set). The denominator drift is pinned separately below."""
    anchor = json.loads(_TEB_ANCHOR.read_text())
    summary = _rederive_teb_rna(anchor)
    golden = _golden_card("tumor-elevation-breadth")

    # anchor reconciliation (re-run reader == committed anchor)
    assert summary["rna_tumor_elevation_breadth_class"] == anchor["expected_rna"]["rna_tumor_elevation_breadth_class"]
    assert summary["n_indications_elevated"] == anchor["expected_rna"]["n_indications_elevated"]

    # golden bridge on the stable fields
    assert golden["rna_tumor_elevation_breadth_class"] == summary["rna_tumor_elevation_breadth_class"]
    assert golden["rna_n_indications_elevated"] == summary["n_indications_elevated"]
    assert golden["rna_median_max_log2fc_across_elevated"] == summary["median_max_log2fc_across_elevated"]
    assert golden["rna_most_elevated_indications"] == summary["most_elevated_indications"]


def test_elevation_breadth_rna_drift_is_denominator_only_and_non_elevated():
    """Honest record of the RNA-layer product-vintage drift: the current pancan product tests one MORE
    indication than the golden's vintage, but the extra indication is NON-elevated — the elevated
    numerator and set are byte-identical, so only the denominator (n_indications_tested) and its
    dependent fraction moved. Pins the drift as understood, not hidden."""
    anchor = json.loads(_TEB_ANCHOR.read_text())
    summary = _rederive_teb_rna(anchor)
    golden = _golden_card("tumor-elevation-breadth")

    # numerator + elevated set identical
    assert summary["n_indications_elevated"] == golden["rna_n_indications_elevated"] == 10
    golden_elevated = {x["indication"] for x in golden["rna_most_elevated_indications"]}
    current_elevated = {x["indication"] for x in summary["most_elevated_indications"]}
    assert golden_elevated == current_elevated, "elevated indication SET drifted — not a benign denominator advance"

    # denominator grew by adding non-elevated indication(s) only
    assert summary["n_indications_tested"] >= golden["rna_n_indications_tested"]
    added = summary["n_indications_tested"] - golden["rna_n_indications_tested"]
    assert added >= 1, "expected the documented >=1 non-elevated indication advance (26 -> 27)"
    # the golden's fraction is the stale 10/26; the current reader's is 10/current_tested — both consistent
    assert abs(golden["rna_fraction_elevated"] - 10 / golden["rna_n_indications_tested"]) < 1e-12
    assert abs(summary["fraction_elevated"] - 10 / summary["n_indications_tested"]) < 1e-12
