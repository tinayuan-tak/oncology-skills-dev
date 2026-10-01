#!/usr/bin/env python3
"""eval/loop/tiers.py — the subskill-iteration loop's TIER ROUTER (SK#2303 WI-E, #2358).

Routes each CONTAINED finding — a finding that already survived the propose-only judge
(``critic/judge.py``, #2355) AND the containment guard (``critic/containment.py``, #2356; only its
``contained`` list is ever offered here, never ``dropped``/``demoted``) — into exactly one of three
tiers:

  **T1** ``land``        auto-land: additive-only, in-scope, mechanical, no frozen symbol touched, AND
                          the caller has confirmed the judge teeth (#2357) + containment guard (#2356)
                          are green (``teeth_green=True``). Until a caller passes that, EVERY otherwise
                          T1-eligible finding is downgraded to T2 — report-only (plan STOP-A: "nothing
                          routes to T1 until the teeth are green").
  **T2** ``propose``     file a propose-only issue; a human adjudicates.
  **T3** ``adjudicate``  build an adjudication packet. Thresholds are FROZEN — this module never moves a
                          cut, it only files the packet for a human to decide.

**The frozen-symbol denylist is the one hard veto.** A finding whose ``target`` / ``finding`` / ``why``
prose or ``datum_refs`` names a symbol in ``frozen_symbols.yaml`` (a threshold, an enum value, or an
identity key — see that file) is ALWAYS forced to T3, no matter how additive or mechanical it otherwise
looks, and regardless of ``teeth_green``. This is the module's mutation tooth: skip
:func:`touches_frozen_symbol` (or pass an empty denylist) and a finding proposing to rename an enum value
or move a threshold would wrongly land at T1 — ``test_tiers.py`` asserts the denylist check is what
prevents that, not an accident of which ``kind`` the finding carries.

Routing never reasons about the VERDICT (SK#2091) — only about a finding's structural ``kind`` and the
SYMBOLS its prose/refs name. Additive-only, never-rename: the two T1-eligible kinds
(:data:`T1_ELIGIBLE_KINDS`) are both strictly ADDITIVE proposals (surface an unused signal / add a
missing concordance family) — a ``divergence`` or a ``class_not_supported_by_datum`` finding (which by
definition proposes to CHANGE an existing read) can never be T1 even if it names no frozen symbol.

No ``__init__.py`` here (the ``eval/`` convention — a bare sys.path import, see ``critic/judge.py``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

SCHEMA_VERSION = "1.0"

T1 = "T1_land"
T2 = "T2_propose"
T3 = "T3_adjudicate"

# Finding kinds that are structurally ADDITIVE / mechanical enough to be T1-eligible IN PRINCIPLE (still
# subject to the frozen-symbol veto and to teeth_green). Every other kind (divergence, regroup_arms,
# missing_relationship, class_not_supported_by_datum, unstructured) proposes to CHANGE an existing read
# or structure, so it always needs a human — T2 at best.
T1_ELIGIBLE_KINDS = frozenset({"surface_unused_signal", "new_family"})

_DEFAULT_DENYLIST_PATH = Path(__file__).resolve().parent / "frozen_symbols.yaml"

_DENYLIST_SECTIONS = ("thresholds", "enum_values", "identity_keys")

# A denylist symbol is matched as a whole lower-cased token (word-boundary), never a bare substring, so
# e.g. the symbol "token" (if ever added) would not accidentally match "token_key".
_WORD_RE = re.compile(r"[a-z0-9_]+")


def load_denylist(path: "Path | str | None" = None) -> frozenset:
    """Load the frozen-symbol denylist into one flat, lower-cased symbol set.

    FAIL-CLOSED: a missing/unreadable denylist file raises rather than silently behaving as "no frozen
    symbols" — a config file that failed to load is a config error, not evidence that nothing is frozen
    (the fail-open shape this loop must never take)."""
    p = Path(path) if path is not None else _DEFAULT_DENYLIST_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"frozen-symbol denylist not found at {p} — fail-closed: refusing to route any finding "
            "without it (a missing denylist is a config error, not 'no frozen symbols')."
        )
    doc = yaml.safe_load(p.read_text()) or {}
    symbols: set[str] = set()
    for key in _DENYLIST_SECTIONS:
        for s in doc.get(key) or []:
            symbols.add(str(s).strip().lower())
    return frozenset(symbols)


def _tokens(text: str) -> set:
    return set(_WORD_RE.findall(text.lower()))


def touches_frozen_symbol(finding: dict, denylist: "Iterable[str]") -> "Optional[str]":
    """Return the lexicographically-first frozen symbol ``finding`` touches, or ``None``.

    Checked across ``target`` / ``finding`` / ``why`` prose AND every ``datum_refs`` entry (a ref's dots
    and brackets are treated as token separators, e.g. ``l2b.corroboration`` tokenises to include
    ``corroboration``) — a finding that only NAMES a frozen field in its ref, without saying so in prose,
    must still be caught."""
    deny = frozenset(str(s).strip().lower() for s in denylist)
    if not deny:
        return None
    tokens: set = set()
    for key in ("target", "finding", "why"):
        tokens |= _tokens(str(finding.get(key, "")))
    for ref in finding.get("datum_refs") or []:
        if isinstance(ref, str) and ref.strip():
            tokens |= _tokens(ref.replace(".", " ").replace("[", " ").replace("]", " "))
    hit = tokens & deny
    return sorted(hit)[0] if hit else None


def route_finding(
    finding: dict,
    *,
    denylist: "Iterable[str] | None" = None,
    teeth_green: bool = False,
) -> dict:
    """Route ONE containment-survived finding into T1 / T2 / T3.

    ``denylist`` defaults to loading ``frozen_symbols.yaml``; pass an explicit iterable (e.g. in tests) to
    override. ``teeth_green`` must be explicitly set ``True`` by the caller once the judge planted-defect
    teeth (#2357) and the containment guard (#2356) are confirmed green in CI — this module has no way to
    verify that itself, so it defaults ``False`` (report-only, never T1) per STOP-A.

    Returns ``{"tier", "reason", "frozen_symbol", "kind"}``."""
    if not isinstance(finding, dict):
        raise TypeError("finding must be a dict")
    deny = load_denylist() if denylist is None else frozenset(str(s).strip().lower() for s in denylist)
    kind = finding.get("kind")

    frozen_hit = touches_frozen_symbol(finding, deny)
    if frozen_hit is not None:
        return {
            "tier": T3,
            "reason": f"touches frozen symbol '{frozen_hit}' — forced to adjudication, never T1",
            "frozen_symbol": frozen_hit,
            "kind": kind,
        }

    if kind not in T1_ELIGIBLE_KINDS:
        return {
            "tier": T2,
            "reason": f"kind {kind!r} is not additive-only/mechanical — propose for human adjudication",
            "frozen_symbol": None,
            "kind": kind,
        }

    if not teeth_green:
        return {
            "tier": T2,
            "reason": (
                "T1-eligible by shape (additive, no frozen symbol), but the judge+containment teeth are "
                "not confirmed green yet (STOP-A) — report-only until then"
            ),
            "frozen_symbol": None,
            "kind": kind,
        }

    return {
        "tier": T1,
        "reason": "additive-only, in-scope, mechanical, no frozen symbol touched, teeth green",
        "frozen_symbol": None,
        "kind": kind,
    }


def route_many(
    findings: "Iterable[dict]",
    *,
    denylist: "Iterable[str] | None" = None,
    teeth_green: bool = False,
) -> dict:
    """Route a whole batch of contained findings. Returns a report partitioning them by tier, each
    finding annotated with its routing decision under ``_tier``."""
    deny = load_denylist() if denylist is None else frozenset(str(s).strip().lower() for s in denylist)
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "teeth_green": teeth_green,
        T1: [],
        T2: [],
        T3: [],
    }
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        decision = route_finding(f, denylist=deny, teeth_green=teeth_green)
        out[decision["tier"]].append({**f, "_tier": decision})
    return out


# ── CLI (manual inspection — never reached by the test suite) ─────────────────────────────────────────
def _cli(argv: "Optional[list[str]]" = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Route a containment report's `contained` findings into T1/T2/T3.")
    parser.add_argument("containment_result_path", help="a containment.contain(...) JSON result")
    parser.add_argument("--teeth-green", action="store_true", help="confirm judge+containment teeth are green")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.containment_result_path).read_text())
    contained = data.get("contained") or []
    report = route_many(contained, teeth_green=args.teeth_green)
    print(f"=== tier routing: {args.containment_result_path} ===")
    print(f"  teeth_green={report['teeth_green']}  T1={len(report[T1])}  T2={len(report[T2])}  T3={len(report[T3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
