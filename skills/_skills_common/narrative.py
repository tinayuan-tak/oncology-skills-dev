"""narrative.py — the shared per-verdict NARRATIVE assembler.

Interpretability layer: the resolver distils cards -> fired rules -> a single verdict TOKEN + one
``driving_rule_id``. That token is thin (it discards the traversal that produced it) and abstract
(the rule_id is opaque). This module re-materialises the traversal the resolver already performed
but threw away, as a deterministic, VERDICT-INERT ``narrative`` object that both the HTML renderer
and the Tier-3 LLM synthesis consume as a single source of truth:

  * movers          — the fired rules that SET the verdict (the winning driver + the other
                      resolver-referenced rules present that pull the same way).
  * dissenters      — fired rules whose per-channel signal OPPOSES the resolved direction but lost
                      the ladder ("HOLD *despite* the reassuring tolerant-safety signal").
  * flip_conditions — the single-rule counterfactuals (from flip_analysis / the composed fragility
                      facet): "this verdict flips iff <rule> toggles -> <to_verdict>".
  * gaps            — what we don't know (ignorance != negation); injected by the composed layer
                      from the fragility facet's acquisition_backlog / underpowered_axes.
  * rule_sentences  — the human sentence for every cited rule_id (fired OR not), via
                      rules_loader.rule_text_index — so a counterfactual flip rule is captioned too.

Design constraints:
  * READ-ONLY / verdict-INERT — never mutates ``fired``, never touches a verdict/gate/recommendation.
    It is a projection over already-computed inputs (fired rules, the resolver, flip_analysis).
  * DETERMINISTIC — every list is sorted by a stable key, so the object is golden-snapshottable.
  * NOT a field on the factored claim_record — the claim_record is under the byte-stable
    render_verdict(record) == token contract (M2); an interpretation projection does not belong on
    ρ(record). This lives beside headline/claim_record_shadow in decision.json, and beside
    fragility/claim_record_shadow (as narrative_by_axis) in nomination.json.

The dissenter valence is read from the DRIVING rule's own per-channel ``signals`` (the sign the
winning rung expresses per modality channel). A fired non-driver rule that expresses the opposite
sign on a channel dissents on that channel — self-contained, no external decision-role vocabulary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .flip_analysis import flip_analysis
from .reachability import resolver_referenced_rule_ids
from .rules_loader import rule_text_index

# Per-channel signal -> sign. supportive pulls +, opposing/killer pull -, neutral/insufficient/absent
# are directionless (0) and never make a rule a mover or a dissenter on their own.
_SIGN = {"supportive": 1, "opposing": -1, "killer": -1, "neutral": 0, "insufficient": 0}


def _sign(signal) -> int:
    return _SIGN.get(signal, 0)


def _sentence_for(rid, text_index, fired_by_id):
    """(rationale, killer_message, card_id) for a rule_id — preferring the fired record's inline
    text (present for rules that fired) and falling back to the global rule_text_index (the only
    source for a counterfactual/display rule that never fired)."""
    fr = fired_by_id.get(rid)
    ti = text_index.get(rid) or {}
    rationale = ((fr or {}).get("rationale") or "").strip() or ti.get("rationale") or ""
    killer = (fr or {}).get("killer_message") if fr else None
    if killer is None:
        killer = ti.get("killer_message")
    card_id = (fr or {}).get("card_id") or ti.get("card_id")
    return rationale, killer, card_id


def build_narrative(
    *,
    axis: str,
    gate: Optional[str],
    fired: list[dict],
    verdict: str,
    driving_rule_id: Optional[str] = None,
    modality: Optional[str] = None,
    contracts_repo: Optional[Path] = None,
    flip_facet: Optional[dict] = None,
    gaps: Optional[list[dict]] = None,
) -> dict:
    """Assemble the per-verdict narrative object. Pure over (fired, resolver spec).

    Args:
      axis:            the skill/axis short name (e.g. "safety").
      gate:            the resolver gate (resolvers/<gate>.resolver.yaml), or None for a gateless
                       skill — then movers reduce to the driver and flips are inapplicable.
      fired:           the shared ``fired_rules`` output (list of {rule_id, card_id, signals,
                       rationale, killer_message, ...}). NOT mutated.
      verdict:         the resolved verdict token (carried through verbatim; narrative never recomputes it).
      driving_rule_id: the rule_id the resolver's winning rung named. None for a default verdict.
      modality:        optional channel filter — restrict dissenters to this signal channel
                       (e.g. "degrader"); the base (None) reports dissent on every channel.
      contracts_repo:  optional target-contracts root override (tests point this at a fixture).
      flip_facet:      optional PRE-COMPUTED flip result (the composed layer passes the fragility
                       facet slice, which carries the richer ``decision_flips``). When None and a
                       gate is given, this computes a single-rule ``flip_analysis`` itself.
      gaps:            optional PRE-COMPUTED gap list (composed layer: acquisition_backlog /
                       underpowered_axes for this axis). Defaults to [] standalone.

    Returns the narrative dict (see module docstring for the field contract).
    """
    text_index = rule_text_index(contracts_repo)
    fired_by_id = {r["rule_id"]: r for r in fired if isinstance(r, dict) and r.get("rule_id")}
    referenced = resolver_referenced_rule_ids(gate, contracts_repo) if gate else set()

    # Reference valence: the per-channel sign the WINNING rung expresses.
    driver_signals = (fired_by_id.get(driving_rule_id) or {}).get("signals") or {} if driving_rule_id else {}
    ref_sign = {ch: _sign(s) for ch, s in driver_signals.items()}

    def _agrees(sigs) -> bool:
        return any(_sign(sigs.get(ch)) != 0 and _sign(sigs.get(ch)) == ref_sign.get(ch, 0) for ch in sigs)

    def _opposes(sigs) -> bool:
        return any(_sign(sigs.get(ch)) != 0 and ref_sign.get(ch, 0) != 0 and _sign(sigs.get(ch)) != ref_sign.get(ch, 0) for ch in sigs)

    # ---- movers: driver first, then resolver-referenced rules present that pull the SAME way.
    movers: list[dict] = []
    mover_ids: list[str] = []
    if driving_rule_id and driving_rule_id in fired_by_id:
        mover_ids.append(driving_rule_id)
    for rid in sorted(referenced & set(fired_by_id)):
        if rid == driving_rule_id:
            continue
        sigs = fired_by_id[rid].get("signals") or {}
        # a referenced+present rule is a mover UNLESS it is a pure opposer (dissents, agrees on nothing)
        if _opposes(sigs) and not _agrees(sigs):
            continue
        mover_ids.append(rid)
    for rid in mover_ids:
        fr = fired_by_id[rid]
        rationale, killer, card_id = _sentence_for(rid, text_index, fired_by_id)
        movers.append({
            "rule_id": rid,
            "card_id": fr.get("card_id") or card_id,
            "role": "driver" if rid == driving_rule_id else "reachability_present",
            "signals": fr.get("signals") or {},
            "sentence": rationale,
            "killer_message": killer,
        })

    # ---- dissenters: fired non-driver rules whose channel sign OPPOSES the driver's on that channel.
    dissenters: list[dict] = []
    for rid in sorted(fired_by_id):
        if rid == driving_rule_id:
            continue
        sigs = fired_by_id[rid].get("signals") or {}
        for ch in sorted(sigs):
            rs, rf = _sign(sigs[ch]), ref_sign.get(ch, 0)
            if rs == 0 or rf == 0 or rs == rf:
                continue
            if modality and ch != modality:
                continue
            fr = fired_by_id[rid]
            rationale, killer, card_id = _sentence_for(rid, text_index, fired_by_id)
            dissenters.append({
                "rule_id": rid,
                "card_id": fr.get("card_id") or card_id,
                "channel": ch,
                "signal": sigs[ch],
                "sentence": rationale,
                "killer_message": killer,
            })
    dissenters.sort(key=lambda d: (d["channel"], d["rule_id"]))

    # ---- flip_conditions: pre-computed (composed) or a single-rule scan (standalone).
    if flip_facet is None and gate:
        flip_facet = flip_analysis(fired, gate, contracts_repo)
    flip_facet = flip_facet or {}
    raw_flips = flip_facet.get("decision_flips") or flip_facet.get("flips") or []
    flip_conditions: list[dict] = []
    for fl in raw_flips:
        rid = fl.get("rule_id")
        rationale, _killer, _card = _sentence_for(rid, text_index, fired_by_id)
        fc = {"rule_id": rid, "present": fl.get("present"),
              "to_verdict": fl.get("to_verdict"), "sentence": rationale}
        if "to_role" in fl:
            fc["to_role"] = fl["to_role"]
        if "recommendation_flip" in fl:
            fc["recommendation_flip"] = fl["recommendation_flip"]
        flip_conditions.append(fc)
    flip_conditions.sort(key=lambda f: (str(f.get("rule_id")), str(f.get("present"))))

    # ---- rule_sentences: caption every cited rule_id (movers + dissenters + flip rules), fired or not.
    cited = {m["rule_id"] for m in movers}
    cited |= {d["rule_id"] for d in dissenters}
    cited |= {f["rule_id"] for f in flip_conditions if f.get("rule_id")}
    rule_sentences: dict[str, dict] = {}
    for rid in sorted(cited):
        rationale, killer, card_id = _sentence_for(rid, text_index, fired_by_id)
        rule_sentences[rid] = {"rationale": rationale, "killer_message": killer, "card_id": card_id}

    return {
        "axis": axis,
        "gate": gate,
        "verdict": verdict,
        "driving_rule_id": driving_rule_id,
        "scan_depth": flip_facet.get("scan_depth", "single_rule"),
        "movers": movers,
        "dissenters": dissenters,
        "flip_conditions": flip_conditions,
        "gaps": list(gaps or []),
        "rule_sentences": rule_sentences,
        "_basis": ("movers=driver+resolver-referenced-present pulling the same way; "
                   "dissenters=opposing-sign fired non-driver rules (per channel); "
                   "flips+gaps re-projected from the flip/fragility facet; verdict-INERT"),
    }
