"""#1794 pan-essential fail-open closure — the SK consumer wiring for the two new resolver paths.

★ PIN-COUPLED: the resolver-routing / rule-reachability tests here require target-contracts >=
fb43651e (interpretation rules 1.4.0 + safety.resolver 2.4.0 + dependency.resolver 1.7.0 + card
3.1.0). Against the OLD skills-validate pin they fail BY DESIGN — this file is one of the changes
that must land atomically with the human `ref:` pin bump (see issue #1794's adoption/landing
comment for the enumerated obligations).

What is pinned, and why each arm exists:
  - UNANCHORED ROUTING: pan-essential-unanchored-broad-tox-safety-warning alone resolves to the
    SAME pan_essential_broad_tox_concern HOLD as the curated arm (an unverifiable pan-essential is
    a concern, never clean), with itself as driving_rule — the arms stay distinguishable in
    provenance. Pre-#1794 the class was conflated into the safety-DARK common_essential_underpowered
    and a transient anchor outage produced a CLEAN safety verdict.
  - GRADED BAND ROUTING + PRECEDENCE (acceptance criterion 2, the sharpest pre-#1794 failure):
    broad_dependency_band == partial_broad_band (0.60-0.85) resolves the NEW graded
    broad_dependency_partial_tox_concern, and it must beat the TC#895 tolerant reassurance — the
    band's own pan-essential-safety-axis-measured-clear witness (which keys the WHOLE
    broadly_dependent class) previously made the measured partial liability actively CORROBORATE
    tolerant_reduced_safety_risk.
  - BELOW THE HOLDS: the graded caution never outranks a real HOLD (curated pan-essential /
    human-genetics) — 12/504 corpus band carriers include managed clinical-stage targets.
  - DEPENDENCY TWIN: common-essential-unanchored-insufficient routes the dependency gate to
    insufficient_underpowered_pan_essential (the T3 direction — NO fraction-only veto, and no new
    dependency token that would fail-close tp_gates to a forced VETO).
  - RULE REACHABILITY: both new safety rules fire through the real shared `when:` matcher from a
    card summary (a rename of the field or enum value upstream reds this, not just the
    synthetic-fired tests).
  - CONSUMER REGISTRATION (mutation teeth): the graded token must be registered everywhere a safety
    verdict is consumed — phrase map + concern polarity (run.py), tp_gates recognized/NON-GATING
    (without the line, band carriers fail-close to a forced hold; with it they fall through as a
    permissive pass and the token still never gates), risk_projection mid bin (never the 0
    fail-toward-safe default, never the HOLD bin), claim + question-table maps for
    common_essential_unanchored (an unverifiable pan-essential never reads safe).
  - NONE-STABILITY (the absence direction): on a package emitted before analysis-methods
    depmap_chronos_distribution 0.3.0 (507439fc) the band field is absent / the class token never
    appears, and every claim/table surface must be byte-identical — verdicts flip only when
    packages regenerate.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import fired_rules, safety_claims, safety_question_table  # noqa: E402
from _skills_common.resolver import resolve_or_raise  # noqa: E402
from _skills_common.risk_projection import _SAFETY_BINS, _SAFETY_DEFAULTED  # noqa: E402

_RUN = load_run_py(SKILL_DIR, "_safety_run_pan_essential_failopen")

CARD = "pan-cancer-crispr-dependency-distribution"
CURATED_RULE = "pan-essential-broad-tox-safety-warning"
UNANCHORED_RULE = "pan-essential-unanchored-broad-tox-safety-warning"
BAND_RULE = "broad-dependency-partial-tox-safety-warning"
DEP_RULE = "common-essential-unanchored-insufficient"
HOLD = "pan_essential_broad_tox_concern"
GRADED = "broad_dependency_partial_tox_concern"


def _fired(*rule_ids: str) -> list[dict]:
    return [{"rule_id": r} for r in rule_ids]


# ── resolver routing (pin-coupled: safety.resolver 2.4.0) ─────────────────────────────────────────
def test_resolver_routes_the_unanchored_rule_to_the_pan_essential_hold():
    verdict, driving = resolve_or_raise(_fired(UNANCHORED_RULE), "safety")
    assert verdict == HOLD, f"unanchored rung missing or repointed: resolved {verdict!r}"
    assert driving == UNANCHORED_RULE, "provenance: the unanchored arm must be distinguishable from the curated one"


def test_resolver_routes_the_band_rule_to_the_graded_verdict():
    verdict, driving = resolve_or_raise(_fired(BAND_RULE), "safety")
    assert verdict == GRADED, f"graded band rung missing or repointed: resolved {verdict!r}"
    assert driving == BAND_RULE


def test_partial_band_outranks_the_tolerant_reassurance():
    """Acceptance criterion 2: a band carrier fires pan-essential-safety-axis-measured-clear (it keys
    the whole broadly_dependent class), which co-corroborates the TC#895 tolerant reassurance — the
    measured PARTIAL liability must beat it, not corroborate it. Against the old pin this resolves
    tolerant_reduced_safety_risk: the exact pre-#1794 pathology."""
    verdict, driving = resolve_or_raise(
        _fired("tolerant-safety-supportive", "pan-essential-safety-axis-measured-clear", BAND_RULE),
        "safety",
    )
    assert verdict == GRADED, (
        f"resolved {verdict!r} — a measured 0.60-0.85 broad-dependency liability is being outvoted "
        "(or worse, corroborated into a reassurance) by the tolerant rung"
    )
    assert driving == BAND_RULE


def test_graded_caution_stays_below_the_holds():
    for hold_rule, hold_verdict in (
        (CURATED_RULE, HOLD),
        ("gene-burden-lof-safety-warning", "human_genetics_safety_concern"),
    ):
        verdict, driving = resolve_or_raise(_fired(BAND_RULE, hold_rule), "safety")
        assert verdict == hold_verdict, f"graded caution outranked the {hold_rule!r} HOLD: {verdict!r}"
        assert driving == hold_rule


def test_curated_arm_keeps_driving_for_existing_carriers():
    verdict, driving = resolve_or_raise(_fired(CURATED_RULE), "safety")
    assert (verdict, driving) == (HOLD, CURATED_RULE), "existing curated-arm packages must stay byte-stable"


# ── dependency twin (pin-coupled: dependency.resolver 1.7.0) ──────────────────────────────────────
def test_dependency_gate_routes_unanchored_to_insufficient_not_a_veto():
    verdict, driving = resolve_or_raise(_fired(DEP_RULE), "dependency")
    assert verdict == "insufficient_underpowered_pan_essential", (
        f"resolved {verdict!r} — the anchor-unreachable class must take the T3 admissibility route "
        "(no fraction-only veto, and no NEW dependency token that would fail-close tp_gates)"
    )
    assert driving == DEP_RULE


# ── rule reachability from a real card summary (pin-coupled: rules 1.4.0 + card 3.1.0) ────────────
def test_unanchored_rules_fire_from_the_card_summary_through_the_shared_matcher():
    cards = [{"card_id": CARD, "summary": {"dependency_class": "common_essential_unanchored"}}]
    ids = {f.get("rule_id") for f in fired_rules(cards, "intracellular_intrinsic")}
    assert UNANCHORED_RULE in ids, "the unanchored broad-tox rule is not reachable on the intracellular_intrinsic axis"
    assert DEP_RULE in ids, "the dependency-twin insufficiency rule is not reachable"
    assert CURATED_RULE not in ids, "the curated arm must not double-fire on the unanchored class"


def test_band_rule_fires_only_on_the_partial_band():
    cards = [
        {
            "card_id": CARD,
            "summary": {"dependency_class": "broadly_dependent", "broad_dependency_band": "partial_broad_band"},
        }
    ]
    ids = {f.get("rule_id") for f in fired_rules(cards, "intracellular_intrinsic")}
    assert BAND_RULE in ids, "the partial-band rule is not reachable from broad_dependency_band"
    for band in ("pan_essential_band", "below_band"):
        cards = [{"card_id": CARD, "summary": {"dependency_class": "broadly_dependent", "broad_dependency_band": band}}]
        ids = {f.get("rule_id") for f in fired_rules(cards, "intracellular_intrinsic")}
        assert BAND_RULE not in ids, f"{band!r} must never fire the partial-band rule"


# ── consumer read: the headline carries the band (run.py mutation teeth) ──────────────────────────
def _cards_with(summary: dict) -> list[dict]:
    cards = [{"card_id": cid, "summary": {}} for cid in _RUN.CARDS]
    for c in cards:
        if c["card_id"] == CARD:
            c["summary"] = dict(summary)
    return cards


def test_headline_reads_the_band_field():
    summary = {"dependency_class": "broadly_dependent", "broad_dependency_band": "partial_broad_band"}
    hl = _RUN._headline(_cards_with(summary), _fired(BAND_RULE), (GRADED, BAND_RULE))
    assert hl.get("broad_dependency_band") == "partial_broad_band", "headline dropped/mangled broad_dependency_band"
    assert "broad_dependency_band" in _RUN._SYNTHESIS_FACET_KEYS, "the composed synthesis must see the band"


def test_headline_is_none_stable_when_the_band_is_absent():
    hl = _RUN._headline(_cards_with({}), [], ("insufficient", None))
    assert "broad_dependency_band" in hl and hl["broad_dependency_band"] is None


# ── consumer registration: the graded token everywhere a safety verdict is consumed ───────────────
def test_graded_token_has_a_phrase_and_concern_polarity():
    assert GRADED in _RUN._SAFETY_VERDICT_PHRASE, "headline phrase missing for the graded verdict"
    assert _RUN._safety_verdict_polarity(GRADED) == "negative", "a measured partial liability is a concern (red badge)"


def test_tp_gates_recognizes_the_graded_token_as_non_gating():
    sys.path.insert(0, str(SKILLS_ROOT / "target-profile" / "scripts"))
    try:
        import tp_gates
    finally:
        sys.path.pop(0)
    recognized = tp_gates._RECOGNIZED_GATING_VERDICTS["safety"]
    assert GRADED in recognized, (
        "unregistered: an unrecognized safety verdict fail-closes to a forced hold — the 12/504 band "
        "carriers would all hold at pin time"
    )
    assert ("safety", GRADED) not in tp_gates._FALLBACK_KILL_CAPABLE_VERDICTS, (
        "the graded caution is DELIBERATELY not a nomination-gate hold (nomination_verdict_gate 1.26.0) "
        "— do not add it to the kill-capable fallback"
    )
    assert GRADED not in tp_gates._SAFETY_WT_LOSS_CONCERNS, (
        "exists-safe-modality suppression applies to gate HITS only; the non-gating caution never "
        "produces one — keep the set aligned with the four HOLDs"
    )


def test_risk_projection_bins_the_graded_token_mid():
    assert _SAFETY_BINS.get(GRADED) == 1, (
        "the graded caution must be KEYED at the mid bin: the .get() default 0 is the fail-toward-safe "
        "under-read (#1573), and bin 2 would project a deliberate non-hold as a HOLD"
    )
    assert GRADED not in _SAFETY_DEFAULTED


# ── claim layer + question table (the unanchored class must read as the liability it is) ──────────
def test_claim_signal_is_strong_for_the_unanchored_class_and_discloses_the_outage():
    h = {"dependency_class": "common_essential_unanchored", "pan_essential_score": 0.91}
    sig, ev, _conflict = safety_claims._paness_signal(h, {})
    assert sig == "strong", f"unanchored pan-essential read {sig!r} — the measured fraction IS the liability signal"
    assert "UNREACHABLE" in ev and "UNVERIFIED" in ev, "the anchor outage must be disclosed, never silent"


def test_claim_evidence_discloses_the_partial_band():
    h = {"dependency_class": "broadly_dependent", "broad_dependency_band": "partial_broad_band"}
    sig, ev, _conflict = safety_claims._paness_signal(h, {})
    assert sig == "moderate"  # broadly_dependent was already a measured moderate liability
    assert "partial_broad_band" in ev, "the band grading must ride the claim evidence"


def test_claim_layer_is_byte_stable_when_the_new_states_are_absent():
    for h in ({}, {"dependency_class": "common_essential"}, {"dependency_class": "broadly_dependent"}):
        _sig, ev, _conflict = safety_claims._paness_signal(h, {})
        assert "UNREACHABLE" not in ev and "partial_broad_band" not in ev, (
            "pre-0.3.0 packages must not grow a #1794 evidence clause"
        )


def test_claim_atom_binds_the_band_and_stays_byte_stable_without_it():
    c = {CARD: {"dependency_class": "broadly_dependent", "broad_dependency_band": "partial_broad_band"}}
    atom = safety_claims._paness_atom({}, c)
    assert atom and "broad_dependency_band" in atom["values"], "the band must ride the citable atom"
    c = {CARD: {"dependency_class": "common_essential"}}
    atom = safety_claims._paness_atom({}, c)
    assert atom and "broad_dependency_band" not in atom["values"], "absent field must not appear in the atom"


def test_question_table_never_reads_the_unanchored_class_as_safe():
    assert safety_question_table._PAN_ESSENTIAL.get("common_essential_unanchored") == "absent", (
        "an UNVERIFIABLE pan-essential must mirror common_essential on the safe-valence row (concern), "
        "not the underpowered 'weak' — the fraction here is trusted"
    )
