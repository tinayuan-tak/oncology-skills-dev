"""cis-feature-coherence skill — hermetic verdict tests (no S3/network).

Pins that run.py's _verdict wires the SHARED cis_coherence resolver (resolve_or_raise → the merged
cis_coherence.resolver.yaml) and reproduces the deterministic 2×2 cross-tab (leg-1 cis-dosage ×
leg-2 dependency-coupling), plus the honest-abstention default. This is the skills-layer integration
golden; the target-contracts side has its own resolver golden (test_cis_coherence_resolver.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from run import _verdict  # noqa: E402

# leg tokens (fired by interpretation-rules/cis-coherence.rules.yaml)
DOSAGE_COUPLED = "cis-dosage-coupled-supportive"
DOSAGE_UNCOUPLED = "cis-dosage-uncoupled-neutral"
DEP_CORR = "cis-expr-dependency-coupled-supportive"
DEP_ABSENT = "cis-expr-dependency-absent-neutral"
DEP_CONJOINT = "cis-conjoint-dependent-supportive"


def _fired(*rule_ids):
    return [{"rule_id": rid} for rid in rule_ids]


def test_coherent_cis_driver_via_conjoint():
    v, drv = _verdict(_fired(DOSAGE_COUPLED, DEP_CONJOINT))
    assert v == "coherent_cis_driver"
    assert drv == DOSAGE_COUPLED


def test_coherent_cis_driver_via_correlation():
    v, drv = _verdict(_fired(DOSAGE_COUPLED, DEP_CORR))
    assert v == "coherent_cis_driver"
    assert drv == DOSAGE_COUPLED


def test_expressed_cis_coupled_inert():
    """CN drives expression but dependency absent → the abundance-laundering guard."""
    v, drv = _verdict(_fired(DOSAGE_COUPLED, DEP_ABSENT))
    assert v == "expressed_cis_coupled_inert"
    assert drv == DEP_ABSENT


def test_dependency_without_cis_dosage():
    """Real dependency, but expression is copy-number-independent (trans-regulated)."""
    assert _verdict(_fired(DOSAGE_UNCOUPLED, DEP_CONJOINT)) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)
    assert _verdict(_fired(DOSAGE_UNCOUPLED, DEP_CORR)) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)


def test_cis_uncoupled_no_dependency():
    assert _verdict(_fired(DOSAGE_UNCOUPLED, DEP_ABSENT)) == ("cis_uncoupled_no_dependency", DOSAGE_UNCOUPLED)


def test_coherent_wins_first_match_when_both_leg2_fire():
    assert _verdict(_fired(DOSAGE_COUPLED, DEP_CONJOINT, DEP_CORR)) == ("coherent_cis_driver", DOSAGE_COUPLED)


def test_insufficient_default_when_nothing_fired():
    assert _verdict(_fired()) == ("insufficient_cis_coherence", None)


def test_insufficient_when_only_one_leg():
    # leg-1 present but leg-2 unmeasured (and vice versa) → cannot assemble the chain → abstain.
    assert _verdict(_fired(DOSAGE_COUPLED)) == ("insufficient_cis_coherence", None)
    assert _verdict(_fired(DEP_CORR)) == ("insufficient_cis_coherence", None)
