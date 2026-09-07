"""Hermetic tests for the v1.1.0 sl_partner confidence surface (literature-and-claims arc, item #3).

Covers the VERDICT-INERT enrichment over the curated-SynLethDB synthetic-lethal-partners skill:
  - sl_partner_confidence_caveat  (3 tiers + false-demote guard [combination + paralog] + precedence + None)
  - sl_partner_provenance         (quorum fields; None on the thin path)
  - the SYNTHETIC_LETHAL_PARTNERS lens (registry, verdict mode, verdict_key, single axis)
  - the shared sl_crosswalks reuse + no resolver-golden touch (verdict-INERT)

Pure caveat tests use synthetic headline dicts (no card / no resolver / no LLM). SET literals, not 2-string
tuples (reference-drift guard)."""

from __future__ import annotations
from pathlib import Path

import pytest

from _test_support import load_run_py
from _skills_common.narrator_lenses import SYNTHETIC_LETHAL_PARTNERS, LENSES

SKILL_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def M():
    return load_run_py(SKILL_DIR, "slp_run_caveats")


def _hl(
    verdict="has_experimental_sl_partner",
    cls="has_experimental_sl_partner",
    count=3,
    n_exp=3,
    has_exp=True,
    tier="experimental",
):
    return {
        "sl_partner_verdict": verdict,
        "sl_partner_class": cls,
        "sl_partner_count": count,
        "n_experimental_partners": n_exp,
        "has_experimental_partner": has_exp,
        "best_evidence_tier": tier,
    }


# ── MILDER — validated_established_synthetic_lethal guard (combination + paralog crosswalks) ─────────
@pytest.mark.parametrize(
    "target,indication", [("BRCA1", "BRCA"), ("BRCA2", "OV"), ("WRN", "COADREAD"), ("KRAS", "PAAD")]
)
def test_validated_combination_guard(M, target, indication):
    c = M._sl_partner_confidence_caveat(_hl(), target=target, indication=indication)
    assert c["reason"] == "validated_established_synthetic_lethal" and c["false_demote_guarded"] is True


@pytest.mark.parametrize("target", ["SMARCA4", "ARID1A", "STAG2"])
def test_validated_paralog_guard(M, target):
    # indication-independent paralog-SL guard (via the shared crosswalk).
    c = M._sl_partner_confidence_caveat(_hl(), target=target, indication="LUAD")
    assert c["reason"] == "validated_established_synthetic_lethal"
    assert c.get("paralog_partner") is not None


def test_guard_wins_over_computational(M):
    # a canonical pair reported computational-only still wins the milder guard (precedence).
    c = M._sl_partner_confidence_caveat(
        _hl(
            verdict="has_computational_sl_partner",
            cls="has_computational_sl_partner",
            has_exp=False,
            n_exp=0,
            tier="computational",
        ),
        target="BRCA1",
        indication="BRCA",
    )
    assert c["reason"] == "validated_established_synthetic_lethal"


# ── SHARP — computational_only_sl_edge ──────────────────────────────────────────────────────────────
def test_computational_only_fires_sharp(M):
    c = M._sl_partner_confidence_caveat(
        _hl(
            verdict="has_computational_sl_partner",
            cls="has_computational_sl_partner",
            has_exp=False,
            n_exp=0,
            tier="computational",
        ),
        target="FOO",
        indication="BAR",
    )
    assert c["reason"] == "computational_only_sl_edge" and c["tier"] == "sharp"


# ── SHARP — curated_sl_edge_context_unconfirmed default ─────────────────────────────────────────────
def test_curated_context_default(M):
    c = M._sl_partner_confidence_caveat(_hl(), target="FOO", indication="BAR")
    assert c["reason"] == "curated_sl_edge_context_unconfirmed" and c["tier"] == "sharp"


# ── None path (no curated partner) ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("verdict", ["no_curated_sl_partner", "insufficient", None])
def test_no_substrate_none(M, verdict):
    assert (
        M._sl_partner_confidence_caveat(
            {
                "sl_partner_verdict": verdict,
                "sl_partner_class": verdict,
                "n_experimental_partners": 0,
                "sl_partner_count": 0,
            },
            target="BRCA1",
            indication="BRCA",
        )
        is None
    )


# ── provenance ──────────────────────────────────────────────────────────────────────────────────────
def test_provenance_fields(M):
    p = M._sl_partner_provenance(_hl(), target="BRCA1", indication="BRCA")
    assert p["validated_combination_flag"] is True
    assert p["best_evidence_tier"] == "experimental"
    assert "curated" in p["provenance_note"].lower()


def test_provenance_none_on_thin(M):
    assert (
        M._sl_partner_provenance({"sl_partner_verdict": "no_curated_sl_partner"}, target="FOO", indication="BAR")
        is None
    )


# ── lens contract ───────────────────────────────────────────────────────────────────────────────────
def test_lens_registered_verdict_mode():
    assert LENSES.get("synthetic-lethal-partners") is SYNTHETIC_LETHAL_PARTNERS
    assert SYNTHETIC_LETHAL_PARTNERS.mode == "verdict"
    assert SYNTHETIC_LETHAL_PARTNERS.verdict_key == "sl_partner_verdict"
    assert set(SYNTHETIC_LETHAL_PARTNERS.axis_labels) == {"SL"}


def test_literature_fn_and_synthesize_wired(M):
    src = (SKILL_DIR / "scripts" / "run.py").read_text()
    assert "synthesize_fn=make_synthesize_fn" in src
    assert "literature_fn=make_literature_fn" in src


def test_reference_containers_are_sets_or_dicts(M):
    from _skills_common import sl_crosswalks as X

    assert isinstance(X.VALIDATED_COMBINATION_PRECEDENT, dict)
    assert isinstance(X.VALIDATED_PARALOG_SL, dict)
    assert isinstance(M._SL_PARTNER_PRESENT, set)
