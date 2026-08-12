"""Counterfactual flip-analysis over the pure verdict resolver.

"How close was this verdict to flipping?" — computed by perturbing the SET of fired rule IDs
one rule at a time and re-running the *pure* ``resolve_verdict`` (resolver.py). This is bounded
uncertainty WITHOUT probability: no priors, no likelihoods, no independence assumption. It is a
deterministic function of (fired rules, resolver spec) — the same purity that lets the golden-oracle
migration assert spec==code byte-for-byte — so it is itself golden-snapshottable and reviewable
*as biology* ("this veto flips iff `non-dependent-killer` had not fired").

It is the shared substrate for the verdict-inert FRAGILITY facet in target-profile (a fragile
verdict — one a single plausible rule-toggle flips — is a low-confidence call), and it is strictly
READ-ONLY: it never mutates ``fired`` and never touches a verdict, a gate, or a recommendation.

SCAN DEPTH: v1 is a single-rule (distance-1) scan over ``resolver_referenced_rule_ids(gate)`` — the
exact set of rule IDs the resolver's rungs pattern-match, i.e. the only rules that can move the
verdict (every other fired rule is verdict-inert; toggling it is provably a no-op, so we skip it).
``robust`` therefore means "no single verdict-movable rule toggle flips the call", not "no
combination". A distance-k scan is a future extension; the honest label is carried in the output.
"""
from __future__ import annotations

from pathlib import Path

from .resolver import load_resolver, resolve_verdict
from .reachability import resolver_referenced_rule_ids


def flip_analysis(fired: list[dict], gate: str,
                  contracts_repo: Path | None = None) -> dict | None:
    """Single-rule flip scan for one gate's verdict.

    Args:
      fired: the sub-skill's fired-rules list (the shared ``fired_rules`` output — a list of
             ``{rule_id, ...}`` dicts). Not mutated.
      gate:  the resolver gate name (``resolvers/<gate>.resolver.yaml``), e.g. "dependency".
      contracts_repo: optional target-contracts root override (tests point this at a fixture).

    Returns a dict describing the base verdict + every single-rule toggle that flips it, or
    ``None`` if the gate has no resolver spec (the caller then treats the axis as flip-inapplicable,
    NOT as robust — mirroring reachability.py's "empty means cannot prove, not nothing" contract).

    Keys: ``gate, base_verdict, base_driver, n_relevant, n_flips, flip_fragility (=n_flips/
    n_relevant), robust (=n_flips==0), scan_depth ("single_rule"), flips: [{rule_id, present,
    to_verdict}]``. ``flip_fragility`` is 0.0 when there are no verdict-movable rules (a verdict
    with nothing to move it is not "uncertain" — it is unconditionally the default).
    """
    spec = load_resolver(gate, contracts_repo)
    if spec is None:
        return None
    relevant = sorted(resolver_referenced_rule_ids(gate, contracts_repo))
    base_verdict, base_driver = resolve_verdict(fired, spec)
    fired_ids = {r["rule_id"] for r in fired}

    flips: list[dict] = []
    for rid in relevant:
        if rid in fired_ids:
            toggled = [f for f in fired if f["rule_id"] != rid]
            present = True
        else:
            toggled = fired + [{"rule_id": rid}]
            present = False
        v, _ = resolve_verdict(toggled, spec)
        if v != base_verdict:
            flips.append({"rule_id": rid, "present": present, "to_verdict": v})

    n_relevant = len(relevant)
    return {
        "gate": gate,
        "base_verdict": base_verdict,
        "base_driver": base_driver,
        "n_relevant": n_relevant,
        "n_flips": len(flips),
        "flip_fragility": (len(flips) / n_relevant) if n_relevant else 0.0,
        "robust": len(flips) == 0,
        "scan_depth": "single_rule",
        "flips": flips,
    }
