"""Scorecard L1 accuracy batch C (#2045) — EPCAM/COADREAD CPTAC-protein re-derivation from raw substrate.

FILE-DISJOINT sibling of test_scorecard_l1_accuracy_rederivation.py (#1988, A0c exemplar),
test_scorecard_l1_accuracy_rederivation_batch_a.py (#2043) and _batch_b.py (#2044) — do NOT edit those;
this one covers the LAST verdict-bearing card without an accuracy anchor rather than extending them.
Same method: it reuses analysis-methods' T3 recomputation anchor (plan foamy-bird Stage I) and BRIDGES
it one step further than analysis-methods' own test does — asserting the re-derived number ALSO equals
what tumor-presence's own committed golden (`tests/fixtures/epcam_coadread_decision.json`) emits for the
tumor-protein-abundance-cptac card, for the same target/indication. Two repos' independent captures
meeting at the same float64 value is the reconciliation.

Covers the verdict-bearing card:
  - tumor-protein-abundance-cptac  (per-indication CPTAC protein tumor-vs-normal ->
                                    methods.cptac_protein_deg.read.read_target_summary)

WITHIN-COHORT SEMANTICS (#1512/#1664): CPTAC TMT effect sizes are pooled-reference-relative RATIOS.
EPCAM/COADREAD is a LEAF indication -> a SINGLE CPTAC cohort (COAD), so read_target_summary's
representative-cohort pick is over one candidate and NO cross-cohort aggregation of non-comparable
ratios occurs on this verdict-bearing path (that is confined to the umbrella / indication-free paths,
where #1664 F1 ranks on the comparable |Cohen's d| axis). The all-gene percentile is a within-cohort
rank. HONEST FINDING: the flagship re-derivation reproduces the golden byte-exact -> GREEN.

The analysis-methods anchor set spans 4 targets (EPCAM/ERBB2/KRAS/TACSTD2, per
capture_cptac_protein_abundance_anchor.py); this file bridges the EPCAM/COADREAD flagship specifically,
because it is the only pair with a committed tumor-presence decision.json golden to bridge against
(mirrors the #1988/#2043 precedent).

OFFLINE — reads only committed fixtures (this repo's golden + analysis-methods' committed anchor), no
S3, no creds. Skips (not fails) if the analysis-methods sibling checkout is absent, so a partial
checkout degrades honestly instead of red on an unrelated absence.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

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
ANCHOR = ANCHOR_DIR / "epcam_coad.cptac_protein_abundance.json"
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"

pytestmark = pytest.mark.skipif(
    not ANCHOR.exists(),
    reason=f"analysis-methods CPTAC-protein anchor not found at {ANCHOR} (sibling checkout absent/partial)",
)

# The golden card summary keys re-derived through the real reader (the reader also emits
# protein_contrast_estimable, which the card projection drops — so we bridge over the golden's keys).
_BRIDGED_FIELDS = (
    "cohort",
    "protein_expression_class",
    "protein_effect_size",
    "allgene_percentile",
    "allgene_percentile_class",
    "allgene_percentile_context",
    "protein_bh_q_value",
    "protein_p_value",
    "protein_median_log2_tumor",
    "protein_median_log2_normal",
    "n_tumor_samples",
    "n_normal_samples",
    "protein_effect_size_se",
    "protein_effect_standardized_t",
    "protein_effect_cohens_d",
    "protein_effect_standardized_class",
    "protein_effect_standardized_method",
)


def _golden_card(card_id: str) -> dict:
    d = json.loads(GOLDEN.read_text())
    for c in d["cards"]:
        if c["card_id"] == card_id:
            return c["summary"]
    raise AssertionError(f"golden fixture carries no card {card_id!r}")


def _load_cptac_module():
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    import methods.cptac_protein_deg.read as mod  # noqa: PLC0415

    return mod


def _load_anchor() -> dict:
    return json.loads(ANCHOR.read_text())


def _rederive_target_summary(cp, target_rows, matched_cohort, null_effects, target, indication):
    """Re-derive read_target_summary(target, indication) OFFLINE by reconstructing the (df,
    cohort_gene_idx, gene_idx, cohort_effect_null) tuple _load_indexed returns — from the frozen target
    rows + matched-cohort all-gene null — and monkeypatching ONLY that S3-load seam. Mirrors _load_indexed's
    own indexing exactly. IDENTICAL logic to the analysis-methods capture/test helper."""
    from unittest import mock

    import pandas as pd

    df = pd.DataFrame(target_rows)
    cohort_gene_idx: dict = {}
    gene_idx: dict = {}
    cohort_col = df["cohort"].values
    gene_col = df["gene_symbol"].values
    for idx in range(len(df)):
        cohort = str(cohort_col[idx]).strip().upper()
        gene = str(gene_col[idx]).strip().upper()
        if not cohort or not gene:
            continue
        cohort_gene_idx[(cohort, gene)] = idx
        gene_idx.setdefault(gene, []).append(idx)
    cohort_effect_null = {matched_cohort.strip().upper(): list(null_effects)}
    with mock.patch.object(cp, "_load_indexed", lambda: (df, cohort_gene_idx, gene_idx, cohort_effect_null)):
        return cp.read_target_summary(target, indication)


def _rows(anchor: dict) -> list[dict]:
    return pq.read_table(RECOMPUTATION_DIR / anchor["target_rows_fixture"]).to_pylist()


def _null(anchor: dict) -> list:
    return (
        pq.read_table(RECOMPUTATION_DIR / anchor["allgene_effect_null_fixture"])
        .column("protein_effect_size")
        .to_pylist()
    )


def test_tumor_protein_abundance_cptac_rederives_from_raw_substrate_and_matches_golden():
    """EPCAM/COADREAD raw per-cohort CPTAC df rows + matched-cohort all-gene null -> read_target_summary
    must reproduce BOTH the analysis-methods anchor's pinned numbers AND the tumor-presence golden's
    tumor-protein-abundance-cptac card summary — two independent captures agreeing at full float64
    precision."""
    anchor = _load_anchor()
    cp = _load_cptac_module()
    rows, null = _rows(anchor), _null(anchor)
    assert len(rows) >= 1 and len(null) >= 50, f"raw substrate too small (rows={len(rows)}, null={len(null)})"

    summary = _rederive_target_summary(cp, rows, anchor["matched_cohort"], null, anchor["target"], anchor["indication"])

    # Anchor-side reconciliation (analysis-methods' own promise).
    for f in ("cohort", "protein_expression_class", "protein_effect_size", "allgene_percentile"):
        assert summary[f] == anchor["expected"][f], f"anchor mismatch on {f}"

    # THE BRIDGE: the skill's own committed golden must carry the identical numbers, independently.
    golden = _golden_card("tumor-protein-abundance-cptac")
    for f in _BRIDGED_FIELDS:
        assert golden[f] == summary[f], f"golden vs re-derived mismatch on {f}: {golden[f]!r} != {summary[f]!r}"


def test_teeth_unestimable_effect_breaks_the_golden_match():
    """Teeth: forcing the matched-cohort row's protein_effect_size to +Inf (MSstatsTMT's unestimable
    sentinel) drives read_target_summary down the _unestimable_reason path — the re-derived class
    collapses to data_unavailable and no longer matches the golden's not_significant. Proves the bridge
    is a live function of the frozen substrate, not a self-echo."""
    anchor = _load_anchor()
    cp = _load_cptac_module()
    rows, null = _rows(anchor), _null(anchor)
    golden = _golden_card("tumor-protein-abundance-cptac")
    mc = anchor["matched_cohort"].strip().upper()
    for r in rows:
        if str(r["cohort"]).strip().upper() == mc:
            r["protein_effect_size"] = math.inf

    summary = _rederive_target_summary(cp, rows, anchor["matched_cohort"], null, anchor["target"], anchor["indication"])
    assert summary["protein_expression_class"] == "data_unavailable"
    assert summary["protein_expression_class"] != golden["protein_expression_class"]
    assert summary["protein_effect_size"] != golden["protein_effect_size"]


def test_teeth_shifting_the_null_breaks_the_percentile_golden_match():
    """Teeth: shifting the matched cohort's all-gene effect null far above the target's effect moves the
    WITHIN-cohort allgene_percentile away from the golden's — proving the percentile is ranked live
    against the frozen null, not echoed."""
    anchor = _load_anchor()
    cp = _load_cptac_module()
    rows = _rows(anchor)
    null = [float(v) + 1000.0 for v in _null(anchor)]
    golden = _golden_card("tumor-protein-abundance-cptac")

    summary = _rederive_target_summary(cp, rows, anchor["matched_cohort"], null, anchor["target"], anchor["indication"])
    assert summary["allgene_percentile"] != golden["allgene_percentile"]
