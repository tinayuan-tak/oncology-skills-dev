"""Tests for the per-modality-ARM decomposition (druggability_verdict_by_modality, 2026-09-01).

tractability-small-molecule loads the intracellular axis, which scores TWO modalities in parallel:
small-molecule INHIBITION (druggability_snapshot) and DEGRADATION (degrader_snapshot). Degradation is
KO-like complete removal, so an SM-intractable scaffold can still be a degrader prospect. This is the SM
analog of surface_modality_verdict_by_modality / safety_verdict_by_modality / presence_verdict_by_modality.

Pins the load-bearing properties:
  (1) EVERY resolver-emittable snapshot token (SM + degrader) is mapped — none falls through to the
      insufficient default silently;
  (2) it is a pure PROJECTION of the two resolved snapshots → CANNOT disagree with the one-word spine
      (verdict-inert); None/unknown → insufficient, never a fabricated viable arm;
  (3) the arms ride in the headline_block hero payload, the 5 evidence axes untouched, verdict.call
      byte-stable.
All pure (no S3).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

_M = load_run_py(Path(__file__).resolve().parent.parent, "tsm_run_bymod")


# ── (1) every resolver token maps (no silent default) ────────────────────────────────────────────
def test_every_sm_snapshot_token_is_mapped():
    """Every druggability_snapshot token the resolver can emit (the _DRUGGABILITY_VERDICT_PHRASE vocab)
    must have an SM arm mapping — a missing token would silently project to insufficient."""
    missing = set(_M._DRUGGABILITY_VERDICT_PHRASE) - set(_M._SM_ARM)
    assert not missing, f"druggability_snapshot tokens missing an SM arm mapping: {sorted(missing)}"


def test_every_degrader_snapshot_token_is_mapped():
    """Every degrader_snapshot token (_DEGRADER_CLASS_TO_SCOPE keys + insufficient) must map."""
    degrader_tokens = set(_M._DEGRADER_CLASS_TO_SCOPE) | {"insufficient"}
    missing = degrader_tokens - set(_M._DEG_ARM)
    assert not missing, f"degrader_snapshot tokens missing a degrader arm mapping: {sorted(missing)}"


def test_none_and_unknown_fall_back_to_insufficient_never_viable():
    for sm, deg in ((None, None), ("some_future_token", "another_future_token")):
        arms = _M._druggability_verdict_by_modality(sm, deg)
        assert arms == {"small_molecule": "insufficient", "degrader": "insufficient"}
        assert "viable" not in arms.values() and "supported" not in arms.values()


# ── (2) arm semantics + pure projection ──────────────────────────────────────────────────────────
def test_sm_positive_maps_viable_negative_maps_opposed_or_not_viable():
    assert _M._druggability_verdict_by_modality("well_covered", "insufficient")["small_molecule"] == "viable"
    assert _M._druggability_verdict_by_modality("discordant", "insufficient")["small_molecule"] == "opposed"
    assert _M._druggability_verdict_by_modality("chemically_unhit", "insufficient")["small_molecule"] == "not_viable"
    # a forward/weaker positive is a caveated handle, not a proven hit
    assert (
        _M._druggability_verdict_by_modality("structurally_ligandable", "insufficient")["small_molecule"] == "caveated"
    )


def test_degrader_arm_independent_of_sm_arm():
    # an SM-intractable scaffold can still be a degrader prospect (the whole point of the degrader lens)
    arms = _M._druggability_verdict_by_modality("structurally_intractable", "strong_degrader_rationale")
    assert arms["small_molecule"] == "not_viable" and arms["degrader"] == "viable"


def test_projection_is_pure_function():
    a = _M._druggability_verdict_by_modality("well_covered", "degrader_rationale")
    b = _M._druggability_verdict_by_modality("well_covered", "degrader_rationale")
    assert a == b and a is not b


# ── (3) the arms ride in the headline_block hero, evidence axes + verdict spine untouched ─────────
def test_arms_surface_in_headline_block_hero():
    headline = {
        "druggability_snapshot": "structurally_intractable",
        "degrader_snapshot": "strong_degrader_rationale",
        "druggability_verdict_by_modality": _M._druggability_verdict_by_modality(
            "structurally_intractable", "strong_degrader_rationale"
        ),
        "driving_rule_id": "structure-low-confidence-sm-opposing",
        "claim_vector": {
            k: {"signal": "strong", "corroboration": "high"}
            for k in ("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER")
        },
        "key_signals": {},
    }
    blk = _M._build_headline_block(headline)
    hero = blk["hero"]
    assert [a["key"] for a in hero["axes"]] == ["POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"]
    assert hero["modality_arms"]["small_molecule"] == "not_viable"
    assert hero["modality_arms"]["degrader"] == "viable"
    # verdict.call stays the resolved snapshot (byte-stable spine)
    assert blk["verdict"]["call"] == "structurally_intractable"
