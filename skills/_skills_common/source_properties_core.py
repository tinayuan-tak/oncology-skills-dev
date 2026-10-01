"""source_properties_core — the SHARED machinery behind the NAMED, typed L2a `source_properties` map.

WHAT THIS IS: the skill-agnostic extraction of the three copy-pasted source-property clusters that the
presence / safety / dependency claim modules each carried (the code's own comments documented the copy
lineage). Three pieces, formerly re-declared per module and drifting only in a skill constant + the
recipe/scale tables:

  * `reach_map(skill, skills_root)` — {(card_id, field): interpretation_reach} read off a skill's
    field-disposition ledger (the SECOND disposition axis, SK#1525). Empty when the ledger is absent or
    declares the axis on no row, so anchor typing stays additive/byte-stable where the source is missing.
  * `typed_anchor(card_id, field, value, scale_map, skill, skills_root)` — one retained quantitative
    anchor {field, value, scale} plus the ledger-declared disposition typing (`semantic_role` via the
    role axis, `interpretation_reach` via the reach axis). Typing keys are OMITTED when the ledger does
    not classify the field, so the anchor never fabricates a disposition it cannot source.
  * `build_source_properties(cards, recipes, …)` — the recipe loop: one entry per source/grain, lifting
    the per-source observational properties out of the claim signal blocks into an explicit, recoverable
    object. Returns None when no source resolves (whole key omitted → byte-stable), matching the atom
    discipline on every claim vector.

THE DISCIPLINE (unchanged from the three originals): pure projection, VERDICT-INERT (SK#2091) — carries
no signal tier, feeds no rule/resolver/gate/ladder. A source with no card / no resolved observational
class emits no entry; a partial card keeps the run byte-stable. The per-domain shape differences
(whether `property_field`/`context`/`reliability` are emitted, the optional per-entry `interpretation`
provenance, and any per-recipe `entry_extra`) are passed in by the calling module, so the output stays
byte-identical to the hand-rolled originals.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Callable, Optional, Sequence

from _skills_common.reliability import _derive_reliability


@functools.lru_cache(maxsize=None)
def reach_map(skill: str, skills_root: "str | None" = None) -> dict:
    """{(card_id, field): interpretation_reach} for ``skill``'s field-disposition ledger — the SECOND
    disposition axis (SK#1525), read-only, sourced the same way `role_for` sources the first axis.

    Returns {} when the ledger is absent or declares the reach axis on no row, so anchor typing stays
    additive/byte-stable where the source is missing (the mechanism is wired anyway and proven by a test
    pointing it at a ledger that DOES declare it, so anchors type themselves the day a ledger gains reach
    rows)."""
    from _skills_common.field_disposition_contract import INTERPRETATION_REACH
    from _skills_common.field_disposition_ledger import (
        LEDGER_NAME,
        _default_skills_root,
        iter_rows,
        load_ledger,
    )

    root = Path(skills_root) if skills_root else _default_skills_root()
    path = root / skill / LEDGER_NAME
    if not path.exists():
        return {}
    doc = load_ledger(path)
    return {
        (cid, field): spec["interpretation_reach"]
        for cid, field, spec in iter_rows(doc)
        if spec.get("interpretation_reach") in INTERPRETATION_REACH
    }


def typed_anchor(card_id, field, value, scale_map: dict, skill: str, *, skills_root=None):
    """One retained quantitative anchor: {field, value, scale} + the ledger-declared disposition typing
    (semantic_role via the role axis, interpretation_reach via the reach axis, #1525) when ``skill``'s
    ledger declares them. Typing keys are OMITTED when the ledger does not classify the field, so the
    anchor never fabricates a disposition it cannot source."""
    from _skills_common.field_disposition_ledger import role_for

    anchor = {"field": field, "value": value, "scale": scale_map.get(field, "raw")}
    role = role_for(card_id, field, skill, skills_root=Path(skills_root) if skills_root else None)
    if role is not None:
        anchor["semantic_role"] = role
    reach = reach_map(skill, skills_root).get((card_id, field))
    if reach is not None:
        anchor["interpretation_reach"] = reach
    return anchor


def build_source_properties(
    cards: dict,
    recipes: Sequence[dict],
    *,
    anchor_scale: dict,
    skill: str,
    skills_root=None,
    headline: Optional[dict] = None,
    interpretation_fns: Optional[dict] = None,
    include_property_field: bool = True,
    include_context: bool = True,
    include_reliability: bool = True,
    entry_extra: Optional[Callable[[dict, dict, dict], None]] = None,
) -> "dict | None":
    """The NAMED, typed L2a source_properties map: one entry per source/grain, lifting the per-source
    observational properties out of a vector's claim signal blocks into an explicit, recoverable object.
    Returns None when no source resolves (whole key omitted → byte-stable). Pure projection,
    verdict-inert, carries no signal tier.

    ``cards`` is the cards-by-id map; ``recipes`` the per-domain recipe table; ``anchor_scale`` the
    per-domain {field: scale} map; ``skill`` the ledger-owning skill. Per-domain shape differences are
    passed in so the output stays byte-identical to the three hand-rolled originals:
      * include_property_field — emit the `property_field` key (presence omits it);
      * include_context        — emit the `context` map of retained categorical qualifiers;
      * include_reliability    — emit the typed `reliability` facet (#2306) from each recipe's spec;
      * interpretation_fns     — {recipe name: fn(headline)->dict} for the entries whose class token is
                                 produced through a multi-arm disjunction (safety's normal-tissue arm);
      * entry_extra(recipe, summ, entry) — a per-domain hook mutating the entry in place (presence's
                                 resolved `expression_properties` passthrough). Appended last.
    Key insertion ORDER is part of the byte output and matches each original exactly."""
    out: dict = {}
    for recipe in recipes:
        summ = cards.get(recipe["card_id"], {}) or {}
        prop = summ.get(recipe["property_field"])
        # A source with no card / no resolved observational class emits no entry (byte-stable).
        if not prop or prop == "data_unavailable":
            continue
        anchors = [
            typed_anchor(recipe["card_id"], f, summ[f], anchor_scale, skill, skills_root=skills_root)
            for f in recipe["anchors"]
            if summ.get(f) is not None
        ]
        entry: dict = {"card_id": recipe["card_id"]}
        # The L1 card field the class token was read from — NAMED on the entry so every entry
        # reconstructs to L1 as {card_id, property_field, property}.
        if include_property_field:
            entry["property_field"] = recipe["property_field"]
        entry["property"] = prop
        entry["anchors"] = anchors
        entry["comparability"] = dict(recipe["comparability"])
        # Retained categorical qualifiers that orient the anchors without being quantities themselves.
        # OMITTED entirely when the card supplies none, keeping a partial-card run byte-stable.
        if include_context:
            context = {f: summ[f] for f in recipe["context"] if summ.get(f) is not None}
            if context:
                entry["context"] = context
        if interpretation_fns:
            interp_fn = interpretation_fns.get(recipe["name"])
            if interp_fn is not None:
                entry["interpretation"] = interp_fn(headline)
        # The typed `reliability` facet (#2306 step 2): a PURE projection over the entry's OWN retained
        # anchors + this recipe's n-anchor spec. Verdict-inert (SK#2091). See _skills_common/reliability.py.
        if include_reliability:
            entry["reliability"] = _derive_reliability(entry["anchors"], recipe["reliability"])
        if entry_extra is not None:
            entry_extra(recipe, summ, entry)
        out[recipe["name"]] = entry
    return out or None


__all__ = ["reach_map", "typed_anchor", "build_source_properties"]
