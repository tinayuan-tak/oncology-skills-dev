"""Scorecard L1 accuracy batch D (#2046) — EPCAM/COADREAD derived-statistics quartet re-derivation.

FILE-DISJOINT sibling of test_scorecard_l1_accuracy_rederivation.py (#1988, A0c exemplar) and
_batch_a.py (#2043) / _batch_b.py (#2044) / _batch_c.py (#2045) — do NOT edit those; this covers the
NON-verdict-bearing derived-statistics quartet, enrolling four more cards into the accuracy ledger
(7 -> 11 of 17). Same method: it reuses analysis-methods' T3 recomputation anchors (plan foamy-bird
Stage I) and BRIDGES them one step further than analysis-methods' own tests — re-deriving the number
through the REAL reader offline AND asserting it also equals the tumor-presence golden's card summary
for EPCAM/COADREAD. Two repos' independent captures meeting at the same value is the reconciliation.

Covers four cards:
  - cellline-rna-protein-concordance  (read_rna_protein_concordance, 26q1 pin)
  - rna-protein-concordance-tumor     (read_tumor_rna_protein_concordance)
  - expression-purity-confound        (read_expression_purity_confound)
  - hpa-pathology-cancer-ihc          (read_target_summary; read-path lookup)

## THE #1510 ADJUDICATION (settled GREEN)

#1510 flagged rna_proxy_classified_on as a corpus-tell that shipped rna_as_biomarker classes MIGHT
have been computed on Pearson, not the intended Spearman. Mechanized here: the re-derivation through
the REAL reader reproduces rna_as_biomarker + rna_proxy_classified_on='spearman' byte-exact against
the golden, and the reader provably classifies on the Spearman value (methods read.py G10). The AM
half's KRAS cell-line anchor is the decisive witness (Pearson would say partial_proxy, Spearman says
poor_proxy, reader emits poor_proxy). So the #1510 concern is resolved GREEN on this read path — the
class is NOT a Pearson artifact.

## TWO HONESTLY-RECORDED DRIFTS (verdict-inert, class-invariant; NOT silently normalized)

1. CONCORDANCE ci95_low/high (both grains): the committed golden's Fisher-z CI bounds were computed
   with the PEARSON SE coefficient (1.0); the current reader uses the SPEARMAN coefficient (1.06,
   ~6% wider — the F3 fix). So the golden's ci95 predates F3 and the re-derived band is strictly
   WIDER on both bounds. rna_proxy_class_boundary_fragile and rna_as_biomarker are unchanged, so this
   is verdict-inert. Cross-linked to #1510 (the same G10/F3 work that fixed the Spearman
   classification also widened the CI). Pinned, not normalized.
2. PURITY correlation coefficients: expression_purity_pearson_r / _spearman_r / _pearson_p drift at
   the ~4th decimal from the committed golden (the recount3 tumor-expression snapshot advanced
   slightly since the golden was built); purity_confound_class, n_paired_samples, n_expr_samples and
   median_purity are byte-exact, so the class is stable. Pinned as bounded + class-invariant.

hpa-pathology-cancer-ihc reconciles BYTE-EXACT (the reader is a lookup; see the AM boundary note).

OFFLINE — reads only committed fixtures (this repo's golden + analysis-methods' committed anchors),
no S3, no creds. Skips (not fails) if the analysis-methods sibling checkout lacks the batch-D anchors
(e.g. the CI-pinned sibling SHA predates them) — a partial checkout degrades honestly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.paths import analysis_methods_root  # noqa: E402

AM_ROOT = analysis_methods_root()
RECOMPUTATION_DIR = AM_ROOT / "tests" / "calibration" / "recomputation"
ANCHOR_DIR = RECOMPUTATION_DIR / "anchors"
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"

CELLLINE_ANCHOR = ANCHOR_DIR / "epcam_26q1.cellline_rna_protein_concordance.json"
TUMOR_ANCHOR = ANCHOR_DIR / "epcam_coadread.tumor_rna_protein_concordance.json"
PURITY_ANCHOR = ANCHOR_DIR / "epcam_coadread.expression_purity_confound.json"
IHC_ANCHOR = ANCHOR_DIR / "epcam_coadread.hpa_pathology_cancer_ihc.json"

pytestmark = pytest.mark.skipif(
    not (CELLLINE_ANCHOR.exists() and TUMOR_ANCHOR.exists() and PURITY_ANCHOR.exists() and IHC_ANCHOR.exists()),
    reason=f"analysis-methods batch-D anchors not found under {ANCHOR_DIR} (sibling checkout absent/predates #2046)",
)


def _golden_card(card_id: str) -> dict:
    d = json.loads(GOLDEN.read_text())
    for c in d["cards"]:
        if c["card_id"] == card_id:
            return c["summary"]
    raise AssertionError(f"golden fixture carries no card {card_id!r}")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _rd_module():
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    import methods.depmap_rna_protein_concordance.read as rd  # noqa: PLC0415

    return rd


# ── cell-line concordance ──────────────────────────────────────────────────────────────────────

_CELLLINE_STABLE = (
    "rna_protein_r",
    "rna_protein_spearman",
    "n_paired_models",
    "protein_detection_fraction",
    "rna_expressed_fraction",
    "rna_high_protein_low_fraction",
    "rna_as_biomarker",
    "rna_proxy_classified_on",
    "rna_proxy_class_boundary_fragile",
)


def _rederive_cellline():
    rd = _rd_module()
    anchor = _load(CELLLINE_ANCHOR)
    rna_tbl = pq.read_table(RECOMPUTATION_DIR / anchor["rna_vector_fixture"])
    prot_tbl = pq.read_table(RECOMPUTATION_DIR / anchor["protein_vector_fixture"])
    rna_by_model = dict(zip(rna_tbl.column("model_id").to_pylist(), rna_tbl.column("rna_log2tpm").to_pylist()))
    prot_by_model = dict(
        zip(prot_tbl.column("model_id").to_pylist(), prot_tbl.column("protein_log2abundance").to_pylist())
    )
    with mock.patch.object(
        rd, "_paired_rna_protein", lambda t, release_pin="26q3": (rna_by_model, prot_by_model, None)
    ):
        return rd.read_rna_protein_concordance(anchor["target"], release_pin=anchor["release_pin"]), anchor


def test_cellline_concordance_rederives_and_matches_anchor_and_golden():
    summary, anchor = _rederive_cellline()
    # anchor-side reconciliation (two repos' independent captures agree)
    for k, v in anchor["expected"].items():
        assert summary[k] == v, f"cell-line anchor mismatch on {k}: {summary[k]!r} != {v!r}"
    # THE BRIDGE: the committed golden carries the identical stable numbers, independently.
    golden = _golden_card("cellline-rna-protein-concordance")
    for f in _CELLLINE_STABLE:
        assert golden[f] == summary[f], f"golden vs re-derived mismatch on {f}: {golden[f]!r} != {summary[f]!r}"
    # #1510: the class provably tracks Spearman.
    assert summary["rna_proxy_classified_on"] == "spearman"


def test_cellline_ci95_drift_is_the_f3_prefix_wider_band_and_class_invariant():
    """The golden's ci95 was built with the Pearson SE coefficient; the reader now uses the Spearman
    coefficient (F3, ~6% wider). The re-derived band is strictly WIDER on both bounds, and the
    class + boundary-fragility flag are unchanged — a verdict-inert, honestly-pinned drift (#1510)."""
    summary, _ = _rederive_cellline()
    golden = _golden_card("cellline-rna-protein-concordance")
    assert summary["rna_protein_r_ci95_low"] < golden["rna_protein_r_ci95_low"], "F3 band should be wider (lower low)"
    assert summary["rna_protein_r_ci95_high"] > golden["rna_protein_r_ci95_high"], (
        "F3 band should be wider (higher high)"
    )
    assert summary["rna_proxy_class_boundary_fragile"] == golden["rna_proxy_class_boundary_fragile"]
    assert summary["rna_as_biomarker"] == golden["rna_as_biomarker"]


# ── tumor concordance ────────────────────────────────────────────────────────────────────────────

_TUMOR_STABLE = (
    "cptac_cohort",
    "substrate",
    "rna_protein_r",
    "rna_protein_spearman",
    "n_paired_tumors",
    "rna_as_biomarker",
    "rna_proxy_classified_on",
    "rna_proxy_class_boundary_fragile",
)


def _rederive_tumor():
    rd = _rd_module()
    anchor = _load(TUMOR_ANCHOR)
    rows = pd.read_parquet(RECOMPUTATION_DIR / anchor["matched_rows_fixture"])
    frames = {c: rows[rows["cohort"] == c].drop(columns=["cohort"]).reset_index(drop=True) for c in anchor["cohorts"]}

    def _fake(cohort, target=None):
        df = frames.get(cohort)
        return (
            df
            if df is not None
            else pd.DataFrame(columns=["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"])
        )

    with mock.patch.object(rd, "_read_matched_cohort", _fake):
        return rd.read_tumor_rna_protein_concordance(anchor["target"], anchor["indication"]), anchor


def test_tumor_concordance_rederives_and_matches_anchor_and_golden():
    summary, anchor = _rederive_tumor()
    for k, v in anchor["expected"].items():
        assert summary[k] == v, f"tumor anchor mismatch on {k}: {summary[k]!r} != {v!r}"
    golden = _golden_card("rna-protein-concordance-tumor")
    for f in _TUMOR_STABLE:
        assert golden[f] == summary[f], f"golden vs re-derived mismatch on {f}: {golden[f]!r} != {summary[f]!r}"
    assert summary["rna_proxy_classified_on"] == "spearman"


def test_tumor_ci95_drift_is_the_f3_prefix_wider_band_and_class_invariant():
    summary, _ = _rederive_tumor()
    golden = _golden_card("rna-protein-concordance-tumor")
    assert summary["rna_protein_r_ci95_low"] < golden["rna_protein_r_ci95_low"], "F3 band should be wider (lower low)"
    assert summary["rna_protein_r_ci95_high"] > golden["rna_protein_r_ci95_high"], (
        "F3 band should be wider (higher high)"
    )
    assert summary["rna_proxy_class_boundary_fragile"] == golden["rna_proxy_class_boundary_fragile"]
    assert summary["rna_as_biomarker"] == golden["rna_as_biomarker"]


# ── expression-purity-confound ─────────────────────────────────────────────────────────────────

_PURITY_STABLE = ("purity_confound_class", "n_paired_samples", "n_expr_samples", "median_purity")
_PURITY_DRIFT = ("expression_purity_pearson_r", "expression_purity_spearman_r", "expression_purity_pearson_p")
_PURITY_DRIFT_TOL = 0.002


def _rederive_purity():
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    import methods.expression_purity_confound.read as epc  # noqa: PLC0415
    import methods.tcga_gtex_expression_distribution.read as exprmod  # noqa: PLC0415

    anchor = _load(PURITY_ANCHOR)
    expr = pd.read_parquet(RECOMPUTATION_DIR / anchor["expr_fixture"])
    purity_tbl = pd.read_parquet(RECOMPUTATION_DIR / anchor["purity_fixture"])
    purity_by_case = dict(zip(purity_tbl["case"].tolist(), purity_tbl["purity"].tolist()))
    with (
        mock.patch.object(epc, "ensure_aws_profile", lambda: None),
        mock.patch.object(exprmod, "read_tumor_samples_with_case", lambda t, i: expr),
        mock.patch.object(epc, "_load_purity_by_case", lambda: purity_by_case),
    ):
        return epc.read_expression_purity_confound(anchor["target"], anchor["indication"]), anchor


def test_purity_confound_rederives_and_matches_anchor_and_golden():
    summary, anchor = _rederive_purity()
    for k, v in anchor["expected"].items():
        assert summary[k] == v, f"purity anchor mismatch on {k}: {summary[k]!r} != {v!r}"
    golden = _golden_card("expression-purity-confound")
    # class + counts + median are byte-exact to the golden
    for f in _PURITY_STABLE:
        assert golden[f] == summary[f], f"golden vs re-derived mismatch on {f}: {golden[f]!r} != {summary[f]!r}"


def test_purity_correlation_drift_is_bounded_and_class_invariant():
    """The correlation coefficients drift at the ~4th decimal from the golden (recount3 snapshot
    advanced slightly since the golden was built); the drift is bounded and does not move
    purity_confound_class — an honestly-pinned, verdict-inert drift."""
    summary, _ = _rederive_purity()
    golden = _golden_card("expression-purity-confound")
    for f in _PURITY_DRIFT:
        assert abs(float(summary[f]) - float(golden[f])) < _PURITY_DRIFT_TOL, (
            f"{f} drift {summary[f]!r} vs golden {golden[f]!r} exceeds {_PURITY_DRIFT_TOL} — investigate, not a snapshot nudge"
        )
    assert summary["purity_confound_class"] == golden["purity_confound_class"]


# ── hpa-pathology-cancer-ihc (byte-exact lookup) ─────────────────────────────────────────────────

_IHC_FIELDS = (
    "protein_presence_class",
    "fraction_detected",
    "fraction_moderate_strong",
    "staining_score",
    "n_high",
    "n_medium",
    "n_low",
    "n_not_detected",
    "n_patients_total",
    "prognostic_type",
    "prognostic_is_significant",
    "prognostic_p_value",
    "hpa_cancer_type",
)


def _rederive_ihc():
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    import methods.hpa_pathology_cancer_ihc.read as hp  # noqa: PLC0415

    anchor = _load(IHC_ANCHOR)
    tbl = pq.read_table(RECOMPUTATION_DIR / anchor["rows_fixture"])

    def _replay(_uri, filesystem=None, columns=None, filters=None):  # noqa: ARG001
        t = tbl
        for col, _op, val in filters or []:
            t = t.filter(pc.equal(t[col], val))
        if columns:
            t = t.select([c for c in columns if c in t.column_names])
        return t

    with mock.patch.object(hp, "_get_s3fs", lambda: None), mock.patch("pyarrow.parquet.read_table", _replay):
        return hp.read_target_summary(anchor["target"], anchor["indication"]), anchor, tbl


def test_hpa_ihc_rederives_and_matches_anchor_and_golden_byte_exact():
    summary, anchor, _ = _rederive_ihc()
    for k, v in anchor["expected"].items():
        assert summary.get(k) == v, f"HPA IHC anchor mismatch on {k}: {summary.get(k)!r} != {v!r}"
    golden = _golden_card("hpa-pathology-cancer-ihc")
    for f in _IHC_FIELDS:
        assert golden[f] == summary.get(f), f"golden vs re-derived mismatch on {f}: {golden[f]!r} != {summary.get(f)!r}"


def test_hpa_ihc_teeth_dropping_the_matched_row_breaks_the_golden_match():
    """Teeth: dropping the resolved HPA cancer-type row collapses the read to data_unavailable, no
    longer matching the golden's ihc_detected_high — proving the selection is a live function of the
    substrate, not a self-echo."""
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    import methods.hpa_pathology_cancer_ihc.read as hp  # noqa: PLC0415

    _, anchor, tbl = _rederive_ihc()
    kept = tbl.filter(pc.not_equal(tbl["cancer_type"], anchor["hpa_cancer_type"]))
    golden = _golden_card("hpa-pathology-cancer-ihc")

    def _replay(_uri, filesystem=None, columns=None, filters=None):  # noqa: ARG001
        t = kept
        for col, _op, val in filters or []:
            t = t.filter(pc.equal(t[col], val))
        if columns:
            t = t.select([c for c in columns if c in t.column_names])
        return t

    with mock.patch.object(hp, "_get_s3fs", lambda: None), mock.patch("pyarrow.parquet.read_table", _replay):
        summary = hp.read_target_summary(anchor["target"], anchor["indication"])
    assert summary["protein_presence_class"] == "data_unavailable"
    assert summary["protein_presence_class"] != golden["protein_presence_class"]
