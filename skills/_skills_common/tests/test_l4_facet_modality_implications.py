"""Guards for the L4 modality_implications facet builder (epic #1986, C0e #2008).

modality_implications = PER MODALITY (adc / tce / small_molecule) {opportunity, liability,
critical_unknown} triples — never a scalar per-modality fit score. Built over the assessed L3d domain
stories, filtered by a fixed modality-relevance map, plus the SK#1844 ADC/TCE decision frames evaluated
read-only over the decision's own headline. These tests pin the properties #2008 requires:

  * FLAGSHIP END-TO-END (EPCAM) — real per-modality content resolves from the tumor_presence L3d story,
    every cell traceable, riding under assemble_target_synthesis alongside the C0a floor.
  * ABSENCE PATH (KRAS) — no L3d domain anywhere -> the facet (and the whole assembly) is None.
  * DETERMINISM / BYTE-STABILITY.
  * CLAIM-ID TRACEABILITY TEETH.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]  # skills/

from _skills_common.l4_synthesis import (  # noqa: E402
    assemble_target_synthesis,
    facet_modality_implications,
    resolve_ref,
    unresolved_refs,
)
from _skills_common.l4_synthesis import schema as S  # noqa: E402
from _skills_common.l4_synthesis.assembler import L4TraceabilityError  # noqa: E402
from _skills_common.l4_synthesis.context import read_context  # noqa: E402

EPCAM_GOLDEN = SKILLS / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"
KRAS_DECISION = SKILLS / "genomic-alteration-profile" / "tests" / "fixtures" / "kras_coadread_decision.json"


def _epcam():
    return json.loads(EPCAM_GOLDEN.read_text())


def _kras():
    return json.loads(KRAS_DECISION.read_text())


def test_modality_implications_is_built():
    assert facet_modality_implications.BUILT is True


# ── flagship end-to-end: EPCAM ──────────────────────────────────────────────────────────────────
def test_modality_implications_emits_real_content_for_epcam_flagship():
    ctx = read_context(_epcam())
    fr = facet_modality_implications.build(ctx)
    assert fr is not None
    assert fr["facet"] == S.FACET_MODALITY_IMPLICATIONS
    assert fr["layer"] == S.L4_LAYER
    implications = fr["modality_implications"]
    assert implications  # at least one modality resolved something

    # ADC/TCE both depend on tumor_presence (the one assessed domain) -> both surface real opportunities.
    for modality in (facet_modality_implications.MODALITY_ADC, facet_modality_implications.MODALITY_TCE):
        triple = implications[modality]
        assert set(triple) == {"opportunity", "liability", "critical_unknown"}
        assert triple["opportunity"], f"{modality} should surface a tumor_presence opportunity"
        assert triple["critical_unknown"], f"{modality} should flag its unassessed relevant domains"
        for cell in ("opportunity", "liability", "critical_unknown"):
            for item in triple[cell]:
                for ref in item["claim_ids"]:
                    assert resolve_ref(ctx, ref)

    # small_molecule depends on none of the assessed domains -> critical_unknown only, no opportunity.
    sm = implications[facet_modality_implications.MODALITY_SMALL_MOLECULE]
    assert sm["critical_unknown"]
    assert sm["opportunity"] == []
    for item in sm["critical_unknown"]:
        assert item["status"] == "NOT_ASSESSED"
        for ref in item["claim_ids"]:
            assert resolve_ref(ctx, ref)


def test_modality_implications_rides_the_assembled_synthesis_alongside_the_thesis_floor():
    syn = assemble_target_synthesis(_epcam())
    assert syn is not None
    assert S.FACET_THESIS_ARCHETYPE in syn["facets"]
    assert S.FACET_MODALITY_IMPLICATIONS in syn["facets"]
    ctx = read_context(_epcam())
    assert unresolved_refs(ctx, syn) == []


def test_adc_and_tce_liability_surfaces_the_epcam_abundance_caveat():
    """The EPCAM tumor_presence chapter carries an abundance caveat (MS-protein ranks below RNA) — that
    is a liability for the surface-antigen (ADC/TCE) modalities that need reliable surface abundance."""
    ctx = read_context(_epcam())
    fr = facet_modality_implications.build(ctx)
    for modality in (facet_modality_implications.MODALITY_ADC, facet_modality_implications.MODALITY_TCE):
        liabilities = fr["modality_implications"][modality]["liability"]
        aspects = {li["aspect"] for li in liabilities}
        assert "abundance" in aspects


# ── absence path: KRAS (no L3d domain anywhere) ─────────────────────────────────────────────────
def test_modality_implications_is_none_when_no_l3d_domain_resolves():
    ctx = read_context(_kras())
    assert ctx.l3d_domains == {}
    assert facet_modality_implications.build(ctx) is None


def test_kras_flagship_yields_no_synthesis_at_all():
    assert assemble_target_synthesis(_kras()) is None


# ── determinism / byte-stability ─────────────────────────────────────────────────────────────────
def test_modality_implications_is_deterministic():
    ctx = read_context(_epcam())
    a = facet_modality_implications.build(ctx)
    b = facet_modality_implications.build(ctx)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_synthesis_with_modality_implications_stays_byte_stable_to_the_decision():
    d = _epcam()
    before = json.dumps(d, sort_keys=True)
    assemble_target_synthesis(d)
    assert json.dumps(d, sort_keys=True) == before


# ── claim-ID traceability teeth ──────────────────────────────────────────────────────────────────
def test_broken_claim_id_on_a_modality_statement_red_fails_the_assemble(monkeypatch):
    real_build = facet_modality_implications.build

    def poisoned(ctx):
        fr = real_build(ctx)
        assert fr is not None
        fr = copy.deepcopy(fr)
        fr["statements"].append(
            S.statement(
                "fabricated modality statement",
                [S.claim_ref("NOT_A_REAL_CLAIM_ID", vector="pooled_claim_vector")],
            )
        )
        return fr

    monkeypatch.setattr(facet_modality_implications, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())


def test_empty_claim_ids_on_a_modality_statement_red_fails_the_assemble(monkeypatch):
    real_build = facet_modality_implications.build

    def poisoned(ctx):
        fr = copy.deepcopy(real_build(ctx))
        fr["statements"].append(S.statement("un-cited modality statement", []))
        return fr

    monkeypatch.setattr(facet_modality_implications, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())
