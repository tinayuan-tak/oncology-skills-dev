#!/usr/bin/env python3
"""Teeth for eval/loop/findings.py — the hash-chain findings ledger (SK#2303 WI-E, #2358).

Acceptance (issue #2358):
  - the hash chain detects a tampered/inserted entry (tamper-evidence);
  - dedup collapses a repeat finding (same finding across iterations never grows the chain).

Plus the determinism property (SCHEMA requires a deterministic chain) and the SK#2091 property-layer
indexing (dedup/severity never key on a verdict field).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]  # eval/loop
if str(_LOOP) not in sys.path:
    sys.path.insert(0, str(_LOOP))

import findings as F  # noqa: E402

_F1 = {
    "kind": "surface_unused_signal",
    "target": "L2b.protein_presence_concordance",
    "finding": "median_tpm is computed but never surfaced in the L3 story.",
    "why": "the datum is present on every arm but the story omits it.",
    "datum_refs": ["l2b.protein_presence_concordance.arms[rnaseq].datum.median_tpm"],
}
_F2 = {
    "kind": "divergence",
    "target": "L2b.abundance_concordance",
    "finding": "literature disagrees with the omics read.",
    "why": "key_divergence names a conflicting direction.",
    "datum_refs": ["l2b.abundance_concordance.corroboration"],
}


# ── hash chain: tamper-evidence ─────────────────────────────────────────────────────────────────────
def test_fresh_chain_verifies_ok():
    ledger = F.Ledger()
    ledger.append(_F1)
    ledger.append(_F2)
    result = ledger.verify()
    assert result["ok"] is True
    assert result["break_at"] is None


def test_tampered_payload_breaks_the_chain():
    """Mutating a committed entry's payload (the tamper this ledger exists to catch) must break
    verification — this is the module's mutation tooth: a ledger that recomputed nothing, or that
    recomputed the hash FROM the (now-tampered) payload instead of checking it against the STORED hash,
    would wrongly report 'ok'."""
    ledger = F.Ledger()
    ledger.append(_F1)
    ledger.append(_F2)
    assert ledger.verify()["ok"] is True

    tampered = copy.deepcopy(ledger.entries)
    tampered[0]["payload"]["finding"] = "a tampered claim nobody actually proposed."
    result = F.verify_chain(tampered)
    assert result["ok"] is False
    assert result["break_at"] == 0


def test_inserted_entry_breaks_the_chain():
    """An entry inserted/duplicated in the middle (never re-chained) breaks downstream prev_hash links."""
    ledger = F.Ledger()
    ledger.append(_F1)
    ledger.append(_F2)
    entries = copy.deepcopy(ledger.entries)
    injected = copy.deepcopy(entries[0])
    tampered = [entries[0], injected, entries[1]]
    # Fix up seq so the ONLY defect under test is the broken hash chain, not a trivially-caught seq gap.
    for i, e in enumerate(tampered):
        e["seq"] = i
    result = F.verify_chain(tampered)
    assert result["ok"] is False


def test_reordered_entries_break_the_chain():
    ledger = F.Ledger()
    ledger.append(_F1)
    ledger.append(_F2)
    entries = copy.deepcopy(ledger.entries)
    swapped = [entries[1], entries[0]]
    for i, e in enumerate(swapped):
        e["seq"] = i
    result = F.verify_chain(swapped)
    assert result["ok"] is False


def test_chain_is_deterministic_across_two_fresh_runs():
    """The SAME two findings appended in the SAME order to two independent fresh ledgers must produce
    the IDENTICAL head hash — the chain is a pure function of (prior chain, payload), never of wall-clock
    time or object identity."""
    l1, l2 = F.Ledger(), F.Ledger()
    l1.append(_F1)
    l1.append(_F2)
    l2.append(copy.deepcopy(_F1))
    l2.append(copy.deepcopy(_F2))
    assert l1.head_hash == l2.head_hash
    assert l1.entries == l2.entries


# ── dedup ────────────────────────────────────────────────────────────────────────────────────────────
def test_dedup_collapses_a_repeat_finding():
    """The identical finding appended twice (e.g. the same structural claim recurring across two loop
    iterations) must NOT grow the chain to length 2 — it collapses to one entry with seen=2."""
    ledger = F.Ledger()
    first = ledger.append(_F1)
    assert first["duplicate"] is False
    assert len(ledger) == 1

    second = ledger.append(copy.deepcopy(_F1))
    assert second["duplicate"] is True
    assert second["seen"] == 2
    assert len(ledger) == 1  # chain did NOT grow
    assert ledger.verify()["ok"] is True


def test_dedup_ignores_prose_rewording_but_not_a_real_structural_change():
    """Two findings with the SAME kind/target/datum_refs but DIFFERENT prose (two judge calls phrasing
    the identical claim differently) dedup to one entry; a genuinely different datum_ref is a NEW
    finding, not a dup."""
    reworded = dict(_F1, finding="this signal is computed but dropped from the narrative.")
    ledger = F.Ledger()
    ledger.append(_F1)
    result = ledger.append(reworded)
    assert result["duplicate"] is True
    assert len(ledger) == 1

    different = dict(_F1, datum_refs=["l2b.protein_presence_concordance.arms[ihc].datum.n_high"])
    ledger.append(different)
    assert len(ledger) == 2


def test_dedup_key_never_reads_a_verdict_field():
    """Two findings differing ONLY in a (hypothetical) verdict-shaped field must dedup identically — the
    key is built from kind/target/datum_refs alone (SK#2091: never index on the verdict)."""
    with_verdict_a = dict(_F1, synthesis_verdict="go")
    with_verdict_b = dict(_F1, synthesis_verdict="no-go")
    assert F.dedup_key(with_verdict_a) == F.dedup_key(with_verdict_b) == F.dedup_key(_F1)


# ── severity ─────────────────────────────────────────────────────────────────────────────────────────
def test_severity_by_kind():
    assert F.severity_of(_F2) == "S1"  # divergence
    assert F.severity_of(_F1) == "S3"  # surface_unused_signal
    assert F.severity_of({"kind": "totally_unknown_kind"}) == F.DEFAULT_SEVERITY


# ── resumed ledger ───────────────────────────────────────────────────────────────────────────────────
def test_resumed_ledger_still_dedups_against_persisted_entries():
    first_run = F.Ledger()
    first_run.append(_F1)
    resumed = F.Ledger(entries=copy.deepcopy(first_run.entries))
    result = resumed.append(copy.deepcopy(_F1))
    assert result["duplicate"] is True
    assert len(resumed) == 1


def test_save_and_load_ledger_round_trips(tmp_path):
    ledger = F.Ledger()
    ledger.append(_F1)
    ledger.append(_F2)
    path = tmp_path / "ledger.json"
    F.save_ledger(ledger, path)

    loaded = F.load_ledger(path)
    assert loaded.entries == ledger.entries
    assert loaded.verify()["ok"] is True

    # A missing file is a FRESH empty ledger, not an error.
    assert len(F.load_ledger(tmp_path / "does_not_exist.json")) == 0
