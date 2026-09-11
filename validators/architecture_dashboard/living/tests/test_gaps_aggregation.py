"""Gaps tab: normalized records, tally consistency, and validator wiring."""

from _util import load_committed

_REQUIRED_KEYS = {"severity", "gap_type", "component_type", "component_id", "code", "message", "source"}
_VALID_SEV = {"error", "warn", "info"}


def test_gap_records_are_normalized():
    for r in load_committed().get("gaps", {}).get("items", []):
        assert _REQUIRED_KEYS <= set(r), f"gap missing keys: {_REQUIRED_KEYS - set(r)}"
        assert r["severity"] in _VALID_SEV, f"bad severity {r['severity']}"


def test_summary_tally_matches_items():
    G = load_committed().get("gaps", {})
    items = G.get("items", [])
    s = G.get("summary", {})
    assert s.get("n_gaps") == len(items)
    for sev in _VALID_SEV:
        assert s.get(f"n_{sev}") == sum(1 for r in items if r["severity"] == sev)


def test_validators_were_wired():
    """The committed doc was generated with siblings present, so several validators must have
    run in-process — catches a signature/import regression that would silently drop them."""
    run = load_committed().get("gaps", {}).get("validators_run", [])
    # cards + resolvers are the two we most rely on; require a healthy subset overall.
    assert "validate_cards" in run and "validate_resolvers" in run, f"core validators missing: {run}"
    assert len(run) >= 6, f"expected >=6 validators wired, got {len(run)}: {run}"


def test_placeholder_cards_are_not_also_counted_as_orphans():
    """A DECLARED placeholder is unconsumed BECAUSE it is a placeholder — one backlog item, not two.

    2026-09-11: orphan_card was an exact subset of placeholder_card (the same 9 cards), so the same
    staging backlog was reported twice and, with its 8 PRODUCT_ID_UNRESOLVED warns, inflated the
    gap total ~3x. The orphan WARN now means only what it says: nobody consumes this card and nobody
    declared it staged.
    """
    items = load_committed().get("gaps", {}).get("items", [])
    orphans = {r["component_id"] for r in items if r["gap_type"] == "orphan_card"}
    placeholders = {r["component_id"] for r in items if r["gap_type"] == "placeholder_card"}
    both = orphans & placeholders
    assert not both, f"cards double-counted as orphan AND placeholder: {sorted(both)}"


def test_orphan_and_placeholder_records_are_one_per_card():
    """No card may emit two records of the same gap_type (a dedup regression would be invisible in
    the tally test, which only checks that the summary matches the item list)."""
    items = load_committed().get("gaps", {}).get("items", [])
    for gt in ("orphan_card", "placeholder_card"):
        ids = [r["component_id"] for r in items if r["gap_type"] == gt]
        assert len(ids) == len(set(ids)), f"duplicate {gt} records: {sorted(ids)}"
