"""Completeness tests for the kill_capable_verdicts registry (v1.5.0, roadmap §6.6).

The registry is the COMPLETE, per-resolver enumeration of every emitted verdict with
NEGATIVE decision semantics. These tests are the fail-closed, gate-complete teeth:

  * test_registry_well_formed            — shape + disposition vocabulary.
  * test_disposition_matches_classification — every entry's disposition MATCHES where it is
                                            actually classified (gated↔gates, excluded↔
                                            excluded_modality_scoped, contradiction↔
                                            positive_contradictions, uncorroborated↔
                                            positive_uncorroborated). A misfiled kill fails.
  * test_registry_verdicts_are_emitted   — every resolver-backed entry is emitted CASE-EXACT
                                            by its resolver. A rename that orphans a kill fails
                                            (this is the fail-open a renamed verdict would cause).
  * test_registry_covers_all_classified_negatives — every negative-classification pair whose
                                            sub_skill has a resolver MUST be in the registry, so a
                                            newly classified kill can never be silently omitted.
  * test_vetoes_and_gates_unchanged_by_the_registry — the gates block, veto set included, is
                                            unchanged by ADDING THE REGISTRY. (Renamed 2026-09-18
                                            from test_two_vetoes_…: the cardinality was the control,
                                            never the invariant, and naming it made a deliberate
                                            third veto arm read as the defect the test guards.)
  * test_uncorroborated_is_relabelled_not_dropped — the LABEL-NOT-DROP teeth for the 4th
                                            disposition (v1.20.0). An `uncorroborated` verdict is
                                            not opposing evidence (so it must NOT sit in
                                            positive_contradictions) but it MUST still be in the
                                            strong-blocking union — deleting the row instead of
                                            relabelling it RELAXES the `strong` gate, which is
                                            fail-OPEN (measured: 2 pairs reach `strong`).

The sub_skill→resolver crosswalk (incl. the tractability_sm alias and the no-resolver
advisory axes) is reused from validators/validate_verdict_tokens.py so it cannot drift.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
VOCAB = REPO / "vocabularies" / "nomination_verdict_gate.yaml"
RESOLVERS = REPO / "resolvers"

_VALID_DISPOSITIONS = {"gated", "excluded_modality_scoped", "contradiction", "uncorroborated"}

# The two rows that moved contradiction → uncorroborated in v1.20.0, pinned BY NAME. They are the
# reason the 4th disposition exists, and the pairs the fail-open measurement was taken on
# (KRAS/COADREAD selectivity, and the dependency channel-disagreement rung). Pinned so that a later
# edit which DROPS them — instead of keeping the strong-block and only changing the label — fails
# here rather than silently promoting a target to `strong`.
_UNCORROBORATED_PAIRS = {
    ("selectivity", "discordant_across_comparators"),
    ("dependency", "discordant"),
}


def _load():
    return yaml.safe_load(VOCAB.read_text())


def _load_verdict_tokens_module():
    spec = importlib.util.spec_from_file_location(
        "validate_verdict_tokens", REPO / "validators" / "validate_verdict_tokens.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["validate_verdict_tokens"] = m
    spec.loader.exec_module(m)
    return m


VT = _load_verdict_tokens_module()
_EMITTED = VT.emitted_verdicts_by_gate(RESOLVERS)


def _registry_entries(v):
    """Yield (sub_skill, verdict, disposition) for every registry entry."""
    reg = v["kill_capable_verdicts"]
    for sub_skill, entries in reg.items():
        for e in entries:
            yield sub_skill, e["verdict"], e["disposition"]


def _classification_sets(v):
    gated = {(g["sub_skill"], g["verdict"]) for g in v["gates"]}
    excluded = {(e["sub_skill"], e["verdict"]) for e in v["excluded_modality_scoped"]}
    contra = {(c["sub_skill"], c["verdict"]) for c in v["positive_contradictions"]}
    uncorr = {(u["sub_skill"], u["verdict"]) for u in v["positive_uncorroborated"]}
    return gated, excluded, contra, uncorr


# ---------------------------------------------------------------------------


def test_registry_well_formed():
    v = _load()
    reg = v["kill_capable_verdicts"]
    assert isinstance(reg, dict) and reg, "kill_capable_verdicts must be a non-empty mapping"
    for sub_skill, verdict, disposition in _registry_entries(v):
        assert sub_skill and verdict, f"malformed registry entry under {sub_skill!r}"
        assert disposition in _VALID_DISPOSITIONS, (
            f"({sub_skill}, {verdict}) has disposition {disposition!r} ∉ {sorted(_VALID_DISPOSITIONS)}"
        )
    # No duplicate (sub_skill, verdict) pairs.
    pairs = [(s, verd) for s, verd, _ in _registry_entries(v)]
    assert len(pairs) == len(set(pairs)), f"duplicate registry entries: {pairs}"


def test_disposition_matches_classification():
    """Every registry entry's disposition must match the block it is actually classified in —
    a kill verdict can never be tagged one way and filed another (or filed nowhere)."""
    v = _load()
    gated, excluded, contra, uncorr = _classification_sets(v)
    by_disposition = {
        "gated": gated,
        "excluded_modality_scoped": excluded,
        "contradiction": contra,
        "uncorroborated": uncorr,
    }
    assert set(by_disposition) == _VALID_DISPOSITIONS, (
        "every valid disposition must have a classification block to check against — a disposition "
        "with no block here is unverified by construction"
    )
    for sub_skill, verdict, disposition in _registry_entries(v):
        expected_set = by_disposition[disposition]
        assert (sub_skill, verdict) in expected_set, (
            f"({sub_skill}, {verdict}) is registered as {disposition!r} but is NOT present in the "
            f"corresponding classification block — a kill verdict must be EXPLICITLY classified, "
            f"never silently ignored (§6.6 fail-open)"
        )


def test_registry_verdicts_are_emitted():
    """Every resolver-backed registry verdict must be emitted CASE-EXACT by its resolver. A
    rename that orphans a kill (the exact fail-open the registry guards) fails here."""
    v = _load()
    checked = 0
    for sub_skill, verdict, _disposition in _registry_entries(v):
        gate = VT.resolver_gate_for_subskill(sub_skill, _EMITTED)
        if gate is None:
            continue  # advisory-only axis (subtype_fit) — no resolver to compare against
        checked += 1
        assert verdict in _EMITTED[gate], (
            f"kill_capable_verdicts entry ({sub_skill}, {verdict}) is NOT emitted case-exact by "
            f"resolver `{gate}` (emits: {sorted(_EMITTED[gate])}) — a rename orphaned a kill verdict"
        )
    assert checked > 0, "no registry verdicts were resolver-checked (crosswalk broke?)"


def test_registry_covers_all_classified_negatives():
    """Every negative-classification pair (gates ∪ excluded_modality_scoped ∪
    positive_contradictions ∪ positive_uncorroborated) whose sub_skill has a resolver MUST appear in
    the registry — so a newly classified kill can never be omitted from the complete declared set
    the gate iterates."""
    v = _load()
    gated, excluded, contra, uncorr = _classification_sets(v)
    registry_pairs = {(s, verd) for s, verd, _ in _registry_entries(v)}
    all_negatives = gated | excluded | contra | uncorr
    missing = set()
    for sub_skill, verdict in all_negatives:
        gate = VT.resolver_gate_for_subskill(sub_skill, _EMITTED)
        if gate is None:
            continue  # advisory-only axis (expression / mechanism) — no resolver enumeration
        if (sub_skill, verdict) not in registry_pairs:
            missing.add((sub_skill, verdict))
    assert not missing, (
        f"classified kill verdicts absent from kill_capable_verdicts: {sorted(missing)} — "
        f"every resolver-backed negative must be in the registry"
    )


def test_vetoes_and_gates_unchanged_by_the_registry():
    """Adding the registry must NOT add a veto/hold — the active veto set stays exactly the
    cross-target killers and the gates block is byte-stable (guards scope creep / over-veto).

    RENAMED + WIDENED 2026-09-18 (Stage 2b): was `test_two_vetoes_and_gates_unchanged`, asserting a
    literal two-element set. The count was never the invariant — this test's job is that INTRODUCING
    THE REGISTRY did not add a kill, and it read the veto set only as the control for that. Baking
    the cardinality into the NAME made a deliberate third arm look like the failure the test was
    written to catch, so the name now says what is actually guarded. The set itself is asserted
    exactly once, in test_nomination_verdict_gate.test_conservative_veto_set, which keeps the ratchet.
    """
    v = _load()
    veto = {(g["sub_skill"], g["verdict"]) for g in v["gates"] if g["action"] == "veto"}
    assert veto == {
        ("dependency", "pan_essential_killer"),
        ("dependency", "non_dependent"),
        ("dependency", "not_dependent_in_indication"),
    }
    # Every registry `gated` entry is present in gates, and vice-versa for resolver-backed gates.
    gated = {(g["sub_skill"], g["verdict"]) for g in v["gates"]}
    reg_gated = {(s, verd) for s, verd, d in _registry_entries(v) if d == "gated"}
    assert reg_gated == gated, f"registry `gated` set {sorted(reg_gated)} must equal the gates block {sorted(gated)}"


def test_uncorroborated_is_relabelled_not_dropped():
    """LABEL-NOT-DROP teeth for the `uncorroborated` disposition (v1.20.0).

    An `uncorroborated` verdict says the axis's own arms DISAGREE WITH EACH OTHER — an absence of
    resolution, not a measurement against the target — so it must NOT be labelled opposing (not in
    positive_contradictions). But it MUST stay in the strong-blocking union: a `strong` claim
    requires corroboration, and removing the row instead of relabelling it RELAXES the gate, which
    is fail-OPEN. Measured 2026-09-13 over 56 target×indication pairs: 0 carrying pairs are at
    `strong` today, but KRAS/COADREAD (selectivity, 5 hits) reaches `strong` if the block is lost.
    """
    v = _load()
    _gated, _excluded, contra, uncorr = _classification_sets(v)

    # (1) Anti-vacuity: the block exists and is populated, so the assertions below have a population.
    assert uncorr, "positive_uncorroborated must be non-empty — an empty block makes these teeth vacuous"
    reg_uncorr = {(s, verd) for s, verd, d in _registry_entries(v) if d == "uncorroborated"}
    assert reg_uncorr == uncorr, (
        f"registry `uncorroborated` set {sorted(reg_uncorr)} must equal the positive_uncorroborated "
        f"block {sorted(uncorr)}"
    )

    # (2) The pinned rows are still classified uncorroborated (a drop, or a silent move back to
    # `contradiction`, fails here).
    assert _UNCORROBORATED_PAIRS <= uncorr, (
        f"pairs missing from positive_uncorroborated: {sorted(_UNCORROBORATED_PAIRS - uncorr)} — these "
        f"rows must be RELABELLED, never dropped (dropping relaxes the `strong` block = fail-open)"
    )

    # (3) NOT opposing: an absence of resolution must not be double-filed as opposing evidence.
    assert not (uncorr & contra), (
        f"{sorted(uncorr & contra)} is filed BOTH uncorroborated and as a positive_contradiction — "
        f"'the arms disagree' is not 'the measurement opposes'; it cannot be both"
    )

    # (4) The strong-blocking union still covers them (this is the property tp_gates must preserve:
    # tier byte-stability across the relabelling).
    strong_blocking = contra | uncorr
    assert _UNCORROBORATED_PAIRS <= strong_blocking, (
        "the relabelled rows left the strong-blocking union entirely — fail-open"
    )

    # (5) The contrast that must NOT move: tractability_sm/discordant stays a contradiction. There
    # the discordance IS the finding (a compound kills, but NOT through the target = evidence
    # against tractability, per that resolver's own rung comment), and it is the only live
    # contradiction holding CEACAM5/NSCLC below `strong`.
    assert ("tractability_sm", "discordant") in contra, (
        "tractability_sm/discordant must remain a positive_contradiction — `discordant` does two "
        "different jobs across axes and only the arms-disagree sense is uncorroborated"
    )
    assert ("tractability_sm", "discordant") not in uncorr
