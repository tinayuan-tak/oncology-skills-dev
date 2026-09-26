"""Guard A — resolver verdicts must stay classified by their Python consumers.

Bug class: a new verdict is added to a target-contracts resolver YAML, but a stale Python
consumer (an annotation whitelist / note-gate) is never updated, so a real, reachable verdict
silently falls through a branch that assumes it cannot occur. Two confirmed instances:
  - functional-requirement._DEPENDENCY_CALL_VERDICTS omitted partner_conditional_dependent
  - on-target-safety-liability._MECHANISM_MISMATCH_VERDICTS omitted wt_human_genetics_mechanism_mismatch
These tests read each resolver's verdict enum and assert the consumer sets stay exhaustive/aligned,
so the next such omission fails in CI instead of shipping. Skips cleanly when target-contracts is
not checked out (load_resolver returns None).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _skills_common.resolver import load_resolver
from _test_support import load_run_py

SKILLS_DIR = Path(__file__).resolve().parent.parent


def _resolver_verdicts(gate: str):
    """The full set of verdicts a resolver spec can emit (every rung + the default)."""
    spec = load_resolver(gate)
    if not isinstance(spec, dict):
        return None
    vs = {
        r["verdict"] for r in (spec.get("resolve") or []) if isinstance(r, dict) and isinstance(r.get("verdict"), str)
    }
    if isinstance(spec.get("default"), str):
        vs.add(spec["default"])
    return vs or None


def _load_skill_run(skill_name: str):
    return load_run_py(SKILLS_DIR / skill_name, f"_guarda_{skill_name.replace('-', '_')}_run")


_DEP = _resolver_verdicts("dependency")
_SAF = _resolver_verdicts("safety")
_CIS = _resolver_verdicts("cis_coherence")


@pytest.mark.skipif(_DEP is None, reason="dependency.resolver.yaml unavailable (target-contracts not checked out)")
def test_dependency_verdicts_are_exhaustively_classified():
    fr = _load_skill_run("functional-requirement")
    calls = set(fr._DEPENDENCY_CALL_VERDICTS)
    noncalls = set(fr._NON_CALL_VERDICTS)
    assert calls.isdisjoint(noncalls), f"verdict in BOTH call and non-call sets: {sorted(calls & noncalls)}"
    unclassified = _DEP - calls - noncalls
    assert not unclassified, (
        f"dependency.resolver.yaml emits verdict(s) {sorted(unclassified)} that "
        f"functional-requirement/run.py classifies as NEITHER a call nor a non-call. Add each to "
        f"_DEPENDENCY_CALL_VERDICTS (a real dependency call) or _NON_CALL_VERDICTS (predictability "
        f"annotation stays neutral)."
    )
    stale = (calls | noncalls) - _DEP
    assert not stale, f"consumer lists verdict(s) no longer in dependency.resolver.yaml: {sorted(stale)}"


@pytest.mark.skipif(_SAF is None, reason="safety.resolver.yaml unavailable (target-contracts not checked out)")
def test_safety_mechanism_mismatch_set_matches_resolver():
    saf = _load_skill_run("on-target-safety-liability")
    by_name = {v for v in _SAF if "mechanism_mismatch" in v}
    # RETIRED 2026-08-24 (VERDICT_REPRESENTATION.md Layer-2b/3): the role-proxy scalar mutant-selective
    # downgrade was removed from safety.resolver.yaml — the resolver emits the raw WT-loss concern and
    # the modality-conditional downgrade moved to tp_gates exists-safe-modality. Guard now asserts the
    # resolver emits ZERO *_mechanism_mismatch verdicts and the consumer set is correspondingly empty.
    assert not by_name, (
        f"expected ZERO *_mechanism_mismatch verdicts post-retirement, found {by_name} — a scalar "
        f"role-proxy downgrade has crept back; modality-conditionality belongs in the per-modality verdict."
    )
    assert set(saf._MECHANISM_MISMATCH_VERDICTS) == by_name == set(), (
        f"_MECHANISM_MISMATCH_VERDICTS {set(saf._MECHANISM_MISMATCH_VERDICTS)} must be empty post-retirement."
    )


@pytest.mark.skipif(_CIS is None, reason="cis_coherence.resolver.yaml unavailable (target-contracts not checked out)")
def test_cis_coherence_verdicts_are_exhaustively_registered():
    """cis-feature-coherence is a confidence-tier axis with no gate/veto, so an unregistered resolver
    verdict cannot cross the kill boundary — but it can silently forfeit its human phrase / polarity /
    coherent-chain classification (a future 8th cis rung shipping unnamed). Guard: every verdict the
    resolver can emit MUST have an entry in _CIS_COHERENCE_VERDICT_PHRASE (the registration surface that
    every downstream consumer keys off), and the phrase map must carry no stale token."""
    cis = _load_skill_run("cis-feature-coherence")
    registered = set(cis._CIS_COHERENCE_VERDICT_PHRASE)
    unregistered = _CIS - registered
    assert not unregistered, (
        f"cis_coherence.resolver.yaml emits verdict(s) {sorted(unregistered)} unregistered in "
        f"cis-feature-coherence/run.py _CIS_COHERENCE_VERDICT_PHRASE — add each a human phrase and, if "
        f"it is a coherent cis chain, to _CIS_COHERENT / _CIS_COHERENCE_FAVORABLE as appropriate."
    )
    stale = registered - _CIS
    assert not stale, (
        f"_CIS_COHERENCE_VERDICT_PHRASE lists verdict(s) no longer in cis_coherence.resolver.yaml: {sorted(stale)}"
    )
    # the coherent-chain classification set must itself be a subset of real resolver verdicts.
    assert set(cis._CIS_COHERENT) <= _CIS, (
        f"_CIS_COHERENT lists verdict(s) not emitted by cis_coherence.resolver.yaml: {sorted(set(cis._CIS_COHERENT) - _CIS)}"
    )


# ── deterministic_bins all-legs completeness (the consolidated guard #1547/#1555/#1568/#1573/#1602) ──
# The recurring bug: a keyed verdict→bin map in `deterministic_bins` is frozen, the resolver later grows
# a token, and that token silently falls to the `.get(v, D)` default — fail-OPEN on a governance-citable
# risk dim. This asserts, for every ADJUDICATED leg, that the LIVE map object + its declared
# route-to-default set exactly PARTITION the resolver's live verdict vocab, so a new resolver token can
# no longer reach a default without a deliberate map/defaulted-set edit that this guard forces.
from _skills_common.risk_projection import DETERMINISTIC_BIN_COMPLETENESS  # noqa: E402


def _completeness_gaps(keyed: set, defaulted: set, vocab: set):
    """Returns (uncovered, unknown, overlap): tokens in vocab covered by neither keyed nor defaulted;
    tokens declared but not in the vocab (stale); and tokens in BOTH keyed and defaulted (ambiguous)."""
    covered = set(keyed) | set(defaulted)
    return (set(vocab) - covered, covered - set(vocab), set(keyed) & set(defaulted))


@pytest.mark.parametrize("gate", sorted(DETERMINISTIC_BIN_COMPLETENESS))
def test_deterministic_bin_maps_cover_their_resolver_vocab(gate):
    vocab = _resolver_verdicts(gate)
    if vocab is None:
        pytest.skip(f"{gate}.resolver.yaml unavailable (target-contracts not checked out)")
    bin_map, defaulted = DETERMINISTIC_BIN_COMPLETENESS[gate]
    uncovered, unknown, overlap = _completeness_gaps(set(bin_map), defaulted, vocab)
    assert not uncovered, (
        f"deterministic_bins '{gate}' leg fails OPEN: resolver token(s) {sorted(uncovered)} are neither "
        f"keyed nor in the leg's *_DEFAULTED set — they silently hit the .get() default. Key them or "
        f"declare them as intentionally-defaulted."
    )
    assert not unknown, (
        f"deterministic_bins '{gate}' leg declares token(s) {sorted(unknown)} not in the resolver vocab (stale)."
    )
    assert not overlap, f"deterministic_bins '{gate}' leg lists token(s) {sorted(overlap)} as BOTH keyed and defaulted."


def test_completeness_guard_has_teeth():
    """The guard must FAIL when a leg fails open. Take a registered leg, drop one keyed token from the
    map copy (simulating a resolver token that was never mapped), and assert the check flags it."""
    gate = "surface_modality"
    vocab = _resolver_verdicts(gate)
    if vocab is None:
        pytest.skip("surface_modality.resolver.yaml unavailable")
    bin_map, defaulted = DETERMINISTIC_BIN_COMPLETENESS[gate]
    assert not _completeness_gaps(set(bin_map), defaulted, vocab)[0]  # baseline: really complete
    dropped = set(bin_map) - {sorted(bin_map)[0]}  # simulate one unmapped token
    uncovered, _, _ = _completeness_gaps(dropped, defaulted, vocab)
    assert uncovered, "completeness guard is toothless: an unmapped resolver token was not detected"
    # a stale declaration and a keyed∩defaulted overlap must also be caught
    assert _completeness_gaps(set(bin_map) | {"__phantom__"}, defaulted, vocab)[1] == {"__phantom__"}
    a_token = sorted(bin_map)[0]
    assert _completeness_gaps(set(bin_map), defaulted | {a_token}, vocab)[2] == {a_token}
