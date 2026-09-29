"""Regression guard: pan-essential broad-tox fail-open closure (skills #1794, tracker #1791).

THE TWO FAIL-OPENS THIS PINS AGAINST REOPENING (both relaxed a SAFETY liability):

1. UNREACHABLE CURATED ANCHOR → NO KILLER. When AchillesCommonEssentialControls was unreachable
   (offline / creds fail), a well-powered >=85% strongly-dependent fraction classified
   `common_essential_underpowered` — a class that is deliberately DARK on the safety axis — so
   `pan-essential-broad-tox-safety-warning` never fired and a transient/coverage miss read as
   "no broad-tox liability" for a PLK1-class core-essential. The closure splits the DISTINCT
   `common_essential_unanchored` class (analysis-methods depmap_chronos_distribution 0.3.0) and
   routes it to the SAME `pan_essential_broad_tox_concern` HOLD (driving_rule distinguishes the
   arms), while the dependency gate keeps treating it as insufficient (no fraction-only veto).

2. SILENT 0.60-0.85 BAND. The partial broad-dependency band classified `broadly_dependent`,
   raised NO safety signal (the warning keys only on common_essential) and — worse — actively
   CORROBORATED the TC#895 tolerant reassurance via `pan-essential-safety-axis-measured-clear`
   (which keys the whole broadly_dependent class). The closure grades it: NEW band field
   `broad_dependency_band == partial_broad_band` → `broad-dependency-partial-tox-safety-warning`
   → NEW graded verdict `broad_dependency_partial_tox_concern`, placed ABOVE every tolerant
   co-condition rung (min-priority reduce makes the witness co-fire verdict-harmless) but below
   the HOLDs (12/504 corpus carriers include managed clinical-stage targets AURKA/MTOR/ATR/PRMT5
   — a HOLD would over-fire; CLEAN was the fail-open).

Each test asserts one half of an add→consume chain, so reverting ANY half (card vocab, rule,
rung, precedence, dependency-gate admissibility, WT-loss conditioning, nomination-gate
provenance) fails RED here — "declaring the rule != declaring the verdict".
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml"
SAFETY = REPO / "resolvers" / "safety.resolver.yaml"
DEPENDENCY = REPO / "resolvers" / "dependency.resolver.yaml"
COND = REPO / "vocabularies" / "wt_loss_safety_conditioning.yaml"
GATE = REPO / "vocabularies" / "nomination_verdict_gate.yaml"
CARD = REPO / "cards" / "pan-cancer-crispr-dependency-distribution.card.yaml"

CARD_ID = "pan-cancer-crispr-dependency-distribution"
UNANCHORED_CLASS = "common_essential_unanchored"
BAND_FIELD = "broad_dependency_band"
PARTIAL_BAND = "partial_broad_band"

UNANCHORED_SAFETY_RULE = "pan-essential-unanchored-broad-tox-safety-warning"
BAND_SAFETY_RULE = "broad-dependency-partial-tox-safety-warning"
UNANCHORED_DEP_RULE = "common-essential-unanchored-insufficient"
CURATED_SAFETY_RULE = "pan-essential-broad-tox-safety-warning"

HOLD_VERDICT = "pan_essential_broad_tox_concern"
GRADED_VERDICT = "broad_dependency_partial_tox_concern"


def _rules() -> list[dict]:
    return yaml.safe_load(RULES.read_text())["rules"]


def _rule(rule_id: str) -> dict:
    r = next((r for r in _rules() if isinstance(r, dict) and r.get("rule_id") == rule_id), None)
    assert r is not None, f"{rule_id} must be defined in intracellular-intrinsic.rules.yaml"
    return r


def _safety() -> dict:
    return yaml.safe_load(SAFETY.read_text())


# ── card declarations (the vocabulary half of the add→consume chain) ────────────────────────────


def test_card_declares_the_unanchored_class_and_the_band_field():
    card = yaml.safe_load(CARD.read_text())
    vocab = card["outputs"]["summary_fields_vocabulary"]
    assert UNANCHORED_CLASS in vocab["dependency_class"], (
        f"{UNANCHORED_CLASS} missing from the card's dependency_class vocabulary — the emitted "
        "class would be an undeclared token (false absence for every closed-set consumer)"
    )
    assert BAND_FIELD in card["outputs"]["summary_fields"], f"{BAND_FIELD} not declared a summary field"
    assert set(vocab[BAND_FIELD]) == {"pan_essential_band", PARTIAL_BAND, "below_band"}, vocab.get(BAND_FIELD)
    # the audit/ladder field is the RAW fraction-only call and must NOT grow the unanchored value
    # (the flag is False on that path by design — auditable degradation).
    assert UNANCHORED_CLASS not in vocab["pan_essential_fraction_call"], (
        "pan_essential_fraction_call is the fraction-only audit ladder; it never emits unanchored"
    )


# ── fail-open 1: unreachable anchor ──────────────────────────────────────────────────────────────


def test_unanchored_safety_rule_keys_on_the_unanchored_class():
    rule = _rule(UNANCHORED_SAFETY_RULE)
    w = rule["when"]
    assert w.get("card_id") == CARD_ID and w.get("field") == "dependency_class"
    assert w.get("equals") == UNANCHORED_CLASS
    sig = rule.get("signals", {})
    # mirror of the curated sibling: opposing on the full-KO channels, dominant.
    assert sig.get("small_molecule") == "opposing" and sig.get("degrader") == "opposing", sig
    assert rule.get("dominant") is True


def test_unanchored_rung_reuses_the_pan_essential_hold_directly_below_the_curated_arm():
    """An UNVERIFIABLE pan-essential holds exactly as a verified one (the missing anchor removes
    the exculpatory T3 evidence, not the liability). SAME token — a NEW one would be unseen by
    the nomination gate's closed sets. Sits directly below the curated rung."""
    spec = _safety()
    rungs = {r.get("when_fired"): r for r in spec["resolve"] if isinstance(r.get("when_fired"), str)}
    assert UNANCHORED_SAFETY_RULE in rungs, (
        f"safety resolver has NO rung consuming {UNANCHORED_SAFETY_RULE} — the anchor-outage "
        "fail-open is silently reopened (rule fires into nothing)"
    )
    rung = rungs[UNANCHORED_SAFETY_RULE]
    assert rung["verdict"] == HOLD_VERDICT, rung
    curated = rungs[CURATED_SAFETY_RULE]
    assert curated["priority"] < rung["priority"], "curated arm must stay the primary provenance"
    # and above every soft / reassurance / co-condition rung
    for r in spec["resolve"]:
        if r["verdict"] in ("tolerant_reduced_safety_risk", "moderately_constrained_safety", "data_unavailable"):
            assert rung["priority"] < r["priority"], (
                f"unanchored HOLD must outrank the soft rung {r} — reassurance beating an "
                "unverifiable pan-essential is the fail-open direction"
            )


def test_dependency_gate_still_routes_unanchored_to_insufficient_not_a_veto():
    """The DEPENDENCY reading is unchanged by design: no fraction-only veto (T3 direction). The
    priority-0 admissibility rung must consume the unanchored rule so the re-routed population
    keeps the insufficient verdict — and never reaches pan_essential_killer."""
    dep_rule = _rule(UNANCHORED_DEP_RULE)
    w = dep_rule["when"]
    assert w.get("card_id") == CARD_ID and w.get("field") == "dependency_class"
    assert w.get("equals") == UNANCHORED_CLASS
    sig = dep_rule.get("signals", {})
    assert sig.get("small_molecule") == "insufficient" and sig.get("degrader") == "insufficient", sig

    dep = yaml.safe_load(DEPENDENCY.read_text())
    guard = next(r for r in dep["resolve"] if r.get("verdict") == "insufficient_underpowered_pan_essential")
    assert UNANCHORED_DEP_RULE in guard.get("when_any_fired", []), (
        "the priority-0 pan-essential admissibility rung must consume "
        f"{UNANCHORED_DEP_RULE}; without it the unanchored population loses its insufficient routing"
    )
    assert guard.get("priority") == 0
    # NO new dependency verdict token (tp_gates fail-closes an unrecognized dependency verdict to
    # a forced VETO): the unanchored population must reuse the existing admissibility verdict.
    killer_keys = [
        r
        for r in dep["resolve"]
        if r.get("verdict") == "pan_essential_killer" and r.get("when_fired") == UNANCHORED_DEP_RULE
    ]
    assert not killer_keys, "unanchored must NEVER feed pan_essential_killer"


# ── fail-open 2: the 0.60-0.85 band ─────────────────────────────────────────────────────────────


def test_band_rule_keys_on_partial_broad_band_and_is_graded_not_dominant():
    rule = _rule(BAND_SAFETY_RULE)
    w = rule["when"]
    assert w.get("card_id") == CARD_ID and w.get("field") == BAND_FIELD
    assert w.get("equals") == PARTIAL_BAND
    sig = rule.get("signals", {})
    assert sig.get("small_molecule") == "opposing" and sig.get("degrader") == "opposing", sig
    assert rule.get("dominant") is not True, (
        "the band rule is a GRADED concern (12/504 corpus carriers include managed clinical-stage "
        "targets); dominant would over-claim the pan-essential severity"
    )


def test_band_rung_emits_the_graded_verdict_above_every_tolerant_co_condition_rung():
    """The sharpest half of fail-open 2: pan-essential-safety-axis-measured-clear fires on the
    WHOLE broadly_dependent class, so a band carrier CO-FIRES the tolerant co-condition witness.
    The graded rung must outrank every tolerant_reduced_safety_risk rung (min-priority reduce),
    or the band's measured partial liability keeps corroborating the reassurance."""
    spec = _safety()
    rung = next((r for r in spec["resolve"] if r.get("when_fired") == BAND_SAFETY_RULE), None)
    assert rung is not None, (
        f"safety resolver has NO rung consuming {BAND_SAFETY_RULE} — the 0.60-0.85 band is "
        "invisible on the safety axis again"
    )
    assert rung["verdict"] == GRADED_VERDICT, (
        f"band rung must emit the GRADED {GRADED_VERDICT}, got {rung['verdict']} — reusing the "
        "pan-essential HOLD erases the grading; reusing a soft token erases the concern"
    )
    for r in spec["resolve"]:
        if r["verdict"] in ("tolerant_reduced_safety_risk", "moderately_constrained_safety", "data_unavailable"):
            assert rung["priority"] < r["priority"], (
                f"graded band rung must outrank {r.get('when_fired') or r.get('when_all_fired')} "
                "— otherwise the measured-clear witness corroborates tolerant for band carriers"
            )
    # ...but stays BELOW the measured HOLDs (graded, not a hold).
    for r in spec["resolve"]:
        if r["verdict"] in (
            "highly_constrained_safety_concern",
            HOLD_VERDICT,
            "normal_tissue_protein_safety_concern",
            "human_genetics_safety_concern",
        ):
            assert r["priority"] < rung["priority"], f"band rung must not outrank the HOLD rung {r}"


def test_measured_clear_witness_still_excludes_the_dark_classes():
    """The TC#895 witness keys broadly_dependent (deliberate: the band conservatism is enforced at
    resolver precedence, asserted above) but must keep excluding the DARK coverage-gap classes —
    including the NEW unanchored one — so they can never corroborate a constraint-only reassurance."""
    witness = _rule("pan-essential-safety-axis-measured-clear")
    allowed = witness["when"].get("in", [])
    for dark in ("common_essential_underpowered", UNANCHORED_CLASS, "non_dependent_underpowered", "data_unavailable"):
        assert dark not in allowed, f"{dark} is a coverage gap / unverified state, not a measured-clear"


# ── shared conditioning + provenance ─────────────────────────────────────────────────────────────


def test_both_new_rules_join_the_wt_loss_concern_conditioning():
    cond = yaml.safe_load(COND.read_text())
    concern = cond.get("concern_rules", [])
    assert UNANCHORED_SAFETY_RULE in concern, "unanchored warning is a WT-loss/full-KO concern"
    assert BAND_SAFETY_RULE in concern, "band warning is a WT-loss/full-KO concern"


def test_gate_provenance_names_both_pan_essential_arms_and_deliberately_omits_the_graded_token():
    gate = yaml.safe_load(GATE.read_text())
    rows = [g for g in gate["gates"] if g.get("verdict") == HOLD_VERDICT]
    assert len(rows) == 1
    ids = rows[0].get("driving_rule_ids", [])
    assert CURATED_SAFETY_RULE in ids and UNANCHORED_SAFETY_RULE in ids, ids
    # DELIBERATE ABSENCE (recorded in the vocab version note): the graded token is a caution with
    # no negative decision semantics — like moderately_constrained_safety it must appear in NO
    # gates / kill_capable / positive_* block. If someone later classifies it, the kill-capable
    # completeness suite takes over; this pin catches the accidental half-add.
    text = GATE.read_text()
    for block in ("gates", "kill_capable_verdicts"):
        blk = gate.get(block)
        assert GRADED_VERDICT not in str(blk), (
            f"{GRADED_VERDICT} classified in {block}: that promotes the graded caution to a kill/hold "
            "— a deliberate design change that needs its own review, not a drive-by"
        )
    assert text.count(GRADED_VERDICT) >= 1, "the deliberate absence must at least be documented"
