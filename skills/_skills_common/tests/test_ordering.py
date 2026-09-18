"""Tests for the shared bucket-key ordering kernel (`ordering.ordered_bucket_keys`).

The panel deliberately covers BOTH real consumers' policies so the kernel is validated against a
panel, not overfit to one:
  * l2_substrate.group_records_by_context — sorted keys, residual bucket last.
  * report_render.ReportIR.lenses         — known_order first, unknown keys stably last, no residual.
"""

from __future__ import annotations

from _skills_common.ordering import ordered_bucket_keys

# ── sorted policy (the by_context shape) ─────────────────────────────────────────────────────────


def test_sorted_when_no_known_order():
    buckets = {"c": 1, "a": 1, "b": 1}
    assert ordered_bucket_keys(buckets) == ["a", "b", "c"]


def test_residual_last_even_though_it_would_sort_first():
    # a leading-NUL sentinel (as l2_substrate.UNKEYED) sorts lexicographically FIRST — must go last
    resid = "\x00unkeyed"
    buckets = {"m": 1, resid: 1, "a": 1}
    assert ordered_bucket_keys(buckets, residual_key=resid) == ["a", "m", resid]


def test_residual_absent_is_noop():
    buckets = {"b": 1, "a": 1}
    assert ordered_bucket_keys(buckets, residual_key="\x00unkeyed") == ["a", "b"]


# ── known_order policy (the lenses shape) ─────────────────────────────────────────────────────────


def test_known_order_first_skipping_absent():
    order = ("decision", "signals", "modality", "risk", "biology")
    buckets = {"risk": 1, "decision": 1, "signals": 1}  # modality/biology absent
    assert ordered_bucket_keys(buckets, known_order=order) == ["decision", "signals", "risk"]


def test_unknown_keys_follow_in_insertion_order_stably_last():
    order = ("decision", "signals")
    buckets = {"signals": 1, "zeta": 1, "decision": 1, "alpha": 1}  # zeta before alpha by insertion
    # known first (in known_order), then unknowns in INSERTION order (not sorted): zeta, then alpha
    assert ordered_bucket_keys(buckets, known_order=order) == ["decision", "signals", "zeta", "alpha"]


def test_known_order_with_residual_last():
    order = ("decision", "signals")
    resid = "\x00resid"
    buckets = {"signals": 1, resid: 1, "decision": 1, "extra": 1}
    assert ordered_bucket_keys(buckets, known_order=order, residual_key=resid) == [
        "decision",
        "signals",
        "extra",
        resid,
    ]


# ── invariants ────────────────────────────────────────────────────────────────────────────────


def test_every_key_present_exactly_once():
    order = ("a", "b")
    buckets = {"b": 1, "a": 1, "c": 1, "a_dup_guard": 1}
    out = ordered_bucket_keys(buckets, known_order=order)
    assert sorted(out) == sorted(buckets.keys())
    assert len(out) == len(set(out)) == len(buckets)


def test_known_order_key_not_in_buckets_is_ignored():
    # a known_order entry absent from buckets must not appear (lenses skips absent lenses)
    out = ordered_bucket_keys({"a": 1}, known_order=("z", "a", "y"))
    assert out == ["a"]


def test_empty_buckets():
    assert ordered_bucket_keys({}) == []
    assert ordered_bucket_keys({}, known_order=("a",), residual_key="r") == []


# ── equivalence with the pre-refactor open-coded lenses loop ─────────────────────────────────────


def test_matches_legacy_lenses_ordering():
    """Byte-for-byte reproduce the loop ir.py.lenses() used before this kernel: LENS_ORDER-present
    first, then any lens not in LENS_ORDER in insertion order."""
    LENS_ORDER = ("decision", "signals", "modality", "risk", "biology")
    buckets = {"risk": ["x"], "signals": ["y"], "future_lens": ["z"], "decision": ["w"]}

    legacy = []
    for lens_id in LENS_ORDER:
        if buckets.get(lens_id):
            legacy.append(lens_id)
    for lens_id in buckets:
        if lens_id not in LENS_ORDER:
            legacy.append(lens_id)

    assert ordered_bucket_keys(buckets, known_order=LENS_ORDER) == legacy
