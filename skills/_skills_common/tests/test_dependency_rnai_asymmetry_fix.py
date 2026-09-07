"""2026-08-08 review fix: RNAi-alone must NOT drive pan_essential_killer or selective_dependent.

RNAi (DEMETER2) has well-documented seed-effect off-target toxicity → FALSE pan-essential/selective
signals. The dependency resolver formerly let RNAi-ALONE fire the SAFETY killer (rung 2) and a full
selective_dependent verdict (rung 5) via `when_any_fired`, overriding a trusted CRISPR-selective call
and contradicting both the resolver's "CRISPR-beats-RNAi" invariant and the two RNAi rules' own
rationales ("Cross-check vs CRISPR … if both agree"; "NOT dominant on its own … needs CRISPR
cross-check"). This pins the fix: RNAi-alone falls through; RNAi corroborates only WITH CRISPR.

Evaluates the shipped dependency resolver via the shared interpreter (reads target-contracts).
"""
from __future__ import annotations

import os
from pathlib import Path


from _test_support import load_module

SKILLS = Path(__file__).resolve().parents[2]   # the skills/ dir (this test is skills/_skills_common/tests/)
CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT",
                                "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))

_r = load_module(SKILLS / "_skills_common" / "resolver.py", "rnai_fix_rslv")


def _verdict(rule_ids):
    spec = _r.load_resolver("dependency", contracts_repo=CONTRACTS)
    assert spec is not None
    return _r.resolve_verdict([{"rule_id": r} for r in rule_ids], spec)


def test_rnai_alone_pan_essential_does_not_kill():
    """RNAi-alone pan-essential (no CRISPR killer) must NOT fire pan_essential_killer."""
    v, _ = _verdict(["rnai-pan-essential-killer"])
    assert v != "pan_essential_killer", (
        "RNAi-alone pan-essential fired the safety killer — seed-effect false-positive risk; "
        "the killer must require CRISPR corroboration.")


def test_rnai_pan_essential_does_not_override_crispr_selective():
    """The core false-negative-for-pipeline case: CRISPR strongly-selective + RNAi pan-essential
    must resolve to the CRISPR-selective call, NOT be killed by RNAi."""
    v, _ = _verdict(["strongly-selective-supportive", "rnai-pan-essential-killer"])
    assert v == "selective_dependent", (
        f"CRISPR-selective was overridden by RNAi-alone pan-essential (got {v!r}) — "
        "the RNAi-asymmetry regression.")


def test_crispr_pan_essential_still_kills():
    """CRISPR pan-essential (the trusted assay) must still fire the killer."""
    v, _ = _verdict(["pan-essential-killer"])
    assert v == "pan_essential_killer"


def test_rnai_pan_essential_with_crispr_broad_still_kills():
    """Both-agree corroboration preserved: CRISPR broadly-dependent + RNAi pan-essential → killer."""
    v, _ = _verdict(["broadly-dependent-neutral", "rnai-pan-essential-killer"])
    assert v == "pan_essential_killer"


def test_rnai_alone_selective_does_not_mint_selective_dependent():
    """RNAi-alone strongly-selective (no CRISPR dependency signal) must NOT reach selective_dependent."""
    v, _ = _verdict(["rnai-strongly-selective-supportive"])
    assert v != "selective_dependent", (
        "RNAi-alone selective minted a full selective_dependent verdict against its own rule's "
        "'needs CRISPR cross-check' rationale.")


def test_rnai_selective_with_crispr_broad_corroborates():
    """RNAi selective WITH CRISPR broadly-dependent → selective_dependent (orthogonal corroboration)."""
    v, _ = _verdict(["rnai-strongly-selective-supportive", "broadly-dependent-neutral"])
    assert v == "selective_dependent"


def test_crispr_selective_still_drives_directly():
    """CRISPR strongly-selective alone still fires selective_dependent."""
    v, _ = _verdict(["strongly-selective-supportive"])
    assert v == "selective_dependent"
