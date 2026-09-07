"""Completeness tests for the kill_capable_verdicts registry (v1.5.0, roadmap §6.6).

The registry is the COMPLETE, per-resolver enumeration of every emitted verdict with
NEGATIVE decision semantics. These tests are the fail-closed, gate-complete teeth:

  * test_registry_well_formed            — shape + disposition vocabulary.
  * test_disposition_matches_classification — every entry's disposition MATCHES where it is
                                            actually classified (gated↔gates, excluded↔
                                            excluded_modality_scoped, contradiction↔
                                            positive_contradictions). A misfiled kill fails.
  * test_registry_verdicts_are_emitted   — every resolver-backed entry is emitted CASE-EXACT
                                            by its resolver. A rename that orphans a kill fails
                                            (this is the fail-open a renamed verdict would cause).
  * test_registry_covers_all_classified_negatives — every negative-classification pair whose
                                            sub_skill has a resolver MUST be in the registry, so a
                                            newly classified kill can never be silently omitted.
  * test_two_vetoes_and_gates_unchanged  — the active veto set stays EXACTLY 2 and the gates
                                            block is unchanged by adding the registry.

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

_VALID_DISPOSITIONS = {"gated", "excluded_modality_scoped", "contradiction"}


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
    return gated, excluded, contra


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
    gated, excluded, contra = _classification_sets(v)
    by_disposition = {"gated": gated, "excluded_modality_scoped": excluded, "contradiction": contra}
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
    positive_contradictions) whose sub_skill has a resolver MUST appear in the registry — so a
    newly classified kill can never be omitted from the complete declared set the gate iterates."""
    v = _load()
    gated, excluded, contra = _classification_sets(v)
    registry_pairs = {(s, verd) for s, verd, _ in _registry_entries(v)}
    all_negatives = gated | excluded | contra
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


def test_two_vetoes_and_gates_unchanged():
    """Adding the registry must NOT add a veto/hold — the active veto set stays exactly the two
    cross-target killers and the gates block is byte-stable (guards scope creep / over-veto)."""
    v = _load()
    veto = {(g["sub_skill"], g["verdict"]) for g in v["gates"] if g["action"] == "veto"}
    assert veto == {("dependency", "pan_essential_killer"), ("dependency", "non_dependent")}
    # Every registry `gated` entry is present in gates, and vice-versa for resolver-backed gates.
    gated = {(g["sub_skill"], g["verdict"]) for g in v["gates"]}
    reg_gated = {(s, verd) for s, verd, d in _registry_entries(v) if d == "gated"}
    assert reg_gated == gated, f"registry `gated` set {sorted(reg_gated)} must equal the gates block {sorted(gated)}"
