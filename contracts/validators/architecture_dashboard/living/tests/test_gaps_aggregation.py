"""Gaps tab: normalized records, tally consistency, and validator wiring."""

from pathlib import Path

import pytest
from _util import COMMITTED_JSON, load_committed

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


# --------------------------------------------------------------------------- #
# The root a gap scan runs against. Every test above reads the COMMITTED artifact, so none of
# them can see a builder that scanned the wrong tree: `test_validators_were_wired` passes on a
# doc whose `roots.target_contracts` points at a deleted worktree, because the gaps were
# computed from the live argument while the dead path was only recorded. These run the builder.
# --------------------------------------------------------------------------- #

_REPO = COMMITTED_JSON.parent.parent  # .../target-contracts


def _gaps_module():
    import gaps  # noqa: E402  (living/ is on sys.path via _util)

    return gaps


def test_bogus_root_raises_instead_of_reporting_zero_gaps(tmp_path, monkeypatch):
    """A wrong root does not fail on its own: every adapter globs an empty tree and emits
    nothing, so the result is `validators_run: [...]` with ZERO findings — a confident clean
    bill of health for a directory containing no cards. Measured before the guard: real root
    131 records / 129 card_structural / 9 validators, nonexistent root 4 / 0 / 7.

    cwd is pinned because CWD — not the import cache — is the dominant variable here.
    """
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="not a target-contracts checkout"):
        _gaps_module()._validator_gaps(tmp_path / "nope", None)


def test_dot_root_raises_when_cwd_is_not_a_checkout(tmp_path, monkeypatch):
    """`build_gaps`/`build_glossary` resolve the root as
    `roots.get(...) or graph.get("roots", {}).get(...) or "."`, so a caller that omits live
    roots lands on a cwd-relative `Path(".")`. That is the reachable path to the silent zero.
    """
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="not a target-contracts checkout"):
        _gaps_module()._validator_gaps(Path("."), None)


def test_guard_is_cwd_independent(monkeypatch):
    """★The trap this test exists for: with cwd AT a contracts checkout, `Path(".")` returns
    fully CORRECT results (131 / 129 / 9), because `_import_validators` leans on `sys.path`
    which contains `''`. So a bogus-root test that does not pin cwd demonstrates the bug
    working as a feature. The guard must reject a bad root from ANY cwd, including this one.
    """
    monkeypatch.chdir(_REPO)
    with pytest.raises(ValueError, match="not a target-contracts checkout"):
        _gaps_module()._validator_gaps(_REPO / "health", None)


def test_existing_but_empty_cards_dir_also_raises(tmp_path, monkeypatch):
    """The directory EXISTING is not the property that matters — an empty cards/ produces the
    identical silent zero, which is why the guard globs for a card instead of calling is_dir().
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cards").mkdir()
    with pytest.raises(ValueError, match="not a target-contracts checkout"):
        _gaps_module()._validator_gaps(tmp_path, None)


def test_real_root_still_scans(monkeypatch, tmp_path):
    """Non-vacuity for the four tests above: the guard must reject bad roots WITHOUT rejecting
    the real one. Run from a neutral cwd so the pass cannot come from cwd resolution."""
    monkeypatch.chdir(tmp_path)
    records, run = _gaps_module()._validator_gaps(_REPO, None)
    assert "validate_cards" in run, f"real root did not wire validate_cards: {run}"
    assert len(run) >= 6, f"real root wired only {len(run)} validators: {run}"
    card = [r for r in records if r.get("gap_type") == "card_structural"]
    assert card, "real root produced no card_structural findings — the scan found no cards"


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
