"""#1793 organ-coverage spine — the SK consumer wiring for the TPHP HPA-BLIND vital-organ view.

★ PIN-COUPLED: the resolver-routing / rule-reachability tests here require target-contracts >=
b2e19734 (interpretation rules 1.3.0 + safety.resolver 2.3.0). Against the OLD skills-validate pin
they fail BY DESIGN — this file is one of the changes that must land atomically with the human
`ref:` pin bump (see issue #1793's pin-bump-obligations comment).

What is pinned, and why each arm exists:
  - RESOLVER ROUTING: tphp-hpa-blind-vital-organ-protein-safety-warning alone resolves to the
    normal_tissue_protein_safety_concern HOLD with itself as driving_rule — the organ-coverage twin
    of the HPA rung, same verdict token, arms distinguishable in provenance.
  - PRECEDENCE (acceptance criterion 1, the sharpest pre-#1793 failure): HPA `absent` fires the
    normal-tissue-essential-tissue-measured-clear witness, which co-corroborates the TC#895
    tolerant_reduced_safety_risk rung — so a thyroid-abundant, gnomAD-tolerant target did not merely
    miss a HOLD, it resolved REASSURING. The blind-organ rung must outrank that.
  - PROVENANCE STABILITY: when BOTH protein arms fire, the HPA rung keeps driving_rule — existing
    carriers stay byte-stable.
  - RULE REACHABILITY: the rule fires through the real shared `when:` matcher from a card summary
    (a rename of the field or enum value upstream reds this, not just the synthetic-fired tests).
  - CONSUMER READ (mutation teeth for run.py): _headline must carry all four new fields — reverting
    the headline read reds these without touching the resolver.
  - NONE-STABILITY (the absence direction): on a package frozen before analysis-methods
    tphp_normal_protein 0.5.0 (ae94fb3e) the fields are absent and every claim/table surface must be
    byte-identical to the pre-1.22.0 behavior — the verdict flips only when packages regenerate.
  - FAIL-CLOSED DIRECTION: vital_organ_low / no_vital_organ_signal / data_unavailable NEVER reassure
    (no_vital_organ_signal is not a clean sweep; pituitary is covered by NO protein panel).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

from _skills_common import fired_rules, safety_claims, safety_question_table  # noqa: E402
from _skills_common.resolver import resolve_or_raise  # noqa: E402

_RUN = load_run_py(SKILL_DIR, "_safety_run_tphp_blind")

TPHP_CARD = "normal-tissue-protein-abundance-tphp"
RULE = "tphp-hpa-blind-vital-organ-protein-safety-warning"
HPA_RULE = "normal-tissue-protein-liability-safety-warning"
HOLD = "normal_tissue_protein_safety_concern"

NEW_FIELDS = (
    "tphp_hpa_blind_vital_organ_liability_class",
    "n_hpa_blind_vital_organs_above_abundance_floor",
    "hpa_blind_vital_organs_above_floor",
    "hpa_blind_vital_organs_uncovered",
)


def _fired(*rule_ids: str) -> list[dict]:
    return [{"rule_id": r} for r in rule_ids]


# ── resolver routing (pin-coupled: safety.resolver 2.3.0) ─────────────────────────────────────────
def test_resolver_routes_the_blind_organ_rule_to_the_hold():
    verdict, driving = resolve_or_raise(_fired(RULE), "safety")
    assert verdict == HOLD, f"blind-organ rung missing or repointed: resolved {verdict!r}"
    assert driving == RULE


def test_blind_organ_liability_outranks_the_tolerant_reassurance():
    """Acceptance criterion 1: HPA-absent (measured-clear witness) + gnomAD-tolerant + TPHP
    blind-organ liability must resolve to the HOLD, not tolerant_reduced_safety_risk."""
    verdict, driving = resolve_or_raise(
        _fired("tolerant-safety-supportive", "normal-tissue-essential-tissue-measured-clear", RULE),
        "safety",
    )
    assert verdict == HOLD, (
        f"resolved {verdict!r} — a thyroid-abundant, gnomAD-tolerant target is being reassured by a "
        "protein panel that never looked at the implicated organ"
    )
    assert driving == RULE


def test_hpa_rung_keeps_driving_when_both_protein_arms_fire():
    verdict, driving = resolve_or_raise(_fired(HPA_RULE, RULE), "safety")
    assert verdict == HOLD
    assert driving == HPA_RULE, "provenance drift: existing HPA-carrier packages must stay byte-stable"


# ── rule reachability from a real card summary (pin-coupled: rules 1.3.0) ─────────────────────────
def test_rule_fires_from_the_card_summary_through_the_shared_matcher():
    cards = [
        {
            "card_id": TPHP_CARD,
            "summary": {
                "tphp_hpa_blind_vital_organ_liability_class": "vital_organ_abundant",
                "hpa_blind_vital_organs_above_floor": ["thyroid gland"],
            },
        }
    ]
    ids = {f.get("rule_id") for f in fired_rules(cards, "intracellular_intrinsic")}
    assert RULE in ids, "the blind-organ rule is not reachable on the intracellular_intrinsic axis"


def test_non_liability_classes_do_not_fire_the_rule():
    for cls in ("vital_organ_low", "no_vital_organ_signal", "data_unavailable"):
        cards = [{"card_id": TPHP_CARD, "summary": {"tphp_hpa_blind_vital_organ_liability_class": cls}}]
        ids = {f.get("rule_id") for f in fired_rules(cards, "intracellular_intrinsic")}
        assert RULE not in ids, f"{cls!r} must never fire the liability rule (absence is not a liability)"


# ── consumer read: the headline carries all four fields (run.py mutation teeth) ───────────────────
def _cards_with(tphp_summary: dict) -> list[dict]:
    cards = [{"card_id": cid, "summary": {}} for cid in _RUN.CARDS]
    for c in cards:
        if c["card_id"] == TPHP_CARD:
            c["summary"] = dict(tphp_summary)
    return cards


def test_headline_reads_the_four_blind_organ_fields():
    summary = {
        "tphp_hpa_blind_vital_organ_liability_class": "vital_organ_abundant",
        "n_hpa_blind_vital_organs_above_abundance_floor": 1,
        "hpa_blind_vital_organs_above_floor": ["thyroid gland"],
        "hpa_blind_vital_organs_uncovered": ["pituitary"],
    }
    hl = _RUN._headline(_cards_with(summary), _fired(RULE), (HOLD, RULE))
    for k in NEW_FIELDS:
        assert hl.get(k) == summary[k], f"headline dropped/mangled {k}: {hl.get(k)!r}"


def test_headline_is_none_stable_when_the_fields_are_absent():
    hl = _RUN._headline(_cards_with({}), [], ("insufficient", None))
    for k in NEW_FIELDS:
        assert k in hl and hl[k] is None, f"absent field must read None, got {hl.get(k)!r}"


# ── claim layer (#1792 confidence machinery must SEE the measured liability) ──────────────────────
def test_claim_signal_promotes_on_the_measured_blind_organ_liability():
    h = {"tphp_hpa_blind_vital_organ_liability_class": "vital_organ_abundant"}
    assert safety_claims._normaltissue_sig(h) == "strong"
    # over an HPA measured-clear too (disjoint organ sets), with the scope-limitation disclosed:
    h["essential_tissue_flag"] = "absent"
    sig, ev, conflict = safety_claims._normaltissue_signal(h, {})
    assert sig == "strong"
    assert "TPHP" in ev and "vital_organ_abundant" in ev
    assert conflict and "16-name" in conflict


def test_claim_layer_is_byte_stable_when_the_field_is_absent():
    for h in ({}, {"essential_tissue_flag": "absent"}, {"essential_tissue_flag": "present"}):
        expected_sig = {"absent": "absent", "present": "strong"}.get(h.get("essential_tissue_flag"), "unmeasured")
        sig, ev, conflict = safety_claims._normaltissue_signal(h, {})
        assert sig == expected_sig
        assert "TPHP" not in ev, "pre-0.5.0 packages must not grow a TPHP evidence clause"
        assert conflict is None


def test_claim_signal_never_promotes_on_non_liability_classes():
    for cls in ("vital_organ_low", "no_vital_organ_signal", "data_unavailable"):
        h = {"tphp_hpa_blind_vital_organ_liability_class": cls, "essential_tissue_flag": "absent"}
        assert safety_claims._normaltissue_sig(h) == "absent", f"{cls!r} must not move the claim signal"


def test_claim_atom_cites_the_tphp_card_when_the_blind_arm_drives():
    c = {
        TPHP_CARD: {
            "tphp_hpa_blind_vital_organ_liability_class": "vital_organ_abundant",
            "hpa_blind_vital_organs_above_floor": ["thyroid gland"],
            "hpa_blind_vital_organs_uncovered": ["pituitary"],
        },
        "normal-tissue-liability": {"essential_tissue_flag": "absent"},
    }
    atom = safety_claims._normaltissue_atom({}, c)
    assert atom and atom["cite"]["card_id"] == TPHP_CARD, f"atom cites {atom and atom['cite']['card_id']!r}"
    assert "hpa_blind_vital_organs_uncovered" in atom["values"], "the coverage GAP must ride the citable atom"
    # HPA `present` keeps its own atom — the HPA arm measured the concern itself:
    c["normal-tissue-liability"]["essential_tissue_flag"] = "present"
    atom = safety_claims._normaltissue_atom({}, c)
    assert atom and atom["cite"]["card_id"] == "normal-tissue-liability"


def test_claim_atom_is_byte_stable_when_the_field_is_absent():
    c = {"normal-tissue-liability": {"essential_tissue_flag": "absent"}}
    atom = safety_claims._normaltissue_atom({}, c)
    assert atom and atom["cite"]["card_id"] == "normal-tissue-liability"


# ── question table (the #1792 leg must not read strong-safe off a blind arm) ──────────────────────
def test_question_table_leg_flags_the_blind_organ_liability():
    h = {"essential_tissue_flag": "absent", "tphp_hpa_blind_vital_organ_liability_class": "vital_organ_abundant"}
    tier, label = safety_question_table._normal_tissue_leg(h)
    assert tier == "absent", f"leg read {tier!r} — a measured blind-organ liability rendered as safe"
    assert "HPA-blind" in label


def test_question_table_leg_is_byte_stable_and_fail_closed_otherwise():
    assert safety_question_table._normal_tissue_leg({"essential_tissue_flag": "absent"}) == ("strong", "absent")
    assert safety_question_table._normal_tissue_leg({"essential_tissue_flag": "present"}) == ("absent", "present")
    assert safety_question_table._normal_tissue_leg({}) == ("unmeasured", "—")
    for cls in ("vital_organ_low", "no_vital_organ_signal", "data_unavailable"):
        h = {"essential_tissue_flag": "absent", "tphp_hpa_blind_vital_organ_liability_class": cls}
        assert safety_question_table._normal_tissue_leg(h) == ("strong", "absent"), (
            f"{cls!r} must neither flag nor reassure beyond the HPA read"
        )
