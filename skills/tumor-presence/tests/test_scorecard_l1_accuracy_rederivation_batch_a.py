"""Scorecard L1 accuracy batch A (#2043) — EPCAM/COADREAD re-derivation from raw substrate.

FILE-DISJOINT sibling of test_scorecard_l1_accuracy_rederivation.py (#1988, A0c exemplar) — do NOT
edit that file; this one covers the NEXT two verdict-bearing cards rather than extending the first.
Same method as #1988: it reuses analysis-methods' T3 recomputation anchors (plan foamy-bird Stage I)
and BRIDGES them one step further than analysis-methods' own tests do — asserting the re-derived
number ALSO equals what tumor-presence's own committed golden
(`tests/fixtures/epcam_coadread_decision.json`) emits for the same card, for the same
target/indication. Two repos' independent captures meeting at the same float64 value is the
reconciliation; either repo drifting independently would show up here as a real red, not a
self-echo.

Covers the two verdict-bearing cards batch A adds a landed T3 anchor for:
  - tumor-rna-distribution       (recount3 TCGA per-sample tumor log2(TPM+1) vector ->
                                  read_tumor_expression_distribution)
  - cellline-protein-abundance   (Gygi TMT per-cell-line log2-abundance column ->
                                  compute_summary)

The analysis-methods anchor sets for both cards span >1 target (10 tumor_rna_distribution pairs / 9
cellline_protein_abundance pairs, per capture_tumor_distribution_anchor.py /
capture_protein_abundance_anchor.py) — this file bridges the EPCAM/COADREAD flagship pair specifically,
because it is the only pair with a committed tumor-presence decision.json golden to bridge against
(mirrors the #1988 precedent, which is EPCAM-only for the same reason).

OFFLINE — reads only committed fixtures (this repo's golden + analysis-methods' committed anchors),
no S3, no creds. Skips (not fails) if the analysis-methods sibling checkout is absent, so a partial
checkout degrades honestly instead of red on an unrelated absence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

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

pytestmark = pytest.mark.skipif(
    not ANCHOR_DIR.exists(),
    reason=f"analysis-methods recomputation anchors not found at {ANCHOR_DIR} (sibling checkout absent/partial)",
)


def _golden_card(card_id: str) -> dict:
    d = json.loads(GOLDEN.read_text())
    for c in d["cards"]:
        if c["card_id"] == card_id:
            return c["summary"]
    raise AssertionError(f"golden fixture carries no card {card_id!r}")


# ── tumor-rna-distribution ───────────────────────────────────────────────────────────────────────


def _load_tumor_distribution_module():
    # NOTE: tcga_gtex_expression_distribution/read.py does a package-relative `from . import stats`,
    # so it must be imported as a real package member (not via spec_from_file_location, which the
    # #1988 exemplar can use because depmap_expression_distribution/cli.py has no relative imports).
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    import methods.tcga_gtex_expression_distribution.read as mod  # noqa: PLC0415

    return mod


def _load_tumor_distribution_anchor() -> dict:
    p = ANCHOR_DIR / "epcam_coadread.tumor_rna_distribution.json"
    if not p.exists():
        pytest.skip(f"no EPCAM tumor_rna_distribution anchor at {p}")
    return json.loads(p.read_text())


def _load_tumor_vector(anchor: dict) -> list[float]:
    table = pq.read_table(RECOMPUTATION_DIR / anchor["vectors_fixture"]).to_pydict()
    target, indication, cohort = anchor["target"], anchor["indication"], anchor["vectors_fixture_cohort"]
    out = []
    for t, i, c, val in zip(table["target"], table["indication"], table["cohort"], table["log2_tpm"], strict=True):
        if t == target and i == indication and c == cohort:
            out.append(float(val))
    return out


def test_tumor_rna_distribution_rederives_from_raw_substrate_and_matches_golden():
    """EPCAM/COADREAD raw per-sample tumor log2(TPM+1) vector -> read_tumor_expression_distribution
    must reproduce BOTH the analysis-methods anchor's pinned numbers AND the tumor-presence golden's
    tumor-rna-distribution card summary for EPCAM/COADREAD — two independent captures agreeing at
    full float64 precision."""
    anchor = _load_tumor_distribution_anchor()
    rd = _load_tumor_distribution_module()
    tumor = _load_tumor_vector(anchor)
    assert len(tumor) >= 50, f"raw tumor vector too small ({len(tumor)}) — fixture truncated?"

    with mock.patch.object(rd, "read_tumor_samples", lambda t, i: list(tumor)):
        summary = rd.read_tumor_expression_distribution(anchor["target"], anchor["indication"])

    # Anchor-side reconciliation (analysis-methods' own promise).
    assert summary["tumor_expression_class"] == anchor["expected_tumor_expression_class"]
    assert summary["median_log2tpm"] == anchor["expected_median_log2tpm"]
    assert summary["high_fraction"] == anchor["expected_high_fraction"]

    # THE BRIDGE: the skill's own committed golden must carry the identical numbers, independently.
    golden = _golden_card("tumor-rna-distribution")
    assert golden["n_tumor_samples"] == len(tumor) == anchor["n_tumor_samples"]
    assert golden["median_log2tpm"] == summary["median_log2tpm"]
    assert golden["p95_log2tpm"] == summary["p95_log2tpm"]
    assert golden["p99_log2tpm"] == summary["p99_log2tpm"]
    assert golden["min_log2tpm"] == summary["min_log2tpm"]
    assert golden["max_log2tpm"] == summary["max_log2tpm"]
    assert golden["coefficient_of_variation"] == summary["coefficient_of_variation"]
    assert golden["distribution_pattern"] == summary["distribution_pattern"]
    assert golden["detectable_fraction"] == summary["detectable_fraction"]
    assert golden["moderate_fraction"] == summary["moderate_fraction"]
    assert golden["high_fraction"] == summary["high_fraction"]
    assert golden["tumor_expression_class"] == summary["tumor_expression_class"]


def test_tumor_rna_distribution_teeth_mutated_input_breaks_the_golden_match():
    """Teeth: if the raw substrate is not what the golden was captured against, the bridge assertion
    above must NOT hold — proving it is a real reconciliation, not a vacuous self-comparison.
    Silencing every tumor sample is a legitimate different-input probe (EPCAM's real cohort is not
    all-zero)."""
    anchor = _load_tumor_distribution_anchor()
    rd = _load_tumor_distribution_module()
    tumor = _load_tumor_vector(anchor)
    golden = _golden_card("tumor-rna-distribution")

    mutated = [0.0 for _ in tumor]
    with mock.patch.object(rd, "read_tumor_samples", lambda t, i: list(mutated)):
        summary = rd.read_tumor_expression_distribution(anchor["target"], anchor["indication"])

    assert summary["detectable_fraction"] != golden["detectable_fraction"]
    assert summary["tumor_expression_class"] != golden["tumor_expression_class"]


# ── cellline-protein-abundance ───────────────────────────────────────────────────────────────────


def _load_protein_module():
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    from methods.depmap_protein_abundance import cli as pa_cli  # noqa: PLC0415

    return pa_cli


def _load_protein_anchor() -> dict:
    p = ANCHOR_DIR / "epcam_gygi.cellline_protein_abundance.json"
    if not p.exists():
        pytest.skip(f"no EPCAM cellline_protein_abundance anchor at {p}")
    return json.loads(p.read_text())


def _load_protein_vectors(anchor: dict) -> tuple[dict, dict, tuple]:
    table = pq.read_table(
        RECOMPUTATION_DIR / anchor["vector_fixture"], columns=["model_id", "log2_abundance", "lineage"]
    )
    model_ids = table.column("model_id").to_pylist()
    abund = table.column("log2_abundance").to_pylist()
    lineages = table.column("lineage").to_pylist()
    abundance_by_model = dict(zip(model_ids, abund))
    lineage_by_model = {m: lin for m, lin in zip(model_ids, lineages) if lin is not None}
    null_table = pq.read_table(RECOMPUTATION_DIR / anchor["null_fixture"], columns=["median_log2_abundance"])
    all_protein_medians = tuple(float(v) for v in null_table.column("median_log2_abundance").to_pylist())
    return abundance_by_model, lineage_by_model, all_protein_medians


def test_cellline_protein_abundance_rederives_from_raw_substrate_and_matches_golden():
    """EPCAM/Gygi raw per-cell-line log2-abundance column -> compute_summary must reproduce BOTH the
    analysis-methods anchor's pinned numbers AND the tumor-presence golden's cellline-protein-abundance
    card summary for EPCAM — two independent captures agreeing at full float64 precision."""
    anchor = _load_protein_anchor()
    pa_cli = _load_protein_module()
    abundance_by_model, lineage_by_model, all_protein_medians = _load_protein_vectors(anchor)
    assert len(abundance_by_model) >= 50, f"raw panel too small ({len(abundance_by_model)}) — fixture truncated?"

    summary = pa_cli.compute_summary(
        anchor["target"],
        abundance_by_model,
        lineage_by_model,
        n_panel=anchor["n_panel"],
        all_protein_medians=all_protein_medians,
    )

    # Anchor-side reconciliation (analysis-methods' own promise).
    assert summary["protein_expression_class"] == anchor["expected_class"]
    assert summary["fraction_detected"] == anchor["expected_fraction_detected"]
    assert summary["median_log2_abundance_panel"] == anchor["expected_median_log2_abundance_panel"]

    # THE BRIDGE: the skill's own committed golden must carry the identical numbers, independently.
    golden = _golden_card("cellline-protein-abundance")
    assert golden["n_cell_lines_evaluated"] == len(abundance_by_model) == anchor["n_cell_lines_evaluated"]
    assert golden["fraction_detected"] == summary["fraction_detected"]
    assert golden["median_log2_abundance_panel"] == summary["median_log2_abundance_panel"]
    assert golden["p5_log2_abundance_panel"] == summary["p5_log2_abundance_panel"]
    assert golden["p95_log2_abundance_panel"] == summary["p95_log2_abundance_panel"]
    assert golden["n_lineages_evaluated"] == summary["n_lineages_evaluated"]
    assert golden["n_lineage_restricted_lineages"] == summary["n_lineage_restricted_lineages"]
    assert golden["protein_expression_class"] == summary["protein_expression_class"]


def test_cellline_protein_abundance_teeth_mutated_input_breaks_the_golden_match():
    """Teeth: emptying the abundance column must NOT hold against the golden — proving the bridge
    above is a real function of the raw substrate, not a vacuous self-comparison."""
    anchor = _load_protein_anchor()
    pa_cli = _load_protein_module()
    _, lineage_by_model, all_protein_medians = _load_protein_vectors(anchor)
    golden = _golden_card("cellline-protein-abundance")

    summary = pa_cli.compute_summary(
        anchor["target"], None, lineage_by_model, n_panel=anchor["n_panel"], all_protein_medians=all_protein_medians
    )

    assert summary["fraction_detected"] != golden["fraction_detected"]
    assert summary["protein_expression_class"] != golden["protein_expression_class"]
