"""Ladder invariants (2026-08-20). The presence verdict is resolved INLINE in run.py (not via a
*.resolver.yaml — see CONTRACT.md § "Why the verdict is resolved inline"), so the ladder ORDER carries
scientific-priority judgments with no declarative-resolver governance behind it. These tests are that
governance: they assert the ordering PRINCIPLES the ladder is built on, so a reorder that violates a
principle fails here and forces the rationale to be updated with it.

Four guards:

  1. NO DANGEROUS FLIP (supersedes the ephemeral 43-pair backtest). The original tumor-over-cell-line
     re-anchor was justified by an out-of-tree backtest ("23 flips, zero dangerous flips") whose data is
     not recoverable. A "dangerous flip" is defined here precisely: the collapsed verdict resolves to a
     presence-POSITIVE when NOTHING but presence-negatives and/or coverage-gaps fired (a positive
     conjured from measured-against / absent evidence). We prove the ladder can NEVER produce one — as a
     TOTAL structural property over the ladder, not a 43-point sample, which is strictly stronger.

  2. LADDER RATIONALE. The documented ordering principles (positives > negatives > gaps; tumor tissue >
     cell-line proxy; RNA backbone > protein > single-cell; protein-absence is a NEGATIVE) hold.

  3. VOCABULARY REACH (added 2026-09-18 with the subset_high split). The ladder is a CLOSED
     (rule_id -> verdict) list read live against target-contracts, so a class value the producer can
     emit whose only rule is absent from the ladder does not rank low — it is INVISIBLE, and collapses
     to `insufficient`: a FALSE ABSENCE reported to a scientist as "no data" for a measured target.
     Guards 1 and 2 are both blind to that, because they only ever look at rungs the ladder already
     lists. This tier looks the other way round — from the producer's declared vocabulary INTO the
     ladder — and carries its own anti-vacuity control.

  4. OUTPUT-VOCABULARY DECLARATION (added 2026-09-18, same arc). Guard 3 checks the vocabulary the
     ladder READS (card class values → rule_ids). This one checks the vocabulary the ladder WRITES:
     every verdict token a rung can produce must be declared in target-contracts' pinned
     `presence_verdict_enum`, or the emitted decision.json fails its own data-product schema. That
     enum is a SECOND, separate declaration site from the rules YAML — declaring the rule does not
     declare the verdict — and nothing else in either repo compares the two, which is how the
     subset_high rung reached a green suite with an undeclared output token.
"""

from __future__ import annotations

import copy
import json
from itertools import combinations
from pathlib import Path

import pytest
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_ladder")


def _fr(rule_id, card_id="x"):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


def _pos_neg_gap_indices():
    pos, neg, gap = [], [], []
    for i, (_, v) in enumerate(tp._VERDICT_RANK):
        if v in tp._MEASURED_NEGATIVE_VERDICTS:
            neg.append(i)
        elif v in tp._COLLAPSE_GAP_VERDICTS:
            gap.append(i)
        elif tp._is_presence_positive(v):
            pos.append(i)
    return pos, neg, gap


# ── 1. NO DANGEROUS FLIP ─────────────────────────────────────────────────────────────────────────
def test_no_positive_outranked_by_any_negative_or_gap():
    """Structural proof: every presence-POSITIVE rung sorts strictly above every measured-NEGATIVE and
    every coverage-GAP rung in the collapsed ladder. Because _rank_verdict returns the FIRST fired rung,
    this guarantees a fired-set with no positive can never resolve positive."""
    pos, neg, gap = _pos_neg_gap_indices()
    assert pos and neg and gap, "ladder must contain positive, negative, and gap rungs"
    assert max(pos) < min(neg), "a measured-negative rung outranks a positive — dangerous-flip risk"
    assert max(pos) < min(gap), "a coverage-gap rung outranks a positive — measured-first violated"


def test_negatives_only_firesets_never_resolve_positive():
    """Behavioural corollary, checked directly: no combination of measured-negative / gap rungs (up to
    triples, plus the all-negatives-and-gaps set) resolves to a presence-positive."""
    neg_gap = [
        rid for rid, v in tp._VERDICT_RANK if v in tp._MEASURED_NEGATIVE_VERDICTS or v in tp._COLLAPSE_GAP_VERDICTS
    ]
    subsets = (
        [[r] for r in neg_gap] + list(combinations(neg_gap, 2)) + list(combinations(neg_gap, 3)) + [neg_gap]
    )  # the maximal adversarial set
    for combo in subsets:
        v, _ = tp._verdict([_fr(r) for r in combo])
        assert not tp._is_presence_positive(v), f"dangerous flip: {list(combo)} -> {v!r} (positive)"


def test_all_negatives_resolve_to_a_negative_not_a_gap():
    """When only measured-negatives fire (no positives, no gaps), the verdict must be a measured
    negative — a real 'against' call, not swallowed into data_unavailable."""
    neg_rids = [rid for rid, v in tp._VERDICT_RANK if v in tp._MEASURED_NEGATIVE_VERDICTS]
    v, _ = tp._verdict([_fr(r) for r in neg_rids])
    assert v in tp._MEASURED_NEGATIVE_VERDICTS


# ── 2. LADDER RATIONALE ────────────────────────────────────────────────────────────────────────────
def _idx(rule_id, ladder):
    for i, (rid, _) in enumerate(ladder):
        if rid == rule_id:
            return i
    raise AssertionError(f"{rule_id} not in ladder")


def test_tumor_tissue_outranks_cellline_proxy_in_expression_ladder():
    """Principle: tumor-tissue broadly/moderately-expressed rungs sit ABOVE the pan-cancer cell-line
    proxy rungs (lineage_restricted / broadly_moderate), so a de-differentiating antigen is not
    understated. Cell-line broadly_high stays at the very top (both-lenses-agree)."""
    L = tp._EXPRESSION_RANK
    assert _idx("tumor-expression-broadly-high-supportive", L) < _idx("expression-lineage-restricted-supportive", L)
    assert _idx("tumor-expression-broadly-high-supportive", L) < _idx("expression-broadly-moderate-neutral", L)
    assert _idx("expression-broadly-high-supportive", L) < _idx("tumor-expression-broadly-high-supportive", L)


def test_rna_backbone_precedes_protein_precedes_sc_in_positive_tier():
    """Principle: within the measured-positive tier, RNA (expression) rungs precede protein rungs, which
    precede single-cell rungs — the RNA-backbone byte-stability guarantee."""
    pos, _, _ = tp._partition_measured(tp._VERDICT_RANK)
    order = [rid for rid, _ in pos]
    expr = {rid for rid, _ in tp._EXPR_POS}
    prot = {rid for rid, _ in tp._PROT_POS}
    sc = {rid for rid, _ in tp._SC_POS}
    last_expr = max(i for i, rid in enumerate(order) if rid in expr)
    first_prot = min(i for i, rid in enumerate(order) if rid in prot)
    last_prot = max(i for i, rid in enumerate(order) if rid in prot)
    first_sc = min(i for i, rid in enumerate(order) if rid in sc)
    assert last_expr < first_prot, "a protein positive precedes an RNA positive (backbone violated)"
    assert last_prot < first_sc, "a single-cell positive precedes a protein positive"


def test_protein_absence_is_a_measured_negative():
    """Principle: a measured protein-absence is a presence-NEGATIVE, so it lands in the negative tier and
    trips presence_headline_conflict — never treated as a coverage gap. The ONLY reachable protein-absence
    signal is cell-line whole-panel MS `protein_broadly_low`; the former `protein_not_detected` was retired
    (target-contracts #467 — whole-proteome CPTAC TMT cannot assert per-gene absence), so the negative set
    must NOT still carry that unreachable token."""
    assert "protein_broadly_low" in tp._MEASURED_NEGATIVE_VERDICTS
    assert "protein_not_detected" not in tp._MEASURED_NEGATIVE_VERDICTS


def _live_intracellular_rule_ids():
    """The rule_ids DEFINED in the shared intracellular-intrinsic interpretation-rules (target-contracts).
    Returns None when the sibling contracts checkout is absent (checkout-only CI) so callers can skip."""
    import yaml
    from _skills_common.paths import target_contracts_root

    path = target_contracts_root() / "interpretation-rules" / "intracellular-intrinsic.rules.yaml"
    if not path.exists():
        return None
    spec = yaml.safe_load(path.read_text()) or {}
    return {r["rule_id"] for r in (spec.get("rules") or []) if isinstance(r, dict) and r.get("rule_id")}


def test_protein_absence_rids_non_empty():
    """The `present_rna_only_protein_absent` caveat (run.py `_verdict`) — the ONLY verdict word that warns
    an RNA-present target is protein-ABSENT — fires only when a rule in `_PROTEIN_ABSENCE_RIDS` is among
    the fired set. An empty set silently disables that entire demotion pathway with no other test catching
    it, so pin it non-empty."""
    assert tp._PROTEIN_ABSENCE_RIDS, (
        "_PROTEIN_ABSENCE_RIDS is empty — the protein-absence demotion is silently unreachable"
    )


def test_protein_absence_rids_resolve_to_live_contract_rules():
    """Cross-repo staleness guard: every rid in `_PROTEIN_ABSENCE_RIDS` must resolve to a LIVE rule in the
    shared intracellular-intrinsic interpretation-rules. The whole `present_rna_only_protein_absent`
    demotion hinges on a single cell-line `protein-abundance-broadly-low-degrader-killer` rung; if
    target-contracts renamed or retired it, the caveat would go silently unreachable with no failure here.
    Skips when the sibling contracts checkout is absent (checkout-only CI)."""
    live = _live_intracellular_rule_ids()
    if live is None:
        pytest.skip("target-contracts checkout absent — cross-repo rule-id guard not applicable")
    missing = sorted(set(tp._PROTEIN_ABSENCE_RIDS) - live)
    assert not missing, (
        f"_PROTEIN_ABSENCE_RIDS reference rules not defined in intracellular-intrinsic.rules.yaml: {missing}"
    )


def test_present_rna_only_protein_absent_demotion_fires_behaviorally():
    """Behavioral coverage of the single-rung protein-absence demotion (no live panel target hits it —
    the CTAs tried are cell-line broadly_moderate, not broadly_low): an RNA positive + the cell-line
    `protein-abundance-broadly-low-degrader-killer` + NO protein-positive collapses to
    present_rna_only_protein_absent."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
        _fr("protein-abundance-broadly-low-degrader-killer", "cellline-protein-abundance"),
    ]
    v, _drv = tp._verdict(fired)
    assert v == tp.PRESENT_RNA_ONLY_PROTEIN_ABSENT


def test_protein_absence_demotion_suppressed_by_any_protein_positive():
    """Guard the demotion's precondition: if ANY protein-positive fired, the broadly_low killer does NOT
    demote (the target IS protein-present somewhere) — the RNA positive stands."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("protein-abundance-broadly-low-degrader-killer", "cellline-protein-abundance"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
    ]
    v, _drv = tp._verdict(fired)
    assert v != tp.PRESENT_RNA_ONLY_PROTEIN_ABSENT


# ── 3. THE subset_high SPLIT (phase 2 of 3) ────────────────────────────────────────────────────────
# `tumor_expression_class: subset_high` fires at high_fraction >= 0.1 (plus a bimodal/long_tail shape),
# so on the shared rung a 10%-of-patients antigen and a 60%-of-patients one produced the SAME verdict
# and the SAME headline phrase. The split is sequenced across three PRs because `_EXPRESSION_RANK` is
# CLOSED and read live against target-contracts: _rank_verdict returns the first FIRED entry, so a
# fired rule_id the ladder does not list is INVISIBLE, not demoted. Re-routing the enum value in one
# step therefore ERASES its verdict — measured, it collapsed `tumor_broadly_expressed` to
# `insufficient`, a coverage-GAP class below measured negatives, i.e. a FALSE ABSENCE for a target
# measured high in 12% of patients.
#
#   phase 1 (TC#805, landed) — contracts ADDS tumor-expression-subset-high-supportive while the broad
#                              rule KEEPS subset_high in its `in:` list. Both rules fire; broad wins.
#   phase 2 (here)           — the ladder CONSUMES the new rung, below broad. Still inert.
#   phase 3 (contracts)      — remove subset_high from the broad rule. THE flip point.
#
# So the tests below come in pairs: an INERTNESS assertion against the live rules (what ships today)
# and a REACHABILITY assertion against the same rules NARROWED in memory (what phase 3 will do). The
# narrowed arm is what makes phase 2 load-bearing rather than dead code — without it, deleting the new
# rung would leave this suite green.
_BROAD_RID = "tumor-expression-broadly-high-supportive"
_SUBSET_RID = "tumor-expression-subset-high-supportive"
_SUBSET_VERDICT = "tumor_subset_high_expression"


def _live_rules():
    """The intracellular-intrinsic rules as the skill loads them at RUNTIME. None when the sibling
    contracts checkout is absent (checkout-only CI), so callers skip rather than pass vacuously."""
    from _skills_common.paths import target_contracts_root
    from _skills_common.rules_loader import load_interpretation_rules

    root = target_contracts_root()
    if not (root / "interpretation-rules" / "intracellular-intrinsic.rules.yaml").exists():
        return None
    # NB: the axis arg must equal the file's own DECLARED axis, which is UNDERSCORED. Passing the kebab
    # form returns None, and a zero-rule load makes every comparison below trivially agree.
    rules = load_interpretation_rules("intracellular_intrinsic", contracts_root=root)
    assert rules and len(rules) > 250, f"loaded {len(rules or [])} rules — the loader failed, not the repo"
    return rules


def _restore_broad_overlap(rules):
    """Re-ADD subset_high to the broad rule's `in:` list, in memory — the PRE-3b shape.

    INVERTED at phase 3b (contracts c3eec12). Until 3b this helper SUBTRACTED subset_high to simulate a
    narrowing that had not happened yet; now the narrowing is live in contracts, so the counterfactual
    runs the other way and the helper reconstructs the overlap. The direction had to flip with the pin:
    the old body asserted `stripped == 1`, and against a narrowed tree there is nothing left to strip, so
    it failed with `narrowed 0` — a control that had quietly stopped being a control. Keep an
    exact-count assert on THIS side too, for the same reason.
    """
    out = copy.deepcopy(rules)
    restored = 0
    for r in out:
        if r.get("rule_id") == _BROAD_RID:
            vals = (r.get("when") or {}).get("in") or []
            assert "subset_high" not in vals, (
                "the broad rule still lists subset_high — the contracts tree in use predates 3b "
                "(c3eec12), so this helper would be a no-op and every arm built on it vacuous. Bump the "
                "`ref:` in .github/workflows/skills-validate.yml / fetch the sibling checkout."
            )
            r["when"]["in"] = [*vals, "subset_high"]
            restored += 1
    assert restored == 1, f"restored {restored} rules, expected 1 — this arm would not be a control"
    return out


def _subset_high_card():
    """A subset_high target: bimodal, high in 12% of patients, broadly detectable."""
    return {
        "card_id": "tumor-rna-distribution",
        "summary": {
            "tumor_expression_class": "subset_high",
            "high_fraction": 0.12,
            "detectable_fraction": 0.82,
            "moderate_fraction": 0.55,
            "distribution_pattern": "bimodal",
        },
    }


def _verdict_for(card, rules):
    from _skills_common import fired_rules

    fired = fired_rules([card], "intracellular-intrinsic", card_id_filter=[card["card_id"]], rules=rules)
    v, drv = tp._verdict(fired)
    return v, drv, sorted(r["rule_id"] for r in fired)


def test_subset_high_rung_sits_below_broad_and_above_moderate():
    """Ordering principle for the new rung: a minority-high subset is a NARROWER population than broad
    tumor expression (so it must not outrank it) but a STRONGER abundance read than broadly-moderate."""
    L = tp._EXPRESSION_RANK
    assert _idx(_BROAD_RID, L) < _idx(_SUBSET_RID, L), "the subset rung outranks broad tumor expression"
    assert _idx(_SUBSET_RID, L) < _idx("tumor-expression-broadly-moderate-neutral", L)


def test_subset_high_verdict_facets_are_coherent_and_not_strong():
    """Every per-token map that keys on the verdict must agree, and `presence_signal_strength` must NOT
    read strong. presence_signal_strength was the OTHER channel that could not separate a 10%-high
    target from a 60%-high one; classing the new token strong_positive would preserve the over-claim one
    layer below the verdict. Membership in one of the three _PRES_*_POS sets is mandatory, not
    decorative: _pres_direction returns 'neutral' and _presence_strength 'none' for an unlisted token."""
    v = _SUBSET_VERDICT
    assert tp._is_presence_positive(v), "the new rung must be a measured-POSITIVE, not a gap"
    assert v in tp._PRES_MOD_POS and v not in tp._PRES_STRONG_POS, "strong abundance, NARROW population"
    assert tp._presence_strength(v) == "moderate_positive"
    assert tp._pres_direction(v) == "supports"
    assert v in tp._RNA_PRESENCE_POSITIVE, "else _bulk_rna_proxy_quality silently drops the qualifier"
    assert tp._PRESENCE_TIER.get(v) == 2, "tier 2 keeps the INV-1 tier-3 cap inapplicable BY DESIGN"
    assert v not in tp._TIER3_TO_TIER2, "abundance-demotion map: mapping a POPULATION token here is a category error"
    assert v not in tp._MEASURED_NEGATIVE_VERDICTS and v not in tp._COLLAPSE_GAP_VERDICTS


def test_subset_high_phrase_names_the_population_not_breadth():
    """The headline phrase is the whole point of the split: it must not read 'broadly'."""
    phrase = tp._PRESENCE_VERDICT_PHRASE.get(_SUBSET_VERDICT)
    assert phrase, "the new verdict has no human phrase — the headline would fall back to a title-cased token"
    assert "broad" not in phrase.lower(), f"the subset phrase still implies breadth: {phrase!r}"
    assert phrase != tp._PRESENCE_VERDICT_PHRASE["tumor_broadly_expressed"]


def test_subset_high_drives_the_verdict_against_the_live_rules():
    """PHASE 3B LIVE, measured against the rules the skill actually loads. Contracts c3eec12 (TC#809)
    removed subset_high from the broad rule, so a subset_high card now fires ONLY the subset rule and the
    new rung drives the verdict. If this fails without a contracts change, the ladder order was edited.

    INVERTED FROM ITS PRE-3b FORM. Until 3b this arm asserted the OPPOSITE — that the deliberate phase-1/2
    overlap was still present and the broad rung still won (`test_subset_high_is_still_inert_...`). Both
    forms cannot hold at once, which is exactly why the pin bump and this rewrite are forced-atomic.

    PIN-SENSITIVE. This arm reads the sibling contracts CHECKOUT, which in CI is a hand-bumped fixed SHA,
    so it can only pass against a tree at or after TC#809 (c3eec12). Against the previous pin (26eee89) it
    fails with `broad rule still fires`. See the `ref:` comment in .github/workflows/skills-validate.yml."""
    rules = _live_rules()
    if rules is None:
        pytest.skip("target-contracts checkout absent — live-rules arm not applicable")
    v, drv, fired = _verdict_for(_subset_high_card(), rules)
    assert _SUBSET_RID in fired, (
        f"{_SUBSET_RID} did not fire. TC#805 (contracts 6ff21f8) declared this rule, so the contracts tree "
        f"in use predates it — in CI that means the hand-bumped `ref:` in .github/workflows/skills-validate.yml "
        f"is behind; locally it means the sibling checkout is stale. Bump/fetch rather than weakening this "
        f"assert, and do NOT convert it to a skip: a skip here reads as a pass for the wrong reason."
    )
    assert fired == [_SUBSET_RID], (
        f"a subset_high card fired {fired}. {_BROAD_RID} still firing means the contracts tree in use "
        f"predates TC#809 (c3eec12) — the pre-3b overlap. Bump the pin; do not relax this to a membership "
        f"check, because the whole point of 3b is that the broad rung no longer claims this population."
    )
    assert v == _SUBSET_VERDICT and drv == _SUBSET_RID, f"3b is not live: {v} via {drv}"
    assert tp._PRESENCE_VERDICT_PHRASE[v] == "High in a tumor subset (patient selection required)"


def test_restoring_the_broad_overlap_collapses_the_subset_verdict():
    """TWO-DIRECTIONAL CONTROL for the arm above, and the arm that keeps the LADDER ORDER under test.

    Same code, same card, the pre-3b overlap reconstructed in memory: both rules fire and the broad rung —
    ranked above — takes the verdict back to `tumor_broadly_expressed`. So the arm above is not passing
    because the subset rung is the only thing that could ever win; it passes because contracts stopped
    routing this population to the broad rule. That distinction is the whole content of 3b.

    This also preserves, as an executable record, the exact over-claim the split removed: a target high in
    12% of patients reported as "Broadly expressed in tumor".

    PIN-SENSITIVE in the mirror direction: `_restore_broad_overlap` asserts the overlap is ABSENT before
    re-adding it, so it fails loudly against a pre-3b tree instead of silently no-op'ing."""
    rules = _live_rules()
    if rules is None:
        pytest.skip("target-contracts checkout absent — live-rules arm not applicable")
    v, drv, fired = _verdict_for(_subset_high_card(), _restore_broad_overlap(rules))
    assert fired == sorted([_BROAD_RID, _SUBSET_RID]), f"restored arm fired {fired}, expected both rules"
    assert v == "tumor_broadly_expressed" and drv == _BROAD_RID, (
        f"with the overlap restored the broad rung must win by ladder order, got {v} via {drv} — "
        f"_EXPRESSION_RANK was reordered"
    )
    assert _idx(_BROAD_RID, tp._EXPRESSION_RANK) < _idx(_SUBSET_RID, tp._EXPRESSION_RANK)


def _values_reaching_a_rung(vocab, rules, ladder):
    """Per class value: does anything it fires appear in `ladder`? Factored out so the guard below can be
    shown to DISCRIMINATE against a synthetic ladder, rather than only ever being asserted true."""
    from _skills_common import fired_rules

    rids = {rid for rid, _v in ladder}
    out = {}
    for val in vocab:
        card = _subset_high_card()
        card["summary"]["tumor_expression_class"] = val
        fired = fired_rules([card], "intracellular-intrinsic", card_id_filter=[card["card_id"]], rules=rules)
        out[val] = bool({r["rule_id"] for r in fired} & rids)
    return out


def _declared_class_vocabulary():
    import yaml
    from _skills_common.paths import target_contracts_root

    path = target_contracts_root() / "cards" / "tumor-rna-distribution.card.yaml"
    if not path.exists():
        return None
    spec = yaml.safe_load(path.read_text()) or {}
    return ((spec.get("outputs") or {}).get("summary_fields_vocabulary") or {}).get("tumor_expression_class")


def test_every_declared_tumor_expression_class_value_reaches_a_ladder_rung():
    """THE GENERALIZED GUARD — this is the check whose absence let the phase-1 draft nearly land a false
    absence, and it is pointed the OPPOSITE way from
    test_protein_absence_rids_resolve_to_live_contract_rules (which checks ladder rid -> live rule).
    Here: every value the PRODUCER can emit must reach a rung the ladder actually lists. Because
    `_EXPRESSION_RANK` is closed, a value whose only rule is unlisted collapses to `insufficient` —
    reported to a scientist as 'no data' for a target that was measured. No other test in either repo
    constrains this: contracts validators do not check which ladder consumes a rule_id, and the GATING
    skills workflow pins contracts at a hand-picked SHA so it cannot observe a contracts change at all."""
    rules = _live_rules()
    vocab = _declared_class_vocabulary() if rules is not None else None
    if rules is None or not vocab:
        pytest.skip("target-contracts checkout absent — cross-repo vocabulary reach guard not applicable")
    assert len(vocab) >= 5, f"vocabulary looks truncated ({vocab}) — the guard would be near-vacuous"
    reach = _values_reaching_a_rung(vocab, rules, tp._EXPRESSION_RANK)
    unreachable = sorted(v for v, ok in reach.items() if not ok)
    assert not unreachable, (
        f"tumor_expression_class values that reach NO rung in _EXPRESSION_RANK: {unreachable}. "
        "Each one collapses to `insufficient` — a FALSE ABSENCE, not a demotion."
    )


def test_the_vocabulary_reach_guard_can_actually_fail():
    """ANTI-VACUITY control for the guard above. A guard that only ever runs against a passing
    configuration is indistinguishable from one that cannot fail, and the all-pass result above is
    exactly what a broken instrument reports. So: hold the rules narrowed (phase-3 shape) and delete the
    subset rung from a COPY of the ladder — the phase-1-draft configuration — and require the guard to
    name subset_high. Uses a synthetic ladder, so it cannot go vacuous by the fix being reverted.

    At 3b this stopped needing a helper: the LIVE rules are now the narrowed shape, so the only synthetic
    part left is the ladder. Before 3b it had to call `_narrow_broad_rule(rules)` to reach the same
    configuration, and that call is why this test — not just the two obviously-paired guards — went red
    the moment contracts landed 3b. A shared helper makes the blast radius of a contracts change larger
    than the guards that name it: count the CALLERS, not the helper."""
    rules = _live_rules()
    vocab = _declared_class_vocabulary() if rules is not None else None
    if rules is None or not vocab:
        pytest.skip("target-contracts checkout absent — cross-repo vocabulary reach guard not applicable")
    ladder_without_rung = [(rid, v) for rid, v in tp._EXPRESSION_RANK if rid != _SUBSET_RID]
    assert len(ladder_without_rung) == len(tp._EXPRESSION_RANK) - 1, "the synthetic ladder was not narrowed"
    reach = _values_reaching_a_rung(vocab, rules, ladder_without_rung)
    assert reach.get("subset_high") is False, "the guard cannot see an unreachable value — it is vacuous"
    assert reach.get("broadly_high") is True, "the guard flags everything — it is not discriminating"


# ── § 4. OUTPUT-VOCABULARY DECLARATION — the second declaration site (2026-09-18) ───────────────────
# The ladder READS card class values and WRITES verdict tokens. Those are two vocabularies declared in
# two different places in target-contracts:
#   READ  side: interpretation-rules/intracellular-intrinsic.rules.yaml   (guard 3 above covers this)
#   WRITE side: schemas/_skill_output/pins/tumor-presence.pins.json, `$defs.presence_verdict_enum`,
#               which validators/gen_skill_output_schemas.py bakes into
#               schemas/skills/tumor-presence.decision.schema.json — the artifact that actually
#               validates an emitted decision.json.
# MEASURED 2026-09-18: the enum held 33 tokens and `tumor_subset_high_expression` was NOT among them,
# while the whole tumor-presence suite plus skills/tests/ was green — because the only consumer,
# test_data_product_schema.py, validates a FROZEN GOLDEN whose verdict is tumor_broadly_expressed. A
# fixture can only exercise tokens it contains, so a golden-based conformance test is structurally blind
# to an undeclared token no fixture uses. That blindness is what this guard closes.
#
# We read the GENERATED schema, not the pins source: the generated file is what validation consumes, so
# it is what can actually bite. The pins file is where the FIX is authored (append to $defs; the pins
# $comment says "append-only within contract major version").
_DECISION_SCHEMA_REL = ("schemas", "skills", "tumor-presence.decision.schema.json")
_GOLDEN_REL = ("fixtures", "epcam_coadread_decision.json")

# THE ALLOWLIST IS GONE, AND ITS ABSENCE IS THE ASSERTION. There used to be a named
# `_UNDECLARED_LADDER_VERDICTS = {"tumor_subset_high_expression"}` here, held open while phase 3a of the
# subset_high split was unlanded. 3a landed (target-contracts #807, 26eee89, which appended the token to
# `$defs.presence_verdict_enum`), the paired "GOOD NEWS, ACTION REQUIRED" assert red exactly as designed,
# and the set was deleted rather than emptied. Deleted, not emptied, on purpose: an empty set left in place
# is a re-entry point — the next undeclared token can be excused by adding one word, with no reviewer
# noticing that a gap-documenting allowlist has become a gap-hiding one. With no set, the guard below is a
# plain universal over the ladder and the only way to satisfy it is to declare the token.
#
# WHY THE PIN BUMP IS IN THIS SAME COMMIT (do not split it out). `target_contracts_root()` resolves a
# sibling CHECKOUT, and in CI that checkout is a FIXED SHA (`ref:` in
# .github/workflows/skills-validate.yml, bumped by hand) — NOT contracts `main`; only two non-gating
# monitors (card-behavior-matrix-nightly, discordance-monitor) read `main`. So deleting the allowlist while
# the pin still names a pre-3a tree is GREEN LOCALLY and RED IN CI: locally the sibling tree declares the
# token so the ladder has no undeclared members, while the pinned tree does not and the first assert fires.
# That is the same forced-atomic pairing as the previous bump but in the opposite direction, and a local
# suite run cannot detect either direction, because it reads whatever SHA the sibling checkout happens to
# sit on. Measured as a 2x2 over both axes at the EXACT refs — see the pin comment in the workflow.


def _pinned_presence_verdict_enum():
    """The verdict enum the emitted decision.json is validated against. None when the sibling contracts
    checkout is absent (checkout-only CI), so callers skip rather than pass vacuously."""
    from _skills_common.paths import target_contracts_root

    path = target_contracts_root().joinpath(*_DECISION_SCHEMA_REL)
    if not path.exists():
        return None
    schema = json.loads(path.read_text())
    enum = schema.get("$defs", {}).get("presence_verdict_enum", {}).get("enum")
    assert isinstance(enum, list) and enum, (
        f"$defs.presence_verdict_enum missing or empty in {path} — the guard below would pass "
        f"vacuously against an empty enum, so this is a hard failure, not a skip."
    )
    return set(enum)


def test_every_ladder_verdict_token_is_declared_in_the_pinned_enum():
    """A rung whose verdict token is absent from presence_verdict_enum makes the skill emit a
    decision.json that fails its own data-product schema — on every target that reaches the rung.
    Now a plain UNIVERSAL over the ladder: every rung's token must be declared, no exceptions. The
    allowlist that used to carve out `tumor_subset_high_expression` is gone (see the comment above
    `_pinned_presence_verdict_enum`), so there is nowhere left to park a new gap."""
    declared = _pinned_presence_verdict_enum()
    if declared is None:
        pytest.skip("target-contracts checkout absent — output-vocabulary declaration guard not applicable")

    ladder_tokens = {v for _rid, v in tp._VERDICT_RANK}
    assert len(ladder_tokens) > 20, f"anti-vacuity: only {len(ladder_tokens)} ladder tokens — ladder not loaded"

    undeclared = sorted(ladder_tokens - declared)
    assert not undeclared, (
        f"ladder verdict token(s) not declared in target-contracts presence_verdict_enum: {undeclared}. "
        f"Any target reaching that rung emits a decision.json that fails "
        f"schemas/skills/tumor-presence.decision.schema.json. Declare them in "
        f"schemas/_skill_output/pins/tumor-presence.pins.json ($defs.presence_verdict_enum, append-only) "
        f"and regenerate, BEFORE the rung becomes reachable. If CI reds here while a local run is green, "
        f"the declaration has landed in contracts main but the `ref:` pin in "
        f".github/workflows/skills-validate.yml still names a tree that predates it — bump the pin, do "
        f"NOT re-introduce an allowlist."
    )


def test_the_pinned_enum_actually_rejects_an_undeclared_verdict():
    """ANTI-VACUITY CONTROL for the guard above: it is only meaningful if the enum is load-bearing —
    i.e. if an undeclared token in `headline.presence_verdict` really does fail validation. Proven in
    BOTH directions against the frozen full decision: the token the golden already carries validates,
    and the undeclared token fails EXACTLY as a garbage string does. Without this, a schema that had
    quietly gone permissive (`additionalProperties`/enum dropped by a regeneration) would make the
    declaration guard above pass while declaring nothing."""
    from _skills_common.paths import target_contracts_root

    jsonschema = pytest.importorskip("jsonschema")
    schema_path = target_contracts_root().joinpath(*_DECISION_SCHEMA_REL)
    golden_path = Path(__file__).resolve().parent.joinpath(*_GOLDEN_REL)
    if not schema_path.exists() or not golden_path.exists():
        pytest.skip("target-contracts checkout or frozen golden absent — enum load-bearing control not applicable")

    schema = json.loads(schema_path.read_text())
    golden = json.loads(golden_path.read_text())
    assert "presence_verdict" in golden.get("headline", {}), "golden is not a full decision — control invalid"

    def validates(token):
        doc = copy.deepcopy(golden)
        doc["headline"]["presence_verdict"] = token
        try:
            jsonschema.validate(doc, schema)
            return True
        except jsonschema.ValidationError:
            return False

    assert validates(golden["headline"]["presence_verdict"]), "the golden's own verdict must validate"
    assert not validates("zzz_definitely_not_a_verdict"), (
        "the decision schema accepted a garbage presence_verdict — presence_verdict_enum is NOT "
        "load-bearing, so the declaration guard above proves nothing. Fix the schema, not this test."
    )
    # The subset_high rung specifically, asserted POSITIVELY now that phase 3a has landed. This replaces a
    # loop over the retired `_UNDECLARED_LADDER_VERDICTS` that asserted the opposite — that the token was
    # REJECTED — while the gap was open. Keeping the token named in both eras matters: it is the one rung
    # whose declaration and whose emission landed in different repos and different PRs, so this is the
    # single assertion that the two halves actually met. A golden-fixture conformance test cannot cover it,
    # because the frozen golden carries `tumor_broadly_expressed` and can only ever exercise tokens the
    # fixture already contains.
    assert validates("tumor_subset_high_expression"), (
        "tumor_subset_high_expression does NOT validate, so the rung in run.py's _EXPRESSION_RANK can emit "
        "a decision.json that fails its own data-product schema. Either the contracts pin in "
        ".github/workflows/skills-validate.yml predates target-contracts #807 (26eee89), or the pins enum "
        "was regenerated without it."
    )
