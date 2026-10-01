"""SK#1747 — the three tumor-presence legacy/asymmetry items, each resolved and pinned here.

The issue offered "remove the dead code" OR "document as intentional with rationale" for each item. The
audit's three findings were all re-measured against the current tree, and all three resolved to KEEP +
DOCUMENT. That outcome is only worth anything if the *reason* each thing stays is itself gated, because a
rationale in a comment decays silently while a test reds. So each item below pins the PROPERTY that makes
the retention correct — never "nothing emits it today", which is the inert-by-corpus fallacy — and reds
when that property expires, which is the signal to do the removal.

ITEM 1 — the `ns` legacy token. The audit asked whether `ns` is dead and removable from
`presence_cardboard_figure._NO_SIGNAL`. Measured: it is UNDECLARED (contracts dropped it from
tumor-protein-abundance-cptac's `protein_expression_class` on 2026-08-21, after cptac_protein_deg
METHOD_VERSION 1.2.0 split it into `not_significant` + `small_effect`), so the comment calling it a
"DECLARED legacy key" was stale. But it is NOT dead, in two independent senses, and that is why it stays:
a frozen PRE-split fixture in this very directory still emits it (`method_version: 1.0.0`), and the
SIBLING reader of the same field — run.py's `_MEASURED_UNRULED_PRESENT` / `_PRESENCE_READER`
`present_synonyms` — still accepts it, where dropping it is the FAIL-OPEN direction (a measured flat
protein would fall from `measured` to `data_unavailable`: a false absence). The invariant pinned here is
therefore AGREEMENT between the two readers, in both directions, plus the fixture that keeps the
retention live. Retiring `ns` is a coupled change (re-freeze the fixture, then drop it from BOTH readers
in one commit), not a token deletion.

ITEM 2 — the `ihc_not_detected` "own-bucket fence". Re-read the consumers and the audit's framing does
not survive them: the fence is per-BUCKET and SYMMETRIC (protein_ihc has no ladder, so its bucket carries
no driving_rule_id, and `_any_modality_presence_positive` excludes it in BOTH polarities — an
`ihc_detected_high` is excluded by the same clause), and the negative is not fenced off from its own
bucket's readout at all (the bucket's verdict IS `ihc_not_detected`; presence_matrix, protein-confirmation
state and presence_claims all consume it). The one thing it cannot do is RANK as a killer rung, and making
that symmetric would be verdict-MOVING in the false-negative direction on the framework's lowest-
specificity protein modality — the same discipline already recorded for the single-cell leg (#1516 F1).

ITEM 3 — `_CLAIM_A_TO_TIER` merging `moderate` and `weak` onto tier 2. Load-bearing: the map is a
CEILING, not a label (claim A's own signal still carries the distinction into the data package), and
preserving it would require a tier-1 demotion target that exists benignly in only 1 of the 3 lens
families — in the other 2 it would flip a PRESENT call into a measured-NEGATIVE token, which the cap
explicitly forbids. Pinned so a completeness sweep that "finishes" the map reds instead of shipping a
silent verdict move.

Full rationale for each item lives beside the code it governs (`presence_cardboard_figure._NO_SIGNAL`,
run.py's `_MEASURED_NEGATIVE_VERDICTS` / `_MEASURED_UNRULED_PRESENT` / `_CLAIM_A_TO_TIER`) and in
CONTRACT.md; this file is the gate, not a second home for the prose.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT
from _skills_common.presence_cardboard_figure import _NO_SIGNAL, _bucket
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_ns_asymmetries")

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_CARDS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT)) / "cards"

_CPTAC_CARD = "tumor-protein-abundance-cptac"
_CPTAC_FIELD = "protein_expression_class"
_LEGACY = "ns"
# The post-split replacements, named so the floor assertions below cannot be satisfied by an empty or
# wrong vocabulary. Both mean "protein quantified, not tumor-elevated".
_POST_SPLIT = ("not_significant", "small_effect")
# The fixture whose frozen PRE-split vintage keeps the legacy token live. Named, not discovered, so the
# sweep cannot pass by finding nothing.
_PRESPLIT_FIXTURE = "epcam_coadread.yaml"


def _declared_cptac_vocabulary() -> list[str]:
    path = _CARDS / f"{_CPTAC_CARD}.card.yaml"
    assert path.is_file(), f"contracts card not found: {path} (stale checkout? TARGET_CONTRACTS_ROOT)"
    outputs = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("outputs") or {}
    vocab = (outputs.get("summary_fields_vocabulary") or {}).get(_CPTAC_FIELD)
    assert isinstance(vocab, list) and vocab, (
        f"{_CPTAC_CARD} declares no list vocabulary for {_CPTAC_FIELD} — this gate would otherwise "
        "quantify over an empty set and pass for the wrong reason"
    )
    return [v for v in vocab if isinstance(v, str)]


# ── ITEM 1: the `ns` legacy token ────────────────────────────────────────────────────────────────
def test_the_ns_token_is_undeclared_but_its_post_split_replacements_are_declared():
    """THE FACT THAT CORRECTS THE OLD COMMENT. `ns` was described in two places as a "DECLARED legacy
    key"; it is not declared. Contracts dropped it from this card on 2026-08-21 (review M3) once
    cptac_protein_deg 1.2.0 split it. Asserted WITH a floor — the vocabulary must be readable, non-empty,
    and must contain BOTH post-split tokens by name — so "ns is absent" cannot be satisfied by an unread
    card, a renamed field, or an empty list."""
    vocab = _declared_cptac_vocabulary()
    assert len(vocab) >= 6, f"{_CPTAC_CARD}.{_CPTAC_FIELD} declares only {len(vocab)} values: {vocab}"
    for token in _POST_SPLIT:
        assert token in vocab, (
            f"{token!r} is missing from {_CPTAC_CARD}.{_CPTAC_FIELD} ({vocab}). The post-split vocabulary "
            "is the premise of this whole item; if it moved, re-audit SK#1747 item 1 rather than editing "
            "this floor."
        )
    assert _LEGACY not in vocab, (
        f"{_LEGACY!r} is DECLARED again in {_CPTAC_CARD}.{_CPTAC_FIELD}. That reverses the 2026-08-21 "
        "contracts fix and re-makes the token a live producer value; the retention rationale recorded at "
        "_NO_SIGNAL and _MEASURED_UNRULED_PRESENT needs rewriting, not extending."
    )


def test_a_frozen_presplit_fixture_still_emits_the_ns_token():
    """WHY `ns` IS NOT 'DEAD ON THE CURRENT CORPUS'. The committed fixture is a frozen PRE-split product
    vintage and still carries the token, so a reader that stopped accepting `ns` would mis-render (or
    worse, fail-open on) a real committed artifact. The sweep carries its own floor: every fixture YAML in
    this directory is enumerated, the count is asserted, and the emitting fixture is named — an empty
    sweep cannot pass.

    WHEN THIS REDS: the fixture was re-frozen on a post-split product, which is the removal signal. Do the
    COUPLED retirement in one commit — drop `ns` from presence_cardboard_figure._NO_SIGNAL AND from
    run.py's `_MEASURED_UNRULED_PRESENT` + `_PRESENCE_READER['tumor_protein_abundance']['present_synonyms']`
    — then delete this test. Do not relax it to keep a half-retired token alive."""
    fixtures = sorted(p for p in _FIXTURES.glob("*.yaml"))
    assert len(fixtures) >= 2, f"fixture sweep found only {[p.name for p in fixtures]} — expected >= 2"
    assert _PRESPLIT_FIXTURE in {p.name for p in fixtures}, (
        f"{_PRESPLIT_FIXTURE} is gone from {_FIXTURES}; re-audit SK#1747 item 1 before trusting any "
        "claim that the legacy token is unreachable"
    )
    emitters = {}
    for path in fixtures:
        summary = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(_CPTAC_CARD) or {}
        if isinstance(summary, dict) and summary.get(_CPTAC_FIELD) == _LEGACY:
            emitters[path.name] = summary.get("method_version")
    assert _PRESPLIT_FIXTURE in emitters, (
        f"no committed fixture emits {_CPTAC_FIELD}={_LEGACY!r} any more (swept {[p.name for p in fixtures]}). "
        "The retention reason for the legacy token has EXPIRED — read this test's docstring and do the "
        "coupled removal."
    )


def test_the_ns_token_is_accepted_by_both_readers_or_neither():
    """THE BINDING INVARIANT, and the one that makes the retention safe rather than merely inherited. Two
    modules read tumor-protein-abundance-cptac's `protein_expression_class`: the display reader
    (`presence_cardboard_figure._NO_SIGNAL`, where an unaccepted token renders `?`) and the bucket reader
    (run.py `_MEASURED_UNRULED_PRESENT`, where an unaccepted token leaves the bucket `data_unavailable` —
    the FAIL-OPEN direction, a false absence for a protein that was measured and found flat). The figure
    module's own header calls itself "convergence on that shape, not a new design", so the two accepting
    exactly the same vocabulary IS the design. Retiring `ns` from one alone is the defect this pins.

    Falsifiable in BOTH directions on purpose: removing it from either reader reds here."""
    rescue = tp._MEASURED_UNRULED_PRESENT[("bulk_protein_ms", "tumor")]
    card_id, field, class_map = rescue
    assert (card_id, field) == (_CPTAC_CARD, _CPTAC_FIELD), f"the rescue moved off the audited field: {rescue[:2]}"
    # Floor: the rescue map must already carry the CURRENT split, else "ns is also present" proves nothing.
    for token in _POST_SPLIT:
        assert class_map.get(token) == "protein_present_not_elevated", f"{token!r} missing from the rescue map"
    synonyms = tp._PRESENCE_READER["tumor_protein_abundance"]["present_synonyms"]
    for token in _POST_SPLIT:
        assert token in synonyms, f"{token!r} missing from present_synonyms {synonyms}"

    accepted_by_bucket_reader = _LEGACY in class_map
    accepted_by_synonyms = _LEGACY in synonyms
    accepted_by_display = _LEGACY in _NO_SIGNAL
    assert accepted_by_bucket_reader == accepted_by_synonyms == accepted_by_display, (
        f"the readers of {_CPTAC_CARD}.{_CPTAC_FIELD} DISAGREE about {_LEGACY!r}: "
        f"_MEASURED_UNRULED_PRESENT={accepted_by_bucket_reader}, present_synonyms={accepted_by_synonyms}, "
        f"_NO_SIGNAL={accepted_by_display}. Accept it everywhere or nowhere — a half-retired token makes "
        "one reader call a measured flat protein a coverage gap while another calls it a measured negative."
    )
    if accepted_by_display:  # the documented state: all three accept it, with the same meaning as the split
        assert class_map[_LEGACY] == "protein_present_not_elevated"
        assert _bucket(_LEGACY, "signal") == _bucket("not_significant", "signal") == "no_signal", (
            "the legacy token and its post-split replacement must render identically; a vintage difference "
            "in the product must not become a polarity difference on the card board"
        )


# ── ITEM 2: the `ihc_not_detected` own-bucket fence ──────────────────────────────────────────────
def test_protein_ihc_has_no_ladder_so_the_ihc_negative_is_never_a_collapse_rung():
    """The structural half of the fence, asserted at the ladder table rather than from the token's name.
    Giving protein_ihc a ladder is what "make the IHC negative able to inform its own bucket
    symmetrically" would mean in practice, and it is VERDICT-MOVING: an `ihc_not_detected` killer rung
    would let one indication-grain antibody read veto a target-wide presence nomination. Declined
    (SK#1747 item 2). Floor: the three real ladders are named, so this cannot pass over an empty table."""
    assert set(tp._MEASUREMENT_RANK) == {"bulk_rna", "bulk_protein_ms", "sc_rna"}, (
        f"_MEASUREMENT_RANK changed to {sorted(tp._MEASUREMENT_RANK)}. If protein_ihc gained a ladder, the "
        "collapsed presence verdict is now reachable from HPA antibody IHC — that is a verdict move and "
        "needs its own issue + flip measurement, not this cleanup's rationale."
    )
    assert tp._VERDICT_RANK, "the collapsed ladder is empty — every assertion below would be vacuous"
    rungs = {v for _rid, v in tp._VERDICT_RANK}
    assert tp._IHC_ABSENT_VERDICT in tp._MEASURED_NEGATIVE_VERDICTS, "the IHC negative must classify negative"
    assert tp._IHC_ABSENT_VERDICT not in rungs, f"{tp._IHC_ABSENT_VERDICT} became a collapse rung"
    for present in sorted(tp._IHC_PRESENT_VERDICTS):
        assert present not in rungs, f"{present} became a collapse rung — the fence is no longer symmetric"


def test_the_ihc_bucket_is_excluded_from_the_matrix_positivity_predicate_in_both_polarities():
    """THE AUDIT'S FRAMING, REFUTED. "It can down-weight another bucket but is fenced off from its own"
    reads as a polarity asymmetry; it is not. `_any_modality_presence_positive` keys on
    `driving_rule_id`, which the measured-unruled protein_ihc bucket never has, so the detected classes
    are excluded by exactly the same clause as the not-detected one. No direction is privileged."""
    for verdict in sorted(tp._IHC_PRESENT_VERDICTS) + [tp._IHC_ABSENT_VERDICT]:
        pm = {
            "protein_ihc/tumor": {
                "measurement": "protein_ihc",
                "sample_context": "tumor",
                "verdict": verdict,
                "driving_rule_id": None,
                "evidence_state": "measured",
            }
        }
        assert tp._any_modality_presence_positive(pm) is False, (
            f"the measured-unruled protein_ihc bucket voted in the rule-derived positivity predicate on "
            f"{verdict!r}; it must be excluded in BOTH polarities (it fires no ladder rule and never "
            "entered the collapse)."
        )


def test_the_ihc_negative_still_reaches_the_cross_bucket_conflict_guard():
    """…and the behavioural half: being outside the ladder does NOT silence the negative. The
    verdict-INERT `presence_headline_conflict` guard scans the per-modality matrix, so an RNA-positive
    headline sitting over a measured IHC not-detected is surfaced in words — which is why the declined
    killer rung does not leave an ADC/degrader reader unwarned. The spine word is untouched."""
    positive = "tumor_broadly_expressed"
    assert tp._is_presence_positive(positive)
    pm = {
        "bulk_rna/tumor": {
            "verdict": positive,
            "driving_rule_id": "tumor-expression-broadly-high-supportive",
            "evidence_state": "measured",
        },
        "protein_ihc/tumor": {
            "verdict": tp._IHC_ABSENT_VERDICT,
            "driving_rule_id": None,
            "evidence_state": "measured",
        },
    }
    conflict, note, buckets = tp._headline_conflict(positive, pm, fired=[])
    assert conflict is True and "protein_ihc/tumor" in buckets, (
        f"the measured IHC negative is invisible to the conflict guard (conflict={conflict}, "
        f"buckets={buckets}). That guard is the compensating channel for the declined killer rung; if it "
        "stops firing, SK#1747 item 2's rationale no longer holds."
    )
    assert note and "MEASURED presence-negative" in note


# ── ITEM 3: the _CLAIM_A_TO_TIER moderate+weak merge ─────────────────────────────────────────────
def test_the_claim_a_tier_cap_never_allows_a_demotion_below_tier_two():
    """The merge, pinned as the invariant that CAUSES it: the cap floor is tier 2. Splitting `weak` onto
    tier 1 reds here, which is the point — tier 1 is where the measured-NEGATIVE tokens live, so that
    split cannot be made without choosing a per-lens demotion target, and in 2 of the 3 lens families the
    only within-family candidate flips PRESENT into absent. Keys pinned by name in both directions:
    claim A also emits `absent` and `unmeasured`, and their ABSENCE from this map is deliberate (the cap
    governs the RELATIVE distribution tier; absolute abundance rides on abundance_floor_flag)."""
    assert set(tp._CLAIM_A_TO_TIER) == {"strong", "moderate", "weak"}, (
        f"_CLAIM_A_TO_TIER keys changed to {sorted(tp._CLAIM_A_TO_TIER)}. Adding `absent`/`unmeasured` "
        "makes an absolute-abundance signal cap a relative-distribution word — re-read the rationale at "
        "the map before doing it."
    )
    assert tp._CLAIM_A_TO_TIER["strong"] == 3
    for signal in ("moderate", "weak"):
        assert tp._CLAIM_A_TO_TIER[signal] >= 2, (
            f"claim A {signal!r} now caps below tier 2. Tier 1 contains measured-NEGATIVE tokens "
            f"({sorted(t for t, tier in tp._PRESENCE_TIER.items() if tier == 1 and t in tp._MEASURED_NEGATIVE_VERDICTS)}), "
            "so this can flip a PRESENT call to absent. That is a verdict move and needs its own issue."
        )


def test_every_tier_cap_demotion_target_stays_presence_positive():
    """The companion property: the cap demotes 3→2 WITHIN a lens family and never out of the positive
    tier. Floor: all three lens families are named, so an emptied map cannot pass."""
    assert set(tp._TIER3_TO_TIER2) == {
        "broadly_high_expression",
        "strongly_upregulated_in_tumor",
        "tumor_broadly_expressed",
    }, f"_TIER3_TO_TIER2 keys changed to {sorted(tp._TIER3_TO_TIER2)}"
    for raw, demoted in tp._TIER3_TO_TIER2.items():
        assert tp._PRESENCE_TIER.get(raw) == 3, f"{raw} is no longer tier 3; the cap would not reach it"
        assert tp._PRESENCE_TIER.get(demoted) == 2, f"{raw} -> {demoted} is not a tier-2 demotion"
        assert demoted not in tp._MEASURED_NEGATIVE_VERDICTS, f"{raw} -> {demoted} demotes into a measured NEGATIVE"
        assert tp._is_presence_positive(demoted), f"{raw} -> {demoted} leaves the positive tier"


def test_moderate_and_weak_claim_a_reconcile_to_the_same_word():
    """The information loss itself, stated as behaviour so it is a DECISION on the record rather than an
    accident someone later 'fixes'. A weak Claim-A and a moderate Claim-A cap a tier-3 word to the same
    tier-2 sibling. If this ever reds, the moderate/weak distinction became verdict-AFFECTING and needs a
    measured flip delta across the committed corpus — not a quiet landing."""
    state = {"malignant_intrinsic": "malignant", "present": "yes"}
    for raw, demoted in tp._TIER3_TO_TIER2.items():
        got = {sig: tp.reconcile_presence_verdict(raw, state, {"A": {"signal": sig}}) for sig in ("moderate", "weak")}
        assert got["moderate"] == got["weak"] == demoted, f"{raw}: moderate/weak no longer reconcile alike: {got}"
        # and the strong signal is not capped at all — the cap must stay a disagreement guard.
        assert tp.reconcile_presence_verdict(raw, state, {"A": {"signal": "strong"}}) == raw
