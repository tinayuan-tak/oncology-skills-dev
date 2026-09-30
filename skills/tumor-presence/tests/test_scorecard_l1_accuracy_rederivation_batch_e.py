"""Scorecard L1 accuracy batch E (#2047) — EPCAM/COADREAD normal-tissue comparator pair
re-derivation.

FILE-DISJOINT sibling of test_scorecard_l1_accuracy_rederivation.py (#1988, A0c exemplar) and
_batch_a.py (#2043) / _batch_b.py (#2044) / _batch_c.py (#2045) / _batch_d.py (#2046) — do NOT edit
those; this covers the two remaining NORMAL-TISSUE comparator cards, enrolling them into the
accuracy ledger (11 -> 13 of 17). CORRECTED DENOMINATOR NOTE: #2047's own title claims
"15/17->17/17, closes the roster" — that is stale. The committed shard
(scorecard/tumor-presence.json, as of batch D / PR #2068) carries 11 of 17 `cards_covered`; this
batch's two cards bring it to 13/17. The remaining 4 (tumor-rna-distribution-by-subtype,
cellline-rna-distribution-by-subtype, tumor-protein-distribution-by-subtype,
cellline-protein-abundance-procan) are NOT covered here and need a batch F.

Same method as batch A-D: reuses analysis-methods' T3 recomputation anchors (plan foamy-bird
Stage I) and BRIDGES them one step further — re-deriving the number through the REAL reader
offline AND asserting it also equals the tumor-presence golden's card summary for EPCAM/COADREAD.

Covers two cards:
  - sc-normal-celltype-expression  (methods.sc_normal_expression: read_target_summary + cli.build_summary)
  - normal-tissue-liability        (methods.hpa_normal_tissue_liability.cli.compute_summary — a
                                     pure lookup/classification over one frozen HPA row)

## DO-NOT-REFILE GUARDRAIL (sc-normal-celltype-expression)

The sc-normal Tier-1 product's cross-donor aggregate is an UNWEIGHTED cross-donor median BY DESIGN
(methods/sc_normal_expression/aggregate.py's module docstring: the DONOR is the biological
replicate, never a cell-weighted mean, which would let one large donor/dataset dominate). That
aggregation runs upstream in the data-catalog Tier-2->Tier-1 build, out of scope for this
re-derivation (which validates the READ + CLASSIFY path AM owns) — do not "fix" it to a weighted
form; it validates as-is.

## TWO HONESTLY-RECORDED DRIFTS (pinned, NOT silently normalized; cross-linked to #2061)

1. **sc-normal-celltype-expression schema growth** (bounded, class-invariant): the golden
   predates the #984 Tier-2 abundance/named-driver fields and the safety-essential cell-type panel
   expansion (stats.py #663/#664). `per_cell_type_top` rows now carry 2 extra keys
   (`median_abund`, `n_datasets_reliable`); `safety_essential_flags` gained 38 cell-type keys the
   golden's vintage panel did not recognize (renal-tubule conjunctive-pattern fixes + gut/pancreas
   additions), and LOST exactly one (`interneuron` — the regex tightened to a word-boundary match,
   deliberately dropping a substring false-positive class). Every key the golden DOES carry, other
   than the one named removal, still matches EXACTLY (verified below) — bounded, not a value
   change, and `sc_normal_expression_class` / `sc_normal_safety_essential_class` /
   `max_detection_cell_type` / `max_detection_fraction` are byte-stable.
2. **normal-tissue-liability essential_tissue_flag flip** (verdict-relevant field, but a
   documented-deliberate upstream change, not a regression introduced here): "intestine" was
   promoted to the canonical essential-tissue set (`gut`, 2026-09-18, predates the #1793/#1794
   safety-pin bump this issue was held on) — the golden predates that promotion.
   `essential_tissue_flag` moves `unknown` -> `present`, `essential_tissues_flagged` moves
   `[]` -> `["intestine"]`, `n_essential_tissues_with_expression` moves `0` -> `1`,
   `safety_tissue_flags` gains `essential_tissue`. Two more keys (`hpa_ihc_reliability`,
   `essential_tissue_low_reliability`) are wholly new (AM#745, antibody reliability) and absent
   from the golden entirely. `normal_tissue_breadth_class` / `hpa_tissue_distribution` /
   `hpa_tissue_specificity` / `n_specific_tissues` / `specific_tissues` / `method_version` are
   byte-stable. Both drifts are deferred to the full structural regen tracked in #2061 (behind the
   26Q3 migration + #1638) — NOT regenerated here, per this issue's explicit instruction.

OFFLINE — reads only committed fixtures (this repo's golden + analysis-methods' committed anchors),
no S3, no creds. Skips (not fails) if the analysis-methods sibling checkout lacks the batch-E
anchors (e.g. the CI-pinned sibling ref predates them) — a partial checkout degrades honestly.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent

from _skills_common.paths import analysis_methods_root

AM_ROOT = analysis_methods_root()
RECOMPUTATION_DIR = AM_ROOT / "tests" / "calibration" / "recomputation"
ANCHOR_DIR = RECOMPUTATION_DIR / "anchors"
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"

SC_ANCHOR = ANCHOR_DIR / "epcam_coadread.sc_normal_celltype.json"
HPA_ANCHOR = ANCHOR_DIR / "epcam_coadread.hpa_normal_tissue_liability.json"

pytestmark = pytest.mark.skipif(
    not (SC_ANCHOR.exists() and HPA_ANCHOR.exists()),
    reason=f"analysis-methods batch-E anchors not found under {ANCHOR_DIR} (sibling checkout absent/predates #2047)",
)


def _golden_card(card_id: str) -> dict:
    d = json.loads(GOLDEN.read_text())
    for c in d["cards"]:
        if c["card_id"] == card_id:
            return c["summary"]
    raise AssertionError(f"golden fixture carries no card {card_id!r}")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _sc_modules():
    import onc_methods.sc_normal_expression.cli as sc_cli  # noqa: PLC0415
    import onc_methods.sc_normal_expression.read as sc_rd  # noqa: PLC0415

    return sc_rd, sc_cli


def _hpa_module():
    import onc_methods.hpa_normal_tissue_liability.cli as hpa_cli  # noqa: PLC0415

    return hpa_cli


# ── sc-normal-celltype-expression ──────────────────────────────────────────────────────────────

_SC_STABLE = (
    "sc_normal_expression_class",
    "sc_normal_safety_essential_class",
    "max_detection_cell_type",
    "max_detection_fraction",
    "expressing_donor_fraction_max",
    "n_cell_types_above_20pct",
    "n_reliable_cell_types",
    "tissues_queried",
    "origin_tissues",
    "indication",
)


def _rederive_sc(anchor_path: Path = SC_ANCHOR):
    sc_rd, sc_cli = _sc_modules()
    anchor = _load(anchor_path)
    rows = pd.read_parquet(RECOMPUTATION_DIR / anchor["rows_fixture"])
    records = rows.to_dict("records")
    tissues = sc_rd.tissues_for_indication(anchor["indication"])
    tissues_loaded = anchor["tissues_loaded"]

    def _fake(_target, _tissues):
        df = pd.DataFrame(records, columns=list(sc_rd._PARQUET_COLS))  # noqa: SLF001
        df.attrs["tissues_requested"] = list(tissues)
        df.attrs["tissues_with_product"] = list(tissues)
        df.attrs["tissues_loaded"] = list(tissues_loaded)
        df.attrs["tissues_missing"] = [t for t in tissues if t not in set(tissues_loaded)]
        return df

    with mock.patch.object(sc_rd, "read_gene_celltype_rows", _fake):
        summary = sc_cli.build_summary(anchor["target"], anchor["indication"])
    return summary, anchor


def test_sc_normal_rederives_and_matches_anchor_and_golden():
    summary, anchor = _rederive_sc()
    for k, v in anchor["expected"].items():
        got = summary.get(k)
        if k == "per_cell_type_top":
            # Intra-tie row ORDER is not part of the anchor contract: rows tied on
            # median_detection_fraction (a whole block sits at exactly 1.0) come back in an
            # environment-dependent order — the capture host and CI disagree while every VALUE is
            # identical (first observed when the SK#2063 consolidation un-skipped this test's
            # anchor+test pair in one CI for the first time). Canonicalize both sides by cell_type
            # (unique within the top-N) so the assertion keeps full value teeth, order excluded —
            # mirroring the golden comparison below, which is already keyed by cell_type.
            # Producer-side deterministic tie-break is the real fix (follow-up filed).
            v = sorted(v, key=lambda r: r["cell_type"])
            got = sorted(got or [], key=lambda r: r["cell_type"])
        assert got == v, f"sc-normal anchor mismatch on {k}: {got!r} != {v!r}"
    golden = _golden_card("sc-normal-celltype-expression")
    for f in _SC_STABLE:
        assert golden[f] == summary[f], f"golden vs re-derived mismatch on {f}: {golden[f]!r} != {summary[f]!r}"
    assert summary["method_version"] == golden["method_version"]


def test_sc_normal_schema_growth_is_additive_and_class_invariant():
    """Drift 1 (pinned, cross-linked #2061): the golden predates the #984 abundance/named-driver
    fields and the safety-essential cell-type panel expansion (stats.py #663/#664: renal-tubule
    conjunctive-pattern fixes + gut/pancreas additions). The panel grew by 38 cell types (measured
    2026-09-29) — every ADDED key is additive-only (no value change on keys golden already carried,
    checked below). One key was DELIBERATELY REMOVED alongside the growth: `interneuron` — the
    safety-essential regex tightened from a bare substring match to a word-boundary pattern (stats.py
    docstring: "non-neuronal cell" / "neuronal-restricted precursor" were false-positive substring
    hits on "neuron"), and "interneuron" no longer satisfies the boundary-safe pattern. This is a
    single, named, bounded narrowing amid a 38-item widening — not a broken invariant — so it is
    pinned explicitly rather than asserted as a strict subset."""
    summary, _anchor = _rederive_sc()
    golden = _golden_card("sc-normal-celltype-expression")

    g_flags = golden["safety_essential_flags"]
    s_flags = summary["safety_essential_flags"]
    _KNOWN_REMOVED = {"interneuron"}
    missing = set(g_flags) - set(s_flags)
    assert missing == _KNOWN_REMOVED, f"unexpected panel removal(s) beyond the pinned set: {missing - _KNOWN_REMOVED}"
    for ct, frac in g_flags.items():
        if ct in _KNOWN_REMOVED:
            continue
        assert s_flags[ct] == frac, f"safety_essential_flags value drifted for {ct!r}: {s_flags[ct]!r} != {frac!r}"

    # is_safety_essential is DERIVED from the same panel checked above (it is expected to flip
    # false->true for any cell_type the panel grew to cover) — excluded here, not re-checked twice.
    s_by_ct = {r["cell_type"]: r for r in summary["per_cell_type_top"]}
    for g_row in golden["per_cell_type_top"]:
        s_row = s_by_ct.get(g_row["cell_type"])
        assert s_row is not None, (
            f"golden per_cell_type_top cell_type {g_row['cell_type']!r} missing from re-derived top-15"
        )
        for k, v in g_row.items():
            if k == "is_safety_essential":
                continue
            assert s_row.get(k) == v, (
                f"per_cell_type_top[{g_row['cell_type']!r}].{k} drifted: {s_row.get(k)!r} != {v!r}"
            )


def test_sc_normal_teeth_dropping_the_essential_driver_breaks_the_golden_safety_class_match():
    """Teeth: dropping every row for the named essential-organ driver cell type must move
    sc_normal_safety_essential_class away from the golden's committed `critical_organ_liability` —
    proving the golden-bridge is a live function of the frozen substrate, not a self-echo."""
    summary, anchor = _rederive_sc()
    golden = _golden_card("sc-normal-celltype-expression")
    assert summary["sc_normal_safety_essential_class"] == golden["sc_normal_safety_essential_class"]

    driver_ct = anchor["expected"]["sc_normal_essential_max_cell_type"]
    assert driver_ct, "teeth vacuous: anchor carries no named essential-organ driver"

    sc_rd, sc_cli = _sc_modules()
    rows = pd.read_parquet(RECOMPUTATION_DIR / anchor["rows_fixture"])
    mutated = [r for r in rows.to_dict("records") if r["cell_type"] != driver_ct]
    tissues = sc_rd.tissues_for_indication(anchor["indication"])
    tissues_loaded = anchor["tissues_loaded"]

    def _fake(_target, _tissues):
        df = pd.DataFrame(mutated, columns=list(sc_rd._PARQUET_COLS))  # noqa: SLF001
        df.attrs["tissues_requested"] = list(tissues)
        df.attrs["tissues_with_product"] = list(tissues)
        df.attrs["tissues_loaded"] = list(tissues_loaded)
        df.attrs["tissues_missing"] = [t for t in tissues if t not in set(tissues_loaded)]
        return df

    with mock.patch.object(sc_rd, "read_gene_celltype_rows", _fake):
        mutated_summary = sc_cli.build_summary(anchor["target"], anchor["indication"])
    assert (
        mutated_summary["sc_normal_safety_essential_class"] != golden["sc_normal_safety_essential_class"]
        or mutated_summary["sc_normal_essential_max_cell_type"] != driver_ct
    )


# ── normal-tissue-liability ─────────────────────────────────────────────────────────────────────

_HPA_STABLE = (
    "normal_tissue_breadth_class",
    "hpa_tissue_distribution",
    "hpa_tissue_specificity",
    "n_specific_tissues",
    "specific_tissues",
    "method_version",
)
_HPA_DRIFT_FIELDS = (
    "essential_tissue_flag",
    "essential_tissues_flagged",
    "n_essential_tissues_with_expression",
    "safety_tissue_flags",
)
_HPA_NEW_KEYS = ("hpa_ihc_reliability", "essential_tissue_low_reliability")


def _rederive_hpa(anchor_path: Path = HPA_ANCHOR):
    hpa_cli = _hpa_module()
    anchor = _load(anchor_path)
    row = _load(RECOMPUTATION_DIR / anchor["row_fixture"])
    summary = hpa_cli.compute_summary(anchor["target"], row)
    return summary, anchor, row


def test_hpa_liability_rederives_and_matches_anchor():
    summary, anchor, _row = _rederive_hpa()
    for k, v in anchor["expected"].items():
        assert summary.get(k) == v, f"normal-tissue-liability anchor mismatch on {k}: {summary.get(k)!r} != {v!r}"


def test_hpa_liability_vintage_stable_fields_match_golden_byte_exact():
    summary, _anchor, _row = _rederive_hpa()
    golden = _golden_card("normal-tissue-liability")
    for f in _HPA_STABLE:
        assert golden[f] == summary[f], f"golden vs re-derived mismatch on {f}: {golden[f]!r} != {summary[f]!r}"


def test_hpa_liability_essential_tissue_flag_drift_is_pinned_verdict_inert_and_cross_linked_2061():
    """Drift 2 (pinned, cross-linked #2061, NOT regenerated here per this issue's explicit
    instruction): 'intestine' was promoted to the canonical essential-tissue set (2026-09-18,
    predates the #1793/#1794 safety-pin bump this issue was held on) — the golden predates that
    promotion. This assertion PINS the exact current-vs-golden divergence so a future golden regen
    (#2061) that silently reverts it fails loudly, rather than asserting a stale byte-exact equality
    that would RED today."""
    summary, _anchor, _row = _rederive_hpa()
    golden = _golden_card("normal-tissue-liability")

    assert golden["essential_tissue_flag"] == "unknown"
    assert summary["essential_tissue_flag"] == "present"
    assert summary["essential_tissue_flag"] != golden["essential_tissue_flag"]

    assert golden["essential_tissues_flagged"] == []
    assert summary["essential_tissues_flagged"] == ["intestine"]

    assert golden["n_essential_tissues_with_expression"] == 0
    assert summary["n_essential_tissues_with_expression"] == 1

    assert "essential_tissue" not in golden["safety_tissue_flags"]
    assert "essential_tissue" in summary["safety_tissue_flags"]

    # Wholly new keys (AM#745 antibody reliability) — absent from the golden entirely, not a value flip.
    for k in _HPA_NEW_KEYS:
        assert k not in golden, f"golden unexpectedly already carries {k!r} — re-check the drift framing"
        assert k in summary, f"current reader unexpectedly missing {k!r}"


def test_hpa_liability_teeth_blanking_intensity_moves_the_essential_flag():
    """Teeth: blanking Protein tissue specific Intensity on the frozen EPCAM row must re-derive a
    DIFFERENT essential_tissue_flag/essential_tissues_flagged than the live re-derivation above —
    proving the trichotomy is a live function of the frozen row, not echoed from the anchor.
    Revert-verified the other direction by test_hpa_liability_rederives_and_matches_anchor (the
    un-mutated row reproduces exactly)."""
    hpa_cli = _hpa_module()
    summary, anchor, row = _rederive_hpa()
    assert summary["essential_tissues_flagged"], "teeth setup: EPCAM anchor must carry enrichment-driven flags"

    mutated_row = dict(row)
    mutated_row[hpa_cli.HPA_INTENSITY_COL] = None
    mutated_summary = hpa_cli.compute_summary(anchor["target"], mutated_row)
    assert mutated_summary["essential_tissues_flagged"] != summary["essential_tissues_flagged"]
    assert mutated_summary["essential_tissue_flag"] != summary["essential_tissue_flag"]
