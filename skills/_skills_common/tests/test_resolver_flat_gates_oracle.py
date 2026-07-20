"""GOLDEN-ORACLE equivalence for the 6 flat-ladder gates (gap #5 step 3).

For each gate, proves the declarative resolver spec == the Python _verdict if-chain
byte-for-byte (verdict AND driving_rule_id) across ALL 2^n fired-set combinations of the
gate's rule_ids. Same discipline as the dependency oracle — transcribe the brain, PROVE
the transcription is exact, THEN the if-chain becomes deletable.

The 6 flat gates are pure single-rule (when_fired) ladders (no compound/any-of cases —
those live only in dependency). tumor-presence + genomic-alteration-profile are EXCLUDED:
their verdict logic (per-modality dual-ladder / multi-axis mutation+CN) exceeds the
fired-set-pattern-match guardrail, so they stay as code (documented exception).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SKILLS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills")
CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)
    return m


_resolver = _load("resolver_ut_flat", SKILLS / "_skills_common" / "resolver.py")

# gate short → (skill dir, [rule_ids the _verdict references])
GATES = {
    "selectivity": ("tumor-selectivity", [
        "tvn-strong-selective-supportive", "tvn-modest-selective-supportive",
        "tvn-discordant-neutral-flagged", "tvn-not-selective-neutral",
        "tvn-not-informative-neutral", "tvn-data-unavailable-insufficient"]),
    "mechanism": ("mechanism-and-pharmacology", [
        "mechanism-well-characterized-supportive", "mechanism-partial-neutral",
        "mechanism-sparse-warning", "has-pd-marker-supportive",
        "mechanism-data-unavailable-insufficient"]),
    "differentiation": ("differentiation-landscape", [
        "cooccurrence-both-patterns-supportive", "strong-mutual-exclusivity-supportive",
        "cooccurrence-strong-supportive", "has-cooccurring-driver-supportive",
        "cooccurrence-modest-cooccurring-neutral",
        "cooccurrence-modest-mutually-exclusive-neutral", "cooccurrence-ns-neutral",
        "cooccurrence-data-unavailable-insufficient"]),
    "surface_modality": ("surface-modality-fit", [
        "adc-preferred-supportive", "tce-preferred-supportive", "both-viable-supportive",
        "neither-viable-killer", "isoform-dependent-modality-suppression",
        "modality-ambiguous-insufficient"]),
    "safety": ("on-target-safety-liability", [
        "highly-constrained-safety-warning", "tolerant-safety-supportive",
        "moderately-constrained-safety-neutral", "constraint-data-unavailable-insufficient"]),
    "synthetic_lethal_partners": ("synthetic-lethal-partners", [
        "sl-experimental-partner-context-conditional",
        "sl-computational-partner-informational", "sl-no-partner-neutral",
        "sl-data-unavailable-insufficient"]),
}


def _oracle_verdict_fn(skill_dir: str):
    mod = _load(f"oracle_{skill_dir.replace('-', '_')}",
                SKILLS / skill_dir / "scripts" / "run.py")
    return mod._verdict


@pytest.mark.parametrize("gate", list(GATES.keys()))
def test_spec_loads(gate):
    spec = _resolver.load_resolver(gate, contracts_repo=CONTRACTS)
    assert spec is not None and spec["gate"] == gate


@pytest.mark.parametrize("gate", list(GATES.keys()))
def test_exhaustive_equivalence(gate):
    """EVERY subset of the gate's rule_ids: resolver spec == Python _verdict, both
    verdict AND driving_rule_id."""
    skill_dir, rule_ids = GATES[gate]
    spec = _resolver.load_resolver(gate, contracts_repo=CONTRACTS)
    oracle = _oracle_verdict_fn(skill_dir)
    n = len(rule_ids)
    mismatches = []
    for bits in range(2 ** n):
        fired = [{"rule_id": rule_ids[i]} for i in range(n) if bits & (1 << i)]
        if oracle(fired) != _resolver.resolve_verdict(fired, spec):
            mismatches.append((
                [r["rule_id"] for r in fired], oracle(fired),
                _resolver.resolve_verdict(fired, spec)))
    assert not mismatches, (
        f"[{gate}] {len(mismatches)}/{2**n} combos diverge. First:\n" +
        "\n".join(f"  {m[0]}\n    oracle={m[1]} spec={m[2]}" for m in mismatches[:5]))
