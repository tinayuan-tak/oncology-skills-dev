#!/usr/bin/env python3
"""eval/loop/findings.py — the subskill-iteration loop's FINDINGS LEDGER (SK#2303 WI-E, #2358).

Durable, append-only, hash-chained record of every finding that survives the propose-only triangulation
judge (``critic/judge.py``, #2355) + the containment guard (``critic/containment.py``, #2356). This is
the memory a coordinator (and ``tiers.py``, this same issue) acts on: it is append-only (no entry is ever
edited or deleted), tamper-evident (each entry's hash is chained over the previous entry's hash — mutate
or reorder/delete/insert ANY entry and :func:`verify_chain` detects the break), deduplicated (the SAME
finding recurring across loop iterations collapses to one ledger entry with a bumped ``seen`` count,
never a growing chain of identical entries), and severity-tagged.

Index on the PROPERTY-LAYER delta, never the verdict (SK#2091). Both the dedup key
(:func:`dedup_key`) and the severity (:func:`severity_of`) are derived from a finding's ``kind`` +
``target`` + its sorted ``datum_refs`` — the structural claim's identity — never from any verdict field.
A Tier-2/3 adjudication therefore always resolves a PROPERTY-DELTA matrix, never a verdict-flip matrix.

Dedup design note: a repeat finding does NOT get a new hash-chain entry (that would force rewriting a
past entry's ``payload.seen``, which is itself tamper — this ledger never mutates a past entry). Instead
``Ledger.append`` recognises the repeat by its dedup key, returns the ORIGINAL entry unchanged, and bumps
an out-of-chain ``seen`` counter. The chain only ever grows at the tail, and only for genuinely new
findings — that is what keeps hash-chain verification meaningful.

No ``__init__.py`` here (the ``eval/`` convention — a bare sys.path import, see ``critic/judge.py``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

SCHEMA_VERSION = "1.0"

# The hash chain's root — the "previous hash" of entry 0. 64 '0's, the same width as a sha256 hexdigest,
# so a chain of length 1 is verified by the exact same comparison as every later entry.
GENESIS_HASH = "0" * 64

# ── severity ─────────────────────────────────────────────────────────────────────────────────────────
# Severity is a property of the finding's STRUCTURAL KIND — what sort of claim it is about the property
# layers — never of any verdict it might (incorrectly) be read to imply. S1 = highest / most load-bearing.
SEVERITY_BY_KIND: dict[str, str] = {
    "class_not_supported_by_datum": "S1",  # a class/token label the raw datum contradicts
    "divergence": "S1",  # the three judge views disagree
    "missing_relationship": "S2",
    "regroup_arms": "S2",
    "new_family": "S2",
    "surface_unused_signal": "S3",  # computed but unsurfaced — lowest-stakes, most mechanical
    "unstructured": "S3",
}
DEFAULT_SEVERITY = "S3"
_SEVERITY_ORDER = ("S1", "S2", "S3")


def severity_of(finding: dict) -> str:
    """The severity of ONE finding, keyed on its ``kind`` (never its verdict implication)."""
    kind = finding.get("kind") if isinstance(finding, dict) else None
    return SEVERITY_BY_KIND.get(kind, DEFAULT_SEVERITY)


def severity_rank(severity: str) -> int:
    """Lower rank = higher severity (S1 → 0), for sorting; an unknown severity sorts last."""
    try:
        return _SEVERITY_ORDER.index(severity)
    except ValueError:
        return len(_SEVERITY_ORDER)


# ── dedup key ────────────────────────────────────────────────────────────────────────────────────────
def dedup_key(finding: dict) -> str:
    """Stable dedup key for ONE finding: ``kind`` + ``target`` + the SORTED ``datum_refs`` — the
    finding's property-layer identity. Deliberately excludes ``finding`` / ``why`` prose (two judge calls
    phrase the identical structural claim differently — prose must never defeat dedup) and excludes any
    verdict field (SK#2091: dedup never indexes on the verdict)."""
    if not isinstance(finding, dict):
        return hashlib.sha256(b"\x00invalid-finding").hexdigest()
    kind = str(finding.get("kind", ""))
    target = str(finding.get("target", ""))
    refs = finding.get("datum_refs") or []
    refs_sorted = sorted(str(r) for r in refs if isinstance(r, (str, int, float)))
    payload = json.dumps({"kind": kind, "target": target, "datum_refs": refs_sorted}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── canonical payload + hash chain ──────────────────────────────────────────────────────────────────
def _canonical(payload: dict) -> str:
    """Deterministic JSON rendering of a payload — sorted keys, stable float/str coercion via
    ``default=str`` — so the SAME payload always hashes to the SAME value (determinism requirement)."""
    return json.dumps(payload, sort_keys=True, default=str)


def _entry_hash(prev_hash: str, payload: dict) -> str:
    """One hash-chain link: sha256(prev_hash || canonical(payload)). Chaining on ``prev_hash`` is what
    makes the structure a CHAIN (not just a per-entry checksum) — reordering, deleting, or inserting an
    entry changes some downstream ``prev_hash`` and so breaks verification from that point on."""
    return hashlib.sha256((prev_hash + _canonical(payload)).encode("utf-8")).hexdigest()


def _finding_payload(finding: dict, *, severity: str, dedup_key_: str) -> dict:
    """The exact fields committed into the hash chain for ONE finding — a frozen snapshot, never the
    live dict (a caller mutating their own ``finding`` dict after append must not retroactively change
    what was committed)."""
    return {
        "kind": finding.get("kind"),
        "target": finding.get("target"),
        "finding": finding.get("finding"),
        "why": finding.get("why"),
        "datum_refs": sorted(str(r) for r in (finding.get("datum_refs") or [])),
        "severity": severity,
        "dedup_key": dedup_key_,
    }


@dataclass
class Ledger:
    """An append-only, hash-chained, deduplicated findings ledger.

    ``entries`` is the ordered list of committed ledger entries, each
    ``{"seq", "prev_hash", "hash", "payload"}``. Construct empty (``Ledger()``) to start a fresh chain,
    or ``Ledger(entries=persisted_entries)`` to RESUME a chain a prior loop iteration persisted — a
    resumed ledger's dedup state is rebuilt from the loaded entries, so a finding seen in a PRIOR
    iteration still collapses in this one."""

    entries: list = field(default_factory=list)
    _by_dedup: dict = field(default_factory=dict, repr=False, compare=False)
    _seen_counts: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_dedup: dict[str, int] = {}
        seen_counts: dict[str, int] = {}
        for e in self.entries:
            dk = (e.get("payload") or {}).get("dedup_key")
            if dk is not None:
                by_dedup[dk] = e.get("seq")
                seen_counts[dk] = max(seen_counts.get(dk, 1), int(e.get("seen_count", 1)))
        self._by_dedup = by_dedup
        self._seen_counts = seen_counts

    @property
    def head_hash(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS_HASH

    def __len__(self) -> int:
        return len(self.entries)

    def append(self, finding: dict) -> dict:
        """Append ONE finding. A REPEAT (same dedup key as an existing entry) does NOT grow the chain —
        it returns the original entry (augmented with ``duplicate=True`` and the bumped ``seen`` count)
        unchanged; the stored entry's hash is never recomputed. A genuinely NEW finding is committed as a
        new tail entry chained off ``head_hash``."""
        if not isinstance(finding, dict):
            raise TypeError("finding must be a dict")
        dk = dedup_key(finding)
        if dk in self._by_dedup:
            seq = self._by_dedup[dk]
            self._seen_counts[dk] = self._seen_counts.get(dk, 1) + 1
            entry = self.entries[seq]
            return {**entry, "duplicate": True, "seen": self._seen_counts[dk]}

        severity = severity_of(finding)
        payload = _finding_payload(finding, severity=severity, dedup_key_=dk)
        prev_hash = self.head_hash
        h = _entry_hash(prev_hash, payload)
        entry = {"seq": len(self.entries), "prev_hash": prev_hash, "hash": h, "payload": payload, "seen_count": 1}
        self.entries.append(entry)
        self._by_dedup[dk] = entry["seq"]
        self._seen_counts[dk] = 1
        return {**entry, "duplicate": False, "seen": 1}

    def extend(self, findings: "Iterable[dict]") -> "list[dict]":
        """Append each of ``findings`` in order; returns the per-finding append results."""
        return [self.append(f) for f in findings]

    def verify(self) -> dict:
        return verify_chain(self.entries)

    def to_jsonable(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "entries": self.entries}


def verify_chain(entries: "list[dict]") -> dict:
    """Recompute the hash chain over ``entries`` from genesis and report whether it is intact.

    Returns ``{"ok": bool, "break_at": seq|None, "reason": str|None}``. ANY of the following breaks
    verification at (or before) the offending entry — this is the ledger's tamper-evidence property:
      - an entry's ``seq`` is out of order (an entry deleted, inserted, or reordered),
      - an entry's stored ``prev_hash`` does not match the hash of the entry that actually precedes it,
      - an entry's stored ``hash`` does not match the hash RECOMPUTED from its own ``prev_hash`` +
        ``payload`` (the entry's payload was mutated after the fact — the tamper this ledger exists to
        catch)."""
    prev_hash = GENESIS_HASH
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            return {"ok": False, "break_at": i, "reason": "entry is not an object"}
        if e.get("seq") != i:
            return {"ok": False, "break_at": i, "reason": f"out-of-order seq (expected {i}, got {e.get('seq')!r})"}
        if e.get("prev_hash") != prev_hash:
            return {"ok": False, "break_at": i, "reason": "stored prev_hash does not match the running chain"}
        expected = _entry_hash(prev_hash, e.get("payload") or {})
        if e.get("hash") != expected:
            return {
                "ok": False,
                "break_at": i,
                "reason": "stored hash does not match the recomputed hash (tampered entry)",
            }
        prev_hash = e["hash"]
    return {"ok": True, "break_at": None, "reason": None}


# ── persistence (optional convenience — the ledger is equally usable in-memory, e.g. in tests) ───────
def load_ledger(path: "Path | str") -> Ledger:
    """Load a persisted ledger JSON file; a MISSING file is a fresh, empty ledger (the first iteration
    of a loop has nothing to resume)."""
    p = Path(path)
    if not p.exists():
        return Ledger()
    data = json.loads(p.read_text())
    return Ledger(entries=list(data.get("entries") or []))


def save_ledger(ledger: Ledger, path: "Path | str") -> None:
    Path(path).write_text(json.dumps(ledger.to_jsonable(), indent=1, default=str))


# ── CLI (manual inspection — never reached by the test suite) ─────────────────────────────────────────
def _cli(argv: "Optional[list[str]]" = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify a persisted findings ledger's hash chain.")
    parser.add_argument("ledger_path", help="path to a ledger JSON file (see save_ledger)")
    args = parser.parse_args(argv)

    ledger = load_ledger(args.ledger_path)
    result = ledger.verify()
    print(f"=== findings ledger: {args.ledger_path} ===")
    print(f"  entries: {len(ledger)}")
    print(f"  chain intact: {result['ok']}")
    if not result["ok"]:
        print(f"  BROKEN at entry {result['break_at']}: {result['reason']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
