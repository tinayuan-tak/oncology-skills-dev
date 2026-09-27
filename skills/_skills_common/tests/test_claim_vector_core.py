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

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.claim_vector_core import (  # noqa: E402
    CORROBORATION_ORD,
    SIGNAL_ORD,
    ClaimSpec,
    build_atom,
    build_claim_vector,
    build_key_signals,
    build_summary_atom,
    bump_corroboration,
    cap_corroboration,
    cards_by_id,
    sig_ge,
    weakest,
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
    # RAW-vs-DERIVED boundary (#1861): all-numeric here → numeric holds both, categorical empty
    assert a["numeric"] == {"chronos": -1.2, "n": 300}
    assert a["categorical"] == {}


def test_build_atom_drops_none_and_returns_none_when_empty():
    # None values are dropped; an all-absent atom returns None so the axis stays byte-stable (no atom key)
    assert build_atom(card_id="c", values={"a": 1, "b": None}, read="r", entity=_ENTITY)["values"] == {"a": 1}
    assert build_atom(card_id="c", values={"a": None}, read="r", entity=_ENTITY) is None
    assert build_atom(card_id="c", values={}, read="r", entity=_ENTITY) is None


def test_build_atom_preserves_value_order_but_sorts_fields():
    # values insertion order is preserved (JSON byte-order is part of the output); fields are sorted
    a = build_atom(card_id="c", values={"z": 1, "a": 2}, read="r", entity=_ENTITY)
    assert list(a["values"]) == ["z", "a"]  # order preserved
    assert a["cite"]["fields"] == ["a", "z"]  # fields sorted


def test_build_atom_exclude_fields_omits_list_valued_from_citation():
    # the bespoke axes (combination/immune) drop list-valued keys from `fields` but KEEP them in `values`
    a = build_atom(
        card_id="sl",
        values={"sl_class": "x", "partners": [1, 2, 3]},
        read="x",
        entity=_ENTITY,
        exclude_fields=("partners",),
    )
    assert "partners" in a["values"]  # still carried in values
    assert a["cite"]["fields"] == ["sl_class"]  # but NOT a citation field


def test_build_summary_atom_matches_the_legacy_standard_archetype():
    # build_summary_atom reproduces the former per-module _atom(card_id, summary, keys, entity, read)
    summary = {"k1": 5, "k2": None, "k3": "hi"}
    a = build_summary_atom(card_id="c", summary=summary, keys=("k1", "k2", "k3"), read="r", entity=_ENTITY)
    assert a == {
        "read": "r",
        "values": {"k1": 5, "k3": "hi"},
        # #1861 additive raw-vs-derived split: k1 (int) → numeric, k3 (str class) → categorical
        "numeric": {"k1": 5},
        "categorical": {"k3": "hi"},
        "cite": {"card_id": "c", "fields": ["k1", "k3"]},
        "entity": _ENTITY,
    }


def test_build_atom_splits_raw_scalars_from_derived_classes():
    # #1861 Arm A gap 2: the flat `values` co-mingles raw numbers with derived *_class labels; the
    # additive numeric/categorical sub-maps give the measurement/interpretation boundary the capsule
    # already has, so a pure raw layer is `evidence_atom.numeric` — no manual strip of class keys.
    a = build_atom(
        card_id="tumor-rna-distribution",
        values={
            "tumor_expression_class": "broadly_high",  # derived class
            "allgene_percentile": 99.74,  # raw number
            "median_log2tpm": 9.62,  # raw number
            "distribution_pattern": "continuous",  # derived class
            "n_flag": True,  # a bool is a flag/label, not a raw number → categorical
        },
        read="r",
        entity=_ENTITY,
    )
    assert a["numeric"] == {"allgene_percentile": 99.74, "median_log2tpm": 9.62}
    assert a["categorical"] == {
        "tumor_expression_class": "broadly_high",
        "distribution_pattern": "continuous",
        "n_flag": True,
    }
    # TOTAL, order-preserving partition: the two sub-maps reconstruct `values` exactly.
    assert {**a["numeric"], **a["categorical"]} == a["values"]
    # each sub-map preserves `values` insertion order (JSON byte-order is part of the output)
    assert list(a["numeric"]) == ["allgene_percentile", "median_log2tpm"]
    assert list(a["categorical"]) == ["tumor_expression_class", "distribution_pattern", "n_flag"]
    # `cite.fields` stays the full sorted union (byte-stable); each sub-map's field list is its keys
    assert a["cite"]["fields"] == sorted(a["values"])


# ── ordinal / gap≠absent invariants ───────────────────────────────────────────────────────────────
def test_gap_is_off_scale_not_zero():
    assert SIGNAL_ORD["unmeasured"] is None  # a GAP is off-scale
    assert SIGNAL_ORD["absent"] == 0  # a measured floor IS on-scale
    assert SIGNAL_ORD["negative"] == 0
    assert CORROBORATION_ORD["unmeasured"] is None


def test_underpowered_is_a_gap_with_intent_off_scale_like_unmeasured():
    """`underpowered` (measured, but under the power floor) is a gap WITH INTENT: distinct in TEXT from
    `unmeasured` (nobody looked) but identical in the ordinal MACHINERY — None, off-scale, the slot
    `negative`/`absent` share at 0 one level down. Pinned the way `single_arm`'s ordering is pinned, so the
    tier cannot silently decay to an on-scale integer — which would let an underpowered axis read as a
    driver (sig_ge true) or as a measured `absent` floor / passenger, the gap≠absent violation this tier
    exists to prevent."""
    assert SIGNAL_ORD["underpowered"] is None  # off-scale gap, NOT 0 (0 would read as a measured floor)
    assert CORROBORATION_ORD["underpowered"] is None
    assert SIGNAL_ORD["underpowered"] == SIGNAL_ORD["unmeasured"]  # same off-scale slot as the other gap
    assert not sig_ge("underpowered", "absent")  # a gap is never >= even the floor → never a driver
    # excluded from the measured-rung machinery exactly like `unmeasured`, for free (the `o is not None` idiom)
    assert weakest(["high", "underpowered"], CORROBORATION_ORD) == "high"  # a gap never wins weakest-link
    assert bump_corroboration("underpowered", True) == "underpowered"  # a gap cannot be corroborated
    assert cap_corroboration("underpowered", "low") == "underpowered"  # nor capped by a conflict
    # DISTINCT recognized token from `unmeasured` — a gap-with-intent, not one aliased onto the other
    assert "underpowered" in SIGNAL_ORD and "underpowered" in CORROBORATION_ORD


def test_sig_ge_treats_unmeasured_as_never_meeting_floor():
    assert sig_ge("strong", "moderate")
    assert sig_ge("moderate", "moderate")
    assert not sig_ge("weak", "moderate")
    assert not sig_ge("unmeasured", "absent")  # gap is never >= even the floor
    assert not sig_ge(None, "absent")


# ── sub-additive corroboration + conflict cap ──────────────────────────────────────────────────────
def test_bump_corroboration_is_sub_additive_and_capped():
    """EVERY measured rung is pinned, `single_arm` included. It was the one rung this test omitted, and
    the omission is why `single_arm -> high` sat unasserted while two call sites reached it from a
    same-arm qualifier: a test that enumerates the rungs it already knew about cannot notice a new one
    (same hole as `test_claim_features_ordinal_maps`). Derived from the ladder below so a future rung
    cannot be added without either a pin or a failure."""
    assert bump_corroboration("single_arm", True) == "high"  # n=1 -> n=2 in agreement IS `high`
    assert bump_corroboration("low", True) == "moderate"
    assert bump_corroboration("moderate", True) == "high"
    assert bump_corroboration("high", True) == "high"  # cannot exceed high
    assert bump_corroboration("low", False) == "low"  # no corroboration = no-op
    assert bump_corroboration("unmeasured", True) == "unmeasured"  # a gap can't be corroborated
    measured = [r for r, o in CORROBORATION_ORD.items() if o is not None]
    unpinned = set(measured) - {"single_arm", "low", "moderate", "high"}
    assert not unpinned, f"new corroboration rung(s) {unpinned} have no bump pin"


def test_a_same_arm_qualifier_cannot_lift_a_lone_arm_over_the_floor():
    """`arm=False` marks a localisation / model fit / strength grade — something that makes the ONE arm
    better, not a second arm. It must not clear CORROBORATION_ARM_FLOOR. Both directions asserted, so
    neither the guard nor the default can be deleted silently."""
    assert bump_corroboration("single_arm", True, arm=False) == "single_arm"
    assert bump_corroboration("single_arm", True, arm=True) == "high", "the real-arm default must differ"
    # A qualifier still refines a tier whose arms WERE compared — `low` already has >= 2 arms.
    assert bump_corroboration("low", True, arm=False) == "moderate"
    assert bump_corroboration("moderate", True, arm=False) == "high"
    assert bump_corroboration("unmeasured", True, arm=False) == "unmeasured"


def test_cap_corroboration_never_raises():
    assert cap_corroboration("high", "moderate") == "moderate"
    assert cap_corroboration("low", "moderate") == "low"  # already below ceiling → unchanged
    assert cap_corroboration("unmeasured", "low") == "unmeasured"


def test_weakest_ignores_unmeasured():
    assert weakest(["high", "moderate", "low"], CORROBORATION_ORD) == "low"
    assert weakest(["high", "unmeasured"], CORROBORATION_ORD) == "high"  # gap doesn't win weakest-link
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
    assert vec["X"] == {
        "signal": "strong",
        "corroboration": "high",
        "evidence": "e-x",
        "conflict": None,
        "informs": "informs-x",
    }
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
    spec = [
        ClaimSpec("A", "a", lambda h, c: ("strong", "", None), lambda h, c: "high", "i"),
        ClaimSpec("B", "b", lambda h, c: ("moderate", "", None), lambda h, c: "moderate", "i"),
    ]
    vec = build_claim_vector(spec, {}, [], "D")
    out = build_key_signals(
        vec,
        rank_keys=("A", "B"),
        support_fns={"A": lambda cl: "sa", "B": lambda cl: "sb"},
        critical_keys=("A", "B"),
        caveat_fns={"A": lambda cl: "ca", "B": lambda cl: "cb"},
        headline_fn=lambda v, s: "h",
    )
    assert out["caveat"] is None  # weakest critical is moderate (tier 2 > weak)
    assert out["supports"] == ["sa", "sb"]


def test_key_signals_fallback_caveat_when_no_measured_critical():
    spec = [ClaimSpec("A", "a", lambda h, c: ("unmeasured", "", None), lambda h, c: "unmeasured", "i")]
    vec = build_claim_vector(spec, {}, [], "D")
    out = build_key_signals(
        vec,
        rank_keys=("A",),
        support_fns={},
        critical_keys=("A",),
        caveat_fns={},
        headline_fn=lambda v, s: "h",
        fallback_caveat_fn=lambda: "FALLBACK",
    )
    assert out["caveat"] == "FALLBACK"


# ── optional citable atom (atom_fn) — additive, backward-compatible ─────────────────────────────────
def test_atom_fn_is_optional_and_additive():
    spec = [
        # no atom_fn → legacy 5-key shape, byte-for-byte
        ClaimSpec("A", "a", lambda h, c: ("strong", "e", None), lambda h, c: "high", "i"),
        # atom_fn returns a dict → exactly one extra key `evidence_atom`
        ClaimSpec(
            "B",
            "b",
            lambda h, c: ("moderate", "e", None),
            lambda h, c: "low",
            "i",
            lambda h, c: {"values": {"x": 1}, "cite": {"card_id": "card-b", "fields": ["x"]}},
        ),
        # atom_fn present but returns None (e.g. source card absent) → NO key added
        ClaimSpec("C", "c", lambda h, c: ("weak", "e", None), lambda h, c: "low", "i", lambda h, c: None),
    ]
    vec = build_claim_vector(spec, {}, [], "D")
    assert set(vec["A"]) == {"signal", "corroboration", "evidence", "conflict", "informs"}
    assert "evidence_atom" not in vec["A"]
    assert vec["B"]["evidence_atom"]["cite"]["card_id"] == "card-b"
    assert set(vec["B"]) == {"signal", "corroboration", "evidence", "conflict", "informs", "evidence_atom"}
    assert "evidence_atom" not in vec["C"]
