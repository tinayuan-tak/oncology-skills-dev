"""Tests for the I.3 wiring reconciliation gate (READS vs DECLARES vs EMITS).

WHY THE SHAPE OF THESE TESTS MATTERS. The committed baseline is EMPTY (the one genuine finding,
known-drug-tractability reading dgidb-drug-target-directional-v1, was FIXED in the card rather than
baselined). An empty baseline + zero live findings means the ONLY proof the gate has teeth is a
mutation test: a hand-built snapshot where the right answer is known independently of the extractor,
mutated to force each finding, with a positive AND a negative case for every tooth — a gate that only
ever fires is as broken as one that never does.

These are HERMETIC: they exercise self_check_hermetic / _reconcile / _floors over a synthetic cards
dir + synthetic snapshot dict, needing no analysis-methods / skills / data-catalog sibling, so they
run in the checkout-only contracts-validate CI. The single LIVE test is skipped when the siblings are
absent. `test_committed_snapshot_passes_hermetic` pins the real artifact against today's real cards —
the same assertion CI's --self-check makes, mirrored in pytest so it is visible as a red test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validators"))
import build_wiring_reconciliation as bwr  # noqa: E402


# ---------------------------------------------------------------------------
# synthetic fixtures
# ---------------------------------------------------------------------------
def _write_card(root: Path, card_id: str, declares: list[str]) -> None:
    (root / "cards").mkdir(parents=True, exist_ok=True)
    (root / "cards" / f"{card_id}.card.yaml").write_text(
        yaml.safe_dump(
            {"card_id": card_id, "required_inputs": [{"product_id": d} for d in declares]},
            sort_keys=False,
        )
    )


def _sound_entry(declares, reads, read_closures, templates=None, findings=None) -> dict:
    return {
        "confidence": "sound",
        "declares": sorted(declares),
        "modules": ["m"],
        "emits_in_ledger": True,
        "reads": sorted(reads),
        "read_closures": read_closures,
        "templates": sorted(templates or []),
        "off_contract_reads": [],
        "findings": findings if findings is not None else [],
    }


def _snapshot(by_card: dict, known_keys=None, sound=14, routed=68) -> dict:
    return {
        "n_dispatcher_routed_cards": routed,
        "counts": {"sound": sound},
        "known_violations": {"as_of": "2026-09-20", "keys": sorted(known_keys or [])},
        "by_card": by_card,
    }


@pytest.fixture
def cards(tmp_path, monkeypatch):
    """Point card_declares at a sandbox cards/ dir. Floors are satisfied via the snapshot's own
    counts (sound=14, routed=68), so the finding logic is isolated from the vacuity floors — which
    test_floors_trip_on_empty proves still bite."""
    monkeypatch.setattr(bwr, "CARDS", tmp_path / "cards")
    return tmp_path


# ---------------------------------------------------------------------------
# _reconcile — the pure core, positive and negative for lineage + template
# ---------------------------------------------------------------------------
def test_reconcile_clean_when_reads_equal_declares():
    du, ru = _reconcile_call(declares=["A"], reads=["A"], closures={"A": ["A"]})
    assert du == [] and ru == []


def test_reconcile_flags_declared_unread():
    du, ru = _reconcile_call(declares=["A", "B"], reads=["A"], closures={"A": ["A"]})
    assert du == ["B"] and ru == []


def test_reconcile_flags_read_undeclared():
    du, ru = _reconcile_call(declares=["A"], reads=["A", "X"], closures={"A": ["A"], "X": ["X"]})
    assert du == [] and ru == ["X"]


def test_reconcile_lineage_covers_both_directions():
    # declare a SOURCE, read a product that derives from it: neither direction should flag.
    du, ru = _reconcile_call(declares=["SRC"], reads=["DERIV"], closures={"DERIV": ["DERIV", "SRC"]})
    assert du == [] and ru == []


def test_reconcile_template_covers_declared_shard():
    du, ru = _reconcile_call(declares=["x-brca-v1"], reads=[], closures={}, templates=["x-*-v1"])
    assert du == [] and ru == []


def _reconcile_call(declares, reads, closures, templates=None):
    return bwr._reconcile(reads, closures, templates or [], declares)


# ---------------------------------------------------------------------------
# self_check_hermetic — mutation-proved teeth
# ---------------------------------------------------------------------------
def test_clean_baseline_passes(cards):
    _write_card(cards, "c", ["A"])
    snap = _snapshot({"c": _sound_entry(["A"], ["A"], {"A": ["A"]})})
    assert bwr.self_check_hermetic(snap) == []


def test_declared_unread_is_unlisted_then_suppressed_by_baseline(cards):
    # card declares A and B; the sound entry reads only A -> B is DECLARED_UNREAD.
    _write_card(cards, "c", ["A", "B"])
    entry = _sound_entry(["A", "B"], ["A"], {"A": ["A"]}, findings=["DECLARED_UNREAD::B"])
    key = "c::DECLARED_UNREAD::B"

    errs = bwr.self_check_hermetic(_snapshot({"c": entry}))
    assert any("unlisted wiring violation" in e and key in e for e in errs), errs

    # listing it in the dated baseline suppresses the gate (each removal is then a one-line PR)
    assert bwr.self_check_hermetic(_snapshot({"c": entry}, known_keys=[key])) == []


def test_read_undeclared_is_unlisted_then_suppressed_by_baseline(cards):
    _write_card(cards, "c", ["A"])
    entry = _sound_entry(["A"], ["A", "X"], {"A": ["A"], "X": ["X"]}, findings=["READ_UNDECLARED::X"])
    key = "c::READ_UNDECLARED::X"

    errs = bwr.self_check_hermetic(_snapshot({"c": entry}))
    assert any("unlisted wiring violation" in e and key in e for e in errs), errs
    assert bwr.self_check_hermetic(_snapshot({"c": entry}, known_keys=[key])) == []


def test_declaration_drift_reds_even_when_committed_findings_looked_clean(cards):
    # SAFETY-ADVERSE case: the committed entry was clean (findings []), but the card since GAINED a
    # declared input nothing reads. The hermetic half re-derives against TODAY's card and reds.
    _write_card(cards, "c", ["A", "B_added_later"])
    entry = _sound_entry(["A"], ["A"], {"A": ["A"]}, findings=[])  # committed before B was added
    errs = bwr.self_check_hermetic(_snapshot({"c": entry}))
    assert any("findings drift" in e and "c" in e for e in errs), errs


def test_stale_known_violation_reds(cards):
    # a baseline entry that is no longer a live violation must red, so the list cannot go vacuous.
    _write_card(cards, "c", ["A"])
    entry = _sound_entry(["A"], ["A"], {"A": ["A"]})
    errs = bwr.self_check_hermetic(_snapshot({"c": entry}, known_keys=["c::DECLARED_UNREAD::A"]))
    assert any("no longer a violation" in e for e in errs), errs


def test_internal_inconsistency_reds(cards):
    # a read with no self-entry in its closure = a hand-edited / partially regenerated row.
    _write_card(cards, "c", ["A"])
    entry = _sound_entry(["A"], ["A"], {})  # closure missing A
    errs = bwr.self_check_hermetic(_snapshot({"c": entry}))
    assert any("internally inconsistent" in e for e in errs), errs


def test_undetermined_cards_are_not_reconciled(cards):
    # an undetermined card carries no reads and must never produce a finding, however it declares.
    _write_card(cards, "c", ["A", "B", "C"])
    snap = _snapshot(
        {"c": {"confidence": "undetermined", "declares": ["A", "B", "C"], "reason": "0 concrete catalog reads"}}
    )
    assert bwr.self_check_hermetic(snap) == []


def test_floors_trip_on_empty():
    # no monkeypatch of CARDS needed: floors read the snapshot's own counts.
    errs = bwr.self_check_hermetic(_snapshot({}, sound=0, routed=0))
    assert any("vacuous" in e and "routed" in e for e in errs)
    assert any("vacuous" in e and "sound cards" in e for e in errs)


# ---------------------------------------------------------------------------
# pins on the real artifact
# ---------------------------------------------------------------------------
def test_committed_snapshot_passes_hermetic():
    """The committed snapshot must reconcile against TODAY's real cards — the CI --self-check
    assertion, mirrored as a red-able test. No siblings needed (hermetic)."""
    snap = yaml.safe_load(bwr.SNAPSHOT_PATH.read_text())
    assert bwr.self_check_hermetic(snap) == []


def test_committed_baseline_is_empty():
    """Documents the decision: the one genuine finding was FIXED in the card, not baselined. If a
    future finding is baselined instead of fixed this reds, forcing the choice to be explicit."""
    snap = yaml.safe_load(bwr.SNAPSHOT_PATH.read_text())
    assert (snap.get("known_violations") or {}).get("keys") == []


@pytest.mark.skipif(
    not bwr._siblings_available(),
    reason="analysis-methods / skills / data-catalog siblings absent (checkout-only CI)",
)
def test_live_extraction_meets_floors_and_matches_committed():
    # self_check_live re-extracts and diffs against the committed snapshot; a null diff proves the
    # committed reads match the methods on disk. Floors are checked on the committed counts (the same
    # numbers a null-diff live pass certifies), so one extraction pass covers both.
    committed = yaml.safe_load(bwr.SNAPSHOT_PATH.read_text())
    assert committed["counts"]["sound"] >= bwr.MIN_SOUND_CARDS
    assert committed["n_dispatcher_routed_cards"] >= bwr.MIN_ROUTED_CARDS
    live_errs, skipped = bwr.self_check_live(committed)
    assert skipped is None and live_errs == [], live_errs
