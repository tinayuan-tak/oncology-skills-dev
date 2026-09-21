"""Tests for the I.4 wiring ledger (dataset-grain: read / declared_only / dark).

WHY THE SHAPE OF THESE TESTS MATTERS. `dark` is a DIMENSION, not a gate — a backlog of unwired
datasets is the I.4 worklist, not a failure. So the ONLY thing --self-check enforces is that the
committed number cannot silently move: the three status lists must partition the committed universe,
the anti-vacuity floors must hold, and no committed-`dark` id may be declared by a card today without
regenerating. With nothing "baselined," a mutation test is the only proof those checks have teeth — a
gate that only ever fires, or never does, is as broken as no gate.

These are HERMETIC: they exercise self_check_hermetic / _partition_errors / _floors over a synthetic
snapshot dict + a sandbox cards/ dir, needing no analysis-methods / skills / data-catalog sibling, so
they run in the checkout-only contracts-validate CI. The single LIVE test is skipped when the siblings
are absent. `test_committed_snapshot_passes_hermetic` pins the real artifact — the same assertion
CI's --self-check makes, mirrored so it is visible as a red test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validators"))
import build_wiring_ledger as bwl  # noqa: E402


# ---------------------------------------------------------------------------
# synthetic fixtures — a snapshot whose right answer is known independent of the extractor
# ---------------------------------------------------------------------------
def _snap(read: list[str], declared_only: list[str], dark: list[str], universe: int | None = None) -> dict:
    read, declared_only, dark = sorted(read), sorted(declared_only), sorted(dark)
    return {
        "n_catalog_datasets": universe if universe is not None else len(read) + len(declared_only) + len(dark),
        "counts": {"read": len(read), "declared_only": len(declared_only), "dark": len(dark)},
        "n_literal_reads": len(read),
        "read": read,
        "declared_only": declared_only,
        "dark": dark,
    }


def _healthy_snap() -> dict:
    # universe 500 >= MIN_CATALOG_DATASETS (400); read 60 >= MIN_READ_DATASETS (40); dark < universe.
    read = [f"read-{i}" for i in range(60)]
    declared = [f"decl-{i}" for i in range(390)]
    dark = [f"dark-{i}" for i in range(50)]
    return _snap(read, declared, dark)


@pytest.fixture
def empty_cards(tmp_path, monkeypatch):
    """Point _all_declared() at a sandbox cards/ dir so the declaration-drift check sees only the cards
    a test writes. Partition + floors read the snapshot's own numbers, independent of this."""
    (tmp_path / "cards").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bwl, "CARDS", tmp_path / "cards")
    return tmp_path


def _write_card(root: Path, card_id: str, declares: list[str]) -> None:
    (root / "cards").mkdir(parents=True, exist_ok=True)
    (root / "cards" / f"{card_id}.card.yaml").write_text(
        yaml.safe_dump(
            {"card_id": card_id, "required_inputs": [{"product_id": d} for d in declares]},
            sort_keys=False,
        )
    )


# ---------------------------------------------------------------------------
# clean baseline
# ---------------------------------------------------------------------------
def test_healthy_snapshot_passes_hermetic(empty_cards):
    assert bwl.self_check_hermetic(_healthy_snap()) == []


# ---------------------------------------------------------------------------
# partition — mutation-proved teeth, positive and negative
# ---------------------------------------------------------------------------
def test_overlap_between_read_and_dark_reds(empty_cards):
    snap = _healthy_snap()
    snap["dark"].append(snap["read"][0])  # same id in two statuses
    snap["counts"]["dark"] += 1
    snap["n_catalog_datasets"] += 1
    errs = bwl.self_check_hermetic(snap)
    assert any("not disjoint" in e and "read" in e and "dark" in e for e in errs), errs


def test_partition_sum_mismatch_reds(empty_cards):
    snap = _healthy_snap()
    snap["dark"].pop()  # drop an id without touching the universe count
    errs = bwl.self_check_hermetic(snap)
    assert any("partition broken" in e for e in errs), errs


def test_count_hand_edit_reds(empty_cards):
    snap = _healthy_snap()
    snap["counts"]["dark"] = snap["counts"]["dark"] - 1  # count no longer matches the list length
    errs = bwl.self_check_hermetic(snap)
    assert any("counts.dark" in e for e in errs), errs


# ---------------------------------------------------------------------------
# floors — trip an empty / all-dark / read-oracle-broke run
# ---------------------------------------------------------------------------
def test_floor_trips_on_tiny_universe(empty_cards):
    snap = _snap([f"r{i}" for i in range(60)], [], [], universe=60)  # 60 < 400
    errs = bwl.self_check_hermetic(snap)
    assert any("vacuous" in e and "n_catalog_datasets" in e for e in errs), errs


def test_floor_trips_when_read_side_empty(empty_cards):
    # universe healthy but the reads oracle found ~nothing -> everything looks dark.
    snap = _snap([], [f"d{i}" for i in range(450)], [f"x{i}" for i in range(50)])
    errs = bwl.self_check_hermetic(snap)
    assert any("vacuous" in e and "read datasets" in e for e in errs), errs


def test_floor_trips_when_everything_dark(empty_cards):
    snap = _snap([f"r{i}" for i in range(60)], [], [f"x{i}" for i in range(60)], universe=60)
    errs = bwl.self_check_hermetic(snap)
    assert any("dark=" in e and "nothing is wired" in e for e in errs), errs


# ---------------------------------------------------------------------------
# declaration drift — the one in-repo signal the hermetic half CAN see (no sibling)
# ---------------------------------------------------------------------------
def test_declaring_a_committed_dark_id_reds(empty_cards):
    snap = _healthy_snap()
    victim = snap["dark"][0]
    # POSITIVE: no card declares it -> clean
    assert bwl.self_check_hermetic(snap) == []
    # a card is edited to declare the dark id -> the hermetic half reds (must regenerate to move it)
    _write_card(empty_cards, "c", [victim])
    errs = bwl.self_check_hermetic(snap)
    assert any("declaration drift" in e and victim in e for e in errs), errs


def test_declaring_a_non_dark_id_does_not_red(empty_cards):
    # NEGATIVE control: declaring an id that is already `read` is not drift (it is expected).
    snap = _healthy_snap()
    _write_card(empty_cards, "c", [snap["read"][0]])
    assert bwl.self_check_hermetic(snap) == []


# ---------------------------------------------------------------------------
# pins on the real artifact
# ---------------------------------------------------------------------------
def test_committed_snapshot_passes_hermetic():
    """The committed ledger must pass the hermetic gate against today's real cards — the CI
    --self-check assertion, mirrored as a red-able test. No siblings needed."""
    snap = yaml.safe_load(bwl.SNAPSHOT_PATH.read_text())
    assert bwl.self_check_hermetic(snap) == []


def test_committed_snapshot_has_expected_shape():
    """Pin the measured status counts so a silent extractor regression that shifts the numbers is a
    red test, not an invisible re-baseline. Ranges, not exact values, so a legitimate wiring PR that
    moves a handful of datasets does not force a churn edit here — only a large drift reds."""
    snap = yaml.safe_load(bwl.SNAPSHOT_PATH.read_text())
    c = snap["counts"]
    assert snap["n_catalog_datasets"] == c["read"] + c["declared_only"] + c["dark"]
    assert c["read"] >= bwl.MIN_READ_DATASETS
    assert c["dark"] < snap["n_catalog_datasets"]
    # dark is the I.4 worklist; it should be a real, non-empty backlog on landing (measured 139).
    assert c["dark"] > 0


@pytest.mark.skipif(
    not bwl.wr._siblings_available(),
    reason="analysis-methods / skills / data-catalog siblings absent (checkout-only CI)",
)
def test_live_recompute_matches_committed():
    # self_check_live recomputes the whole ledger and diffs it; a null diff proves the committed
    # read/declared_only/dark sets match the methods + catalog on disk today.
    committed = yaml.safe_load(bwl.SNAPSHOT_PATH.read_text())
    live_errs, skipped = bwl.self_check_live(committed)
    assert skipped is None and live_errs == [], live_errs
