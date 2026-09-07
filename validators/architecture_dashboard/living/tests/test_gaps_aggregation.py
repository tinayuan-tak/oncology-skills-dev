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
