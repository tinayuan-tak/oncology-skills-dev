#!/usr/bin/env python3
"""validate_card_resolver_consumption.py — card ↔ resolver verdict-role reconciliation.

WHY (cards review 2026-08-17, S2 contract-drift class): the framework's most pervasive S2 defect is
cards MISLABELLING their own verdict role in PROSE (comments/caveats), in BOTH directions:
  - `mutation-drug-response` states 3× "VERDICT-INERT … no resolver rung", but its
    `mutation-drug-response-strongly-sensitive-supportive` rule IS a rung in genomic_alteration.resolver
    (→ verdict `drug_response_biomarker`);
  - `genomic-event-model-match` labels its class "drives Tier-2 rules", `phospho-pathway-activity`
    claims "ROUTES INTO GATES", `mutation-hotspot-frequency` was assumed verdict-driving — all three are
    consumed by NO resolver rung (verdict-INERT).
Prose is not machine-checked, so these silently drift. The existing validators cover adjacent
dimensions — validate_interpretation_rules (rule→card field/vocab reachability), validate_resolvers
(no dangling rungs), validate_verdict_tokens (gate↔resolver tokens) — but NONE computes whether a
card is actually verdict-bearing via a resolver. This validator does, and pins the answer in a
committed snapshot so a change in any card's resolver-consumption fails CI (conscious update), and the
snapshot itself is the authoritative "which cards drive a verdict" map the prose kept getting wrong.

SCOPE / semantics: "resolver_consumed" = at least one interpretation-rule whose `when.card_id` is this
card is referenced by some resolver rung (when_fired / when_any_fired / when_all_fired). This is the
RESOLVER-verdict dimension. A card can ALSO influence a verdict via skill-layer Python (e.g. the
tumor-presence rank ladder, the selectivity post-resolver clamp, the tractability degrader lens) — that
is a DIFFERENT dimension not captured here (and not statically checkable from target-contracts alone);
so `resolver_consumed: false` means "not consumed by a resolver rung", NOT "verdict-inert everywhere".

Usage:
    python validators/validate_card_resolver_consumption.py            # validate vs snapshot (CI)
    python validators/validate_card_resolver_consumption.py --write    # regenerate the snapshot

Exit: 0 = matches snapshot; 1 = drift (a card gained/lost resolver consumption) or missing snapshot.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO / "cards"
RULES_DIR = REPO / "interpretation-rules"
RESOLVERS_DIR = REPO / "resolvers"
SNAPSHOT = REPO / "coverage" / "card_resolver_consumption.yaml"

_RUNG_KEYS = ("when_fired", "when_any_fired", "when_all_fired")


def _load(path: Path):
    return yaml.safe_load(path.read_text())


def card_ids() -> set[str]:
    out = set()
    for f in sorted(CARDS_DIR.glob("*.card.yaml")):
        spec = _load(f)
        if isinstance(spec, dict) and spec.get("card_id"):
            out.add(spec["card_id"])
    return out


def rule_to_card() -> dict[str, str]:
    """rule_id -> card_id (from `when.card_id`). Rules without a simple card_id are skipped
    (composed/multi-condition rules don't attribute to a single card)."""
    m: dict[str, str] = {}
    for f in sorted(RULES_DIR.glob("*.rules.yaml")):
        doc = _load(f)
        rules = doc.get("rules", doc) if isinstance(doc, dict) else doc
        for r in (rules or []):
            if not isinstance(r, dict) or not r.get("rule_id"):
                continue
            when = r.get("when") or {}
            cid = when.get("card_id") if isinstance(when, dict) else None
            if cid:
                m[r["rule_id"]] = cid
    return m


def resolver_referenced_rules() -> dict[str, set[str]]:
    """rule_id -> set of resolver gate names that reference it in a rung."""
    ref: dict[str, set[str]] = {}
    for f in sorted(RESOLVERS_DIR.glob("*.resolver.yaml")):
        doc = _load(f)
        gate = (doc.get("gate") if isinstance(doc, dict) else None) or f.stem
        for rung in (doc.get("resolve") or []):
            for k in _RUNG_KEYS:
                v = rung.get(k)
                ids = [v] if isinstance(v, str) else list(v or [])
                for rid in ids:
                    ref.setdefault(rid, set()).add(gate)
    return ref


def compute() -> dict:
    r2c = rule_to_card()
    ref = resolver_referenced_rules()
    detail: dict[str, dict] = {}
    for rid, gates in ref.items():
        cid = r2c.get(rid)
        if not cid:
            continue  # rule existence/linkage is guarded by validate_resolvers / validate_interpretation_rules
        d = detail.setdefault(cid, {"resolvers": set(), "rules": set()})
        d["resolvers"] |= gates
        d["rules"].add(rid)
    consumed = {
        cid: {"resolvers": sorted(d["resolvers"]), "rules": sorted(d["rules"])}
        for cid, d in detail.items()
    }
    return {
        "resolver_consumed_cards": sorted(consumed),
        "detail": {k: consumed[k] for k in sorted(consumed)},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="regenerate the committed snapshot")
    args = ap.parse_args()

    current = compute()
    # sanity: every consumed card must be a real card_id
    known = card_ids()
    unknown = [c for c in current["resolver_consumed_cards"] if c not in known]
    if unknown:
        print(f"ERROR: resolver consumes rules keyed on unknown card_id(s): {unknown}", file=sys.stderr)
        return 1

    header = (
        "# AUTO-GENERATED by validators/validate_card_resolver_consumption.py — do not hand-edit.\n"
        "# The authoritative card->resolver-consumption (verdict-role) map. `resolver_consumed_cards`\n"
        "# lists every card at least one of whose rules feeds a resolver rung (i.e. it can move a gate\n"
        "# VERDICT). A card NOT listed is verdict-inert AT THE RESOLVER layer (it may still feed a\n"
        "# skill-python verdict path — see the validator docstring). Regenerate with --write after a\n"
        "# CONSCIOUS review whenever a card gains/loses resolver consumption.\n"
    )
    if args.write:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(header + yaml.safe_dump(current, sort_keys=False))
        print(f"wrote snapshot: {SNAPSHOT} ({len(current['resolver_consumed_cards'])} consumed cards)")
        return 0

    if not SNAPSHOT.exists():
        print(f"ERROR: snapshot missing at {SNAPSHOT}; run with --write.", file=sys.stderr)
        return 1
    committed = _load(SNAPSHOT) or {}
    cur_set = set(current["resolver_consumed_cards"])
    com_set = set(committed.get("resolver_consumed_cards") or [])
    if cur_set != com_set:
        gained = sorted(cur_set - com_set)
        lost = sorted(com_set - cur_set)
        print("ERROR: card->resolver consumption DRIFTED from the committed snapshot.", file=sys.stderr)
        if gained:
            print(f"  NEWLY resolver-consumed (a card became verdict-bearing): {gained}", file=sys.stderr)
        if lost:
            print(f"  NO LONGER resolver-consumed (a card's verdict rung went dead?): {lost}", file=sys.stderr)
        print("  If intended, regenerate: python validators/validate_card_resolver_consumption.py --write",
              file=sys.stderr)
        return 1
    print(f"OK: {len(cur_set)} resolver-consumed cards match the committed snapshot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
