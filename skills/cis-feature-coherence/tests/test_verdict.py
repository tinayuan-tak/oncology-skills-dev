"""cis-feature-coherence skill — hermetic verdict tests (no S3/network).

Pins that run.py's _verdict wires the SHARED cis_coherence resolver (resolve_or_raise → the merged
cis_coherence.resolver.yaml) and reproduces the deterministic cross-tab (leg-1 cis-dosage × its
DIRECTION × leg-2 dependency-coupling), plus the honest-abstention default. This is the skills-layer
integration golden; the target-contracts side has its own resolver golden (test_cis_coherence_resolver.py).

Resolver v1.3.0 made leg-1 a 3×2: the cis-dosage CLASS token says the coupling exists, and a separate
DIRECTION token says which CN arm carries it. A coupled class with NO direction can no longer reach a
coherent verdict — that is deliberate (an amplicon oncogene and a deleted suppressor used to read
identically), and `test_dosage_class_without_a_direction_abstains` is the pin for it.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

_run = load_run_py(Path(__file__).resolve().parent.parent, "cis_run")
_verdict = _run._verdict

# leg tokens (fired by interpretation-rules/cis-coherence.rules.yaml)
DOSAGE_COUPLED = "cis-dosage-coupled-supportive"
AMP = "cis-dosage-amplification-coupled-supportive"  # direction: gain drives expression UP
DEL = "cis-dosage-deletion-coupled-neutral"  # direction: loss drives expression DOWN
DOSAGE_UNCOUPLED = "cis-dosage-uncoupled-neutral"
DEP_CORR = "cis-expr-dependency-coupled-supportive"
DEP_ABSENT = "cis-expr-dependency-absent-neutral"
DEP_CONJOINT = "cis-conjoint-dependent-supportive"
SILENCING = "cis-silencing-coupled-supportive"


def _fired(*rule_ids):
    return [{"rule_id": rid} for rid in rule_ids]


def test_coherent_cis_driver_via_conjoint():
    v, drv = _verdict(_fired(DOSAGE_COUPLED, AMP, DEP_CONJOINT))
    assert v == "coherent_cis_driver"
    assert drv == DOSAGE_COUPLED


def test_coherent_cis_driver_via_correlation():
    v, drv = _verdict(_fired(DOSAGE_COUPLED, AMP, DEP_CORR))
    assert v == "coherent_cis_driver"
    assert drv == DOSAGE_COUPLED


def test_expressed_cis_coupled_inert():
    """CN (amplification arm) drives expression but dependency absent → the abundance-laundering guard."""
    v, drv = _verdict(_fired(DOSAGE_COUPLED, AMP, DEP_ABSENT))
    assert v == "expressed_cis_coupled_inert"
    assert drv == DEP_ABSENT


def test_amplification_coupled_inert_gene_is_not_labeled_silenced():
    """The MET-class pin (resolver v1.3.0 closed this residual): an AMPLIFICATION-coupled, dependency-inert
    gene that ALSO carries a methylation-silencing token must read expressed_cis_coupled_inert, not
    coherent_epigenetic_silencing — a gene whose expression rises with copy gain is not a silenced gene."""
    v, _ = _verdict(_fired(DOSAGE_COUPLED, AMP, DEP_ABSENT, SILENCING))
    assert v == "expressed_cis_coupled_inert"


def test_deletion_coupled_without_a_dependency_leg_is_coherent_cis_loss_of_function():
    """The DELETED arm with no dependency leg: coherent, but a LoF / SL-hypothesis read (APC/STK11/NF1)."""
    v, drv = _verdict(_fired(DOSAGE_COUPLED, DEL, DEP_ABSENT))
    assert v == "coherent_cis_loss_of_function"
    assert drv == DEL


def test_deletion_coupled_with_a_dependency_leg_is_not_a_cis_driver():
    """A dependency alongside a DELETION-coupled leg-1 cannot be amplification-driven → the trans-regulated
    reading, never coherent_cis_driver."""
    for dep in (DEP_CORR, DEP_CONJOINT):
        v, _ = _verdict(_fired(DOSAGE_COUPLED, DEL, dep))
        assert v == "dependency_without_cis_dosage"


def test_deletion_coupled_silencing_still_reads_epigenetic_silencing():
    """CDKN2A's shape — deletion-coupled AND methylation-silenced, no dependency leg: the silencing rung
    still wins, because the MET-class lift is scoped to the AMPLIFICATION direction only."""
    v, _ = _verdict(_fired(DOSAGE_COUPLED, DEL, DEP_ABSENT, SILENCING))
    assert v == "coherent_epigenetic_silencing"


def test_dependency_without_cis_dosage():
    """Real dependency, but expression is copy-number-independent (trans-regulated)."""
    assert _verdict(_fired(DOSAGE_UNCOUPLED, DEP_CONJOINT)) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)
    assert _verdict(_fired(DOSAGE_UNCOUPLED, DEP_CORR)) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)


def test_cis_uncoupled_no_dependency():
    assert _verdict(_fired(DOSAGE_UNCOUPLED, DEP_ABSENT)) == ("cis_uncoupled_no_dependency", DOSAGE_UNCOUPLED)


def test_coherent_wins_first_match_when_both_leg2_fire():
    assert _verdict(_fired(DOSAGE_COUPLED, AMP, DEP_CONJOINT, DEP_CORR)) == ("coherent_cis_driver", DOSAGE_COUPLED)


def test_insufficient_default_when_nothing_fired():
    assert _verdict(_fired()) == ("insufficient_cis_coherence", None)


def test_insufficient_when_only_one_leg():
    # leg-1 present but leg-2 unmeasured (and vice versa) → cannot assemble the chain → abstain.
    assert _verdict(_fired(DOSAGE_COUPLED, AMP)) == ("insufficient_cis_coherence", None)
    assert _verdict(_fired(DEP_CORR)) == ("insufficient_cis_coherence", None)


def test_dosage_class_without_a_direction_abstains():
    """The v1.3.0 contract: the CLASS token alone says a coupling exists but not which arm carries it, and
    every coherent-dosage rung requires the direction. A reader that emits cis_dosage_class without
    cis_dosage_direction therefore ABSTAINS rather than silently picking the amplification reading."""
    for dep in (DEP_CORR, DEP_CONJOINT, DEP_ABSENT):
        v, _ = _verdict(_fired(DOSAGE_COUPLED, dep))
        assert v == "insufficient_cis_coherence"


def test_direction_alone_cannot_reach_a_verdict():
    """Mirror of the contracts-side pin: a direction token with no dependency leg is not a verdict."""
    assert _verdict(_fired(DOSAGE_COUPLED, AMP)) == ("insufficient_cis_coherence", None)
    assert _verdict(_fired(DOSAGE_COUPLED, DEL)) == ("insufficient_cis_coherence", None)
