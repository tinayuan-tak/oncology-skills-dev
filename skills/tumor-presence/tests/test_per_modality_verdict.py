"""Test tumor-presence per-(measurement, sample_context) sub-verdicts.

Slice A2 (MODALITY_TAXONOMY.md) refines the per-modality view: buckets are now keyed
by the (measurement, sample_context) PAIR — `bulk_rna/cell_line`, `bulk_rna/tumor`,
`bulk_protein_ms/cell_line`, `bulk_protein_ms/tumor` — so a cell-line-RNA signal is
never conflated with a tumor-RNA signal (both are `measurement: bulk_rna`).

The refactor is ADDITIVE: the collapsed `presence_verdict` (the audit spine the
target-profile consumer reads as `verdict`) stays byte-stable. These tests pin:
  1. collapsed verdict = same rank ladder as before (F1-safe / consumer contract);
  2. fired rules group by their card's (measurement, sample_context) pair (CARD_CONTEXT);
  3. within-bucket ranking uses the MEASUREMENT's ladder (rule vocab is measurement-scoped);
  4. buckets with no card (sc_rna/tumor, protein_ihc/normal) emit explicit
     data_unavailable — a NAMED gap, never a fabricated negative;
  5. the disagreement case (RNA-high, protein-low) is legible per-bucket while the
     collapsed verdict is unchanged;
  6. THE DEGENERATE CASE: a target-only query (cell-line RNA measured, tumor RNA
     absent) is now HONEST — bulk_rna/cell_line measured + bulk_rna/tumor
     data_unavailable are distinct, not collapsed into one bulk_rna bucket.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x",
            "value": "y", "signals": {}}


# --- collapsed verdict unchanged (F1-safe / consumer contract) --------------

def test_collapsed_verdict_ranks_across_all_cards():
    fired = [_fr("expression-broadly-high-supportive", "expression-distribution"),
             _fr("expression-strong-upregulation-supportive", "expression-tumor-vs-adjacent")]
    assert tp._verdict(fired) == ("broadly_high_expression",
                                  "expression-broadly-high-supportive")


def test_collapsed_verdict_no_rules_is_insufficient():
    assert tp._verdict([]) == ("insufficient", None)


# --- per-bucket grouping + within-bucket ranking ----------------------------

def test_bulk_rna_buckets_are_split_by_sample_context():
    """Two bulk_rna cards with DIFFERENT sample_context land in SEPARATE buckets —
    the whole point of Slice A2. Previously both collapsed into one `bulk_rna` key."""
    fired = [_fr("expression-strong-upregulation-supportive", "expression-tumor-vs-adjacent"),
             _fr("expression-broadly-high-supportive", "expression-distribution")]
    pm = tp._per_modality_verdicts(fired)
    # cell-line RNA: broadly-high (the distribution card)
    assert pm["bulk_rna/cell_line"]["verdict"] == "broadly_high_expression"
    assert pm["bulk_rna/cell_line"]["evidence_state"] == "measured"
    # tumor RNA: strong-upregulation (the tumor-vs-adjacent card) — a DISTINCT bucket
    assert pm["bulk_rna/tumor"]["verdict"] == "strongly_upregulated_in_tumor"
    assert pm["bulk_rna/tumor"]["evidence_state"] == "measured"


def test_degenerate_target_only_case_is_honest():
    """THE degenerate-case fix: a target-only query fires ONLY the cell-line card, so
    bulk_rna/cell_line is measured while bulk_rna/tumor is data_unavailable — no longer
    collapsed into a single bulk_rna bucket that masqueraded as tumor evidence."""
    fired = [_fr("expression-broadly-moderate-neutral", "expression-distribution")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna/cell_line"]["evidence_state"] == "measured"
    assert pm["bulk_rna/cell_line"]["verdict"] == "broadly_moderate_expression"
    assert pm["bulk_rna/tumor"]["evidence_state"] == "data_unavailable"
    assert pm["bulk_rna/tumor"]["verdict"] == "data_unavailable"


def test_protein_bucket_is_separate_from_rna():
    # bulk_protein_ms/tumor fires a REAL protein rule_id ranked against _PROTEIN_RANK.
    fired = [_fr("expression-broadly-high-supportive", "expression-distribution"),
             _fr("protein-strongly-down-opposing", "protein-presence-cptac")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna/cell_line"]["verdict"] == "broadly_high_expression"
    assert pm["bulk_protein_ms/tumor"]["verdict"] == "protein_strongly_downregulated"
    assert pm["bulk_protein_ms/tumor"]["evidence_state"] == "measured"


def test_protein_only_signal_not_swallowed_C1_regression():
    """C1 regression guard (2026-07-20): a target with a MEASURED bulk_protein_ms
    signal and NO expression signal must produce a real protein verdict — NOT the
    silent `insufficient` collapse the expression-only ladder caused."""
    # measured cell-line protein presence, no RNA
    pm = tp._per_modality_verdicts([_fr("protein-abundance-broadly-high-supportive",
                                        "protein-abundance-celline")])
    assert pm["bulk_protein_ms/cell_line"]["verdict"] == "protein_broadly_high"
    assert pm["bulk_protein_ms/cell_line"]["verdict"] != "insufficient"
    # protein-not-detected killer (tumor CPTAC) must surface, not vanish
    pm2 = tp._per_modality_verdicts([_fr("protein-not-detected-degrader-killer",
                                         "protein-presence-cptac")])
    assert pm2["bulk_protein_ms/tumor"]["verdict"] == "protein_not_detected"
    # collapsed verdict: a protein-only target resolves instead of collapsing
    v, drv = tp._verdict([_fr("protein-abundance-broadly-high-supportive",
                              "protein-abundance-celline")])
    assert v == "protein_broadly_high" and drv is not None


def test_celline_proteomics_card_feeds_bulk_protein_ms_cell_line():
    """The protein-abundance-celline card (E3b) is bulk_protein_ms × cell_line — its
    fired rule lands in the bulk_protein_ms/cell_line bucket, DISTINCT from CPTAC's
    bulk_protein_ms/tumor bucket."""
    assert tp.CARD_CONTEXT["protein-abundance-celline"] == ("bulk_protein_ms", "cell_line")
    fired = [_fr("protein-abundance-broadly-high-supportive", "protein-abundance-celline")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_protein_ms/cell_line"]["evidence_state"] == "measured"
    # CPTAC tumor protein bucket stays data_unavailable (no CPTAC card fired)
    assert pm["bulk_protein_ms/tumor"]["evidence_state"] == "data_unavailable"
    # all bulk_rna buckets stay data_unavailable (no RNA card fired) — axes independent
    assert pm["bulk_rna/cell_line"]["evidence_state"] == "data_unavailable"
    assert pm["bulk_rna/tumor"]["evidence_state"] == "data_unavailable"


def test_rna_high_protein_low_disagreement_is_legible():
    """The taxonomy's core payoff: collapsed verdict unchanged, but the per-bucket
    breakdown EXPOSES that tumor protein contradicts cell-line RNA."""
    fired = [_fr("expression-broadly-high-supportive", "expression-distribution"),
             _fr("protein-strongly-down-opposing", "protein-presence-cptac")]
    assert tp._verdict(fired)[0] == "broadly_high_expression"   # collapsed unchanged (RNA wins)
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna/cell_line"]["verdict"] != pm["bulk_protein_ms/tumor"]["verdict"]


# --- honest gaps: unbuilt substrates are data_unavailable, never negative ---

def test_unbuilt_substrates_are_data_unavailable():
    fired = [_fr("expression-broadly-high-supportive", "expression-distribution")]
    pm = tp._per_modality_verdicts(fired)
    for key in ("sc_rna/tumor", "protein_ihc/normal"):
        assert pm[key]["verdict"] == "data_unavailable"
        assert pm[key]["evidence_state"] == "data_unavailable"


def test_no_fired_rules_all_buckets_data_unavailable():
    pm = tp._per_modality_verdicts([])
    expected = {tp._ctx_key(m, s) for m, s in tp.ALL_CONTEXTS}
    assert set(pm.keys()) == expected
    for v in pm.values():
        assert v["verdict"] == "data_unavailable"


def test_all_taxonomy_buckets_present():
    pm = tp._per_modality_verdicts([])
    assert set(pm.keys()) == {"bulk_rna/cell_line", "bulk_rna/tumor",
                              "bulk_protein_ms/cell_line", "bulk_protein_ms/tumor",
                              "sc_rna/tumor", "protein_ihc/normal"}
    # each bucket carries its two axes as explicit fields
    for (m, s) in tp.ALL_CONTEXTS:
        b = pm[tp._ctx_key(m, s)]
        assert b["measurement"] == m and b["sample_context"] == s


# --- drift guard: CARD_CONTEXT matches the card specs on BOTH axes ----------

def test_card_context_map_covers_all_skill_cards():
    """Every card in CARDS must have a (measurement, sample_context) entry (else it
    silently drops out of the per-bucket view)."""
    for cid in tp.CARDS:
        assert cid in tp.CARD_CONTEXT, f"{cid} missing from CARD_CONTEXT"


_CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")


def test_card_context_matches_target_contracts_specs():
    """Drift guard: CARD_CONTEXT must mirror the `measurement:` + `sample_context:`
    tags in the target-contracts card specs. Graceful-skips if target-contracts is not
    checked out alongside (isolated CI), mirroring the other cross-repo checks."""
    cards_dir = _CONTRACTS / "cards"
    if not cards_dir.is_dir():
        import pytest
        pytest.skip("target-contracts not checked out alongside")
    for cid, (measurement, sample_context) in tp.CARD_CONTEXT.items():
        spec_path = cards_dir / f"{cid}.card.yaml"
        assert spec_path.is_file(), f"card spec missing: {spec_path}"
        spec = yaml.safe_load(spec_path.read_text())
        assert spec.get("measurement") == measurement, (
            f"{cid}: CARD_CONTEXT measurement {measurement!r} != spec "
            f"{spec.get('measurement')!r}")
        assert spec.get("sample_context") == sample_context, (
            f"{cid}: CARD_CONTEXT sample_context {sample_context!r} != spec "
            f"{spec.get('sample_context')!r}")


def test_verdict_fn_discoverable_by_composer():
    assert hasattr(tp, "_verdict") or hasattr(tp, "_snapshot")
