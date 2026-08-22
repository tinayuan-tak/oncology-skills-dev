"""Unit tests for the SHARED claim_vector_core contract (skills/_skills_common/claim_vector_core.py).

Pin the COMBINATION DISCIPLINE the shared machinery must uphold, independent of any one skill's axes:
  * ordinal (not metric) tiers; gap (`unmeasured`) is off-scale, never comparable, never == absent;
  * within-claim corroboration is SUB-ADDITIVE (lifts corroboration, never the signal tier);
  * conflict caps corroboration; claims stay separate; the key-signals builder ranks + gates + picks the
    weakest MEASURED critical caveat deterministically.
Pure — no S3, no card reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.claim_vector_core import (  # noqa: E402
    SIGNAL_ORD, CORROBORATION_ORD, ClaimSpec, build_claim_vector, build_key_signals,
    bump_corroboration, cap_corroboration, weakest, sig_ge, cards_by_id,
    build_atom, build_summary_atom,
)


# ── shared evidence-atom builder (Group D 2026-08-21 — the single build_atom all 13 axes delegate to) ──
_ENTITY = {"measurement_type": "dependency_score", "grain": "target_indication"}


def test_build_atom_shape_and_citation_integrity():
    a = build_atom(card_id="crispr", values={"chronos": -1.2, "n": 300}, read="dependent", entity=_ENTITY)
    assert a["read"] == "dependent" and a["values"] == {"chronos": -1.2, "n": 300}
    assert a["entity"] == _ENTITY
    # CITATION-INTEGRITY CONTRACT: the atom always cites its OWN source card_id (never a phantom), and
    # fields are exactly the (sorted) value keys — so a consumer's cite.card_id resolves to a real card.
    assert a["cite"] == {"card_id": "crispr", "fields": ["chronos", "n"]}


def test_build_atom_drops_none_and_returns_none_when_empty():
    # None values are dropped; an all-absent atom returns None so the axis stays byte-stable (no atom key)
    assert build_atom(card_id="c", values={"a": 1, "b": None}, read="r", entity=_ENTITY)["values"] == {"a": 1}
    assert build_atom(card_id="c", values={"a": None}, read="r", entity=_ENTITY) is None
    assert build_atom(card_id="c", values={}, read="r", entity=_ENTITY) is None


def test_build_atom_preserves_value_order_but_sorts_fields():
    # values insertion order is preserved (JSON byte-order is part of the output); fields are sorted
    a = build_atom(card_id="c", values={"z": 1, "a": 2}, read="r", entity=_ENTITY)
    assert list(a["values"]) == ["z", "a"]           # order preserved
    assert a["cite"]["fields"] == ["a", "z"]         # fields sorted


def test_build_atom_exclude_fields_omits_list_valued_from_citation():
    # the bespoke axes (combination/immune) drop list-valued keys from `fields` but KEEP them in `values`
    a = build_atom(card_id="sl", values={"sl_class": "x", "partners": [1, 2, 3]}, read="x",
                   entity=_ENTITY, exclude_fields=("partners",))
    assert "partners" in a["values"]                 # still carried in values
    assert a["cite"]["fields"] == ["sl_class"]        # but NOT a citation field


def test_build_summary_atom_matches_the_legacy_standard_archetype():
    # build_summary_atom reproduces the former per-module _atom(card_id, summary, keys, entity, read)
    summary = {"k1": 5, "k2": None, "k3": "hi"}
    a = build_summary_atom(card_id="c", summary=summary, keys=("k1", "k2", "k3"), read="r", entity=_ENTITY)
    assert a == {"read": "r", "values": {"k1": 5, "k3": "hi"},
                 "cite": {"card_id": "c", "fields": ["k1", "k3"]}, "entity": _ENTITY}


# ── ordinal / gap≠absent invariants ───────────────────────────────────────────────────────────────
def test_gap_is_off_scale_not_zero():
    assert SIGNAL_ORD["unmeasured"] is None          # a GAP is off-scale
    assert SIGNAL_ORD["absent"] == 0                  # a measured floor IS on-scale
    assert SIGNAL_ORD["negative"] == 0
    assert CORROBORATION_ORD["unmeasured"] is None


def test_sig_ge_treats_unmeasured_as_never_meeting_floor():
    assert sig_ge("strong", "moderate")
    assert sig_ge("moderate", "moderate")
    assert not sig_ge("weak", "moderate")
    assert not sig_ge("unmeasured", "absent")        # gap is never >= even the floor
    assert not sig_ge(None, "absent")


# ── sub-additive corroboration + conflict cap ──────────────────────────────────────────────────────
def test_bump_corroboration_is_sub_additive_and_capped():
    assert bump_corroboration("low", True) == "moderate"
    assert bump_corroboration("moderate", True) == "high"
    assert bump_corroboration("high", True) == "high"          # cannot exceed high
    assert bump_corroboration("low", False) == "low"           # no corroboration = no-op
    assert bump_corroboration("unmeasured", True) == "unmeasured"  # a gap can't be corroborated


def test_cap_corroboration_never_raises():
    assert cap_corroboration("high", "moderate") == "moderate"
    assert cap_corroboration("low", "moderate") == "low"       # already below ceiling → unchanged
    assert cap_corroboration("unmeasured", "low") == "unmeasured"


def test_weakest_ignores_unmeasured():
    assert weakest(["high", "moderate", "low"], CORROBORATION_ORD) == "low"
    assert weakest(["high", "unmeasured"], CORROBORATION_ORD) == "high"   # gap doesn't win weakest-link
    assert weakest(["unmeasured"], CORROBORATION_ORD) is None


def test_cards_by_id_tolerates_none():
    assert cards_by_id(None) == {}
    assert cards_by_id([{"card_id": "x", "summary": None}]) == {"x": {}}
    assert cards_by_id([{"card_id": "y", "summary": {"a": 1}}]) == {"y": {"a": 1}}


# ── build_claim_vector: axes stay SEPARATE, shape is uniform ───────────────────────────────────────
def _toy_spec():
    return [
        ClaimSpec("X", "x", lambda h, c: ("strong", "e-x", None), lambda h, c: "high", "informs-x"),
        ClaimSpec("Y", "y", lambda h, c: ("absent", "e-y", "conf-y"), lambda h, c: "low", "informs-y"),
        ClaimSpec("Z", "z", lambda h, c: ("unmeasured", "e-z", None), lambda h, c: "unmeasured", "informs-z"),
    ]


def test_build_claim_vector_shape_and_separation():
    vec = build_claim_vector(_toy_spec(), {}, [], "DISC")
    assert vec["_disclaimer"] == "DISC"
    assert vec["X"] == {"signal": "strong", "corroboration": "high", "evidence": "e-x",
                        "conflict": None, "informs": "informs-x"}
    # a weak/absent Y sits UNCHANGED next to a strong X — no averaging, no cross-contamination
    assert vec["Y"]["signal"] == "absent" and vec["Y"]["conflict"] == "conf-y"
    assert vec["Z"]["signal"] == "unmeasured"


# ── build_key_signals: rank, >=moderate gate, weakest-critical caveat, deterministic headline ──────
def test_key_signals_ranks_gates_and_caveats():
    vec = build_claim_vector(_toy_spec(), {}, [], "DISC")
    out = build_key_signals(
        vec,
        rank_keys=("X", "Y", "Z"),
        support_fns={"X": lambda cl: "SUP-X", "Y": lambda cl: "SUP-Y", "Z": lambda cl: "SUP-Z"},
        critical_keys=("X", "Y"),
        caveat_fns={"X": lambda cl: "CAV-X", "Y": lambda cl: "CAV-Y"},
        headline_fn=lambda v, sup: f"H:{len(sup)}",
    )
    # only X is >= moderate → the sole support; Y(absent)/Z(gap) are gated out
    assert out["supports"] == ["SUP-X"]
    # weakest MEASURED critical claim is Y (absent, tier 0 <= weak) → its caveat fires (Z gap ignored)
    assert out["caveat"] == "CAV-Y"
    assert out["headline"] == "H:1"


def test_key_signals_no_caveat_when_all_critical_strong():
    spec = [ClaimSpec("A", "a", lambda h, c: ("strong", "", None), lambda h, c: "high", "i"),
            ClaimSpec("B", "b", lambda h, c: ("moderate", "", None), lambda h, c: "moderate", "i")]
    vec = build_claim_vector(spec, {}, [], "D")
    out = build_key_signals(vec, rank_keys=("A", "B"),
                            support_fns={"A": lambda cl: "sa", "B": lambda cl: "sb"},
                            critical_keys=("A", "B"), caveat_fns={"A": lambda cl: "ca", "B": lambda cl: "cb"},
                            headline_fn=lambda v, s: "h")
    assert out["caveat"] is None                       # weakest critical is moderate (tier 2 > weak)
    assert out["supports"] == ["sa", "sb"]


def test_key_signals_fallback_caveat_when_no_measured_critical():
    spec = [ClaimSpec("A", "a", lambda h, c: ("unmeasured", "", None), lambda h, c: "unmeasured", "i")]
    vec = build_claim_vector(spec, {}, [], "D")
    out = build_key_signals(vec, rank_keys=("A",), support_fns={}, critical_keys=("A",),
                            caveat_fns={}, headline_fn=lambda v, s: "h",
                            fallback_caveat_fn=lambda: "FALLBACK")
    assert out["caveat"] == "FALLBACK"


# ── optional citable atom (atom_fn) — additive, backward-compatible ─────────────────────────────────
def test_atom_fn_is_optional_and_additive():
    spec = [
        # no atom_fn → legacy 5-key shape, byte-for-byte
        ClaimSpec("A", "a", lambda h, c: ("strong", "e", None), lambda h, c: "high", "i"),
        # atom_fn returns a dict → exactly one extra key `evidence_atom`
        ClaimSpec("B", "b", lambda h, c: ("moderate", "e", None), lambda h, c: "low", "i",
                  lambda h, c: {"values": {"x": 1}, "cite": {"card_id": "card-b", "fields": ["x"]}}),
        # atom_fn present but returns None (e.g. source card absent) → NO key added
        ClaimSpec("C", "c", lambda h, c: ("weak", "e", None), lambda h, c: "low", "i",
                  lambda h, c: None),
    ]
    vec = build_claim_vector(spec, {}, [], "D")
    assert set(vec["A"]) == {"signal", "corroboration", "evidence", "conflict", "informs"}
    assert "evidence_atom" not in vec["A"]
    assert vec["B"]["evidence_atom"]["cite"]["card_id"] == "card-b"
    assert set(vec["B"]) == {"signal", "corroboration", "evidence", "conflict", "informs", "evidence_atom"}
    assert "evidence_atom" not in vec["C"]
